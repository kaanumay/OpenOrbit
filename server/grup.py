"""Grup (arkadaş sunucusu; istemcinin GroupComponentSystem / UIGroupSystem'i): davet, kabul ve ret, davetin geri alınması, ayrılma,
atma, liderlik, davet kipi, ping, takip ve üyelerin grup penceresindeki durumu.

Davet ada göre (InvitationCreationRequest: grup penceresi, sohbetin oyuncu menüsü) ya da kimliğe göre (GroupInvitationRequest: rehber).
Gerçek sunucudaki gibi:
  - InvitationInitializationCommand davet edene, adaya ve davet edenin grubundakilere gider (istemci üçüncü kişide "%inviter%
    invited %candidate%." yazar). Davet DAVET_SN sonra düşer (InvitationRemovalCommand TIMEOUT), ret REJECT, geri alma REVOKE,
    kabul ACKNOWLEDGE.
  - Kabulde grup yoksa kurulur (lider davet eden): yeni üyeye ve kurulan grubun liderine GroupInitializationCommand (üyeler kendisi
    dahil; istemci üyeyi kahramanın kimliğiyle karşılaştırır), eski üyelere GroupMemberInitializationCommand.
  - Ayrılma ve atma herkese MemberLeaveCommand (ayrılana da: istemci grubun sohbet odasını kapatır); liderin yerine sıradaki geçer
    (LeaderChangeCommand); iki kişiden az kalınca grup dağılır (GroupCloseCommand).
  - Ping (PingPositionRequest, PingMemberRequest) aynı haritadaki üyelere PingCommand; takip (FollowRequest) üyenin konumuna
    HeroMoveCommand (istemci kahramanı oraya uçurur). Başka haritadaysa GroupErrorCommand.
Üyelerin durumu (can, konum, hedef, savaşta mı, gizli mi, çevrimiçi mi, seviye, gemi) GUNCELLEME_SN'de bir karşılaştırılır, değişen
GroupMemberUpdateCommand ile gider. Misafir bağlantısı kopunca üye "çevrimdışı" kalır (kaydı sunucuda durdukça; aynı anahtarla dönünce
kimliği aynı); kaydı bitince gruptan düşer. Grup bellekte: sunucu kapanınca dağılır.
Aynı ortak haritadaki üyeler (ortak_harita.py; kapı ve mod haritaları herkesin kendi kopyası, oralarda paylaşım yok):
  - Birbirini haritanın her yerinde görür (Harita.gorunurluk: görüş mesafesi grup üyesine uygulanmaz; ölü, atlamadaki, gizli yine görünmez).
  - Bir üyenin öldürdüğü uzaylının ödülü paylaşılır (dunya.World.paydaslar, npc_reward; wiki "Uridium, Cr, XP and honor of kills
    shared"): ödülü öldürenle birlikte haritada yaşayan, atlamada olmayan üyeler alır (uzaklık önemsiz; asıl oyunun ~20 sn ateş
    şartı yok). Her paydaşın ödülü kendi çarpanlarıyla hesaplanır, EP, onur, kredi ve uridyum paydaş sayısına bölünür (yukarı
    yuvarlanır). Ganimet herkese tam ve kendi şansıyla: kargo kutusu ve patron sandıkları her üyeye ayrı düşer, kutu sahibinindir
    (öteki oyuncular görmez, P.E.T.'leri de toplamaz), ek ödüller (Palladium …), booster ve harita etkinliğinin düşmeleri de.
  - Görevler: üyelerin öldürdüğü uzaylı herkesin görevine sayılır (wiki "All aliens killed by group members count towards our
    mission"): ana, günlük ve haftalık görevler, Season/Battle Pass, etkinlik görevleri ve Urgent Missions. Başkasının öldürmesi
    "şunu öldürme" kısıtını bozmaz; başarımlar, rütbe, seri öldürme, dron EP'si ve etkinlik kancaları (unvan, Hitac …) öldürenindir.
"""
import json, os, threading, time
import topluluk as TP
import harita as H
from cbs import stm

