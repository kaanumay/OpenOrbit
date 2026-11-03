"""Concrete bots: the bots' ships on the player's map (BotShip, inside world.World.npcs) and their tactical behavior.

A bot sits in the alien table but looks like a player to the client (ShipCreateCommand npc=False, company, rank, clan tag, drones):
vision, selection, the player's laser/rocket/abilities, and shared-map sharing work on their own through the world's alien path. Where it
branches off (world.py hooks):
  ship_create   -> appearance      player look
  think         -> think           tactics: go to the portal, flee, retaliate, PvP, hunt aliens, rest
  think (NPC)   -> npc_to_bot      an alien the bot hit turns on it and fires
  laser_start   -> attack_error    the player's attack rules (DMZ, own company on the starting map)
  hit_npc       -> was_hit         the same rules + the bot remembers the attacker
  kill          -> was_killed      PvP reward (player_combat.on_kill), the bot dies, returns to base
  hero_death    -> player_died     the bot's victory (honor, memory)
  step (leader) -> tick            sync with the manager's bots on this map (once a second)
  stop          -> detach          ships are removed, bots return to the abstract simulation

Tactical thinking is intermittent with a human reaction time (the personality's reaction time); it fires once every 1.1 s. Combat visuals go only
to clients that know both ends (not sent while an out-of-sight bot is killing an alien).
"""
import math, random, time

import world as WD
import map_links as H
import map_layout as ML
from legacy_protocol import legacy
from . import catalog as K
from . import abstract_sim as S
from . import playstyle as PL
from . import appearance as GR
from . import society as T
from . import manager as MGR
from .goals.pvp import order_grudge

CARRIER = next(iter(WD.CFG['types']))       # a type that exists for NPC.__init__ (later replaced with the bot's values)
LASER_RANGE = WD.COMBAT['laser_range']
COMBAT_SEC = 8.0                                 # regenerates this long after the last damage
REGEN_RATE = 0.02                               # outside combat, the share of max HP+shield per second
JUMP_SEC = H.JUMP_DELAY_SEC
TAKEOFF_SEC = 4.0                  # typical wait after arriving on a map before setting off (BotShip.takeoff's mode)
WANDER = 3000                      # a grinding bot that has flown farther than this since it arrived can be anywhere on the map
COMBAT_INTERVAL = WD.COMBAT['laser_interval_sec']


class BotShip(WD.NPC):
    def __init__(self, bot, x, y, now=None):
        WD.NPC.__init__(self, bot.uid, CARRIER, x, y)
        self.bot = bot
        self.tip = 'bot'
        self.summoned = True                    # does not respawn like an alien (the manager spawns the bot)
        self.target = None                       # the one it fires at (id)
        self.fire = False
        self.attacker = {}                      # id -> time of the last hit
        self.last_damage = 0.0
        self.portal_time = 0.0
        self.movement = None                     # the last target point sent
        self.intent_time = 0.0                      # the last time of a PvP-start decision
        self.spawn = now or time.time()
        self.next_think = self.spawn + random.uniform(0.3, 1.5)
        self.takeoff = random.triangular(1.5, 18, 4)     # does not set off right after spawning: so everyone does not leave in a single file at once
        self.route = None                        # (target, [waypoints]): a curved route on a long trip (_route)
        self.approach_points = {}                         # portal -> docking point (around the portal, specific to the bot)
        self.next_shot = 0.0
        d = bot.value()
        self.d = {}
        self.refresh()
        self.hp, self.shield = d['hp'], d['shield']

    def refresh(self):
        """Equipment changed: look, values, drones."""
        b = self.bot
        d = b.value()
        e = b.k['gear']
        self.model = e['ship']
        self.d = dict(name=b.name, hp=int(d['hp']), shield=int(d['shield']), damage=0, speed=int(d['speed']), aggressive=False,
                      reward=dict(ep=0, honor=0, credits=0, uridium=0), cargo={}, npc_id=0,
                      spread=3 if d['laser'] >= 12 else 2 if d['laser'] >= 6 else 1, bot=True)
        self.behavior = {}
        self.hp, self.shield = min(self.hp, d['hp']), min(self.shield, d['shield'])
        # drones only from extra_look (appearance.messages: formation, drone level, designs); a second string here with formation 0
        # went after it in show() and overwrote the formation (player report 2026-11-01: no bot uses a formation)
        self.images = {}

    def speed(self):
        return self.d['speed']


# ------------------------------------------------------------------------------------------------------------ look
def appearance(w, n):
    b = n.bot
    x, y = n.mover.pos(time.time())
    T.profile(b)
    pl = b.profile.d['pilot']
    return ('ShipCreateCommand', dict(
        userId=n.id, typeId=GR.tip(b), expansionStage=n.d['spread'], userName=b.name, x=int(x), y=int(y),
        clanTag='CM' if b.__dict__.get('moderator') else pl.get('clanTag', ''),        # chat moderator (bot/moderation.py)
        factionId=b.company, clanId=int(pl.get('clanId') or 0), dailyRank=pl.get('dailyRank', 1), warnBox=False,
        clanDiplomacy=WD.mod('ClanRelationModule', type=relation(w, b)), galaxyGatesDone=GR.rings(b), useSystemFont=False, npc=False,
        cloaked=False, motherShipId=0, positionIndex=0, designSet='', modifier=[],
        minimapStrategyModule=WD.mod('MinimapStrategyModule', minimapStrategy=0), specialNpcType=''))


def extra_look(n):
    return GR.messages(n)


def relation(w, b):
    """Relation between clans (ClanRelationModule.type: 1 alliance, 2 non-aggression, 3 war) or 0."""
    try:
        import clan as KL
        return KL.relation(w.p, T.profile(b))
    except Exception:
        return 0


# ------------------------------------------------------------------------------------------------------------ sync
def tick(w, now):
    """Once a second: the manager's online, alive bots on this map that have not left their route come into existence as ships; those that left are removed."""
    y = MGR.ACTIVE
    if y is None or now < getattr(w, '_bot_t', 0):
        return
    w._bot_t = now + 1.0
    try:
        m = int(w.map_id)
    except ValueError:
        return
    if is_gate_world(w):
        return gate_tick(w, now, y)
    with y.lock:
        wanted = {b.uid: b for b in y.on_map.get(m, ()) if b.online and b.dead_until <= now
                   and now - b.__dict__.get('in_gate', 0) > 5}           # a bot at the gate with the player is not visible on another map
    var = {uid: n for uid, n in w.npcs.items() if n.bot is not None}
    msgs = []
    for uid, n in var.items():
        if uid not in wanted:
            msgs += remove(w, n)
    limit = y.setting('max_concrete', 40) or 9999
    count = len(var) - sum(1 for u in var if u not in wanted)
    if len(wanted) > limit:                             # if the limit is full: bots near you, with history with you, in your group first
        hx, hy = w.hero_pos(now)
        name = str(w.p.d['pilot'].get('userName', '')).lower()

        def priority(b):
            x, yy = b.k.get('x') or 0, b.k.get('y') or 0
            is_acquaintance = name in (b.k.get('memory') or {})
            return (not w.is_group_member(b.uid), not is_acquaintance, math.hypot(x - hx, yy - hy))
        wanted = dict(sorted(wanted.items(), key=lambda kv: priority(kv[1])))
    for uid, b in wanted.items():
        if b.body is not None and (not b.body.alive or w.npcs.get(b.body.id) is not b.body):
            b.body = None                                # a ship deleted from outside (debugging, a crashed world): so the bot does not freeze
        if uid in var or count >= limit or b.body is not None:
            continue
        x, yy, since = spawn_point(w, b, now)
        n = BotShip(b, x, yy, since)                     # its takeoff wait counts from its arrival, not from the player's
        resume(n, now)
        if b.__dict__.pop('in_place_repair', None):       # repair on the spot: 10% of HP, no shield, 10 s protection (like the player's)
            n.hp, n.shield = max(1, int(n.hp * K.ITEMS['death_screen']['in_place_hp_ratio'])), 0
            n.immune_until = now + K.ITEMS['death_screen']['in_place_protection_sec']
        w.npcs[n.id] = n
        b.body = n
        b.k['x'], b.k['y'] = x, yy
        count += 1
    if msgs:
        w.send(msgs)


def is_gate_world(w):
    """A gate or sample map (Galaxy Gate, Hades, LoW, QZ, event gates): not an ordinary map."""
    try:
        m = int(w.map_id)
    except ValueError:
        return True
    return m not in K.MAPS or getattr(w, 'gate', None) is not None and bool(getattr(w.gate, 'key', None)) \
        or getattr(w, 'low', None) is not None


def gate_tick(w, now, y):
    """Gate filler (player request 2026-10-31): the bots in the hero's group enter the gate with them (spawning next to the gate), follow the group's
    target (Group) and fire at aliens; a bot that is in its own gate or mode, dead or offline does not come. Permission
    'gate_filler'; if off, there are no bots in the gate (as before)."""
    import group as GR
    wanted = {}
    if y.permission('gate_filler') and not w.hero_dead:
        g = GR.group_of(w.hid)
        with y.lock:
            for b in y.bots:
                if (g is not None and b.uid in g.members and b.online and b.dead_until <= now
                        and (b.target is None or b.target.name not in ('gate', 'mod', 'duel'))):
                    wanted[b.uid] = b
    msgs = []
    for uid, n in [(u, n) for u, n in w.npcs.items() if n.bot is not None]:
        if uid not in wanted:
            msgs += remove(w, n)
    hx, hy = w.hero_pos(now)
    for uid, b in wanted.items():
        b.in_gate = now
        if b.target is None or b.target.name != 'group':
            from . import brain as BR
            BR.force(b, 'group', pay=2.0, duration=3600, now=now)
        if b.body is not None and (not b.body.alive or w.npcs.get(b.body.id) is not b.body):
            b.body = None
        if uid in w.npcs or b.body is not None:
            continue
        a = random.uniform(0, 2 * math.pi)
        x, yy = int(hx + math.cos(a) * random.uniform(150, 400)), int(hy + math.sin(a) * random.uniform(150, 400))
        x, yy = max(300, min(w.map_w - 300, x)), max(300, min(w.map_h - 300, yy))
        n = BotShip(b, x, yy, now)
        resume(n, now)
        w.npcs[n.id] = n
        b.body = n
        b.event('entered_gate', gate=str(getattr(getattr(w, 'gate', None), 'key', '') or w.map_id))
    if msgs:
        w.send(msgs)


