"""Botların toplumu: oyundaki kimliği (Profil) ve oyunun sosyal sistemlerine bağı.

Profil bellekte durur, dosyaya yazılmaz (BotProfil.save boş): kalıcı kayıt paketin durum.json'udur. guncelle() botun ilerlemesini
profile kopyalar (seviye, para, onur, gemi, dronlar, konum); rehber ve müzayede bölümleri botun kaydıyla aynı sözlüktür (kalıcı).

Oyunun bütün "öteki oyuncu" aramaları topluluk.hepsi()'den geçer: botlar oraya sahte oturumla (BotOturum) kaydolunca rehber,
klan, grup, fısıltı, posta, sıralama ve müzayede onları kendiliğinden görür. Botun kararları tick()'te (yöneticinin iş parçacığı):
  grup daveti        kabul / ret (sosyallik, ilişki, seviye farkı, süren işi), grupta liderin peşinden (hedefler/group.py)
  arkadaşlık         gelen isteği kabul / ret; birlikte oynadığı ya da yardım ettiği kişiye istek
  klan               lider ruhlu, zengin bot klan kurar; öteki botlar kişiliğine uyan klana başvurur; bot lider başvuruları
                     değerlendirir (oyuncununkiler de); sadakati az olan bot zamanla ayrılabilir
  müzayede           tüccar ve zengin botlar değerine göre teklif verir, son dakikalarda artırır
  sohbet             speech.py (Normal) ya da llm.py (Gelişmiş)
"""
import os, random, re, time

import player_profile as PF
import paths as PTH
from . import name_style as NS
from . import catalog as K


class BotProfile(PF.Profile):
    def __init__(self, bot):
        self.bot = bot
        super().__init__({}, path=os.path.join(PTH.LOGS, 'bot_profili_yok.json'), d=_skeleton(bot))   # yol hiç yazılmaz

    def save(self, force=False):
        self.dirty = False


def _skeleton(bot):
    return {
        'surum': 1, 'created': '2026-01-01 00:00:00',
        'pilot': {'userId': bot.uid, 'userName': bot.name, 'factionId': bot.firma, 'clanId': 0, 'clanTag': '', 'level': 1, 'ep': 0,
                  'honourPoints': 0, 'credits': 0, 'uridium': 0, 'premium': False, 'dailyRank': 1, 'useSystemFont': False},
        'gemi': {'typeId': 'ship_phoenix', 'speed': 320, 'shield': 0, 'shieldMax': 0, 'hitPoints': 104000, 'hitMax': 104000},
        'position': {'mapId': bot.game_map, 'x': 0, 'y': 0},
        'ships': {'1': {'lootId': 'ship_phoenix', 'hangarId': 1, 'configs': {}, 'active_config': 1}}, 'active_ship': 1,
        'drones': [], 'esyalar': {}, 'ores': [], 'formation': 0, 'settings': {}, 'key_bindings': [], 'ui': {'featureBars': []},
        'contacts': bot.k.setdefault('contacts', {}), 'auction': bot.k.setdefault('auction', {'bids': {}}),
        'mailer': bot.k.setdefault('mailer', {}),
    }


def profile(bot):
    """Botun profili (ilk istenince kurulur, her istekte güncellenir)."""
    if bot.profile is None:
        bot.profile = BotProfile(bot)
        import clan as KL
        me = KL.name(bot.profile)
        with KL.LOCK:
            k = next((c for c in KL.CLANS.values() if me in c['members']), None)
            if k is not None:
                KL._copy(k, bot.profile)          # iskelet klansız (clanId 0) kurulur: oyuncunun klanındaki bot yeniden başlatınca
                                                   # klansız kalıp emir dinlemiyor, başka klana başvuruyordu (canlı 2026-11-01)
    update(bot)
    return bot.profile


def update(bot):
    p = bot.profile
    if p is None:
        return
    k, d = bot.k, bot.value()
    pl, g = p.d['pilot'], p.d['gemi']
    last = getattr(bot, '_fmt_money', None)
    if last is not None:                  # oyun profilden harcadı ya da verdi (klan kurma, başvuru ücreti, klan ödemesi): bota geçer
        k['kredi'] = max(0, k['kredi'] + int(pl.get('credits', 0)) - last[0])
        k['uridyum'] = max(0, k['uridyum'] + int(pl.get('uridium', 0)) - last[1])
    k['rutbe'] = rank(bot)                      # panelin kadrosu da gösterir
    pl.update(userName=bot.name, factionId=bot.firma, level=k['seviye'], ep=k['ep'], honourPoints=k['onur'], credits=k['kredi'],
              uridium=k['uridyum'], dailyRank=k['rutbe'])
    bot._fmt_money = (k['kredi'], k['uridyum'])
    ship = k['gear']['gemi']
    p.d['ships']['1']['lootId'] = ship
    g.update(typeId=ship, speed=int(d['hiz']), hitMax=int(d['can']), shieldMax=int(d['kalkan']))
    if bot.body is None:
        g.update(hitPoints=int(d['can']), shield=int(d['kalkan']))
    else:
        g.update(hitPoints=int(bot.body.hp), shield=int(bot.body.shield))
    p.d['position'].update(mapId=bot.game_map, x=int(k.get('x') or 0), y=int(k.get('y') or 0))
    p.d['drones'] = [dict(lootId=loot, seviye=1, kimlik=i) for i, (loot, n) in
                      enumerate((l, n) for l, n in k['gear'].get('drone', {}).items() for _ in range(n))]


def npc_rank_points(tip):
    """Uzaylının rütbe puanı (ranks.json npc_puan, npc_kimlik ile; oyuncunun rutbe.npc_points'i gibi)."""
    import ranks as RT
    uid = K.NPC['types'].get(tip, {}).get('npc_kimlik')
    return RT.R['npc_points'].get(str(uid), {}).get('puan', 0)


