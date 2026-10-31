"""Soyut benzetim: oyuncunun haritasında olmayan botların yolculuğu, kasılması, ölümü ve bot-bot karşılaşmaları (istatistiksel).

Sonuçlar katalog.harita_degerlendir'in beklenen değerlerinden gürültüyle çekilir: aynı güçteki iki bot aynı sürede birbirine yakın
ama aynı olmayan ilerleme yapar (şans, dikkat, "o gün iyi oynadı"). Botun gün içindeki verimi de kişiliğiyle oynar: sabırlı bot
düzenli, sabırsız bot dalgalı kasar.
"""
import math, time

import harita as H
from . import katalog as K
from . import kisilik as KS

BONUS_URI_SAAT = 220          # bonus kutularından saatte uridyum (seviye başına artar; 1-x'te ~200, yukarıda daha çok kutu)
KUTU_URI = 170 / 19.0                 # bonus kutusunun ortalama uridyumu (dunya.CFG['bonus_kutu']: 19 eşit olasılıklı içerik)
OLUM_BEKLEME = (25, 70)       # öldükten sonra doğmaya dek (ölüm ekranı, tamir seçimi, üsse dönüş)


def git(bot, hedef, y=None, now=None):
    """Portal yolunu kurar -> yol var mı. Yolda her harita ATLAMA_SN'de bir (hıza göre) geçilir."""
    now = now or (y.now if y is not None else time.time())
    hedef = int(hedef)
    if hedef == bot.harita:
        bot.yolda = None
        return True
    yol = K.yol(bot.harita, hedef, bot.firma, bot.seviye)
    if not yol:
        bot.yolda = None
        return False
    if len(yol) > 3 and bot.govde is None:              # atlama CPU'su: uzun yolu tek atlamada üsse (somutta govde.portala)
        from . import ekstra as EK
        cpu = EK.atlama(bot, hedef)
        if cpu and EK.kullan(bot, cpu):
            atla(bot, hedef, y)
            bot.yolda = None
            bot.ist('atlama_cpu')
            return True
    bot.yolda = yol[1:]
    bot.yolda_t = now + atlama_suresi(bot)
    return True


def atlama_suresi(bot):
    return K.ATLAMA_SN * bot.r.uniform(0.7, 1.3) * 320.0 / max(200, bot.deger()['hiz'])


def yolculuk(bot, y, now=None):
    """Yoldaysa sıradaki atlama zamanı geldiyse atlar -> hâlâ yolda mı."""
    if not bot.yolda:
        return False
    now = now or (y.now if y is not None else time.time())
    if bot.govde is not None:            # somut: gemi portala uçar, atlamayı govde yapar
        return True
    if now >= bot.yolda_t:
        atla(bot, bot.yolda.pop(0), y)
        bot.yolda_t = now + atlama_suresi(bot)
    return bool(bot.yolda)


def atla(bot, hedef, y):
    eski = bot.k['harita']
    bot.k['harita'] = int(hedef)
    bot.k['x'] = bot.k['y'] = 0
    gorulen = bot.k.setdefault('gorulen', [])
    if int(hedef) not in gorulen:
        gorulen.append(int(hedef))
    if y is not None:
        y.harita_degisti(bot, eski)


def _kutu_topla(bot, dt, hiz):
    """Mermisi yok: kasamaz, oyuncu gibi bonus kutusu toplar (kutudan cephane ve kredi gelir; parası bitmiş bot böyle toparlanır)."""
    from . import silah as SL
    k = dt / 3600.0 * hiz * 0.5 * (1 - 0.35 * bot.ruh['yorgunluk'])
    kutu = BONUS_URI_SAAT * (1 + bot.seviye / 6.0) * k * x1_kesinti(bot)
    bot.odul('kutu', uridyum=kutu)
    SL.kutu_cephanesi(bot, kutu / KUTU_URI)


