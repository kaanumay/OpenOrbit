"""Alışveriş: parası yeten en verimli yükseltmeyi almak ya da büyük bir hedef için biriktirmek.

Adaylar katalogdan (lazer, kalkan/hız jeneratörü, dron, gemi): her biri için yeni donanımın güç artışı / fiyat (kredi karşılığı,
1 U = kur kredisi). Tutumlu bot biriktirdiği büyük hedef (Goliath gibi) varken küçük alımlara para harcamaz; dürtüsel bot ara
sıra en iyisi olmayan bir şey de alır (insan hatası).
"""
from ..beyin import Hedef, hedef
from .. import katalog as K
from .. import kisilik as KS

KUR = 100                 # 1 uridyum kaç kredi (fiyatlar.json kur)
SEFER_ALIM = 15           # bir alışveriş seferinde en çok bu kadar eşya
try:
    import json, os
    KUR = json.load(open(os.path.join(K.HERE, 'data', 'fiyatlar.json'), encoding='utf8')).get('kur', KUR)
except (OSError, ValueError):
    pass


def adaylar(bot):
    """[(güç artışı, para, fiyat, loot)]: yuvası olan ya da gemisi daha iyi her alım. Donanım değişene dek botta saklanır."""
    if bot._adaylar is None:
        bot._adaylar = _adaylar(bot)
    return bot._adaylar


def _adaylar(bot):
    e = bot.k['ekip']
    kp = bot.kalkan_payi()
    td = K.degerler(e, kp)
    taban = td['guc']
    yuva = K.donat(e, kp)
    out = []

    def dene(loot, sahip=0, dolgu=None, zorla=False):
        f = K.fiyat(loot, sahip)
        if not f or f[1] <= 0:
            return
        y = {a: dict(v) if isinstance(v, dict) else v for a, v in e.items()}
        if loot.startswith('ship_'):
            y['gemi'] = loot
        else:
            grup = 'lazer' if loot in K.ESYA['lazerler'] else 'kalkan' if loot in K.ESYA['kalkan_jeneratorleri'] else \
                'hiz' if loot in K.ESYA['hiz_jeneratorleri'] else 'dron'
            y[grup][loot] = y[grup].get(loot, 0) + 1
        if dolgu:                                        # dronun boş yuvaları sonra alınacak lazerle dolar
            y['lazer'][dolgu[0]] = y['lazer'].get(dolgu[0], 0) + dolgu[1]
        yd = K.degerler(y, kp)
        artis = yd['guc'] - taban + 0.02 * (yd['hiz'] - td['hiz']) * (0.5 + bot.o('risk'))    # hız güçte yok: kaçmaya, avlanmaya yarar
        if loot.startswith('ship_'):                     # zevk: sevdiği gemi ailesine yakınlık (herkes aynı gemiye yakınsamasın)
            artis *= 1.35 if KS.zevk(bot.k['kisilik']) in loot else 0.9
        if dolgu:                                        # verim lazerlerin parasıyla birlikte (dronun fiyatına düşen pay)
            lf = K.fiyat(dolgu[0])
            ceq = lambda c: c[1] * (KUR if c[0] == 'U' else 1)
            artis *= ceq(f) / (ceq(f) + dolgu[1] * ceq(lf))
        if artis > 1e-6 or zorla:                       # zorla: klan emri (daha iyi olmasa da istenen gemi/eşya)
            out.append((max(artis, 1e-3), f[0], f[1], loot))

    # lazer: yuva boşsa ya da en zayıfından iyiyse; fiyat/hasar sırasıyla ilk birkaç
    lz = K.lazerler()
    for loot in sorted(lz, key=lz.get):
        if len(yuva['lazer']) < yuva['lazer_yuva'] or lz[loot] > min(yuva['lazer'] or [0]):
            dene(loot)
    for loot in K.kalkanlar():
        dene(loot)
    for loot in K.hizlar():
        dene(loot)
    # dron yalnız lazer yuvası açar: yedek lazer yoksa artışı 0 sayılıyor, Flax hiç alınmıyordu (oyuncu bildirimi 2026-10-31);
    # boş yuvası eldeki en iyi (satın alınabilen) lazerle dolmuş sayılır
    yedek = sum(e.get('lazer', {}).values()) - len(yuva['lazer'])
    en_iyi = max((l for l in e.get('lazer', {}) if l in lz), key=lz.get, default=None)
    for loot, d in K.ESYA['dronlar'].items():
        n = e.get('dron', {}).get(loot, 0)
        if sum(e.get('dron', {}).values()) < K.ESYA['dron_azami'] and K.fiyat(loot, n):
            eksik = max(0, d.get('yuva', 1) - yedek)
            dene(loot, n, (en_iyi, eksik) if en_iyi and eksik else None)
    simdiki = K.ESYA['gemiler'].get(e['gemi'], {})
    for loot, g in K.gemiler().items():
        if loot != e['gemi'] and g['hp'] + 20000 * (g['laser'] + g['generators']) > simdiki.get('hp', 0) + 20000 * (
                simdiki.get('laser', 0) + simdiki.get('generators', 0)):
            dene(loot)
    istenen = bot.k.get('birikim')
    if istenen and not any(c[3] == istenen for c in out) and (istenen.startswith('ship_') or any(
            istenen in K.ESYA[g] for g in ('lazerler', 'kalkan_jeneratorleri', 'hiz_jeneratorleri', 'dronlar'))):
        dene(istenen, e.get('dron', {}).get(istenen, 0), zorla=True)
    from .. import ekstra as EK
    out += EK.adaylar(bot)                               # CPU'lar ve onarım robotları (faydası güç payı olarak)
    from .. import teknoloji as TK
    out += TK.adaylar(bot)                               # roket fırlatıcısı
    return out


