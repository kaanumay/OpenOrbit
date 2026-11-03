"""Clan Battle Stations (CBS, "ksi") of bot clans (user request 2026-10-31): with bots present there is no fake rival (cbs.with_bots), asteroids are
opened empty; the leaders of bot clans (and officers with the right to build) really compete. The fastest-growing clan takes the best spot.

  target     the most valuable empty asteroid (4-x, X-BL, X-5..7, X-3/4; the map of its own company first), someone else if the leading rival is far ahead
  module     bought from the treasury, with the CBS share of the budget (clan_management.spendable); prices in cbs.json bot_clan (adaptation: in the game
             modules are produced with Assembly). The team follows the leader's style: aggressive laser/rocket, ambitious and peaceful booster, cautious
             repair module
  race       one module per asteroid every 50 s (cbs.json install_sec); progress a['race'] (the "leading clan" in the window). The first to reach 10/10
             builds (cbs.bot_build); if a player builds first or another clan wins, the modules go back to stock
  growth     modules of a built station rise level by level (0-15), a destroyed satellite is repaired as the budget allows: every station is different
  defense    when a player attacks, the leader sends online members to the station (clan_orders 'git'), announcement and mass mail, grudge against the attacker
The clan's record holds k['ksi'] = {target, plan, stock: [module], last_*}; the asteroid's record is in the shared profile (cbs.shared)."""
import random, time

import cbs as CB
import map_links as H
import clan as KL
from . import clan_management as CMG

DEFAULTS = {'price': {}, 'level_multiplier': 0.35, 'repair_ratio': 0.4, 'upgrade_sec': 3600, 'build_min': [5, 30],
              'defense_sec': 1800}                     # actual values in cbs.json bot_klan
WEAPONS = ('module_ltm-lr', 'module_ltm-mr', 'module_ltm-hr', 'module_ram-la', 'module_ram-ma')
BOOSTER = ('module_honm-1', 'module_xpm-1', 'module_dmgm-1')


def setting():
    return dict(DEFAULTS, **(CB.D.get('bot_clan') or {}))


def is_open():
    return CB.with_bots()


def price(loot, level=0):
    a = setting()
    f = a['price'].get(loot, 1000000)
    return int(f if level <= 0 else f * a['level_multiplier'] * level)


def _registry():
    """(shared profile, asteroids) or (None, None): the shared record must have been built in a session (cbs.Cbs.asts: embed)."""
    h = CB.shared()
    d = (h.d.get('cbs') or {}) if h is not None else {}
    return (h, d['asteroids']) if h is not None and d.get('shared') and 'asteroids' in d else (None, None)


def cbs(k):
    with KL.LOCK:
        s = k.setdefault('cbs', {})
        s.setdefault('stock', [])
        return s


def stations(k):
    """Names of the clan's built stations."""
    h, asteroids = _registry()
    return [CB.ASTEROIDS[int(aid)]['name'] for aid, a in (asteroids or {}).items()
            if a.get('state') == 'built' and a.get('clan') == k['id'] and int(aid) in CB.ASTEROIDS]


def _mine(asteroids, k):
    return {int(aid): a for aid, a in asteroids.items() if a.get('clan') == k['id'] and a.get('state') in ('building', 'built')}


def need(k):
    """Remaining cost of the next CBS target: the price of the missing modules if there is no station, otherwise the next upgrade."""
    s = k.get('cbs') or {}
    h, asteroids = _registry()
    if asteroids is None:
        return 0
    own = _mine(asteroids, k)
    if not own:
        owner = [m['loot'] for m in s.get('stock', [])]
        race = (asteroids.get(str(s.get('target'))) or {}).get('race', {}).get(str(k['id']), {}).get('modules', [])
        owner += [m['loot'] for m in race]
        missing = list(s.get('plan') or [])
        for l in owner:
            if l in missing:
                missing.remove(l)
        return sum(price(l) for l in missing)
    y = _to_upgrade(next(iter(own.values())), None)
    return price(y['loot'], y['level'] + 1) if y else 0


