"""Rank, counters and records (roadmap stage 3). Data data/ranks.json (tools/ranks.py: alien and ship points from the official
server's Hall of Fame details, ship types from the client's game.xml, ranks and formula from the wiki).

In the profile:
  counters        aliens killed (per type), player ships killed, deaths (enemy, radiation, other), quests
  rank            daily rank calculation {day, points, history: {day: {points, ep, honor}}} (for weekly/monthly ranking differences)
  logbook         LogbookDataCommand records (newest first, at most LOG_LIMIT)
  account_history BalanceInfoCommand records (newest first)

Client (1.1.114, research: the client's code):
  - ranks 1-21 (rang_N, the rankN icon in the ship label), 6000 admin, 5000 icon. There is no message that updates it during play:
    with ShipInitializationCommand.dailyRank (login, map change; during play world.badge_refresh). In the real game it is
    calculated once a day; here immediately when a threshold is crossed (live_rank).
  - Hall of Fame: HallOfFameTopRequest {type: TopReqType} -> HallOfFameTopDataListCommand. 17 "Your rank" page (myRankingPoints:
    the parts of the formula; pages npcPointsDetails / playerPointsDetails: points x value), 18/19 main page (top pilots/clans),
    4-7 EP, 8-11 honor, 0-3 and 16 user (rank points), 12-15 clan; HallOfFamePagesRequest {type 1-3, page} -> HallOfFamePages;
    HallOfFameDataListRequest {requested} -> event rankings (no event: empty).
  - Logbook: LogbookDataListRequest {startIndex: page from 0} -> 12 records each; infoText is translated in the client
    (kill_npcID_<id>, experience_points_<n>, honour_points_<n>, received_item, killed_by_npc_<id>, killed_by_radiation ...).
  - Account history: BalanceInfoListRequest {page: from 1} -> amountType GOLD/PEARL _PLUS/_MINUS, description is the client's key
    (bonus_abschussAlien, quest_won, buy_BATTERY_id ...; internalInfo item, infoText count).
Local adaptation: rank by the point thresholds; the players on the server in the Hall of Fame lists (single player: only the player; multi-client
and friend server: all connected players, every client sees the same list), the server's clans in the clan lists (clan.py;
points are the sum of the members' rank points).
"""
import bisect, json, math, os, threading, time
import game_data as DATA
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
R = DATA.load('ranks.json')            # World Editor: formula and thresholds
F = R['formula']
LOG_LIMIT = 500
LOGBOOK_PAGE = 12                  # the client's page size
ACCOUNT_PAGE = 50                   # official server record (2026-10-25): 50 rows per page
NPC_PAGE = 250                    # npcPointsDetails pages in the save
TOP = {'exp': (4, 5, 6, 7), 'honor': (8, 9, 10, 11), 'points': (0, 1, 2, 3, 16), 'clan': (12, 13, 14, 15, 19)}
TOP_WEEK, TOP_CLIMB, TOP_MONTH = (2, 6, 10), (3, 7, 11), (16,)
ORE_NAMES = {0: 'PROMETIUM', 1: 'ENDURIUM', 2: 'TERBIUM', 3: 'XENOMIT', 4: 'PROMETID', 5: 'DURANIUM', 6: 'PROMERIUM', 7: 'SEPROM',
             8: 'PALLADIUM'}
# Monthly ranking (darkorbitwiki events/monthly-ranking; the client's hof_rank_month_info_popup): Champion Token for the top 50 (Assembly's
# champion designs) and a title: 1st 100 + General of the Month; 2nd-5th 80, 6th-10th 60, 11th-25th 40, 26th-50th 20 + Acclaimed Pilot.
# Single-player adaptation: there is no ranking, the player's virtual place comes from their rank (the top rank is 1st; 1-3 below it 2nd-5th, 4-6 below 6th-10th,
# 7-10 below 11th-25th, 11-15 below 26th-50th; lower than that outside the top 50: no token or title). The last active month (points rose) is searched.
# Tier: (at most how many ranks below the top rank, token, title, achievement event: achievement.SERVER_SIDE)
CHAMPION, CHAMPION_MAX = 'resource_collectable_champion-token', 100
MONTHLY = ((0, 100, 'title_monthlyranking-general', 'monthly_general'), (3, 80, 'title_monthlyranking-pilot', 'monthly_pilot'),
           (6, 60, 'title_monthlyranking-pilot', 'monthly_pilot'), (10, 40, 'title_monthlyranking-pilot', 'monthly_pilot'),
           (15, 20, 'title_monthlyranking-pilot', 'monthly_pilot'))


