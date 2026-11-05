"""Sector Control (darkorbitwiki events/sector-control, 2022-06-13; official Turkish FAQ board-tr 127679; the client's SectorControl*
handlers, lobby, HUD, control point model and flashres texts). Research: belgeler/arastirma/PVP_MODLARI.md section 2.

Real rules kept: the Sector Control beacon near the middle of every X-1 (asset 42) opens the lobby; level groups 8-13 (map 201, SC-1) and
14+ (map 202, SC-2); at most 15 per company; a match starts when two companies have at least 5 pilots on standby, then a 30 s countdown in
which nobody can leave the start area (leaving it is radiation); new pilots join a running match while there is room; standby is cancelled
on gate / mode maps; every company bleeds tickets constantly, a kill takes one ticket from the victim's company, holding control points
makes the others bleed (one point: the other two; two companies one each: only the third; all three one each: nobody; two points: both
enemies unless one of them holds the other two; all four: the other two), after 15 minutes every bleed is 5 times faster; 4 control points
captured by having more pilots in the radius than the holder (each extra pilot shortens the capture, up to 8; a tie keeps the holder; cloaked
pilots do not count; the progress returns to the holder, or to neutral, when the attackers leave; neutral is always in between); the start
area repairs 10,000 HP a second and cannot be captured; companies behind get a damage bonus (2 points behind +5%, 3 +8%, all 4 held by one
+15%, lasers and rockets); the death screen's free respawn at the company's start area within 15 s (with the in-place repair's protection),
after that only the X-1 repair; the door at the start area leaves at any time without the bonus; a company without tickets is out and goes
to X-1; the last company with tickets wins: its pilots get their kill statistics and the EP & Honor bonus, then go to X-1.
Single-player adaptation (data/extra_events.json "_adaptation"): the other pilots are bot players (bot/; nearest levels fill a young pack),
the matches the player is not in are simulated (lobby rows), the ticket amount (500, old fandom value), the bleed rates, the capture times,
the control point and start area positions and radii, the team size the bots fill, the bonus percentage per kill.
"""
import math, random, time

import event_calendar as CAL
import game_data as DATA
import map_links as H
from legacy_protocol import stm
import team_deathmatch as TDM

EVENT = 'sector_control'
D = DATA.load('extra_events.json').get('sector_control', {})
BATTLEMASTER, EXIT_POINT = 42, 40                 # AssetTypeModule SECTOR_CONTROL_BATTLEMASTER / _EXIT_POINT
HOME_ZONE, SECTOR_ZONE = 12, 13                   # POITypeModule (client codes HZ / SZ; the client makes the beacon of an SZ itself)
HOME_DESIGN, SECTOR_DESIGN = 7, 8                 # POIDesignModule
DAMAGE = 2                                        # BoostedAttributeTypeModule.AttributeType.DAMAGE (the HUD reads only this one)
SC_REPAIR = 4                                     # KillScreenOptionTypeModule.AT_SECTOR_CONTROL_SPAWNPOINT
ASSET_BASE = 158900000                            # + map (beacon), + 1000 + company (exit door)
MATCH_MAKING, RUNNING = 0, 1
ERR_LEVEL, ERR_NO_TICKETS = 0, 1                  # SectorControlErrorCommand.ErrorType (2 QUEUE_FULL never: bots fill the room)
NONE, CAPTURING, NEUTRALIZING = 0, 1, 2           # SectorControlSectorStateCommand.ActionType
COMPANIES = (1, 2, 3)
NAMES = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
mod = TDM.mod
faction = TDM.faction


def active(now=None):
    return bool(D) and CAL.is_active(EVENT, now)


def on_map(map_id):
    try:
        return int(map_id) in {b['map'] for b in D.get('brackets', [])}
    except (TypeError, ValueError):
        return False


def bracket(level):
    for b in D.get('brackets', []):
        if b['min_level'] <= level <= b['max_level']:
            return b
    return None


def poi(pid, kind, design, x, y, r, extra=None):
    f = dict(inverted=False, poiTypeSpecification='', poiType=mod('POITypeModule', typeValue=kind), shape=0, active=True,
             design=mod('POIDesignModule', designValue=design), poiId=pid, shapeCoordinates=[int(x), int(y), int(r)])
    if extra is None:
        return ('MapAddPOICommand', f)
    f.update(extra)
    return ('MapAddControlPOIZoneCommand', f)


def bleed(held):
    """The extra ticket bleed of each company from the control points (wiki's table): a company bleeds by how many more points each other
    company holds than it. held: {company: points} -> {company: units}."""
    return {c: sum(max(0, held.get(o, 0) - held.get(c, 0)) for o in held if o != c) for c in held}


def underdog(held, c):
    """The damage bonus of a company behind (wiki): another holds 2 more points +5%, 3 more +8%, all 4 +15%."""
    others = [held.get(o, 0) for o in held if o != c]
    top = max(others) if others else 0
    if top >= D['sectors_count']:
        return D['underdog'][2]
    diff = top - held.get(c, 0)
    return D['underdog'][1] if diff >= 3 else D['underdog'][0] if diff >= 2 else 0.0


