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
Aynı ortak haritadaki üyeler (shared_maps.py; kapı ve mod haritaları herkesin kendi kopyası, oralarda paylaşım yok):
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
import community as TP
import map_links as H
from cbs import stm

MAX_COUNT = 8                    # grubun en çok üyesi (gerçek oyun)
INVITE_SEC = 120                # yanıtlanmayan davetin ömrü
INVITE_MAX = 10             # bir oyuncunun bekleyen davetleri (gönderdiği ya da aldığı)
UPDATE_SEC = 1.0
COMBAT_SEC = 10.0               # son atış ya da alınan hasardan sonra "savaşta" sayılma süresi
PING_SEC = 1.0                 # iki ping arası en az
POSITION_THRESHOLD = 50               # bu kadar yer değiştirmeyen üyenin konumu yeniden gönderilmez
# InvitationErrorCommand.error
GROUP_FULL, CANDIDATE_IN_GROUP, CANDIDATE_NONEXISTENT, INVITER_NONEXISTENT, NO_INVITATION, BOSS_ONLY, MAX_INVITER, \
    MAX_CANDIDATE, CANDIDATE_BLOCKING, DUPLICATE_INVITATION = range(10)
# InvitationRemovalCommand.reason
TIMEOUT, REVOKE, REJECT, ACKNOWLEDGE = 1, 2, 3, 4
# GroupErrorCommand.type
PING_FAILED, NO_GROUP, FOLLOW_FAILED = 0, 1, 2
MODE_LEADER, MODE_EVERYONE = 0, 1  # InvitationModeModule.mode: davet yalnız liderden / herkesten
LEFT, KICKED = 1, 2        # MemberLeaveCommand.reason

REQUESTS = {'InvitationCreationRequest', 'GroupInvitationRequest', 'InvitationAcceptRequest', 'InvitationRejectRequest',
            'InvitationCancelRequest', 'LeaveGroupRequest', 'KickMemberRequest', 'ChangeLeaderRequest', 'InvitationModeRequest',
            'PingPositionRequest', 'PingMemberRequest', 'FollowRequest'}

LOCK = threading.RLock()
GROUPS = {}                  # grup kimliği -> Grup
MEMBER = {}                      # oyuncu kimliği -> grup kimliği
INVITES = {}                 # (davet eden, aday) -> son geçerlilik anı
_seq = [0]
_icon = None
_thread = None


def mod(_cls, **f):
    return dict(_=_cls, **f)


class Group:
    def __init__(self, leader):
        _seq[0] += 1
        self.id, self.leader, self.members, self.mod = _seq[0], leader, [leader], MODE_LEADER
        self.state = {}       # üye -> son gönderilen durum (guncelle)
        self.ping = {}        # üye -> son ping anı


def room(gid):
    """Grubun sohbet odası (sosyal.rooms; chat.py)."""
    return ('group', 'group', 'group_%d' % gid)


def group_of(uid):
    with LOCK:
        g = GROUPS.get(MEMBER.get(uid))
        return g


# ------------------------------------------------------------ mesajlar
def icon(loot):
    """Geminin lootId'si (ship_goliath, ship_g-champion, ship_a-elite) -> ShipIcon değeri (bilinmeyen: DEFAULT)."""
    global _icon
    if _icon is None:
        _icon = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ship_icons.json'),
                                encoding='utf8'))['icons']
    name = str(loot or '')[5:] if str(loot or '').startswith('ship_') else str(loot or '')
    on, _, last = name.partition('-')
    base = {'a': 'AEGIS', 'c': 'CITADEL', 's': 'SPEARHEAD', 'n': 'NOSTROMO', 'g': 'GOLIATH', 'v': 'VENGEANCE', 'bb': 'BIGBOY',
             'd': 'DEFCOM', 'y': 'YAMATO'}.get(on)
    # tasarım gemileri: g-champion -> GOLIATH, a-elite -> AEGIS_ELITE, n-envoy -> NOSTROMO_ENVOY, v-adept -> ADEPT
    candidates = [name.replace('-', '_').upper()] + ([base + '_' + last.replace('-', '_').upper()] if base and last else []) \
        + ([last.replace('-', '_').upper()] if on in ('g', 'v', 'bb') and last else []) + ([base] if base else [])
    return next((_icon[a] for a in candidates if a in _icon), _icon['DEFAULT'])