EN_COK = 8                    # grubun en çok üyesi (gerçek oyun)
DAVET_SN = 120                # yanıtlanmayan davetin ömrü
DAVET_EN_COK = 10             # bir oyuncunun bekleyen davetleri (gönderdiği ya da aldığı)
GUNCELLEME_SN = 1.0
SAVAS_SN = 10.0               # son atış ya da alınan hasardan sonra "savaşta" sayılma süresi
PING_SN = 1.0                 # iki ping arası en az
KONUM_ESIK = 50               # bu kadar yer değiştirmeyen üyenin konumu yeniden gönderilmez
# InvitationErrorCommand.error
GROUP_FULL, CANDIDATE_IN_GROUP, CANDIDATE_NONEXISTENT, INVITER_NONEXISTENT, NO_INVITATION, BOSS_ONLY, MAX_INVITER, \
    MAX_CANDIDATE, CANDIDATE_BLOCKING, DUPLICATE_INVITATION = range(10)
# InvitationRemovalCommand.reason
TIMEOUT, REVOKE, REJECT, ACKNOWLEDGE = 1, 2, 3, 4
# GroupErrorCommand.type
PING_FAILED, NO_GROUP, FOLLOW_FAILED = 0, 1, 2
MOD_LIDER, MOD_HERKES = 0, 1  # InvitationModeModule.mode: davet yalnız liderden / herkesten
AYRILDI, ATILDI = 1, 2        # MemberLeaveCommand.reason

REQUESTS = {'InvitationCreationRequest', 'GroupInvitationRequest', 'InvitationAcceptRequest', 'InvitationRejectRequest',
            'InvitationCancelRequest', 'LeaveGroupRequest', 'KickMemberRequest', 'ChangeLeaderRequest', 'InvitationModeRequest',
            'PingPositionRequest', 'PingMemberRequest', 'FollowRequest'}

LOCK = threading.RLock()
GRUPLAR = {}                  # grup kimliği -> Grup
UYE = {}                      # oyuncu kimliği -> grup kimliği
DAVETLER = {}                 # (davet eden, aday) -> son geçerlilik anı
_sira = [0]
_simge = None
_is = None


def mod(_cls, **f):
    return dict(_=_cls, **f)


class Grup:
    def __init__(self, lider):
        _sira[0] += 1
        self.id, self.lider, self.uyeler, self.mod = _sira[0], lider, [lider], MOD_LIDER
        self.durum = {}       # üye -> son gönderilen durum (guncelle)
        self.ping = {}        # üye -> son ping anı


def oda(gid):
    """Grubun sohbet odası (sosyal.rooms; sohbet.py)."""
    return ('group', 'group', 'grup_%d' % gid)


def grubu(uid):
    with LOCK:
        g = GRUPLAR.get(UYE.get(uid))
        return g


# ------------------------------------------------------------ mesajlar
def simge(loot):
    """Geminin lootId'si (ship_goliath, ship_g-champion, ship_a-elite) -> ShipIcon değeri (bilinmeyen: DEFAULT)."""
    global _simge
    if _simge is None:
        _simge = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'gemi_simgeleri.json'),
                                encoding='utf8'))['simgeler']
    ad = str(loot or '')[5:] if str(loot or '').startswith('ship_') else str(loot or '')
    on, _, son = ad.partition('-')
    temel = {'a': 'AEGIS', 'c': 'CITADEL', 's': 'SPEARHEAD', 'n': 'NOSTROMO', 'g': 'GOLIATH', 'v': 'VENGEANCE', 'bb': 'BIGBOY',
             'd': 'DEFCOM', 'y': 'YAMATO'}.get(on)
    # tasarım gemileri: g-champion -> GOLIATH, a-elite -> AEGIS_ELITE, n-envoy -> NOSTROMO_ENVOY, v-adept -> ADEPT
    adaylar = [ad.replace('-', '_').upper()] + ([temel + '_' + son.replace('-', '_').upper()] if temel and son else []) \
        + ([son.replace('-', '_').upper()] if on in ('g', 'v', 'bb') and son else []) + ([temel] if temel else [])
    return next((_simge[a] for a in adaylar if a in _simge), _simge['DEFAULT'])


def npc_simge(ad):
    """Uzaylının görünen adı -> ShipIcon değeri (basarim.ship_icons adayları; bulunamazsa DEFAULT)."""
    from basarim import ship_icons
    simge('')
    return next((_simge[a] for a in ship_icons(ad) if a in _simge), _simge['DEFAULT'])


