"""Extras and CPUs: repair robots, R0K-T01, cargo CPU, HM-7, jump, cloak, Insta-Shield, Smart Bomb, extra slot.

What is installed is bot.k['gear']['ekstra'] {loot: remaining uses (if it has uses) or 1}; the slot count is the ship's (items.json ships.extra) +
the extra_slot of the SLE CPUs. Shopping candidates (shopping.candidates): each extra's benefit to the bot as a share of its power score,
by personality, level and permissions (a real player's priority order: repair robot first, then the CPUs that are useful to it).
Effects: ship (repair), weapons (rocket cooldown), catalog (cargo), targets/selling (HM-7), abstract_sim (jump, cloak, PvP).
"""
from . import catalog as K

EXTRAS = K.ITEMS['extras']
REPAIR_BOTS = K.ITEMS['repair_robots']
ORDER = ('equipment_extra_repbot_rep-s', 'equipment_extra_repbot_rep-1', 'equipment_extra_repbot_rep-2',
        'equipment_extra_repbot_rep-3', 'equipment_extra_repbot_rep-4')
ROKT = 'equipment_extra_cpu_rok-t01'
CARGO_CPU = 'equipment_extra_cpu_g3x-crgo-x'
HM7 = 'equipment_extra_hmd-07'
JP1, JP2 = 'equipment_extra_cpu_jp-01', 'equipment_extra_cpu_jp-02'
CLOAK = ('equipment_extra_cpu_cl04k-xs', 'equipment_extra_cpu_cl04k-m', 'equipment_extra_cpu_cl04k-xl')
ISH, SMB = 'equipment_extra_cpu_ish-01', 'equipment_extra_cpu_smb-01'
AIM1, AIM2 = 'equipment_extra_cpu_aim-01', 'equipment_extra_cpu_aim-02'
SLE = ('equipment_extra_cpu_sle-01', 'equipment_extra_cpu_sle-02', 'equipment_extra_cpu_sle-03', 'equipment_extra_cpu_sle-04')


def equipped(bot):
    return bot.k['gear'].setdefault('ekstra', {})


def var(bot, loot):
    return equipped(bot).get(loot, 0) > 0


def slot(bot):
    g = K.ITEMS['ships'].get(bot.k['gear']['ship']) or {}
    return int(g.get('extra') or 1) + max((EXTRAS[s]['extra_slot'] for s in SLE if var(bot, s)), default=0)


def right(loot):
    return (EXTRAS.get(loot) or {}).get('right', 1)


def use(bot, loot):
    """Spends one use of an extra that has uses -> was it spent (when the uses run out it leaves the slot)."""
    t = equipped(bot)
    if t.get(loot, 0) <= 0:
        return False
    t[loot] -= 1
    if t[loot] <= 0 and 'right' in (EXTRAS.get(loot) or {}):
        del t[loot]
        bot.loadout_changed()
    return True


def repair_level(bot):
    """Best installed repair robot 0 (none) .. 5 (REP-4)."""
    return max((i + 1 for i, r in enumerate(ORDER) if var(bot, r)), default=0)


def repair_sec(bot):
    """Full repair time (s; None if there is none)."""
    for r in reversed(ORDER):
        if var(bot, r):
            v = REPAIR_BOTS[r]
            return v.get('full_repair_sec') or (bot.value()['can'] / max(1, v.get('hp_per_minute', 1000)) * 60)
    return None


def cargo_multiplier(gear):
    return EXTRAS[CARGO_CPU]['cargo_multiplier'] if (gear.get('ekstra') or {}).get(CARGO_CPU) else 1.0