def npc_icon(name):
    """Uzaylının görünen adı -> ShipIcon değeri (basarim.ship_icons adayları; bulunamazsa DEFAULT)."""
    from achievement import ship_icons
    icon('')
    return next((_icon[a] for a in ship_icons(name) if a in _icon), _icon['DEFAULT'])


def hp(hp, hp_max, shield, shield_max, nano=0, nano_max=0):
    return mod('HealthModule', hp=int(hp), hpMax=int(hp_max), shield=int(shield), shieldMax=int(shield_max), nanoHull=int(nano),
               nanoHullMax=int(nano_max))


def ship_hp(p):
    g = p.d['ship']
    return hp(g.get('hitPoints', 0), g.get('hitMax', 0), g.get('shield', 0), g.get('shieldMax', 0), g.get('nanoHull', 0),
               g.get('maxNanoHull', 0))


def target(k, now):
    """Üyenin seçili hedefi (uzaylı ya da oyuncu) -> TargetModule (hedefsiz: boş)."""
    w = k.world
    t = w.target if w is not None and w.running else None
    n = w.npcs.get(t) if t is not None else None
    if n is not None and n.alive:
        return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=npc_icon(n.d.get('name'))), name=str(n.d.get('name', '')),
                   health=hp(n.hp, n.d.get('hp', 0), n.shield, n.d.get('kalkan', 0)))
    o = TP.find(uid=t) if t is not None else None
    if o is not None and o.uid != k.uid:
        return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=icon(o.profile.ship()['lootId'])), name=o.name,
                   health=ship_hp(o.profile))
    return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=0), name='', health=hp(0, 0, 0, 0))


def position(k, now):
    p = k.profile
    w = k.world
    n = getattr(getattr(k.session, 'bot', None), 'body', None)         # bot: haritadaki gemisi (kayıttaki konum eski kalır)
    if w is not None:
        x, y = w.hero_pos(now)
    elif n is not None and n.alive:
        x, y = n.mover.pos(now)
    else:
        x, y = p.d['position'].get('x', 0), p.d['position'].get('y', 0)
    return int(p.d['position'].get('mapId', 0)), int(x), int(y)


def state(k, now):
    """Üyenin grup penceresindeki hâli: modül adı -> modül (GroupMemberUpdateCommand'ın parçaları)."""
    p, w = k.profile, k.world
    pl = p.d['pilot']
    m, x, y = position(k, now)
    return {'ActivityModule': mod('ActivityModule', active=w is not None),
            'ClanModule': mod('ClanModule', clanTag=str(pl.get('clanTag', '')), clanId=int(pl.get('clanId', 0) or 0)),
            'CloakDeviceActivityModule': mod('CloakDeviceActivityModule', active=bool(w is not None and w.hidden(now))),
            'FactionModule': mod('FactionModule', faction=int(pl.get('factionId', 0) or 0)),
            'FightActivityModule': mod('FightActivityModule', active=bool(w is not None and now - w.last_combat < COMBAT_SEC)),
            'HealthModule': ship_hp(p),
            'InvitationBlockModule': mod('InvitationBlockModule', active=bool(p.d.get('invite_block'))),
            'LevelModule': mod('LevelModule', level=int(pl.get('level', 1))),
            'LocationModule': mod('LocationModule', mapId=m, x=x, y=y),
            'MemberLoggedOutModule': mod('MemberLoggedOutModule', loggedOut=k.session is None),
            'RaidGateGameStageModule': mod('RaidGateGameStageModule', gameStage=0, isInGate=False),
            'ShipIconModule': mod('ShipIconModule', shipIcon=icon(p.ship()['lootId'])),
            'TargetModule': target(k, now)}


