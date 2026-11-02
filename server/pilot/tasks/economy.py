"""Economy:
  - ore (Hunt mode: pilot.json ore, between fights when ticked; Mining mode: pilot.json mining): the chosen ore types near the ship are
    harvested; when the cargo is (nearly) full the ship flies to the company's station (this map's, or the nearest of X-1 / X-8), sells every
    cargo ore and comes back (tasks/modes.allows says when);
  - ammo resupply (supply): when an ammo's stock falls below a threshold, a silent purchase, within the session's budgets."""
from .. import brain as B

SUPPLY_SEC = 5.0
SUPPLY_FAIL_SEC = 60.0
SELL_FAIL_SEC = 120.0


def wants_sale(pilot, now):
    from . import modes as MODES
    c = MODES.ore_settings(pilot)
    return MODES.allows(pilot, 'sell') and now >= pilot.sell_block and pilot.act.cargo_free() <= c['sell_free'] and bool(pilot.act.ore_counts())


def sell_goal(pilot, s, now):
    """The trip to sell the cargo -> a label while on the way."""
    if not wants_sale(pilot, now):
        return None
    act = pilot.act
    st = act.go_to_station(now, act.sell_maps())
    if st == 'no_route':
        pilot.sell_block = now + SELL_FAIL_SEC
        pilot.note('cargo full but no station within reach')
        return None
    if st != 'here':
        return 'sell'
    earned = act.sell_all()
    if earned > 0:
        pilot.stats.add('sales')
        pilot.note('cargo sold: %d credits' % earned)
    if wants_sale(pilot, now):                      # nothing could be sold here: not again for a while
        pilot.sell_block = now + SELL_FAIL_SEC
    return None


def harvest(pilot, s, now):
    """An ore to harvest near the ship -> a label, or None."""
    from . import modes as MODES
    c = MODES.ore_settings(pilot)
    if not MODES.allows(pilot, 'harvest') or pilot.act.cargo_free() < 1:
        return None
    hx, hy = s['hero']
    thr = B.threats(s, pilot.cfg, None)
    ores = [o for o in s['ores'] if (not c['types'] or o['tip'] in c['types']) and B.dist(o['x'], o['y'], hx, hy) <= c['radius']
            and B.danger(o['x'], o['y'], thr) == 0]
    o = B.nearest(ores, hx, hy)
    if o is None:
        return None
    pilot.act.harvest(o['hash'], now)
    return 'ore'


def supply(pilot, now):
    """Buy the ammo of the resupply rules that ran low."""
    c = pilot.cfg['supply']
    if not c['rules'] or now - pilot.supply_at < SUPPLY_SEC:
        return
    pilot.supply_at = now
    act = pilot.act
    for r in c['rules']:
        loot = r['loot']
        if act.ammo_count(loot) >= r['below'] or now < pilot.supply_fail.get(loot, 0):
            continue
        cost = affordable(pilot, loot, r['amount'])
        if cost is None or not act.buy(loot, r['amount']):
            pilot.supply_fail[loot] = now + SUPPLY_FAIL_SEC
            pilot.note('could not buy %s (budget or money)' % loot)
            continue
        cur, n = cost
        pilot.stats.add('spent_' + cur, n)
        pilot.note('bought %d %s (%d %s)' % (r['amount'], loot, n, cur))


def affordable(pilot, loot, amount):
    """-> (currency, cost) when the budget left and the money allow the purchase, else None."""
    pr = pilot.act.buy_price(loot)
    if not pr:
        return None
    cur, unit = pr
    cost = int(round(unit * amount))
    left = pilot.cfg['supply']['max_' + cur] - pilot.stats['spent_' + cur]
    if cost > left or cost > pilot.act.money(cur):
        return None
    return cur, cost


def pending(pilot, loot):
    """A resupply rule will buy this ammo (stopping on low ammo waits for it)."""
    r = next((r for r in pilot.cfg['supply']['rules'] if r['loot'] == loot), None)
    return r is not None and affordable(pilot, loot, r['amount']) is not None
