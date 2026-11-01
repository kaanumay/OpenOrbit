"""The bots' Skylab: the same tables and rules as the player's (data/skylab.json; the game's skylab.py), abstract and lazy computation.

State bot.k['skylab'] = {'mod': {module: level}, 'storage': {ore: count}, 'last': time, 'build': [module, end] | None, 'transport': time}
  production  collectors make raw ore, the Xeno module makes Xenomit, refineries work in order from the inputs in storage (Prometid/Duranium ->
              Promerium -> Seprom); the storage limit comes from the storage module's level; the energy of running modules cannot exceed
              the solar module's (the excess modules count as off, latest built first)
  upgrade     credits + P/E/T resources from storage, timed (one job at a time); the base module is the ceiling, the Promerium refinery
              cannot exceed the Xeno module
  transport   7.2 s per ore (500 per hour): while the bot sells at a station, as much ore as its accumulated transport allowance comes to
              the ship (valuable first) and is sold or goes to the lab (lab.py)
The upgrade order is the real player's order: collectors, solar if energy is short, storage when it fills, then refineries and Xeno.
"""
import json, os

from . import catalog as K

S = json.load(open(os.path.join(K.HERE, 'data', 'skylab.json'), encoding='utf8'))
ROW = S['levels']
MOD = S['modules']
COSTS = S['costs']
ORES = S['ores']                       # skylab ore -> [name, storage column, cargo ore]
COLLECTORS = S['collectors']              # module -> ore
REFINERIES = S['refineries']               # module -> [product, inputs, column]
REFINE_ORDER = ('PROMETID_REFINERY', 'DURANIUM_REFINERY', 'PROMERIUM_REFINERY', 'SEPROM_REFINERY')
XENO = S['xeno']
TRANSPORT_SEC = S['transport']['unit_sec']
RESOURCES = ('1', '2', '3')                    # upgrade resources: Prometium, Endurium, Terbium (each by the 'resource' amount)
STEP_SEC = 1800.0
ORDER = ('PROMETIUM_COLLECTOR', 'ENDURIUM_COLLECTOR', 'TERBIUM_COLLECTOR', 'PROMETID_REFINERY', 'DURANIUM_REFINERY',
        'XENO_MODULE', 'PROMERIUM_REFINERY', 'SEPROM_REFINERY')


def row(lv):
    return ROW[max(1, min(len(ROW), lv)) - 1]


def state(bot, now):
    st = bot.k.get('skylab')
    if st is None:
        st = bot.k['skylab'] = {'mod': {m: lv for m, (lv, _) in S['start']['modules'].items()},
                                'storage': {o: float(n) for o, n in S['start']['storage'].items()}, 'last': now, 'build': None,
                                'transport': now}
    return st


def level(st, m):
    return st['mod'].get(m, 0)


def energy(m, lv):
    return row(lv)['energy'] if lv > 0 and m != 'SOLAR_MODULE' else 0


def workers(st):
    """Modules with enough energy (solar, base, storage, transport always on; the others in ORDER, once the solar runs out the rest are off)."""
    solar = row(level(st, 'SOLAR_MODULE'))['solar']
    spent = sum(energy(m, level(st, m)) for m in ('BASE_MODULE', 'STORAGE_MODULE'))
    is_open = set()
    for m in ORDER:
        e = energy(m, level(st, m))
        if level(st, m) > 0 and spent + e <= solar:
            is_open.add(m)
            spent += e
    return is_open


def capacity(st, ore):
    return row(level(st, 'STORAGE_MODULE'))['storage'][ORES[ore][1]]


def production(st, m):
    lv = level(st, m)
    if lv <= 0:
        return 0
    if m in COLLECTORS:
        return row(lv)['uretim']['raw']
    if m in REFINERIES:
        return row(lv)['uretim'][REFINERIES[m][2]]
    if m == 'XENO_MODULE':
        return row(lv)['uretim'][XENO['column']]
    return 0


def produce(st, hour, multiplier=1.0):
    dep = st['storage']
    is_open = workers(st)

    def add(ore, n):
        dep[ore] = min(capacity(st, ore), dep.get(ore, 0) + n)
    for m, ore in COLLECTORS.items():
        if m in is_open:
            add(ore, production(st, m) * hour * multiplier)
    if 'XENO_MODULE' in is_open:
        add(XENO['ore'], production(st, 'XENO_MODULE') * hour * multiplier)
    for m in REFINE_ORDER:
        if m not in is_open:
            continue
        output, input_, _ = REFINERIES[m]
        n = min([production(st, m) * hour * multiplier, capacity(st, output) - dep.get(output, 0)] + [dep.get(o, 0) / k for o, k in input_.items()])
        if n <= 0:
            continue
        for o, k in input_.items():
            dep[o] = max(0.0, dep.get(o, 0) - n * k)
        add(output, n)


