"""Quantum Fluid Core ve Hyperforge (yol haritası Aşama 9; veri data/new_systems.json 'qfc' <- tools/new_systems.py, kaynak
darkorbitwiki ve Deep Space Echoes SSS'i).

QFC'ler (equipment_core_ax-10 … df-40) envanterdeki eşyalar: hangarda geminin QUANTUM FLUID CORE yuvalarına takılır
(HangarShipEquipmentMsg.QuantumFluidCore; istemcinin gemi verisinde 2 yuva). Her QFC bir gemiye bağlıdır, yalnız ona takılır;
gemide en çok bir saldırı (AX) ve bir savunma (DF) QFC'si. İstemci (HyperforgeViewSystem; Assembly'nin Hyperforge sekmesi):
  QuantumFluidCoreDataListCommand {allModules}   girişte ve değişince (kayıtta UnstableModulesListCommand ile birlikte)
  QuantumFluidCoreRequest {ItemId, type}         1 forge: Luminaflux ile bir seviye (en çok 12); nitelikler upMin..upMax arasında
                                                 rastgele artar, 5 ve 10'da yeni nitelik (tekrarsız, en çok 3)
                                                 2 recycle: QFC gider, Luminaflux gelir ("This core will be destroyed.")
  QuantumFluidCoreData: lootId, itemId, quality (1-4), lv/maxLv, spendPrice (sonraki seviyenin bedeli), useLootId (Luminaflux),
  sellPrice (geri dönüşüm), shipIds (bağlı gemi), unlock (1: kilitli bir nitelik satırı daha), equipAttributes (EquipAttributeModule:
  AttributeID istemcinin shipupgrade_modifiertype_ anahtarı, değerler yüzde x100).
Etki: etkin gemide takılı QFC'lerin nitelikleri (profil.ship_mods; anahtarlar gemi_modul.ATTR_KEYS).
Profilde: qfc {itemId: {gemi, seviye, nitelikler: [[ad, değer (%)]]}}.
"""
import json, os, random

import inventory as INV
from ship_module import ATTR_KEYS

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'new_systems.json'), encoding='utf8'))['qfc']
ITEMS = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))['esyalar']
TYPES = D['turler']
LUMI = D['luminaflux']
SLOT = 'QuantumFluidCore'
PREFIX = 'equipment_core_'
MAX_LV = D['azami_seviye']
FORGE, RECYCLE = 1, 2
REQUESTS = {'QuantumFluidCoreRequest'}
KEYS = dict(ATTR_KEYS, damage_factions=('pvp',))          # factions: başka firmanın oyuncuları (botlarla, Aşama 11)


def mod(_cls, **f):
    f['_'] = _cls
    return f


def kind(loot):
    """'ax' ya da 'df'."""
    return loot[len(PREFIX):len(PREFIX) + 2]


def slots(ship_loot):
    return int((ITEMS.get(ship_loot, {}).get('yuvalar') or {}).get(SLOT, 2))


def state(p, iid):
    return p.d.get('qfc', {}).get(str(iid))


def ranges(loot, primary=True):
    """Niteliğin (ilk değer aralığı, seviye başına artış aralığı, azami) yüzdeleri."""
    lo, hi = TYPES[loot]['aralik']
    f = 1.0 if primary else D['ek_carpan']
    a, b = D['artis_carpan']
    return (lo * f, hi * f), (hi * a, hi * b), hi * D['azami_carpan']


def cost(loot, lv):
    """lv'den lv+1'e Luminaflux (yoksa None: en üst seviye)."""
    row = D['yukseltme_bedeli'][str(TYPES[loot]['kalite'])]
    return row[lv - 1] if 1 <= lv < MAX_LV else None


def echo_box(level):
    """Deep Space Echoes'un patron seviyesinin düşürdüğü Echo sandığı (boxes.json türü) ya da None."""
    return D['echo_seviye'].get(str(level))


