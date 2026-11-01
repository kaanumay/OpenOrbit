"""Recall (Return) Battle Pass (client 1.1.115; data in data/tickets.json 'return_pass' <- tools/version_115.py; the quest pool is the
Season Pass's, season.py).

During Return of Hero (calendar return_of_hero) the menu item 'recallBattlePass'. From the client's code (UIRecallBattlePassSystem):
  opening     RecallBattlePassActionRequest {action 0 VIEW, requestId} -> RecallBattlePassViewCommand (same requestId; specialId > 0;
              pointsCost per level, the levels' requiredExperience is a cumulative threshold and the lists must be the same length; if a
              reward's count is 0 the lootId may be empty) and RecallBattlePassPointsInfoCommand {points}: the window opens once both arrive.
              Level = number of thresholds passed (starts from 0). Error: RecallBattlePassActionResultCommand {result 0 INACTIVE, 3 SERVER_ERROR}
  reward      RecallBattlePassRewardClaimRequest {track {type 0 FREE, 1 RETURN, 2 VIP}, level} -> RewardClaimResultCommand {result 0
              SUCCESS, 1 ALREADY_CLAIMED, 2 INACTIVE, 5 LEVEL_LOCKED, 6 RETURN_INELIGIBLE, 7 VIP_REQUIRED}; the client marks the row itself
              RecallBattlePassRewardClaimAllRequest -> ClaimAllResultCommand {claimedCount, result}; the client asks for the view again
  level       RecallBattlePassLevelPurchaseRequest {amount, expectedPoints, maxUridium, quoteOnly}: first a quote (quoteOnly), confirm
              the purchase -> LevelPurchaseCommand {success, result 0 SUCCESS / 6 STALE_POINTS / 7 PRICE_CHANGED / 8 INSUFFICIENT_URIDIUM,
              originalLevel, targetLevel, currentPoints, resultingPoints, uridiumCost}; on purchase the points become resultingPoints
  quests      RecallBattlePassMissionRequest -> MissionInfoCommand {missionInfoType 0 REPLACE, refreshInfo, missionItems
              [MissionModule {questDefinitionModule, period 0 DAILY / 1 WEEKLY / 2 SEASON, periodStart, nextReset (unix s),
              missionStatus {type 0 NORMAL_RUNNING, 1 VIP_RUNNING, 2 VIP_LOCKED_INCOMPLETE, 3 NORMAL_COMPLETED, 4 VIP_COMPLETED,
              5 VIP_LOCKED_COMPLETE}, experience}]}; RecallBattlePassMissionRefreshRequest -> MissionRefreshResultCommand {result 0
              SUCCESS, 5 NO_FREE_REFRESH, 7 INSUFFICIENT_URIDIUM}; the client asks for the list again
  VIP         opens the "Buy" payment page in the window (JavascriptHelper.OpenWebUrl PAY_TYPE RecallPassVip): payment.py opens the shop,
              Return VIP Badge (resource_recall-pass-vip-badge) from the pack; the badge is used up as soon as it is bought (bought) or
              found in the inventory (ensure), and the open window gets a fresh view with its last requestId (refresh_msgs)
Levels, costs, specialId and quests are from the official server recording (2026-10-25). Single player: the player is a returning hero (HeroState
TRUE; in Return of Hero, when tied to a veteran, INVITEE), so the Return track is open; a non-returnee (FALSE) gets RETURN_INELIGIBLE.
The quests are those in the recording:
daily 3 + 2 VIP every day, weekly 5 + 3 VIP on Monday, throughout the 12-season period; on refresh the replacement comes from the Season Pass pool
(ids shifted; Gold quests are the VIP quests, the experience is Season Pass points). Refresh is free once a day, then 500 U (weekly 500 U).
In the profile: return_pass {period, version, points, vip, claimed {0: [], 1: [], 2: []}, day, daily, week, weekly, seasonal, value, done,
renewal}.
"""
import datetime, json, os, random, time

import quest_tracker as GT
import season as SE
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, 'data', 'tickets.json'), encoding='utf8'))['return_pass']
EVENT, SPECIAL, VIP_ITEM = R['calendar'], R['special_id'], R['vip']
COST, UCOST = R['point_cost'], R['uridium_cost']
LEVELS = {r[0]: r[1:] for r in R['levels']}               # level -> [[free], [return], [vip]]
MAX_LEVEL = len(COST)
OFS = R['quest_id_offset']
FREE, RETURN, VIP = 0, 1, 2
HERO_FALSE, HERO_TRUE, HERO_INVITEE = 1, 2, 4                  # client HeroState: NONE 0, FALSE 1, TRUE 2, INVITER 3, INVITEE 4
PERIOD = {SE.DAILY: 0, SE.WEEKLY: 1, SE.SEASON: 2}
REFRESH_U = R['refresh_uridium']


