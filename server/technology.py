"""Technology items (the shortcut bar's tech_items category): Energy Leech, Chain Impulse, Precision Targeter, Backup Shield 1/2,
Battle Repair Bot 1/2, Explosive Charging Blob, Burning Trail, NPC Nuke, Anti-AI Emergency Reserves, Frost Field, Anti-Mine
Transmitter, Speed Burst, Versus Laser Overdrive. Data items.json "technology" (wiki: belgeler/wiki/extras_cpu_tech.md); counts in the profile
"technology" (come with the Assembly: roadmap Stage 5), duration and cooldowns in "technology_state" (persist when the map changes).

Client (1.1.114, research: the client's code):
  - a click sends MenuActionRequest {menuItemId tech_…, actionType 0 (timer item)}; TechActivationRequest is never sent,
    TechActivationCommand/TechStatusCommand are not handled.
  - one MenuItemTimerCommand per timer item (no cooldown group): READY 0, ACTIVE 1, COOLING_DOWN 2.
  - visuals: VisualModifierCommand {userId, modifier, activated} (ELA 59, BRB 60, BRB2 61, ECB 73: explosion on closing, SB 95,
    AMT 96, AAER 100, FRF 102); Backup Shield 0|n|A|S|SBU(2)|uid; Chain Impulse 0|n|ECI|1|attacker|target…; Burning Trail
    0|n|BT|uid and NPC Nuke 0|n|NNK|uid: a shock wave on that unit.
"""
import json, math, os, time

from legacy_protocol import legacy, stm
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
T = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))['technology']
ITEMS = T['items']
READY, ACTIVE, COOLING = 0, 1, 2
ATTACK_ROCKET, ATTACK_ECI = 0, 5            # the client's AttackType


def mod(name, **f):
    f['_'] = name
    return f


def used_msg(code):
    """Used notification, on screen and in the log (client resource.json tech_used_<CODE>, e.g. "NPC Nuke used"). The resource.json
    keys are resolved only by the old protocol's 0|A|STM|key message: MessageCommand (type 5 flashres, 3-7 item) cannot find them and
    shows nothing (live test 2026-10-26)."""
    return stm('tech_used_' + code)


def count(p, item):
    return p.d.get('technology', {}).get(item, 0)


def add(p, item, n=1):
    """Assembly (Stage 5) and tests: add count -> new count."""
    with p.lock:
        d = p.d.setdefault('technology', {})
        d[item] = max(0, d.get(item, 0) + n)
        p.dirty = True
        return d[item]


def state(p):
    return p.d.setdefault('technology_state', {})


def is_active(p, item, now=None):
    return (now or time.time()) < state(p).get(item, {}).get('end_time', 0)


def timer_fields(p, item, now=None):
    now = now or time.time()
    s = state(p).get(item, {})
    if now < s.get('end_time', 0):
        return dict(activatable=False, timerState=ACTIVE, maxTime=s.get('duration_ms', 0), time=int((s['end_time'] - now) * 1000))
    if now < s.get('ready', 0):
        return dict(activatable=False, timerState=COOLING, maxTime=s.get('cooldown_ms', 0), time=int((s['ready'] - now) * 1000))
    return dict(activatable=True, timerState=READY, maxTime=0, time=0)


def timer_msg(p, item, now=None):
    f = timer_fields(p, item, now)
    return ('MenuItemTimerCommand', dict(activatable=f['activatable'], timerState=mod('TimerStateModule', timerStateValue=f['timerState']),
                                         menuItemId=item, maxTime=f['maxTime'], time=f['time']))


def menu_status(p, item, st):
    """Visible if owned, the count on the counter (when not in the save: ttip_visit_tech_factory / ttip_tech_not_owned)."""
    if item not in ITEMS:
        return None
    n = count(p, item)
    if n <= 0:
        st.update(visible=False, available=False, activatable=False, counterValue=0)
        return st
    maps = ITEMS[item].get('map_only')
    usable = not maps or str(p.d['position'].get('mapId', 0)) in map(str, maps)        # Versus Laser Overdrive: only on the Vortex of Greed map
    usable = usable and not echoes_map(p.d['position'].get('mapId', 0))              # forum 177095: no technology in Echoes
    lines = [{'_': 'MessageKeyListWildcardModule', 'baseKey': item, 'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 3},
              'textStyle': 0, 'wildCardReplacements': []},
             {'_': 'MessageKeyListWildcardModule', 'baseKey': 'ttip_count', 'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 5},
              'textStyle': 0, 'wildCardReplacements': [
                  {'_': 'MessageWildcardReplacementModule', 'wildcard': '%COUNT%', 'replacement': str(n),
                   'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': 0}}]}]
    for k in ('toolTipSlotBar', 'toolTipItemBar'):
        st[k] = {'_': 'MessageKeyListWildcardCommand', 'commandList': json.loads(json.dumps(lines))}
    st.update(visible=True, available=usable, activatable=usable and timer_fields(p, item)['activatable'], counterValue=n,
              counterStyle=0)
    return st