def capture_speed(n):
    """Progress per second with n more pilots than the other side in the radius (each extra pilot shortens the capture, up to 8)."""
    n = min(n, D['capture_max_pilots'])
    sec = max(1.0, D['capture_sec'] - (n - 1) * D['capture_step_sec'])
    return D['capture_threshold'] / sec


def state(p, now=None):
    st = p.d.setdefault('sc', {})
    st.setdefault('matches', {})
    return st


def sim(st, now, band, own=None):
    """The matches the player is not in (bot companies): standby for a few minutes, then running until one company is left with tickets."""
    rng = random.Random()
    for mid in range(1, D['matches'] + 1):
        key = '%d_%d' % (band, mid)
        m = st['matches'].setdefault(key, {'state': MATCH_MAKING, 'until': now + rng.uniform(20, 180), 'queue': [0, 0, 0]})
        if mid == own:
            continue
        if now - m.get('seen', now) > 1800:
            m.update(state=MATCH_MAKING, until=now + rng.uniform(20, 180), queue=[0, 0, 0])
        m['seen'] = now
        for _ in range(4):
            if m['state'] == MATCH_MAKING:
                k = max(0.0, 1 - (m['until'] - now) / 240.0)
                m['queue'] = [min(D['team_max'], int(D['team_target'] * k + rng.random())) for _ in COMPANIES]
                if now < m['until']:
                    break
                m.update(state=RUNNING, start=m['until'], rates=[rng.uniform(0.25, 0.9) for _ in COMPANIES],
                         players=[rng.randint(D['team_min'], D['team_max']) for _ in COMPANIES])
            if m['state'] == RUNNING:
                t = now - m['start']
                m['tickets'] = [max(0, int(D['tickets'] - r * t)) for r in m['rates']]
                if sum(1 for x in m['tickets'] if x > 0) > 1:
                    break
                m.update(state=MATCH_MAKING, until=now + rng.uniform(60, 240), queue=[0, 0, 0])
    return st


