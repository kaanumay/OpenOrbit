"""Skylab (roadmap stage 5): collectors, refineries, the Xeno module, energy, upgrades, robots and transport to the ship.

Data: data/skylab.json (tools/skylab.py <- wiki tables + the starting state in the recording). Requests are from the client's code
(UISkylabSystem: SendActionRequest(construction, subaction, transportMode, numbers), SendBuyRobot(robotType 1|2)):
  SkylabActionRequest {subaction}      '' window/refresh; 'upgrade' timed upgrade (credits + Prometium/Endurium/Terbium from storage);
                                       'instantUpgrade' instantly, with uridium only; 'instantFinishUpgrade' finishes the running upgrade with uridium in
                                       proportion to the remaining time; 'abortUpgrade' cancel (the client's warning: what was spent is not
                                       returned); 'setActive' / 'setInactive'; 'startTransport' {transportMode '' normal, 'fast' instant
                                       send, 'instantFinish' finish the one under way; count<Ore>}
     -> SkylabMainViewCommand {listModule, oreList} + SkylabUnifiedReceiptCommand {construction, subaction, transportPrice,
        robotsLeftTimeList, errorId / sucessId: BaseStackCommand (BaseKey 22, 30-53)}
  SkylabViewModuleRequest {moduleName} -> SkylabViewModuleBackCommand (production, upgrade cost, robots, Xeno, storage info)
  SkylabPurchaseRobotRequest {construction, robotType}: 1 = 250 credits (+1%), 2 = 50 uridium (+4%); 12 active per collector,
                                       the excess waits in storage and replaces the one whose time (48 hours) runs out
Rules (wiki and client texts): the level of a collector/refinery/solar/storage cannot exceed the base module; one upgrade at a time; the energy of active
modules cannot exceed what the solar module gives; a module being upgraded does not run and uses no energy. Production is per hour,
with efficiency (robot bonus) and the storage limit; refineries consume inputs from storage (Prometid / Duranium -> Promerium -> Seprom).
Times run while the game is closed too (computed from where it left off on login and every second).
Adaptations: in a timed upgrade the resources spent come from the Skylab storage; the Xeno module provides Xenomit (data/skylab.json _xeno);
instant send / finish uses the transportPrice in the recording (1,250 U). Normal transport is 7.2 s per ore, Premium 3.6 s (wikiwiki).
In the profile: skylab {modules: {type: {level, 'etkin' (active), upgrade: end | None}}, storage: {ore id: amount}, robots: {type: [[type,
end]]}, backup: {type: [type]}, transport: {end_time, cargo} | None, last}.
"""
import json, math, os, time

import inventory as INV
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, 'data', 'skylab.json'), encoding='utf8'))
LEVELS, COSTS, MODULES, ORES = S['levels'], S['costs'], S['modules'], S['ores']
COLLECTORS, REFINERIES, XENO = S['collectors'], S['refineries'], S['xeno']
ROBOTS, TRANSPORT = S['robots'], S['transport']
ORDER = ['DURANIUM_REFINERY', 'BASE_MODULE', 'ENDURIUM_COLLECTOR', 'SOLAR_MODULE', 'XENO_MODULE', 'PROMETID_REFINERY',
         'STORAGE_MODULE', 'TRANSPORT_MODULE', 'SEPROM_REFINERY', 'PROMETIUM_COLLECTOR', 'TERBIUM_COLLECTOR', 'PROMERIUM_REFINERY']
ORE_ORDER = ['1', '2', '3', '11', '12', '4', '13', '14']           # order of the storage list in the recording
COUNT_FIELDS = {'count' + v[0]: k for k, v in ORES.items()}         # SkylabActionRequest.countPrometium ... -> ore id
ALWAYS_ON = ('BASE_MODULE', 'SOLAR_MODULE', 'STORAGE_MODULE')     # the client shows no on/off button for these
UPGRADE_RES = (('1', 33), ('2', 34), ('3', 35))                     # Prometium, Endurium, Terbium yetmezse BaseKey
REFINE_ORDER = ['PROMETID_REFINERY', 'DURANIUM_REFINERY', 'PROMERIUM_REFINERY', 'SEPROM_REFINERY']
CARGO = {k: v[2] for k, v in ORES.items()}                          # Skylab ore -> the ship's OreType
STEP_SEC = 600                                                       # calculation step of offline accumulation


