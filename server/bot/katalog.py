"""Botların bildiği oyun: gemiler, lazerler, jeneratörler, dronlar (fiyatları mağazanın kataloğundan, değerleri esyalar.json'dan),
geminin güç değerleri, haritaların zorluğu ve beklenen geliri, portal ağı.

Hepsi veriden üretilir: yeni gemi, lazer ya da uzaylı eklenince (Dünya Editörü dahil) botlar onu kendiliğinden tanır. Bot
donanımı yalın bir sözlüktür (ekip): {'gemi': loot, 'lazer': {loot: adet}, 'kalkan': {loot: adet}, 'hiz': {loot: adet},
'dron': {loot: adet}, 'cephane': loot}. donat() eldeki eşyayı yuvalara en iyi biçimde yerleştirir.
"""
import functools, json, math, os
from collections import deque

import veri as VERI
import yollar as YOL
import harita as H
import ayar as AY

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESYA = json.load(open(os.path.join(HERE, 'data', 'esyalar.json'), encoding='utf8'))
NPC = VERI.yukle('npc.json')
SAVAS = NPC['savas']

# botların dolaştığı haritalar: X-1..X-8, 4-1..4-5 (korsan haritaları anahtar, kapılar ve mod haritaları bilet ister)
HARITALAR = tuple(range(1, 30))
LAZER_ARALIK = SAVAS['lazer_aralik_sn']
NPC_ARALIK = SAVAS['npc_saldiri_aralik_sn']
ARAMA_SN = 9.0             # iki uzaylı arasında hedef arama ve yaklaşma (gözlem: 1-x'te 6-12 sn)
ATLAMA_SN = 45.0           # portaldan portala uçuş + atlama (harita başına ortalama)
ONARIM_ORAN = 0.012        # savaş dışında saniyede yenilenen can+kalkan payı (kalkan yenilenmesi + onarım robotu, kabaca)
CEPHANE = ('ammunition_laser_lcb-10', 'ammunition_laser_mcb-25', 'ammunition_laser_mcb-50')

_fiyat = None


def fiyatlar():
    """lootId -> ('C' | 'U', fiyat): mağazanın standart kataloğu, Dünya Editörü'nün fiyatı ve satıştan kaldırması dahil."""
    global _fiyat
    if _fiyat is None:
        import magaza as MG
        p = YOL.sablon('yanitlar.json') if 'yanitlar.json' in YOL.SABLONLAR else os.path.join(HERE, 'data', 'yanitlar.json')
        y = {}
        if p and os.path.exists(p):
            with open(p, encoding='utf8') as f:
                y = json.load(f)
        out = {i['lootId']: (i['para'], i['fiyat']) for c in MG.katalog(y).values() for i in c}
        for loot, w in MG.DUNYA_MAGAZA.items():
            if w.get('satista') is False:
                out.pop(loot, None)
            elif w.get('fiyat') is not None and loot in out:
                out[loot] = (w.get('para') or out[loot][0], w['fiyat'])
        for loot, v in ESYA['dronlar'].items():
            out[loot] = ('C' if v['para'] == 'credits' else 'U', v['fiyatlar'][0])
        _fiyat = out
    return _fiyat


def fiyat(loot, sahip=0):
    """Satın alma fiyatı ('C' | 'U', tutar) ya da None. Dronlar kaçıncı olduğuna göre (sahip: eldeki aynı dron sayısı)."""
    d = ESYA['dronlar'].get(loot)
    if d:
        if d.get('tek') and sahip:
            return None
        return ('C' if d['para'] == 'credits' else 'U'), d['fiyatlar'][min(sahip, len(d['fiyatlar']) - 1)]
    return fiyatlar().get(loot)


def gemiler():
    """Satın alınabilen temel gemiler (tasarımlar hariç) -> esyalar.json değerleri."""
    return {k: v for k, v in ESYA['gemiler'].items() if 'taban' not in v and fiyat(k)}


def lazerler():
    return {k: v['hasar'] for k, v in ESYA['lazerler'].items() if fiyat(k)}


def kalkanlar():
    return {k: v for k, v in ESYA['kalkan_jeneratorleri'].items() if fiyat(k)}