# ------------------------------------------------------------------------------------------------ the session's system
class SectorControl:
    REQUESTS = ('SectorControlMatchOverviewRequest', 'SectorControlMatchDetailRequest', 'SectorControlMatchJoinRequest',
                'SectorControlMatchLeaveQueueRequest', 'SectorControlDraftConfirmationRequest', 'SectorControlMatchExitRequest')

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.change_map = None
        self.queued = -1
        self.queue = None             # {'teams': {company: [bots]}, 'at', 'next', 'draft', 'band', 'join_running'}
        self.match = None
        self.near = None

    def level(self):
        return int(self.p.d['pilot'].get('level', 1))

    def company(self):
        return int(self.p.d['pilot'].get('factionId') or 1)

    def band(self):
        return bracket(self.level()) or D['brackets'][0]

    # ------------------------------------------------------------ lobby
    def row(self, mid, now):
        b = self.band()
        st = sim(state(self.p), now, b['map'], self.own_match())
        m = st['matches']['%d_%d' % (b['map'], mid)]
        side = self.company() - 1
        if self.match is not None and self.match.mid == mid:
            g = self.match
            return mod('SectorControlMatchOverviewModule', matchId=mid, matchState=RUNNING, playersOfOwnFaction=len(g.team(self.company())),
                       maxPlayerPerFaction=D['team_max'], remainingTickets=int(g.tickets.get(self.company(), 0)),
                       totalTickets=D['tickets'], playersInQueue=0)
        if mid == self.queued and self.queue is not None:
            own = 1 + len(self.queue['teams'][self.company()])
            return mod('SectorControlMatchOverviewModule', matchId=mid, matchState=m['state'], playersOfOwnFaction=own,
                       maxPlayerPerFaction=D['team_max'], remainingTickets=D['tickets'], totalTickets=D['tickets'],
                       playersInQueue=sum(len(v) for v in self.queue['teams'].values()) + 1)
        running = m['state'] == RUNNING
        return mod('SectorControlMatchOverviewModule', matchId=mid, matchState=m['state'],
                   playersOfOwnFaction=m['players'][side] if running else m['queue'][side], maxPlayerPerFaction=D['team_max'],
                   remainingTickets=m['tickets'][side] if running else D['tickets'], totalTickets=D['tickets'],
                   playersInQueue=0 if running else sum(m['queue']))

    def overview(self):
        now = time.time()
        b = self.band()
        return ('SectorControlMatchOverviewCommand', dict(
            minLevel=b['min_level'], maxLevel=b['max_level'], minPlayersPerTeam=D['team_min'], queuedForMatch=self.queued,
            overviewModules=[self.row(mid, now) for mid in range(1, D['matches'] + 1)]))

    def own_match(self):
        if self.match is not None:
            return self.match.mid
        return self.queued if self.queued > 0 else None

    def detail(self, mid):
        now = time.time()
        b = self.band()
        st = sim(state(self.p), now, b['map'], self.own_match())
        m = st['matches'].get('%d_%d' % (b['map'], mid))
        if m is None:
            return []
        if self.match is not None and self.match.mid == mid:
            g = self.match
            tickets = {c: int(g.tickets.get(c, 0)) for c in COMPANIES}
            players = {c: len(g.team(c)) for c in COMPANIES}
            run = int(now - g.begin) if g.begin else 0
        elif mid == self.queued and self.queue is not None:
            tickets = {c: D['tickets'] for c in COMPANIES}
            players = {c: len(self.queue['teams'][c]) + (1 if c == self.company() else 0) for c in COMPANIES}
            run = 0
        elif m['state'] == RUNNING:
            tickets = dict(zip(COMPANIES, m['tickets']))
            players = dict(zip(COMPANIES, m['players']))
            run = int(now - m['start'])
        else:
            tickets = {c: D['tickets'] for c in COMPANIES}
            players = dict(zip(COMPANIES, m['queue']))
            run = 0
        return [('SectorControlMatchDetailCommand', dict(
            matchId=mid, runningTimeInSecs=run,
            ticketCounts=[mod('SectorControlTicketCountCommand', faction=faction(c), ticketCount=tickets[c], maxTickets=D['tickets'])
                          for c in COMPANIES],
            playerCounts=[mod('SectorControlPlayerCountModule', faction=faction(c), playerCount=players[c], maxPlayers=D['team_max'])
                          for c in COMPANIES]))]

    def join(self, mid):
        now = time.time()
        b = bracket(self.level())
        if b is None:
            return [('SectorControlErrorCommand', {'errorType': ERR_LEVEL})]
        if self.match is not None:
            return []
        if self.world is not None and (getattr(self.world, 'gate', None) is not None or getattr(self.world, 'low', None)):
            return [stm('msg_sectorcontrol_kicked_from_queue')]
        st = sim(state(self.p), now, b['map'])
        m = st['matches'].get('%d_%d' % (b['map'], mid))
        if m is None:
            return []
        if m['state'] == RUNNING and m['tickets'][self.company() - 1] <= 0:
            return [('SectorControlErrorCommand', {'errorType': ERR_NO_TICKETS})]
        self.queued = mid
        self.queue = {'teams': {c: [] for c in COMPANIES}, 'at': now, 'next': now, 'draft': None, 'band': b['map']}
        taken = set()
        if m['state'] == RUNNING:                       # a running match takes pilots while there is room (wiki): straight to the confirmation
            self.queue['join_running'] = dict(tickets=list(m['tickets']), start=m['start'])
            for c, n in zip(COMPANIES, m['players']):
                if m['tickets'][c - 1] <= 0:
                    continue
                want = min(n, D['team_target']) - (1 if c == self.company() else 0)
                got = TDM.pick_bots(c, b, self.level(), now, taken)[:max(0, want)]
                self.queue['teams'][c] = got
                taken |= {x.uid for x in got}
            self.queue['draft'] = now
            self.log('   SC: joining running match %d' % mid)
            return [self.overview(), stm('msg_sectorcontrol_queue_status', '%POSITION%', 1, '%MATCHID%', mid),
                    ('SectorControlDraftConfirmationCommand', {'seconds': D['draft_sec']})]
        for c, n in zip(COMPANIES, m['queue']):         # the pilots already on standby (the lobby row): real bots take their places
            got = TDM.pick_bots(c, b, self.level(), now, taken)[:max(0, min(n, D['team_target']) - (1 if c == self.company() else 0))]
            self.queue['teams'][c] = got
            taken |= {x.uid for x in got}
        self.log('   SC: queued for match %d (%s)' % (mid, H.name(b['map'])))
        return [self.overview(), stm('msg_sectorcontrol_queue_status', '%POSITION%', 1, '%MATCHID%', mid)]

    def leave_queue(self, msg=True):
        out = [stm('msg_sectorcontrol_queue_left')] if msg and self.queue is not None else []
        self.queued, self.queue = -1, None
        return out

    def handle(self, name, f):
        if name == 'SectorControlMatchExitRequest':
            return self.exit()
        if not active():
            return [('SectorControlMatchOverviewCommand', dict(minLevel=0, maxLevel=0, minPlayersPerTeam=0, queuedForMatch=-1,
                                                                overviewModules=[]))] if name == 'SectorControlMatchOverviewRequest' else []
        if name == 'SectorControlMatchOverviewRequest':
            return [self.overview()]
        if name == 'SectorControlMatchDetailRequest':
            return self.detail(int(f.get('matchId', -1)))
        if name == 'SectorControlMatchJoinRequest':
            return self.join(int(f.get('matchId', -1)))
        if name == 'SectorControlMatchLeaveQueueRequest':
            return self.leave_queue() + [self.overview()]
        if name == 'SectorControlDraftConfirmationRequest':
            return self.confirm(bool(f.get('accepted')))
        return []

    def fill(self, now):
        """Standby: the bots of the band join one by one (adaptation: 1-3 s apart) up to the team size the bots fill; with two companies
        of at least 5 (the player's among them) the confirmation comes (all full, or after the fill wait)."""
        q = self.queue
        if q is None or q['draft'] is not None:
            return []
        b = bracket(self.level())
        if b is None or b['map'] != q['band']:
            return self.leave_queue(False) + [self.overview()]
        if now < q['next']:
            return []
        q['next'] = now + random.uniform(*D['queue_fill_sec'])
        taken = {x.uid for v in q['teams'].values() for x in v}
        for c in COMPANIES:
            room = D['team_target'] - (1 if c == self.company() else 0)
            if len(q['teams'][c]) < room:
                got = TDM.pick_bots(c, b, self.level(), now, taken)[:1]
                q['teams'][c] += got
                taken |= {x.uid for x in got}
        size = {c: len(q['teams'][c]) + (1 if c == self.company() else 0) for c in COMPANIES}
        ready = size[self.company()] >= D['team_min'] and sum(1 for c in COMPANIES if size[c] >= D['team_min']) >= 2
        full = all(size[c] >= D['team_target'] for c in COMPANIES)
        if ready and (full or now - q['at'] >= D['fill_wait_sec']):
            q['draft'] = now
            self.log('   SC: match ready %s, confirmation' % size)
            return [('SectorControlDraftConfirmationCommand', {'seconds': D['draft_sec']}), self.overview()]
        return [self.overview()]

    def confirm(self, accepted):
        q = self.queue
        if q is None or q['draft'] is None:
            return []
        if not accepted:
            return self.leave_queue() + [self.overview()]
        return self.start()

    def start(self):
        import bot.manager as MGR
        q, mid = self.queue, self.queued
        b = bracket(self.level())
        self.leave_queue(False)
        if b is None or MGR.ACTIVE is None:
            return []
        now = time.time()
        self.match = Match(self, mid, b['map'], self.company(), q['teams'], now, q.get('join_running'))
        self.log('   SC: match %d on %s' % (mid, H.name(b['map'])))
        if self.change_map:
            self.change_map(b['map'], None, self.match.spawn(self.company(), 300))
        return []

    def exit(self):
        """The door at the start area: leaves at once without the EP & Honor bonus (wiki)."""
        g = self.match
        if g is None:
            return []
        g.close('left')
        self.home()
        return []

    def home(self):
        self.match = None
        if self.change_map and self.world is not None and on_map(self.world.map_id):
            self.change_map(TDM.x1_maps().get(self.company(), 1), None, 'station')

    # ------------------------------------------------------------ world
    def attach(self, world):
        self.world = world
        self.near = None
        msgs = []
        if world.gate is not None and self.queue is not None and not on_map(world.map_id):
            msgs += [stm('msg_sectorcontrol_kicked_from_queue')]       # gate / mode map: no standby (wiki)
            self.leave_queue(False)
        if on_map(world.map_id):
            g = self.match
            if g is None or g.over or g.map != int(world.map_id):
                self.match = None
                world.later(2.0, lambda: self.change_map and self.world is world and self.change_map(
                    TDM.x1_maps().get(self.company(), 1), None, 'station'))
                return msgs
            g.attach(world)
            return msgs + g.enter_msgs()
        if self.match is not None:
            self.match.close('left')
            self.match = None
        if active() and int(world.map_id) in TDM.x1_maps().values():
            x, y = self.beacon_pos(world)
            msgs.append(TDM.asset_cmd(ASSET_BASE + int(world.map_id), BATTLEMASTER, x, y, 'Sector Control'))
        return msgs

    def beacon_pos(self, w):
        """Near the middle of the X-1 (wiki); adaptation: the exact place is not published."""
        dx, dy = D['beacon_offset']
        return int(w.map_w / 2 + dx), int(w.map_h / 2 + dy)

    def on_ready(self):
        g, w = self.match, self.world
        if g is not None and w is not None and g.w is w and not g.over:
            g.ready = True
            w.send(g.hud_msgs(time.time(), full=True))
        return []

    def tick(self, now):
        msgs = []
        if active(now):
            msgs += self.fill(now)
            q = self.queue
            if q is not None and q['draft'] is not None and now - q['draft'] > D['draft_sec'] + 5:
                msgs += self.leave_queue() + [self.overview()]
        elif self.queue is not None:
            self.leave_queue(False)
        w = self.world
        if w is not None and not w.hero_dead:
            msgs += self.near_step(w, now)
        return msgs

    def near_step(self, w, now):
        hx, hy = w.hero_pos(now)
        near = None
        if on_map(w.map_id) and self.match is not None:
            x, y = self.match.spawn(self.company())
            if math.hypot(hx - x, hy - y) <= TDM.NEAR:
                near = (ASSET_BASE + 1000 + self.company(), 'sectorcontrol_popup_leavegame_title')
        elif active() and int(w.map_id) in TDM.x1_maps().values():
            x, y = self.beacon_pos(w)
            if math.hypot(hx - x, hy - y) <= TDM.NEAR:
                near = (ASSET_BASE + int(w.map_id), 'ttip_sector_control_beacon')
        if near == self.near:
            return []
        msgs = []
        if self.near:
            msgs.append(TDM.asset_available(self.near[0], self.near[1], False))
        if near:
            msgs.append(TDM.asset_available(near[0], near[1], True))
        self.near = near
        return msgs


