"""Team Deathmatch (darkorbitwiki events/team-death-match, 2022-06-08; fandom Team_Deathmatch for the old rules; the client's
TeamDeathMatch* handlers, lobby, status and result windows; flashres tdm_* texts). Research: belgeler/arastirma/PVP_MODLARI.md section 1.

Real rules kept: the battlemaster in every X-1 (asset 43) opens the lobby; level bands 8-13 (map 81, TDM I) and 14+ (map 82, TDM II); three
matches MMO-EIC, EIC-VRU, MMO-VRU, a company in two of them; queued for one match only; at least 3 and at most 8 per side; a confirmation
window when the match can begin (not confirming leaves the queue); 15 minutes or 100 points; +1 point per kill, no friendly fire; 3 lives,
with no life left only the X-1 repair; a 20 s start phase in which nobody can attack and leaving the start zone is radiation; the death screen's
free repair at the TDM spawn (TDM_REPAIR) within 15 s of the death, otherwise out of the match, and 20 s attack protection after it;
the exit point (asset 44) at the spawn leaves at
any time without a reward; a draw: both teams lose; a side without opponents for 30 s ends without a reward; the result window (30 s) with
K/D, point delta, damage, peak damage, winning streak and the reward; the reward by kills, a loser reward when kills <= deaths (once per
match); the company with the most match points over the event gets +10% ore price, +10% bonus box content (not energy) and +10% EP from kills
for 24 hours (not in the booster list); levelling past the band while queued leaves the queue; the TDM kill achievement (200/500/1000).
Single-player adaptation (labelled in data/extra_events.json "_adaptation"): the other pilots are the bot players of the band (bot/; offline
ones log in for the event), the matches the player is not in are simulated (lobby rows and the event score), the reward amounts, the queue
fill speed, the confirmation seconds, the spawn and battlemaster positions and the start-zone radius are not published.
"""
import math, random, time

import event_calendar as CAL
import game_data as DATA
import map_links as H
from legacy_protocol import stm

EVENT = 'team_deathmatch'
D = DATA.load('extra_events.json').get('team_deathmatch', {})
BATTLEMASTER, EXIT_POINT = 43, 44                # AssetTypeModule (TEAMDEATHMATCH_BATTLEMASTER / _EXIT_POINT)
TDM_REPAIR = 8                                    # KillScreenOptionTypeModule.TDM_REPAIR
ASSET_BASE = 158800000                            # + map (battlemaster), + 1000 + faction (exit point)
MATCH_MAKING, RUNNING = 0, 1                      # TeamDeathMatchOverviewModule.MatchState
WIN, LOSE, NO_LIFES_LEFT, DRAW = 0, 1, 2, 3       # TeamDeathMatchResultScreenCommand.ResultState
ERR_LEVEL, ERR_NO_MATCH, ERR_ENDED = 0, 2, 3      # ErrorType (1 QUEUE_FULL opens an empty window in the client: never sent)
PAIRS = {1: (1, 2), 2: (2, 3), 3: (1, 3)}          # match id -> companies (wiki: MMO-EIC, EIC-VRU, MMO-VRU)
NEAR = 600                                        # the asset's action range (the client's MapAssetActionAvailable, like the CBS)


def mod(_name, **f):
    f['_'] = _name
    return f


def faction(c):
    return mod('FactionModule', faction=int(c))


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


def x1_maps():
    return {1: 1, 2: 5, 3: 9}                     # the companies' X-1 (galaxy_gates.HOME_MAP)


def battlemaster_pos(station, w, h):
    """Next to the X-1 station, towards the middle of the map (adaptation: the position is not published)."""
    sx, sy = station['posX'], station['posY']
    a = math.atan2(h / 2.0 - sy, w / 2.0 - sx)
    d = D.get('battlemaster_distance', 1500)
    return int(sx + math.cos(a) * d), int(sy + math.sin(a) * d)


def asset_cmd(aid, kind, x, y, name, company=0):
    return ('AssetCreateCommand', dict(designId=0, clanId=0, showBubble=True, userName=name, assetId=aid, expansionStage=0, modifier=[],
                                       type=mod('AssetTypeModule', typeValue=kind), detectedByWarnRadar=False, invisible=False, posY=int(y),
                                       clanRelation=mod('ClanRelationModule', type=0), clanTag='', factionId=int(company), posX=int(x),
                                       visibleOnWarnRadar=False))


def asset_available(aid, tip, near):
    return H.asset_available(aid, tip, near)


# ------------------------------------------------------------------------------------------------ event state (the save)
def state(p, now=None):
    """p.d['tdm']: this event period's company scores, the simulated matches, the player's TDM kills (achievement) and the company reward."""
    now = now or time.time()
    st = p.d.setdefault('tdm', {})
    span = CAL.period(EVENT, now) if active(now) else None
    key = time.strftime('%Y-%m-%d', time.localtime(span[0])) if span else time.strftime('%Y', time.localtime(now)) if active(now) else None
    if key and st.get('period') != key:
        st.update(period=key, overall={'1': 0, '2': 0, '3': 0}, matches={}, settled=None)
        p.dirty = True
    st.setdefault('overall', {'1': 0, '2': 0, '3': 0})
    st.setdefault('matches', {})
    return st


