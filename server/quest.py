"""Quests: quest list, info, accept/cancel, progress and rewards (the flows in the record). Data: data/quests.json (tools/quests.py).

Flows in the record:
  approaching a quest giver  QuestGiversAvailableCommand(quest giver) + QuestListCommand; moving away an empty list
  QuestInfoRequest           -> QuestInfoCommand(definition, points)
  QuestAcceptRequest         -> QuestInitializationCommand(definition, condition states) + QuestListCommand
  progress                   -> QuestConditionUpdateCommand(condition, value/active/done); on reaching the target first the value, then done
                                and the next condition active. When "Return to the quest giver" becomes active a mark on the minimap (CreateMinimapMark)
  QuestGiverApproachedRequest -> return condition + QuestCompletedCommand + RemoveMinimapMark + rewards + QuestListCommand
  QuestCancelRequest         -> RemoveMinimapMark + QuestCancelledCommand + QuestListCommand
Time-limited quest ("sure_sn"; a HASTE condition in the definition, its value the elapsed ms): if time runs out or the restriction is broken ("basarisiz": death,
shooting a player of a company) QuestFailedCommand {id} (the client removes the quest with the "q2_failed_quest" message) + QuestListCommand; the quest
can be accepted again. Time runs in real time (also after leaving the game).
List states (the client's AcceptabilityType): 0 cannot be accepted (missing level/previous quest), 1 can be accepted, 2 in progress, 3 completed.
Quest limit: the list's maxQuests is the number of free slots, not the total (record: 5 with no quest, 4 with one in progress). The client keeps it
in QuestComponent.MaxAcceptedQuests, shows it in its window as "n quest slots free" (label_questslots_free_s) and when it reaches 0
disables accepting (QuestComponentSystem.IsQuestSlotLimitReached). The limit is the panel's 'max_quests' setting (the game's value is MAX_QUESTS).
The window's tabs (QuestType; E6, data/quest_extras.json): 3 daily and 6 weekly quests one per difficulty (daily changes every day, weekly on
Monday; if one in progress passes its period it fails), 5 event quests in a separate slot (maxEventQuests, empty slot), 4 challenges
unranked: taken again, the score is the completion time (s), the personal best in the quest info. Measuring the conditions is shared with the Pass quests
(quest_tracker.measure); here only the types specific to main quests and positions resolved by the player's company. Restrictions ("failed"):
death, shooting a player of a company, damage limit (AVOID_DAMAGE display), killing a forbidden alien, forbidden ammo (type: 1 laser,
2 rocket, 3 mine, 0 all; SAVE_AMMUNITION display). Score quest ("points": ids of the target-less kill conditions; "as many as
possible"): the completion score is the number of kills, the best is the most. Company-specific challenge ("company"): visible only to that company's pilot.
Dailies with level pools ("pool": {"level": 3 | 10 | 15 | 17}; darkorbitwiki Daily Missions): from each pool one at random per day
(a fixed choice derived from the date and level), ends 24 hours after accepting (REAL_TIME_HASTE: the client counts the remaining time itself; when time is up it
fails). In difficulty pools (Tetrathrin daily, Kyhalon weekly) only one can be in progress at a time (the client's
EXCLUSIVE_POOL_QUEST_RUNNING condition: the others cannot be accepted). Elite quests ("hidden": not shown in the list until the prerequisite is finished; not in the record either).
Special quests (event quests, "event": calendar keys): listed only while the event is open, and if in progress when the event ends they fail;
"repeat": once a day (daily) or once per event (event); "title": an achievement title on completion.
In the profile: quests.active {quest: {condition: value}}, quests.done [quest], quests.period {daily/weekly/repeating quest: the period it was completed in},
quests.score {challenge: best time (score in a score quest)}.
"""
import copy, datetime, json, math, os, random, time
import game_data as GD
import ranks as RT
import booster as BOOSTER
import settings as SET
import event_calendar as CAL

import map_links as H
import galaxy_gates as KAPI

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = GD.load('quests.json')
QUESTS = {int(k): v for k, v in DATA['quests'].items()}
MAX_QUESTS = DATA.get('max_quests', 5)      # the game's limit (the largest maxQuests in the record); in the game the panel setting applies
EX = GD.load('quest_extras.json')       # E6 (tools/gorev_ekleri.py)
QUESTS.update({int(k): v for k, v in EX['quests'].items()})
MAX_EVENT_QUESTS = EX['max_event_quests']
POOLS = {}                                    # ('gunluk' | 'haftalik', difficulty) -> quests
LEVEL_POOLS = {}                              # level (3 | 10 | 15 | 17) -> daily quests (offers one each day)
for _q, _v in sorted(QUESTS.items()):
    if _v.get('pool'):
        if 'level' in _v['pool']:
            LEVEL_POOLS.setdefault(_v['pool']['level'], []).append(_q)
        else:
            POOLS.setdefault((_v['pool']['type'], _v['pool']['difficulty']), []).append(_q)
