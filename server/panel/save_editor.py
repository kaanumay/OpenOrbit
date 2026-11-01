"""Save editor (character editor; the panel runs it in a separate process so as not to load server modules into the panel's process).

The editor works on the save's draft (saves.py: <slot>/edit_base.json); equipping, unequipping, ship activation, design, config cleanup
and transfer go through the game's own hangar code (shop.Shop.handle: the same rules as the client's requests), giving items and ships goes through
the game's reward path (shop.reward). Counts (ammo, ore, resources, boosters), levels (pilot, drone, P.E.T., item upgrade)
change directly in the profile.

  python -I save_editor.py read <profile.json> [<original profile.json>]
      the editor's view; if an original profile is given, a summary of the differences from it
  python -I save_editor.py apply <profile.json> <operations JSON> [<original profile.json>]
      apply the operations in order, save -> view (operations: OPS)
  python -I save_editor.py info
      each item's hint lines (values, bonuses, ships, upgrade, sale; info())
  python -I save_editor.py catalog
      items that can be added: [lootId, category, ship slot, P.E.T. slot, can it be fitted to a drone]
Output: on the last line JSON {'ok': true, ...} or {'ok': false, 'error': '...', 'template': ..., 'arg': [...]} (like profile_tool.py).
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
sys.path.insert(0, SERVER)
sys.path.insert(0, HERE)
import profile_tool as PA        # noqa: E402


def _(s):
    """Marker for text to be translated: the panel builds the message in its own language (saves.run_tool, lang.py; test_panel_lang.py collects it)."""
    return s


COMPANIES = (1, 2, 3)
# the game's rejection reasons (BaseKey name or shop.REASONS key) -> the panel's message
REJECTS = {
    'error_can_not_equip_to_slot': _("This item can't go in this slot: the game's rules don't allow it (ship compatibility, slot type or config limit)."),
    'special_generic_hint': _("This config already has this extra."),
    'drone_slotCPUinUse': _("The slot CPU is in use: empty your extra slots first."),
    'pet_gear_requirement': _("The P.E.T.'s level is too low for this item."),
    'dse_ship_not_exist': _('Ship not found.'),
    'pet_already': _("This item is already equipped on the P.E.T."),
    'pet_full': _("The P.E.T. has no free slot for this item."),
    'other_ship': _('This item is equipped on another ship: unequip it there first.'),
    'same_cannon': _('The ship already has a cannon of this type.'),
    'qfc_ship': _('This Quantum Fluid Core is bound to another ship.'),
    'same_qfc': _('The ship already has a Quantum Fluid Core of this type.'),
    'single_slot_cpu': _("Only one Slot CPU can be equipped per config."),
    'same_module': _('Only one module of each type (damage, HP, shield, special) can be equipped on a ship.'),
}
HOME_MAP = PA.HOME_MAP
AMMO = (('ammunition_laser_', 'laser'), ('ammunition_rocketlauncher_', 'rocket_launcher'), ('ammunition_rocket_', 'rocket'),
           ('ammunition_mine_', 'mine'), ('ammunition_specialammo_', 'special'), ('ammunition_', 'other'))
# catalog categories: (id, the client's item classes, lootId prefixes); the order is the order in the selection window
CATEGORIES = (
    ('ship', ('ShipType',), ()), ('design', ('ShipDesignType',), ()), ('laser', ('LaserType',), ('equipment_weapon_laser_',)),
    ('rocket_launcher', ('HellstormLauncherType',), ('equipment_weapon_rocketlauncher_',)),
    ('generator', ('ShieldType', 'EngineType'), ('equipment_generator_',)),
    ('ekstra', ('CPUType', 'ExtraType', 'HardwareType', 'RobotType', 'TechType'), ('equipment_extra_',)),
    ('module', ('ShipUpgradeType', 'QuantumFluidCoreType'), ('equipment_shipupgrade_', 'equipment_core_')),
    ('heavy', ('CannonType', 'CannonShieldType', 'DriveType', 'LensType'), ('equipment_cannon', 'equipment_lens_', 'equipment_drive')),
    ('drone', ('DroneType', 'DroneFormationType', 'DroneDesignType', 'DroneCustomizationType'), ('drone_',)),
    ('pet', ('PetGearType', 'AIProtocolType', 'PetCustomizationType', 'PetType'), ('equipment_petgear_', 'equipment_aiprotocol_', 'pet_')),
    ('ammunition', ('AmmunitionType',), ('ammunition_',)), ('booster', (), ('booster_',)),
    ('source', ('OreType', 'ItemType', 'SynthesisResourceType'), ('resource_',)), ('package', (), ('package_', 'deal_')),
)


def _ist():
    return PA._load('client_items.json').get('items') or {}


def category(loot, ist=None):
    ist = _ist() if ist is None else ist
    klass = (ist.get(loot) or {}).get('class_name')
    if loot.startswith('booster_'):                    # ExtraType in the client
        return 'booster'
    for k, classes, prefixes in CATEGORIES:
        if klass in classes or loot.startswith(prefixes):
            return k
    return 'other'


def catalog():
    import shop as SHP
    import pet as PETM
    ist = _ist()
    return {'items': sorted([l, category(l, ist), SHP.slot_of(l), PETM.slot_for(l), bool(SHP.drone_ok(l) or l in SHP.DESIGNS)]
                              for l in PA.known_loots()),
            'categories': [k for k, _s, _o in CATEGORIES] + ['other']}


# ------------------------------------------------------------------ item info (the panel's hint)
# the server's bonus key -> the client's attribute name (metinler_<lang>.json "n": the panel writes in that language)
ATTRIBUTE_NAME = {'laser': 'dmg_laser', 'rocket': 'dmg_rockets', 'can': 'hitpoints', 'kalkan': 'shield', 'speed': 'speed', 'ep': 'experience',
               'honor': 'honour', 'evasion': 'evasion', 'npc': 'dmg_npc', 'pvp': 'dmg_pvp', 'laser_hit_chance': 'hitchance_laser',
               'rocket_hit_chance': 'hitchance_rocket', 'shield_penetration': 'shield_penetration'}
BOOSTER_NAME = {'DAMAGE': 'damage', 'HITPOINTS': 'hitpoints', 'SHIELD': 'shield', 'EXPERIENCE_POINTS': 'experience', 'HONOUR_POINTS': 'honour'}


def info():
    """Each item's hint lines (from the client's and the server's item data). lootId -> {
      dg: [[label, value, format]]   format: n number, p percent (fraction), x times, sn seconds, dk minutes, sa hours; the label is the panel's text
      m: [[attribute, fraction]]     bonus with the client's attribute name (module, design, ship, formation, booster)
      gm: [ship lootId]              ships the module appears in (priority ships when undecided)
      up: [percent, max, type]       upgrade (Assembly): bonus per level
      sat: credits                   sale value
      yv: {slot: count}              slots of the ship and the drone
      ph: {placeholder: value}       %HOURS%, %BOOSTERVALUE% ... in the description
      tk: [SHIP, PET, DRONE]         places it can be fitted}"""
    import shop as SHP
    import ship_module as GM
    import particle as PC
    import qfc as QF
    import pet as PETM
    import upgrades as UPG
    import booster as BOOSTER
    E, ist, out = SHP.ITEMS, _ist(), {}

    def row(l):
        return out.setdefault(l, {})

    def stats(l, tag, v, style='n'):
        if v is not None:
            row(l).setdefault('stats', []).append([tag, v, style])

    def bonus(l, b):
        for k, v in (b or {}).items():
            if k in ATTRIBUTE_NAME and v:
                row(l).setdefault('m', []).append([ATTRIBUTE_NAME[k], v])
    for l, v in ist.items():
        if l.startswith(('shipId_', 'paymentItem_')):
            continue
        if v.get('selling'):
            row(l)['sell'] = int(v['selling'])
        if v.get('equippable'):
            row(l)['tk'] = v['equippable']
        up = [u for u in v.get('upgrade', []) if u.get('percent')]
        if up and UPG.max_level(l):
            row(l)['up'] = [[u['percent'] / 100.0, UPG.max_level(l), u['type']] for u in up]
        if v.get('class_name') in ('ShipType', 'ShipDesignType'):
            gr = E['ships'].get(l) or E['ships'].get(l.split('_design_')[0]) or {}
            stats(l, 'can', v.get('can') or gr.get('hp'))
            stats(l, 'speed', v.get('speed') or gr.get('base_speed'))
            stats(l, 'cargo', v.get('cargo') or gr.get('cargo'))
            row(l)['slot_info'] = {k: n for k, n in (v.get('slots') or {}).items() if n}
            bonus(l, gr.get('bonus'))
            bonus(l, (E.get('designs', {}).get(l) or {}).get('bonus'))
        if l in E['drones']:
            row(l)['slot_info'] = {'default': E['drones'][l]['slot']}
    for l, v in E['lasers'].items():
        stats(l, 'damage', v.get('damage'))
        stats(l, 'pvp_damage', v.get('pvp_damage'))
    for l, v in E['shield_generators'].items():
        stats(l, 'kalkan', v.get('kalkan'))
        stats(l, 'absorb', v.get('absorb'), 'p')
    for l, v in E['speed_generators'].items():
        stats(l, 'speed', v.get('speed'))
    for l, v in E['laser_ammo'].items():
        stats(l, 'laser_multiplier', v.get('multiplier'), 'x')
    for l, v in E['rockets'].items():
        if isinstance(v, dict):
            stats(l, 'damage', v.get('damage'))
            stats(l, 'hit', v.get('hit'), 'p')
    for l, v in E['repair_robots'].items():
        stats(l, 'full_repair', v.get('full_repair_sec'), 'sn')
        stats(l, 'hp_per_minute', v.get('hp_per_minute'))
    for l, v in E['extras'].items():
        if not isinstance(v, dict):
            continue
        stats(l, 'right', v.get('right'))
        stats(l, 'extra_slot', v.get('extra_slot'))
        stats(l, 'cooldown', v.get('cooldown_sec'), 'sn')
        stats(l, 'cargo_multiplier', v.get('cargo_multiplier'), 'x')
    for l, v in E['formations'].items():
        bonus(l, {k: x for k, x in v.items() if k != 'id'})
    for l, v in E['drone_designs'].items():
        if isinstance(v, dict):
            bonus(l, v.get('set_bonus'))
            stats(l, 'drone_shield', v.get('drone_shield'), 'p')
            stats(l, 'drone_laser', (v.get('set_bonus') or {}).get('drone_laser'), 'p')
    hour = E['boosters'].get('hour', {})
    for l in list(E['boosters']['kinds']) + list(BOOSTER.ALIAS):
        effect = BOOSTER.B['kinds'].get(l) or {}
        for k, x in effect.items():
            if k in BOOSTER_NAME:
                row(l).setdefault('m', []).append([BOOSTER_NAME[k], x / 100.0])
            else:
                stats(l, 'booster_' + k.lower(), x / 100.0, 'p')
        h = hour.get(l) or BOOSTER.B['sure_sn'] / 3600          # duration of a shop booster (booster.add)
        stats(l, 'sure', h, 'sa')
        if effect:
            row(l)['ph'] = {'HOURS': '%g' % h, 'BOOSTERVALUE': next(iter(effect.values()))}
    for l, v in GM.M.items():
        if 'unstable' in v:
            unstable = v['unstable']
            row(l)['gm'] = unstable.get('preference', [])
            stats(l, 'en_az', unstable.get('en_az'), 'p')
            a = unstable['interval']
            stats(l, 'value_range', '%d-%d%%' % tuple(a['caps']) + (' / %d-%d%%' % tuple(a['lowercase']) if a.get('lowercase') else ''), 't')
            stats(l, 'reroll', unstable['restabilize']['right'])
        else:
            row(l)['gm'] = v.get('ships', [])
            bonus(l, v.get('effects'))
    for l, v in PC.CANNONS.items():
        stats(l, 'base_damage', v.get('base'))
        stats(l, 'element', v.get('element'), 'e')
        stats(l, 'extra_attribute', v.get('extra'))
        stats(l, 'reroll', PC.rerolls(l))
    for l, v in PC.SHIELDS.items():
        stats(l, 'savunma', v.get('savunma'))
        stats(l, 'element', v.get('element'), 'e')
        stats(l, 'extra_attribute', v.get('extra'))
        stats(l, 'reroll', PC.rerolls(l))
    for l, v in PC.DRIVES.items():
        stats(l, 'damage', v.get('damage'))
        stats(l, 'shot', v.get('shot'))
    for l, v in PC.LENSES.items():
        stats(l, 'savunma', v.get('savunma'))
    for l, v in QF.TYPES.items():
        stats(l, 'quality', v.get('quality'))
        stats(l, 'value_range', '%g-%g%%' % tuple(v['interval']), 't')
        stats(l, 'max_level', QF.MAX_LV)
    for l, v in PETM.GEARS.items():
        for k, label in (('range', 'range'), ('sure_sn', 'sure_sn'), ('cooldown_sec', 'cooldown')):
            if isinstance(v.get(k), list):
                stats(l, label, ' / '.join(str(x) for x in v[k]), 't')
    for l, v in PETM.PROTOCOLS.items():
        for k, x in v.items():
            if isinstance(x, list) and k != 'price' and all(isinstance(y, (int, float)) for y in x):
                stats(l, 'level_bonus', ' / '.join('%g%%' % (y * 100) for y in x), 't')
                row(l)['ph'] = {'amount': '%g' % (x[0] * 100)}
    return {'items': out}


# ------------------------------------------------------------------ profile and shop
def open_save(path):
    """The profile and the game's shop (hangar rules, reward path; like profile_tool.give)."""
    import galaxy_gates as KAPI
    import new_systems as NS
    from player_profile import Profile
    from shop import Shop
    notes = []
    pr = Profile(PA._load('login.json').get('seed'), path)
    m = Shop(pr, PA._load('responses.json'), notes.append)
    m.gates = KAPI.Gates(pr, notes.append)
    m.new_ = NS.NewSystems(pr, m, notes.append)
    return pr, m