def sim(st, now, own=None):
    """The matches the player is not in (bot teams): MATCH_MAKING for a few minutes, then RUNNING for at most 15 minutes or 100 points; the
    finished match's points go to the companies' event score. own: the player's match id (not simulated)."""
    rng = random.Random()
    for mid in PAIRS:
        m = st['matches'].setdefault(str(mid), {'state': MATCH_MAKING, 'until': now + rng.uniform(30, 240), 'queue': [0, 0]})
        if mid == own:
            continue
        if now - m.get('seen', now) > 1800:              # the server was off: the matches start over (no score from the gap)
            m.update(state=MATCH_MAKING, until=now + rng.uniform(30, 240), queue=[0, 0])
        m['seen'] = now
        for _ in range(4):
            if m['state'] == MATCH_MAKING:
                m['queue'] = [min(D['team_max'], int(D['team_max'] * (1 - (m['until'] - now) / 300.0) + rng.random())) for _ in (0, 1)]
                m['queue'] = [max(0, q) for q in m['queue']]
                if now < m['until']:
                    break
                m.update(state=RUNNING, start=m['until'], end=m['until'] + D['match_sec'], rates=[rng.uniform(0.03, 0.10), rng.uniform(0.03, 0.10)],
                         points=[0, 0], size=[rng.randint(D['team_min'], D['team_max']) for _ in (0, 1)])
            if m['state'] == RUNNING:
                t = min(now, m['end']) - m['start']
                m['points'] = [min(D['max_score'], int(r * t)) for r in m['rates']]
                if now < m['end'] and max(m['points']) < D['max_score']:
                    break
                a, b = PAIRS[mid]
                st['overall'][str(a)] += m['points'][0]
                st['overall'][str(b)] += m['points'][1]
                m.update(state=MATCH_MAKING, until=max(now, m['end']) + rng.uniform(120, 360), queue=[0, 0])
                m.pop('rates', None)
    return st


def bonus_active(p, now=None):
    return (now or time.time()) < p.d.get('tdm', {}).get('bonus_until', 0)


def company_mods(p):
    """The winning company's 24-hour reward (wiki): +10% ore price, +10% bonus box content (not extra energy), +10% EP from kills."""
    if not bonus_active(p):
        return {}
    r = D.get('company_reward', {})
    return {'ep': r.get('ep', 0.1), 'ore_price': r.get('ore_price', 0.1), 'bonus_box_extra': r.get('bonus_box', 0.1)}


def reward_for(kills, deaths):
    """The personal reward (adaptation: the wiki gives only "more kills, better reward" and a loser reward when kills <= deaths)."""
    if kills <= deaths:
        return [tuple(x) for x in D['rewards']['loser']]
    best = []
    for need, items in D['rewards']['tiers']:
        if kills >= need:
            best = items
    return [tuple(x) for x in best]


def pick_bots(company, b, level, now, taken):
    """The bot pilots of a company who can be drafted into a mode match (not dead, not in a gate, mode or duel): those in the level band
    first (online ones first), then the nearest levels (a young bot pack has few pilots in the band; adaptation)."""
    import bot.manager as MGR
    y = MGR.ACTIVE
    if y is None or not y.permission('pvp'):
        return []
    band, rest = [], []
    with y.lock:
        for x in y.bots:
            busy = x.target is not None and x.target.name in ('gate', 'mod', 'duel', 'pvp_match') and not x.plan.get('finished')
            if x.company != company or x.dead_until > now or busy or x.uid in taken:
                continue
            (band if b['min_level'] <= x.level <= b['max_level'] else rest).append(x)
    random.shuffle(band)
    band.sort(key=lambda x: not x.online)            # those online first; offline ones log in for the event
    lv = level
    rest.sort(key=lambda x: (abs(x.level - lv), not x.online, random.random()))
    return band + rest                               # too few pilots in the band (a young bot pack): the nearest levels fill in (adaptation)


def draft_bots(bots, map_id, now, hold_sec):
    """The bots join a mode match: offline ones log in, their ship elsewhere goes, they move to the mode map (the match places their ships at
    its spawns) with the pvp_match goal (the brain keeps it until the match ends), their session lasts at least hold_sec."""
    import bot.manager as MGR
    from bot import abstract_sim as S
    from bot.brain import GOALS
    y = MGR.ACTIVE
    with y.lock:
        for b in bots:
            if not b.online:
                y.entry(b, now, silent=True)
            if b.body is not None and b.body.alive:
                b.body.alive = False                   # its ship on another map goes (that world removes it)
            b.body = None
            S.jump_to(b, map_id, y, now)
            b.k['x'] = b.k['y'] = 0
            b.en_route = None
            b.target, b.goal_start, b.plan = GOALS['pvp_match'], now, {'min': 3600 * 3, 'match': map_id}
            b.k['target'] = 'pvp_match'
            b.session_end = max(b.session_end, now + hold_sec)
            b.__dict__.pop('carry', None)


