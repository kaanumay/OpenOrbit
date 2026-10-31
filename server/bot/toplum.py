"""Botların toplumu: oyundaki kimliği (Profil) ve oyunun sosyal sistemlerine bağı.

Profil bellekte durur, dosyaya yazılmaz (BotProfil.save boş): kalıcı kayıt paketin durum.json'udur. guncelle() botun ilerlemesini
profile kopyalar (seviye, para, onur, gemi, dronlar, konum); rehber ve müzayede bölümleri botun kaydıyla aynı sözlüktür (kalıcı).

Oyunun bütün "öteki oyuncu" aramaları topluluk.hepsi()'den geçer: botlar oraya sahte oturumla (BotOturum) kaydolunca rehber,
klan, grup, fısıltı, posta, sıralama ve müzayede onları kendiliğinden görür. Botun kararları tick()'te (yöneticinin iş parçacığı):
  grup daveti        kabul / ret (sosyallik, ilişki, seviye farkı, süren işi), grupta liderin peşinden (hedefler/grup.py)
  arkadaşlık         gelen isteği kabul / ret; birlikte oynadığı ya da yardım ettiği kişiye istek
  klan               lider ruhlu, zengin bot klan kurar; öteki botlar kişiliğine uyan klana başvurur; bot lider başvuruları
                     değerlendirir (oyuncununkiler de); sadakati az olan bot zamanla ayrılabilir
  müzayede           tüccar ve zengin botlar değerine göre teklif verir, son dakikalarda artırır
  sohbet             konusma.py (Normal) ya da llm.py (Gelişmiş)
"""
import os, random, re, time

import profil as PF
import yollar as YOL
from . import ad_uslup as AU
from . import katalog as K


class BotProfil(PF.Profil):
    def __init__(self, bot):
        self.bot = bot
        super().__init__({}, path=os.path.join(YOL.LOGS, 'bot_profili_yok.json'), d=_iskelet(bot))   # yol hiç yazılmaz

    def save(self, force=False):
        self.dirty = False


def _iskelet(bot):
    return {
        'surum': 1, 'olusturma': '2026-01-01 00:00:00',
        'pilot': {'userId': bot.uid, 'userName': bot.ad, 'factionId': bot.firma, 'clanId': 0, 'clanTag': '', 'level': 1, 'ep': 0,
                  'honourPoints': 0, 'credits': 0, 'uridium': 0, 'premium': False, 'dailyRank': 1, 'useSystemFont': False},
        'gemi': {'typeId': 'ship_phoenix', 'speed': 320, 'shield': 0, 'shieldMax': 0, 'hitPoints': 104000, 'hitMax': 104000},
        'konum': {'mapId': bot.harita, 'x': 0, 'y': 0},
        'gemiler': {'1': {'lootId': 'ship_phoenix', 'hangarId': 1, 'konfigler': {}, 'aktif_konfig': 1}}, 'aktif_gemi': 1,
        'dronlar': [], 'esyalar': {}, 'madenler': [], 'formasyon': 0, 'ayarlar': {}, 'tus_atamalari': [], 'arayuz': {'featureBars': []},
        'rehber': bot.k.setdefault('rehber', {}), 'muzayede': bot.k.setdefault('muzayede', {'teklifler': {}}),
        'posta': bot.k.setdefault('posta', {}),
    }


def profil(bot):
    """Botun profili (ilk istenince kurulur, her istekte güncellenir)."""
    if bot.profil is None:
        bot.profil = BotProfil(bot)
    guncelle(bot)
    return bot.profil


def guncelle(bot):
    p = bot.profil
    if p is None:
        return
    k, d = bot.k, bot.deger()
    pl, g = p.d['pilot'], p.d['gemi']
    son = getattr(bot, '_para', None)
    if son is not None:                  # oyun profilden harcadı ya da verdi (klan kurma, başvuru ücreti, klan ödemesi): bota geçer
        k['kredi'] = max(0, k['kredi'] + int(pl.get('credits', 0)) - son[0])
        k['uridyum'] = max(0, k['uridyum'] + int(pl.get('uridium', 0)) - son[1])
    k['rutbe'] = rutbe(bot)                      # panelin kadrosu da gösterir
    pl.update(userName=bot.ad, factionId=bot.firma, level=k['seviye'], ep=k['ep'], honourPoints=k['onur'], credits=k['kredi'],
              uridium=k['uridyum'], dailyRank=k['rutbe'])
    bot._para = (k['kredi'], k['uridyum'])
    gemi = k['ekip']['gemi']
    p.d['gemiler']['1']['lootId'] = gemi
    g.update(typeId=gemi, speed=int(d['hiz']), hitMax=int(d['can']), shieldMax=int(d['kalkan']))
    if bot.govde is None:
        g.update(hitPoints=int(d['can']), shield=int(d['kalkan']))
    else:
        g.update(hitPoints=int(bot.govde.hp), shield=int(bot.govde.shield))
    p.d['konum'].update(mapId=bot.harita, x=int(k.get('x') or 0), y=int(k.get('y') or 0))
    p.d['dronlar'] = [dict(lootId=loot, seviye=1, kimlik=i) for i, (loot, n) in
                      enumerate((l, n) for l, n in k['ekip'].get('dron', {}).items() for _ in range(n))]


def npc_rutbe_puani(tip):
    """Uzaylının rütbe puanı (rutbe.json npc_puan, npc_kimlik ile; oyuncunun rutbe.npc_points'i gibi)."""
    import rutbe as RT
    kimlik = K.NPC['tipler'].get(tip, {}).get('npc_kimlik')
    return RT.R['npc_puan'].get(str(kimlik), {}).get('puan', 0)


