"""Botların bildiği oyun: gemiler, lazerler, jeneratörler, dronlar (fiyatları mağazanın kataloğundan, değerleri items.json'dan),
geminin güç değerleri, haritaların zorluğu ve beklenen geliri, portal ağı.

Hepsi veriden üretilir: yeni gemi, lazer ya da uzaylı eklenince (Dünya Editörü dahil) botlar onu kendiliğinden tanır. Bot
donanımı yalın bir sözlüktür (ekip): {'gemi': loot, 'lazer': {loot: adet}, 'kalkan': {loot: adet}, 'hiz': {loot: adet},
'dron': {loot: adet}, 'cephane': loot}. donat() eldeki eşyayı yuvalara en iyi biçimde yerleştirir.
"""
import functools, json, math, os
from collections import deque

import game_data as DATA
import paths as PTH
import map_links as H
import settings as SET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
NPC = DATA.load('npc.json')
COMBAT = NPC['savas']

# botların dolaştığı haritalar: X-1..X-8, 4-1..4-5 (korsan haritaları anahtar, kapılar ve mod haritaları bilet ister)
MAPS = tuple(range(1, 30))
LASER_INTERVAL = COMBAT['lazer_aralik_sn']
NPC_INTERVAL = COMBAT['npc_saldiri_aralik_sn']
SEARCH_SEC = 9.0             # iki uzaylı arasında hedef arama ve yaklaşma (gözlem: 1-x'te 6-12 sn)
JUMP_SEC = 45.0           # portaldan portala uçuş + atlama (harita başına ortalama)
REPAIR_RATE = 0.012        # savaş dışında saniyede yenilenen can+kalkan payı (kalkan yenilenmesi + onarım robotu, kabaca)
AMMO = ('ammunition_laser_lcb-10', 'ammunition_laser_mcb-25', 'ammunition_laser_mcb-50')

_price = None


def prices():
    """lootId -> ('C' | 'U', fiyat): mağazanın standart kataloğu, Dünya Editörü'nün fiyatı ve satıştan kaldırması dahil."""
    global _price
    if _price is None:
        import shop as SHP
        p = PTH.template('yanitlar.json') if 'yanitlar.json' in PTH.TEMPLATES else os.path.join(HERE, 'data', 'yanitlar.json')
        y = {}
        if p and os.path.exists(p):
            with open(p, encoding='utf8') as f:
                y = json.load(f)
        out = {i['lootId']: (i['para'], i['fiyat']) for c in SHP.catalog(y).values() for i in c}
        for loot, w in SHP.WORLD_SHOP.items():
            if w.get('satista') is False:
                out.pop(loot, None)
            elif w.get('fiyat') is not None and loot in out:
                out[loot] = (w.get('para') or out[loot][0], w['fiyat'])
        for loot, v in ITEMS['dronlar'].items():
            out[loot] = ('C' if v['para'] == 'credits' else 'U', v['fiyatlar'][0])
        _price = out
    return _price


def price(loot, owner=0):
    """Satın alma fiyatı ('C' | 'U', tutar) ya da None. Dronlar kaçıncı olduğuna göre (sahip: eldeki aynı dron sayısı)."""
    d = ITEMS['dronlar'].get(loot)
    if d:
        if d.get('tek') and owner:
            return None
        return ('C' if d['para'] == 'credits' else 'U'), d['fiyatlar'][min(owner, len(d['fiyatlar']) - 1)]
    return prices().get(loot)


def ships():
    """Satın alınabilen temel gemiler (tasarımlar hariç) -> items.json değerleri."""
    return {k: v for k, v in ITEMS['gemiler'].items() if 'taban' not in v and price(k)}


def lasers():
    return {k: v['hasar'] for k, v in ITEMS['lazerler'].items() if price(k)}


def shield_generators():
    return {k: v for k, v in ITEMS['kalkan_jeneratorleri'].items() if price(k)}


def speed_generators():
    return {k: v['hiz'] for k, v in ITEMS['hiz_jeneratorleri'].items() if price(k)}


def new_gear():
    return {'gemi': 'ship_phoenix', 'lazer': {'equipment_weapon_laser_lf-1': 1}, 'kalkan': {}, 'hiz': {}, 'dron': {},
            'cephane': AMMO[0]}