def summary(k):
    """The agent's observation: the clan's stations (modules and their levels), the race, the stock, the next cost and empty asteroids."""
    if not is_open():
        return ''
    h, asteroids = _registry()
    if asteroids is None:
        return ''
    row = []
    for aid, a in _mine(asteroids, k).items():
        mods = [y.get('module') for y in a['slots'].values() if y.get('module')]
        row.append('Your battle station %s (%s): %s, deflector %s, modules %s.' % (
            CB.ASTEROIDS[aid]['name'], H.name(CB.ASTEROIDS[aid]['map']), 'building' if a['state'] == 'building' else 'built',
            'on' if (a.get('deflector') or {}).get('on') else 'off',
            ', '.join('%s L%d%s' % (CB.MODS[m['loot']]['code'], m['level'] + 1, ' destroyed' if m['hp'] <= 0 else '') for m in mods)))
    s = k.get('cbs') or {}
    if s.get('target'):
        a = asteroids.get(str(s['target'])) or {}
        ours = len(((a.get('race') or {}).get(str(k['id'])) or {}).get('modules') or ())
        en = CB.race_leader(a)
        row.append('Building race at %s: you have %d/10 modules%s.' % (CB.ASTEROIDS[int(s['target'])]['name'], ours,
                                                                       ', leader %s %d/10' % (en[0], en[1] * 10) if en and en[0] != k['name'] else ''))
    if s.get('stock'):
        row.append('Modules in clan stock: %s.' % ', '.join(sorted(CB.MODS[m['loot']]['code'] for m in s['stock'])))
    row.append('Next station cost: about %s credits (the station share of the budget pays it).' % '{:,}'.format(need(k)))
    empty = sorted(((value(aid, k), aid) for aid in CB.ASTEROIDS if (asteroids.get(str(aid)) or {}).get('state', 'vacant') == 'vacant'), reverse=True)[:6]
    if empty:
        row.append('Free asteroids (best first; clan_station to target one): %s.' % ', '.join(
            '%s (%s)' % (CB.ASTEROIDS[aid]['name'], H.name(CB.ASTEROIDS[aid]['map'])) for _, aid in empty))
    return '\n'.join(row)


def set_target(k, name, b):
    """The asteroid the agent chose (by name): if empty it becomes the target; modules of the previous target go back to stock."""
    h, asteroids = _registry()
    aid = next((i for i, a in CB.ASTEROIDS.items() if a['name'].lower() == str(name or '').strip().lower()), None)
    if asteroids is None or aid is None or (asteroids.get(str(aid)) or {}).get('state', 'vacant') != 'vacant':
        return False
    s = cbs(k)
    old = s.get('target')
    if old and old != aid:
        a = asteroids.get(str(old)) or {}
        with h.lock:
            r = (a.get('race') or {}).pop(str(k['id']), None)
            a['version'] = a.get('version', 0) + 1
        if r:
            CB.refund_race(k['id'], r.get('modules'))
    s['target'] = aid
    s['plan'] = s.get('plan') or build_plan(b)
    return True


# ------------------------------------------------------------------------------------------------------------ decision
def value(aid, k):
    """The asteroid's value to the clan: 4-x is the most valuable (PvP zone, open to every company), then X-BL, X-5..7, X-3/4; the map of its own
    company first, the enemy company's last."""
    m = int(CB.ASTEROIDS[aid]['map'])
    name = H.name(m)
    on, _, last = name.partition('-')
    v = 3.0 if on == '4' else 2.5 if last.upper() == 'BL' else 2.0 if last in ('5', '6', '7') else 1.2
    owner = H.company(m)
    company = int(k.get('company') or 0) or int((k['members'].get(k['leader']) or {}).get('company') or 0)
    return v + (0.5 if owner and owner == company else -0.6 if owner else 0)


def build_plan(b):
    """The team (center + 8 satellites) in the leader's style: aggressive laser/rocket, ambitious and peaceful booster, cautious repair."""
    aggression = b.o('aggression')
    satellite = []
    if b.r.random() < 0.35 + 0.45 * (1 - b.o('risk')):
        satellite.append('module_repm-1')
    for x in BOOSTER:
        if b.r.random() < 0.12 + 0.55 * b.o('ambition') * (1 - aggression):
            satellite.append(x)
    weight = (2 + 3 * aggression, 2 + aggression, 1 + aggression, 1 + 2 * (1 - b.o('risk')), 1.5)
    while len(satellite) < CB.SLOTS - 2:
        satellite.append(b.r.choices(WEAPONS, weight)[0])
    b.r.shuffle(satellite)
    return ['module_hulm-1', 'module_defm-1'] + satellite


def _new_module(loot):
    hp = CB.level_value(CB.MODS[loot]['hp'], 0)
    return {'loot': loot, 'level': 0, 'hp': hp, 'shield': int(hp * CB.D['shield_ratio'])}


