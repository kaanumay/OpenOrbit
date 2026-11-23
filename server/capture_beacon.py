"""Capture the Beacon (darkorbitwiki events/capture-the-beacon, 2022-06-08; official Turkish FAQ board-tr 127523; fandom; the client's
CTB* handlers, window and home zone objects). Research: belgeler/arastirma/PVP_MODLARI.md section 3.

Real rules kept: every company's X-2 has two beacons (buoys), one for each enemy company, in that company's colour (beacon id 1xy: x the
company whose X-2 it is in, y the company that steals it); a pilot steals the beacon of their colour on an enemy X-2 and delivers it to the
matching place on their own X-2 for a point; the beacon then returns to the map it was stolen from; the cloak is switched off while
carrying; killing the carrier stops the theft; one's own map's beacons cannot be taken; level 13 to go for them; the company with the most
deliveries wins the prize; a tournament every hour (the client's breakingNewsContent_springfight_ctb).
Client facts: CTBSetHomeZonesCommand draws ctbHomeZone_<id> (map object and minimap icon); CTBBeaconCapturedCommand puts the beacon on the
carrier's ship, CTBBeaconReleasedCommand takes it off; CTBBeaconPositionCommand {beaconId, mapId} (0: at home) and CTBScoreUpdateCommand fill
the window (ctb); the old text channel 0|n|ctb is dead. The beacon at rest is AddBeaconCommand {hash, x, y, beaconId}: the client's
beacon_<beaconId> collectable (AddBeaconCommandHandler -> UnitFactory.CreateCollectables; Unit.IsBeacon), a click flies the ship to it
and sends CollectBoxRequest (MoveHelper.MoveHeroToCoordinates, like a box); RemoveCollectableCommand takes it off the map (AssetCreate
21-26 build nothing).
Adaptation (data/extra_events.json "_adaptation"): delivering by flying into the zone; a beacon of a killed carrier goes home at once
(it is not left lying where the carrier died); the carrier is slowed; enemy bot pilots raid
the player's X-2 now and then (the player can stop them), the other deliveries of the hour are simulated; the zone positions and radius,
the raid interval, the hour winner's prize (the next hour's +5% EP and Honor).
"""
import math, random, time

import event_calendar as CAL
import game_data as DATA

EVENT = 'capture_the_beacon'
D = DATA.load('extra_events.json').get('capture_the_beacon', {})
COMPANIES = (1, 2, 3)
NAMES = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
X2 = {1: 2, 2: 6, 3: 10}
HASH = 'CTB-%d'                 # the beacon's collectable hash: outside world.rand_hash's alphabet, so never a box's or an ore's


def active(now=None):
    return bool(D) and CAL.is_active(EVENT, now)


def beacon(home, thief):
    return 100 + 10 * home + thief