def levels():
    return PA._load('levels.json').get('levels') or [[1, 0]]


def level_of(ep):
    lv = 1
    for level, need in levels():
        if ep >= need:
            lv = level
    return lv


def _item(p, i):
    """Short record of a fitted or inventory item: id, lootId, P.E.T. level (gear with a level, and protocol), upgrade level."""
    import pet as PETM
    l = p.d['items'].get(str(i))
    if not l:
        return None
    out = {'id': int(i), 'lootId': l}
    up = p.d.get('upgrade_level', {}).get(str(i))
    if PETM.has_levels(l):
        out['level'] = p.item_level(i)
    if up:
        out['upgrade'] = int(up)
    r = rng_record(p, i, l)
    if r:
        out['rng'] = r
    return out


# ------------------------------------------------------------------ items with random attributes
def rng_kind(l):
    """An item's random attribute type: module (unstable module), pc (particle cannon, breaker, driver, lens), qfc or None."""
    import ship_module as GM
    import particle as PC
    import qfc as QF
    return 'module' if GM.unstable(l) else 'pc' if PC.is_item(l) else 'qfc' if l in QF.TYPES else None


def rng_pool(l):
    """Options of the edit window: attribute names, unit (fraction or percent), value limit, uses limit, star limit."""
    import ship_module as GM
    import particle as PC
    import qfc as QF
    t = rng_kind(l)
    if t == 'module':
        a = GM.M[l]['unstable']['interval']
        return {'attribute': list(GM.SECONDARY), 'unit': 'fraction', 'max_attributes': 3, 'right': GM.restab(l)['right'],
                'interval': [a['caps'][0], (a.get('lowercase') or a['caps'])[1]], 'preference': GM.M[l]['unstable'].get('preference', [])}
    if t == 'pc':
        if l in PC.DRIVES or l in PC.LENSES:
            pool = {k: v for k, v in PC.D['attributes']['drive'].items() if not k.startswith('_')}
            return {'attribute': sorted(pool), 'unit': 'percent', 'max_attributes': len(PC.D['lock']['levels']), 'right': 0,
                    'interval': [min(v[0] for v in pool.values()), max(v[1] for v in pool.values())]}
        pool, tier = PC.pool(l), PC.tier(l)
        return {'attribute': sorted(pool), 'unit': 'percent', 'max_attributes': len(pool), 'right': PC.rerolls(l),
                'interval': [min(v[tier][0] for v in pool.values()), max(v[tier][1] for v in pool.values())],
                'star': len(PC.C['star']) - 1 if l in PC.CANNONS else 0}
    if t == 'qfc':
        k = QF.kind(l)
        (lo, hi), _, top = QF.ranges(l)
        return {'attribute': sorted(set(QF.D['initial_attributes'][k]) | set(QF.D['extra_attribute'][k])), 'unit': 'percent', 'interval': [lo, round(top, 2)],
                'max_attributes': QF.D['max_attributes'], 'max_level': QF.MAX_LV}
    return None