def ship_rank_points(ship):
    """Yok edilen oyuncu gemisinin rütbe puanı (ranks.json gemi_puan; Goliath 20, Phoenix 1)."""
    import ranks as RT
    return RT.R['ship_points'].get(ship, {}).get('puan', 0)


def points(bot):
    """Rütbe puanı, oyuncununkiyle (rutbe.breakdown) aynı wiki formülü: EP/100.000 + onur/100 + oyuncu gemisi puanları x3 + seviye
    x100 + kayıttan beri gün x6 + gemi türü x1.000 + uzaylı puanları /2 + görev x100 - ölüm x4 (oyuncu bildirimi 2026-10-31: uzun süre
    oynayan botlar düşük rütbede kalıyordu; uzaylı ve oyuncu öldürmeleri tür puanı yerine adetle, gemi türü yerine gemi puanıyla, gün ve
    ölüm hiç sayılmıyordu)."""
    import ranks as RT
    F = RT.R['formula']
    k, i = bot.k, bot.k['stats']
    day = (bot.hour() - k['registered_at']) // 86400 if k.get('registered_at') else i.get('sure_sn', 0) // 86400   # eski kayıt: oynadığı süre
    return k['ep'] * F['ep'] + k['onur'] * F['onur'] + k['seviye'] * F['seviye'] + i.get('npc_points', 0) * F['npc'] \
        + i.get('player_points', 0) * F['player'] + i.get('gorev', 0) * F['gorev'] + max(0, day) * F['gun'] \
        + RT.R['ship_type'].get(k['gear']['gemi'], 0) * F['gemi'] + i.get('olum', 0) * F['death_by_enemy']


def rank(bot):
    """Görünen rütbe simgesi (dailyRank 1-21): eşiklere göre, şirketteki sırayla sınırlı (rutbe.sirket_rutbesi: Chief General 1 ...)."""
    import ranks as RT
    p = points(bot)
    threshold = RT.R['thresholds']
    r = max(1, min(len(threshold), sum(1 for e in threshold if p >= e)))
    s = RT.company_rank(bot.uid, bot.firma, p)
    return r if s is None else min(r, s)


# ------------------------------------------------------------------------------------------------------------ oturum ve kayıt
class BotSession:
    """Çevrimiçi botun sahte oturumu (topluluk.Kisi.oturum): oyunun ona gönderdiği mesajlar gelen()'e düşer."""
    social = None
    shop = None
    world = None

    def __init__(self, bot):
        self.bot = bot
        self.profile = bot.profile

    def send(self, msgs, note=None):
        for m in msgs or ():
            incoming(self.bot, m)


def incoming(bot, m):
    """Oyunun bota gönderdiği mesaj: davetler kararı bekler (tick)."""
    if m[0] == 'InvitationInitializationCommand' and m[1].get('candidateId') == bot.uid:
        bot.pending.append(('grup', m[1]['inviterId'], m[1].get('inviterName', ''), time.time()))
    elif m[0] in ('GroupInitializationCommand', 'GroupMemberInitializationCommand'):
        bot.pending.append(('group_formed', 0, '', 0.0))   # (bot davet etti, kabul edildi): liderin yanına (tick)


_PEOPLE = {'t': 0.0, 'd': {}, 'y': None}


def people(y):
    """uid -> topluluk.Kisi: paketin bütün botları (çevrimdışıların da profili; posta, rehber, klan onları bilir). 2 sn önbellek."""
    import community as TP
    now = time.time()
    if now - _PEOPLE['t'] < 2.0 and _PEOPLE['y'] is y:
        return _PEOPLE['d']
    out = {}
    for b in y.bots:
        if b.saved:                                    # henüz kayıt olmamış pilot sunucuda yok
            out[b.uid] = person(b, TP)
    _PEOPLE.update(t=now, d=out, y=y)
    return out


def person(bot, TP=None):
    if TP is None:
        import community as TP
    p = profile(bot)
    if not bot.online:
        return TP.Person(p, None)
    if bot.session is None:
        bot.session = BotSession(bot)
    return TP.Person(p, bot.session)


def register(y, chat=None):
    """Oyun sunucusunda: botlar topluluğa ve sohbete bağlanır."""
    import community as TP
    TP.BOTS = lambda: people(y)
    if chat is not None:
        chat.bot_hook = y.incoming_chat
        chat.bot_whisper_hook = y.incoming_whisper
        from . import moderation as MOD
        chat.block_hook = lambda user, path, lang: MOD.block(y, user, path, lang)
    y.chat = chat


def _refund(bot):
    """Oyunun bot profilinden harcadığı / verdiği para botun kaydına (klan kurma, başvuru ücreti, klan ödemesi)."""
    update(bot)


# ------------------------------------------------------------------------------------------------------------ kararlar
def tick(y, now):
    """Yöneticinin tick'inden (5 sn'de bir): çevrimiçi botların sosyal kararları. Her bot kendi aralığıyla (insan gibi gecikmeli)."""
    for b in y.bots:
        if not b.online or b.dead_until > now:
            continue
        if b.pending:
            try:
                invites(y, b, now)
            except Exception as e:            # bir davetin hatası öteki botların sosyal tikini durdurmasın
                y.log('   botlar: %s davet hatası: %r' % (b.name, e))
                b.pending = []
        if now < getattr(b, 'next_social', 0):
            continue
        b.next_social = now + b.r.uniform(20, 70) * (1.5 - b.o('sociability'))
        profile(b)
        try:
            handshake(y, b, now)
            if y.permission('arkadas'):
                friendship(y, b, now)
            if y.permission('klan'):
                clan_actions(y, b, now)
            if y.permission('auction'):
                auction(y, b, now)
            if y.permission('sohbet'):
                mail_tasks(y, b, now)
        except Exception as e:                # bir botun hatası ötekileri durdurmasın
            y.log('   botlar: %s sosyal hata: %r' % (b.name, e))