def hizlar():
    return {k: v['hiz'] for k, v in ESYA['hiz_jeneratorleri'].items() if fiyat(k)}


def yeni_ekip():
    return {'gemi': 'ship_phoenix', 'lazer': {'equipment_weapon_laser_lf-1': 1}, 'kalkan': {}, 'hiz': {}, 'dron': {},
            'cephane': CEPHANE[0]}


# ------------------------------------------------------------------------------------------------------------ güç
def donat(ekip, kalkan_payi=0.6):
    """Eldeki eşyanın yuvalara yerleşimi -> {'lazer': [hasar...], 'kalkan': [(kalkan, emme)...], 'hiz': [hız...], ...}.
    Lazer yuvası: gemi + dronlar (Flax 1, Iris 2); jeneratör yuvası gemininki, kalkan_payi kadarı kalkana (kişiliğe göre)."""
    g = ESYA['gemiler'].get(ekip['gemi']) or ESYA['gemiler']['ship_phoenix']
    dron_yuva = sum(ESYA['dronlar'].get(d, {}).get('yuva', 1) * n for d, n in ekip.get('dron', {}).items())
    lz = sorted((ESYA['lazerler'][l]['hasar'] for l, n in ekip.get('lazer', {}).items() for _ in range(n) if l in ESYA['lazerler']),
                reverse=True)[:g['laser'] + dron_yuva]
    ks = sorted(((ESYA['kalkan_jeneratorleri'][k]['kalkan'], ESYA['kalkan_jeneratorleri'][k]['emme'])
                 for k, n in ekip.get('kalkan', {}).items() for _ in range(n) if k in ESYA['kalkan_jeneratorleri']), reverse=True)
    hz = sorted((ESYA['hiz_jeneratorleri'][k]['hiz'] for k, n in ekip.get('hiz', {}).items() for _ in range(n)
                 if k in ESYA['hiz_jeneratorleri']), reverse=True)
    yuva = g['generators']
    nk = min(len(ks), max(int(round(yuva * kalkan_payi)), yuva - len(hz)))
    nh = min(len(hz), yuva - nk)
    return {'gemi': g, 'lazer': lz, 'kalkan': ks[:nk], 'hiz': hz[:nh], 'lazer_yuva': g['laser'] + dron_yuva, 'jen_yuva': yuva}


def degerler(ekip, kalkan_payi=0.6):
    """Botun savaş değerleri: dps (saniyede hasar, uzaylıya), can, kalkan, emme, ehp (etkin can), hız, güç puanı."""
    y = donat(ekip, kalkan_payi)
    carpan = ESYA['lazer_cephane'].get(ekip.get('cephane'), {}).get('carpan', 1)
    hasar = sum(y['lazer']) * carpan * 0.88 * SAVAS['lazer_isabet']          # 0,88: rastgelenin ortalaması (0,76-1,0)
    dps = hasar / LAZER_ARALIK
    kalkan = sum(k for k, _ in y['kalkan'])
    emme = (sum(k * e for k, e in y['kalkan']) / kalkan) if kalkan else 0.0
    can = y['gemi']['hp']
    ehp = can + kalkan * 2.5 * min(1.0, emme + 0.2)         # kalkan hasarın çoğunu emer ve hedefler arasında dolar
    hiz = y['gemi']['temel_hiz'] + sum(y['hiz'])
    return dict(dps=dps, can=can, kalkan=kalkan, emme=emme, ehp=ehp, hiz=hiz, guc=guc_puani(dps, ehp),
                lazer=len(y['lazer']), lazer_yuva=y['lazer_yuva'], jen=len(y['kalkan']) + len(y['hiz']), jen_yuva=y['jen_yuva'])


def guc_puani(dps, ehp):
    """Tek sayıda güç: dps ile etkin canın geometrik ortası (Phoenix + LF-1 ≈ 4, LF-3'lü, B02'li, 8 Iris'li Goliath ≈ 100)."""
    return math.sqrt(max(dps, 0) * max(ehp, 0)) / 490.0


# ------------------------------------------------------------------------------------------------------------ haritalar
_npc_onbellek = {}
_harita_npc_onbellek = {}


