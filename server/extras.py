"""Ekstralar ve CPU'lar (veri items.json "ekstralar" ← belgeler/wiki/extras_cpu_tech.md; yalnız etkin config'te takılı olanlar etkili).

Pasif etkiler (bu modül sorgular, ilgili modüller uygular):
  ek_yuva          ekstra yuvası (SL-01..04 +2/+4/+6/+10; config başına bir yuva CPU'su, o config'in yuvası)    magaza.capacity
  kargo_carpan     kargo alanı çarpanı (G3X-CRGO-X)                                                          magaza.apply_stats
  roket_bekleme    roket beklemesi çarpanı (R0K-T01 0,5)                                                     dunya.rocket
  mayin_bekleme    mayın ve mayından yapılan eşyaların beklemesi (MIN-T01 -%25, MIN-T02 -%50)                dunya (mayınlar)
  oto_onarim       can eksilince onarım robotu kendiliğinden çalışır (NC-RRB-X)                              dunya.auto_tick
  oto_alim         {type: lazer|roket|yakit, esik, adet}: eşiğin altına inince alır (ALB-X, RB-X, FB-X)       dunya.auto_tick
  oto_lab          [parça]: yükseltme bitince aynı cevherle ya da (en_iyi) en iyi cevherle yeniden (NC-AWL/AWR/AWB/AGB)
  her_yerde_satis  cevher her yerde satılır, adet sınırı (HM-7, 100 satış)                                  dunya.at_trade
Etkin olanlar (kısayol çubuğundan; combat_items.py):
  atlama           {haritalar | yasak}: ana haritaya atlama (JP-01 10, JP-02 20 hak); gelismis_atlama: AJP-01 istenen haritaya
  gizlenme         gizlenme CPU'su (CL04K-XS 1, M 10, XL 50 hak)       nisan  AIM-01/02 ıska oranı -%25/-%50 (10 Xenomit)
  aninda_kalkan    Insta-Shield (ISH-01)                                akilli_bomba  Smart Bomb (SMB-01)
  oto_roket        AROL-X: lazer saldırısında seçili roket             oto_fircatici  RL-LB1: lazer saldırısında dolu fırlatıcı
Hak (hak): profilde (ekstra_haklari), ilk takılışta tam; satın alınınca eklenir (recharge).
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
E = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
X = E.get('extras', {})


def equipped(p, sid=None):
    """Etkin (ya da verilen) geminin etkin config'indeki ekstraların lootId'leri; dronlara takılı ekstralar (CPU'lar) da sayılır."""
    if sid is None or str(sid) == str(p.d['active_ship']):
        own, drones = list(p.d.get('equipment', {}).get('extra', [])), p.d.get('drone_equipment', [])
    else:
        own, drones = p.loadout(sid).get('extra', []), [(x, loots) for x, loots in p.drone_loadout(sid)]
    return own + [l for _, loots in drones for l in loots if l.startswith('equipment_extra_')]


def props(p, key, sid=None):
    """Takılı ekstraların bir özelliği: [(lootId, değer)]."""
    return [(l, X[l][key]) for l in equipped(p, sid) if l in X and key in X[l]]


def has(p, key, sid=None):
    return bool(props(p, key, sid))


def owned(p, loot):
    """Ekstra envanterde ya da takılı mı (takılması gerekmeyenler: HM-7 ticaret dronu, satın alınınca kısayol çubuğunda görünür)."""
    return loot in p.d['items'].values() or loot in equipped(p)


def slot_bonus(p, sid=None, cid=None):
    """Yuva CPU'sunun ekstra yuvası: geminin bir config'inde (varsayılan: etkin gemi, etkin config) takılı olanın."""
    return slot_bonus_of(equipped(p, sid) if cid is None else p.loadout(sid, cid).get('extra', []))


def slot_bonus_of(loots):
    """Ekstraların arasındaki yuva CPU'sunun (SL-01..04) bonusu (config başına bir tane takılır)."""
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
    """Hakkı sınırsız mı: HM-7 için Goliath'ın Amber, Jade ya da Sapphire tasarımına sahip olanlar (wiki: eski kural; istemci
    items_equipment_extra_hmd-07_hint_unlimited "You already have an unlimited trade drone")."""
    designs = X.get(loot, {}).get('unlimited_design')
    return bool(designs) and any(d in s.get('designs', []) for s in p.d['ships'].values() for d in designs)


def uses(p, loot):
    """Kullanım sınırlı ekstranın kalan hakkı (HM-7 satış, Jump CPU atlama, gizlenme): profilde, ilk takılışta tam."""
    if unlimited(p, loot):
        return UNLIMITED
    st = p.d.setdefault('extra_uses', {})
    if loot not in st:
        st[loot] = X.get(loot, {}).get('right', 0)
    return st[loot]


def recharge(p, loot, n=1):
    """Hakkı olan ekstra satın alındı: n tanesinin hakkı eklenir."""
    if 'right' not in X.get(loot, {}):
        return
    with p.lock:
        st = p.d.setdefault('extra_uses', {})
        st[loot] = st.get(loot, 0) + X[loot]['right'] * n
        p.dirty = True


def attached(p, loot):
    """Otomatik alım CPU'sunun hangarda seçilen cephanesi (HangarShipAutoBuyCpuAmmoRequest) ya da None."""
    return p.d.get('auto_buy_ammo', {}).get(loot)


def use(p, loot, n=1):
    if unlimited(p, loot):
        return UNLIMITED
    with p.lock:
        left = uses(p, loot) - n
        p.d['extra_uses'][loot] = max(0, left)
        p.dirty = True
    return max(0, left)