def gemi_rutbe_puani(gemi):
    """Yok edilen oyuncu gemisinin rütbe puanı (rutbe.json gemi_puan; Goliath 20, Phoenix 1)."""
    import rutbe as RT
    return RT.R['gemi_puan'].get(gemi, {}).get('puan', 0)


def puan(bot):
    """Rütbe puanı, oyuncununkiyle (rutbe.breakdown) aynı wiki formülü: EP/100.000 + onur/100 + oyuncu gemisi puanları x3 + seviye
    x100 + kayıttan beri gün x6 + gemi türü x1.000 + uzaylı puanları /2 + görev x100 - ölüm x4 (oyuncu bildirimi 2026-10-31: uzun süre
    oynayan botlar düşük rütbede kalıyordu; uzaylı ve oyuncu öldürmeleri tür puanı yerine adetle, gemi türü yerine gemi puanıyla, gün ve
    ölüm hiç sayılmıyordu)."""
    import rutbe as RT
    F = RT.R['formul']
    k, i = bot.k, bot.k['istat']
    gun = (bot.saat() - k['kayit_t']) // 86400 if k.get('kayit_t') else i.get('sure_sn', 0) // 86400   # eski kayıt: oynadığı süre
    return k['ep'] * F['ep'] + k['onur'] * F['onur'] + k['seviye'] * F['seviye'] + i.get('npc_puan', 0) * F['npc'] \
        + i.get('oyuncu_puan', 0) * F['oyuncu'] + i.get('gorev', 0) * F['gorev'] + max(0, gun) * F['gun'] \
        + RT.R['gemi_turu'].get(k['ekip']['gemi'], 0) * F['gemi'] + i.get('olum', 0) * F['olum_dusman']


def rutbe(bot):
    """Görünen rütbe simgesi (dailyRank 1-21): eşiklere göre, şirketteki sırayla sınırlı (rutbe.sirket_rutbesi: Chief General 1 ...)."""
    import rutbe as RT
    p = puan(bot)
    esik = RT.R['esikler']
    r = max(1, min(len(esik), sum(1 for e in esik if p >= e)))
    s = RT.sirket_rutbesi(bot.uid, bot.firma, p)
    return r if s is None else min(r, s)


# ------------------------------------------------------------------------------------------------------------ oturum ve kayıt
class BotOturum:
    """Çevrimiçi botun sahte oturumu (topluluk.Kisi.oturum): oyunun ona gönderdiği mesajlar gelen()'e düşer."""
    sosyal = None
    magaza = None
    world = None

    def __init__(self, bot):
        self.bot = bot
        self.profil = bot.profil

    def send(self, msgs, note=None):
        for m in msgs or ():
            gelen(self.bot, m)


def gelen(bot, m):
    """Oyunun bota gönderdiği mesaj: davetler kararı bekler (tick)."""
    if m[0] == 'InvitationInitializationCommand' and m[1].get('candidateId') == bot.uid:
        bot.bekleyen.append(('grup', m[1]['inviterId'], m[1].get('inviterName', ''), time.time()))
    elif m[0] in ('GroupInitializationCommand', 'GroupMemberInitializationCommand'):
        bot.bekleyen.append(('grup_kuruldu', 0, '', 0.0))   # (bot davet etti, kabul edildi): liderin yanına (tick)


_KISILER = {'t': 0.0, 'd': {}, 'y': None}


def kisiler(y):
    """uid -> topluluk.Kisi: paketin bütün botları (çevrimdışıların da profili; posta, rehber, klan onları bilir). 2 sn önbellek."""
    import topluluk as TP
    now = time.time()
    if now - _KISILER['t'] < 2.0 and _KISILER['y'] is y:
        return _KISILER['d']
    out = {}
    for b in y.botlar:
        if b.kayitli:                                    # henüz kayıt olmamış pilot sunucuda yok
            out[b.uid] = kisi(b, TP)
    _KISILER.update(t=now, d=out, y=y)
    return out


def kisi(bot, TP=None):
    if TP is None:
        import topluluk as TP
    p = profil(bot)
    if not bot.cevrimici:
        return TP.Kisi(p, None)
    if bot.oturum is None:
        bot.oturum = BotOturum(bot)
    return TP.Kisi(p, bot.oturum)


def kaydol(y, sohbet=None):
    """Oyun sunucusunda: botlar topluluğa ve sohbete bağlanır."""
    import topluluk as TP
    TP.BOTLAR = lambda: kisiler(y)
    if sohbet is not None:
        sohbet.bot_kanca = y.sohbet_gelen
        sohbet.bot_fisilti = y.fisilti_gelen
        from . import moderasyon as MOD
        sohbet.engel_kanca = lambda user, path, dil: MOD.engel(y, user, path, dil)
    y.sohbet = sohbet


def _para_geri(bot):
    """Oyunun bot profilinden harcadığı / verdiği para botun kaydına (klan kurma, başvuru ücreti, klan ödemesi)."""
    guncelle(bot)


