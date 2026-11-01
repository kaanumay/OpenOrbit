"""The game as the bots know it: ships, lasers, generators, drones (prices from the shop's catalog, values from items.json),
the ship's power values, the difficulty and expected income of maps, the portal network.

Everything is generated from data: when a new ship, laser or alien is added (including through the World Editor) the bots recognize it
on their own. A bot's equipment is a plain dictionary (gear): {'ship': loot, 'laser': {loot: count}, 'kalkan': {loot: count}, 'speed': {loot: count},
'drone': {loot: count}, 'ammunition': loot}. outfit() places the items at hand into the slots in the best way.
"""
import functools, json, math, os
from collections import deque

import game_data as DATA
import paths as PTH
import map_links as H
import settings as SET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
NPC = DATA.load('npc.json')
COMBAT = NPC['combat']

# maps the bots roam: X-1..X-8, 4-1..4-5 (pirate maps need a key, gates and mode maps need a ticket)
MAPS = tuple(range(1, 30))
LASER_INTERVAL = COMBAT['laser_interval_sec']
NPC_INTERVAL = COMBAT['npc_attack_interval_sec']
SEARCH_SEC = 9.0             # searching for a target and approaching between two aliens (observed: 6-12 s on 1-x)
JUMP_SEC = 45.0           # flight from portal to portal + jump (average per map)
REPAIR_RATE = 0.012        # share of HP+shield regenerated per second outside combat (shield regeneration + repair robot, roughly)
AMMO = ('ammunition_laser_lcb-10', 'ammunition_laser_mcb-25', 'ammunition_laser_mcb-50')

_price = None


def prices():
    """lootId -> ('C' | 'U', price): the shop's standard catalog, including the World Editor's price and removal from sale."""
    global _price
    if _price is None:
        import shop as SHP
        p = PTH.template('responses.json') if 'responses.json' in PTH.TEMPLATES else os.path.join(HERE, 'data', 'responses.json')
        y = {}
        if p and os.path.exists(p):
            with open(p, encoding='utf8') as f:
                y = json.load(f)
        out = {i['lootId']: (i['currency'], i['price']) for c in SHP.catalog(y).values() for i in c}
        for loot, w in SHP.WORLD_SHOP.items():
            if w.get('on_sale') is False:
                out.pop(loot, None)
            elif w.get('price') is not None and loot in out:
                out[loot] = (w.get('currency') or out[loot][0], w['price'])
        for loot, v in ITEMS['drones'].items():
            out[loot] = ('C' if v['currency'] == 'credits' else 'U', v['prices'][0])
        _price = out
    return _price


def price(loot, owner=0):
    """Purchase price ('C' | 'U', amount) or None. Drones depend on which one it is (owner: the number of the same drone at hand)."""
    d = ITEMS['drones'].get(loot)
    if d:
        if d.get('single') and owner:
            return None
        return ('C' if d['currency'] == 'credits' else 'U'), d['prices'][min(owner, len(d['prices']) - 1)]
    return prices().get(loot)


def ships():
    """Base ships that can be bought (designs excluded) -> items.json values."""
    return {k: v for k, v in ITEMS['ships'].items() if 'base' not in v and price(k)}


def lasers():
    return {k: v['damage'] for k, v in ITEMS['lasers'].items() if price(k)}


def shield_generators():
    return {k: v for k, v in ITEMS['shield_generators'].items() if price(k)}


def speed_generators():
    return {k: v['speed'] for k, v in ITEMS['speed_generators'].items() if price(k)}


def new_gear():
    return {'ship': 'ship_phoenix', 'laser': {'equipment_weapon_laser_lf-1': 1}, 'kalkan': {}, 'speed': {}, 'drone': {},
            'ammunition': AMMO[0]}


# ------------------------------------------------------------------------------------------------------------ power
def outfit(gear, shield_share=0.6):
    """Placement of the items at hand into the slots -> {'laser': [damage...], 'kalkan': [(shield, absorption)...], 'speed': [speed...], ...}.
    Laser slots: ship + drones (Flax 1, Iris 2); generator slots are the ship's, shield_share of them go to the shield (by personality)."""
    g = ITEMS['ships'].get(gear['ship']) or ITEMS['ships']['ship_phoenix']
    drone_slots = sum(ITEMS['drones'].get(d, {}).get('slot', 1) * n for d, n in gear.get('drone', {}).items())
    lasers = sorted((ITEMS['lasers'][l]['damage'] for l, n in gear.get('laser', {}).items() for _ in range(n) if l in ITEMS['lasers']),
                reverse=True)[:g['laser'] + drone_slots]
    shields = sorted(((ITEMS['shield_generators'][k]['kalkan'], ITEMS['shield_generators'][k]['absorb'])
                 for k, n in gear.get('kalkan', {}).items() for _ in range(n) if k in ITEMS['shield_generators']), reverse=True)
    speeds = sorted((ITEMS['speed_generators'][k]['speed'] for k, n in gear.get('speed', {}).items() for _ in range(n)
                 if k in ITEMS['speed_generators']), reverse=True)
    slot = g['generators']
    nk = min(len(shields), max(int(round(slot * shield_share)), slot - len(speeds)))
    n_speed = min(len(speeds), slot - nk)
    return {'ship': g, 'laser': lasers, 'kalkan': shields[:nk], 'speed': speeds[:n_speed], 'laser_slots': g['laser'] + drone_slots, 'gen_slot': slot}