# ------------------------------------------------------------------------------------------------------------ güç
def outfit(gear, shield_share=0.6):
    """Eldeki eşyanın yuvalara yerleşimi -> {'lazer': [hasar...], 'kalkan': [(kalkan, emme)...], 'hiz': [hız...], ...}.
    Lazer yuvası: gemi + dronlar (Flax 1, Iris 2); jeneratör yuvası gemininki, kalkan_payi kadarı kalkana (kişiliğe göre)."""
    g = ITEMS['gemiler'].get(gear['gemi']) or ITEMS['gemiler']['ship_phoenix']
    drone_slots = sum(ITEMS['dronlar'].get(d, {}).get('yuva', 1) * n for d, n in gear.get('dron', {}).items())
    lasers = sorted((ITEMS['lazerler'][l]['hasar'] for l, n in gear.get('lazer', {}).items() for _ in range(n) if l in ITEMS['lazerler']),
                reverse=True)[:g['laser'] + drone_slots]
    shields = sorted(((ITEMS['kalkan_jeneratorleri'][k]['kalkan'], ITEMS['kalkan_jeneratorleri'][k]['emme'])
                 for k, n in gear.get('kalkan', {}).items() for _ in range(n) if k in ITEMS['kalkan_jeneratorleri']), reverse=True)
    speeds = sorted((ITEMS['hiz_jeneratorleri'][k]['hiz'] for k, n in gear.get('hiz', {}).items() for _ in range(n)
                 if k in ITEMS['hiz_jeneratorleri']), reverse=True)
    slot = g['generators']
    nk = min(len(shields), max(int(round(slot * shield_share)), slot - len(speeds)))
    n_speed = min(len(speeds), slot - nk)
    return {'gemi': g, 'lazer': lasers, 'kalkan': shields[:nk], 'hiz': speeds[:n_speed], 'lazer_yuva': g['laser'] + drone_slots, 'jen_yuva': slot}


def drone_set(gear):
    """Bütün dronlar aynı bonuslu tasarımdaysa (Havoc, Hercules …) takım bonusu (profil.design_mods ile aynı kural), yoksa {}."""
    n = sum(gear.get('dron', {}).values())
    t = ((gear.get('dron_tasarim') or {}).get('tasarim') or [])[:n]
    return ITEMS['dron_tasarimlari'].get(t[0], {}).get('takim', {}) if n and len(t) == n and t[0] and len(set(t)) == 1 else {}


def values(gear, shield_share=0.6):
    """Botun savaş değerleri: dps (saniyede hasar, uzaylıya), can, kalkan, emme, ehp (etkin can), hız, güç puanı."""
    y = outfit(gear, shield_share)
    multiplier = ITEMS['lazer_cephane'].get(gear.get('cephane'), {}).get('carpan', 1)
    damage = sum(y['lazer']) * multiplier * 0.88 * COMBAT['lazer_isabet']          # 0,88: rastgelenin ortalaması (0,76-1,0)
    set_bonus = drone_set(gear)
    drone_slots = sum(ITEMS['dronlar'].get(d, {}).get('yuva', 1) * n for d, n in gear.get('dron', {}).items())
    damage *= 1 + set_bonus.get('dron_lazer', 0) * min(1.0, drone_slots / max(1, len(y['lazer'])))        # Havoc: yalnız dron lazerlerine
    dps = damage / LASER_INTERVAL
    shield = sum(k for k, _ in y['kalkan'])
    absorb = (sum(k * e for k, e in y['kalkan']) / shield) if shield else 0.0
    hp = y['gemi']['hp'] * (1 + set_bonus.get('can', 0))               # Hercules takımı: +%20 can
    ehp = hp + shield * 2.5 * min(1.0, absorb + 0.2)         # kalkan hasarın çoğunu emer ve hedefler arasında dolar
    speed = y['gemi']['temel_hiz'] + sum(y['hiz'])
    return dict(dps=dps, can=hp, kalkan=shield, emme=absorb, ehp=ehp, hiz=speed, guc=power_score(dps, ehp),
                lazer=len(y['lazer']), lazer_yuva=y['lazer_yuva'], jen=len(y['kalkan']) + len(y['hiz']), jen_yuva=y['jen_yuva'])