def npc_degeri(tip):
    """Uzaylının bot için değerleri (salt okunur; npc.json içe aktarmada bir kez yüklenir, sonuç önbellekte)."""
    if tip in _npc_onbellek:
        return _npc_onbellek[tip]
    t = NPC['tipler'].get(tip)
    v = None if not t else dict(
        tip=tip, ad=t['ad'], ehp=t['hp'] + t['kalkan'], dps=t['hasar'] * t.get('isabet', SAVAS['npc_isabet'])
        / t.get('atis_aralik_sn', NPC_ARALIK), saldirgan=bool(t.get('saldirgan')), odul=t['odul'], hiz=t['hiz'],
        kimlik=t.get('npc_kimlik', 0))
    _npc_onbellek[tip] = v
    return v


def harita_npcleri(map_id):
    """[(npc değeri, adet)]: haritanın sürekli uzaylıları (npc.json haritalar; salt okunur, önbellekte)."""
    if map_id in _harita_npc_onbellek:
        return _harita_npc_onbellek[map_id]
    out = []
    for r in (NPC['haritalar'].get(str(map_id)) or {}).get('npc', []):
        v = npc_degeri(r['tip'])
        if v and r.get('adet', 0) > 0:
            out.append((v, r['adet']))
    _harita_npc_onbellek[map_id] = out
    return out


_harita_onbellek = {}