def kas(bot, dt, y, hedef_tip=None):
    """dt saniye uzaylı kasma: kazanç, görev ilerlemesi, kargo, cephane tüketimi, ölüm. hedef_tip: görevin istediği uzaylı (yalnız onu
    kovalar: daha yavaş). Cephane ve roket stoktan (silah.py): dayanıklı uzaylıya x2/x3, roket varsa onun hasarı da; mermi biterse
    o kadar az kasar."""
    from . import silah as SL
    hiz = y.hiz(bot) if y is not None else 1.0
    d = bot.deger()
    cesaret = max(0.0, min(1.0, 0.3 + 0.6 * bot.o('risk') + 0.2 * bot.ruh['ozguven'] - 0.3))
    r = K.harita_degerlendir(bot.harita, d['dps'], d['ehp'], cesaret)
    if not r['hedefler']:
        if not SL.lazer_sec(bot) and not SL.roket_sec(bot):
            _kutu_topla(bot, dt, hiz)        # gücüne uygun uzaylı olmayan haritada da (yoksa mermisiz bot orada hiç toparlanmıyordu)
        return
    nv = K.npc_degeri(hedef_tip) if hedef_tip else None
    ehp_ort = nv['ehp'] if nv else sum(K.npc_degeri(t)['ehp'] * v for t, v in r['oldurme'].items()) / max(1e-9, sum(r['oldurme'].values()))
    lz, rk, dps, lazer_dps = SL.kasma_plani(bot, ehp_ort)
    if not lz and not rk:
        _kutu_topla(bot, dt, hiz)
        return
    from . import lab as LB
    ehp = d['ehp'] * (1 + 0.5 * LB.bonus(bot, LB.KALKAN))      # kalkan yükü (kalkan payı ~yarısı)
    if abs(dps - d['dps']) > 1e-6 or ehp != d['ehp']:
        r = K.harita_degerlendir(bot.harita, dps, ehp, cesaret)
        if not r['hedefler']:
            return
    # verim: gürültülü (sabırsız bot dalgalı), yorgunken düşük
    verim = max(0.2, bot.r.gauss(KS.AKTIFLIK[bot.arketip][1], 0.12 + 0.2 * (1 - bot.o('sabir')))) * (1 - 0.35 * bot.ruh['yorgunluk'])
    from . import ekstra as EK
    verim *= 1 + 0.04 * EK.onarim_seviyesi(bot)          # onarım robotu: toparlanmaya daha az zaman
    k = dt / 3600.0 * hiz * verim
    oldurme = r['oldurme']
    if hedef_tip and hedef_tip in oldurme:
        oldurme = {hedef_tip: oldurme[hedef_tip] * 1.6}      # yalnız istediğini kovalar: o türden daha çok
        oran = sum(oldurme.values()) / max(1e-9, sum(r['oldurme'].values()))
        k_odul = k * min(1.0, oran)
    else:
        k_odul = k
    # mermi ve roket: öldürülecek canlar kadar (oyuncu her atışta lazer sayısı kadar mermi harcar)
    yetti = SL.tuket(bot, sum(K.npc_degeri(t)['ehp'] * v * k for t, v in oldurme.items()), lz, rk, dps, lazer_dps)
    from . import lab as LB
    LB.harca(bot, LB.KALKAN, dt)                         # kalkan yükü dakikayla
    k, k_odul = k * yetti, k_odul * yetti
    lv = bot.seviye
    x1 = x1_kesinti(bot)
    bot.odul('npc', ep=r['saat_ep'] * k_odul * x1, kredi=r['saat_kredi'] * k_odul * x1, uridyum=r['saat_uridyum'] * k_odul * x1,
             onur=r['saat_onur'] * k_odul)
    kutu = BONUS_URI_SAAT * (1 + lv / 6.0) * k * x1
    bot.odul('kutu', uridyum=kutu)
    SL.kutu_cephanesi(bot, kutu / KUTU_URI)                # bonus kutularının cephanesi ve kredisi
    toplam = 0
    for tip, saat in oldurme.items():
        n = _poisson(bot.r, saat * k)
        if n:
            toplam += n
            from . import toplum as TB
            bot.ist('npc_puan', TB.npc_rutbe_puani(tip) * n)
            from . import ganimet as GB
            GB.ek_ganimet(bot, tip, n)                   # Scrapium, Mucosum, günlük dosyası …
            if bot.izin.get('kargo', True):             # kargo kutuları: sabırlı oyuncu hepsini toplar, aceleci çoğunu bırakır
                al = (0.55 + 0.4 * bot.o('sabir')) * bot.oa.carpan('toplama', 'kargo') * (1 + GB.booster_payi(bot, 'COLLECT_RESOURCES'))
                bot.kargo_ekle({t: int(v * n * al) for t, v in K.npc_kargosu(tip, bot.seviye, bot.harita).items()})
            if y is not None:
                y.npc_oldurdu(bot, tip, n)
    if toplam:
        bot.ist('npc', toplam)
        bot.ruh.it(moral=0.002 * toplam)
    from . import ganimet as GB, etkinlik as ET
    GB.soyut(bot, dt, y)                                 # haritanın anahtarlı kutuları
    ET.soyut(bot, dt, y, dps)                            # etkinlik uzaylıları, düşmeleri ve kutuları
    if bot.r.random() < r['olum_saat'] * dt / 3600.0 * (0.6 + 0.8 * (1 - bot.o('sabir')) * 0.5):
        olum(bot, y, neden='npc', now=y.now if y is not None else None)


