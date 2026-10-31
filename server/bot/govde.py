"""Somut botlar: oyuncunun haritasındaki botların gemisi (BotGemi, dunya.World.npcs içinde) ve taktik davranışı.

Bot uzaylı tablosunda durur ama istemciye oyuncu gibi görünür (ShipCreateCommand npc=False, firma, rütbe, klan etiketi, dronlar):
görüş, seçme, oyuncunun lazeri/roketi/yetenekleri, ortak harita paylaşımı dünyanın uzaylı yolundan kendiliğinden çalışır. Ayrıldığı
yerler (dunya.py kancaları):
  ship_create   -> gorunum         oyuncu görünümü
  think         -> dusun           taktik: portala git, kaç, karşılık ver, PvP, uzaylı avla, dinlen
  think (NPC)   -> npc_bota        bot vurduğu uzaylı ona döner ve ateş eder
  laser_start   -> saldiri_hatasi  oyuncunun saldırı kuralları (DMZ, başlangıç haritasında kendi firması)
  hit_npc       -> vuruldu         aynı kurallar + bot saldıranı hatırlar
  kill          -> olduruldu       PvP ödülü (oyuncu_savas.on_kill), bot ölür, üste döner
  hero_death    -> oyuncu_oldu     botun zaferi (onur, hafıza)
  step (lider)  -> tick            yöneticinin bu haritadaki botlarıyla eşitleme (saniyede bir)
  stop          -> ayril           gemiler kaldırılır, botlar soyut benzetime döner

Taktik düşünme insan tepki süresiyle (kişiliğin tepki_sn'si) aralıklı; ateş 1,1 sn'de bir. Savaş görselleri yalnız iki ucu da
tanıyan istemcilere gider (görüş dışındaki bot uzaylı keserken gönderilmez).
"""
import math, random, time

import dunya as DN
import harita as H
from eski_protokol import legacy
from . import katalog as K
from . import soyut as S
from . import gorunum as GR
from . import toplum as T
from . import yonetici as YN

TASIYICI = next(iter(DN.CFG['tipler']))       # NPC.__init__ için var olan bir tür (sonra botun değerleriyle değiştirilir)
LAZER_MENZIL = DN.SAVAS['lazer_menzil']
SAVAS_SN = 8.0                                 # son hasardan bu kadar sonra yenilenir
YENILENME = 0.02                               # savaş dışında saniyede azami can+kalkanın payı
ATLAMA_SN = H.JUMP_DELAY_SN
GELIS_SN = 10.0                 # atlayan bot bu süre içinde gövdelenirse varış portalında doğar (sonra uçup gitmiştir)
SAVAS_ARALIK = DN.SAVAS['lazer_aralik_sn']