# ------------------------------------------------------------------------------------------------------------ kararlar
def tick(y, now):
    """Yöneticinin tick'inden (5 sn'de bir): çevrimiçi botların sosyal kararları. Her bot kendi aralığıyla (insan gibi gecikmeli)."""
    for b in y.botlar:
        if not b.cevrimici or b.olu_bitis > now:
            continue
        if b.bekleyen:
            try:
                davetler(y, b, now)
            except Exception as e:            # bir davetin hatası öteki botların sosyal tikini durdurmasın
                y.log('   botlar: %s davet hatası: %r' % (b.ad, e))
                b.bekleyen = []
        if now < getattr(b, 'sonraki_sosyal', 0):
            continue
        b.sonraki_sosyal = now + b.r.uniform(20, 70) * (1.5 - b.o('sosyallik'))
        profil(b)
        try:
            tanisma(y, b, now)
            if y.izin('arkadas'):
                arkadaslik(y, b, now)
            if y.izin('klan'):
                klan_isleri(y, b, now)
            if y.izin('muzayede'):
                muzayede(y, b, now)
            if y.izin('sohbet'):
                posta_isleri(y, b, now)
        except Exception as e:                # bir botun hatası ötekileri durdurmasın
            y.log('   botlar: %s sosyal hata: %r' % (b.ad, e))


def tanisma(y, b, now):
    """Aynı haritada aynı firmadan kasan biriyle birlikte avlanma (aynı uzaylıya ateş, birbirinin kutusunu bırakma, kısa laflaşma):
    ikisinin de hafızasına 'birlikte_avlandik'. Çoğunlukla daha önce tanıştığı biri seçilir; ilişki zamanla arkadaşlığa, gruba
    dönüşür. Önceden ilişki yalnız sohbet ve yardımla doğuyordu: 44 dakikada 499 pilottan 423'ü kimseyle tanışmamıştı."""
    if b.r.random() > 0.3 * (0.3 + b.o('sosyallik')) or b.hedef is None or b.hedef.ad not in ('kasilma', 'gorev'):
        return
    orada = [o for o in y.haritada.get(b.harita, ()) if o is not b and o.firma == b.firma and o.cevrimici and o.olu_bitis <= now]
    if not orada:
        return
    tanidik = [o for o in orada if b.hafiza.iliski(o.ad, now) > 0]
    o = b.r.choice(tanidik) if tanidik and b.r.random() < 0.6 else b.r.choice(orada)
    b.hafiza.olay(o.ad, 'birlikte_avlandik', now)
    o.hafiza.olay(b.ad, 'birlikte_avlandik', now)


def davetler(y, b, now):
    import grup as GR
    kalan = []
    for tur, uid, ad, t in b.bekleyen:
        if now - t < b.k['kisilik']['tepki_sn'] * b.r.uniform(3, 9):
            kalan.append((tur, uid, ad, t))
            continue
        if tur == 'grup_kuruldu':
            _grupla(y, b, now)
            continue
        if tur != 'grup' or not y.izin('grup'):
            continue
        k = kisi(b)
        if karar_grup(y, b, ad, uid, now):
            GR.handle(k, 'InvitationAcceptRequest', {'inviterId': uid})
            b.hafiza.olay(ad, 'grup', now)
            b.olay('gruba_girdi', now, ad=ad)
            from . import beyin as B
            B.zorla(b, 'grup', pay=0.8, sure=1800, now=now)
        else:
            GR.handle(k, 'InvitationRejectRequest', {'inviterId': uid})
            b.olay('grup_reddetti', now, ad=ad)
    b.bekleyen = kalan


def _grupla(y, b, now):
    """Bot bir gruba girdi (kendi daveti kabul edildi): grubun insan oyuncusunun yanına gider (hedefler/grup.py)."""
    from .hedefler import grup as HG
    from . import beyin as B
    k = HG.lider(b)
    if k is None or (b.hedef is not None and b.hedef.ad == 'grup'):
        return
    b.hafiza.olay(k.ad, 'grup', now)
    b.olay('gruba_girdi', now, ad=k.ad)
    B.zorla(b, 'grup', pay=0.8, sure=1800, now=now)


def karar_grup(y, b, ad, uid, now):
    """Grup davetini kabul eder mi: sosyallik, davet edene ilişki, seviye farkı, süren işi (görevin ortasında daha az), yorgunluk,
    firma (başka firmadan davet nadiren). Sohbette "inv me" dediyse (söz) kabul eder."""
    from . import etkilesim as ET
    if ET.soz_var(b, 'grup', ad, now):
        return True
    import topluluk as TP
    o = TP.bul(uid=uid)
    lv = int(o.profil.d['pilot'].get('level', 1)) if o is not None else b.seviye
    fark = abs(lv - b.seviye)
    p = 0.25 + 0.5 * b.o('sosyallik') + 0.6 * b.hafiza.iliski(ad, now) - 0.04 * max(0, fark - 3) - 0.3 * b.ruh['yorgunluk']
    if b.hedef is not None and b.hedef.ad == 'gorev':
        p -= 0.15
    if o is not None and int(o.profil.d['pilot'].get('factionId', 0)) != b.firma:
        p -= 0.5
    return b.r.random() < max(0.03, min(0.95, p))


def arkadaslik(y, b, now):
    import rehber as RH
    r = RH.kayit(b.profil)
    k = None
    for ad in list(r.get('gelen', [])):
        k = k or kisi(b)
        rel = b.hafiza.iliski(ad, now)
        kabul = b.r.random() < 0.2 + 0.5 * b.o('sosyallik') + rel
        RH.handle(k, 'ContactRequest', {'contactRequestType': RH.KABUL if kabul else RH.RET, 'userName': ad})
        b.olay('arkadas_kabul' if kabul else 'arkadas_ret', now, ad=ad)
        if kabul:
            b.hafiza.olay(ad, 'arkadas', now)
    if b.r.random() < 0.15 * b.o('sosyallik'):
        dost = [a for a in b.hafiza.dostlar(0.25, now) if not RH._var(r.get('arkadas', []), a) and not RH._var(r.get('giden', []), a)]
        if dost:
            ad = b.r.choice(dost)
            RH.handle(k or kisi(b), 'ContactRequest', {'contactRequestType': RH.OLUSTUR, 'userName': ad})
            b.olay('arkadas_istek', now, ad=ad)