EVENT_QUEST = 5                               # QuestType: 3 daily, 4 challenge, 5 event, 6 weekly

KILL_NPC, CARGO, COLLECT_BONUS_BOX, COLLECT_LOOT, SELL_ORE, VISIT_MAP, VISIT_QUEST_GIVER, ON_MAP = 6, 51, 55, 67, 52, 34, 62, 77
KILL_PLAYERS = 28            # PvP quests: event "kill_player" (bot players will send it in future)
# Ö1: put an item on the bar (event slot_bar: {(bar, item)}; match [bar, item] or [bar, slot, item]), go to a station object
# (event asset: object type; match [type], 48 hangar ...), upgrade a Skylab module to a level (event skylab: module, level; match
# [module], target level). The client's condition classes: PutItemInSlotBarCondition, VisitMapAssetCondition, UpdateSkylabToLevelCondition
PUT_ITEM_IN_SLOT_BAR, VISIT_MAP_ASSET, UPDATE_SKYLAB_TO_LEVEL = 70, 75, 76
HASTE = 2                    # time limit display (client: HasteCondition, in time format)
REAL_TIME_HASTE = 63         # real-time limit (client: RealTimeHasteCondition; the value is the remaining ms, the client decrements it every second)
AVOID_DAMAGE = 8             # damage limit display (its value is the damage taken; on reaching the limit the quest fails)
# Staying on the map (ENDURANCE, target ms) advances with the per-second position event ('pos', world.ach_tick; recorded time: ms). DAMAGE
# ("all damage is recorded", target-less display) counts the damage taken. VISIT_MAP's COORDINATES sub-condition (match [x*100, y*100,
# radius], client: CoordinatesCondition) completes on entering the radius of that point on the map. The id of the MISCELLANEOUS sub-condition
# (client: GameDefineSystem.InitMiscellaneousConditionTypes) -> (session state, expected value): 3 visible, 4 hidden, 5 in a radiation
# zone, 7 HP below one tenth (the session provides the state: Gorevler.state).
ENDURANCE, DAMAGE, COORDINATES, MISCELLANEOUS = 3, 7, 11, 19
MISC_STATE = {3: ('hidden', False), 4: ('hidden', True), 5: ('radiation', True), 7: ('az_can', True)}
START = '_bas'               # start time in the active quest's values (timed quests and challenges)
PERIOD = '_donem'            # the period in which the daily/weekly quest was accepted
ACCEPT = '_accept'             # the moment a pool quest was accepted (14 days of the weekly GG ore quest)
NOT_ACCEPTABLE, NOT_STARTED, RUNNING, COMPLETED = 0, 1, 2, 3
REQ_LEVEL, REQ_PRE_QUEST, REQ_EXCLUSIVE_POOL = 0, 3, 6      # QuestRequirementType (6: EXCLUSIVE_POOL_QUEST_RUNNING)
MARK_GIVER, MARK_TRADE = 1, 2            # mark id quest_<quest>_<n> (record: 1 on return)
CAMPAIGN_SEC = 30 * 86400                 # starter campaign ("Level N" 502001-502006; ~1 month at a new server launch): the profile's
                                          # 'kampanya' (the moment of opening when chosen in a new save) is visible for this long


def mod(name, **f):
    f['_'] = name
    return f


def conditions(case):
    """Conditions in the tree (those with an id)."""
    for el in case['modifier']:
        c = el['condition']
        if c['id']:
            yield c
        if el['questCase']['id'] or el['questCase']['modifier']:
            yield from conditions(el['questCase'])


def cap(c, v):
    """The condition value is limited by the target; unlimited in a target-less (0) score condition ("kill as many as possible")."""
    return min(v, c['targetValue']) if c['targetValue'] else v


def evaluate(case, values, enabled=True, out=None):
    """Condition states {condition: (active, done)} and whether the state is complete. In a sequential state the ones after the first incomplete item
    are not active and all are required; in an unordered one all are active, mandatoryCount of them is enough. Non-mandatory conditions (time,
    without dying, damage limit, ammo restriction, score display) are never completed and not counted."""
    out = {} if out is None else out
    done, gate = 0, enabled
    for el in case['modifier']:
        c = el['condition']
        if c['id']:
            comp = c['mandatory'] and values.get(str(c['id']), 0) >= c['targetValue']
            out[c['id']] = (gate and not comp, comp)
        else:
            comp = evaluate(el['questCase'], values, gate, out)[1]
        done += comp
        if not comp and case['ordered']:
            gate = False
    need = len(case['modifier']) if case['ordered'] else (case['mandatoryCount'] or len(case['modifier']))
    return out, done >= need