class BotGemi(DN.NPC):
    def __init__(self, bot, x, y, now=None):
        DN.NPC.__init__(self, bot.uid, TASIYICI, x, y)
        self.bot = bot
        self.tip = 'bot'
        self.summoned = True                    # uzaylı gibi yeniden doğmaz (botu yönetici doğurur)
        self.hedef = None                       # ateş ettiği (kimlik)
        self.ates = False
        self.saldiran = {}                      # kimlik -> son vuruş anı
        self.son_hasar = 0.0
        self.portal_t = 0.0
        self.hareket = None                     # son gönderilen hedef nokta
        self.niyet_t = 0.0                      # PvP başlatma kararının son anı
        self.dogus = now or time.time()
        self.next_think = self.dogus + random.uniform(0.3, 1.5)
        self.kalkis = random.triangular(1.5, 18, 4)     # doğunca yola hemen çıkmaz: herkes aynı anda tek sıra kalkmasın
        self.rota = None                        # (hedef, [ara noktalar]): uzun yolda eğri rota (_rota)
        self.yanas = {}                         # portal -> yanaşma noktası (portalın çevresinde, bota özgü)
        self.next_shot = 0.0
        d = bot.deger()
        self.d = {}
        self.yenile()
        self.hp, self.shield = d['can'], d['kalkan']

    def yenile(self):
        """Donanım değişti: görünüm, değerler, dronlar."""
        b = self.bot
        d = b.deger()
        e = b.k['ekip']
        self.model = e['gemi']
        self.d = dict(ad=b.ad, hp=int(d['can']), kalkan=int(d['kalkan']), hasar=0, hiz=int(d['hiz']), saldirgan=False,
                      odul=dict(ep=0, onur=0, kredi=0, uridyum=0), kargo={}, npc_kimlik=0,
                      genisleme=3 if d['lazer'] >= 12 else 2 if d['lazer'] >= 6 else 1, bot=True)
        self.davranis = {}
        self.hp, self.shield = min(self.hp, d['can']), min(self.shield, d['kalkan'])
        dronlar = [(K.ESYA['dronlar'][l]['tur'], min(6, 1 + b.seviye // 4)) for l, n in e.get('dron', {}).items()
                   for _ in range(n) if l in K.ESYA['dronlar']]
        self.gorseller = {'dron': legacy('0|n|d|%d|0|%s' % (self.id, '|'.join('%d|%d|0|0' % x for x in dronlar)))} if dronlar else {}

    def speed(self):
        return self.d['hiz']


# ------------------------------------------------------------------------------------------------------------ görünüm
def gorunum(w, n):
    b = n.bot
    x, y = n.mover.pos(time.time())
    T.profil(b)
    pl = b.profil.d['pilot']
    return ('ShipCreateCommand', dict(
        userId=n.id, typeId=GR.tip(b), expansionStage=n.d['genisleme'], userName=b.ad, x=int(x), y=int(y),
        clanTag='CM' if b.__dict__.get('moderator') else pl.get('clanTag', ''),        # sohbet moderatörü (bot/moderasyon.py)
        factionId=b.firma, clanId=int(pl.get('clanId') or 0), dailyRank=pl.get('dailyRank', 1), warnBox=False,
        clanDiplomacy=DN.mod('ClanRelationModule', type=iliski(w, b)), galaxyGatesDone=GR.halkalar(b), useSystemFont=False, npc=False,
        cloaked=False, motherShipId=0, positionIndex=0, designSet='', modifier=[],
        minimapStrategyModule=DN.mod('MinimapStrategyModule', minimapStrategy=0), specialNpcType=''))


def ek_gorunum(n):
    return GR.mesajlar(n)


def iliski(w, b):
    """Klanlar arası ilişki (ClanRelationModule.type: 1 ittifak, 2 saldırmazlık, 3 savaş) ya da 0."""
    try:
        import klan as KL
        return KL.iliski(w.p, T.profil(b))
    except Exception:
        return 0


# ------------------------------------------------------------------------------------------------------------ eşitleme
def tick(w, now):
    """Saniyede bir: yöneticinin bu haritadaki çevrimiçi, yaşayan, yoldan çıkmamış botları gemi olarak var olur; ayrılanlar kalkar."""
    y = YN.AKTIF
    if y is None or now < getattr(w, '_bot_t', 0):
        return
    w._bot_t = now + 1.0
    try:
        m = int(w.map_id)
    except ValueError:
        return
    if kapi_dunyasi(w):
        return kapi_tick(w, now, y)
    with y.lock:
        istenen = {b.uid: b for b in y.haritada.get(m, ()) if b.cevrimici and b.olu_bitis <= now
                   and now - b.__dict__.get('kapida', 0) > 5}           # oyuncuyla kapıdaki bot başka haritada görünmez
    var = {uid: n for uid, n in w.npcs.items() if n.bot is not None}
    msgs = []
    for uid, n in var.items():
        if uid not in istenen:
            msgs += kaldir(w, n)
    sinir = y.ayar('somut_en_cok', 40) or 9999
    sayi = len(var) - sum(1 for u in var if u not in istenen)
    if len(istenen) > sinir:                             # sınır doluysa: sana yakın, seninle geçmişi olan, grubundaki botlar önce
        hx, hy = w.hero_pos(now)
        ad = str(w.p.d['pilot'].get('userName', '')).lower()

        def oncelik(b):
            x, yy = b.k.get('x') or 0, b.k.get('y') or 0
            tanis = ad in (b.k.get('hafiza') or {})
            return (not w.grup_uyesi(b.uid), not tanis, math.hypot(x - hx, yy - hy))
        istenen = dict(sorted(istenen.items(), key=lambda kv: oncelik(kv[1])))
    for uid, b in istenen.items():
        if b.govde is not None and (not b.govde.alive or w.npcs.get(b.govde.id) is not b.govde):
            b.govde = None                                # dışarıdan silinmiş gemi (hata ayıklama, çöken dünya): bot donmasın
        if uid in var or sayi >= sinir or b.govde is not None:
            continue
        x, yy = dogus_yeri(w, b)
        n = BotGemi(b, x, yy, now)
        if b.__dict__.pop('yerinde_tamir', None):       # yerinde tamir: canın %10'u, kalkansız, 10 sn koruma (oyuncununki gibi)
            n.hp, n.shield = max(1, int(n.hp * K.ESYA['olum_ekrani']['yerinde_can_orani'])), 0
            n.dokunulmaz = now + K.ESYA['olum_ekrani']['yerinde_koruma_sn']
        w.npcs[n.id] = n
        b.govde = n
        b.k['x'], b.k['y'] = x, yy
        sayi += 1
    if msgs:
        w.send(msgs)


def kapi_dunyasi(w):
    """Kapı ya da örnek harita (Galaksi Kapısı, Hades, LoW, QZ, etkinlik kapıları): olağan harita değil."""
    try:
        m = int(w.map_id)
    except ValueError:
        return True
    return m not in K.HARITALAR or getattr(w, 'kapi', None) is not None and bool(getattr(w.kapi, 'key', None)) \
        or getattr(w, 'low', None) is not None


def kapi_tick(w, now, y):
    """Kapı dolgusu (oyuncu isteği 2026-10-31): kahramanın grubundaki botlar kapıya onunla girer (kapının yanında doğar), grubun
    hedefini (Grup) izleyip uzaylılara ateş eder; kendi kapısında ya da modunda olan, ölü ya da çevrimdışı bot gelmez. İzin
    'kapi_dolgu'; kapalıysa kapıda bot yok (eskisi gibi)."""
    import grup as GR
    istenen = {}
    if y.izin('kapi_dolgu') and not w.hero_dead:
        g = GR.grubu(w.hid)
        with y.lock:
            for b in y.botlar:
                if (g is not None and b.uid in g.uyeler and b.cevrimici and b.olu_bitis <= now
                        and (b.hedef is None or b.hedef.ad not in ('kapi', 'mod', 'duello'))):
                    istenen[b.uid] = b
    msgs = []
    for uid, n in [(u, n) for u, n in w.npcs.items() if n.bot is not None]:
        if uid not in istenen:
            msgs += kaldir(w, n)
    hx, hy = w.hero_pos(now)
    for uid, b in istenen.items():
        b.kapida = now
        if b.hedef is None or b.hedef.ad != 'grup':
            from . import beyin as BN
            BN.zorla(b, 'grup', pay=2.0, sure=3600, now=now)
        if b.govde is not None and (not b.govde.alive or w.npcs.get(b.govde.id) is not b.govde):
            b.govde = None
        if uid in w.npcs or b.govde is not None:
            continue
        a = random.uniform(0, 2 * math.pi)
        x, yy = int(hx + math.cos(a) * random.uniform(150, 400)), int(hy + math.sin(a) * random.uniform(150, 400))
        x, yy = max(300, min(w.map_w - 300, x)), max(300, min(w.map_h - 300, yy))
        n = BotGemi(b, x, yy, now)
        w.npcs[n.id] = n
        b.govde = n
        b.olay('kapiya_girdi', kapi=str(getattr(getattr(w, 'kapi', None), 'key', '') or w.map_id))
    if msgs:
        w.send(msgs)


def dogus_yeri(w, b):
    gelis = getattr(b, 'gelis', None)
    b.gelis = None
    # portalda yalnız az önce atlayan doğar: oyuncu yokken atlayıp soyut kalanlar oyuncu gelince hep birlikte portaldan çıkıyordu
    # (oyuncu bildirimi: 2-1'de portalda bekleyip 2-2'ye geçince 10-20 bot oyuncuyla aynı anda portaldan çıktı)
    if gelis is not None and time.time() - gelis[1] < GELIS_SN:
        gx, gy = H.arrival(gelis[0], int(w.map_id), b.firma)
        a, r = random.uniform(0, 2 * math.pi), random.uniform(80, 280)      # portalın çevresinde dağınık (üst üste değil)
        return int(gx + math.cos(a) * r), int(gy + math.sin(a) * r)
    x, y = b.k.get('x') or 0, b.k.get('y') or 0
    if 300 < x < w.map_w - 300 and 300 < y < w.map_h - 300:
        return int(x), int(y)
    s = w.station
    if s and s.get('type') == b.firma:          # yeni giren ya da üste dönen: kendi istasyonunun çevresinde (gerçek oyundaki gibi)
        a, r = random.uniform(0, 2 * math.pi), random.uniform(250, 1300)
        return (int(max(400, min(w.map_w - 400, s['posX'] + math.cos(a) * r))),
                int(max(400, min(w.map_h - 400, s['posY'] + math.sin(a) * r))))
    return w.random_spot()


def kaldir(w, n):
    """Gemi haritadan kalkar (çıkış, atlama, ölüm sonrası): konum kayda, bot soyut benzetime."""
    n.alive = False
    b = n.bot
    x, y = n.mover.pos(time.time())
    b.k['x'], b.k['y'] = int(x), int(y)
    if b.govde is n:
        b.govde = None
    b.son_soyut = time.time()
    return w.remove_npc(n) + ([('AttackAbortLaserCommand', {'uid': n.id})] if n.ates else [])


def ayril(w):
    """Dünya duruyor: ortak haritada başka oyuncu kalmadıysa gemiler kaldırılır (harita durumu saklanmadan önce)."""
    if w.ortak is not None and any(o is not w and o.running for o in w.ortak.uyeler):
        return
    with w.lock:
        for n in [n for n in w.npcs.values() if n.bot is not None]:
            kaldir(w, n)


# ------------------------------------------------------------------------------------------------------------ yardımcılar
def _konum(w, uid, now):
    n = w.npcs.get(uid)
    if n is not None:
        return n.mover.pos(now) if n.alive else None
    o = _oyuncu(w, uid)
    return o.hero_pos(now) if o is not None else None


def _oyuncu(w, uid):
    """Kimliği uid olan kahramanın dünyası (bu dünya ya da ortak haritadaki öteki oyuncu) ya da None."""
    if uid == w.hid:
        return w
    if w.ortak is not None:
        return next((o for o in w.ortak.uyeler if o.hid == uid and o.running), None)
    return None


def _yayin(w, msgs, *uids):
    """Savaş görseli: bu dünyanın istemcisi iki ucu da tanıyorsa ona; ortak haritada öteki oyunculara (yansit kendisi süzer)."""
    if not msgs:
        return
    if all(w.tanir(u) for u in uids):
        w.send(msgs)
    elif w.ortak is not None:
        w.ortak.yansit(w, msgs)


def _git(w, n, x, y, now, esik=80):
    x = max(200, min(w.map_w - 200, x))
    y = max(200, min(w.map_h - 200, y))
    h = n.hareket
    if h is not None and math.hypot(h[0] - x, h[1] - y) < esik and n.mover.t1 > now:
        return
    n.hareket = (x, y)
    ms = n.mover.go(x, y, n.speed(), now)
    w.send([('MoveCommand', dict(userId=n.id, x=int(x), y=int(y), timeToTarget=ms))])


def _ara_noktalar(w, n, sx, sy, x, y):
    """Uzun yolun ara noktaları: rotaya dik, hafif bir yay (sinüs) üstünde; yönü ve genişliği bota ve yolculuğa göre tohumlu (her
    botun yolu başka, aynı yolculukta değişmez). Kısa yol doğrudan."""
    d = math.hypot(x - sx, y - sy)
    k = 0 if d < 1500 else 1 if d < 3500 else 2 if d < 7000 else 3
    if not k:
        return []
    r = random.Random('%s|%d|%d|%d' % (n.bot.ad, int(n.dogus), int(x) // 50, int(y) // 50))
    ux, uy = (x - sx) / d, (y - sy) / d
    genislik = r.choice((-1, 1)) * d * r.uniform(0.05, 0.17)
    out = []
    for i in range(1, k + 1):
        t = i / (k + 1.0) + r.uniform(-0.04, 0.04)
        s = genislik * math.sin(math.pi * t) + d * r.uniform(-0.025, 0.025)
        out.append((max(250, min(w.map_w - 250, sx + ux * d * t - uy * s)), max(250, min(w.map_h - 250, sy + uy * d * t + ux * s))))
    return out


def _rota(w, n, x, y, now, esik=150):
    """Uzun yolculuk (portal, istasyon, devriye): düz çizgi yerine ara noktalı hafif bir yay; ara noktaya varmadan sıradakine döner
    (durup kalkmaz). Oyuncu bildirimi 2026-10-31: haritaya girince botlar tek sıra, dümdüz ve aynı yoldan portala uçuyordu."""
    nx, ny = n.mover.pos(now)
    r = n.rota
    if r is None or math.hypot(r[0][0] - x, r[0][1] - y) > esik:
        r = n.rota = ((x, y), _ara_noktalar(w, n, nx, ny, x, y))
    ara = r[1]
    erken = max(250, n.speed() * 1.6)                     # bir düşünme aralığında alınan yol: köşede beklemesin
    kalan = math.hypot(x - nx, y - ny)
    while ara and (math.hypot(ara[0][0] - nx, ara[0][1] - ny) < erken
                   or math.hypot(x - ara[0][0], y - ara[0][1]) > kalan):     # geride kaldı (araya savaş girdi): geri dönmez
        ara.pop(0)
    hx, hy = ara[0] if ara else (x, y)
    _git(w, n, hx, hy, now, esik=60)


def _dur(w, n, now):
    if n.mover.t1 > now:
        x, y = n.mover.pos(now)
        _git(w, n, x, y, now, esik=0)


def kahraman_gucu(o):
    """Oyuncunun kabaca gücü (botun kararı için): lazerleri ve gemisinin canı/kalkanı."""
    try:
        lz = sum(K.ESYA['lazerler'].get(l, {}).get('hasar', 0) for l in o.lasers())
        g = o.p.d['gemi']
        carpan = K.ESYA['lazer_cephane'].get(o.p.d.get('secili', {}).get('lazer'), {}).get('carpan', 1)
        dps = lz * min(carpan, 3) * 0.88 * 0.8 / SAVAS_ARALIK
        ehp = g.get('hitMax', 0) + g.get('shieldMax', 0) * 2.5 * 0.9
        return K.guc_puani(dps, ehp)
    except Exception:
        return 50.0


def _barista(w, x, y):
    return w.in_pvp_peace(x, y)


# ------------------------------------------------------------------------------------------------------------ kurallar
def saldiri_hatasi(w, n, now=None):
    """Oyuncunun bu bota saldırısı -> [] serbest ya da istemcinin ret mesajları (oyuncu_savas.attack_error'ın kuralları)."""
    now = now or time.time()
    b = n.bot
    if w.hero_dead or w.jumping or not n.alive:
        return [legacy('0|A|STM|msg_grp_attack_impossible')]
    hx, hy = w.hero_pos(now)
    nx, ny = n.mover.pos(now)
    if _barista(w, hx, hy) or _barista(w, nx, ny):
        # güvenli bölge: "Saldırıya-Korumalı-Bölge" (istemcinin peacearea'sı; "Grup üyelerine saldırılamaz" yazıyordu, oyuncu
        # bildirimi 2026-10-30)
        return [legacy('0|A|STM|peacearea')]
    pl = w.p.d['pilot']
    klan = int(pl.get('clanId') or 0)
    if klan and klan == int(T.profil(b).d['pilot'].get('clanId') or 0):
        return [legacy('0|A|STM|friendlyfire_disabled')]
    if iliski(w, b) in (1, 2):
        return [legacy('0|A|STM|friendlyfire_disabled')]
    if int(pl.get('factionId') or 0) == b.firma and H.company(w.map_id) == b.firma and H.name(w.map_id).split('-')[-1] in ('1', '2'):
        return [legacy('0|A|STM|no_attack_on_start_maps')]
    return []


def vuruldu(w, n, attacker=None):
    """hit_npc: vuruş geçerli mi; geçerliyse bot saldıranı (kahraman ya da P.E.T.'i) hatırlar."""
    now = time.time()
    from . import aktif as AK
    # Insta-Shield süresinde vurulmaz; gizliyken yalnız onu seçmiş olan vurur (wiki: "Cloaked ships can still be attacked (if
    # targeted)"; oyuncu bildirimi 2026-10-31: gizlenen bota saldırılamıyordu)
    if saldiri_hatasi(w, n, now) or now < n.__dict__.get('dokunulmaz', 0) or (n.__dict__.get('gizli') and w.target != n.id):
        return False
    n.saldiran[w.hid] = now
    n.son_hasar = now
    if n.next_think > now + 0.3:
        n.next_think = now + min(0.6, n.bot.k['kisilik']['tepki_sn'])
    return True


# ------------------------------------------------------------------------------------------------------------ ölüm
def olduruldu(w, n):
    """Oyuncu (ya da P.E.T.'i, mayını, yeteneği) botu yok etti -> mesajlar (kill'in yerine)."""
    import oyuncu_savas as OS
    b = n.bot
    x, y = n.mover.pos(time.time())
    msgs = kaldir(w, n)
    if any(m[0] == 'ShipRemoveCommand' for m in msgs):
        msgs.insert(0, ('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0)))
    p = T.profil(b)
    p.d['gemi']['hitPoints'] = 0

    class Kurban:
        pass
    kurban = Kurban()
    kurban.p = p
    try:
        msgs += OS.on_kill(w, kurban)
    except Exception as e:
        w.log('   bot ödülü verilemedi: %s' % e)
    ad = w.p.d['pilot'].get('userName', '')
    if b.hedef is not None and b.hedef.ad == 'duello':
        b.plan['bitti'] = True                           # düelloyu kaybetti
        b.k['niyet'] = None
    y_ = YN.AKTIF
    if y_ is not None:
        with y_.lock:
            S.olum(b, y_, neden='oyuncu', katil=ad, now=time.time())
    w.log('   bot %s yok edildi (%s)' % (b.ad, H.name(w.map_id)))
    return msgs


def oyuncu_oldu(w, n):
    """Bot oyuncuyu yok etti: onur ve hafıza (oyuncunun ölüm ekranı dünyada)."""
    b = n.bot
    ad = w.p.d['pilot'].get('userName', '')
    oo = K.ESYA['oyuncu_oldurme']
    y = YN.AKTIF
    hiz = y.hiz(b) if y is not None else 1.0
    b.odul(None, hiz, ep=oo['ep_puan'], onur=oo['onur_puan'])
    b.ist('oyuncu')
    b.ist('oyuncu_puan', T.gemi_rutbe_puani(w.p.ship()['lootId']))
    b.hafiza.olay(ad, 'oldurdum')
    b.ruh.it(moral=0.12, ozguven=0.1, ofke=-0.3)
    b.olay('oyuncu_oldurdum', ad=ad)
    if b.hedef is not None and b.hedef.ad == 'duello':
        b.plan['bitti'] = True                           # düelloyu kazandı
        b.k['niyet'] = None
    n.hedef = None


def bot_hasar(w, t, dmg, kaynak_id, now, katil_bot=None, npc=None):
    """Bot gemisi hasar aldı (uzaylıdan ya da başka bottan): kalkan emer, can biterse bot ölür."""
    from . import aktif as AK
    if not t.alive or AK.korumali(t, now):
        return
    emme = t.bot.deger()['emme']
    to_shield = min(int(t.shield), int(dmg * emme))
    t.shield -= to_shield
    t.hp = max(0, t.hp - (dmg - to_shield))
    t.son_hasar = now
    t.saldiran[kaynak_id] = now
    msgs = [('AttackHitCommand', dict(attackType=DN.attack_type(1), attackerId=kaynak_id, victimId=t.id, victimHitpoints=int(t.hp),
                                      victimShield=int(t.shield), victimNanoHull=0, damage=int(dmg), skilled=False, strike=False,
                                      cannonType=0))]
    if w.target == t.id:
        msgs.append(w.selection(t))
    _yayin(w, msgs, kaynak_id, t.id)
    if t.hp <= 0:
        bot_ol(w, t, katil_bot, npc)


def bot_ol(w, t, katil_bot=None, npc=None):
    b = t.bot
    msgs = kaldir(w, t)
    if any(m[0] == 'ShipRemoveCommand' for m in msgs):
        msgs.insert(0, ('ShipDestroyedCommand', dict(destroyedUserId=t.id, explosionTypeId=0)))
    w.send(msgs)
    y = YN.AKTIF
    if y is None:
        return
    with y.lock:
        if katil_bot is not None:
            S.pvp_odul(katil_bot, b, y, time.time())
        S.olum(b, y, neden='oyuncu' if katil_bot else 'npc', katil=katil_bot.ad if katil_bot else None, now=time.time())


def npc_oldur(w, m, n, now):
    """Bot uzaylıyı öldürdü: uzaylı kalkar ve yeniden doğar (kill'in ödülsüz hâli), ödül bota, kargo kutusu yanına (botun; başkaları
    mavi görür). Uzaylı başkasının etiketliyse (oyuncunun ya da başka botun) dünyanın kill'i ödülü ona verir."""
    kim = DN.etiket_sahibi(m, now)
    if kim is not None and tuple(kim) != ('b', n.id):
        w.send(w.kill(m))
        n.hedef = None
        return
    m.alive = False
    w.npcs.pop(m.id, None)
    x, y = m.mover.pos(now)
    msgs = w.pet.npc_gone(m.id) if w.pet else []
    if m.id in w.visible:
        w.visible.discard(m.id)
        msgs += [('ShipDestroyedCommand', dict(destroyedUserId=m.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': m.id})]
    if w.target == m.id:
        w.target, w.attacking = None, False
        msgs.append(('ShipDeselectionCommand', {}))
    if not m.gate and not m.summoned and not m.d.get('sayilmaz'):
        w.schedule(random.uniform(*w.respawn_range(m)), 'npc', m.tip)
    try:
        msgs += w.alien.on_kill(m, x, y)
    except Exception:
        pass
    w.send(msgs)
    # grup (grup.py): bot kahramanla gruptaysa ödül haritadaki kahramanla ve gruptaki botlarla paylaşılır, kahramanın görevine sayılır
    pay = [w] if w.grup_uyesi(n.id) and w.running and not w.hero_dead and not w.jumping else []
    botlar = [n.bot] + ([o for o in grup_botlari(w) if o is not n.bot] if pay else [])
    for b in botlar:
        npc_odulu(b, m, len(pay) + len(botlar))
    for h in pay:
        h.npc_reward(m, x, y, len(pay) + len(botlar), own=False)
    kargo_birak(w, m, n.id, x, y)
    if patron_mu(m):
        n.bot.olay('patron_oldurdum', ad=m.d.get('ad', ''))
        tanik(w, 'patron', x, y, haric=n.id, ad=m.d.get('ad', ''), kim=n.bot.ad)
    n.hedef = None
    n.next_think = now + random.uniform(0.8, 2.5) * n.bot.k['kisilik']['tepki_sn']      # öldürünce kısa duraklama (ganimete bakar)


# ------------------------------------------------------------------------------------------------------------ ateş
def _cephane(n, hedef, m, o):
    """Bu atışın cephanesi stoktan (silah.lazer_sec: dayanıklı uzaylıya x2/x3, PvP'de RSB/x3; hedef başına bir kez seçilir, gerçek
    oyuncu gibi) ve harcanması: lazer sayısı kadar mermi -> cephane ya da None (mermi yok, ateş edemez)."""
    from . import silah as SL
    b = n.bot
    if getattr(n, 'cep_hedef', (None,))[0] != hedef or SL.stok(b).get(n.cep_hedef[1], 0) <= 0:
        pvp = o is not None or (m is not None and m.bot is not None)
        ehp = 0 if pvp or m is None else m.d.get('hp', 0) + m.d.get('kalkan', 0)
        n.cep_hedef = (hedef, SL.lazer_sec(b, ehp, pvp))
    cep = n.cep_hedef[1]
    if cep is None:
        return None
    lazer = max(1, len(K.donat(b.k['ekip'], b.kalkan_payi())['lazer']))
    if not SL.harca(b, cep, lazer):
        return None
    from . import lab as LB
    n.lab_atis = LB.bonus(b, LB.LAZER)                   # bu atışın laboratuvar bonusu
    LB.harca(b, LB.LAZER, lazer)
    return cep


def _renk(b, cephane=None):
    lr = K.ESYA['lazer_renkleri']
    e = b.k['ekip']
    c = cephane or e['cephane']
    lz = [l for l, k in e['lazer'].items() if k]
    if len(lz) == 1 and c in lr['tam_set'].get(lz[0], {}):
        return lr['tam_set'][lz[0]][c]
    return lr['cephane'].get(c, 0)


def _atis(b, pvp=False, cephane=None):
    y = K.donat(b.k['ekip'], b.kalkan_payi())
    carpan = K.ESYA['lazer_cephane'].get(cephane or b.k['ekip']['cephane'], {}).get('carpan', 1)
    lab = b.govde.lab_atis if b.govde is not None and hasattr(b.govde, 'lab_atis') else 0.0
    return int(sum(y['lazer']) * carpan * (1 + lab) * random.uniform(*K.ESYA['hasar_rastgele']))


def ates(w, n, now):
    """Hedefe ateş (1,1 sn'de bir): uzaylıya, oyuncuya ya da başka bota."""
    if n.hedef is None:
        if n.ates:
            n.ates = False
            _yayin(w, [('AttackAbortLaserCommand', {'uid': n.id})], n.id)
        return
    if now < n.next_shot:
        return
    pos = _konum(w, n.hedef, now)
    if pos is None:
        n.hedef = None
        return
    nx, ny = n.mover.pos(now)
    if math.hypot(pos[0] - nx, pos[1] - ny) > LAZER_MENZIL:
        return
    n.next_shot = now + SAVAS_ARALIK
    hedef = n.hedef
    m = w.npcs.get(hedef)
    o = _oyuncu(w, hedef) if m is None else None
    if o is not None and not oyuncuya_saldirabilir(w, n, o, now):
        n.hedef = None
        return
    if m is not None and m.bot is not None and not bota_saldirabilir(w, n, m, now):
        n.hedef = None
        return
    cep = _cephane(n, hedef, m, o)
    if cep is None:                                      # mermisi bitti: ateş edemez (ikmal karar anında)
        if n.ates:
            n.ates = False
            _yayin(w, [('AttackAbortLaserCommand', {'uid': n.id})], n.id)
        return
    n.ates = True
    roket(w, n, hedef, m, o, now)
    salvo(w, n, hedef, m, o, now)
    from . import aktif as AK, silah as SL
    AK.gorun(w, n)                                       # ateş eden gizli bot görünür olur
    if m is not None and m.bot is None:
        AK.chain_impulse(w, n, now)
    run = ('AttackLaserRunCommand', dict(attackerId=n.id, targetId=hedef, laserColor=_renk(n.bot, cep), isDiminishedBySkillShield=False,
                                         skilledLaser=False, visualType=0))
    zor = o is not None or (m is not None and (m.bot is not None or (m.d.get('hp', 0) + m.d.get('kalkan', 0))
                                               / max(1, n.bot.deger()['dps']) > SL.ZOR_SN))
    isabet = random.random() < AK.nisan(n, DN.SAVAS['lazer_isabet'], zor)      # AIM CPU (Xenomit)
    if o is not None:
        msgs = [run]
        if isabet:
            dmg = _atis(n.bot, pvp=True, cephane=cep)
            AK.leech(n, dmg, n.bot.deger()['can'], now)
            msgs += o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=now)
        else:
            msgs.append(('AttackMissedCommand', dict(attackType=DN.attack_type(1), targetUserId=hedef, skillColorId=0)))
        o.send(msgs)
        return
    if m is None or not m.alive:
        n.hedef = None
        return
    if not isabet:
        _yayin(w, [run, ('AttackMissedCommand', dict(attackType=DN.attack_type(1), targetUserId=hedef, skillColorId=0))], n.id, hedef)
        return
    dmg = _atis(n.bot, pvp=m.bot is not None, cephane=cep)
    AK.leech(n, dmg, n.bot.deger()['can'], now)
    if m.bot is not None:
        _yayin(w, [run], n.id, hedef)
        bot_hasar(w, m, dmg, n.id, now, katil_bot=n.bot)
        return
    npc_vur(w, n, m, dmg, now, 1, [run], ammo=cep)


def salvo(w, n, hedef, m, o, now):
    """Roket fırlatıcısının salvosu (dayanıklı uzaylıya ya da PvP'de): kapasite kadar roket, yarım saniye arayla; görseli roketin
    eski metni (fırlatıcı roketinin kimliğiyle), hasarı her roket varınca."""
    from . import teknoloji as TK, silah as SL
    b = n.bot
    if now < getattr(n, 'salvo_hazir', 0):
        return
    pvp = o is not None or (m is not None and m.bot is not None)
    zor = m is not None and m.bot is None and (m.d.get('hp', 0) + m.d.get('kalkan', 0)) / max(1, b.deger()['dps']) > SL.ZOR_SN
    fr = TK.froket_sec(b) if (pvp or zor) else None
    pos = _konum(w, hedef, now)
    nx, ny = n.mover.pos(now)
    if not fr or pos is None or math.hypot(pos[0] - nx, pos[1] - ny) > TK.FIRCATICI['menzil']:
        return
    kap, ara = TK.salvo(b)
    kap = SL.harca(b, fr, kap)
    if not kap:
        return
    n.salvo_hazir = now + ara
    r = TK.FCEPHANE[fr]
    dmg = int(r.get('pvp_hasar' if pvp else 'hasar', r['hasar']))
    for i in range(kap):
        def at(i=i):
            t = time.time()
            if not n.alive:
                return
            _yayin(w, [legacy('0|v|%d|%d|H|%d|0|0' % (n.id, hedef, r.get('kimlik', 9)))], n.id, hedef)

            def vur():
                t2 = time.time()
                if not n.alive:
                    return                                # ölmüş botun salvosu vurmaz
                if o is not None:
                    if oyuncuya_saldirabilir(w, n, o, t2):
                        o.send(o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=t2))
                    return
                x = w.npcs.get(hedef)
                if x is not None and x.alive:
                    if x.bot is not None:
                        bot_hasar(w, x, dmg, n.id, t2, katil_bot=b)
                    else:
                        npc_vur(w, n, x, dmg, t2, 0, ammo=fr)
            w.later(DN.SAVAS['roket_ucus_sn'], vur)
        w.later(i * 0.5, at)
    b.ist('salvo')


def oyuncu_yakin(w, m, now, menzil=1500):
    """Oyuncu uzaylının yakınında mı: bot vuruşunun tetiklediği oyuncuya yönelik etkiler (EMP, ters kontrol) yalnız o zaman."""
    if w.hero_dead or w.jumping:
        return False
    hx, hy = w.hero_pos(now)
    mx, my = m.mover.pos(now)
    return math.hypot(hx - mx, hy - my) <= menzil


def npc_vur(w, n, m, dmg, now, atype, once=(), kalkan=False, ammo=None):
    """Botun lazeri (atype 1) ya da roketi (0) uzaylıya: kalkan emer, gövde; ölürse npc_oldur, yoksa uzaylı bota döner.
    kalkan: yalnız kalkana (Chain Impulse). Uzaylının mekanikleri oyuncunun vuruşundaki gibi (dunya.hit_npc): yardımcıları yaşarken
    dokunulmazlık, yalnız belirli cephane, hasar azaltma, gizli komandonun görünmesi, vurulunca çağırma (yardımcılar botun çevresinde
    doğar, bota saldırır), can tabanı, can eşiğinde çağırma ve kaybolma (uzayli.on_hit; oyuncuya yönelik EMP ve ters kontrol yalnız
    oyuncu yakınsa). Önceden bot vuruşu bunları atlıyordu: Cubikon bota Protegit çağırmıyordu (kullanıcı bildirimi 2026-10-30)."""
    if not m.alive:
        return
    only = m.d.get('sadece_cephane')
    if (m.invulnerable and m.invulnerable()) or m.etki.invulnerable(now) or w.guarded(m) or (only and ammo not in only):
        dmg = 0
    red = getattr(m, 'hasar_azaltma', None)
    if red:
        dmg = int(dmg * max(0.0, 1 - red()))
    if getattr(m, 'gizli', False):                       # gizli komando vurulunca görünür (sizma.py)
        m.gizli = False
        w.send([legacy('0|n|INV|%d|0' % m.id)])
    w.alien.attacked(m, n.id, now)
    w.npc_summon(m, now, vuran=n)
    absorb = 1.0 if kalkan else m.d.get('kalkan_emme', DN.SAVAS['npc_kalkan_emme'])
    to_shield = min(int(m.shield), int(round(dmg * absorb)))
    m.shield -= to_shield
    m.hp = max(0, m.hp - (dmg - to_shield))
    floor = getattr(m, 'can_tabani', 0)                  # Guardian 1 HP'de "düşer" (evreler)
    if floor and m.hp < floor:
        m.hp = floor
        if getattr(m, 'tabanda', None):
            m.tabanda(m)
    m.last_hit = now
    w.alien.on_hit(m, dmg, n.id, now, oyuncuya=oyuncu_yakin(w, m, now))
    if not m.alive or m.id not in w.npcs:                 # kayboldu ya da kalktı (uzayli.on_hit)
        return
    DN.etiketle(m, ('h', w.hid) if yardimci(w, n, m, now) else ('b', n.id), now)
    hit = ('AttackHitCommand', dict(attackType=DN.attack_type(atype), attackerId=n.id, victimId=m.id, victimHitpoints=int(m.hp),
                                    victimShield=int(m.shield), victimNanoHull=0, damage=dmg, skilled=False, strike=False, cannonType=0))
    msgs = list(once) + [hit] + ([w.selection(m)] if w.target == m.id and m.hp > 0 else [])
    _yayin(w, msgs, n.id, m.id)
    if m.hp <= 0:
        npc_oldur(w, m, n, now)
    elif m.bot_hedef is None and not m.engaged and m.d['hasar'] > 0:
        m.bot_hedef = n.id                     # uzaylı bota döner
        m.next_think = now


def roket(w, n, hedef, m, o, now):
    """Roket (bekleme 4 sn, R0K-T01 ile 2): menzildeyse stoktaki en güçlüsü; görseli oyuncununki gibi eski metin (0|v|…), ~0,8 sn
    sonra vuruş (isabet roketin kendi oranı)."""
    from . import silah as SL
    b = n.bot
    if now < getattr(n, 'roket_hazir', 0):
        return
    rk = SL.roket_sec(b)
    pos = _konum(w, hedef, now)
    nx, ny = n.mover.pos(now)
    if not rk or pos is None or math.hypot(pos[0] - nx, pos[1] - ny) > DN.SAVAS['roket_menzil'] or not SL.harca(b, rk, 1):
        return
    n.roket_hazir = now + SL.roket_beklemesi(b)
    r = K.ESYA['roketler'][rk]
    isabet = random.random() < r.get('isabet', DN.SAVAS['roket_isabet'])
    _yayin(w, [legacy('0|v|%d|%d|%s|%d|0|0' % (n.id, hedef, 'H' if isabet else 'M', r.get('kimlik', 1)))], n.id, hedef)
    if not isabet:
        return
    from . import lab as LB
    dmg = int(r.get('pvp_hasar' if (o is not None or (m is not None and m.bot is not None)) else 'hasar', r['hasar'])
              * random.uniform(0.85, 1.0) * (1 + LB.bonus(b, LB.ROKET)))
    LB.harca(b, LB.ROKET, 1)

    def vur():
        t = time.time()
        if not n.alive:
            return
        if o is not None:
            if oyuncuya_saldirabilir(w, n, o, t):
                o.send(o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=t))
            return
        x = w.npcs.get(hedef)
        if x is None or not x.alive:
            return
        if x.bot is not None:
            bot_hasar(w, x, dmg, n.id, t, katil_bot=b)
        else:
            npc_vur(w, n, x, dmg, t, 0, ammo=rk)
    w.later(DN.SAVAS['roket_ucus_sn'], vur)


def npc_odulu(b, m, pay=1):
    """Uzaylının ödülü bota (paketin hızı, X-1 kesintisi), ek ganimeti ve görev ilerlemesi. pay: grupta paydaş sayısı (ödül
    bölünür, ganimet ve görev tam; dunya.npc_reward gibi)."""
    from . import ganimet as GB, etkinlik as ET
    GB.ek_ganimet(b, m.tip, 1)
    ET.dusme(b, b.harita, m.tip)                         # etkinlik düşmeleri (Candy Corn …)
    y_ = YN.AKTIF
    hiz = y_.hiz(b) if y_ is not None else 1.0
    o = m.d.get('odul', {})
    x1 = S.x1_kesinti(b) / pay                           # oyuncudaki gibi dört ödüle de
    b.odul('npc', hiz, ep=o.get('ep', 0) * x1, kredi=o.get('kredi', 0) * x1, uridyum=o.get('uridyum', 0) * x1,
           onur=o.get('onur', 0) * x1)
    b.ist('npc')
    b.ist('npc_puan', T.npc_rutbe_puani(m.tip))
    if y_ is not None:
        with y_.lock:
            y_.npc_oldurdu(b, m.tip, 1)


def grup_botlari(w):
    """Kahramanın grubundaki, bu haritada yaşayan botlar (uzaylı ödülünün paydaşları; grup.py)."""
    return [m.bot for m in list(w.npcs.values()) if m.bot is not None and m.alive and w.grup_uyesi(m.id)]


def kargo_birak(w, m, uid, x, y):
    """Uzaylının kargo kutusu (cevherleri) botun adına: yalnız bot gemisi haritadaysa (toplayacak biri var)."""
    t = w.npcs.get(uid)
    if t is None or t.bot is None or not t.bot.izin.get('kargo', True):
        return
    kargo = {str(k): v for k, v in K.npc_kargosu(m.tip, t.bot.seviye, w.map_id).items()}
    if not kargo:
        return
    mal = ('b', uid) if DN.AY.get('kargo_sahipligi') else None
    w.later(DN.SAVAS['kutu_gecikme_sn'], lambda: w.drop_box('FROM_SHIP', x, y, kargo, DN.SAVAS['kutu_omur_sn'], mal=mal))


def _bot(uid):
    y_ = YN.AKTIF
    return next((b for b in y_.botlar if b.uid == uid), None) if y_ is not None else None


def bot_firma(uid):
    b = _bot(uid)
    return b.firma if b is not None else None


def etiket_odulu(w, m, uid, x, y):
    """Botun etiketlediği uzaylıyı başkası bitirdi: ödül, görev ve kargo kutusu botun (dunya.World.etiket_paydaslari)."""
    b = _bot(uid)
    if b is None or not b.cevrimici:
        return
    npc_odulu(b, m)
    kargo_birak(w, m, uid, x, y)


def kutusu_calindi(mal, ad):
    """Oyuncu botun kargo kutusunu topladı: bot onu unutmaz (hafızasında hakaret gibi)."""
    if not mal or mal[0] != 'b':
        return
    b = _bot(mal[1])
    if b is not None and ad:
        b.hafiza.olay(ad, 'hakaret', b.saat(), kat=0.5)
        b.olay('kutu_calindi', ad=ad)


def oyuncuya_saldirabilir(w, n, o, now):
    if o.hero_dead or o.jumping or o.gizli(now) or not o.running:
        return False
    import yonetici_modu as YM
    from . import yonetici_uyari as YU
    if YM.mi(profil=o.p) or YM.izleyici(o.p) or YU.etkin(n.bot, 'pvp', now):
        return False                                     # yöneticiye saldırılmaz (wiki Administrator: "should not be shot at"); PvP uyarısı
    if now < o.invuln_until or o.invulnerable or o.hero_etki.invulnerable(now):
        return False
    hx, hy = o.hero_pos(now)
    nx, ny = n.mover.pos(now)
    if _barista(w, hx, hy) or _barista(w, nx, ny) or iliski(o, n.bot) in (1, 2):
        return False                                     # klanı müttefik ya da saldırmazlıkta
    return int(o.p.d['pilot'].get('factionId') or 0) != n.bot.firma or not (
        H.company(w.map_id) == n.bot.firma and H.name(w.map_id).split('-')[-1] in ('1', '2'))


def bota_saldirabilir(w, n, m, now):
    from . import yonetici_uyari as YU
    if not m.alive or m.bot.firma == n.bot.firma or YU.etkin(n.bot, 'pvp', now):
        return False
    if (n.bot.k.get('klan') and n.bot.k.get('klan') == m.bot.k.get('klan')) or T.klan_iliskisi(n.bot, m.bot) in (1, 2):
        return False
    nx, ny = n.mover.pos(now)
    mx, my = m.mover.pos(now)
    return not (_barista(w, nx, ny) or _barista(w, mx, my))


# ------------------------------------------------------------------------------------------------------------ uzaylının bota karşılığı
def npc_bota(w, m, now):
    """Bot vurduğu uzaylı bota döner (oyuncuyla savaşmıyorsa): kovalar ve ateş eder -> işlendi mi (think'in kalanı atlanır)."""
    t = w.npcs.get(m.bot_hedef)
    if m.engaged or t is None or not t.alive or t.bot is None:
        m.bot_hedef = None
        return False
    if now < m.next_think and now < m.next_shot:
        return True
    tx, ty = t.mover.pos(now)
    mx, my = m.mover.pos(now)
    dist = math.hypot(tx - mx, ty - my)
    if dist > 2500:
        m.bot_hedef = None
        return False
    if w.in_peace(tx, ty) and t.id not in m.attackers:
        # güvenli bölge: oyuncunun kuralı (dunya.npc_retaliating), yalnız botun vurduğu uzaylı peşinden girer; çağrılan yardımcılar
        # bölgeye dalıp ateş ediyordu
        m.bot_hedef = None
        w.alien_ceasefire(m)
        w.stop_npc_motion(m, now)
        return False
    if now >= m.next_think:
        m.next_think = now + 1.0
        if dist > m.keep + 60:
            a = math.atan2(my - ty, mx - tx) + m.spread
            gx, gy = tx + math.cos(a) * m.keep, ty + math.sin(a) * m.keep
            ms = m.mover.go(gx, gy, m.speed(), now)
            w.send([('MoveCommand', dict(userId=m.id, x=int(gx), y=int(gy), timeToTarget=ms))])
    if now >= m.next_shot and dist <= w.npc_range(m) and m.d['hasar'] > 0:
        m.next_shot = now + m.d.get('atis_aralik_sn', DN.SAVAS['npc_saldiri_aralik_sn'])
        _yayin(w, [('AttackLaserRunCommand', dict(attackerId=m.id, targetId=t.id, laserColor=0, isDiminishedBySkillShield=False,
                                                  skilledLaser=False, visualType=0))], m.id, t.id)
        if random.random() < m.d.get('isabet', DN.SAVAS['npc_isabet']):
            bot_hasar(w, t, int(m.d['hasar'] * random.uniform(0.8, 1.0)), m.id, now, npc=m)
    return True


# ------------------------------------------------------------------------------------------------------------ taktik
def dusun(w, n, now):
    """Botun dünya döngüsündeki aklı (think'in yerine; her adım çağrılır, kendi aralığıyla düşünür)."""
    if not n.alive:
        return
    b = n.bot
    ates(w, n, now)
    if now < n.next_think:
        return
    n.next_think = now + b.k['kisilik']['tepki_sn'] * random.uniform(0.6, 1.4)
    d = b.deger()
    if now - n.son_hasar > SAVAS_SN:                     # yenilenme
        from . import ekstra as EK
        k = YENILENME * b.k['kisilik']['tepki_sn'] * 1.0
        rep = EK.onarim_sn(b)
        n.shield = min(d['kalkan'], n.shield + d['kalkan'] * k * 2)
        n.hp = min(d['can'], n.hp + d['can'] * max(k, b.k['kisilik']['tepki_sn'] / rep if rep else 0))     # onarım robotu
    nx, ny = n.mover.pos(now)
    b.k['x'], b.k['y'] = int(nx), int(ny)
    if b.__dict__.get('cikis_istegi') and not any(now - t < 6 for t in n.saldiran.values()):
        return cikisa_git(w, n, now)                     # oturum bitti: istasyona ya da portala uçup orada çıkar
    if (n.hedef is None and not any(now - t < 6 for t in n.saldiran.values()) and not b.yolda
            and (b.hedef is None or b.hedef.ad != 'kapi') and kutu_topla(w, n, now)):
        return                                           # yolunun üstündeki kutuyu alır (her işte; dövüşte değilken)
    if b.hedef is not None and b.hedef.somut(b, n, w, now):
        return
    oran = (n.hp + n.shield) / max(1, d['can'] + d['kalkan'])
    saldiranlar = [u for u, t in n.saldiran.items() if now - t < 6]
    from . import aktif as AK
    if AK.savas(w, n, now, d, oran, saldiranlar):         # Insta-Shield, Backup Shields, Battle Repair, Smart Bomb, Energy Leech
        oran = (n.hp + n.shield) / max(1, d['can'] + d['kalkan'])
    # 1) tehlike: canı azaldı ve vuruluyor -> kaç
    kapida = kapi_dunyasi(w)
    if saldiranlar and oran < 0.18 + 0.32 * (1 - b.o('risk')) and not kapida:
        return kac(w, n, now)
    # 2) portal yolunda
    if b.yolda and not saldiranlar and not kapida:
        return portala(w, n, now)
    # 2b) hasarlı ve kimse vurmuyor: durup toparlanır
    if not saldiranlar and toparlan(w, n, now, d):
        return
    # 3) saldırıya karşılık ya da kaç
    if saldiranlar and (n.hedef is None or n.hedef not in saldiranlar):
        u = saldiranlar[-1]
        if u in w.npcs and w.npcs[u].bot is None:
            n.hedef = u                                  # uzaylı vurdu: karşılık
        else:
            karsi = _guc(w, u)
            if karsi / max(0.5, d['guc']) > 1.3 + b.o('risk') + 0.5 * b.ruh['ofke'] and oran < 0.9:
                return kac(w, n, now)
            n.hedef = u
            b.hafiza.olay(_ad(w, u), 'hakaret', now, kat=0.3)
    # 4) PvP fırsatı
    if n.hedef is None or n.hedef in w.npcs and w.npcs[n.hedef].bot is None:
        t = pvp_hedefi(w, n, now)
        if t is not None:
            n.hedef = t
    # 4b) eşlik: sana ya da arkadaşı olan bir bota katıldıysa onun hedefine ateş eder, yoksa yanında uçar
    if eslik(w, n, now):
        return
    # 5) hedefe yaklaş / hedefe göre davran
    if n.hedef is not None:
        pos = _konum(w, n.hedef, now)
        if pos is None:
            n.hedef = None
        else:
            return yaklas(w, n, pos, now)
    h = b.hedef.ad if b.hedef is not None else 'kasilma'
    if h == 'dinlenme':
        return dinlen(w, n, now)
    return avlan(w, n, now)


def _ad(w, uid):
    o = _oyuncu(w, uid)
    if o is not None:
        return o.p.d['pilot'].get('userName', '')
    m = w.npcs.get(uid)
    if m is not None:
        return m.bot.ad if m.bot is not None else m.d.get('ad', '')
    # haritada değil (ayrılmış ya da ölmüş bot, oyuncunun P.E.T.'i): önceden "" dönüyor, botlar adsız birinden "hakaret" biriktiriyordu
    b = _bot(uid)
    if b is not None:
        return b.ad
    if getattr(w, 'pet', None) is not None and w.pet.owned and w.pet.pid == uid:      # P.E.T.'i yoksa pid okunamaz (canlı test)
        return w.p.d['pilot'].get('userName', '')
    return ''


def _guc(w, uid):
    o = _oyuncu(w, uid)
    if o is not None:
        return kahraman_gucu(o)
    m = w.npcs.get(uid)
    return m.bot.deger()['guc'] if m is not None and m.bot is not None else 1.0


def yaklas(w, n, pos, now):
    """Hedefle savaş mesafesi: lazer menzilinin içinde, kişiliğe göre yakın ya da uzak; hedefin çevresinde hafif döner."""
    nx, ny = n.mover.pos(now)
    dist = math.hypot(pos[0] - nx, pos[1] - ny)
    istenen = 280 + 300 * (1 - n.bot.o('saldirganlik'))
    if dist > istenen + 120 or dist < 120:
        a = math.atan2(ny - pos[1], nx - pos[0]) + random.uniform(-0.5, 0.5)
        _git(w, n, pos[0] + math.cos(a) * istenen, pos[1] + math.sin(a) * istenen, now)
    elif n.mover.t1 <= now and random.random() < 0.25 + 0.4 * n.bot.o('saldirganlik'):
        # menzilde: hedefin çevresinde döner (gerçek oyuncu dururken değil, dönerek ateş eder); yön botun huyuna göre sabit
        yon = n.__dict__.setdefault('yorunge_yon', random.choice((-1, 1)))
        a = math.atan2(ny - pos[1], nx - pos[0]) + yon * random.uniform(0.25, 0.6)
        _git(w, n, pos[0] + math.cos(a) * istenen, pos[1] + math.sin(a) * istenen, now, esik=40)


def pvp_hedefi(w, n, now):
    """Görüşteki düşman oyuncu ya da bot: saldırmaya değer mi (kişilik, güç oranı, kin, PvP hedefi)."""
    b = n.bot
    y = YN.AKTIF
    if y is None or now - n.niyet_t < 4:
        return None
    n.niyet_t = now
    nx, ny = n.mover.pos(now)
    gor = DN.SAVAS['gorus_mesafesi']
    adaylar = []
    if y.izin('oyuncuya_saldir') and y.izin('pvp'):
        for o in ([w] + [x for x in (w.ortak.uyeler if w.ortak else []) if x is not w]):
            if not o.running or int(o.p.d['pilot'].get('factionId') or 0) == b.firma:
                continue
            hx, hy = o.hero_pos(now)
            if math.hypot(hx - nx, hy - ny) > gor or not oyuncuya_saldirabilir(w, n, o, now):
                continue
            adaylar.append((o.hid, kahraman_gucu(o), o.p.d['pilot'].get('userName', ''), iliski(o, b)))
    if y.izin('pvp'):
        for m in w.npcs.values():
            if m.bot is None or m is n or not m.alive:
                continue
            mx, my = m.mover.pos(now)
            if math.hypot(mx - nx, my - ny) > gor or not bota_saldirabilir(w, n, m, now):
                continue
            adaylar.append((m.id, m.bot.deger()['guc'], m.bot.ad, T.klan_iliskisi(b, m.bot)))
    if not adaylar:
        return None
    benim = max(0.5, b.deger()['guc'])
    av = b.hedef is not None and b.hedef.ad in ('pvp', 'yardim', 'duello')
    rakip = str(b.plan.get('ad', '')).lower() if b.hedef is not None and b.hedef.ad == 'duello' else ''
    en, ep = None, 0.0
    for uid, guc, ad, rel in adaylar:
        oran = guc / benim
        kin = -min(0.0, b.hafiza.iliski(ad, now)) + (0.6 if rel == 3 else 0.0)     # klan savaşı: düşman klanın üyesi
        if rakip and str(ad).lower() == rakip:
            return uid                                   # düello: meydan okuyana hemen saldırır
        p = (0.04 + 0.5 * b.o('saldirganlik') * b.o('rekabet')) * (2.2 if av else 1.0)
        p *= max(0.0, 1.6 - oran) * (0.5 + b.ruh['ozguven']) + kin * 0.8
        if oran > 1.2 + b.o('risk') + kin:
            p *= 0.1
        if p > ep:
            en, ep = uid, p
    # saniyede değil karar başına (4 sn'de bir) olasılık: hemen değil, bir süre sonra saldırır gibi
    return en if random.random() < min(0.9, ep * 0.5) else None


def kac(w, n, now):
    """Kaç: en yakın portala (ya da kendi üssündeyse istasyona); varınca atlayıp haritadan çıkar. Oyuncudan kaçarken arkasına
    mayın bırakır (stokta varsa, beklemesi dolduysa; güvenli bölgede ve başlangıç haritalarında değil)."""
    b = n.bot
    n.hedef = None
    nx, ny = n.mover.pos(now)
    if any(_oyuncu(w, u) is not None for u, t in n.saldiran.items() if now - t < 6):
        from . import aktif as AK
        AK.emp(w, n, now)                                # kilitlenen oyuncunun seçimi düşer
        if b.o('risk') < 0.6:
            AK.gizlen(w, n, now)                         # gizlenme CPU'su
        mayin_birak(w, n, nx, ny, now)
    gs = [g for g in H.gates(w.map_id, b.firma) if not g.get('ucret') and g['hedef'] in K.HARITALAR
          and K.girebilir(g['hedef'], b.firma, b.seviye)]
    s = w.station
    if s and s.get('type') == b.firma:
        sx, sy = s['posX'], s['posY']
        if not gs or math.hypot(sx - nx, sy - ny) < min(math.hypot(g['x'] - nx, g['y'] - ny) for g in gs):
            _git(w, n, sx, sy, now)
            return
    if not gs:
        return
    g = min(gs, key=lambda g: math.hypot(g['x'] - nx, g['y'] - ny))
    y = YN.AKTIF
    if y is not None and y.kip == 'basit':
        _git(w, n, g['x'] + random.uniform(-200, 200), g['y'] + random.uniform(-200, 200), now)    # basit: portalın güvenli bölgesine
        return
    if not b.yolda or b.yolda[0] != g['hedef']:
        b.yolda = [g['hedef']]
        b.olay('kacti', harita=H.name(w.map_id))
    portala(w, n, now, acil=True)


def mayin_birak(w, n, x, y, now):
    """Botun mayını (oyuncunun gemisine yaklaşınca patlar: savas_esya.alien_mine) -> bırakıldı mı."""
    from . import silah as SL
    b = n.bot
    m = SL.mayin_sec(b)
    if m is None or now < getattr(n, 'mayin_hazir', 0) or w.items.start_map() or w.in_pvp_peace(x, y):
        return False
    if not SL.harca(b, m, 1):
        return False
    n.mayin_hazir = now + SL.MAYIN_BEKLEME
    w.items.alien_mine(m, x, y, n.id, now)
    b.ist('mayin')
    return True


def portala(w, n, now, acil=False):
    """Yolun sıradaki haritasının portalına uç; varınca ATLAMA_SN sonra haritadan çık (yönetici botu yeni haritaya geçirir)."""
    b = n.bot
    if not b.yolda:
        return
    if len(b.yolda) > 2 and not acil:                     # atlama CPU'su: uzun yolu tek atlamada üsse
        from . import ekstra as EK
        cpu = EK.atlama(b, b.yolda[-1])
        y = YN.AKTIF
        if cpu and y is not None and EK.kullan(b, cpu):
            hedef = b.yolda[-1]
            w.send(kaldir(w, n))
            with y.lock:
                S.atla(b, hedef, y)
                b.yolda = None
                b.gelis = (int(w.map_id), time.time())
                b.ist('atlama_cpu')
            return
    g = next((g for g in H.gates(w.map_id, b.firma) if g['hedef'] == b.yolda[0]), None)
    if g is None:
        b.yolda = None
        return
    nx, ny = n.mover.pos(now)
    if not acil and now < n.dogus + n.kalkis:             # yeni geldi: biraz oyalanır, sonra kendi vaktinde yola çıkar
        if n.hareket is None:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(100, 350)
            _git(w, n, nx + math.cos(a) * r, ny + math.sin(a) * r, now)
        return
    p = n.yanas.get(g['hedef'])
    if p is None:                                         # portalın çevresinde kendi yanaşma noktası (hep aynı noktaya değil)
        a, r = random.uniform(0, 2 * math.pi), random.uniform(30, 140)
        p = n.yanas[g['hedef']] = (g['x'] + math.cos(a) * r, g['y'] + math.sin(a) * r)
    if math.hypot(g['x'] - nx, g['y'] - ny) > 180:
        n.portal_t = 0.0
        if acil:
            _git(w, n, p[0], p[1], now)                   # kaçarken dosdoğru
        else:
            _rota(w, n, p[0], p[1], now)
        return
    if not n.portal_t:
        n.portal_t = now + ATLAMA_SN * (0.8 if acil else random.uniform(1.0, 2.5))
        n.hedef = None
        return
    if now < n.portal_t:
        return
    y = YN.AKTIF
    hedef = b.yolda.pop(0)
    w.send(kaldir(w, n))
    if y is not None:
        with y.lock:
            S.atla(b, hedef, y)
            b.gelis = (int(w.map_id), time.time())
            b.yolda_t = time.time() + S.atlama_suresi(b)


def kesebilir(b, m):
    """Haritanın sabit listesinde olmayan uzaylı (etkinlik, Urgent Missions hedefi, Hitac taşıyıcısı …): gücü yetiyorsa (türe göre
    önbellekli; gerçek oyuncu gördüğü ve kesebildiği her şeye ateş eder)."""
    c = b.__dict__.setdefault('_kesebilir', {})
    v = c.get(m.tip)
    if v is None or v[1] != b.deger()['guc']:
        d = b.deger()
        ehp = m.d.get('hp', 0) + m.d.get('kalkan', 0)
        gelen = m.d.get('hasar', 0) * K.SAVAS['npc_isabet'] / K.NPC_ARALIK
        sure = ehp / max(1.0, d['dps'])
        v = c[m.tip] = (sure < 180 and sure * gelen < d['ehp'] * (0.4 + 0.5 * b.o('risk')), d['guc'])
    return v[0]


def _oldurulebilir(b, m_id):
    from . import etkinlik as ET
    d = b.deger()
    cesaret = max(0.0, min(1.0, 0.3 + 0.6 * b.o('risk') + 0.2 * b.ruh['ozguven'] - 0.3))
    out = set(K.harita_degerlendir(int(m_id), d['dps'], d['ehp'], cesaret)['hedefler'])
    return out | ET.etkinlik_turleri(b, int(m_id)) if b.izin.get('etkinlik', True) else out      # etkinlik uzaylıları da


def avlan(w, n, now):
    """Uzaylı avı: öldürmeye cesaret ettiği türlerden en yakını (görevin istediği önce); oyuncunun savaştığını kapmaz (kaba botlar
    ara sıra kapar). Yakında bonus kutusu varsa önce onu alır. Hedef yoksa amaçlı devriye: uzak bir ara noktaya uçar, yalnız varınca
    yenisini seçer (önceden her saniye kısa rastgele sıçramalar sağa sola kıpırdanma gibi görünüyordu)."""
    b = n.bot
    nx, ny = n.mover.pos(now)
    if kutu_topla(w, n, now):
        return
    tipler = _oldurulebilir(b, w.map_id)
    istenen = b.plan.get('tip')
    kaba = random.random() < 0.15 * b.o('saldirganlik') * (1 - b.o('yardimseverlik'))
    en, ed = None, 1e18
    for m in w.npcs.values():
        if m.bot is not None or not m.alive or m.d.get('dost') or getattr(m, 'gizli', False):
            continue                                     # gizli komandoyu (Infiltration) göremez
        if m.tip not in tipler and not kesebilir(b, m):
            continue
        if (m.engaged or w.target == m.id) and not kaba:
            continue
        if m.bot_hedef not in (None, n.id) and w.npcs.get(m.bot_hedef) is not None:
            continue                                     # başka bot onunla savaşıyor
        if DN.etiket_sahibi(m, now) not in (None, ('b', n.id)):
            continue                                     # başkasının etiketlisi: kazancı olmaz
        mx, my = m.mover.pos(now)
        dd = math.hypot(mx - nx, my - ny) * (0.5 if m.tip == istenen else 1.0)
        if dd < ed:
            en, ed = m, dd
    if en is not None and ed < 3500:
        n.hedef = en.id
        n.devriye = None
        return yaklas(w, n, en.mover.pos(now), now)
    eslik_basla(w, n, now)
    if _lider(w, n, now) is not None:
        return                                           # eşliğe başladı: bir sonraki düşüncede liderin yanına
    dv = getattr(n, 'devriye', None)
    if dv is None or math.hypot(dv[0] - nx, dv[1] - ny) < 300:
        if dv is not None and random.random() < 0.4:
            n.next_think = now + random.uniform(2, 6)    # vardı: biraz bakınır
            n.devriye = None
            return
        a = random.uniform(0, 2 * math.pi)
        r = random.uniform(2500, 6000)
        dv = n.devriye = (max(600, min(w.map_w - 600, nx + math.cos(a) * r)), max(600, min(w.map_h - 600, ny + math.sin(a) * r)))
    _rota(w, n, dv[0], dv[1], now, esik=400)


def cikisa_git(w, n, now):
    """Oturumu biten bot: kendi istasyonu bu haritadaysa ona, değilse en yakın portala uçar; varınca yönetici çıkışını yapar."""
    b = n.bot
    n.hedef = None
    nx, ny = n.mover.pos(now)
    s = w.station
    if s and s.get('type') == b.firma:
        hx, hy = s['posX'], s['posY']
    else:
        g = min(H.gates(w.map_id, b.firma) or [{'x': nx, 'y': ny}], key=lambda g: math.hypot(g['x'] - nx, g['y'] - ny))
        hx, hy = g['x'], g['y']
    if math.hypot(hx - nx, hy - ny) > 250:
        p = n.yanas.get('cikis')
        if p is None or math.hypot(p[0] - hx, p[1] - hy) > 200:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(20, 140)
            p = n.yanas['cikis'] = (hx + math.cos(a) * r, hy + math.sin(a) * r)
        _rota(w, n, p[0], p[1], now)
    else:
        b.cikis_hazir = True


ESLIK_MENZIL = 1600


def yardimci(w, n, m, now):
    """Bot oyuncunun hedefine yardım mı ediyor (eşlik eden ya da onunla gruptaki bot, oyuncunun seçtiği uzaylı): etiket, ödül
    ve kutu oyuncunun (eşlikçi bot önce ateş edip kutuyu alıyordu: kullanıcı bildirimi 2026-10-30)."""
    if m.id != w.target:
        return False
    l = _lider(w, n, now)
    if l is not None and l[0] == 'h':
        return True
    import grup as GR
    g = GR.grubu(n.bot.uid)
    return g is not None and w.hid in g.uyeler


def _lider(w, n, now):
    """Eşlik edilen: ('h', None) kahraman ya da ('b', gemi); gitti, öldü ya da uzaklaştıysa None."""
    e = n.__dict__.get('eslik')
    if not e or now > e[1]:
        return None
    if e[0] == 'h':
        if w.hero_dead or w.jumping:
            return None
        return ('h', None)
    m = w.npcs.get(e[0])
    return ('b', m) if m is not None and m.alive and m.bot is not None else None


def eslik_basla(w, n, now):
    """İşi yokken (avlanırken hedefsiz) arada: aynı firmadan sana (yakındaysan) ya da arkadaşı olan bir bota katılır.
    Olasılık sosyallik, sana karşı ilişki ve yardımseverlikle; süre 1-3 dakika."""
    b = n.bot
    if n.__dict__.get('eslik') and now <= n.eslik[1]:
        return
    if now < n.__dict__.get('eslik_bak', 0):
        return
    n.eslik_bak = now + random.uniform(20, 40)
    nx, ny = n.mover.pos(now)
    sure = random.uniform(60, 180)
    ad = str(w.p.d['pilot'].get('userName', ''))
    if (w.p.d['pilot'].get('factionId') == b.firma and not w.hero_dead and not w.jumping
            and math.hypot(*(a - c for a, c in zip(w.hero_pos(now), (nx, ny)))) < ESLIK_MENZIL):
        p = 0.08 * (0.3 + b.o('sosyallik')) * (0.5 + b.o('yardimseverlik')) * (1 + 3 * max(0.0, b.hafiza.iliski(ad, now)))
        if random.random() < p:
            n.eslik = ('h', now + sure, random.uniform(0, 2 * math.pi))
            b.hafiza.olay(ad, 'birlikte_avlandik', now)
            return
    dostlar = set(b.hafiza.dostlar(0.25, now))
    for m in w.npcs.values():
        if m is n or m.bot is None or not m.alive or m.bot.firma != b.firma or m.bot.ad not in dostlar:
            continue
        if math.hypot(*(a - c for a, c in zip(m.mover.pos(now), (nx, ny)))) < ESLIK_MENZIL and random.random() < 0.3:
            n.eslik = (m.id, now + sure, random.uniform(0, 2 * math.pi))
            return


def eslik(w, n, now):
    """Eşlik: liderin hedefi (senin seçtiğin uzaylı ya da arkadaş botun hedefi) gücü yetiyorsa onunki; hedef yoksa liderin
    yanında, kendi yerinde (formasyon) uçar -> bu düşüncede iş yaptı mı."""
    lider = _lider(w, n, now)
    if lider is None:
        n.__dict__.pop('eslik', None)
        return False
    if n.hedef is None:
        t = w.target if lider[0] == 'h' else lider[1].hedef
        m = w.npcs.get(t) if t is not None else None
        if m is not None and m.alive and m.bot is None and not m.d.get('dost') and kesebilir(n.bot, m):
            n.hedef = m.id
            return False                                 # hedefe yaklaşmayı olağan akış yapar
    if n.hedef is not None:
        return False
    lx, ly = w.hero_pos(now) if lider[0] == 'h' else lider[1].mover.pos(now)
    a = n.eslik[2]
    hx, hy = lx + math.cos(a) * 280, ly + math.sin(a) * 280
    nx, ny = n.mover.pos(now)
    if math.hypot(hx - nx, hy - ny) > 200:
        _git(w, n, hx, hy, now, esik=120)
    return True


def patron_mu(m):
    ad = str(m.d.get('ad', ''))
    return m.bot is None and ('Boss' in ad or 'Uber' in ad or bool(m.d.get('patron')))


def tanik(w, tur, x, y, haric=None, **f):
    """Haritada görülen olay (patron öldü, oyuncu öldü): 1.500 birimdeki botlardan en çok ikisi, konuşkanlığına göre, sohbette
    tepki verir (olay 'tanik'; kalıplar konusma.py, Gelişmiş kipte dil modeli)."""
    adet = 0
    for m in list(w.npcs.values()):
        if m.bot is None or not m.alive or m.id == haric or adet >= 2:
            continue
        mx, my = m.mover.pos(time.time())
        if math.hypot(mx - x, my - y) > 1500 or random.random() > 0.35 * m.bot.o('konuskanlik'):
            continue
        m.bot.olay('tanik', alt=tur, **f)
        adet += 1


def kutu_topla(w, n, now):
    """Yakındaki kutuya uçar ve alır (gerçek oyuncular gibi; kutu oyuncunun ekranından da kalkar) -> bununla meşgul mü.
    Bonus kutusu (yerine yenisi doğar), kendi kargo kutusu (cevherler kargosuna) ve kaba botlar ara sıra başkasınınkini (izin
    'kutu_calma'; aynı firmadansa onur kaybeder, oyuncu gibi). Grupta yalnız birine düşen ganimete (sahip) dokunmaz."""
    if n.hedef is not None and n.hedef in w.npcs:
        return False
    b = n.bot
    nx, ny = n.mover.pos(now)
    kendi = ('b', n.id)
    karar = n.__dict__.setdefault('calma', {})
    en, ed = None, 900.0
    for h, k in w.boxes.items():
        tip = k.get('tip')
        if k.get('etk'):                                 # etkinlik kutusu: anahtarsız, herkes toplar
            if not b.izin.get('etkinlik', True) or k.get('sahip') is not None:
                continue
        elif k.get('anahtarli'):                          # anahtarlı ganimet kutusu: anahtarı varsa ya da yeşil anahtarı alırsa
            from . import ganimet as GB
            k_ = karar.get(h)
            if k_ is None or (k_ is not True and now > k_):         # "açamam" kararı 60 sn'de bir yeniden (anahtar gelmiş olabilir)
                karar[h] = True if tip in GB.GN.BOXES and GB.acar_mi(b, tip) else now + 60
            if karar[h] is not True:
                continue
        elif k.get('sahip') is not None or (tip != 'BONUS_BOX' and tip not in DN.CARGO_BOXES):
            continue
        if tip in DN.CARGO_BOXES and (not b.izin.get('kargo', True) or b.kargo_dolu() >= 1):
            continue                                   # kargo kapalı ya da dolu
        mal = k.get('mal')
        if tip in DN.CARGO_BOXES and mal is not None and tuple(mal) != kendi and DN.AY.get('kargo_sahipligi'):
            if h not in karar:                         # başkasının kargosu: kaba bot ara sıra alır (kutu başına bir karar)
                karar[h] = calar_mi(w, b, mal)
            if not karar[h]:
                continue
        dd = math.hypot(k['x'] - nx, k['y'] - ny)
        if dd < ed:
            en, ed = h, dd
    if en is None:
        return False
    k = w.boxes[en]
    if ed > 60:
        _git(w, n, k['x'], k['y'], now, esik=40)
        return True
    if k.get('etk'):
        from . import etkinlik as ET
        del w.boxes[en]
        w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
        karar.pop(en, None)
        if k['etk'].get('yeniden_sn'):
            w.schedule(random.uniform(*k['etk']['yeniden_sn']) * DN.AY.carpan('kutu_yenilenme'), 'etk_kutu', k['tip'])
        ET.kutu_ac(b, k['etk'])
        n.next_think = now + random.uniform(0.3, 1.0)
        return True
    if k.get('anahtarli'):                               # açılış ganimet.ACMA_SN sürer (oyuncudaki gibi), sonra kutu alınır
        from . import ganimet as GB
        acilis = getattr(n, 'acilis', None)
        if not acilis or acilis[0] != en:
            n.acilis = (en, now + GB.GN.ACMA_SN)
            return True
        if now < acilis[1]:
            return True
        n.acilis = None
        del w.boxes[en]
        w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
        karar.pop(en, None)
        w.schedule(GB.GN.respawn_delay(k['tip']) * DN.AY.carpan('kutu_yenilenme'), 'booty', k['tip'])
        GB.ac(b, k['tip'])
        n.next_think = now + random.uniform(0.3, 1.0)
        return True
    if k['tip'] in DN.CARGO_BOXES:                     # cevherler sığdığı kadar; sığmayan kutuda kalır (oyuncudaki gibi)
        alinan = b.kargo_ekle(k.get('icerik') or {})
        kalan = {t: int(v) - alinan.get(int(t), 0) for t, v in (k.get('icerik') or {}).items() if int(v) - alinan.get(int(t), 0) > 0}
        b.ist('kargo_kutusu')
        mal = k.get('mal')
        if mal is not None and tuple(mal) != kendi and not k.get('calindi') and DN.AY.get('kargo_sahipligi'):
            k['calindi'] = True
            calma_cezasi(w, b, mal)
        if kalan:
            k['icerik'] = kalan
            n.next_think = now + random.uniform(0.3, 1.0)
            return True
    del w.boxes[en]
    w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
    karar.pop(en, None)
    if k['tip'] == 'BONUS_BOX':
        w.schedule(random.uniform(30, 60), 'bonus')
        b.odul('kutu', ep=random.randint(0, 100), kredi=random.choice((0, 0, 100, 500, 1000)), uridyum=random.choice((0, 0, 10, 20, 50, 100)))
        b.ist('kutu')
    n.next_think = now + random.uniform(0.3, 1.0)
    return True


def _kutu_firmasi(w, mal):
    return w.p.d['pilot'].get('factionId') if mal[0] == 'h' and mal[1] == w.hid else bot_firma(mal[1]) if mal[0] == 'b' else None


def _calma_bugun(b):
    """Botun bugünkü kargo alma sayacı {gun, n} (o günün ilk cezası 10, her seferinde iki katı)."""
    d = b.k.setdefault('kargo_calma', {})
    gun = time.strftime('%Y-%m-%d', time.localtime(b.saat()))
    if d.get('gun') != gun:
        d.update(gun=gun, n=0)
    return d


def calar_mi(w, b, mal):
    """Başkasının kargo kutusunu alır mı. Düşman firmanınki cezasız: kaba bot ara sıra alır. Kendi firmasınınki onur kaybettirir
    (o gün 10, her seferinde iki katı): gerçek oyuncu bunu bilir, nadiren ve günde en çok bir kez el uzatır. Önceden bot her kutu
    için zar atıyordu; kalabalık haritada günde onlarca kutu alıp onurunu yüzbinlerce eksiye düşürüyordu (kullanıcı 2026-10-30)."""
    from . import yonetici_uyari as YU
    if not b.izin.get('kutu_calma', True) or YU.etkin(b, 'kutu'):
        return False                                     # yöneticinin kutu uyarısı (bot/yonetici_uyari.py)
    p = 0.35 * b.o('saldirganlik') * (1 - b.o('yardimseverlik'))
    if _kutu_firmasi(w, mal) == b.firma:
        if _calma_bugun(b)['n'] >= 1:
            return False                               # bugün bir kez ceza yedi: bir daha almaz
        p *= 0.15
    return random.random() < p


def calma_cezasi(w, b, mal):
    """Bot başkasının kargo kutusunu aldı: sahibi aynı firmadansa onur kaybı (oyuncuyla aynı kural: o gün 10, her seferinde x2);
    sahibi oyuncuysa bot onun gözünde kötüleşmez ama oyuncu kutusunu kaybeder."""
    fac = _kutu_firmasi(w, mal)
    b.ist('kutu_caldi')
    if fac != b.firma:
        return
    d = _calma_bugun(b)
    b.kazan(onur=-10 * 2 ** min(d['n'], 16))
    d['n'] += 1
    if mal[0] == 'b':
        o = _bot(mal[1])
        if o is not None:
            o.hafiza.olay(b.ad, 'hakaret', b.saat(), kat=0.5)


def toparlan(w, n, now, d):
    """Hasarlı ama kimse vurmuyor: avı bırakıp durur, kalkan ve onarım robotu dolana dek bekler (kendi üssüne yakınsa istasyona
    çekilir) -> bekliyor mu. Gerçek oyuncu yarım canla yeni uzaylıya dalmaz."""
    oran = (n.hp + n.shield) / max(1, d['can'] + d['kalkan'])
    b = n.bot
    if getattr(n, 'toparlaniyor', False):
        if oran >= 0.9:
            n.toparlaniyor = False
            return False
    elif oran >= 0.3 + 0.3 * (1 - b.o('risk')):
        return False
    n.toparlaniyor = True
    n.hedef = None
    s = w.station
    nx, ny = n.mover.pos(now)
    if s and s.get('type') == b.firma and math.hypot(s['posX'] - nx, s['posY'] - ny) < 4000:
        return dinlen(w, n, now)
    _dur(w, n, now)
    n.next_think = now + random.uniform(2, 4)
    return True


def park_yeri(w, n, now):
    """Dinlenecek yer, botlar arasında çeşitli (kullanıcı isteği: hepsi istasyonun aynı yerinde durmasın): kendi istasyonunun
    çevresinde geniş bir halka, bir portalın güvenli bölgesi ya da olduğu yer (haritanın ortasında "afk"). Öteki botların park
    yerlerine 300 birimden yakın olmaz."""
    b = n.bot
    s = w.station
    nx, ny = n.mover.pos(now)
    dolu = [getattr(m, 'park', None) for m in w.npcs.values() if m.bot is not None and m is not n]
    dolu = [p for p in dolu if p is not None]
    portallar = [g for g in H.gates(w.map_id, b.firma) if not g.get('ucret') and math.hypot(g['x'] - nx, g['y'] - ny) < 6000]
    for _ in range(12):
        k = random.random()
        if s and s.get('type') == b.firma and k < 0.5:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(350, 1700)
            p = (s['posX'] + math.cos(a) * r, s['posY'] + math.sin(a) * r)
        elif portallar and k < 0.75:
            g = random.choice(portallar)
            a, r = random.uniform(0, 2 * math.pi), random.uniform(150, 650)
            p = (g['x'] + math.cos(a) * r, g['y'] + math.sin(a) * r)
        else:
            p = (nx + random.uniform(-200, 200), ny + random.uniform(-200, 200))
        p = (max(400, min(w.map_w - 400, p[0])), max(400, min(w.map_h - 400, p[1])))
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 300 for q in dolu):
            return p
    return p


def dinlen(w, n, now):
    """Dinlenme: kendi istasyonunun çevresinde bir yere park eder ve orada durur ("afk", sohbet, alışveriş); arada uzun aralıklarla
    yer değiştirir. Park yeri bir kez seçilir (önceden her saniye yeni rastgele nokta seçip istasyon çevresinde zikzak çiziyordu)."""
    b = n.bot
    s = w.station
    nx, ny = n.mover.pos(now)
    park = getattr(n, 'park', None)
    if park is None or now > getattr(n, 'park_bitis', 0):
        park = park_yeri(w, n, now)
        n.park, n.park_bitis = park, now + random.uniform(90, 400)
    if math.hypot(park[0] - nx, park[1] - ny) > 60:
        _git(w, n, park[0], park[1], now, esik=100)
    else:
        n.next_think = now + random.uniform(3, 8)        # duruyor