def member_cmd(k, d):
    pl = k.profile.d['pilot']
    return mod('GroupMemberInitializationCommand', id=k.uid, name=k.name, level=int(pl.get('level', 1)),
               loggedOut=d['MemberLoggedOutModule']['loggedOut'], active=d['ActivityModule']['active'],
               cloaked=d['CloakDeviceActivityModule']['active'], inFight=d['FightActivityModule']['active'],
               blockingInvitations=d['InvitationBlockModule']['active'], raidGateGameStage=d['RaidGateGameStageModule'],
               location=d['LocationModule'], shipIcon=d['ShipIconModule'], health=d['HealthModule'], clan=d['ClanModule'],
               target=d['TargetModule'], faction=d['FactionModule'])


def group_cmd(g, people, now):
    members = []
    for u in g.members:
        k = people.get(u)
        if k is not None:
            d = state(k, now)
            g.state.setdefault(u, d)          # öteki üyelerin gördüğü hâl değişmez: farkı guncelle gönderir (dönen üyenin "online"ı)
            members.append(member_cmd(k, d))
    return ('GroupInitializationCommand', {'id': g.id, 'leaderId': g.leader, 'maxSize': MAX_COUNT, 'members': members,
                                           'invitationMode': mod('InvitationModeModule', mode=g.mod)})


def invite_cmd(a, b):
    return ('InvitationInitializationCommand', {'inviterId': a.uid, 'inviterName': a.name, 'candidateId': b.uid, 'candidateName': b.name,
                                                'inviterShip': mod('ShipIconModule', shipIcon=icon(a.profile.ship()['lootId'])),
                                                'candidateShip': mod('ShipIconModule', shipIcon=icon(b.profile.ship()['lootId']))})


def error(a, b, code):
    return ('InvitationErrorCommand', {'inviterId': a, 'candidateId': b, 'error': code})


def remove(a, b, reason):
    return ('InvitationRemovalCommand', {'inviterId': a, 'candidateId': b, 'reason': reason})


def distribute(exit):
    """{uid: [mesaj]} -> her biri bağlıysa istemcisine (kilit dışında)."""
    people = TP.all_()
    for uid, msgs in exit.items():
        k = people.get(uid)
        if k is not None and msgs:
            k.send(msgs, 'group')


def _add(exit, uid, *msgs):
    exit.setdefault(uid, []).extend(msgs)


# ------------------------------------------------------------ istekler
def handle(k, name, f, now=None):
    """İsteği yapan oyuncu (topluluk.Kisi) -> kendisine giden yanıt; başkalarına gidenler doğrudan gönderilir."""
    now = now or time.time()
    exit = {}
    with LOCK:
        if name == 'InvitationCreationRequest':
            b = TP.find(name=f.get('name'))
            _invite(k, b, exit, now)
        elif name == 'GroupInvitationRequest':
            _invite(k, TP.find(uid=f.get('candidateId')), exit, now)
        elif name == 'InvitationAcceptRequest':
            _accepted(k, int(f.get('inviterId') or 0), exit, now)
        elif name == 'InvitationRejectRequest':
            a = int(f.get('inviterId') or 0)
            if INVITES.pop((a, k.uid), None) is None:
                _add(exit, k.uid, error(a, k.uid, NO_INVITATION))
            else:
                _invite_ended(a, k.uid, REJECT, exit)
        elif name == 'InvitationCancelRequest':
            b = int(f.get('candidateId') or 0)
            if INVITES.pop((k.uid, b), None) is None:
                _add(exit, k.uid, error(k.uid, b, NO_INVITATION))
            else:
                _invite_ended(k.uid, b, REVOKE, exit)
        elif name == 'LeaveGroupRequest':
            if group_of(k.uid) is None:
                _add(exit, k.uid, ('GroupErrorCommand', {'type': NO_GROUP}))
            else:
                _leave(k.uid, LEFT, exit)
        elif name == 'KickMemberRequest':
            g, u = group_of(k.uid), int(f.get('memberId') or 0)
            if g is not None and g.leader == k.uid and u in g.members and u != k.uid:
                _leave(u, KICKED, exit)
        elif name == 'ChangeLeaderRequest':
            g, u = group_of(k.uid), int(f.get('memberId') or 0)
            if g is not None and g.leader == k.uid and u in g.members and u != k.uid:
                g.leader = u
                for x in g.members:
                    _add(exit, x, ('LeaderChangeCommand', {'leaderId': u}))
        elif name == 'InvitationModeRequest':
            g = group_of(k.uid)
            mode = int((f.get('mode') or {}).get('mode', MODE_LEADER))
            if g is not None and g.leader == k.uid and mode in (MODE_LEADER, MODE_EVERYONE):
                g.mod = mode
                for x in g.members:
                    _add(exit, x, ('InvitationModeModule', {'mode': mode}))
        elif name in ('PingPositionRequest', 'PingMemberRequest'):
            _ping(k, name, f, exit, now)
        elif name == 'FollowRequest':
            g, u = group_of(k.uid), int(f.get('memberId') or 0)
            o = TP.find(uid=u) if g is not None and u in g.members else None
            # bot üyenin dünyası yok (oturumu sahte): çevrimiçiyse konumu gemisinden (oyuncu bildirimi 2026-10-31: "Go to!" botta
            # "location unknown: wrong map" diyordu)
            if o is not None and o.session is not None and k.world is not None and position(o, now)[0] == position(k, now)[0]:
                _, x, y = position(o, now)
                _add(exit, k.uid, ('HeroMoveCommand', {'x': x, 'y': y}))
            else:
                _add(exit, k.uid, ('GroupErrorCommand', {'type': FOLLOW_FAILED if g is not None else NO_GROUP}))
    own = exit.pop(k.uid, [])
    distribute(exit)
    return own