# ------------------------------------------------------------------------------------------------------------ klan
_ON = ('Dark', 'Black', 'Red', 'Iron', 'Silent', 'Eternal', 'Royal', 'Shadow', 'Storm', 'Crimson', 'Galactic', 'Void', 'Star')
_ON_TR = ('Kara', 'Kizil', 'Anadolu', 'Gok', 'Demir', 'Olumsuz', 'Turk', 'Yildiz')
_ARKA = ('Legion', 'Knights', 'Wolves', 'Eagles', 'Raiders', 'Hunters', 'Order', 'Empire', 'Brotherhood', 'Alliance', 'Reapers',
         'Guardians', 'Titans', 'Pirates')
_ARKA_TR = ('Kurtlar', 'Kartallar', 'Akincilar', 'Savascilar', 'Lejyon', 'Ordu', 'Sahinler', 'Korsanlar')


_ULKE = {'tr': 'Turkish', 'de': 'German', 'pl': 'Polish', 'ru': 'Russian', 'es': 'Spanish', 'fr': 'French', 'pt': 'Brazilian'}
_TEK = ('Bandidos', 'Nocturnos', 'Inferno', 'Phantoms', 'Outlaws', 'Spartans', 'Vikings', 'Immortals', 'Mercenaries', 'Renegades',
        'Elite', 'Legends', 'Nemesis', 'Valhalla', 'Ragnarok', 'Apocalypse', 'Chaos', 'Exodus', 'Oblivion', 'Hellfire')
_SON = ('Power', 'Army', 'Force', 'Elite', 'Warriors', 'Family', 'Team', 'Mafia')


def klan_adi(b, r, etiketler=()):
    """Gerçek sunuculardaki gibi klan adı ve etiketi: ikili ad, tek sözcük (bazen süslü, küçük harf ya da sarılı), "The X",
    "Turkish Power"; etiket önce paketin gerçek etiket havuzundan (DOStats), değilse baş harfler, bazen süslü (Λ И Σ)."""
    dil = b.k['kisilik'].get('ad_dili') or b.k['kisilik'].get('dil')
    tr = dil == 'tr' and r.random() < 0.7
    bicim = r.choices(('ikili', 'tek', 'the', 'ulke', 'kucuk', 'sarili'), (35, 20, 10, 15 if dil in _ULKE else 0, 10, 10))[0]
    tek = r.choice(_TEK + (_ARKA_TR if tr else _ARKA))
    if bicim == 'ikili':
        ad = '%s %s' % (r.choice(_ON_TR if tr else _ON), r.choice(_ARKA_TR if tr else _ARKA))
    elif bicim == 'tek':
        ad = AU._harfler(tek.upper(), r) if r.random() < 0.5 else tek
    elif bicim == 'the':
        ad = 'The ' + tek
    elif bicim == 'ulke':
        ad = '%s %s' % (_ULKE[dil], r.choice(_SON))
    elif bicim == 'kucuk':
        ad = tek.lower() + r.choice(('', '', '.', ' clan', ' squad'))
    else:
        on, son = AU._sec(r, AU.SARGI[:8])
        ad = on + tek + son
    if etiketler and r.random() < 0.7:
        return ad, r.choice(list(etiketler))[:4]
    sade = re.sub(r'[^A-Za-z ]', '', AU.sade(ad) if not ad.isascii() else ad).split() or [tek]
    etiket = (''.join(w[0] for w in sade).upper() if len(sade) > 1 else sade[0][:r.choice((3, 3, 4))].upper())
    etiket += r.choice(('', '', str(r.randint(1, 99)), 'X', 'TR' if tr else 'EU')) if len(etiket) < 3 else ''
    if r.random() < 0.3:
        etiket = ''.join(r.choice(AU.BUYUK[c]) if c in AU.BUYUK and r.random() < 0.6 else c for c in etiket)
    return ad, etiket[:4]


