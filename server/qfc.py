"""Quantum Fluid Core and Hyperforge (roadmap stage 9; data in data/new_systems.json 'qfc' <- tools/new_systems.py, sources: the
darkorbit wiki and the Deep Space Echoes FAQ).

QFCs (equipment_core_ax-10 ... df-40) are inventory items: in the hangar they are fitted into the ship's QUANTUM FLUID CORE slots
(HangarShipEquipmentMsg.QuantumFluidCore; 2 slots in the client's ship data). Each QFC is bound to a ship and can only be fitted to it;
at most one attack (AX) and one defense (DF) QFC per ship. Client (HyperforgeViewSystem; Assembly's Hyperforge tab):
  QuantumFluidCoreDataListCommand {allModules}   on login and on change (together with UnstableModulesListCommand in the recording)
  QuantumFluidCoreRequest {ItemId, type}         1 forge: one level with Luminaflux (at most 12); attributes rise randomly
                                                 between upMin..upMax, at 5 and 10 a new attribute (no repeats, at most 3)
                                                 2 recycle: the QFC goes, Luminaflux comes ("This core will be destroyed.")
  QuantumFluidCoreData: lootId, itemId, quality (1-4), lv/maxLv, spendPrice (the next level's cost), useLootId (Luminaflux),
  sellPrice (recycling), shipIds (bound ship), unlock (1: one more locked attribute row), equipAttributes (EquipAttributeModule:
  AttributeID is the client's shipupgrade_modifiertype_ key, values are percent x100).
Effect: the attributes of the QFCs fitted on the active ship (profile.ship_mods; keys ship_module.ATTR_KEYS).
In the profile: qfc {itemId: {ship, level, attributes: [[name, value (%)]]}}.
"""
import json, os, random

import inventory as INV
from ship_module import ATTR_KEYS

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'new_systems.json'), encoding='utf8'))['qfc']
ITEMS = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))['items']
TYPES = D['kinds']
LUMI = D['luminaflux']
SLOT = 'QuantumFluidCore'
PREFIX = 'equipment_core_'
MAX_LV = D['max_level']
FORGE, RECYCLE = 1, 2
REQUESTS = {'QuantumFluidCoreRequest'}
KEYS = dict(ATTR_KEYS, damage_factions=('pvp',))          # factions: players of the other company (with bots, stage 11)


def mod(_cls, **f):
    f['_'] = _cls
    return f


def kind(loot):
    """'ax' ya da 'df'."""
    return loot[len(PREFIX):len(PREFIX) + 2]


def slots(ship_loot):
    return int((ITEMS.get(ship_loot, {}).get('slots') or {}).get(SLOT, 2))


def state(p, iid):
    return p.d.get('qfc', {}).get(str(iid))


def ranges(loot, primary=True):
    """The percentages of an attribute (first value range, per-level increase range, maximum)."""
    lo, hi = TYPES[loot]['interval']
    f = 1.0 if primary else D['extra_multiplier']
    a, b = D['increase_multiplier']
    return (lo * f, hi * f), (hi * a, hi * b), hi * D['max_multiplier']


def cost(loot, lv):
    """Luminaflux from lv to lv+1 (None if the top level)."""
    row = D['upgrade_cost'][str(TYPES[loot]['quality'])]
    return row[lv - 1] if 1 <= lv < MAX_LV else None


def echo_box(level):
    """The Echo chest (boxes.json type) dropped by Deep Space Echoes' boss level, or None."""
    return D['echo_level'].get(str(level))


def mods(p, ship_loot, iids):
    """The fitted QFCs' bonuses (only on the ship they are bound to)."""
    out = {}
    for iid in iids:
        loot = p.d['items'].get(str(iid), '')
        rec = state(p, iid)
        if not loot.startswith(PREFIX) or not rec or rec['ship'] != ship_loot:
            continue
        for a, v in rec['attributes']:
            for k in KEYS.get(a, ()):
                out[k] = out.get(k, 0) + v / 100.0
    return out