def mod(name, **f):
    f['_'] = name
    return f


def shifted(node):
    """A Season Pass quest's definition, ids shifted (separate quests in the two windows) and without reward (the experience is in MissionModule)."""
    if isinstance(node, dict):
        out = {k: shifted(v) for k, v in node.items() if k != 'rewards'}
        if isinstance(out.get('id'), int) and out['id'] > 0:
            out['id'] += OFS
        return out
    if isinstance(node, list):
        return [shifted(x) for x in node]
    return node


REAL = {m['definition']['id']: m for m in R['quests']}              # the quests in the recording (sourceQuestId: 'source')
MISSIONS = {**{q + OFS: dict(m, definition=shifted(m['definition']), source=q + OFS) for q, m in SE.MISSIONS.items()}, **REAL}
VERSION = R['quest_version']


def thresholds():
    out, t = [], 0
    for c in COST:
        t += c
        out.append(t)
    return out


def level_of(points):
    return sum(1 for t in thresholds() if points >= t)


def pool(qtype, gold):
    return [q for q, m in MISSIONS.items() if m['type'] == qtype and m['gold'] == gold]


def listed(qtype):
    """The period's quests: those in the recording, in the recording's order."""
    return [q for q, m in REAL.items() if m['type'] == qtype]


def day_start(now):
    return datetime.datetime.combine(datetime.date.fromtimestamp(now), datetime.time()).timestamp()


def week_start(now):
    d = datetime.date.fromtimestamp(now)
    return datetime.datetime.combine(d - datetime.timedelta(days=d.weekday()), datetime.time()).timestamp()