def klan_isleri(y, b, now):
    import klan as KL
    p = profil(b)
    k = KL.klani(p)
    if k is None:
        b.k['klan'] = None
        lider_ruhlu = b.arketip == 'lider' or b.o('sosyallik') * b.o('hirs') > 0.5
        bot_klanlari = sum(1 for c in KL.KLANLAR.values() if c['lider'] in y.ada)
        sinir = max(1, sum(b.kayitli for b in y.botlar) // int(y.ayar('klan_basina', 12) or 12))
        if (y.izin('klan_kur') and lider_ruhlu and b.seviye >= 5 and bot_klanlari < sinir
                and b.k['kredi'] >= KL.KURMA_BEDELI * 1.3 and b.r.random() < 0.3):
            r = random.Random('%s|klan|%d' % (b.ad, len(KL.KLANLAR)))
            kl = KL.Klan(p, log=y.log)
            for _ in range(6):
                ad, etiket = klan_adi(b, r, y.paket.get('klan_etiketleri') or ())
                if KL.Klan.valid_tag(etiket) and not kl.taken(ad, etiket):      # [CM] gibi ayrılmış etiketler olmaz
                    break
            aciklama = 'PvP' if b.o('saldirganlik') > 0.6 else 'PvE & quests'
            out = kl.handle('FoundClanRequest', {'clanTag': etiket, 'clanName': ad, 'clanDescription': aciklama})
            _para_geri(b)
            if out and out[0][1].get('success'):
                b.k['klan'] = out[0][1]['clanId']
                b.olay('klan_kurdu', now, ad=ad, etiket=etiket)
                b.ruh.it(moral=0.2)
            return
        if b.seviye >= 3 and b.r.random() < 0.25 * (0.4 + b.o('sosyallik')):
            aday = klan_sec(y, b, list(KL.KLANLAR.values()))
            if aday is not None and b.k['kredi'] >= KL.BASVURU_UCRETI * 3:
                msg = 'lvl %d, %s' % (b.seviye, 'pvp' if b.o('saldirganlik') > 0.6 else 'pve')
                KL.Klan(p, log=y.log).handle('ApplyClanRequest', {'clanId': aday['id'], 'message': msg})
                _para_geri(b)
                b.olay('klana_basvurdu', now, klan=aday['ad'])
        return
    if b.k.get('klan') != k['id']:
        b.k['klan'] = k['id']
        b.olay('klana_girdi', now, klan=k['ad'])
    vergi_ode(b, k)
    kl = KL.Klan(p, log=y.log)
    if kl.hak('hiremember', k):
        for bs in list(k.get('basvurular', [])):
            if not basvuru_karari(y, b, k, bs, now):
                continue
            kabul = basvuru_karari(y, b, k, bs, now, kesin=True)
            kl.handle('ApplyAcceptRequest' if kabul else 'ApplyDeclineRequest', {'applyId': bs['id']})
            b.olay('basvuru_kabul' if kabul else 'basvuru_ret', now, ad=bs.get('ad'))
            if kabul and str(bs.get('ad', '')).lower() not in y.ada:
                hos_geldin_postasi(y, b, k, bs.get('ad', ''))
    if y.izin('klan_diplomasi') and kl.hak('diplo_start', k):
        diplomasi(y, b, k, kl, now)
    from . import klan_yonetim as KY
    KY.yonet(y, b, k, kl, now)                           # rütbeler, açıklama, duyuru, vergi, bütçe, ödeme, üyeler (klan_yonetim)
    if KL.klani(p) is not k:
        return                                           # liderliği bıraktı ya da klanı dağıttı
    if k['lider'] != b.ad.lower() and b.o('sadakat') < 0.3 and b.r.random() < 0.004:
        kl.handle('LeaveClanRequest', {})
        b.k['klan'] = None
        b.olay('klandan_ayrildi', now, klan=k['ad'])


def klan_iliskisi(a, b):
    """İki botun klanları arası ilişki (1 ittifak, 2 saldırmazlık, 3 savaş, 0 yok)."""
    import klan as KL
    return KL.iliski_klan(int(a.k.get('klan') or 0), int(b.k.get('klan') or 0))


def vergi_ode(b, k):
    """Üyenin son kazancından klanın vergisi kasaya (oyunda uzaylı ödülünden kesilir; klan.vergi)."""
    import klan as KL
    gelir = b.__dict__.pop('_klan_geliri', 0)
    pay = gelir * int(k.get('vergi') or 0) // 100
    if pay <= 0:
        return
    b.k['kredi'] = max(0, b.k['kredi'] - pay)
    with KL.LOCK:
        k['kasa'] += pay
        k['gelir'] = int(k.get('gelir', 0)) + pay
        u = k['uyeler'].get(b.ad.lower())
        if u is not None:
            u['katki_donem'] = int(u.get('katki_donem', 0)) + pay     # haftalık ödemede en çok katkı verenlere (klan_yonetim)


def klan_firmasi(c):
    """Klanın firması; bütün firmalara açık (0) klanda liderinki (klan.py sıralaması gibi)."""
    return int(c.get('firma') or 0) or int((c.get('uyeler', {}).get(c.get('lider')) or {}).get('firma') or 0)


def _uyeler(c):
    return {str(a).lower() for a in c.get('uyeler', {})}


def diplomasi(y, b, k, kl, now):
    """Klan liderinin diplomasisi, oyunun klan diplomasisiyle (ittifak 1, saldırmazlık 2, savaş 3, barış isteği 0): gelen
    isteklere birkaç dakikada yanıt (senin klanınınkiler dahil), arada kendisi istek gönderir. Aynı firmadan klanlarla
    ittifak ya da saldırmazlık; başka firmadan, üyelerimizi öldürmüş ya da denk bir klana savaş (500.000 kredi kasadan; kasada
    yoksa lider yatırır); uzayan savaşta barış. Kişilik: sosyallik ittifakı, saldırganlık savaşı, temkin barışı sever."""
    import klan as KL
    gelen = [r for r in k.get('diplo_istek', []) if r['kime'] == k['id']]
    if gelen and b.r.random() < 0.35:
        r = gelen[0]
        o = KL.KLANLAR.get(r['kimden'])
        if o is not None:
            dusman = len(_uyeler(o) & {a.lower() for a in b.hafiza.kinliler(-0.3, now)})
            if r['tur'] == 0:                       # barış
                kabul = b.r.random() < 0.25 + 0.5 * (1 - b.o('saldirganlik')) - 0.1 * dusman
            else:
                ayni = klan_firmasi(o) == klan_firmasi(k)
                kabul = ayni and not dusman and b.r.random() < 0.3 + 0.5 * b.o('sosyallik') + (0.2 if r['tur'] == 2 else 0)
            kl.handle('ClanEditDiploOfferRequest', {'diploId': r['id'], 'status': 'allow' if kabul else 'deny'})
            b.olay('diplomasi', now, form=r['tur'], klan=o['ad'], etiket=o.get('etiket', ''), kabul=kabul, gelen=True)
        return
    if b.r.random() > 0.015:
        return                                      # yeni girişim nadir (lider aşağı yukarı saatte bir düşünür)
    mevcut = {d['klan']: d for d in k.get('diplomasi', [])}
    bekleyen = {r['kime'] for r in k.get('diplo_istek', [])} | {r['kimden'] for r in k.get('diplo_istek', [])}
    savaslar = [d for d in mevcut.values() if d['tur'] == 3]
    for d in savaslar:                              # uzayan savaş: barış ister
        if d['klan'] not in bekleyen and b.r.random() < 0.15 * (1.2 - b.o('saldirganlik')):
            kl.handle('ClanNewDiplomacyRequest', {'diploClanID': d['klan'], 'diploForm': 0, 'desc': 'gg, peace?'})
            b.olay('diplomasi', now, form=0, klan=d.get('ad', ''), gelen=False)
            return
    firma = klan_firmasi(k) or b.firma
    dusmanlar = {a.lower() for a in b.hafiza.kinliler(-0.3, now)}
    adaylar = []
    for c in list(KL.KLANLAR.values()):
        if c['id'] == k['id'] or c['id'] in mevcut or c['id'] in bekleyen or not c.get('uyeler'):
            continue
        cf = klan_firmasi(c)
        boy = 1.0 - min(1.0, abs(len(c['uyeler']) - len(k['uyeler'])) / max(5.0, len(k['uyeler'])))
        if cf == firma:
            tur = 1 if b.o('sosyallik') > 0.5 else 2
            adaylar.append((0.4 * b.o('sosyallik') + 0.3 * boy + b.r.uniform(0, 0.3), tur, c))
        elif cf and b.o('saldirganlik') > 0.55 and len(savaslar) < 2:
            kin = len(_uyeler(c) & dusmanlar)
            adaylar.append((0.4 * b.o('saldirganlik') + 0.3 * boy + 0.25 * min(3, kin) + b.r.uniform(0, 0.3), 3, c))
    if not adaylar:
        return
    puan, tur, c = max(adaylar, key=lambda a: a[0])
    if puan < 0.55:
        return
    if tur == 3 and k['kasa'] < KL.SAVAS_BEDELI:
        eksik = KL.SAVAS_BEDELI - k['kasa']
        if b.k['kredi'] < eksik * 1.5:
            return                                  # savaşı göze alacak parası yok
        b.kazan(kredi=-eksik)                       # lider kasaya yatırır
        with KL.LOCK:
            k['kasa'] += eksik
        KL.degisti(k)
    metin = {1: 'alliance?', 2: 'nap?', 3: 'see you in space'}[tur]
    out = kl.handle('ClanNewDiplomacyRequest', {'diploClanID': c['id'], 'diploForm': tur, 'desc': metin})
    if out and out[0][1].get('success'):
        b.olay('diplomasi', now, form=tur, klan=c['ad'], etiket=c.get('etiket', ''), gelen=False)


def klan_sec(y, b, klanlar):
    """Botun kişiliğine en uyan klan: aynı firma, üyelerinin ortalama seviyesine yakın, PvP/PvE açıklaması, üye sayısı (kalabalık
    çeker ama dolu değil). Başvurusu bekleyen ya da reddedilmiş bot yeniden başvurmaz."""
    adaylar = []
    for c in klanlar:
        if any(str(x.get('ad', '')).lower() == b.ad.lower() for x in c.get('basvurular', [])):
            return None
        if c.get('firma') and c['firma'] != b.firma or b.ad.lower() in [str(r).lower() for r in c.get('retler', [])]:
            continue
        uy = list(c['uyeler'].values())
        if len(uy) >= 50:
            continue
        ort = sum(int(u.get('seviye', 1)) for u in uy) / max(1, len(uy))
        pvp = 'pvp' in str(c.get('aciklama', '')).lower()
        uyum = 1.0 - abs(ort - b.seviye) / 12.0 + (0.3 if pvp == (b.o('saldirganlik') > 0.6) else 0) + min(0.3, len(uy) / 30.0)
        adaylar.append((uyum + b.r.uniform(-0.2, 0.2), c))
    return max(adaylar, key=lambda x: x[0])[1] if adaylar else None


def basvuru_karari(y, b, k, bs, now, kesin=False):
    """Bot lider başvuruya bakar mı (kesin=False: tepki süresi doldu mu) / kabul eder mi (kesin=True): seviye, ilişki. Oyuncunun
    başvurusu da böyle değerlendirilir (hemen değil, bir süre sonra)."""
    if not kesin:
        t = bs.get('_bot_gordu')
        if t is None:
            bs['_bot_gordu'] = now
            return False
        return now - t > b.r.uniform(30, 240)
    from . import etkilesim as ET
    if ET.soz_var(b, 'klan', bs.get('ad', ''), now):
        return True                                      # sohbette "başvur, kabul ederim" dedi
    import topluluk as TP
    o = TP.bul(ad=bs.get('ad'))
    lv = int(o.profil.d['pilot'].get('level', 1)) if o is not None else 1
    uy = list(k['uyeler'].values())
    ort = sum(int(u.get('seviye', 1)) for u in uy) / max(1, len(uy))
    p = 0.55 + 0.05 * (lv - ort + 3) + 0.6 * b.hafiza.iliski(bs.get('ad', ''), now)
    return b.r.random() < max(0.1, min(0.97, p))


# ------------------------------------------------------------------------------------------------------------ müzayede
def lot_onemi(b, lot):
    """Lotun bota önemi: 0 istemez; 1 sıradan (cephane, booster, kaynak; tüccar her lota); 2 donanım (lazer, jeneratör, dron); 3 takılı
    olmayan CPU ya da modül; 4 şimdikinden iyi gemi; 5 biriktirdiği gemi. Müzayedenin asıl değeri CPU'lar ve büyük gemiler:
    resmî oyunda günlerce uridyum biriktirmek yerine krediyle alınırlar, bu yüzden rekabet onlarda (kullanıcı isteği 2026-10-30)."""
    from . import ekstra as EK
    loot = lot['loot']
    if loot.startswith('ship_'):
        g, simdiki = K.ESYA['gemiler'].get(loot) or {}, K.ESYA['gemiler'].get(b.k['ekip']['gemi']) or {}
        # yalnız değerleri olan ve şimdikinden iyi olan (yalnız görünüm olan tasarımlar, "goliath_design_jade", gemi değildir)
        if not g.get('hp') or g['hp'] + 20000 * (g['laser'] + g['generators']) <= simdiki.get('hp', 0) + 20000 * (
                simdiki.get('laser', 0) + simdiki.get('generators', 0)):
            return 0
        return 5 if b.k.get('birikim') == loot else 4
    if lot.get('grup') in ('extra', 'module'):
        return 0 if EK.var(b, loot) else 3
    if loot in K.ESYA['lazerler'] or loot in K.ESYA['kalkan_jeneratorleri'] or loot in K.ESYA['dronlar'] or lot.get('grup') == 'generator':
        return 2
    if loot.startswith('ammunition_') or lot.get('grup') in ('booster', 'special') or b.arketip == 'tuccar':
        return 1
    return 0


def muzayede(y, b, now):
    """Teklif: geçilen teklifini her sosyal turda savunur; yoksa ara sıra lotlara bakar, önemli olanı (CPU, iyi gemi) seçer. Tavan lotun
    anında alım değeri x önem, rekabet, hırs ve dönemin sonuna yakınlık; serbest kredinin hırsa göre bir payı. Sonuçları settle_bot
    verir (kazanırsa eşya, geçilirse kredi geri)."""
    import muzayede as MZ
    settle_bot(b, now)
    from . import ganimet as GB
    serbest = b.k['kredi'] - b.klan_birikimi()
    if serbest < 3 * MZ.D.get('en_az_teklif', 10000):
        return
    adaylar = []
    for lot in list(MZ.LOTS.values()):
        onem = lot_onemi(b, lot)
        if onem:
            end = MZ.period_end(lot['tur'], now)
            benim = b.k['muzayede']['teklifler'].get('%s|%s' % (lot['tur'], lot['loot']))
            adaylar.append((onem, lot, end, int(benim['teklif']) if benim and benim.get('bitis') == end else 0))
    savun = [a for a in adaylar if a[3] and a[3] <= (MZ.best(MZ.bids(a[1], a[2], skip=b.profil)) or (0,))[0]]
    if savun:
        onem, lot, end, eski = max(savun, key=lambda a: a[0])           # geçildi: karşılık (oyuncu gibi pencereye geri döner)
    else:
        istek = (0.6 if b.arketip == 'tuccar' else 0.2) * (0.5 + b.o('rekabet')) * (0.6 + 0.8 * b.o('hirs'))
        if not adaylar or b.r.random() > istek:
            return
        agirlik = [a[0] ** 3 * (1 + (a[1].get('fiyat') or 0) / 50000.0) for a in adaylar]      # önemli ve değerli lot öne
        onem, lot, end, eski = b.r.choices(adaylar, weights=agirlik)[0]
        if eski:
            return                                   # zaten önde
    loot = lot['loot']
    key = '%s|%s' % (lot['tur'], loot)
    # lotun fiyatı anında alımın uridyumu (tamamı için): krediye çevrilir (eskiden kredi sanılıyordu, ucuz lotlara hiç teklif yoktu)
    deger = int((lot.get('fiyat') or 0) * GB.KUR) or 1000000
    kalan = max(0.0, (end - now) / MZ.SPAN[lot['tur']])
    hirs = b.o('hirs')
    tavan = deger * (0.35 + 0.4 * b.o('rekabet') + 0.25 * (1 - kalan)) * (0.7 + 0.3 * (b.arketip == 'tuccar'))
    if onem >= 3:
        tavan *= 1 + hirs + 0.25 * (onem - 3)       # CPU ve gemi: hırslı bot anında alım değerinin iki katına kadar çıkar
    tavan = min(tavan, serbest * (0.5 + (0.45 * hirs if onem >= 3 else 0)))
    rakip = MZ.best(MZ.bids(lot, end, skip=b.profil))
    simdi = rakip[0] if rakip else 0
    teklif = max(MZ.D.get('en_az_teklif', 10000), int(simdi * b.r.uniform(1.05, 1.25)) + MZ.D.get('artis', 1000))
    if teklif > tavan and simdi + MZ.D.get('artis', 1000) <= tavan:
        teklif = int(tavan)                          # son kuruşuna kadar: tavanı geçmeden en yüksek
    if teklif > tavan or not b.ode('C', teklif - eski):
        return
    b.k['muzayede']['teklifler'][key] = {'teklif': teklif, 'bitis': end, 'zaman': int(now)}
    b.olay('muzayede_teklif', now, esya=loot, teklif=teklif)


def hos_geldin_postasi(y, b, k, ad):
    from . import araclar as AR
    from . import konusma as KN
    metin = KN.kalip(b, 'posta_hosgeldin', klan=k['ad'], etiket=k['etiket'])
    if metin:
        AR.cagir(y, b, 'posta_gonder', {'ad': ad, 'konu': '[%s] %s' % (k['etiket'], k['ad']), 'metin': metin})


def posta_isleri(y, b, now):
    """Gelen posta: insanın (paketin botları değil) okunmamış mesajı bir süre sonra okunur; içindeki istek (grup, klan, arkadaşlık,
    gel) karar motoruyla uygulanır ve postayla yanıt verilir (Gelişmiş kipte metni dil modeli yazar)."""
    import posta as PS
    p = profil(b)
    with p.lock:
        gelen = [r for r in p.d.get('posta', {}).get('gelen', ()) if r.get('durum') == PS.OKUNMADI]
    for r in gelen:
        if r.get('tur') not in (PS.USER, PS.CLAN) or str(r.get('gonderen', '')).lower() in y.ada or not r.get('gonderen'):
            with p.lock:
                r['durum'] = PS.OKUNDU                       # sistem, müzayede, bot postası: okunur geçilir
            continue
        gordu = r.setdefault('_bot_gordu', now)
        if now - gordu < b.k['kisilik']['tepki_sn'] * 20 + b.r.uniform(30, 300):
            continue                                         # postaya hemen değil, birkaç dakika sonra bakar
        with p.lock:
            r['durum'] = PS.OKUNDU
        posta_yanitla(y, b, r, now)
        return                                               # tick başına bir posta


def posta_kalibi(b, k):
    """Kararın postaya uygun kalıp metni (sohbet kalıpları postaya fazla kısa: "inv me", "no thx") ya da None."""
    from . import konusma as KN
    if not k:
        return None
    if k['niyet'] == 'grup':
        return KN.kalip(b, 'posta_grup_evet' if k['kabul'] else 'posta_grup_hayir')
    metin = KN.kalip(b, k['kalip'][0], **k['kalip'][1]) if k.get('kalip') else None
    return metin and (metin + ', ' + KN.kalip(b, 'posta_cevap') if len(metin.split()) < 4 else metin)


def posta_yanitla(y, b, r, now):
    from . import araclar as AR
    from . import etkilesim as ET
    from . import konusma as KN
    import topluluk as TP
    ad = r['gonderen']
    o = TP.bul(ad=ad)
    kim = {'userId': ad, 'id': str(r.get('gonderen_id', 0)),
           'factionId': str(o.profil.d['pilot'].get('factionId', 0)) if o is not None else '0'}
    metin = '%s\n%s' % (r.get('konu', ''), r.get('metin', ''))
    niyet, harita = KN.niyet(metin)
    k = ET.karar(y, b, niyet, ad, kim, harita, metin, now, posta=True) if niyet in ET.NIYETLER and niyet != 'yardim' else None
    ET.uygula(y, b, k)
    b.hafiza.olay(ad, 'sohbet', now)
    b.olay('posta_geldi', now, ad=ad)
    konu = 'Re: ' + str(r.get('konu', ''))[:46]
    if y.llm is not None and y.llm.hazir and y.llm.posta(y, b, r, k):
        return                                               # Gelişmiş: metni model yazar (llm._posta)
    govde = posta_kalibi(b, k) or KN.kalip(b, 'posta_cevap')
    if govde and (k is not None or b.r.random() < 0.85):           # karar verdiyse sessiz kalmaz
        AR.cagir(y, b, 'posta_gonder', {'ad': ad, 'konu': konu, 'metin': govde + ('' if len(govde) >= 5 else ' :)')})


def settle_bot(b, now):
    """Biten dönemlerdeki bot teklifleri: en yüksekse eşya, değilse kredi geri."""
    import muzayede as MZ
    t = b.k['muzayede']['teklifler']
    for key, bd in list(t.items()):
        if bd['bitis'] + 120 > now:
            continue                                     # oyuncunun sonucu (Muzayede.settle) bot teklifini görsün diye biraz sonra
        tur, loot = key.split('|', 1)
        lot = MZ.LOTS.get((tur, loot))
        en = MZ.best(MZ.bids(lot, bd['bitis'])) if lot else None
        del t[key]
        if lot and en and en[3] == b.uid:
            g = b.k['muzayede'].setdefault('gecmis', [])          # oyuncunun müzayede geçmişi de gösterir (Muzayede.history)
            g.insert(0, {'grup': lot['grup'], 'kim': b.uid, 'teklif': int(bd['teklif']), 'tarih': MZ.stamp(bd['bitis'] - MZ.SPAN[tur]),
                         'loot': loot, 'tur': tur, 'ad': b.ad})
            del g[MZ.D['gecmis_siniri']:]
            if not b.ekle(loot, lot.get('adet', 1)):
                b.kazan(kredi=int(bd['teklif']) // 2)       # işine yaramayan: satar (yarı değer)
            b.olay('muzayede_kazandi', now, esya=loot)
            b.ruh.it(moral=0.15)
        else:
            b.kazan(kredi=int(bd['teklif']))
