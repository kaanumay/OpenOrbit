"""Klan (yol haritası Aşama 10): istemcinin klan penceresi (UIClan). Sunucudaki oyuncuların klanları ortak (çoklu istemci, arkadaş
sunucusu): arama, başvuru, kabul/ret, üyeler, rütbeler, haberler, klan postası, vergi ve kasa, liderlik, diplomasi.

Klanın asıl kaydı bellekte (KLANLAR); her üyenin profilinde kopyası durur (kayıt yuvası kendi başına yetsin: yedek, dışa aktarma,
tek oyunculu). Oturum açılınca (Klan kurulurken: bagla) kopya asıl kayıtla birleşir: yenisi (surum) geçer; aynı kimlikli başka klan
(aynı tohumdan kayıtlar aynı kimlikle kuruyordu) yeni kimlik alır; üyelikten çıkarılan ya da silinen klanın kopyası düşer. Her
değişiklikte (degisti) bağlı üyelerin kopyaları yenilenir; açık pencerelere LoginInitClanCommand (istemci MyClanDataVo.UpdateAllInfo:
bütün liste) gider. Çok oyunculuda asıl kayıtlar save/klanlar.json'da da (configure: game.main): çevrimdışıyken çıkarılan üye, kabul
edilen başvuru, ödeme sonraki girişte uygulanır.
Üyeler pilot adıyla (küçük harf) tutulur: misafirin sunucudaki kimliği her katılmada başka (cok_oyunculu). Çevrimdışı üyenin
sayıları son bilinen hâli.
İstemci: üye listesi, başvurular, haberler, posta için ayrı istek yok (ClanMemberList/ClanApplyInfoList işleyicileri boş); pencere
LoginInitClanRequest ile hepsini alır. Ayrılan, çıkarılan ya da klanı silinen oyuncunun istemcisi kendi verisini silmez (LeaveClanCommand
yalnız bilgi penceresi, ClearClanCommand işleyicisi boş): klansız hâli LoginInitMyApplyCommand kurar. Başvurusu kabul edilen oyuncuya
JoinClanCommand (klan odası: ChatComponentSystem.RefreshMembershipRoom). Gemi etiketi ClanTagChangedCommand (userId'nin gemisi).
Diplomasi: ittifak (1) ve saldırmazlık (2) karşı klanın onayıyla (ClanEditDiploOfferRequest 'allow'/'deny'), savaş (3) hemen,
savaşı bitirme isteği (0) onayla. Gemilerin klan ilişkisi (ShipCreateCommand.clanDiplomacy) bakana göre (iliski; ortak_harita).
Vergi: üyenin uzaylı ödülünden (profil.gain) oranı kadar kredi kasaya.
"""
import copy, json, os, random, secrets, sys, threading, time

import settings as SET

FOUNDING_COST = 300000
COMPANY_CHANGE_COST = 5000           # şirket değiştirme (istemcide sabit: ClanSubViewCompany.InitUI, changeFaction_infoText)
X1 = {1: 1, 2: 5, 3: 9}       # firma -> X-1 haritası
RIGHTS = ['hiremember', 'firemember', 'editranks', 'news', 'roundmail', 'tax', 'payout', 'diplo_start', 'diplo_end',
          'diplo_war', 'battle_station_replace_module', 'battle_station_deflector', 'battle_station_build']      # + Ö5 (CBS)
MAX_TAX = 5               # resmî forum 127471, 127585: klan vergisi %0-%5
MAX_MEMBERS = 50                # resmî forum 127471, 127585 (11.2): klan en çok 50 oyuncu (istemci err_clan_full)
APPLICATION_FEE = 1500         # klana başvuru (forum 127471, 127585 11.4; darkorbitwiki guides/clan): kasaya girmez; kabulde geri
#                               verilmez, ret ya da geri almada iade
PAYOUT_FIRST, PAYOUT_INCREASE, PAYOUT_CAP = 5000000, 10000000, 250000000      # kasadan üyeye haftalık sınır (forum 127471): katıldığı hafta
#                               5 M, her hafta +10 M, en çok 250 M; üyelik başına (klandan çıkınca sıfırlanır)
WAR_COST, MAX_WARS, WAR_DAYS = 500000, 20, 10      # savaş ilanı (forum 127321): 500.000 kredi (klan kasasından:
#                               uyarlama), aynı anda en çok 20 ilan, 10 gün sonra kendiliğinden biter
COMPANY_CBS, COMPANY_NO_CBS = 10, -1          # şirket hiyerarşisi (forum 127469): kurulu KSİ'si olan klan saatte +10, olmayan -1
COOLDOWN_SEC = 48 * 3600        # klandan ayrılınca yeni klan kurma/katılma yok; klan adı/etiketi iki değişim arası (istemci: clan_user_2dayblock,
#                               err_clannameChange2Days; darkorbitwiki guides/clan: 48 saat)
PAYOUT_FEE = 10          # kasadan üyeye ödemede kendiliğinden silinen pay, yüzde (darkorbitwiki guides/clan)
DIPLO_RIGHTS = {0: 'diplo_end', 1: 'diplo_start', 2: 'diplo_start', 3: 'diplo_war'}
REQUESTS = {'LoginInitClanRequest', 'ClanFilterSearchRequest', 'ClanSearchNameTagRequest', 'ClanListRequest', 'ShowClanInfoRequest',
            'FoundClanRequest', 'ApplyClanRequest', 'DeleteClanApplyRequest', 'ClanApplyInfoListRequest', 'ApplyAcceptRequest',
            'ApplyDeclineRequest', 'ChangeClanDescriptionRequest', 'EditClanInfoRequest', 'ChangeClanFirmaRequest',
            'ChangeClanTaxRequest', 'ClanAddNewsRequest', 'ClanNewsListRequest', 'ClanMemberListRequest', 'ClanRankListRequest',
            'ClanNewRankRequest', 'ClanDeleteRankRequest', 'EditClanRanksRequest', 'DeleteMyRankRequest', 'EditClanMemberRequest',
            'ChangeClanLeaderRequest', 'DeleteClanMemberRequest', 'ClanMessageListRequest', 'ClanSendMessageRequest',
            'ClanSendAllMessageRequest', 'ClanDeleteMessageRequest', 'ClanDeleteAllMessageRequest', 'PayoutClanRequest',
            'LeaveClanRequest', 'DeleteClanRequest', 'DelClanRequest', 'ClanReportAdminRequest', 'ClanNewDiplomacyRequest',
            'ClanDeleteDiploRequest', 'ClanDeleteOpenDiploRequest', 'ClanEditDiploOfferRequest', 'ClanBattleStationInfoRequest',
            'BattleStationHistoryListRequest', 'CompanyHierarchyRequest'}

LOCK = threading.RLock()
CLANS = {}                  # klan kimliği -> asıl kayıt
DELETED = {}                  # silinen klanın kimliği -> anahtarı (bağlanan üyenin eski kopyası geri gelmesin)
FILE = None                  # çok oyunculuda asıl kayıtların dosyası (configure)
BOT_NAME_N = 0                  # bot ad kaydının (ad_kaydi.py) bu kayıtlara uygulanan son sırası


def mod(_cls, **f):
    f['_'] = _cls
    return f


def stamp(t=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))


def err(key='empty', **args):
    from shop import stack_msg
    return stack_msg(key, **args)


def _res(key):
    from shop import res
    return res(key)


def text(key, **args):
    """BaseKey'i olmayan metin (istemcinin kaynağındaki anahtar): ham "XXX" + XXX'in yerelleştirilmiş değeri (magaza.RES_YERINE gibi)."""
    from shop import BASEKEY, ARG_KEYS
    if key in BASEKEY:
        return err(key, **args)
    lst = [mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS[k], value=str(v)) for k, v in args.items()]
    lst.append(mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS['XXX'], value=_res(key)))
    return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX', argsList=lst)


NEWS_KEYS = {'found': 'clan_found', 'left': 'success_clan_left', 'leader': 'info_clan_changeLeader',
             'war': 'diplo_declare_war_info', 'war2': 'diplo_declare_war_info2', 'peace': 'diplo_stop_war_msg',
             'peace2': 'diplo_stop_war_msg2'}      # istemci haberi dil anahtarından kurar (%username%, %clanname%)


def name(p):
    return str(p.d['pilot'].get('userName', '')).strip().lower()