def x1_kesinti(bot):
    """Kendi X-1'inde yüksek seviyede ödül azalır (npc.json x1_odul; dunya.World.grant_loot)."""
    if H.map_class(bot.harita) != 'X-1' or H.company(bot.harita) != bot.firma:
        return 1.0
    return next((k for l, k in reversed(K.SAVAS['x1_odul']) if bot.seviye >= l), 1.0)


def tamir_sec(bot, y, katil=None):
    """Ölüm ekranında oyuncunun seçeceği gibi: 'istasyon' (ücretsiz, üsse döner), 'portal' (500 U, aynı haritanın en yakın
    portalında) ya da 'yerinde' (1.000 U, canın %10'u ve 10 sn koruma). Pahalılar ancak uridyumu bolsa: yerinde sabırsızlık ve
    intikam hırsıyla, portal evden uzaklıkla ve cömertlikle. Ödenen uridyum düşer."""
    m = bot.harita
    if m not in K.HARITALAR or y is not None and y.kip == 'basit':
        return 'istasyon'
    yol = K.yol(m, K.ev(bot.firma), bot.firma, bot.seviye)
    uzak = len(yol) - 1 if yol else 0
    if uzak < 1:
        return 'istasyon'                           # zaten evinde: istasyon tamiri hem ücretsiz hem yakın
    C, k, tut = K.ESYA['olum_ekrani'], bot.oa.carpan('tamir_ucreti'), bot.o('tutumluluk')
    for tur, fiyat, istek in (('yerinde', C['yerinde_uridyum'] * k,
                               0.12 * (1 - bot.o('sabir')) + (0.3 * bot.ruh['ofke'] if katil else 0.0)),
                              ('portal', C['portal_uridyum'] * k, 0.1 * uzak * (1.2 - tut))):
        if bot.k['uridyum'] >= fiyat * (3 + 5 * tut) and bot.r.random() < istek:     # birikimin küçük bir payıysa öder
            bot.kazan(uridyum=-int(round(fiyat)))
            return tur
    return 'istasyon'


def olum(bot, y, neden='npc', katil=None, now=None):
    """Bot öldü: ruh hâli, istatistik, oyuncunun ölüm ekranındaki gibi tamir seçimi (tamir_sec). İstasyonda tamir: bir süre
    sonra firmanın üssünde (X-1 ya da seviyesine göre X-8) istasyonun çevresinde; portal ve yerinde tamir: aynı haritada, kısa
    sürede. Kargo kalır (oyuncu da ölünce kargosunu kaybetmez)."""
    now = now or (y.now if y is not None else time.time())
    bot.ist('olum')
    bot.ruh.it(ofke=0.35 if katil else 0.15, moral=-0.15, ozguven=-0.12)
    if katil:
        bot.hafiza.olay(katil, 'oldurdu_beni', now)
    tamir = tamir_sec(bot, y, katil)
    bot.olay('olum', now, neden=neden, katil=katil, harita=H.name(bot.harita), tamir=tamir)
    bot.yolda = None
    bot.olu_bitis = now + bot.r.uniform(*OLUM_BEKLEME)
    if y is not None and y.kip == 'basit':
        y.bot_oldu(bot, katil)
        bot.sonraki_karar = bot.olu_bitis
        return                                      # basit kip: aynı haritada yeniden doğar
    if tamir != 'istasyon':
        bot.olu_bitis = now + bot.r.uniform(5, 15)    # ölüm ekranında hemen seçti
        x, yy = bot.k.get('x') or 0, bot.k.get('y') or 0
        if tamir == 'portal':
            g = min(H.gates(bot.harita, bot.firma) or [{'x': x, 'y': yy}], key=lambda g: math.hypot(g['x'] - x, g['y'] - yy))
            bot.k['x'], bot.k['y'] = int(g['x'] + bot.r.uniform(-150, 150)), int(g['y'] + bot.r.uniform(-150, 150))
        else:
            bot.yerinde_tamir = True                  # gövde %10 canla ve 10 sn korumayla doğar (govde.tick)
        if y is not None:
            y.bot_oldu(bot, katil)
        bot.sonraki_karar = bot.olu_bitis
        return
    bot.k['x'] = bot.k['y'] = None                    # üste: ölüm yerinde değil istasyonun çevresinde doğar
    ev = H.x8_home(bot.firma, bot.seviye, bot.harita) if bot.seviye >= 12 else None
    hedef = int(ev) if ev else K.ev(bot.firma)
    if y is not None:
        y.bot_oldu(bot, katil)
    if hedef != bot.harita:
        atla(bot, hedef, y)
    bot.sonraki_karar = bot.olu_bitis


