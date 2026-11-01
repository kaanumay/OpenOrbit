"""Galaxy Trek (Space Search; roadmap Ö3; data data/extra_events.json 'galaxy_trek').

Client (menu item space_search, window 134, UISpaceSearchSystem; quests and rewards UIActivityWindowSystem):
  - When the window opens it downloads the XML unityApi/events/spaceSearch.php: root/planets/<planet planetId resKey/>, root/planetEvents/<event
    eventId resKey degree><reward lootId amount/></event>; event text GetText(resKey) + " (" + GetText(degree) + ")"
    (SS_result_lowEvents_N / SS_result_event_low ...). The reward tab unityApi/events/ssRewards.php: root/rangeBoundPackageEntry
    [special, name]/package/{range from; item lootId amount; title name} (SpaceSearchRewardsDate: Time = from).
  - SpaceSearchRequest {id, action, count}: 0 window -> SpaceSearchInfoCommand {planetIndex, planetPct, quantity, lootId, cost};
    1 explore (count 1/5/10) -> SpaceSearchEventsCommand {rewards [RewardModule], eventIds [EventCommand {eventId, planetId}], planets
    [PlanetCommand {planetId, planetPct, increase}]}; 2 reward tab -> SpaceSearchSectorRewardsCommand {rewards
    [SpaceSearchSectorRewards {unlock, count, range, received}]}; 3 claim reward (count = from; id 0); 4 quests -> SpaceSearchMissionListCommand
    {missions [EventQuestDefinitionModule {module, completed, claimed}]}. UpdateSpaceSearchKeyCommand {quantity} key count.
Rules (official SSS, darkorbitwiki): 40 planets (8 regions); each exploration costs 1 FTL Key (resource_ftl-key); event Simple 50% (+3%), Moderate 30%
(+5%), Difficult 20% (+9%) and the reward package of its type (fixed + sub-package draw); when a planet reaches 100% the next one opens; 13 reward tiers
by number of completed planets (titles at 16 and 36); 10 quests a day (1 fixed login, 9 random) give FTL Keys; when the event ends the
keys are deleted.
In the profile: galaxy_trek {period, planet (1-40), percent, done, claimed [tier], day, quests [id], value {uid: condition
values}, finished [id]}.
"""
import datetime, json, os, random, time
from xml.sax.saxutils import quoteattr

import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('galaxy_trek', {})
EVENT = 'galaxy_trek'
KEY = D.get('key', 'resource_ftl-key')
PLANETS = D.get('planet', 40)
QUEST_BY_ID = {q['definition']['id']: q for q in D.get('quests', [])}


def active(now=None):
    return EVENT in CAL.active(now)


def all_events():
    """[(event id, type record)]."""
    return [(i, e) for e in D.get('events', []) for i in e['ids']]


# ------------------------------------------------------------ web (web.py)
def planets_xml():
    ev = []
    for i, e in all_events():
        rewards = ''.join('<reward lootId=%s amount="%d"/>' % (quoteattr(l), n) for l, n in e['fixed'])
        ev.append('<event eventId="%d" resKey=%s degree=%s>%s</event>' % (i, quoteattr(e['text'] % i), quoteattr(e['grade']), rewards))
    planets = ''.join('<planet planetId="%d" resKey="SS_planet_name_%d"/>' % (i, i) for i in range(1, PLANETS + 1))
    return '<?xml version="1.0" encoding="UTF-8"?><spaceSearch><planets>%s</planets><planetEvents>%s</planetEvents></spaceSearch>' % (
        planets, ''.join(ev))


def rewards_xml():
    out = []
    for t in D.get('steps', []):
        rows = ''.join('<item lootId=%s amount="%d"/>' % (quoteattr(l), n) for l, n in t['items'])
        title = '<title name=%s/>' % quoteattr(t['title']) if t.get('title') else ''
        out.append('<rangeBoundPackageEntry special="0" name="%d"><package><range from="%d"/>%s%s</package></rangeBoundPackageEntry>'
                   % (t['required'], t['required'], rows, title))    # row key: the required planet count (text and claim request)
    return '<?xml version="1.0" encoding="UTF-8"?><ssRewards>%s</ssRewards>' % ''.join(out)


def mod(name, **f):
    f['_'] = name
    return f


