"""Xeno Resonator (yol haritası Ö6; veri data/items_o6.json 'rezonator' <- tools/items_o6.py, kaynak belgeler/wiki/items_o6.json).

İstemci 1.1.114'te yalnız metinleri var (eşya verisi, simgesi ve hangar yuvası yok; yayımlanmamış içerik). Synthesis'in Resonator
sekmesi sunucu verisiyle çalışıyor (canlı deneme 2026-10-18): SynthesisGroupCommand group synthesis_resonator_title, sol düğmeler
synthesis_resonator_strike / _aegis; eşyalar "?" simgeli, adları ipucunda istemcinin metinlerinden.
  C: türün kaynaklarından (resource_attack-* / resource_defensive-*) 3 tane + 1.000 U. Bedel satırı oyuncunun en çok tuttuğu kaynak;
     rezonatörün niteliği o kaynağın niteliği (C aralığından).
  UC..UL: 4 alt kalite (seçilen ilki ana rezonatör) + uridyum: ana rezonatörün nitelikleri yeni kalitenin aralığından yeniden çekilir,
     eksikler türün öteki niteliklerinden tamamlanır (Collapse ile Evernight birlikte gelmez). Başarı %100 (pencerede oran yok).
Etki (Strike): oyuncunun en iyi Strike Resonator'ı (kalite, sonra nitelik toplamı; hangarda yuvası yok) Singularity alanını değiştirir
(parcacik.fire_drive): expansion yarıçap, collapse süre -%25 ve toplam hasar +x, evernight süre +%25 ve toplam hasar +x, aftershock
hasarın %25'i bitişte (yarıçap +x) patlar, stagnation alandakileri yavaşlatır, adhesion alan ilk x sn ana hedefi izler.
Aegis düşman Singularity alanına karşı korur; tek oyunculuda uzaylılar sürücü kullanmıyor (botlarla anlam kazanır, Aşama 11).
"""
import json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'items_o6.json'), encoding='utf8'))['resonator']
ITEMS, SOURCES, ATTR = D['esyalar'], D['sources'], D['attributes']
RECIPES = {r['hedef']: r for r in D['recipes']}
INPUTS = {r['input'] for r in D['recipes'] if r.get('input')}
STATE = 'resonators'                  # profil: itemId -> {'nitelik': [[ad, değer], …]}


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
    """Nitelik adlarını n'ye tamamlar (türün ötekilerinden, dışlananlar hariç)."""
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
    """Niteliksiz gelen rezonatör (ödül, GM): kalitesinin sayısı kadar rastgele nitelik."""
    st = state(p, iid)
    loot = p.d['esyalar'].get(str(iid))
    if st is None and loot in ITEMS:
        e = ITEMS[loot]
        with p.lock:
            st = p.d.setdefault(STATE, {})[str(iid)] = {'nitelik': fill(e['tur'], e['quality'], [], e['attribute_count'], rng)}
            p.dirty = True
    return st


def create(p, loot, attrs):
    iid = p.new_item(loot)
    with p.lock:
        p.d.setdefault(STATE, {})[str(iid)] = {'nitelik': attrs}
        p.dirty = True
    return iid


def modifiers_str(p, iid):
    """Hangar ipucunun nitelik satırları (parcacik.modifiers_str biçimi: "AD,değer;…")."""
    st = ensure(p, iid) or {}
    return ';'.join('%s,%g' % (a.upper(), v) for a, v in st.get('nitelik', []))


def best(p, kind='strike'):
    """Oyuncunun en iyi rezonatörü (kalite, sonra nitelik toplamı) -> (itemId, {nitelik: değer}) ya da (None, {})."""
    rows = []
    for i, loot in p.d['esyalar'].items():
        e = ITEMS.get(loot)
        if e and e['tur'] == kind:
            st = ensure(p, int(i)) or {}
            attrs = {a: v for a, v in st.get('nitelik', [])}
            rows.append(((e['order'], sum(attrs.values())), int(i), attrs))
    if not rows:
        return None, {}
    _, iid, attrs = max(rows)
    return iid, attrs


def strike_mods(p):
    return best(p, 'strike')[1]