def _invite(a, b, exit, now):
    g = group_of(a.uid)
    bid = b.uid if b is not None else 0
    if b is None or b.uid == a.uid or b.session is None:
        err = CANDIDATE_NONEXISTENT
    elif g is not None and g.leader != a.uid and g.mod == MODE_LEADER:
        err = BOSS_ONLY
    elif g is not None and len(g.members) + sum(1 for x, _ in INVITES if x in g.members) >= MAX_COUNT:
        err = GROUP_FULL
    elif group_of(b.uid) is not None:
        err = CANDIDATE_IN_GROUP
    elif b.profile.d.get('invite_block'):
        err = CANDIDATE_BLOCKING
    elif (a.uid, b.uid) in INVITES:
        err = DUPLICATE_INVITATION
    elif sum(1 for x, _ in INVITES if x == a.uid) >= INVITE_MAX:
        err = MAX_INVITER
    elif sum(1 for _, y in INVITES if y == b.uid) >= INVITE_MAX:
        err = MAX_CANDIDATE
    else:
        err = None
    if err is not None:
        _add(exit, a.uid, error(a.uid, bid, err))
        return
    INVITES[(a.uid, b.uid)] = now + INVITE_SEC
    launch()                                                  # süresi dolan davetler ve üyelerin durumu
    cmd = invite_cmd(a, b)
    _add(exit, a.uid, cmd, stm('msg_grp_inv_sent', name=b.name))
    _add(exit, b.uid, cmd, stm('msg_grp_inv_received', name=a.name))
    for x in (g.members if g is not None else ()):
        if x != a.uid:
            _add(exit, x, cmd)


def _invite_ended(a, b, reason, exit):
    """Davet düştü: davet edene, adaya ve davet edenin grubundakilere InvitationRemovalCommand (metni istemci yazar)."""
    g = group_of(a)
    for x in {a, b} | set(g.members if g is not None else ()):
        _add(exit, x, remove(a, b, reason))