def release_bots(w, bots, map_id, event):
    """The drafted bots leave the mode map: their ships go, they return to their X-1 and decide again. bots: [(bot, event fields)]."""
    import bot.manager as MGR
    from bot import abstract_sim as S
    from bot import catalog as K
    from bot import ship as BS
    y = MGR.ACTIVE
    uids = {b.uid for b, _ in bots}
    msgs = []
    if w is not None:
        for n in [n for n in w.npcs.values() if n.bot is not None and n.id in uids]:
            msgs += BS.remove(w, n)
    if y is not None:
        with y.lock:
            for b, f in bots:
                b.plan['finished'] = True
                b.target = None
                b.k['target'] = None
                b.__dict__.pop('carry', None)
                if int(b.k['map']) == int(map_id):
                    S.jump_to(b, K.ev(b.company), y, time.time())
                b.next_decision = time.time()
                b.event(event, **f)
    if w is not None and msgs:
        w.send(msgs)


# ------------------------------------------------------------------------------------------------ the session's system
class TeamDeathmatch:
    REQUESTS = ('TeamDeathMatchOverviewInitRequest', 'TeamDeathMatchDetailRequest', 'TeamDeathMatchJoinRequest',
                'TeamDeathMatchLeaveQueueRequest', 'TeamDeathMatchDraftConfirmationRequest', 'TeamDeathMatchExitRequest')

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.change_map = None        # the session binds: (map, portal, position)
        self.queued = -1              # the match id in the queue (-1: none)
        self.queue = None             # {'own': [bots], 'opp': [bots], 'at': t, 'next': t, 'draft': t or None}
        self.match = None             # the running Match
        self.near = None              # the asset in range (battlemaster / exit point)
        self.pending = None           # after the result: (time, function) back to base

    # ------------------------------------------------------------ lobby
    def level(self):
        return int(self.p.d['pilot'].get('level', 1))

    def company(self):
        return int(self.p.d['pilot'].get('factionId') or 1)

    def overview(self, init=False):
        now = time.time()
        st = sim(state(self.p, now), now, self.own_match())
        b = bracket(self.level()) or D['brackets'][0]
        rows = []
        c = self.company()
        for mid, pair in PAIRS.items():
            if c not in pair:
                continue
            m = st['matches'][str(mid)]
            side = pair.index(c)
            opp = pair[1 - side]
            if mid == self.queued and self.queue is not None:
                own_n, opp_n = 1 + len(self.queue['own']), len(self.queue['opp'])
                rows.append(mod('TeamDeathMatchOverviewModule', matchId=mid, opponent=faction(opp), matchState=MATCH_MAKING,
                                playersInOwnTeam=own_n, maxPlayerPerTeam=D['team_max'], pointsOfOwnTeam=0, pointsOfOpponentTeam=0,
                                playersInQueue=own_n + opp_n))
                continue
            if self.match is not None and self.match.mid == mid:
                g = self.match
                rows.append(mod('TeamDeathMatchOverviewModule', matchId=mid, opponent=faction(opp), matchState=RUNNING,
                                playersInOwnTeam=len(g.team(g.own)), maxPlayerPerTeam=D['team_max'], pointsOfOwnTeam=g.score[g.own],
                                pointsOfOpponentTeam=g.score[g.opp], playersInQueue=0))
                continue
            running = m['state'] == RUNNING
            pts = m.get('points', [0, 0]) if running else [0, 0]
            size = m.get('size', [0, 0]) if running else m.get('queue', [0, 0])
            rows.append(mod('TeamDeathMatchOverviewModule', matchId=mid, opponent=faction(opp), matchState=m['state'],
                            playersInOwnTeam=size[side], maxPlayerPerTeam=D['team_max'], pointsOfOwnTeam=pts[side],
                            pointsOfOpponentTeam=pts[1 - side], playersInQueue=0 if running else sum(m.get('queue', [0, 0]))))
        return ('TeamDeathMatchOverviewInitCommand' if init else 'TeamDeathMatchOverviewCommand',
                dict(minLevel=b['min_level'], maxLevel=b['max_level'], queuedForMatch=self.queued, overviewModules=rows))

    def own_match(self):
        if self.match is not None:
            return self.match.mid
        return self.queued if self.queued > 0 and self.queue is not None else None

    def detail(self, mid):
        now = time.time()
        st = sim(state(self.p, now), now, self.own_match())
        pair = PAIRS.get(mid)
        c = self.company()
        if pair is None or c not in pair:
            return [('TeamDeathMatchErrorCommand', {'errorType': ERR_NO_MATCH})]
        side = pair.index(c)
        m = st['matches'][str(mid)]
        own_n = opp_n = 0
        pts, left = [0, 0], D['match_sec']
        if self.match is not None and self.match.mid == mid:
            g = self.match
            own_n, opp_n, pts, left = len(g.team(g.own)), len(g.team(g.opp)), [g.score[g.own], g.score[g.opp]], int(g.left(now))
            side = 0
        elif mid == self.queued and self.queue is not None:
            own_n, opp_n, side = 1 + len(self.queue['own']), len(self.queue['opp']), 0
        elif m['state'] == RUNNING:
            own_n, opp_n = m['size'][side], m['size'][1 - side]
            pts, left = m['points'], int(max(0, m['end'] - now))
        else:
            own_n, opp_n = m['queue'][side], m['queue'][1 - side]
        if side and not (self.match is not None and self.match.mid == mid):
            pts = [pts[1], pts[0]]
        return [('TeamDeathMatchDetailCommand', dict(
            matchId=mid, ownFaction=faction(c), opponentFaction=faction(pair[1 - pair.index(c)]), playersInOwnTeam=own_n,
            playersInOpponentTeam=opp_n, pointsOfOwnTeam=pts[0], pointsOfOpponentTeam=pts[1], minPlayersPerTeam=D['team_min'],
            maxPlayersPerTeam=D['team_max'], remainingTimeInSecs=left, maxTimeInSecs=D['match_sec']))]

    def join(self, mid):
        now = time.time()
        b = bracket(self.level())
        if b is None:
            return [('TeamDeathMatchErrorCommand', {'errorType': ERR_LEVEL})]
        pair = PAIRS.get(mid)
        if pair is None or self.company() not in pair:
            return [('TeamDeathMatchErrorCommand', {'errorType': ERR_NO_MATCH})]
        if self.match is not None:
            return []
        if self.world is not None and (getattr(self.world, 'gate', None) is not None or getattr(self.world, 'low', None)):
            return [(stm('msg_tdm_kicked_from_queue'))]          # GG, LoW, mode maps: no queue (wiki)
        self.leave_queue()
        self.queued = mid
        self.queue = {'own': [], 'opp': [], 'at': now, 'next': now + random.uniform(*D['queue_fill_sec']), 'draft': None,
                      'band': b['map'], 'opp_company': pair[1 - pair.index(self.company())]}
        st = sim(state(self.p, now), now)
        m = st['matches'][str(mid)]
        if m['state'] == RUNNING and now - m.get('start', 0) < 30:      # it began just as the pilot joined (the lobby showed it waiting)
            m.update(state=MATCH_MAKING, until=now + 300)
            m.pop('rates', None)
        if m['state'] == RUNNING:
            self.queue['wait'] = m['end']               # the match runs: the queue waits for its end (Detail shows the time left)
        else:                                           # the pilots already queued (the lobby row) stay: real bots take their places
            side = pair.index(self.company())
            have = m.get('queue', [0, 0])
            for key, company, n in (('own', self.company(), min(have[side], D['team_max'] - 1)),
                                    ('opp', self.queue['opp_company'], min(have[1 - side], D['team_max']))):
                taken = {x.uid for x in self.queue['own'] + self.queue['opp']}
                self.queue[key] += self.candidates(company, b, now, taken)[:n]
        self.log('   TDM: queued for match %d (%s)' % (mid, H.name(b['map'])))
        return [self.overview(), (stm('tdm_queue_position', '%POSITION%', 1))]

    def leave_queue(self):
        if self.queue is not None:
            self.log('   TDM: left the queue')
        self.queued, self.queue = -1, None

    def handle(self, name, f):
        if not active():
            return [('TeamDeathMatchErrorCommand', {'errorType': ERR_ENDED})] if name != 'TeamDeathMatchExitRequest' else self.exit()
        if name == 'TeamDeathMatchOverviewInitRequest':
            # the client only stores the Init (and opens the lobby or the level window); the rows and the title come with the update
            return [self.overview(init=True), self.overview()]
        if name == 'TeamDeathMatchDetailRequest':
            return self.detail(int(f.get('matchId', -1)))
        if name == 'TeamDeathMatchJoinRequest':
            return self.join(int(f.get('matchId', -1)))
        if name == 'TeamDeathMatchLeaveQueueRequest':
            self.leave_queue()
            return [self.overview()]
        if name == 'TeamDeathMatchDraftConfirmationRequest':
            return self.confirm(bool(f.get('accepted')))
        if name == 'TeamDeathMatchExitRequest':
            return self.exit()
        return []

    # ------------------------------------------------------------ queue -> match
    def candidates(self, company, b, now, taken):
        return pick_bots(company, b, self.level(), now, taken)

    def fill(self, now):
        """Bots of the band join the queue one by one (adaptation: 2-6 s apart); with at least 3 per side and the team full (or after the
        fill wait) the confirmation window comes."""
        q = self.queue
        if q is None or q['draft'] is not None:
            return []
        if bracket(self.level()) is None or bracket(self.level())['map'] != q['band']:
            self.leave_queue()                            # levelled past the band while queued (wiki)
            return [self.overview()]
        if now < q.get('wait', 0) or now < q['next']:
            return []
        q['next'] = now + random.uniform(*D['queue_fill_sec'])
        b = bracket(self.level())
        taken = {x.uid for x in q['own'] + q['opp']}
        for side, company, room in (('own', self.company(), D['team_max'] - 1), ('opp', q['opp_company'], D['team_max'])):
            if len(q[side]) < room:
                c = self.candidates(company, b, now, taken)
                if c:
                    q[side].append(c[0])
                    taken.add(c[0].uid)
        full = len(q['own']) >= D['team_max'] - 1 and len(q['opp']) >= D['team_max']
        enough = 1 + len(q['own']) >= D['team_min'] and len(q['opp']) >= D['team_min']
        if enough and (full or now - max(q['at'], q.get('wait', 0)) >= D['fill_wait_sec']):
            q['draft'] = now
            self.log('   TDM: match ready %d v %d, confirmation' % (1 + len(q['own']), len(q['opp'])))
            return [('TeamDeathMatchDraftConfirmationCommand', {'seconds': D['draft_sec']}), self.overview()]
        return [self.overview()]

    def confirm(self, accepted):
        q = self.queue
        if q is None or q['draft'] is None:
            return []
        if not accepted:
            self.leave_queue()
            return [self.overview()]
        return self.start()

    def start(self):
        import bot.manager as MGR
        q = self.queue
        now = time.time()
        b = bracket(self.level())
        y = MGR.ACTIVE
        self.leave_queue()
        if b is None or y is None:
            return [('TeamDeathMatchErrorCommand', {'errorType': ERR_ENDED})]
        mid = next(k for k, v in PAIRS.items() if self.company() in v and q['opp_company'] in v)
        self.match = Match(self, mid, b['map'], self.company(), q['opp_company'], q['own'], q['opp'], now)
        self.log('   TDM: match %d starts on %s' % (mid, H.name(b['map'])))
        x, yy = self.match.spawn(self.company())
        if self.change_map:
            self.change_map(b['map'], None, (x, yy))
        return []

    def exit(self):
        """The exit point (or the logout window): leaves the match at once, without a reward (wiki); the result window is shown."""
        g = self.match
        if g is None:
            return []
        if not g.over and self.world is not None:
            self.world.send([g.result_cmd(LOSE, rewards=[])])      # before the jump (the window stays open on X-1)
        g.close('left')
        self.home()
        return []

    def home(self):
        self.match = None
        if self.change_map and self.world is not None and on_map(self.world.map_id):
            self.change_map(x1_maps().get(self.company(), 1), None, 'station')

    # ------------------------------------------------------------ world
    def attach(self, world):
        self.world = world
        self.near = None
        msgs = []
        if world.gate is not None and self.queue is not None and not on_map(world.map_id):
            self.leave_queue()                            # a gate or mode map: the queue is cancelled (wiki)
            msgs.append((stm('msg_tdm_kicked_from_queue')))
        if on_map(world.map_id):
            g = self.match
            if g is None or g.over or g.map != int(world.map_id):
                self.match = None
                world.later(2.0, lambda: self.change_map and self.world is world and self.change_map(
                    x1_maps().get(self.company(), 1), None, 'station'))
                return msgs
            g.attach(world)
            return msgs + g.enter_msgs()
        if self.match is not None:                         # left the TDM map another way (repair at X-1, logout)
            self.match.close('left')
            self.match = None
        if active() and int(world.map_id) in x1_maps().values() and world.station:
            x, y = battlemaster_pos(world.station, world.map_w, world.map_h)
            msgs.append(asset_cmd(ASSET_BASE + int(world.map_id), BATTLEMASTER, x, y, 'Team Deathmatch'))
        return msgs

    def on_ready(self):
        """The map is loaded (ReadyRequest): the match's status window can open now."""
        g, w = self.match, self.world
        if g is not None and w is not None and g.w is w and not g.over:
            g.ready = True
            w.send([g.status_cmd()])
        return []

    def tick(self, now):
        msgs = []
        st = state(self.p, now)
        if active(now):
            sim(st, now, self.own_match())
            msgs += self.fill(now)
            q = self.queue
            if q is not None and q['draft'] is not None and now - q['draft'] > D['draft_sec'] + 5:
                self.leave_queue()                        # no answer: out of the queue (the client sends false itself when its timer ends)
                msgs.append(self.overview())
        else:
            if self.queue is not None:
                self.leave_queue()
            msgs += self.settle(st, now)
        w = self.world
        if w is not None and not w.hero_dead:
            msgs += self.near_step(w, now)
        return msgs

    def near_step(self, w, now):
        hx, hy = w.hero_pos(now)
        near = None
        if on_map(w.map_id) and self.match is not None:
            x, y = self.match.spawn(self.company())
            if math.hypot(hx - x, hy - y) <= NEAR:
                near = (ASSET_BASE + 1000 + self.company(), 'tdm_popup_leavegame_title')
        elif active() and int(w.map_id) in x1_maps().values() and w.station:
            x, y = battlemaster_pos(w.station, w.map_w, w.map_h)
            if math.hypot(hx - x, hy - y) <= NEAR:
                near = (ASSET_BASE + int(w.map_id), 'tdm_register')
        if near == self.near:
            return []
        msgs = []
        if self.near:
            msgs.append(asset_available(self.near[0], self.near[1], False))
        if near:
            msgs.append(asset_available(near[0], near[1], True))
        self.near = near
        return msgs

    def settle(self, st, now):
        """The event is over: the company with the most match points (a tie: nobody) gets the 24-hour reward (wiki)."""
        if not st.get('period') or st.get('settled') == st['period']:
            return []
        st['settled'] = st['period']
        self.p.dirty = True
        top = max(st['overall'].values()) if st['overall'] else 0
        leaders = [c for c, v in st['overall'].items() if v == top]
        if top <= 0 or len(leaders) != 1:
            return []
        if int(leaders[0]) == self.company():
            st['bonus_until'] = now + D.get('company_reward', {}).get('hours', 24) * 3600
            self.log('   TDM: own company won the event, +10%% reward for 24 h')
        return []

    def on_kill(self, w, npc, x, y):
        return []