def power_score(dps, ehp):
    """Tek sayıda güç: dps ile etkin canın geometrik ortası (Phoenix + LF-1 ≈ 4, LF-3'lü, B02'li, 8 Iris'li Goliath ≈ 100)."""
    return math.sqrt(max(dps, 0) * max(ehp, 0)) / 490.0


# ------------------------------------------------------------------------------------------------------------ haritalar
_npc_cache = {}
_map_npc_cache = {}


def npc_value(tip):
    """Uzaylının bot için değerleri (salt okunur; npc.json içe aktarmada bir kez yüklenir, sonuç önbellekte)."""
    if tip in _npc_cache:
        return _npc_cache[tip]
    t = NPC['tipler'].get(tip)
    v = None if not t else dict(
        tip=tip, ad=t['ad'], ehp=t['hp'] + t['kalkan'], dps=t['hasar'] * t.get('isabet', COMBAT['npc_isabet'])
        / t.get('atis_aralik_sn', NPC_INTERVAL), saldirgan=bool(t.get('saldirgan')), odul=t['odul'], hiz=t['hiz'],
        kimlik=t.get('npc_kimlik', 0))
    _npc_cache[tip] = v
    return v


def map_npcs(map_id):
    """[(npc değeri, adet)]: haritanın sürekli uzaylıları (npc.json haritalar; salt okunur, önbellekte)."""
    if map_id in _map_npc_cache:
        return _map_npc_cache[map_id]
    out = []
    for r in (NPC['haritalar'].get(str(map_id)) or {}).get('npc', []):
        v = npc_value(r['tip'])
        if v and r.get('adet', 0) > 0:
            out.append((v, r['adet']))
    _map_npc_cache[map_id] = out
    return out


_map_cache = {}