def maps_for(spec, faction):
    """"own X-3" / "enemy X-5" / "any enemy map" / "4-5" / "Epsilon Gate" / "LoW" -> map ids (by the player's company;
    gate: the gate's maps, gates.json)."""
    ids = {v: k for k, v in H.NAMES.items()}
    if spec.endswith(' Gate') and spec.split()[0].lower() in KAPI.KAPI:
        return list(KAPI.KAPI[spec.split()[0].lower()]['maps'])
    import event_gate as EKP
    g = next((g for g in EKP.GATES.values() if g.get('name') == spec), None)       # by event gate name (Quarantine Zone: Epidemi 512263)
    if g:
        return list(g['maps'])
    if spec.endswith(' X-BL'):                           # Blacklight: BL-n is the nth company's (map_links.company)
        facs = {'own': [faction], 'enemy': [f for f in (1, 2, 3) if f != faction], 'any': [1, 2, 3]}[spec.split()[0]]
        names = ['BL-%d' % f for f in facs]
    elif len(spec) == 3 and spec[0] in '1235' and spec[1:] == '-X':     # "1-X": all of the company's maps, "5-X": 5-1..5-4
        names = ['%s-%d' % (spec[0], n) for n in range(1, 9)]
    elif spec == 'own 4-2':                              # the company's PvP map (4-1 MMO, 4-2 EIC, 4-3 VRU; wiki "your 4-2 map")
        names = ['4-%d' % faction]
    elif spec.startswith('own X-'):
        names = ['%d-%s' % (faction, spec[6:])]
    elif spec.startswith('enemy X-'):
        names = ['%d-%s' % (f, spec[8:]) for f in (1, 2, 3) if f != faction]
    elif spec.startswith('any X-'):                     # any company's X-n (official forum 149871: 111006)
        names = ['%d-%s' % (f, spec[6:]) for f in (1, 2, 3)]
    elif spec == 'any enemy map':
        names = ['%d-%d' % (f, n) for f in (1, 2, 3) if f != faction for n in range(1, 9)]
    else:
        names = [spec]
    return [ids[n] for n in names if n in ids]


def period_key(qid, now=None):
    """The day of a daily quest or the week of a weekly quest (local time; the week starts on Monday). GG ore quests with difficulty pools
    are renewed at 06:30 (weekly on Monday 06:30) (official forum 129125)."""
    t = time.time() if now is None else now
    if 'difficulty' in QUESTS[qid]['pool']:
        t -= 6.5 * 3600
    d = datetime.date.fromtimestamp(t)
    return d.isoformat() if QUESTS[qid]['pool']['type'] == 'daily' else '%d-W%02d' % d.isocalendar()[:2]


def offered(now=None):
    """Today's dailies and this week's weeklies: one per difficulty, advancing in order from the choice of the day in the record; from the level
    pools (3, 10, 15, 17) one at random each day (a fixed choice derived from the date and level: the same within the day and after a restart)."""
    t = time.time() if now is None else now
    d = datetime.date.fromtimestamp(t)
    dz = datetime.date.fromtimestamp(t - 6.5 * 3600)    # difficulty pools rotate at 06:30 (same as period_key; otherwise between 00:00-06:30 it could be taken again)
    out = set()
    for kind in ('daily', 'weekly'):
        d0 = datetime.date.fromisoformat(EX[kind]['date'])
        steps = (dz - d0).days if kind == 'daily' else ((dz - d0).days + d0.weekday() - dz.weekday()) // 7
        for first in EX[kind]['selected']:
            pool = POOLS[(kind, QUESTS[first]['pool']['difficulty'])]
            out.add(pool[(pool.index(first) + steps) % len(pool)])
    for level, pool in LEVEL_POOLS.items():
        out.add(random.Random('%s:%d' % (d.isoformat(), level)).choice(pool))
    return out


def event_open(q, now=None):
    """Is the special quest's event open ("event": one of the calendar keys is active); a quest with no event field is always open."""
    return not q.get('event') or any(CAL.is_active(k, now) for k in q['event'])