def pick_target(k, asteroids, now):
    """New target: the most valuable empty asteroid if the clan's station limit is not reached; if the leading rival is past 6/10 and we have none,
    that asteroid is skipped (we cannot catch up)."""
    s = cbs(k)
    limit = 1 + (len(k['members']) >= 20 and k['treasury'] > 40000000)
    if len(_mine(asteroids, k)) >= limit:
        return None
    candidate = []
    for aid in CB.ASTEROIDS:
        a = asteroids.get(str(aid)) or {}
        if a.get('state', 'vacant') != 'vacant':
            continue
        ours = len(((a.get('race') or {}).get(str(k['id'])) or {}).get('modules') or ())
        en = max([len(r.get('modules') or ()) for c, r in (a.get('race') or {}).items() if int(c) != k['id']] + [0])
        player = len(a.get('slots') or {})
        if max(en, player) >= 6 and ours < max(en, player):
            continue
        candidate.append((value(aid, k) - 0.12 * max(en, player) + random.uniform(0, 0.4), aid))
    if not candidate:
        return None
    s['target'] = max(candidate)[1]
    return s['target']


def _to_upgrade(a, b):
    """The module to upgrade at a built station (lowest level; an aggressive leader weapons first, a cautious one the center)."""
    candidates = []
    for s, y in a.get('slots', {}).items():
        m = y.get('module')
        if not m or m['hp'] <= 0 or m['level'] >= 15:
            continue
        md = CB.MODS[m['loot']]
        on = 0.0
        if b is not None:
            on = (0.6 * b.o('aggression') if md.get('weapon') else 0) + (0.6 * (1 - b.o('risk')) if md['center'] else 0)
        candidates.append((m['level'] - on, int(s), m))
    return min(candidates, key=lambda x: x[:2])[2] if candidates else None


def _pay(k, area, cost):
    if cost <= 0 or CMG.spendable(k, area) < cost:
        return False
    with KL.LOCK:
        k['treasury'] -= cost
        k['treasury_log'].insert(0, {'balanceUserId': 0, 'credits': -cost, 'insertDate': KL.stamp(), 'toName': '', 'fromName': '',
                                   'moneyType': 'cbs', 'reason': 'battle station'})
        del k['treasury_log'][200:]
    KL.changed(k)                                        # the treasury is in the members' window and in clans.json
    return True


def to_stock(k, d):
    """A destroyed station's or removed modules' (pending '@klan:<id>') transfer to the clan's stock."""
    pending = (d.get('pending') or {}).pop('@klan:%d' % k['id'], None)
    if pending:
        cbs(k)['stock'].extend(pending.values())


def race_step(y, b, k, h, asteroids, now):
    """One step at the target asteroid: fits the next module in stock if there is one (every 50 s), otherwise buys as the budget allows; builds at 10/10."""
    s = cbs(k)
    aid = s.get('target')
    if aid and str(aid) not in asteroids:
        with h.lock:
            asteroids.setdefault(str(aid), {'state': 'vacant', 'slots': {}})
    a = asteroids.get(str(aid)) if aid else None
    if a is None or a.get('state', 'vacant') != 'vacant':
        if a is not None and a.get('clan') == k['id']:
            return                                       # we won: being built or built
        if aid:
            b.event('cbs_lost', now, station=CB.ASTEROIDS[int(aid)]['name'])
        s['target'] = None
        aid = pick_target(k, asteroids, now)
        if aid is None:
            return
        with h.lock:
            a = asteroids.setdefault(str(aid), {'state': 'vacant', 'slots': {}})
        s['plan'] = build_plan(b)
        CMG.announce(b, CMG.kl_of(b), 'clan_announce_cbs_race', station=CB.ASTEROIDS[aid]['name'], map=H.name(CB.ASTEROIDS[aid]['map']))
        b.event('cbs_target', now, station=CB.ASTEROIDS[aid]['name'])
    r = (a.get('race') or {}).get(str(k['id'])) or {'modules': [], 't': 0}
    equipped = [m['loot'] for m in r['modules']]
    s['plan'] = s.get('plan') or build_plan(b)
    missing = list(s['plan'])
    for l in equipped:
        if l in missing:
            missing.remove(l)
    if not missing:
        minutes = b.r.randint(*setting()['build_min'])
        if CB.bot_build(int(aid), k, r['modules'], minutes, log=y.log):
            s['target'] = None
            b.event('cbs_building', now, station=CB.ASTEROIDS[int(aid)]['name'])
        return
    if now - r.get('t', 0) < CB.D['install_sec']:
        return
    loot = missing[0]
    m = next((x for x in s['stock'] if x['loot'] == loot), None)
    if m is None:
        if not _pay(k, 'cbs', price(loot)):
            return                                       # money accumulates
        m = _new_module(loot)
    else:
        s['stock'].remove(m)
        if m['hp'] <= 0:                                # a module that was destroyed and came back: repaired first
            if not _pay(k, 'cbs', int(price(loot) * setting()['repair_ratio'])):
                s['stock'].append(m)
                return
            m.update(_new_module(loot), level=m['level'])
            m['hp'] = CB.level_value(CB.MODS[loot]['hp'], m['level'])
            m['shield'] = int(m['hp'] * CB.D['shield_ratio'])
            m.pop('cbs', None)                           # base values: cbs.hp_sync scales them to the panel's CBS HP multiplier
    with h.lock:
        r = a.setdefault('race', {}).setdefault(str(k['id']), {'modules': [], 't': 0})
        r['modules'].append(m)
        r['t'] = now
        a['version'] = a.get('version', 0) + 1
        h.d['cbs']['bot_clans'] = True
        h.dirty = True


