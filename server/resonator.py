"""Xeno Resonator (client 1.1.119; data data/items_o6.json 'resonator' <- tools/version_119.py; sources: the official FAQ board-en
130532 and the client's code, belgeler/istemci/xeno_resonator_istemci.md).

Items: equipment_xenoresonator_<c|uc|r|ep|ma|leg|ul>-<strike|aegis>-resonator, level 1-7 (the item's level in the hangar list). Strike
(DRIVE_ATK) adds 2..14% Singularity Drive damage, Aegis (DRIVE_DEF) cuts the Singularity damage taken by as much. Each ship config has one
offensive and one defensive slot (HangarShipEquipmentMsg.xenoResonators {slotId 1 ATK / 2 DEF, type, itemId, enabled}); equipping is
HangarShipMoveItemsRequest with slotSet "xeno_resonators" (shop.move). Per item in the profile: resonators {itemId: {effect, tier, ship,
ship_bp}}; the hangar item carries them as extAttributes xenoEffectId / xenoEffectLevel / xenoLocked / xenoShipId / xenoShipDamageBasisPoints.
Client requests (window xeno_resonator 153, and the Synthesis window's group "xeno_resonator"):
  XenoResonatorConfigRequest    -> XenoResonatorConfigResult {status, gems [type, levels, effects]} (the client rejects the whole result if a
                                   value is out of range)
  XenoResonatorInventoryRequest -> XenoResonatorInventoryResult {status, batchIndex, batchCount, items} (at most 100 per batch)
  XenoResonatorUpgradeRequest {mainItemId, materialItemIds[4]}: Intensify; the main and the four are the same type and level T-1, not
      equipped; success upgradeSuccessBasisPoints(T); on success the main becomes level T (and at T 6/7 may gain a random special attribute),
      on failure the main stays; the four are consumed either way -> XenoResonatorUpgradeResult (the client then re-reads the inventory)
  XenoResonatorEffectRequest {itemId, operation, materialLootId}: on a max-level resonator; ACTIVATE (Activation Chip: a random attribute,
      tier 1), SELECT (the attribute's own item: that attribute, replaces), CALIBRATE (Calibration Chip: +1 tier) -> XenoResonatorEffectResult
  DisassemblyRequest {disassemble_disassemble-xenoresonator}: recycle -> Xeno-Tech Fragments (upgrades.py, the client's table)
C resonators come from Assembly (10 fragments, the client's recipes); the higher ones from the Vortex of Greed (boss drops, shops).
"""
import json, os, random

import game_data as DATA

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'items_o6.json'), encoding='utf8'))['resonator']
ITEMS, KINDS, LEVELS = D['items'], D['kinds'], {r['level']: r for r in D['levels']}
EFFECTS = {k: {e['effect']: e for e in rows} for k, rows in D['effects'].items()}
BY_MATERIAL = {e['material']: (k, e) for k, rows in D['effects'].items() for e in rows}
CHIPS = D['chips']
SOURCES = set(BY_MATERIAL) | set(CHIPS.values()) | {D['fragments']}     # resources of the window (shop counters)
INPUTS = set()                                                         # the Synthesis window's own resonator inputs (none: Intensify is below)
MAX_LEVEL = max(LEVELS)
LOOT = {(e['type'], e['level']): loot for loot, e in ITEMS.items()}
STATE = 'resonators'                  # profile: itemId -> {'effect', 'tier', 'ship', 'ship_bp'}
SLOT_SET = 'xeno_resonators'          # the hangar's slot set and the config key
BATCH = 100
SUCCESS, FAILED, INVALID, BUSY, ERROR = 1, 2, 3, 4, 5                  # XenoResonatorUpgradeResult.Status
E_OK, E_INVALID_ITEM, E_NOT_MAX, E_EQUIPPED, E_EXISTS, E_NOT_FOUND, E_INVALID_EFFECT, E_MAX_TIER, E_MATERIALS, E_OPERATION = range(1, 11)
ACTIVATE, SELECT, CALIBRATE = 1, 2, 3                                   # XenoResonatorEffectRequest.Operation


def mod(_cls, **f):
    f['_'] = _cls
    return f


def is_item(loot):
    return loot in ITEMS


def kind_of(loot):
    return ITEMS[loot]['type'] if loot in ITEMS else None


def level_of(loot):
    return ITEMS[loot]['level'] if loot in ITEMS else 0


