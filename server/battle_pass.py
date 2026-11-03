"""Battle Pass and key exchange (roadmap stage 7, E8; data data/tickets.json "battle_pass" <- tools/tickets.py): one pass per
event ('passes': Halloween from the save and from pass_halloween2026.xml on the CDN, Immortal Union from the official pass_valentine2026.xml,
Hitac, Protegit, Mimesis, GoP, Treacherous Domain, Frozen Labyrinth, Galactic Strife, Astral Ascension and Space Cup with the written
pass_offline_*.xml files); key exchange: for Halloween the list in the save, preceded by the event's designs (event_appearances.py);
the other events have their own table (passes[k].key_exchange: the table on the wiki, cost/limit/priority per event).

Messages (the client's code and the save):
  login       BattlePassInfoCommand {filename, statusCommand BattlePassUpdateStatusCommand {questsToCollectReward [quest],
              purchased}, battlePassQuestModuleList [BattlePassQuestModule {acceptabilityStatus 2 in progress / 3 done, questDefinition}]},
              BattlePassKeyExchangeInfoCommand {rewardList, numOfKeys, exchangeType}, BattlePassWindowSettingsModule
  progress    QuestConditionUpdateCommand; when done QuestCompletedCommand and the list to collect (BattlePassUpdateStatusCommand)
  collect     BattlePassCollectRequest: the reward of finished quests (the XML's questReward) and, if the Battle Pass was bought, the keys (bpReward)
  exchange    BattlePassKeyExchangeRequest {exchangeReward}: a key (resource_battle-pass-key) is spent, the reward is given ->
              BattlePassKeyExchangeUpdateCommand {numOfKeys, claimCount, exchangeReward, lootId}; also when the key count changes (save)
  filter      BattlePassSetFilterRequest {battlePassWindowSettingsModule}
The Battle Pass lasts as long as the event (event_calendar.py: an event of type 'BattlePass' that has a pass); so does the key exchange. The Battle Pass is in the shop
(resource_battle-pass 200,000 U): when bought, the keys of the quests collected up to that moment are given too (adaptation). Pass without keys ('keyless':
Plague Mutation 2020, official Turkish forum 154610): the Battle Pass's reward is the target's ticket reward ('ticket_reward', the XML's bpReward); there is
no key exchange.
Save-specific duration (developer note 2026-10-28): when an event with a pass opens, the save's pass starts from day 1 ('start') and lasts the panel's
battle_pass_duration days; during this time the event also counts as open (event_calendar.PASS_RUNS: the quests depend on the event's content), even if its
calendar period ends earlier. Only one pass at a time: while a pass runs it does not change even if another event with a pass opens; a finished pass does not
restart in the same period.
In the profile: battle_pass {period, start, purchased, value, done, to_collect, collected, exchange, filters}.
"""
import json, os, time

import settings as SET
import inventory as INV
import event_appearances as EG
import quest_tracker as GT
import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
B = json.load(open(os.path.join(HERE, 'data', 'tickets.json'), encoding='utf8'))['battle_pass']
PASSES = {k: dict(p, quests={int(q): d for q, d in p['quests'].items()}, rewards={int(q): r for q, r in p['rewards'].items()})
          for k, p in B['passes'].items()}
EXCHANGE = {r['exchangeReward']: r for r in B['key_exchange']}
EVENT_EXCHANGE = {k: {r['exchangeReward']: r for r in EG.exchange_rows(k)} for k in PASSES}      # event -> design rows
PASS_EXCHANGE = {k: {r['exchangeReward']: dict(r) for r in p['key_exchange']} for k, p in PASSES.items() if p.get('key_exchange')}
for _k, _rows in PASS_EXCHANGE.items():
    # designs that are not in the event's own table (event_appearances.json: the sources of other design pages) stay as a special row at the end;
    # this is the only way to get these designs, which are not sold in the shop (event_appearances.ITEMS)
    _have = {x['lootId'] for r in _rows.values() for x in r['listOfloot']}
    _top = max([r['priority'] for r in _rows.values() if r['isSpecial']] or [0])
    for _r in EVENT_EXCHANGE[_k].values():
        if _r['listOfloot'][0]['lootId'] not in _have:
            _top += 1
            _rows[_r['exchangeReward']] = dict(_r, priority=_top)