def parts(bid):
    return (bid // 10) % 10, bid % 10                     # (the company whose X-2 it rests in, the company that steals it)


def zone(bid):
    """Where the beacon rests on its X-2 (and where the thieves deliver the matching beacon on theirs)."""
    home, thief = parts(bid)
    return tuple(D['zones'][str(home)][str(thief)])


def slot(now=None):
    """The hour (epoch hours like prize_until: the local '%H' repeated on the DST fall-back day, one tournament ran 2 hours)."""
    return str(int((now or time.time()) // 3600))


def state(p, now=None):
    """p.d['ctb']: this hour's scores (and the simulated deliveries), the hour winner's prize."""
    now = now or time.time()
    st = p.d.setdefault('ctb', {})
    cur = slot(now)
    if st.get('slot') != cur:
        sc = st.get('scores') or {}
        if sc:
            top = max(sc.values())
            leaders = [c for c, v in sc.items() if v == top]
            st['winner'] = int(leaders[0]) if top > 0 and len(leaders) == 1 else 0
            st['prize_until'] = (now // 3600 + 1) * 3600
        st.update(slot=cur, scores={'1': 0, '2': 0, '3': 0}, sim_next=now + random.uniform(*D['sim_sec']))
        p.dirty = True
    return st


def raiders_company(now):
    """The company of a simulated delivery of the hour: in proportion to each company's online level 13+ bot pilots on the X-2 maps (who
    could steal a beacon there; bot manager on_map), none when nobody is there; a uniform company without the bots."""
    import bot.manager as MGR
    y = MGR.ACTIVE
    if y is None:
        return random.choice(COMPANIES)
    n = {c: 0 for c in COMPANIES}
    for m in X2.values():
        for b in list(y.on_map.get(m, ())):
            if b.level >= D['min_level'] and b.dead_until <= now:
                n[b.company] += 1
    total = sum(n.values())
    if not total:
        return 0
    x = random.random() * total
    for c in COMPANIES:
        x -= n[c]
        if x < 0:
            return c
    return COMPANIES[-1]


def company_mods(p):
    """The hour winner's prize for the next hour (adaptation: +5% EP and Honor)."""
    st = p.d.get('ctb', {})
    if time.time() >= st.get('prize_until', 0) or st.get('winner') != int(p.d['pilot'].get('factionId') or 0):
        return {}
    return {'ep': D['prize']['ep'], 'honor': D['prize']['honor']}


class CaptureBeacon:
    team_mode = False

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.carrying = None          # the beacon the player carries
        self.raider = None            # {'bot', 'beacon', 'carrying', 'until'}
        self.where = {}               # beacon -> map it is on (0: home)
        self.next_raid = 0.0
        self.shown = set()            # the beacons at rest the client of self.world has (AddBeaconCommand)
        self.wish = None              # (beacon, until): clicked while the ship was still on its way

    def company(self):
        return int(self.p.d['pilot'].get('factionId') or 1)

    def score_cmd(self):
        sc = state(self.p)['scores']
        return ('CTBScoreUpdateCommand', dict(score_MMO=int(sc['1']), score_EIC=int(sc['2']), score_VRU=int(sc['3'])))

    def positions(self):
        return [('CTBBeaconPositionCommand', dict(beaconId=b, mapId=int(self.where.get(b, 0))))
                for h in COMPANIES for t in COMPANIES if h != t for b in (beacon(h, t),)]

    def login_msgs(self):
        return [self.score_cmd()] + self.positions() if active() else []

    # ------------------------------------------------------------ world
    def attach(self, world):
        self.world = world
        self.shown, self.wish = set(), None           # a new map: the client has none of them
        world.death_hooks.append(self.hero_killed)    # also when the event begins while on the map (tick: setup)
        if not active():
            self.carrying = None
            return []
        m = int(world.map_id)
        msgs = self.setup(world)
        if self.carrying:                            # the beacon goes along with its carrier (and so does the slowing)
            self.where[self.carrying] = m
            world.hero_effect('slow', 24 * 3600, D['carrier_slow'], source='ctb')
            msgs.append(('CTBBeaconPositionCommand', dict(beaconId=self.carrying, mapId=m)))
            self.show_carried(world)
        if self.raider is not None and self.raider.get('world') is not world:
            self.end_raid(None)
        return msgs + [self.score_cmd()] + self.beacon_msgs(world)

    def setup(self, w):
        """An X-2 while the event runs: its two beacon places (CTBSetHomeZonesCommand), the raids."""
        owner = next((c for c, x in X2.items() if x == int(w.map_id)), None)
        if not owner:
            return []
        w.mode_brain = self
        self.next_raid = time.time() + random.uniform(*D['raid_first_sec'])
        return self.zone_msgs(w)

    def zone_msgs(self, w):
        owner = next((c for c, x in X2.items() if x == int(w.map_id)), None)
        return [('CTBSetHomeZonesCommand', dict(beaconId=beacon(owner, t), x=zone(beacon(owner, t))[0], y=zone(beacon(owner, t))[1]))
                for t in COMPANIES if t != owner] if owner else []

    def show_carried(self, w):
        """The carried beacon on the player's ship (the client's BeaconEntityTrait goes with the ship's unit: a new map or a reload
        builds a new one); a moment later, once the ship is built."""
        w.later(1.5, lambda: w.send([('CTBBeaconCapturedCommand', dict(userId=w.hid, beaconId=self.carrying))]
                                    if self.carrying and self.world is w else []))

    def beacon_msgs(self, w):
        """The beacons at rest on this X-2 in its client: the ones at home are added, a taken one is removed (collected) and added again
        when it comes back (delivered, its carrier killed, the raid over); none outside the event."""
        if w is None or w is not self.world:
            return []
        owner = next((c for c, x in X2.items() if x == int(w.map_id)), None)
        want = {beacon(owner, t) for t in COMPANIES if t != owner and not self.where.get(beacon(owner, t))} \
            if owner and active() and w.mode_brain is self else set()
        msgs = [('AddBeaconCommand', dict(hash=HASH % b, x=zone(b)[0], y=zone(b)[1], beaconId=b)) for b in sorted(want - self.shown)]
        msgs += [('RemoveCollectableCommand', {'collected': bool(self.where.get(b)), 'hash': HASH % b}) for b in sorted(self.shown - want)]
        self.shown = want
        return msgs

    def resend_msgs(self, w):
        """world.resend: the client cleared the map (respawn, reload): the beacon places, the beacons at rest, a carried beacon on its
        carrier's new ship (the player's; a raider's comes with its ship: n.images['ctb'], bot/tactics.py)."""
        if w is not self.world:
            return []
        self.shown = set()
        msgs = self.zone_msgs(w) if active() and w.mode_brain is self else []
        if self.carrying:
            self.show_carried(w)
        return msgs + self.beacon_msgs(w)

    def near(self, w, b, now=None):
        import world as WD
        hx, hy = w.hero_pos(now)
        zx, zy = zone(b)
        return math.hypot(hx - zx, hy - zy) <= WD.COMBAT['harvest_distance']

    def collect(self, w, h):
        """CollectBoxRequest on a beacon (world.collect): the pilot (level 13) takes the beacon of their colour on an enemy X-2 when the ship
        is at it; if the ship is still on its way, on arrival (like a box: world.COLLECT_WAIT_SEC)."""
        import world as WD
        b = next((x for x in self.shown if HASH % x == h), None)
        if b is None or self.carrying is not None or w.hero_dead or w.jumping or parts(b)[1] != self.company() \
                or int(self.p.d['pilot'].get('level', 1)) < D['min_level']:
            return []
        if not self.near(w, b):
            self.wish = (b, time.time() + WD.COLLECT_WAIT_SEC)
            return []
        self.wish = None
        return self.take(w, b) + self.beacon_msgs(w)

    def on_kill(self, w, npc, x, y):
        return []

    def tick(self, now):
        if not active(now):                          # the event ended while playing: the carried beacon (and its slowing) and a raid end
            w = self.world
            msgs = self.drop(w, w.hid) if self.carrying is not None and w is not None else []
            return msgs + (self.end_raid(w) if self.raider is not None else []) + (self.beacon_msgs(w) if self.shown else [])
        st = state(self.p, now)
        msgs = []
        if now >= st.get('sim_next', 0):             # the other pilots' deliveries of the hour (bot companies)
            st['sim_next'] = now + random.uniform(*D['sim_sec'])
            c = raiders_company(now)
            if c:
                st['scores'][str(c)] += 1
                msgs.append(self.score_cmd())
        w = self.world
        if w is not None and w.mode_brain is not self and int(w.map_id) in X2.values():
            msgs += self.setup(w) + [self.score_cmd()] + self.positions()       # the event began while the pilot is on an X-2
        if w is None or w.hero_dead:
            return msgs
        hx, hy = w.hero_pos(now)
        m = int(w.map_id)
        me = self.company()
        if self.carrying is None:
            if self.wish and (now > self.wish[1] or self.wish[0] not in self.shown):
                self.wish = None
            elif self.wish and self.near(w, self.wish[0], now):           # clicked on the way: taken on arrival
                msgs += self.collect(w, HASH % self.wish[0])
        else:
            if m == X2[me]:
                home, _ = parts(self.carrying)
                zx, zy = zone(beacon(me, home))
                if math.hypot(hx - zx, hy - zy) <= D['zone_radius']:
                    msgs += self.deliver(w)
        msgs += self.raid_tick(w, now)
        return msgs + self.beacon_msgs(w)         # a raider took one / brought one back, a beacon went home

    # ------------------------------------------------------------ the player as carrier
    def take(self, w, b):
        self.carrying = b
        self.where[b] = int(w.map_id)
        try:
            w.abilities.reveal()
            w.items.reveal()                          # the cloak is switched off (wiki)
        except Exception:
            w.step_error('ctb cloak')                 # logged (the pickup goes on)
        w.invuln_until = 0.0
        w.hero_effect('slow', 24 * 3600, D['carrier_slow'], source='ctb')
        self.log('   CTB: beacon %d taken' % b)
        return [('CTBBeaconCapturedCommand', dict(userId=w.hid, beaconId=b)), ('CTBBeaconPositionCommand', dict(beaconId=b, mapId=int(w.map_id)))]

    def drop(self, w, uid):
        b, self.carrying = self.carrying, None
        self.where[b] = 0
        w.hero_effects.remove('slow', source='ctb')
        return [('CTBBeaconReleasedCommand', dict(userId=uid, beaconId=b)), ('CTBBeaconPositionCommand', dict(beaconId=b, mapId=0))]

    def deliver(self, w):
        b = self.carrying
        st = state(self.p)
        st['scores'][str(self.company())] += 1
        self.p.dirty = True
        self.log('   CTB: beacon %d delivered' % b)
        return self.drop(w, w.hid) + [self.score_cmd()]

    def hero_killed(self, w, killer, source_player):
        if self.carrying is None or w is not self.world:
            return []
        self.log('   CTB: the carrier died, beacon %d goes home' % self.carrying)
        return self.drop(w, w.hid)

    # ------------------------------------------------------------ enemy bot raids on the player's X-2
    def raid_tick(self, w, now):
        from bot import tactics as TT
        return TT.ctb_raid_tick(self, w, now)

    def start_raid(self, w, now):
        from bot import tactics as TT
        return TT.ctb_start_raid(self, w, now)

    def end_raid(self, w):
        from bot import tactics as TT
        return TT.ctb_end_raid(self, w)

    def bot_think(self, w, n, now):
        """The raiders' ships: bot/tactics.py steers them."""
        from bot import tactics as TT
        return TT.ctb_think(self, w, n, now)

    def bot_died(self, w, t, killer_uid):
        from bot import tactics as TT
        return TT.ctb_bot_died(self, w, t, killer_uid)