def develop(y, b, k, h, asteroids, now):
    """Built stations: a destroyed satellite is repaired, then one module rises one level (every upgrade_sec)."""
    s = cbs(k)
    for aid, a in _mine(asteroids, k).items():
        if a.get('state') != 'built' or now - a.get('attack_at', 0) < 600:
            continue
        for y_ in a['slots'].values():
            m = y_.get('module')
            if m and m['hp'] <= 0 and _pay(k, 'cbs', int(price(m['loot']) * setting()['repair_ratio'])):
                with h.lock:
                    m['hp'] = CB.level_value(CB.MODS[m['loot']]['hp'], m['level'])
                    m['shield'] = int(m['hp'] * CB.D['shield_ratio'])
                    m.pop('cbs', None)
                    a['version'] = a.get('version', 0) + 1
                    h.dirty = True
                return
        if now - s.get('last_upgrade', 0) < setting()['upgrade_sec']:
            continue
        m = _to_upgrade(a, b)
        if m is None or not _pay(k, 'cbs', price(m['loot'], m['level'] + 1)):
            continue
        with h.lock:
            ratio = m['hp'] / max(1, CB.hp_max(m))          # the scaled HP ratio (the panel's CBS HP multiplier)
            m['level'] += 1
            m['hp'] = int(CB.level_value(CB.MODS[m['loot']]['hp'], m['level']) * min(1.0, ratio))
            m['shield'] = int(CB.level_value(CB.MODS[m['loot']]['hp'], m['level']) * CB.D['shield_ratio'] * min(1.0, ratio))
            m.pop('cbs', None)
            a['version'] = a.get('version', 0) + 1
            h.dirty = True
        s['last_upgrade'] = now
        b.event('cbs_upgraded', now, module=m['loot'], level=m['level'])
        return


DEFENSE_FIRST = 2                  # number of members sent as soon as the attack starts
DEFENSE_WAVE = 1                # number of members in each later wave
DEFENSE_GAP_SEC = 75.0            # between waves (s): they trickle to the base, no swarm
DEFENSE_LAST_SEC = 90              # an attack older than this counts as over, the queued ones are not sent


def defense_quota(attackers):
    """The most members sent in one attack: grows with the number of attackers (5 for a single player, 3 more per extra attacker; at most 12)."""
    return min(12, 5 + 3 * max(0, attackers - 1))


def _wave(y, b, k, st, game_map, n, now):
    """Sends at most n of the queued members to the station's map (clan_orders 'git') -> the number sent."""
    from . import clan_orders as CO
    outgoing = 0
    while st['queued'] and outgoing < n and st['sent'] < st['quota']:
        name = st['queued'].pop(0)
        o = y.name_index.get(name.lower())
        if o is None or not (o.online and o.dead_until <= now and o.k.get('clan') == k['id']):
            continue
        if CO.will_obey(o, b.name, True, now) and CO.apply(y, o, {'type': 'git', 'map': game_map}, b.name, None, now)[0] == 'coming':
            outgoing += 1
            st['sent'] += 1
    return outgoing