def effect_value(e, tier):
    """The attribute's value at a tier in percent, as the client computes it (XenoResonatorEffectDescription.Calculate)."""
    v = e['values']
    if e['name'] == 'adhesion':                                     # [start, floor, step]: falls with the tier
        return max(v[0] - v[2] * (tier - 1), v[1]) / 100.0
    start, cap, step = v[-3:]
    return min(start + (tier - 1) * step, cap) / 100.0


def roll_ship(rng=random):
    """The ship-specific Singularity Drive bonus of a new Strike Resonator (adaptation, items_o6.json _adaptation): model id, basis points."""
    b = D['ship_bonus']
    return _model(rng.choice(b['ships'])), rng.randrange(b['bp'][0], b['bp'][1] + 1, b['step'])


def _model(loot):
    global _CL
    if _CL is None:
        _CL = DATA.shared('client_items.json')['items']
    return (_CL.get(loot) or {}).get('model')


_CL = None


def state(p, iid):
    return p.d.get(STATE, {}).get(str(iid))


def ensure(p, iid, rng=random):
    """The item's record; a resonator that arrives without one (reward, shop, Assembly) gets its ship bonus (Strike). The pre-release
    records (attribute lists, 1.1.114 adaptation) are replaced: no attribute, the level is the quality."""
    st = state(p, iid)
    loot = p.d['items'].get(str(iid))
    if loot not in ITEMS:
        return st
    if st is None or 'attribute' in st:
        ship, bp = roll_ship(rng) if ITEMS[loot]['type'] == 'strike' else (0, 0)
        with p.lock:
            st = p.d.setdefault(STATE, {})[str(iid)] = {'effect': 0, 'tier': 0, 'ship': ship or 0, 'ship_bp': bp if ship else 0}
            p.dirty = True
    return st


def ext_attributes(p, iid):
    st = ensure(p, iid) or {}
    rows = [('xenoEffectId', st.get('effect', 0)), ('xenoEffectLevel', st.get('tier', 0) if st.get('effect') else 0),
            ('xenoLocked', 'False')]
    if st.get('ship') and st.get('ship_bp'):
        rows += [('xenoShipId', st['ship']), ('xenoShipDamageBasisPoints', st['ship_bp'])]
    return [mod('TupleTwoModule', param0=k, param1=str(v)) for k, v in rows]


def hangar_fields(p, iid, loot):
    return {'level': level_of(loot), 'extAttributes': ext_attributes(p, iid)}


def modifiers_str(p, iid):
    return ''


def resonators(p):
    return sorted(int(i) for i, l in p.d['items'].items() if l in ITEMS)


# ---------------------------------------------------------------- hangar slots
def slot_ids(p, sid=None, cid=None):
    """The resonators fitted in a ship config -> {'strike': itemId, 'aegis': itemId}."""
    out = {}
    for iid in p.config(cid, sid).get(SLOT_SET, []):
        k = kind_of(p.d['items'].get(str(iid)))
        if k:
            out[k] = iid
    return out


def slots_msg(p, sid=None, cid=None):
    """HangarShipEquipmentMsg.xenoResonators: one ATK and one DEF slot, open."""
    have = slot_ids(p, sid, cid)
    return [mod('XenoResonatorSlotModule', slotId=D['slots'][k], type=KINDS[k], itemId=have.get(k, 0), enabled=True) for k in KINDS]


def equip(p, cfg, iid, loot):
    """Fits the resonator in its type's slot of the config; the one there before -> returned (to the inventory)."""
    lst = cfg.setdefault(SLOT_SET, [])
    old = [i for i in lst if kind_of(p.d['items'].get(str(i))) == kind_of(loot) and i != iid]
    for i in old:
        lst.remove(i)
    if iid not in lst:
        lst.append(iid)
    return old


def active(p, kind):
    """The resonator fitted in the active config of the active ship -> (itemId, loot) or (None, None)."""
    iid = slot_ids(p).get(kind)
    return (iid, p.d['items'].get(str(iid))) if iid else (None, None)


def strike_mods(p):
    """For the Singularity field (particle.resonate): {'damage': %, 'ship': %, <attribute name>: %} of the active Strike Resonator."""
    iid, loot = active(p, 'strike')
    if not iid:
        return {}
    st = ensure(p, iid) or {}
    out = {'damage': LEVELS[level_of(loot)]['damage_bp'] / 100.0}
    if st.get('ship') and st.get('ship') == _model(p.ship()['lootId']):
        out['ship'] = st['ship_bp'] / 100.0
    e = EFFECTS['strike'].get(st.get('effect'))
    if e:
        out[e['name']] = effect_value(e, st.get('tier', 1))
    return out


