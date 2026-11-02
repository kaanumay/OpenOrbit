"""Season Pass (roadmap Stage 7; data data/tickets.json "season" <- tools/tickets.py, from the window in the record).

Flows in the record and the client's messages:
  login              SeasonPassStatusCommand {pointsCost, uridiumCost (per level), goldPass, extGoldPass, seasonName, marketingImage,
                     timeToEventEnd s}, SeasonPassRewardInfoCommand (three reward tracks, claimed), SeasonPassMissionInfoCommand
                     {refreshInfo, missionItems [SeasonPassMissionModule {missionStatus, questDefinitionModule}]}, SeasonPointsInfoCommand
  quest progress     QuestConditionUpdateCommand (the quest engine's format); when done "0|A|STM|sp_daily-mission-completed" (weekly, season),
                     QuestCompletedCommand {id, rating}, achievement event (record: achievement_quest_quests_1), SeasonPointsInfoCommand
  reward             SeasonPassRewardClaimRequest {level, goldPass, extGoldPass} -> reward + SeasonPassRewardClaimCommand {claimed}
                     SeasonPassRewardClaimAllRequest -> everything that can be claimed
  level purchase     SeasonPassLevelPurchaseRequest {amount} -> with uridium (uridiumCost) -> SeasonPassLevelPurchaseCommand {success}
  quest refresh      SeasonPassRefreshRequest {questId, costType}: another one from the pool in place of a daily or weekly quest
Quest status (the client's MissionStatusType): 0 in progress, 1 Gold in progress, 2 Gold Pass needed, 3 done, 4 Gold done, 5 Gold Pass
needed but done (its points arrive when the Gold Pass is obtained).
Single-player adaptations: the reward track and quests are those of the season in the record (the same every season); only the season designs (drone and P.E.T.;
in the 2024-2025 seasons a ship design at the end of the Gold track) come from the season's track: 2023-05 Mobius ... 2026-08 Cerevisia (in the record),
then from the start (event_appearances.season_track; designs of past seasons could not be obtained any other way).
Seasons are in the real game's months: February, May, August, beginning of November (season_id "2026-08"); the real dates of known seasons are in
data/tickets.json "season.calendar" (wiki: XIV 01.08.2026 - 25.10.2026 = 86 days, the record's timeToEventEnd corresponds to 25.10 23:59; XV
from 26.10.2026, adaptation until the source appears), those not in the table follow the month rule.
When a season ends unclaimed rewards are given (the client's text: "Any unclaimed rewards from the previous season has been booked to you");
N.O.V.A. captains wait: the end-of-season window SeasonPassRewardUnclaimedInfoCommand {captainPending, captainOwned, captainLimit,
captainWarning} (the client's ShowEndView; also at login while any are pending), its button SeasonPassRewardClaimAllRequest. If there is no room in the roster
the captain reward is not claimed, SeasonPassCaptainLimitCommand ("Your N.O.V.A. roster is already full!"); the pending ones burn at the end of the next season.
Daily quests (3 + 2 Gold) are drawn from the pool every day, weeklies (5 + 3 Gold) on Monday (wiki pool: 48 daily, 51 weekly quests;
the "Complete 1 of the following tasks" rows are multi-condition quests); season quests last the whole season. Refresh: 1 free per day, then
purchased ones: 1st-4th 500 U, 5th-7th 1,000 U, 8th-10th 2,000 U, 11th+ 4,000 U (wiki; daily and weekly are counted separately, reset at the start of the day and week;
the record's refreshInfo reports the next price). When the level is at the maximum, extra purchased points: 1 point = 10 Honor. Gold Pass
in the shop (resource_gold-pass 400,000 U) or from a package; Extra Gold Pass after the Gold Pass.
Save-specific season (developer note 2026-10-28; player report: when the real calendar's season ended on 25.10 the ticket "closed"):
the season starts from day 1 at the save's first login and lasts the panel's season_duration days (independent of the calendar; when the duration changes it applies to the running season too);
a single season at a time. In place of the ended season the next one: if the save was created "progressive" (profile 'progressive', the panel's new
save window) starting from the first season (2023-05 Mobius), moving to the next each time a season ends, up to the newest; seasons added later
open when their turn comes, if all were played the newest repeats. Otherwise always the newest season. The season's id is the season of its designs
(event_appearances.SEASONS); the achievement group and the end of timed recipes come from this season (ACTIVE). The calendar functions (season_id ...)
remain to know the real game's seasons.
In the profile: season {period, start, played, points, gold, ext, claimed, day, daily, week, weekly, value, done, seasonal, renewal, pending [[captain, count]]}.
"""
import datetime, json, os, random, threading, time

