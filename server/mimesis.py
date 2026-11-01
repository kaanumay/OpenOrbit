"""Mimesis Mutiny / Payload Escort (roadmap Ö4; data in data/major_content.json 'mimesis' <- tools/major_content.py).

On the calendar (12-26 March, 12-26 November) the company's Escort map (MMO 433, EIC 436, VRU 430) is entered through the portal at X-1 and X-8 with
an Escort Key. The EM Freighter spawns every full hour (10:00-23:00); it can be entered in the first 5 minutes, and must reach the target in
45 minutes (with the panel's "Seasonal events always open" setting the run starts once entered). The ship advances only while it is inside the
player's protection area (1,200); outside the area is radiation (the reverse RADIATION POI). The route is four points and a beacon: at each point
a Mimesis wave, the ship stops until it is cleared (msg_mutiny_escort_disrupted); on the way an Assailant/Raider now and then. Half of the aliens'
shots go to the ship (Deep Space Echoes' escort pattern). At the beacon a Marker and turrets; once cleared and arrived, 5 s later the ship and
beacon explode, the exit portal opens, the map becomes radiation. Score: kills (the type's score), points (400), arrival (3,000 x the ship's HP
ratio); a run's score is kept even on a failed run. On a successful run the run tier's rewards (1,000-8,000+). Total score is the sum of the best
10 runs; the window's reward tab has ranking bands (RankRewardRequest rankType 5; single player: the player is 1st). If the ship is destroyed or
time runs out the run ends. On death, free repair on the spot (you stay) or return to base (this run cannot be re-entered).
Rewards (wiki aliens / Mimesis Box): when an alien dies, Byte Remnant directly (the type's 'byte'; npc extra_reward), plus from its box; when the box
is collected, with 30% the Mimesis Chest effect (mimesis_chest.py).
Escort Key: once a day "Freighter Protection" (10,000 units of travel inside radiation; the client's quest 500483 is not on the server, adaptation),
by chance from the run's elite Mimesis. At most 100.
Client: PayloadEscortInfoCommand (on login, on state change, entering/leaving the map), PayloadEscortTimeInfoCommand, KeyInfo, ScoreCommand.
In the profile: mimesis {period, trips [score], last (run entered), day, route, key_day}.
"""
import datetime, json, math, os, random, time

import settings as SET
import world as world_module
import event_gate as EKP
import map_links as H
import galaxy_gates as KAPI
import rankings as RK
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'major_content.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('mimesis', {})
EVENT = D.get('event', 'mimesis_mutiny')
MAPS = {int(v): int(k) for k, v in (D.get('maps') or {}).items()}       # map -> company
PORTAL_ID = EKP.PORTAL_BASE + 95                   # the Escort portal at X-1 / X-8
EXIT_ID = EKP.PORTAL_BASE + 96
FREIGHTER = 'mm_freighter'
POI_ZONE = 'payloadEscortProtectionZone'
RANK_TYPE = 5
KEY = D.get('anahtar', 'resource_key_access-escort')
RUN_SEC = 3600
BYTE = 'resource_collectable_byte-remnant'


def _register():
    for k, v in (D.get('kinds') or {}).items():
        t = {x: y for x, y in v.items() if x not in ('points', 'byte')}
        if v.get('byte'):
            t['extra_reward'] = {BYTE: v['byte']}         # wiki aliens: Byte Remnant directly on kill (the one in the box is extra)
        world_module.CFG['types'][k] = t
    g = D.get('ship')
    if g:
        world_module.CFG['types'][FREIGHTER] = dict(name=g['name'], model=g['model'], npc_id=g['npc_id'], hp=g['min_hp'], kalkan=0,
                                              damage=0, speed=g['speed'], aggressive=False, friendly=True, reward={}, cargo={})
    if D.get('ranking'):
        RK.TABLES[RANK_TYPE] = {'ranges': [dict(from_=r['from_'], e=r['e'], items=r['rewards'], title=r.get('title'))
                                              for r in D['ranking']]}


_register()


def active(now=None):
    return EVENT in CAL.active(now)


def always_open():
    return bool(SET.get('session_always_open'))