def spawn_point(w, b, now=None):
    """Where the bot's ship appears -> (x, y, since); since: when it came onto the map (its takeoff wait counts from there).
    A known position (it was a ship on this map, portal repair) stays. Otherwise it came onto the map while abstract (portal jump, death at
    the station, login) and is where it would be after the time since: at the arrival portal or the station just after, later on its way
    to the next portal of its route or, when grinding, anywhere on the map. Before, it was always at the station or portal as if it had just
    arrived (player reports: 2026-10-31 bots came out of the portal with the player; 2026-11-03 on 2-1 the 20-30 bots that had arrived
    while the player was away waited at the station and all flew to the bottom-left portal at once when the player came)."""
    now = now or time.time()
    arrival, b.arrival = getattr(b, 'arrival', None), None
    x, y = b.k.get('x') or 0, b.k.get('y') or 0
    if 300 < x < w.map_w - 300 and 300 < y < w.map_h - 300:
        return int(x), int(y), now
    src, since = arrival or (None, now)
    s = w.station
    if src is not None:
        (ox, oy), scatter = H.arrival(src, int(w.map_id), b.company), (80, 280)
    elif arrival is not None and s and s.get('type') == b.company:
        (ox, oy), scatter = (s['posX'], s['posY']), (250, 1300)
    else:                                                # unknown since when (server start: in the middle of its session)
        x, y = w.random_spot()
        return x, y, since
    flown = max(0.0, now - since - TAKEOFF_SEC) * b.value()['speed'] * 0.8      # routes curve, it lingers at boxes
    a, r = random.uniform(0, 2 * math.pi), random.uniform(*scatter)
    g = next((g for g in H.gates(w.map_id, b.company) if g['target'] == b.en_route[0]), None) if b.en_route else None
    if g is not None:                                    # on its way to the next portal (it jumps when its abstract time comes)
        f = min(0.85, flown / max(1.0, math.hypot(g['x'] - ox, g['y'] - oy)))
        ox, oy = ox + (g['x'] - ox) * f, oy + (g['y'] - oy) * f
    elif flown > WANDER:
        x, y = w.random_spot()
        return x, y, since
    else:
        r += flown
    return (int(max(400, min(w.map_w - 400, ox + math.cos(a) * r))),
            int(max(400, min(w.map_h - 400, oy + math.sin(a) * r))), since)


CARRY = ('last_damage', 'immune_until', 'leech_end', 'rocket_ready', 'salvo_ready', 'mine_ready')


def resume(n, now):
    """A ship spawning again (after a jump, a gate, the player's map change): HP, shield and cooldowns carry over from the last ship
    (player report 2026-11-02: jumping through a portal refilled the bot's HP), regenerated for the time it was away as in think."""
    c = n.bot.__dict__.pop('carry', None)
    if c is None:
        return
    from . import extras as EX
    d = n.bot.value()
    n.__dict__.update(c['state'])
    idle = max(0.0, now - max(c['t'], n.last_damage + COMBAT_SEC))
    rep = EX.repair_sec(n.bot)
    n.hp = min(d['hp'], c['hp'] + d['hp'] * max(REGEN_RATE, 1.0 / rep if rep else 0) * idle)
    n.shield = min(d['shield'], c['shield'] + d['shield'] * REGEN_RATE * 2 * idle)


def remove(w, n):
    """The ship leaves the map (exit, jump, after death): position to the save, the bot to the abstract simulation."""
    n.alive = False
    b = n.bot
    x, y = n.mover.pos(time.time())
    b.k['x'], b.k['y'] = int(x), int(y)
    b.carry = dict(t=time.time(), hp=n.hp, shield=n.shield,
                   state={k: v for k, v in n.__dict__.items() if k in CARRY or k.startswith('cd_')})     # resume; cleared on death
    if b.body is n:
        b.body = None
    b.last_abstract = time.time()
    g = next((g for g in H.gates(w.map_id, b.company) if g['target'] == b.en_route[0]), None) if b.en_route else None
    if g is not None:              # left mid-route (the player left the map): the abstract jump waits for the rest of the flight to the portal
        b.en_route_time = time.time() + math.hypot(g['x'] - x, g['y'] - y) / max(1.0, b.value()['speed'])
    return w.remove_npc(n) + ([('AttackAbortLaserCommand', {'uid': n.id})] if n.fire else [])


def detach(w):
    """The world is stopping: if no other player remains on the shared map the ships are removed (before the map state is stored)."""
    if w.shared is not None and any(o is not w and o.running for o in w.shared.members):
        return
    with w.lock:
        for n in [n for n in w.npcs.values() if n.bot is not None]:
            remove(w, n)


# ------------------------------------------------------------------------------------------------------------ helpers
def _position(w, uid, now):
    n = w.npcs.get(uid)
    if n is not None:
        return n.mover.pos(now) if n.alive else None
    o = _player(w, uid)
    return o.hero_pos(now) if o is not None else None


def _player(w, uid):
    """The world of the hero with id uid (this world or the other player on the shared map) or None."""
    if uid == w.hid:
        return w
    if w.shared is not None:
        return next((o for o in w.shared.members if o.hid == uid and o.running), None)
    return None


def _broadcast(w, msgs, *uids):
    """Combat visual: to this world's client if it knows both ends; to the other players on the shared map (mirror filters itself)."""
    if not msgs:
        return
    if all(w.knows(u) for u in uids):
        w.send(msgs)
    elif w.shared is not None:
        w.shared.mirror(w, msgs)


def _go_to(w, n, x, y, now, threshold=80):
    x = max(200, min(w.map_w - 200, x))
    y = max(200, min(w.map_h - 200, y))
    h = n.movement
    if h is not None and math.hypot(h[0] - x, h[1] - y) < threshold and n.mover.t1 > now:
        return
    n.movement = (x, y)
    ms = n.mover.go(x, y, n.speed(), now)
    w.send([('MoveCommand', dict(userId=n.id, x=int(x), y=int(y), timeToTarget=ms))])


