"""Loot: key boxes, keys, boosters, aliens' extra loot and Assembly (the player's rules: loot.py, world.extra_loot, assembly.py, booster.py).

  box       opens a key box on the map with the key of its type; if it has no key for a green box, buys one with uridium (the player's
            autoBuyGreenBootyKeys) but only if the box's expected value is higher than the key's price and depending on personality (a frugal
            bot does not spend its uridium); the reward is drawn from the box's table by weight
  extra     the alien's extra loot (npc.json extra_reward: Scrapium, Mucosum, log file ...) goes to stock
  assembly  from the recipes visible at that moment (single player: all in the save; those who want event currency while the event runs or
            while they hold currency) makes the one whose materials it has and whose result is worth more than it spends: key, technology
            item, ammo, equipment
  booster   10 hours (booster data); EP, honor, resource, damage, HP, shield shares, capped by the type
Values are in credit terms (1 U = 100 C): by money, ammo and items by shop price, a key box by its expected value.
"""
import json, os, random

from . import catalog as K

EXCHANGE_RATE = 100
import loot as LOOT                                   # noqa: E402  (the game's loot module: boxes, maps, calendar)

RECIPES = json.load(open(os.path.join(K.HERE, 'data', 'recipes.json'), encoding='utf8'))['recipes']
BOOSTER = K.ITEMS['boosters']
ORE_LOOT = {v: int(k) for k, v in K.ITEMS['ores']['kinds'].items()}     # resource_ore_* -> cargo ore
CURRENCY = {'currency_credits': 'credits', 'currency_uridium': 'uridium', 'currency_experience': 'ep', 'currency_honour': 'honor'}
_ev = {}


def stock(bot):
    from . import weapons as WP
    return WP.stock(bot)


# ------------------------------------------------------------------------------------------------------------ value
def value(loot, n=1, depth=0):
    """The item's approximate value to the bot (credits)."""
    if loot in CURRENCY:
        return n * {'credits': 1, 'uridium': EXCHANGE_RATE, 'ep': 0.3, 'honor': 3}[CURRENCY[loot]]
    if loot in ORE_LOOT:
        return n * K.ore_prices(0).get(ORE_LOOT[loot], 0)
    if loot.startswith('resource_booty-key') and depth < 1:
        kind = LOOT.KEYS.get(loot)
        return n * box_value(kind, depth + 1) if kind else 0
    if loot.startswith('booster_'):
        return n * 3000
    f = K.price(loot)
    if f and f[1] > 0:
        v = n * f[1] * (EXCHANGE_RATE if f[0] == 'U' else 1)
        return v * 0.3 if loot.startswith(('ship_', 'equipment_', 'drone_')) else v     # item from loot: its sale value if it is of no use
    return 0


def box_value(kind, depth=0):
    """The box's expected value (weighted average of the reward table)."""
    if kind in _ev:
        return _ev[kind]
    rows = LOOT.BOXES[kind].get('reward') or []
    total = sum(r[2] for r in rows) or 1
    v = 0.0
    for loot, n, w in rows:
        if loot == LOOT.PACKAGE:
            v += w * sum(value(l, c, depth) for l, c in n)
        else:
            v += w * value(loot, n, depth)
    _ev[kind] = v / total
    return _ev[kind]


# ------------------------------------------------------------------------------------------------------------ reward
def give(bot, loot, n):
    """The reward to the bot: money is income, ore goes to cargo, booster is activated, items and ammo bot.add, the rest (keys, resources) to stock."""
    if loot in CURRENCY:
        bot.reward('box', **{CURRENCY[loot]: n})
    elif loot in ORE_LOOT:
        bot.add_cargo({ORE_LOOT[loot]: n})
    elif loot.startswith('booster_'):
        booster(bot, loot)
    elif loot.startswith(('ship_', 'equipment_', 'ammunition_', 'tech_', 'drone_')) and bot.add(loot, n):
        pass
    else:
        s = stock(bot)
        s[loot] = s.get(loot, 0) + int(n)


def booster(bot, loot):
    """Booster 10 hours: k['booster'] {type: [value, end]} (a second one of the same type extends the duration)."""
    b = bot.k.setdefault('booster', {})
    now = bot.hour()
    for kind, v in (BOOSTER['kinds'].get(loot) or {}).items():
        e = b.get(kind)
        end_time = max(now, e[1] if e else now) + BOOSTER['sure_sn']
        b[kind] = [min(BOOSTER['cap'].get(kind, v), v), end_time]
    bot.loadout_changed()


def booster_share(bot, kind):
    e = (bot.k.get('booster') or {}).get(kind)
    return e[0] / 100.0 if e and e[1] > bot.hour() else 0.0


def extra_loot(bot, tip, n=1):
    """The alien's extra loot (collectible resources, log file) to stock."""
    import world as WD
    for loot, spec in ((K.NPC['types'].get(str(tip)) or {}).get('extra_reward') or {}).items():
        c = sum(WD.extra_count(spec) for _ in range(min(int(n), 20))) * (n / min(int(n), 20) if n > 20 else 1)
        if c > 0:
            give(bot, loot, int(c))


# ------------------------------------------------------------------------------------------------------------ boxes
def key_item(kind):
    return LOOT.BOXES[kind]['anahtar']