def aegis_mods(p):
    """Protection against an enemy Singularity Drive (bot players): {'defense': %, <attribute name>: %}."""
    iid, loot = active(p, 'aegis')
    if not iid:
        return {}
    st = ensure(p, iid) or {}
    out = {'defense': LEVELS[level_of(loot)]['damage_bp'] / 100.0}
    e = EFFECTS['aegis'].get(st.get('effect'))
    if e:
        out[e['name']] = effect_value(e, st.get('tier', 1))
    return out


# ---------------------------------------------------------------- messages
def config_result():
    gems = []
    for kind, tid in KINDS.items():
        gems.append(mod('XenoResonatorGemConfigModule', type=tid, levels=[
            mod('XenoResonatorLevelConfigModule', level=lv, lootId=LOOT[(kind, lv)], damageBasisPoints=r['damage_bp'],
                effectChanceBasisPoints=r['effect_chance_bp'], upgradeSuccessBasisPoints=r['upgrade_success_bp'])
            for lv, r in sorted(LEVELS.items())], effects=[
            mod('XenoResonatorEffectConfigModule', effect=e['effect'], weight=e['weight'], maxLv=e['max_level'], values=list(e['values']),
                materialLootId=e['material']) for e in D['effects'][kind]]))
    return 'XenoResonatorConfigResult', {'status': 1, 'gems': gems}


def synthesis_group():
    """The Synthesis window's Resonator tab (Intensify): the client reads the type from modules[0].lootId of the selected list and the
    target levels from the config; the module rows are the levels 2-7 of the type."""
    s = D['synthesis']
    return mod('SynthesisGroupCommand', button=s['button'], group=s['group'], moduleList=[
        mod('SynthesisModuleListCommand', moduleListGroupType=s['tables'][k], modules=[
            mod('SynthesisModuleCommand', lootId=LOOT[(k, lv)], star=0, moduleGroupType=s['tables'][k], costs=[], affectedShip=0)
            for lv in sorted(LEVELS) if lv > 1]) for k in KINDS])