KEY, PASS_ITEM = 'resource_battle-pass-key', 'resource_battle-pass'
RUNNING, DONE = 2, 3
CLOAK = 'equipment_extra_cpu_cl04k'      # Cloak CPU variants (-m, -xl, -xs): the quests are tied to a single id (-xs)


def mod(name, **f):
    f['_'] = name
    return f


def measure(c, kind, kw, map_id=None):
    """quest_tracker.measure + three mappings specific to Pass quests: "take damage" (type 7, view 9 = TAKE_DAMAGE) counts the damage taken;
    spending ammo (SPEND_ITEM + ammo: use_ammo emits an 'ammo' event) counts like 'spend'; Cloak CPU variants are a single id."""
    if c['type'] == 7 and c.get('displayType') == 9:
        c = dict(c, type=9)
    if c['type'] == 89 and kind == 'ammo':
        kind = 'spend'
    if kind == 'spend' and kw.get('loot', '').startswith(CLOAK):
        kw = dict(kw, loot=CLOAK + '-xs')
    return GT.measure(c, kind, kw, map_id)


def duration():
    return max(1, int(SET.get('battle_pass_duration'))) * 86400


def event_key(now=None):
    """The event that opens the Battle Pass and its period ('halloween-2026') or None."""
    for k in sorted(CAL.active(now)):
        if 'BattlePass' in CAL.EVENTS[k].get('kinds', []) and k in PASSES:
            p = CAL.period(k, now)
            year = time.localtime(p[0]).tm_year if p else time.localtime(now).tm_year
            return '%s-%d' % (k, year)
    return None