def _poisson(r, lam):
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(r.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= r.random()
        if p <= L:
            return k
        k += 1


# ------------------------------------------------------------------------------------------------------------ bot-bot PvP
def karsilasma(a, b, y, now=None):
    """İki düşman bot aynı haritada karşılaştı (yonetici.pvp_tick seçer): saldıran saldırır, öteki savaşır ya da kaçar; sonuç
    güç oranından, şanstan ve kişilikten. -> ('kazandi', kazanan, kaybeden) | ('kacti', kacan, kovalayan) | None"""
    now = now or time.time()
    from . import ekstra as EK
    from . import teknoloji as TK
    ga = max(0.5, a.deger()['guc']) * EK.pvp_carpani(a) * TK.pvp_carpani(a)
    gb = max(0.5, b.deger()['guc']) * EK.pvp_carpani(b) * TK.pvp_carpani(b)
    oran = gb / ga                                 # >1: b daha güçlü
    if oran < 0.6 and b.r.random() < 1 - b.o('risk') and EK.gizlen(b):          # gizlenme CPU'su: görünmeden sıvışır
        b.ist('gizlendi')
        return ('kacti', b, a)
    from . import silah as SL
    mayin_b = SL.mayin_sec(b)                      # kaçan arkasına mayın bırakır: kovalayan yavaşlar
    # b kaçar mı: temkinli ve zayıfsa
    kac = oran < 0.8 and b.r.random() < (1 - b.o('risk')) * (1 - oran) + 0.2 * (1 - b.o('saldirganlik'))
    if kac and b.r.random() < 0.55 + 0.25 * (b.deger()['hiz'] > a.deger()['hiz']) + 0.15 * bool(mayin_b and SL.harca(b, mayin_b, 1)):
        b.hafiza.olay(a.ad, 'hakaret', now, kat=0.5)
        b.ruh.it(ofke=0.1, ozguven=-0.05)
        return ('kacti', b, a)
    pa = ga ** 1.5 / (ga ** 1.5 + gb ** 1.5)       # güçlü olanın üstünlüğü doğrusal değil
    pa = 0.08 + 0.84 * pa                          # sürpriz her zaman mümkün
    kazanan, kaybeden = (a, b) if a.r.random() < pa else (b, a)
    pvp_odul(kazanan, kaybeden, y, now)
    olum(kaybeden, y, neden='oyuncu', katil=kazanan.ad, now=now)
    return ('kazandi', kazanan, kaybeden)


def pvp_odul(kazanan, kaybeden, y, now):
    """Öldürmenin onuru ve EP'si (esyalar.json oyuncu_oldurme: onur 100 x, EP 1.000 x kurbanın gemi puanı; kabaca seviyeyle)."""
    oo = K.ESYA['oyuncu_oldurme']
    kat = max(1, kaybeden.seviye // 2)
    hiz = y.hiz(kazanan) if y is not None else 1.0
    kazanan.odul(None, hiz, ep=oo['ep_puan'] * kat, onur=oo['onur_puan'] * kat)
    kazanan.ist('oyuncu')
    from . import toplum as TB
    kazanan.ist('oyuncu_puan', TB.gemi_rutbe_puani(kaybeden.k['ekip']['gemi']))
    kazanan.ruh.it(moral=0.1, ozguven=0.08, ofke=-0.2)
    kazanan.hafiza.olay(kaybeden.ad, 'oldurdum', now)
    kazanan.olay('oldurdum', now, kurban=kaybeden.ad)
