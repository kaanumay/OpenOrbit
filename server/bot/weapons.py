"""Weapons: stock of laser ammo and rockets, choosing by target, consumption on firing and resupply (like a real player).

Stock bot.k['stock'] {loot: count}: like a new pilot player it starts with 1,000 LCB-10 and 20 R-310; ammo comes from bonus boxes and
quests, the rest is bought from the shop (the player spends as many rounds per shot as the laser count: world.py). Choice:
  laser  LCB-10 for an ordinary alien; for a tough alien (over 90 s with LCB-10) x2/x3/x4 (MCB-25/50, UCB-100), in PvP RSB-75 or x4/x3,
         SAB-50 for a player with high shields (permission 'custom_ammunition'); if out of stock, whatever it has
  rocket the strongest it has (permission 'rocket'); cooldown 4 s, half with the R0K-T01 CPU
Resupply (at decision time): when the LCB-10 stock drops below a few hours' need, with a share of the credits; rockets and special ammo by
personality and money.
"""
from . import catalog as K

LCB, MCB25, MCB50, SAB, RSB = ('ammunition_laser_lcb-10', 'ammunition_laser_mcb-25', 'ammunition_laser_mcb-50',
                               'ammunition_laser_sab-50', 'ammunition_laser_rsb-75')
UCB = 'ammunition_laser_ucb-100'                     # x4: comes from gate and mode rewards; if it gets a shop price, resupply buys it too
MINES = ('ammunition_mine_acm-01', 'ammunition_mine_ddm-01')          # standard and direct damage (with uridium)
MINE_COOLDOWN = K.ITEMS['combat_items']['mine']['cooldown_sec']
ROCKETS = ('ammunition_rocket_r-310', 'ammunition_rocket_plt-2026', 'ammunition_rocket_plt-2021', 'ammunition_rocket_plt-3030')
STARTER_STOCK = {LCB: 1000, ROCKETS[0]: 20}             # a new player's stock (profile template)
ROCKET_COOLDOWN = K.COMBAT['rocket_cooldown_ms'] / 1000.0
HARD_SEC = 90                                         # an alien that takes longer than this with LCB-10 is "tough"


def stock(bot):
    return bot.k.setdefault('stock', dict(STARTER_STOCK))


def has_laser(bot):
    """Is there laser ammo (without it it cannot fire at an alien or a player; SAB-50 does not hit the hull)."""
    return pick_laser(bot) is not None


def multiplier(loot):
    return K.ITEMS['laser_ammo'].get(loot, {}).get('multiplier', 1)


def pick_laser(bot, ehp=0.0, pvp=False):
    """Which laser ammo (in stock) for this target -> loot or None (no rounds at all)."""
    s = stock(bot)
    special = bot.permission.get('custom_ammunition', True)
    frugal = bot.o('frugality')
    if special:
        if pvp:
            for c in (RSB, UCB, MCB50, MCB25):
                if s.get(c, 0) > 0:
                    return c
        dps = bot.value()['dps']
        if ehp and dps > 0 and ehp / dps > HARD_SEC:
            if s.get(UCB, 0) > 0 and (frugal < 0.5 or ehp / dps > 3 * HARD_SEC):
                return UCB
            if s.get(MCB50, 0) > 0 and (frugal < 0.5 or ehp / dps > 3 * HARD_SEC):
                return MCB50
            if s.get(MCB25, 0) > 0:
                return MCB25
    if s.get(LCB, 0) > 0:
        return LCB
    return next((c for c in (MCB25, MCB50, UCB, RSB) if s.get(c, 0) > 0), None)      # SAB-50 does not hit the hull: only the shield in PvP


def pick_rocket(bot):
    if not bot.permission.get('rocket', True):
        return None
    s = stock(bot)
    return next((r for r in reversed(ROCKETS) if s.get(r, 0) > 0), None)


def pick_mine(bot):
    if not bot.permission.get('mine', True):
        return None
    s = stock(bot)
    return next((m for m in MINES if s.get(m, 0) > 0), None)


def rocket_cooldown(bot):
    return ROCKET_COOLDOWN * (0.5 if 'equipment_extra_cpu_rok-t01' in (bot.k['gear'].get('extras') or {}) else 1.0)


def rocket_dps(bot, rocket):
    r = K.ITEMS['rockets'].get(rocket) or {}
    return r.get('damage', 0) * 0.92 * r.get('hit', K.COMBAT['rocket_hit_chance']) / rocket_cooldown(bot)


