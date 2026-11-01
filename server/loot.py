"""Anahtarlı ganimet kutuları (yol haritası Aşama 5; veri data/boxes.json <- tools/boxes.py, wiki + istemcinin adları).

Haritada AddBoxCommand {boxType: PIRATE_BOOTY | PIRATE_BOOTY_GOLD | PIRATE_BOOTY_RED | PIRATE_BOOTY_BLUE | BLACK_BOOTY_BOX |
PIRATE_BOOTY_SILVER | UNSTABLE_BLACKLIGHT_CACHE | BLACKLIGHT-CRYPT | ASTRAL_BOOTY_BOX | ASTRAL_PRIME_BOOTY_BOX | MASQUE_BOOTY_BOX
(Apocalypse) | PERSEUS_BLESSING_BOOTY_BOX | PROMETHEUS_BOOTY_BOX | LAUREL_BOX (son ikisi E8'in etkinliklerinde) | etkinlik kutuları};
toplarken (CollectBoxRequest) türün anahtarı yoksa kutu yerinde
kalır ve istemcinin metni gelir (0|A|STM|msg_loot_failed_no_booty-key-…); varsa bir anahtar harcanır, HUD sayacı güncellenir
("0|A|<kod>|<kalan>"), içerikten bir ödül çekilir (ağırlıkla; sahip olunan gemi/tasarım/dron çekilmez; Epic paketi çıkarsa
parçalarının hepsi) ve mağazanın ödül işleviyle verilir. Black Light Cache'teki tasarıma zaten sahipse 10.000 uridyum (wiki).
Yeşil anahtar yoksa ve ayarlarda otomatik alım açıksa (autoBuyGreenBootyKeys) mağaza fiyatıyla bir anahtar alınır.
Haritalar: X-2..X-8 (1-2 … 3-8), X-1..X-8 (Perseus, Laurel), 4-X, 5-X (5-1..5-3), 5-4 (gümüş), BL (BL-1..3). Altın kutular iki
haftada bir cuma (wiki).
"""
import json, os, random, re, time
import game_data as DATA

import event_appearances as EG

HERE = os.path.dirname(os.path.abspath(__file__))
K = DATA.load('boxes.json')
BOXES = K['kutular']
for _k, _b in BOXES.items():                 # etkinlik görünümleri: kutunun yerel tasarım satırları (wiki tablosunun dışında; pick_all)
    _b['yerel'] = EG.box_rows(_k)
PACKAGE = 'paket'                               # Epic paketi satırı: ['paket', [[lootId, adet], ...], ağırlık]; açılışta parçaların hepsi
MAPS = {k: re.compile(v) for k, v in K['haritalar'].items()}
GREEN_KEY = 'resource_booty-key'
OPEN_SEC = 3                                   # açılış süresi (tam saniye: istemcinin sayacı): resmî ~5 sn, kullanıcının kararı 3 sn
BL_CACHE = 'UNSTABLE_BLACKLIGHT_CACHE'
KEYS = {}                                     # anahtar -> onu kullanan ilk kutu türü (HUD kodu için)
for _k, _b in BOXES.items():
    KEYS.setdefault(_b['anahtar'], _k)
CODES = {b['code']: KEYS[b['anahtar']] for b in BOXES.values() if b.get('code')}   # HUD kodu -> kutu türü (girişteki "0|A|BK…|0" satırları)


def active(kind, now=None):
    """Takvim (kutunun 'takvim'i event_calendar.py'deki etkinliğin adı): altın kutu ayın 2. ve 4. cuması, Obsidian / R&B / Apocalypse
    haftalık rotasyonda (E8), etkinlik kutuları (Empyrian, Prosperous, Lucent Egg) etkinlik sürerken; liste: biri sürerken (Battle
    Pass Box)."""
    return bool(BOXES[kind].get('takvim') is None or box_event(kind, now))


def box_event(kind, now=None):
    """Kutunun takvimindeki etkin etkinlik (yoksa None)."""
    import event_calendar as CAL
    cal = BOXES[kind].get('takvim')
    return next((k for k in (cal if isinstance(cal, list) else [cal]) if k in CAL.EVENTS and CAL.is_active(k, now)), None)


def spawns(map_name, now=None):
    """Bu haritada doğan kutular -> [(tür, adet)]."""
    return [(k, b['adet']) for k, b in BOXES.items()
            if active(k, now) and any(MAPS[m].match(map_name or '') for m in b['haritalar'])]