def source_for(p, kind):
    """C kalitesinin bedeli: oyuncunun en çok tuttuğu kaynak (eşitlikte sıradaki ilk)."""
    rows = sorted(SOURCES.items())
    have = [(p.d.get('other_items', {}).get(l, 0), -k, l) for k, (l, s) in enumerate(rows) if s['tur'] == kind]
    return max(have)[2] if have else None


# ---------------------------------------------------------------- Synthesis sekmesi
def modules(p, table_key):
    out = {}
    for r in D['recipes']:
        if r.get('input'):
            costs = [mod('SynthesisCostLootCommand', lootId=r['input'], amount=1, star=0, certain=True)] * r['adet']
        else:
            costs = [mod('SynthesisCostLootCommand', lootId=source_for(p, r['tur']), amount=r['source_amount'], star=0, certain=False)]
        costs.append(mod('SynthesisCostLootCommand', lootId='currency_uridium', amount=r['uridyum'], star=0, certain=False))
        out.setdefault(r['tur'], []).append(mod('SynthesisModuleCommand', lootId=r['hedef'], star=0, moduleGroupType=table_key[r['tur']],
                                                costs=costs, affectedShip=0))
    return out


def group_cmd(p):
    s = D['synthesis']
    mods = modules(p, s['tables'])
    return mod('SynthesisGroupCommand', button=s['button'], group=s['grup'], moduleList=[
        mod('SynthesisModuleListCommand', moduleListGroupType=s['tables'][t], modules=mods.get(t, [])) for t in ('strike', 'aegis')])


def synth(sy, loot, ids, rng=random):
    """sy: synthesis.Synthesis (profil, mağaza, günlük). -> mesajlar."""
    import inventory as INV
    from legacy_protocol import legacy
    p, r = sy.p, RECIPES[loot]
    e = ITEMS[loot]
    removed = []
    if r.get('input'):
        free = set(sy.free_items())
        ok = lambda i: i in free and p.d['esyalar'].get(str(i)) == r['input']
        ids = [i for i in dict.fromkeys(int(x) for x in ids) if ok(i)]
        if len(ids) < r['adet']:
            ids += [i for i in sorted(free) if ok(i) and i not in ids][:r['adet'] - len(ids)]
        if len(ids) < r['adet']:
            return sy.fail('%s yetmiyor (%d/%d)' % (r['input'], len(ids), r['adet']))
        ids = ids[:r['adet']]
        cost = {'currency_uridium': r['uridyum']}
        if INV.spend(p, cost, 'buy_SPECIAL', 'resonator') is None:
            return sy.fail('bedel yetmiyor (%s)' % cost)
        main = [a for a, _ in (ensure(p, ids[0]) or {}).get('nitelik', [])]
        with p.lock:
            for i in ids:
                p.d['esyalar'].pop(str(i), None)
                p.d.get(STATE, {}).pop(str(i), None)
            p.dirty = True
        removed = ids
        attrs = fill(e['tur'], e['quality'], main, e['attribute_count'], rng)
    else:
        src = source_for(p, e['tur'])
        cost = {src: r['source_amount'], 'currency_uridium': r['uridyum']}
        if not src or INV.spend(p, cost, 'buy_SPECIAL', 'resonator') is None:
            return sy.fail('bedel yetmiyor (%s)' % cost)
        attrs = fill(e['tur'], e['quality'], [SOURCES[src]['nitelik']], e['attribute_count'], rng)
    new = create(p, loot, attrs)
    msgs = [('InventoryItemRemovedCommand', {'itemId': i}) for i in removed] + INV.update_msgs(sy.m, p, list(cost))
    if sy.m:
        msgs += [sy.m.inv_item(new, loot, 1), sy.m.pack([sy.m.hangar_item(new, loot, 1)])]
    sy.log('   Resonator: %s%s -> %s %s' % ('%d x %s' % (len(removed), r['input']) if removed else '', ' bedel %s' % cost, loot, attrs))
    return msgs + [legacy('0|LM|ST|LOT|%s|1' % loot), sy.list_cmd()] + sy.inventory_cmds()