def handshake(y, b, now):
    """Aynı haritada aynı firmadan kasan biriyle birlikte avlanma (aynı uzaylıya ateş, birbirinin kutusunu bırakma, kısa laflaşma):
    ikisinin de hafızasına 'birlikte_avlandik'. Çoğunlukla daha önce tanıştığı biri seçilir; ilişki zamanla arkadaşlığa, gruba
    dönüşür. Önceden ilişki yalnız sohbet ve yardımla doğuyordu: 44 dakikada 499 pilottan 423'ü kimseyle tanışmamıştı."""
    if b.r.random() > 0.3 * (0.3 + b.o('sociability')) or b.target is None or b.target.name not in ('grinding', 'gorev'):
        return
    nearby = [o for o in y.on_map.get(b.game_map, ()) if o is not b and o.firma == b.firma and o.online and o.dead_until <= now]
    if not nearby:
        return
    acquaintances = [o for o in nearby if b.memory.relation(o.name, now) > 0]
    o = b.r.choice(acquaintances) if acquaintances and b.r.random() < 0.6 else b.r.choice(nearby)
    b.memory.event(o.name, 'hunted_together', now)
    o.memory.event(b.name, 'hunted_together', now)


def invites(y, b, now):
    import group as GR
    remaining = []
    for kind, uid, name, t in b.pending:
        if now - t < b.k['personality']['reaction_sec'] * b.r.uniform(3, 9):
            remaining.append((kind, uid, name, t))
            continue
        if kind == 'group_formed':
            _group_up(y, b, now)
            continue
        if kind != 'grup' or not y.permission('grup'):
            continue
        k = person(b)
        if decide_group(y, b, name, uid, now):
            GR.handle(k, 'InvitationAcceptRequest', {'inviterId': uid})
            b.memory.event(name, 'grup', now)
            b.event('joined_group', now, ad=name)
            from . import brain as B
            B.force(b, 'grup', pay=0.8, duration=1800, now=now)
        else:
            GR.handle(k, 'InvitationRejectRequest', {'inviterId': uid})
            b.event('group_declined', now, ad=name)
    b.pending = remaining


def _group_up(y, b, now):
    """Bot bir gruba girdi (kendi daveti kabul edildi): grubun insan oyuncusunun yanına gider (hedefler/group.py)."""
    from .goals import group as GG
    from . import brain as B
    k = GG.leader(b)
    if k is None or (b.target is not None and b.target.name == 'grup'):
        return
    b.memory.event(k.name, 'grup', now)
    b.event('joined_group', now, ad=k.name)
    B.force(b, 'grup', pay=0.8, duration=1800, now=now)


def decide_group(y, b, name, uid, now):
    """Grup davetini kabul eder mi: sosyallik, davet edene ilişki, seviye farkı, süren işi (görevin ortasında daha az), yorgunluk,
    firma (başka firmadan davet nadiren). Sohbette "inv me" dediyse (söz) kabul eder."""
    from . import interaction as IX
    if IX.has_promise(b, 'grup', name, now):
        return True
    import community as TP
    o = TP.find(uid=uid)
    lv = int(o.profile.d['pilot'].get('level', 1)) if o is not None else b.level
    diff = abs(lv - b.level)
    p = 0.25 + 0.5 * b.o('sociability') + 0.6 * b.memory.relation(name, now) - 0.04 * max(0, diff - 3) - 0.3 * b.mood['fatigue']
    if b.target is not None and b.target.name == 'gorev':
        p -= 0.15
    if o is not None and int(o.profile.d['pilot'].get('factionId', 0)) != b.firma:
        p -= 0.5
    return b.r.random() < max(0.03, min(0.95, p))


def friendship(y, b, now):
    import contacts as CT
    r = CT.save(b.profile)
    k = None
    for name in list(r.get('incoming', [])):
        k = k or person(b)
        rel = b.memory.relation(name, now)
        accept = b.r.random() < 0.2 + 0.5 * b.o('sociability') + rel
        CT.handle(k, 'ContactRequest', {'contactRequestType': CT.ACCEPT if accept else CT.REJECT, 'userName': name})
        b.event('friend_accept' if accept else 'friend_refuse', now, ad=name)
        if accept:
            b.memory.event(name, 'arkadas', now)
    if b.r.random() < 0.15 * b.o('sociability'):
        friendly = [a for a in b.memory.allies(0.25, now) if not CT._var(r.get('arkadas', []), a) and not CT._var(r.get('outgoing', []), a)]
        if friendly:
            name = b.r.choice(friendly)
            CT.handle(k or person(b), 'ContactRequest', {'contactRequestType': CT.CREATE, 'userName': name})
            b.event('friend_request', now, ad=name)


# ------------------------------------------------------------------------------------------------------------ klan
_PREFIX = ('Dark', 'Black', 'Red', 'Iron', 'Silent', 'Eternal', 'Royal', 'Shadow', 'Storm', 'Crimson', 'Galactic', 'Void', 'Star')
_PREFIX_TR = ('Kara', 'Kizil', 'Anadolu', 'Gok', 'Demir', 'Olumsuz', 'Turk', 'Yildiz')
_SUFFIX = ('Legion', 'Knights', 'Wolves', 'Eagles', 'Raiders', 'Hunters', 'Order', 'Empire', 'Brotherhood', 'Alliance', 'Reapers',
         'Guardians', 'Titans', 'Pirates')
_SUFFIX_TR = ('Kurtlar', 'Kartallar', 'Akincilar', 'Savascilar', 'Lejyon', 'Ordu', 'Sahinler', 'Korsanlar')