def mod(name, **f):
    f['_'] = name
    return f


def row(level):
    return LEVELS[max(1, min(level, len(LEVELS))) - 1]


def stack(code):
    return mod('BaseStackCommand', type=0, enumBaseKey=code, stringBasekey='', argsList=[])


class Skylab:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                 # shop (money and cargo updates; the session binds it)
        self.send = None              # notification for jobs that finish with time (upgrade, transport) (the session binds it)
        self.quest = None             # quest event (UPDATE_SKYLAB_TO_LEVEL; the session binds it) -> messages
        self.pending_quest = []      # (module, level): the quest event when the profile lock is released (quest_tracker takes that lock too)
        self.next_tick = 0.0

    # ------------------------------------------------------------ state
    @property
    def st(self):
        d = self.p.d.get('skylab')
        if not d:
            d = self.p.d['skylab'] = {
                'modules': {k: {'level': v[0], 'enabled': v[1], 'upgrade': None} for k, v in S['start']['modules'].items()},
                'storage': {k: float(v) for k, v in S['start']['storage'].items()},
                'robots': {}, 'backup': {}, 'transport': None, 'last': time.time()}
            self.p.dirty = True
        return d

    def module(self, key):
        return self.st['modules'].setdefault(key, {'level': 0, 'enabled': False, 'upgrade': None})

    def level(self, key):
        return self.module(key)['level']

    def levels(self):
        """Module -> level (the current state when a quest is accepted; stage 1)."""
        return {k: m['level'] for k, m in self.st['modules'].items()}

    def state(self, key):
        m = self.module(key)
        if m.get('upgrade'):
            return 'UPGRADE'
        return 'ACTIVE' if m['enabled'] and m['level'] > 0 else 'INACTIVE'

    def working(self, key):
        return self.state(key) == 'ACTIVE'

    def energy(self, key, level=None):
        lv = self.level(key) if level is None else level
        return row(lv)['energy'] if lv > 0 and key != 'SOLAR_MODULE' else 0

    def consumption(self):
        return sum(self.energy(k) for k in MODULES if k != 'SOLAR_MODULE' and self.working(k))

    def solar(self):
        return row(self.level('SOLAR_MODULE'))['solar']

    def capacity(self, ore):
        v = row(self.level('STORAGE_MODULE'))['storage'][ORES[ore][1]]
        return v if SET.multiplier('skylab_storage') == 1.0 else min(SET.I32, int(v * SET.multiplier('skylab_storage')))    # panel: storage

    def amount(self, ore):
        return int(self.st['storage'].get(ore, 0))

    def bonus(self, key):
        return sum(ROBOTS[str(t)]['bonus'] for t, _ in self.st['robots'].get(key, []))

    def efficiency(self, key):
        return 100 + self.bonus(key)

    def production(self, key):
        """Hourly production (with efficiency)."""
        lv = self.level(key)
        if lv <= 0:
            return 0
        k = SET.multiplier('skylab_production')                     # panel: Skylab production
        if key in COLLECTORS:
            return int(row(lv)['production']['raw'] * self.efficiency(key) / 100 * k)
        if key in REFINERIES:
            return int(row(lv)['production'][REFINERIES[key][2]] * k)
        if key == 'XENO_MODULE':
            return int(row(lv)['production'][XENO['column']] * k)
        return 0

    # ------------------------------------------------------------ time
    def events(self, after):
        ev = [m['upgrade'] for m in self.st['modules'].values() if m.get('upgrade')]
        ev += [b for rs in self.st['robots'].values() for _, b in rs]
        if self.st.get('transport'):
            ev.append(self.st['transport']['end_time'])
        return [e for e in ev if e > after]

    def advance(self, now=None):
        """Production since the last computation; the events in between (upgrade finish, robot time, transport) in order -> notifications."""
        now = now or time.time()
        st, out = self.st, []
        t = min(st.get('last', now), now)
        with self.p.lock:
            while True:
                ev = self.events(t)
                nxt = min([now, t + STEP_SEC] + [e for e in ev if e <= now])     # a long interval step by step (production/consumption order)
                if nxt > t:
                    self.produce((nxt - t) / 3600.0)
                t = nxt
                out += self.fire(t)
                if t >= now:
                    break
            st['last'] = now
            self.p.dirty = True
        self.notify_quest()
        return out

    def notify_quest(self):
        """Quest event for finished upgrades: outside the lock (when called under the lock threading.Lock waited for itself)."""
        while self.pending_quest:
            key, lv = self.pending_quest.pop(0)
            if self.quest and self.send:                     # quest: "Upgrade the Prometium collector to level 1" (stage 1)
                msgs = self.quest(module=key, level=lv)
                if msgs:
                    self.send(msgs)

    def produce(self, hours):
        dep = self.st['storage']

        def add(ore, n):
            dep[ore] = min(self.capacity(ore), dep.get(ore, 0) + n) if n > 0 else dep.get(ore, 0)
        for key, ore in COLLECTORS.items():
            if self.working(key):
                add(ore, self.production(key) * hours)
        if self.working('XENO_MODULE'):
            add(XENO['ore'], self.production('XENO_MODULE') * hours)
        for key in REFINE_ORDER:
            if not self.working(key):
                continue
            out, inputs, _ = REFINERIES[key]
            n = self.production(key) * hours
            n = min([n, self.capacity(out) - dep.get(out, 0)] + [dep.get(o, 0) / k for o, k in inputs.items()])
            if n <= 0:
                continue
            for o, k in inputs.items():
                dep[o] = max(0.0, dep.get(o, 0) - n * k)
            add(out, n)

    def fire(self, t):
        """Events that fill at time t -> client notifications."""
        st, out = self.st, []
        for key, m in st['modules'].items():
            if m.get('upgrade') and m['upgrade'] <= t:
                out += self.finish_upgrade(key, code=46)
        for key, rs in list(st['robots'].items()):
            alive = [r for r in rs if r[1] > t]
            for _ in range(len(rs) - len(alive)):
                spare = st['backup'].get(key) or []
                if spare:
                    alive.append([spare.pop(0), t + ROBOTS['lifetime_sec']])
            st['robots'][key] = alive
        tr = st.get('transport')
        if tr and tr['end_time'] <= t:
            out += self.deliver(tr['cargo'])
            st['transport'] = None
        return out

    def finish_upgrade(self, key, code):
        m = self.module(key)
        m['level'] += 1
        m['upgrade'] = None
        self.pending_quest.append((key, m['level']))      # quest_notify: when the lock is released
        others = self.consumption() - (self.energy(key) if self.working(key) else 0)
        if key not in ALWAYS_ON and others + self.energy(key) > self.solar():
            m['enabled'] = False                              # not enough energy: it stays off
        self.p.dirty = True
        self.log('   Skylab: %s level %d' % (key, m['level']))
        return [('_receipt', key, '', [], [code])]

    def deliver(self, load):
        """There was a transport: the part that fits the cargo goes to the ship ('_ores', render adds it outside the lock), the rest back to the Skylab storage.
        Can be called while holding the profile lock (only a dict changes)."""
        free, got, back = self.p.cargo_free(), {}, {}
        for ore, n in sorted(load.items(), key=lambda kv: ORE_ORDER.index(kv[0])):
            take = min(int(n), free)
            if take > 0:
                got[CARGO[ore]] = got.get(CARGO[ore], 0) + take
                free -= take
            if n - take > 0:
                back[ore] = n - take
        for ore, n in back.items():
            self.st['storage'][ore] = min(self.capacity(ore), self.st['storage'].get(ore, 0) + n)
        self.log('   Skylab: transport arrived %s%s' % (got, ' (what did not fit returned to storage %s)' % back if back else ''))
        return ([('_ores', got)] if got else []) + [('_receipt', 'TRANSPORT_MODULE', 'startTransport', [], [53])]

    # ------------------------------------------------------------ mesajlar
    def main_view(self):
        mods = []
        for key in ORDER:
            m = self.module(key)
            power = self.consumption() if key == 'SOLAR_MODULE' else (self.energy(key) if self.working(key) else 0)
            mods.append(mod('SkylabMainViewModuleCommand', maxLevel=MODULES[key]['maximum'], state=self.state(key), moduleType=key,
                            efficiency=self.bonus(key) if key in COLLECTORS else 0, currentPower=power,
                            maxPower=self.solar() if key == 'SOLAR_MODULE' else -1, level=m['level']))
        ores = [mod('SkylabStorageOreCommand', current=self.amount(o), oreId=int(o), capacity=self.capacity(o), oreName=ORES[o][0])
                for o in ORE_ORDER]
        return ('SkylabMainViewCommand', {'listModule': mods, 'oreList': ores})

    def robots_left(self, key, now=None):
        now = now or time.time()
        return [mod('SkylabActiveRobotsLeftTimeCommand', uridium=1 if t == 2 else 0, leftTime=max(0, int(b - now)))
                for t, b in self.st['robots'].get(key, [])]

    def robot_price(self, kind):
        """The robot's currency and the price paid (with the panel's service-fee multiplier; this is shown in the window too)."""
        cur, price = ROBOTS[kind]['price']
        return cur, SET.price('service_price', price, 'skylab')

    def productivity(self, key, now=None):
        """The collector's Productivity tab (robots, efficiency, prices)."""
        price = lambda kind: mod('SkylabRobotPriceCommand', priceType=ROBOTS[kind]['price'][0], value=self.robot_price(kind)[1])
        return mod('SkylabModuleProductivityCommand', type1Price=price('1'), efficienty=self.efficiency(key),
                   active=len(self.st['robots'].get(key, [])), robotsLeftTimeList=self.robots_left(key, now), type2Price=price('2'),
                   bonus=self.bonus(key), maxActive=ROBOTS['maximum'], inStorage=len(self.st['backup'].get(key, [])))

    def receipt(self, construction='', subaction='', errors=(), success=()):
        """The client (UISkylabSystem.ShowTips) shows only errorId in the pop-up window; with sucessId the window opened empty.
        Success texts are in errorId too; the %module% / %level% / %date% placeholders go with ArgStackCommand (live test H37).
        The client (SetSkylabActionHandler.Run) opens the window if construction is not empty: with no text construction goes empty (on
        robot purchase, toggling a module that does not close brought up a textless "Ok" window; user 2026-10-24). A ready-made text can be
        given instead of a code (BaseStackCommand)."""
        texts = [c if isinstance(c, dict) else self.stack_args(c, construction) for c in list(errors) + list(success)]
        return ('SkylabUnifiedReceiptCommand', dict(
            construction=construction if texts else '', resultId=0, transportPrice=TRANSPORT['fast_uridium'],
            robotsLeftTimeList=self.robots_left(construction) if construction in COLLECTORS else [], subaction=subaction,
            errorId=texts, sucessId=[]))

    def stack_args(self, code, key):
        import shop as SHP
        st = stack(code)
        if key in MODULES:
            lv = self.level(key)
            args = dict(_module_=SHP.res('skylab_' + key.lower()), _level_=lv + (1 if code in (40, 43) else 0),
                        _date_=time.strftime('%d.%m.%Y'))      # must not contain ':' : the client takes anything with ':' for the 'res' format and skips it
            st['argsList'] = [mod('ArgStackCommand', type=0, value2=None, key=SHP.ARG_KEYS[k], value=str(v)) for k, v in args.items()]
        return st

    def window(self, construction='', subaction='', errors=(), success=()):
        return [self.main_view(), self.receipt(construction, subaction, errors, success)]

    def upgrade_cost(self, key):
        g, lv = MODULES[key]['group'], self.level(key)
        if not g or lv >= MODULES[key]['maximum']:
            return None
        c = COSTS[g][lv]
        f = lambda n: SET.price('service_price', n, 'skylab')  # panel: service fees (credits and uridium; the resources are the same)
        return dict(c, credits=f(c['credits']), uridium=f(c['uridium']))

    def ore_info(self, ore, n, cap=None):
        return mod('SkylabStorageOreCommand', current=int(n), oreId=int(ore), capacity=int(self.capacity(ore) if cap is None else cap),
                   oreName=ORES[ore][0])

    def view(self, key, now=None):
        now = now or time.time()
        if key not in MODULES:
            return None
        m, c = self.module(key), self.upgrade_cost(key)
        left = max(0, int(m['upgrade'] - now)) if m.get('upgrade') else 0
        upgrade = mod('SkylabModuleUpgradeCommand', timeLeft=left, credits=c['credits'] if c else 0, terbium=c['source'] if c else 0,
                      uridiumInstant=self.finish_price(key, now) if left else (c['uridium'] if c else 0),
                      endurium=c['source'] if c else 0, prometium=c['source'] if c else 0, timeNormal=SET.duration(c['duration_sec'], 'skylab') // 60 if c else 0)
        info = mod('SkylabCollectorInfoCommand', production=self.production(key), maxTime=0, leftTime=0)
        prod, xeno, ores = None, mod('SkylabXenoInfoCommand', activeEfficiency=0, activeConsumption=0, inactiveConsumption=0,
                                     activeEnergy=0), []
        if key in COLLECTORS:
            prod = self.productivity(key, now)
            ores = [self.ore_info(COLLECTORS[key], self.production(key))]
        elif key in REFINERIES:
            out, inputs, _ = REFINERIES[key]
            n = self.production(key)
            ores = [self.ore_info(o, -n * k) for o, k in inputs.items()] + [self.ore_info(out, n)]
        elif key == 'XENO_MODULE':
            use = self.production('PROMERIUM_REFINERY') * REFINERIES['PROMERIUM_REFINERY'][1].get(XENO['ore'], 0) \
                if self.working('PROMERIUM_REFINERY') else 0
            xeno = mod('SkylabXenoInfoCommand', activeEfficiency=self.production(key), activeConsumption=use, inactiveConsumption=0,
                       activeEnergy=self.energy(key))
            ores = [self.ore_info(XENO['ore'], self.production(key))]
        elif key == 'STORAGE_MODULE':
            nxt = row(self.level(key) + 1)['storage'] if self.level(key) < MODULES[key]['maximum'] else None
            ores = [self.ore_info(o, (nxt[ORES[o][1]] - self.capacity(o)) if nxt else 0, nxt[ORES[o][1]] if nxt else None)
                    for o in ORE_ORDER]
        elif key == 'TRANSPORT_MODULE':
            tr = self.st.get('transport')
            if tr:
                info = mod('SkylabCollectorInfoCommand', production=int(sum(tr['cargo'].values())), maxTime=self.transport_time(tr['cargo']),
                           leftTime=max(0, int(tr['end_time'] - now)))
                ores = [self.ore_info(o, n) for o, n in sorted(tr['cargo'].items(), key=lambda kv: ORE_ORDER.index(kv[0]))]
        return ('SkylabViewModuleBackCommand', dict(collectorInfo=info, upgrade=upgrade, productivity=prod, xenoInfo=xeno,
                                                    strorageInfo=mod('SkylabStorageInfoCommand', efficiency=self.efficiency(key)
                                                                     if key in COLLECTORS else 0, infoOreList=ores),
                                                    moduleName=key))

    # ------------------------------------------------------------ upgrade
    def finish_price(self, key, now=None):
        """Finishing a running upgrade: the instant upgrade price times the fraction of time remaining (at least 1)."""
        m, now = self.module(key), now or time.time()
        if not m.get('upgrade'):
            return 0
        c = COSTS[MODULES[key]['group']][m['level']]
        u = SET.price('service_price', c['uridium'], 'skylab')
        return max(1 if u else 0, int(math.ceil(u * (m['upgrade'] - now) / max(1, SET.duration(c['duration_sec'], 'skylab')))))

    def check_upgrade(self, key):
        """Can it be upgraded -> error code or None."""
        if key not in MODULES or not MODULES[key]['group'] or self.level(key) >= MODULES[key]['maximum']:
            return 30
        if self.module(key).get('upgrade'):        # several modules can be upgraded at once (player report 2026-10-30); the same module once
            return 42
        if key != 'BASE_MODULE' and self.level(key) + 1 > self.level('BASE_MODULE'):
            return 31
        if key == 'PROMERIUM_REFINERY' and self.level(key) + 1 > self.level('XENO_MODULE'):     # official forum: Xeno module limit
            return self.raw('skylab_message_upgrade_xenomoduleLevel')
        if key != 'SOLAR_MODULE' and self.module(key)['enabled'] and \
                self.consumption() - (self.energy(key) if self.working(key) else 0) + self.energy(key, self.level(key) + 1) > self.solar():
            return 41
        return None

    def upgrade(self, key, now):
        err = self.check_upgrade(key)
        if err:
            return [err], []
        c = self.upgrade_cost(key)
        if INV.count(self.p, 'currency_credits') < c['credits']:
            return [32], []
        for ore, code in UPGRADE_RES:
            if self.amount(ore) < c['source']:
                return [code], []
        INV.spend(self.p, {'currency_credits': c['credits']}, reason='buy_SPECIAL', detail='skylab_' + key.lower())
        with self.p.lock:
            for ore, _ in UPGRADE_RES:
                self.st['storage'][ore] -= c['source']
            m = self.module(key)
            m['upgrade'] = now + SET.duration(c['duration_sec'], 'skylab')       # panel: waiting time
            if m['level'] == 0:
                m['enabled'] = True                          # a newly built module runs when it finishes (if energy suffices)
            self.p.dirty = True
        self.log('   Skylab: %s -> %d upgrade started (%d s, %d C, %d x3 resources)' % (key, m['level'] + 1, c['duration_sec'], c['credits'],
                                                                                        c['source']))
        return [], [40]

    def instant_upgrade(self, key, now):
        err = self.check_upgrade(key)
        if err:
            return [err], []
        c = self.upgrade_cost(key)
        if INV.missing(self.p, {'currency_uridium': c['uridium']}):
            return [44], []
        INV.spend(self.p, {'currency_uridium': c['uridium']}, reason='buy_SPECIAL', detail='skylab_' + key.lower())
        with self.p.lock:
            if self.level(key) == 0:
                self.module(key)['enabled'] = True
            self.finish_upgrade(key, 45)
        self.notify_quest()
        self.log('   Skylab: %s upgraded instantly (%d U)' % (key, c['uridium']))
        return [], [45]

    def instant_finish(self, key, now):
        m = self.module(key)
        if not m.get('upgrade'):
            return [30 if self.level(key) >= MODULES.get(key, {}).get('maximum', 0) else 42], []
        price = self.finish_price(key, now)
        if INV.missing(self.p, {'currency_uridium': price}):
            return [44], []
        INV.spend(self.p, {'currency_uridium': price}, reason='buy_SPECIAL', detail='skylab_' + key.lower())
        with self.p.lock:
            self.finish_upgrade(key, 46)
        self.notify_quest()
        self.log('   Skylab: %s upgrade finished (%d U)' % (key, price))
        return [], [45, 46]

    def abort(self, key):
        m = self.module(key)
        if not m.get('upgrade'):
            return [], []
        with self.p.lock:
            m['upgrade'] = None
            if m['level'] == 0:
                m['enabled'] = False
            self.p.dirty = True
        self.log('   Skylab: %s upgrade cancelled (what was spent is not returned)' % key)
        return [], [43]

    def toggle(self, key, on):
        m = self.module(key)
        if key not in MODULES or key in ALWAYS_ON:
            return [], []
        if on:
            if m['level'] <= 0:
                return [36], []
            if m.get('upgrade'):
                return [42], []
            if not m['enabled'] and self.consumption() + self.energy(key) > self.solar():
                return [39], []
        with self.p.lock:
            m['enabled'] = on
            self.p.dirty = True
        return [], [38 if on else 37]

    # ------------------------------------------------------------ transport
    def transport_time(self, load):
        """Duration of normal transport: unit_sec per ore (Premium premium_unit_sec)."""
        per = TRANSPORT['premium_unit_sec' if self.p.premium else 'unit_sec']
        return SET.duration(int(math.ceil(sum(load.values()) * per)), 'skylab')

    def transport(self, f, now):
        mode, st = f.get('transportMode') or '', self.st
        price = SET.price('service_price', TRANSPORT['fast_uridium'], 'skylab')      # panel
        if mode == 'instantFinish':
            if not st.get('transport'):
                return [22], [], []
            if INV.missing(self.p, {'currency_uridium': price}):
                return [47], [], []
            INV.spend(self.p, {'currency_uridium': price}, reason='buy_SPECIAL', detail='skylab_transport')
            with self.p.lock:
                load, st['transport'] = st['transport']['cargo'], None
                msgs = [x for x in self.deliver(load) if x[0] != '_receipt']
            return [], [53], msgs
        if not self.working('TRANSPORT_MODULE'):
            return [22], [], []
        if st.get('transport'):
            return [48], [], []
        load = {}
        for field, ore in COUNT_FIELDS.items():
            n = min(max(0, int(f.get(field) or 0)), self.amount(ore))
            if n > 0:
                load[ore] = n
        total = sum(load.values())
        if not any(int(f.get(k) or 0) > 0 for k in COUNT_FIELDS):
            return [49], [], []
        if total <= 0:
            return [51], [], []
        if total > self.p.cargo_free():
            return [50], [], []
        if mode == 'fast' and INV.missing(self.p, {'currency_uridium': price}):
            return [47], [], []
        if mode == 'fast':
            INV.spend(self.p, {'currency_uridium': price}, reason='buy_SPECIAL', detail='skylab_transport')
        with self.p.lock:
            for ore, n in load.items():
                st['storage'][ore] -= n
            if mode == 'fast':
                msgs = [x for x in self.deliver(load) if x[0] != '_receipt']
            else:
                st['transport'] = {'end_time': now + self.transport_time(load), 'cargo': load}
                msgs = []
            self.p.dirty = True
        self.log('   Skylab: transport %s %s' % ('instantly' if mode == 'fast' else 'started', load))
        return [], [52, 53] if mode == 'fast' else [52], msgs

    # ------------------------------------------------------------ robots
    def raw(self, key):
        """A client text not among the BaseKeys: raw "XXX" + its translated value (like shop.RES_REPLACEMENT)."""
        import shop as SHP
        return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX', argsList=[
            mod('ArgStackCommand', type=0, value2=None, key=SHP.ARG_KEYS['XXX'], value=SHP.res(key))])

    def robots_bought(self):
        """"Skylab robots bought" (the client's text; not among the BaseKeys: raw "XXX" + its translated value, like shop.RES_REPLACEMENT)."""
        import shop as SHP
        return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX', argsList=[
            mod('ArgStackCommand', type=0, value2=None, key=SHP.ARG_KEYS['XXX'], value=SHP.res('skylab_history_robots_bought'))])

    def productivity_msg(self, key, now):
        f = dict(self.productivity(key, now))
        f.pop('_')
        return ('SkylabModuleProductivityCommand', f)

    def buy_robot(self, f, now):
        """Robot purchase. The reply has no module page (SkylabViewModuleBackCommand): when the client opens the page (ShowSecondPage) it switched the tab
        to Info, and Productivity could not be stayed on (user 2026-10-24). The tab is refreshed with SkylabModuleProductivityCommand
        (RefreshSkyInfoRobotEvent -> UISkylabSystem.WriteProductivity)."""
        key, kind = f.get('construction', ''), str(f.get('robotType') or 1)
        if key not in COLLECTORS or kind not in ('1', '2'):
            return []
        cur, price = self.robot_price(kind)                                       # panel
        loot = 'currency_' + cur
        if INV.missing(self.p, {loot: price}):
            self.log('   Skylab: not enough %s for the robot' % cur)
            self.last_operation = ([32 if cur == 'credits' else 44], [])
            return self.out(key, 'purchase', [32 if cur == 'credits' else 44], [], [], now) + [self.productivity_msg(key, now)]
        INV.spend(self.p, {loot: price}, reason='buy_SPECIAL', detail='skylab_robot')
        with self.p.lock:
            rs = self.st['robots'].setdefault(key, [])
            if len(rs) < ROBOTS['maximum']:
                rs.append([int(kind), now + ROBOTS['lifetime_sec']])
            else:
                self.st['backup'].setdefault(key, []).append(int(kind))
            self.p.dirty = True
        self.log('   Skylab: %s robot (%s) bought, active %d, in storage %d' % (key, cur, len(rs), len(self.st['backup'].get(key, []))))
        self.last_operation = ([], [self.robots_bought()])
        return self.out(key, 'purchase', [], [self.robots_bought()], [loot], now) + [self.productivity_msg(key, now)]

    # ------------------------------------------------------------ requests
    def out(self, key, sub, errors, success, spent, now, extra=()):
        msgs = INV.update_msgs(self.m, self.p, spent) if spent else []
        return msgs + list(extra) + self.window(key, sub, errors, success)

    def action(self, f, now=None):
        now = now or time.time()
        key, sub = f.get('construction') or '', f.get('subaction') or ''
        pending = self.render(self.advance(now))
        before = (INV.count(self.p, 'currency_credits'), INV.count(self.p, 'currency_uridium'))
        extra = []
        if sub == '':
            err, ok = [], []
        elif sub == 'upgrade':
            err, ok = self.upgrade(key, now)
        elif sub == 'instantUpgrade':
            err, ok = self.instant_upgrade(key, now)
        elif sub == 'instantFinishUpgrade':
            err, ok = self.instant_finish(key, now)
        elif sub == 'abortUpgrade':
            err, ok = self.abort(key)
        elif sub in ('setActive', 'setInactive'):
            err, ok = self.toggle(key, sub == 'setActive')
        elif sub == 'startTransport':
            err, ok, extra = self.transport(f, now)
            extra = self.render(extra)
        else:
            self.log('   Skylab: unknown operation %r' % sub)
            err, ok = [], []
        self.last_operation = (err, ok)          # the panel's Skylab page (panel_channel.py): error or success
        if err:
            self.log('   Skylab: %s %s -> error %s' % (sub, key, err))
        after = (INV.count(self.p, 'currency_credits'), INV.count(self.p, 'currency_uridium'))
        spent = ['currency_credits'] if after != before else []
        # the module page (SkylabViewModuleBackCommand) is not sent: the client closes the page on an action request and returns to the main page
        # (UISkylabSystem.SendActionRequest) and reads the page's "upgrading" view from the state at the moment the module was clicked
        # (UISkylab.Module.state); the page sent reopened with the old state, and closing and reopening fixed it (user 2026-10-18)
        return pending + self.out(key, sub, err, ok, spent, now, extra)

    def render(self, items):
        """Output of advance/deliver (outside the profile lock): ('_ores', {OreType: count}) is added to the cargo; ('_receipt', module, sub
        action, errors, successes) -> window messages; the others as they are."""
        out = []
        for it in items:
            if it[0] == '_receipt':
                out += self.window(it[1], it[2], it[3], it[4])
            elif it[0] == '_ores':
                out.append(('AttributeOreCountUpdateCommand', {'oreCountList': self.p.add_ores(it[1])}))
                if self.m:
                    out.append(self.m.ore_pack(sorted(it[1])))
            else:
                out.append(it)
        return out

    def handle(self, name, f):
        now = time.time()
        if name == 'SkylabActionRequest':
            return self.action(f, now)
        if name == 'SkylabViewModuleRequest':
            msgs = self.render(self.advance(now))
            v = self.view(f.get('moduleName', ''), now)
            return msgs + ([v] if v else [])
        if name == 'SkylabPurchaseRobotRequest':
            return self.render(self.advance(now)) + self.buy_robot(f, now)
        return None

    def tick(self, now):
        """Every second: finished upgrades and transports are notified to the client (harmless if the window is not open)."""
        if now < self.next_tick:
            return
        self.next_tick = now + 1.0
        if not any(e <= now for e in self.events(0)):
            return
        msgs = self.render(self.advance(now))
        if msgs and self.send:
            self.send(msgs)