def rng_record(p, i, l):
    """An instance's random attributes (if not drawn yet only the type: drawn when edited)."""
    t = rng_kind(l)
    if not t:
        return None
    key = {'module': 'unstable', 'pc': 'particle', 'qfc': 'qfc'}[t]
    rec = p.d.get(key, {}).get(str(i))
    out = {'type': t}
    if rec:
        out.update(attribute=rec.get('attribute') or rec.get('attributes') or [], right=rec.get('right'), ships=rec.get('ships'),
                   ship=rec.get('ship'), level=rec.get('level'), star=rec.get('star'))
    return {k: v for k, v in out.items() if v is not None}


def stats(pr):
    """Statistics tab (read-only; player request 2026-10-30): the parts of the rank points, alien and player kills, deaths,
    gates (completion and times: galaxy_gates.record_duration), the best of the modes."""
    import ranks as RT
    import galaxy_gates as GT
    c = RT.counters(pr)
    npc = sorted(([RT.R['npc_points'].get(k, {}).get('name', '#' + k).strip(), int(n), RT.R['npc_points'].get(k, {}).get('points', 0)]
                  for k, n in c['npc'].items() if n), key=lambda x: -x[1])
    player = sorted(([RT.R['ship_points'].get(k, {}).get('name', k.replace('ship_', '')), int(n)] for k, n in c['player'].items() if n),
                    key=lambda x: -x[1])
    roster_row = (pr.d.get('kapilar') or {}).get('kapilar') or {}
    duration = pr.d.get('gate_times') or {}
    gates = [{'anahtar': k, 'name': GT.KAPI[k]['name'], 'done': int((roster_row.get(k) or {}).get('done', 0)), **(duration.get(k) or {})}
               for k in GT.KAPI if (roster_row.get(k) or {}).get('done') or k in duration]
    pve = pr.d.get('pve') or {}
    return {'points': RT.breakdown(pr), 'npc': npc, 'player': player,
            'death': {'enemy': c['death_by_enemy'], 'radiation': c['death_by_radiation'], 'other': c['death_other']},
            'quest': c['quest'], 'friendly': c['friendly'], 'kapilar': gates,
            'modes': {'ebl': int((pve.get('ebl') or {}).get('best', 0)), 'labyrinth': int((pr.d.get('labyrinth') or {}).get('hunts', 0)),
                       'mimesis': int(max((pr.d.get('mimesis') or {}).get('trips') or [0]))},
            'play_sec': int(pr.d.get('play_sec') or 0)}


