"""Oyuncunun eşyaları lootId'ye göre tek arayüzde (yol haritası Aşama 5): Assembly tarifleri, anahtarlı kutular, Dispatch ve Skylab
ücretleri hangi depoda durduğuna bakmadan sayar ve harcar.

  currency_credits / currency_uridium     pilotun kredisi / uridyumu (harcama hesap geçmişine yazılır)
  resource_ore_<cevher>                   kargodaki cevher (magaza.ORES türleri)
  resource_logfile                        log diskleri (kapı sayacı: profil kapilar.log_disk)
  ammunition_*                            cephane
  tech_*                                  teknoloji eşyaları (technology.py sayacı)
  equipment_* / drone_* / pet_*           envanterdeki takılı olmayan eşya örnekleri (profil esyalar)
  ship_*                                  etkin olmayan gemiler (Plus tarifleri taban gemiyi harcar; Aşama 6): gemi ve config'leri
                                          silinir, takılı eşyaları envantere döner, tasarımları gider
  ötekiler                                kaynak deposu (profil diger_esyalar: Assembly malzemeleri, anahtarlar, kuponlar …)
"""
import json, os

import ranks as RT
import technology as TECH

HERE = os.path.dirname(os.path.abspath(__file__))
ORES = {loot: int(t) for t, loot in json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
        ['cevherler']['turler'].items()}
CURRENCY = {'currency_credits': ('credits', 'kredi'), 'currency_uridium': ('uridium', 'uridyum')}
ITEM_PREFIXES = ('equipment_', 'drone_', 'pet_')
_CLIENT = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))['esyalar']


def client_item_ok(loot):
    """İstemcinin envanterine eşya olarak gidebilir mi. İstemcinin AssemblyInventoryIndex.UpdateItem'i cevherlerde (resource_ore_*:
    istemci AttributeOreCountUpdateCommand ile sayar) ve yığın sınırı olmayan ItemType'larda (Gold Pass, Lottery Capsule, Trinity VIP
    Badge) NullReference veriyor; kırılan öğe değişenler listesinde kaldığından sonraki her envanter güncellemesi de kırılıyor, Assembly
    dizini girişte hiç kurulmuyordu: Synthesis ve Assembly kaynak sayıları hep 0 (canlı deneme Ö6, H134; tek tek denendi: para
    güncellemesi kırmıyor, kayıttaki sunucu da gönderiyor)."""
    if loot.startswith('resource_ore_'):
        return False
    c = _CLIENT.get(loot)
    if loot.startswith('ship_') and c:           # Assembly'nin taban gemi sayacı: özellik listesi (traits) olan gemiler (hepsinde slotable)
        return any(k in c for k in ('yuvalar', 'satis', 'takilir', 'yigin'))
    return not (c and loot.startswith('resource_') and c.get('sinif') == 'ItemType' and 'yigin' not in c)


def client_filter(msgs):
    """Giden mesajlardan istemcinin envanterini kıran InventoryItemUpdatedCommand'lar (client_item_ok) atılır."""
    if not any(n == 'InventoryItemUpdatedCommand' for n, f in msgs):
        return msgs
    return [(n, f) for n, f in msgs if n != 'InventoryItemUpdatedCommand' or client_item_ok((f.get('item') or {}).get('lootId', ''))]


def free_items(p, loot):
    """Takılı olmayan eşya örnekleri (itemId listesi)."""
    eq, lv = p.equipped_ids(), p.d.get('yukseltme_seviye', {})
    ids = [int(i) for i, l in p.d['esyalar'].items() if l == loot and int(i) not in eq]
    return sorted(ids, key=lambda i: (int(lv.get(str(i), 0)), i))      # forum 160116: harcanan "stoğundaki en düşük seviyeli"


def count(p, loot):
    if loot in CURRENCY:
        return int(p.d['pilot'].get(CURRENCY[loot][0], 0))
    if loot in ORES:
        return p.ore_count(ORES[loot])
    if loot == 'resource_logfile':
        return int((p.d.get('kapilar') or {}).get('log_disk', 0))
    if loot.startswith('ammunition_'):
        return p.ammo(loot)
    if loot.startswith('tech_'):
        return TECH.count(p, loot)
    if loot.startswith(ITEM_PREFIXES):
        return len(free_items(p, loot))
    if loot.startswith('ship_'):
        return len(spare_ships(p, loot))
    return p.resource(loot)


