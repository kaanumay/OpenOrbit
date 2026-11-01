"""Silahlar: lazer cephanesi ve roketlerin stoku, hedefe göre seçimi, atışta tüketimi ve ikmali (gerçek oyuncu gibi).

Stok bot.k['stok'] {loot: adet}: yeni pilot oyuncu gibi 1.000 LCB-10 ve 20 R-310 ile başlar; bonus kutularından ve görevlerden
cephane gelir, gerisi mağazadan alınır (oyuncu her atışta lazer sayısı kadar mermi harcar: dunya.World.attack). Seçim:
  lazer  sıradan uzaylıya LCB-10; dayanıklı uzaylıya (LCB-10 ile 90 sn'den uzun) x2/x3/x4 (MCB-25/50, UCB-100), PvP'de RSB-75 ya da x4/x3,
         kalkanı yüksek oyuncuya SAB-50 (izin 'ozel_cephane'); stok yoksa elinde ne varsa
  roket  elindeki en güçlüsü (izin 'roket'); bekleme 4 sn, R0K-T01 CPU'suyla yarısı
İkmal (karar anında): LCB-10 stoku birkaç saatlik ihtiyacın altına inince kredinin bir payıyla, roket ve özel cephane kişiliğe ve
paraya göre.
"""
from . import katalog as K

LCB, MCB25, MCB50, SAB, RSB = ('ammunition_laser_lcb-10', 'ammunition_laser_mcb-25', 'ammunition_laser_mcb-50',
                               'ammunition_laser_sab-50', 'ammunition_laser_rsb-75')
UCB = 'ammunition_laser_ucb-100'                     # x4: kapı ve mod ödüllerinden gelir; mağaza fiyatı olursa ikmal de alır
MAYINLAR = ('ammunition_mine_acm-01', 'ammunition_mine_ddm-01')          # standart ve doğrudan hasarlı (uridyumla)
MAYIN_BEKLEME = K.ESYA['savas_esyalari']['mayin']['bekleme_sn']
ROKETLER = ('ammunition_rocket_r-310', 'ammunition_rocket_plt-2026', 'ammunition_rocket_plt-2021', 'ammunition_rocket_plt-3030')
BASLANGIC = {LCB: 1000, ROKETLER[0]: 20}             # yeni oyuncunun stoku (profil şablonu)
ROKET_BEKLEME = K.SAVAS['roket_bekleme_ms'] / 1000.0
ZOR_SN = 90                                         # LCB-10 ile bundan uzun süren uzaylı "dayanıklı"


def stok(bot):
    return bot.k.setdefault('stok', dict(BASLANGIC))


def lazer_var(bot):
    """Lazer cephanesi var mı (yoksa uzaylıya da oyuncuya da ateş edemez; SAB-50 gövdeye vurmaz)."""
    return lazer_sec(bot) is not None


def carpan(loot):
    return K.ESYA['lazer_cephane'].get(loot, {}).get('carpan', 1)


def lazer_sec(bot, ehp=0.0, pvp=False):
    """Bu hedefe hangi lazer cephanesi (stokta olan) -> loot ya da None (hiç mermi yok)."""
    s = stok(bot)
    ozel = bot.izin.get('ozel_cephane', True)
    tutumlu = bot.o('tutumluluk')
    if ozel:
        if pvp:
            for c in (RSB, UCB, MCB50, MCB25):
                if s.get(c, 0) > 0:
                    return c
        dps = bot.deger()['dps']
        if ehp and dps > 0 and ehp / dps > ZOR_SN:
            if s.get(UCB, 0) > 0 and (tutumlu < 0.5 or ehp / dps > 3 * ZOR_SN):
                return UCB
            if s.get(MCB50, 0) > 0 and (tutumlu < 0.5 or ehp / dps > 3 * ZOR_SN):
                return MCB50
            if s.get(MCB25, 0) > 0:
                return MCB25
    if s.get(LCB, 0) > 0:
        return LCB
    return next((c for c in (MCB25, MCB50, UCB, RSB) if s.get(c, 0) > 0), None)      # SAB-50 gövdeye vurmaz: yalnız PvP'de kalkana


def roket_sec(bot):
    if not bot.izin.get('roket', True):
        return None
    s = stok(bot)
    return next((r for r in reversed(ROKETLER) if s.get(r, 0) > 0), None)


def mayin_sec(bot):
    if not bot.izin.get('mayin', True):
        return None
    s = stok(bot)
    return next((m for m in MAYINLAR if s.get(m, 0) > 0), None)


def roket_beklemesi(bot):
    return ROKET_BEKLEME * (0.5 if 'equipment_extra_cpu_rok-t01' in (bot.k['ekip'].get('ekstra') or {}) else 1.0)


def roket_dps(bot, roket):
    r = K.ESYA['roketler'].get(roket) or {}
    return r.get('hasar', 0) * 0.92 * r.get('isabet', K.SAVAS['roket_isabet']) / roket_beklemesi(bot)