def run_state(now=None):
    """The run's state -> (key, whether entry is open, time left until entry closes, time left until the next spawn, run end)."""
    now = time.time() if now is None else now
    t = datetime.datetime.fromtimestamp(now)
    if always_open():                                # every entry is a new run (one key)
        return 'hep-%.3f' % now, True, 300 - now % 300, 0, None
    hours = D.get('hours', [])
    base = t.replace(minute=0, second=0, microsecond=0)
    if t.hour in hours:
        a = base.timestamp()
        key = base.strftime('%Y-%m-%d-%H')
        if now < a + D['entry_sec']:
            return key, True, a + D['entry_sec'] - now, 0, a + D['sure_sn']
    for k in range(1, 48):
        nx = base + datetime.timedelta(hours=k)
        if nx.hour in hours:
            return None, False, 0, nx.timestamp() - now, None
    return None, False, 0, 0, None


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Mimesis:
    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.world = None
        self.run = None
        self.change_map = None
        self.titles = None
        self.in_map = False
        self.last_open = None
        self.last_pos = None

    @property
    def st(self):
        d = self.p.d.setdefault('mimesis', {})
        today = datetime.date.today().isoformat()
        if d.get('day') != today:
            d.update(day=today, route=0)
        for k, v in (('trips', []), ('route', 0)):
            d.setdefault(k, v)
        return d

    def total(self):
        return int(sum(sorted(self.st['trips'], reverse=True)[:D.get('best_trip_count', 10)]))

    def keys(self):
        return int(self.p.resource(KEY))

    # ------------------------------------------------------------ window
    def time_cmd(self, now=None):
        key, open_, close_left, next_left, end = run_state(now)
        now = time.time() if now is None else now
        return mod('PayloadEscortTimeInfoCommand', timeToGateClose=int(close_left) if open_ else 0,
                   timeToNextSpawn=int(next_left) if not open_ else 0,
                   timeToSessionEnd=int(end - now) if end else (D['sure_sn'] if open_ else 0))

    def info_cmd(self, in_session=None):
        return ('PayloadEscortInfoCommand', dict(timeInfoCommand=self.time_cmd(), playerRankRanges=RK.ranges(RANK_TYPE),
                                                 totalScore=self.total(), keyInfoCommand=mod('PayloadEscortKeyInfoCommand', keyCount=self.keys()),
                                                 isInSession=bool(self.in_map if in_session is None else in_session)))

    def key_cmd(self):
        return ('PayloadEscortKeyInfoCommand', {'keyCount': self.keys()})

    def login_msgs(self):
        return [self.info_cmd()] if active() else []

    def window(self, item):
        return [self.info_cmd()] if item == 'payload_escort' and active() else []

    # ------------------------------------------------------------ portal
    def my_map(self):
        return next((m for m, f in MAPS.items() if f == self.p.d['pilot'].get('factionId')), None)

    def portals(self, map_id, station):
        if int(map_id) in MAPS or not active() or not station or H.map_class(map_id) not in D.get('entries', ['X-1', 'X-8']) \
                or H.company(map_id) != self.p.d['pilot'].get('factionId'):
            return []
        sx, sy = station['posX'], station['posY']
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2
        x, y = int(sx + (cx - sx) * 0.35), int(sy + (cy - sy) * 0.35 - 1500)
        return [dict(gateId=PORTAL_ID, x=x, y=y, target=0, designId=D.get('portal_design', 1), windowed='mimesis',
                     tooltip=D.get('tooltip', 'ttip_jumpgate_escort'))]

    def portal_window(self, g, w, go):
        key, open_, close_left, next_left, end = run_state()
        if not active():
            return
        if not open_:
            w.send([legacy('0|A|STM|msg_mutiny_escort_closed')])
            return
        if self.st.get('last') == key:
            w.send([legacy('0|A|STM|msg_mutiny_escort_too_late')])
            return
        if self.keys() < 1:
            w.send([legacy('0|A|STM|msg_mutiny_escort_no_key')])
            return
        self.p.add_resource(KEY, -1)
        self.p.ach('spend', loot=KEY, count=1)                      # Pass quests: "Use an Escort Key" (battle_pass.py)
        with self.p.lock:
            self.st['last'] = key
            self.p.dirty = True
        w.send(self.m.resource_msgs(KEY, self.keys(), -1) + [self.key_cmd(), legacy('0|A|STM|resource_key_access-escort_used')])
        self.pending = (key, end)
        x, y = D['route'][0]
        go(self.my_map(), (x - 600, y + 300))

    # ------------------------------------------------------------ world
    def attach(self, world):
        self.world = world
        self.run = None
        msgs = []
        if int(world.map_id) in MAPS and active() and getattr(self, 'pending', None):
            key, end = self.pending
            self.pending = None
            self.run = MmRun(self, world, end)
            world.gate = self.run
            world.ally = self.run
            self.in_map = True
            return [self.info_cmd(True)] + self.run.enter_msgs()
        if int(world.map_id) in MAPS:                       # no run (spawned on this map at login): to base
            import vortex
            vortex.send_home(self, world)
        if self.in_map:
            self.in_map = False
            msgs.append(self.info_cmd(False))
        return msgs

    def on_kill(self, w, npc, x, y):
        if self.run and self.run.w is w:
            return self.run.on_kill(npc, x, y)
        return []

    def tick(self, now):
        if not active(now):
            return self.event_end()
        msgs = []
        if self.st.get('period') is None:
            with self.p.lock:
                self.st['period'] = (CAL.period(EVENT, now) or (now,))[0]
                self.p.dirty = True
        open_ = run_state(now)[1]
        if open_ != self.last_open:
            if self.last_open is not None and open_ and not always_open():
                msgs.append(legacy('0|A|STM|msg_mutiny_escort_spawn_now'))
            self.last_open = open_
            msgs.append(self.info_cmd())
        msgs += self.protection_mission(now)
        return msgs

    def protection_mission(self, now):
        """Daily "Freighter Protection" (adaptation): 10,000 units of travel inside radiation -> 1 Escort Key (once a day)."""
        w = self.world
        st = self.st
        if not w or w.hero_dead or st.get('key_day') == st['day']:
            self.last_pos = None
            return []
        pos = w.hero_pos(now)
        if w.radiation_since is None:
            self.last_pos = None
            return []
        if self.last_pos:
            d = math.hypot(pos[0] - self.last_pos[0], pos[1] - self.last_pos[1])
            if d < 2000:                             # does not count as teleporting
                with self.p.lock:
                    st['route'] += d
                    self.p.dirty = True
        self.last_pos = pos
        if st['route'] < 10000:
            return []
        return self.grant_keys(1, daily=True)

    def grant_keys(self, n, daily=False):
        st = self.st
        have = self.keys()
        n = min(n, D.get('key_max', 100) - have)
        with self.p.lock:
            if daily:
                st['key_day'] = st['day']
            self.p.dirty = True
        if n > 0:
            self.p.add_resource(KEY, n)
        if n <= 0:
            return []
        self.log('   Mimesis Mutiny: +%d Escort Key%s' % (n, ' (Freighter Protection)' if daily else ''))
        return self.m.resource_msgs(KEY, self.keys(), n) + [self.key_cmd(),
                                                             KAPI.screen('Freighter Protection completed: +1 Escort Key' if daily
                                                                         else '+%d Escort Key' % n)]

    def finish_run(self, score, success):
        msgs = []
        with self.p.lock:
            self.st['trips'] = sorted(self.st['trips'] + [int(score)], reverse=True)[:50]
            self.p.dirty = True
        if success:
            row = next((r for r in D['trip_tiers'] if score >= r['from_'] and (r['e'] is None or score <= r['e'])), None)
            if row:
                for loot, n in row['rewards']:
                    msgs += self.m.prize(loot, n)
                msgs.append(KAPI.screen('Escort reward tier: %d+ points' % row['from_'], big=True))
        msgs.append(('PayloadEscortScoreCommand', dict(totalScore=self.total(), runScore=int(score))))
        self.log('   Mimesis Mutiny run finished: %d points (%s), total %d' % (score, 'succeeded' if success else 'failed', self.total()))
        return msgs + self.m.money_msgs()

    def event_end(self):
        st = self.p.d.get('mimesis')
        if not st or st.get('period') is None:
            return []
        msgs = []
        total = sum(sorted(st.get('trips', []), reverse=True)[:D.get('best_trip_count', 10)])
        if total > 0:                             # end-of-event ranking reward (single player: 1st)
            r = RK.TABLES[RANK_TYPE]['ranges'][0]
            for loot, n in r['items']:
                msgs += self.m.prize(loot, n)
            if r.get('title') and self.titles:
                msgs += self.titles(r['title'])
            msgs.append(RK.confirmation(1, RK.PAYLOAD_ESCORT_REWARD, r))
            self.log('   Mimesis Mutiny ended: total %d, 1st place reward' % total)
        with self.p.lock:
            self.p.d['mimesis'] = {}
            self.p.dirty = True
        return msgs

    def home(self):
        return self.k.home() if self.k else 5