class Xeno:
    REQUESTS = {'XenoResonatorConfigRequest', 'XenoResonatorInventoryRequest', 'XenoResonatorUpgradeRequest', 'XenoResonatorEffectRequest'}

    def __init__(self, profile, log=print, rng=random):
        self.p, self.log, self.rng = profile, log, rng
        self.m = None                                   # shop (hangar items, inventory updates)

    def handle(self, name, f):
        if name == 'XenoResonatorConfigRequest':
            return [config_result()]
        if name == 'XenoResonatorInventoryRequest':
            return self.inventory()
        if name == 'XenoResonatorUpgradeRequest':
            return self.upgrade(f)
        if name == 'XenoResonatorEffectRequest':
            return self.effect(f)
        return []

    def inventory(self):
        hm = self.p.hangar_map()
        items = [self.m.hangar_item(i, self.p.d['items'][str(i)], 1, hm.get(i, 0)) for i in resonators(self.p)] if self.m else []
        n = max(1, (len(items) + BATCH - 1) // BATCH)
        return [('XenoResonatorInventoryResult', dict(status=1, batchIndex=k, batchCount=n, items=items[k * BATCH:(k + 1) * BATCH]))
                for k in range(n)]

    def free(self, iid):
        return str(iid) in self.p.d['items'] and iid not in self.p.equipped_ids()

    def item_msgs(self, changed, removed, loots=()):
        import inventory as INV
        msgs = INV.update_msgs(self.m, self.p, list(loots), removed)
        if self.m and changed:
            msgs += self.m.item_updates(changed)
        return msgs

    def upgrade(self, f):
        p = self.p
        main = int(f.get('mainItemId') or 0)
        mats = [int(x) for x in (f.get('materialItemIds') or [])]
        result = lambda st, old=0, new=0, used=(): ('XenoResonatorUpgradeResult', dict(
            status=st, mainItemId=main, oldLevel=old, newLevel=new, consumedItemIds=[float(i) for i in used]))
        loot = p.d['items'].get(str(main))
        if not is_item(loot) or not self.free(main):
            self.log('   Xeno Intensify: main %s is not a free resonator' % main)
            return [result(INVALID)]
        kind, lv = kind_of(loot), level_of(loot)
        ok = lambda i: i != main and self.free(i) and p.d['items'].get(str(i)) == loot
        mats = list(dict.fromkeys(mats))
        if lv + 1 not in LEVELS or len(mats) != D['material_count'] or not all(ok(i) for i in mats):
            self.log('   Xeno Intensify: invalid materials %s for %s' % (mats, loot))
            return [result(INVALID, lv, lv)]
        target = lv + 1
        win = self.rng.random() * 10000 < LEVELS[target]['upgrade_success_bp']
        with p.lock:
            for i in mats:
                p.d['items'].pop(str(i), None)
                p.d.get(STATE, {}).pop(str(i), None)
            if win:
                p.d['items'][str(main)] = LOOT[(kind, target)]
            p.dirty = True
        st = ensure(p, main)
        gained = None
        if win and not st.get('effect') and self.rng.random() * 10000 < LEVELS[target]['effect_chance_bp']:
            gained = self.random_effect(kind)
            with p.lock:
                st.update(effect=gained['effect'], tier=1)
                p.dirty = True
        from legacy_protocol import legacy
        self.log('   Xeno Intensify: %s + 4 -> %s%s' % (loot, LOOT[(kind, target)] if win else 'failed (main kept)',
                                                     ' + %s' % gained['name'] if gained else ''))
        msgs = [result(SUCCESS if win else FAILED, lv, target if win else lv, mats)] + self.item_msgs([main], mats)
        msgs.append(legacy('0|A|STM|%s' % ('xeno_resonator_upgrade_success' if win else 'xeno_resonator_upgrade_failed')))
        if gained:
            msgs.append(legacy('0|A|STM|xeno_resonator_activated'))
        return msgs

    def random_effect(self, kind):
        rows = D['effects'][kind]
        return self.rng.choices(rows, weights=[max(e['weight'], 0) or 1 for e in rows])[0]

    def effect(self, f):
        p = self.p
        iid, op = int(f.get('itemId') or 0), int(f.get('operation') or 0)
        material = f.get('materialLootId') or ''
        result = lambda st, e=0, t=0: ('XenoResonatorEffectResult', dict(status=st, operation=op, itemId=iid, effect=e, effectLevel=t))
        loot = p.d['items'].get(str(iid))
        if not is_item(loot):
            return [result(E_INVALID_ITEM)]
        if level_of(loot) < MAX_LEVEL:
            return [result(E_NOT_MAX)]
        if iid in p.equipped_ids():
            return [result(E_EQUIPPED)]
        kind, st = kind_of(loot), ensure(p, iid)
        cur = EFFECTS[kind].get(st.get('effect'))
        if op == ACTIVATE:
            if cur:
                return [result(E_EXISTS, cur['effect'], st['tier'])]
            need, new, tier, text = CHIPS['activation'], self.random_effect(kind), 1, 'xeno_resonator_activated'
        elif op == SELECT:
            k, new = BY_MATERIAL.get(material, (None, None))
            if k != kind:
                return [result(E_INVALID_EFFECT)]
            need, tier, text = material, (st.get('tier') or 1) if cur else 1, 'xeno_resonator_selected'
            tier = min(tier, new['max_level'])
        elif op == CALIBRATE:
            if not cur:
                return [result(E_NOT_FOUND)]
            if st['tier'] >= cur['max_level']:
                return [result(E_MAX_TIER, cur['effect'], st['tier'])]
            need, new, tier, text = CHIPS['calibration'], cur, st['tier'] + 1, 'xeno_resonator_calibrated'
        else:
            return [result(E_OPERATION)]
        if not p.spend_resources({need: 1}):
            return [result(E_MATERIALS, st.get('effect', 0), st.get('tier', 0))]
        with p.lock:
            st.update(effect=new['effect'], tier=tier)
            p.dirty = True
        self.log('   Xeno effect %s: %s -> %s tier %d (%s)' % ({1: 'activate', 2: 'select', 3: 'calibrate'}[op], loot, new['name'], tier,
                                                            need))
        from legacy_protocol import legacy
        return [result(E_OK, new['effect'], tier)] + self.item_msgs([iid], [], [need]) + [legacy('0|A|STM|%s' % text)]


def recycled(p, iid):
    """upgrades.disassemble: the record of a recycled resonator goes with it."""
    with p.lock:
        p.d.get(STATE, {}).pop(str(iid), None)
        p.dirty = True
