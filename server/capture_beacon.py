"""Capture the Beacon (darkorbitwiki events/capture-the-beacon, 2022-06-08; official Turkish FAQ board-tr 127523; fandom; the client's
CTB* handlers, window and home zone objects). Research: belgeler/arastirma/PVP_MODLARI.md section 3.

Real rules kept: every company's X-2 has two beacons (buoys), one for each enemy company, in that company's colour (beacon id 1xy: x the
company whose X-2 it is in, y the company that steals it); a pilot steals the beacon of their colour on an enemy X-2 and delivers it to the
matching place on their own X-2 for a point; the beacon then returns to the map it was stolen from; the cloak is switched off while
carrying; killing the carrier stops the theft; one's own map's beacons cannot be taken; level 13 to go for them; the company with the most
deliveries wins the prize; a tournament every hour (the client's breakingNewsContent_springfight_ctb).
Client facts: CTBSetHomeZonesCommand draws ctbHomeZone_<id> (map object and minimap icon); CTBBeaconCapturedCommand puts the beacon on the
carrier's ship, CTBBeaconReleasedCommand takes it off; CTBBeaconPositionCommand {beaconId, mapId} (0: at home) and CTBScoreUpdateCommand fill
the window (ctb); the old text channel 0|n|ctb is dead. A beacon lying on the map has no model in this client (AssetCreate 21-26 build
nothing).
Adaptation (data/extra_events.json "_adaptation"): taking and delivering by flying into the zone (the beacon at rest has no model to
click); a beacon of a killed carrier goes home at once (it could not be seen lying there); the carrier is slowed; enemy bot pilots raid
the player's X-2 now and then (the player can stop them), the other deliveries of the hour are simulated; the zone positions and radius,
the raid interval, the hour winner's prize (the next hour's +5% EP and Honor).
"""
import math, random, time

import event_calendar as CAL
import game_data as DATA
import map_links as H

