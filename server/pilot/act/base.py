"""Auto Mode: the basic World adapter (reading the map, moving, firing, collecting). The act/ package is the only place that reads or drives
world.World and the session's systems (so a change elsewhere in the server breaks the bot in one place). Called under the world lock (the
bot's loop runs as a World timer).

Movement, two modes (pilot.json move_mode):
  hero_move  HeroMoveCommand {x, y} (group "Follow" uses it, group.py): the client flies its own ship there and sends a normal MoveRequest,
             so the server's position, the save and the other players on a shared map follow the usual path (game.py MoveRequest -> World.on_move).
  server     the server moves the ship (World.respeed_flight's pattern): Mover.go + MoveCommand for the hero's own id; the saved position and the
             players who see the ship on a shared map are updated here.
"""
import math, time

import autopilot as AP
import map_layout as ML
import map_links as H
import settings as SET
import world as W

MOVE_EVERY = 0.6              # at most one move order per 0.6 s (the client's own autopilot uses the same throttle)
SAME_POINT = 50               # a new order closer than this to the last one while still flying there is not sent
OWN_MOVE_SEC = 6.0            # a MoveRequest to one of our destinations within this time is ours (hero_move), not the player's click
OWN_MOVE_DIST = 90
ON_TOP = 40                   # a box / ore this close is under the ship
RADIATION_REACH = 600         # how far past the map's edge a radiation quest may take the ship


