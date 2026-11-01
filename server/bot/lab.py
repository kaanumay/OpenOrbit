"""Refining and laboratory: refine raw ore in the cargo into Prometid, Duranium, Promerium and load it onto the laser, rocket and shield
(like a player: shop.upgrade, items.json laboratuvar).

Recipes (per unit): Prometid 20 Prometium + 10 Endurium, Duranium 10 Endurium + 20 Terbium, Promerium 10 Prometid + 10
Duranium + 1 Xenomit. Loading: laser (0) and rocket (1) Prometid +15%, Promerium +30%, Seprom +60%; shield (2) Duranium +10%,
Promerium +20%. One unit of ore lasts 10 shots on the laser, 10 rockets on the rocket, 1 minute on the shield.
bot.k['lab'] {part: [ore, remaining]}: remaining shots / rockets / seconds. The same ore adds up, a different ore wipes the previous one
(as in the game).

Who upgrades: ambitious, competitive or spendthrift bots (permission 'lab', from level 4); a thrifty bot sells its ore. Refined ore
sells for less than raw, so only as much as it will load is refined.
"""
from . import catalog as K

LAB = K.ITEMS['lab']
RECIPES = {int(u): {int(t): n for t, n in g.items()} for u, g in LAB['recipes'].items()}      # 4, 5, 6
BONUS = {int(p): {int(c): v for c, v in g.items()} for p, g in LAB['bonuses'].items()}
UNIT = {int(p): v for p, v in LAB['unit'].items()}
LAZER, ROCKET, SHIELD = 0, 1, 2
PROMETID, DURANIUM, PROMERIUM = 4, 5, 6


def lab_data(bot):
    return bot.k.setdefault('lab', {})


def bonus(bot, part):
    """The part's current laboratory bonus (0: not loaded or used up)."""
    v = lab_data(bot).get(str(part))
    return BONUS[part].get(int(v[0]), 0.0) if v and v[1] > 0 else 0.0


def spend(bot, part, n):
    """Spends n units (shots, rockets or seconds) of the load; when it runs out the load is removed."""
    y = lab_data(bot)
    v = y.get(str(part))
    if not v:
        return
    v[1] -= n
    if v[1] <= 0:
        del y[str(part)]


def _cargo(bot):
    return bot.k.setdefault('cargo', {})


def refine(bot, product, count):
    """Refines at most `count` units from the inputs in the cargo -> amount refined."""
    cargo = _cargo(bot)
    recipe = RECIPES[product]
    n = min([count] + [cargo.get(str(t), 0) // g for t, g in recipe.items()])
    if n <= 0:
        return 0
    for t, g in recipe.items():
        cargo[str(t)] -= g * n
        if cargo[str(t)] <= 0:
            del cargo[str(t)]
    cargo[str(product)] = cargo.get(str(product), 0) + n
    bot.ist('refining', n)
    return n


def load(bot, part, ore, count):
    """Loads `count` units of ore from the cargo onto the part (the same ore adds up, a different one wipes the previous) -> amount loaded."""
    cargo = _cargo(bot)
    count = min(count, cargo.get(str(ore), 0))
    if count <= 0:
        return 0
    cargo[str(ore)] -= count
    if cargo[str(ore)] <= 0:
        del cargo[str(ore)]
    y = lab_data(bot)
    duration = count * UNIT[part] * (LAB.get('minute_sec', 60) if part >= 2 else 1)
    v = y.get(str(part))
    y[str(part)] = [ore, (v[1] if v and int(v[0]) == ore else 0) + duration]
    bot.ist('lab_load', count)
    return count


def will_upgrade(bot):
    if not bot.permission.get('lab', True) or bot.level < 4:
        return False
    return bot.o('ambition') * 0.5 + bot.o('rekabet') * 0.3 + (1 - bot.o('frugality')) * 0.4 > 0.55


def _is_promerium_good(bot, need):
    """Does the Promerium route (+30%) with the cargo gain much more than the Prometid route (+15%) (bonus x shots): tries it on a copy of
    the cargo."""
    original, counter = dict(_cargo(bot)), bot.k['stats'].get('refining', 0)
    try:
        refine(bot, PROMETID, need * 10)
        refine(bot, DURANIUM, need * 10)
        prom = refine(bot, PROMERIUM, need)
        bot.k['cargo'] = dict(original)
        prometid = refine(bot, PROMETID, need)
    finally:
        bot.k['cargo'] = original
        bot.k['stats']['refining'] = counter
    return BONUS[LAZER][PROMERIUM] * prom > BONUS[LAZER][PROMETID] * prometid


def decision(bot, hourly_ammo):
    """Laboratory with the ore in the cargo: if the load has dropped, refines and loads (laser first, then shield and rocket). Called
    before selling: the remaining ore is sold."""
    if not will_upgrade(bot):
        return
    cargo = _cargo(bot)
    target = hourly_ammo * (1 + bot.o('ambition'))                     # about one or two hours of shots
    v = lab_data(bot).get(str(LAZER))
    if not v or v[1] < target * 0.3:
        need = int(target / UNIT[LAZER]) + 1
        if cargo.get('3', 0) > 0 and _is_promerium_good(bot, need):     # Promerium (+30%) if there is Xenomit and it gains more
            refine(bot, PROMETID, need * 10)
            refine(bot, DURANIUM, need * 10)
            if refine(bot, PROMERIUM, need):
                load(bot, LAZER, PROMERIUM, need)
        else:
            refine(bot, PROMETID, need)
            load(bot, LAZER, PROMETID, need)
    v = lab_data(bot).get(str(SHIELD))
    if bot.o('risk') < 0.6 and (not v or v[1] < 1800):
        refine(bot, DURANIUM, 60)
        load(bot, SHIELD, DURANIUM, 60)                           # one hour of shield
    v = lab_data(bot).get(str(ROCKET))
    if bot.permission.get('rocket', True) and (not v or v[1] < 50):
        refine(bot, PROMETID, 10)
        load(bot, ROCKET, PROMETID, 10)