_ULKE = {'tr': 'Turkish', 'de': 'German', 'pl': 'Polish', 'ru': 'Russian', 'es': 'Spanish', 'fr': 'French', 'pt': 'Brazilian'}
_SINGLE = ('Bandidos', 'Nocturnos', 'Inferno', 'Phantoms', 'Outlaws', 'Spartans', 'Vikings', 'Immortals', 'Mercenaries', 'Renegades',
        'Elite', 'Legends', 'Nemesis', 'Valhalla', 'Ragnarok', 'Apocalypse', 'Chaos', 'Exodus', 'Oblivion', 'Hellfire')
_TAIL = ('Power', 'Army', 'Force', 'Elite', 'Warriors', 'Family', 'Team', 'Mafia')


def clan_name(b, r, tags=()):
    """Gerçek sunuculardaki gibi klan adı ve etiketi: ikili ad, tek sözcük (bazen süslü, küçük harf ya da sarılı), "The X",
    "Turkish Power"; etiket önce paketin gerçek etiket havuzundan (DOStats), değilse baş harfler, bazen süslü (Λ И Σ)."""
    lang = b.k['personality'].get('name_lang') or b.k['personality'].get('dil')
    tr = lang == 'tr' and r.random() < 0.7
    style = r.choices(('two_word', 'tek', 'the', 'ulke', 'lowercase', 'wrapped'), (35, 20, 10, 15 if lang in _ULKE else 0, 10, 10))[0]
    single = r.choice(_SINGLE + (_SUFFIX_TR if tr else _SUFFIX))
    if style == 'two_word':
        name = '%s %s' % (r.choice(_PREFIX_TR if tr else _PREFIX), r.choice(_SUFFIX_TR if tr else _SUFFIX))
    elif style == 'tek':
        name = NS._swap_letters(single.upper(), r) if r.random() < 0.5 else single
    elif style == 'the':
        name = 'The ' + single
    elif style == 'ulke':
        name = '%s %s' % (_ULKE[lang], r.choice(_TAIL))
    elif style == 'lowercase':
        name = single.lower() + r.choice(('', '', '.', ' clan', ' squad'))
    else:
        on, last = NS._sec(r, NS.WRAPS[:8])
        name = on + single + last
    if tags and r.random() < 0.7:
        return name, r.choice(list(tags))[:4]
    plain = re.sub(r'[^A-Za-z ]', '', NS.plain(name) if not name.isascii() else name).split() or [single]
    tag = (''.join(w[0] for w in plain).upper() if len(plain) > 1 else plain[0][:r.choice((3, 3, 4))].upper())
    tag += r.choice(('', '', str(r.randint(1, 99)), 'X', 'TR' if tr else 'EU')) if len(tag) < 3 else ''
    if r.random() < 0.3:
        tag = ''.join(r.choice(NS.UPPER_LOOKALIKES[c]) if c in NS.UPPER_LOOKALIKES and r.random() < 0.6 else c for c in tag)
    return name, tag[:4]


