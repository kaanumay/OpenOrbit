"""PvP avı: düşman firmanın oyuncularını aramak (4-X, başka firmanın haritaları). Karşılaşmaları yonetici.pvp_tick çözer; avdaki bot
saldırgan sayılır. Öfke (az önce öldürüldü) ve kin (hafızada onu öldüren) avı çeker: intikam."""
from ..beyin import Hedef, hedef
from .. import katalog as K
from .. import soyut as S


def hedef_bul(y, ad):
    """Av emrindeki kişi: botlardan ya da gerçek oyunculardan (ad büyük/küçük harf ayrımsız) -> (ad, firma, harita ya da None
    (çevrimdışı), klan, insan mı) ya da None."""
    a = str(ad or '').strip().lower()
    if not a:
        return None
    x = y.ada.get(a)
    if x is not None:
        return x.ad, x.firma, (x.harita if x.cevrimici else None), x.k.get('klan'), False
    import topluluk as TP
    import klan as KL
    k = TP.bul(ad=a)
    if k is None:
        return None
    kl = KL.klani(k.profil)
    return (k.ad, int(k.profil.d['pilot'].get('factionId') or 0),
            int(k.profil.d['konum'].get('mapId', 0)) or None if k.oturum is not None else None, kl['id'] if kl else None, True)


def emir_kini(bot, ad, now):
    """Klan emriyle (klan_emir) verilen av ya da klan odağı: bu kişiye kin gibi davranılır (govde.pvp_hedefi 'kin' terimine eklenir)."""
    a = bot.k.get('av_emri')
    ad = str(ad).lower()
    if a and now < a['bitis'] and a['ad'] == ad:
        return 1.0
    f = bot.k.get('klan_odagi')
    if f and now < f['bitis']:
        import klan as KL
        c = KL.KLANLAR.get(f['klan'])
        if c is not None and ad in c['uyeler']:
            return 0.8
    return 0.0


def emir_hedefi(bot, y, now):
    """Sürmekte olan av emrinin (ya da klan odağının) çevrimiçi hedefi -> (ad, harita) ya da None."""
    a = bot.k.get('av_emri')
    if a and now < a['bitis']:
        t = hedef_bul(y, a['ad'])
        if t is not None and t[2] and t[1] != bot.firma and K.yol(bot.harita, t[2], bot.firma, bot.seviye):
            return t[0], t[2]
    f = bot.k.get('klan_odagi')
    if f and now < f['bitis']:
        import klan as KL
        c = KL.KLANLAR.get(f['klan'])
        for u in (c or {}).get('uyeler', ()):
            t = hedef_bul(y, u)
            if t is not None and t[2] and t[1] != bot.firma and K.yol(bot.harita, t[2], bot.firma, bot.seviye):
                return t[0], t[2]
    return None