def appearance(pr, m, original=None):
    import shop as SHP
    import pet as PETM
    import upgrades as UPG
    import map_links as H
    p, pl = pr, pr.d['pilot']
    lv_tab = levels()
    lv = pl.get('level', 1)
    next_ = next((need for l, need in lv_tab if l == lv + 1), None)
    base = next((need for l, need in lv_tab if l == lv), 0)
    places = p.item_places()
    max_upgrade = {}

    def maximum(l):
        if l not in max_upgrade:
            max_upgrade[l] = UPG.max_level(l)
        return max_upgrade[l]

    ships = []
    for sid, g in p.d['ships'].items():
        slots = [y for _p, y in SHP.SLOTS if m.capacity(y, sid) > 0]
        configs, drones, pet = {}, {}, {}
        for cid in sorted(g['configs']):
            cfg = p.config(cid, sid)
            configs[cid] = {y: {'capacity': m.capacity(y, sid, cid), 'items': [e for e in (_item(p, i) for i in cfg.get(y, [])) if e]}
                              for y in slots}
            dcfg = p.drone_config(cid, sid)
            drones[cid] = {str(x['uid']): {'items': [e for e in (_item(p, i) for i in dcfg.get(str(x['uid']), [])) if e],
                                               'design': _item(p, p.drone_design_id(x, 'design', cid, sid)),
                                               'appearance': _item(p, p.drone_design_id(x, 'visual', cid, sid))}
                            for x in p.d['drones']}
            if m.pet.owned:
                pc = m.pet.config(cid, sid)
                pet[cid] = {y: {'capacity': m.pet.open_slots(y), 'items': [e for e in (_item(p, i) for i in pc.get(y, [])) if e]}
                            for y in PETM.ALL_SLOTS}
        row = p.ship_row(sid)
        st = m.stats(sid)
        damage = sum(SHP.ITEMS['lasers'].get(l, {}).get('damage', 0) for l in p.loadout(sid).get('laser', []))
        ships.append({'id': sid, 'lootId': g['lootId'], 'design': g.get('design'), 'appearance': p.ship_look(sid), 'active': sid == p.d['active_ship'],
                        'favorite': bool(g.get('favorite')), 'active_config': str(g['active_config']), 'slots': slots, 'configs': configs,
                        'drones': drones, 'pet': pet or None, 'designs': m.designs(sid),
                        'position': g.get('position'), 'registered': bool(g.get('saved_config')),
                        'value': {'can': st.get('hp_max') or row.get('hp'), 'kalkan': st.get('shield_max'), 'speed': st.get('display'),
                                  'cargo': row.get('cargo'), 'damage': damage, 'laser': st.get('lasers')}})
    ships.sort(key=lambda x: (not x['active'], not x['favorite'], int(x['id'])))

    def targets(l):
        h = (['ship'] if SHP.slot_of(l) else []) + (['drone'] if SHP.drone_ok(l) or l in SHP.DESIGNS else [])
        return h + (['pet'] if PETM.slot_for(l) else [])
    inventory = []
    for i, l in p.d['items'].items():
        if l.startswith(('drone_', 'ship_')):
            continue
        place = places.get(int(i))                       # equipped items stay listed with their ship and configs (other config can use them)
        if place and not targets(l):
            continue
        e = _item(p, i)
        e.update(targets=targets(l), slot=SHP.slot_of(l) or PETM.slot_for(l) or ('design' if l in SHP.DESIGNS else 'other'),
                 pet_yuva=PETM.slot_for(l), heat=bool(PETM.heat_slot_ok(l)), maximum=maximum(l),
                 ship=place[0] if place else None, configs=sorted(place[1]) if place else [])
        inventory.append(e)
    for g in ships:                                  # upgrade limit of the fitted items (level window)
        for c in list(g['configs'].values()) + [d for per in g['drones'].values() for d in per.values()] + list((g['pet'] or {}).values()):
            for e in c['items'] if 'items' in c else []:
                e['maximum'] = maximum(e['lootId'])
    drone_list = []
    for x in p.d['drones']:
        info = SHP.DRONES.get(x['lootId'], {})
        drone_list.append({'id': x['uid'], 'lootId': x['lootId'], 'level': x.get('level', 1), 'points': x.get('points', 0),
                   'upgrade': int(x.get('upgrade', 0)), 'max_upgrade': UPG.max_level(x['lootId']) or 16,
                   'capacity': info.get('slot', 1), 'single': bool(info.get('single'))})
    petd = m.pet.d if m.pet.owned else None
    pet = None
    if petd:
        pet = {'name': petd.get('name'), 'level': petd.get('level', 0), 'ep': petd.get('ep', 0), 'fuel': int(petd.get('fuel', 0)),
               'max_fuel': PETM.PET['max_fuel'], 'max_level': len(PETM.PET['levels']) - 1, 'destroyed': bool(petd.get('destroyed')),
               'slot': {y: m.pet.open_slots(y) for y in PETM.SLOTS}, 'max_slots': dict(PETM.PET['max_slots']),
               'heat': m.pet.heat_lv()}
    ammo = [[l, int(n), next((t for pre, t in AMMO if l.startswith(pre)), 'other')] for l, n in sorted(p.d.get('ammunition', {}).items())]
    minerals = {m_['oreType']['typeValue']: m_['count'] for m_ in p.d.get('ores', [])}
    ores = [[int(t), loot, int(minerals.get(int(t), 0))] for t, loot in sorted(SHP.ITEMS['ores']['kinds'].items(), key=lambda kv: int(kv[0]))]
    now = time.time()
    boosters = [[l, int(max(0, (b.get('end_time') or 0) - now) + (b.get('remaining') or 0))] for l, b in sorted(p.d.get('boosters', {}).items())]
    k = p.d.get('position', {})
    quests = p.d.get('quests', {})
    out = {
        'pilot': {'name': pl.get('userName'), 'company': pl.get('factionId'), 'level': lv, 'ep': pl.get('ep', 0), 'level_base': base,
                  'next_level': next_, 'max_level': lv_tab[-1][0], 'honor': pl.get('honourPoints', 0), 'credits': pl.get('credits', 0),
                  'uridium': pl.get('uridium', 0), 'premium': bool(pl.get('premium')), 'clan': pl.get('clanTag') or '',
                  'rank': (p.d.get('rank') or {}).get('rank'), 'bank': p.d.get('bank', 0), 'play_sec': int(p.d.get('play_sec') or 0),
                  'created': p.d.get('created'), 'skill_points': (p.d.get('skills') or {}).get('points', 0)},
        'state': {'can': int(p.d['ship'].get('hitPoints', 0)), 'max_hp': p.d['ship'].get('hitMax', 0),
                  'kalkan': int(p.d['ship'].get('shield', 0)), 'shield_max': p.d['ship'].get('shieldMax', 0),
                  'map': k.get('mapId'), 'map_name': H.name(k.get('mapId', 0)), 'main_map': H.name(HOME_MAP.get(pl.get('factionId'), 5)),
                  'cargo': p.cargo_used(), 'cargo_max': p.d['ship'].get('cargoSpaceMax', 0)},
        'ships': ships, 'active_ship': p.d['active_ship'], 'drones': drone_list, 'max_drones': SHP.ITEMS['max_drones'],
        'drone_levels': [x['points'] for x in SHP.LEVELS], 'pet': pet, 'pet_slots': list(PETM.ALL_SLOTS),
        'inventory': inventory, 'ammunition': ammo, 'ores': ores,
        'sources': [[l, int(n)] for l, n in sorted(p.d.get('other_items', {}).items()) if isinstance(n, (int, float))],
        'boosters': boosters,
        'quests': {'active': len(quests.get('active', {})), 'done': len(quests.get('done', []))},
        # CPUs that work with uses (Jump CPU, Cloak ...): lootId -> [remaining, uses of one refill]; uses per lootId (extras.py)
        'rights': {l: [int(p.d.get('extra_uses', {}).get(l, SHP.EX.X[l]['right'])), SHP.EX.X[l]['right']]
                   for l in sorted(set(p.d['items'].values())) if 'right' in SHP.EX.X.get(l, {})},
        'pools': {l: rng_pool(l) for l in sorted(set(p.d['items'].values())) if rng_kind(l)},
        'all_ships': sorted(SHP.ITEMS['ships']),
        'stats': stats(p),
    }
    if original:
        out['diff'] = diff(original, p.d)
    return out