def _waypoints(w, n, sx, sy, x, y):
    """Waypoints of a long route: on a slight arc (sine) perpendicular to the route; direction and width seeded by the bot and the trip (each
    bot's route is different, unchanged within one trip). A short route is direct."""
    d = math.hypot(x - sx, y - sy)
    k = 0 if d < 1500 else 1 if d < 3500 else 2 if d < 7000 else 3
    if not k:
        return []
    r = random.Random('%s|%d|%d|%d' % (n.bot.name, int(n.spawn), int(x) // 50, int(y) // 50))
    ux, uy = (x - sx) / d, (y - sy) / d
    width = r.choice((-1, 1)) * d * r.uniform(0.05, 0.17)
    out = []
    for i in range(1, k + 1):
        t = i / (k + 1.0) + r.uniform(-0.04, 0.04)
        s = width * math.sin(math.pi * t) + d * r.uniform(-0.025, 0.025)
        out.append((max(250, min(w.map_w - 250, sx + ux * d * t - uy * s)), max(250, min(w.map_h - 250, sy + uy * d * t + ux * s))))
    return out


def _route(w, n, x, y, now, threshold=150):
    """A long trip (portal, station, patrol): a slight arc with waypoints instead of a straight line; it turns to the next one without reaching the waypoint
    (does not stop and restart). Player report 2026-10-31: on entering the map the bots flew to the portal in a single file, dead straight and on the same path."""
    nx, ny = n.mover.pos(now)
    r = n.route
    if r is None or math.hypot(r[0][0] - x, r[0][1] - y) > threshold:
        r = n.route = ((x, y), _waypoints(w, n, nx, ny, x, y))
    mid = r[1]
    early = max(250, n.speed() * 1.6)                     # the distance covered in one thinking interval: so it does not wait at the corner
    remaining = math.hypot(x - nx, y - ny)
    while mid and (math.hypot(mid[0][0] - nx, mid[0][1] - ny) < early
                   or math.hypot(x - mid[0][0], y - mid[0][1]) > remaining):     # left behind (a fight intervened): does not turn back
        mid.pop(0)
    hx, hy = mid[0] if mid else (x, y)
    _go_to(w, n, hx, hy, now, threshold=60)


def _stop(w, n, now):
    if n.mover.t1 > now:
        x, y = n.mover.pos(now)
        _go_to(w, n, x, y, now, threshold=0)


def hero_power(o):
    """The player's rough power (for the bot's decision): lasers and the ship's HP/shield."""
    try:
        lasers = sum(K.ITEMS['lasers'].get(l, {}).get('damage', 0) for l in o.lasers())
        g = o.p.d['ship']
        multiplier = K.ITEMS['laser_ammo'].get(o.p.d.get('selected', {}).get('laser'), {}).get('multiplier', 1)
        dps = lasers * min(multiplier, 3) * 0.88 * 0.8 / COMBAT_INTERVAL
        ehp = g.get('hitMax', 0) + g.get('shieldMax', 0) * 2.5 * 0.9
        return K.power_score(dps, ehp)
    except Exception:
        return 50.0


def _in_peace(w, x, y, bot=None):
    """A safe zone at this spot for the pilot (bot None) or for that bot ship: zones protect a ship only on its own company's maps."""
    return w.in_pvp_peace(x, y, None if bot is None else bot.company)


# ------------------------------------------------------------------------------------------------------------ rules
def attack_error(w, n, now=None):
    """The player's attack on this bot -> [] allowed or the client's rejection messages (the rules of player_combat.attack_error)."""
    now = now or time.time()
    b = n.bot
    if w.hero_dead or w.jumping or not n.alive:
        return [legacy('0|A|STM|msg_grp_attack_impossible')]
    hx, hy = w.hero_pos(now)
    nx, ny = n.mover.pos(now)
    if _in_peace(w, hx, hy) or _in_peace(w, nx, ny, b):
        # safe zone: "Attack-Protected-Zone" (the client's peacearea; it used to say "Group members cannot be attacked", player
        # report 2026-10-30)
        return [legacy('0|A|STM|peacearea')]
    pl = w.p.d['pilot']
    clan = int(pl.get('clanId') or 0)
    if clan and clan == int(T.profile(b).d['pilot'].get('clanId') or 0):
        return [legacy('0|A|STM|friendlyfire_disabled')]
    if relation(w, b) in (1, 2):
        return [legacy('0|A|STM|friendlyfire_disabled')]
    if int(pl.get('factionId') or 0) == b.company and relation(w, b) != 3 and not WD.SET.get('company_pvp'):
        return [legacy('0|A|STM|friendlyfire_disabled')]       # panel: attacking one's own company is off (except a clan at war)
    if int(pl.get('factionId') or 0) == b.company and H.company(w.map_id) == b.company and H.name(w.map_id).split('-')[-1] in ('1', '2'):
        return [legacy('0|A|STM|no_attack_on_start_maps')]
    return []


def was_hit(w, n, attacker=None):
    """hit_npc: is the hit valid; if so the bot remembers the attacker (the hero or their P.E.T.)."""
    now = time.time()
    from . import active_items as AC
    # not hit during Insta-Shield; while cloaked only one who has selected it hits (wiki: "Cloaked ships can still be attacked (if
    # targeted)"; player report 2026-10-31: a cloaked bot could not be attacked)
    if attack_error(w, n, now) or now < n.__dict__.get('immune_until', 0) or (n.__dict__.get('hidden') and w.target != n.id):
        return False
    n.attacker[w.hid] = now
    n.last_damage = now
    if n.next_think > now + 0.3:
        n.next_think = now + min(0.6, n.bot.k['personality']['reaction_sec'])
    return True


# ------------------------------------------------------------------------------------------------------------ death
def was_killed(w, n):
    """The player (or their P.E.T., mine, ability) destroyed the bot -> messages (in place of kill)."""
    import player_combat as OS
    b = n.bot
    x, y = n.mover.pos(time.time())
    msgs = remove(w, n)
    if any(m[0] == 'ShipRemoveCommand' for m in msgs):
        msgs.insert(0, ('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0)))
    p = T.profile(b)
    p.d['ship']['hitPoints'] = 0

    class Victim:
        pass
    victim = Victim()
    victim.p = p
    try:
        msgs += OS.on_kill(w, victim)
    except Exception as e:
        w.log('   could not give the bot reward: %s' % e)
    name = w.p.d['pilot'].get('userName', '')
    if b.target is not None and b.target.name == 'duel':
        b.plan['finished'] = True                           # lost the duel
        b.k['intent'] = None
    y_ = MGR.ACTIVE
    if y_ is not None:
        with y_.lock:
            S.death(b, y_, reason='player', killer=name, now=time.time())
    w.log('   bot %s destroyed (%s)' % (b.name, H.name(w.map_id)))
    return msgs


def player_died(w, n):
    """The bot destroyed the player: honor and memory (the player's death screen is in the world)."""
    b = n.bot
    name = w.p.d['pilot'].get('userName', '')
    kill_rewards = K.ITEMS['player_kill']
    y = MGR.ACTIVE
    speed = y.speed(b) if y is not None else 1.0
    b.reward(None, speed, ep=kill_rewards['ep_points'], honor=kill_rewards['honor_points'])
    b.ist('player')
    b.ist('player_points', T.ship_rank_points(w.p.ship()['lootId']))
    b.memory.event(name, 'i_killed')
    b.mood.it(morale=0.12, confidence=0.1, anger=-0.3)
    b.event('i_killed_player', name=name)
    if b.target is not None and b.target.name == 'duel':
        b.plan['finished'] = True                           # won the duel
        b.k['intent'] = None
    n.target = None


def bot_damage(w, t, dmg, source_id, now, killer_bot=None, npc=None):
    """The bot ship took damage (from an alien or another bot): the shield absorbs, if HP runs out the bot dies."""
    from . import active_items as AC
    if not t.alive or AC.is_protected(t, now):
        return
    absorb = t.bot.value()['absorb']
    to_shield = min(int(t.shield), int(dmg * absorb))
    t.shield -= to_shield
    t.hp = max(0, t.hp - (dmg - to_shield))
    t.last_damage = now
    t.attacker[source_id] = now
    msgs = [('AttackHitCommand', dict(attackType=WD.attack_type(1), attackerId=source_id, victimId=t.id, victimHitpoints=int(t.hp),
                                      victimShield=int(t.shield), victimNanoHull=0, damage=int(dmg), skilled=False, strike=False,
                                      cannonType=0))]
    if w.target == t.id:
        msgs.append(w.selection(t))
    _broadcast(w, msgs, source_id, t.id)
    if t.hp <= 0:
        bot_die(w, t, killer_bot, npc)


def bot_die(w, t, killer_bot=None, npc=None):
    b = t.bot
    msgs = remove(w, t)
    if any(m[0] == 'ShipRemoveCommand' for m in msgs):
        msgs.insert(0, ('ShipDestroyedCommand', dict(destroyedUserId=t.id, explosionTypeId=0)))
    w.send(msgs)
    y = MGR.ACTIVE
    if y is None:
        return
    with y.lock:
        if killer_bot is not None:
            S.pvp_reward(killer_bot, b, y, time.time())
        S.death(b, y, reason='player' if killer_bot else 'npc', killer=killer_bot.name if killer_bot else None, now=time.time())


def kill_npc(w, m, n, now):
    """The bot killed an alien: the alien is removed and respawns (kill's rewardless form), the reward goes to the bot, the cargo box next to it (the bot's; others
    see it as blue). If the alien is tagged by someone else (the player or another bot) the world's kill gives the reward to them."""
    who = WD.tag_owner(m, now)
    if (who is not None and tuple(who) != ('b', n.id)) or getattr(m, 'damage_split', None):     # damage_split: a group alien, the world splits
        w.send(w.kill(m))
        n.target = None
        return
    m.alive = False
    w.npcs.pop(m.id, None)
    x, y = m.mover.pos(now)
    msgs = w.pet.npc_gone(m.id) if w.pet else []
    if m.id in w.visible:
        w.visible.discard(m.id)
        msgs += [('ShipDestroyedCommand', dict(destroyedUserId=m.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': m.id})]
    if w.target == m.id:
        w.target, w.attacking = None, False
        msgs.append(('ShipDeselectionCommand', {}))
    if not m.gate and not m.summoned and not m.d.get('uncounted'):
        w.schedule(random.uniform(*w.respawn_range(m)), 'npc', m.tip)
    try:
        msgs += w.alien.on_kill(m, x, y)
    except Exception:
        pass
    w.send(msgs)
    # group (group.py): if the bot is in a group with the hero, the reward is shared with the hero on the map and the bots in the group, and counts for the hero's quest
    pay = [w] if w.is_group_member(n.id) and w.running and not w.hero_dead and not w.jumping else []
    bots = [n.bot] + ([o for o in group_bots(w) if o is not n.bot] if pay else [])
    for b in bots:
        npc_reward(b, m, len(pay) + len(bots))
    for h in pay:
        h.npc_reward(m, x, y, len(pay) + len(bots), own=False)
    drop_cargo(w, m, n.id, x, y)
    if is_boss(m):
        n.bot.event('i_killed_boss', name=m.d.get('name', ''))
        witness(w, 'boss', x, y, exclude=n.id, name=m.d.get('name', ''), who=n.bot.name)
    n.target = None
    n.next_think = now + random.uniform(0.8, 2.5) * n.bot.k['personality']['reaction_sec']      # a short pause after a kill (looks at the loot)


# ------------------------------------------------------------------------------------------------------------ fire
def _ammo(n, target, m, o):
    """The ammo of this shot from stock (weapons.laser_choice: x2/x3 against a tough alien, RSB/x3 in PvP; chosen once per target, like a real
    player) and its consumption: as many rounds as lasers -> ammo or None (no rounds, cannot fire)."""
    from . import weapons as WP
    b = n.bot
    if getattr(n, 'ammo_target', (None,))[0] != target or WP.stock(b).get(n.ammo_target[1], 0) <= 0:
        pvp = o is not None or (m is not None and m.bot is not None)
        ehp = 0 if pvp or m is None else m.d.get('hp', 0) + m.d.get('shield', 0)
        n.ammo_target = (target, WP.pick_laser(b, ehp, pvp))
    ammo = n.ammo_target[1]
    if ammo is None:
        return None
    laser = max(1, len(K.outfit(b.k['gear'], b.shield_share())['laser']))
    if not WP.spend(b, ammo, laser):
        return None
    from . import lab as LB
    n.lab_shot = LB.bonus(b, LB.LASER)                   # the lab bonus of this shot
    LB.spend(b, LB.LASER, laser)
    return ammo


def _color(b, ammo=None):
    laser_colors = K.ITEMS['laser_colors']
    e = b.k['gear']
    c = ammo or e['ammunition']
    full = laser_colors['full_set']
    lasers = [l for l, k in e['laser'].items() if k]
    if lasers and set(lasers) <= set(full['lasers']) and c in full['ammunition']:
        return full['ammunition'][c]
    return laser_colors['ammunition'].get(c, 0)


def _fire(b, pvp=False, ammo=None):
    y = K.outfit(b.k['gear'], b.shield_share())
    multiplier = K.ITEMS['laser_ammo'].get(ammo or b.k['gear']['ammunition'], {}).get('multiplier', 1)
    lab = b.body.lab_shot if b.body is not None and hasattr(b.body, 'lab_shot') else 0.0
    return int(sum(y['laser']) * multiplier * (1 + lab) * random.uniform(*K.ITEMS['damage_random']))


def fire(w, n, now):
    """Fire at the target (once every 1.1 s): at an alien, a player or another bot."""
    if n.target is None:
        if n.fire:
            n.fire = False
            _broadcast(w, [('AttackAbortLaserCommand', {'uid': n.id})], n.id)
        return
    if now < n.next_shot:
        return
    pos = _position(w, n.target, now)
    if pos is None:
        n.target = None
        return
    nx, ny = n.mover.pos(now)
    if math.hypot(pos[0] - nx, pos[1] - ny) > LASER_RANGE:
        return
    n.next_shot = now + COMBAT_INTERVAL
    target = n.target
    m = w.npcs.get(target)
    o = _player(w, target) if m is None else None
    if o is not None and not can_attack_player(w, n, o, now):
        n.target = None
        return
    if m is not None and m.bot is not None and not can_attack_bot(w, n, m, now):
        n.target = None
        return
    ammo = _ammo(n, target, m, o)
    if ammo is None:                                      # out of rounds: cannot fire (resupply at decision time)
        if n.fire:
            n.fire = False
            _broadcast(w, [('AttackAbortLaserCommand', {'uid': n.id})], n.id)
        return
    n.fire = True
    rocket(w, n, target, m, o, now)
    salvo(w, n, target, m, o, now)
    from . import active_items as AC, weapons as WP
    AC.decloak(w, n)                                       # a cloaked bot that fires becomes visible
    if m is not None and m.bot is None:
        AC.chain_impulse(w, n, now)
    run = ('AttackLaserRunCommand', dict(attackerId=n.id, targetId=target, laserColor=_color(n.bot, ammo), isDiminishedBySkillShield=False,
                                         skilledLaser=False, visualType=0))
    is_hard = o is not None or (m is not None and (m.bot is not None or (m.d.get('hp', 0) + m.d.get('shield', 0))
                                               / max(1, n.bot.value()['dps']) > WP.HARD_SEC))
    landed = random.random() < AC.aim(n, WD.COMBAT['laser_hit_chance'], is_hard)      # AIM CPU (Xenomit)
    if o is not None:
        msgs = [run]
        if landed:
            dmg = _fire(n.bot, pvp=True, ammo=ammo)
            AC.leech(n, dmg, n.bot.value()['hp'], now)
            msgs += o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=now)
        else:
            msgs.append(('AttackMissedCommand', dict(attackType=WD.attack_type(1), targetUserId=target, skillColorId=0)))
        o.send(msgs)
        return
    if m is None or not m.alive:
        n.target = None
        return
    if not landed:
        _broadcast(w, [run, ('AttackMissedCommand', dict(attackType=WD.attack_type(1), targetUserId=target, skillColorId=0))], n.id, target)
        return
    dmg = _fire(n.bot, pvp=m.bot is not None, ammo=ammo)
    AC.leech(n, dmg, n.bot.value()['hp'], now)
    if m.bot is not None:
        _broadcast(w, [run], n.id, target)
        bot_damage(w, m, dmg, n.id, now, killer_bot=n.bot)
        return
    hit_npc(w, n, m, dmg, now, 1, [run], ammo=ammo)


def salvo(w, n, target, m, o, now):
    """The rocket launcher's salvo (against a tough alien or in PvP): as many rockets as capacity, half a second apart; its visual is the rocket's
    old text (with the launcher rocket's id), the damage when each rocket arrives."""
    from . import technology as TECH, weapons as WP
    b = n.bot
    if now < getattr(n, 'salvo_ready', 0):
        return
    pvp = o is not None or (m is not None and m.bot is not None)
    is_hard = m is not None and m.bot is None and (m.d.get('hp', 0) + m.d.get('shield', 0)) / max(1, b.value()['dps']) > WP.HARD_SEC
    fr = TECH.pick_launcher_rocket(b) if (pvp or is_hard) else None
    pos = _position(w, target, now)
    nx, ny = n.mover.pos(now)
    if not fr or pos is None or math.hypot(pos[0] - nx, pos[1] - ny) > TECH.LAUNCHER['range']:
        return
    capacity, mid = TECH.salvo(b)
    capacity = WP.spend(b, fr, capacity)
    if not capacity:
        return
    n.salvo_ready = now + mid
    r = TECH.LAUNCHER_AMMO[fr]
    dmg = int(r.get('pvp_damage' if pvp else 'damage', r['damage']))
    for i in range(capacity):
        def at(i=i):
            t = time.time()
            if not n.alive:
                return
            _broadcast(w, [legacy('0|v|%d|%d|H|%d|0|0' % (n.id, target, r.get('uid', 9)))], n.id, target)

            def hit():
                t2 = time.time()
                if not n.alive:
                    return                                # a dead bot's salvo does not hit
                if o is not None:
                    if can_attack_player(w, n, o, t2):
                        o.send(o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=t2))
                    return
                x = w.npcs.get(target)
                if x is not None and x.alive:
                    if x.bot is not None:
                        bot_damage(w, x, dmg, n.id, t2, killer_bot=b)
                    else:
                        hit_npc(w, n, x, dmg, t2, 0, ammo=fr)
            w.later(WD.COMBAT['rocket_flight_sec'], hit)
        w.later(i * 0.5, at)
    b.ist('salvo')


def player_near(w, m, now, reach=1500):
    """Is the player near the alien: effects aimed at the player triggered by a bot's hit (EMP, reverse control) only then."""
    if w.hero_dead or w.jumping:
        return False
    hx, hy = w.hero_pos(now)
    mx, my = m.mover.pos(now)
    return math.hypot(hx - mx, hy - my) <= reach


def hit_npc(w, n, m, dmg, now, atype, once=(), shield=False, ammo=None):
    """The bot's laser (atype 1) or rocket (0) on an alien: the shield absorbs, then the hull; if it dies npc_kill, otherwise the alien turns on the bot.
    shield: shield only (Chain Impulse). The alien's mechanics are as in the player's hit (world.hit_npc): invulnerability while its helpers are alive,
    only specific ammo, damage reduction, a cloaked commando becoming visible, summoning when hit (the helpers spawn around the bot and
    attack it), HP floor, summoning and disappearing at an HP threshold (alien.on_hit; EMP and reverse control aimed at the player only if the
    player is near). Before, a bot's hit skipped these: Cubikon was not summoning Protegit on a bot (user report 2026-10-30)."""
    if not m.alive:
        return
    only = m.d.get('ammo_only')
    if (m.invulnerable and m.invulnerable()) or m.effect.invulnerable(now) or w.guarded(m) or (only and ammo not in only):
        dmg = 0
    red = getattr(m, 'damage_reduction', None)
    if red:
        dmg = int(dmg * max(0.0, 1 - red()))
    if getattr(m, 'hidden', False):                       # a cloaked commando becomes visible when hit (infiltration.py)
        m.hidden = False
        w.send([legacy('0|n|INV|%d|0' % m.id)])
    w.alien.attacked(m, n.id, now)
    w.npc_summon(m, now, hitter=n)
    absorb = 1.0 if shield else m.d.get('shield_absorb', WD.COMBAT['npc_shield_absorb'])
    to_shield = min(int(m.shield), int(round(dmg * absorb)))
    m.shield -= to_shield
    m.hp = max(0, m.hp - (dmg - to_shield))
    floor = getattr(m, 'hp_floor', 0)                  # Guardian "falls" at 1 HP (phases)
    if floor and m.hp < floor:
        m.hp = floor
        if getattr(m, 'at_floor', None):
            m.at_floor(m)
    m.last_hit = now
    w.alien.on_hit(m, dmg, n.id, now, to_player=player_near(w, m, now))
    if not m.alive or m.id not in w.npcs:                 # disappeared or left (alien.on_hit)
        return
    who = ('h', w.hid) if is_helping(w, n, m, now) else ('b', n.id)
    WD.tag_alien(m, who, now)
    WD.record_damage(m, who, dmg)                            # on a group alien the reward is split by damage (tag_sharers)
    hit = ('AttackHitCommand', dict(attackType=WD.attack_type(atype), attackerId=n.id, victimId=m.id, victimHitpoints=int(m.hp),
                                    victimShield=int(m.shield), victimNanoHull=0, damage=dmg, skilled=False, strike=False, cannonType=0))
    msgs = list(once) + [hit] + ([w.selection(m)] if w.target == m.id and m.hp > 0 else [])
    _broadcast(w, msgs, n.id, m.id)
    if m.hp <= 0:
        kill_npc(w, m, n, now)
    elif m.bot_target is None and m.d['damage'] > 0:
        m.bot_target = n.id                     # the alien turns on the bot (if it fights the player too: the nearer one, npc_to_bot)
        m.next_think = now


def rocket(w, n, target, m, o, now):
    """Rocket (cooldown 4 s, 2 with R0K-T01): if in range the strongest in stock; its visual is the old text like the player's (0|v|...), the hit
    after ~0.8 s (the hit chance is the rocket's own rate)."""
    from . import weapons as WP
    b = n.bot
    if now < getattr(n, 'rocket_ready', 0):
        return
    rocket = WP.pick_rocket(b)
    pos = _position(w, target, now)
    nx, ny = n.mover.pos(now)
    if not rocket or pos is None or math.hypot(pos[0] - nx, pos[1] - ny) > WD.COMBAT['rocket_range'] or not WP.spend(b, rocket, 1):
        return
    n.rocket_ready = now + WP.rocket_cooldown(b)
    r = K.ITEMS['rockets'][rocket]
    landed = random.random() < r.get('hit', WD.COMBAT['rocket_hit_chance'])
    _broadcast(w, [legacy('0|v|%d|%d|%s|%d|0|0' % (n.id, target, 'H' if landed else 'M', r.get('uid', 1)))], n.id, target)
    if not landed:
        return
    from . import lab as LB
    dmg = int(r.get('pvp_damage' if (o is not None or (m is not None and m.bot is not None)) else 'damage', r['damage'])
              * random.uniform(0.85, 1.0) * (1 + LB.bonus(b, LB.ROCKET)))
    LB.spend(b, LB.ROCKET, 1)

    def hit():
        t = time.time()
        if not n.alive:
            return
        if o is not None:
            if can_attack_player(w, n, o, t):
                o.send(o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=t))
            return
        x = w.npcs.get(target)
        if x is None or not x.alive:
            return
        if x.bot is not None:
            bot_damage(w, x, dmg, n.id, t, killer_bot=b)
        else:
            hit_npc(w, n, x, dmg, t, 0, ammo=rocket)
    w.later(WD.COMBAT['rocket_flight_sec'], hit)


def npc_reward(b, m, pay=1):
    """The alien's reward to the bot (the pack's speed, the X-1 cut), extra loot and quest progress. pay: number of stakeholders in a group (the reward
    is split, loot and quest are whole; like world.npc_reward)."""
    from . import loot as LT, events as EV
    LT.extra_loot(b, m.tip, 1)
    EV.drop(b, b.game_map, m.tip)                         # event drops (Candy Corn ...)
    y_ = MGR.ACTIVE
    speed = y_.speed(b) if y_ is not None else 1.0
    o = m.d.get('reward', {})
    x1 = S.x1_cut(b) / pay                           # to all four rewards, as in the player
    b.reward('npc', speed, ep=o.get('ep', 0) * x1, credits=o.get('credits', 0) * x1, uridium=o.get('uridium', 0) * x1,
           honor=o.get('honor', 0) * x1)
    b.ist('npc')
    b.ist('npc_points', T.npc_rank_points(m.tip))
    if y_ is not None:
        with y_.lock:
            y_.npc_killed(b, m.tip, 1)


def group_bots(w):
    """The bots in the hero's group that are alive on this map (stakeholders of the alien's reward; group.py)."""
    return [m.bot for m in list(w.npcs.values()) if m.bot is not None and m.alive and w.is_group_member(m.id)]


def drop_cargo(w, m, uid, x, y):
    """The alien's cargo box (its ores) in the bot's name: only if the bot's ship is on the map (there is someone to collect it)."""
    t = w.npcs.get(uid)
    if t is None or t.bot is None or not t.bot.permission.get('cargo', True):
        return
    cargo = {str(k): v for k, v in K.npc_cargo(m.tip, t.bot.level, w.map_id).items()}
    if not cargo:
        return
    owner_tag = ('b', uid) if WD.SET.get('cargo_ownership') else None
    w.later(WD.COMBAT['box_delay_sec'], lambda: w.drop_box('FROM_SHIP', x, y, cargo, WD.COMBAT['box_life_sec'], owner_tag=owner_tag))


def _bot(uid):
    y_ = MGR.ACTIVE
    return next((b for b in y_.bots if b.uid == uid), None) if y_ is not None else None


def bot_company(uid):
    b = _bot(uid)
    return b.company if b is not None else None


def tag_reward(w, m, uid, x, y):
    """Someone else finished the alien the bot tagged: the reward, quest and cargo box go to the bot (world.World.tag_stakeholders)."""
    b = _bot(uid)
    if b is None or not b.online:
        return
    npc_reward(b, m)
    drop_cargo(w, m, uid, x, y)


def bot_online(uid):
    b = _bot(uid)
    return b is not None and b.online


def split_reward(w, m, uid, ratio, x, y, box=False):
    """The bot's share by damage on a group alien (world.World.by_damage): the reward by the ratio (npc_reward pay=1/ratio), and if the bot dealt the most
    damage the cargo box is its too."""
    b = _bot(uid)
    if b is None or not b.online:
        return
    npc_reward(b, m, 1.0 / ratio)
    if box:
        drop_cargo(w, m, uid, x, y)


def on_box_taken(owner_tag, name):
    """The player collected the bot's cargo box: the bot does not forget it (in its memory like an insult)."""
    if not owner_tag or owner_tag[0] != 'b':
        return
    b = _bot(owner_tag[1])
    if b is not None and name:
        b.memory.event(name, 'insult', b.hour(), multiplier=0.5)
        b.event('box_taken', name=name)


def can_attack_player(w, n, o, now):
    if o.hero_dead or o.jumping or o.hidden(now) or not o.running:
        return False
    import admin_mode as YM
    from . import admin_warnings as AW
    if YM.mi(profile=o.p) or YM.spectator(o.p) or AW.active(n.bot, 'pvp', now):
        return False                                     # the manager is not attacked (wiki Administrator: "should not be shot at"); PvP warning
    if now < o.invuln_until or o.invulnerable or o.hero_effects.invulnerable(now):
        return False
    hx, hy = o.hero_pos(now)
    nx, ny = n.mover.pos(now)
    if _in_peace(w, hx, hy) or _in_peace(w, nx, ny, n.bot) or relation(o, n.bot) in (1, 2):
        return False                                     # its clan is an ally or in non-aggression
    return int(o.p.d['pilot'].get('factionId') or 0) != n.bot.company or not (
        H.company(w.map_id) == n.bot.company and H.name(w.map_id).split('-')[-1] in ('1', '2'))


def can_attack_bot(w, n, m, now):
    from . import admin_warnings as AW
    if not m.alive or m.bot.company == n.bot.company or AW.active(n.bot, 'pvp', now):
        return False
    if (n.bot.k.get('clan') and n.bot.k.get('clan') == m.bot.k.get('clan')) or T.clan_relation(n.bot, m.bot) in (1, 2):
        return False
    nx, ny = n.mover.pos(now)
    mx, my = m.mover.pos(now)
    return not (_in_peace(w, nx, ny, n.bot) or _in_peace(w, mx, my, m.bot))


# ------------------------------------------------------------------------------------------------------------ the alien's reply to the bot
def notice_bot(w, m, now, hero_dist):
    """An aggressive alien notices a bot ship within its notice distance that is nearer than the player (hero_dist; inf if the player cannot be
    attacked) and turns on it (npc_to_bot) -> did it. Before, only the player's distance was checked: aliens attacked bots only when hit."""
    if now < m.bot_scan:
        return False
    m.bot_scan = now + 1.0
    mx, my = m.mover.pos(now)
    reach = min(hero_dist, m.d.get('notice_distance', WD.COMBAT['npc_notice_distance']) * WD.SET.multiplier('npc_notice'))
    best = None
    for t in list(w.npcs.values()):
        if t.bot is None or not t.alive:
            continue
        tx, ty = t.mover.pos(now)
        d = math.hypot(tx - mx, ty - my)
        if d < reach and (best is None or d < best[0]) and not _in_peace(w, tx, ty, t.bot):
            best = (d, t)
    if best is None:
        return False
    m.bot_target, m.next_think = best[1].id, now
    return True


def fighting(w, n):
    """The bot is fighting: its target is a living ship on the map (an alien or a bot; world.hero_fighting for the pilot)."""
    t = w.npcs.get(n.target)
    return t is not None and t.alive


def npc_to_bot(w, m, now):
    """The alien the bot hit (or noticed: notice_bot) turns on the bot: chases and fires -> handled or not (the rest of think is skipped). If it
    fights the player too, the nearer of the two (player report 2026-11-02: aliens almost never attacked bots, a bot's hit was ignored while
    the alien was after the player, and an alien that got to the player dropped the bot for good)."""
    t = w.npcs.get(m.bot_target)
    if t is None or not t.alive or t.bot is None:
        m.bot_target = None
        return False
    tx, ty = t.mover.pos(now)
    mx, my = m.mover.pos(now)
    dist = math.hypot(tx - mx, ty - my)
    if m.engaged:
        hx, hy = w.hero_pos(now)
        if not w.hero_dead and math.hypot(hx - mx, hy - my) <= dist:
            return False                        # the player is nearer: the bot stays in mind for later
        m.engaged = False                       # the bot is nearer: the laser on the player stops
        w.alien_ceasefire(m)
    if _in_peace(w, tx, ty, t.bot) and not fighting(w, t):
        # safe zone (the zones that protect this bot: its company's): the player's rule (world.npc_retaliating): the zone is void only
        # while the bot keeps fighting there; a bot that is not fighting (fled, ceased fire) is let go by every alien after it, at once
        # (checked before the wait for the next think: test_bot_safe failed when its second call fell inside that wait)
        m.bot_target = None
        w.alien_ceasefire(m)
        w.stop_npc_motion(m, now)
        return False
    if now < m.next_think and now < m.next_shot:
        return True
    post = w.ward_of(m)
    if dist > 2500 or (post and w.leashed(m, post, tx, ty, now)):
        # a guard (Cubikon's Protegits) does not chase the bot away from its summoner all the way to the portal: the same as the player's leash (world.leashed)
        m.bot_target = None
        return False
    if now >= m.next_think:
        m.next_think = now + 1.0
        if dist > m.keep + 60:
            a = math.atan2(my - ty, mx - tx) + m.spread
            gx, gy = tx + math.cos(a) * m.keep, ty + math.sin(a) * m.keep
            ms = m.mover.go(gx, gy, m.speed(), now)
            w.send([('MoveCommand', dict(userId=m.id, x=int(gx), y=int(gy), timeToTarget=ms))])
    if now >= m.next_shot and dist <= w.npc_range(m) and m.d['damage'] > 0:
        m.next_shot = now + m.d.get('shot_interval_sec', WD.COMBAT['npc_attack_interval_sec'])
        _broadcast(w, [('AttackLaserRunCommand', dict(attackerId=m.id, targetId=t.id, laserColor=0, isDiminishedBySkillShield=False,
                                                  skilledLaser=False, visualType=0))], m.id, t.id)
        if random.random() < m.d.get('hit', WD.COMBAT['npc_hit_chance']):
            bot_damage(w, t, int(m.d['damage'] * random.uniform(0.8, 1.0)), m.id, now, npc=m)
    return True


# ------------------------------------------------------------------------------------------------------------ taktik
def think(w, n, now):
    """The bot's brain in the world loop (in place of think; called every step, thinks at its own interval)."""
    if not n.alive:
        return
    b = n.bot
    fire(w, n, now)
    if now < n.next_think:
        return
    n.next_think = now + b.k['personality']['reaction_sec'] * random.uniform(0.6, 1.4)
    d = b.value()
    if now - n.last_damage > COMBAT_SEC:                     # yenilenme
        from . import extras as EX
        k = REGEN_RATE * b.k['personality']['reaction_sec'] * 1.0
        rep = EX.repair_sec(b)
        n.shield = min(d['shield'], n.shield + d['shield'] * k * 2)
        n.hp = min(d['hp'], n.hp + d['hp'] * max(k, b.k['personality']['reaction_sec'] / rep if rep else 0))     # repair robot
    nx, ny = n.mover.pos(now)
    b.k['x'], b.k['y'] = int(nx), int(ny)
    if b.__dict__.get('exit_request') and now < b.session_end:
        b.exit_request = b.logout_ready = None           # the session was extended / the bot came back online: stale request
    if b.__dict__.get('exit_request') and not any(now - t < 6 for t in n.attacker.values()):
        return go_logout(w, n, now)                     # session over: flies to the station or portal and leaves there
    if getattr(n, 'shelter', None) is not None and sheltering(w, n, now, d):
        return                                           # fled: no box, goal or fight until it has recovered in its shelter
    if (n.target is None and not any(now - t < 6 for t in n.attacker.values()) and not b.en_route
            and (b.target is None or b.target.name != 'gate') and collect_box(w, n, now)):
        return                                           # picks up a box on its route (on every job; when not fighting)
    if b.target is not None and b.target.concrete(b, n, w, now):
        return
    ratio = (n.hp + n.shield) / max(1, d['hp'] + d['shield'])
    attackers = [u for u, t in n.attacker.items() if now - t < 6]
    from . import active_items as AC
    if AC.combat(w, n, now, d, ratio, attackers):         # Insta-Shield, Backup Shields, Battle Repair, Smart Bomb, Energy Leech
        ratio = (n.hp + n.shield) / max(1, d['hp'] + d['shield'])
    # 1) danger: HP is low and it is being hit -> flee (to a shelter; it keeps fleeing there until it has recovered: sheltering)
    in_gate = is_gate_world(w)
    if attackers and ratio < 0.18 + 0.32 * (1 - b.o('risk')) + PL.flee_shift(b) and not in_gate and flee(w, n, now):
        return                                           # (survival skill: unaware pilots flee late; cowards early, kamikazes hardly)
    # 2) portal yolunda
    if b.en_route and not attackers and not in_gate:
        return portala(w, n, now)
    # 2b) damaged and nobody is hitting: stops and recovers
    if not attackers and recover(w, n, now, d):
        return
    # 3) retaliate against an attack or flee
    if attackers and (n.target is None or n.target not in attackers):
        u = attackers[-1]
        if u in w.npcs and w.npcs[u].bot is None:
            n.target = u                                  # an alien hit: retaliate
        else:
            opponent = _power(w, u)
            if opponent / max(0.5, d['power']) > 1.3 + b.o('risk') + 0.5 * b.mood['anger'] and ratio < 0.9 and flee(w, n, now):
                return
            n.target = u
            b.memory.event(_name(w, u), 'insult', now, multiplier=0.3)
    # 4) PvP opportunity
    if n.target is None or n.target in w.npcs and w.npcs[n.target].bot is None:
        t = pvp_target(w, n, now)
        if t is not None:
            n.target = t
    # 4b) escort: if it joined you or a bot that is its friend, it fires at their target, otherwise flies beside them
    if escort(w, n, now):
        return
    # 5) approach the target / behave according to the target
    if n.target is not None:
        pos = _position(w, n.target, now)
        if pos is None:
            n.target = None
        else:
            return approach(w, n, pos, now)
    h = b.target.name if b.target is not None else 'grinding'
    if h == 'resting':
        return rest(w, n, now)
    return go_hunt(w, n, now)


def _name(w, uid):
    o = _player(w, uid)
    if o is not None:
        return o.p.d['pilot'].get('userName', '')
    m = w.npcs.get(uid)
    if m is not None:
        return m.bot.name if m.bot is not None else m.d.get('name', '')
    # not on the map (a bot that left or died, the player's P.E.T.): it used to return "" and bots accumulated "insults" from a nameless someone
    b = _bot(uid)
    if b is not None:
        return b.name
    if getattr(w, 'pet', None) is not None and w.pet.owned and w.pet.pid == uid:      # without a P.E.T. the pid cannot be read (live test)
        return w.p.d['pilot'].get('userName', '')
    return ''


def _power(w, uid):
    o = _player(w, uid)
    if o is not None:
        return hero_power(o)
    m = w.npcs.get(uid)
    return m.bot.value()['power'] if m is not None and m.bot is not None else 1.0


def approach(w, n, pos, now):
    """Combat distance to the target: within laser range, close or far depending on personality; circles lightly around the target."""
    nx, ny = n.mover.pos(now)
    dist = math.hypot(pos[0] - nx, pos[1] - ny)
    pl = PL.profile(n.bot)
    wanted = (280 + 300 * (1 - n.bot.o('aggression'))) * pl['range']         # its own preferred distance (playstyle.py)
    pvp = n.target in w.npcs and w.npcs[n.target].bot is not None or n.target not in w.npcs
    sk = PL.skill(n.bot, 'pvp' if pvp else 'combat')
    if dist > wanted + 120 or dist < 120:
        a = math.atan2(ny - pos[1], nx - pos[0]) + random.uniform(-0.5, 0.5)
        _go_to(w, n, pos[0] + math.cos(a) * wanted, pos[1] + math.sin(a) * wanted, now)
    elif n.mover.t1 <= now and random.random() < (0.12 + 0.6 * pl['orbit']) * (0.55 + 0.9 * sk):     # skilled pilots keep moving
        # in range: circles around the target (a real player fires while circling, not standing still); the direction is fixed by the bot's temperament
        direction = n.__dict__.setdefault('orbit_direction', random.choice((-1, 1)))
        a = math.atan2(ny - pos[1], nx - pos[0]) + direction * random.uniform(0.25, 0.6)
        _go_to(w, n, pos[0] + math.cos(a) * wanted, pos[1] + math.sin(a) * wanted, now, threshold=40)


def pvp_target(w, n, now):
    """An enemy player or bot in sight: worth attacking (personality, power ratio, grudge, PvP target)."""
    b = n.bot
    y = MGR.ACTIVE
    if y is None or now - n.intent_time < 4:
        return None
    n.intent_time = now
    nx, ny = n.mover.pos(now)
    sight = WD.COMBAT['sight_range']
    candidates = []
    if y.permission('attack_player') and y.permission('pvp'):
        for o in ([w] + [x for x in (w.shared.members if w.shared else []) if x is not w]):
            if not o.running or int(o.p.d['pilot'].get('factionId') or 0) == b.company:
                continue
            hx, hy = o.hero_pos(now)
            if math.hypot(hx - nx, hy - ny) > sight or not can_attack_player(w, n, o, now):
                continue
            candidates.append((o.hid, hero_power(o), o.p.d['pilot'].get('userName', ''), relation(o, b)))
    if y.permission('pvp'):
        for m in w.npcs.values():
            if m.bot is None or m is n or not m.alive:
                continue
            mx, my = m.mover.pos(now)
            if math.hypot(mx - nx, my - ny) > sight or not can_attack_bot(w, n, m, now):
                continue
            candidates.append((m.id, m.bot.value()['power'], m.bot.name, T.clan_relation(b, m.bot)))
    if not candidates:
        return None
    own = max(0.5, b.value()['power'])
    ev = H.company(w.map_id) == b.company                  # its own company's map: defends its map against an invader
    hunt = b.target is not None and b.target.name in ('pvp', 'assist', 'duel')
    rival = str(b.plan.get('name', '')).lower() if b.target is not None and b.target.name == 'duel' else ''
    en, ep = None, 0.0
    for uid, power, name, rel in candidates:
        ratio = power / own
        grudge = -min(0.0, b.memory.relation(name, now)) + (0.6 if rel == 3 else 0.0)     # clan war: a member of the enemy clan
        grudge += order_grudge(b, name, now)                      # clan order: the person to hunt / the clan in focus (goals/pvp.py)
        if rival and str(name).lower() == rival:
            return uid                                   # duel: attacks the challenger at once
        defending = ev and uid not in w.npcs                    # a foreign company's player on its own map
        p = (0.04 + 0.5 * b.o('aggression') * b.o('rivalry')) * (2.2 if hunt else 1.0)
        if defending:
            p = max(p, 0.06) * (2.0 + b.o('aggression'))
        # at home it also stands up to a somewhat stronger one (calls for help); before, the probability at 1.6x stronger was zero at home too (live 2026-11-01)
        p *= max(0.0, (2.4 if defending else 1.6) - ratio) * (0.5 + b.mood['confidence']) + grudge * 0.8
        if ratio > 1.2 + b.o('risk') + grudge + (0.5 if defending else 0.0):
            p *= 0.1
        if p > ep:
            en, ep = uid, p
    # a probability per decision (every 4 s) rather than per second: it looks like attacking after a while, not immediately
    if en is None or random.random() >= min(0.9, ep * 0.5):
        return None
    if ev and en not in w.npcs:
        call_defense(w, n, en, now)
    return en


DEFENSE_MAX = 2                # the most helpers called against one invader (not a swarm)
DEFENSE_COOLDOWN = 60.0           # between two calls on the same map (s)


def call_defense(w, n, uid, now):
    """A bot attacking a foreign player on its own map calls at most DEFENSE_MAX of the idle company bots on the map
    (the nearby ones, by aggression; there is a cooldown; the PvP rules are the same as can_attack_player)."""
    if now < w.__dict__.get('defense_time', 0):
        return
    o = _player(w, uid)
    if o is None:
        return
    w.defense_time = now + DEFENSE_COOLDOWN
    nx, ny = n.mover.pos(now)
    candidates = []
    for m in w.npcs.values():
        if m is n or m.bot is None or not m.alive or m.bot.company != n.bot.company or m.target is not None:
            continue
        if m.bot.target is not None and m.bot.target.name in ('gate', 'mod', 'duel', 'group'):
            continue
        if now - m.last_damage < COMBAT_SEC or m.bot.en_route or not can_attack_player(w, m, o, now):
            continue
        mx, my = m.mover.pos(now)
        distance = math.hypot(mx - nx, my - ny)
        if distance < 6000 and random.random() < 0.3 + 0.6 * m.bot.o('aggression'):
            candidates.append((distance, m))
    for _, m in sorted(candidates, key=lambda x: x[0])[:DEFENSE_MAX]:
        m.target = uid
        m.intent_time = now


SHELTER_RESUME = 0.9            # a fled bot leaves its shelter at this HP+shield ratio (recover's "full")
SHELTER_HIT_SEC = 3.0           # still hit this recently inside a portal's zone: it jumps


def shelters(w, b):
    """The zones that protect this bot ship on this map, (x, y, radius): its company's station, its company's portals and the layout's safe
    zones; the same zones as world.in_pvp_peace for its company (none on an enemy company's map or a war map)."""
    out = []
    s = w.home_station(b.company)
    if s:
        out.append((s['posX'], s['posY'], s['peaceRadius']))
    r = ML.gate_peace_radius(w.map_id, H.GATE_PEACE_RADIUS)
    out += [(g['x'], g['y'], r) for g in w.peace_gates(b.company)]
    return out + [tuple(z) for z in ML.safe_zones(w.map_id)]


def _exits(w, b):
    """The portals it can jump through to escape (free, to a map it may enter)."""
    return [g for g in H.gates(w.map_id, b.company) if not g.get('fee') and g['target'] in K.MAPS
            and K.can_enter(g['target'], b.company, b.level)]


def flee(w, n, now):
    """Flee like a pilot does: stop fighting and go to the nearest zone that protects it (shelters). There the aliens let go of a ship that is
    not fighting (npc_to_bot) and players cannot attack it; it stays and recovers (sheltering) and goes on with its job. It escapes through a
    portal only when no zone protects it on this map (an enemy company's or a war map) or when it is still being hit inside a portal's zone;
    simple mode bots do not change maps. While fleeing from a player it drops a mine behind (not in a safe zone or on starting maps).
    User report 2026-11-03: it used to head for a portal and jump even on its own map, where the portal's zone already protects it.
    -> is it fleeing (False: nowhere to go, no zone and no portal it may enter: cornered, it fights back)."""
    b = n.bot
    n.target = None
    nx, ny = n.mover.pos(now)
    if any(_player(w, u) is not None for u, t in n.attacker.items() if now - t < 6):
        from . import active_items as AC
        AC.emp(w, n, now)                                # the locked player's selection is dropped
        if b.o('risk') < 0.6:
            AC.cloak(w, n, now)                         # cloaking CPU
        drop_mine(w, n, nx, ny, now)
    y = MGR.ACTIVE
    jumps = y is None or y.mode != 'simple'
    sh = getattr(n, 'shelter', None)
    if sh is None:
        zones = shelters(w, b)
        sh = n.shelter = min(zones, key=lambda z: math.hypot(z[0] - nx, z[1] - ny) - z[2]) if zones else 'portal'
        b.event('fled', map=H.name(w.map_id))
    if sh != 'portal':
        cx, cy, r = sh
        d = math.hypot(nx - cx, ny - cy)
        if d > r * 0.8:
            k = r * 0.5 / max(1.0, d)
            _go_to(w, n, cx + (nx - cx) * k, cy + (ny - cy) * k, now)      # straight in, on its near side
            return True
        gate = next((g for g in _exits(w, b) if (g['x'], g['y']) == (cx, cy)), None)
        if not (jumps and gate and now - n.last_damage < SHELTER_HIT_SEC):
            return True                                              # in the shelter: waits (the hits stop, it recovers)
        sh = n.shelter = 'portal'                                    # still hit inside a portal's zone: jumps like a pilot would
        b.en_route = [gate['target']]
    gs = _exits(w, b)
    if not gs:
        n.shelter = None
        return False
    g = min(gs, key=lambda g: math.hypot(g['x'] - nx, g['y'] - ny))
    if not jumps:
        _go_to(w, n, g['x'] + random.uniform(-200, 200), g['y'] + random.uniform(-200, 200), now)    # simple: no zone protects it here
        return True
    if not b.en_route or b.en_route[0] != g['target']:
        b.en_route = [g['target']]
    portala(w, n, now, urgent=True)
    return True


def sheltering(w, n, now, d):
    """A fled bot (n.shelter) keeps fleeing until it has recovered (SHELTER_RESUME) and nobody hits it: a heal over the flee threshold
    (Backup Shields, Battle Repair) or a pause in the hits no longer turns it back on the aliens (user report 2026-11-03) -> handled."""
    if is_gate_world(w):
        n.shelter = None
        return False
    attackers = [u for u, t in n.attacker.items() if now - t < 6]
    ratio = (n.hp + n.shield) / max(1, d['hp'] + d['shield'])
    if attackers:
        from . import active_items as AC
        if AC.combat(w, n, now, d, ratio, attackers):     # Insta-Shield, Backup Shields, Battle Repair … while fleeing too
            ratio = (n.hp + n.shield) / max(1, d['hp'] + d['shield'])
    if ratio >= SHELTER_RESUME and not attackers:
        n.shelter = None
        return False
    return flee(w, n, now)


def drop_mine(w, n, x, y, now):
    """The bot's mine (explodes when it approaches the player's ship: combat_items.alien_mine) -> was it dropped."""
    from . import weapons as WP
    b = n.bot
    m = WP.pick_mine(b)
    if m is None or now < getattr(n, 'mine_ready', 0) or w.items.start_map() or w.in_pvp_peace(x, y, n.bot.company):
        return False
    if not WP.spend(b, m, 1):
        return False
    n.mine_ready = now + WP.MINE_COOLDOWN
    w.items.alien_mine(m, x, y, n.id, now)
    b.ist('mine')
    return True


def portala(w, n, now, urgent=False):
    """Fly to the portal of the route's next map; on arrival, JUMP_SEC later leave the map (the manager moves the bot to the new map)."""
    b = n.bot
    if not b.en_route:
        return
    if len(b.en_route) > 2 and not urgent:                     # jump CPU: the long route to base in a single jump
        from . import extras as EX
        cpu = EX.jump(b, b.en_route[-1])
        y = MGR.ACTIVE
        if cpu and y is not None and EX.use(b, cpu):
            target = b.en_route[-1]
            w.send(remove(w, n))
            with y.lock:
                S.jump_to(b, target, y, time.time())
                b.en_route = None
                b.ist('jump_cpu')
            return
    g = next((g for g in H.gates(w.map_id, b.company) if g['target'] == b.en_route[0]), None)
    if g is None:
        b.en_route = None
        return
    nx, ny = n.mover.pos(now)
    if not urgent and now < n.spawn + n.takeoff:             # just arrived: lingers a bit, then sets off at its own time
        if n.movement is None:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(100, 350)
            _go_to(w, n, nx + math.cos(a) * r, ny + math.sin(a) * r, now)
        return
    p = n.approach_points.get(g['target'])
    if p is None:                                         # its own docking point around the portal (not always the same point)
        a, r = random.uniform(0, 2 * math.pi), random.uniform(30, 140)
        p = n.approach_points[g['target']] = (g['x'] + math.cos(a) * r, g['y'] + math.sin(a) * r)
    if math.hypot(g['x'] - nx, g['y'] - ny) > 180:
        n.portal_time = 0.0
        if urgent:
            _go_to(w, n, p[0], p[1], now)                   # straight when fleeing
        else:
            _route(w, n, p[0], p[1], now)
        return
    if not n.portal_time:
        n.portal_time = now + JUMP_SEC * (0.8 if urgent else random.uniform(1.0, 2.5))
        n.target = None
        return
    if now < n.portal_time:
        return
    y = MGR.ACTIVE
    target = b.en_route.pop(0)
    w.send(remove(w, n))
    if y is not None:
        with y.lock:
            S.jump_to(b, target, y, time.time())
            b.en_route_time = time.time() + S.jump_duration(b)


def can_kill(b, m):
    """An alien not in the map's fixed list (event, Urgent Missions target, Hitac carrier ...): if it is strong enough (cached by kind; a real
    player fires at everything it sees and can kill)."""
    c = b.__dict__.setdefault('_can_kill', {})
    v = c.get(m.tip)
    if v is None or v[1] != b.value()['power']:
        d = b.value()
        ehp = m.d.get('hp', 0) + m.d.get('shield', 0)
        incoming = m.d.get('damage', 0) * K.COMBAT['npc_hit_chance'] / K.NPC_INTERVAL
        duration = ehp / max(1.0, d['dps'])
        v = c[m.tip] = (duration < 180 and duration * incoming < d['ehp'] * (0.4 + 0.5 * b.o('risk')), d['power'])
    return v[0]


def _killable(b, m_id):
    from . import events as EV
    d = b.value()
    courage = max(0.0, min(1.0, 0.3 + 0.6 * b.o('risk') + 0.2 * b.mood['confidence'] - 0.3))
    out = set(K.evaluate_map(int(m_id), d['dps'], d['ehp'], courage)['targets'])
    return out | EV.event_types(b, int(m_id)) if b.permission.get('event', True) else out      # event aliens too


def go_hunt(w, n, now):
    """Alien hunt: the nearest of the kinds it dares to kill (the quest's first); does not grab one the player is fighting (rude bots
    occasionally do). If there is a bonus box nearby it takes it first. With no target, a purposeful patrol: flies to a far waypoint and picks
    a new one only on arrival (before, short random jumps every second looked like twitching left and right)."""
    b = n.bot
    nx, ny = n.mover.pos(now)
    if collect_box(w, n, now):
        return
    types = _killable(b, w.map_id)
    wanted = b.plan.get('tip')
    rude = random.random() < 0.15 * b.o('aggression') * (1 - b.o('helpfulness'))
    style = PL.profile(b)['target']                     # nearest / weakest (lowest HP) / richest (best reward) first
    en, best_score = None, 1e18
    for m in w.npcs.values():
        if m.bot is not None or not m.alive or m.d.get('friendly') or getattr(m, 'hidden', False):
            continue                                     # cannot see a cloaked commando (Infiltration)
        if m.tip not in types and not can_kill(b, m):
            continue
        if (m.engaged or w.target == m.id) and not rude:
            continue
        if m.bot_target not in (None, n.id) and w.npcs.get(m.bot_target) is not None:
            continue                                     # another bot is fighting it
        if WD.tag_owner(m, now) not in (None, ('b', n.id)):
            continue                                     # tagged by someone else: no gain
        mx, my = m.mover.pos(now)
        dd = math.hypot(mx - nx, my - ny) * (0.5 if m.tip == wanted else 1.0)
        if style != 'nearest' and dd < 3500:
            if style == 'weakest':
                dd *= 0.4 + (m.hp + m.shield) / max(1.0, m.d.get('hp', 1) + m.d.get('shield', 0))
            else:
                dd /= 0.5 + min(3.0, (m.d.get('reward') or {}).get('ep', 0) / max(1.0, 400.0 * b.level))
        if dd < best_score:
            en, best_score = m, dd
    if en is not None and best_score < 3500:
        n.target = en.id
        n.patrol = None
        return approach(w, n, en.mover.pos(now), now)
    start_escort(w, n, now)
    if _leader(w, n, now) is not None:
        return                                           # started escorting: next thought to the leader's side
    patrol_point = getattr(n, 'patrol', None)
    if patrol_point is None or math.hypot(patrol_point[0] - nx, patrol_point[1] - ny) < 300:
        focus = PL.skill(b, 'focus')
        if patrol_point is not None and random.random() < 0.25 + 0.4 * (1 - focus) + 0.3 * PL.has(b, 'afk'):
            n.next_think = now + random.uniform(2, 6) * (1.6 - focus) * (3 if PL.has(b, 'afk') else 1)    # arrived: looks around a bit
            n.patrol = None
            return
        roam = PL.profile(b)['roam']                    # wide roamer, local loops, or a camper around its own spot
        lo, hi = {'wide': (4000, 9000), 'local': (1800, 4500), 'camper': (500, 1600)}[roam]
        r = random.uniform(lo, hi)
        if roam == 'camper':
            home = n.__dict__.setdefault('camp', (nx, ny))
            a = math.atan2(home[1] - ny, home[0] - nx) + random.uniform(-1.2, 1.2) if math.hypot(home[0] - nx, home[1] - ny) > hi else random.uniform(0, 2 * math.pi)
        else:
            a = random.uniform(0, 2 * math.pi)
        patrol_point = n.patrol = (max(600, min(w.map_w - 600, nx + math.cos(a) * r)), max(600, min(w.map_h - 600, ny + math.sin(a) * r)))
    _route(w, n, patrol_point[0], patrol_point[1], now, threshold=400)


def go_logout(w, n, now):
    """A bot whose session ended: flies to its own station if it is on this map, otherwise to the nearest portal; on arrival the manager does its exit."""
    b = n.bot
    n.target = None
    nx, ny = n.mover.pos(now)
    s = w.station
    if s and s.get('type') == b.company:
        hx, hy = s['posX'], s['posY']
    else:
        g = min(H.gates(w.map_id, b.company) or [{'x': nx, 'y': ny}], key=lambda g: math.hypot(g['x'] - nx, g['y'] - ny))
        hx, hy = g['x'], g['y']
    if math.hypot(hx - nx, hy - ny) > 250:
        p = n.approach_points.get('exit')
        if p is None or math.hypot(p[0] - hx, p[1] - hy) > 200:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(20, 140)
            p = n.approach_points['exit'] = (hx + math.cos(a) * r, hy + math.sin(a) * r)
        _route(w, n, p[0], p[1], now)
    else:
        b.logout_ready = True


ESCORT_RANGE = 1600


def is_helping(w, n, m, now):
    """Is the bot helping the player's target (a bot escorting or in a group with them, the alien the player selected): the tag, reward
    and box are the player's (an escorting bot was firing first and taking the box: user report 2026-10-30)."""
    if m.id != w.target:
        return False
    l = _leader(w, n, now)
    if l is not None and l[0] == 'h':
        return True
    import group as GR
    g = GR.group_of(n.bot.uid)
    return g is not None and w.hid in g.members


def _leader(w, n, now):
    """The one being escorted: ('h', None) the hero or ('b', ship); None if gone, dead or too far."""
    e = n.__dict__.get('escort')
    if not e or now > e[1]:
        return None
    if e[0] == 'h':
        if w.hero_dead or w.jumping:
            return None
        return ('h', None)
    m = w.npcs.get(e[0])
    return ('b', m) if m is not None and m.alive and m.bot is not None else None


def start_escort(w, n, now):
    """When idle (hunting without a target) now and then: joins you (if you are nearby) or a bot that is its friend from the same company.
    The probability depends on sociability, relation toward you and helpfulness; 1-3 minutes."""
    b = n.bot
    if n.__dict__.get('escort') and now <= n.escort[1]:
        return
    if now < n.__dict__.get('escort_check', 0):
        return
    n.escort_check = now + random.uniform(20, 40)
    nx, ny = n.mover.pos(now)
    duration = random.uniform(60, 180)
    name = str(w.p.d['pilot'].get('userName', ''))
    if (w.p.d['pilot'].get('factionId') == b.company and not w.hero_dead and not w.jumping
            and math.hypot(*(a - c for a, c in zip(w.hero_pos(now), (nx, ny)))) < ESCORT_RANGE):
        p = 0.08 * (0.3 + b.o('sociability')) * (0.5 + b.o('helpfulness')) * (1 + 3 * max(0.0, b.memory.relation(name, now)))
        if random.random() < p:
            n.escort = ('h', now + duration, random.uniform(0, 2 * math.pi))
            b.memory.event(name, 'hunted_together', now)
            return
    allies = set(b.memory.allies(0.25, now))
    for m in w.npcs.values():
        if m is n or m.bot is None or not m.alive or m.bot.company != b.company or m.bot.name not in allies:
            continue
        if math.hypot(*(a - c for a, c in zip(m.mover.pos(now), (nx, ny)))) < ESCORT_RANGE and random.random() < 0.3:
            n.escort = (m.id, now + duration, random.uniform(0, 2 * math.pi))
            return


def escort(w, n, now):
    """Escort: the leader's target (the alien you selected or the friend bot's target) if strong enough; with no target it flies beside the
    leader, in its own place (formation) -> did it do work in this thought."""
    leader = _leader(w, n, now)
    if leader is None:
        n.__dict__.pop('escort', None)
        return False
    if n.target is None:
        t = w.target if leader[0] == 'h' else leader[1].target
        m = w.npcs.get(t) if t is not None else None
        if m is not None and m.alive and m.bot is None and not m.d.get('friendly') and can_kill(n.bot, m):
            n.target = m.id
            return False                                 # the normal flow handles approaching the target
    if n.target is not None:
        return False
    lx, ly = w.hero_pos(now) if leader[0] == 'h' else leader[1].mover.pos(now)
    a = n.escort[2]
    hx, hy = lx + math.cos(a) * 280, ly + math.sin(a) * 280
    nx, ny = n.mover.pos(now)
    if math.hypot(hx - nx, hy - ny) > 200:
        _go_to(w, n, hx, hy, now, threshold=120)
    return True


def is_boss(m):
    name = str(m.d.get('name', ''))
    return m.bot is None and ('Boss' in name or 'Uber' in name or bool(m.d.get('boss')))


def witness(w, kind, x, y, exclude=None, **f):
    """An event seen on the map (boss died, player died): at most two of the bots within 1,500 units react in chat, depending on talkativeness
    (event 'witness'; templates speech.py, language model in Advanced mode)."""
    count = 0
    for m in list(w.npcs.values()):
        if m.bot is None or not m.alive or m.id == exclude or count >= 2:
            continue
        mx, my = m.mover.pos(time.time())
        if math.hypot(mx - x, my - y) > 1500 or random.random() > 0.35 * m.bot.o('talkativeness'):
            continue
        m.bot.event('witness', sub=kind, **f)
        count += 1


def collect_box(w, n, now):
    """Flies to a nearby box and takes it (like real players; the box also disappears from the player's screen) -> is it busy with this.
    A bonus box (a new one spawns in its place), its own cargo box (ores to the cargo), and rude bots now and then take someone else's (permission
    'box_stealing'; if from the same company it loses honor, like a player). It does not touch loot that dropped for only one person in a group (owner)."""
    if n.target is not None and n.target in w.npcs:
        return False
    b = n.bot
    nx, ny = n.mover.pos(now)
    own = ('b', n.id)
    decision = n.__dict__.setdefault('stealing', {})
    en, best_score = None, 900.0 * PL.box_factor(b) ** 0.7       # a box hunter sees boxes from far away (playstyle.py)
    for h, k in w.boxes.items():
        tip = k.get('tip')
        if k.get('event'):                                 # event box: keyless, everyone collects
            if not b.permission.get('event', True) or k.get('owner') is not None:
                continue
        elif k.get('keyed'):                          # keyed loot box: if it has the key or picks up the green key
            from . import loot as LT
            k_ = decision.get(h)
            if k_ is None or (k_ is not True and now > k_):         # the "cannot open" decision is retried every 60 s (the key may have come)
                decision[h] = True if tip in LT.LOOT.BOXES and LT.can_open(b, tip) else now + 60
            if decision[h] is not True:
                continue
        elif k.get('owner') is not None or (tip != 'BONUS_BOX' and tip not in WD.CARGO_BOXES):
            continue
        if tip in WD.CARGO_BOXES and (not b.permission.get('cargo', True) or b.cargo_fill() >= 1):
            continue                                   # cargo off or full
        owner_tag = k.get('owner_tag')
        if tip in WD.CARGO_BOXES and owner_tag is not None and tuple(owner_tag) != own and WD.SET.get('cargo_ownership'):
            if h not in decision:                         # someone else's cargo: a rude bot takes it now and then (one decision per box)
                decision[h] = is_theft(w, b, owner_tag)
            if not decision[h]:
                continue
        dd = math.hypot(k['x'] - nx, k['y'] - ny)
        if dd < best_score:
            en, best_score = h, dd
    if en is None:
        return False
    k = w.boxes[en]
    if best_score > 60:
        _go_to(w, n, k['x'], k['y'], now, threshold=40)
        return True
    if k.get('event'):
        from . import events as EV
        del w.boxes[en]
        w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
        decision.pop(en, None)
        if k['event'].get('renew_sec'):
            w.schedule(random.uniform(*k['event']['renew_sec']) * WD.SET.multiplier('box_respawn'), 'event_box', k['tip'])
        EV.open_box(b, k['event'])
        n.next_think = now + random.uniform(0.3, 1.0)
        return True
    if k.get('keyed'):                               # opening takes loot.OPEN_SEC (like the player), then the box is taken
        from . import loot as LT
        opening = getattr(n, 'opening', None)
        if not opening or opening[0] != en:
            n.opening = (en, now + LT.LOOT.OPEN_SEC)
            return True
        if now < opening[1]:
            return True
        n.opening = None
        del w.boxes[en]
        w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
        decision.pop(en, None)
        w.schedule(LT.LOOT.respawn_delay(k['tip']) * WD.SET.multiplier('box_respawn'), 'booty', k['tip'])
        LT.open_box(b, k['tip'])
        n.next_think = now + random.uniform(0.3, 1.0)
        return True
    if k['tip'] in WD.CARGO_BOXES:                     # ores as many as fit; what does not fit stays in the box (like the player)
        claimed = b.add_cargo(k.get('contents') or {}, refine=True)
        remaining = {t: int(v) - claimed.get(int(t), 0) for t, v in (k.get('contents') or {}).items() if int(v) - claimed.get(int(t), 0) > 0}
        b.ist('cargo_box')
        owner_tag = k.get('owner_tag')
        if owner_tag is not None and tuple(owner_tag) != own and not k.get('stolen') and WD.SET.get('cargo_ownership'):
            k['stolen'] = True
            theft_penalty(w, b, owner_tag)
        if remaining:
            k['contents'] = remaining
            n.next_think = now + random.uniform(0.3, 1.0)
            return True
    del w.boxes[en]
    w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
    decision.pop(en, None)
    if k['tip'] == 'BONUS_BOX':
        w.schedule(random.uniform(30, 60), 'bonus')
        b.reward('box', ep=random.randint(0, 100), credits=random.choice((0, 0, 100, 500, 1000)), uridium=random.choice((0, 0, 10, 20, 50, 100)))
        b.ist('box')
    n.next_think = now + random.uniform(0.3, 1.0)
    return True


def _box_company(w, owner_tag):
    return w.p.d['pilot'].get('factionId') if owner_tag[0] == 'h' and owner_tag[1] == w.hid else bot_company(owner_tag[1]) if owner_tag[0] == 'b' else None


def _stolen_today(b):
    """The bot's cargo-taking counter for today {day, n} (the first penalty of the day is 10, doubling each time)."""
    d = b.k.setdefault('cargo_theft', {})
    day = time.strftime('%Y-%m-%d', time.localtime(b.hour()))
    if d.get('day') != day:
        d.update(day=day, n=0)
    return d


def is_theft(w, b, owner_tag):
    """Does it take someone else's cargo box. The enemy company's is without penalty: a rude bot takes it now and then. Its own company's costs honor
    (10 that day, doubling each time): a real player knows this, reaches out rarely and at most once a day. Before, the bot rolled a die for every box;
    on a crowded map it took dozens of boxes a day and dropped its honor to hundreds of thousands negative (user 2026-10-30)."""
    from . import admin_warnings as AW
    if not b.permission.get('box_stealing', True) or AW.active(b, 'box'):
        return False                                     # the manager's box warning (bot/admin_warnings.py)
    p = 0.35 * b.o('aggression') * (1 - b.o('helpfulness'))
    if _box_company(w, owner_tag) == b.company:
        if _stolen_today(b)['n'] >= 1:
            return False                               # got a penalty once today: does not take again
        p *= 0.15
    return random.random() < p


def theft_penalty(w, b, owner_tag):
    """The bot took someone else's cargo box: honor loss if the owner is from the same company (same rule as the player: 10 that day, x2 each time);
    if the owner is the player, the bot does not get worse in their eyes but the player loses their box."""
    fac = _box_company(w, owner_tag)
    b.ist('box_stolen')
    if fac != b.company:
        return
    d = _stolen_today(b)
    b.earn(honor=-10 * 2 ** min(d['n'], 16))
    d['n'] += 1
    if owner_tag[0] == 'b':
        o = _bot(owner_tag[1])
        if o is not None:
            o.memory.event(b.name, 'insult', b.hour(), multiplier=0.5)


def recover(w, n, now, d):
    """Damaged but nobody is hitting: leaves the hunt and stops, waits until the shield and repair robot are full (if near its own base it
    withdraws to the station) -> is it waiting. A real player does not dive at a new alien with half HP."""
    ratio = (n.hp + n.shield) / max(1, d['hp'] + d['shield'])
    b = n.bot
    if getattr(n, 'recovering', False):
        if ratio >= 0.9:
            n.recovering = False
            return False
    elif ratio >= 0.3 + 0.3 * (1 - b.o('risk')):
        return False
    n.recovering = True
    n.target = None
    s = w.station
    nx, ny = n.mover.pos(now)
    if s and s.get('type') == b.company and math.hypot(s['posX'] - nx, s['posY'] - ny) < 4000:
        rest(w, n, now)
        return True
    _stop(w, n, now)
    n.next_think = now + random.uniform(2, 4)
    return True


def park_spot(w, n, now):
    """A place to rest, varied among bots (user request: not all standing in the same spot of the station): a wide ring around its own station,
    a portal's safe zone, or where it is (in the middle of the map "afk"). Not closer than 300 units to the other bots' parking
    spots."""
    b = n.bot
    s = w.station
    nx, ny = n.mover.pos(now)
    full = [getattr(m, 'park', None) for m in w.npcs.values() if m.bot is not None and m is not n]
    full = [p for p in full if p is not None]
    portals = [g for g in H.gates(w.map_id, b.company) if not g.get('fee') and math.hypot(g['x'] - nx, g['y'] - ny) < 6000]
    for _ in range(12):
        k = random.random()
        if s and s.get('type') == b.company and k < 0.5:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(350, 1700)
            p = (s['posX'] + math.cos(a) * r, s['posY'] + math.sin(a) * r)
        elif portals and k < 0.75:
            g = random.choice(portals)
            a, r = random.uniform(0, 2 * math.pi), random.uniform(150, 650)
            p = (g['x'] + math.cos(a) * r, g['y'] + math.sin(a) * r)
        else:
            p = (nx + random.uniform(-200, 200), ny + random.uniform(-200, 200))
        p = (max(400, min(w.map_w - 400, p[0])), max(400, min(w.map_h - 400, p[1])))
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 300 for q in full):
            return p
    return p


def rest(w, n, now):
    """Rest: parks somewhere around its own station and stays there ("afk", chat, shopping); relocates now and then at long intervals.
    The parking spot is chosen once (before, picking a new random point every second drew a zigzag around the station)."""
    b = n.bot
    s = w.station
    nx, ny = n.mover.pos(now)
    park = getattr(n, 'park', None)
    if park is None or now > getattr(n, 'park_end', 0):
        park = park_spot(w, n, now)
        n.park, n.park_end = park, now + random.uniform(90, 400)
    if math.hypot(park[0] - nx, park[1] - ny) > 60:
        _go_to(w, n, park[0], park[1], now, threshold=100)
    else:
        n.next_think = now + random.uniform(3, 8)        # duruyor
