"""Vortex of Greed / Strike and Exit (roadmap Ö4; data data/major_content.json 'vortex' <- tools/major_content.py).

From level 13; on the calendar (the 1st-20th of each month) the map (483) is entered through the portal in X-1 when a session is open. Sessions are three a day (09:00, 13:00,
20:00; 15 min; Tuesday/Thursday/Saturday 20:00 double coins); with the panel's "Sessioned events always open" setting the portal is always open and the session
starts at login.
Every 2 minutes a wave: 15 boxes (4 Stellar Coins each, boxes from the previous wave that were not collected vanish) and the aliens are topped up to 12 Interceptors / 6 Barracudas
/ 3 Saboteurs; when an alien dies a coin box (20 / 46 / 100). At the 10th minute the Deadly Battleray: whoever lands the last hit becomes the treasure holder
(SPOT_LIGHT on the ship, position on the HUD). At the 8th minute 2, at the 10th minute 1 evacuation zone (EXIT_AREA; on an invisible entity): after standing in it
10 s the coins are credited (double session x2, Vanguard x1.5; weekly limit 11,000, Vanguard 15,400), the treasure holder also gets 500 SC, Cryo-
Nano Coolant and the "Escape Artist" title; the ship returns to X-1. On death the carried coins drop as a box (Vanguard keeps 30%); on the death
screen "Free repairs in Vortex of Greed" (10 s later at a random point on the map) or return to base. When the session ends what is carried is lost.
Client: StrikeAndExitInfoRequest -> StrikeAndExitInfoCommand (window 132), on the map StrikeAndExitMapInfoCommand (HUD 131),
StrikeAndExitScoreCommand / RemoveScoreCommand, ExchangeShopRequest {eventName StrikeAndExit | StrikeAndExitVIP, action 0 list, 1 buy}
-> ExchangeShopCommand. Vanguard (resource_vog-vanguard) is bought in the shop with uridium; it expires when the event ends.
In the profile: vortex {week, earnings, claimed {shop: {eid: [period, count]}}}.
"""
import datetime, json, math, os, random, time

import settings as SET
import world as world_module
import event_gate as EKP
import map_links as H
import galaxy_gates as GALAXY
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'major_content.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('vortex', {})
EVENT = D.get('event', 'vortex_of_greed')
MAP = D.get('map', 483)
PORTAL_ID = EKP.PORTAL_BASE + 92          # the Vortex portal in X-1 (windowed: enters if a session is open)
ZONE_TYPE = 'vog_evacuation'                 # the invisible anchor of the evacuation zone (ship)
EXIT_AREA, SPOT_LIGHT = 142, 143          # VisualModifierCommand (client: EscapeZoneEffect 418, marker 143)
REPAIR_SAE = 13                           # KillScreenOptionTypeModule STRIKE_AND_EXIT
COIN = D.get('currency', 'resource_collectable_stellar-coin')
NPC_IDS = [D['alien_spawns'][k]['npc_id'] for k in ('vog_interceptor', 'vog_barracuda', 'vog_saboteur')] if D else []
SESSION_WINDOW = 15 * 60                  # "always open": every 15-minute slot
HINT_SEC = 30                             # the nearest evacuation zone's direction, while out of the zones (Run.zone_hint)
DIRECTIONS = ('east', 'north-east', 'north', 'north-west', 'west', 'south-west', 'south', 'south-east')


def _register():
    """Vortex aliens as NPC types (1.5x the HP of their normal types; client designs 551-554)."""
    for k, v in D.get('alien_spawns', {}).items():
        world_module.CFG['types'][k] = {x: y for x, y in v.items() if x not in ('count', 'sc', 'box')}
    if D.get('boss'):
        world_module.CFG['types'][D['boss']['type']] = {x: y for x, y in D['boss'].items() if x not in ('type', 'time_sec')}
    # the evacuation zone's anchor: the client looks for the VisualModifier's target among ships (UnitHelper.GetShip; no effect appeared
    # on an entity, live tour Ö4): an invisible, friendly, motionless ship
    world_module.CFG['types'][ZONE_TYPE] = dict(name='', model='84', npc_id=0, hp=1, shield=0, damage=0, speed=0, aggressive=False, friendly=True,
                                          reward={}, cargo={})


