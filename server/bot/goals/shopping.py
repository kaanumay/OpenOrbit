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
    import json, os
    EXCHANGE_RATE = json.load(open(os.path.join(K.HERE, 'data', 'prices.json'), encoding='utf8')).get('exchange_rate', EXCHANGE_RATE)
except (OSError, ValueError):
    pass


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


def _candidates(bot):
    e = bot.k['gear']
    shield_share = bot.shield_share()
    base_values = K.values(e, shield_share)
    base = base_values['power']
    slot = K.outfit(e, shield_share)
    out = []

    def attempt(loot, owner=0, filler=None, force=False):
        f = K.price(loot, owner)
        if not f or f[1] <= 0:
            return
        y = {a: dict(v) if isinstance(v, dict) else v for a, v in e.items()}
        if loot.startswith('ship_'):
            y['ship'] = loot
        else:
            group = 'laser' if loot in K.ITEMS['lasers'] else 'shield' if loot in K.ITEMS['shield_generators'] else \
                'speed' if loot in K.ITEMS['speed_generators'] else 'drone'
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
    backup = sum(e.get('laser', {}).values()) - len(slot['laser'])
    best = max((l for l in e.get('laser', {}) if l in lasers), key=lasers.get, default=None)
    for loot, d in K.ITEMS['drones'].items():
        n = e.get('drone', {}).get(loot, 0)
        if sum(e.get('drone', {}).values()) < K.ITEMS['max_drones'] and K.price(loot, n):
            missing = max(0, d.get('slot', 1) - backup)
            attempt(loot, n, (best, missing) if best and missing else None)
    for loot in K.ships():
        if loot != e['ship']:
            attempt(loot)
    wanted = bot.k.get('savings')
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
    credit_equiv = lambda c: c[2] * (EXCHANGE_RATE if c[1] == 'U' else 1)
    # efficiency: gain / (price + a quarter of wealth): with little money efficiency per credit, with lots of money the size of the gain wins (a rich bot
    # with 80M credits and 2M uridium chose a 2,000 C +0.04 speed generator over a +3.4 power Apis; Laya trial 2026-10-31)
    wealth = currency['C'] + currency['U'] * EXCHANGE_RATE
    efficiency = lambda c: c[0] / max(1.0, credit_equiv(c) + 0.25 * wealth) * 1e5
    t = bot.o('frugality')
    target = next((c for c in all_candidates if c[3] == bot.k.get('savings')), None)
    if target is not None:                       # its own chosen saving goal (the agent's save-up tool): it buys only that
        if currency[target[1]] >= target[2]:
            return target, target
        # purchases that do not delay the goal's accumulation are free (another currency, or money left over above the goal): it used to look only
        # at the goal, a bot saving for an 80,000 U ship stood idle with 66M credits without buying shields/engines (player report 2026-11-01)
        free = [c for c in all_candidates if c[1] != target[1] and currency[c[1]] >= c[2] * (1 + 0.3 * bot.o('frugality'))
                   or c[1] == target[1] and currency[c[1]] - c[2] >= target[2]]
        return max(free, key=lambda c: c[0], default=None), target
    affordable = [c for c in all_candidates if currency[c[1]] >= c[2] * (1 + 0.3 * t)]        # a thrifty bot leaves a little reserve
    g = income(bot)
    horizon = 1.0 + 1.5 * t
    reachable = [c for c in all_candidates if c[2] * (1 + 0.3 * t) <= currency[c[1]] + g[c[1]] * horizon]
    target_candidate = max(reachable, key=efficiency, default=None)
    # far saving goal (panel, chat): the biggest gain it cannot afford yet
    remaining = [c for c in all_candidates if c not in affordable]
    savings = max(remaining, key=lambda c: c[0] * (0.5 + t) - credit_equiv(c) / 5e6, default=None)
    if target_candidate is not None and target_candidate not in affordable:
        savings = target_candidate
    if not affordable:
        return None, savings
    if bot.r.random() < 0.05 * (1 - t):                                     # impulsive purchase (human error)
        return bot.r.choice(affordable), savings
    if target_candidate is None or target_candidate in affordable:
        return max(affordable, key=efficiency), savings
    iyi = [c for c in affordable if efficiency(c) >= 0.7 * efficiency(target_candidate)]
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
        # buys in turn as long as the money suffices in one shopping trip (at most MAX_TRIP_ITEMS): it used to buy a single item per trip, a bot with 10M
        # credits bought 8 items in an hour and stood idle without spending 80% of its money (player report 2026-10-31)
        c = b.shopping[0]
        for _ in range(MAX_TRIP_ITEMS):
            increase, currency, price, loot = c
            if not bot.pay(currency, price):
                break
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
        bot.plan['finished'] = True

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