def modifiers_str(p, iid):
    """The hangar tooltip's attributes (ship_module.modifiers_str format "NAME,percent;..."): the tooltip's "Type:" line was empty, with no values
    (user report 2026-10-25: no value shown on QFC-AX40)."""
    rec = state(p, iid) or {}
    return ';'.join('%s,%s' % (a.upper(), format(v, '.2f').rstrip('0').rstrip('.')) for a, v in rec.get('attributes', []) if v > 0)


def equip_allowed(p, iid, ship_loot, current):
    """-> error text or None: bound ship, a second QFC of the same type on the ship."""
    loot = p.d['items'].get(str(iid), '')
    rec = state(p, iid)
    if not rec:
        return 'QFC kaydı yok'
    if rec['ship'] != ship_loot:
        return 'bu QFC %s gemisine bağlı' % rec['ship']
    if any(kind(p.d['items'].get(str(i), '')) == kind(loot) for i in current if i != iid):
        return 'gemide zaten bir %s QFC var' % kind(loot).upper()
    return None


class Qfc:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                              # shop (inventory, values); binds the session
        with profile.lock:
            profile.d.setdefault('qfc', {})

    def data(self, iid):
        loot = self.p.d['items'][str(iid)]
        rec = state(self.p, iid)
        attrs = []
        for i, (a, v) in enumerate(rec['attributes']):
            _, (ulo, uhi), top = ranges(loot, i == 0)
            attrs.append(mod('EquipAttributeModule', AttributeValue=int(round(v * 100)), maxAttributeValue=int(round(top * 100)),
                             upMin=int(round(ulo * 100)), upMax=int(round(uhi * 100)), AttributeID=a))
        nxt = cost(loot, rec['level'])
        return mod('QuantumFluidCoreData', equipAttributes=attrs, quality=TYPES[loot]['quality'], sellPrice=TYPES[loot]['recycle'],
                   itemId=int(iid), useLootId=LUMI, shipIds=[rec['ship']], unlock=1 if len(rec['attributes']) < D['max_attributes'] else 0,
                   lv=rec['level'], spendPrice=nxt or 0, maxLv=MAX_LV, lootId=loot)

    def list_cmd(self):
        ids = [i for i, l in self.p.d['items'].items() if l.startswith(PREFIX) and state(self.p, i)]
        return 'QuantumFluidCoreDataListCommand', {'allModules': [self.data(i) for i in sorted(ids, key=int)]}

    def roll_attr(self, loot, have, rng):
        pool = D['initial_attributes' if not have else 'extra_attribute'][kind(loot)]
        pool = [a for a in pool if a not in [x[0] for x in have]]
        (lo, hi), _, _ = ranges(loot, not have)
        return [rng.choice(pool), round(rng.uniform(lo, hi), 2)]

    def heal(self, rng=random):
        """Records for QFCs that have no record (bound ship, first attribute): a QFC without a record could not be fitted, had no value, and did not
        appear in the Hyperforge list. The session calls it at every login -> the itemIds that got a record."""
        done = [int(i) for i, l in list(self.p.d['items'].items()) if l in TYPES and not state(self.p, i)]
        for iid in done:
            self.record(self.p.d['items'][str(iid)], iid, rng=rng)
        return done

    def create(self, loot, ship=None, rng=random):
        """New QFC: a random ship (from the player's ships; adaptation), the first attribute -> itemId."""
        return self.record(loot, self.p.new_item(loot), ship, rng)

    def record(self, loot, iid, ship=None, rng=random):
        ships = sorted({s['lootId'] for s in self.p.d['ships'].values()}) or [self.p.ship()['lootId']]
        rec = {'ship': ship or rng.choice(ships), 'level': 1, 'attributes': []}
        rec['attributes'].append(self.roll_attr(loot, [], rng))
        with self.p.lock:
            self.p.d['qfc'][str(iid)] = rec
            self.p.dirty = True
        self.log('   QFC: %s (%s) %s %.2f%%' % (loot, rec['ship'], rec['attributes'][0][0], rec['attributes'][0][1]))
        return iid

    def grant(self, loot, n=1, rng=random):
        """Reward (Echo chest, package): QFCs to the inventory; not fitted (the bound ship and type rule is in the hangar)."""
        if loot not in TYPES:
            return None
        msgs = []
        for _ in range(n):
            iid = self.create(loot, rng=rng)
            if self.m:
                msgs += [self.m.inv_item(iid, loot, 1), self.m.pack([self.m.hangar_item(iid, loot, 1)])]
        from legacy_protocol import legacy
        return msgs + [legacy('0|LM|ST|LOT|%s|%d' % (loot, n)), self.list_cmd()]

    def handle(self, f):
        iid, t = int(f.get('ItemId') or f.get('itemId') or 0), f.get('type')
        t = t.get('typeValue', t) if isinstance(t, dict) else t
        if str(iid) not in self.p.d['items'] or not state(self.p, iid):
            self.log('   Hyperforge: no such QFC (%s)' % iid)
            return [self.list_cmd()]
        if int(t or 0) == FORGE:
            return self.forge(iid)
        if int(t or 0) == RECYCLE:
            return self.recycle(iid)
        return [self.list_cmd()]

    def forge(self, iid, rng=random):
        from legacy_protocol import stm
        loot = self.p.d['items'][str(iid)]
        rec = state(self.p, iid)
        price = cost(loot, rec['level'])
        if price is None:
            return [stm('msg_reroll_error_item'), self.list_cmd()]
        if INV.spend(self.p, {LUMI: price}, 'buy_SPECIAL', 'hyperforge') is None:
            self.log('   Hyperforge: not enough Luminaflux (%d < %d)' % (INV.count(self.p, LUMI), price))
            return [stm('ttip_not_enough_resources'), self.list_cmd()]
        with self.p.lock:
            rec['level'] += 1
            for i, a in enumerate(rec['attributes']):
                _, (ulo, uhi), top = ranges(loot, i == 0)
                a[1] = round(min(top, a[1] + rng.uniform(ulo, uhi)), 2)
            if rec['level'] in D['unlocked_levels'] and len(rec['attributes']) < D['max_attributes']:
                rec['attributes'].append(self.roll_attr(loot, rec['attributes'], rng))
            self.p.dirty = True
        self.log('   Hyperforge: %s level %d (%s)' % (loot, rec['level'], ', '.join('%s %.2f%%' % (a, v) for a, v in rec['attributes'])))
        name = loot.replace(PREFIX, 'QFC-').replace('-', '').upper().replace('QFC', 'QFC-')
        msgs = INV.update_msgs(self.m, self.p, [LUMI]) + [stm('log_message_core_forge_finished', '%NAME%', name, '%LEVEL%', rec['level'])]
        return msgs + [self.list_cmd()] + self.after(iid)

    def recycle(self, iid):
        from legacy_protocol import stm
        loot = self.p.d['items'][str(iid)]
        if iid in self.p.equipped_ids():
            self.log('   Hyperforge: a fitted QFC cannot be recycled (%s)' % iid)
            return [stm('msg_reroll_error_item'), self.list_cmd()]
        n = TYPES[loot]['recycle']
        with self.p.lock:
            del self.p.d['items'][str(iid)]
            self.p.d['qfc'].pop(str(iid), None)
            self.p.dirty = True
        msgs = [('InventoryItemRemovedCommand', {'itemId': iid})]
        msgs += self.m.reward(LUMI, n) if self.m else []
        if not self.m:
            self.p.add_resource(LUMI, n)
        name = loot.replace(PREFIX, 'QFC-').replace('-', '').upper().replace('QFC', 'QFC-')
        self.log('   Hyperforge: %s recycled (+%d Luminaflux)' % (loot, n))
        return msgs + [stm('log_message_core_recycle_finished', '%NAME%', name, '%COUNT%', n), self.list_cmd()]

    def after(self, iid):
        """If a fitted QFC changed, the active ship's values."""
        if self.m and iid in self.p.equipped_ids():
            return self.m.apply_stats()
        return []