def spend(bot, loot, n):
    """Spends n units (as many as available) -> spent. Not spent if "infinite ammo" is on in the bots' game settings profile."""
    s = stock(bot)
    if bot.game_settings.get('infinite_ammo'):
        return min(n, s.get(loot, 0)) if s.get(loot, 0) > 0 else 0
    fractions = bot.__dict__.setdefault('_spend_fraction', {})
    v = n + fractions.get(loot, 0.0)
    fractions[loot] = v - int(v)
    n = min(int(v), s.get(loot, 0))
    if n > 0:
        s[loot] -= n
        if not s[loot]:
            del s[loot]
    return n


def add(bot, loot, n):
    """Adds to the stock; the fraction accumulates separately (the bonus boxes' average share is a few rounds per hour)."""
    s = stock(bot)
    fractions = bot.__dict__.setdefault('_stock_fraction', {})
    v = n + fractions.get(loot, 0.0)
    fractions[loot] = v - int(v)
    if int(v) > 0:
        s[loot] = s.get(loot, 0) + int(v)


# ------------------------------------------------------------------------------------------------------------ abstract combat
def grind_plan(bot, ehp):
    """What to use in abstract grinding -> (laser ammo, rocket, total dps, round damage per shot)."""
    d = bot.value()
    lasers = pick_laser(bot, ehp)
    rocket = pick_rocket(bot)
    from . import lab as LB, technology as TECH
    laser_dps = d['dps'] * multiplier(lasers) / max(1, multiplier(bot.k['gear'].get('ammunition'))) * (1 + LB.bonus(bot, LB.LASER)) if lasers else 0.0
    is_hard = d['dps'] > 0 and ehp / d['dps'] > HARD_SEC
    rkt_dps = rocket_dps(bot, rocket) * (1 + LB.bonus(bot, LB.ROCKET)) if rocket else 0.0
    if rkt_dps and is_hard and (bot.__dict__.get('_targeter', 0) > bot.hour() or TECH.use(bot, 'tech_precision-targeter')):
        if bot.__dict__.get('_targeter', 0) <= bot.hour():
            bot._targeter = bot.hour() + TECH.TECH['tech_precision-targeter']['duration_sec']
        rkt_dps /= (K.ITEMS['rockets'].get(rocket) or {}).get('hit', 0.8)            # Precision Targeter: rockets always hit
    from . import extras as EX
    aim = next((c for c in (EX.AIM2, EX.AIM1) if EX.var(bot, c)), None) if is_hard and bot.permission.get('extras', True) else None
    if aim and bot.k.get('cargo', {}).get('3', 0) >= 1000:                     # AIM CPU: 10 Xenomit per shot
        hit = K.COMBAT['laser_hit_chance']
        laser_dps *= (1 - (1 - hit) * (1 - K.ITEMS['extras'][aim]['aim'])) / hit
        bot._aim = True
    else:
        bot._aim = False
    fr = TECH.pick_launcher_rocket(bot) if is_hard else None
    bot._launcher_rocket = fr
    dps = laser_dps + rkt_dps + TECH.launcher_dps(bot, fr)
    return lasers, rocket, dps, laser_dps


def consume(bot, ehp_total, lasers, rocket, dps, laser_dps):
    """Rounds and rockets spent to melt ehp_toplam of alien HP -> sufficiency ratio (0..1; if the rounds run out it falls short)."""
    if dps <= 0 or ehp_total <= 0:
        return 1.0
    duration = ehp_total / dps
    ratio = 1.0
    if lasers and laser_dps > 0:
        d = K.outfit(bot.k['gear'], bot.shield_share())
        shot = duration / K.LASER_INTERVAL * max(1, len(d['laser']))           # as many rounds per shot as the laser count
        spent = spend(bot, lasers, shot)
        ratio = spent / shot if shot else 1.0
        if bot.__dict__.get('_aim'):
            k = bot.k['cargo']
            k['3'] = max(0, k.get('3', 0) - int(spent / max(1, len(d['laser'])) * 10))     # AIM CPU: 10 Xenomit per shot
        from . import lab as LB
        LB.spend(bot, LB.LASER, spent)                      # laboratory load per round
    if rocket:
        from . import lab as LB
        LB.spend(bot, LB.ROCKET, spend(bot, rocket, duration * ratio / rocket_cooldown(bot)))
    fr = bot.__dict__.get('_launcher_rocket')
    if fr:
        from . import technology as TECH
        capacity, search = TECH.salvo(bot)
        spend(bot, fr, duration * ratio * capacity / search)              # launcher salvos
    return ratio


_BOX = (None, None)


def _box_average():
    """Average per item of the bonus box table (once unless the table changes; again if the World Editor changes it)."""
    global _BOX
    import world as WD
    table = WD.CFG['bonus_boxes']
    if _BOX[0] is not table:
        avg = {}
        for loot, n in table:
            avg[loot] = avg.get(loot, 0) + n / len(table)
        _BOX = (table, avg)
    return _BOX[1]