def mods(p, ship_loot, iids):
    """Takılı QFC'lerin bonusları (yalnız bağlı oldukları gemide)."""
    out = {}
    for iid in iids:
        loot = p.d['esyalar'].get(str(iid), '')
        rec = state(p, iid)
        if not loot.startswith(PREFIX) or not rec or rec['gemi'] != ship_loot:
            continue
        for a, v in rec['nitelikler']:
            for k in KEYS.get(a, ()):
                out[k] = out.get(k, 0) + v / 100.0
    return out


def modifiers_str(p, iid):
    """Hangar ipucunun nitelikleri (gemi_modul.modifiers_str biçimi "AD,yüzde;…"): ipucunda "Tür:" satırı boş, değerler yoktu
    (kullanıcı bildirimi 2026-10-25: QFC-AX40'ta değer görünmüyor)."""
    rec = state(p, iid) or {}
    return ';'.join('%s,%s' % (a.upper(), format(v, '.2f').rstrip('0').rstrip('.')) for a, v in rec.get('nitelikler', []) if v > 0)


def equip_allowed(p, iid, ship_loot, current):
    """-> hata metni ya da None: bağlı gemi, gemide aynı türden ikinci QFC."""
    loot = p.d['esyalar'].get(str(iid), '')
    rec = state(p, iid)
    if not rec:
        return 'QFC kaydı yok'
    if rec['gemi'] != ship_loot:
        return 'bu QFC %s gemisine bağlı' % rec['gemi']
    if any(kind(p.d['esyalar'].get(str(i), '')) == kind(loot) for i in current if i != iid):
        return 'gemide zaten bir %s QFC var' % kind(loot).upper()
    return None