def can(hp, hp_max, kalkan, kalkan_max, nano=0, nano_max=0):
    return mod('HealthModule', hp=int(hp), hpMax=int(hp_max), shield=int(kalkan), shieldMax=int(kalkan_max), nanoHull=int(nano),
               nanoHullMax=int(nano_max))


def gemi_cani(p):
    g = p.d['gemi']
    return can(g.get('hitPoints', 0), g.get('hitMax', 0), g.get('shield', 0), g.get('shieldMax', 0), g.get('nanoHull', 0),
               g.get('maxNanoHull', 0))


def hedef(k, now):
    """Üyenin seçili hedefi (uzaylı ya da oyuncu) -> TargetModule (hedefsiz: boş)."""
    w = k.world
    t = w.target if w is not None and w.running else None
    n = w.npcs.get(t) if t is not None else None
    if n is not None and n.alive:
        return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=npc_simge(n.d.get('ad'))), name=str(n.d.get('ad', '')),
                   health=can(n.hp, n.d.get('hp', 0), n.shield, n.d.get('kalkan', 0)))
    o = TP.bul(uid=t) if t is not None else None
    if o is not None and o.uid != k.uid:
        return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=simge(o.profil.ship()['lootId'])), name=o.ad,
                   health=gemi_cani(o.profil))
    return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=0), name='', health=can(0, 0, 0, 0))


def konum(k, now):
    p = k.profil
    w = k.world
    n = getattr(getattr(k.oturum, 'bot', None), 'govde', None)         # bot: haritadaki gemisi (kayıttaki konum eski kalır)
    if w is not None:
        x, y = w.hero_pos(now)
    elif n is not None and n.alive:
        x, y = n.mover.pos(now)
    else:
        x, y = p.d['konum'].get('x', 0), p.d['konum'].get('y', 0)
    return int(p.d['konum'].get('mapId', 0)), int(x), int(y)


def durum(k, now):
    """Üyenin grup penceresindeki hâli: modül adı -> modül (GroupMemberUpdateCommand'ın parçaları)."""
    p, w = k.profil, k.world
    pl = p.d['pilot']
    m, x, y = konum(k, now)
    return {'ActivityModule': mod('ActivityModule', active=w is not None),
            'ClanModule': mod('ClanModule', clanTag=str(pl.get('clanTag', '')), clanId=int(pl.get('clanId', 0) or 0)),
            'CloakDeviceActivityModule': mod('CloakDeviceActivityModule', active=bool(w is not None and w.gizli(now))),
            'FactionModule': mod('FactionModule', faction=int(pl.get('factionId', 0) or 0)),
            'FightActivityModule': mod('FightActivityModule', active=bool(w is not None and now - w.last_combat < SAVAS_SN)),
            'HealthModule': gemi_cani(p),
            'InvitationBlockModule': mod('InvitationBlockModule', active=bool(p.d.get('davet_engeli'))),
            'LevelModule': mod('LevelModule', level=int(pl.get('level', 1))),
            'LocationModule': mod('LocationModule', mapId=m, x=x, y=y),
            'MemberLoggedOutModule': mod('MemberLoggedOutModule', loggedOut=k.oturum is None),
            'RaidGateGameStageModule': mod('RaidGateGameStageModule', gameStage=0, isInGate=False),
            'ShipIconModule': mod('ShipIconModule', shipIcon=simge(p.ship()['lootId'])),
            'TargetModule': hedef(k, now)}


def uye_cmd(k, d):
    pl = k.profil.d['pilot']
    return mod('GroupMemberInitializationCommand', id=k.uid, name=k.ad, level=int(pl.get('level', 1)),
               loggedOut=d['MemberLoggedOutModule']['loggedOut'], active=d['ActivityModule']['active'],
               cloaked=d['CloakDeviceActivityModule']['active'], inFight=d['FightActivityModule']['active'],
               blockingInvitations=d['InvitationBlockModule']['active'], raidGateGameStage=d['RaidGateGameStageModule'],
               location=d['LocationModule'], shipIcon=d['ShipIconModule'], health=d['HealthModule'], clan=d['ClanModule'],
               target=d['TargetModule'], faction=d['FactionModule'])