import settings as SET
import event_appearances as EG
import quest_tracker as GT
import nova as NV
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, 'data', 'tickets.json'), encoding='utf8'))['season']
COST, UCOST = S['point_cost'], S['uridium_cost']
MAX_LEVEL = len(COST) - 1
MISSIONS = {int(k): v for k, v in S['quests'].items()}
DAILY, WEEKLY, SEASON = 3, 6, 9
DAILY_N, WEEKLY_N = (3, 2), (5, 3)            # (normal, Gold) (record)
REFRESH_LADDER = [tuple(x) for x in S['refresh_ladder']]        # (refresh up to this tier or None, cost U)
OVERFLOW_HONOR = 10                           # purchased points above the maximum level: 1 point = 10 Honor (wiki)
DONE_TEXT = {DAILY: 'sp_daily-mission-completed', WEEKLY: 'sp_weekly-mission-completed', SEASON: 'sp_season-mission-completed'}
TRACKS = (('free', False, False), ('gold', True, False), ('ext', False, True))
GOLD_ITEM, EXT_ITEM, POINT_ITEM = 'resource_gold-pass', 'resource_ext-gold-pass', 'resource_season-pass-point'
# the window's title by the season's month (the client's sp_season-name_1..4; its achievement texts: 2023-08, 2024-08, 2025-08, 2026-08 Waxing
# Gibbous, 2023-11, 2024-11, 2025-11 Waning Gibbous, 2024-02, 2025-02, 2026-02 Waning Crescent; May the Waxing Crescent left; Season XV 2026-11
# "Waning Gibbous" in the official window, player screenshot 2026-11-02). Every season used to be "Waxing Crescent"
NAME_BY_MONTH = {5: 'sp_season-name_1', 8: 'sp_season-name_2', 11: 'sp_season-name_3', 2: 'sp_season-name_4'}


def _reserve_pool(*tracks):
    return [(r[1], r[2]) for t in tracks for r in S['reward'][t]
            if r[1].startswith('resource_') and r[1] not in (GOLD_ITEM, EXT_ITEM, POINT_ITEM)]


# Season Pass reserves (package_seasonpass-*): they come as packages in the reward tracks, the client does not give their contents (only "A reserve
# containing useful resources for the average pilot" / "... only the most sought after resources in the galaxy" / "... booty keys").
# Adaptation: when opened, one of the resource rows in the same season's reward track (Gold: the Gold and Extra Gold tracks; the giant reserve three draws),
# the booty key reserve is the free track's 10 keys. Previously it was not recognized in the reward path and fell into the invisible storage (2026-10-22).
RESERVES = {'package_seasonpass-free': (_reserve_pool('free'), 1),
            'package_seasonpass-gold': (_reserve_pool('gold', 'ext'), 1),
            'package_seasonpass-gold-giant': (_reserve_pool('gold', 'ext'), 3),
            'package_seasonpass-bootykey': ([('resource_booty-key', 10)], 1),
            'package_seasonpass-bootykey-giant': ([('resource_booty-key', 10)], 3)}


def reserve(loot, n=1):
    """What is given when a reserve is opened [(lootId, count)] (the same item merges) or None (not a reserve)."""
    if loot not in RESERVES:
        return None
    pool, draws = RESERVES[loot]
    out = {}
    for _ in range(int(n) * draws):
        l, k = random.choice(pool)
        out[l] = out.get(l, 0) + k
    return sorted(out.items())


def mod(name, **f):
    f['_'] = name
    return f


def _day(text, plus=0):
    return (datetime.datetime.strptime(text, '%Y-%m-%d') + datetime.timedelta(days=plus)).timestamp()