def echoes_map(map_id):
    """Echoes in the Depths of Space maps and hall: technology items cannot be used (official forum 177095)."""
    import echoes as EC
    return int(map_id or 0) in set(EC.D['maps']) | {EC.D['hall']}


class Technology:
    def __init__(self, world):
        self.w, self.p = world, world.p
        self.ending = {}           # timed active item -> end
        self.waiting = {}          # one on cooldown -> ready moment (READY notification)
        self.next_tick = 0.0
        self.charges = []          # Burning Trail charges: {x, y, end}
        self.trail_n = 0           # elapsed seconds of Burning Trail (a charge every interval_sec)
        self.nuke = None           # NPC Nuke: {next, remaining}
        self.started = False
        now = time.time()
        for item, s in state(self.p).items():
            maps = ITEMS.get(item, {}).get('map_only')
            if maps and now < s.get('end_time', 0) and str(world.map_id) not in map(str, maps):
                s['end_time'] = now                       # Versus Laser Overdrive: when the ship leaves the Vortex of Greed the effect is cleared (cooldown continues)
                self.p.dirty = True
            if now < s.get('end_time', 0):
                self.ending[item] = s['end_time']
                if item == 'tech_npc-nuke':            # when the map changes the remaining hits continue (hits every interval_sec from the start)
                    c = ITEMS[item]
                    start, total = s['end_time'] - c['duration_sec'], int(c['duration_sec'] // c['interval_sec'])
                    done = min(total, max(0, int((now - start) // c['interval_sec'])))
                    self.nuke = dict(next=start + (done + 1) * c['interval_sec'], remaining=total - done)
            elif now < s.get('ready', 0):
                self.waiting[item] = s['ready']

    def send(self, msgs):
        if msgs:
            self.w.send(msgs)

    def visual(self, item, on):
        g = ITEMS[item].get('visual')
        return [('VisualModifierCommand', dict(userId=self.w.hid, modifier=g, attribute=0, additionalAttribute='', count=0,
                                               activated=on))] if g else []

    def status(self, item):
        st = self.p.menu_status(item)
        return [('MenuItemStatusCommand', st)] if st else []

    # ------------------------------------------------------------ queries (world.py, combat_items.py)
    def active(self, item, now=None):
        return item in self.ending and is_active(self.p, item, now)

    def full_rocket_hit(self, now=None):
        return self.active('tech_precision-targeter', now)

    def hp_floor(self, now=None):
        """Anti-AI Emergency Reserves: alien damage cannot bring HP below this (0 if none)."""
        return ITEMS['tech_anti-ai-emergency-reserves']['min_hp'] if self.active('tech_anti-ai-emergency-reserves', now) else 0

    def mine_protected(self, now=None):
        return self.active('tech_anti-mine-transmitter', now)

    def laser_bonus(self, now=None):
        """Versus Laser Overdrive: while active, flat damage added to each laser's base damage (0 if none)."""
        return ITEMS['tech_versus-laser-overdrive']['base_laser'] if self.active('tech_versus-laser-overdrive', now) else 0

    def leech(self, ammo, dmg):
        """Energy Leech: 10% of the damage dealt with ordinary laser ammo goes to HP."""
        if dmg <= 0 or ammo not in T['ammo_types'] or not self.active('tech_energy-leech'):
            return
        g = self.p.d['ship']
        if g.get('hitPoints', 0) >= g.get('hitMax', 0):
            return
        self.p.set_hull(hp=g.get('hitPoints', 0) + dmg * ITEMS['tech_energy-leech']['laser_hp'])
        self.send([self.w.hp_msg()])

    # ------------------------------------------------------------ activation
    def activate(self, item, now=None):
        """MenuActionRequest tech_…: if owned and ready -> True."""
        w, p = self.w, self.p
        now = now or time.time()
        c = ITEMS.get(item)
        if not c or count(p, item) <= 0 or w.hero_dead or w.jumping or echoes_map(w.map_id) or                 (c.get('map_only') and str(w.map_id) not in map(str, c['map_only'])):
            w.log('   technology unavailable: %s' % item)
            return False
        if is_active(p, item, now) or now < state(p).get(item, {}).get('ready', 0):
            self.send([timer_msg(p, item, now)])
            return False
        msgs = self.start(item, c, now)
        if msgs is None:
            w.log('   technology useless right now: %s' % item)
            return False
        if not SET.get('infinite_technology'):          # panel: infinite tech (not used up; at least one still needed)
            add(p, item, -1)
        p.ach('spend', loot=item, count=1)           # Quests/Pass "use an item": counted with or without infinite tech
        sec, cd = c.get('duration_sec', 0), c.get('cooldown_sec', 0) * SET.multiplier('skill_cooldown', 'technology')      # panel
        with p.lock:
            state(p)[item] = dict(end_time=now + sec, ready=now + sec + cd, duration_ms=int(sec * 1000), cooldown_ms=int(cd * 1000))
            p.dirty = True
        if sec:
            self.ending[item] = now + sec
        else:
            self.waiting[item] = now + cd
        self.send(msgs + [timer_msg(p, item, now)] + self.status(item))
        w.log('   technology: %s (%d left)' % (item, count(p, item)))
        return True

    def start(self, item, c, now):
        """The item's initial effect -> messages, or None (cannot be used now: no target, shield full …)."""
        w, p = self.w, self.p
        g = p.d['ship']
        hx, hy = w.hero_pos(now)
        if 'shield' in c:                                               # Backup Shield
            if g.get('shield', 0) >= g.get('shieldMax', 0):
                return None
            sh0 = g.get('shield', 0)
            p.set_hull(shield=sh0 + c['shield'])
            return [legacy('0|n|A|S|%s|%d' % (c['old'], w.hid)),
                    ('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})] + w.heal_msgs(sh0=sh0)
        if item == 'tech_chain-impulse':
            near = sorted(((math.hypot(nx - hx, ny - hy), n) for n in w.npcs.values() if n.alive
                           for nx, ny in [n.mover.pos(now)]), key=lambda t: t[0])
            targets = [n for d, n in near if d <= c['radius']][:c['target']]
            if not targets:
                return None
            msg = legacy('0|n|ECI|1|%d|%s' % (w.hid, '|'.join(str(n.id) for n in targets)))
            def strike():
                for n in targets:
                    w.hit_npc(n.id, c['damage'], ATTACK_ECI, shield_only=True)      # client: "chain reaction of shield damage"
                    if not n.alive:
                        p.ach('chain_kill')                 # achievement ChainImpulse
            w.later(0.3, strike)
            w.last_combat = now
            return [msg]
        if item == 'tech_npc-nuke':
            # client: "burst of damage to NPCs in an area around your ship once every 10 seconds": no target needed, sure_sn / interval_sec hits
            # to all aliens around the ship (nuke_tick)
            self.nuke = dict(next=now + c['interval_sec'], remaining=int(c['duration_sec'] // c['interval_sec']))
            return [used_msg('NNK')]
        if item == 'tech_speed-burst':
            w.hero_effect('speed_up', c['duration_sec'], c['speed'], source=item)
        if item == 'tech_burning-trail':
            self.charges, self.trail_n = [], 0
        return self.visual(item, True)

    # ------------------------------------------------------------ loop
    def tick(self, now):
        w, p = self.w, self.p
        if not self.started:
            self.started = True                    # visuals that persist across a map change again
            self.send(sum((self.visual(i, True) for i in self.ending), []))
        for item, until in list(self.waiting.items()):
            if now >= until:
                del self.waiting[item]
                self.send([timer_msg(p, item, now)] + self.status(item))
        self.trail_tick(now)
        if now >= self.next_tick:
            self.next_tick = now + 1.0
            for item in list(self.ending):
                if now < self.ending[item]:
                    self.second(item, ITEMS[item], now)
        self.nuke_tick(now)
        for item, until in list(self.ending.items()):
            if now >= until:
                self.finish(item, now)

    def second(self, item, c, now):
        """Effects that run every second: Battle Repair Bot, Frost Field, Burning Trail charge."""
        w, p = self.w, self.p
        g = p.d['ship']
        if 'hp_sec' in c and not w.hero_dead:
            hp0, sh0 = g.get('hitPoints', 0), g.get('shield', 0)
            p.set_hull(hp=hp0 + c['hp_sec'], shield=sh0 + c.get('shield_per_sec', 0))
            msgs = [w.hp_msg()]
            if c.get('shield_per_sec'):
                msgs.append(('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)}))
            self.send(msgs + w.heal_msgs(hp0, sh0 if c.get('shield_per_sec') else None))
        if item == 'tech_frost-field':
            hx, hy = w.hero_pos(now)
            for n in list(w.npcs.values()):
                nx, ny = n.mover.pos(now)
                if n.alive and math.hypot(nx - hx, ny - hy) <= c['radius']:
                    w.npc_effect(n, 'slow', 1.5, c['slow'], source=item)
                    w.hit_npc(n.id, c['damage_per_sec'], 1)
        if item == 'tech_burning-trail':
            if self.trail_n % c['interval_sec'] == 0:
                x, y = w.hero_pos(now)
                self.charges.append(dict(x=x, y=y, end_time=now + c['lifetime_sec']))
            self.trail_n += 1

    def trail_tick(self, now):
        if not self.charges:
            return
        w, c = self.w, ITEMS['tech_burning-trail']
        for ch in list(self.charges):
            if now >= ch['end_time']:
                self.charges.remove(ch)
                continue
            n = next((n for n in w.npcs.values() if n.alive
                      and math.hypot(n.mover.pos(now)[0] - ch['x'], n.mover.pos(now)[1] - ch['y']) <= c['trigger']), None)
            if n:
                self.charges.remove(ch)
                self.send([legacy('0|n|BT|%d' % n.id)])
                w.hit_npc(n.id, c['damage'], ATTACK_ROCKET)

    def nuke_tick(self, now):
        """NPC Nuke: every interval_sec, damage to all aliens around the ship (yaricap); the shock wave is on the ship's id.
        Hits are counted (6 x 100,000): the last hit falls at the same moment as the end of the duration, a tick delay does not lose it."""
        nk = self.nuke
        if not nk:
            return
        w, c = self.w, ITEMS['tech_npc-nuke']
        while nk['remaining'] > 0 and now >= nk['next']:
            nk['next'] += c['interval_sec']
            nk['remaining'] -= 1
            hx, hy = w.hero_pos(now)
            hits = [n.id for n in w.npcs.values()
                    if n.alive and math.hypot(n.mover.pos(now)[0] - hx, n.mover.pos(now)[1] - hy) <= c['radius']]
            self.send([legacy('0|n|NNK|%d' % w.hid)])
            w.last_combat = now
            for uid in hits:
                w.hit_npc(uid, c['damage'], ATTACK_ROCKET)
        if nk['remaining'] <= 0:
            self.nuke = None

    def finish(self, item, now, frac=1.0):
        """Duration ended (or the ship was destroyed): the visual is removed, cooldown starts. Explosive Charging Blob explodes."""
        self.ending.pop(item, None)
        w, p, c = self.w, self.p, ITEMS[item]
        if item == 'tech_explosive-charging-blob':
            lo, hi = c['damage']
            dmg = int(lo + (hi - lo) * max(0.0, min(1.0, frac)))
            hx, hy = w.hero_pos(now)
            for n in list(w.npcs.values()):
                nx, ny = n.mover.pos(now)
                if n.alive and math.hypot(nx - hx, ny - hy) <= c['radius']:
                    w.hit_npc(n.id, dmg, ATTACK_ROCKET)
            w.log('   Explosive Charging Blob exploded: %d' % dmg)
        if item == 'tech_npc-nuke':
            self.nuke = None
        s = state(p).get(item, {})
        self.waiting[item] = s.get('ready', now)
        self.send(self.visual(item, False) + [timer_msg(p, item, now)])

    def on_death(self):
        """Ship destroyed: running effects end (the blob explodes with its current charge), cooldowns remain."""
        now = time.time()
        for item in list(self.ending):
            s = state(self.p).get(item, {})
            sec = s.get('duration_ms', 0) / 1000.0
            frac = 1 - (s.get('end_time', now) - now) / sec if sec else 1.0
            left = s.get('end_time', now) - now
            with self.p.lock:
                s['end_time'] = now
                s['ready'] = s.get('ready', now) - max(0.0, left)
            self.finish(item, now, frac)
        self.charges = []