def gelir(bot):
    """Saatlik tahmini kazanç {'C': kredi, 'U': uridyum}: bulunduğu haritada kasarsa (katalog.harita_degerlendir)."""
    d = bot.deger()
    try:
        r = K.harita_degerlendir(int(bot.harita), d['dps'], d['ehp'], 0.5)
    except (KeyError, ValueError, TypeError):
        return {'C': 0.0, 'U': 0.0}
    return {'C': r['saat_kredi'], 'U': r['saat_uridyum'] + 25}           # +25: bonus kutuları, görev ödülleri


def aday(bot):
    """-> (şimdi alınacak (artis, para, fiyat, loot) ya da None, biriktirilen hedef ya da None).

    Gerçek oyuncu gibi hedefli: yakında (tutumluluğa göre 1-2,5 saatlik kazançla) ulaşabileceği en verimli yükseltme hedeftir;
    parası yetiyorsa onu alır. Yetmiyorsa ancak hedef kadar verimli (en az %70) küçük bir alım yapar, yoksa biriktirir. Önceden
    yeten en verimli şeyi hemen alıyordu: SLL-01'e (50.000 C) para biriktirirken sırayla 2.000-8.000 C'lik hız jeneratörleri
    ve MP-1 alıp tek yuvalı Phoenix'te birbirinin yerine koyuyordu (paket analizi 2026-10-29)."""
    tum = adaylar(bot)
    if not tum:
        return None, None
    m = bot.oa.carpan('magaza_fiyat')                  # profilin mağaza fiyatı çarpanı
    if m != 1.0:
        tum = [(a, p, f * m, l) for a, p, f, l in tum]
    para = {'C': bot.k['kredi'], 'U': bot.k['uridyum']}
    para['C'] = max(0, para['C'] - bot.klan_birikimi())                     # klan kuracak: kuruluş bedelini biriktirir
    ceq = lambda c: c[2] * (KUR if c[1] == 'U' else 1)
    # verim: artış / (fiyat + servetin çeyreği): az parada kredi başına verim, çok parada artışın büyüklüğü öne geçer (zengin bot
    # 80M kredi ve 2M uridyumla +3,4 güçlü Apis yerine 2.000 C'lik +0,04'lük hız jeneratörünü seçiyordu; Laya denemesi 2026-10-31)
    servet = para['C'] + para['U'] * KUR
    verim = lambda c: c[0] / max(1.0, ceq(c) + 0.25 * servet) * 1e5
    t = bot.o('tutumluluk')
    hedefi = next((c for c in tum if c[3] == bot.k.get('birikim')), None)
    if hedefi is not None:                       # kendi seçtiği biriktirme hedefi (ajanın biriktir aracı): yalnız onu alır
        return (hedefi if para[hedefi[1]] >= hedefi[2] else None), hedefi
    yetisir = [c for c in tum if para[c[1]] >= c[2] * (1 + 0.3 * t)]        # tutumlu bot biraz yedek bırakır
    g = gelir(bot)
    ufuk = 1.0 + 1.5 * t
    ulasir = [c for c in tum if c[2] * (1 + 0.3 * t) <= para[c[1]] + g[c[1]] * ufuk]
    hedef_c = max(ulasir, key=verim, default=None)
    # uzak biriktirme hedefi (panel, sohbet): parası yetmeyen en büyük artış
    kalan = [c for c in tum if c not in yetisir]
    birikim = max(kalan, key=lambda c: c[0] * (0.5 + t) - ceq(c) / 5e6, default=None)
    if hedef_c is not None and hedef_c not in yetisir:
        birikim = hedef_c
    if not yetisir:
        return None, birikim
    if bot.r.random() < 0.05 * (1 - t):                                     # dürtüsel alım (insan hatası)
        return bot.r.choice(yetisir), birikim
    if hedef_c is None or hedef_c in yetisir:
        return max(yetisir, key=verim), birikim
    iyi = [c for c in yetisir if verim(c) >= 0.7 * verim(hedef_c)]
    return (max(iyi, key=verim) if iyi else None), birikim


@hedef
class Alisveris(Hedef):
    ad = 'alisveris'
    izin = 'magaza'
    en_az_sn = 5

    def uygun(self, bot, b):
        return b.alisveris[0] is not None

    def puan(self, bot, b):
        artis = b.alisveris[0][0]
        return min(1.6, 0.45 + artis / max(1.0, bot.deger()['guc']) * 3 + 0.2 * bot.o('hirs'))

    def basla(self, bot, b):
        # bir alışveriş seferinde parası yettikçe sırayla alır (en çok SEFER_ALIM): önceden sefer başına tek eşya alıyordu, 10M
        # kredili bot bir saatte 8 eşya alıp paranın %80'ini harcamadan duruyordu (oyuncu bildirimi 2026-10-31)
        c = b.alisveris[0]
        for _ in range(SEFER_ALIM):
            artis, para, fiyat, loot = c
            if not bot.ode(para, fiyat):
                break
            bot.ekle(loot)
            bot.ist('alim')
            bot.ruh.it(moral=0.12 + min(0.3, artis / max(1.0, bot.deger()['guc'])))
            bot.olay('alim', esya=loot, fiyat=fiyat, para=para)
            if loot.startswith('ship_'):
                bot.olay('yeni_gemi', esya=loot)
            if bot.k.get('birikim') == loot:
                bot.k['birikim'] = None                  # biriktirdiği şeye kavuştu (ajanın biriktir aracı)
            bot._adaylar = None                          # (gemi değişmese de kalan yuvalar ve para değişti)
            c = aday(bot)[0]
            if c is None:
                break
        bot.plan['bitti'] = True

    def bitti(self, bot, b):
        return bot.plan.get('bitti', False)