@hedef
class PvpAvi(Hedef):
    ad = 'pvp'
    izin = 'pvp'
    en_az_sn = 240

    def uygun(self, bot, b):
        from .. import yonetici_uyari as YU
        from .. import silah as SL
        return bot.seviye >= (b.ayar('pvp_seviye', 6) or 1) and bot.deger()['guc'] >= 8 and not YU.etkin(bot, 'pvp', b.now)             and SL.lazer_var(bot)                         # cephanesiz oyuncu avlanmaz

    def puan(self, bot, b):
        o = bot.ozellik
        p = 0.1 + 0.55 * o['saldirganlik'] * o['rekabet'] + (0.35 if bot.arketip == 'avci' else 0)
        p += 0.45 * bot.ruh['ofke'] * o['saldirganlik']
        p *= 0.6 + 0.6 * bot.ruh['ozguven']
        if b.y is not None and bot.hafiza.kinliler() and b.y.cevrimici_ad(bot.hafiza.kinliler()):
            p += 0.25 * o['saldirganlik']
        if b.y is not None and b.y.prime(b.now):
            p *= float(b.ayar('prime_pvp', 2.0) or 1.0)           # akşam yoğun saati: PvP canlanır
        return p

    def basla(self, bot, b):
        y = b.y
        hedef_map = None
        kin = y.cevrimici_ad(bot.hafiza.kinliler()) if y is not None else None
        emir = emir_hedefi(bot, y, b.now) if y is not None else None
        if emir is not None:
            hedef_map = emir[1]                           # klan emri: söylenen kişiyi (ya da odaktaki klanın üyesini) bulmaya gider
            bot.plan['av'] = emir[0]
            kin = emir
        elif kin is not None and K.yol(bot.harita, kin.harita, bot.firma, bot.seviye):
            hedef_map = kin.harita                        # intikam: onu öldüreni bulmaya gider
            bot.plan['av'] = kin.ad
        elif y is not None:
            # düşmanların olduğu, gidilebilen ve çok güçlü düşmanı olmayan harita
            guc = bot.deger()['guc']
            adaylar = []
            for m, dusman in y.dusman_nufusu(bot).items():
                if not dusman or not K.girebilir(m, bot.firma, bot.seviye) or not K.yol(bot.harita, m, bot.firma, bot.seviye):
                    continue
                tehdit = max(d.deger()['guc'] for d in dusman) / max(1.0, guc)
                adaylar.append((len(dusman) - 2.5 * max(0.0, tehdit - 1.0 - bot.o('risk')), m))
            if adaylar:
                hedef_map = max(adaylar)[1]
        if (y is not None and kin is None and y.prime(b.now) and b.ayar('buyuk_savas', True) and bot.r.random() < 0.75
                and K.girebilir(y.cephe(b.now), bot.firma, bot.seviye) and K.yol(bot.harita, y.cephe(b.now), bot.firma, bot.seviye)):
            hedef_map = y.cephe(b.now)                    # büyük savaş: firmalar yoğun saatin cephesinde toplanır
            cagri = y.__dict__.setdefault('cephe_cagri', {})
            anahtar = (bot.firma, int(b.now // 3600))
            if anahtar not in cagri and bot.o('konuskanlik') + bot.o('saldirganlik') > 1.0:
                cagri[anahtar] = bot.ad
                import harita as H
                from .. import konusma as KN
                y.konus(bot, 'firma', KN.kalip(bot, 'savas_cagri', harita=H.name(hedef_map)), now=b.now + bot.r.uniform(3, 20))
        if hedef_map is None:
            hedef_map = next((m for m in (13 + bot.firma - 1, 16, 29) if K.girebilir(m, bot.firma, bot.seviye)), bot.harita)
        bot.plan['harita'] = int(hedef_map)
        S.git(bot, hedef_map, y, b.now)

    def somut(self, bot, g, w, now):
        """Haritada av (klan emri ya da intikam): avlanan bu haritadaysa görmese de ona doğru uçar, görüşe girince govde.pvp_hedefi
        saldırır (emir_kini ve kin onu öne alır); başka haritaya geçtiyse peşinden gider (canlı 2026-11-01: bot avın haritasına
        varıp orada uzaylı kesiyordu). Dövüşteyken, yolda ve avsızken govde'nin olağan davranışı."""
        from .. import govde as BG
        y = BG.YN.AKTIF
        emir = emir_hedefi(bot, y, now) if y is not None else None
        if emir is not None:
            bot.plan['av'] = emir[0]                      # süren emir önce gelir (zaten PvP'deyken verilen emirde basla yeniden çalışmaz)
        ad = str(bot.plan.get('av') or '').lower()
        if not ad or g.hedef is not None or bot.yolda or any(now - t < 6 for t in g.saldiran.values()):
            return False
        uid = next((m.id for m in w.npcs.values() if m.alive and m.bot is not None and m.bot.ad.lower() == ad), None)
        if uid is None:
            uid = next((o.hid for o in ([w] + list(w.ortak.uyeler if w.ortak is not None else [])) if o.running and not o.hero_dead
                        and str(o.p.d['pilot'].get('userName', '')).lower() == ad), None)
        if uid is None:
            t = hedef_bul(y, ad) if y is not None else None
            if (t is not None and t[2] and t[2] != bot.harita and now >= bot.__dict__.get('_av_izi', 0)
                    and K.yol(bot.harita, t[2], bot.firma, bot.seviye)):
                bot._av_izi = now + 30
                bot.plan['harita'] = int(t[2])
                S.git(bot, t[2], y, now)                  # av başka haritaya geçti: peşinden
                return True
            return False
        t = BG.pvp_hedefi(w, g, now)
        if t is not None:
            g.hedef = t                                   # görüşte: saldırır (savaş govde'de)
            return False
        pos = BG._konum(w, uid, now)
        if pos is None:
            return False
        BG._git(w, g, pos[0], pos[1], now, esik=300)
        return True

    def soyut(self, bot, dt, y):
        if S.yolculuk(bot, y):
            return
        if K.harita_npcleri(bot.harita) and bot.r.random() < 0.5:
            S.kas(bot, dt * 0.5, y)        # beklerken uzaylı da keser (yarı verim)