def box_ammo(bot, box_count):
    """Ammo and credits from bonus boxes (the average of world's bonus box table)."""
    for loot, n in _box_average().items():
        pay = box_count * n
        if loot.startswith('ammunition'):
            add(bot, loot, pay)
        elif loot == 'credits':
            bot.reward('box', credits=pay)
        elif loot == 'energy':
            add(bot, 'resource_extra-energy', pay)      # Galaxy Gate energy


# ------------------------------------------------------------------------------------------------------------ resupply
def price(loot):
    f = K.price(loot)
    m = 1.0
    return (f[0], f[1] * m) if f else None


def hourly_ammo(bot):
    """Rounds spent per hour (share of time spent firing ~35%; as many per shot as the laser count)."""
    d = K.outfit(bot.k['gear'], bot.shield_share())
    return 3600 / K.LASER_INTERVAL * max(1, len(d['laser'])) * 0.35


def resupply(bot):
    """Buys from the shop when stock runs low (at decision time; a real player buys before running out of ammo). First LCB-10 (mandatory),
    then rockets and special ammo (by money and thrift) -> what was bought."""
    if not bot.permission.get('shop', True):
        return {}
    s = stock(bot)
    t = bot.o('frugality')
    hourly = hourly_ammo(bot)
    claimed = {}

    def buy(loot, count, pay):
        f = price(loot)
        if not f:
            return
        currency = 'credits' if f[0] == 'C' else 'uridium'
        budget = bot.k[currency] * pay
        count = int(min(count, budget // max(f[1], 1e-9)))
        if count > 0 and bot.pay(f[0], count * f[1]):
            add(bot, loot, count)
            claimed[loot] = count

    if s.get(LCB, 0) < hourly * (0.5 + t):
        buy(LCB, hourly * (2 + 2 * t), 0.6)            # mandatory: up to most of the credits
    if bot.permission.get('rocket', True) and sum(s.get(r, 0) for r in ROCKETS) < 30:
        en = None
        for r in ROCKETS:
            f = price(r)
            if f and (f[0] == 'C' and bot.k['credits'] > f[1] * 400 or f[0] == 'U' and bot.k['uridium'] > f[1] * 300 * (1 + t)):
                en = r
        if en:
            buy(en, 100 + 400 * (1 - t), 0.15)
    if bot.permission.get('custom_ammunition', True) and bot.level >= 3:
        if s.get(MCB25, 0) < 200 and bot.k['uridium'] > 300 * (1 + t):
            buy(MCB25, 500 + 1500 * (1 - t), 0.25)
        if bot.level >= 8 and s.get(MCB50, 0) < 200 and bot.k['uridium'] > 3000 * (1 + t):
            buy(MCB50, 1000 + 3000 * (1 - t), 0.2)
        if bot.level >= 10 and s.get(UCB, 0) < 200 and bot.k['uridium'] > 8000 * (1 + t):
            buy(UCB, 500 + 1500 * (1 - t), 0.2)              # if it has no price (not sold in the shop) al() skips it
        if bot.level >= 8 and bot.o('aggression') > 0.5 and s.get(RSB, 0) < 50 and bot.k['uridium'] > 5000 * (1 + t):
            buy(RSB, 200, 0.1)
    if bot.permission.get('mine', True) and bot.level >= 8 and bot.o('aggression') + bot.o('risk') > 0.9 \
            and sum(s.get(m, 0) for m in MINES) < 5 and bot.k['uridium'] > 4000 * (1 + t):
        buy(MINES[bot.r.random() < 0.3], 10 + 20 * (1 - t), 0.1)
    if bot.permission.get('extras', True) and bot.permission.get('pvp', True) and bot.level >= 8 and s.get('ammunition_specialammo_emp-01', 0) < 2 \
            and bot.k['uridium'] > 5000 * (1 + t) and bot.o('risk') < 0.7:
        buy('ammunition_specialammo_emp-01', 5, 0.1)
    if bot.permission.get('custom_ammunition', True) and bot.permission.get('pvp', True) and bot.level >= 8 and bot.k['uridium'] > 4000 * (1 + t):
        from . import active_items as AC
        for c in AC.SLOWERS:                           # slowing and freezing: in PvP (active_items.slow_down), small stock
            if s.get(c, 0) < 3 and bot.o('aggression') + bot.o('risk') > 0.8:
                buy(c, 3, 0.05)
    if claimed:
        bot.ist('resupply')
    return claimed