class GalaxyTrek:
    REQUESTS = ('SpaceSearchRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.titles = None                        # reward title (the session binds it: to the achievement's title list)
        self.on = None                            # whether the event is running (once a second in tick)
        if shop is not None:
            shop.on_bought.append(self.bought)

    def bought(self, loot, amount):
        """FTL Key pack from the shop: the open window's counter (UISpaceSearch.Quantity) changes only with UpdateSpaceSearchKeyCommand;
        when bought from the window's Shop button (GoShop) the old number stayed (player report 2026-10-28: the 150 pack looked like 50)."""
        if any(g == KEY for g, n in self.m.contents(loot, amount) or []):
            return [self.key_cmd()]
        return []

    @property
    def st(self):
        d = self.p.d.setdefault('galaxy_trek', {})
        for k, v in (('planet', 1), ('percent', 0), ('done', 0), ('claimed', []), ('value', {}), ('finished', []), ('quests', [])):
            d.setdefault(k, v)
        return d

    def keys(self):
        return self.p.resource(KEY)

    # ------------------------------------------------------------ period
    def roll_period(self, now=None):
        """New run: progress resets (low confidence in the source: every run from scratch)."""
        p = CAL.period(EVENT, now)
        period = int(p[0]) if p else 0
        if self.p.d.get('galaxy_trek', {}).get('period') != period:
            with self.p.lock:
                self.p.d['galaxy_trek'] = {'period': period}
                self.p.dirty = True

    def roll_day(self, now=None):
        """The day's quests: 1 fixed (login) + 9 random."""
        day = datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()
        st = self.st
        if st.get('day') == day and st['quests']:
            return
        fixed = [q['definition']['id'] for q in D.get('quests', []) if q.get('fixed')]
        rest = [q['definition']['id'] for q in D.get('quests', []) if not q.get('fixed')]
        pick = fixed + random.sample(rest, max(0, min(len(rest), D.get('daily', 10) - len(fixed))))
        with self.p.lock:
            st.update(day=day, quests=pick, value={}, finished=[])
            self.p.dirty = True

    # ------------------------------------------------------------ komutlar
    def info_cmd(self):
        st = self.st
        return ('SpaceSearchInfoCommand', dict(planetIndex=min(st['planet'], PLANETS), planetPct=int(st['percent']), quantity=self.keys(),
                                               lootId=KEY, cost=D.get('cost', 1)))

    def key_cmd(self):
        return ('UpdateSpaceSearchKeyCommand', {'quantity': self.keys()})

    def sector_cmd(self):
        st = self.st
        return ('SpaceSearchSectorRewardsCommand', {'rewards': [
            mod('SpaceSearchSectorRewards', unlock=st['done'] >= t['required'], count=min(st['done'], t['required']),
                range=t['required'], received=t['uid'] in st['claimed']) for t in D.get('steps', [])]})
        # the client writes "(count/range)" on the row: count is the planets finished, range the target (live: the tier number was mistaken for the target)

    def missions_cmd(self):
        import quest_tracker as GT
        st = self.st
        out = []
        for qid in st['quests']:
            q = QUEST_BY_ID.get(qid)
            if q:
                done = qid in st['finished']
                out.append(mod('EventQuestDefinitionModule', module=GT.with_state(q['definition'], st['value'].get(str(qid), {}), done),
                               completed=done, claimed=done))
        return ('SpaceSearchMissionListCommand', {'missions': out})

    def login_msgs(self):
        if not active():
            return []
        self.roll_period()
        self.roll_day()
        msgs = self.event('login', {})               # the quest list is not sent: the client opens the window when it receives it
        return msgs + [self.key_cmd()]

    def tick(self, now):
        """The run ended: the keys are deleted (the client's text); quests on a new day."""
        self.on = active(now)                     # events come often: event state once a second
        if not self.on:
            st = self.p.d.get('galaxy_trek')
            if st and st.get('period') is not None:
                n = self.keys()
                msgs = []
                if n:
                    self.p.add_resource(KEY, -n)
                    msgs = self.m.resource_msgs(KEY, 0, -n)
                    self.log('   Galaxy Trek ended: %d FTL Key deleted' % n)
                with self.p.lock:
                    self.p.d['galaxy_trek'] = {}
                    self.p.dirty = True
                return msgs
            return []
        day = datetime.date.fromtimestamp(now).isoformat()
        if self.st.get('day') != day:
            self.roll_period(now)
            self.roll_day(now)
        return []

    # ------------------------------------------------------------ requests
    def handle(self, name, f):
        if not active():
            return []
        self.roll_period()
        self.roll_day()
        action = int(f.get('action') or 0)
        if action == 0:
            return [self.info_cmd(), self.key_cmd()]
        if action == 1:
            return self.explore(max(1, min(10, int(f.get('count') or 1))))
        if action == 2:
            return [self.sector_cmd()]
        if action == 3:
            return self.claim(int(f.get('count') or 0))      # client: {action 3, id 0, count = range from}
        if action == 4:
            return [self.missions_cmd()]
        return []

    def explore(self, count):
        st = self.st
        if st['done'] >= PLANETS:
            return [self.info_cmd()]
        count = min(count, self.keys() // max(1, D.get('cost', 1)))
        if count <= 0:
            self.log('   Galaxy Trek: no FTL Key')
            return [self.info_cmd(), self.key_cmd()]
        self.p.add_resource(KEY, -count * D.get('cost', 1))
        events, planets, got = [], [], {}
        kinds = D.get('events', [])
        for _ in range(count):
            if st['done'] >= PLANETS:
                break
            e = random.choices(kinds, [k['chance'] for k in kinds])[0]
            eid = random.choice(e['ids'])
            planet = st['planet']
            events.append(mod('EventCommand', eventId=eid, planetId=planet))
            for l, n in e['fixed']:
                got[l] = got.get(l, 0) + n
            for rows in e['spin']:
                l, n, _ = random.choices(rows, [r[2] for r in rows])[0]
                got[l] = got.get(l, 0) + n
            with self.p.lock:
                st['percent'] = min(100, st['percent'] + e['progress'])
                inc = e['progress']
                if st['percent'] >= 100:
                    st['done'] += 1
                    if st['planet'] < PLANETS:
                        st['planet'] += 1
                    st['percent'] = 0
                self.p.dirty = True
            if planets and planets[-1]['planetId'] == planet:
                planets[-1]['increase'] += inc
                planets[-1]['planetPct'] = 100 if st['planet'] != planet or st['done'] >= PLANETS else st['percent']
            else:
                planets.append(mod('PlanetCommand', planetId=planet, increase=inc,
                                   planetPct=100 if st['planet'] != planet or st['done'] >= PLANETS else st['percent']))
        msgs = self.m.resource_msgs(KEY, self.keys(), -count)
        for l, n in sorted(got.items()):
            msgs += self.m.prize(l, n)
        self.log('   Galaxy Trek: %d explorations, planet %d (%%%d), done %d' % (count, st['planet'], st['percent'], st['done']))
        return [('SpaceSearchEventsCommand', dict(rewards=[mod('RewardModule', lootId=l, amount=n) for l, n in sorted(got.items())],
                                                  eventIds=events, planets=planets)),
                self.info_cmd(), self.key_cmd()] + msgs + self.m.money_msgs()

    def claim(self, tier):
        st = self.st
        t = next((t for t in D.get('steps', []) if t['required'] == tier), None)     # the claim request's count = range from
        if not t or t['uid'] in st['claimed'] or st['done'] < t['required']:
            return [self.sector_cmd()]
        tier = t['uid']
        with self.p.lock:
            st['claimed'].append(tier)
            self.p.dirty = True
        msgs = []
        for l, n in t['items']:
            msgs += self.m.prize(l, n)
        if t.get('title') and self.titles:
            msgs += self.titles(t['title'])
        self.log('   Galaxy Trek reward %d: %s %s' % (tier, t['items'], t.get('title') or ''))
        return [self.sector_cmd()] + msgs + self.m.money_msgs()

    # ------------------------------------------------------------ quests
    def event(self, kind, kw):
        """Game event (the session's achievement/quest events): the day's quests progress; a finished quest's FTL Key is given immediately."""
        if not (self.on if self.on is not None else active()):
            return []
        import quest_tracker as GT
        st = self.st
        msgs = []
        for qid in list(st['quests']):
            q = QUEST_BY_ID.get(qid)
            if not q or qid in st['finished']:
                continue
            vals = st['value'].setdefault(str(qid), {})
            _, done = GT.advance(self.p, q['definition']['rootCase'], vals, kind, kw, map_id=self.p.d['position'].get('mapId'), notify=False)
            if done:
                with self.p.lock:
                    st['finished'].append(qid)
                    self.p.dirty = True
                for r in q['definition']['rewards']:
                    msgs += self.m.prize(r['lootId'], r['amount'])
                self.log('   Galaxy Trek quest finished: %s' % q['name'])
        if msgs:
            msgs.append(self.key_cmd())                 # the list (SpaceSearchMissionListCommand) opens the window: only on request
        return msgs