def clan_actions(y, b, now):
    import clan as KL
    p = profile(b)
    k = KL.clan_of(p)
    if k is None:
        b.k['klan'] = None
        leader_like = b.archetype == 'lider' or b.o('sociability') * b.o('ambition') > 0.5
        bot_clans = sum(1 for c in KL.CLANS.values() if c['lider'] in y.name_index)
        limit = max(1, sum(b.saved for b in y.bots) // int(y.setting('bots_per_clan', 12) or 12))
        if (y.permission('clan_found') and leader_like and b.level >= 5 and bot_clans < limit
                and b.k['kredi'] >= KL.FOUNDING_COST * 1.3 and b.r.random() < 0.3):
            r = random.Random('%s|klan|%d' % (b.name, len(KL.CLANS)))
            kl = KL.Clan(p, log=y.log)
            for _ in range(6):
                name, tag = clan_name(b, r, y.package.get('clan_tags') or ())
                if KL.Clan.valid_tag(tag) and not kl.taken(name, tag):      # [CM] gibi ayrılmış etiketler olmaz
                    break
            description = 'PvP' if b.o('aggression') > 0.6 else 'PvE & quests'
            out = kl.handle('FoundClanRequest', {'clanTag': tag, 'clanName': name, 'clanDescription': description})
            _refund(b)
            if out and out[0][1].get('success'):
                b.k['klan'] = out[0][1]['clanId']
                b.event('clan_founded', now, ad=name, etiket=tag)
                b.mood.it(morale=0.2)
            return
        if b.level >= 3 and b.r.random() < 0.25 * (0.4 + b.o('sociability')):
            candidate = pick_clan(y, b, list(KL.CLANS.values()))
            if candidate is not None and b.k['kredi'] >= KL.APPLICATION_FEE * 3:
                msg = application_text(b, candidate, now)
                KL.Clan(p, log=y.log).handle('ApplyClanRequest', {'clanId': candidate['id'], 'message': msg})
                _refund(b)
                b.event('applied_to_clan', now, klan=candidate['ad'])
        return
    if b.k.get('klan') != k['id']:
        b.k['klan'] = k['id']
        b.event('joined_clan', now, klan=k['ad'])
    pay_tax(b, k)
    kl = KL.Clan(p, log=y.log)
    if kl.right('hiremember', k):
        for bs in list(k.get('applications', [])):
            if not application_decision(y, b, k, bs, now):
                continue
            accept = application_decision(y, b, k, bs, now, final=True)
            kl.handle('ApplyAcceptRequest' if accept else 'ApplyDeclineRequest', {'applyId': bs['id']})
            b.event('application_accept' if accept else 'application_refuse', now, ad=bs.get('ad'))
            if accept and str(bs.get('ad', '')).lower() not in y.name_index:
                welcome_mail(y, b, k, bs.get('ad', ''))
    if y.permission('clan_diplomacy') and kl.right('diplo_start', k):
        diplomacy(y, b, k, kl, now)
    from . import clan_management as CMG
    CMG.manage(y, b, k, kl, now)                           # rütbeler, açıklama, duyuru, vergi, bütçe, ödeme, üyeler (klan_yonetim)
    if KL.clan_of(p) is not k:
        return                                           # liderliği bıraktı ya da klanı dağıttı
    if k['lider'] != b.name.lower() and b.o('loyalty') < 0.3 and b.r.random() < 0.004:
        kl.handle('LeaveClanRequest', {})
        b.k['klan'] = None
        b.event('left_clan', now, klan=k['ad'])


def clan_relation(a, b):
    """İki botun klanları arası ilişki (1 ittifak, 2 saldırmazlık, 3 savaş, 0 yok)."""
    import clan as KL
    return KL.clan_relation(int(a.k.get('klan') or 0), int(b.k.get('klan') or 0))


def pay_tax(b, k):
    """Üyenin son kazancından klanın vergisi kasaya (oyunda uzaylı ödülünden kesilir; klan.vergi)."""
    import clan as KL
    income = b.__dict__.pop('_clan_income', 0)
    pay = income * int(k.get('tax') or 0) // 100
    if pay <= 0:
        return
    b.k['kredi'] = max(0, b.k['kredi'] - pay)
    with KL.LOCK:
        k['treasury'] += pay
        k['income'] = int(k.get('income', 0)) + pay
        u = k['members'].get(b.name.lower())
        if u is not None:
            u['contrib_period'] = int(u.get('contrib_period', 0)) + pay     # haftalık ödemede en çok katkı verenlere (klan_yonetim)


def clan_company(c):
    """Klanın firması; bütün firmalara açık (0) klanda liderinki (clan.py sıralaması gibi)."""
    return int(c.get('firma') or 0) or int((c.get('members', {}).get(c.get('lider')) or {}).get('firma') or 0)


def _members(c):
    return {str(a).lower() for a in c.get('members', {})}


def diplomacy(y, b, k, kl, now):
    """Klan liderinin diplomasisi, oyunun klan diplomasisiyle (ittifak 1, saldırmazlık 2, savaş 3, barış isteği 0): gelen
    isteklere birkaç dakikada yanıt (senin klanınınkiler dahil), arada kendisi istek gönderir. Aynı firmadan klanlarla
    ittifak ya da saldırmazlık; başka firmadan, üyelerimizi öldürmüş ya da denk bir klana savaş (500.000 kredi kasadan; kasada
    yoksa lider yatırır); uzayan savaşta barış. Kişilik: sosyallik ittifakı, saldırganlık savaşı, temkin barışı sever."""
    import clan as KL
    incoming = [r for r in k.get('diplomacy_requests', []) if r['to'] == k['id']]
    if incoming and b.r.random() < 0.35:
        r = incoming[0]
        o = KL.CLANS.get(r['from_clan'])
        if o is not None:
            enemy = len(_members(o) & {a.lower() for a in b.memory.grudges(-0.3, now)})
            il = _clan_relation(y, b, o, now)[0]
            if r['tur'] == 0:                       # barış
                accept = b.r.random() < 0.25 + 0.5 * (1 - b.o('aggression')) - 0.1 * enemy
            else:
                # başka firmadan da olur, ama oyuncu klanından ve ona kötü bakmıyorsa: saldırmazlık hemen, ittifak için iyi ilişki
                same = (clan_company(o) == clan_company(k)
                        or bool(_humans(y, o)) and il >= (0.2 if r['tur'] == 1 else 0.0))
                accept = same and not enemy and b.r.random() < 0.3 + 0.5 * b.o('sociability') + (0.2 if r['tur'] == 2 else 0) + 0.4 * max(0, il)
            kl.handle('ClanEditDiploOfferRequest', {'diploId': r['id'], 'status': 'allow' if accept else 'deny'})
            b.event('diplomacy', now, form=r['tur'], klan=o['ad'], etiket=o.get('etiket', ''), kabul=accept, incoming=True)
        return
    # yeni girişim nadir (lider aşağı yukarı saatte bir düşünür); oyuncu klanıyla bir nedeni (yardım, kin) varsa iki kat sık
    has_reason = any(_clan_relation(y, b, c, now)[2] for c in list(KL.CLANS.values()) if c['id'] != k['id'] and _humans(y, c))
    if b.r.random() > (0.03 if has_reason else 0.015):
        return
    existing = {d['klan']: d for d in k.get('diplomacy', [])}
    last = b.k.setdefault('last_diplo', {})            # bir klana teklifi tekrarlamaz: reddedilen ya da yanıtsız kalan 6 saat dinlenir
    pending = {r['to'] for r in k.get('diplomacy_requests', [])} | {r['from_clan'] for r in k.get('diplomacy_requests', [])}
    wars = [d for d in existing.values() if d['tur'] == 3]
    for d in wars:                              # uzayan savaş: barış ister
        if d['klan'] not in pending and b.r.random() < 0.15 * (1.2 - b.o('aggression')):
            kl.handle('ClanNewDiplomacyRequest', {'diploClanID': d['klan'], 'diploForm': 0, 'desc': 'gg, peace?'})
            b.event('diplomacy', now, form=0, klan=d.get('ad', ''), incoming=False)
            return
    firma = clan_company(k) or b.firma
    enemies = {a.lower() for a in b.memory.grudges(-0.3, now)}
    candidates = []
    for c in list(KL.CLANS.values()):
        if c['id'] == k['id'] or c['id'] in existing or c['id'] in pending or not c.get('members'):
            continue
        if now - last.get(str(c['id']), 0) < 6 * 3600:
            continue
        cc = clan_company(c)
        if _humans(y, c):                         # oyuncu klanı: boyuna bakılmaz (tek kişilik klan da teklif alır), ilişki belirler
            il, grudge, reason = _clan_relation(y, b, c, now)
            if (grudge or il <= -0.3) and cc != firma and cc and b.o('aggression') > 0.4 and len(wars) < 2:
                candidates.append((0.8 + 0.3 * b.o('aggression') + 0.25 * min(3, grudge), 3, c))        # üyelerimizi öldürdü
            elif il >= 0.2 and (cc == firma or il >= 0.25):
                candidates.append((0.7 + 0.5 * il + b.r.uniform(0, 0.2), 1 if b.o('sociability') > 0.5 or il >= 0.5 else 2, c))   # yardım etti
            elif cc == firma and il > -0.3:
                candidates.append((0.4 * b.o('sociability') + 0.4 + b.r.uniform(0, 0.3), 1 if b.o('sociability') > 0.6 else 2, c))
            continue
        size = 1.0 - min(1.0, abs(len(c['members']) - len(k['members'])) / max(5.0, len(k['members'])))
        if cc == firma:
            kind = 1 if b.o('sociability') > 0.5 else 2
            candidates.append((0.4 * b.o('sociability') + 0.3 * size + b.r.uniform(0, 0.3), kind, c))
        elif cc and b.o('aggression') > 0.55 and len(wars) < 2:
            grudge = len(_members(c) & enemies)
            candidates.append((0.4 * b.o('aggression') + 0.3 * size + 0.25 * min(3, grudge) + b.r.uniform(0, 0.3), 3, c))
    if not candidates:
        return
    points, kind, c = max(candidates, key=lambda a: a[0])
    if points < 0.55:
        return
    if kind == 3 and k['treasury'] < KL.WAR_COST:
        missing = KL.WAR_COST - k['treasury']
        if b.k['kredi'] < missing * 1.5:
            return                                  # savaşı göze alacak parası yok
        b.earn(kredi=-missing)                       # lider kasaya yatırır
        with KL.LOCK:
            k['treasury'] += missing
        KL.changed(k)
    text = {1: 'alliance?', 2: 'nap?', 3: 'see you in space'}[kind]
    out = kl.handle('ClanNewDiplomacyRequest', {'diploClanID': c['id'], 'diploForm': kind, 'desc': text})
    if out and out[0][1].get('success'):
        last[str(c['id'])] = now
        b.event('diplomacy', now, form=kind, klan=c['ad'], etiket=c.get('etiket', ''), incoming=False)


def _humans(y, c):
    """Klandaki gerçek oyuncular (bot olmayan üyeler)."""
    return _members(c) - set(y.name_index)


def _clan_relation(y, b, c, now):
    """Botun bir klana ilişkisi (hafızasındaki üyeleriyle): (en iyi/en kötü ilişki, kinli üye sayısı, sebep var mı). Yardım eden
    ya da bizimkileri öldüren oyuncunun klanı diplomasi için 'sebepli' sayılır."""
    name = _members(c)
    relations = [b.memory.relation(a, now) for a in name if a in b.memory.d]
    grudge = len(name & {a.lower() for a in b.memory.grudges(-0.3, now)})
    il = max(relations) if relations and max(relations) >= 0.2 else min(relations) if relations and min(relations) <= -0.3 else 0.0
    return il, grudge, abs(il) >= 0.2 or bool(grudge)


def pick_clan(y, b, clans):
    """Botun kişiliğine en uyan klan: aynı firma, üyelerinin ortalama seviyesine yakın, PvP/PvE açıklaması, üye sayısı (kalabalık
    çeker ama dolu değil). Başvurusu bekleyen ya da reddedilmiş bot yeniden başvurmaz."""
    candidates = []
    for c in clans:
        if any(str(x.get('ad', '')).lower() == b.name.lower() for x in c.get('applications', [])):
            return None
        if c.get('firma') and c['firma'] != b.firma or b.name.lower() in [str(r).lower() for r in c.get('rejected', [])]:
            continue
        uy = list(c['members'].values())
        if len(uy) >= 50:
            continue
        avg = sum(int(u.get('seviye', 1)) for u in uy) / max(1, len(uy))
        pvp = 'pvp' in str(c.get('aciklama', '')).lower()
        affinity = 1.0 - abs(avg - b.level) / 12.0 + (0.3 if pvp == (b.o('aggression') > 0.6) else 0) + min(0.3, len(uy) / 30.0)
        affinity += 2.0 * _friend_member(b, c)[1]             # yardım ettiği, grup olduğu, arkadaş olduğu birinin klanı öne çıkar
        candidates.append((affinity + b.r.uniform(-0.2, 0.2), c))
    return max(candidates, key=lambda x: x[0])[1] if candidates else None


def _friend_member(b, c):
    """Klanın botun en yakın ilişkideki üyesi: (ad, ilişki 0..1); iyi (>= 0.2) bir ilişki yoksa (None, 0)."""
    en = (None, 0.0)
    for a, e in b.memory.d.items():
        if a in c.get('members', {}) and b.memory.relation(a) >= max(0.2, en[1]):
            en = (e.get('ad', a), b.memory.relation(a))
    return en


def application_text(b, c, now=None):
    """Klan başvurusunun yazısı (botun dilinde, kalıplardan): tanıdığı bir üye varsa nedeni (yardım etti ya da grup oldular),
    yoksa seviye ve oyun tarzı."""
    from . import speech as SPC
    name, il = _friend_member(b, c)
    lv, style = b.level, ('pvp' if b.o('aggression') > 0.6 else 'pve')
    f = dict(ad=name or '', klan=c.get('ad', ''), lv=lv, stil=style)
    if name:
        key = 'klan_basvuru_dost' if b.memory.count(name, 'helped_me') or b.memory.count(name, 'arkadas') else 'klan_basvuru_grup'
    else:
        key = 'klan_basvuru_pvp' if style == 'pvp' else 'klan_basvuru_pve'
    return SPC.template(b, key, **f) or 'lvl %d, %s' % (lv, style)


def application_decision(y, b, k, bs, now, final=False):
    """Bot lider başvuruya bakar mı (kesin=False: tepki süresi doldu mu) / kabul eder mi (kesin=True): seviye, ilişki. Oyuncunun
    başvurusu da böyle değerlendirilir (hemen değil, bir süre sonra)."""
    if not final:
        t = bs.get('_bot_seen')
        if t is None:
            bs['_bot_seen'] = now
            return False
        return now - t > b.r.uniform(30, 240)
    from . import interaction as IX
    if IX.has_promise(b, 'klan', bs.get('ad', ''), now):
        return True                                      # sohbette "başvur, kabul ederim" dedi
    import community as TP
    o = TP.find(name=bs.get('ad'))
    lv = int(o.profile.d['pilot'].get('level', 1)) if o is not None else 1
    uy = list(k['members'].values())
    avg = sum(int(u.get('seviye', 1)) for u in uy) / max(1, len(uy))
    p = 0.55 + 0.05 * (lv - avg + 3) + 0.6 * b.memory.relation(bs.get('ad', ''), now)
    return b.r.random() < max(0.1, min(0.97, p))


# ------------------------------------------------------------------------------------------------------------ müzayede
def lot_importance(b, lot):
    """Lotun bota önemi: 0 istemez; 1 sıradan (cephane, booster, kaynak; tüccar her lota); 2 donanım (lazer, jeneratör, dron); 3 takılı
    olmayan CPU ya da modül; 4 şimdikinden iyi gemi; 5 biriktirdiği gemi. Müzayedenin asıl değeri CPU'lar ve büyük gemiler:
    resmî oyunda günlerce uridyum biriktirmek yerine krediyle alınırlar, bu yüzden rekabet onlarda (kullanıcı isteği 2026-10-30)."""
    from . import extras as EX
    loot = lot['loot']
    if loot.startswith('ship_'):
        g, current = K.ITEMS['ships'].get(loot) or {}, K.ITEMS['ships'].get(b.k['gear']['gemi']) or {}
        # yalnız değerleri olan ve şimdikinden iyi olan (yalnız görünüm olan tasarımlar, "goliath_design_jade", gemi değildir)
        if not g.get('hp') or g['hp'] + 20000 * (g['laser'] + g['generators']) <= current.get('hp', 0) + 20000 * (
                current.get('laser', 0) + current.get('generators', 0)):
            return 0
        return 5 if b.k.get('savings') == loot else 4
    if lot.get('grup') in ('extra', 'module'):
        return 0 if EX.var(b, loot) else 3
    if loot in K.ITEMS['lasers'] or loot in K.ITEMS['shield_generators'] or loot in K.ITEMS['drones'] or lot.get('grup') == 'generator':
        return 2
    if loot.startswith('ammunition_') or lot.get('grup') in ('booster', 'special') or b.archetype == 'trader':
        return 1
    return 0


def auction(y, b, now):
    """Teklif: geçilen teklifini her sosyal turda savunur; yoksa ara sıra lotlara bakar, önemli olanı (CPU, iyi gemi) seçer. Tavan lotun
    anında alım değeri x önem, rekabet, hırs ve dönemin sonuna yakınlık; serbest kredinin hırsa göre bir payı. Sonuçları settle_bot
    verir (kazanırsa eşya, geçilirse kredi geri)."""
    import auction as MZ
    settle_bot(b, now)
    from . import loot as LT
    free = b.k['kredi'] - b.clan_savings()
    if free < 3 * MZ.D.get('min_bid', 10000):
        return
    candidates = []
    for lot in list(MZ.LOTS.values()):
        importance = lot_importance(b, lot)
        if importance:
            end = MZ.period_end(lot['tur'], now)
            own = b.k['auction']['bids'].get('%s|%s' % (lot['tur'], lot['loot']))
            candidates.append((importance, lot, end, int(own['bid']) if own and own.get('bitis') == end else 0))
    defend = [a for a in candidates if a[3] and a[3] <= (MZ.best(MZ.bids(a[1], a[2], skip=b.profile)) or (0,))[0]]
    if defend:
        importance, lot, end, old = max(defend, key=lambda a: a[0])           # geçildi: karşılık (oyuncu gibi pencereye geri döner)
    else:
        request = (0.6 if b.archetype == 'trader' else 0.2) * (0.5 + b.o('rekabet')) * (0.6 + 0.8 * b.o('ambition'))
        if not candidates or b.r.random() > request:
            return
        weight = [a[0] ** 3 * (1 + (a[1].get('price') or 0) / 50000.0) for a in candidates]      # önemli ve değerli lot öne
        importance, lot, end, old = b.r.choices(candidates, weights=weight)[0]
        if old:
            return                                   # zaten önde
    loot = lot['loot']
    key = '%s|%s' % (lot['tur'], loot)
    # lotun fiyatı anında alımın uridyumu (tamamı için): krediye çevrilir (eskiden kredi sanılıyordu, ucuz lotlara hiç teklif yoktu)
    value = int((lot.get('price') or 0) * LT.EXCHANGE_RATE) or 1000000
    remaining = max(0.0, (end - now) / MZ.SPAN[lot['tur']])
    ambition = b.o('ambition')
    cap = value * (0.35 + 0.4 * b.o('rekabet') + 0.25 * (1 - remaining)) * (0.7 + 0.3 * (b.archetype == 'trader'))
    if importance >= 3:
        cap *= 1 + ambition + 0.25 * (importance - 3)       # CPU ve gemi: hırslı bot anında alım değerinin iki katına kadar çıkar
    cap = min(cap, free * (0.5 + (0.45 * ambition if importance >= 3 else 0)))
    rival = MZ.best(MZ.bids(lot, end, skip=b.profile))
    current_time = rival[0] if rival else 0
    bid = max(MZ.D.get('min_bid', 10000), int(current_time * b.r.uniform(1.05, 1.25)) + MZ.D.get('increase', 1000))
    if bid > cap and current_time + MZ.D.get('increase', 1000) <= cap:
        bid = int(cap)                          # son kuruşuna kadar: tavanı geçmeden en yüksek
    if bid > cap or not b.pay('C', bid - old):
        return
    b.k['auction']['bids'][key] = {'bid': bid, 'bitis': end, 'time': int(now)}
    b.event('auction_bid', now, esya=loot, bid=bid)


def welcome_mail(y, b, k, name):
    from . import agent_tools as TL
    from . import speech as SPC
    text = SPC.template(b, 'posta_hosgeldin', klan=k['ad'], etiket=k['etiket'])
    if text:
        TL.call(y, b, 'send_mail', {'ad': name, 'konu': '[%s] %s' % (k['etiket'], k['ad']), 'metin': text})


def mail_tasks(y, b, now):
    """Gelen posta: insanın (paketin botları değil) okunmamış mesajı bir süre sonra okunur; içindeki istek (grup, klan, arkadaşlık,
    gel) karar motoruyla uygulanır ve postayla yanıt verilir (Gelişmiş kipte metni dil modeli yazar)."""
    import mail as PS
    p = profile(b)
    with p.lock:
        incoming = [r for r in p.d.get('mailer', {}).get('incoming', ()) if r.get('durum') == PS.UNREAD]
    for r in incoming:
        if r.get('tur') not in (PS.USER, PS.CLAN) or str(r.get('sender', '')).lower() in y.name_index or not r.get('sender'):
            with p.lock:
                r['durum'] = PS.READ                       # sistem, müzayede, bot postası: okunur geçilir
            continue
        seen = r.setdefault('_bot_seen', now)
        if now - seen < b.k['personality']['reaction_sec'] * 20 + b.r.uniform(30, 300):
            continue                                         # postaya hemen değil, birkaç dakika sonra bakar
        with p.lock:
            r['durum'] = PS.READ
        reply_mail(y, b, r, now)
        return                                               # tick başına bir posta


def mail_template(b, k):
    """Kararın postaya uygun kalıp metni (sohbet kalıpları postaya fazla kısa: "inv me", "no thx") ya da None."""
    from . import speech as SPC
    if not k:
        return None
    if k['intent'] == 'grup':
        return SPC.template(b, 'posta_grup_evet' if k['kabul'] else 'posta_grup_hayir')
    text = SPC.template(b, k['template'][0], **k['template'][1]) if k.get('template') else None
    return text and (text + ', ' + SPC.template(b, 'posta_cevap') if len(text.split()) < 4 else text)


def reply_mail(y, b, r, now):
    from . import agent_tools as TL
    from . import interaction as IX
    from . import speech as SPC
    import community as TP
    name = r['sender']
    o = TP.find(name=name)
    who = {'userId': name, 'id': str(r.get('sender_id', 0)),
           'factionId': str(o.profile.d['pilot'].get('factionId', 0)) if o is not None else '0'}
    text = '%s\n%s' % (r.get('konu', ''), r.get('metin', ''))
    intent, game_map = SPC.intent(text)
    k = IX.decision(y, b, intent, name, who, game_map, text, now, mailer=True) if intent in IX.INTENTS and intent != 'yardim' else None
    IX.apply(y, b, k)
    b.memory.event(name, 'sohbet', now)
    b.event('mail_received', now, ad=name)
    subject = 'Re: ' + str(r.get('konu', ''))[:46]
    if y.llm is not None and y.llm.ready and y.llm.mailer(y, b, r, k):
        return                                               # Gelişmiş: metni model yazar (llm._posta)
    body = mail_template(b, k) or SPC.template(b, 'posta_cevap')
    if body and (k is not None or b.r.random() < 0.85):           # karar verdiyse sessiz kalmaz
        TL.call(y, b, 'send_mail', {'ad': name, 'konu': subject, 'metin': body + ('' if len(body) >= 5 else ' :)')})


def settle_bot(b, now):
    """Biten dönemlerdeki bot teklifleri: en yüksekse eşya, değilse kredi geri."""
    import auction as MZ
    t = b.k['auction']['bids']
    for key, bid in list(t.items()):
        if bid['bitis'] + 120 > now:
            continue                                     # oyuncunun sonucu (Muzayede.settle) bot teklifini görsün diye biraz sonra
        kind, loot = key.split('|', 1)
        lot = MZ.LOTS.get((kind, loot))
        en = MZ.best(MZ.bids(lot, bid['bitis'])) if lot else None
        del t[key]
        if lot and en and en[3] == b.uid:
            g = b.k['auction'].setdefault('history', [])          # oyuncunun müzayede geçmişi de gösterir (Muzayede.history)
            g.insert(0, {'grup': lot['grup'], 'kim': b.uid, 'bid': int(bid['bid']), 'tarih': MZ.stamp(bid['bitis'] - MZ.SPAN[kind]),
                         'loot': loot, 'tur': kind, 'ad': b.name})
            del g[MZ.D['history_limit']:]
            if not b.add(loot, lot.get('adet', 1)):
                b.earn(kredi=int(bid['bid']) // 2)       # işine yaramayan: satar (yarı değer)
            b.event('auction_won', now, esya=loot)
            b.mood.it(morale=0.15)
        else:
            b.earn(kredi=int(bid['bid']))
