"""Palladium: free Galaxy Gate energy from the pirate maps (the player's rules: world.ore_spot, world.trade_palladium).

  collect   Palladium lies only in the fog field of 5-1 (50 pieces) and 5-3 (250 pieces); a bot that wants gates spends part of its time
            there picking it up instead of killing aliens (COLLECT_SHARE), more on 5-3 where the field is larger
  trade     at the pirate trader on 5-2, 15 Palladium = 1 gate energy (items.json ores.palladium_energy; the gate_energy setting applies);
            the generator spends energy before uridium (galaxy_gates.draw), so the gates cost nothing
  value     for the map choice one Palladium is worth what its energy saves: the spin price / 15 in uridium
A bot wants Palladium when it may play gates (permission 'gate', level 10 as the generator) and still has a gate to build.
"""
from . import catalog as K

PALLADIUM = 8                              # the ore index (items.json ores.kinds)
LOOT = 'resource_ore_palladium'
MARKET = 92                                # 5-2: the pirate trader
FIELDS = {91: 500.0, 93: 1500.0}           # Palladium per hour of collecting: 5-1 (50 pieces), 5-3 (250 pieces; 0.5 s each, regrow 15-30 s)
COLLECT_SHARE = 0.5                        # share of the time on 5-1/5-3 spent collecting instead of killing
COLLECT_PHASE_SEC = 90.0                   # concrete mode: collects and hunts in turns of this length
RATE = int(K.ITEMS['ores'].get('palladium_energy', 15))
TRADE_ENERGY = 20                          # it goes to the trader once it holds this much energy's worth (or a full hold)


def wants(bot):
    """Does the bot want Palladium: gates allowed, the generator's level, a gate still to build, cargo collected; not in simple mode
    (its bots never leave their map, the Palladium could not reach the trader)."""
    from . import manager as MGR
    if MGR.ACTIVE is not None and MGR.ACTIVE.mode == 'simple':
        return False
    if not bot.permission.get('gate', True) or not bot.permission.get('cargo', True) or bot.level < 10:
        return False
    now = bot.hour()
    c = bot.__dict__.get('_palladium_wants')
    if c is None or abs(now - c[0]) > 300:            # the gate estimate is not free: once every 5 minutes
        from . import galaxy_gates as GG
        c = (now, GG.target_gate(bot) is not None)
        bot.__dict__['_palladium_wants'] = c
    return c[1]


def pull(bot):
    """How much a gate-minded pilot is drawn to the Palladium maps: a share of its best map's utility (0.6 .. 1.3, ambition and rivalry)."""
    return 0.6 + 0.4 * bot.o('ambition') + 0.3 * bot.o('rivalry')


def quest_needs(bot):
    """Is the running quest's next condition a Palladium collection (pirate quests: A Cross to Bear, Penultimate Operations)."""
    if not bot.k.get('quest') or not bot.permission.get('cargo', True):
        return False
    from .goals import quest as BQ
    s = BQ.next_up(bot)
    return bool(s) and s[0]['type'] == BQ.COLLECT_LOOT


def collecting(bot):
    """Does it pick up Palladium where it is: for gate energy or for its quest."""
    return int(bot.game_map) in FIELDS and (quest_needs(bot) or wants(bot))


def counted(bot, n, y=None):
    """Palladium picked up: the quest's collection condition advances."""
    if n > 0 and bot.k.get('quest'):
        from .goals import quest as BQ
        BQ.advance(bot, BQ.COLLECT_LOOT, n, game_map=int(bot.game_map), y=y, loot=LOOT)


def held(bot):
    """Palladium in the cargo and in storage (sell_cargo puts it in storage at the company station)."""
    from . import weapons as WP
    return int((bot.k.get('cargo') or {}).get(str(PALLADIUM), 0)) + int(WP.stock(bot).get(LOOT, 0))


def value_u(bot):
    """Uridium one Palladium is worth: the spin price it saves / RATE."""
    from . import galaxy_gates as GG
    return GG.D['energy_price'] * bot.game_settings.multiplier('shop_price') / RATE


def per_hour(bot, map_id):
    """Palladium per hour while collecting on this map (the collection setting applies)."""
    return FIELDS.get(int(map_id), 0.0) * bot.game_settings.multiplier('collecting', 'ore')


def collect(bot, k, y=None):
    """Abstract mode: k hours of effective play on the bot's map -> Palladium into the cargo (as far as it fits)."""
    n = int(per_hour(bot, bot.game_map) * COLLECT_SHARE * k + bot.r.random())
    if n > 0:
        got = bot.add_cargo({PALLADIUM: n}).get(PALLADIUM, 0)
        if got:
            bot.ist('palladium', got)
            counted(bot, got, y)


def trade(bot):
    """At the 5-2 trader: Palladium (cargo first, then storage) -> gate energy; the remainder under RATE stays -> energy gained."""
    from . import weapons as WP
    from . import galaxy_gates as GG
    cargo = bot.k.setdefault('cargo', {})
    s = WP.stock(bot)
    total = held(bot)
    units = total // RATE
    if units <= 0:
        return 0
    use = units * RATE
    c = min(use, int(cargo.get(str(PALLADIUM), 0)))
    if c:
        cargo[str(PALLADIUM)] = int(cargo[str(PALLADIUM)]) - c
        if not cargo[str(PALLADIUM)]:
            cargo.pop(str(PALLADIUM))
    if use - c:
        s[LOOT] = int(s.get(LOOT, 0)) - (use - c)
        if not s[LOOT]:
            s.pop(LOOT)
    energy = max(1, int(round(units * bot.game_settings.multiplier('gate_energy'))))
    s[GG.ENERGY] = s.get(GG.ENERGY, 0) + energy
    bot.ist('palladium_energy', energy)
    bot.event('palladium_traded', energy=energy)
    return energy


def trade_due(bot):
    """Enough Palladium for the trip to 5-2: TRADE_ENERGY worth, or a hold mostly full of it."""
    n = held(bot)
    if n < RATE:
        return False
    return n >= RATE * TRADE_ENERGY or (bot.cargo_fill() >= 0.8 and n >= 0.5 * K.cargo_capacity(bot.k['gear']))