def advance(bot, now):
    """Production since the last computation and finished upgrades (abstract, step by step) -> state."""
    st = state(bot, now)
    t = max(st['last'], now - 24 * 3600)                 # after a long gap at most one day of production (like the catch-up limit)
    k = bot.game_settings.multiplier('skylab_uretim')
    while t < now:
        end_time = st['build'][1] if st.get('build') else None
        nxt = min(now, t + STEP_SEC, end_time if end_time and end_time > t else now)
        produce(st, (nxt - t) / 3600.0, k)
        t = nxt
        if st.get('build') and st['build'][1] <= t:
            m = st['build'][0]
            st['mod'][m] = level(st, m) + 1
            st['build'] = None
            bot.event('skylab', module=m, level=st['mod'][m])
    st['last'] = now
    return st


# ------------------------------------------------------------------------------------------------------------ upgrade
def cost(st, m):
    g, lv = MOD[m]['group'], level(st, m)
    if not g or lv >= MOD[m]['maximum']:
        return None
    return COSTS[g][lv]


def upgradable(st, m):
    if cost(st, m) is None or st.get('build'):
        return False
    if m != 'BASE_MODULE' and level(st, m) + 1 > level(st, 'BASE_MODULE'):
        return False
    if m == 'PROMERIUM_REFINERY' and level(st, m) + 1 > level(st, 'XENO_MODULE'):
        return False
    return True


def next_up(st):
    """The real player's order: solar if energy is short, storage if it is full; base if it has reached the ceiling; then the lowest-level
    module in ORDER (collectors first)."""
    solar = row(level(st, 'SOLAR_MODULE'))['solar']
    need = sum(energy(m, level(st, m)) for m in st['mod'] if m != 'SOLAR_MODULE')
    if need > solar * 0.9 and upgradable(st, 'SOLAR_MODULE'):
        return 'SOLAR_MODULE'
    if any(st['storage'].get(o, 0) > 0.9 * capacity(st, o) for o in st['storage']) and upgradable(st, 'STORAGE_MODULE'):
        return 'STORAGE_MODULE'
    candidates = [m for m in ORDER if upgradable(st, m)]
    if not candidates:
        return 'BASE_MODULE' if upgradable(st, 'BASE_MODULE') else None
    m = min(candidates, key=lambda m: (level(st, m) + (2 if m in REFINERIES or m == 'XENO_MODULE' else 0), ORDER.index(m)))
    if level(st, m) >= level(st, 'BASE_MODULE') and upgradable(st, 'BASE_MODULE'):
        return 'BASE_MODULE'
    return m


def invest(bot, now):
    """Upgrades the Skylab (permission 'skylab', from level 3; one job): if the next module's credit cost fits the budget (a share of the credits,
    a frugal bot invests more: long-term gain) and its resource fits storage -> the started module or None."""
    if not bot.permission.get('skylab', True) or bot.level < 3:
        return None
    st = advance(bot, now)
    m = next_up(st)
    c = cost(st, m) if m else None
    if not c:
        return None
    credits = c['credits'] * bot.game_settings.multiplier('service_price', 'skylab')
    if bot.k['credits'] < credits * (2.5 - bot.o('frugality') - 0.5 * bot.o('patience')) or any(st['storage'].get(o, 0) < c['source'] for o in RESOURCES):
        return None
    if not bot.pay('C', credits):
        return None
    for o in RESOURCES:
        st['storage'][o] -= c['source']
    st['build'] = [m, now + c['sure_sn']]
    bot.ist('skylab_upgrade')
    return m


# ------------------------------------------------------------------------------------------------------------ transport
VALUE = {'14': 0, '13': 1, '4': 2, '11': 3, '12': 4, '3': 5, '2': 6, '1': 7}       # valuable first: Seprom, Promerium, Xenomit ...


def carry(bot, now, max_count):
    """At a station: as much ore as the allowance since the last transport (3600/7.2 per hour) moves from storage to cargo (valuable first; at most
    max_count units) -> the transported {cargo ore: count}."""
    if not bot.permission.get('skylab', True):
        return {}
    st = advance(bot, now)
    right = min(max_count, (now - st.get('transport', now)) / TRANSPORT_SEC)
    st['transport'] = now
    out = {}
    for ore in sorted(st['storage'], key=lambda o: VALUE.get(o, 9)):
        n = int(min(right, st['storage'][ore]))
        if n <= 0:
            continue
        st['storage'][ore] -= n
        right -= n
        cargo = ORES[ore][2]
        out[cargo] = out.get(cargo, 0) + n
    for t, n in out.items():
        bot.k['cargo'][str(t)] = bot.k['cargo'].get(str(t), 0) + n
    if out:
        bot.ist('skylab_transport', sum(out.values()))
    return out