# ------------------------------------------------------------------ difference summary (draft vs. original save)
def _layout(d):
    """Where the fitted items are: a set of (ship, config, section, item)."""
    out = set()
    for sid, s in d.get('ships', {}).items():
        for key in ('configs', 'drone_config', 'pet_config'):
            for cid, cfg in s.get(key, {}).items():
                for slot, ids in cfg.items():
                    out |= {(sid, cid, key, slot, i) for i in ids}
        for cid, cfg in s.get('drone_design', {}).items():
            for did, per in cfg.items():
                out |= {(sid, cid, 'design', did, i) for i in per.values() if i}
    return out


def diff(a, b):
    """What changed from the original save (a) to the draft (b): fields [name, old, new], added/removed items (lootId -> count), count differences
    [lootId, old, new], equipment (number of items whose place changed), ships, drones."""
    pa, pb = a.get('pilot', {}), b.get('pilot', {})
    fields = [[k, pa.get(f), pb.get(f)] for k, f in (('name', 'userName'), ('company', 'factionId'), ('level', 'level'), ('ep', 'ep'),
                                                     ('credits', 'credits'), ('uridium', 'uridium'), ('honor', 'honourPoints'),
                                                     ('premium', 'premium')) if pa.get(f) != pb.get(f)]
    if a.get('active_ship') != b.get('active_ship'):
        fields.append(['active_ship', a['ships'].get(a.get('active_ship'), {}).get('lootId'),
                        b['ships'].get(b.get('active_ship'), {}).get('lootId')])
    if a.get('position', {}).get('mapId') != b.get('position', {}).get('mapId'):
        import map_links as H
        fields.append(['map', H.name(a.get('position', {}).get('mapId', 0)), H.name(b.get('position', {}).get('mapId', 0))])
    if int(a.get('ship', {}).get('hitPoints', 0)) != int(b.get('ship', {}).get('hitPoints', 0)):
        fields.append(['can', int(a['ship'].get('hitPoints', 0)), int(b['ship'].get('hitPoints', 0))])
    say = lambda d: {l: sum(1 for x in d.values() if x == l) for l in set(d.values())}
    items_a, items_b = say(a.get('items', {})), say(b.get('items', {}))
    ga = say({k: s['lootId'] for k, s in a.get('ships', {}).items()})
    gb = say({k: s['lootId'] for k, s in b.get('ships', {}).items()})
    da = say({str(x['uid']): x['lootId'] for x in a.get('drones', [])})
    db = say({str(x['uid']): x['lootId'] for x in b.get('drones', [])})
    added, leaving = {}, {}
    for x, y in ((items_a, items_b), (ga, gb), (da, db)):
        for l in set(x) | set(y):
            n = y.get(l, 0) - x.get(l, 0)
            if n > 0:
                added[l] = added.get(l, 0) + n
            elif n < 0:
                leaving[l] = leaving.get(l, 0) - n
    counts = []
    for key in ('ammunition', 'other_items'):
        counts_a, counts_b = a.get(key, {}), b.get(key, {})
        counts += [[l, int(counts_a.get(l, 0)), int(counts_b.get(l, 0))] for l in sorted(set(counts_a) | set(counts_b))
                    if isinstance(counts_a.get(l, 0), (int, float)) and isinstance(counts_b.get(l, 0), (int, float)) and int(counts_a.get(l, 0)) != int(counts_b.get(l, 0))]
    import shop as SHP
    ma = {m['oreType']['typeValue']: m['count'] for m in a.get('ores', [])}
    mb = {m['oreType']['typeValue']: m['count'] for m in b.get('ores', [])}
    counts += [[SHP.ORES.get(t, str(t)), int(ma.get(t, 0)), int(mb.get(t, 0))] for t in sorted(set(ma) | set(mb)) if ma.get(t, 0) != mb.get(t, 0)]
    ba, bb = a.get('boosters', {}), b.get('boosters', {})
    boost = sorted(l for l in set(ba) | set(bb) if ba.get(l) != bb.get(l))
    level = []
    counts_a = {x['uid']: x for x in a.get('drones', [])}
    for x in b.get('drones', []):
        y = counts_a.get(x['uid'])
        if y and (y.get('level'), y.get('upgrade', 0)) != (x.get('level'), x.get('upgrade', 0)):
            level.append(x['lootId'])
    upgrades_a, upgrades_b = a.get('upgrade_level', {}), b.get('upgrade_level', {})
    level += [b['items'][i] for i in set(upgrades_a) | set(upgrades_b) if upgrades_a.get(i, 0) != upgrades_b.get(i, 0) and i in b.get('items', {})]
    for key in ('unstable', 'particle', 'qfc'):                    # random attributes (edit window)
        ra, rb = a.get(key, {}), b.get(key, {})
        level += [b['items'][i] for i in rb if ra.get(i) and ra[i] != rb[i] and i in b.get('items', {})]
    charges_a, hb = a.get('extra_uses', {}), b.get('extra_uses', {})
    counts += [[l, int(charges_a.get(l, 0)), int(hb[l])] for l in sorted(hb) if charges_a.get(l) != hb[l]]
    pet_of = lambda d:{k: (d.get('pet') or {}).get(k) for k in ('name', 'level', 'ep', 'fuel', 'destroyed', 'slot')}
    if pet_of(a) != pet_of(b):
        level.append('pet')
    layout_a, layout_b = _layout(a), _layout(b)
    hardware = len({t[-1] for t in layout_a ^ layout_b})
    return {'fields': fields, 'added': added, 'leaving': leaving, 'counts': counts, 'boosters': boost, 'levels': level,
            'hardware': hardware,
            'number': len(fields) + len(added) + len(leaving) + len(counts) + len(boost) + len(level) + (1 if hardware else 0)}