def defend(y, b, k, asteroids, now):
    """A player is attacking the station: news and mass mail (every defense_sec), the leader holds a grudge against the attacker. Online members are not
    all sent at once but in stages (clan_orders 'git'): the first DEFENSE_FIRST immediately, the rest DEFENSE_WAVE every DEFENSE_GAP_SEC; total
    defense_quota(number of attackers). If there has been no attack for longer than DEFENSE_LAST_SEC the queue is dropped. The pending queue is in the clan's record
    (k['ksi']['savunma'], clans.json): even if the server restarts, the rest are sent in an ongoing attack."""
    defense_state = cbs(k).setdefault('defense', {})
    for aid, a in _mine(asteroids, k).items():
        ongoing = now - a.get('last_player', 0) <= DEFENSE_LAST_SEC
        st = defense_state.get(str(aid))
        if st is not None:
            if not ongoing:
                defense_state.pop(str(aid), None)                      # the attack is over: the queued ones are not sent
                continue
            if a.get('last_attacker') and a['last_attacker'] not in st['attackers']:
                st['attackers'].append(a['last_attacker'])
                st['quota'] = max(st['quota'], defense_quota(len(st['attackers'])))
            if now >= st['next'] and st['queued']:
                st['next'] = now + DEFENSE_GAP_SEC
                _wave(y, b, k, st, st['map'], DEFENSE_WAVE, now)
            continue
        if not ongoing or now - cbs(k).get('last_defense', 0) < setting()['defense_sec']:
            continue
        cbs(k)['last_defense'] = now
        ist, game_map = CB.ASTEROIDS[aid]['name'], H.name(CB.ASTEROIDS[aid]['map'])
        who = a.get('last_attacker') or ''
        if who:
            b.memory.event(who, 'insult', now, multiplier=1.0)
        kl = CMG.kl_of(b)
        CMG.announce(b, kl, 'clan_announce_cbs_attack', station=ist, map=game_map)
        if KL.right(b.profile, 'roundmail'):
            CMG.bulk_mail(b, kl, 'clan_mail_cbs', station=ist, map=game_map)
        members = [o for o in y.bots if o.k.get('clan') == k['id'] and o.online and o.dead_until <= now]
        random.shuffle(members)
        st = defense_state[str(aid)] = dict(map=game_map, queued=[o.name for o in members], sent=0, quota=defense_quota(1),
                                  attackers=[who] if who else [], next=now + DEFENSE_GAP_SEC)
        outgoing = _wave(y, b, k, st, game_map, DEFENSE_FIRST, now)
        y.log('   bots: [%s] %s station under attack (%s), %d members to defense (%d left in stages)'
              % (k['tag'], ist, who or '?', outgoing, len(st['queued'])))
        b.event('cbs_defense', now, station=ist, attacker=who)
        return


def announce_status(b, k, asteroids, now):
    """Built / destroyed news (changes since the previous look)."""
    s = cbs(k)
    current_time = {str(aid): a.get('state') for aid, a in _mine(asteroids, k).items()}
    once = s.get('seen') or {}
    kl = None
    for aid, d in current_time.items():
        if d == 'built' and once.get(aid) != 'built':
            kl = kl or CMG.kl_of(b)
            CMG.announce(b, kl, 'clan_announce_cbs_built', station=CB.ASTEROIDS[int(aid)]['name'], map=H.name(CB.ASTEROIDS[int(aid)]['map']))
            b.event('cbs_built', now, station=CB.ASTEROIDS[int(aid)]['name'])
    for aid, d in once.items():
        if d == 'built' and aid not in current_time and int(aid) in CB.ASTEROIDS:
            kl = kl or CMG.kl_of(b)
            CMG.announce(b, kl, 'clan_announce_cbs_destroyed', station=CB.ASTEROIDS[int(aid)]['name'], map=H.name(CB.ASTEROIDS[int(aid)]['map']))
            b.event('cbs_destroyed', now, station=CB.ASTEROIDS[int(aid)]['name'])
    s['seen'] = current_time


def clean_up(y, h, asteroids):
    """Stations of dissolved clans are destroyed, their races and pending modules deleted."""
    d = h.d['cbs']
    for aid, a in list(asteroids.items()):
        if a.get('owner') == 'bot' and a.get('clan') not in KL.CLANS and a.get('state') in ('building', 'built'):
            CB.bot_demolish(int(aid), log=y.log)
        race = a.get('race') or {}
        for cid in [c for c in race if int(c) not in KL.CLANS]:
            with h.lock:
                race.pop(cid, None)
                a['version'] = a.get('version', 0) + 1
    for o in [o for o in (d.get('pending') or {}) if o.startswith('@klan:') and int(o[6:]) not in KL.CLANS]:
        d['pending'].pop(o, None)


def manage(y, b, k, kl, now):
    """The leader (or an officer with the right to build) in the social round: defense, race step, growth, news."""
    if not is_open() or not kl.right('battle_station_build', k):
        return
    h, asteroids = _registry()
    if h is None:
        return
    if CMG.is_due(k, 'cbs_cleanup', now, 600):
        clean_up(y, h, asteroids)
    to_stock(k, h.d['cbs'])
    defend(y, b, k, asteroids, now)
    announce_status(b, k, asteroids, now)
    race_step(y, b, k, h, asteroids, now)
    develop(y, b, k, h, asteroids, now)