def stamp(t=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t)) + '.0'


def today(t=None):
    return time.strftime('%Y-%m-%d', time.localtime(t))


# ------------------------------------------------------------ counters
def counters(p):
    c = p.d.setdefault('counters', {})
    done = len((p.d.get('quests') or {}).get('done', []))          # quests finished before the counters also count
    for k, v in (('npc', {}), ('player', {}), ('death_by_enemy', 0), ('death_by_radiation', 0), ('death_other', 0), ('quest', done),
                 ('friendly', 0), ('phoenix', 0)):
        c.setdefault(k, v)
    return c


def event(p, kind, **kw):
    """Game events (profile.ach; the same events as the achievements) -> counters."""
    if kind not in ('kill', 'death', 'quest'):
        return
    with p.lock:
        c = counters(p)
        if kind == 'kill' and kw.get('avatar', 'NPC') == 'NPC' and kw.get('npc') is not None:
            c['npc'][str(kw['npc'])] = c['npc'].get(str(kw['npc']), 0) + 1
        elif kind == 'kill' and kw.get('avatar') == 'PLAYER':           # bot players (stage 11)
            c['player'][kw.get('ship', '')] = c['player'].get(kw.get('ship', ''), 0) + 1
        elif kind == 'death':
            k = {'RADIATION': 'death_by_radiation', 'NPC': 'death_by_enemy', 'PLAYER': 'death_by_enemy'}.get(kw.get('reason'), 'death_other')
            c[k] += 1
        elif kind == 'quest':
            c['quest'] += 1
        p.dirty = True