class MmRun:
    """A run on the Escort map (the world's 'kapi' and the escorted ship: world.ally)."""
    key = 'mimesis'

    def __init__(self, mode, world, end):
        self.m, self.w = mode, world
        self.g = {'name': 'Mimesis Mutiny'}
        now = time.time()
        self.end = end or now + D['sure_sn']
        self.leg = 0                                 # the next route point
        self.phase = 'wait'                         # wait, route, point, beacon, finished
        self.wave = set()
        self.score = 0
        self.ship = None
        self.next_move = 0.0
        self.next_trickle = now + D['waves']['route_sec']
        self.disrupted = None
        self.done_at = None
        self.success = False
        import world_boss as WB
        s = WB.scale(mode.p, world, None)           # the player's strength (the equipment's sustained laser damage / 60,000, 0.25-2.5)
        k = D['single_player']
        self.hp_f = k['can'] * s                     # adaptation (live round): with fixed x0.3 / x0.5 the first wave destroyed the 356,000-HP ship in 25 s,
        self.dmg_f = k['damage'] * max(0.5, min(1.5, s))     # and the player could not finish off one Mimesis in that time

    @property
    def npcs(self):
        return set(self.wave)

    def wave_name(self):
        return self.phase

    def enter_msgs(self):
        self.spawn_ship()
        self.spawn_wave(D['waves']['start'], near=D['route'][0])
        return [self.score_cmd(), self.zone_poi()]

    def score_cmd(self):
        return ('PayloadEscortScoreCommand', dict(totalScore=self.m.total(), runScore=int(self.score)))

    # ------------------------------------------------------------ ship
    def spawn_ship(self):
        w = self.w
        x, y = D['route'][0]
        n = w.spawn_npc_at(FREIGHTER, x, y)
        n.gate = True
        n.next_think = time.time() + 10 ** 6
        hp = self.ship_hp()
        n.d = dict(n.d, hp=hp, kalkan=0)
        n.hp, n.shield = hp, 0
        self.ship = n
        w.log('   Mimesis Mutiny: EM Freighter %d HP' % hp)

    def ship_hp(self):
        """The ship withstands the strongest wave's fire for endure_sec (Echoes' toughen_ally; with the single-player damage multiplier)."""
        T = world_module.CFG['types']
        waves = D['waves']['waypoints'] + [D['waves']['beacon']]
        dps = max(sum(c * float(T.get(t, {}).get('damage', 0)) for t, c in wv) for wv in waves)
        dps *= self.dmg_f * 0.5 * 0.85 / world_module.COMBAT['npc_attack_interval_sec']
        return int(max(D['ship']['min_hp'], dps * D['ship']['endure_sec']))

    def ship_pos(self, now=None):
        return self.ship.mover.pos(time.time() if now is None else now) if self.ship else D['route'][0]

    def zone_poi(self, now=None):
        x, y = self.ship_pos(now)
        return ('MapAddPOICommand', dict(inverted=True, poiTypeSpecification='', poiType=mod('POITypeModule', typeValue=8), shape=0,
                                         active=True, design=mod('POIDesignModule', designValue=10), poiId=POI_ZONE,
                                         shapeCoordinates=[int(x), int(y), int(D['ship']['protection_radius'])]))

    def safe_at(self, x, y, now):
        """Radiation hook (world.radiation_tick): on a run the inside of the protection area, then the exit portal's surroundings are safe."""
        if self.phase == 'finished':
            return math.hypot(x - self.exit_x, y - self.exit_y) <= 1500
        sx, sy = self.ship_pos(now)
        return math.hypot(x - sx, y - sy) <= D['ship']['protection_radius']

    def take_shot(self, n, now):
        """Does the alien's shot go to the ship (half and half if in range; Echoes' pattern) -> True."""
        a, w = self.ship, self.w
        if not a or not a.alive or self.phase == 'finished' or random.random() > 0.5:
            return False
        ax, ay = a.mover.pos(now)
        nx, ny = n.mover.pos(now)
        if math.hypot(ax - nx, ay - ny) > w.npc_range(n) + 200:
            return False
        n.next_shot = now + n.d.get('shot_interval_sec', world_module.COMBAT['npc_attack_interval_sec'])
        dmg = int(n.d['damage'] * random.uniform(0.8, 1.0) * SET.multiplier('npc_damage', 'wave' if n.hunt else 'map'))
        a.hp = max(0, a.hp - dmg)
        w.send([('AttackLaserRunCommand', dict(attackerId=n.id, targetId=a.id, laserColor=0, isDiminishedBySkillShield=False,
                                               skilledLaser=False, visualType=0)),
                ('AttackHitCommand', dict(attackType=mod('AttackTypeModule', attackTypeValue=1), attackerId=n.id, victimId=a.id,
                                          victimHitpoints=int(a.hp), victimShield=0, victimNanoHull=0, damage=dmg,
                                          skilled=False, strike=False, cannonType=0))])
        if a.hp <= 0:
            a.alive = False
            w.npcs.pop(a.id, None)
            w.send([('ShipDestroyedCommand', dict(destroyedUserId=a.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': a.id})])
            self.fail('msg_mutiny_escort_failed_destroyed')
        return True

    # ------------------------------------------------------------ waves
    def spawn_wave(self, rows, near=None):
        w = self.w
        import pve_common as PS
        cx, cy = near or self.ship_pos()
        for tip, count in rows:
            for _ in range(count):
                a, r = random.uniform(0, 2 * math.pi), random.uniform(900, 1600)
                x = min(max(int(cx + math.cos(a) * r), 500), w.map_w - 500)
                y = min(max(int(cy + math.sin(a) * r), 500), w.map_h - 500)
                n = w.spawn_npc_at(tip, x, y, prep=lambda n: PS.scale_npc(n, hp=self.hp_f, dmg=self.dmg_f), wave=True)
                n.gate, n.engaged, n.hunt = True, True, True
                n.next_think = 0
                self.wave.add(n.id)

    def alive_wave(self):
        return [i for i in self.wave if i in self.w.npcs]

    # ------------------------------------------------------------ loop
    def tick(self, now):
        w = self.w
        if self.phase == 'finished':
            if self.done_at and now >= self.done_at + 300 and self.m.change_map and not w.hero_dead:
                self.done_at = None
                w.send([legacy('0|A|STM|msg_mutiny_escort_sent_home')])
                w.later(2.0, lambda: self.m.change_map(self.m.home(), None, 'station'))
            return
        if now >= self.end:
            self.fail('msg_mutiny_escort_failed_time')
            return
        alive = self.alive_wave()
        if self.phase in ('point', 'beacon'):
            if alive:
                if len(alive) != self.disrupted:
                    self.disrupted = len(alive)
                    w.send([legacy('0|A|STM|msg_mutiny_escort_disrupted|%%AMOUNT%%|%d' % len(alive))])
                return
            self.disrupted = None
            if self.phase == 'beacon':
                self.arrive(now)
                return
            self.score += D['waypoint_points']
            w.send([self.score_cmd(), KAPI.screen('Checkpoint %d cleared!' % self.leg)])
            self.phase = 'route'
        if self.phase == 'wait':
            self.phase = 'route'
        if self.phase == 'route':
            if now >= self.next_trickle:
                self.next_trickle = now + D['waves']['route_sec']
                self.spawn_wave(D['waves']['route'])
            self.move(now)

    def move(self, now):
        w, a = self.w, self.ship
        if not a or not a.alive or now < self.next_move:
            return
        hx, hy = w.hero_pos(now)
        ax, ay = a.mover.pos(now)
        if w.hero_dead or math.hypot(hx - ax, hy - ay) > D['ship']['protection_radius']:
            if a.mover.pos(now) != a.mover.pos(now + 0.5):           # the player left the area: the ship stops
                a.mover.go(ax, ay, D['ship']['speed'], now)
                w.send([('MoveCommand', dict(userId=a.id, x=int(ax), y=int(ay), timeToTarget=0))])
            self.next_move = now + 0.5
            return
        tx, ty = D['route'][self.leg + 1] if self.leg + 1 < len(D['route']) else D['route'][-1]
        d = math.hypot(tx - ax, ty - ay)
        if d < 60:
            self.reach(now)
            return
        step = min(d, 700)
        nx, ny = ax + (tx - ax) * step / d, ay + (ty - ay) * step / d
        ms = a.mover.go(nx, ny, D['ship']['speed'], now)
        self.next_move = now + ms / 1000.0
        w.send([('MoveCommand', dict(userId=a.id, x=int(nx), y=int(ny), timeToTarget=ms)), ('MapRemovePOICommand', {'poiId': POI_ZONE}),
                self.zone_poi(now + ms / 2000.0)])

    def reach(self, now):
        self.leg += 1
        w = self.w
        last = self.leg >= len(D['route']) - 1
        if last:
            self.phase = 'beacon'
            self.spawn_wave(D['waves']['beacon'])
            w.send([KAPI.screen('The signalling beacon is guarded!', big=True)])
        else:
            self.phase = 'point'
            self.spawn_wave(D['waves']['waypoints'][min(self.leg - 1, len(D['waves']['waypoints']) - 1)])
        w.log('   Mimesis Mutiny: point %d%s' % (self.leg, ' (beacon)' if last else ''))

    def arrive(self, now):
        w, a = self.w, self.ship
        ratio = a.hp / float(max(1, a.d['hp'])) if a and a.alive else 0
        self.score += int(D['arrival_bonus'] * ratio)
        self.success = True
        self.phase = 'arrival'                         # explosion after 5 s (before the timer: so 'ended' is not overwritten if it runs at once)
        w.send([legacy('0|A|STM|msg_mutiny_escort_succeeded'), self.score_cmd()])

        def boom():
            if a and a.alive:
                a.alive = False
                w.npcs.pop(a.id, None)
                w.send([('ShipDestroyedCommand', dict(destroyedUserId=a.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': a.id})])
            self.end_run(True)
        w.later(5.0, boom)

    def fail(self, key):
        if self.phase in ('finished', 'arrival'):         # a timeout after arrival must not end the success a second time (as failed)
            return
        self.w.send([legacy('0|A|STM|%s' % key)])
        self.end_run(False)

    def end_run(self, success):
        w = self.w
        self.phase = 'finished'
        self.done_at = time.time()
        bx, by = D['route'][-1]
        self.exit_x, self.exit_y = min(bx, w.map_w - 1500), by
        w.add_gate(dict(gateId=EXIT_ID, x=self.exit_x, y=self.exit_y, target=self.m.home(), designId=1, gate=self.key, exit=True,
                        arrival='station'))
        for i in self.alive_wave():
            n = w.npcs.get(i)
            if n:
                w.send(w.remove_npc(n))
        w.send([('MapRemovePOICommand', {'poiId': POI_ZONE})] + self.m.finish_run(self.score, success))

    def on_kill(self, npc, x, y):
        t = (D.get('kinds') or {}).get(npc.tip)
        if not t or self.phase == 'finished':
            return []
        self.score += t.get('points', 0)
        msgs = [self.score_cmd()]
        chance = 0.1 if t.get('points', 0) >= 350 else 0                 # elite Mimesis: Escort Key (adaptation)
        if chance and random.random() < chance:
            msgs += self.m.grant_keys(1)
        return msgs

    # death screen: free repair on the spot (you stay) or return to base
    def on_death(self):
        return None

    def revive(self):
        pass

    def repair_offers(self):
        return {world_module.REPAIR_BASE: 0, world_module.REPAIR_LOCATION: 0}