def grup_cmd(g, kisiler, now):
    uyeler = []
    for u in g.uyeler:
        k = kisiler.get(u)
        if k is not None:
            d = durum(k, now)
            g.durum.setdefault(u, d)          # öteki üyelerin gördüğü hâl değişmez: farkı guncelle gönderir (dönen üyenin "online"ı)
            uyeler.append(uye_cmd(k, d))
    return ('GroupInitializationCommand', {'id': g.id, 'leaderId': g.lider, 'maxSize': EN_COK, 'members': uyeler,
                                           'invitationMode': mod('InvitationModeModule', mode=g.mod)})


def davet_cmd(a, b):
    return ('InvitationInitializationCommand', {'inviterId': a.uid, 'inviterName': a.ad, 'candidateId': b.uid, 'candidateName': b.ad,
                                                'inviterShip': mod('ShipIconModule', shipIcon=simge(a.profil.ship()['lootId'])),
                                                'candidateShip': mod('ShipIconModule', shipIcon=simge(b.profil.ship()['lootId']))})


def hata(a, b, kod):
    return ('InvitationErrorCommand', {'inviterId': a, 'candidateId': b, 'error': kod})


def kaldir(a, b, neden):
    return ('InvitationRemovalCommand', {'inviterId': a, 'candidateId': b, 'reason': neden})


def dagit(cikis):
    """{kimlik: [mesaj]} -> her biri bağlıysa istemcisine (kilit dışında)."""
    kisiler = TP.hepsi()
    for uid, msgs in cikis.items():
        k = kisiler.get(uid)
        if k is not None and msgs:
            k.gonder(msgs, 'grup')


def _ekle(cikis, uid, *msgs):
    cikis.setdefault(uid, []).extend(msgs)


# ------------------------------------------------------------ istekler
def handle(k, name, f, now=None):
    """İsteği yapan oyuncu (topluluk.Kisi) -> kendisine giden yanıt; başkalarına gidenler doğrudan gönderilir."""
    now = now or time.time()
    cikis = {}
    with LOCK:
        if name == 'InvitationCreationRequest':
            b = TP.bul(ad=f.get('name'))
            _davet(k, b, cikis, now)
        elif name == 'GroupInvitationRequest':
            _davet(k, TP.bul(uid=f.get('candidateId')), cikis, now)
        elif name == 'InvitationAcceptRequest':
            _kabul(k, int(f.get('inviterId') or 0), cikis, now)
        elif name == 'InvitationRejectRequest':
            a = int(f.get('inviterId') or 0)
            if DAVETLER.pop((a, k.uid), None) is None:
                _ekle(cikis, k.uid, hata(a, k.uid, NO_INVITATION))
            else:
                _davet_bitti(a, k.uid, REJECT, cikis)
        elif name == 'InvitationCancelRequest':
            b = int(f.get('candidateId') or 0)
            if DAVETLER.pop((k.uid, b), None) is None:
                _ekle(cikis, k.uid, hata(k.uid, b, NO_INVITATION))
            else:
                _davet_bitti(k.uid, b, REVOKE, cikis)
        elif name == 'LeaveGroupRequest':
            if grubu(k.uid) is None:
                _ekle(cikis, k.uid, ('GroupErrorCommand', {'type': NO_GROUP}))
            else:
                _ayril(k.uid, AYRILDI, cikis)
        elif name == 'KickMemberRequest':
            g, u = grubu(k.uid), int(f.get('memberId') or 0)
            if g is not None and g.lider == k.uid and u in g.uyeler and u != k.uid:
                _ayril(u, ATILDI, cikis)
        elif name == 'ChangeLeaderRequest':
            g, u = grubu(k.uid), int(f.get('memberId') or 0)
            if g is not None and g.lider == k.uid and u in g.uyeler and u != k.uid:
                g.lider = u
                for x in g.uyeler:
                    _ekle(cikis, x, ('LeaderChangeCommand', {'leaderId': u}))
        elif name == 'InvitationModeRequest':
            g = grubu(k.uid)
            mode = int((f.get('mode') or {}).get('mode', MOD_LIDER))
            if g is not None and g.lider == k.uid and mode in (MOD_LIDER, MOD_HERKES):
                g.mod = mode
                for x in g.uyeler:
                    _ekle(cikis, x, ('InvitationModeModule', {'mode': mode}))
        elif name in ('PingPositionRequest', 'PingMemberRequest'):
            _ping(k, name, f, cikis, now)
        elif name == 'FollowRequest':
            g, u = grubu(k.uid), int(f.get('memberId') or 0)
            o = TP.bul(uid=u) if g is not None and u in g.uyeler else None
            # bot üyenin dünyası yok (oturumu sahte): çevrimiçiyse konumu gemisinden (oyuncu bildirimi 2026-10-31: "Go to!" botta
            # "location unknown: wrong map" diyordu)
            if o is not None and o.oturum is not None and k.world is not None and konum(o, now)[0] == konum(k, now)[0]:
                _, x, y = konum(o, now)
                _ekle(cikis, k.uid, ('HeroMoveCommand', {'x': x, 'y': y}))
            else:
                _ekle(cikis, k.uid, ('GroupErrorCommand', {'type': FOLLOW_FAILED if g is not None else NO_GROUP}))
    own = cikis.pop(k.uid, [])
    dagit(cikis)
    return own