def _accepted(b, a, exit, now):
    if INVITES.pop((a, b.uid), None) is None:
        _add(exit, b.uid, error(a, b.uid, NO_INVITATION))
        return
    person_a = TP.find(uid=a)
    if person_a is None:
        _invite_ended(a, b.uid, REJECT, exit)
        _add(exit, b.uid, error(a, b.uid, INVITER_NONEXISTENT))
        return
    if group_of(b.uid) is not None:
        _invite_ended(a, b.uid, ACKNOWLEDGE, exit)
        _add(exit, b.uid, error(a, b.uid, CANDIDATE_IN_GROUP))
        return
    g = group_of(a)
    if g is not None and len(g.members) >= MAX_COUNT:
        _invite_ended(a, b.uid, ACKNOWLEDGE, exit)
        _add(exit, b.uid, error(a, b.uid, GROUP_FULL))
        return
    _invite_ended(a, b.uid, ACKNOWLEDGE, exit)
    for (x, y) in [d for d in INVITES if d[1] == b.uid]:     # adayın öteki davetleri düşer (artık bir grupta)
        del INVITES[(x, y)]
        _invite_ended(x, y, REJECT, exit)
    people = TP.all_()
    new_ = g is None
    if new_:
        g = Group(a)
        GROUPS[g.id] = g
        MEMBER[a] = g.id
    old = list(g.members)
    g.members.append(b.uid)
    MEMBER[b.uid] = g.id
    if _bot(g.leader) and not _bot(b.uid):        # bot liderliğinde oyuncu: lider o olur (botlar davet kipini, atmayı kullanmaz;
        g.leader = b.uid                          # oyuncu bildirimi 2026-10-31: "Change invite settings" çalışmıyordu)
        for x in old:
            _add(exit, x, ('LeaderChangeCommand', {'leaderId': g.leader}))
    init = group_cmd(g, people, now)
    _add(exit, b.uid, init)
    if new_:
        _add(exit, a, init, stm('msg_grp_new_member', name=b.name))
    else:
        member = next(m for m in init[1]['members'] if m['id'] == b.uid)
        for x in old:
            _add(exit, x, ('GroupMemberInitializationCommand', {k: v for k, v in member.items() if k != '_'}),
                  stm('msg_grp_new_member', name=b.name))


def _bot(uid):
    return TP.BOTS is not None and uid in TP.BOTS()


def _leave(u, reason, exit):
    g = group_of(u)
    if g is None:
        return
    for x in g.members:
        _add(exit, x, ('MemberLeaveCommand', {'playerId': u, 'reason': reason}))
    g.members.remove(u)
    g.state.pop(u, None)
    MEMBER.pop(u, None)
    for (x, y) in [d for d in INVITES if d[0] == u]:          # ayrılanın grubu adına davetleri düşer
        del INVITES[(x, y)]
        _invite_ended(x, y, REVOKE, exit)
    leaving = [u]
    if len(g.members) < 2:
        for x in g.members:
            _add(exit, x, ('GroupCloseCommand', {}), stm('msg_grp_broken_up'))
            MEMBER.pop(x, None)
        leaving += g.members
        del GROUPS[g.id]
    elif g.leader == u:
        g.leader = g.members[0]
        for x in g.members:
            _add(exit, x, ('LeaderChangeCommand', {'leaderId': g.leader}))
    _leave_chat(g.id, leaving)


def _ping(k, name, f, exit, now):
    g = group_of(k.uid)
    if g is None:
        _add(exit, k.uid, ('GroupErrorCommand', {'type': NO_GROUP}))
        return
    if now - g.ping.get(k.uid, 0) < PING_SEC:
        _add(exit, k.uid, ('GroupErrorCommand', {'type': PING_FAILED}), stm('msg_grp_ping_error'))
        return
    people = TP.all_()
    game_map = position(k, now)[0]
    if name == 'PingMemberRequest':
        o = people.get(int(f.get('memberId') or 0))
        if o is None or o.uid not in g.members or o.world is None or position(o, now)[0] != game_map:
            _add(exit, k.uid, ('GroupErrorCommand', {'type': PING_FAILED}))
            return
        _, x, y = position(o, now)
    else:
        x, y = int(f.get('x', 0)), int(f.get('y', 0))
    g.ping[k.uid] = now
    for u in g.members:
        o = people.get(u)
        if o is not None and o.world is not None and position(o, now)[0] == game_map:
            _add(exit, u, ('PingCommand', {'x': x, 'y': y}))


