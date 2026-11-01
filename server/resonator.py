"""Xeno Resonator (roadmap Ö6; data data/items_o6.json 'rezonator' <- tools/items_o6.py, source belgeler/wiki/items_o6.json).

In client 1.1.114 only the texts exist (no item data, icon or hangar slot; unreleased content). The Synthesis window's Resonator
tab works with server data (live test 2026-10-18): SynthesisGroupCommand group synthesis_resonator_title, left buttons
synthesis_resonator_strike / _aegis; the items have a "?" icon, their names in the tooltip from the client's texts.
  C: 3 of the type's resources (resource_attack-* / resource_defensive-*) + 1,000 U. The cost row is the resource the player holds most of;
     the resonator's attribute is that resource's attribute (from the C range).
  UC..UL: 4 lower qualities (the first selected is the main resonator) + uridium: the main resonator's attributes are re-rolled from the
     new quality's range, missing ones are filled from the type's other attributes (Collapse and Evernight do not come together). Success
is 100% (no rate in the window). Effect (Strike): the player's best Strike Resonator (quality, then attribute sum; no slot in the hangar)
changes the Singularity field (particle.fire_drive): expansion radius, collapse duration -25% and total damage +x, evernight duration +25%
and total damage +x, aftershock 25% of the damage explodes at the end (radius +x), stagnation slows those in the field, adhesion the field
follows the main target for the first x s. Aegis protects against an enemy Singularity field; in single player aliens do not use drives
(it gains meaning with bots, Stage 11). """
import json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'items_o6.json'), encoding='utf8'))['resonator']
ITEMS, SOURCES, ATTR = D['items'], D['sources'], D['attributes']
RECIPES = {r['target']: r for r in D['recipes']}
INPUTS = {r['input'] for r in D['recipes'] if r.get('input')}
STATE = 'resonators'                  # profile: itemId -> {'attribute': [[name, value], …]}


def mod(_cls, **f):
    f['_'] = _cls
    return f


def is_item(loot):
    return loot in ITEMS


def exclusive(names, cand):
    return any(cand in pair and any(o in names for o in pair if o != cand) for pair in D['excluded'])


def roll(kind, name, quality, rng=random):
    lo, hi = ATTR[kind][name]['interval'][quality]
    return round(rng.uniform(lo, hi), 1)


def fill(kind, quality, names, n, rng=random):
    """Fills the attribute names up to n (from the type's others, excluding the excluded)."""
    names = list(names)
    pool = [a for a in ATTR[kind] if a not in names]
    rng.shuffle(pool)
    for a in pool:
        if len(names) >= n:
            break
        if not exclusive(names, a):
            names.append(a)
    return [[a, roll(kind, a, quality, rng)] for a in names[:n]]


def state(p, iid):
    return p.d.get(STATE, {}).get(str(iid))


def ensure(p, iid, rng=random):
    """A resonator that arrives without attributes (reward, GM): as many random attributes as its quality number."""
    st = state(p, iid)
    loot = p.d['items'].get(str(iid))
    if st is None and loot in ITEMS:
        e = ITEMS[loot]
        with p.lock:
            st = p.d.setdefault(STATE, {})[str(iid)] = {'attribute': fill(e['type'], e['quality'], [], e['attribute_count'], rng)}
            p.dirty = True
    return st


def create(p, loot, attrs):
    iid = p.new_item(loot)
    with p.lock:
        p.d.setdefault(STATE, {})[str(iid)] = {'attribute': attrs}
        p.dirty = True
    return iid


def modifiers_str(p, iid):
    """Attribute rows of the hangar tooltip (particle.modifiers_str format: "NAME,value;…")."""
    st = ensure(p, iid) or {}
    return ';'.join('%s,%g' % (a.upper(), v) for a, v in st.get('attribute', []))


def best(p, kind='strike'):
    """The player's best resonator (quality, then attribute sum) -> (itemId, {attribute: value}) or (None, {})."""
    rows = []
    for i, loot in p.d['items'].items():
        e = ITEMS.get(loot)
        if e and e['type'] == kind:
            st = ensure(p, int(i)) or {}
            attrs = {a: v for a, v in st.get('attribute', [])}
            rows.append(((e['order'], sum(attrs.values())), int(i), attrs))
    if not rows:
        return None, {}
    _, iid, attrs = max(rows)
    return iid, attrs