# seasons with known real dates: ((year, month), start, end or None = the end of the month rule); the end day is included
WINDOWS = [(tuple(int(x) for x in w['id'].split('-')), _day(w['start']), _day(w['end_time'], 1) if w.get('end_time') else None)
           for w in S.get('calendar', [])]


def formula_end(y, m):
    """By the month rule the end of season (y, m): the first day of the month three months later."""
    return datetime.datetime(y + (m == 11), (m + 2) % 12 + 1, 1).timestamp()


def season_span(now=None):
    """The season at a time: ((year, month), end time). The real game's seasons are at the start of February, May, August and November
    (achievement_seasonpass_202608); the dates of a season in the table (season.calendar) override the rule."""
    now = time.time() if now is None else now
    t = datetime.datetime.fromtimestamp(now)
    rule = t.year - (t.month < 2), (t.month - 2) % 12 // 3 * 3 + 2
    for ym, a, b in WINDOWS:
        if a <= now and (now < b if b else rule <= ym):          # an open-ended season lasts until the month rule moves to the next one
            return ym, b or formula_end(*ym)
    return rule, formula_end(*rule)


def season_start(now=None):
    """The (year, month) the season started."""
    return season_span(now)[0]


def season_id(now=None):
    return '%d-%02d' % season_start(now)


def season_end(now=None):
    return season_span(now)[1]


ACTIVE = {}                 # the season being played {sid, end_time} (written by Season.ensure): the achievement group and timed recipes (assembly) look at this


def current_end(now=None):
    """The end of the season being played (save-specific); if unknown, that of the calendar's season."""
    return ACTIVE.get('end_time') or season_end(now)


def achievement_group(now=None):
    """This season's Season Pass achievement group (SEASONPASS_Qn; the client's LevelAbsolute achievements: "50 / 80 levels of the
    Gold Season Pass"). The real game's seasons are named by their start month (achievement_seasonpass_202608 = Q14); if the client has none for this season, that of the
    newest season that started before it (adaptation). If there is a season being played (ACTIVE), that one's."""
    import re
    import achievement as BS
    start = tuple(int(x) for x in ACTIVE['sid'].split('-')) if ACTIVE.get('sid') else season_start(now)
    best = None
    for aid, a in BS.ACH.items():
        m = re.match(r'achievement_seasonpass_(\d{4})(\d{2})$', aid)
        if m and (int(m.group(1)), int(m.group(2))) <= start and (best is None or m.groups() > best[0]):
            best = (m.groups(), a['group'])
    return best[1] if best else None