def spare_ships(p, loot):
    """Harcanabilecek gemiler: bu türden, etkin olmayan (shipId listesi)."""
    return [sid for sid, s in p.d['gemiler'].items() if s['lootId'] == loot and sid != str(p.d['aktif_gemi'])]


def client_count(p, loot):
    """İstemcinin Assembly sayacına giden adet. Gemiler etkin olan dahil: istemci tarifin taban gemisini yalnız bu sayaçtan biliyor
    (gemileri eşya listesine kendisi eklemiyor); hiç gönderilmiyordu, Plus tariflerinde sahip olunan gemi "yok" görünüyordu
    (kullanıcı 2026-10-19: Solaris Plus). Etkin gemi harcanmaz: üretimde oyunun uyarısı (assembly.build)."""
    if loot.startswith('ship_'):
        return sum(1 for s in p.d['gemiler'].values() if s['lootId'] == loot)
    return count(p, loot)


def spendable(loot):
    return True


def missing(p, need):
    """Yetmeyenler {lootId: eksik} (harcanamayanlar dahil)."""
    return {k: n - count(p, k) for k, n in need.items() if count(p, k) < n or not spendable(k)}


def spend(p, need, reason='buy_SPECIAL', detail=''):
    """Hepsi varsa birlikte harcar -> harcananlar listesi; biri yetmezse hiçbiri (None)."""
    if missing(p, need):
        return None
    removed = []
    for loot, n in need.items():
        if n <= 0:
            continue
        p.ach('spend', loot=loot, adet=n)               # Pass görevleri: eşya harca (gorev_takip.py)
        if loot in CURRENCY:
            p.gain(**{CURRENCY[loot][1]: -n, 'neden': reason, 'detay': detail})
        elif loot in ORES:
            p.remove_ores({ORES[loot]: n})
        elif loot == 'resource_logfile':
            with p.lock:
                p.d['kapilar']['log_disk'] -= n
                p.dirty = True
        elif loot.startswith('ammunition_'):
            p.use_ammo(loot, n, event=False)            # already counted above as 'spend' (no double count)
        elif loot.startswith('tech_'):
            TECH.add(p, loot, -n)
        elif loot.startswith('ship_'):
            for sid in spare_ships(p, loot)[:n]:
                with p.lock:
                    del p.d['gemiler'][sid]                 # config'leri gider: takılı eşyalar envantere döner
                    p.dirty = True
        elif loot.startswith(ITEM_PREFIXES):
            for iid in free_items(p, loot)[:n]:
                with p.lock:
                    del p.d['esyalar'][str(iid)]
                    p.d.get('esya_seviye', {}).pop(str(iid), None)
                    p.dirty = True
                removed.append(iid)
        else:
            p.add_resource(loot, -n)
    return removed


def update_msgs(m, p, loots, removed=()):
    """Değişen eşyaların arayüz güncellemesi (mağaza yardımcılarıyla): para, kargo, cephane, kaynak deposu, silinen örnekler."""
    msgs = [('InventoryItemRemovedCommand', {'itemId': iid}) for iid in removed]
    if not m:
        return msgs
    if any(l in CURRENCY for l in loots):
        msgs += m.money_msgs()
    if any(l.startswith('ship_') for l in loots):
        msgs.append(m.ships_cmd())                        # harcanan gemi hangar listesinden düşer
        msgs += m.ship_count_msgs([l for l in loots if l.startswith('ship_')])     # Assembly sayacı
    ores = sorted(ORES[l] for l in loots if l in ORES)
    if ores:
        msgs += [('AttributeOreCountUpdateCommand', {'oreCountList': p.d['madenler']}), m.ore_pack(ores)]
    for loot in loots:
        if loot in CURRENCY or loot in ORES or loot.startswith(ITEM_PREFIXES + ('ship_',)):
            continue
        n = count(p, loot)
        if loot.startswith('ammunition_'):
            st = p.menu_status(loot)
            msgs += [('MenuItemStatusCommand', st)] if st else []
        elif loot.startswith('tech_'):
            st = p.menu_status(loot)                    # kısayol çubuğundaki teknoloji öğesinin sayacı
            msgs += [('MenuItemStatusCommand', st)] if st else []
            continue
        iid = m.item_id(loot)
        msgs += [m.inv_item(iid, loot, n), m.pack([m.hangar_item(iid, loot, n)])]
    return msgs


def note_spend(p, need, reason):
    """Hesap geçmişi dışındaki harcamalar için seyir defterine bir satır (gerekirse)."""
    RT.note(p, reason, ','.join('%s:%d' % kv for kv in need.items()))
