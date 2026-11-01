"""Dispatch (roadmap stage 5): retriever dispatch (Retriever) and gate dispatch (Gate). Data in data/dispatch.json: retrievers from the
client's code (tools/il2cpp/client_data.py), reward lists, slot prices and rules from the wiki; the amounts are an adaptation.

Flow (the recording has the list request and the "not enough resources" reply; the rest from the client's commands and enums):
  on login                         DispatchSlotInfoCommand {currentMaxSlotCount, availableSlotCount}
  DispatchGetRetrieverListRequest  {statusType}: 0 sendable (retriever definitions), 1 in progress (seconds left; 0 = collectable)
                                   -> DispatchGetRetrieverListCommand + DispatchActiveEventCommand (1 Dispatch Day: Monday, Friday;
                                   2 Galaxy Gate Day: Sunday GG Double Rewards, recording 2026-10-25)
  DispatchSendRetrieverRequest     {dispatchId}: free slot and fee -> DispatchMessageCommand SUCCESS_SEND_RETRIEVER; if there is no money
                                   DispatchLootMessageCommand NO_RESOURCE {loots: the missing items} (the recorded reply); if there is no slot ERROR_NO_SLOT
  DispatchCollectRetrieverRequest  {slotId}: if time is up, random rewards -> DispatchLootMessageCommand COLLECTED
  DispatchInstantCompleteRequest   {slotId}: Prime Coupon (the retriever's instant-finish fee) -> collectable at once
  DispatchBuySlotRequest           next slot (3rd 50,000 U, 4th-5th 100,000 U) -> SUCCESS_ADD_SLOT
  DispatchGetRewardPackageRequest  {dispatchId}: possible rewards (DispatchRewardModule lootId/amount/probability)
  DispatchGetGateListRequest       gates: a gate that is built and at wave 1 can be sent (1 GGEU), in progress, collectable
  DispatchSendGateRequest / DispatchCollectGateRewardRequest: gate dispatch, the gate's completion rewards when done
In the profile: dispatch {slot, sent: {slot: {id, end_time}}, kapilar: {gate: end_time}}.
"""
import json, os, random, time

import inventory as INV
import settings as SET
import galaxy_gates as GALAXY

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'dispatch.json'), encoding='utf8'))
R = D['collectors']
AVAILABLE, IN_PROGRESS, READY = 0, 1, 2                    # StatusType (client)
NO_RESOURCE, COLLECTED = 0, 1                             # DispatchLootMessageCommand.MessageType
(SUCCESS_SEND_RETRIEVER, SUCCESS_SEND_GATE, SUCCESS_ADD_SLOT, ERROR_NO_GATE, ERROR_NO_SLOT, ERROR_NO_RESOURCE, ERROR_NOT_READY,
 ERROR_COLLECT, ERROR_SEND_RETRIEVER, ERROR_SEND_GATE, ERROR_INCOMPLETE_GATE, ERROR_MAX_SLOT) = range(12)   # DispatchMessageCommand
EVENT_NONE, DISPATCH_DAY, GALAXY_GATE_DAY = 0, 1, 2          # DispatchActiveEventCommand.activeEvent (istemci enum'u)


def mod(name, **f):
    f['_'] = name
    return f


def loot(l, n):
    return mod('LootModule', lootId=l, amount=int(n), modifier='')


def dispatch_day(now=None):
    import event_calendar as CAL                       # event_calendar.py: dispatch_day (Monday and Friday)
    return CAL.is_active('dispatch_day', now)


def gate_day(now=None):
    import event_calendar as CAL                       # event_calendar.py: gg_double_reward (Sunday GG Double Rewards)
    return CAL.is_active('gg_double_reward', now)


def event_ranges(code, now=None):
    """Items that ongoing events add to this retriever (or to the 'gate' dispatch): {lootId: [min, max]} (event_rewards)."""
    import event_calendar as CAL
    return {l: rngs[code] for ev, items in D['event_rewards'].items() if CAL.is_active(ev, now)
            for l, rngs in items.items() if code in rngs}


def event_loot(code, now=None):
    return {l: random.randint(*lohi) for l, lohi in event_ranges(code, now).items()}