def _davet(a, b, cikis, now):
    g = grubu(a.uid)
    bid = b.uid if b is not None else 0
    if b is None or b.uid == a.uid or b.oturum is None:
        err = CANDIDATE_NONEXISTENT
    elif g is not None and g.lider != a.uid and g.mod == MOD_LIDER:
        err = BOSS_ONLY
    elif g is not None and len(g.uyeler) + sum(1 for x, _ in DAVETLER if x in g.uyeler) >= EN_COK:
        err = GROUP_FULL
    elif grubu(b.uid) is not None:
        err = CANDIDATE_IN_GROUP
    elif b.profil.d.get('davet_engeli'):
        err = CANDIDATE_BLOCKING
    elif (a.uid, b.uid) in DAVETLER:
        err = DUPLICATE_INVITATION
    elif sum(1 for x, _ in DAVETLER if x == a.uid) >= DAVET_EN_COK:
        err = MAX_INVITER
    elif sum(1 for _, y in DAVETLER if y == b.uid) >= DAVET_EN_COK:
        err = MAX_CANDIDATE
    else:
        err = None
    if err is not None:
        _ekle(cikis, a.uid, hata(a.uid, bid, err))
        return
    DAVETLER[(a.uid, b.uid)] = now + DAVET_SN
    baslat()                                                  # süresi dolan davetler ve üyelerin durumu
    cmd = davet_cmd(a, b)
    _ekle(cikis, a.uid, cmd, stm('msg_grp_inv_sent', name=b.ad))
    _ekle(cikis, b.uid, cmd, stm('msg_grp_inv_received', name=a.ad))
    for x in (g.uyeler if g is not None else ()):
        if x != a.uid:
            _ekle(cikis, x, cmd)


def _davet_bitti(a, b, neden, cikis):
    """Davet düştü: davet edene, adaya ve davet edenin grubundakilere InvitationRemovalCommand (metni istemci yazar)."""
    g = grubu(a)
    for x in {a, b} | set(g.uyeler if g is not None else ()):
        _ekle(cikis, x, kaldir(a, b, neden))