def day_id(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()


def week_id(now=None):
    y, w, _ = datetime.date.fromtimestamp(time.time() if now is None else now).isocalendar()
    return '%d-W%02d' % (y, w)


def level_of(points):
    total, lv = 0, 0
    for i, c in enumerate(COST):
        total += c
        if points >= total:
            lv = i
        else:
            break
    return lv


def threshold(lv):
    return sum(COST[:lv + 1])


def pool(qtype, gold):
    return sorted(q for q, m in MISSIONS.items() if m['type'] == qtype and m['gold'] == gold)


def pick(qtype, seed, counts, exclude=()):
    rng = random.Random(seed)
    out = []
    for gold, n in zip((False, True), counts):
        cands = [q for q in pool(qtype, gold) if q not in exclude]
        out += rng.sample(cands, min(n, len(cands)))
    return out


def refresh_price(n):
    """The cost of a quest refresh (U): the next one when n refreshes have been purchased (wiki: 1st-4th 500, 5th-7th 1,000, 8th-10th 2,000, after that 4,000)."""
    for last, cost in REFRESH_LADDER:
        if last is None or n < last:
            return cost


def seasons(now=None):
    """Ids of the seasons, oldest to newest (event_appearances.SEASONS: those with known designs); also newer seasons that started on the
    real calendar (their designs are sampled from the table: EG.season_track)."""
    cur = season_id(now)
    ids = [s['season'] for s in EG.SEASONS if s['season'] <= cur]        # a season in the table opens on its real start day
    return ids + [cur] if cur > ids[-1] else ids


def next_season(played, progressive, now=None):
    """The next season: in progressive mode the first season not yet played (the newest if none), otherwise the newest."""
    ids = seasons(now)
    return next((i for i in ids if i not in played), ids[-1]) if progressive else ids[-1]


def duration():
    return max(1, int(SET.get('season_duration'))) * 86400


def points_of(qid):
    return sum(r['amount'] for r in MISSIONS[qid]['definition']['rewards'] if r['lootId'] == POINT_ITEM)


class Season:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None              # shop (rewards, money messages; the session binds)
        self.send = None           # sending to the session (quest progress comes from events)
        self.quest_done = None     # Season Pass quest finished (category '5'/'6'/'2') -> msgs; the session sends it to the event systems
        self.map_id = None
        # prevents a nested event only within the same thread: events arriving at the same time from the world (kill, collect) and the session (buy, sell)
        # were knocking each other out with a shared flag
        self.local = threading.local()

    # ------------------------------------------------------------ state
    @property
    def st(self):
        return self.p.d.setdefault('season', {})

    def track(self, key):
        """The season's reward track: the record's with the season designs replaced by those in the season's track (event_appearances.season_track)."""
        return EG.season_track(key, S['reward'][key], self.st.get('period') or seasons()[-1])

    def end(self):
        """The end of the season being played: its start + the panel's duration."""
        return self.st.get('start', time.time()) + duration()

    def ended(self, now):
        return bool(self.st.get('period')) and (not self.st.get('start') or now >= self.end())

    def ensure(self, now=None):
        """If the season, day or week changed, renew -> messages to report."""
        now = time.time() if now is None else now
        st, msgs = self.st, []
        if '-Q' in st.get('period', ''):             # old format (calendar quarter): the season of the quarter's first day (so progress is not deleted)
            y, q = st['period'].split('-Q')
            with self.p.lock:
                st['period'] = season_id(datetime.datetime(int(y), int(q) * 3 - 2, 1).timestamp())
        if st.get('period') and not st.get('start'):    # old save tied to the calendar: its progress stays, the season continues from today
            with self.p.lock:
                st['start'] = now
                st.setdefault('played', [st['period']])
                self.p.dirty = True
        if not st.get('period') or self.ended(now):
            wait, played = [], list(st.get('played', []))
            if st.get('period'):
                ended, wait = self.close_season()
                msgs += ended
            sid = next_season(played, bool(self.p.d.get('progressive')), now)
            with self.p.lock:
                st.clear()
                st.update(period=sid, start=now, played=played + [sid], points=0, gold=False, ext=False,
                          claimed={k: [] for k, g, e in TRACKS}, value={}, done=[], seasonal=pool(SEASON, False) + pool(SEASON, True),
                          renewal={'day': 0, 'week': 0}, pending=wait)
                self.p.dirty = True
            self.log('   Season Pass season started: %s (%s, %d days)' % (sid, EG.season(sid)['name'], duration() // 86400))
            msgs += self.activate_items()
        ACTIVE.update(sid=st['period'], end_time=self.end())
        # quest ids that were removed from the pool (the pool was renewed per the wiki): the list is drawn again, old progress is deleted
        if any(q not in MISSIONS for q in st.get('daily', [])):
            st['day'] = None
        if any(q not in MISSIONS for q in st.get('weekly', [])):
            st['week'] = None
        if st.get('day') != day_id(now):
            self.reset_list('daily', DAILY, DAILY_N, 'day', day_id(now))
        if st.get('week') != week_id(now):
            self.reset_list('weekly', WEEKLY, WEEKLY_N, 'week', week_id(now))
        return msgs

    def reset_list(self, key, qtype, counts, stamp_key, stamp):
        st = self.st
        with self.p.lock:
            for q in st.get(key, []):
                st['value'].pop(str(q), None)
                if q in st['done']:
                    st['done'].remove(q)
            st[key] = pick(qtype, '%s|%s' % (st['period'], stamp), counts)
            st[stamp_key] = stamp
            st['renewal'][stamp_key] = 0
            self.p.dirty = True

    def missions(self):
        st = self.st
        return st.get('daily', []) + st.get('weekly', []) + st.get('seasonal', [])

    def level(self):
        return level_of(self.st.get('points', 0))

    def image(self):
        """The window's image: that of the season being played (from the record for those not on the official CDN)."""
        return S['images'].get(self.st.get('period'), S['visual'])

    def name(self):
        """The window's title: the moon phase of the season's month."""
        period = self.st.get('period') or seasons()[-1]
        return NAME_BY_MONTH.get(int(period.split('-')[1]), S['name'])

    def status_code(self, qid):
        gold, done = MISSIONS[qid]['gold'], qid in self.st['done']
        if not gold:
            return 3 if done else 0
        if self.st.get('gold'):
            return 4 if done else 1
        return 5 if done else 2

    # ------------------------------------------------------------ mesajlar
    def status_cmd(self, now=None, tips=False):
        st = self.st
        return ('SeasonPassStatusCommand', dict(pointsCost=list(COST), uridiumCost=list(UCOST), goldPass=bool(st.get('gold')),
                                                showTips=tips, marketingImage=self.image(), seasonName=self.name(),
                                                extGoldPass=bool(st.get('ext')),
                                                timeToEventEnd=max(0, int(self.end() - (time.time() if now is None else now)))))

    def reward_cmd(self):
        claimed = self.st['claimed']
        rows = {}
        for key, gold, ext in TRACKS:
            rows[key] = [mod('SeasonPassRewardModule', amount=n, goldPass=gold, claimed=lv in claimed[key], level=lv, extGoldPass=ext, lootId=l)
                         for lv, l, n in self.track(key)]
        return ('SeasonPassRewardInfoCommand', dict(goldPassRewardItems=rows['gold'], freeRewardItems=rows['free'],
                                                    extGoldPassRewardItems=rows['ext']))

    def refresh_info(self):
        y = self.st['renewal']
        free_left = max(0, 1 - y.get('day', 0))
        return mod('RefreshQuestInfo', nextDailyUridium=-1 if free_left else refresh_price(self.paid_refreshes('daily')), weeklyCount=0,
                   dailyLeft=free_left, dailyCount=1, nextWeeklyUridium=refresh_price(self.paid_refreshes('weekly')), weeklyLeft=0)

    def paid_refreshes(self, key):
        """Number of refreshes purchased this day (daily) or week (weekly) (the first of the daily is free)."""
        y = self.st['renewal']
        return max(0, y.get('day', 0) - 1) if key == 'daily' else y.get('week', 0)

    def mission_cmd(self):
        st = self.st
        items = [mod('SeasonPassMissionModule', missionStatus=mod('SeasonPassMissionStatusModule', type=self.status_code(q)),
                     questDefinitionModule=GT.with_state(MISSIONS[q]['definition'], st['value'].get(str(q), {}), q in st['done']))
                 for q in self.missions()]
        return ('SeasonPassMissionInfoCommand', dict(refreshInfo=self.refresh_info(), missionInfoType=0, missionItems=items))

    def points_cmd(self):
        return ('SeasonPointsInfoCommand', {'points': int(self.st.get('points', 0))})

    def login_msgs(self):
        msgs = self.ensure()
        # showTips: the client (UIMainCenterNewSystem.InitWindows) opens the window at login and clears the flag only on its own side. Since it was never
        # saved the window opened at every login (live test H56): once per season, the tip is reset in the new season
        tips = not self.st.get('tooltip')
        if tips:
            with self.p.lock:
                self.st['tooltip'] = True
                self.p.dirty = True
        self.level_event()                                          # achievement (old profiles: the level may already be past 50)
        return msgs + [self.status_cmd(tips=tips), self.mission_cmd(), self.points_cmd(), self.reward_cmd()] + self.unclaimed_msgs()

    def roster(self):
        return len((self.p.d.get('nova') or {}).get('roster', []))

    def roster_full(self, loot, n):
        """Is there no room in the roster for the N.O.V.A. reward (nova.py's hire would turn the captain into uridium when the roster is full)."""
        return loot.startswith('captain_') and self.roster() + n > NV.D['max_roster']

    def unclaimed_msgs(self):
        """The end-of-season window if there are N.O.V.A.s pending from the previous season."""
        wait = sum(n for l, n in self.st.get('pending', []))
        if not wait:
            return []
        return [('SeasonPassRewardUnclaimedInfoCommand', dict(captainLimit=NV.D['max_roster'], captainPending=wait,
                                                              captainOwned=self.roster(), captainWarning=self.roster_full('captain_', wait),
                                                              spcId=0, marketingImage=self.image(), seasonName=self.name()))]

    # ------------------------------------------------------------ points and Gold Pass
    def add_points(self, n, bought=False):
        """Adds points. bought: from a points package; the part that overflows above the maximum level becomes 1 point = 10 Honor (wiki)."""
        old = self.level()
        with self.p.lock:
            total = self.st.get('points', 0) + n
            excess = min(n, max(0, total - threshold(MAX_LEVEL))) if bought else 0
            self.st['points'] = total - excess
            self.p.dirty = True
        msgs = []
        if excess:
            honor = excess * OVERFLOW_HONOR
            if self.m:
                msgs += self.m.reward('currency_honour', honor)
            else:
                self.p.gain(honor=honor)
            self.log('   Season Pass points exceeded the maximum level: %d points -> %d Honor' % (excess, honor))
        if self.level() > old:
            self.log('   Season Pass level %d (%d points)' % (self.level(), self.st['points']))
            self.level_event()
            return msgs + [self.points_cmd(), self.reward_cmd()]       # the grid opens only with the reward list (live test H44)
        return msgs + [self.points_cmd()]

    def level_event(self):
        """Achievement: the Gold Season Pass's level (LevelAbsolute; 0 if no Gold Pass)."""
        self.p.ach('season_level', value=self.level() if self.st.get('gold') else 0, group=achievement_group())

    def activate_items(self):
        """The Gold / Extra Gold Pass in storage to this season (Extra only after Gold) -> messages."""
        msgs = []
        st = self.st
        if not st.get('gold') and self.p.resource(GOLD_ITEM) > 0:
            self.p.add_resource(GOLD_ITEM, -1)
            with self.p.lock:
                st['gold'] = True
                self.p.dirty = True
            pend = [q for q in self.missions() if MISSIONS[q]['gold'] and q in st['done']]
            for q in pend:                                          # points of Gold quests finished before the Gold Pass
                msgs += self.add_points(points_of(q))
            self.log('   Gold Pass active (%s)%s' % (st['period'], ', points of %d quests' % len(pend) if pend else ''))
            self.level_event()                                      # the level reached before the Gold Pass counts too
        if st.get('gold') and not st.get('ext') and self.p.resource(EXT_ITEM) > 0:
            self.p.add_resource(EXT_ITEM, -1)
            with self.p.lock:
                st['ext'] = True
                self.p.dirty = True
            self.log('   Extra Gold Pass active (%s)' % st['period'])
        return msgs

    def grant(self, loot, n):
        """Shop reward: Season Pass points or Gold/Extra Gold Pass -> messages."""
        self.ensure()
        if loot == POINT_ITEM:
            return self.add_points(n, bought=True)
        self.p.add_resource(loot, n)
        msgs = self.activate_items()
        return msgs + [self.status_cmd(), self.mission_cmd(), self.reward_cmd(), self.points_cmd()]

    # ------------------------------------------------------------ quests
    def event(self, kind, **kw):
        """Game event -> quest progress (sent to the session)."""
        if getattr(self.local, 'busy', False) or not self.p.d.get('season'):
            return []
        self.local.busy = True
        try:
            msgs = self._event(kind, kw)
        finally:
            self.local.busy = False
        if msgs and self.send:
            self.send(msgs)
        return msgs

    def _event(self, kind, kw):
        msgs, done = [], []
        st = self.st
        for q in self.missions():
            if q in st['done']:
                continue
            vals = st['value'].setdefault(str(q), {})
            m, fin = GT.advance(self.p, MISSIONS[q]['definition']['rootCase'], vals, kind, kw, self.map_id)
            msgs += m
            if fin:
                done.append(q)
        for q in done:
            msgs += self.complete(q)
        for q in done:                                              # season quests: finish N daily/weekly
            cat = GT.SP_CATEGORY[MISSIONS[q]['type']]
            msgs += self._event('sp_quest', dict(category=cat))
            if self.quest_done:                                     # Recall Battle Pass, Return of Hero quests that count them
                msgs += self.quest_done(cat)
        return msgs

    def complete(self, qid):
        st = self.st
        with self.p.lock:
            if qid not in st['done']:
                st['done'].append(qid)
            self.p.dirty = True
        qt = MISSIONS[qid]['type']
        msgs = [legacy('0|A|STM|%s' % DONE_TEXT[qt]), ('QuestCompletedCommand', {'id': qid, 'rating': 0})]
        locked = MISSIONS[qid]['gold'] and not st.get('gold')
        if not locked:
            bonus = self.p.mods().get('season_points', 0)                     # N.O.V.A. Bonus Hunter / Bonus Slayer (nova.py)
            msgs += self.add_points(int(round(points_of(qid) * (1 + bonus) * SET.multiplier('season_points'))))      # panel
        if qt == DAILY and self.m:                                          # daily quest: Armory Token (Stage 9; armory.py)
            import armory as AU
            msgs += self.m.reward(AU.TOKEN, AU.D['daily_quest_token'])
        self.p.ach('quest', id=qid)                                  # record: a Season Pass quest counts in the achievements
        self.log('   Season Pass quest finished: %d (%s, %d points%s)' % (qid, {DAILY: 'daily', WEEKLY: 'weekly', SEASON: 'season'}[qt],
                                                                     points_of(qid), ', Gold Pass waiting' if locked else ''))
        return msgs

    # ------------------------------------------------------------ requests
    def claimable(self, key, lv):
        st = self.st
        if lv > self.level() or lv in st['claimed'][key]:
            return None
        if key == 'gold' and not st.get('gold') or key == 'ext' and not st.get('ext'):
            return None
        return next(((l, n) for rlv, l, n in self.track(key) if rlv == lv), None)

    def give(self, key, lv):
        got = self.claimable(key, lv)
        if not got:
            return None
        with self.p.lock:
            self.st['claimed'][key].append(lv)
            self.p.dirty = True
        l, n = got
        self.log('   Season Pass reward: level %d %s: %s x%d' % (lv, key, l, n))
        return self.m.reward(l, n) if self.m else []

    def claim(self, f):
        self.ensure()
        lv = int(f.get('level') or 0)
        key = 'ext' if f.get('extGoldPass') else 'gold' if f.get('goldPass') else 'free'
        got = self.claimable(key, lv)
        if got and self.roster_full(*got):
            return [('SeasonPassCaptainLimitCommand', {})]
        msgs = self.give(key, lv)
        if msgs is None:
            return [legacy('0|A|STM|sp_error_no-claimable-rewards')]
        return msgs + [('SeasonPassRewardClaimCommand', dict(extGoldPass=key == 'ext', goldPass=key == 'gold', claimed=True, level=lv))]

    def claim_all(self, f=None):
        """Claim All or the end-of-season window's button (spcId): first the N.O.V.A.s pending from the previous season."""
        self.ensure()
        msgs, n, full = [], 0, False
        for row in list(self.st.get('pending', [])):
            if self.roster_full(*row):
                full = True
                continue
            with self.p.lock:
                self.st['pending'].remove(row)
                self.p.dirty = True
            msgs += self.m.reward(*row) if self.m else []
            n += 1
        for key, gold, ext in TRACKS:
            for lv, l, a in self.track(key):
                got = self.claimable(key, lv)
                if got and self.roster_full(*got):
                    full = True
                    continue
                got = self.give(key, lv)
                if got is not None:
                    n += 1
                    msgs += got + [('SeasonPassRewardClaimCommand', dict(extGoldPass=ext, goldPass=gold, claimed=True, level=lv))]
        if full:
            msgs.append(('SeasonPassCaptainLimitCommand', {}))
        if not n:
            return msgs or [legacy('0|A|STM|sp_error_no-claimable-rewards')]
        return msgs + [self.reward_cmd()]

    def buy_levels(self, f):
        self.ensure()
        cur = self.level()
        n = max(0, min(int(f.get('amount') or 0), MAX_LEVEL - cur))
        cost = sum(UCOST[cur + 1:cur + 1 + n])
        pl = self.p.d['pilot']
        if not n or pl.get('uridium', 0) < cost:
            self.log('   Season Pass level could not be bought: %d levels, %d U' % (n, cost))
            return [('SeasonPassLevelPurchaseCommand', {'success': False})]
        tot = self.p.gain(uridium=-cost, reason='buy_SPECIAL', detail='season_pass_level')
        with self.p.lock:
            self.st['points'] = max(self.st.get('points', 0), threshold(cur + n))
            self.p.dirty = True
        self.log('   Season Pass: %d levels bought (%d U) -> %d' % (n, cost, self.level()))
        self.level_event()
        return ([('SeasonPassLevelPurchaseCommand', {'success': True}), self.points_cmd(), self.reward_cmd()]     # grid (H44)
                + (self.m.money_msgs() if self.m else []))

    def refresh(self, f):
        """SeasonPassRefreshRequest: another one from the pool in place of a daily/weekly quest (a finished quest is not refreshed)."""
        self.ensure()
        st, qid = self.st, int(f.get('questId') or 0)
        key = 'daily' if qid in st.get('daily', []) else 'weekly' if qid in st.get('weekly', []) else None
        if not key or qid in st['done']:
            return [self.mission_cmd()]
        stamp = 'day' if key == 'daily' else 'week'
        free = key == 'daily' and st['renewal'].get('day', 0) < 1
        cost = 0 if free else refresh_price(self.paid_refreshes(key))
        qt, gold = MISSIONS[qid]['type'], MISSIONS[qid]['gold']
        cands = [q for q in pool(qt, gold) if q not in st[key]]
        if not cands:                                              # no quest to change: no cost is charged
            return [self.mission_cmd()]
        if cost:
            if self.p.d['pilot'].get('uridium', 0) < cost:
                return [legacy('0|A|STM|not_enough_uridium'), self.mission_cmd()]
            self.p.gain(uridium=-cost, reason='buy_SPECIAL', detail='season_pass_refresh')
        new = random.choice(cands)
        with self.p.lock:
            st[key][st[key].index(qid)] = new
            st['value'].pop(str(qid), None)
            st['renewal'][stamp] = st['renewal'].get(stamp, 0) + 1
            self.p.dirty = True
        self.log('   Season Pass quest refreshed: %d -> %d%s' % (qid, new, '' if free else ' (%d U)' % cost))
        return [self.mission_cmd()] + ([] if free or not self.m else self.m.money_msgs())

    def close_season(self):
        """Season ended: unclaimed rewards of the levels reached are given; N.O.V.A.s wait -> (messages, pending)."""
        msgs, n, wait = [], 0, []
        for key, gold, ext in TRACKS:
            for lv, l, a in self.track(key):
                got = self.claimable(key, lv)
                if got and got[0].startswith('captain_'):
                    wait.append(list(got))
                    continue
                got = self.give(key, lv)
                if got is not None:
                    msgs += got
                    n += 1
        self.log('   Season Pass season ended (%s): %d rewards given, %d N.O.V.A. pending' % (self.st.get('period'), n, len(wait)))
        return msgs + [legacy('0|A|STM|sp_season-has-ended_description')], wait

    def handle(self, name, f):
        fn = {'SeasonPassRewardClaimRequest': self.claim, 'SeasonPassRewardClaimAllRequest': self.claim_all,
              'SeasonPassLevelPurchaseRequest': self.buy_levels, 'SeasonPassRefreshRequest': self.refresh}.get(name)
        return fn(f) if fn else None

    def tick(self, now):
        if self.p.d.get('season') and (self.st.get('day') != day_id(now) or self.ended(now)):
            ended = self.ended(now)
            msgs = self.ensure(now) + [self.status_cmd(now), self.mission_cmd(), self.points_cmd(), self.reward_cmd()]
            msgs += self.unclaimed_msgs() if ended else []
            if self.send:
                self.send(msgs)