EVENT = 'capture_the_beacon'
D = DATA.load('extra_events.json').get('capture_the_beacon', {})
COMPANIES = (1, 2, 3)
NAMES = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
X2 = {1: 2, 2: 6, 3: 10}


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
    return time.strftime('%Y-%m-%d %H', time.localtime(now or time.time()))


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
        if not active():
            self.carrying = None
            return []
        msgs = []
        m = int(world.map_id)
        owner = next((c for c, x in X2.items() if x == m), None)
        if owner:                                    # an X-2: its two beacon places
            msgs += [('CTBSetHomeZonesCommand', dict(beaconId=beacon(owner, t), x=zone(beacon(owner, t))[0], y=zone(beacon(owner, t))[1]))
                     for t in COMPANIES if t != owner]
            world.mode_brain = self
            self.next_raid = time.time() + random.uniform(*D['raid_first_sec'])
        if self.carrying:                            # the beacon goes along with its carrier (and so does the slowing)
            self.where[self.carrying] = m
            world.hero_effect('slow', 24 * 3600, D['carrier_slow'], source='ctb')
            msgs.append(('CTBBeaconPositionCommand', dict(beaconId=self.carrying, mapId=m)))
            world.later(1.5, lambda: world.send([('CTBBeaconCapturedCommand', dict(userId=world.hid, beaconId=self.carrying))]
                                                if self.carrying else []))
        if self.raider is not None and self.raider.get('world') is not world:
            self.end_raid(None)
        world.death_hooks.append(self.hero_killed)
        return msgs + [self.score_cmd()]

    def on_kill(self, w, npc, x, y):
        return []

    def tick(self, now):
        if not active(now):
            return []
        st = state(self.p, now)
        msgs = []
        if now >= st.get('sim_next', 0):             # the other pilots' deliveries of the hour (bot companies)
            st['sim_next'] = now + random.uniform(*D['sim_sec'])
            c = random.choice([c for c in COMPANIES])
            st['scores'][str(c)] += 1
            msgs.append(self.score_cmd())
        w = self.world
        if w is None or w.hero_dead:
            return msgs
        hx, hy = w.hero_pos(now)
        m = int(w.map_id)
        me = self.company()
        if self.carrying is None:
            home = next((c for c, x in X2.items() if x == m), None)
            if home and home != me and int(self.p.d['pilot'].get('level', 1)) >= D['min_level']:
                b = beacon(home, me)
                zx, zy = zone(b)
                if not self.where.get(b) and math.hypot(hx - zx, hy - zy) <= D['zone_radius']:
                    msgs += self.take(w, b)
        else:
            if m == X2[me]:
                home, _ = parts(self.carrying)
                zx, zy = zone(beacon(me, home))
                if math.hypot(hx - zx, hy - zy) <= D['zone_radius']:
                    msgs += self.deliver(w)
        msgs += self.raid_tick(w, now)
        return msgs

    # ------------------------------------------------------------ the player as carrier
    def take(self, w, b):
        self.carrying = b
        self.where[b] = int(w.map_id)
        try:
            w.abilities.reveal()
            w.items.reveal()                          # the cloak is switched off (wiki)
        except Exception:
            pass
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
        me = self.company()
        if int(w.map_id) != X2[me]:
            return []
        r = self.raider
        if r is None:
            if now >= self.next_raid:
                self.next_raid = now + random.uniform(*D['raid_sec'])
                return self.start_raid(w, now)
            return []
        if now > r['until'] or not r['bot'].online:
            return self.end_raid(w)
        return []

    def start_raid(self, w, now):
        import team_deathmatch as TDM
        enemy = random.choice([c for c in COMPANIES if c != self.company()])
        b = beacon(self.company(), enemy)
        if self.where.get(b):
            return []
        band = {'min_level': D['min_level'], 'max_level': 999}
        bots = TDM.pick_bots(enemy, band, D['min_level'] + 5, now, set())
        if not bots:
            return []
        bot = bots[0]
        TDM.draft_bots([bot], int(w.map_id), now, 1800)
        self.raider = dict(bot=bot, beacon=b, carrying=False, until=now + D['raid_max_sec'], world=w)
        self.log('   CTB: %s (%s) raids for beacon %d' % (bot.name, NAMES[enemy], b))
        return []

    def end_raid(self, w):
        import team_deathmatch as TDM
        r, self.raider = self.raider, None
        msgs = []
        if r is None:
            return msgs
        if r['carrying']:
            self.where[r['beacon']] = 0
            msgs += [('CTBBeaconReleasedCommand', dict(userId=r['bot'].uid, beaconId=r['beacon'])),
                     ('CTBBeaconPositionCommand', dict(beaconId=r['beacon'], mapId=0))]
        TDM.release_bots(w, [(r['bot'], {})], int(r['bot'].k['map']), 'ctb_done')
        return msgs

    def bot_think(self, w, n, now):
        """The raider: to the beacon's place, takes it (the cloak and speed rules apply to it too), then to the nearest portal; it fights
        back only while it does not carry the beacon."""
        from bot import ship as BS
        r = self.raider
        if r is None or n.bot is not r['bot']:
            return False
        nx, ny = n.mover.pos(now)
        attacked = any(now - t < 4 for t in n.attacker.values())
        if not r['carrying']:
            if attacked:
                return False
            zx, zy = zone(r['beacon'])
            if math.hypot(nx - zx, ny - zy) <= D['zone_radius'] * 0.7:
                r['carrying'] = True
                self.where[r['beacon']] = int(w.map_id)
                n.__dict__.pop('hidden', None)
                n.effect.add('slow', 3600, D['carrier_slow'], 'ctb', now)
                w.send([('CTBBeaconCapturedCommand', dict(userId=n.id, beaconId=r['beacon'])),
                        ('CTBBeaconPositionCommand', dict(beaconId=r['beacon'], mapId=int(w.map_id)))])
                self.log('   CTB: %s took beacon %d' % (n.bot.name, r['beacon']))
            else:
                BS._go_to(w, n, zx, zy, now)
            return True
        gates = H.gates(int(w.map_id), n.bot.company)
        g = min(gates, key=lambda g: math.hypot(g['x'] - nx, g['y'] - ny))
        if math.hypot(g['x'] - nx, g['y'] - ny) <= 200:
            st = state(self.p)
            st['scores'][str(n.bot.company)] += 1    # it reaches its X-2 and delivers it (the beacon goes home)
            self.p.dirty = True
            r['carrying'] = False
            self.where[r['beacon']] = 0
            w.send([('CTBBeaconReleasedCommand', dict(userId=n.id, beaconId=r['beacon'])),
                    ('CTBBeaconPositionCommand', dict(beaconId=r['beacon'], mapId=0)), self.score_cmd()])
            self.log('   CTB: %s escaped with beacon %d' % (n.bot.name, r['beacon']))
            w.send(self.end_raid(w))
            return True
        BS._go_to(w, n, g['x'], g['y'], now)
        return True

    def bot_died(self, w, t, killer_uid):
        """The raider was destroyed: the beacon goes home, the raid is over (its death is a normal one)."""
        r = self.raider
        if r is None or t.bot is not r['bot']:
            return None
        w.send(self.end_raid(w))
        return None