def harita_degerlendir(map_id, dps, ehp, cesaret=0.5):
    """Bu güçteki bir geminin haritada uzaylı kasması -> {saat_ep, saat_kredi, saat_uridyum, saat_onur, olum_saat (saatte ölüm
    beklentisi), hedefler [tip], oldurme {tip: saatte öldürme}, zorluk (0 kolay .. 1+ ölümcül)}. cesaret (0-1): öldürmeye değer bulduğu en tehlikeli uzaylı
    (alınan hasar / etkin can sınırı). Uzaylı başına: öldürme süresi = etkin can / dps; alınan hasar = uzaylının dps'i x süre (yalnız
    saldırgansa ya da vurulunca karşılık verdiği için hep); arada onarım. Sonuçlar (harita, yuvarlanmış güç) için önbellekte."""
    key = (map_id, int(dps // 5), int(ehp // 5000), round(cesaret, 1))
    if key in _harita_onbellek:
        return _harita_onbellek[key]
    sinir = 0.25 + 0.5 * cesaret
    toplam = dict(ep=0.0, kredi=0.0, uridyum=0.0, onur=0.0)
    sure = 0.0
    olum = 0.0
    hedefler = []
    oldurme = {}
    agir = 0.0
    for v, adet in harita_npcleri(map_id):
        if dps <= 0:
            break
        t = v['ehp'] / dps
        alinan = v['dps'] * t
        oran = alinan / max(ehp, 1)
        if v['saldirgan']:
            agir += adet * min(2.0, oran)
        if oran > sinir:
            continue
        hedefler.append(v['tip'])
        tur = t + ARAMA_SN + alinan / max(ehp * ONARIM_ORAN, 1)
        oldurme[v['tip']] = adet
        for k in toplam:
            toplam[k] += v['odul'].get(k, 0) * adet
        sure += tur * adet
        olum += adet * max(0.0, oran - 0.15) ** 2 * 0.15        # ara sıra birden çok uzaylı ve kötü şans
    zorluk = agir / 40.0
    if sure <= 0:
        r = dict(saat_ep=0, saat_kredi=0, saat_uridyum=0, saat_onur=0, olum_saat=1.0 + zorluk, hedefler=[], zorluk=zorluk + 1,
                 oldurme={})
    else:
        k = 3600.0 / sure
        r = dict(saat_ep=toplam['ep'] * k, saat_kredi=toplam['kredi'] * k, saat_uridyum=toplam['uridyum'] * k,
                 saat_onur=toplam['onur'] * k, olum_saat=olum * k / max(1, len(hedefler)) + zorluk * 0.4, hedefler=hedefler,
                 zorluk=zorluk, oldurme={t: n * k for t, n in oldurme.items()})
    if len(_harita_onbellek) > 20000:
        _harita_onbellek.clear()
    _harita_onbellek[key] = r
    return r


_GIRIS = {}


def girebilir(map_id, firma, seviye):
    k = (map_id, firma, bool(AY.get('seviye_kisiti_yok')))     # panelin seviye kısıtı ayarı değişirse yeni anahtar
    if k not in _GIRIS:
        _GIRIS[k] = H.level_required(map_id, firma)
    return seviye >= _GIRIS[k]


def komsular(map_id, firma):
    """Portalla gidilen haritalar (ücretli / anahtarlı portallar hariç)."""
    return [g['hedef'] for g in H.gates(map_id, firma) if not g.get('ucret') and g['hedef'] in HARITALAR
            and g.get('yalniz_firma') in (None, firma)]


def yol(kaynak, hedef, firma, seviye):
    """En kısa portal yolu [kaynak, ..., hedef] (girilemeyen haritalardan geçmez) ya da None."""
    r = _yol(int(kaynak), int(hedef), firma, seviye)
    return list(r) if r is not None else None


@functools.lru_cache(maxsize=8192)
def _yol(kaynak, hedef, firma, seviye):
    if kaynak == hedef:
        return (kaynak,)
    onceki = {kaynak: None}
    q = deque([kaynak])
    while q:
        m = q.popleft()
        for n in komsular(m, firma):
            if n in onceki or not girebilir(n, firma, seviye):
                continue
            onceki[n] = m
            if n == hedef:
                out = [n]
                while onceki[out[-1]] is not None:
                    out.append(onceki[out[-1]])
                return tuple(out[::-1])
            q.append(n)
    return None


def ev(firma):
    """Firmanın üs haritası (X-1)."""
    return {1: 1, 2: 5, 3: 9}[firma]


# ------------------------------------------------------------------------------------------------------------ kargo
KARGO_CEVHER = frozenset((0, 1, 2, 4, 5, 6, 7, 8, 28))       # kargoda yer kaplayanlar (profil.CARGO_ORES; Xenomit kaplamaz)


def satis_haritalari(firma):
    """Cevherin satıldığı kendi istasyonları: X-1 ve X-8 (oyunda ticaret yalnız istasyonda)."""
    return {1: (1, 20), 2: (5, 24), 3: (9, 28)}[firma]


def cevher_fiyatlari(onur, carpan=1.0):
    """Rafineri fiyatları: taban + onur/bölen, tavanlı (dunya.ore_prices ile aynı formül)."""
    out = {}
    for t, (taban, bolen, tavan) in ESYA['cevherler']['fiyatlar'].items():
        v = min(tavan, taban + (int(max(0, onur) // bolen) if bolen else 0))
        out[int(t)] = int(round(v * carpan))
    return out


def kargo_kapasitesi(ekip):
    from . import ekstra as EK
    return int(int((ESYA['gemiler'].get(ekip['gemi']) or ESYA['gemiler']['ship_phoenix']).get('kargo') or 100)
               * EK.kargo_carpani(ekip))                  # G3X-CRGO-X: iki katı


def npc_kargosu(tip, seviye=1, harita=None):
    """Uzaylının kargo kutusundaki cevherler {tür: adet}; X-1 haritalarında yüksek seviyede azalır (npc.json x1_kargo)."""
    kargo = {int(k): int(v) for k, v in ((NPC['tipler'].get(str(tip)) or {}).get('kargo') or {}).items() if int(v) > 0}
    if harita is not None and H.map_class(harita) == 'X-1':
        import ayar as AY
        if AY.get('x1_kargo'):
            f = next((k for l, k in reversed(SAVAS['x1_kargo']) if seviye >= l), 1)
            kargo = {t: int(v * f) for t, v in kargo.items() if int(v * f) > 0}
    return kargo


def pvp_haritasi(map_id, firma):
    """Başka firmanın oyuncularıyla karşılaşılan harita mı (kendi X-1/X-2'si dışında her yer; 4-X ve başka firmanın haritaları)."""
    c = H.company(map_id)
    return c != firma or H.map_class(map_id) not in ('X-1', 'X-2')