# ------------------------------------------------------------ asıl kayıtlar
def configure(path):
    """Çok oyunculu sunucu (game.main): asıl kayıtlar dosyadan; değiştikçe yazılır."""
    global FILE, BOT_NAME_N
    FILE = path
    try:
        with open(path, encoding='utf8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    with LOCK:
        for k in (d.get('klanlar') or {}).values():
            if isinstance(k, dict) and 'uyeler' in k:
                CLANS.setdefault(int(k['id']), k)
        DELETED.update({int(i): a for i, a in (d.get('silinen') or {}).items()})
        BOT_NAME_N = max(BOT_NAME_N, int(d.get('bot_name_log') or 0))
    import name_log as NL
    NL.apply_clans(sys.modules[__name__])        # panelde değişen ya da silinen bot adları (oyun kapalıyken)


def save():
    if not FILE:
        return
    with LOCK:
        text = json.dumps({'klanlar': {str(i): k for i, k in CLANS.items()}, 'silinen': {str(i): a for i, a in DELETED.items()},
                           'bot_name_log': BOT_NAME_N}, ensure_ascii=False)
        tmp = FILE + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf8') as fh:
                fh.write(text)
            os.replace(tmp, FILE)
        except OSError:
            pass


def _new_id():
    while True:
        cid = random.randint(100000, 999999)
        if cid not in CLANS and cid not in DELETED:
            return cid


def _no():
    return random.randint(1, 2 ** 31 - 1)


def _move(k, p):
    """Tek kişilik klanın kaydı (önceki sürüm) -> üyeli kayıt."""
    if 'uyeler' in k:
        return
    me = name(p)
    for f, v in (('etiket', ''), ('ad', ''), ('aciklama', ''), ('kurulus', stamp()), ('alim', 0), ('alim_bilgi', 0), ('vergi', 0),
                 ('kasa', 0), ('kasa_kaydi', []), ('ts', ''), ('firma', int(p.d['pilot'].get('factionId', 0))), ('haberler', []),
                 ('mesajlar', []), ('rutbeler', []), ('sira', 1)):
        k.setdefault(f, v)
    k['uyeler'] = {me: {'ad': p.d['pilot'].get('userName', ''), 'uid': p.user_id, 'rutbe': k.pop('my_rank', 0),
                        'katilma': k['kurulus']}}
    k.update(lider=me, anahtar=secrets.token_hex(8), surum=1, applications=[], rejected=[], diplomasi=[], diplomacy_requests=[], income=0)


def profiles():
    """Sunucudaki oyuncuların profilleri (ad -> profil)."""
    import community as TP
    return {name(x.profile): x.profile for x in TP.all_().values()}


def people():
    import community as TP
    return {name(x.profile): x for x in TP.all_().values()}


def _copy(k, p):
    """Profildeki kopya ve gemi etiketi asıl kayda göre (k None: klansız) -> etiket ya da kimlik değişti mi."""
    pl = p.d['pilot']
    with p.lock:
        old = (pl.get('clanId', 0), pl.get('clanTag', ''))
        p.d['klan'] = copy.deepcopy(k) if k else None
        pl.update(clanId=k['id'] if k else 0, clanTag=k['etiket'] if k else '')
        p.dirty = True
        return old != (pl['clanId'], pl['clanTag'])


def bind(p, log=print):
    """Oturum açılırken: profildeki kopya asıl kayıtla birleşir (bkz. modül notu). Önce panelde değişen ya da silinen bot adları
    kopyaya ve asıl kayıtlara uygulanır (ad_kaydi): silinen paketin botları klandan çıkar, adı değişen yeni adla görünür."""
    import name_log as NL
    NL.apply_profile(p)
    NL.apply_clans(sys.modules[__name__])
    me = name(p)
    with LOCK:
        s = p.d.get('klan')
        if s:
            if 'uyeler' not in s:
                with p.lock:
                    _move(s, p)
            cid, key = int(s['id']), s.get('anahtar')
            m = next((c for c in CLANS.values() if c.get('anahtar') == key), None)
            if m is None and key in DELETED.values():
                pass
            elif m is None and cid not in CLANS:
                m = CLANS[cid] = copy.deepcopy(s)
            elif m is None:                                         # başka klan aynı kimlikle (aynı tohumdan kayıtlar)
                nid = _new_id()
                log('   klan kimliği çakışıyor: [%s] %s %d -> %d' % (s['etiket'], s['ad'], cid, nid))
                m = CLANS[nid] = dict(copy.deepcopy(s), id=nid)
            elif int(s.get('surum', 0)) > int(m.get('surum', 0)):     # asıl kayıt eski (dosyası yok): profildeki yeni
                mid = m['id']
                m.clear()
                m.update(copy.deepcopy(s), id=mid)
            if m is not None and me not in m['uyeler']:
                m = None
        else:
            m = next((k for k in CLANS.values() if me in k['uyeler']), None)   # çevrimdışıyken kabul edilen başvuru
        if m is not None:
            u = m['uyeler'][me]
            u.update(live(p))
            pay = int(u.pop('pending', 0) or 0)
        _copy(m, p)
        if m is not None:
            if pay:
                p.gain(kredi=pay, neden='clan_hl_auszahlungen', detay=m['ad'])
            save()
    refund_fee(p)
    return m


def changed(k, extra=()):
    """Asıl kayıt değişti: sürüm artar, bağlı üyelerin (ve ek profillerin) kopyaları yenilenir -> etiketi değişen profiller."""
    with LOCK:
        k['surum'] = int(k.get('surum', 0)) + 1
        target = {a: x for a, x in profiles().items() if a in k['uyeler']}
        for x in extra:                                     # üyeliği yeni biten ya da başlayan
            s = x.d.get('klan')
            if name(x) in k['uyeler'] or (s and s.get('id') == k['id']):
                target[name(x)] = x
        out = [x for a, x in target.items() if _copy(k if a in k['uyeler'] and CLANS.get(k['id']) is k else None, x)]
        save()
    return out


def clan_of(p):
    """Profilin klanının asıl kaydı ya da None."""
    cid = int(p.d['pilot'].get('clanId', 0) or 0)
    with LOCK:
        k = CLANS.get(cid)
        return k if k is not None and name(p) in k['uyeler'] else None


def right(p, right):
    """Oyuncunun klandaki hakkı (HAKLAR; lider hepsine sahip)."""
    with LOCK:
        k = clan_of(p)
        if not k:
            return False
        if k['lider'] == name(p):
            return True
        rid = k['uyeler'][name(p)].get('rutbe', 0)
        return any(r['id'] == rid and right in r['haklar'] for r in k['rutbeler'])


def relation(p, q):
    """p'nin gözünden q'nun gemisinin klan ilişkisi (ClanRelationModule.type): 1 ittifak, 2 saldırmazlık, 3 savaş, 0 yok."""
    return clan_relation(int(p.d['pilot'].get('clanId', 0) or 0), int(q.d['pilot'].get('clanId', 0) or 0))


def clan_relation(a, b):
    """a klanının gözünden b klanı (iliski gibi)."""
    if not a or not b or a == b:
        return 0
    with LOCK:
        k = CLANS.get(a)
        return next((d['tur'] for d in (k or {}).get('diplomasi', ()) if d['klan'] == b and not is_war_over(d)), 0)


def tax(p, credits):
    """Uzaylı ödülünden klanın vergisi (profil.gain: kilit dışında) -> kasaya giden kredi."""
    if credits <= 0 or not p.d['pilot'].get('clanId'):
        return 0
    with LOCK:
        k = clan_of(p)
        if not k or not k.get('vergi'):
            return 0
        tax = credits * int(k['vergi']) // 100
        if tax:
            k['kasa'] += tax
            k['income'] = int(k.get('income', 0)) + tax
            for x in profiles().values():               # kopyaların kasası (tek oyunculuda tek kayıt profil)
                s = x.d.get('klan')
                if s and s.get('id') == k['id']:
                    s.update(kasa=k['kasa'], income=k['income'])
            if p.d.get('klan') and p.d['klan'].get('id') == k['id']:
                p.d['klan'].update(kasa=k['kasa'], income=k['income'])
        return tax


BANNED = ('admin', 'moderator', 'gamemaster', 'support', 'bigpoint', 'darkorbit', 'communitymanager', 'nazi', 'hitler', 'nigger',
           'orospu', 'sikis', 'amcik', 'fuck', 'porn')


def is_banned(text):
    """Oyun Kuralları 7 (resmî forum 131990): personel adına benzeyen, ırkçı, cinsiyetçi ya da müstehcen ad, klan adı ve etiketi.
    Küçük harf, ayırıcılar atılır, 0/1/3/4/5/7 harfe çevrilir; kısa bir alt dizge listesi (uyarlama)."""
    t = str(text or '').lower().translate(str.maketrans('013457', 'oleast'))
    t = ''.join(c for c in t if c.isalnum())
    return any(w in t for w in BANNED) or t in ('gm', 'mod', 'cm')


def name_changed(old, new_):
    """Pilot adı değişti (game.rename): üyelik, liderlik ve başvurular yeni adla."""
    old, new_lower = str(old).strip().lower(), str(new_).strip().lower()
    if old == new_lower:
        return
    with LOCK:
        for k in CLANS.values():
            if old in k['uyeler']:
                u = k['uyeler'].pop(old)
                k['uyeler'][new_lower] = dict(u, ad=new_)
                if k['lider'] == old:
                    k['lider'] = new_lower
            for b in k['applications']:
                if b['ad'] == old:
                    b.update(ad=new_lower, isim=new_)
            k['rejected'] = [new_lower if r == old else r for r in k['rejected']]
            if new_lower in k['uyeler']:
                changed(k)                      # başvurular ve retler de güncellendikten sonra (üyelerin kopyası eski kalıyordu)
        save()


def is_member_name(name, own=''):
    """Bir klanda (çevrimdışı) üyenin adı mı: yeniden adlandırma o üyenin kaydını ezmesin."""
    name, own = str(name).strip().lower(), str(own).strip().lower()
    with LOCK:
        return name != own and any(name in k['uyeler'] for k in CLANS.values())


def live(p):
    """Üyenin listedeki sayıları (çevrimiçiyken güncellenir)."""
    import ranks as RT
    pl, c = p.d['pilot'], p.d.get('counters') or {}
    return {'ad': pl.get('userName', ''), 'uid': p.user_id, 'firma': int(pl.get('factionId', 0)), 'ep': int(pl.get('ep', 0)),
            'onur': int(pl.get('honourPoints', 0)), 'seviye': int(pl.get('level', 1)), 'rank_no': int(pl.get('dailyRank', 1) or 1),
            'puan': RT.user_score(p), 'harita': int(p.d['position'].get('mapId', 1)),
            'gemi': sum((c.get('oyuncu') or {}).values()), 'uzayli': sum((c.get('npc') or {}).values())}


def players(p=None):
    """Sunucudaki bilinen oyuncular (ad -> sayılar): bağlı olanlar canlı, klanların çevrimdışı üyeleri son bilinen hâliyle."""
    prof = profiles()
    if p is not None:
        prof.setdefault(name(p), p)
    out = {}
    with LOCK:
        for k in CLANS.values():
            for a, u in k['uyeler'].items():
                if a not in prof:
                    out[a] = dict(u)
    for a, x in prof.items():
        out[a] = live(x)
        with LOCK:
            k = clan_of(x)
            if k:
                k['uyeler'][a].update(out[a])
    return out


def points(k, who=None):
    who = who if who is not None else players()
    return sum(int((who.get(a) or u).get('puan', 0)) for a, u in k['uyeler'].items())


def payout_limit(u, now=None):
    """Üyeye bu hafta kasadan verilebilecek kalan (forum 127471; istemci clan_message_error_payout_userMax_reached)."""
    now = now or time.time()
    try:
        start = time.mktime(time.strptime(u.get('katilma', ''), '%Y-%m-%d %H:%M:%S'))
    except (ValueError, OverflowError):
        start = now
    weeks = max(0, int((now - start) // (7 * 86400)))
    paid = int((u.get('payment_week') or {}).get(time.strftime('%G-%V', time.localtime(now)), 0))
    return max(0, min(PAYOUT_CAP, PAYOUT_FIRST + PAYOUT_INCREASE * weeks) - paid)


def is_war_over(d, now=None):
    return d['tur'] == 3 and d.get('bitis') and (now or time.time()) >= d['bitis']


def clear_wars(now=None):
    """Süresi (10 gün) dolan savaşlar iki klandan da kalkar -> değişen klanlar."""
    out = []
    with LOCK:
        for k in CLANS.values():
            n = len(k['diplomasi'])
            k['diplomasi'] = [d for d in k['diplomasi'] if not is_war_over(d, now)]
            if len(k['diplomasi']) != n:
                out.append(k)
    return out


def refund_fee(p):
    """Başvuru ücreti: yanıt bekleyenler dururken; kabul edilen klanınki geri verilmez, reddedilen, geri alınan ya da klanı silinen
    başvurununki iade (çevrimdışıyken reddedilen sonraki girişte) -> iade edilen kredi."""
    fees, me, back = p.d.get('clan_application_fees') or {}, name(p), 0
    with LOCK:
        for cid, n in list(fees.items()):
            c = CLANS.get(int(cid))
            if c is not None and any(b['ad'] == me for b in c['applications']):
                continue
            del fees[cid]
            p.dirty = True
            if c is None or me not in c['uyeler']:
                back += int(n)
    if back:
        p.gain(kredi=back, neden='clan_hl_clan_bewerbung')
    return back


def stations(k, p):
    """Klanın kurulu Klan Savaş İstasyonları (cbs.py; tek oyunculuda oyuncunun klanınınkiler) -> ['Ad (harita)', …]."""
    import cbs as CBS
    import map_links as H
    h = CBS.shared()
    if h is None and int(p.d['pilot'].get('clanId', 0) or 0) != k['id']:
        return []
    out = []
    for aid, a in sorted(((h or p).d.get('cbs') or {}).get('asteroitler', {}).items()):
        if a.get('durum') != 'kurulu' or a.get('sahip') == 'rakip' or (h is not None and a.get('klan') != k['id']):
            continue
        ast = CBS.ASTEROIDS.get(int(aid)) or {}
        out.append('%s (%s)' % (ast.get('ad', aid), H.name(ast.get('harita', 0))))
    return out


def company_points(k, p, now=None):
    """Şirket hiyerarşisi puanı: son güncellemeden beri geçen her tam saat için kurulu KSİ varsa +10, yoksa -1 (en az 0)."""
    now = now or time.time()
    with LOCK:
        last = k.setdefault('company_time', now)
        hours = int((now - last) // 3600)
        if hours > 0:
            k['company_points'] = max(0, int(k.get('company_points', 0)) + hours * (COMPANY_CBS if stations(k, p) else COMPANY_NO_CBS))
            k['company_time'] = last + hours * 3600
        return int(k.get('company_points', 0))


def ranking(who=None):
    """Klanlar puanına (üyelerin en iyi kullanıcı puanı toplamı) göre (büyükten) -> [(klan, puan)]."""
    who = who if who is not None else players()
    with LOCK:
        lst = [(k, points(k, who)) for k in CLANS.values()]
    return sorted(lst, key=lambda item: (-item[1], item[0]['id']))



RESERVED_TAGS = ('cm',)          # sohbet moderatörlerinin etiketi [CM] (bot/moderasyon.py): hiçbir klan alamaz


def is_reserved(tag):
    """Ayrılmış etiket mi: büyük/küçük harf ve süslü benzerleri dahil ("Cm", "ϹΜ", "ᴄᴍ")."""
    import unicodedata
    from bot.name_style import plain
    t = ''.join(c for c in unicodedata.normalize('NFKC', str(tag)) if c.isalnum()).lower()
    return t in RESERVED_TAGS or plain(tag) in RESERVED_TAGS or _similar(t) in RESERVED_TAGS


def _similar(t):
    """Latin harfe benzeyen Yunan/Kiril harfleri (Ϲ Μ С М ...)."""
    return t.translate(str.maketrans({'ϲ': 'c', 'σ': 'c', 'ς': 'c', 'с': 'c', 'ᴄ': 'c', 'μ': 'm', 'м': 'm', 'ᴍ': 'm'}))

class Clan:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None
        self.on_change = None             # klana girdi/çıktı, etiket: sohbet odaları, gemi etiketi (sosyal.py)
        self.cbs = None                   # Clan Battle Station (Ö5; cbs.py): istasyon sekmesi ve günlüğü
        bind(profile, log)

    @property
    def k(self):
        s = self.p.d.get('klan')
        if not s:
            return None
        with LOCK:
            m = CLANS.get(int(s.get('id', 0)))
            if m is None or m.get('anahtar') != s.get('anahtar') or self.me not in m['uyeler']:
                m = bind(self.p, self.log)
            return m

    @property
    def me(self):
        return name(self.p)

    def right(self, right, k=None):
        k = k or self.k
        if not k:
            return False
        if k['lider'] == self.me:
            return True
        rid = k['uyeler'].get(self.me, {}).get('rutbe', 0)
        return any(r['id'] == rid and right in r['haklar'] for r in k['rutbeler'])

    def blocked(self):
        """Klandan ayrıldıktan sonra BEKLEME_SN dolmadan yeni klan kurulamaz, klana katılınamaz."""
        return SET.get('klan_bekleme') and time.time() < self.p.d.get('clan_left_at', 0) + COOLDOWN_SEC

    def member_name(self, k, uid):
        """Üyenin adı (istemci kimlikle sorar) ya da None."""
        return next((a for a, u in k['uyeler'].items() if int(u.get('uid', 0)) == int(uid or 0)), None)

    # -------------------------------------------------------- komutlar
    def company(self):
        """Firma bilgisi: sunucudaki oyuncuların firmasınınkiler (üye sayısı, gemi ve uzaylı, EP, onur, rütbe puanı)."""
        fac = int(self.p.d['pilot'].get('factionId', 0))
        lst = [u for u in players(self.p).values() if int(u.get('firma', 0)) == fac]
        return mod('CompanyDateInfoCommand', members=len(lst), ships=sum(int(u.get('gemi', 0)) for u in lst),
                   EP=sum(int(u.get('ep', 0)) for u in lst), aliens=sum(int(u.get('uzayli', 0)) for u in lst),
                   hounr=sum(int(u.get('onur', 0)) for u in lst), ranking=sum(int(u.get('puan', 0)) for u in lst))

    def hierarchy(self):
        """CompanyHierarchyRequest: firmaların klan sıralaması (sunucudaki klanlar; kayıttaki başka oyuncuların klanları yok, H79)."""
        k, pl = self.k, self.p.d['pilot']
        fac = int(pl.get('factionId', 0))
        own = mod('CompanyHierarchyRankingModule', clanId=-1, rank=0, clanName='', leaderName='', cbsNamesAndLocations='',
                  rankingPoints=0)
        lists = {1: [], 2: [], 3: []}
        with LOCK:                                          # forum 127469: KSİ şirket puanı; firma başına ilk 9, kendi klanı ayrıca
            for c, pts in sorted(((c, company_points(c, self.p)) for c in CLANS.values()), key=lambda cp: (-cp[1], cp[0]['id'])):
                f = int(c['firma'] or 0) or int((c['uyeler'].get(c['lider']) or {}).get('firma') or 0)    # bütün firmalar: liderinki
                if f not in lists:
                    continue
                row = mod('CompanyHierarchyRankingModule', clanId=c['id'], rank=len(lists[f]) + 1, clanName=c['ad'],
                          leaderName=(c['uyeler'].get(c['lider']) or {}).get('ad', ''),
                          cbsNamesAndLocations=', '.join(stations(c, self.p)), rankingPoints=pts)
                lists[f].append(row)
                if k is not None and c is k:
                    own = row
            lists = {f: rows[:9] for f, rows in lists.items()}
        return ('CompanyHierarchyInitializationCommand', dict(mmoRanking=lists[1], eicRanking=lists[2], vruRanking=lists[3],
                                                                ownRanking=own, ownFaction=mod('FactionModule', faction=fac)))

    def info(self, k=None, order=None):
        k = k or self.k
        with LOCK:
            if order is None:
                order = ranking()
            no, pts = next(((i + 1, s) for i, (c, s) in enumerate(order) if c is k), (0, 0))
            lead = k['uyeler'].get(k['lider']) or {}
            return mod('ClanInfoCommand', recruitionInfo=k['alim_bilgi'], taxRate=k['vergi'], clanId=k['id'],
                       recruitionStatus=k['alim'], clanCredits=k['kasa'], teamspeakAdd=k['ts'], clanLeaderName=lead.get('ad', ''),
                       clanName=k['ad'], clanRank=no, clanIcon='', clanLeaderId=int(lead.get('uid', 0)), memberCount=len(k['uyeler']),
                       clanTag=k['etiket'], clanDesc=k['aciklama'], company=k['firma'], insertDate=k['kurulus'], ranking=pts)

    def member_cmd(self, u):
        from map_links import name as map_name
        return mod('ClanMemberInfoCommand', faction=int(u.get('firma', 0)), mapName=map_name(int(u.get('harita', 1))),
                   name=u.get('ad', ''), maxPayout=payout_limit(u), insertDate=u.get('katilma', ''), ep=int(u.get('ep', 0)),
                   userId=int(u.get('uid', 0)), ranksId=int(u.get('rutbe', 0)), rank=int(u.get('rank_no', 1)))

    def members(self, k=None):
        k = k or self.k
        if not k:
            return []
        players(self.p)                                   # bağlı üyelerin sayıları
        with LOCK:
            order = sorted(k['uyeler'].items(), key=lambda uid_member: (uid_member[0] != k['lider'], uid_member[1].get('katilma', ''), uid_member[0]))
            return [self.member_cmd(u) for _, u in order]

    def member(self):
        return self.member_cmd(dict(self.k['uyeler'].get(self.me) or {}, **live(self.p)))

    def rank_cmd(self, r):
        return mod('ClanRankInfoCommand', rankId=r['id'], clanId=self.k['id'], rankName=r['ad'], rights=list(r['haklar']))

    def ranks(self):
        return [self.rank_cmd(r) for r in self.k['rutbeler']]

    def news_cmd(self, n):
        """İstemci (MyClanDataVo.AddNews): type "user" ise context düz metin; değilse context bir dil anahtarı (%username%,
        %clanname% değiştirilir). Kuruluş haberi istemcinin "clan_found" metni (canlı deneme 2026-10-17: ikisi de boş çıkıyordu)."""
        k = self.k
        kind, text = ('user', n['metin']) if n['tur'] in ('news', 'user') else (n['tur'], NEWS_KEYS.get(n['tur'], n['metin']))
        return mod('ClanNewsInfoCommand', type=kind, clanNewsId=n['id'], userName=n['ad'], clanId=k['id'], context=text,
                   userId=n['kim'], clanName=n.get('clan_name') or k['ad'], insertDate=n['tarih'])

    def mail_cmd(self, m):
        return mod('ClanMessageInfoCommand', insertDate=m['tarih'], subject=m['konu'], mailText=m['metin'], type=m.get('tur', 0),
                   sendUserId=m['kim'], textIncName='', subjectIncName='', sendUserName=m['ad'], messageId=m['id'],
                   textParams='', subjectParams='')

    def mails(self, k=None):
        """Oyuncunun gördüğü klan postası: herkese gidenler ve ona gelenler (sildikleri hariç)."""
        k = k or self.k
        me = self.me
        return [m for m in k['mesajlar'] if m.get('recipient') in (None, me) and me not in m.get('deleted_by', ())]

    def tax_cmd(self):
        return mod('ClanTaxInfoCommand', income=int(self.k.get('income', 0)),
                   logList=[mod('ClanTaxLogCommand', **x) for x in self.k['kasa_kaydi'][:50]])

    def apply_cmd(self, b):
        u = players().get(b['ad']) or {}
        return mod('ClanApplyInfoCommand', userName=b['isim'], EP=int(u.get('ep', 0)), applyDesc=b['metin'], level=int(u.get('seviye', 1)),
                   clanApplyId=b['id'], insertDate=b['tarih'], company=int(u.get('firma', 0)))

    def diplo_req_cmd(self, r, k):
        other = r['to'] if r['kimden'] == k['id'] else r['kimden']
        o = CLANS.get(other) or {}
        return mod('ClanDiploReqInfoCommand', desc=r['metin'], fromClanId=r['kimden'], insertDate=r['tarih'], cdrId=r['id'],
                   clanName=o.get('ad', r.get('ad', '')), toClanId=r['to'], diploType=r['tur'])

    def diplo_cmd(self, d):
        o = CLANS.get(d['klan']) or {}
        left = max(0, -int(-(d['bitis'] - time.time()) // 86400)) if d.get('bitis') else 0
        return mod('ClanDiploInfoCommand', clanName=o.get('ad', d.get('ad', '')), daysLeft=left, cdiId=d['id'], diploType=d['tur'],
                   fromClanId=d['kimden'], insertDate=d['tarih'], desc=d['metin'])

    def all_info(self):
        k = self.k
        with LOCK:
            incoming = [self.diplo_req_cmd(r, k) for r in k['diplomacy_requests'] if r['to'] == k['id']]
            outgoing = [self.diplo_req_cmd(r, k) for r in k['diplomacy_requests'] if r['kimden'] == k['id']]
            apps = [self.apply_cmd(b) for b in k['applications']] if self.right('hiremember', k) else []
            return mod('ClanAllInfoCommand', clanMemberInfoCommandList=self.members(k), clanTaxInfoCommand=self.tax_cmd(),
                       clanDiploReqInfoCommands=incoming, myClanDiploReqInfoCommands=outgoing,
                       clanApplyInfoListCommand=mod('ClanApplyInfoListCommand', applyClanInfoCommandList=apps),
                       clanMessageInfoCommands=[self.mail_cmd(m) for m in self.mails(k)],
                       clanDiploInfoCommands=[self.diplo_cmd(d) for d in k['diplomasi']],
                       clanRankInfoCommands=self.ranks(), clanInfoCommand=self.info(k),
                       clanNewsInfoCommands=[self.news_cmd(n) for n in k['haberler']], companyDateInfoCommand=self.company())

    def tag_cmd(self):
        pl = self.p.d['pilot']
        return ('ClanTagChangedCommand', {'clanTag': pl.get('clanTag', ''), 'clanId': pl.get('clanId', 0), 'userId': self.p.user_id})

    def no_clan(self):
        """Klansız pencere: başvurduğu klanlar ve reddedenler."""
        me = self.me
        with LOCK:
            order = ranking()
            applied = [self.info(c, order) for c in CLANS.values() if any(b['ad'] == me for b in c['applications'])]
            rejected = [c['id'] for c in CLANS.values() if me in c['rejected']]
        return ('LoginInitMyApplyCommand', {'applyClanList': applied, 'foundCost': FOUNDING_COST, 'companyDateInfoCommand': self.company(),
                                            'rejectApplyClanList': rejected})

    def nametag(self, k=None):
        k = k or self.k
        return mod('ClanNameTagInfoCommand', tag=k['etiket'], id=k['id'], name=k['ad'])

    # -------------------------------------------------------- yardımcılar
    def next_id(self, k=None):
        k = k or self.k
        with LOCK:
            k['sira'] = k.get('sira', 1) + 1
            return k['sira']

    def add_news(self, kind, text, k=None, who=None, other=''):
        k = k or self.k
        pl = (who or self.p).d['pilot']
        with LOCK:
            n = {'id': self.next_id(k), 'tur': kind, 'ad': pl.get('userName', ''), 'kim': (who or self.p).user_id, 'metin': text[:500],
                 'tarih': stamp()}
            if other:
                n['clan_name'] = other                         # %clanname%: diplomasideki öteki klan
            k['haberler'].insert(0, n)
            del k['haberler'][50:]
        return n

    def changed(self, k=None, push=True, extra=()):
        """Asıl kayıt değişti: kopyalar, etiketi değişenlerin gemisi ve sohbeti, açık pencereler (öteki üyeler)."""
        k = k or self.k
        moved = changed(k, (self.p,) + tuple(extra))
        for x in moved:
            self.tag_changed(x)
        if push:
            self.push(k)

    def tag_changed(self, x):
        """x'in klanı ya da etiketi değişti: kendi istemcisine etiket, sohbetine oda ve etiket."""
        if x is self.p:
            if self.on_change:
                self.on_change()
            return
        s = (people().get(name(x)) or None)
        o = getattr(s.session, 'social', None) if s is not None and s.session is not None else None
        if o is not None:
            s.send([o.clan.tag_cmd()], 'klan etiketi')
            o.clan_changed()

    def push(self, k, extra=None, skip_self=True):
        """Klanın bağlı öteki üyelerine (açık pencere) güncel klan; extra: ad -> ek mesajlar."""
        for a, s in people().items():
            if (skip_self and a == self.me) or a not in k['uyeler'] or s.session is None:
                continue
            o = getattr(s.session, 'social', None)
            if o is None or o.clan.k is not k:
                continue
            s.send([('LoginInitClanCommand', {'clanAllInfoCommand': o.clan.all_info()})] + list((extra or {}).get(a, ())), 'klan')

    def push_clan(self, cid):
        k = CLANS.get(cid)
        if k:
            self.push(k, skip_self=False)

    def kick_out(self, a):
        """Klandan düşen (çıkarılan, klanı silinen) bağlı oyuncunun istemcisi: klansız pencere, gemi etiketi, sohbet odası."""
        s = people().get(a)
        if s is None:
            return
        _copy(None, s.profile)
        o = getattr(s.session, 'social', None) if s.session is not None else None
        if o is not None:
            s.send([o.clan.no_clan(), o.clan.tag_cmd()], 'klandan çıktı')
            o.clan_changed()

    @staticmethod
    def valid_tag(tag):
        return 1 <= len(tag) <= 4 and all(c.isalnum() or c in '-_.!?*+' for c in tag) and not is_reserved(tag)

    @staticmethod
    def taken(name, tag, skip=None):
        """Ad ya da etiket başka klanda -> metin anahtarı ya da None."""
        with LOCK:
            for c in CLANS.values():
                if c is skip:
                    continue
                if c['ad'].strip().lower() == name.strip().lower():
                    return 'clan_errmsg_clanname_exists'
                if c['etiket'].strip().lower() == tag.strip().lower():
                    return 'err_clantag_exist'
        return None

    # -------------------------------------------------------- istekler
    def handle(self, name, f):
        k = self.k
        if name == 'CompanyHierarchyRequest':
            return [self.hierarchy()]
        if name == 'ChangeClanFirmaRequest':           # oturum yanıttan sonra oyuncuyu yeni firmanın X-1'ine götürür (game.py)
            return self.switch_company(f)[0]
        if name == 'LoginInitClanRequest':
            return [('LoginInitClanCommand', {'clanAllInfoCommand': self.all_info()})] if k else [self.no_clan()]
        if name == 'ClanFilterSearchRequest':
            return [self.search(f)]
        if name == 'ClanSearchNameTagRequest':
            q = str(f.get('lookup', '')).strip().lower()
            with LOCK:
                hit = [self.nametag(c) for c in CLANS.values() if q and (q in c['etiket'].lower() or q in c['ad'].lower())]
            return [('ClanSearchNameTagCommand', {'lookup': f.get('lookup', ''), 'infoCommandList': hit[:50]})]
        if name == 'ClanListRequest':
            with LOCK:
                lst = [self.nametag(c) for c, _ in ranking() if c is not k]
            return [('ClanListCommand', {'type': int(f.get('type') or 0), 'infoCommandList': lst})]
        if name == 'ShowClanInfoRequest':
            c = CLANS.get(int(f.get('clanId') or 0))
            return [('ShowClanInfoCommand', {'success': c is not None, 'errorMsg': err() if c else err('err_clan_noClanID'),
                                             'clanInfoCommand': self.info(c) if c else None})]
        if name == 'FoundClanRequest':
            return self.found(f)
        if name in ('ApplyClanRequest', 'DeleteClanApplyRequest'):
            return self.apply(name, f)
        if name == 'ClanApplyInfoListRequest':
            with LOCK:
                apps = [self.apply_cmd(b) for b in k['applications']] if k and self.right('hiremember', k) else []
            return [('ClanApplyInfoListCommand', {'applyClanInfoCommandList': apps})]
        if name == 'ClanBattleStationInfoRequest' and self.cbs:
            return [self.cbs.clan_info()]
        if name == 'BattleStationHistoryListRequest' and self.cbs:
            return [self.cbs.history(int(f.get('startIndex') or 0))]
        if name == 'ClanBattleStationInfoRequest':
            return [('ClanBattleStationInfoCommand', {'battleStationOverviewInfoCommands': [], 'stationOwnedLongestTime': '',
                                                      'maxStationAtOnce': 0, 'destroyedStations': 0, 'stations': 0, 'allStations': 0})]
        if name == 'BattleStationHistoryListRequest':
            return [('BattleStationHistoryListCommand', {'commandList': [], 'startIndex': int(f.get('startIndex') or 0), 'total': 0})]
        if not k:
            return self.no_clan_reply(name, f)
        return self.member_request(name, f)

    def search(self, f):
        """ClanFilterSearchRequest: sunucudaki klanlar (ad/etiket, firma; sıralamaya göre; start/range sayfası)."""
        q = str(f.get('lookup', '')).strip().lower()
        fac = int(f.get('factionType') or 0)
        with LOCK:
            order = ranking()
            lst = [c for c, _ in order if (not q or q in c['etiket'].lower() or q in c['ad'].lower())
                   and (not fac or not c['firma'] or fac == c['firma'])]
            if f.get('desc'):
                lst.reverse()
            start, n = max(0, int(f.get('start') or 0)), int(f.get('range') or 20) or 20
            return ('ClanFilterSearchInfoCommand', {'list': [self.info(c, order) for c in lst[start:start + n]], 'count': len(lst)})

    def no_clan_reply(self, name, f):
        """Klansızken gelen üye istekleri: istemcinin "klanda değilsin" metni."""
        e = err('err_clan_user_not_in_clan')
        replies = {'LeaveClanRequest': ('LeaveClanCommand', {'errorMsg': e, 'success': False}),
                   'DeleteClanRequest': ('DeleteClanCommand', {'success': False, 'errorMsg': e}),
                   'DelClanRequest': ('DelClanCommand', {'success': False, 'errorMsg': e}),
                   'ApplyAcceptRequest': ('ApplyAcceptCommand', {'command': None, 'errorMsg': e, 'success': False,
                                                                 'applyId': int(f.get('applyId') or 0)}),
                   'ApplyDeclineRequest': ('ApplyDeclineCommand', {'errorMsg': e, 'success': False, 'applyId': int(f.get('applyId') or 0)})}
        r = replies.get(name)
        self.log('   klan isteği klansız: %s' % name)
        return [r] if r else []

    def found(self, f):
        tag, cname = str(f.get('clanTag', '')).strip(), str(f.get('clanName', '')).strip()
        desc = str(f.get('clanDescription', ''))
        reply = lambda ok, key='empty', cid=0, **a: [('FoundClanCommand', {'success': ok, 'clanId': cid, 'errorMsg': err(key, **a)})]
        if self.k:
            return reply(False, 'err_user_in_clan')
        if self.blocked():
            return reply(False, 'clan_user_2dayblock')
        if not tag or not cname:
            return reply(False, 'clan_errmsg_required', _NAME_=_res('clan_name' if not cname else 'clan_tag'))
        if len(cname) > 50:
            return reply(False, 'clan_errmsg_to_long')
        if len(desc) > 2000:
            return reply(False, 'clan_errmsg_desc_to_long')
        if not self.valid_tag(tag):
            return reply(False, 'clan_errmsg_clantag_not_allowed')
        if is_banned(cname) or is_banned(tag):                  # Oyun Kuralları 7 (resmî forum 131990)
            return reply(False, 'clan_name_not_allowed')
        busy = self.taken(cname, tag)
        if busy:
            return [('FoundClanCommand', {'success': False, 'clanId': 0, 'errorMsg': text(busy)})]
        import inventory as INV
        if INV.spend(self.p, {'currency_credits': FOUNDING_COST}, 'nav_sub1_clan_found_long') is None:
            return reply(False, 'clan_errmsg_user_not_enough_money')
        me = self.me
        with LOCK:
            cid = _new_id()
            k = CLANS[cid] = {'id': cid, 'etiket': tag, 'ad': cname, 'aciklama': desc, 'kurulus': stamp(), 'alim': 0,
                                'alim_bilgi': 0, 'vergi': 0, 'kasa': 0, 'kasa_kaydi': [], 'ts': '',
                                'firma': int(self.p.d['pilot'].get('factionId', 0)), 'haberler': [], 'mesajlar': [],
                                'rutbeler': [], 'sira': 1, 'lider': me, 'anahtar': secrets.token_hex(8), 'surum': 0,
                                'uyeler': {me: dict(live(self.p), rutbe=0, katilma=stamp())}, 'applications': [], 'rejected': [],
                                'diplomasi': [], 'diplomacy_requests': [], 'income': 0}
            for c in CLANS.values():                      # başka klanlara başvuruları düşer
                c['applications'] = [b for b in c['applications'] if b['ad'] != me]
            self.add_news('found', cname, k)
        self.changed(k, push=False)
        self.log('   klan kuruldu: [%s] %s (%d)' % (tag, cname, cid))
        msgs = reply(True, 'empty', cid) + [('JoinClanCommand', {'clanAllInfoCommand': self.all_info()}), self.tag_cmd()]
        return msgs + (self.m.money_msgs() if self.m else [])

    def apply(self, name, f):
        """ApplyClanRequest {clanId, message}: başvuru klanın yetkili üyelerinin penceresine; DeleteClanApplyRequest {applyId}: geri alma."""
        me, cid = self.me, int(f.get('clanId') or 0)
        if name == 'DeleteClanApplyRequest':
            aid = int(f.get('applyId') or 0)
            with LOCK:
                hit = [(c, b) for c in CLANS.values() for b in c['applications'] if b['ad'] == me and b['id'] == aid]
                for c, b in hit:
                    c['applications'].remove(b)
            for c, _ in hit:
                self.changed(c, extra=())
            refund_fee(self.p)
            return [('DeleteClanApplyCommand', {'success': bool(hit), 'applyId': aid, 'errorMsg': err() if hit else err('err_clan_apply')})] + \
                (self.m.money_msgs() if self.m else [])
        reply = lambda ok, key, aid=0: [('ApplyClanCommand', {'applyId': aid, 'credits': APPLICATION_FEE if ok else 0, 'errorMsg': err(key),
                                                              'clanId': cid, 'success': ok})]
        if self.k:
            return reply(False, 'err_user_in_clan')
        if self.blocked():
            return reply(False, 'clan_user_2dayblock')
        with LOCK:
            c = CLANS.get(cid)
            if c is None:
                return reply(False, 'err_select_clan')
            if any(b['ad'] == me for b in c['applications']):
                return reply(False, 'err_clan_apply')
            if c['firma'] and int(c['firma']) != int(self.p.d['pilot'].get('factionId', 0)):     # firmaya bağlı klan
                return reply(False, 'err_clan_other_fractionID')
            if len(c['uyeler']) >= MAX_MEMBERS:
                return reply(False, 'err_clan_full')
        import inventory as INV
        if INV.spend(self.p, {'currency_credits': APPLICATION_FEE}, 'clan_hl_clan_bewerbung') is None:
            return reply(False, 'clan_errmsg_user_not_enough_money')
        with LOCK:
            self.p.d.setdefault('clan_application_fees', {})[str(cid)] = APPLICATION_FEE
            self.p.dirty = True
            b = {'id': _no(), 'ad': me, 'isim': self.p.d['pilot'].get('userName', ''), 'metin': str(f.get('message', ''))[:1000],
                 'tarih': stamp()}
            c['applications'].append(b)
            if me in c['rejected']:
                c['rejected'].remove(me)
        self.changed(c)
        self.log('   klan başvurusu: %s -> [%s] %s' % (b['isim'], c['etiket'], c['ad']))
        return reply(True, 'err_clan_apply_send', b['id']) + (self.m.money_msgs() if self.m else [])

    def switch_company(self, f):
        """ChangeClanFirmaRequest: oyuncunun şirket değiştirmesi (klan penceresinin COMPANY sekmesi, klanlı ya da klansız; istemci
        ClanSubViewCompany "Switch company"). Önce klanın firması değişiyordu, klansızken yanıt yoktu: şirket değişmiyordu
        (kullanıcı 2026-10-24). Kurallar istemcinin metinlerinden: yalnız X-1'de (err_changing_company_tips), açık görev yokken
        (görevlerin hedefleri firmaya göre: err_clan_firmchange_closeQuest), 5.000 U; yeni firma onurun yarısını tanır, eksi onur
        kalır (changeFactionText). İstemci başarıda kendi firmasını ve firma sohbet odasını yeniler (UpdateChangeClanFirmaCommand);
        oyuncuyu yeni firmanın X-1 istasyonuna oturum götürür. Tek üyeli klanın firması liderle birlikte değişir.
        -> (mesajlar, gidilecek X-1 ya da None)"""
        pl = self.p.d['pilot']
        old, firm = int(pl.get('factionId', 0)), int(f.get('firma') or 0)

        def reply(ok, key):
            return [('ChangeClanFirmaCommand', {'success': ok, 'firm': int(pl.get('factionId', 0)), 'companyDateInfoCommand': self.company(),
                                                'errorMsg': err(key)})]
        if firm not in X1 or firm == old:
            return reply(False, 'firmChange_notavailable'), None
        if int(self.p.d['position'].get('mapId', 0)) not in X1.values():
            return reply(False, 'err_changing_company_tips'), None
        if (self.p.d.get('gorevler') or {}).get('aktif'):
            return reply(False, 'err_clan_firmchange_closeQuest'), None
        import inventory as INV
        if INV.spend(self.p, {'currency_uridium': COMPANY_CHANGE_COST}, 'changeFirm') is None:
            return reply(False, 'not_enough_uridium'), None
        with self.p.lock:
            hon = int(pl.get('honourPoints', 0))
            pl.update(factionId=firm, honourPoints=hon // 2 if hon > 0 else hon)
            self.p.dirty = True
        k = self.k
        if k:
            with LOCK:
                k['uyeler'][self.me]['firma'] = firm
                if int(k.get('firma') or 0) == old and len(k['uyeler']) <= 1:
                    k['firma'] = firm
            self.changed(k)
        self.log('   şirket değişti: %d -> %d (onur %d -> %d)' % (old, firm, hon, pl['honourPoints']))
        return reply(True, 'firmChange_done'), X1[firm]

    def member_request(self, name, f):
        k = self.k
        if name == 'ChangeClanDescriptionRequest':
            desc = str(f.get('desc', ''))
            if k['lider'] != self.me:
                return [('ChangeClanDescriptionCommand', {'success': False, 'errorMsg': err('err_clan_no_access'), 'desc': k['aciklama']})]
            ok = len(desc) <= 2000
            if ok:
                with LOCK:
                    k['aciklama'] = desc
                self.changed(k)
            return [('ChangeClanDescriptionCommand', {'success': ok, 'errorMsg': err('success_clan_change_descr' if ok else
                                                                                     'clan_errmsg_desc_to_long'), 'desc': k['aciklama']})]
        if name == 'EditClanInfoRequest':
            return self.edit_info(f)
        if name == 'ChangeClanTaxRequest':
            tax = int(f.get('tax') or 0)
            if not self.right('tax', k):
                return [('ChangeClanTaxCommand', {'tax': k['vergi'], 'success': False, 'errorMsg': err('err_clan_noRights')})]
            ok = 0 <= tax <= MAX_TAX
            if ok:
                with LOCK:
                    k['vergi'] = tax
                self.changed(k)
            return [('ChangeClanTaxCommand', {'tax': k['vergi'], 'success': ok,
                                              'errorMsg': err('clan_changed_tax' if ok else 'clan_err_wrong_value')})]
        if name == 'ClanAddNewsRequest':
            text = str(f.get('newsMessage', '')).strip()
            if not self.right('news', k):
                return [('ClanAddNewsCommand', {'errorMsg': err('err_clan_noRights'), 'success': False, 'clanNewsInfoCommand': None})]
            if not text:
                return [('ClanAddNewsCommand', {'errorMsg': err('clan_errmsg_required', _NAME_=_res('diplo_hl_bewerbungstext')),
                                                'success': False, 'clanNewsInfoCommand': None})]
            n = self.add_news('news', text, k)
            self.changed(k)
            return [('ClanAddNewsCommand', {'errorMsg': err(), 'success': True, 'clanNewsInfoCommand': self.news_cmd(n)})]
        if name == 'ClanNewsListRequest':
            return [('ClanNewsListCommand', {'newsList': [self.news_cmd(n) for n in k['haberler']]})]
        if name == 'ClanMemberListRequest':
            return [('ClanMemberListCommand', {'memberList': self.members(k)})]
        if name in ('ApplyAcceptRequest', 'ApplyDeclineRequest'):
            return self.answer(name, f)
        if name in ('ClanRankListRequest', 'ClanNewRankRequest', 'ClanDeleteRankRequest', 'EditClanRanksRequest',
                    'DeleteMyRankRequest', 'EditClanMemberRequest'):
            return self.rank_request(name, f)
        if name == 'ChangeClanLeaderRequest':
            return self.change_leader(f)
        if name == 'DeleteClanMemberRequest':
            return self.remove_member(f)
        if name in ('ClanMessageListRequest', 'ClanSendMessageRequest', 'ClanSendAllMessageRequest', 'ClanDeleteMessageRequest',
                    'ClanDeleteAllMessageRequest'):
            return self.mail_request(name, f)
        if name == 'PayoutClanRequest':
            return self.payout(f)
        if name == 'LeaveClanRequest':
            return self.leave()
        if name in ('DeleteClanRequest', 'DelClanRequest'):
            return self.delete(name)
        if name == 'ClanReportAdminRequest':
            return [('ClanReportAdminCommand', {'success': True, 'errorMsg': err('clan_message_report_to_admin')})]
        if name in ('ClanNewDiplomacyRequest', 'ClanDeleteDiploRequest', 'ClanDeleteOpenDiploRequest', 'ClanEditDiploOfferRequest'):
            return self.diplo(name, f)
        return []

    def edit_info(self, f):
        """EditClanInfoRequest (liderin bilgi formu): ad, etiket, TS, alım ve firma bağlılığı (newFraction: 0 bütün firmalar, 1-3 firma;
        yok sayılıyordu, bağlılık değişmiyordu: kullanıcı 2026-10-24)."""
        k = self.k
        tag, cname = str(f.get('clanTag', k['etiket'])).strip(), str(f.get('clanName', k['ad'])).strip()
        firma = int(f.get('newFraction', k['firma']) or 0)
        reply = lambda ok, key='empty', **a: [('EditClanInfoCommand', {'success': ok, 'clanId': k['id'], 'clanInfoCommand': self.info(),
                                                                       'errorMsg': err(key, **a)})]
        if k['lider'] != self.me:
            return reply(False, 'err_clan_no_access')
        if not tag or not cname:
            return reply(False, 'clan_errmsg_required', _NAME_=_res('clan_name' if not cname else 'clan_tag'))
        if not self.valid_tag(tag):
            return reply(False, 'clan_errmsg_clantag_not_allowed')
        if len(cname) > 50:
            return reply(False, 'clan_errmsg_to_long')
        renamed = (tag, cname) != (k['etiket'], k['ad'])
        if renamed and (is_banned(cname) or is_banned(tag)):
            return reply(False, 'clan_name_not_allowed')
        if renamed and SET.get('klan_bekleme') and time.time() < k.get('name_changed_at', 0) + COOLDOWN_SEC:
            return reply(False, 'err_clannameChange2Days')
        busy = self.taken(cname, tag, skip=k)
        if busy:
            return [('EditClanInfoCommand', {'success': False, 'clanId': k['id'], 'clanInfoCommand': self.info(), 'errorMsg': text(busy)})]
        with LOCK:
            if renamed:
                k['name_changed_at'] = time.time()
            k.update(etiket=tag, ad=cname, ts=str(f.get('clanTS', k['ts']))[:100], alim=int(f.get('recruitingStatus') or 0),
                     alim_bilgi=int(f.get('recuritingInfo') or 0), firma=firma if firma in (0,) + tuple(X1) else k['firma'])
        self.changed(k)
        return reply(True) + [self.tag_cmd()]

    def answer(self, name, f):
        """Başvuruya yanıt (hiremember): kabulde oyuncu üye olur (bağlıysa JoinClanCommand, etiket, klan odası), retle başvurduğu
        pencerede reddedenler arasında görünür."""
        k, aid = self.k, int(f.get('applyId') or 0)
        accept = name == 'ApplyAcceptRequest'
        cmd = 'ApplyAcceptCommand' if accept else 'ApplyDeclineCommand'

        def reply(ok, e):
            r = {'errorMsg': e, 'success': ok, 'applyId': aid}
            if accept:
                r['command'] = mod('ClanMemberListCommand', memberList=self.members(k))
            return [(cmd, r)]
        if not self.right('hiremember', k):
            return reply(False, err('err_clan_noRights'))
        with LOCK:
            b = next((x for x in k['applications'] if x['id'] == aid), None)
            if b is None:
                return reply(False, err('err_select_clan'))
            k['applications'].remove(b)
            other = next((c for c in CLANS.values() if b['ad'] in c['uyeler']), None)
            if accept and other is not None:
                return reply(False, err('clan_user_in_clan'))
            if accept and len(k['uyeler']) >= MAX_MEMBERS:
                k['applications'].append(b)
                return reply(False, err('err_clan_full'))
            if accept:
                u = players().get(b['ad']) or {'ad': b['isim']}
                k['uyeler'][b['ad']] = dict(u, rutbe=0, katilma=stamp())
                for c in CLANS.values():
                    c['applications'] = [x for x in c['applications'] if x['ad'] != b['ad']]
                    if b['ad'] in c['rejected'] and c is k:
                        c['rejected'].remove(b['ad'])
            elif b['ad'] not in k['rejected']:
                k['rejected'].append(b['ad'])
        s = people().get(b['ad'])
        self.changed(k, extra=(s.profile,) if s is not None and accept else ())
        self.log('   klan başvurusu %s: %s -> [%s]' % ('kabul' if accept else 'ret', b['isim'], k['etiket']))
        if s is not None:                                 # bağlı başvuranın ücreti: retle hemen iade (çevrimdışı: sonraki giriş)
            refund_fee(s.profile)
        o = getattr(s.session, 'social', None) if s is not None and s.session is not None else None
        if o is not None:
            s.send([('JoinClanCommand', {'clanAllInfoCommand': o.clan.all_info()}), o.clan.tag_cmd()] if accept else [o.clan.no_clan()],
                     'klan başvurusu')
            if not accept and o.clan.m:
                s.send(o.clan.m.money_msgs(), 'başvuru ücreti')
        return reply(True, err() if accept else err('err_clan_decline'))

    def change_leader(self, f):
        k, uid = self.k, int(f.get('newLeaderId') or 0)
        a = self.member_name(k, uid)
        reply = lambda ok, e: [('ChangeClanLeaderCommand', {'success': ok, 'stack': e, 'command': self.info(), 'newLeaderId': uid})]
        if k['lider'] != self.me:
            return reply(False, err('err_clan_noRights'))
        if a is None:
            return reply(False, err('err_clan_user_not_in_clan'))
        if a == self.me:
            return reply(False, err('err_clan_you_are_leader'))
        with LOCK:
            k['lider'] = a
            n = self.add_news('leader', '', k)
            n.update(ad=k['uyeler'][a].get('ad', ''), kim=uid)
        self.changed(k)
        self.log('   klan lideri: %s' % k['uyeler'][a].get('ad'))
        return reply(True, err('success_clan_changeLeader'))

    def remove_member(self, f):
        k, uid = self.k, int(f.get('removeUserID') or 0)
        a = self.member_name(k, uid)
        reply = lambda ok, e: [('DeleteClanMemberCommand', {'removeUserID': uid, 'success': ok, 'errorMsg': e})]
        if not self.right('firemember', k):
            return reply(False, err('err_clan_noRights'))
        if a is None:
            return reply(False, err('err_clan_user_not_in_clan'))
        if a == k['lider'] or a == self.me:
            return reply(False, err('err_clan_you_are_leader' if a == k['lider'] else 'err_clan_noRights'))
        with LOCK:
            u = k['uyeler'].pop(a)
        extra = self.cbs.member_left(k, a) if self.cbs else []      # forum 127469: modülleri envanterine döner
        self.changed(k)
        self.kick_out(a)
        self.log('   klandan çıkarıldı: %s' % u.get('ad'))
        return reply(True, err('clan_remove_member')) + extra

    def leave(self):
        k = self.k
        if k['lider'] == self.me:
            return [('LeaveClanCommand', {'errorMsg': text('err_clan_noleave'), 'success': False})]
        with LOCK:
            k['uyeler'].pop(self.me, None)
            self.add_news('left', '', k)
        extra = self.cbs.member_left(k, self.me) if self.cbs else []
        self.p.d['clan_left_at'] = time.time()            # 48 saat yeni klan kurma/katılma yok (blocked)
        self.p.dirty = True
        self.changed(k)                                   # kendi kopyası düşer (üye değil)
        self.log('   klandan ayrıldı: [%s]' % k['etiket'])
        return [('LeaveClanCommand', {'errorMsg': text('clan_leave_clan_success'), 'success': True}), self.no_clan(), self.tag_cmd()] + extra

    def rank_request(self, name, f):
        k = self.k
        lst = lambda: mod('ClanRankListCommand', ranks=self.ranks())
        if name == 'ClanRankListRequest':
            return [('ClanRankListCommand', {'ranks': self.ranks()})]
        if name == 'DeleteMyRankRequest':
            with LOCK:
                k['uyeler'][self.me]['rutbe'] = 0
            self.changed(k)
            return [('DeleteMyRankCommand', {'command': self.member(), 'errorMsg': err('clan_delete_my_rank_success'), 'success': True})]
        if not self.right('editranks', k):
            e = err('err_clan_noRights')
            return [{'ClanNewRankRequest': ('ClanNewRankCommand', {'command': lst(), 'errorMsg': e, 'success': False}),
                     'ClanDeleteRankRequest': ('ClanDeleteRankCommand', {'clanRankListCommand': lst(), 'success': False, 'errorMsg': e}),
                     'EditClanRanksRequest': ('EditClanRanksCommand', {'command': lst(), 'errorMsg': e, 'success': False}),
                     'EditClanMemberRequest': ('EditClanMemberCommand', {'clanId': k['id'], 'success': False, 'command': self.member(),
                                                                         'errorMsg': e})}[name]]
        if name == 'ClanNewRankRequest':
            rname = str(f.get('newRank', '')).strip()
            if not rname:
                return [('ClanNewRankCommand', {'command': lst(), 'errorMsg': err('err_clan_emptyRankNotAllowed'), 'success': False})]
            if any(r['ad'].lower() == rname.lower() for r in k['rutbeler']):
                return [('ClanNewRankCommand', {'command': lst(), 'errorMsg': err('err_clan_rankExist'), 'success': False})]
            if len(k['rutbeler']) >= 10:
                return [('ClanNewRankCommand', {'command': lst(), 'errorMsg': err('err_clan_maxRank', XXX=10), 'success': False})]
            with LOCK:
                k['rutbeler'].append({'id': self.next_id(k), 'ad': rname[:30], 'haklar': []})
            self.changed(k)
            return [('ClanNewRankCommand', {'command': lst(), 'errorMsg': err('clan_new_rank_insert', XXX=rname[:30]), 'success': True})]
        if name == 'ClanDeleteRankRequest':
            rid = int(f.get('deleteRankId') or 0)
            ok = any(r['id'] == rid for r in k['rutbeler'])
            with LOCK:
                k['rutbeler'] = [r for r in k['rutbeler'] if r['id'] != rid]
                for u in k['uyeler'].values():
                    if u.get('rutbe') == rid:
                        u['rutbe'] = 0
            self.changed(k)
            return [('ClanDeleteRankCommand', {'clanRankListCommand': lst(), 'success': ok,
                                               'errorMsg': err() if ok else err('err_clan_no_rank')})]
        if name == 'EditClanRanksRequest':
            by_id = {r['id']: r for r in k['rutbeler']}
            with LOCK:
                for r in f.get('ranks') or []:
                    cur = by_id.get(int(r.get('rankId') or 0))
                    if cur:
                        cur['ad'] = str(r.get('rankName', cur['ad']))[:30] or cur['ad']
                        cur['haklar'] = [x for x in r.get('rights') or [] if x in RIGHTS]
            self.changed(k)
            return [('EditClanRanksCommand', {'command': lst(), 'errorMsg': err('success_clan_edit_rank'), 'success': True})]
        if name == 'EditClanMemberRequest':
            rid, uid = int(f.get('rankId') or 0), int(f.get('memberId') or 0)
            a = self.member_name(k, uid)
            ok = a is not None and (rid == 0 or any(r['id'] == rid for r in k['rutbeler']))
            if ok:
                with LOCK:
                    k['uyeler'][a]['rutbe'] = rid
                self.changed(k)
            u = k['uyeler'].get(a) if a else None
            return [('EditClanMemberCommand', {'clanId': k['id'], 'success': ok, 'command': self.member_cmd(u) if u else self.member(),
                                               'errorMsg': err('success_clan_change_rank' if ok else 'err_clan_no_change_rank')})]
        return []

    def mail_request(self, name, f):
        k, pl = self.k, self.p.d['pilot']
        if name == 'ClanMessageListRequest':
            return [('ClanMessageListCommand', {'messageList': [self.mail_cmd(m) for m in self.mails(k)]})]
        if name in ('ClanSendMessageRequest', 'ClanSendAllMessageRequest'):
            subject, text = str(f.get('subject', '')).strip(), str(f.get('msgText', '')).strip()
            cmd = 'ClanSendMessageCommand' if name == 'ClanSendMessageRequest' else 'ClanSendAllMessageCommand'
            fail = lambda e: [(cmd, {'errorMsg': e, 'success': False, 'clanMessageInfoCommand': None})]
            if not subject or not text:
                return fail(err('clan_errmsg_required', _NAME_=_res('clan_betreff' if not subject else 'diplo_hl_bewerbungstext')))
            to = None
            if name == 'ClanSendMessageRequest':
                to = self.member_name(k, f.get('toUserId')) if int(f.get('toUserId') or 0) else self.me
                if to is None:
                    return fail(err('err_clan_user_not_in_clan'))
            elif not self.right('roundmail', k):
                return fail(err('err_clan_noRights'))
            with LOCK:
                m = {'id': self.next_id(k), 'konu': subject[:50], 'metin': text[:5000], 'kim': self.p.user_id,
                     'ad': pl.get('userName', ''), 'tarih': stamp(), 'tur': 0 if to else 1, 'recipient': to, 'deleted_by': []}
                k['mesajlar'].insert(0, m)
                del k['mesajlar'][200:]
            self.changed(k)
            return [(cmd, {'errorMsg': err('clan_msg_send'), 'success': True, 'clanMessageInfoCommand': self.mail_cmd(m)})]
        if name in ('ClanDeleteMessageRequest', 'ClanDeleteAllMessageRequest'):
            mid = int(f.get('messageId') or 0)
            with LOCK:
                mine = [m for m in self.mails(k) if name == 'ClanDeleteAllMessageRequest' or m['id'] == mid]
                for m in mine:
                    m.setdefault('deleted_by', []).append(self.me)
                k['mesajlar'] = [m for m in k['mesajlar'] if not ((m.get('recipient') and m['recipient'] in m['deleted_by'])
                                                                   or set(k['uyeler']) <= set(m.get('deleted_by', ())))]
            self.changed(k, push=False)
            if name == 'ClanDeleteAllMessageRequest':
                return [('ClanDeleteAllMessageCommand', {'errorMsg': err('clan_msg_all_delete'), 'success': True})]
            return [('ClanDeleteMessageCommand', {'messageId': mid, 'errorMsg': err('clan_msg_delete') if mine else err(),
                                                  'success': bool(mine)})]
        return []

    def payout(self, f):
        """Kasadan üyeye (payout hakkı; verilen kredinin %10'u silinir): bağlıysa hemen, değilse sonraki girişinde (bagla)."""
        k, pl = self.k, self.p.d['pilot']
        amount, uid = int(f.get('amount') or 0), int(f.get('payoutUserId') or 0)
        a = self.member_name(k, uid) if uid else self.me
        fail = lambda e: [('PayoutClanCommand', {'success': False, 'errorMsg': err(e), 'clanTaxLogCommand': None, 'clanInfoCommand': self.info()})]
        if not self.right('payout', k):
            return fail('err_clan_noRights')
        if a is None:
            return fail('err_clan_user_not_in_clan')
        if amount <= 0 or amount > k['kasa']:
            return fail('err_clan_no_money')
        u = k['uyeler'][a]
        left = payout_limit(u)
        if amount > left:
            return [('PayoutClanCommand', {'success': False, 'clanTaxLogCommand': None, 'clanInfoCommand': self.info(),
                                           'errorMsg': err('clan_message_error_payout_userMax_reached', _AMOUNT_='{:,}'.format(left),
                                                           _CURRENCY_=_res('currency_credits'))})]
        net = amount * (100 - PAYOUT_FEE) // 100            # kasadan çıkan tutarın kesintisi silinir
        log = {'balanceUserId': int(u.get('uid', 0)), 'credits': amount, 'insertDate': stamp(), 'toName': u.get('ad', ''),
               'fromName': pl.get('userName', ''), 'moneyType': 'payout', 'reason': str(f.get('reason', ''))[:100]}
        s = people().get(a) if a != self.me else None
        with LOCK:
            if amount > k['kasa'] or amount > payout_limit(u):   # iki yetkili aynı anda öderse kasa eksiye düşmesin
                return fail('err_clan_no_money')
            k['kasa'] -= amount
            wk = u.setdefault('payment_week', {})
            week = time.strftime('%G-%V')
            for old in [x for x in wk if x != week]:
                del wk[old]
            wk[week] = int(wk.get(week, 0)) + amount
            k['kasa_kaydi'].insert(0, log)
            del k['kasa_kaydi'][200:]
            if a != self.me and s is None:
                u['pending'] = int(u.get('pending', 0)) + net
        if a == self.me:
            self.p.gain(kredi=net, neden='clan_hl_auszahlungen', detay=k['ad'])
        elif s is not None:
            s.profile.gain(kredi=net, neden='clan_hl_auszahlungen', detay=k['ad'])
            o = s.session
            if o is not None and getattr(o, 'shop', None) is not None:
                s.send(o.shop.money_msgs(), 'klan ödemesi')
        self.changed(k)
        return [('PayoutClanCommand', {'success': True, 'errorMsg': err('success_clan_payout'),
                                       'clanTaxLogCommand': mod('ClanTaxLogCommand', **log), 'clanInfoCommand': self.info()})] + \
            (self.m.money_msgs() if self.m and a == self.me else [])

    def delete(self, name):
        k = self.k
        cmd = 'DeleteClanCommand' if name == 'DeleteClanRequest' else 'DelClanCommand'
        if k['lider'] != self.me:
            return [(cmd, {'success': False, 'errorMsg': err('err_clan_noRights')})]
        extra = self.cbs.clan_disbanded(k) if self.cbs else []          # forum 127469: istasyon yıkılır, asteroit boşalır
        with LOCK:
            CLANS.pop(k['id'], None)
            DELETED[k['id']] = k['anahtar']
            others = [a for a in k['uyeler'] if a != self.me]
            for c in CLANS.values():                   # diplomasisi ve istekleri
                c['diplomasi'] = [d for d in c['diplomasi'] if d['klan'] != k['id']]
                c['diplomacy_requests'] = [r for r in c['diplomacy_requests'] if k['id'] not in (r['kimden'], r['to'])]
            peers = {d['klan'] for d in k['diplomasi']} | {r['kimden'] for r in k['diplomacy_requests']} | {r['to'] for r in k['diplomacy_requests']}
            _copy(None, self.p)
            save()
        if self.on_change:
            self.on_change()
        for a in others:
            self.kick_out(a)
        for cid in peers - {k['id']}:
            c = CLANS.get(cid)
            if c:
                self.changed(c)
                self.push(c, skip_self=False)
        self.log('   klan silindi: [%s] %s' % (k['etiket'], k['ad']))
        return [(cmd, {'success': True, 'errorMsg': err()}), ('ClearClanCommand', {'clanId': k['id']}), self.no_clan(), self.tag_cmd()] + extra

    # -------------------------------------------------------- diplomasi
    def diplo(self, name, f):
        k = self.k
        if name == 'ClanNewDiplomacyRequest':
            return self.diplo_new(k, f)
        did = int(f.get('diploId') or 0)
        if name == 'ClanEditDiploOfferRequest':
            return self.diplo_answer(k, did, str(f.get('status', '')))
        if name == 'ClanDeleteOpenDiploRequest':
            with LOCK:
                r = next((x for x in k['diplomacy_requests'] if x['id'] == did and x['kimden'] == k['id']), None)
                ok = r is not None and self.right(DIPLO_RIGHTS.get(r['tur'], 'diplo_start'), k)
                if ok:
                    self._diplo_drop(r)
            if ok:
                self.changed(k)
                self.diplo_sync(r['to'])
            return [('ClanDeleteOpenDiploCommand', {'diploId': did, 'success': ok,
                                                    'errorMsg': err('diplo_request_delete' if ok else 'err_diplo_default')})]
        with LOCK:                                       # ClanDeleteDiploRequest: ittifak/saldırmazlık biter (savaş isteğle)
            d = next((x for x in k['diplomasi'] if x['id'] == did), None)
            if d is None or not self.right('diplo_end', k):
                e = 'err_clan_noRights' if d is not None else 'err_diplo_default'
            elif d['tur'] == 3:
                e = 'err_diplo_war_is_running'
            else:
                e = None
                for c in (k, CLANS.get(d['klan'])):
                    if c:
                        c['diplomasi'] = [x for x in c['diplomasi'] if x['id'] != did]
        if e:
            return [('ClanDeleteDiploCommand', {'diploId': did, 'baseStackCommand': err(e), 'success': False})]
        self.changed(k)
        self.diplo_sync(d['klan'])
        return [('ClanDeleteDiploCommand', {'diploId': did, 'baseStackCommand': err('diplo_end_success'), 'success': True})]

    def _diplo_drop(self, r):
        for cid in (r['kimden'], r['to']):
            c = CLANS.get(cid)
            if c:
                c['diplomacy_requests'] = [x for x in c['diplomacy_requests'] if x['id'] != r['id']]

    def _diplo_set(self, a, b, kind, did, desc, frm):
        """İki klan arasında diplomasi (tur 0: kalkar)."""
        for c, o in ((a, b), (b, a)):
            c['diplomasi'] = [x for x in c['diplomasi'] if x['klan'] != o['id']]
            if kind:
                c['diplomasi'].append({'id': did, 'klan': o['id'], 'ad': o['ad'], 'tur': kind, 'tarih': stamp(), 'metin': desc,
                                       'kimden': frm})

    def diplo_sync(self, cid):
        """Öteki klanın kopyaları ve açık pencereleri; iki klanın gemileri bakana göre yeniden (ortak_harita: ilişki imzada)."""
        c = CLANS.get(cid)
        if c:
            changed(c)
            self.push(c, skip_self=False)

    def diplo_new(self, k, f):
        tid, form = int(f.get('diploClanID') or 0), int(f.get('diploForm') or 0)
        desc = str(f.get('desc', ''))[:500]
        fail = lambda key, **a: [('ClanNewDiplomacyCommand', {'errorMsg': err(key, **a), 'success': False,
                                                              'clanDiploReqInfoCommand': None})]
        if form not in DIPLO_RIGHTS:
            return fail('err_diplo_default')
        if not self.right(DIPLO_RIGHTS[form], k):
            return fail('err_clan_noRights')
        if tid == k['id']:
            return fail('err_diplo_not_with_own_clan')
        for c in clear_wars():
            changed(c)
        with LOCK:
            t = CLANS.get(tid)
            if t is None:
                return fail('err_clan_noClanID')
            cur = next((d for d in k['diplomasi'] if d['klan'] == tid), None)
            if form == 3 and cur is not None and cur['tur'] == 3:
                return fail('err_diplo_war_is_running')
            if form in (1, 2, 3) and cur is not None:
                return fail('err_diplo_isRunning', XXX=_res('diplo_status%d' % cur['tur']))
            if form == 0 and (cur is None or cur['tur'] != 3):
                return fail('err_diplo_default')
            if any(r['kimden'] == k['id'] and r['to'] == tid for r in k['diplomacy_requests']):
                return fail('err_diplo_applyIsRunning')
            if any(r['kimden'] == tid and r['to'] == k['id'] for r in k['diplomacy_requests']):
                return fail('err_clan_diploRequest_exist')
            if form == 3 and sum(d['tur'] == 3 and d['kimden'] == k['id'] for d in k['diplomasi']) >= MAX_WARS:
                return fail('err_diplo_default')
            if form == 3 and k['kasa'] < WAR_COST:
                # bedel klan kasasından (istemcinin metni de "klanının yeterince kredisi yok"); oyuncu kendi kredisini sanıyordu
                # (oyuncu bildirimi 2026-10-30): kasadaki ve gereken tutar ileti ardında
                from shop import stack_extra
                return [('ClanNewDiplomacyCommand', {'errorMsg': stack_extra('err_clan_no_money', ' ({:,} / {:,} Credits)'.format(
                                                                          int(k['kasa']), WAR_COST)),
                                                     'success': False, 'clanDiploReqInfoCommand': None})]
            did = _no()
            if form == 3:                                   # savaş hemen: bedel kasadan, 10 gün
                k['kasa'] -= WAR_COST
                self._diplo_set(k, t, 3, did, desc, k['id'])
                for c in (k, t):
                    c['diplomasi'][-1]['bitis'] = time.time() + WAR_DAYS * 86400
                self.add_news('war2', '', k, other=t['ad'])
                self.add_news('war', '', t, other=k['ad'])
                r = {'id': did, 'kimden': k['id'], 'to': tid, 'tur': 3, 'tarih': stamp(), 'metin': desc}
            else:
                r = {'id': did, 'kimden': k['id'], 'to': tid, 'tur': form, 'tarih': stamp(), 'metin': desc}
                k['diplomacy_requests'].append(r)
                t['diplomacy_requests'].append(dict(r))
            cmd = self.diplo_req_cmd(r, k)
        self.changed(k, push=form == 3)
        self.diplo_sync(tid)
        self.log('   diplomasi: [%s] -> [%s] tür %d' % (k['etiket'], t['etiket'], form))
        out = [('ClanNewDiplomacyCommand', {'errorMsg': err('clan_newDiploOffer' if form != 3 else 'empty'), 'success': True,
                                            'clanDiploReqInfoCommand': cmd})]
        if form == 3:                                       # istemci yanıtı isteklere ekler: savaş diplomasilerde (bütün liste)
            out.append(('LoginInitClanCommand', {'clanAllInfoCommand': self.all_info()}))
        return out

    def diplo_answer(self, k, did, status):
        """ClanEditDiploOfferRequest {status 'allow'/'deny'}: gelen isteğe yanıt (istemci 'allow'da isteği diplomasilere taşır)."""
        allow = status == 'allow'
        fail = lambda key: [('ClanEditDiploOfferCommand', {'status': status, 'success': False, 'clanDiploInfoCommand': None,
                                                           'stack': err(key), 'clanDiploReqInfoCommand': None})]
        with LOCK:
            r = next((x for x in k['diplomacy_requests'] if x['id'] == did and x['to'] == k['id']), None)
            if r is None:
                return fail('err_diplo_default')
            if not self.right(DIPLO_RIGHTS.get(r['tur'], 'diplo_start'), k):
                return fail('err_clan_noRights')
            o = CLANS.get(r['kimden'])
            req = self.diplo_req_cmd(r, k)
            self._diplo_drop(r)
            info = None
            if allow and o is not None:
                self._diplo_set(k, o, r['tur'], did, r['metin'], o['id'])
                if r['tur'] == 0:                          # savaş bitti
                    self.add_news('peace', '', o, other=k['ad'])
                    self.add_news('peace2', '', k, other=o['ad'])
                else:
                    info = self.diplo_cmd(next(d for d in k['diplomasi'] if d['klan'] == o['id']))
            oname = (o or {}).get('ad', '')
        self.changed(k, push=False)
        if o is not None:
            self.diplo_sync(o['id'])
        key = ('diplo_new_allow' if allow else 'diplo_new_deny')
        args = {'XXX': oname, 'YYY': _res('diplo_status%d' % r['tur'])} if allow else {'XXX': oname}
        out = [('ClanEditDiploOfferCommand', {'status': status, 'success': True, 'clanDiploInfoCommand': info, 'stack': err(key, **args),
                                              'clanDiploReqInfoCommand': req})]
        if allow and info is None:
            out.append(('LoginInitClanCommand', {'clanAllInfoCommand': self.all_info()}))
        return out

    # -------------------------------------------------------- sohbet
    def rooms(self):
        k = self.p.d.get('klan')
        return [('clan', 'clan', str(k['id']))] if k else []
