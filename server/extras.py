"""Extras and CPUs (data items.json "extras" <- belgeler/wiki/extras_cpu_tech.md; only those fitted in the active config take effect).

Passive effects (this module queries them, the relevant modules apply them):
  extra_slot       extra slot (SL-01..04 +2/+4/+6/+10; one slot CPU per config, that config's slot)                  shop.capacity
  cargo_multiplier cargo space multiplier (G3X-CRGO-X)                                                               shop.apply_stats
  rocket_cooldown  rocket cooldown multiplier (R0K-T01 0.5)                                                          world.rocket
  mine_cooldown    cooldown of mines and items made from mines (MIN-T01 -25%, MIN-T02 -50%)                         world (mines)
  auto_repair      when HP drops, the repair robot runs by itself (NC-RRB-X)                                         world.auto_tick
  auto_pickup      {type: laser|rocket|fuel, threshold, count}: buys when it falls below the threshold (ALB-X, RB-X, FB-X) world.auto_tick
  auto_lab         [part]: when the upgrade finishes, again with the same ore or (best) the best ore (NC-AWL/AWR/AWB/AGB)
  sell_anywhere    ore can be sold anywhere, count limit (HM-7, 100 sales)                                           world.at_trade
Active ones (from the shortcut bar; combat_items.py):
  jump             {maps | ban}: jump to the main map (JP-01 10, JP-02 20 uses); advanced_jump: AJP-01 to the map of choice
  cloak            cloak CPU (CL04K-XS 1, M 10, XL 50 uses)            aim            AIM-01/02 miss rate -25%/-50% (10 Xenomit)
  insta_shield     Insta-Shield (ISH-01)                               smart_bomb     Smart Bomb (SMB-01)
  auto_rocket      AROL-X: the selected rocket on a laser attack      auto_launcher  RL-LB1: the loaded launcher on a laser attack
Uses (right): in the profile (extra_uses), full when first fitted; added when bought (recharge).
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
E = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
X = E.get('extras', {})


def equipped(p, sid=None):
    """The lootIds of the extras in the active (or given) ship's active config; extras fitted to drones (CPUs) count too."""
    if sid is None or str(sid) == str(p.d['active_ship']):
        own, drones = list(p.d.get('equipment', {}).get('extra', [])), p.d.get('drone_equipment', [])
    else:
        own, drones = p.loadout(sid).get('extra', []), [(x, loots) for x, loots in p.drone_loadout(sid)]
    return own + [l for _, loots in drones for l in loots if l.startswith('equipment_extra_')]


def props(p, key, sid=None):
    """A property of the fitted extras: [(lootId, value)]."""
    return [(l, X[l][key]) for l in equipped(p, sid) if l in X and key in X[l]]


def has(p, key, sid=None):
    return bool(props(p, key, sid))


def owned(p, loot):
    """Whether the extra is in the inventory or fitted (those that need not be fitted: the HM-7 trade drone, appears in the shortcut bar once bought)."""
    return loot in p.d['items'].values() or loot in equipped(p)


def slot_bonus(p, sid=None, cid=None):
    """The extra slot of the slot CPU: that of the one fitted in one of the ship's configs (default: active ship, active config)."""
    return slot_bonus_of(equipped(p, sid) if cid is None else p.loadout(sid, cid).get('extra', []))


def slot_bonus_of(loots):
    """The bonus of the slot CPU (SL-01..04) among the extras (one is fitted per config)."""
    return max((X[l]['extra_slot'] for l in loots if 'extra_slot' in X.get(l, {})), default=0)


def cargo_factor(p):
    f = 1.0
    for l, v in props(p, 'cargo_multiplier'):
        f = max(f, v)
    return f


def rocket_factor(p):
    return min((v for l, v in props(p, 'rocket_cooldown')), default=1.0)


def mine_factor(p):
    return 1 + min((v for l, v in props(p, 'mine_cooldown')), default=0.0)


UNLIMITED = 10 ** 6


def unlimited(p, loot):
    """Whether the uses are unlimited: for HM-7, those who own Goliath's Amber, Jade or Sapphire design (wiki: old rule; client
    items_equipment_extra_hmd-07_hint_unlimited "You already have an unlimited trade drone")."""
    designs = X.get(loot, {}).get('unlimited_design')
    return bool(designs) and any(d in s.get('designs', []) for s in p.d['ships'].values() for d in designs)


def uses(p, loot):
    """Remaining uses of a limited-use extra (HM-7 sales, Jump CPU jumps, cloaking): in the profile, full when first fitted."""
    if unlimited(p, loot):
        return UNLIMITED
    st = p.d.setdefault('extra_uses', {})
    if loot not in st:
        st[loot] = X.get(loot, {}).get('right', 0)
    return st[loot]


def recharge(p, loot, n=1):
    """An extra that has uses was bought: n of its uses are added."""
    if 'right' not in X.get(loot, {}):
        return
    with p.lock:
        st = p.d.setdefault('extra_uses', {})
        st[loot] = st.get(loot, 0) + X[loot]['right'] * n
        p.dirty = True


def attached(p, loot):
    """The ammo the Auto-Buy CPU has selected in the hangar (HangarShipAutoBuyCpuAmmoRequest) or None."""
    return p.d.get('auto_buy_ammo', {}).get(loot)


def use(p, loot, n=1):
    if unlimited(p, loot):
        return UNLIMITED
    with p.lock:
        left = uses(p, loot) - n
        p.d['extra_uses'][loot] = max(0, left)
        p.dirty = True
    return max(0, left)