def repeat_key(qid, now=None):
    """The period of a repeating special quest: "daily" is the day's date; "event" is the start of the event's current period ("force" for an event
    opened by force from the panel or one with no period)."""
    q = QUESTS[qid]
    if q.get('repeat') == 'daily':
        return datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()
    for k in q.get('event', []):
        if k in CAL.EVENTS and CAL.is_active(k, now):
            p = CAL.period(k, now)
            return str(int(p[0])) if p else 'force'
    return 'force'


import quest_tracker as GT         # noqa: E402  (quest_tracker uses this module's conditions/evaluate/mod: after them)


class Quests:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.map_id = None
        self.giver = None          # the quest giver on this map (id, x, y)
        self.trade = None          # the refinery on this map (x, y)
        self.grant = None          # (lootId, count) -> reward messages (session: shop and world)
        self.marks = {}            # quest -> marks shown
        self.send = None           # the timer's messages (the session binds)
        self.state = dict          # current state for the MISCELLANEOUS sub-conditions {hidden, radiation, az_can} (the session binds)
        self.next_tick = 0.0
        self.offer = None          # the daily/weekly quests in the last list (the list is refreshed when they change)

    @property
    def st(self):
        return self.p.d['quests']

    def faction(self):
        return self.p.d['pilot'].get('factionId', 2)

    def resolve(self, matches):
        return [str(m) for x in matches for m in (maps_for(x[1:], self.faction()) if str(x).startswith('@') else [x])]

    # ------------------------------------------------------------ state and list
    def values(self, qid):
        return self.st['active'].get(str(qid), {})

    def visible(self, qid, offer):
        """Is it in the list: daily/weekly only the period's quest (or if in progress), no "Steal ... resources" of its own company, a company-specific
        challenge ("company": 17 / 186 / 187 ...) only to that company's pilot."""
        q = QUESTS[qid]
        if q.get('off') and str(qid) not in self.st['active']:
            return False                                    # a quest turned off in the World Editor (can be finished if in progress)
        if q.get('campaign') and str(qid) not in self.st['active'] and not SET.get('campaign') and time.time() >=self.p.d.get('campaign', -CAMPAIGN_SEC) + CAMPAIGN_SEC:
            return False                                    # starter campaign: the first month if chosen in a new save (can be finished if in progress)
        if q.get('pool') and qid not in offer and str(qid) not in self.st['active']:
            return False
        if str(qid) not in self.st['active'] and ((q.get('event') and not event_open(q))
                                                  or (q.get('hidden') and not all(self.done(x) for x in q['previous']))):
            return False                                    # the event is closed or the elite quest's lock (Silent Sabotage) is not open
        return q.get('company_excluded') != self.faction() and q.get('company', self.faction()) == self.faction()

    def done(self, qid):
        """Is the quest finished: ones taken once are in completed, daily/weekly/repeating special quests in the period for this period."""
        q = QUESTS.get(qid)
        if qid in self.st['done']:
            return True
        key = period_key(qid) if q and q.get('pool') else repeat_key(qid) if q and q.get('repeat') else None
        return key is not None and self.st.get('period', {}).get(str(qid)) == key

    def exclusive_running(self, qid):
        """Is another quest in progress in the difficulty pool (Tetrathrin daily, Kyhalon weekly): only one in the pool can be in progress at a time."""
        h = QUESTS[qid].get('pool') or {}
        return 'difficulty' in h and any(
            int(a) != qid and int(a) in QUESTS and 'difficulty' in (QUESTS[int(a)].get('pool') or {})
            and QUESTS[int(a)]['pool']['type'] == h['type'] for a in self.st['active'])

    def portrait(self, q):
        """The quest giver's portrait; level 3 dailies use the player's company leader ("portrait_company")."""
        return q.get('portrait_company', {}).get(str(self.faction()), q.get('portrait', ''))

    def status(self, qid):
        """-> (state, missing conditions)."""
        q = QUESTS[qid]
        if self.done(qid):
            return COMPLETED, []
        if str(qid) in self.st['active']:
            return RUNNING, []
        miss = []
        if self.p.d['pilot'].get('level', 1) < q['level']:
            miss.append(mod('QuestRequirementModule', requirementType=REQ_LEVEL, minValue=q['level'], maxValue=0, matches=[], missingMatches=[]))
        if self.exclusive_running(qid):
            miss.append(mod('QuestRequirementModule', requirementType=REQ_EXCLUSIVE_POOL, minValue=0, maxValue=0, matches=[], missingMatches=[]))
        pre = [x for x in q['previous'] if x in QUESTS and not self.done(x)]       # an unplayable previous quest is not an obstacle
        if pre:
            miss.append(mod('QuestRequirementModule', requirementType=REQ_PRE_QUEST, minValue=0, maxValue=len(pre), matches=[],
                            missingMatches=[mod('QuestLocalizationModule', questId=x, textKeyFoundation='') for x in pre]))
        return (NOT_ACCEPTABLE if miss else NOT_STARTED), miss

    def slim(self, qid):
        q = QUESTS[qid]
        s, miss = self.status(qid)
        return mod('QuestSlimInfoModule', questId=qid, rootCaseId=q['root']['id'], minLevel=q['level'], priority=q['priority'],
                   types=[mod('QuestTypeModule', type=t) for t in q['kinds']], icon=mod('QuestIconModule', icon=q['icon']),
                   acceptabilityStatus=mod('QuestAcceptabilityStatusModule', type=s), missingAcceptRequirements=miss,
                   textKeyFoundation='', portraitId=self.portrait(q), star=0)

    def running(self, event=False):
        """Quests that hold a slot (active quests that can be played); event: the separate slot of event quests."""
        return sum(1 for q in self.st['active'] if int(q) in QUESTS and (EVENT_QUEST in QUESTS[int(q)]['kinds']) == event)

    def free_slots(self, event=False):
        return max(0, (MAX_EVENT_QUESTS if event else SET.get('max_quests')) - self.running(event))

    def list_cmd(self):
        self.offer = offered()
        return ('QuestListCommand', {'list': [self.slim(q) for q in sorted(QUESTS) if self.visible(q, self.offer)], 'onlyStarter': False,
                                     'maxQuests': self.free_slots(), 'maxEventQuests': self.free_slots(True)})

    def definition(self, qid):
        q = QUESTS[qid]
        root = copy.deepcopy(q['root'])
        vals = self.values(qid)
        flags = evaluate(root, vals)[0]
        for c in conditions(root):
            active, comp = flags[c['id']]
            c['state'].update(currentValue=cap(c, vals.get(str(c['id']), 0)), active=active, completed=comp)
            if c['type'] == HASTE:
                c['state']['currentValue'] = self.elapsed_ms(qid, c['targetValue'])
            elif c['type'] == REAL_TIME_HASTE:                  # remaining time (ms); the client decrements it every second
                c['state']['currentValue'] = c['targetValue'] - self.elapsed_ms(qid, c['targetValue'])
            c['matches'] = self.resolve(c['matches'])
            for s in c['subConditions']:
                s['matches'] = self.resolve(s['matches'])
        return mod('QuestDefinitionModule', id=qid, types=[mod('QuestTypeModule', type=t) for t in q['kinds']], rootCase=root,
                   rewards=[mod('LootModule', lootId=l, amount=n, modifier='') for l, n in q['rewards']],
                   icons=[mod('QuestIconModule', icon=q['icon'])], textKeyFoundation='', portraitId=self.portrait(q), star=0)

    def info(self, qid):
        """Quest info; in a challenge the player's best time (unranked: a single row, first place)."""
        if qid not in QUESTS:
            return []
        best = self.st.get('score', {}).get(str(qid))
        me = {'_': 'QuestChallengeRatingModule', 'name': self.p.d['pilot'].get('userName', '') if best is not None else '',
              'epppLink': '', 'rank': 1 if best is not None else 0, 'rating': best or 0, 'diffToFirst': 0}
        return [('QuestInfoCommand', {'definition': self.definition(qid), 'ratings': [me] if best is not None else [],
                                      'playersRating': me})]

    def login_msgs(self):
        """On login and on map change: active quests, the list and the marks on this map."""
        self.marks = {}
        msgs = [('QuestInitializationCommand', {'quest': self.definition(int(q))}) for q in self.st['active'] if int(q) in QUESTS]
        msgs.append(self.list_cmd())
        for q in self.st['active']:
            if int(q) in QUESTS:
                msgs += self.mark_msgs(int(q))
        return msgs

    # ------------------------------------------------------------ marks
    def mark_msgs(self, qid):
        """Minimap mark for an active "return to the quest giver" / "sell ore" condition (record: the quest giver's position, blinks)."""
        flags = evaluate(QUESTS[qid]['root'], self.values(qid))[0]
        want = set()
        for c in conditions(QUESTS[qid]['root']):
            if flags[c['id']][0]:
                if c['type'] == VISIT_QUEST_GIVER and self.giver:
                    want.add(MARK_GIVER)
                elif c['type'] == SELL_ORE and self.trade:
                    want.add(MARK_TRADE)
        have = self.marks.setdefault(qid, set())
        msgs = []
        for n in sorted(want - have):
            x, y = self.giver[1:] if n == MARK_GIVER else self.trade
            msgs.append(('CreateMinimapMark', dict(count=-1, scale=1.0, uid='quest_%d_%d' % (qid, n), positionX=x, positionY=y, interval=0.5,
                                                   inverse=False, soundModule=mod('SoundTriggerModule', playSound=True, soundId=132), type=0)))
        for n in sorted(have - want):
            msgs.append(('RemoveMinimapMark', {'uid': 'quest_%d_%d' % (qid, n)}))
        self.marks[qid] = want
        return msgs

    # ------------------------------------------------------------ requests
    def accept(self, qid):
        q = QUESTS.get(qid)
        s = self.status(qid)[0] if q else None
        event = bool(q) and EVENT_QUEST in q['kinds']
        if s != NOT_STARTED or not self.free_slots(event) or not self.visible(qid, offered()):
            self.log('   quest could not be accepted: %s (state %s, active %d/%d)' % (qid, s, self.running(event), SET.get('max_quests')))
            return [self.list_cmd()]
        if q.get('pool') and 'difficulty' in q['pool'] and any(
                'difficulty' in (QUESTS.get(int(a), {}).get('pool') or {}) and QUESTS[int(a)]['pool']['type'] == q['pool']['type']
                for a in self.st['active']):
            self.log('   quest could not be accepted: %s (only one %s ore quest at a time)' % (qid, q['pool']['type']))    # forum 129125
            return [self.list_cmd()]
        vals = {START: time.time()} if q.get('sure_sn') or q.get('challenge') else {}
        if q.get('pool'):
            vals[PERIOD] = period_key(qid)
            vals[ACCEPT] = time.time()
        elif q.get('repeat'):
            vals[PERIOD] = repeat_key(qid)
        with self.p.lock:
            self.st['active'][str(qid)] = vals
            self.p.dirty = True
        self.log('   quest accepted: %d %s%s' % (qid, q['name'], ' (%d sn)' % q['sure_sn'] if q.get('sure_sn') else ''))
        msgs = [('QuestInitializationCommand', {'quest': self.definition(qid)}), self.list_cmd()] + self.mark_msgs(qid)
        msgs += self.event('level', value=self.p.d['pilot'].get('level', 1))        # "Level N": the current level
        return msgs + self.event('map', map=self.map_id) if self.map_id is not None else msgs

    def cancel(self, qid):
        if str(qid) not in self.st['active']:
            return []
        with self.p.lock:
            del self.st['active'][str(qid)]
            self.p.dirty = True
        msgs = [('RemoveMinimapMark', {'uid': 'quest_%d_%d' % (qid, n)}) for n in sorted(self.marks.pop(qid, set()))]
        self.log('   quest cancelled: %d' % qid)
        return msgs + [('QuestCancelledCommand', {'id': qid}), self.list_cmd()]

    # ------------------------------------------------------------ progress
    def matches(self, c, kind, kw, map_id=None):
        """Does the event advance this condition -> the amount to add or ('set', value). Common types are in quest_tracker.measure (a single
        measuring point with the Pass quests); here the position ("@own X-3") is resolved by the player's company and types specific to main quests are measured."""
        subs = c['subConditions']
        on_map = [s for s in subs if s['type'] == ON_MAP]
        if on_map and str(kw.get('map', self.map_id)) not in self.resolve(on_map[0]['matches']):
            return 0
        misc = [MISC_STATE.get(int(s['matches'][0]) if s['matches'] else -1) for s in subs if s['type'] == MISCELLANEOUS]
        if misc:
            now = self.state()
            if any(x is None or now.get(x[0], False) != x[1] for x in misc):
                return 0
        m = c['matches']
        if c['type'] == VISIT_MAP:
            coord = next((s['matches'] for s in subs if s['type'] == COORDINATES), None)
            if coord:                                       # reaching a coordinate on the map: per-second position within the radius
                return 1 if (kind == 'pos' and str(kw.get('map')) in self.resolve(m)
                             and math.hypot(kw.get('x', 0) - int(coord[0]), kw.get('y', 0) - int(coord[1])) <= int(coord[2])) else 0
            return 1 if kind == 'map' and str(kw.get('map')) in self.resolve(m) else 0
        if c['type'] == ENDURANCE:
            return int(kw.get('ms', 1000)) if kind == 'pos' else 0      # staying time with the per-second event (not the minute event)
        if c['type'] == DAMAGE:
            return int(kw.get('count', 0)) if kind == 'damage_taken' else 0       # "all damage is recorded": damage taken
        if c['type'] == AVOID_DAMAGE:
            return 0                                        # restriction (broken)
        if c['type'] == VISIT_QUEST_GIVER and kind == 'giver':
            return 1
        if c['type'] == PUT_ITEM_IN_SLOT_BAR and kind == 'slot_bar' and len(m) >= 2:
            items = set(kw.get('items', ()))
            return 1 if (m[0], m[-1]) in items and (len(m) < 3 or (m[0], m[1], m[-1]) in set(kw.get('slots', ()))) else 0
        if c['type'] == VISIT_MAP_ASSET and kind == 'asset':
            return 1 if str(kw.get('type')) in m else 0
        if c['type'] == UPDATE_SKYLAB_TO_LEVEL and kind == 'skylab':
            return c['targetValue'] if m and kw.get('module') == m[0] and kw.get('level', 0) >= c['targetValue'] else 0
        if c['type'] == KILL_PLAYERS and kind == 'kill_player':
            # match [ship count, ships..., company count, companies...] (client: KillPlayersCondition.ParseMatches)
            n = int(m[0]) if m else 0
            ships, rest = m[1:1 + n], m[1 + n:]
            facs = rest[1:1 + int(rest[0])] if rest else []
            if kw.get('faction') == self.faction():
                return 0
            return 1 if (not ships or str(kw.get('ship')) in ships) and (not facs or str(kw.get('faction')) in facs) else 0
        return GT.measure(dict(c, subConditions=[]), kind, kw, self.map_id)

    def event(self, kind, **kw):
        """Game event (quest events: kill, cargo, bonus, loot, sell, map, giver ...; achievement events: damage, distance, gate, level ...)
        -> condition updates, marks, completed quests. A kill by a group member (group) counts, it does not break the restriction."""
        msgs = self.broken(kind, **kw) if kind in ('kill_player', 'kill', 'damage_taken', 'damage_player', 'ammo') and not kw.get('group') else []
        for qs in list(self.st['active']):
            qid = int(qs)
            if qid not in QUESTS or qs not in self.st['active']:
                continue
            upd, done = GT.advance(self.p, QUESTS[qid]['root'], self.st['active'][qs], kind, kw, self.map_id, fn=self.matches)
            if not upd and not done:
                continue
            msgs += upd + self.mark_msgs(qid)
            if done:
                msgs += self.complete(qid)
        return msgs

    # ------------------------------------------------------------ time and restrictions
    def elapsed_ms(self, qid, target):
        vals = self.values(qid)
        if START not in vals:
            return 0
        return int(min(target - 1, max(0, (time.time() - vals[START]) * 1000)))

    def fail(self, qid, why):
        if str(qid) not in self.st['active']:
            return []
        with self.p.lock:
            del self.st['active'][str(qid)]
            self.p.dirty = True
        msgs = [('RemoveMinimapMark', {'uid': 'quest_%d_%d' % (qid, n)}) for n in sorted(self.marks.pop(qid, set()))]
        self.log('   quest failed: %d %s (%s)' % (qid, QUESTS[qid]['name'], why))
        return msgs + [('QuestFailedCommand', {'id': qid}), self.list_cmd()]

    def broken(self, kind, **kw):
        """Was a restriction broken: death, shooting a player of a forbidden company, killing a forbidden alien or the damage limit (damage taken
        accumulates in the AVOID_DAMAGE condition, shown once a second) -> messages for failed quests and the damage display."""
        msgs = []
        for qs in list(self.st['active']):
            q = QUESTS.get(int(qs))
            for f in (q or {}).get('failed', []):
                if f['type'] == 'damage' and kind == 'damage_taken':
                    c = next(c for c in conditions(q['root']) if c['type'] == AVOID_DAMAGE)
                    with self.p.lock:
                        v = self.st['active'][qs][str(c['id'])] = self.st['active'][qs].get(str(c['id']), 0) + int(kw.get('count', 0))
                        self.p.dirty = True
                    hit = v >= f['cap']
                    if not hit and time.time() - GT.LAST_SENT.get(c['id'], 0) >= GT.THROTTLE_SEC:
                        GT.LAST_SENT[c['id']] = time.time()
                        msgs.append(self.cond_update(c['id'], v, True, False))
                else:
                    hit = ((f['type'] == 'death' and kind == 'death')
                           or (f['type'] == 'player_damage' and kind == 'damage_player' and kw.get('count', 0) > 0)       # "Don't damage other players"
                           or (f['type'] == 'player' and kind == 'kill_player' and kw.get('faction') == f['company'])
                           or (f['type'] == 'kills' and kind == 'kill' and kw.get('npc') in f['npc'])
                           or (f['type'] == 'ammunition' and kind == 'ammo' and kw.get('count', 0) > 0
                               and GT.ammo_kind(kw.get('loot', '')) in (('1', '2', '3') if f['ammo_class'] == '0' else (f['ammo_class'],))))
                if hit:
                    msgs += self.fail(int(qs), 'kısıt: %s' % f['type'])
                    break
        return msgs

    def tick(self, now):
        """Timed quests: fail when time runs out; otherwise the time condition's value every 5 s. If a daily/weekly quest's period has
        passed it fails; when the period changes the list is refreshed."""
        if now < self.next_tick:
            return
        self.next_tick = now + 5.0
        msgs = []
        if self.offer is not None and offered(now) != self.offer:
            msgs.append(self.list_cmd())
        for qs in list(self.st['active']):
            q = QUESTS.get(int(qs))
            if q and q.get('event') and not event_open(q, now):
                msgs += self.fail(int(qs), 'etkinlik bitti')
                continue
            if (q and q.get('pool') and 'difficulty' in q['pool'] and q['pool']['type'] != 'daily'
                    and now - self.st['active'][qs].get(ACCEPT, now) > 14 * 86400):
                msgs += self.fail(int(qs), '14 gün geçti')        # forum 129125: an accepted quest does not drop when the period ends; weekly 14 days
                continue
            if not q or not q.get('sure_sn'):
                continue
            start = self.st['active'][qs].get(START, now)
            if now - start >= q['sure_sn']:
                msgs += self.fail(int(qs), 'süre doldu')
                continue
            for c in conditions(q['root']):
                if c['type'] == HASTE:
                    msgs.append(self.cond_update(c['id'], self.elapsed_ms(int(qs), c['targetValue']), True, False))
        if msgs and self.send:
            self.send(msgs)

    @staticmethod
    def cond_update(cid, value, active, completed):
        return ('QuestConditionUpdateCommand', {'questConditionId': cid, 'state': mod(
            'QuestConditionStateModule', currentValue=value, active=active, completed=completed)})

    def complete(self, qid):
        """Quest finished: written to the daily/weekly period, to the challenge's best time (to the best score in a score quest; taken again),
        to completed for the others."""
        q = QUESTS[qid]
        rating = 0
        with self.p.lock:
            vals = self.st['active'].pop(str(qid), {})
            if q.get('pool'):
                self.st.setdefault('period', {})[str(qid)] = vals.get(PERIOD) or period_key(qid)
            elif q.get('repeat'):                    # special quest: finished for this day / this event
                self.st.setdefault('period', {})[str(qid)] = vals.get(PERIOD) or repeat_key(qid)
            elif q.get('challenge'):
                best = self.st.setdefault('score', {})
                if q.get('points'):                    # score quest ("as many as possible"): the score is the number of kills, the best is the most
                    rating = sum(vals.get(str(i), 0) for i in q['points'])
                    best[str(qid)] = max(best.get(str(qid), rating), rating)
                else:
                    rating = max(1, int(time.time() - vals.get(START, time.time())))
                    best[str(qid)] = min(best.get(str(qid), rating), rating)
            elif qid not in self.st['done']:
                self.st['done'].append(qid)
            self.p.dirty = True
        self.p.ach('quest', id=qid)
        if q.get('title'):
            RT.grant_title(self.p, q['title'])       # reward title (Plus Ultra: Transcendent Radiance); selected in the achievements window
        RT.note(self.p, 'quest_success_%d' % qid, quest=qid, done=1)          # logbook
        if qid == 20003:
            self.p.ach('tutorial')                   # achievement: the starter quests (20000-20003) are finished
        msgs = [('QuestCompletedCommand', {'id': qid, 'rating': rating})]
        msgs += [('RemoveMinimapMark', {'uid': 'quest_%d_%d' % (qid, n)}) for n in sorted(self.marks.pop(qid, set()))]
        mult = 1 + BOOSTER.mods(self.p).get('quest_reward', 0)        # QR-01 / NQR-B01: quest rewards x2 (except uridium; Ö6)
        for loot, n in QUESTS[qid]['rewards']:
            n = n if loot == 'currency_uridium' or loot.startswith('resource_premium-days') else int(n * mult)   # Titan FAQ: Premium day does not multiply
            msgs += self.grant(loot, n) if self.grant else []
        self.log('   quest completed: %d %s (%s)' % (qid, QUESTS[qid]['name'], ', '.join('%s x%d' % (l, n) for l, n in QUESTS[qid]['rewards'])))
        return msgs + [self.list_cmd()]