def can_open(bot, kind):
    """Can it open the box / is it worth opening: yes if it has the key; for a green box it can buy a key (if its uridium and personality
    allow and the box is worth more than its price). A key that is bought is added to stock."""
    if not bot.permission.get('booty', True):
        return False
    key = key_item(kind)
    if stock(bot).get(key, 0) > 0:
        return True
    f = K.price(key)
    if key != LOOT.GREEN_KEY or not f or not bot.permission.get('shop', True):
        return False
    price = f[1] * bot.game_settings.multiplier('shop_price')
    t = bot.o('frugality')
    if box_value(kind) < price * EXCHANGE_RATE * (0.8 + 0.8 * t) or bot.k['uridium'] < price * (2 + 4 * t):
        return False
    if not bot.pay('U', price):
        return False
    stock(bot)[key] = stock(bot).get(key, 0) + 1
    bot.ist('key_pickup')
    return True


def open_box(bot, kind, rng=random):
    """A key is spent, a reward is drawn from the table by weight -> [(loot, count)]."""
    s = stock(bot)
    key = key_item(kind)
    if s.get(key, 0) <= 0:
        return []
    s[key] -= 1
    if not s[key]:
        del s[key]
    rows = LOOT.BOXES[kind].get('reward') or []
    if not rows:
        return []
    r = rng.choices(rows, weights=[x[2] for x in rows])[0]
    out = list(r[1]) if r[0] == LOOT.PACKAGE else [(r[0], r[1])]
    for loot, n in out:
        give(bot, loot, n)
    bot.ist('box_opened')
    bot.event('box_opened', box=LOOT.BOXES[kind]['name'])
    return out


_active = {}


def active_boxes(name):
    """The key boxes spawning on the map now [(type, count)]: the calendar computation is heavy, once a minute (per map)."""
    import time
    t = time.time()
    e = _active.get(name)
    if e is None or t - e[0] > 60:
        e = _active[name] = (t, [(k, n) for k, n in LOOT.spawns(name) if LOOT.active(k)])
    return e[1]


def abstract(bot, dt, y):
    """Encountering the map's key boxes in abstract mode: box count / respawn, shared with the bots on the map."""
    import map_links as H
    if not bot.permission.get('booty', True):
        return
    crowd = len(y.on_map.get(bot.game_map, ())) if y is not None else 1
    for kind, count in active_boxes(H.name(bot.game_map)):
        ratio = count * dt / max(60.0, sum(LOOT.BOXES[kind]['renew_sec']) / 2) / max(1.0, 0.3 * crowd)
        if bot.r.random() < ratio and can_open(bot, kind):
            open_box(bot, kind, bot.r)


# ------------------------------------------------------------------------------------------------------------ assembly
def _yeter(bot, parts):
    s = stock(bot)
    for p, n in parts.items():
        if p in CURRENCY:
            if bot.k[CURRENCY[p]] < n:
                return False
        elif p.startswith('equipment_'):
            if not any(p in v for v in bot.k['gear'].values() if isinstance(v, dict)) and bot.k['gear'].get('launcher') != p:
                return False
        elif s.get(p, 0) < n:
            return False
    return True


def _spend(bot, parts):
    s = stock(bot)
    for p, n in parts.items():
        if p in CURRENCY:
            bot.k[CURRENCY[p]] -= n
        elif p.startswith('equipment_'):
            if bot.k['gear'].get('launcher') == p:
                bot.k['gear']['launcher'] = None
        else:
            s[p] -= n
            if not s[p]:
                del s[p]


MATERIALS = [(k, tuple(p for p in r['parts'] if p not in CURRENCY)) for k, r in RECIPES.items()
           if any(p not in CURRENCY for p in r['parts']) and 'test' not in k]      # test recipes are closed to the player too      # money recipes are in technology.produce


def assembly(bot):
    """Makes the most valuable of the recipes whose materials it has (if the result is worth more than it spends; those that spend money are in
    technology.produce). Usage limits: USABLE_ONCE once. -> the result produced or None."""
    if not bot.permission.get('assembly', True):
        return None
    now = bot.hour()
    if now < bot.__dict__.get('_asm_t', 0):
        return None
    bot._asm_t = now + 600                               # the player checks Assembly now and then: once every 10 minutes
    s = stock(bot)
    if not any(k.startswith('resource_') for k in s):
        return None
    crafted = bot.k.setdefault('assembly', {})
    en, best_score = None, 0.0
    for key, need in MATERIALS:
        if not all(p in s or p.startswith('equipment_') for p in need):
            continue
        r = RECIPES[key]
        if r['usage'] == 'USABLE_ONCE' and crafted.get(key):
            continue
        if not _yeter(bot, r['parts']):
            continue
        earnings = sum(value(l, n) for l, n in r['result'].items())
        cost = sum(value(p, n) for p, n in r['parts'].items() if not p.startswith('resource_collectable'))
        if earnings - cost > best_score:
            en, best_score = key, earnings - cost
    if en is None:
        return None
    r = RECIPES[en]
    _spend(bot, r['parts'])
    for loot, n in r['result'].items():
        give(bot, loot, n)
    crafted[en] = crafted.get(en, 0) + 1
    bot.ist('assembly')
    return en