class ReturnPass:
    REQUESTS = ('RecallBattlePassActionRequest', 'RecallBattlePassRewardClaimRequest', 'RecallBattlePassRewardClaimAllRequest',
                'RecallBattlePassLevelPurchaseRequest', 'RecallBattlePassMissionRequest', 'RecallBattlePassMissionRefreshRequest')

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.hero = None                 # the session binds it: whether tied to a veteran in Return of Hero (shops.py)
        self.returning = True            # single player: the player is always the returning hero (Return track open)
        self.open = False                # whether the window is open (PointsInfoCommand when the points change)
        self.rid = {'view': 0, 'mission': None}   # last requestIds of the open window (pushed refreshes reuse them)
        if shop is not None:
            shop.on_bought.append(self.bought)

    @property
    def st(self):
        return self.p.d.setdefault('return_pass', {})

    def active(self, now=None):
        return CAL.is_active(EVENT, now)

    def ensure(self, now=None):
        now = time.time() if now is None else now
        st = self.st
        per = CAL.period(EVENT, now)
        key = '%s-%d' % (EVENT, time.localtime(per[0] if per else now).tm_year)
        if st.get('period') != key:
            with self.p.lock:
                st.clear()
                st.update(period=key, points=0, vip=False, claimed={str(t): [] for t in (FREE, RETURN, VIP)}, value={}, done=[],
                          renewal={'day': 0, 'week': 0})
                self.p.dirty = True
        if st.get('version') != VERSION:          # new period or the quests changed (2026-10-25: those in the recording): lists from the start
            self.reset_list('seasonal', SE.SEASON)
            with self.p.lock:
                st.update(version=VERSION, day=None, week=None)
        if st.get('day') != SE.day_id(now):
            self.reset_list('daily', SE.DAILY, 'day', SE.day_id(now))
        if st.get('week') != SE.week_id(now):
            self.reset_list('weekly', SE.WEEKLY, 'week', SE.week_id(now))
        if not st.get('vip') and self.p.resource(VIP_ITEM) > 0:     # Return VIP Badge (paketten): pass'e
            self.p.add_resource(VIP_ITEM, -1)
            with self.p.lock:
                st['vip'] = True
                self.p.dirty = True
            pend = sum(MISSIONS[q]['points'] for q in st['done'] if MISSIONS[q]['gold'])
            self.add_points(pend)                                 # pending experience of the VIP quests
            self.log('   Recall Battle Pass: VIP active (%d pending points)' % pend)
            return True
        return False

    def refresh_msgs(self):
        """Fresh view, points and missions for the window that is already open. The client only asks for the view when the
        window is first opened, and accepts a pushed view only with its last requestId (UIRecallBattlePassSystem.OnViewCommand
        compares it), so reuse the ids of its last requests."""
        if not self.open:
            return []
        msgs = [self.view_cmd(self.rid['view']), self.points_cmd()]
        if self.rid.get('mission') is not None:
            msgs.append(self.mission_cmd(self.rid['mission']))
        return msgs

    def bought(self, loot, amount):
        """Shop purchase (shop.on_bought): a package with the Return VIP Badge turns VIP on right away and refreshes the open
        window (before this, the badge waited for the next request and the window kept its "Buy" button)."""
        if not self.active() or VIP_ITEM not in {g for g, n in (self.m.contents(loot, amount) or [])}:
            return []
        return self.refresh_msgs() if self.ensure() else []

    def reset_list(self, key, qtype, stamp_key=None, stamp=None):
        st = self.st
        with self.p.lock:
            for q in st.get(key, []):
                st['value'].pop(str(q), None)
                if q in st['done']:
                    st['done'].remove(q)
            st[key] = listed(qtype)
            if stamp_key:
                st[stamp_key] = stamp
                st['renewal'][stamp_key] = 0
            self.p.dirty = True

    def level(self):
        return level_of(self.st.get('points', 0))

    def add_points(self, n):
        if n <= 0:
            return []
        with self.p.lock:
            self.st['points'] = self.st.get('points', 0) + n
            self.p.dirty = True
        return [self.points_cmd()] if self.open else []

    # ------------------------------------------------------------ mesajlar
    def points_cmd(self):
        return ('RecallBattlePassPointsInfoCommand', dict(points=int(self.st.get('points', 0)), specialId=SPECIAL))

    def eligible(self):
        """Return track: open to a returning hero (client HeroState TRUE, or INVITEE once bound to a veteran). Binding in
        Return of Hero is not required: requiring it locked the track for players who never entered an invite code."""
        return self.hero_state() in (HERO_TRUE, HERO_INVITEE)

    def hero_state(self):
        if self.hero and self.hero():
            return HERO_INVITEE                                     # returning hero tied to a veteran
        return HERO_TRUE if self.returning else HERO_FALSE

    def view_cmd(self, rid, now=None):
        claimed, th = self.st['claimed'], thresholds()
        rows = []
        for i in range(1, MAX_LEVEL + 1):
            (fl, fn), (rl, rn), (vl, vn) = LEVELS[i]
            rows.append(mod('RecallBattlePassLevelModule', level=i, requiredExperience=th[i - 1],
                            freeLootId=fl, freeAmount=fn, freeClaimed=i in claimed[str(FREE)],
                            returnLootId=rl, returnAmount=rn, returnClaimed=i in claimed[str(RETURN)],
                            vipLootId=vl, vipAmount=vn, vipClaimed=i in claimed[str(VIP)]))
        return ('RecallBattlePassViewCommand', dict(
            requestId=int(rid), specialId=SPECIAL, heroState=self.hero_state(), inviteCount=0, returnEligible=self.eligible(),
            vipOwned=bool(self.st.get('vip')), vipPurchaseEnabled=not self.st.get('vip'), claimsEnabled=True,
            levelPurchaseEnabled=self.level() < MAX_LEVEL, levelPurchaseCap=MAX_LEVEL, pointsCost=list(COST), uridiumCost=list(UCOST),
            timeToEventEnd=int(CAL.time_left(EVENT, now)), levels=rows))

    def status(self, q):
        gold, done = MISSIONS[q]['gold'], q in self.st['done']
        if not gold:
            return 3 if done else 0
        if self.st.get('vip'):
            return 4 if done else 1
        return 5 if done else 2

    def refresh_info(self):
        y = self.st['renewal']
        free = max(0, 1 - y.get('day', 0))
        return mod('RecallBattlePassMissionRefreshInfo', dailyCount=1, dailyLeft=free, dailySequence=int(y.get('day', 0)),
                   nextDailyUridium=-1 if free else REFRESH_U, weeklyCount=0, weeklyLeft=0, weeklySequence=int(y.get('week', 0)),
                   nextWeeklyUridium=REFRESH_U)

    def mission_cmd(self, rid, now=None):
        now = time.time() if now is None else now
        st = self.st
        spans = {0: (day_start(now), day_start(now) + 86400), 1: (week_start(now), week_start(now) + 7 * 86400),
                 2: (0, 0)}                                         # seasonal: both are 0 (recording)
        items = []
        for q in st.get('daily', []) + st.get('weekly', []) + st.get('seasonal', []):
            p = PERIOD[MISSIONS[q]['type']]
            items.append(mod('RecallBattlePassMissionModule', sourceQuestId=MISSIONS[q]['source'], period=p, periodStart=int(spans[p][0]),
                             nextReset=int(spans[p][1]), experience=MISSIONS[q]['points'],
                             missionStatus=mod('RecallBattlePassMissionStatusModule', type=self.status(q)),
                             questDefinitionModule=GT.with_state(MISSIONS[q]['definition'], st['value'].get(str(q), {}), q in st['done'])))
        return ('RecallBattlePassMissionInfoCommand', dict(requestId=int(rid), specialId=SPECIAL, missionInfoType=0,
                                                           refreshInfo=self.refresh_info(), missionItems=items))

    # ------------------------------------------------------------ requests
    def handle(self, name, f):
        rid = int(f.get('requestId') or 0)
        if not self.active():
            if name == 'RecallBattlePassActionRequest':
                return [('RecallBattlePassActionResultCommand', dict(requestId=rid, specialId=int(f.get('specialId') or 0), result=0))]
            return []
        self.ensure()
        if name == 'RecallBattlePassActionRequest':
            self.open = True
            self.rid['view'] = rid
            return [self.view_cmd(rid), self.points_cmd()]
        if name == 'RecallBattlePassRewardClaimRequest':
            t = int((f.get('track') or {}).get('type') or 0)
            res, msgs = self.claim(t, int(f.get('level') or 0))
            return msgs + [('RecallBattlePassRewardClaimResultCommand', dict(requestId=rid, specialId=SPECIAL, level=int(f.get('level') or 0),
                                                                              track=mod('RecallBattlePassRewardTrackModule', type=t),
                                                                              result=res))]
        if name == 'RecallBattlePassRewardClaimAllRequest':
            msgs, n = [], 0
            for i in range(1, self.level() + 1):
                for t in (FREE, RETURN, VIP):
                    res, got = self.claim(t, i)
                    if res == 0:
                        msgs += got
                        n += 1
            return msgs + [('RecallBattlePassRewardClaimAllResultCommand', dict(requestId=rid, specialId=SPECIAL, claimedCount=n, result=0))]
        if name == 'RecallBattlePassLevelPurchaseRequest':
            return self.purchase(f, rid)
        if name == 'RecallBattlePassMissionRequest':
            self.rid['mission'] = rid
            return [self.mission_cmd(rid)]
        if name == 'RecallBattlePassMissionRefreshRequest':
            return self.refresh(f, rid)
        return []

    def claim(self, track, lv):
        """-> (result, messages): 0 SUCCESS, 1 ALREADY_CLAIMED, 4 INVALID_REQUEST, 5 LEVEL_LOCKED, 6 RETURN_INELIGIBLE, 7 VIP_REQUIRED."""
        st = self.st
        if lv not in LEVELS or track not in (FREE, RETURN, VIP):
            return 4, []
        if lv > self.level():
            return 5, []
        if track == RETURN and not self.eligible():
            return 6, []
        if track == VIP and not st.get('vip'):
            return 7, []
        if lv in st['claimed'][str(track)]:
            return 1, []
        loot, n = LEVELS[lv][track]
        with self.p.lock:
            st['claimed'][str(track)].append(lv)
            self.p.dirty = True
        self.log('   Recall Battle Pass reward: level %d %s: %s x%d' % (lv, ('free', 'return', 'vip')[track], loot, n))
        return 0, (self.m.reward(loot, n) if self.m and n else [])

    def purchase(self, f, rid):
        st, th = self.st, thresholds()
        pts, cur = st.get('points', 0), self.level()
        n = max(0, min(int(f.get('amount') or 0), MAX_LEVEL - cur))
        target = cur + n
        cost = sum(UCOST[cur:target])
        res = dict(requestId=rid, specialId=SPECIAL, quoteOnly=bool(f.get('quoteOnly')), amount=n, originalLevel=cur, targetLevel=target,
                   currentPoints=int(pts), resultingPoints=int(th[target - 1]) if n else int(pts), uridiumCost=int(cost))
        fail = lambda code: [('RecallBattlePassLevelPurchaseCommand', dict(res, success=False, result=code))]
        if not n:
            return fail(5)                                            # LEVEL_CAP
        if f.get('quoteOnly'):
            return [('RecallBattlePassLevelPurchaseCommand', dict(res, success=True, result=0))]
        if int(f.get('expectedPoints') or 0) != pts:
            return fail(6)                                            # STALE_POINTS
        if int(f.get('maxUridium') or 0) < cost:
            return fail(7)                                            # PRICE_CHANGED
        if self.p.d['pilot'].get('uridium', 0) < cost:
            return fail(8)                                            # INSUFFICIENT_URIDIUM
        self.p.gain(uridium=-cost, reason='buy_SPECIAL', detail='recall_pass_level')
        with self.p.lock:
            st['points'] = th[target - 1]
            self.p.dirty = True
        self.log('   Recall Battle Pass: %d levels bought (%d U) -> %d' % (n, cost, target))
        return ([('RecallBattlePassLevelPurchaseCommand', dict(res, success=True, result=0, currentPoints=int(st['points'])))]
                + (self.m.money_msgs() if self.m else []))

    def refresh(self, f, rid):
        """Another quest from the pool in place of a daily or weekly quest: 0 SUCCESS, 3 STALE_MISSION, 7 INSUFFICIENT_URIDIUM, 9 NO_REPLACEMENT."""
        st, q = self.st, int(f.get('questId') or 0)
        # the client may send the source id (sourceQuestId) or the definition's
        q = next((x for x in st.get('daily', []) + st.get('weekly', []) if q in (x, MISSIONS[x]['source'])), q)
        key = 'daily' if q in st.get('daily', []) else 'weekly' if q in st.get('weekly', []) else None
        done = lambda code, extra=(): list(extra) + [('RecallBattlePassMissionRefreshResultCommand',
                                                      dict(requestId=rid, specialId=SPECIAL, result=code))]
        if not key or q in st['done']:
            return done(3)
        stamp = 'day' if key == 'daily' else 'week'
        free = key == 'daily' and st['renewal'].get('day', 0) < 1
        cands = [c for c in pool(MISSIONS[q]['type'], MISSIONS[q]['gold']) if c not in st[key]]
        if not cands:
            return done(9)
        if not free:
            if self.p.d['pilot'].get('uridium', 0) < REFRESH_U:
                return done(7)
            self.p.gain(uridium=-REFRESH_U, reason='buy_SPECIAL', detail='recall_pass_refresh')
        new = random.choice(cands)
        with self.p.lock:
            st[key][st[key].index(q)] = new
            st['value'].pop(str(q), None)
            st['renewal'][stamp] = st['renewal'].get(stamp, 0) + 1
            self.p.dirty = True
        self.log('   Recall Battle Pass quest refreshed: %d -> %d%s' % (q, new, '' if free else ' (%d U)' % REFRESH_U))
        return done(0, [] if free or not self.m else self.m.money_msgs())

    # ------------------------------------------------------------ quest progress
    def event(self, kind, kw):
        if not self.p.d.get('return_pass') or not self.active():
            return []
        st, done = self.st, []
        msgs = self.refresh_msgs() if self.ensure() else []      # badge picked up here: show VIP in the open window
        for q in st.get('daily', []) + st.get('weekly', []) + st.get('seasonal', []):
            if q in st['done']:
                continue
            m, fin = GT.advance(self.p, MISSIONS[q]['definition']['rootCase'], st['value'].setdefault(str(q), {}), kind, kw,
                                self.p.d['position'].get('mapId'),
                                notify=False)
            msgs += m
            if fin:
                done.append(q)
        for q in done:
            with self.p.lock:
                st['done'].append(q)
                self.p.dirty = True
            locked = MISSIONS[q]['gold'] and not st.get('vip')
            msgs += [] if locked else self.add_points(MISSIONS[q]['points'])
            self.log('   Recall Battle Pass quest done: %d (%d points%s)' % (q, MISSIONS[q]['points'], ', VIP pending' if locked else ''))
        return msgs


for _q, _m in MISSIONS.items():
    if _q not in REAL:
        _m['points'] = SE.points_of(_q - OFS)