def harca(bot, loot, n):
    """n adet harcar (yettiği kadar) -> harcanan. Botların oyun ayarı profilinde "sonsuz cephane" açıksa harcanmaz."""
    s = stok(bot)
    if bot.oa.get('sonsuz_cephane'):
        return min(n, s.get(loot, 0)) if s.get(loot, 0) > 0 else 0
    kes = bot.__dict__.setdefault('_harca_kesir', {})
    v = n + kes.get(loot, 0.0)
    kes[loot] = v - int(v)
    n = min(int(v), s.get(loot, 0))
    if n > 0:
        s[loot] -= n
        if not s[loot]:
            del s[loot]
    return n


def ekle(bot, loot, n):
    """Stoğa ekler; küsurat ayrı birikir (bonus kutularının ortalama payı saatte birkaç mermi)."""
    s = stok(bot)
    kes = bot.__dict__.setdefault('_stok_kesir', {})
    v = n + kes.get(loot, 0.0)
    kes[loot] = v - int(v)
    if int(v) > 0:
        s[loot] = s.get(loot, 0) + int(v)


# ------------------------------------------------------------------------------------------------------------ soyut savaş
def kasma_plani(bot, ehp):
    """Soyut kasılmada kullanılacaklar -> (lazer cephanesi, roket, toplam dps, atış başına mermi hasarı)."""
    d = bot.deger()
    lz = lazer_sec(bot, ehp)
    rk = roket_sec(bot)
    from . import lab as LB, teknoloji as TK
    lazer_dps = d['dps'] * carpan(lz) / max(1, carpan(bot.k['ekip'].get('cephane'))) * (1 + LB.bonus(bot, LB.LAZER)) if lz else 0.0
    zor = d['dps'] > 0 and ehp / d['dps'] > ZOR_SN
    r_dps = roket_dps(bot, rk) * (1 + LB.bonus(bot, LB.ROKET)) if rk else 0.0
    if r_dps and zor and (bot.__dict__.get('_hedefleyici', 0) > bot.saat() or TK.kullan(bot, 'tech_precision-targeter')):
        if bot.__dict__.get('_hedefleyici', 0) <= bot.saat():
            bot._hedefleyici = bot.saat() + TK.TEK['tech_precision-targeter']['sure_sn']
        r_dps /= (K.ESYA['roketler'].get(rk) or {}).get('isabet', 0.8)            # Precision Targeter: roketler hep isabet
    from . import ekstra as EK
    aim = next((c for c in (EK.AIM2, EK.AIM1) if EK.var(bot, c)), None) if zor and bot.izin.get('ekstra', True) else None
    if aim and bot.k.get('kargo', {}).get('3', 0) >= 1000:                     # AIM CPU: atış başına 10 Xenomit
        isabet = K.SAVAS['lazer_isabet']
        lazer_dps *= (1 - (1 - isabet) * (1 - K.ESYA['ekstralar'][aim]['nisan'])) / isabet
        bot._aim = True
    else:
        bot._aim = False
    fr = TK.froket_sec(bot) if zor else None
    bot._froket = fr
    dps = lazer_dps + r_dps + TK.fircatici_dps(bot, fr)
    return lz, rk, dps, lazer_dps


def tuket(bot, ehp_toplam, lz, rk, dps, lazer_dps):
    """ehp_toplam kadar uzaylı canını eritmek için harcanan mermi ve roket -> yetme oranı (0..1; mermi biterse eksik kalır)."""
    if dps <= 0 or ehp_toplam <= 0:
        return 1.0
    sure = ehp_toplam / dps
    oran = 1.0
    if lz and lazer_dps > 0:
        d = K.donat(bot.k['ekip'], bot.kalkan_payi())
        mermi = sure / K.LAZER_ARALIK * max(1, len(d['lazer']))           # her atışta lazer sayısı kadar mermi
        harcanan = harca(bot, lz, mermi)
        oran = harcanan / mermi if mermi else 1.0
        if bot.__dict__.get('_aim'):
            k = bot.k['kargo']
            k['3'] = max(0, k.get('3', 0) - int(harcanan / max(1, len(d['lazer'])) * 10))     # AIM CPU: atış başına 10 Xenomit
        from . import lab as LB
        LB.harca(bot, LB.LAZER, harcanan)                      # laboratuvar yükü mermi başına
    if rk:
        from . import lab as LB
        LB.harca(bot, LB.ROKET, harca(bot, rk, sure * oran / roket_beklemesi(bot)))
    fr = bot.__dict__.get('_froket')
    if fr:
        from . import teknoloji as TK
        kap, ara = TK.salvo(bot)
        harca(bot, fr, sure * oran * kap / ara)              # fırlatıcı salvoları
    return oran


_KUTU = (None, None)


def _kutu_ortalamasi():
    """Bonus kutusu tablosunun kalem başına ortalaması (tablo değişmedikçe bir kez; Dünya Editörü değiştirirse yeniden)."""
    global _KUTU
    import dunya as DN
    tablo = DN.CFG['bonus_kutu']
    if _KUTU[0] is not tablo:
        ort = {}
        for loot, n in tablo:
            ort[loot] = ort.get(loot, 0) + n / len(tablo)
        _KUTU = (tablo, ort)
    return _KUTU[1]