# ------------------------------------------------------------------------------------------------------------ shopping
def utility(bot, loot):
    """An extra's benefit to the bot: a share of the power score (0: it does not buy)."""
    trace, lv, o = bot.permission, bot.level, bot.o
    if loot in ORDER:
        i = ORDER.index(loot) + 1
        return max(0.0, 0.04 * i - 0.04 * repair_level(bot)) * (0.6 + 0.6 * (1 - o('risk')))
    if loot == ROKT:
        return (0.06 + 0.08 * o('aggression')) if trace.get('rocket', True) and lv >= 6 else 0.0
    if loot == CARGO_CPU:
        return 0.08 if trace.get('cargo', True) and lv >= 5 else 0.0
    if loot == HM7:
        return 0.1 if trace.get('cargo', True) and lv >= 8 else 0.0
    if loot in (JP1, JP2):
        return 0.05 + 0.04 * o('patience') if lv >= 5 and not var(bot, JP1) and not var(bot, JP2) else 0.0
    if loot in CLOAK:
        return 0.05 * (1 - o('risk')) if lv >= 8 and trace.get('pvp', True) and not any(var(bot, g) for g in CLOAK) else 0.0
    if loot in (ISH, SMB):
        return 0.05 * o('aggression') if lv >= 12 and trace.get('pvp', True) else 0.0
    if loot in (AIM1, AIM2):
        sky = (bot.k.get('skylab') or {}).get('mod', {}).get('XENO_MODULE', 0)
        return 0.06 * o('rekabet') if lv >= 14 and sky >= 3 and not var(bot, AIM1) and not var(bot, AIM2) else 0.0
    if loot in SLE:
        empty = slot(bot) - len(equipped(bot))
        extra = EXTRAS[loot]['extra_slot'] - max((EXTRAS[s]['extra_slot'] for s in SLE if var(bot, s)), default=0)
        return 0.02 * extra if empty <= 0 and extra > 0 else 0.0
    return 0.0


def candidates(bot):
    """Shopping candidates [(power gain, currency, price, loot)]: extras that are useful and not owned, if there is a free slot (or a slot CPU)."""
    if not bot.permission.get('ekstra', True):
        return []
    power = bot.value()['power']
    empty = slot(bot) - len(equipped(bot))
    out = []
    for loot in list(ORDER) + [ROKT, CARGO_CPU, HM7, JP1, JP2, CLOAK[1], ISH, SMB, AIM2, AIM1] + list(SLE):
        if var(bot, loot) or (empty <= 0 and loot not in SLE and loot not in ORDER):
            continue
        f = K.price(loot)
        p = utility(bot, loot)
        if f and f[1] > 0 and p > 0:
            out.append((power * p, f[0], f[1], loot))
    return out


def equip(bot, loot):
    """A purchased extra is installed; a repair robot replaces the old one (single slot); if the slots are full the least useful one is removed."""
    t = equipped(bot)
    if loot in ORDER:
        for r in ORDER:
            t.pop(r, None)
    elif loot in SLE:
        for s in SLE:
            t.pop(s, None)
    if len(t) >= slot(bot) and loot not in SLE:
        dropped = min(t, key=lambda x: utility(bot, x) if x not in ORDER else 1.0)
        del t[dropped]
    t[loot] = right(loot)
    bot.loadout_changed()


# ------------------------------------------------------------------------------------------------------------ use
def jump(bot, target):
    """Does the jump CPU shorten this trip: target is the base (X-1), from a map the CPU allows, has uses -> the CPU used or None."""
    if target != K.ev(bot.firma) or not bot.permission.get('ekstra', True):
        return None
    import map_links as H
    name = H.name(bot.game_map)
    map_class = H.map_class(bot.game_map)
    for cpu in (JP2, JP1):
        if not var(bot, cpu):
            continue
        a = EXTRAS[cpu]['jump']
        if 'maps' in a and map_class not in a['maps']:
            continue
        if any(name.startswith(p) for p in a.get('ban', ())):
            continue
        return cpu
    return None


def cloak(bot):
    """Escapes a strong enemy with the cloak CPU -> was it used."""
    if not bot.permission.get('ekstra', True):
        return False
    return any(use(bot, g) for g in CLOAK if var(bot, g))


def pvp_factor(bot):
    """Contribution of Insta-Shield and Smart Bomb to power in PvP."""
    return 1.0 + 0.12 * var(bot, ISH) + 0.1 * var(bot, SMB)
