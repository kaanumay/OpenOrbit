"""Shopping: buy the most efficient upgrade the bot can afford, or save up for a big goal.

Candidates come from the catalog (laser, shield/speed generator, drone, ship): for each, the new equipment's power gain / price (in credit
terms, 1 U = kur credits). A thrifty bot with a big saved-up goal (like a Goliath) does not spend on small purchases; an impulsive bot
occasionally also buys something that is not the best (human error).
"""
from ..brain import Goal, target
from .. import catalog as K
from .. import personality as PS

EXCHANGE_RATE = 100                 # how many credits 1 uridium is worth (fiyatlar.json kur)
MAX_TRIP_ITEMS = 15           # at most this many items in one shopping trip
try:
    import game_data as DATA
    EXCHANGE_RATE = DATA.shared('prices.json').get('exchange_rate', EXCHANGE_RATE)
except (OSError, ValueError):
    pass


# ------------------------------------------------------------------------------------------------ the ship wish
# A pilot of the mid levels wants a particular ship with abilities for its role (a repair ship, a tank, a hunter ...) and keeps uridium
# for it instead of shooting all of it away as x2/x3 ammunition (lab 2026-11-23: level 12-15 bots earned ~10,000 U a day and spent ~9,900
# on ammunition, 2-15% flew a ship with abilities). Behaviour parameters (not game values):
WISH_NEVER = {'saver': 0.04, 'balanced': 0.12, 'spender': 0.35, 'impulsive': 0.6}     # share of pilots who never save for a ship
WISH_KEEP = {'saver': 0.95, 'balanced': 0.85, 'spender': 0.6, 'impulsive': 0.4}       # share of its uridium kept for the wish
WISH_DAYS = (12, 60)          # how many days of uridium income a ship may cost to be wished (impatient .. patient)
WISH_RETHINK = (3, 10)        # days between two looks at the wish; on a look a pilot changes its mind with WISH_SWITCH
WISH_SWITCH = 0.25
WISH_POWER = {'support': 0.7, 'tank': 0.7, 'hunter': 0.5, 'runner': 0.7}    # least power share against the flown ship (same gear): a
                                                                             # hunter takes a light Spearhead for its cloak and marker
ROLES = {'support': ('heal_ally', 'shield_ally'), 'tank': ('taunt', 'defense'), 'hunter': ('debuff', 'burst', 'control', 'area', 'cloak'),
         'runner': ('speed',)}


def _u(bot, key):
    import zlib
    return (zlib.crc32(('%s|%s' % (bot.name, key)).encode()) % 10000) / 9999.0


def role_fit(bot, role):
    """How much a pilot likes a role (traits and play style)."""
    from .. import playstyle as PL
    o = bot.o
    return {'support': 0.6 * o('helpfulness') + 0.3 * o('sociability') + 0.15 * (PL.like(bot, 'social') - 1),
            'tank': 0.35 * o('patience') + 0.25 * o('loyalty') + 0.15 * (1 - o('risk')),
            'hunter': 0.5 * o('aggression') + 0.35 * o('rivalry') + 0.15 * (PL.like(bot, 'pvp') - 1),
            'runner': 0.35 * o('risk') + 0.2 * (1 - o('patience'))}[role]


def ship_roles(loot):
    """The ship's roles from its abilities' classes (abilities.CLASS): a Citadel's Protection makes it a tank, not a repair ship; speed
    alone makes a runner."""
    from .. import abilities as AB
    ks = {k for i in AB.SHIPS.get(loot, {}).get('skills', ()) if i in AB.CLASS for k in AB.CLASS[i]}
    if 'taunt' in ks:
        ks.discard('shield_ally')
    out = [r for r, kinds in ROLES.items() if r != 'runner' and ks & set(kinds)]
    return out or (['runner'] if 'speed' in ks else [])


def daily_uridium(bot):
    """Uridium a day: the map's income per hour (income) over the pilot's usual hours a day, and its weekly payments."""
    from .. import playstyle as PL
    pl = PL.profile(bot)
    return income(bot)['U'] * pl.get('daily_h', 4) + pl.get('wallet_week', 0) / 7.0