# ------------------------------------------------------------------------------------------------ the match (the world's gate)
class Match:
    key = 'tdm'
    team_mode = True                  # companies are the teams: no friendly fire; drafted bots follow bot_think
    plain_base_repair = True          # the death screen's X-1 repair keeps its usual text (not the Galaxy Gate one)

    def __init__(self, mode, mid, map_id, own, opp, own_bots, opp_bots, now):
        self.m, self.mid, self.map, self.own, self.opp = mode, mid, int(map_id), own, opp
        self.g = {'name': 'Team Deathmatch'}
        self.w = None
        self.created = now
        self.begin = None                 # the start phase begins once the player is on the map
        self.score = {own: 0, opp: 0}
        self.over = False
        self.result_sent = False
        self.alone_since = None
        self.next_status = 0.0
        # the status window opens by itself on the first StatusUpdate; one that arrives while the map loads opens it hidden (live test):
        # the updates start once the map is loaded (on_ready)
        self.ready = False
        self.p = mode.p
        self.hid = None
        self.stats = {}                   # uid -> {name, company, bot, kills, deaths, lives, given, taken, peak, streak, best, respawn}
        name = self.p.d['pilot'].get('userName', '')
        self.player = {'name': name, 'company': own, 'bot': None, 'kills': 0, 'deaths': 0, 'lives': D['lives'], 'given': 0, 'taken': 0,
                       'peak': 0, 'streak': 0, 'best': 0, 'respawn': 0}
        self.enroll(own_bots + opp_bots, now)

    # ------------------------------------------------------------ roster
    def enroll(self, bots, now):
        draft_bots(bots, self.map, now, D['match_sec'] + 900)
        for b in bots:
            self.stats[b.uid] = {'name': b.name, 'company': b.company, 'bot': b, 'kills': 0, 'deaths': 0, 'lives': D['lives'],
                                 'given': 0, 'taken': 0, 'peak': 0, 'streak': 0, 'best': 0, 'respawn': 0}

    def team(self, company):
        out = [u for u, s in self.stats.items() if s['company'] == company]
        if company == self.own:
            out.append('hero')
        return out

    def roster(self, now):
        """The bots that should have a ship on the map now (alive, lives left, respawn time passed, online)."""
        if self.over:
            return {}
        return {u: s['bot'] for u, s in self.stats.items() if s['lives'] > 0 and now >= s['respawn'] and s['bot'].online}

    def spawn(self, company, scatter=0):
        sp = D['spawn']['own' if company == self.own else 'opp']
        if not scatter:
            return int(sp[0]), int(sp[1])
        a, r = random.uniform(0, 2 * math.pi), random.uniform(0, scatter)
        return int(sp[0] + math.cos(a) * r), int(sp[1] + math.sin(a) * r)

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
        world.damage_hooks.append(self.hero_hit)
        if self.begin is None:
            self.begin = time.time()
            self.attack_at = self.begin + D['start_phase_sec']
            self.end = self.attack_at + D['match_sec']
            world.invuln_until = max(world.invuln_until, self.attack_at)

    def enter_msgs(self):
        msgs = [asset_cmd(ASSET_BASE + 1000 + c, EXIT_POINT, *self.spawn(c), name='', company=c) for c in (self.own, self.opp)]
        if time.time() < self.attack_at:
            msgs.append((stm('tdm_no_attack_phase')))
        return msgs

    def left(self, now):
        if self.begin is None:
            return D['match_sec']
        return max(0, min(D['match_sec'], self.end - max(now, self.attack_at)))

    def overall(self):
        st = state(self.p)
        sc = dict(st['overall'])
        return [mod('FactionScoreModule', faction=faction(c), score=int(sc.get(str(c), 0)) + (self.score.get(c, 0) if not self.over else 0))
                for c in (1, 2, 3)]

    def status_cmd(self, now=None):
        now = now or time.time()
        return ('TeamDeathMatchStatusUpdateCommand', dict(
            currentFactionScores=[mod('FactionScoreModule', faction=faction(c), score=self.score[c]) for c in (self.own, self.opp)],
            maxScore=D['max_score'], remainingLifes=self.player['lives'], remainingSeconds=int(self.left(now)),
            initSeconds=D['match_sec'], overallEventScores=self.overall()))

    def safe_at(self, x, y, now):
        """Start phase: outside the start zone is radiation (flashres tdm_no_attack_phase_radiation)."""
        if self.begin is None or now >= self.attack_at:
            return True
        sx, sy = self.spawn(self.own)
        inside = math.hypot(x - sx, y - sy) <= D['start_zone_radius']
        if not inside and not getattr(self, '_warned', False):
            self._warned = True
            self.w.send([(stm('tdm_no_attack_phase_radiation'))])
        elif inside:
            self._warned = False
        return inside

    def tick(self, now):
        w = self.w
        if w is None or self.begin is None:
            return
        if self.over:
            return
        if not getattr(self, 'attack_sent', False) and now >= self.attack_at:
            self.attack_sent = True
            w.send([(stm('tdm_attack_phase'))])
            w.log('   TDM: attack phase')
        if self.ready and now >= self.next_status:
            self.next_status = now + 1.0
            w.send([self.status_cmd(now)])
        if now >= self.attack_at:
            mine = self.player['lives'] > 0 or any(s['lives'] > 0 for s in self.stats.values() if s['company'] == self.own)
            theirs = any(s['lives'] > 0 and s['bot'].online for s in self.stats.values() if s['company'] == self.opp)
            if not (mine and theirs):
                self.alone_since = self.alone_since or now
                if now - self.alone_since >= D['no_opponent_sec']:
                    return self.finish(now, no_opponent=True)
            else:
                self.alone_since = None
        if now >= self.end or max(self.score.values()) >= D['max_score']:
            self.finish(now)

    # ------------------------------------------------------------ bots
    def bot_think(self, w, n, now):
        """The drafted bot's ship: still at the spawn in the start phase; then on the nearest enemy (the player or an enemy bot); the body's
        default combat (approach, fire, abilities) does the rest. -> True when the match moved it (the default behavior is skipped)."""
        from bot import ship as BS
        if self.over:
            return True
        if now < self.attack_at:
            BS._stop(w, n, now)
            return True
        t = n.target
        if t is not None and (t == w.hid and not w.hero_dead or t in w.npcs and w.npcs[t].alive and w.npcs[t].bot is not None):
            return False
        nx, ny = n.mover.pos(now)
        best = None
        if (not w.hero_dead and int(self.p.d['pilot'].get('factionId') or 0) != n.bot.company
                and BS.can_attack_player(w, n, w, now)):
            hx, hy = w.hero_pos(now)
            best = (math.hypot(hx - nx, hy - ny), w.hid)
        for m in w.npcs.values():
            if m.bot is None or m is n or not m.alive or m.bot.company == n.bot.company:
                continue
            mx, my = m.mover.pos(now)
            d = math.hypot(mx - nx, my - ny)
            if (best is None or d < best[0]) and BS.can_attack_bot(w, n, m, now):
                best = (d, m.id)
        if best is not None:
            n.target = best[1]
            return False
        BS._go_to(w, n, w.map_w // 2 + random.randint(-800, 800), w.map_h // 2 + random.randint(-600, 600), now)
        return True

    def on_bot_spawn(self, n, now):
        """A drafted bot's ship appears at its team's spawn: full HP, attack protection in the start phase or for 20 s after a respawn."""
        n.immune_until = max(self.attack_at, now + (D['respawn_protection_sec'] if self.stats[n.id]['deaths'] else 0))
        n.damage_hook = lambda dmg, uid=n.id: self.hit(self.hid, uid, dmg)

    def hit(self, src, dst, dmg):
        a, b = self.stat(src), self.stat(dst)
        if dmg <= 0:
            return
        if a is not None:
            a['given'] += int(dmg)
            a['peak'] = max(a['peak'], int(dmg))
        if b is not None:
            b['taken'] += int(dmg)

    def hero_hit(self, w, dmg, attacker, source_player):
        uid = getattr(attacker, 'id', None)
        self.hit(uid, self.hid, dmg)
        return []

    def kill(self, killer, victim):
        """killer / victim: uids ('hero' or the player's id for the player). +1 point to the killer's team."""
        k, v = self.stat(killer), self.stat(victim)
        if v is not None:
            v['deaths'] += 1
            v['lives'] = max(0, v['lives'] - 1)
            v['streak'] = 0
        if k is not None and k is not v and (v is None or k['company'] != v['company']):
            k['kills'] += 1
            k['streak'] += 1
            k['best'] = max(k['best'], k['streak'])
            self.score[k['company']] = self.score.get(k['company'], 0) + 1
            if k is self.player:
                st = state(self.p)
                st['kills'] = st.get('kills', 0) + 1
                self.p.ach('tdm_kill')
        if self.w is not None and self.ready:
            self.w.send([self.status_cmd()])

    def bot_died(self, w, t, killer_uid):
        """A drafted bot's ship was destroyed (by the player, a bot or anything): no real death (no abstract death penalty); while it has
        lives it takes the free TDM repair within the 15 s window like a player (adaptation: after 3-10 s) and comes back at its spawn."""
        s = self.stats.get(t.id)
        if s is None:
            return False
        self.kill(killer_uid, t.id)
        s['respawn'] = time.time() + random.uniform(*D['bot_respawn_sec'])
        t.bot.__dict__.pop('carry', None)                 # respawns with full HP
        t.bot.k['x'] = t.bot.k['y'] = 0
        w.log('   TDM: %s destroyed (%d lives left)' % (s['name'], s['lives']))
        return True

    def bot_hit(self, src, dst, dmg):
        self.hit(src, dst, dmg)

    # ------------------------------------------------------------ the player's death and repair (world hooks)
    def hero_killed(self, w, killer, source_player):
        if self.over or w.gate is not self:
            return []
        self.kill(getattr(killer, 'id', None), self.hid)
        w.log('   TDM: player destroyed (%d lives left)' % self.player['lives'])
        if self.player['lives'] <= 0:
            self.player_out()
            return []

        def expired():
            """The 15 s of the free TDM repair are over (flashres ttip_killscreen_logout_tdm: "If time is up ... you'll be removed from the
            TDM server"): out of the match without a reward; only the X-1 repair is left."""
            if w.hero_dead and w.gate is self and not self.over and death == self.player['deaths']:
                self.player['removed'] = True
                self.result_sent = True
                w.send([self.result_cmd(LOSE, rewards=[]), ('KillScreenUpdateCommand', {'options': w.repair_options()})])
                w.log('   TDM: the repair window ran out, removed from the match')
        death = self.player['deaths']                # a timer of an earlier death does nothing
        w.later(D['respawn_sec'] + 0.3, expired)
        return []

    def on_death(self):
        return None

    def revive(self):
        pass

    def repair_offers(self):
        import world as WD
        if self.player['lives'] > 0 and not self.over and not self.player.get('removed') and self.repair_left() > 0:
            return {TDM_REPAIR: 0, WD.REPAIR_BASE: 0}
        return {WD.REPAIR_BASE: 0}

    def repair_left(self):
        """Seconds left to take the free TDM repair (15 s from the death; flashres desc_killscreen_option_available_countdown_tdm)."""
        return D['respawn_sec'] - (time.time() - (self.w.death_time or 0)) if self.w is not None and self.w.hero_dead else 0

    def repair_texts(self, kind):
        left = max(0, int(math.ceil(self.repair_left())))
        return (('desc_killscreen_free_repair_cause_tdm', {'COUNT': self.player['lives']}), 'ttip_killscreen_repair_tdm',
                'btn_killscreen_repair_for_free',
                ('desc_killscreen_option_available_countdown_tdm', {'COUNTDOWN': left}) if left else ('', {}))

    def repair(self, kind):
        if kind != TDM_REPAIR or self.player['lives'] <= 0 or self.over or self.player.get('removed') or self.repair_left() <= -0.5:
            return None
        self.w.invuln_until = time.time() + D['respawn_protection_sec']      # 20 s attack protection after the respawn (wiki)
        return self.spawn(self.own, 200)

    # ------------------------------------------------------------ end
    def player_out(self):
        """No life left: the result window (NO_LIFES_LEFT) and the reward now; the death screen offers only the X-1 repair."""
        self.result_sent = True
        self.w.send([self.result_cmd(NO_LIFES_LEFT, rewards=self.pay())])

    def pay(self):
        rewards = reward_for(self.player['kills'], self.player['deaths'])
        msgs = []
        for loot, n in rewards:
            msgs += self.m.m.reward(loot, n) or []
        if msgs and self.w is not None:
            self.w.send(msgs)
        self.paid = True
        return rewards

    def finish(self, now, no_opponent=False):
        self.over = True
        a, b = self.score[self.own], self.score[self.opp]
        if no_opponent:
            state_ = WIN if self.player['lives'] > 0 or any(s['lives'] > 0 for s in self.stats.values() if s['company'] == self.own) else LOSE
        else:
            state_ = WIN if a > b else LOSE if a < b else DRAW
        st = state(self.p)
        st['overall'][str(self.own)] += a
        st['overall'][str(self.opp)] += b
        m = st['matches'].get(str(self.mid))
        if m is not None:
            m.update(state=MATCH_MAKING, until=now + random.uniform(120, 360), queue=[0, 0], seen=now)
        self.p.dirty = True
        self.w.log('   TDM: match over %d:%d (%s)' % (a, b, {WIN: 'won', LOSE: 'lost', DRAW: 'draw'}[state_]))
        if not self.result_sent:
            self.result_sent = True
            rewards = [] if no_opponent or getattr(self, 'paid', False) else self.pay()       # no opponents for 30 s: no reward (wiki)
            self.w.send([self.status_cmd(now), self.result_cmd(state_, rewards)])
        self.release()
        w = self.w
        w.later(D['result_sec'], lambda: self.m.match is self and w.running and self.m.home())

    def result_cmd(self, result, rewards):
        def row(s):
            return mod('TeamDeathMatchResultScreenPlayerModule', name=s['name'], kills=s['kills'], deaths=s['deaths'],
                       pointsDelta=s['kills'] - s['deaths'], totalDamageGiven=int(s['given']), totalDamageTaken=int(s['taken']),
                       peakDamageGiven=int(s['peak']), winningStreak=s['best'])
        own = [row(self.player)] + [row(s) for s in self.stats.values() if s['company'] == self.own]
        opp = [row(s) for s in self.stats.values() if s['company'] == self.opp]
        own.sort(key=lambda r: -r['pointsDelta'])
        opp.sort(key=lambda r: -r['pointsDelta'])
        hint = random.choice(('jackpot_result_window_hint_1', 'jackpot_result_window_hint_2'))
        return ('TeamDeathMatchResultScreenCommand', dict(
            resultState=result, ownFaction=faction(self.own), opponentFaction=faction(self.opp), ownPlayers=own, opponentPlayers=opp,
            playerSessionKills=self.player['kills'], playerSessionDeaths=self.player['deaths'],
            rewards=[mod('RewardModule', lootId=l, amount=int(n)) for l, n in rewards],
            hint=mod('HintModule', messageKey=hint, replacements=[])))

    def release(self):
        """The drafted bots leave the TDM map: their ships go, they return to their X-1 and decide again."""
        release_bots(self.w, [(s['bot'], dict(kills=s['kills'], deaths=s['deaths'])) for s in self.stats.values()], self.map, 'tdm_done')
        self.stats_released = True
        if self.w is not None:
            self.w.mode_bots = None

    def close(self, why):
        """The player left the match (exit point, X-1 repair, logout): the bots go home too (single-player adaptation)."""
        if not self.over:
            self.over = True
            st = state(self.p)
            st['overall'][str(self.own)] += self.score[self.own]
            st['overall'][str(self.opp)] += self.score[self.opp]
            m = st['matches'].get(str(self.mid))
            if m is not None:
                m.update(state=MATCH_MAKING, until=time.time() + random.uniform(120, 360), queue=[0, 0], seen=time.time())
            self.p.dirty = True
        if not getattr(self, 'stats_released', False):
            self.release()
