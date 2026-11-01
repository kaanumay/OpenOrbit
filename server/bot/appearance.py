"""The bot's appearance: ship design, drones and formation, title, gate rings. Built from the messages the player sends to other players
(game.appearance): ShipCreateCommand.typeId and galaxyGatesDone, "0|n|t" title, "0|n|d" drones.

Design and formation are bought at the shop price like a player: only if it is a small share of its savings, depending on its love of showing off. The design
is only from the cosmetic ones (designs with bonuses change strength; the strength calculation does not know designs). The formation is permanent by personality:
aggressive Arrow/Pincer, cautious Turtle, grinder Star. The title comes from the game's achievement thresholds (alien, EP, honor); whether to
show it depends on personality. The choices are in the bot's record (gear['design'], k['formation'], k['formations']).

Drone designs (per drone like on the player, at the shop price): Havoc with a bonus (aggressive: +10% drone laser if all drones are Havoc) and
Hercules (cautious: +20% HP), plus cosmetic looks. In the bot's record gear['drone_design'] = {'design': [loot], 'appearance': [loot]},
by the ordered layout of the drones (by loot name, the order in the string); if all drones have the same bonus design it takes part in the strength calculation
(catalog values). Some bots collect one (a matching set), some mix it with the other when money is short.
"""
import math, zlib

from legacy_protocol import legacy
from . import catalog as K

FORMATION = {'drone_formation_default': 0, 'drone_formation_f-01-tu': 1, 'drone_formation_f-02-ar': 2,
             'drone_formation_f-04-st': 4, 'drone_formation_f-05-pi': 5}
MIN_DRONES = {'drone_formation_f-02-ar': 4, 'drone_formation_f-05-pi': 6}
# (title, statistic, threshold): the game's achievements (data/achievements.json achievement_destroy_aliens, _experience, _honor)
TITLES = (('title_achievement_honor-2', 'honor', 2500000), ('title_achievement_experience-2', 'ep', 10000000000),
            ('title_achievement_destroy_aliens-2', 'npc', 1000000), ('title_achievement_honor-1', 'honor', 450000),
            ('title_achievement_experience-1', 'ep', 100000000), ('title_achievement_destroy_aliens-1', 'npc', 1000))


def _stable_hash(bot, salt):
    return zlib.crc32(('%s|%s' % (salt, bot.name)).encode())


def showiness(bot):
    """Love of showing off (0-1): for those who are not thrifty, are competitive and are social."""
    return max(0.0, min(1.0, 0.5 * (1 - bot.o('frugality')) + 0.3 * bot.o('rekabet') + 0.2 * bot.o('sociability')))


def _can_afford(bot, currency, price):
    """If it is a small share of its savings (if it has 4-10 times as much, depending on thriftiness)."""
    return bot.k['credits' if currency == 'C' else 'uridium'] >= price * (4 + 6 * bot.o('frugality'))


# ------------------------------------------------------------------------------------------------------------ purchase
def cosmetic_designs(ship):
    return sorted(l for l, f in K.prices().items() if l.startswith(ship + '_design_') and l not in K.ITEMS['designs'])


def drone_count(bot):
    return sum(bot.k['gear'].get('drone', {}).values())


def drone_sequence(bot):
    """The drones' loots, in string order (by loot name)."""
    return [d for d, k in sorted(bot.k['gear'].get('drone', {}).items()) for _ in range(k) if d in K.ITEMS['drones']]


def drone_ids(bot):
    """The client's (design, look) ids for each drone (0 standard), in drone-array order."""
    dt = bot.k['gear'].get('drone_design') or {}
    t, g = dt.get('design') or [], dt.get('appearance') or []
    designs = K.ITEMS['drone_designs']
    out = []
    for i, _ in enumerate(drone_sequence(bot)):
        out.append((designs.get(t[i] if i < len(t) else '', {}).get('id', 0), designs.get(g[i] if i < len(g) else '', {}).get('id', 0)))
    return out


def drone_preference(bot):
    """Drone design with a bonus: Havoc for aggressive, Hercules for cautious."""
    return 'drone_designs_havoc' if bot.o('aggression') >= 0.5 else 'drone_designs_hercules'


def drone_looks():
    """Cosmetic drone looks sold in the shop (except the expensive ones with event prices: at most 100,000)."""
    designs = K.ITEMS['drone_designs']
    return sorted(l for l, v in designs.items() if v.get('slot') == 'visual' and K.price(l) and K.price(l)[1] <= 100000
                  and not v.get('per_event'))