def _pick(bot, old, now):
    from .. import playstyle as PL
    style = PL.profile(bot)['spend']
    nxt = now + 86400 * (WISH_RETHINK[0] + (WISH_RETHINK[1] - WISH_RETHINK[0]) * _u(bot, 'rethink%d' % int(now // 86400)))
    if _u(bot, 'never') < WISH_NEVER[style] and not PL.has(bot, 'hoarder'):
        return dict(ship=None, next=nxt)
    if old and old.get('ship') and old['ship'] != bot.k['gear']['ship'] and _u(bot, 'switch%d' % int(now // 86400)) >= WISH_SWITCH:
        return dict(old, next=nxt)                          # keeps wanting the same ship
    e = bot.k['gear']
    shield_share = bot.shield_share()
    base = K.values(e, shield_share)['power']
    cur = K.price(e['ship']) or ('C', 0)
    reach = bot.k['uridium'] + daily_uridium(bot) * (WISH_DAYS[0] + (WISH_DAYS[1] - WISH_DAYS[0]) * bot.o('patience'))
    taste = PS.taste(bot.k['personality'])
    best = None
    for loot in K.ships():
        f = K.price(loot)
        roles = ship_roles(loot)
        if not roles or loot == e['ship'] or not f or f[0] != 'U' or f[1] > reach or (cur[0] == 'U' and f[1] <= cur[1]):
            continue
        if K.values(dict(e, ship=loot), shield_share)['power'] < min(WISH_POWER[r] for r in roles) * base:
            continue
        score = max(role_fit(bot, r) for r in roles) + (0.35 if taste in loot else 0) + 0.25 * _u(bot, loot + str(int(now // 864000)))
        score -= 0.25 * f[1] / max(1.0, reach)                  # a ship far off counts a little less
        if best is None or score > best[0]:
            best = (score, loot)
    return dict(ship=best[1] if best else None, next=nxt)


def wish(bot, now=None):
    """The ship with abilities this pilot saves uridium for (None: none it wants, never saves, or flies it already)."""
    if not bot.permission.get('shop', True):
        return None
    now = now or bot.hour()
    w = bot.k.get('ship_wish')
    if w is None or now >= w.get('next', 0):
        old = w
        w = bot.k['ship_wish'] = _pick(bot, w, now)
        if (old or {}).get('ship') != w['ship']:
            bot._candidates = None
            if w['ship']:
                bot.event('ship_wish', item=w['ship'])
    s = w.get('ship')
    return s if s and s != bot.k['gear']['ship'] else None


def held(bot):
    """Uridium kept for the ship wish (not spent on ammunition, CPUs, gates, looks ...)."""
    s = wish(bot)
    if not s:
        return 0
    from .. import playstyle as PL
    keep = 1.0 if PL.has(bot, 'hoarder') else WISH_KEEP[PL.profile(bot)['spend']]
    return int(min(bot.k['uridium'], K.price(s)[1]) * keep)


def candidates(bot):
    """[(power gain, currency, price, loot)]: every purchase that has a slot or a better ship. Kept on the bot until the equipment changes."""
    if bot._candidates is None:
        bot._candidates = _candidates(bot)
    return bot._candidates


def ship_affinity(bot, ship):
    """How much the bot likes flying this ship (power factor): its ship family (taste) +25%, every other ship a lasting personal liking of
    -8%..+8% (from the name). Without it every bot ended on the Citadel, the ship with the highest power score and an 80,000 U price, and
    nothing else counted as better afterwards (player report 2026-11-02: "every bot is a Citadel")."""
    if PS.taste(bot.k['personality']) in ship:
        return 1.25
    import zlib
    return 0.92 + 0.16 * (zlib.crc32(('%s|%s' % (bot.name, ship)).encode()) % 1000) / 999.0


def replaces_flax(drones, loot):
    return loot == 'drone_iris' and drones.get('drone_flax', 0) > 0 and not K.drone_room(drones, loot)


def _candidates(bot):
    e = bot.k['gear']
    shield_share = bot.shield_share()
    base_values = K.values(e, shield_share)
    base = base_values['power']
    slot = K.outfit(e, shield_share)
    out = []

    def attempt(loot, owner=0, filler=None, force=False):
        if K.ITEMS['lasers'].get(loot, K.ITEMS['shield_generators'].get(loot, {})).get('pet_only'):
            return
        if loot in K.ITEMS['drones'] and not (K.drone_room(e['drone'], loot) or replaces_flax(e['drone'], loot)):
            return
        f = K.price(loot, owner)
        if not f or f[1] <= 0:
            return
        y = {a: dict(v) if isinstance(v, dict) else v for a, v in e.items()}
        if loot.startswith('ship_'):
            y['ship'] = loot
        else:
            group = 'laser' if loot in K.ITEMS['lasers'] else 'shield' if loot in K.ITEMS['shield_generators'] else \
                'speed' if loot in K.ITEMS['speed_generators'] else 'drone'
            if replaces_flax(e['drone'], loot):
                y['drone']['drone_flax'] -= 1
            y[group][loot] = y[group].get(loot, 0) + 1
        if filler:                                        # the drone's empty slots get filled by the laser to be bought later
            y['laser'][filler[0]] = y['laser'].get(filler[0], 0) + filler[1]
        new_values = K.values(y, shield_share)
        power = new_values['power'] - base
        if loot.startswith('ship_'):                     # taste: the power as the bot weighs it on the ship it likes (not everyone converges on one ship);
            # lean: aliens are hunted for income, the kill speed decides it and HP beyond survival adds little: a ship that trades damage for
            # HP (Citadel: 7 lasers, 650,000 HP) counts a little less, one that trades HP for damage a little more
            lean = (new_values['dps'] / max(1.0, new_values['ehp'])) / max(1e-9, base_values['dps'] / max(1.0, base_values['ehp']))
            power = new_values['power'] * lean ** 0.15 * ship_affinity(bot, loot) - base * ship_affinity(bot, e['ship'])
        increase = power + 0.02 * (new_values['speed'] - base_values['speed']) * (0.5 + bot.o('risk'))    # speed is not in power: it helps with escaping and hunting
        if filler:                                        # efficiency together with the lasers' money (the share falling on the drone's price)
            lf = K.price(filler[0])
            credit_equiv = lambda c: c[1] * (EXCHANGE_RATE if c[0] == 'U' else 1)
            increase *= credit_equiv(f) / (credit_equiv(f) + filler[1] * credit_equiv(lf))
        if increase > 1e-6 or force:                       # forced: clan order (the requested ship/item even if not better)
            out.append((max(increase, 1e-3), f[0], f[1], loot))

    # laser: if the slot is empty or better than the weakest; the first few by price/damage order
    lasers = K.lasers()
    for loot in sorted(lasers, key=lasers.get):
        if len(slot['laser']) < slot['laser_slots'] or lasers[loot] > min(slot['laser'] or [0]):
            attempt(loot)
    for loot in K.shield_generators():
        attempt(loot)
    for loot in K.speed_generators():
        attempt(loot)
    # a drone only opens laser slots: with no spare laser the gain was counted as 0 and Flax was never bought (player report 2026-10-31);
    # the empty slots count as filled with the best (purchasable) laser at hand
    backup = sum(n for loot, n in e.get('laser', {}).items()
                 if loot in K.ITEMS['lasers'] and not K.ITEMS['lasers'][loot].get('pet_only')) - len(slot['laser'])
    best = max((l for l in e.get('laser', {}) if l in lasers), key=lasers.get, default=None)
    for loot, d in K.ITEMS['drones'].items():
        n = e.get('drone', {}).get(loot, 0)
        replacing = replaces_flax(e['drone'], loot)
        if (K.drone_room(e['drone'], loot) or replacing) and K.price(loot, n):
            old_slots = K.ITEMS['drones']['drone_flax']['slot'] if replacing else 0
            missing = max(0, d.get('slot', 1) - old_slots - backup)
            attempt(loot, n, (best, missing) if best and missing else None)
    for loot in K.ships():
        if loot != e['ship']:
            attempt(loot)
    wanted = bot.k.get('savings') or wish(bot)
    if wanted and not any(c[3] == wanted for c in out) and (wanted.startswith('ship_') or any(
            wanted in K.ITEMS[g] for g in ('lasers', 'shield_generators', 'speed_generators', 'drones'))):
        attempt(wanted, e.get('drone', {}).get(wanted, 0), force=True)
    from .. import extras as EX
    out += EX.candidates(bot)                               # CPUs and repair robots (benefit as a power share)
    from .. import technology as TECH
    out += TECH.candidates(bot)                               # rocket launcher
    return out


def income(bot):
    """Estimated hourly income {'C': credits, 'U': uridium}: if it grinds on the map it is on (catalog.evaluate_map)."""
    d = bot.value()
    try:
        r = K.evaluate_map(int(bot.game_map), d['dps'], d['ehp'], 0.5)
    except (KeyError, ValueError, TypeError):
        return {'C': 0.0, 'U': 0.0}
    return {'C': r['credits_per_hour'], 'U': r['uridium_per_hour'] + 25}           # +25: bonus boxes, quest rewards


def candidate(bot):
    """-> (what to buy now (power gain, currency, price, loot) or None, the goal being saved for or None).

    Goal-driven like a real player: the most efficient upgrade it can reach soon (with 1-2.5 hours of income, by thriftiness) is the goal;
    if it can afford it, it buys it. If not, it only makes a small purchase that is nearly as efficient as the goal (at least 70%),
    otherwise it saves. It used to immediately buy the most efficient thing it could afford: while saving for the SLL-01 (50,000 C) it kept
    buying 2,000-8,000 C speed generators and MP-1 in turn and replacing one with another on a single-slot Phoenix (packet analysis 2026-10-29)."""
    all_candidates = candidates(bot)
    if not all_candidates:
        return None, None
    m = bot.game_settings.multiplier('shop_price')                  # the profile's shop price multiplier
    if m != 1.0:
        all_candidates = [(a, p, f * m, l) for a, p, f, l in all_candidates]
    currency = {'C': bot.k['credits'], 'U': bot.k['uridium']}
    currency['C'] = max(0, currency['C'] - bot.clan_savings())                     # will found a clan: saves the founding fee
    from .. import playstyle as PL
    keep = PL.reserve(bot)                                     # a saver never goes broke, a spender spends it all
    currency = {'C': currency['C'] * (1 - keep['C']), 'U': currency['U'] * (1 - keep['U'])}
    credit_equiv = lambda c: c[2] * (EXCHANGE_RATE if c[1] == 'U' else 1)
    # efficiency: gain / (price + a quarter of wealth): with little money efficiency per credit, with lots of money the size of the gain wins (a rich bot
    # with 80M credits and 2M uridium chose a 2,000 C +0.04 speed generator over a +3.4 power Apis; Laya trial 2026-10-31)
    wealth = currency['C'] + currency['U'] * EXCHANGE_RATE
    efficiency = lambda c: c[0] * PL.misjudge(bot, c[3]) / max(1.0, credit_equiv(c) + 0.25 * wealth) * 1e5     # weak money sense misjudges
    t = PL.thrift(bot)                                     # frugality shifted by the spending style (saver, spender, impulsive)
    wished = None if bot.k.get('savings') else wish(bot)
    target = next((c for c in all_candidates if c[3] == (bot.k.get('savings') or wished)), None)
    if target is not None:                       # its own chosen saving goal (the agent's save-up tool) or its ship wish: it buys only that
        if currency[target[1]] >= target[2] or (wished and bot.k[{'C': 'credits', 'U': 'uridium'}[target[1]]] >= target[2]):
            return target, target                # the wish: what it kept is for this (not the general reserve)
        # purchases that do not delay the goal's accumulation are free (another currency, or money left over above the goal): it used to look only
        # at the goal, a bot saving for an 80,000 U ship stood idle with 66M credits without buying shields/engines (player report 2026-11-01)
        free = [c for c in all_candidates if c[1] != target[1] and currency[c[1]] >= c[2] * (1 + 0.3 * t)
                   or c[1] == target[1] and currency[c[1]] - c[2] >= target[2]]
        return max(free, key=lambda c: c[0], default=None), target
    affordable = [c for c in all_candidates if currency[c[1]] >= c[2] * (1 + 0.3 * t)]        # a thrifty bot leaves a little reserve
    g = income(bot)
    horizon_h, good_share = PL.shop_horizon(bot)
    horizon = horizon_h * (0.6 + 0.8 * t)
    reachable = [c for c in all_candidates if c[2] * (1 + 0.3 * t) <= currency[c[1]] + g[c[1]] * horizon]
    target_candidate = max(reachable, key=efficiency, default=None)
    # far saving goal (panel, chat): the biggest gain it cannot afford yet
    remaining = [c for c in all_candidates if c not in affordable]
    savings = max(remaining, key=lambda c: c[0] * (0.5 + t) - credit_equiv(c) / 5e6, default=None)
    if target_candidate is not None and target_candidate not in affordable:
        savings = target_candidate
    if not affordable:
        return None, savings
    if bot.r.random() < PL.impulse_chance(bot):                             # impulsive purchase (human error, weak money sense)
        return bot.r.choice(affordable), savings
    if target_candidate is None or target_candidate in affordable:
        return max(affordable, key=efficiency), savings
    iyi = [c for c in affordable if efficiency(c) >= good_share * efficiency(target_candidate)]
    return (max(iyi, key=efficiency) if iyi else None), savings


@target
class Shopping(Goal):
    name = 'shopping'
    permission = 'shop'
    min_sec = 5

    def eligible(self, bot, b):
        return b.shopping[0] is not None

    def points(self, bot, b):
        increase = b.shopping[0][0]
        return min(1.6, 0.45 + increase / max(1.0, bot.value()['power']) * 3 + 0.2 * bot.o('ambition'))

    def start(self, bot, b):
        buy(bot, b.shopping[0])
        bot.plan['finished'] = True

    def finished(self, bot, b):
        return bot.plan.get('finished', False)


def buy(bot, c):
    """One shopping trip from candidate c on (also a quick one between two kills, brain.decision). It buys in turn as long as the money
    suffices (at most the pilot's trip size): it used to buy a single item per trip, a bot with 10M credits bought 8 items in an hour and
    stood idle without spending 80% of its money (player report 2026-10-31)."""
    from .. import playstyle as PL
    for _ in range(PL.trip_items(bot, MAX_TRIP_ITEMS)):
        increase, currency, price, loot = c
        drones = bot.k['gear']['drone']
        replacing = replaces_flax(drones, loot)
        if loot in K.ITEMS['drones'] and not (replacing or K.drone_room(drones, loot)):
            break
        if not bot.pay(currency, price):
            break
        if replacing:
            import upgrades
            drones['drone_flax'] -= 1
            if not drones['drone_flax']:
                del drones['drone_flax']
            bot.k['credits'] += int(upgrades.ITEMS['drone_flax']['selling'])
        bot.add(loot)
        bot.ist('purchase')
        bot.mood.it(morale=0.12 + min(0.3, increase / max(1.0, bot.value()['power'])))
        bot.event('purchase', item=loot, price=price, currency=currency)
        if loot.startswith('ship_'):
            bot.event('new_ship', item=loot)
        if bot.k.get('savings') == loot:
            bot.k['savings'] = None                  # got what it was saving for (the agent's save-up tool)
        bot._candidates = None                          # (even if the ship did not change, the remaining slots and money did)
        c = candidate(bot)[0]
        if c is None:
            break