class Dispatch:
    def __init__(self, profile, gates=None, log=print):
        self.p, self.k, self.log = profile, gates, log
        self.m = None                    # shop (reward and inventory update; binds the session)

    @property
    def st(self):
        d = self.p.d.setdefault('dispatch', {})
        d.setdefault('slot', D['slots']['start'])
        d.setdefault('sent', {})
        d.setdefault('gates', {})
        return d

    def free_slot(self):
        return next((s for s in range(1, self.st['slot'] + 1) if str(s) not in self.st['sent']), None)

    def slot_info(self):
        busy = len(self.st['sent'])
        return ('DispatchSlotInfoCommand', dict(currentMaxSlotCount=self.st['slot'], availableSlotCount=self.st['slot'] - busy))

    def slot_costs(self):
        return ('DispatchSlotCostCommand', {'slotCosts': [mod('DispatchSlotModule', slotId=int(s), costList=[loot(l, n) for l, n in c.items()])
                                                          for s, c in sorted(D['slots']['prices'].items())]})

    def event(self, now=None):
        return ('DispatchActiveEventCommand', {'activeEvent': DISPATCH_DAY if dispatch_day(now) else GALAXY_GATE_DAY if gate_day(now) else EVENT_NONE})

    def login_msgs(self):
        return [self.slot_info()]

    # ------------------------------------------------------------ retrievers
    def retriever_list(self, status, now=None):
        now = now or time.time()
        if status == AVAILABLE:
            lst = [mod('DispatchModule', duration=SET.duration(r['duration_sec'], 'dispatch'), id=int(i), slotId=0) for i, r in sorted(R.items(), key=lambda x: int(x[0]))]
        else:
            lst = [mod('DispatchModule', duration=max(0, int(g['end_time'] - now)), id=g['id'], slotId=int(s))
                   for s, g in sorted(self.st['sent'].items())]
        return [('DispatchGetRetrieverListCommand', dict(statusType=status, retrieverList=lst)), self.event(now)]

    def send(self, f):
        rid = str(f.get('dispatchId'))
        r = R.get(rid)
        if not r:
            return [('DispatchMessageCommand', {'messageType': ERROR_SEND_RETRIEVER})]
        slot = self.free_slot()
        if not slot:
            return [('DispatchMessageCommand', {'messageType': ERROR_NO_SLOT})]
        miss = INV.missing(self.p, r['fee'])
        if miss:
            self.log('   Dispatch: not enough for %s %s' % (r['code'], miss))
            return [('DispatchLootMessageCommand', dict(messageType=NO_RESOURCE, loots=[loot(l, n) for l, n in miss.items()]))]
        removed = INV.spend(self.p, r['fee'], reason='buy_SPECIAL', detail=r['code'])
        with self.p.lock:
            self.st['sent'][str(slot)] = dict(id=int(rid), end_time=time.time() + SET.duration(r['duration_sec'], 'dispatch'))
            self.p.dirty = True
        self.p.ach('dispatch_send', code=r['code'])
        self.log('   Dispatch: %s sent (slot %d, %d s)' % (r['code'], slot, r['duration_sec']))
        # the list is not sent: on every DispatchGetRetrieverListCommand (whatever its state) the client draws the ongoing dispatches from its own
        # cache onto the open tab (DispatchGetRetrieverListUpdateEvent -> CreateUIDispatchProgressItem; only statusType 1 refreshes the
        # cache). The in-progress list was drawn into Available (H34), and the Available list drew the old cache: the latest dispatch was not
        # visible, the tab was not selected (user 2026-10-18). When the IN PROGRESS tab opens the client asks for the list.
        return (INV.update_msgs(self.m, self.p, list(r['fee']), removed)
                + [('DispatchMessageCommand', {'messageType': SUCCESS_SEND_RETRIEVER}), self.slot_info()])

    @staticmethod
    def fixed(r):
        """The series' items on each run: the tier table (fixed_tier; forum 160334) or the old fixed x linear tier."""
        tab = D.get('fixed_tier', {}).get(r['series'])
        if tab:
            return {l: v[r['tier'] - 1] for l, v in tab.items() if v[r['tier'] - 1]}
        f_ = 1 + D['tier_increase'] * (r['tier'] - 1)
        return {l: max(1, int(round(n * f_))) for l, n in D['fixed'][r['series']].items()}

    @staticmethod
    def amount(x, r):
        """A random item's amount at the tier: item x tier table (tier_count), otherwise a single 1 or base x linear tier."""
        tab = D.get('tier_count', {}).get(x)
        if tab and r['tier'] > 1:                  # tier 1 is the base amounts in the real recording (R-01: Mucosum 8, fuel 1,000)
            return tab[r['tier'] - 1]
        return 1 if x in D['single'] else max(1, int(round(D['base_count'][x] * (1 + D['tier_increase'] * (r['tier'] - 1)))))

    def rewards(self, rid, now=None):
        """The rewards of one run (recording: fixed items + 4 different random items): the series' fixed items (Solidus, EXP), reward_count different
        items from the list (rare ones with low weight); the amount grows with the tier, Dispatch Day x1.5; the ongoing event's item is added."""
        r = R[str(rid)]
        f = D['dispatch_day_multiplier'] if dispatch_day(now) else 1
        out = {l: max(1, int(round(n * f))) for l, n in Dispatch.fixed(r).items()}
        pool = [x for x in D['rewards'][r['code']] if x not in out]
        extra = sum(1 for l in out if l not in ('currency_experience', 'resource_collectable_solidus'))   # A-01/02 LCB-10, PLT-2026 …
        for _ in range(min(D['reward_count'] - extra, len(pool))):
            weights = [D['sparse'].get(x, 1.0) for x in pool]
            pick = random.choices(pool, weights)[0]
            pool.remove(pick)
            out[pick] = max(1, int(round(Dispatch.amount(pick, r) * f)))
        out.update(event_loot(r['code'], now))
        return out

    def grant(self, items):
        msgs = []
        for l, n in items.items():
            if self.m:
                msgs += self.m.prize(l, n)               # the panel's reward multipliers
            else:
                self.p.add_resource(l, n)
        return msgs

    def collect(self, f, now=None):
        slot = str(f.get('slotId'))
        g = self.st['sent'].get(slot)
        now = now or time.time()
        if not g:
            return [('DispatchMessageCommand', {'messageType': ERROR_COLLECT})]
        if now < g['end_time']:
            return [('DispatchMessageCommand', {'messageType': ERROR_NOT_READY})]
        items = self.rewards(g['id'], now)
        with self.p.lock:
            del self.st['sent'][slot]
            self.p.dirty = True
        self.p.ach('dispatch_collect', code=R[str(g['id'])]['code'])
        self.p.ach('dispatch', incident='DISPATCH_RETRIEVER')            # achievement: "N Retriever Dispatch"
        self.log('   Dispatch: %s collected %s' % (R[str(g['id'])]['code'], items))
        return (self.grant(items) + [('DispatchLootMessageCommand', dict(messageType=COLLECTED, loots=[loot(l, n) for l, n in items.items()])),
                                     self.slot_info()] + self.retriever_list(IN_PROGRESS)[:1])

    def instant(self, f):
        slot = str(f.get('slotId'))
        g = self.st['sent'].get(slot)
        if not g:
            return [('DispatchMessageCommand', {'messageType': ERROR_COLLECT})]
        cost = R[str(g['id'])]['instant']
        miss = INV.missing(self.p, cost)
        if miss:
            return [('DispatchLootMessageCommand', dict(messageType=NO_RESOURCE, loots=[loot(l, n) for l, n in miss.items()]))]
        INV.spend(self.p, cost)
        with self.p.lock:
            g['end_time'] = time.time()
            self.p.dirty = True
        return INV.update_msgs(self.m, self.p, list(cost)) + self.retriever_list(IN_PROGRESS)[:1]

    def buy_slot(self, f=None):
        nxt = self.st['slot'] + 1
        if nxt > D['slots']['maximum']:
            return [('DispatchMessageCommand', {'messageType': ERROR_MAX_SLOT})]
        cost = D['slots']['prices'].get(str(nxt), {})
        miss = INV.missing(self.p, cost)
        if miss:
            return [('DispatchLootMessageCommand', dict(messageType=NO_RESOURCE, loots=[loot(l, n) for l, n in miss.items()]))]
        INV.spend(self.p, cost, reason='buy_SPECIAL', detail='dispatch_slot')
        with self.p.lock:
            self.st['slot'] = nxt
            self.p.dirty = True
        self.log('   Dispatch: slot %d opened' % nxt)
        return INV.update_msgs(self.m, self.p, list(cost)) + [('DispatchMessageCommand', {'messageType': SUCCESS_ADD_SLOT}), self.slot_info()]

    def reward_package(self, f):
        r = R.get(str(f.get('dispatchId')))
        if not r:
            return []
        fixed = Dispatch.fixed(r)
        pool = [x for x in D['rewards'][r['code']] if x not in fixed]
        total = sum(D['sparse'].get(x, 1.0) for x in pool)
        lst = [mod('DispatchRewardModule', lootId=l, amount=n, chance=100) for l, n in fixed.items()]
        lst += [mod('DispatchRewardModule', lootId=x, amount=Dispatch.amount(x, r),
                    chance=max(1, int(round(100 * D['reward_count'] * D['sparse'].get(x, 1.0) / total)))) for x in pool]
        lst += [mod('DispatchRewardModule', lootId=l, amount=lohi[0], chance=100) for l, lohi in event_ranges(r['code']).items()]
        return [('DispatchGetRewardPackageCommand', dict(name=r['name'], rewards=lst))]

    # ------------------------------------------------------------ gates
    def gate_keys(self):
        return [k for k in GALAXY.GATES if k != 'hades']        # a group gate is not sent (wiki)

    def gate_list(self, now=None):
        now = now or time.time()
        out = []
        for key in self.gate_keys():
            g = GALAXY.GATES[key]
            if key in self.st['gates']:
                left = self.st['gates'][key] - now
                out.append(mod('DispatchGateModule', gateId=g['uid'], status=IN_PROGRESS if left > 0 else READY, timeLeft=max(0, int(left))))
            else:
                # Every gate is in the list; dispatching rejects a gate that is not built or has never been completed (the client's texts
                # dispatch_error-no-gate "Please prepare a Gate manually ...", dispatch_error-incomplete-gate "... complete the Gate manually
                # at least once ..."). Listing only suitable gates left the tab empty (player report 2026-10-28, img3)
                out.append(mod('DispatchGateModule', gateId=g['uid'], status=AVAILABLE,
                               timeLeft=SET.duration(D['gate']['duration_sec'], 'dispatch')))      # the "Time required" column while sendable (live test H35)
        return [('DispatchGetGateListCommand', {'gateList': out})]

    def send_gate(self, f):
        key = GALAXY.BY_ID.get(f.get('gateId'))
        if not key or key not in self.gate_keys() or key in self.st['gates']:
            return [('DispatchMessageCommand', {'messageType': ERROR_NO_GATE})]
        if not self.k.built(key) or self.k.gate(key)['wave'] != 0:          # built and at wave 1 (forum 160334)
            return [('DispatchMessageCommand', {'messageType': ERROR_NO_GATE})]
        if not self.k.gate(key).get('done', 0):                                 # completed manually at least once
            return [('DispatchMessageCommand', {'messageType': ERROR_INCOMPLETE_GATE})]
        cost = {D['gate']['ggeu']: 1}
        miss = INV.missing(self.p, cost)
        if miss:
            return [('DispatchLootMessageCommand', dict(messageType=NO_RESOURCE, loots=[loot(l, n) for l, n in miss.items()]))]
        INV.spend(self.p, cost)
        with self.p.lock:
            self.st['gates'][key] = time.time() + SET.duration(D['gate']['duration_sec'], 'dispatch')
            self.k.gate(key)['ready'] = False
            self.p.dirty = True
        self.log('   Dispatch: gate %s sent' % GALAXY.GATES[key]['name'])
        return INV.update_msgs(self.m, self.p, list(cost)) + [('DispatchMessageCommand', {'messageType': SUCCESS_SEND_GATE})] + self.gate_list()

    def collect_gate(self, f, now=None):
        key = GALAXY.BY_ID.get(f.get('gateId'))
        now = now or time.time()
        if not key or key not in self.st['gates']:
            return [('DispatchMessageCommand', {'messageType': ERROR_COLLECT})]
        if now < self.st['gates'][key]:
            return [('DispatchMessageCommand', {'messageType': ERROR_NOT_READY})]
        with self.p.lock:
            del self.st['gates'][key]
            self.p.dirty = True
        self.p.ach('dispatch', incident='DISPATCH_GATE')                 # achievement: "N Gate Dispatch"
        msgs = self.k.dispatch_complete(key, D['dispatch_day_multiplier'] if dispatch_day(now) else 1)     # Dispatch Day applies to the gate too
        extra = event_loot('gate', now)                              # Chaos Omen / Protegit: Chaos Fragment from gate dispatch
        if extra:
            msgs[-1][1]['loots'] += [loot(l, n) for l, n in extra.items()]       # last message DispatchLootMessageCommand
            msgs = self.grant(extra) + msgs
        return msgs + self.gate_list()

    def handle(self, name, f):
        fn = {'DispatchGetRetrieverListRequest': lambda f: self.retriever_list(f.get('statusType', 0)),
              'DispatchSendRetrieverRequest': self.send, 'DispatchCollectRetrieverRequest': self.collect,
              'DispatchInstantCompleteRequest': self.instant, 'DispatchBuySlotRequest': self.buy_slot,
              'DispatchGetRewardPackageRequest': self.reward_package, 'DispatchGetGateListRequest': lambda f: self.gate_list(),
              'DispatchSendGateRequest': self.send_gate, 'DispatchCollectGateRewardRequest': self.collect_gate}.get(name)
        return fn(f) if fn else None