def evaluate_map(map_id, dps, ehp, courage=0.5):
    """Bu güçteki bir geminin haritada uzaylı kasması -> {saat_ep, saat_kredi, saat_uridyum, saat_onur, olum_saat (saatte ölüm
    beklentisi), hedefler [tip], oldurme {tip: saatte öldürme}, zorluk (0 kolay .. 1+ ölümcül)}. cesaret (0-1): öldürmeye değer bulduğu en tehlikeli uzaylı
    (alınan hasar / etkin can sınırı). Uzaylı başına: öldürme süresi = etkin can / dps; alınan hasar = uzaylının dps'i x süre (yalnız
    saldırgansa ya da vurulunca karşılık verdiği için hep); arada onarım. Sonuçlar (harita, yuvarlanmış güç) için önbellekte."""
    key = (map_id, int(dps // 5), int(ehp // 5000), round(courage, 1))
    if key in _map_cache:
        return _map_cache[key]
    limit = 0.25 + 0.5 * courage
    total = dict(ep=0.0, kredi=0.0, uridyum=0.0, onur=0.0)
    duration = 0.0
    death = 0.0
    targets = []
    kills = {}
    heavy = 0.0
    for v, count in map_npcs(map_id):
        if dps <= 0:
            break
        t = v['ehp'] / dps
        claimed = v['dps'] * t
        ratio = claimed / max(ehp, 1)
        if v['saldirgan']:
            heavy += count * min(2.0, ratio)
        if ratio > limit:
            continue
        targets.append(v['tip'])
        kind = t + SEARCH_SEC + claimed / max(ehp * REPAIR_RATE, 1)
        kills[v['tip']] = count
        for k in total:
            total[k] += v['odul'].get(k, 0) * count
        duration += kind * count
        death += count * max(0.0, ratio - 0.15) ** 2 * 0.15        # ara sıra birden çok uzaylı ve kötü şans
    difficulty = heavy / 40.0
    if duration <= 0:
        r = dict(saat_ep=0, saat_kredi=0, saat_uridyum=0, saat_onur=0, olum_saat=1.0 + difficulty, hedefler=[], zorluk=difficulty + 1,
                 oldurme={})
    else:
        k = 3600.0 / duration
        r = dict(saat_ep=total['ep'] * k, saat_kredi=total['kredi'] * k, saat_uridyum=total['uridyum'] * k,
                 saat_onur=total['onur'] * k, olum_saat=death * k / max(1, len(targets)) + difficulty * 0.4, hedefler=targets,
                 zorluk=difficulty, oldurme={t: n * k for t, n in kills.items()})
    if len(_map_cache) > 20000:
        _map_cache.clear()
    _map_cache[key] = r
    return r


_ENTRY = {}


def can_enter(map_id, firma, level):
    k = (map_id, firma, bool(SET.get('seviye_kisiti_yok')))     # panelin seviye kısıtı ayarı değişirse yeni anahtar
    if k not in _ENTRY:
        _ENTRY[k] = H.level_required(map_id, firma)
    return level >= _ENTRY[k]


def neighbors(map_id, firma):
    """Portalla gidilen haritalar (ücretli / anahtarlı portallar hariç)."""
    return [g['hedef'] for g in H.gates(map_id, firma) if not g.get('ucret') and g['hedef'] in MAPS
            and g.get('yalniz_firma') in (None, firma)]


def route(source, target, firma, level):
    """En kısa portal yolu [kaynak, ..., hedef] (girilemeyen haritalardan geçmez) ya da None."""
    r = _route(int(source), int(target), firma, level, bool(SET.get('seviye_kisiti_yok')))     # ayar değişirse yeni anahtar (girebilir)
    return list(r) if r is not None else None


@functools.lru_cache(maxsize=8192)
def _route(source, target, firma, level, _unrestricted=False):
    if source == target:
        return (source,)
    previous = {source: None}
    q = deque([source])
    while q:
        m = q.popleft()
        for n in neighbors(m, firma):
            if n in previous or not can_enter(n, firma, level):
                continue
            previous[n] = m
            if n == target:
                out = [n]
                while previous[out[-1]] is not None:
                    out.append(previous[out[-1]])
                return tuple(out[::-1])
            q.append(n)
    return None


def ev(firma):
    """Firmanın üs haritası (X-1)."""
    return {1: 1, 2: 5, 3: 9}[firma]


# ------------------------------------------------------------------------------------------------------------ kargo
CARGO_ORE = frozenset((0, 1, 2, 4, 5, 6, 7, 8, 28))       # kargoda yer kaplayanlar (profil.CARGO_ORES; Xenomit kaplamaz)


def sell_maps(firma):
    """Cevherin satıldığı kendi istasyonları: X-1 ve X-8 (oyunda ticaret yalnız istasyonda)."""
    return {1: (1, 20), 2: (5, 24), 3: (9, 28)}[firma]


def ore_prices(honor, multiplier=1.0):
    """Rafineri fiyatları: taban + onur/bölen, tavanlı (dunya.ore_prices ile aynı formül)."""
    out = {}
    for t, (base, divisor, cap) in ITEMS['cevherler']['fiyatlar'].items():
        v = min(cap, base + (int(max(0, honor) // divisor) if divisor else 0))
        out[int(t)] = int(round(v * multiplier))
    return out


def cargo_capacity(gear):
    from . import extras as EX
    return int(int((ITEMS['gemiler'].get(gear['gemi']) or ITEMS['gemiler']['ship_phoenix']).get('kargo') or 100)
               * EX.cargo_multiplier(gear))                  # G3X-CRGO-X: iki katı


def npc_cargo(tip, level=1, game_map=None):
    """Uzaylının kargo kutusundaki cevherler {tür: adet}; X-1 haritalarında yüksek seviyede azalır (npc.json x1_kargo)."""
    cargo = {int(k): int(v) for k, v in ((NPC['tipler'].get(str(tip)) or {}).get('kargo') or {}).items() if int(v) > 0}
    if game_map is not None and H.map_class(game_map) == 'X-1':
        import settings as SET
        if SET.get('x1_kargo'):
            f = next((k for l, k in reversed(COMBAT['x1_kargo']) if level >= l), 1)
            cargo = {t: int(v * f) for t, v in cargo.items() if int(v * f) > 0}
    return cargo


def pvp_map(map_id, firma):
    """Başka firmanın oyuncularıyla karşılaşılan harita mı (kendi X-1/X-2'si dışında her yer; 4-X ve başka firmanın haritaları)."""
    c = H.company(map_id)
    return c != firma or H.map_class(map_id) not in ('X-1', 'X-2')