class BattlePass:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None
        self.send = None
        self.map_id = None
        self.objective = None         # binds the session: a finished quest counts toward Season Pass's "N Battle Pass quests" condition (87)
        # the key count the client knows: the login bundle (login_msgs) sends it; if it were None, the first event during LoginRequest
        # would send the key update before the login bundle
        self.keys_sent = profile.resource(KEY)

    @property
    def st(self):
        return self.p.d.setdefault('battle_pass', {})

    def active(self, now=None):
        return event_key(now) is not None

    @property
    def bp(self):
        """The period's pass (after ensure)."""
        return PASSES[self.st['period'].rsplit('-', 1)[0]]

    def end(self):
        return self.st.get('start', 0) + duration()

    def kept(self, ev, now):
        """Whether the running pass keeps running: the pass of an event closed in the panel stops; a pass started outside its event's
        calendar period (opened by hand, --event, all) runs only while the event stays forced open or its calendar period comes."""
        if SET.event_state(ev) == 'off':
            return False
        return CAL.period(ev, self.st['start']) is not None or CAL.forced(ev) or CAL.period(ev, now) is not None

    def ensure(self, now=None):
        """The save's running pass (period name) or None: a running pass keeps running (and keeps its event open); otherwise the pass of an open event with a pass
        starts from day 1 (a finished pass of the same period does not restart)."""
        now = time.time() if now is None else now
        st = self.st
        ev = st.get('period', '').rsplit('-', 1)[0]
        if st.get('period') and not st.get('start'):                    # old save with no end: if its event is running, the pass starts from today
            with self.p.lock:
                st['start'] = now if event_key(now) == st['period'] else 1
                self.p.dirty = True
        if st.get('period') and now < self.end() and self.kept(ev, now):
            CAL.PASS_RUNS[ev] = (st['start'], self.end())
            return st['period']
        CAL.PASS_RUNS.pop(ev, None)
        extra = event_key(now)
        if not extra or extra == st.get('period'):
            return None
        with self.p.lock:
            st.clear()
            st.update(period=extra, start=now, purchased=False, value={}, done=[], to_collect=[], collected=[], exchange={},
                      filters=B['settings'].get('battlePassItemFilters', []))
            self.p.dirty = True
        if self.p.resource(PASS_ITEM) > 0:                       # a Battle Pass bought earlier applies to this period
            self.p.add_resource(PASS_ITEM, -1)
            st['purchased'] = True
        CAL.PASS_RUNS[extra.rsplit('-', 1)[0]] = (now, self.end())
        self.log('   Battle Pass started: %s (%d days)' % (extra, duration() // 86400))
        return extra

    # ------------------------------------------------------------ messages
    def status_cmd(self):
        st = self.st
        return mod('BattlePassUpdateStatusCommand', questsToCollectReward=list(st.get('to_collect', [])), purchased=bool(st.get('purchased')))

    def info_cmd(self):
        st, bp = self.st, self.bp
        rows = [mod('BattlePassQuestModule', acceptabilityStatus=mod('QuestAcceptabilityStatusModule', type=DONE if q in st['done'] else RUNNING),
                    questDefinition=GT.with_state(d, st['value'].get(str(q), {}), q in st['done'])) for q, d in bp['quests'].items()]
        return ('BattlePassInfoCommand', dict(filename=bp['file'], statusCommand=self.status_cmd(), battlePassQuestModuleList=rows))

    def exchanges(self):
        """The period's key exchange (after ensure): the event's own table; if none (Halloween) its designs, then the list in the save."""
        k = self.st['period'].rsplit('-', 1)[0]
        if self.bp.get('keyless'):
            return {}
        return dict(PASS_EXCHANGE[k]) if k in PASS_EXCHANGE else dict(EVENT_EXCHANGE.get(k, {}), **EXCHANGE)

    def exchange_cmd(self):
        rows = [dict(r, claimCount=self.st.get('exchange', {}).get(k, 0)) for k, r in self.exchanges().items()]
        return ('BattlePassKeyExchangeInfoCommand', dict(rewardList=rows, numOfKeys=self.p.resource(KEY), exchangeType=0))

    def key_update(self, reward='', count=0):
        self.keys_sent = self.p.resource(KEY)
        return ('BattlePassKeyExchangeUpdateCommand', dict(spcId=0, numOfKeys=self.keys_sent, claimCount=count, exchangeReward=reward,
                                                           lootId=KEY))

    def login_msgs(self):
        """Battle Pass windows while the event lasts; otherwise none (the client does not show the Battle Pass button)."""
        if not self.ensure():
            return []
        self.keys_sent = self.p.resource(KEY)
        return [self.info_cmd(), self.exchange_cmd(), ('BattlePassWindowSettingsModule', {'battlePassItemFilters': list(self.st['filters'])})]

    # ------------------------------------------------------------ quests
    def event(self, kind, **kw):
        if not self.p.d.get('battle_pass') or not self.ensure():     # if the event changed, the new period's pass
            return []
        st, msgs, done = self.st, [], []
        for q, d in self.bp['quests'].items():
            if q in st['done']:
                continue
            m, fin = GT.advance(self.p, d['rootCase'], st['value'].setdefault(str(q), {}), kind, kw, self.map_id, fn=measure)
            msgs += m
            if fin:
                done.append(q)
        for q in done:
            with self.p.lock:
                st['done'].append(q)
                st['to_collect'].append(q)
                self.p.dirty = True
            msgs.append(('QuestCompletedCommand', {'id': q, 'rating': 0}))
            self.p.ach('quest', id=q)
            self.log('   Battle Pass quest done: %d' % q)
        if done:
            msgs.append(('BattlePassInfoCommand', self.info_cmd()[1]))
            for q in done:                                            # "finish N Battle Pass quests" (Battle Pass and Season Pass)
                msgs += self.event('objective') if kind != 'objective' else []
                if self.objective:
                    self.objective()
        if kind == 'objective':
            return msgs
        if self.p.resource(KEY) != self.keys_sent:
            msgs.append(self.key_update())
        if msgs and self.send:
            self.send(msgs)
        return msgs

    # ------------------------------------------------------------ requests
    def keys_for(self, q):
        return self.bp['rewards'].get(q, {}).get('key', 0)

    def ticket_rewards(self, qs):
        """Ticket rewards (keyless pass): if the Battle Pass was bought, those of the collected targets."""
        msgs = []
        for q in qs:
            for loot, n in self.bp['rewards'].get(q, {}).get('ticket_reward', []):
                msgs += self.m.reward(loot, n) if self.m else []
        return msgs

    def collect(self, f=None):
        st = self.st
        if not self.ensure() or not st['to_collect']:
            return [('BattlePassInfoCommand', self.info_cmd()[1])] if self.p.d.get('battle_pass') else []
        msgs, keys = [], 0
        for q in list(st['to_collect']):
            for loot, n in self.bp['rewards'].get(q, {}).get('reward', []):
                msgs += self.m.reward(loot, n) if self.m else []
            if st.get('purchased'):
                keys += self.keys_for(q)
                msgs += self.ticket_rewards([q])
        with self.p.lock:
            st['collected'] += st['to_collect']
            st['to_collect'] = []
            self.p.dirty = True
        if keys:
            self.p.add_resource(KEY, keys)
        self.log('   Battle Pass rewards collected%s' % (' (+%d keys)' % keys if keys else ''))
        return msgs + [self.info_cmd(), self.key_update()]

    def grant_pass(self, n=1):
        """Battle Pass from the shop: for this period; the keys of the collected quests are given."""
        if not self.ensure():
            self.p.add_resource(PASS_ITEM, n)                        # if bought while there is no event, it goes to the next Battle Pass
            return []
        st = self.st
        if st.get('purchased'):
            self.p.add_resource(PASS_ITEM, n)
            return []
        keys = sum(self.keys_for(q) for q in st['collected'])
        with self.p.lock:
            st['purchased'] = True
            self.p.dirty = True
        if n > 1:
            self.p.add_resource(PASS_ITEM, n - 1)                    # the remaining passes are in storage (for the next Battle Pass)
        if keys:
            self.p.add_resource(KEY, keys)
        msgs = self.ticket_rewards(st['collected'])                  # forum 154610: the ticket rewards of earlier targets too
        self.log('   Battle Pass bought (+%d keys)' % keys)
        return msgs + [self.info_cmd(), self.key_update()]

    def exchange(self, f):
        name = f.get('exchangeReward') or ''
        st = self.st
        r = self.exchanges().get(name) if self.ensure() else None
        if not r:
            return []
        count = st['exchange'].get(name, 0)
        if count >= r['limit'] or INV.spend(self.p, {KEY: r['cost']}, reason='buy_SPECIAL', detail='battle_pass_' + name) is None:
            self.log('   no key exchange: %s (%d/%d, %d keys)' % (name, count, r['limit'], self.p.resource(KEY)))
            return [self.key_update(name, count)]
        with self.p.lock:
            st['exchange'][name] = count + 1
            self.p.dirty = True
        msgs = []
        for x in r['listOfloot']:
            msgs += self.m.reward(x['lootId'], x['amount']) if self.m else []
        self.log('   key exchange: %s (%d keys)' % (name, r['cost']))
        return msgs + [self.key_update(name, count + 1)]

    def set_filter(self, f):
        mods = (f.get('battlePassWindowSettingsModule') or {}).get('battlePassItemFilters')
        if mods is not None and self.p.d.get('battle_pass'):
            with self.p.lock:
                self.st['filters'] = list(mods)
                self.p.dirty = True
        return []

    def handle(self, name, f):
        fn = {'BattlePassCollectRequest': self.collect, 'BattlePassKeyExchangeRequest': self.exchange,
              'BattlePassSetFilterRequest': self.set_filter}.get(name)
        return fn(f) if fn else None