def drone_set(gear):
    """Team bonus if all drones share the same bonus design (Havoc, Hercules ...) (same rule as player_profile.design_mods), otherwise {}."""
    n = sum(gear.get('drone', {}).values())
    t = ((gear.get('drone_design') or {}).get('design') or [])[:n]
    return ITEMS['drone_designs'].get(t[0], {}).get('set_bonus', {}) if n and len(t) == n and t[0] and len(set(t)) == 1 else {}


def values(gear, shield_share=0.6):
    """The bot's combat values: dps (damage per second, against an alien), HP, shield, absorption, ehp (effective HP), speed, power score."""
    y = outfit(gear, shield_share)
    multiplier = ITEMS['laser_ammo'].get(gear.get('ammunition'), {}).get('multiplier', 1)
    damage = sum(y['laser']) * multiplier * 0.88 * COMBAT['laser_hit_chance']          # 0.88: the mean of the random roll (0.76-1.0)
    set_bonus = drone_set(gear)
    drone_slots = sum(ITEMS['drones'].get(d, {}).get('slot', 1) * n for d, n in gear.get('drone', {}).items())
    damage *= 1 + set_bonus.get('drone_laser', 0) * min(1.0, drone_slots / max(1, len(y['laser'])))        # Havoc: only to the drone lasers
    dps = damage / LASER_INTERVAL
    shield = sum(k for k, _ in y['kalkan'])
    absorb = (sum(k * e for k, e in y['kalkan']) / shield) if shield else 0.0
    hp = y['ship']['hp'] * (1 + set_bonus.get('can', 0))               # Hercules set: +20% HP
    ehp = hp + shield * 2.5 * min(1.0, absorb + 0.2)         # the shield absorbs most of the damage and refills between targets
    speed = y['ship']['base_speed'] + sum(y['speed'])
    return dict(dps=dps, can=hp, kalkan=shield, absorb=absorb, ehp=ehp, speed=speed, power=power_score(dps, ehp),
                laser=len(y['laser']), laser_slots=y['laser_slots'], gen=len(y['kalkan']) + len(y['speed']), gen_slot=y['gen_slot'])


def power_score(dps, ehp):
    """A single power number: the geometric mean of dps and effective HP (Phoenix + LF-1 ≈ 4, Goliath with LF-3, B02 and 8 Iris ≈ 100)."""
    return math.sqrt(max(dps, 0) * max(ehp, 0)) / 490.0


# ------------------------------------------------------------------------------------------------------------ maps
_npc_cache = {}
_map_npc_cache = {}


def npc_value(tip):
    """The alien's values for the bot (read-only; npc.json is loaded once on import, the result is cached)."""
    if tip in _npc_cache:
        return _npc_cache[tip]
    t = NPC['types'].get(tip)
    v = None if not t else dict(
        tip=tip, name=t['name'], ehp=t['hp'] + t['kalkan'], dps=t['damage'] * t.get('hit', COMBAT['npc_hit_chance'])
        / t.get('shot_interval_sec', NPC_INTERVAL), aggressive=bool(t.get('aggressive')), reward=t['reward'], speed=t['speed'],
        uid=t.get('npc_id', 0))
    _npc_cache[tip] = v
    return v


def map_npcs(map_id):
    """[(npc value, count)]: the permanent aliens of the map (npc.json maps; read-only, cached)."""
    if map_id in _map_npc_cache:
        return _map_npc_cache[map_id]
    out = []
    for r in (NPC['maps'].get(str(map_id)) or {}).get('npc', []):
        v = npc_value(r['tip'])
        if v and r.get('count', 0) > 0:
            out.append((v, r['count']))
    _map_npc_cache[map_id] = out
    return out


_map_cache = {}