def _kabul(b, a, cikis, now):
    if DAVETLER.pop((a, b.uid), None) is None:
        _ekle(cikis, b.uid, hata(a, b.uid, NO_INVITATION))
        return
    ka = TP.bul(uid=a)
    if ka is None:
        _davet_bitti(a, b.uid, REJECT, cikis)
        _ekle(cikis, b.uid, hata(a, b.uid, INVITER_NONEXISTENT))
        return
    if grubu(b.uid) is not None:
        _davet_bitti(a, b.uid, ACKNOWLEDGE, cikis)
        _ekle(cikis, b.uid, hata(a, b.uid, CANDIDATE_IN_GROUP))
        return
    g = grubu(a)
    if g is not None and len(g.uyeler) >= EN_COK:
        _davet_bitti(a, b.uid, ACKNOWLEDGE, cikis)
        _ekle(cikis, b.uid, hata(a, b.uid, GROUP_FULL))
        return
    _davet_bitti(a, b.uid, ACKNOWLEDGE, cikis)
    for (x, y) in [d for d in DAVETLER if d[1] == b.uid]:     # adayın öteki davetleri düşer (artık bir grupta)
        del DAVETLER[(x, y)]
        _davet_bitti(x, y, REJECT, cikis)
    kisiler = TP.hepsi()
    yeni = g is None
    if yeni:
        g = Grup(a)
        GRUPLAR[g.id] = g
        UYE[a] = g.id
    eski = list(g.uyeler)
    g.uyeler.append(b.uid)
    UYE[b.uid] = g.id
    if _bot(g.lider) and not _bot(b.uid):        # bot liderliğinde oyuncu: lider o olur (botlar davet kipini, atmayı kullanmaz;
        g.lider = b.uid                          # oyuncu bildirimi 2026-10-31: "Change invite settings" çalışmıyordu)
        for x in eski:
            _ekle(cikis, x, ('LeaderChangeCommand', {'leaderId': g.lider}))
    init = grup_cmd(g, kisiler, now)
    _ekle(cikis, b.uid, init)
    if yeni:
        _ekle(cikis, a, init, stm('msg_grp_new_member', name=b.ad))
    else:
        uye = next(m for m in init[1]['members'] if m['id'] == b.uid)
        for x in eski:
            _ekle(cikis, x, ('GroupMemberInitializationCommand', {k: v for k, v in uye.items() if k != '_'}),
                  stm('msg_grp_new_member', name=b.ad))


def _bot(uid):
    return TP.BOTLAR is not None and uid in TP.BOTLAR()


def _ayril(u, neden, cikis):
    g = grubu(u)
    if g is None:
        return
    for x in g.uyeler:
        _ekle(cikis, x, ('MemberLeaveCommand', {'playerId': u, 'reason': neden}))
    g.uyeler.remove(u)
    g.durum.pop(u, None)
    UYE.pop(u, None)
    for (x, y) in [d for d in DAVETLER if d[0] == u]:          # ayrılanın grubu adına davetleri düşer
        del DAVETLER[(x, y)]
        _davet_bitti(x, y, REVOKE, cikis)
    cikan = [u]
    if len(g.uyeler) < 2:
        for x in g.uyeler:
            _ekle(cikis, x, ('GroupCloseCommand', {}), stm('msg_grp_broken_up'))
            UYE.pop(x, None)
        cikan += g.uyeler
        del GRUPLAR[g.id]
    elif g.lider == u:
        g.lider = g.uyeler[0]
        for x in g.uyeler:
            _ekle(cikis, x, ('LeaderChangeCommand', {'leaderId': g.lider}))
    _sohbet_birak(g.id, cikan)


def _ping(k, name, f, cikis, now):
    g = grubu(k.uid)
    if g is None:
        _ekle(cikis, k.uid, ('GroupErrorCommand', {'type': NO_GROUP}))
        return
    if now - g.ping.get(k.uid, 0) < PING_SN:
        _ekle(cikis, k.uid, ('GroupErrorCommand', {'type': PING_FAILED}), stm('msg_grp_ping_error'))
        return
    kisiler = TP.hepsi()
    harita = konum(k, now)[0]
    if name == 'PingMemberRequest':
        o = kisiler.get(int(f.get('memberId') or 0))
        if o is None or o.uid not in g.uyeler or o.world is None or konum(o, now)[0] != harita:
            _ekle(cikis, k.uid, ('GroupErrorCommand', {'type': PING_FAILED}))
            return
        _, x, y = konum(o, now)
    else:
        x, y = int(f.get('x', 0)), int(f.get('y', 0))
    g.ping[k.uid] = now
    for u in g.uyeler:
        o = kisiler.get(u)
        if o is not None and o.world is not None and konum(o, now)[0] == harita:
            _ekle(cikis, u, ('PingCommand', {'x': x, 'y': y}))