def drone_shopping(bot):
    """One more drone: first the design with a bonus (when money allows; a third of the time, when money is short, it mixes in the other bonus design), then
    sometimes a cosmetic look. At most one purchase per call."""
    n = len(drone_sequence(bot))
    if not n:
        return
    dt = bot.k['gear'].setdefault('drone_design', {})
    designs, looks = dt.setdefault('design', []), dt.setdefault('appearance', [])
    del designs[n:], looks[n:]
    designs += [''] * (n - len(designs))
    looks += [''] * (n - len(looks))
    ist = drone_preference(bot)
    mixed = _stable_hash(bot, 'drone') % 3 == 0
    order = [ist] + ([x for x in ('drone_designs_havoc', 'drone_designs_hercules') if x != ist] if mixed else [])
    for i in range(n):
        if designs[i]:
            continue
        for loot in order:
            f = K.price(loot)
            if f and _can_afford(bot, *f) and bot.pay(*f):
                designs[i] = loot
                bot.event('new_design', item=loot)
                bot.loadout_changed()
                return
        break                                            # not enough money: the next drone waits, move on to cosmetics
    option = drone_looks()
    if option and bot.r.random() < 0.5 * showiness(bot):
        loot = option[_stable_hash(bot, 'appearance') % len(option)]
        f = K.price(loot)
        for i in range(n):
            if not looks[i] and f and _can_afford(bot, *f) and bot.pay(*f):
                looks[i] = loot
                bot.event('new_design', item=loot)
                return


def formation_preference(bot):
    """The formation wanted by personality (the first one the drone count allows)."""
    n = drone_count(bot)
    if not n:
        return 'drone_formation_default'
    if bot.o('aggression') > 0.65:
        order = ('drone_formation_f-05-pi', 'drone_formation_f-02-ar')
    elif bot.o('risk') < 0.35:
        order = ('drone_formation_f-01-tu',)
    elif bot.o('ambition') > 0.6:
        order = ('drone_formation_f-04-st', 'drone_formation_f-02-ar')
    else:
        order = ('drone_formation_f-02-ar', 'drone_formation_f-01-tu')
    return next((f for f in order if n >= MIN_DRONES.get(f, 0)), 'drone_formation_default')


def shopping(bot, now):
    """Every half hour: design and formation (if the shop permission and money allow)."""
    if now < bot.__dict__.get('_cosmetic_t', 0) or not bot.permission.get('shop', True):
        return
    bot._cosmetic_t = now + 1800
    e = bot.k['gear']
    designs = e.get('design')
    if not designs or not designs.startswith(e['ship'] + '_design_'):
        option = cosmetic_designs(e['ship'])
        if option and bot.r.random() < 0.4 * showiness(bot):
            loot = option[_stable_hash(bot, e['ship']) % len(option)]          # each bot's taste: always wants the same design on the same ship
            f = K.price(loot)
            if f and _can_afford(bot, *f) and bot.pay(*f):
                e['design'] = loot
                bot.event('new_design', item=loot)
    drone_shopping(bot)
    owner = bot.k.setdefault('formations', ['drone_formation_default'])
    ist = formation_preference(bot)
    if ist not in owner:
        f = K.price(ist)
        if f and _can_afford(bot, *f) and bot.pay(*f):
            owner.append(ist)
    if ist in owner:
        bot.k['formation'] = ist
    elif bot.k.get('formation') not in owner or drone_count(bot) < MIN_DRONES.get(bot.k.get('formation'), 0):
        bot.k['formation'] = 'drone_formation_default'


# ------------------------------------------------------------------------------------------------------------ appearance
def tip(bot):
    """ShipCreateCommand.typeId: the design worn or the ship."""
    e = bot.k['gear']
    t = e.get('design')
    return t if t and t.startswith(e['ship'] + '_design_') else e['ship']


def rings(bot):
    """galaxyGatesDone: the bits of the gates it completed (galaxy_gates.RINGS)."""
    import galaxy_gates as GT
    return sum(GT.RINGS.get(k, 0) for k in set((bot.k.get('gate') or {}).get('done', ())))


def drone_level(bot):
    """Drones level up as they kill aliens (drone points in the game): level 2-6 at 200, 800, 1,800, 3,200, 5,000 aliens."""
    return 1 + min(5, int(math.sqrt(bot.k['stats'].get('npc', 0) / 200.0)))


def title(bot):
    """The top title it earned; None for a bot that chose not to show it (not showy)."""
    if showiness(bot) < 0.35:
        return None
    st = {'honor': bot.k['honor'], 'ep': bot.k['ep'], 'npc': bot.k['stats'].get('npc', 0)}
    return next((u for u, a, threshold in TITLES if st[a] >= threshold), None)


def messages(n):
    """Title and drone messages that go out with the ship (like game.appearance)."""
    import achievement as BS
    b = n.bot
    out = []
    u = title(b)
    if u in BS.TITLES:
        out.append(legacy('0|n|t|%d|%d|%s' % (n.id, BS.TITLES[u], u)))
    drones = drone_sequence(b)
    if drones:
        lv = drone_level(b)
        body = '|'.join('%d|%d|%d|%d' % (K.ITEMS['drones'][d]['type'], lv, t, g) for d, (t, g) in zip(drones, drone_ids(b)))
        f = FORMATION.get(b.k.get('formation') or '', 0)
        out.append(legacy('0|n|d|%d|%d|%s' % (n.id, f, body)))
    return out