# ------------------------------------------------------------------ operations
def _int(v, lo, hi):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError, OverflowError):
        raise ValueError('A number was expected: %s', str(v))


def _result(msgs, name):
    """Success or rejection reason (BaseKey name) from the game's response command."""
    import shop as SHP
    cmd = next((x[1] for x in msgs or [] if isinstance(x, tuple) and x[0] == name), None) or {}
    ok = (cmd.get('resultId') if 'resultId' in cmd else cmd.get('result')) == 1
    if not ok:
        e = cmd.get('errorMessage') or cmd.get('description') or {}
        if e.get('type') == 1:                         # raw text: shop.REASONS (the client has no language here: it's English)
            key = next((k for k, (en, _tr) in SHP.REASONS.items() if en == e.get('stringBasekey')), e.get('stringBasekey'))
        else:
            key = {v: k for k, v in SHP.BASEKEY.items()}.get(e.get('enumBaseKey'))
        if key in REJECTS:
            raise ValueError(REJECTS[key])
        raise ValueError("The game didn't allow this: %s", key or '?')


def op_pilot(pr, m, o):
    pl = pr.d['pilot']
    if 'name' in o:
        import re
        name = str(o['name']).strip()
        if not re.fullmatch(r'[\w\-\.\[\]\(\) ]{3,20}', name, re.UNICODE):
            raise ValueError('The pilot name must be 3-20 characters.')
        pl['userName'] = name
    for key, field, lo, hi in (('credits', 'credits', 0, 10 ** 12), ('uridium', 'uridium', 0, 10 ** 12),
                               ('honor', 'honourPoints', -10 ** 12, 10 ** 12)):
        if key in o:
            pl[field] = _int(o[key], lo, hi)
    if 'level' in o:                                  # level: EP is that level's threshold (the game also computes the level from EP)
        pl['level'], pl['ep'] = PA.level_ep(_int(o['level'], 1, 10 ** 3))
    if 'ep' in o:
        pl['ep'] = _int(o['ep'], 0, 2 ** 62)
        pl['level'] = level_of(pl['ep'])
    if 'premium' in o:
        pl['premium'] = bool(o['premium'])
    if 'company' in o and int(o['company']) != pl.get('factionId'):
        f = int(o['company'])
        if f not in COMPANIES:
            raise ValueError('Choose a company (MMO, EIC or VRU).')
        pl['factionId'] = f
        home_base(pr)                                     # should not stay on the other company's map
    pr.dirty = True


def home_base(pr):
    mid = HOME_MAP.get(pr.d['pilot'].get('factionId'), 5)
    pos = PA.station_pos(mid)
    if not pos:
        raise ValueError("The home station's position was not found.")
    pr.d['position'] = {'mapId': mid, 'x': pos[0], 'y': pos[1]}
    for s in pr.d['ships'].values():                 # also the places where the ships wait (on activation one would go there)
        s.pop('position', None)
    pr.dirty = True


def op_give(pr, m, o):
    """Give an item (the game's reward path); if equip is given ({ship, config, target, drone, set}) the new items are fitted there (the reward path may have fitted
    them to an active ship with a free slot: they come off from there first). When the target's slots are full the rest stay in the inventory."""
    known = PA.known_loots()
    equip = o.get('equip')
    for loot, n in o.get('items') or []:
        loot = str(loot)
        if loot not in known and not loot.startswith(('ammunition_', 'resource_', 'ship_', 'drone_', 'booster_')):
            raise ValueError('Unknown item: %s', loot)
        if '_design_' not in loot and any(s['lootId'] == loot for s in pr.d['ships'].values()):
            raise ValueError('This ship is already in the hangar: %s', loot)        # one of each ship in the game (the reward path skips)
        before = set(pr.d['items'])
        m.reward(loot, _int(n, 1, 10 ** 9))
        if not equip:
            continue
        new_ = [int(i) for i, l in pr.d['items'].items() if i not in before and l == loot]
        busy, active = pr.equipped_ids(), pr.ship()
        for k, i in enumerate(new_):
            if i in busy:
                m.handle('HangarShipMoveItemsRequest', {'items': [i], 'source': 'ship', 'destination': 'inventory', 'droneId': 0, 'slotSet': '',
                                                        'configId': int(active['active_config']), 'hangarId': active['hangarId']})
            try:
                op_move(pr, m, dict(equip, direction='equip', item=i))
            except ValueError:
                if not k:                              # if none could be fitted, the game's reason
                    raise
                break


def op_move(pr, m, o):
    sid = str(o.get('ship'))
    if sid not in pr.d['ships']:
        raise ValueError('Ship not found.')
    equip, target = o.get('direction') == 'equip', o.get('target') if o.get('target') in ('ship', 'drone', 'pet') else 'ship'
    f = {'items': [int(i) for i in (o.get('items') or [o.get('item')])], 'source': 'inventory' if equip else target,
         'destination': target if equip else 'inventory', 'configId': int(o.get('config') or 1), 'hangarId': pr.ship(sid)['hangarId'],
         'droneId': int(o.get('drone') or 0), 'slotSet': 'default' if target == 'drone' else 'heat' if o.get('set') == 'heat' else ''}
    _result(m.handle('HangarShipMoveItemsRequest', f), 'HangarShipMoveItemsCommand')


def op_delete(pr, m, o):
    """Delete the items that are not fitted (without selling)."""
    busy = pr.equipped_ids()
    for i in o.get('items') or []:
        i = int(i)
        if i in busy:
            raise ValueError("An equipped item can't be deleted: unequip it first.")
        pr.d['items'].pop(str(i), None)
        for k in ('item_level', 'upgrade_level'):
            pr.d.get(k, {}).pop(str(i), None)
    pr.dirty = True