# ------------------------------------------------------------ rank points
def days_registered(p, now=None):
    try:
        t0 = time.mktime(time.strptime(p.d.get('created', ''), '%Y-%m-%d %H:%M:%S'))
    except ValueError:
        return 0
    return max(0, int(((now or time.time()) - t0) // 86400))


def ship_type(p):
    return R['ship_type'].get(p.ship()['lootId'], 0)        # a ship not in the table (non-classic) is 0 (real record: Sentinel 0)


def user_score(p):
    """Hall of Fame 'Top user' points: EP / 1000 + Honor / 100 (official forum 127509; real record 416,032,909 EP, 27,810 honor -> 416,311)."""
    pl = p.d['pilot']
    return int(pl.get('ep', 0) / 1000 + pl.get('honourPoints', 0) / 100)


def user_score_since(p, days, now=None):
    return int(_since(p, 'ep', days, now) / 1000 + _since(p, 'honor', days, now) / 100)


def npc_points(p):
    return sum(R['npc_points'].get(k, {}).get('points', 0) * n for k, n in counters(p)['npc'].items())


def player_points(p):
    return sum(R['ship_points'].get(k, {}).get('points', 0) * n for k, n in counters(p)['player'].items())


def breakdown(p, now=None):
    """HallOfFameRankingPoints fields (the parts of the rank points formula, wiki) + rankPoints."""
    c, pl = counters(p), p.d['pilot']
    parts = dict(ExperiencePoints=int(pl.get('ep', 0)), honorPoints=int(pl.get('honourPoints', 0)), playerShotPoints=player_points(p),
                 yourLevel=int(pl.get('level', 1)), daysSinceRegistration=days_registered(p, now), yourShipType=ship_type(p),
                 npcShotPoints=npc_points(p), missionsCompleted=c['quest'], friendlyPlayersDestroyed=c['friendly'],
                 DestroyedByEnemies=c['death_by_enemy'], DestroyedByRadiationZone=c['death_by_radiation'], phoenixDestroyed=c['phoenix'])
    pts = (parts['ExperiencePoints'] * F['ep'] + parts['honorPoints'] * F['honor'] + parts['playerShotPoints'] * F['player']
           + parts['yourLevel'] * F['level'] + parts['daysSinceRegistration'] * F['day'] + parts['yourShipType'] * F['ship']
           + parts['npcShotPoints'] * F['npc'] + parts['missionsCompleted'] * F['quest'] + parts['friendlyPlayersDestroyed'] * F['friendly']
           + parts['DestroyedByEnemies'] * F['death_by_enemy'] + parts['DestroyedByRadiationZone'] * F['death_by_radiation']
           + parts['phoenixDestroyed'] * F['phoenix'])
    parts['rankPoints'] = max(0, int(pts))
    return parts


def rank_for(points):
    """Rank from rank points (1-21; single-player thresholds, ranks.json thresholds)."""
    return max(i + 1 for i, t in enumerate(R['thresholds']) if points >= t)


# ------------------------------------------------------------ company ranking (bot players)
# The real system (darkorbitwiki guides/ranks; ranks.json ranks): the rank depends on the place in the company, Chief General 1, General 2, Basic
# General 3, Chief Colonel 5, Colonel 20 people; the rest by percentage (Basic Colonel 1% ... Basic Space Pilot 20%). While a bot pack is in the world
# this ranking alone decides the rank (player request 2026-10-30; owner request 2026-11-02: no threshold ceiling, the rules apply from the first day
# whatever the level, so the company's best pilot is Chief General even when everyone is new). Without bots, only the thresholds as before.
# The Level Based Rank Threshold setting (off by default) brings the threshold ceiling back: capped().
RANKING_SEC = 30
_RANKING = {}                        # company -> (timestamp, [(points, uid)])
_SORTED = {}                         # company -> (that list, its sorted (points, -uid) keys, uid -> points): company_rank by bisection
_LOCAL = threading.local()        # while the account runs: community.all_() updates the bots' profiles, which asks for the rank


def _bots():
    from bot import manager as MGR
    y = MGR.ACTIVE
    return y.bots if y is not None and y.bots else None


def _company(company, now):
    """The company's pilots [(rank points, id)]: registered bots and the server's players (cached for RANKING_SEC)."""
    t = _RANKING.get(company)
    if getattr(_LOCAL, 'inside', False):
        return t[1] if t else []                  # nested call (live test 2026-10-30: infinite recursion): the old list
    if t and now - t[0] < RANKING_SEC:
        return t[1]
    _LOCAL.inside = True
    try:
        out = _build_company(company, now)
    finally:
        _LOCAL.inside = False
    _RANKING[company] = (now, out)
    return out


def _build_company(company, now):
    import community as TP
    from bot import society as TB
    import admin_mode as YM
    bots = {b.uid: b for b in _bots() or ()}
    out = [(TB.points(b), uid) for uid, b in bots.items() if b.company == company and b.saved]
    for uid, k in TP.all_().items():
        if uid not in bots and int(k.profile.d['pilot'].get('factionId') or 0) == company and not YM.mi(profile=k.profile):
            out.append((breakdown(k.profile, now)['rankPoints'], uid))
    return out


def place_rank(order, n):
    """The rank of the one at place `rank` (0: most points) among the company's n pilots: first the ranks with a fixed count (down from 21), then the rest
    by their percentages (down from 16; the lowest rank left outside the percentages)."""
    fixed = 0
    for r in reversed(R['ranks']):
        if r['type'] == 'fixedPlayersPerCompany':
            fixed += r['value']
            if order < fixed:
                return r['rank']
    q, c = 100.0 * (order - fixed + 1) / max(1, n - fixed), 0.0
    for r in reversed(R['ranks']):
        if r['type'] == 'percentOfCompany':
            c += r['value']
            if q <= c + 1e-9:
                return r['rank']
    return 1


def company_rank(uid, company, points, now=None):
    """While bots exist, the rank from the place in the company (the current points instead of uid's own record) -> rank or None (no bots)."""
    if _bots() is None or not company:
        return None
    now = now or time.time()
    lst = _company(company, now)
    s = _SORTED.get(company)
    if s is None or s[0] is not lst:
        # every bot profile asks its rank (society.people rebuilds them all every 2 s): a scan of the company per bot was O(n^2) under
        # the bot lock, 1500 bots froze the world loop for seconds (player reports 2026-11-06)
        s = _SORTED[company] = (lst, sorted((p, -u) for p, u in lst), {u: p for p, u in lst})
    _, keys, own = s
    me = (points, -uid)                                      # on a tie the registered one first (smaller id)
    above = len(keys) - bisect.bisect_right(keys, me)
    if uid in own and (own[uid], -uid) > me:
        above -= 1                                           # its own (older) entry is not a rival
    return place_rank(above, len(keys) + (uid not in own))


def points_to_pass(p, rank, now=None):
    """While bots exist, the points of the company pilot that must be passed to reach the rank (the one in the lowest place of that rank) or None."""
    if _bots() is None:
        return None
    now = now or time.time()
    others = sorted((x for x in _company(int(p.d['pilot'].get('factionId') or 0), now) if x[1] != p.user_id), reverse=True)
    n = len(others) + 1
    k = max((i for i in range(n) if place_rank(i, n) >= rank), default=-1)
    return others[k][0] if 0 <= k < len(others) else None


def points_below(p, rank, now=None):
    """While bots exist, the points of the best company pilot at `rank` or lower (the "rank below yours has approx. X points" line) or None."""
    if _bots() is None:
        return None
    now = now or time.time()
    others = sorted((x for x in _company(int(p.d['pilot'].get('factionId') or 0), now) if x[1] != p.user_id), reverse=True)
    n = len(others) + 1
    k = min((i for i in range(n) if place_rank(i, n) <= rank), default=0)
    return others[k - 1][0] if 1 <= k <= len(others) else None      # those places are below the player: others[k - 1] holds place k


def capped(threshold_rank, place):
    """The rank from the threshold rank and the company place (None: no bots -> thresholds). The Level Based Rank Threshold setting brings
    back the system before 2026-11-02 (player request 2026-11-03): the thresholds are a ceiling on the place, the smaller of the two."""
    if place is None:
        return threshold_rank
    return min(threshold_rank, place) if SET.get('level_rank_threshold') else place


def rank_of(p, points, now=None):
    """The player's rank: while bots exist the place in the company (with the setting the thresholds as a ceiling); without bots by thresholds."""
    return capped(rank_for(points), company_rank(p.user_id, int(p.d['pilot'].get('factionId') or 0), points, now))


def daily_rank(p, now=None, force=False):
    """Once a day (checked at login and map change): the rank is computed and written to pilot.dailyRank -> the new rank or None."""
    import admin_mode as YM
    if YM.is_open(p):
        return None                     # an admin is not in the rank system (the badge comes from profile.ship_init)
    day = today(now)
    st = p.d.setdefault('rank', {})
    if st.get('day') == day and not force:
        return None
    b = breakdown(p, now)
    rank = rank_of(p, b['rankPoints'], now)
    icon = rank_icon(p, rank)
    prev, prev_rank = st.get('ay'), st.get('rank') or 1
    monthly = bool(prev and prev != day[:7] and active_month(st.get('history', {}), prev))
    with p.lock:
        st.update(day=day, points=b['rankPoints'], rank=rank, ay=day[:7])
        hist = st.setdefault('history', {})
        hist[day] = dict(points=b['rankPoints'], ep=int(p.d['pilot'].get('ep', 0)), honor=int(p.d['pilot'].get('honourPoints', 0)))
        for old in sorted(hist)[:-40]:
            del hist[old]
        p.d['pilot']['dailyRank'] = icon           # ShipInitializationCommand.dailyRank (player_profile.PILOT_FIELDS)
        p.dirty = True
    tier = next((t for t in MONTHLY if len(R['thresholds']) - prev_rank <= t[0]), None) if monthly else None
    if tier:
        _, tokens, title, kind = tier
        p.ach(kind)                                 # achievement: General of the Month / Acclaimed Pilot counter (achievement.SERVER_SIDE)
        p.add_resource(CHAMPION, tokens)
        grant_title(p, title)
    return icon


def grant_title(p, key):
    """Monthly ranking title: chosen in the achievement window (an event title not in the table; achievement.title_id gives a fixed id)."""
    import achievement as ACV
    ACV.title_id(key)
    st = ACV.state(p)
    if key not in st['titles']:
        with p.lock:
            st['titles'].append(key)
            p.dirty = True


def rank_icon(p, rank):
    """The rank icon on the ship: the rank, or the outlaw icon if honor is -500 or below."""
    return R['outlaw']['icon'] if p.d['pilot'].get('honourPoints', 0) <= R['outlaw']['honor'] else rank


def live_rank(p, now=None):
    """When the rank points change (alien, EP, honor, quest) the rank at once: a player who crosses a threshold rises at that moment (user report
    2026-10-24: even with enough points the rank did not change until the next day; in the real game the rank is given once a day, by the place in the company,
    in single player there is no ranking). The daily record (history, monthly reward) stays in daily_rank. -> (old, new) or None."""
    import admin_mode as YM
    if YM.is_open(p):
        return None                     # admin: the rank does not change, no "you ranked up"
    pl = p.d['pilot']
    rank = rank_of(p, breakdown(p, now)['rankPoints'], now)
    icon, old = rank_icon(p, rank), pl.get('dailyRank', 1)
    if icon == old:
        return None
    with p.lock:
        pl['dailyRank'] = icon
        p.d.setdefault('rank', {})['rank'] = rank
        p.dirty = True
    return old, icon


def active_month(hist, month):
    """Whether the rank points rose within the month (from the daily records)."""
    inside = [hist[d]['points'] for d in sorted(hist) if d.startswith(month)]
    before = [hist[d]['points'] for d in sorted(hist) if d < month]
    return bool(inside) and max(inside) > (before[-1] if before else 0)


def _since(p, field, days, now=None):
    """Gain in the last N days (from the daily records; if the oldest record is newer, from that)."""
    hist = p.d.get('rank', {}).get('history', {})
    cur = breakdown(p, now)['rankPoints'] if field == 'points' else int(p.d['pilot'].get('ep' if field == 'ep' else 'honourPoints', 0))
    limit = today((now or time.time()) - days * 86400)
    olds = [d for d in sorted(hist) if d <= limit] or sorted(hist)[:1]
    return max(0, cur - hist[olds[-1]][field]) if olds else cur


# ------------------------------------------------------------ Hall of Fame
def _row(p, rank, points, value):
    return {'_': 'HallOfFameDataCommand', 'userId': p.user_id, 'rank': rank, 'time': '', 'points': int(points),
            'value': int(value), 'userName': p.d['pilot'].get('userName', '')}


def _zero_points():
    return {'_': 'HallOfFameRankingPoints', **{k: 0 for k in (
        'honorPoints', 'belowRanking', 'belowPoints', 'missionsCompleted', 'friendlyPlayersDestroyed', 'ExperiencePoints',
        'aboveRanking', 'DestroyedByEnemies', 'npcShotPoints', 'DestroyedByRadiationZone', 'yourRanking', 'yourLevel',
        'daysSinceRegistration', 'yourShipType', 'rankPoints', 'playerShotPoints', 'abovePoints', 'phoenixDestroyed')},
        'shipsCategoryName': ''}


def ranking_points(p, now=None):
    """The Your rank page: the parts of the formula, the rank (yourRanking: rang_N), the points needed for the next rank up (abovePoints) and the points of the rank
    below (belowPoints: its threshold). The client (UIHallOfFameSystem.UpdateDailyRankForServer) builds the "hof_your_rank_below" text
    ("The rank directly below yours is that of rang_<yourRanking-1>. Space pilots with this rank have approx. belowPoints rank
    points.") when yourRanking is 2-20, "hof_rank_lowest" at 1, "hof_rank_highest" at 21; it does not read aboveRanking/belowRanking. It does not put the
    line it built into the window and always writes "hof_rank_lowest": the client's BepInEx plugin (panel/plugin/Patches.cs RankWindow)."""
    b = breakdown(p, now)
    rank = rank_of(p, b['rankPoints'], now)
    nxt = R['thresholds'][rank] if rank < len(R['thresholds']) else b['rankPoints']
    below = R['thresholds'][rank - 2] if rank > 1 else 0
    if _bots() is not None:                             # company ranking: one must pass the pilot at that rank's boundary in the company
        rival = points_to_pass(p, rank + 1, now) if rank < len(R['thresholds']) else None
        if SET.get('level_rank_threshold'):             # thresholds as a ceiling: the threshold too must be reached, the rank below is its threshold
            nxt = nxt if rival is None else max(nxt, int(rival) + 1)
        else:
            nxt = int(rival) + 1 if rival is not None else b['rankPoints']
            low = points_below(p, rank - 1, now) if rank > 1 else None
            below = int(low) if low is not None else 0
    loot = p.ship()['lootId']
    out = _zero_points()
    out.update(b, yourRanking=rank, aboveRanking=min(rank + 1, 21), abovePoints=max(0, nxt - b['rankPoints']),
               belowRanking=max(rank - 1, 1), belowPoints=below,
               shipsCategoryName=R['ship_points'].get(loot, {}).get('name', loot.replace('ship_', '').title()))
    return out


def _page(page_type, rows, total=1, cur=1):
    return {'_': 'HallOfFamePages', 'pageType': page_type, 'myList': [], 'dataList': rows, 'type': 0, 'pageSize': NPC_PAGE,
            'currentPage': cur, 'totalPage': total}


def players(p):
    """Those entering the Hall of Fame: the profiles of the players on the server (single player: only the player; a profile not on the server stands alone)."""
    import community as TP
    import admin_mode as YM
    lst = [k.profile for k in TP.all_().values() if not YM.mi(profile=k.profile)]       # an admin is not in the lists
    return lst if any(x is p for x in lst) or YM.mi(profile=p) else [p]


def _sorted(p, value):
    """Players by value (largest first; on a tie by name) -> [(profile, value)]."""
    return sorted(((x, value(x)) for x in players(p)), key=lambda xv: (-xv[1], str(xv[0].d['pilot'].get('userName', '')).lower()))


def _ranked(p, value, extra=None):
    """-> (all rows, the player's row). extra(x, v): the row's value (the value itself if not given)."""
    rows, mine = [], []
    for i, (x, v) in enumerate(_sorted(p, value)):
        row = _row(x, i + 1, v, extra(x, v) if extra else v)
        rows.append(row)
        if x is p:
            mine = [row]
    return rows, mine


def hof_sira(p, now=None):
    """The pilot card's rank: among the players on the server by rank points."""
    _, mine = _ranked(p, user_score)
    return mine[0]['rank'] if mine else 1


def hof_top(p, f, now=None):
    t = int(f.get('type') or 0)
    out = dict(myRankingPoints=_zero_points(), type=t, allRankList=[], pages=[], myRankList=[])
    if t == 17:
        c = counters(p)
        npc = [{'_': 'HallOfFameDataCommand', 'userId': int(k), 'rank': 0, 'time': '', 'points': v['points'],
                'value': c['npc'].get(k, 0), 'userName': v['name']} for k, v in sorted(R['npc_points'].items(), key=lambda kv: int(kv[0]))]
        pages = [npc[i:i + NPC_PAGE] for i in range(0, len(npc), NPC_PAGE)]
        ships = [{'_': 'HallOfFameDataCommand', 'userId': 0, 'rank': 0, 'time': '', 'points': v['points'], 'value': c['player'].get(k, 0),
                  'userName': v['name']} for k, v in R['ship_points'].items()]
        out.update(myRankingPoints=ranking_points(p, now),
                   pages=[_page('npcPointsDetails', pg, len(pages), i + 1) for i, pg in enumerate(pages)] + [_page('playerPointsDetails', ships)])
    elif t == 18:                                                    # main page: points, name, rank; value is the company icon
        rows, mine = _ranked(p, user_score, lambda x, v: x.d['pilot'].get('factionId', 0))
        out.update(allRankList=rows[:50], myRankList=mine)
    elif t in TOP['clan']:        # the server's clans (clan.py): the members' top-user points (forum 127471); real record: points 0,
        #                             value is the clan points
        import clan as KL
        span = {14: 7, 15: 7}.get(t)                                 # 14 weekly, 15 risers (like 2/3 on user)
        if span:
            who = {KL.name(x): x for x in players(p)}
            with KL.LOCK:
                lst = sorted(((k, sum(user_score_since(who[a], span, now) for a in k['members'] if a in who)) for k in KL.CLANS.values()),
                             key=lambda kv: (-kv[1], kv[0]['id']))
        else:
            lst = KL.ranking()
        own = KL.clan_of(p)
        rows, mine = [], []
        for i, (k, v) in enumerate(lst):
            row = dict(_row(p, i + 1, 0, v), userId=k['id'], userName='[%s] %s' % (k['tag'], k['name']))
            rows.append(row)
            if k is own:
                mine = [row]
        out.update(allRankList=rows[:50], myRankList=mine)
    else:
        field = 'ep' if t in TOP['exp'] else 'honor' if t in TOP['honor'] else 'points'

        def value(x):
            days = 7 if t in TOP_WEEK + TOP_CLIMB else 30 if t in TOP_MONTH else None
            if field == 'points':                                          # Top user: EP/1000 + honor/100 (forum 127509)
                return user_score_since(x, days, now) if days else user_score(x)
            if days:
                return _since(x, field, days, now)
            return int(x.d['pilot'].get('ep' if field == 'ep' else 'honourPoints', 0))
        rows, mine = _ranked(p, value)
        out.update(allRankList=rows[:50], myRankList=mine)
    return [('HallOfFameTopDataListCommand', out)]


def hof_pages(p, f, now=None):
    """HallOfFamePagesRequest {type 1 user, 2 EP, 3 honor; page} -> HallOfFamePages (row: rank, name, points, rank icon)."""
    t = int(f.get('type') or 1)
    value = (user_score if t == 1 else (lambda x: int(x.d['pilot'].get('ep', 0))) if t == 2
             else (lambda x: int(x.d['pilot'].get('honourPoints', 0))))
    rows, mine = _ranked(p, value, lambda x, v: x.d['pilot'].get('dailyRank', 1))
    size = 50
    total = max(1, (len(rows) + size - 1) // size)
    page = min(max(1, int(f.get('page') or 1)), total)
    return [('HallOfFamePages', dict(pageType='', myList=mine, dataList=rows[(page - 1) * size:page * size], type=t, pageSize=size,
                                     currentPage=page, totalPage=total))]


def _runs(p, n):
    return sum(sorted((p.d.get('mimesis') or {}).get('trips', []), reverse=True)[:n])


HOF_EVENTS = {2: lambda p: (p.d.get('labyrinth') or {}).get('hunts', 0),                   # FrozenLabyrinth: Synk hunts
              3: lambda p: ((p.d.get('pve') or {}).get('ebl') or {}).get('best', 0),     # EternalGate: Eternal Black Light waves
              4: lambda p: _runs(p, 10),                                                   # MimesisMutiny: best 10 runs (mimesis.total)
              5: lambda p: _runs(p, 1),                                                    # PayloadEscort: best run
              6: lambda p: min(((p.d.get('world_boss') or {}).get('event') or {}).get('damage', 0), 2 ** 31 - 1)}  # PublicWorldBoss: damage


def _ebl_time(p):
    t = ((p.d.get('pve') or {}).get('ebl') or {}).get('best_at')
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(t) / 1000.0)) if t else ''


HOF_TIMES = {3: _ebl_time}          # Time column: the time of the furthest wave (it showed empty; live test H76)


def hof_events(p, f):
    """HallOfFameDataListRequest {requested: the client's HallOfFameType}: event rankings. In the lists of Frozen Labyrinth (Synk hunts),
    Eternal Gate (the furthest wave of Eternal Black Light), Mimesis Mutiny (the sum of the best 10 runs), Payload Escort (the best run)
    and World Boss (damage over the event) the players on the server (those with points); Galactic Strife is empty."""
    t = int(f.get('requested') or 0)
    rows, mine = [], []
    for x, v in _sorted(p, HOF_EVENTS.get(t, lambda x: 0)):
        if not v:
            continue
        row = dict(_row(x, len(rows) + 1, v, v), time=HOF_TIMES.get(t, lambda x: '')(x))
        rows.append(row)
        if x is p:
            mine = [row]
    return [('HallOfFameDataListCommand', dict(dataList=rows[:50], type=t, pages=[], myList=mine))]


# ------------------------------------------------------------ logbook
def note(p, info_text, info='', count=0, args='{}', quest=0, done=0, t=None):
    """A record in the logbook (newest on top)."""
    with p.lock:
        lst = p.d.setdefault('logbook', [])
        lst.insert(0, dict(quest=quest, info=info, args=args, count=int(count), insertDate=stamp(t), questDone=done, infoText=info_text))
        del lst[LOG_LIMIT:]
        p.dirty = True


def note_kill(p, npc_id, ep, honor):
    """Alien kill: in the client, stacked: "... imha ettin", "XXX TP kazandın", "XXX Şeref Puanı kazandın" (Turkish client texts; order in the save)."""
    if honor:
        note(p, 'honour_points_%d' % honor)
    if ep:
        note(p, 'experience_points_%d' % ep)
    note(p, 'kill_npcID_%s' % npc_id)


def logbook(p, f):
    """LogbookDataListRequest {startIndex: page (from 0)} -> LogbookDataListCommand (12 each)."""
    lst = p.d.get('logbook', [])
    page = max(0, int(f.get('startIndex') or 0))
    rows = [dict(e, _='LogbookDataCommand') for e in lst[page * LOGBOOK_PAGE:(page + 1) * LOGBOOK_PAGE]]
    return [('LogbookDataListCommand', dict(startIndex=page, total=len(lst), list=rows))]


# ------------------------------------------------------------ account history
CUR = {'credits': 'GOLD', 'credits': 'GOLD', 'uridium': 'PEARL', 'uridium': 'PEARL'}


def money(p, cur, amount, description, internal='', qty=0, t=None):
    """Money movement record: cur credits/uridium (or credits/uridium), if amount is negative it is spending."""
    amount = int(amount)
    if not amount or cur not in CUR:
        return
    with p.lock:
        lst = p.d.setdefault('account_history', [])
        lst.insert(0, dict(internalInfo=internal, insertDate=stamp(t), amountType='%s_%s' % (CUR[cur], 'PLUS' if amount > 0 else 'MINUS'),
                           amount=abs(amount), infoText=int(qty), description=description, userId=p.d['pilot'].get('userId', 0)))
        del lst[LOG_LIMIT:]
        p.dirty = True
    if amount < 0 and CUR[cur] == 'PEARL':
        # single player: spending uridium advances the Passes' "Make a payment" quest (RECHARGE_AMOUNT); in the real game, a payment
        # (user report 2026-10-25: Galaxy Trade stayed at 0/1). A purchase from the Uridium Bank counts too (game.py)
        p.ach('recharge')


# Descriptions of old records -> the key the client displays correctly (live test H27; tried one by one via the control channel):
# in the buy_* texts with _id, %ITEMNAME%/%AMOUNT% stay raw, the ones without _id add "(count)" (like "buy_BATTERY" in the save).
# A key with no counterpart in the client showed "Extra purchased" (in gains too).
DESC_FIX = {'buy_BATTERY_id': 'buy_BATTERY', 'buy_MINES_id': 'buy_MINES', 'buy_EMP_id': 'buy_EMP', 'buy_ROCKET_id': 'buy_ROCKET',
            'buy_LASER_id': 'buy_LASER', 'buy_ROCKETLAUNCHER_id': 'buy_ROCKETLAUNCHER', 'buy_ROBOT_id': 'buy_ROBOT',
            'buy_CPU_id': 'buy_CPU', 'log_purchased_drone_formation_id': 'buy_SPECIAL', 'buy_DRONE_id': 'buy_DRONE',
            'buy_BOOSTER_id': 'buy_BOOSTER', 'buy_ORE_id': 'buy_ORE', 'buy_SPECIAL_id': 'buy_SPECIAL',
            'auction_book_back_money': 'auction_bookMoneyBack', 'uridium_bank': 'title_uridium_bank',
            'payout': 'clan_hl_auszahlungen', 'gg_reward': 'galaxy_gate_done', 'captain_roster_full': 'aktion_system_back'}


def balance(p, f):
    """BalanceInfoListRequest {page: 1'den} -> BalanceInfoListCommand."""
    lst = p.d.get('account_history', [])
    pages = max(1, math.ceil(len(lst) / ACCOUNT_PAGE))
    page = min(max(1, int(f.get('page') or 1)), pages)
    rows = [dict(e, _='BalanceInfoCommand', description=DESC_FIX.get(e.get('description'), e.get('description')))
            for e in lst[(page - 1) * ACCOUNT_PAGE:page * ACCOUNT_PAGE]]
    return [('BalanceInfoListCommand', dict(page=page, pageCount=pages, list=rows))]


def buy_desc(loot):
    """A purchase's description in the account history (the client's buy_* keys; the count is added from infoText as "(5)")."""
    if loot.startswith('ammunition_laser_'):
        return 'buy_BATTERY'
    if loot.startswith('ammunition_mine_'):
        return 'buy_MINES'
    if loot.startswith('ammunition_specialammo_emp'):
        return 'buy_EMP'
    if loot.startswith(('ammunition_rocket', 'ammunition_specialammo_')):
        return 'buy_ROCKET'
    if loot.startswith('equipment_weapon_laser_'):
        return 'buy_LASER'
    if loot.startswith('equipment_weapon_rocketlauncher_'):
        return 'buy_ROCKETLAUNCHER'
    if loot.startswith('equipment_generator_'):
        return 'buy_GENERATOR'
    if loot.startswith('equipment_extra_repbot'):
        return 'buy_ROBOT'
    if loot.startswith('equipment_extra_cpu_'):
        return 'buy_CPU'
    if loot.startswith('drone_formation_'):
        return 'buy_SPECIAL'
    if loot.startswith('drone_'):
        return 'buy_DRONE'
    if loot.startswith('booster_'):
        return 'buy_BOOSTER'
    if loot.startswith('resource_ore_'):
        return 'buy_ORE'
    if '_design_' in loot:
        return 'buy_SHIPMODEL'
    if loot.startswith('ship_'):
        return 'buy_SHIP'
    return 'buy_SPECIAL'


def sell_desc(loot):
    if loot.startswith('ammunition_laser_'):
        return 'sell_batteries'
    if loot.startswith(('ammunition_rocket', 'ammunition_mine_', 'ammunition_specialammo_')):
        return 'sell_rockets'
    if loot.startswith('equipment_weapon_laser_'):
        return 'sell_laser'
    if loot.startswith('equipment_weapon_rocketlauncher_'):
        return 'sell_rocketlauncher'
    if loot.startswith('equipment_generator_'):
        return 'sell_generator'
    if loot.startswith('equipment_extra_repbot'):
        return 'sell_robot'
    if loot.startswith('drone_designs_'):
        return 'sell_drone_designs_%s' % loot.split('_')[-1]
    if loot.startswith('drone_'):
        return 'sell_drone'
    return 'sell_special'


def ore_desc(ore_type):
    return 'sellOre_%s' % ORE_NAMES.get(int(ore_type), str(ore_type))