def strike_mods(p):
    return best(p, 'strike')[1]


def source_for(p, kind):
    """The cost of quality C: the resource the player holds most of (the first in order on a tie)."""
    rows = sorted(SOURCES.items())
    have = [(p.d.get('other_items', {}).get(l, 0), -k, l) for k, (l, s) in enumerate(rows) if s['type'] == kind]
    return max(have)[2] if have else None


# ---------------------------------------------------------------- Synthesis tab
def modules(p, table_key):
    out = {}
    for r in D['recipes']:
        if r.get('input'):
            costs = [mod('SynthesisCostLootCommand', lootId=r['input'], amount=1, star=0, certain=True)] * r['count']
        else:
            costs = [mod('SynthesisCostLootCommand', lootId=source_for(p, r['type']), amount=r['source_amount'], star=0, certain=False)]
        costs.append(mod('SynthesisCostLootCommand', lootId='currency_uridium', amount=r['uridium'], star=0, certain=False))
        out.setdefault(r['type'], []).append(mod('SynthesisModuleCommand', lootId=r['target'], star=0, moduleGroupType=table_key[r['type']],
                                                costs=costs, affectedShip=0))
    return out


def group_cmd(p):
    s = D['synthesis']
    mods = modules(p, s['tables'])
    return mod('SynthesisGroupCommand', button=s['button'], group=s['group'], moduleList=[
        mod('SynthesisModuleListCommand', moduleListGroupType=s['tables'][t], modules=mods.get(t, [])) for t in ('strike', 'aegis')])


def synth(sy, loot, ids, rng=random):
    """sy: synthesis.Synthesis (profile, shop, daily). -> messages."""
    import inventory as INV
    from legacy_protocol import legacy
    p, r = sy.p, RECIPES[loot]
    e = ITEMS[loot]
    removed = []
    if r.get('input'):
        free = set(sy.free_items())
        ok = lambda i: i in free and p.d['items'].get(str(i)) == r['input']
        ids = [i for i in dict.fromkeys(int(x) for x in ids) if ok(i)]
        if len(ids) < r['count']:
            ids += [i for i in sorted(free) if ok(i) and i not in ids][:r['count'] - len(ids)]
        if len(ids) < r['count']:
            return sy.fail('%s yetmiyor (%d/%d)' % (r['input'], len(ids), r['count']))
        ids = ids[:r['count']]
        cost = {'currency_uridium': r['uridium']}
        if INV.spend(p, cost, 'buy_SPECIAL', 'resonator') is None:
            return sy.fail('bedel yetmiyor (%s)' % cost)
        main = [a for a, _ in (ensure(p, ids[0]) or {}).get('attribute', [])]
        with p.lock:
            for i in ids:
                p.d['items'].pop(str(i), None)
                p.d.get(STATE, {}).pop(str(i), None)
            p.dirty = True
        removed = ids
        attrs = fill(e['type'], e['quality'], main, e['attribute_count'], rng)
    else:
        src = source_for(p, e['type'])
        cost = {src: r['source_amount'], 'currency_uridium': r['uridium']}
        if not src or INV.spend(p, cost, 'buy_SPECIAL', 'resonator') is None:
            return sy.fail('bedel yetmiyor (%s)' % cost)
        attrs = fill(e['type'], e['quality'], [SOURCES[src]['attribute']], e['attribute_count'], rng)
    new = create(p, loot, attrs)
    msgs = [('InventoryItemRemovedCommand', {'itemId': i}) for i in removed] + INV.update_msgs(sy.m, p, list(cost))
    if sy.m:
        msgs += [sy.m.inv_item(new, loot, 1), sy.m.pack([sy.m.hangar_item(new, loot, 1)])]
    sy.log('   Resonator: %s%s -> %s %s' % ('%d x %s' % (len(removed), r['input']) if removed else '', ' cost %s' % cost, loot, attrs))
    return msgs + [legacy('0|LM|ST|LOT|%s|1' % loot), sy.list_cmd()] + sy.inventory_cmds()