def op_active_ship(pr, m, o):
    msgs, _changed = m.activate({'shipId': str(o.get('ship'))}, in_station=True, travel=True)
    _result(msgs, 'HangarShipActivateShipCommand')


def op_config(pr, m, o):
    sid = str(o.get('ship') or pr.d['active_ship'])
    ship = pr.ship(sid)
    n = str(_int(o.get('config'), 1, 2))
    if n in ship['configs']:
        ship['active_config'] = int(n)
        pr.sync_equipment()
        m.apply_stats()
        pr.dirty = True


def op_design(pr, m, o):
    msgs, _reload = m.change_model({'shipId': str(o.get('ship')), 'lootId': str(o.get('lootId') or '')})
    _result(msgs, 'HangarShipChangeShipModelCommand')


def op_favorite(pr, m, o):
    _result(m.handle('HangarShipFavouriteRequest', {'shipId': str(o.get('ship')), 'favourite': bool(o.get('favorite'))}),
           'HangarShipFavouriteCommand')


def op_clear(pr, m, o):
    _result(m.handle('HangarShipClearConfigRequest', {'wipe': 0, 'configId': int(o.get('config') or 1), 'shipId': str(o.get('ship'))}),
           'HangarShipClearConfigCommand')


def op_import(pr, m, o):
    _result(m.handle('HangarShipImportConfigRequest', {'originShipId': str(o.get('ship')), 'targetShipId': str(o.get('target'))}),
           'HangarShipImportConfigCommand')


def op_delete_ship(pr, m, o):
    """Remove the ship from the hangar; the equipment on it goes to the inventory (fitted state is computed from the ships' configs)."""
    sid = str(o.get('ship'))
    if sid not in pr.d['ships']:
        raise ValueError('Ship not found.')
    if sid == pr.d['active_ship']:
        raise ValueError("The active ship can't be removed: make another ship active first.")
    del pr.d['ships'][sid]
    pr.dirty = True


def op_drone(pr, m, o):
    import shop as SHP
    x = pr.drone(o.get('drone') or 0)
    if not x:
        raise ValueError('Drone not found.')
    if 'level' in o:                                  # level and points: the level's threshold
        x['level'] = _int(o['level'], 1, len(SHP.LEVELS))
        x['points'] = max(SHP.LEVELS[x['level'] - 1]['points'], min(int(x.get('points', 0)),
                        SHP.LEVELS[x['level']]['points'] - 1 if x['level'] < len(SHP.LEVELS) else 10 ** 9))
    if 'upgrade' in o:
        import upgrades as UPG
        x['upgrade'] = _int(o['upgrade'], 0, UPG.max_level(x['lootId']) or 16)
    pr.sync_equipment()
    pr.dirty = True


def op_delete_drone(pr, m, o):
    """Remove the drone (without selling): in every ship the items on it and its designs go to the inventory."""
    x = pr.drone(o.get('drone') or 0)
    if not x:
        raise ValueError('Drone not found.')
    for s in pr.d['ships'].values():
        for c in s.get('drone_config', {}).values():
            c.pop(str(x['uid']), None)
        for c in s.get('drone_design', {}).values():
            c.pop(str(x['uid']), None)
    pr.d['drones'].remove(x)
    pr.sync_equipment()
    pr.dirty = True


def op_item_level(pr, m, o):
    """An item's upgrade level (Assembly: 0 = not upgraded) or the level of a P.E.T. gear / protocol (1-4)."""
    import upgrades as UPG
    import pet as PETM
    i = str(int(o.get('item') or 0))
    loot = pr.d['items'].get(i)
    if not loot:
        raise ValueError('Item not found.')
    if 'upgrade' in o:
        n = _int(o['upgrade'], 0, UPG.max_level(loot))
        lv = pr.d.setdefault('upgrade_level', {})
        if n:
            lv[i] = n
        else:
            lv.pop(i, None)
    if 'level' in o and PETM.has_levels(loot):
        n = _int(o['level'], 1, 4)
        lv = pr.d.setdefault('item_level', {})
        if n > 1:
            lv[i] = n
        else:
            lv.pop(i, None)
    pr.sync_equipment()
    m.apply_stats()
    pr.dirty = True


def op_ammo(pr, m, o):
    c = pr.d.setdefault('ammunition', {})
    for loot, n in (o.get('counts') or {}).items():
        if not str(loot).startswith('ammunition_'):
            raise ValueError('Unknown item: %s', loot)
        c[loot] = _int(n, 0, 10 ** 12)
        pr.item_id(loot)                              # the client's counter id (a new ammo type)
    pr.dirty = True


def op_ore(pr, m, o):
    cur = {mm['oreType']['typeValue']: mm['count'] for mm in pr.d.get('ores', [])}
    for t, n in (o.get('counts') or {}).items():
        cur[int(t)] = _int(n, 0, 10 ** 9)
    pr.d['ores'] = [{'_': 'OreCountModule', 'oreType': {'_': 'OreTypeModule', 'typeValue': t}, 'count': n}
                        for t, n in sorted(cur.items()) if n > 0]
    pr.sync_cargo()
    pr.dirty = True


def op_resource(pr, m, o):
    d = pr.d.setdefault('other_items', {})
    for loot, n in (o.get('counts') or {}).items():
        if not str(loot).startswith('resource_'):
            raise ValueError('Unknown item: %s', loot)
        n = _int(n, 0, 10 ** 12)
        if n:
            d[loot] = n
        else:
            d.pop(loot, None)
    pr.dirty = True


def op_booster(pr, m, o):
    """Booster duration (seconds): stored like a booster dropped by an alien (stops while offline); 0 removes it."""
    import booster as BOOSTER
    b = pr.d.setdefault('boosters', {})
    for loot, sec in (o.get('durations') or {}).items():
        if not BOOSTER.is_booster(loot):
            raise ValueError('Unknown item: %s', loot)
        sec = _int(sec, 0, 10 ** 8)
        if sec:
            b[loot] = {'end_time': 0, 'remaining': float(sec)}
        else:
            b.pop(loot, None)
    m.apply_stats()
    pr.dirty = True