class Base:
    def __init__(self, world, mode, session=None):
        self.w = world
        self.session = session
        self.p = world.p
        self.mode = mode
        self.last_move = 0.0
        self.sent = []                                # [(x, y, time)] destinations ordered recently
        self.tried = {}                               # Combat: item -> when it last refused
        self.last_jump_try = 0.0                      # Travel: the last jump asked
        self.portal_goal = self.route_goal = None     # Travel: the portal / route of the last order (Travel.heading, the panel's map)

    # ------------------------------------------------------------ reading
    def snapshot(self, now, cfg):
        w = self.w
        hx, hy = w.hero_pos(now)
        g = w.p.d['ship']
        npcs = []
        ammo = self.laser_ammo()
        hunted, forbid = self.hunted(cfg), cfg.get('forbid') or ()
        for n in w.npcs.values():
            if not self.visible_alien(n):
                continue
            x, y = n.mover.pos(now)
            px, py = n.mover.pos(now + 0.6)
            passive = getattr(n, 'passive', False)
            npcs.append(dict(
                id=n.id, tip=n.tip, name=n.d.get('name', n.tip), x=x, y=y, px=px, py=py,
                engaged=bool(n.engaged) and not passive, aggressive=w.aggressive(n) and not passive,
                notice=n.d.get('notice_distance', W.COMBAT['npc_notice_distance']) * SET.multiplier('npc_notice'),
                fire_range=w.npc_range(n), hp=n.hp, hp_max=n.d.get('hp', 1), shield=getattr(n, 'shield', 0), shield_max=n.d.get('shield', 0),
                ok=self.attackable(n, now, ammo), forbidden=n.tip in forbid,
                allowed=hunted(n),
                priority=n.tip in (cfg.get('priority') or ())))
        if cfg.get('pvp') is not None:                        # a PvP quest: the enemy-company pilots are the targets (act/players.py)
            npcs += self.pvp_targets(now, cfg['pvp'])
        cargo_room = w.p.cargo_free() >= 1
        boxes = []
        steal = cfg.get('steal')
        for h, b in w.boxes.items():
            tag = b.get('owner_tag')
            stolen = steal and tag is not None and not w.own_tag(tag) and b.get('tip') in self.cargo_box_types()    # a steal quest
            if (not w.own(b) and not stolen) or b.get('keyed'):
                continue
            tip = b.get('tip')
            if b.get('event'):
                kind = 'event'
            elif tip == 'BONUS_BOX':
                kind = 'bonus'
            elif tip in self.cargo_box_types() and cargo_room and (stolen or not SET.get('cargo_ownership') or w.own_tag(b.get('owner_tag'))):
                kind = 'cargo'
            else:
                continue
            boxes.append(dict(hash=h, x=b['x'], y=b['y'], kind=kind))
        safe = []
        s = w.home_station()
        if s:
            safe.append((s['posX'], s['posY'], s['peaceRadius']))
        r = ML.gate_peace_radius(w.map_id, H.GATE_PEACE_RADIUS)
        safe += [(gt['x'], gt['y'], r) for gt in w.peace_gates()]
        safe += [tuple(z) for z in ML.safe_zones(w.map_id)]
        ores = [dict(hash=h, tip=o['tip'], x=o['x'], y=o['y']) for h, o in w.ores.items() if not o.get('busy')]
        return dict(hero=(hx, hy), R=w.laser_range(), hp=g.get('hitPoints', 0), hp_max=g.get('hitMax', 0), shield=g.get('shield', 0),
                    shield_max=g.get('shieldMax', 0), bounds=(w.map_w, w.map_h), map=int(w.map_id),
                    in_peace=w.in_peace(hx, hy), npcs=npcs, boxes=boxes, safe=safe, ores=ores)

    def hunted(self, cfg):
        """-> whether an alien is a target of the hunt (cfg: Pilot.hunt_cfg): the mode hunts, the map's list (empty: all; in a galaxy
        gate every wave alien), never one an active quest forbids."""
        gate, aliens, forbid = bool(self.w.gate) or bool(getattr(self.w, 'low', None)), cfg['aliens'], cfg.get('forbid') or ()     # LoW too
        hunting = cfg.get('hunting', True) and cfg.get('pvp') is None            # a PvP quest hunts pilots, not aliens
        return lambda n: hunting and (not aliens or n.tip in aliens or gate) and n.tip not in forbid

    @staticmethod
    def visible_alien(n):
        """An alien of the map (not a player bot, not friendly, not hidden) still alive."""
        return n.bot is None and n.alive and not n.d.get('friendly') and not getattr(n, 'hidden', False)

    @staticmethod
    def cargo_box_types():
        return W.CARGO_BOXES

    def attackable(self, n, now, ammo):
        """The ship's lasers can hurt it now and it is the hero's to take: not immune, not tagged by someone else, not fighting a player bot."""
        w = self.w
        return (not self.immune(n, now, ammo) and w.own_tag(W.tag_owner(n, now))
                and not (n.bot_target is not None and w.npcs.get(n.bot_target) is not None))

    def immune(self, n, now, ammo):
        """Takes no damage from the ship's lasers now (World.hit_npc's rules): its own protection, a status effect, guarded by its summons
        (Battleray's Interceptors), or hit only by another ammo."""
        only = n.d.get('ammo_only')
        return bool((n.invulnerable and n.invulnerable()) or n.effect.invulnerable(now) or self.w.guarded(n) or (only and ammo not in only))

    def busy(self):
        """Why the bot cannot act now (a reason key) or None."""
        w = self.w
        if w.hero_dead:
            return 'dead'
        if w.jumping or w.reload_pending:
            return 'jumping'
        return None

    def client_autopilot(self):
        """The client's own AutoTactic is flying the ship."""
        return self.p.d.get('autopilot', {}).get('state') == AP.START

    def flying(self, now):
        """The ship is still flying to the last point ordered."""
        return bool(self.sent) and self.w.hero.t1 > now

    def hero_pos(self, now):
        return self.w.hero_pos(now)

    def target_hp(self, uid):
        """The alien's HP + shield (whether the bot is hurting it), None if gone."""
        n = self.w.npcs.get(uid)
        return n.hp + getattr(n, 'shield', 0) if n is not None and n.alive else None

    def box_there(self, h):
        return h in self.w.boxes

    def target_alive(self, uid):
        n = self.w.npcs.get(uid)
        return n is not None and n.alive

    def attacking(self, uid):
        return self.w.attacking and self.w.target == uid

    def player_target(self):
        """The alien the player selected and is attacking by hand, or None."""
        w = self.w
        return w.target if w.attacking and w.target in w.npcs else None

    # ------------------------------------------------------------ moving
    def move_to(self, x, y, now=None, outside=False):
        """outside: the point may be beyond the map's edge (the radiation zone, for a quest that asks for it)."""
        now = time.time() if now is None else now
        w = self.w
        lo = -RADIATION_REACH if outside else 0
        x = max(lo, min(w.map_w - lo, int(x)))
        y = max(lo, min(w.map_h - lo, int(y)))
        if self.sent:
            lx, ly, _ = self.sent[-1]
            hx, hy = w.hero_pos(now)
            if math.hypot(lx - x, ly - y) < SAME_POINT and (w.hero.t1 > now or math.hypot(hx - x, hy - y) < SAME_POINT):
                return False                          # already flying there (or there)
        if now - self.last_move < MOVE_EVERY:
            return False
        speed = w.p.d['ship'].get('speed', 300)
        if self.mode == 'server' and speed <= 0:
            return False
        self.last_move = now
        self.sent = [s for s in self.sent if now - s[2] < OWN_MOVE_SEC][-4:] + [(x, y, now)]
        if self.mode == 'server':
            ms = w.hero.go(x, y, speed, now)
            w.p.d['position'].update(x=x, y=y)
            w.p.dirty = True
            w.send([('MoveCommand', dict(userId=w.hid, x=x, y=y, timeToTarget=ms))])
            if w.shared:
                w.shared.movement(w, x, y, ms)
        else:
            w.send([('HeroMoveCommand', {'x': x, 'y': y})])
        return True

    def ours(self, x, y, now):
        """Whether a MoveRequest to (x, y) answers one of our orders (hero_move) rather than a click of the player."""
        if self.mode == 'server':
            return False
        return any(now - t <= OWN_MOVE_SEC and math.hypot(sx - x, sy - y) <= OWN_MOVE_DIST for sx, sy, t in self.sent)

    # ------------------------------------------------------------ acting
    def attack(self, uid):
        w = self.w
        if w.target != uid:
            w.select({'targetId': uid})
        if not (w.attacking and w.target == uid):
            w.laser_start({'targetId': uid})

    def stop_attack(self):
        if self.w.attacking:
            self.w.laser_stop()

    def arrived(self, x, y, now, reach):
        """The ship is on (x, y): right on it, or sent there and stopped within reach of it (the client's last point can fall a little
        short). A player's click flies the ship onto the object and the client asks for it on arrival; the server itself hands it over
        within its pick-up distance (World.box_near: 250), so asking on the way made the box vanish while the ship was still flying to it
        (user report)."""
        hx, hy = self.w.hero_pos(now)
        d = math.hypot(x - hx, y - hy)
        if d <= ON_TOP:
            return True
        ordered = bool(self.sent) and math.hypot(self.sent[-1][0] - x, self.sent[-1][1] - y) < SAME_POINT    # sent there, now stopped
        return ordered and d <= reach and self.w.hero.t1 <= now

    def collect(self, h, now=None):
        """Fly onto box h and take it once there -> whether it was asked for."""
        now = time.time() if now is None else now
        w = self.w
        b = w.boxes.get(h)
        if b is None:
            return False
        if not self.arrived(b['x'], b['y'], now, W.COMBAT['harvest_distance']):
            self.move_to(b['x'], b['y'], now)
            return False
        if not w.collect_wish or w.collect_wish[0] != h:
            w.collect({'itemHash': h})
        return True

    def set_ammo(self, loot):
        if loot and self.w.p.d['selected'].get('laser') != loot and self.w.p.ammo(loot) > 0:
            self.w.menu_action({'menuItemId': loot, 'actionType': 0})

    def laser_ammo(self):
        return self.w.p.d['selected'].get('laser')

    def ammo_count(self, loot):
        return self.w.p.ammo(loot) if loot else 0

    def has_ammo(self, loot):
        return bool(loot) and self.w.p.ammo(loot) > 0

    def slow_ready(self, loot, now):
        """In stock and its cooldown is over. RSB-75 and RCB-140 share one cooldown group (one shortcut-bar timer, items.json
        cooldown_group), while World.ammo_ready keeps one moment per ammo: wait for every ammo of the group."""
        if not self.has_ammo(loot):
            return False
        ammo = W.ITEMS['laser_ammo']
        grp = ammo.get(loot, {}).get('cooldown_group')
        same = [a for a, c in ammo.items() if c.get('cooldown_group') == grp] if grp else [loot]
        return all(now >= self.w.ammo_ready.get(a, 0) for a in same)

    def slow_fired(self, loot, now):
        """The ammo has fired (its cooldown runs)."""
        return now < self.w.ammo_ready.get(loot, 0)

    def can_repair(self, now):
        w = self.w
        return bool(w.repair_rate()) and now - w.last_combat >= W.ITEMS['repair_cooldown_sec']

    def can_heal(self, now):
        """The ship heals here (the repair robot works now or will once out of combat)."""
        return self.can_repair(now) or bool(self.w.repair_rate())

    def repair(self, now=None):
        """Starts the repair robot if it can work now -> whether it is repairing."""
        now = time.time() if now is None else now
        w = self.w
        if w.repairing:
            return True
        g = w.p.d['ship']
        if g.get('hitPoints', 0) < g.get('hitMax', 0) and self.can_repair(now):
            w.start_repair()
        return w.repairing

    def map_aliens(self):
        """The aliens on the map, by type (the panel's hunt list)."""
        out = {}
        for n in list(self.w.npcs.values()):
            if not self.visible_alien(n):
                continue
            e = out.setdefault(n.tip, dict(tip=n.tip, name=n.d.get('name', n.tip), count=0, aggressive=bool(self.w.aggressive(n))))
            e['count'] += 1
        return sorted(out.values(), key=lambda e: e['name'])

    def wallet(self, now):
        """The In-game pages' top bar (panel gameHeader): credits, uridium, whether equipment can be changed here."""
        pl = self.p.d['pilot']
        return dict(credits=pl.get('credits', 0), uridium=pl.get('uridium', 0), in_station=bool(self.w.in_station(now)))

    def map_name(self, map_id=None):
        return H.name(self.w.map_id if map_id is None else map_id)