_register()


def active(now=None):
    return EVENT in CAL.active(now)


def always_open():
    return bool(SET.get('session_always_open'))


def _hm(s):
    h, m = s.split(':')
    return int(h), int(m)


def session(now=None):
    """(open, start, end, double, next start)."""
    now = time.time() if now is None else now
    if always_open():
        start = now - now % SESSION_WINDOW
        return True, start, start + D['session_sec'], False, start + SESSION_WINDOW
    t = datetime.datetime.fromtimestamp(now)
    starts = []
    for day in (-1, 0, 1):
        base = (t + datetime.timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        for s in D.get('sessions', []):
            h, m = _hm(s)
            starts.append(base.replace(hour=h, minute=m))
    starts.sort()
    for s in starts:
        a = s.timestamp()
        if a <= now < a + D['session_sec']:
            double = s.isoweekday() in D.get('double_days', []) and s.strftime('%H:%M') == D.get('double_hour')
            return True, a, a + D['session_sec'], double, next((x.timestamp() for x in starts if x.timestamp() > a), a + 86400)
    nxt = next((s.timestamp() for s in starts if s.timestamp() > now), now + 86400)
    return False, None, None, False, nxt


def week_key(now=None):
    d = datetime.date.fromtimestamp(time.time() if now is None else now)
    y, w, _ = d.isocalendar()
    return '%d-W%02d' % (y, w)                # renews on Monday at 00:00


def period_key(kind, now=None):
    d = datetime.date.fromtimestamp(time.time() if now is None else now)
    if kind == 1:
        return d.isoformat()
    if kind == 2:
        return week_key(now)
    if kind == 3:
        return d.strftime('%Y-%m')
    if kind == 4:
        return str((CAL.period(EVENT, now) or (0,))[0])
    return 'always'


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Vortex:
    REQUESTS = ('StrikeAndExitInfoRequest', 'ExchangeShopRequest')

    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.world = None
        self.run = None                           # the run on the map (VogRun)
        self.change_map = None                    # the session binds it
        self.titles = None                        # granting a title (the session binds it: title_hunt.grant_title)
        self.was_in = False

    @property
    def st(self):
        d = self.p.d.setdefault('vortex', {})
        if d.get('week') != week_key():
            d.update(week=week_key(), earnings=0)
        d.setdefault('earnings', 0)
        d.setdefault('claimed', {})
        return d

    def vip(self):
        return self.p.resource(D.get('vip_item', 'resource_vog-vanguard')) > 0

    def limit(self):
        return D['vip_limit'] if self.vip() else D['weekly_limit']

    # ------------------------------------------------------------ window and shop
    def info_cmd(self, now=None):
        open_, a, b, double, nxt = session(now)
        now = time.time() if now is None else now
        return ('StrikeAndExitInfoCommand', dict(currentGetStellarCoin=int(self.st['earnings']), vip=self.vip(),
                                                 nextOpenSeconds=0 if open_ else max(0, int(nxt - now)), inDouble=bool(open_ and double),
                                                 StellarCoinLimit=int(self.limit()), inSession=bool(open_ and active(now))))

    def shop_cmd(self, event):
        sh = D['store'][event]
        bought = self.st['claimed'].get(event, {})
        rows = []
        for it in sh['items']:
            per, n = bought.get(str(it['eid']), [None, 0])
            used = n if per == period_key(it['limit_type']) else 0
            rows.append(mod('ExchangesShopItem', isSpecial=False, costs=[mod('RewardModule', lootId=COIN, amount=it['price'])],
                            limitType=it['limit_type'], reward=mod('RewardModule', lootId=it['reward'], amount=it['count']),
                            maxLimit=it['cap'], limit=used, eid=it['eid']))
        left = int(CAL.time_left(EVENT)) if active() else 0     # the remainder of an event forced from the panel too (if it has no period)
        asset = mod('InventoryItemModule', upgradeLevel=0, lootId=COIN, amount=int(self.p.resource(COIN)), itemId=0, star=0, isNew=False,
                    hangarId=0, extAttributes=[], inventoryItemAttributes=[])
        return ('ExchangeShopCommand', dict(items=rows, assets=[asset],
                                            isVIPShop=sh['vip'], vipEndSeconds=max(0, left) if self.vip() else 0, isVIP=self.vip(),
                                            shopId=sh['store_id'], eventName=event))

    def buy(self, event, eid):
        sh = D['store'].get(event)
        it = next((x for x in (sh or {}).get('items', []) if x['eid'] == eid), None)
        if not it:
            return []
        if sh['vip'] and not self.vip():
            return [GALAXY.screen('VoG Vanguard required.')]
        per = period_key(it['limit_type'])
        bought = self.st['claimed'].setdefault(event, {})
        p0, n = bought.get(str(eid), [per, 0])
        n = n if p0 == per else 0
        if n >= it['cap'] or self.p.resource(COIN) < it['price']:
            return [self.shop_cmd(event)]
        self.p.add_resource(COIN, -it['price'])
        with self.p.lock:
            bought[str(eid)] = [per, n + 1]
            self.p.dirty = True
        msgs = self.m.resource_msgs(COIN, self.p.resource(COIN), -it['price']) + self.m.reward(it['reward'], it['count'])
        self.log('   Vortex shop (%s): %s x%d, %d SC' % (event, it['reward'], it['count'], it['price']))
        return [self.shop_cmd(event)] + msgs + self.m.money_msgs()

    def handle(self, name, f):
        if name == 'StrikeAndExitInfoRequest':
            return [self.info_cmd()]
        ev = f.get('eventName')
        if name == 'ExchangeShopRequest' and ev in D.get('store', {}):
            if int(f.get('action') or 0) == 1:
                return self.buy(ev, int(f.get('eId') or 0))
            return [self.shop_cmd(ev)]
        return []

    # ------------------------------------------------------------ portal
    def portals(self, map_id, station):
        if not active() or not station or H.map_class(map_id) != D.get('entry', 'X-1') \
                or H.company(map_id) != self.p.d['pilot'].get('factionId'):
            return []
        sx, sy = station['posX'], station['posY']
        cx, cy = GALAXY.MAP_W // 2, GALAXY.MAP_H // 2
        x, y = int(sx + (cx - sx) * 0.45), int(sy + (cy - sy) * 0.45 - 900)
        return [dict(gateId=PORTAL_ID, x=x, y=y, target=0, designId=D.get('portal_design', 1), windowed='vortex',
                     tooltip=D.get('tooltip', 'ttip_jumpgate_sae'))]

    def portal_window(self, g, w, go):
        """Jumped to the portal in X-1 (under the world lock): to the map if a session is open."""
        if self.p.d['pilot'].get('level', 1) < D.get('level', 13):
            w.send([GALAXY.screen('You need to reach level %d to enter the Vortex of Greed.' % D.get('level', 13))])
            return
        open_, a, b, double, nxt = session()
        if not open_:
            left = max(0, int(nxt - time.time()))
            w.send([legacy('0|A|STM|strikeandexit_overview_gate_close|%%TIME%%|%s' % fmt(left))])
            return
        go(MAP, self.spawn_point())

    def spawn_point(self):
        mw, mh = H.map_size(MAP)
        return random.randint(1500, mw - 1500), random.randint(1500, mh - 1500)

    # ------------------------------------------------------------ world
    def attach(self, world):
        self.world = world
        msgs = []
        if int(world.map_id) == MAP and active():
            open_, a, b, double, nxt = session()
            if open_ and always_open():                  # "always open": the session starts at login (15 min even if entered at the end of a slot)
                a, b = time.time(), time.time() + D['session_sec']
            if open_:
                self.run = VogRun(self, world, a, b, double)
                world.gate = self.run
                msgs += self.run.enter_msgs()
                self.was_in = True
                return msgs
        if int(world.map_id) == MAP:                        # no session (spawned on this map at login): to base
            send_home(self, world)
        if self.was_in:
            self.was_in = False
            msgs.append(('StrikeAndExitRemoveScoreCommand', {}))
        self.run = None
        return msgs

    def on_kill(self, w, npc, x, y):
        if self.run and self.run.w is w:
            return self.run.on_kill(npc, x, y)
        return []

    def tick(self, now):
        if not active(now):
            vip = D.get('vip_item', 'resource_vog-vanguard')
            if self.p.resource(vip) > 0:                  # Vanguard is for the event period
                self.p.add_resource(vip, -self.p.resource(vip))
                self.log('   Vortex of Greed ended: Vanguard dropped')
        return []

    def credit(self, coins, bounty):
        """Evacuation: coins (double, Vanguard) are credited up to the weekly limit; treasure reward -> messages."""
        msgs = []
        st = self.st
        room = max(0, self.limit() - st['earnings'])
        got = min(coins, room)
        if bounty:
            extra = min(D['treasure']['sc'], max(0, room - got))
            got += extra
        if got < coins + (D['treasure']['sc'] if bounty else 0):
            msgs.append(legacy('0|A|STM|strikeandexit_message_coin_limit'))
        if got:
            self.p.add_resource(COIN, got)
            with self.p.lock:
                st['earnings'] += got
                self.p.dirty = True
            msgs += self.m.resource_msgs(COIN, self.p.resource(COIN), got)
        if bounty:
            for loot, n in D['treasure']['items']:
                msgs += self.m.reward(loot, n)
            if self.titles and D['treasure'].get('title'):
                msgs += self.titles(D['treasure']['title'])
        self.log('   Vortex evacuation: %d SC credited (this week %d/%d)%s' % (got, st['earnings'], self.limit(), ', hazine' if bounty else ''))
        return msgs + self.m.money_msgs()

    def home(self):
        return self.k.home() if self.k else 5


def send_home(mode, world):
    """No run on the event map (spawned there at login while the session was closed): to base shortly. If the map number belongs to another mode
    (Frozen Labyrinth 430-445 = Escort and Eternal Gate maps; a player landing on 430 in the labyrinth was thrown to base after 3 s,
    test_event_gate login at 430) it is left alone."""
    if mode.change_map:
        home = mode.k.home() if mode.k else 5

        def go():
            if getattr(world, 'labyrinth', None) or getattr(world, 'gate', None) is not None:
                return
            mode.change_map(home, None, 'station')
        world.later(3.0, go)


def fmt(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return '%d:%02d:%02d' % (h, m, s) if h else '%d:%02d' % (m, s)


class VogRun:
    """The session on the Vortex map (the world's `gate`): waves, boss, evacuation zones, carried coins."""
    key = 'vortex'

    def __init__(self, mode, world, start, end, double):
        self.m, self.w = mode, world
        self.g = {'name': 'Vortex of Greed'}
        self.start, self.end, self.double = start, end, double
        self.score = 0
        self.npcs = set()
        self.wave_boxes = set()
        self.boss_id = None
        self.boss_done = False
        self.holder = False
        self.zones = []                            # [x, y, entity]
        self.zone_times = set()
        self.inside_since = None
        self.next_hud = 0.0
        self.next_hint = 0.0                       # the next "nearest evacuation zone" hint (zone_hint)
        self.dirty = True
        self.left = False
        now = time.time()
        k = int((now - start) // D['wave_sec'])
        self.next_wave = start + k * D['wave_sec']            # the wave comes at once even if entered late

    # world interface
    def wave(self):
        return 'wave'

    @property
    def phase(self):
        return 'combat'

    def enter_msgs(self):
        return [self.score_cmd(), self.map_info()]

    def score_cmd(self):
        return ('StrikeAndExitScoreCommand', dict(score=int(self.score), uid=self.w.hid))

    def counts(self):
        alive = [self.w.npcs[i] for i in self.npcs if i in self.w.npcs]
        return [sum(1 for n in alive if n.d.get('npc_id') == k) for k in NPC_IDS]

    def map_info(self, now=None):
        now = time.time() if now is None else now
        boss_at = self.start + D['boss']['time_sec']
        name = self.m.p.d['pilot'].get('userName', '') if self.holder else ''
        hx, hy = self.w.hero_pos(now) if self.holder else (0, 0)
        return ('StrikeAndExitMapInfoCommand', dict(
            spotLightUserY=int(hy), nextSpawnBossSeconds=max(0, int(boss_at - now)) if not self.boss_id and not self.boss_done else 0,
            spotLightUserName=name, spotLightUserX=int(hx), npcRemainingQuantity=self.counts(), npcTypes=list(NPC_IDS),
            bossAlive=bool(self.boss_id and self.boss_id in self.w.npcs), boxRemainingQuantity=sum(1 for h in self.wave_boxes if h in self.w.boxes),
            boxType=D['box_type'], remainingTime=max(0, int(self.end - now)), bossType=D['boss']['npc_id'],
            nextSpawnSeconds=max(0, int(self.next_wave - now)) if self.next_wave < self.end else 0,
            stellarCoinLimit=int(self.m.limit())))

    def tick(self, now):
        w = self.w
        if self.left:
            return
        if now >= self.end:
            self.finish('Session over: the Stellar Coins you carried are lost.')
            return
        if now >= self.next_wave and self.next_wave < self.end:
            self.spawn_wave(now)
            self.next_wave += D['wave_sec']
        if not self.boss_id and not self.boss_done and now >= self.start + D['boss']['time_sec']:
            self.spawn_boss()
        for t, c in D['evacuation']['times']:
            if t not in self.zone_times and now >= self.start + t:
                self.zone_times.add(t)
                self.spawn_zones(c, now)
        self.evac_tick(now)
        if self.dirty or now >= self.next_hud:
            self.dirty = False
            self.next_hud = now + 5
            w.send([self.map_info(now)])

    def random_spot(self, away=None, dist=0):
        mw, mh = self.w.map_w, self.w.map_h
        for _ in range(40):
            x, y = random.randint(1200, mw - 1200), random.randint(1200, mh - 1200)
            if all(math.hypot(x - ax, y - ay) >= dist for ax, ay in (away or [])):
                return x, y
        return random.randint(1200, mw - 1200), random.randint(1200, mh - 1200)

    def spawn_wave(self, now):
        w = self.w
        msgs = []
        for h in list(self.wave_boxes):            # boxes from the previous wave that were not collected vanish
            if h in w.boxes:
                del w.boxes[h]
                msgs.append(('RemoveCollectableCommand', {'collected': False, 'hash': h}))
        self.wave_boxes.clear()
        for _ in range(D['wave_box']):
            x, y = self.random_spot()
            h = w.drop_box(D['box_type'], x, y, None, max(1, int(self.end - now)))
            self.coin_box(h, D['box_sc'])
            self.wave_boxes.add(h)
        alive = self.counts()
        for (tip, a), have in zip(sorted(D['alien_spawns'].items(), key=lambda kv: kv[1]['npc_id']), alive):
            for _ in range(max(0, a['count'] - have)):
                x, y = self.random_spot()
                n = w.spawn_npc_at(tip, x, y)
                n.gate = True
                self.npcs.add(n.id)
        if msgs:
            w.send(msgs)
        self.dirty = True
        w.log('   Vortex: wave (%d boxes, aliens %s)' % (D['wave_box'], self.counts()))

    def coin_box(self, h, coins):
        b = self.w.boxes[h]
        b['no_pet'] = True                        # the P.E.T. cannot collect Vortex boxes (official FAQ)
        b['al'] = lambda box, c=coins: self.collect(c)

    def collect(self, coins):
        self.score += coins
        self.dirty = True
        return [self.score_cmd(), GALAXY.screen('+%d Stellar Coins' % coins)]

    def spawn_boss(self):
        w = self.w
        x, y = self.random_spot()
        n = w.spawn_npc_at(D['boss']['type'], x, y)
        n.gate = True
        self.boss_id = n.id
        self.dirty = True
        w.send([legacy('0|A|STM|strikeandexit_message_boss_spawn')])
        w.log('   Vortex: Deadly Battleray spawned (%d,%d)' % (x, y))

    def spawn_zones(self, count, now):
        w = self.w
        msgs = []
        hx, hy = w.hero_pos(now)
        for _ in range(count):
            x, y = self.random_spot([(hx, hy)] + [(z[0], z[1]) for z in self.zones], D['evacuation']['distance'])
            self.add_zone(x, y)
        msgs.append(legacy('0|A|STM|strikeandexit_message_escape_zone_spawn'))
        w.send(msgs)
        self.next_hint = 0.0                       # where the new zone is: at once
        w.log('   Vortex: %d evacuation zones %s' % (count, [(z[0], z[1]) for z in self.zones[-count:]]))

    def add_zone(self, x, y):
        w = self.w

        def prep(n):
            n.hidden = True                         # ShipCreateCommand.cloaked: the ship is invisible, the effect visible
        n = w.spawn_npc_at(ZONE_TYPE, x, y, prep=prep)
        n.gate = True
        n.next_think = time.time() + 10 ** 6
        self.zones.append([x, y, n.id])
        vm = ('VisualModifierCommand', dict(userId=n.id, modifier=EXIT_AREA, attribute=D['evacuation']['radius'], additionalAttribute='',
                                            count=1, activated=True))
        n.images = {EXIT_AREA: vm}             # again when it comes into view (world.show)
        w.send([vm])

    def zone_at(self, x, y):
        r = D['evacuation']['radius']
        return next((z for z in self.zones if math.hypot(x - z[0], y - z[1]) <= r), None)

    def zone_hint(self, hx, hy, now):
        """Every 30 s while out of the zones: the nearest one's distance and direction. The zones are not on the minimap (wiki) and are drawn only
        once in sight, 3,000+ away on a big map: players found no way out (player report 2026-11-02, "no way to extract yourself")."""
        if now < self.next_hint:
            return []
        self.next_hint = now + HINT_SEC
        x, y, _ = min(self.zones, key=lambda z: math.hypot(z[0] - hx, z[1] - hy))
        d = math.hypot(x - hx, y - hy)
        side = DIRECTIONS[int(round(math.degrees(math.atan2(hy - y, x - hx)) / 45.0)) % 8]     # the map's y grows southwards
        return [GALAXY.screen('Nearest evacuation zone: %s units to the %s.' % ('{:,}'.format(int(round(d, -2))), side))]

    def evac_tick(self, now):
        w = self.w
        if w.hero_dead or w.jumping or not self.zones:
            self.inside_since = None
            return
        hx, hy = w.hero_pos(now)
        if not self.zone_at(hx, hy):
            hint = self.zone_hint(hx, hy, now)
            if hint:
                w.send(hint)
            if self.inside_since is not None:
                self.inside_since = None
                w.send([GALAXY.screen('Evacuation interrupted.')])
            return
        if self.inside_since is None:
            self.inside_since = now
            self.counted = None
        left = int(math.ceil(self.inside_since + D['evacuation']['cooldown_sec'] - now))
        if left <= 0:
            self.evacuate()
        elif left != getattr(self, 'counted', None):
            self.counted = left
            w.send([GALAXY.screen('Evacuating in %d…' % left)])

    def evacuate(self):
        w = self.w
        coins = self.score
        if self.double:
            coins *= 2
        if self.m.vip():
            coins = int(coins * D['vip_earnings'])
        msgs = self.m.credit(int(coins), self.holder)
        msgs += [GALAXY.screen('Evacuation successful!', big=True)]
        self.score = 0
        self.leave(msgs)

    def finish(self, text):
        self.score = 0
        self.leave([GALAXY.screen(text, big=True)])

    def leave(self, msgs):
        w = self.w
        self.left = True
        if self.holder:
            msgs.append(self.spot(False))
            self.holder = False
        msgs.append(('StrikeAndExitRemoveScoreCommand', {}))
        for z in self.zones:
            msgs.append(('VisualModifierCommand', dict(userId=z[2], modifier=EXIT_AREA, attribute=0, additionalAttribute='', count=0,
                                                        activated=False)))
        w.send(msgs)
        self.m.was_in = False
        home = self.m.home()
        if self.m.change_map:
            w.later(2.0, lambda: self.m.change_map(home, None, 'station'))

    def spot(self, on):
        return ('VisualModifierCommand', dict(userId=self.w.hid, modifier=SPOT_LIGHT, attribute=0, additionalAttribute='',
                                              count=1 if on else 0, activated=on))

    def on_kill(self, npc, x, y):
        w = self.w
        msgs = []
        a = D['alien_spawns'].get(npc.tip)
        if a:
            h = w.drop_box(a['box'], int(x), int(y), None, max(1, int(self.end - time.time())))
            self.coin_box(h, a['sc'])
            self.dirty = True
        elif npc.id == self.boss_id:
            self.boss_id, self.boss_done = None, True
            self.holder = True
            msgs += [self.spot(True), legacy('0|A|STM|strikeandexit_message_user_bounty|%%USERNAME%%|%s'
                                             % self.m.p.d['pilot'].get('userName', ''))]
            self.dirty = True
            w.log('   Vortex: the player is the treasure holder')
        return msgs

    # death and the death screen (world.repair_offers / repair_options / kill_screen_repair hooks)
    def on_death(self):
        w = self.w
        keep = int(self.score * D['vip_kept_on_death']) if self.m.vip() else 0
        drop = self.score - keep
        if drop > 0:                               # world.hero_death calls this before it writes the death position
            x, y = w.hero_pos()
            h = w.drop_box(D['ship_box'], int(x), int(y), None, max(1, int(self.end - time.time())))
            self.coin_box(h, drop)
        self.score = keep
        if self.holder:
            self.holder = False
            w.send([self.spot(False)])
        self.dirty = True
        w.send([self.score_cmd()])

        def ready():                               # after 10 s the "Free repairs" option opens (the countdown text goes away)
            if w.hero_dead and w.gate is self:
                w.send([('KillScreenUpdateCommand', {'options': w.repair_options()})])
        w.later(D['spawn_cooldown_sec'] + 0.3, ready)
        return None

    def revive(self):
        pass

    def repair_offers(self):
        return {world_module.REPAIR_BASE: 0, REPAIR_SAE: 0}

    def repair_texts(self, kind):
        left = max(0, int(D['spawn_cooldown_sec'] - (time.time() - (self.w.death_time or 0))))
        return ('ttip_killscreen_repair_sae', 'ttip_killscreen_repair_sae', 'btn_killscreen_repair_for_free',
                ('desc_killscreen_option_available_countdown_sae', {'COUNTDOWN': left}) if left else ('', {}))

    def repair(self, kind):
        """STRIKE_AND_EXIT: after 10 s at a random point on the map with full HP -> (x, y) or None (wait)."""
        if kind != REPAIR_SAE or time.time() - (self.w.death_time or 0) < D['spawn_cooldown_sec'] or self.left:
            return None
        return self.random_spot()