def _leave_chat(gid, uids):
    """Gruptan çıkanların sohbet bağlantısı grubun odasını artık dinlemesin (istemci odayı kendisi kapatır). Girende gerek yok:
    istemci GroupInitializationCommand'da sohbete yeniden bağlanır, odaları sosyal.rooms'tan alır (grubunki orada)."""
    people = TP.all_()
    for u in uids:
        k = people.get(u)
        sh = getattr(getattr(k.session if k is not None else None, 'social', None), 'chat', None)
        if sh is not None:
            sh.room_drop(str(u), *room(gid)[1:])


# ------------------------------------------------------------ giriş ve durum güncellemeleri
def login_msgs(k, now=None):
    """Oyuncu oyuna girdi (ilk ReadyRequest): grubu ve bekleyen davetleri (istemci girişte boş grup penceresiyle başlar)."""
    now = now or time.time()
    out = []
    with LOCK:
        people = TP.all_()
        g = group_of(k.uid)
        if g is not None:
            out.append(group_cmd(g, people, now))
        for (a, b) in list(INVITES):
            if k.uid in (a, b) and a in people and b in people:
                out.append(invite_cmd(people[a], people[b]))
        if k.profile.d.get('invite_block'):
            out.append(('InvitationBlockModule', {'active': True}))
    return out


def update(now=None):
    """Bir adım: süresi dolan davetler, kaydı biten üyeler, üyelerin değişen durumu."""
    now = now or time.time()
    exit = {}
    with LOCK:
        people = TP.all_()
        for (a, b), last in list(INVITES.items()):
            if last <= now or a not in people or b not in people:
                del INVITES[(a, b)]
                _invite_ended(a, b, TIMEOUT, exit)
        for g in list(GROUPS.values()):
            for u in [u for u in g.members if u not in people]:
                _leave(u, LEFT, exit)
            if g.id not in GROUPS:
                continue
            for u in g.members:
                k = people[u]
                new_ = state(k, now)
                old = g.state.get(u) or {}
                diff = [v for n, v in new_.items() if old.get(n) != v and not (n == 'LocationModule' and _nearby(old.get(n), v))]
                if not diff:
                    continue
                g.state[u] = dict(old, **{v['_']: v for v in diff})
                msgs = [('GroupMemberUpdateCommand', {'playerId': u, 'updates': diff})]
                for v in diff:
                    if v['_'] == 'MemberLoggedOutModule' and old:
                        msgs.append(stm('msg_grp_member_logs_out' if v['loggedOut'] else 'msg_grp_member_back', name=k.name))
                    elif v['_'] == 'LocationModule' and old.get('LocationModule') and old['LocationModule']['mapId'] != v['mapId']:
                        msgs.append(stm('msg_grp_jump', name=k.name, map=H.name(v['mapId'])))
                for x in g.members:
                    _add(exit, x, *[m for m in msgs if x != u or m[0] == 'GroupMemberUpdateCommand'])
    distribute(exit)


def _nearby(a, b):
    return a is not None and a['mapId'] == b['mapId'] and abs(a['x'] - b['x']) < POSITION_THRESHOLD and abs(a['y'] - b['y']) < POSITION_THRESHOLD


def died(k):
    """Üye vuruldu (dunya.hero_death): öteki üyelere "%name% was shot down." (istemci yalnız kendi ölümünü yazar)."""
    g = group_of(k.uid)
    if g is not None:
        distribute({u: [stm('msg_grp_member_killed', name=k.name)] for u in list(g.members) if u != k.uid})


def members(uid):
    """Oyuncunun grubundaki öteki üyelerin kimlikleri (saldırı yasağı, sohbet odası)."""
    g = group_of(uid)
    return [u for u in g.members if u != uid] if g is not None else []


def _loop():
    while True:
        time.sleep(UPDATE_SEC)
        try:
            update()
        except Exception:
            import traceback
            traceback.print_exc()


def launch():
    """Durum güncellemelerinin iş parçacığı (ilk grup kurulunca bir kez)."""
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, name='group', daemon=True)
        _thread.start()