def evaluate_map(map_id, dps, ehp, courage=0.5):
    """A ship of this power grinding aliens on a map -> {ep_per_hour, credits_per_hour, uridium_per_hour, honor_per_hour, deaths_per_hour (expected deaths
    per hour), targets [type], kills {type: kills per hour}, difficulty (0 easy .. 1+ deadly)}. courage (0-1): the most dangerous alien it
    finds worth killing (damage taken / effective HP limit). Per alien: kill time = effective HP / dps; damage taken = the alien's dps x time
    (always, since it is either aggressive or retaliates when hit); repair in between. Results are cached for (map, rounded power)."""
    key = (map_id, int(dps // 5), int(ehp // 5000), round(courage, 1))
    if key in _map_cache:
        return _map_cache[key]
    limit = 0.25 + 0.5 * courage
    total = dict(ep=0.0, credits=0.0, uridium=0.0, honor=0.0)
    duration = 0.0
    death = 0.0
    targets = []
    kills = {}
    heavy = 0.0
    for v, count in map_npcs(map_id):
        if dps <= 0:
            break
        t = v['ehp'] / dps
        claimed = v['dps'] * t
        ratio = claimed / max(ehp, 1)
        if v['aggressive']:
            heavy += count * min(2.0, ratio)
        if ratio > limit:
            continue
        targets.append(v['tip'])
        kind = t + SEARCH_SEC + claimed / max(ehp * REPAIR_RATE, 1)
        kills[v['tip']] = count
        for k in total:
            total[k] += v['reward'].get(k, 0) * count
        duration += kind * count
        death += count * max(0.0, ratio - 0.15) ** 2 * 0.15        # occasionally several aliens at once and bad luck
    difficulty = heavy / 40.0
    if duration <= 0:
        r = dict(ep_per_hour=0, credits_per_hour=0, uridium_per_hour=0, honor_per_hour=0, deaths_per_hour=1.0 + difficulty, targets=[], difficulty=difficulty + 1,
                 kills={})
    else:
        k = 3600.0 / duration
        r = dict(ep_per_hour=total['ep'] * k, credits_per_hour=total['credits'] * k, uridium_per_hour=total['uridium'] * k,
                 honor_per_hour=total['honor'] * k, deaths_per_hour=death * k / max(1, len(targets)) + difficulty * 0.4, targets=targets,
                 difficulty=difficulty, kills={t: n * k for t, n in kills.items()})
    if len(_map_cache) > 20000:
        _map_cache.clear()
    _map_cache[key] = r
    return r


_ENTRY = {}


def can_enter(map_id, company, level):
    k = (map_id, company, bool(SET.get('no_level_limit')))     # a new key if the panel's level restriction setting changes
    if k not in _ENTRY:
        _ENTRY[k] = H.level_required(map_id, company)
    return level >= _ENTRY[k]


def neighbors(map_id, company):
    """Maps reachable by portal (excluding paid / keyed portals)."""
    return [g['target'] for g in H.gates(map_id, company) if not g.get('fee') and g['target'] in MAPS
            and g.get('only_company') in (None, company)]


def route(source, target, company, level):
    """Shortest portal route [source, ..., target] (does not pass through maps that cannot be entered) or None."""
    r = _route(int(source), int(target), company, level, bool(SET.get('no_level_limit')))     # a new key if the setting changes (can enter)
    return list(r) if r is not None else None


@functools.lru_cache(maxsize=8192)
def _route(source, target, company, level, _unrestricted=False):
    if source == target:
        return (source,)
    previous = {source: None}
    q = deque([source])
    while q:
        m = q.popleft()
        for n in neighbors(m, company):
            if n in previous or not can_enter(n, company, level):
                continue
            previous[n] = m
            if n == target:
                out = [n]
                while previous[out[-1]] is not None:
                    out.append(previous[out[-1]])
                return tuple(out[::-1])
            q.append(n)
    return None


def ev(company):
    """The company's base map (X-1)."""
    return {1: 1, 2: 5, 3: 9}[company]


# ------------------------------------------------------------------------------------------------------------ cargo
CARGO_ORE = frozenset((0, 1, 2, 4, 5, 6, 7, 8, 28))       # ores that take up cargo space (player_profile.CARGO_ORES; Xenomit does not)


def sell_maps(company):
    """The company's own stations where ore is sold: X-1 and X-8 (in the game trading happens only at a station)."""
    return {1: (1, 20), 2: (5, 24), 3: (9, 28)}[company]


def ore_prices(honor, multiplier=1.0):
    """Refinery prices: base + honor/divisor, capped (same formula as world.ore_prices)."""
    out = {}
    for t, (base, divisor, cap) in ITEMS['ores']['prices'].items():
        v = min(cap, base + (int(max(0, honor) // divisor) if divisor else 0))
        out[int(t)] = int(round(v * multiplier))
    return out


def cargo_capacity(gear):
    from . import extras as EX
    return int(int((ITEMS['ships'].get(gear['ship']) or ITEMS['ships']['ship_phoenix']).get('cargo') or 100)
               * EX.cargo_multiplier(gear))                  # G3X-CRGO-X: double


def npc_cargo(tip, level=1, game_map=None):
    """The ores in an alien's cargo box {type: count}; they decrease at high level on the X-1 maps (npc.json x1_cargo)."""
    cargo = {int(k): int(v) for k, v in ((NPC['types'].get(str(tip)) or {}).get('cargo') or {}).items() if int(v) > 0}
    if game_map is not None and H.map_class(game_map) == 'X-1':
        import settings as SET
        if SET.get('x1_cargo'):
            f = next((k for l, k in reversed(COMBAT['x1_cargo']) if level >= l), 1)
            cargo = {t: int(v * f) for t, v in cargo.items() if int(v * f) > 0}
    return cargo


def pvp_map(map_id, company):
    """Is it a map where players of another company are met (everywhere except one's own X-1/X-2; 4-X and other companies' maps)."""
    c = H.company(map_id)
    return c != company or H.map_class(map_id) not in ('X-1', 'X-2')