def respawn_delay(kind):
    lo, hi = BOXES[kind]['yeniden_sn']
    return random.uniform(lo, hi)


def owned(p, loot):
    """Tekil ödüle sahip mi: gemi, gemi tasarımı (gemide ya da depoda), dronlar, dron ve P.E.T. tasarımları (envanterde ya da depoda)."""
    if '_design_' in loot:
        if any(loot in s.get('designs', []) for s in p.d['gemiler'].values()):
            return True
        return p.resource(loot) > 0
    if loot.startswith('ship_'):
        return any(s['lootId'] == loot for s in p.d['gemiler'].values())
    if loot.startswith('drone_') and any(d.get('lootId') == loot for d in p.d.get('dronlar', [])):
        return True
    return p.resource(loot) > 0 or loot in p.d.get('esyalar', {}).values()     # dron ve P.E.T. tasarımları envanterde


def unique(loot):
    return loot.startswith(tuple(K['single'])) or '_design_' in loot


def design(r):
    """Tasarım kovasındaki satır: tekil ödül (gemi, tasarım, dron) ya da Epic paketi."""
    return r[0] == PACKAGE or unique(r[0])


def gone(p, r):
    """Satır çekilemez mi: sahip olunan tekil ödül ya da parçalarının hepsine sahip olunan paket."""
    return all(owned(p, l) for l, _ in r[1]) if r[0] == PACKAGE else unique(r[0]) and owned(p, r[0])


def pick_all(p, kind, rng=random):
    """İçerikten ödül -> [(lootId, adet)]: bir satır; Epic paketi çıkarsa sahip olunmayan parçalarının hepsi. Sahip olunan tekil
    ödüller çekilmez; 'odul_etkinlik'li kutuda (Battle Pass Box) süren etkinliğin satırları. Yerel tasarım satırları ('yerel': kutu_ek
    ve etkinlik görünümleri; wiki tablosunda yok) tasarım çekilişini tablonun tasarımlarıyla paylaşır: tasarımların toplam şansı
    wiki'deki gibi kalır, yalnız aralarında bölüşülür; tablonun öteki satırlarının şansı bozulmaz."""
    box = BOXES[kind]
    rows = box['odul'] or box.get('reward_event', {}).get(box_event(kind)) or []
    if not rows:                             # etkinlik bitmişken toplanan Battle Pass Box: anahtar geri
        return [(box['anahtar'], 1)]
    if kind == BL_CACHE:                     # wiki: tasarım rastgele, zaten varsa 10.000 uridyum
        loot = rng.choice(rows)[0]
        return [('currency_uridium', K['bl_repeat_uridium']) if owned(p, loot) else (loot, 1)]
    pool = [r for r in rows if not gone(p, r)] or [r for r in rows if not design(r)]
    local = [r for r in box['yerel'] if not owned(p, r[0])]
    wd, wl = sum(r[2] for r in pool if design(r)), sum(r[2] for r in local)
    k = wd / (wd + wl) if wd else 1.0
    pool += local
    row = rng.choices(pool, [r[2] * k if design(r) else r[2] for r in pool])[0]
    if row[0] == PACKAGE:
        return [(l, n) for l, n in row[1] if not (unique(l) and owned(p, l))]
    loot, amount = row[0], row[1]
    if isinstance(amount, list):
        amount = rng.randint(amount[0], amount[1])
    return [(loot, int(amount))]


def pick(p, kind, rng=random):
    """pick_all'un ilk ödülü -> (lootId, adet) (paketsiz kutularda tek ödül)."""
    return pick_all(p, kind, rng)[0]


def key_line(p, kind):
    """HUD'daki anahtar sayacı (eski protokol: SetAttributeAssemblyHelper.AssembleBootyKeysUpdate, kod -> Hero.BootyKeys*Amount: BK yeşil,
    BKP Prosperous, BKPR Prometheus; yeşil BKP gidiyordu, istemci Prosperous yazıyordu: kullanıcı bildirimi 2026-10-24); sayacı olmayan
    anahtarda (Battle Pass Key) None."""
    b = BOXES[kind]
    return '0|A|%s|%d' % (b['code'], p.resource(b['anahtar'])) if b.get('code') else None