class Qfc:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                              # mağaza (envanter, değerler); oturum bağlar
        with profile.lock:
            profile.d.setdefault('qfc', {})

    def data(self, iid):
        loot = self.p.d['esyalar'][str(iid)]
        rec = state(self.p, iid)
        attrs = []
        for i, (a, v) in enumerate(rec['nitelikler']):
            _, (ulo, uhi), top = ranges(loot, i == 0)
            attrs.append(mod('EquipAttributeModule', AttributeValue=int(round(v * 100)), maxAttributeValue=int(round(top * 100)),
                             upMin=int(round(ulo * 100)), upMax=int(round(uhi * 100)), AttributeID=a))
        nxt = cost(loot, rec['seviye'])
        return mod('QuantumFluidCoreData', equipAttributes=attrs, quality=TYPES[loot]['kalite'], sellPrice=TYPES[loot]['geri_donusum'],
                   itemId=int(iid), useLootId=LUMI, shipIds=[rec['gemi']], unlock=1 if len(rec['nitelikler']) < D['azami_nitelik'] else 0,
                   lv=rec['seviye'], spendPrice=nxt or 0, maxLv=MAX_LV, lootId=loot)

    def list_cmd(self):
        ids = [i for i, l in self.p.d['esyalar'].items() if l.startswith(PREFIX) and state(self.p, i)]
        return 'QuantumFluidCoreDataListCommand', {'allModules': [self.data(i) for i in sorted(ids, key=int)]}

    def roll_attr(self, loot, have, rng):
        pool = D['ilk_nitelik' if not have else 'ek_nitelik'][kind(loot)]
        pool = [a for a in pool if a not in [x[0] for x in have]]
        (lo, hi), _, _ = ranges(loot, not have)
        return [rng.choice(pool), round(rng.uniform(lo, hi), 2)]

    def heal(self, rng=random):
        """Kaydı olmayan QFC'lere kayıt (bağlı gemi, ilk nitelik): kayıtsız QFC takılamıyor, değeri yok, Hyperforge listesinde
        görünmüyordu. Oturum her girişte çağırır -> kaydı yapılan itemId'ler."""
        done = [int(i) for i, l in list(self.p.d['esyalar'].items()) if l in TYPES and not state(self.p, i)]
        for iid in done:
            self.record(self.p.d['esyalar'][str(iid)], iid, rng=rng)
        return done

    def create(self, loot, ship=None, rng=random):
        """Yeni QFC: rastgele gemi (oyuncunun gemilerinden; uyarlama), ilk nitelik -> itemId."""
        return self.record(loot, self.p.new_item(loot), ship, rng)

    def record(self, loot, iid, ship=None, rng=random):
        ships = sorted({s['lootId'] for s in self.p.d['gemiler'].values()}) or [self.p.ship()['lootId']]
        rec = {'gemi': ship or rng.choice(ships), 'seviye': 1, 'nitelikler': []}
        rec['nitelikler'].append(self.roll_attr(loot, [], rng))
        with self.p.lock:
            self.p.d['qfc'][str(iid)] = rec
            self.p.dirty = True
        self.log('   QFC: %s (%s) %s %.2f%%' % (loot, rec['gemi'], rec['nitelikler'][0][0], rec['nitelikler'][0][1]))
        return iid

    def grant(self, loot, n=1, rng=random):
        """Ödül (Echo sandığı, paket): QFC'ler envantere; takılmaz (bağlı gemi ve tür kuralı hangarda)."""
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
        if str(iid) not in self.p.d['esyalar'] or not state(self.p, iid):
            self.log('   Hyperforge: QFC yok (%s)' % iid)
            return [self.list_cmd()]
        if int(t or 0) == FORGE:
            return self.forge(iid)
        if int(t or 0) == RECYCLE:
            return self.recycle(iid)
        return [self.list_cmd()]

    def forge(self, iid, rng=random):
        from legacy_protocol import stm
        loot = self.p.d['esyalar'][str(iid)]
        rec = state(self.p, iid)
        price = cost(loot, rec['seviye'])
        if price is None:
            return [stm('msg_reroll_error_item'), self.list_cmd()]
        if INV.spend(self.p, {LUMI: price}, 'buy_SPECIAL', 'hyperforge') is None:
            self.log('   Hyperforge: Luminaflux yetmiyor (%d < %d)' % (INV.count(self.p, LUMI), price))
            return [stm('ttip_not_enough_resources'), self.list_cmd()]
        with self.p.lock:
            rec['seviye'] += 1
            for i, a in enumerate(rec['nitelikler']):
                _, (ulo, uhi), top = ranges(loot, i == 0)
                a[1] = round(min(top, a[1] + rng.uniform(ulo, uhi)), 2)
            if rec['seviye'] in D['acilan_seviyeler'] and len(rec['nitelikler']) < D['azami_nitelik']:
                rec['nitelikler'].append(self.roll_attr(loot, rec['nitelikler'], rng))
            self.p.dirty = True
        self.log('   Hyperforge: %s seviye %d (%s)' % (loot, rec['seviye'], ', '.join('%s %.2f%%' % (a, v) for a, v in rec['nitelikler'])))
        name = loot.replace(PREFIX, 'QFC-').replace('-', '').upper().replace('QFC', 'QFC-')
        msgs = INV.update_msgs(self.m, self.p, [LUMI]) + [stm('log_message_core_forge_finished', '%NAME%', name, '%LEVEL%', rec['seviye'])]
        return msgs + [self.list_cmd()] + self.after(iid)

    def recycle(self, iid):
        from legacy_protocol import stm
        loot = self.p.d['esyalar'][str(iid)]
        if iid in self.p.equipped_ids():
            self.log('   Hyperforge: takılı QFC geri dönüştürülmez (%s)' % iid)
            return [stm('msg_reroll_error_item'), self.list_cmd()]
        n = TYPES[loot]['geri_donusum']
        with self.p.lock:
            del self.p.d['esyalar'][str(iid)]
            self.p.d['qfc'].pop(str(iid), None)
            self.p.dirty = True
        msgs = [('InventoryItemRemovedCommand', {'itemId': iid})]
        msgs += self.m.reward(LUMI, n) if self.m else []
        if not self.m:
            self.p.add_resource(LUMI, n)
        name = loot.replace(PREFIX, 'QFC-').replace('-', '').upper().replace('QFC', 'QFC-')
        self.log('   Hyperforge: %s geri dönüştürüldü (+%d Luminaflux)' % (loot, n))
        return msgs + [stm('log_message_core_recycle_finished', '%NAME%', name, '%COUNT%', n), self.list_cmd()]

    def after(self, iid):
        """Takılı QFC değiştiyse etkin geminin değerleri."""
        if self.m and iid in self.p.equipped_ids():
            return self.m.apply_stats()
        return []