def kutu_cephanesi(bot, kutu_sayisi):
    """Bonus kutularından cephane ve kredi (dunya'nın bonus kutusu tablosunun ortalaması)."""
    for loot, n in _kutu_ortalamasi().items():
        pay = kutu_sayisi * n
        if loot.startswith('ammunition'):
            ekle(bot, loot, pay)
        elif loot == 'kredi':
            bot.odul('kutu', kredi=pay)
        elif loot == 'enerji':
            ekle(bot, 'resource_extra-energy', pay)      # Galaksi Kapısı enerjisi


# ------------------------------------------------------------------------------------------------------------ ikmal
def fiyat(loot):
    f = K.fiyat(loot)
    m = 1.0
    return (f[0], f[1] * m) if f else None


def saatlik_mermi(bot):
    """Saatte harcanan mermi (ateşte geçen pay ~%35; her atışta lazer sayısı kadar)."""
    d = K.donat(bot.k['ekip'], bot.kalkan_payi())
    return 3600 / K.LAZER_ARALIK * max(1, len(d['lazer'])) * 0.35


def ikmal(bot):
    """Stok azalınca mağazadan alır (karar anında; gerçek oyuncu cephanesi bitmeden alır). Önce LCB-10 (zorunlu), sonra roket
    ve özel cephane (paraya ve tutumluluğa göre) -> alınanlar."""
    if not bot.izin.get('magaza', True):
        return {}
    s = stok(bot)
    t = bot.o('tutumluluk')
    saatlik = saatlik_mermi(bot)
    alinan = {}

    def al(loot, adet, pay):
        f = fiyat(loot)
        if not f:
            return
        para = 'kredi' if f[0] == 'C' else 'uridyum'
        butce = bot.k[para] * pay
        adet = int(min(adet, butce // max(f[1], 1e-9)))
        if adet > 0 and bot.ode(f[0], adet * f[1]):
            ekle(bot, loot, adet)
            alinan[loot] = adet

    if s.get(LCB, 0) < saatlik * (0.5 + t):
        al(LCB, saatlik * (2 + 2 * t), 0.6)            # zorunlu: kredinin çoğuna kadar
    if bot.izin.get('roket', True) and sum(s.get(r, 0) for r in ROKETLER) < 30:
        en = None
        for r in ROKETLER:
            f = fiyat(r)
            if f and (f[0] == 'C' and bot.k['kredi'] > f[1] * 400 or f[0] == 'U' and bot.k['uridyum'] > f[1] * 300 * (1 + t)):
                en = r
        if en:
            al(en, 100 + 400 * (1 - t), 0.15)
    if bot.izin.get('ozel_cephane', True) and bot.seviye >= 3:
        if s.get(MCB25, 0) < 200 and bot.k['uridyum'] > 300 * (1 + t):
            al(MCB25, 500 + 1500 * (1 - t), 0.25)
        if bot.seviye >= 8 and s.get(MCB50, 0) < 200 and bot.k['uridyum'] > 3000 * (1 + t):
            al(MCB50, 1000 + 3000 * (1 - t), 0.2)
        if bot.seviye >= 10 and s.get(UCB, 0) < 200 and bot.k['uridyum'] > 8000 * (1 + t):
            al(UCB, 500 + 1500 * (1 - t), 0.2)              # fiyatı yoksa (mağazada satılmıyor) al() atlar
        if bot.seviye >= 8 and bot.o('saldirganlik') > 0.5 and s.get(RSB, 0) < 50 and bot.k['uridyum'] > 5000 * (1 + t):
            al(RSB, 200, 0.1)
    if bot.izin.get('mayin', True) and bot.seviye >= 8 and bot.o('saldirganlik') + bot.o('risk') > 0.9 \
            and sum(s.get(m, 0) for m in MAYINLAR) < 5 and bot.k['uridyum'] > 4000 * (1 + t):
        al(MAYINLAR[bot.r.random() < 0.3], 10 + 20 * (1 - t), 0.1)
    if bot.izin.get('ekstra', True) and bot.izin.get('pvp', True) and bot.seviye >= 8 and s.get('ammunition_specialammo_emp-01', 0) < 2 \
            and bot.k['uridyum'] > 5000 * (1 + t) and bot.o('risk') < 0.7:
        al('ammunition_specialammo_emp-01', 5, 0.1)
    if bot.izin.get('ozel_cephane', True) and bot.izin.get('pvp', True) and bot.seviye >= 8 and bot.k['uridyum'] > 4000 * (1 + t):
        from . import aktif as AK
        for c in AK.YAVASLATICI:                           # yavaşlatma ve dondurma: PvP'de (aktif.yavaslat), az stok
            if s.get(c, 0) < 3 and bot.o('saldirganlik') + bot.o('risk') > 0.8:
                al(c, 3, 0.05)
    if alinan:
        bot.ist('ikmal')
    return alinan