def op_pet(pr, m, o):
    import pet as PETM
    if o.get('give') and not m.pet.owned:
        m.grant_pet(str(o.get('name') or ''))
    d = pr.d.get('pet')
    if not d:
        raise ValueError('This save has no P.E.T.')
    if 'name' in o and str(o['name']).strip():
        d['name'] = str(o['name']).strip()[:24]
    if 'level' in o:
        d['level'] = _int(o['level'], 0, len(PETM.PET['levels']) - 1)
        d['ep'] = PETM.PET['levels'][d['level']]['ep']
    if 'fuel' in o:
        d['fuel'] = _int(o['fuel'], 0, PETM.PET['max_fuel'])
    for y, n in (o.get('slot') or {}).items():
        if y in PETM.SLOTS:
            d.setdefault('slot', {})[y] = _int(n, 0, PETM.PET['max_slots'].get(y, 0))
    if o.get('repair'):
        d['destroyed'] = False
        d['can'] = m.pet.hp_max()
    pr.dirty = True


def op_rng(pr, m, o):
    """Record of an item with random attributes: attributes [[name, value]] (from the pool, without repeats; fraction in a module, percent in the others), the module's
    ships, the QFC's linked ship and level, the reroll uses, the cannon's star. If there is no record it is first drawn as in the game."""
    import ship_module as GM
    import particle as PC
    i = str(int(o.get('item') or 0))
    loot = pr.d['items'].get(i)
    t = loot and rng_kind(loot)
    if not t:
        raise ValueError('This item has no random attributes to edit.')
    pool = rng_pool(loot)
    if t == 'module':
        rec = GM.state(pr, i)
    elif t == 'pc':
        rec = PC.ensure(pr, i)
    else:
        rec = pr.d.setdefault('qfc', {}).setdefault(i, {'ship': pr.ship()['lootId'], 'level': 1, 'attributes': []})
    if 'attribute' in o:
        ns = [[str(a), v] for a, v in o['attribute'] or []]
        names = [a for a, _v in ns]
        if not ns or len(ns) > pool['max_attributes'] or len(set(names)) != len(names) or any(a not in pool['attribute'] for a in names):
            raise ValueError('Invalid attributes: they must come from the pool, without repeats, and at most %s.', str(pool['max_attributes']))
        try:
            vals = [max(0.0, min(1.0 if pool['unit'] == 'fraction' else 1000.0, float(v))) for _a, v in ns]
        except (TypeError, ValueError):
            raise ValueError('A number was expected: %s', str([v for _a, v in ns]))
        rec['attributes' if t == 'qfc' else 'attribute'] = [[a, round(v, 4)] for a, v in zip(names, vals)]
    if 'ships' in o and t == 'module':
        gs = sorted({str(g) for g in o['ships'] or []})
        if not gs or any(g not in GM.all_ships() for g in gs):
            raise ValueError('Choose a ship.')
        rec['ships'] = gs
    if 'ship' in o and t == 'qfc':
        if str(o['ship']) not in GM.all_ships():
            raise ValueError('Choose a ship.')
        rec['ship'] = str(o['ship'])
    if 'level' in o and t == 'qfc':
        rec['level'] = _int(o['level'], 1, pool['max_level'])
    if 'right' in o and pool.get('right') is not None and t != 'qfc':
        rec['right'] = _int(o['right'], 0, pool['right'])
    if 'star' in o and pool.get('star'):
        rec['star'] = _int(o['star'], 0, pool['star'])
    pr.sync_equipment()
    m.apply_stats()
    pr.dirty = True


def op_cpu_charges(pr, m, o):
    """Remaining uses of a CPU that works with uses (extra_uses; per lootId, refilled in the game)."""
    import shop as SHP
    loot = str(o.get('lootId') or '')
    if 'right' not in SHP.EX.X.get(loot, {}):
        raise ValueError('Unknown item: %s', loot)
    pr.d.setdefault('extra_uses', {})[loot] = _int(o.get('right'), 0, 10 ** 6)
    pr.dirty = True


def op_repair(pr, m, o):
    g = pr.d['ship']
    g['hitPoints'], g['shield'] = g.get('hitMax', g.get('hitPoints', 1)), g.get('shieldMax', g.get('shield', 0))
    g['nanoHull'] = 0
    pr.dirty = True


def op_home_base(pr, m, o):
    home_base(pr)


def op_reset(pr, m, o):
    PA.reset_d(pr.d, [x for x in o.get('sections') or [] if x])
    pr.dirty = True


def op_keybinds(pr, m, o):
    import saves as SAV
    pr.d['key_bindings'] = SAV.default_key_bindings()
    pr.dirty = True


OPS = {'pilot': op_pilot, 'give': op_give, 'carry': op_move, 'delete': op_delete, 'active_ship': op_active_ship, 'config': op_config,
            'design': op_design, 'favorite': op_favorite, 'clean_up': op_clear, 'import_action': op_import, 'delete_ship': op_delete_ship, 'drone': op_drone,
            'drone_delete': op_delete_drone, 'item_level': op_item_level, 'ammunition': op_ammo, 'ore': op_ore, 'source': op_resource,
            'booster': op_booster, 'pet': op_pet, 'repair': op_repair, 'home_base': op_home_base, 'keybinds': op_keybinds, 'reset': op_reset,
            'rng': op_rng, 'cpu_charges': op_cpu_charges}


def apply(path, ops, original=None):
    pr, m = open_save(path)
    for o in ops:
        fn = OPS.get(o.get('operation'))
        if not fn:
            raise ValueError('Unknown operation: %s', str(o.get('operation')))
        fn(pr, m, o)
    pr.sync_equipment()
    pr.save(force=True)
    return appearance(*open_save(path), original=_read(original))


def _read(path):
    if not path:
        return None
    with open(path, encoding='utf8') as fh:
        return json.load(fh)


def main(argv):
    if argv[:1] == ['read'] and len(argv) in (2, 3):
        return appearance(*open_save(argv[1]), original=_read(argv[2] if len(argv) > 2 else None))
    if argv[:1] == ['apply'] and len(argv) in (3, 4):
        return apply(argv[1], json.loads(argv[2]), argv[3] if len(argv) > 3 else None)
    if argv[:1] == ['catalog'] and len(argv) == 1:
        return catalog()
    if argv[:1] == ['info'] and len(argv) == 1:
        return info()
    raise ValueError('usage: save_editor.py read <path> [original] | apply <path> <json> [original] | catalog')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    try:
        out = main(sys.argv[1:])
        print(json.dumps(dict(out, ok=True), ensure_ascii=False))
    except Exception as e:
        template = e.args[0] if isinstance(e, ValueError) and e.args and isinstance(e.args[0], str) else None
        msg = (template % e.args[1:] if len(e.args) > 1 else template) if template else str(e)
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, msg), 'template': template, 'arg': [str(a) for a in e.args[1:]]},
                         ensure_ascii=False))