def _sohbet_birak(gid, uids):
    """Gruptan çıkanların sohbet bağlantısı grubun odasını artık dinlemesin (istemci odayı kendisi kapatır). Girende gerek yok:
    istemci GroupInitializationCommand'da sohbete yeniden bağlanır, odaları sosyal.rooms'tan alır (grubunki orada)."""
    kisiler = TP.hepsi()
    for u in uids:
        k = kisiler.get(u)
        sh = getattr(getattr(k.oturum if k is not None else None, 'sosyal', None), 'sohbet', None)
        if sh is not None:
            sh.oda_birak(str(u), *oda(gid)[1:])


# ------------------------------------------------------------ giriş ve durum güncellemeleri
def giris_msgs(k, now=None):
    """Oyuncu oyuna girdi (ilk ReadyRequest): grubu ve bekleyen davetleri (istemci girişte boş grup penceresiyle başlar)."""
    now = now or time.time()
    out = []
    with LOCK:
        kisiler = TP.hepsi()
        g = grubu(k.uid)
        if g is not None:
            out.append(grup_cmd(g, kisiler, now))
        for (a, b) in list(DAVETLER):
            if k.uid in (a, b) and a in kisiler and b in kisiler:
                out.append(davet_cmd(kisiler[a], kisiler[b]))
        if k.profil.d.get('davet_engeli'):
            out.append(('InvitationBlockModule', {'active': True}))
    return out


def guncelle(now=None):
    """Bir adım: süresi dolan davetler, kaydı biten üyeler, üyelerin değişen durumu."""
    now = now or time.time()
    cikis = {}
    with LOCK:
        kisiler = TP.hepsi()
        for (a, b), son in list(DAVETLER.items()):
            if son <= now or a not in kisiler or b not in kisiler:
                del DAVETLER[(a, b)]
                _davet_bitti(a, b, TIMEOUT, cikis)
        for g in list(GRUPLAR.values()):
            for u in [u for u in g.uyeler if u not in kisiler]:
                _ayril(u, AYRILDI, cikis)
            if g.id not in GRUPLAR:
                continue
            for u in g.uyeler:
                k = kisiler[u]
                yeni = durum(k, now)
                eski = g.durum.get(u) or {}
                fark = [v for n, v in yeni.items() if eski.get(n) != v and not (n == 'LocationModule' and _yakin(eski.get(n), v))]
                if not fark:
                    continue
                g.durum[u] = dict(eski, **{v['_']: v for v in fark})
                msgs = [('GroupMemberUpdateCommand', {'playerId': u, 'updates': fark})]
                for v in fark:
                    if v['_'] == 'MemberLoggedOutModule' and eski:
                        msgs.append(stm('msg_grp_member_logs_out' if v['loggedOut'] else 'msg_grp_member_back', name=k.ad))
                    elif v['_'] == 'LocationModule' and eski.get('LocationModule') and eski['LocationModule']['mapId'] != v['mapId']:
                        msgs.append(stm('msg_grp_jump', name=k.ad, map=H.name(v['mapId'])))
                for x in g.uyeler:
                    _ekle(cikis, x, *[m for m in msgs if x != u or m[0] == 'GroupMemberUpdateCommand'])
    dagit(cikis)


def _yakin(a, b):
    return a is not None and a['mapId'] == b['mapId'] and abs(a['x'] - b['x']) < KONUM_ESIK and abs(a['y'] - b['y']) < KONUM_ESIK


def oldu(k):
    """Üye vuruldu (dunya.hero_death): öteki üyelere "%name% was shot down." (istemci yalnız kendi ölümünü yazar)."""
    g = grubu(k.uid)
    if g is not None:
        dagit({u: [stm('msg_grp_member_killed', name=k.ad)] for u in list(g.uyeler) if u != k.uid})


def uyeler(uid):
    """Oyuncunun grubundaki öteki üyelerin kimlikleri (saldırı yasağı, sohbet odası)."""
    g = grubu(uid)
    return [u for u in g.uyeler if u != uid] if g is not None else []


def _dongu():
    while True:
        time.sleep(GUNCELLEME_SN)
        try:
            guncelle()
        except Exception:
            import traceback
            traceback.print_exc()


def baslat():
    """Durum güncellemelerinin iş parçacığı (ilk grup kurulunca bir kez)."""
    global _is
    if _is is None:
        _is = threading.Thread(target=_dongu, name='grup', daemon=True)
        _is.start()