# ------------------------------------------------------------------------------------------------ the match (the world's gate)
class Match:
    key = 'sc'
    team_mode = True
    plain_base_repair = True

    def __init__(self, mode, mid, map_id, own, teams, now, running=None):
        self.m, self.mid, self.map, self.own = mode, mid, int(map_id), own
        self.p = mode.p
        self.g = {'name': 'Sector Control'}
        self.w = None
        self.hid = None
        self.begin = None
        self.ready = False
        self.over = False
        self.next_step = 0.0
        self.next_hud = 0.0
        self.boosted = False
        self.warned = set()
        self.sent_states = {}
        self.participating = None
        self.countdown_sent = set()
        self.companies = [c for c in COMPANIES if c == own or teams.get(c)]
        tickets = (running or {}).get('tickets') or [D['tickets']] * 3
        self.tickets = {c: float(tickets[c - 1]) for c in self.companies}
        self.out = {c for c in self.companies if self.tickets[c] <= 0}
        self.started_at = (running or {}).get('start')       # joined a running match: the 15-minute boost counts from its start
        self.stats = {}
        name = self.p.d['pilot'].get('userName', '')
        self.player = {'name': name, 'company': own, 'kills': 0, 'deaths': 0, 'respawn': 0}
        g = self.p.d['pilot']
        self.ep0, self.honor0 = g.get('ep', 0), g.get('honourPoints', 0)
        self.sectors = [dict(id='sc_sector_%d' % (i + 1), x=x, y=y, owner=0, prog_owner=0, progress=0.0, action=NONE, invaders=[])
                        for i, (x, y) in enumerate(D['sectors'])]
        bots = [b for c in self.companies for b in teams.get(c, [])]
        TDM.draft_bots(bots, self.map, now, 3600)
        for b in bots:
            self.stats[b.uid] = {'name': b.name, 'company': b.company, 'bot': b, 'kills': 0, 'deaths': 0, 'respawn': 0}

    # ------------------------------------------------------------ roster
    def team(self, company):
        out = [u for u, s in self.stats.items() if s['company'] == company and s['bot'].online]
        if company == self.own and not self.player.get('removed'):
            out.append('hero')
        return out

    def roster(self, now):
        if self.over:
            return {}
        return {u: s['bot'] for u, s in self.stats.items()
                if s['company'] not in self.out and now >= s['respawn'] and s['bot'].online}

    def spawn(self, company, scatter=0):
        x, y = D['homes'][str(company)]
        if not scatter:
            return int(x), int(y)
        a, r = random.uniform(0, 2 * math.pi), random.uniform(0, scatter)
        return int(x + math.cos(a) * r), int(y + math.sin(a) * r)

    def bot_spawn(self, b):
        return self.spawn(b.company, D['spawn_scatter'])

    def stat(self, uid):
        if uid == self.hid or uid == 'hero':
            return self.player
        return self.stats.get(uid)

    # ------------------------------------------------------------ world
    def attach(self, world):
        self.w = world
        self.hid = world.hid
        world.gate = self
        world.mode_bots = self.roster
        world.mode_spawn = self.bot_spawn
        world.death_hooks.append(self.hero_killed)
        if self.begin is None:
            self.begin = time.time()
            self.started_at = self.started_at or self.begin
            self.attack_at = self.begin + D['start_sec']
            world.invuln_until = max(world.invuln_until, self.attack_at)
        self.p.pvp_mods = self.player_mods

    def enter_msgs(self):
        msgs = [poi('sc_home_%d' % c, HOME_ZONE, HOME_DESIGN, *self.spawn(c), D['home_radius']) for c in self.companies]
        msgs += [poi(s['id'], SECTOR_ZONE, SECTOR_DESIGN, s['x'], s['y'], D['sector_radius'], dict(
            captureProgress=int(s['progress']), timeTillUnlock=0, progressOwner=faction(s['prog_owner']),
            captureThreshold=D['capture_threshold'], captured=bool(s['owner']))) for s in self.sectors]
        msgs += [TDM.asset_cmd(ASSET_BASE + 1000 + c, EXIT_POINT, *self.spawn(c), name='', company=c) for c in self.companies]
        return msgs

    def held(self):
        return {c: sum(1 for s in self.sectors if s['owner'] == c) for c in self.companies if c not in self.out}

    def player_mods(self):
        """The underdog damage bonus of the player's company (lasers and rockets)."""
        if self.over or self.w is None or self.w.gate is not self:
            return {}
        b = underdog(self.held(), self.own)
        return {'laser': b, 'rocket': b} if b else {}

    def hud_msgs(self, now, full=False):
        held = self.held()
        msgs = [('SectorControlMatchStateInfoCommand', dict(
            bonusInformation=[mod('SectorControlBonusCommand', faction=faction(c), bonusType=mod('BoostedAttributeTypeModule', typeValue=DAMAGE),
                                  bonusFactor=float(underdog(held, c))) for c in self.companies],
            ticketCounts=[mod('SectorControlTicketCountCommand', faction=faction(c), ticketCount=max(0, int(math.ceil(self.tickets[c]))),
                              maxTickets=D['tickets']) for c in self.companies],
            playerCounts=[mod('SectorControlPlayerCountModule', faction=faction(c), playerCount=0 if c in self.out else len(self.team(c)),
                              maxPlayers=D['team_max']) for c in self.companies]))]
        for s in self.sectors:
            st = (int(s['progress']), s['prog_owner'], s['action'], tuple(s['invaders']))
            if full or self.sent_states.get(s['id']) != st:
                self.sent_states[s['id']] = st
                msgs.append(('SectorControlSectorStateCommand', dict(
                    sectorId=s['id'], captureProgress=int(s['progress']), timeTillUnlock=0, progressOwner=faction(s['prog_owner']),
                    invaders=[faction(c) for c in s['invaders']], actionType=s['action'])))
        return msgs

    def safe_at(self, x, y, now):
        """The 30 s countdown: outside the start area is radiation (players cannot leave it, wiki)."""
        if self.begin is None or now >= self.attack_at:
            return True
        sx, sy = self.spawn(self.own)
        return math.hypot(x - sx, y - sy) <= D['home_radius']

    # ------------------------------------------------------------ the match's step
    def tick(self, now):
        w = self.w
        if w is None or self.begin is None or self.over:
            return
        if now < self.attack_at:
            left = int(math.ceil(self.attack_at - now))
            if left in (30, 20, 10, 5, 3) and left not in self.countdown_sent:
                self.countdown_sent.add(left)
                w.send([stm('msg_sectorcontrol_countdown', '%SECONDS%', left)])
        elif 'start' not in self.countdown_sent:
            self.countdown_sent.add('start')
            w.send([stm('msg_sectorcontrol_match_start')])
        if now >= self.next_step:
            dt = 1.0 if not self.next_step else min(3.0, now - self.next_step + 1.0)
            self.next_step = now + 1.0
            if now >= self.attack_at:
                self.step(now, dt)
            self.repair_step(now, dt)
            if self.ready:
                w.send(self.hud_msgs(now))
            self.participation(now)

    def units(self, now):
        """Who counts in the radii: (company, x, y) of the living, not cloaked pilots (the player and the drafted bots)."""
        w = self.w
        out = []
        if not w.hero_dead and not self.player.get('removed') and not w.hidden(now):
            hx, hy = w.hero_pos(now)
            out.append((self.own, hx, hy))
        for n in w.npcs.values():
            if n.bot is not None and n.alive and n.id in self.stats and not n.__dict__.get('hidden'):
                x, y = n.mover.pos(now)
                out.append((n.bot.company, x, y))
        return out

    def step(self, now, dt):
        units = self.units(now)
        thr = D['capture_threshold']
        for s in self.sectors:
            n = {c: 0 for c in COMPANIES}
            for c, x, y in units:
                if math.hypot(x - s['x'], y - s['y']) <= D['sector_radius']:
                    n[c] += 1
            s['invaders'] = [c for c in COMPANIES if n[c] and c != s['owner']]
            holder = s['owner']                                   # the company that captured it (0: neutral)
            rivals = sorted(((n[c], c) for c in COMPANIES if c != holder), reverse=True)
            top_n, top_c = rivals[0]
            tie = len(rivals) > 1 and rivals[1][0] == top_n
            lead = top_n - (n[holder] if holder else 0)
            if top_n and lead > 0 and not tie:
                speed = capture_speed(lead) * dt
                if s['progress'] > 0 and s['prog_owner'] != top_c:       # first back to neutral (neutral is always in between)
                    s['progress'] = max(0.0, s['progress'] - speed)
                    s['action'] = NEUTRALIZING
                    if s['progress'] <= 0:
                        if s['owner']:
                            self.w.log('   SC: %s neutralized by %s' % (s['id'], NAMES[top_c]))
                        s['owner'], s['prog_owner'] = 0, top_c
                else:
                    s['prog_owner'] = top_c
                    s['progress'] = min(thr, s['progress'] + speed)
                    s['action'] = CAPTURING
                    if s['progress'] >= thr and s['owner'] != top_c:
                        s['owner'] = top_c
                        self.w.log('   SC: %s captured by %s' % (s['id'], NAMES[top_c]))
            elif holder and n[holder] >= top_n or not top_n:
                # nobody pushing: the progress returns to the holder (captured: up to full; a capture from neutral: back to neutral)
                back = capture_speed(1) * dt
                if s['owner'] and s['progress'] < thr:
                    s['prog_owner'] = s['owner']
                    s['progress'] = min(thr, s['progress'] + back)
                    s['action'] = CAPTURING
                elif not s['owner'] and s['progress'] > 0:
                    s['progress'] = max(0.0, s['progress'] - back)
                    s['action'] = NEUTRALIZING
                    if s['progress'] <= 0:
                        s['prog_owner'] = 0
                else:
                    s['action'] = NONE
            else:
                s['action'] = NONE
        # tickets
        held = self.held()
        extra = bleed(held)
        factor = D['late_factor'] if now - self.started_at >= D['late_sec'] else 1
        if factor > 1 and not self.boosted:
            self.boosted = True
            self.w.send([stm('msg_sectorcontrol_ticket_bleed_acceleration', '%FACTOR%', factor)])
        for c in list(held):
            self.tickets[c] -= (D['bleed_base'] + D['bleed_point'] * extra[c]) * factor * dt
        bonus = {c: underdog(held, c) for c in held}
        for n in self.w.npcs.values():
            if n.bot is not None and n.id in self.stats:
                n.damage_bonus = bonus.get(n.bot.company, 0.0)
        self.check_tickets(now)

    def check_tickets(self, now):
        w = self.w
        mine = self.tickets.get(self.own, 0)
        for pct in (25, 10):
            if 0 < mine <= D['tickets'] * pct / 100.0 and pct not in self.warned:
                self.warned.add(pct)
                w.send([stm('msg_sectorcontrol_ticket_warning', '%PERCENTAGE%', pct)])
        for c in list(self.companies):
            if c in self.out or self.tickets[c] > 0:
                continue
            self.out.add(c)
            self.tickets[c] = 0
            w.send([stm('msg_sectorcontrol_team_lost', '%COMPANY%', NAMES[c])])
            w.log('   SC: %s is out' % NAMES[c])
            for s in self.sectors:
                if s['owner'] == c or s['prog_owner'] == c:
                    s.update(owner=0, prog_owner=0, progress=0.0, action=NONE)
            TDM.release_bots(w, [(x['bot'], dict(kills=x['kills'], deaths=x['deaths'])) for x in self.stats.values() if x['company'] == c],
                             self.map, 'sc_done')
            if c == self.own:
                self.end(now, won=False)
                return
        left = [c for c in self.companies if c not in self.out]
        if len(left) <= 1:
            self.end(now, won=left == [self.own])

    def repair_step(self, now, dt):
        """The start area repairs 10,000 HP a second for its company (the player and the bots)."""
        w = self.w
        rate = D['home_repair'] * dt
        if not w.hero_dead:
            hx, hy = w.hero_pos(now)
            sx, sy = self.spawn(self.own)
            g = self.p.d['ship']
            if math.hypot(hx - sx, hy - sy) <= D['home_radius'] and g.get('hitPoints', 0) < g.get('hitMax', 0):
                hp0 = g.get('hitPoints', 0)
                self.p.set_hull(hp=hp0 + rate)
                w.send([w.hp_msg()] + w.heal_msgs(hp0))
        for n in w.npcs.values():
            if n.bot is not None and n.alive and n.id in self.stats:
                x, y = n.mover.pos(now)
                sx, sy = self.spawn(n.bot.company)
                if math.hypot(x - sx, y - sy) <= D['home_radius']:
                    n.hp = min(n.bot.value()['hp'], n.hp + rate)

    def participation(self, now):
        """The capture progress bar follows the sector the player is in (SectorControlCaptureParticipationCommand)."""
        w = self.w
        cur = None
        if not w.hero_dead:
            hx, hy = w.hero_pos(now)
            cur = next((s['id'] for s in self.sectors if math.hypot(hx - s['x'], hy - s['y']) <= D['sector_radius']), None)
        if cur != self.participating:
            msgs = []
            if self.participating:
                msgs.append(('SectorControlCaptureParticipationCommand', {'sectorId': self.participating, 'capturing': False}))
            if cur:
                msgs.append(('SectorControlCaptureParticipationCommand', {'sectorId': cur, 'capturing': True}))
            self.participating = cur
            w.send(msgs)

    # ------------------------------------------------------------ bots
    def bot_think(self, w, n, now):
        """A drafted bot: still in the start area in the countdown; an enemy near it first (the body's combat), otherwise a control point
        its company does not hold (the nearest, kept for a while), back to the start area to repair when badly damaged."""
        from bot import ship as BS
        if self.over:
            return True
        if now < self.attack_at:
            BS._stop(w, n, now)
            return True
        b = n.bot
        nx, ny = n.mover.pos(now)
        d = b.value()
        t = n.target
        if t is not None and (t == w.hid and not w.hero_dead or t in w.npcs and w.npcs[t].alive and w.npcs[t].bot is not None):
            return False
        if (n.hp + n.shield) < 0.3 * (d['hp'] + d['shield']):
            sx, sy = self.spawn(b.company)
            if math.hypot(nx - sx, ny - sy) > D['home_radius'] * 0.6:
                BS._go_to(w, n, sx, sy, now)
            return True
        best = None
        if not w.hero_dead and self.own != b.company and BS.can_attack_player(w, n, w, now):
            hx, hy = w.hero_pos(now)
            best = (math.hypot(hx - nx, hy - ny), w.hid)
        for m in w.npcs.values():
            if m.bot is None or m is n or not m.alive or m.bot.company == b.company:
                continue
            mx, my = m.mover.pos(now)
            dd = math.hypot(mx - nx, my - ny)
            if (best is None or dd < best[0]) and BS.can_attack_bot(w, n, m, now):
                best = (dd, m.id)
        if best is not None and best[0] <= D['bot_engage_range']:
            n.target = best[1]
            return False
        goal = n.__dict__.get('sc_goal')
        if goal is None or now >= n.__dict__.get('sc_goal_until', 0):
            options = [s for s in self.sectors if s['owner'] != b.company or s['action'] != NONE]
            options = options or self.sectors
            goal = min(options, key=lambda s: math.hypot(s['x'] - nx, s['y'] - ny) * random.uniform(0.7, 1.4))
            n.sc_goal, n.sc_goal_until = goal, now + random.uniform(8, 16)
        if math.hypot(goal['x'] - nx, goal['y'] - ny) > D['sector_radius'] * 0.6:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(0, D['sector_radius'] * 0.5)
            BS._go_to(w, n, goal['x'] + math.cos(a) * r, goal['y'] + math.sin(a) * r, now)
        elif best is not None:
            n.target = best[1]
            return False
        return True

    def on_bot_spawn(self, n, now):
        """At its start area: protected in the countdown and, after a respawn, like the in-place repair."""
        import settings as SET
        prot = self.attack_at if now < self.attack_at else (now + SET.get('on_spot_protection') if self.stats[n.id]['deaths'] else 0)
        n.immune_until = prot

    def kill(self, killer, victim):
        k, v = self.stat(killer), self.stat(victim)
        if v is not None:
            v['deaths'] += 1
            if v['company'] in self.tickets and v['company'] not in self.out:
                self.tickets[v['company']] -= 1                 # each kill: one ticket of the victim's company (wiki)
        if k is not None and k is not v and (v is None or k['company'] != v['company']):
            k['kills'] += 1

    def bot_died(self, w, t, killer_uid):
        s = self.stats.get(t.id)
        if s is None:
            return False
        self.kill(killer_uid, t.id)
        s['respawn'] = time.time() + random.uniform(*D['bot_respawn_sec'])
        t.bot.__dict__.pop('carry', None)
        t.bot.k['x'] = t.bot.k['y'] = 0
        self.check_tickets(time.time())
        return 'reward'                                 # the player's kill gives its usual EP and Honor (the bonus is a percentage of them)

    # ------------------------------------------------------------ the player's death and repair
    def hero_killed(self, w, killer, source_player):
        if self.over or w.gate is not self:
            return []
        self.kill(getattr(killer, 'id', None), self.hid)
        death = self.player['deaths']

        def expired():
            """After the 15 s the free respawn is replaced by the X-1 repair (wiki): out of the match without the bonus."""
            if w.hero_dead and w.gate is self and not self.over and death == self.player['deaths']:
                self.player['removed'] = True
                w.send([('KillScreenUpdateCommand', {'options': w.repair_options()})])
                w.log('   SC: the free respawn ran out, out of the match')
        w.later(D['respawn_sec'] + 0.3, expired)
        self.check_tickets(time.time())
        return []

    def on_death(self):
        return None

    def revive(self):
        pass

    def repair_left(self):
        return D['respawn_sec'] - (time.time() - (self.w.death_time or 0)) if self.w is not None and self.w.hero_dead else 0

    def repair_offers(self):
        import world as WD
        if not self.over and not self.player.get('removed') and self.own not in self.out and self.repair_left() > 0:
            return {SC_REPAIR: 0, WD.REPAIR_BASE: 0}
        return {WD.REPAIR_BASE: 0}

    def repair_texts(self, kind):
        left = max(0, int(math.ceil(self.repair_left())))
        return ('desc_killscreen_free_repair_cause_sectorcontrol', 'ttip_killscreen_repair_spawnpoint', 'btn_killscreen_repair_for_free',
                ('desc_killscreen_option_available_countdown_spawnpoint', {'COUNTDOWN': left}) if left else ('', {}))

    def repair(self, kind):
        import settings as SET
        if kind != SC_REPAIR or self.over or self.player.get('removed') or self.repair_left() <= -0.5:
            return None
        self.w.invuln_until = time.time() + SET.get('on_spot_protection')     # the in-place repair's protection (wiki)
        return self.spawn(self.own, 250)

    # ------------------------------------------------------------ end
    def end(self, now, won):
        """The match is over for the player: the winners get the kill statistics and the EP & Honor bonus (a percentage of what they earned
        in the match), everybody goes to X-1."""
        w = self.w
        self.over = True
        msgs = []
        if won:
            msgs.append(stm('msg_sectorcontrol_team_won', '%COMPANY%', NAMES[self.own]))
            k, d = self.player['kills'], self.player['deaths']
            pct = min(D['bonus_max_percent'], D['bonus_percent_per_kill'] * k)
            g = self.p.d['pilot']
            ep, honor = max(0, g.get('ep', 0) - self.ep0), max(0, g.get('honourPoints', 0) - self.honor0)
            ep_b, honor_b = int(ep * pct / 100.0), int(honor * pct / 100.0)
            if ep_b or honor_b:
                tot = self.p.gain(ep=ep_b, honor=honor_b, reason='sector_control')
                msgs += w.reward_msgs(tot, ep=ep_b, honor=honor_b) if hasattr(w, 'reward_msgs') else []
            msgs.append(stm('msg_sectorcontrol_kill_statistics', '%KILLS%', k, '%PERCENTAGE%', pct, '%DEATHS%', d,
                            '%KILL_DEATH_RATIO%', '%.2f' % (k / float(d)) if d else str(k)))
            w.log('   SC: won (%d kills, +%d%% EP %d Honor %d)' % (k, pct, ep_b, honor_b))
        w.send(msgs)
        TDM.release_bots(w, [(s['bot'], dict(kills=s['kills'], deaths=s['deaths'])) for s in self.stats.values()], self.map, 'sc_done')
        w.mode_bots = None
        self.p.pvp_mods = None
        w.later(D['end_sec'], lambda: self.m.match is self and w.running and self.m.home())

    def close(self, why):
        if not self.over:
            self.over = True
            if self.w is not None:
                TDM.release_bots(self.w, [(s['bot'], dict(kills=s['kills'], deaths=s['deaths'])) for s in self.stats.values()],
                                 self.map, 'sc_done')
                self.w.mode_bots = None
        self.p.pvp_mods = None
