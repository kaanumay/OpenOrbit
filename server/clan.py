"""Clan (roadmap Stage 10): the client's clan window (UIClan). The clans of the players on the server are shared (multi-client, friend
server): search, application, accept/reject, members, ranks, news, clan mail, tax and treasury, leadership, diplomacy.

The clan's main record is in memory (CLANS); every member's profile keeps a copy (so a save slot is self-sufficient: backup, export,
single player). On login (when a clan is founded: bind) the copy is merged with the main record: the newer one (version) wins; another clan
with the same id (saves from the same seed created them with the same id) gets a new id; the copy of a clan the member was removed from or
that was deleted is dropped. On every change (changed) the connected members' copies are refreshed; open windows get LoginInitClanCommand
(client MyClanDataVo.UpdateAllInfo: the whole list). In multiplayer the main records are also in save/clans.json (configure: game.main): a
member removed while offline, an accepted application or a payment is applied at the next login.
Members are kept by pilot name (lowercase): a guest's id on the server differs on every join (multiplayer). An offline member's numbers
are the last known state.
Client: there are no separate requests for the member list, applications, news, mail (the ClanMemberList/ClanApplyInfoList handlers are
empty); the window gets everything with LoginInitClanRequest. The client of a player who left, was removed or whose clan was deleted does
not delete its own data (LeaveClanCommand is only an info window, the ClearClanCommand handler is empty): LoginInitMyApplyCommand builds
the clanless state. The player whose application is accepted gets JoinClanCommand (clan room: ChatComponentSystem.RefreshMembershipRoom).
Ship tag ClanTagChangedCommand (the ship of userId).
Diplomacy: alliance (1) and non-aggression (2) with the other clan's approval (ClanEditDiploOfferRequest 'allow'/'deny'), war (3) at once,
the request to end a war (0) with approval. The clan relation of ships (ShipCreateCommand.clanDiplomacy) depends on the viewer (relation;
shared_maps). Tax: a rate of the credits the member earns (player_profile.gain; TAXED: the earning sources forum 127471 lists: aliens,
players, ore, quests, gates, boxes; player report 2026-11-02: only alien rewards were taxed) goes to the treasury; the window's
"income/day" is today's tax (income_day).
"""
import copy, json, os, random, secrets, sys, threading, time

import settings as SET

FOUNDING_COST = 300000
COMPANY_CHANGE_COST = 5000           # changing company (fixed in the client: ClanSubViewCompany.InitUI, changeFaction_infoText)
X1 = {1: 1, 2: 5, 3: 9}       # company -> X-1 map
RIGHTS = ['hiremember', 'firemember', 'editranks', 'news', 'roundmail', 'tax', 'payout', 'diplo_start', 'diplo_end',
          'diplo_war', 'battle_station_replace_module', 'battle_station_deflector', 'battle_station_build']      # + Ö5 (CBS)
MAX_TAX = 5               # official forum 127471, 127585: clan tax 0-5%
MAX_MEMBERS = 50                # official forum 127471, 127585 (11.2): at most 50 players per clan (client err_clan_full)
APPLICATION_FEE = 1500         # application to a clan (forum 127471, 127585 11.4; darkorbitwiki guides/clan): does not go to the treasury; not returned
#                               on acceptance, refunded on rejection or withdrawal
PAYOUT_FIRST, PAYOUT_INCREASE, PAYOUT_CAP = 5000000, 10000000, 250000000      # weekly limit from the treasury to a member (forum 127471): the week they joined
#                               5 M, +10 M each week, at most 250 M; per membership (reset when leaving the clan)
WAR_COST, MAX_WARS, WAR_DAYS = 500000, 20, 10      # war declaration (forum 127321): 500,000 credits (from the clan treasury:
#                               adaptation), at most 20 declarations at once, ends by itself after 10 days
COMPANY_CBS, COMPANY_NO_CBS = 10, -1          # company hierarchy (forum 127469): a clan with a built CBS gets +10 per hour, one without -1
COOLDOWN_SEC = 48 * 3600        # after leaving a clan no founding/joining a new clan; clan name/tag between two changes (client: clan_user_2dayblock,
#                               err_clannameChange2Days; darkorbitwiki guides/clan: 48 hours)
PAYOUT_FEE = 10          # share automatically deleted on a payout from the treasury to a member, percent (darkorbitwiki guides/clan)
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
CLANS = {}                  # clan id -> main record
DELETED = {}                  # deleted clan's id -> its key (so a connecting member's old copy does not come back)
FILE = None                  # file of the main records in multiplayer (configure)
BOT_NAME_N = 0                  # last position of the bot name register (name_log.py) applied to these records


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
    """Text without a BaseKey (a key in the client's source): the raw "XXX" + the localized value of XXX (like shop.RES_REPLACEMENT)."""
    from shop import BASEKEY, ARG_KEYS
    if key in BASEKEY:
        return err(key, **args)
    lst = [mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS[k], value=str(v)) for k, v in args.items()]
    lst.append(mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS['XXX'], value=_res(key)))
    return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX', argsList=lst)


NEWS_KEYS = {'found': 'clan_found', 'left': 'success_clan_left', 'leader': 'info_clan_changeLeader',
             'war': 'diplo_declare_war_info', 'war2': 'diplo_declare_war_info2', 'peace': 'diplo_stop_war_msg',
             'peace2': 'diplo_stop_war_msg2'}      # the client builds the news from the language key (%username%, %clanname%)


def name(p):
    return str(p.d['pilot'].get('userName', '')).strip().lower()


# ------------------------------------------------------------ main records
def configure(path):
    """Multiplayer server (game.main): main records from file; written as they change."""
    global FILE, BOT_NAME_N
    FILE = path
    try:
        with open(path, encoding='utf8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    with LOCK:
        for k in (d.get('clans') or {}).values():
            if isinstance(k, dict) and 'members' in k:
                CLANS.setdefault(int(k['id']), k)
        DELETED.update({int(i): a for i, a in (d.get('deleted') or {}).items()})
        BOT_NAME_N = max(BOT_NAME_N, int(d.get('bot_name_log') or 0))
    import name_log as NL
    NL.apply_clans(sys.modules[__name__])        # bot names changed or deleted in the panel (while the game was closed)


def save():
    if not FILE:
        return
    with LOCK:
        text = json.dumps({'clans': {str(i): k for i, k in CLANS.items()}, 'deleted': {str(i): a for i, a in DELETED.items()},
                           'bot_name_log': BOT_NAME_N}, ensure_ascii=False)
        tmp = FILE + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf8') as fh:
                fh.write(text)
            os.replace(tmp, FILE)
        except OSError as e:
            print('clans.json could not be written: %r' % e)


def _new_id():
    while True:
        cid = random.randint(100000, 999999)
        if cid not in CLANS and cid not in DELETED:
            return cid


def _no():
    return random.randint(1, 2 ** 31 - 1)


def _move(k, p):
    """Record of a one-person clan (previous version) -> record with members."""
    if 'members' in k:
        return
    me = name(p)
    for f, v in (('tag', ''), ('name', ''), ('description', ''), ('founded', stamp()), ('purchase', 0), ('recruit_info', 0), ('tax', 0),
                 ('treasury', 0), ('treasury_log', []), ('ts', ''), ('company', int(p.d['pilot'].get('factionId', 0))), ('clan_news', []),
                 ('messages', []), ('ranks', []), ('order', 1)):
        k.setdefault(f, v)
    k['members'] = {me: {'name': p.d['pilot'].get('userName', ''), 'uid': p.user_id, 'rank': k.pop('my_rank', 0),
                        'joined': k['founded']}}
    k.update(leader=me, key=secrets.token_hex(8), version=1, applications=[], rejected=[], diplomacy=[], diplomacy_requests=[], income=0)


def profiles():
    """Profiles of the players on the server (name -> profile)."""
    import community as TP
    return {name(x.profile): x.profile for x in TP.all_().values()}


def people():
    import community as TP
    return {name(x.profile): x for x in TP.all_().values()}


def _copy(k, p):
    """The copy in the profile and the ship tag according to the main record (k None: clanless) -> did the tag or id change."""
    pl = p.d['pilot']
    with p.lock:
        old = (pl.get('clanId', 0), pl.get('clanTag', ''))
        p.d['clan'] = copy.deepcopy(k) if k else None
        pl.update(clanId=k['id'] if k else 0, clanTag=k['tag'] if k else '')
        p.dirty = True
        return old != (pl['clanId'], pl['clanTag'])


def bind(p, log=print):
    """On login: the copy in the profile is merged with the main record (see the module note). First the bot names changed or deleted in
    the panel are applied to the copy and the main records (ad_kaydi): the bots of a deleted pack leave the clan, one whose name changed
    shows with the new name."""
    import name_log as NL
    NL.apply_profile(p)
    NL.apply_clans(sys.modules[__name__])
    me = name(p)
    with LOCK:
        s = p.d.get('clan')
        if s:
            if 'members' not in s:
                with p.lock:
                    _move(s, p)
            cid, key = int(s['id']), s.get('key')
            m = next((c for c in CLANS.values() if c.get('key') == key), None)
            if m is None and key in DELETED.values():
                pass
            elif m is None and cid not in CLANS:
                m = CLANS[cid] = copy.deepcopy(s)
            elif m is None:                                         # another clan with the same id (saves from the same seed)
                nid = _new_id()
                log('   clan id conflict: [%s] %s %d -> %d' % (s['tag'], s['name'], cid, nid))
                m = CLANS[nid] = dict(copy.deepcopy(s), id=nid)
            elif int(s.get('version', 0)) > int(m.get('version', 0)):     # main record is old (no file): the new one in the profile
                mid = m['id']
                m.clear()
                m.update(copy.deepcopy(s), id=mid)
            if m is not None and me not in m['members']:
                m = None
        else:
            m = next((k for k in CLANS.values() if me in k['members']), None)   # application accepted while offline
        if m is not None:
            u = m['members'][me]
            u.update(live(p))
            pay = int(u.pop('pending', 0) or 0)
        _copy(m, p)
        if m is not None:
            if pay:
                p.gain(credits=pay, reason='clan_hl_auszahlungen', detail=m['name'])
            save()
    refund_fee(p)
    return m


def changed(k, extra=()):
    """The main record changed: the version increases, the connected members' (and extra profiles') copies are refreshed -> profiles whose
    tag changed."""
    with LOCK:
        k['version'] = int(k.get('version', 0)) + 1
        target = {a: x for a, x in profiles().items() if a in k['members']}
        for x in extra:                                     # whose membership just ended or started
            s = x.d.get('clan')
            if name(x) in k['members'] or (s and s.get('id') == k['id']):
                target[name(x)] = x
        out = [x for a, x in target.items() if _copy(k if a in k['members'] and CLANS.get(k['id']) is k else None, x)]
        save()
    return out


def clan_of(p):
    """The profile's clan's main record or None."""
    cid = int(p.d['pilot'].get('clanId', 0) or 0)
    with LOCK:
        k = CLANS.get(cid)
        return k if k is not None and name(p) in k['members'] else None


def right(p, right):
    """The player's right in the clan (HAKLAR; the leader has all of them)."""
    with LOCK:
        k = clan_of(p)
        if not k:
            return False
        if k['leader'] == name(p):
            return True
        rid = k['members'][name(p)].get('rank', 0)
        return any(r['id'] == rid and right in r['rights'] for r in k['ranks'])


def relation(p, q):
    """The clan relation of q's ship from p's point of view (ClanRelationModule.type): 1 alliance, 2 non-aggression, 3 war, 0 none."""
    return clan_relation(int(p.d['pilot'].get('clanId', 0) or 0), int(q.d['pilot'].get('clanId', 0) or 0))


def clan_relation(a, b):
    """Clan b from clan a's point of view (like iliski)."""
    if not a or not b or a == b:
        return 0
    with LOCK:
        k = CLANS.get(a)
        return next((d['type'] for d in (k or {}).get('diplomacy', ()) if d['clan'] == b and not is_war_over(d)), 0)


TAXED = ('bonus_abschussAlien', 'bonus_abschussPlayer', 'quest_won', 'galaxy_gate_done', 'collect_bonusbox', 'sell_ore')


def taxed(reason):
    """Is a credit gain with this account history reason earned income (clan tax), not a refund, payout or transfer?"""
    return reason in TAXED or str(reason).startswith('sellOre_')


def add_income(k, n):
    """Today's tax income of the clan (the window's "income/day"; under LOCK)."""
    day = time.strftime('%Y-%m-%d')
    if k.get('income_day') != day:
        k.update(income=0, income_day=day)
    k['income'] = int(k.get('income', 0)) + n


def income_today(k):
    return int(k.get('income', 0)) if k.get('income_day') == time.strftime('%Y-%m-%d') else 0


def tax(p, credits):
    """The clan's tax from earned credits (player_profile.gain: outside the lock) -> credits going to the treasury."""
    if credits <= 0 or not p.d['pilot'].get('clanId'):
        return 0
    with LOCK:
        k = clan_of(p)
        if not k or not k.get('tax'):
            return 0
        tax = credits * int(k['tax']) // 100
        if tax:
            k['treasury'] += tax
            add_income(k, tax)
            for x in profiles().values():               # treasury of the copies (one profile record in single player)
                s = x.d.get('clan')
                if s and s.get('id') == k['id']:
                    s.update(treasury=k['treasury'], income=k['income'])
            if p.d.get('clan') and p.d['clan'].get('id') == k['id']:
                p.d['clan'].update(treasury=k['treasury'], income=k['income'])
        return tax


BANNED = ('admin', 'moderator', 'gamemaster', 'support', 'bigpoint', 'darkorbit', 'communitymanager', 'nazi', 'hitler', 'nigger',
           'orospu', 'sikis', 'amcik', 'fuck', 'porn')


def is_banned(text):
    """Game Rules 7 (official forum 131990): a name, clan name and tag that resembles staff names or is racist, sexist or obscene.
    Lowercase, separators dropped, 0/1/3/4/5/7 converted to letters; a short list of substrings (adaptation)."""
    t = str(text or '').lower().translate(str.maketrans('013457', 'oleast'))
    t = ''.join(c for c in t if c.isalnum())
    return any(w in t for w in BANNED) or t in ('gm', 'mod', 'cm')


def name_changed(old, new_):
    """Pilot name changed (game.rename): membership, leadership and applications under the new name."""
    old, new_lower = str(old).strip().lower(), str(new_).strip().lower()
    if old == new_lower:
        return
    with LOCK:
        for k in CLANS.values():
            if old in k['members']:
                u = k['members'].pop(old)
                k['members'][new_lower] = dict(u, name=new_)
                if k['leader'] == old:
                    k['leader'] = new_lower
            for b in k['applications']:
                if b['name'] == old:
                    b.update(name=new_lower, first_name=new_)
            k['rejected'] = [new_lower if r == old else r for r in k['rejected']]
            if new_lower in k['members']:
                changed(k)                      # after the applications and rejections are updated too (the members' copies used to stay old)
        save()


def is_member_name(name, own=''):
    """Is it the name of a member in a clan (offline): so that a rename does not overwrite that member's record."""
    name, own = str(name).strip().lower(), str(own).strip().lower()
    with LOCK:
        return name != own and any(name in k['members'] for k in CLANS.values())


def live(p):
    """The member's numbers in the list (updated while online)."""
    import ranks as RT
    pl, c = p.d['pilot'], p.d.get('counters') or {}
    return {'name': pl.get('userName', ''), 'uid': p.user_id, 'company': int(pl.get('factionId', 0)), 'ep': int(pl.get('ep', 0)),
            'honor': int(pl.get('honourPoints', 0)), 'level': int(pl.get('level', 1)), 'rank_no': int(pl.get('dailyRank', 1) or 1),
            'points': RT.user_score(p), 'map': int(p.d['position'].get('mapId', 1)),
            'ship': sum((c.get('player') or {}).values()), 'alien': sum((c.get('npc') or {}).values())}


def players(p=None):
    """Known players on the server (name -> numbers): connected ones live, the clans' offline members with their last known state."""
    prof = profiles()
    if p is not None:
        prof.setdefault(name(p), p)
    out = {}
    with LOCK:
        for k in CLANS.values():
            for a, u in k['members'].items():
                if a not in prof:
                    out[a] = dict(u)
    for a, x in prof.items():
        out[a] = live(x)
        with LOCK:
            k = clan_of(x)
            if k:
                k['members'][a].update(out[a])
    return out


def points(k, who=None):
    who = who if who is not None else players()
    return sum(int((who.get(a) or u).get('points', 0)) for a, u in k['members'].items())


def payout_limit(u, now=None):
    """What can still be paid to a member from the treasury this week (forum 127471; client clan_message_error_payout_userMax_reached)."""
    now = now or time.time()
    try:
        start = time.mktime(time.strptime(u.get('joined', ''), '%Y-%m-%d %H:%M:%S'))
    except (ValueError, OverflowError):
        start = now
    weeks = max(0, int((now - start) // (7 * 86400)))
    paid = int((u.get('payment_week') or {}).get(time.strftime('%G-%V', time.localtime(now)), 0))
    return max(0, min(PAYOUT_CAP, PAYOUT_FIRST + PAYOUT_INCREASE * weeks) - paid)


def is_war_over(d, now=None):
    return d['type'] == 3 and d.get('end_time') and (now or time.time()) >= d['end_time']


def clear_wars(now=None):
    """Wars whose time (10 days) has run out are removed from both clans -> changed clans."""
    out = []
    with LOCK:
        for k in CLANS.values():
            n = len(k['diplomacy'])
            k['diplomacy'] = [d for d in k['diplomacy'] if not is_war_over(d, now)]
            if len(k['diplomacy']) != n:
                out.append(k)
    return out


def refund_fee(p):
    """Application fee: while those awaiting a reply stay; the accepted clan's is not returned, the rejected, withdrawn or deleted-clan
    application's is refunded (one rejected while offline at the next login) -> refunded credits."""
    fees, me, back = p.d.get('clan_application_fees') or {}, name(p), 0
    with LOCK:
        for cid, n in list(fees.items()):
            c = CLANS.get(int(cid))
            if c is not None and any(b['name'] == me for b in c['applications']):
                continue
            del fees[cid]
            p.dirty = True
            if c is None or me not in c['members']:
                back += int(n)
    if back:
        p.gain(credits=back, reason='clan_hl_clan_bewerbung')
    return back


def stations(k, p):
    """The clan's built Clan Battle Stations (cbs.py; in single player the player's clan's) -> ['Name (map)', …]."""
    import cbs as CBS
    import map_links as H
    h = CBS.shared()
    if h is None and int(p.d['pilot'].get('clanId', 0) or 0) != k['id']:
        return []
    out = []
    for aid, a in sorted(((h or p).d.get('cbs') or {}).get('asteroids', {}).items()):
        if a.get('state') != 'built' or a.get('owner') == 'rival' or (h is not None and a.get('clan') != k['id']):
            continue
        ast = CBS.ASTEROIDS.get(int(aid)) or {}
        out.append('%s (%s)' % (ast.get('name', aid), H.name(ast.get('map', 0))))
    return out


def company_points(k, p, now=None):
    """Company hierarchy points: for each full hour since the last update +10 if there is a built CBS, otherwise -1 (at least 0)."""
    now = now or time.time()
    with LOCK:
        last = k.setdefault('company_time', now)
        hours = int((now - last) // 3600)
        if hours > 0:
            k['company_points'] = max(0, int(k.get('company_points', 0)) + hours * (COMPANY_CBS if stations(k, p) else COMPANY_NO_CBS))
            k['company_time'] = last + hours * 3600
        return int(k.get('company_points', 0))


def ranking(who=None):
    """By the clans' score (sum of the members' best user scores) (largest first) -> [(clan, score)]."""
    who = who if who is not None else players()
    with LOCK:
        lst = [(k, points(k, who)) for k in CLANS.values()]
    return sorted(lst, key=lambda item: (-item[1], item[0]['id']))



RESERVED_TAGS = ('cm',)          # the chat moderators' tag [CM] (bot/moderation.py): no clan can take it


def is_reserved(tag):
    """Is it a reserved tag: including upper/lowercase and fancy lookalikes ("Cm", "ϹΜ", "ᴄᴍ")."""
    import unicodedata
    from bot.name_style import plain
    t = ''.join(c for c in unicodedata.normalize('NFKC', str(tag)) if c.isalnum()).lower()
    return t in RESERVED_TAGS or plain(tag) in RESERVED_TAGS or _similar(t) in RESERVED_TAGS


def _similar(t):
    """Greek/Cyrillic letters that resemble Latin letters (Ϲ Μ С М ...)."""
    return t.translate(str.maketrans({'ϲ': 'c', 'σ': 'c', 'ς': 'c', 'с': 'c', 'ᴄ': 'c', 'μ': 'm', 'м': 'm', 'ᴍ': 'm'}))

class Clan:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None
        self.on_change = None             # joined/left a clan, tag: chat rooms, ship tag (social.py)
        self.cbs = None                   # Clan Battle Station (Ö5; cbs.py): the station tab and its log
        bind(profile, log)

    @property
    def k(self):
        s = self.p.d.get('clan')
        if not s:
            return None
        with LOCK:
            m = CLANS.get(int(s.get('id', 0)))
            if m is None or m.get('key') != s.get('key') or self.me not in m['members']:
                m = bind(self.p, self.log)
            return m

    @property
    def me(self):
        return name(self.p)

    def right(self, right, k=None):
        k = k or self.k
        if not k:
            return False
        if k['leader'] == self.me:
            return True
        rid = k['members'].get(self.me, {}).get('rank', 0)
        return any(r['id'] == rid and right in r['rights'] for r in k['ranks'])

    def blocked(self):
        """After leaving a clan, a new clan cannot be founded and a clan cannot be joined until COOLDOWN_SEC has elapsed."""
        return SET.get('clan_cooldown') and time.time() < self.p.d.get('clan_left_at', 0) + COOLDOWN_SEC

    def member_name(self, k, uid):
        """The member's name (the client asks by id) or None."""
        return next((a for a, u in k['members'].items() if int(u.get('uid', 0)) == int(uid or 0)), None)

    # -------------------------------------------------------- commands
    def company(self):
        """Company info: of the companies of the players on the server (member count, ships and aliens, EP, honor, rank points)."""
        fac = int(self.p.d['pilot'].get('factionId', 0))
        lst = [u for u in players(self.p).values() if int(u.get('company', 0)) == fac]
        return mod('CompanyDateInfoCommand', members=len(lst), ships=sum(int(u.get('ship', 0)) for u in lst),
                   EP=sum(int(u.get('ep', 0)) for u in lst), aliens=sum(int(u.get('alien', 0)) for u in lst),
                   hounr=sum(int(u.get('honor', 0)) for u in lst), ranking=sum(int(u.get('points', 0)) for u in lst))

    def hierarchy(self):
        """CompanyHierarchyRequest: the companies' clan ranking (clans on the server; the other players' clans in the record are absent,
        H79)."""
        k, pl = self.k, self.p.d['pilot']
        fac = int(pl.get('factionId', 0))
        own = mod('CompanyHierarchyRankingModule', clanId=-1, rank=0, clanName='', leaderName='', cbsNamesAndLocations='',
                  rankingPoints=0)
        lists = {1: [], 2: [], 3: []}
        with LOCK:                                          # forum 127469: CBS company points; top 9 per company, one's own clan additionally
            for c, pts in sorted(((c, company_points(c, self.p)) for c in CLANS.values()), key=lambda cp: (-cp[1], cp[0]['id'])):
                f = int(c['company'] or 0) or int((c['members'].get(c['leader']) or {}).get('company') or 0)    # all companies: the leader's
                if f not in lists:
                    continue
                row = mod('CompanyHierarchyRankingModule', clanId=c['id'], rank=len(lists[f]) + 1, clanName=c['name'],
                          leaderName=(c['members'].get(c['leader']) or {}).get('name', ''),
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
            lead = k['members'].get(k['leader']) or {}
            return mod('ClanInfoCommand', recruitionInfo=k['recruit_info'], taxRate=k['tax'], clanId=k['id'],
                       recruitionStatus=k['purchase'], clanCredits=k['treasury'], teamspeakAdd=k['ts'], clanLeaderName=lead.get('name', ''),
                       clanName=k['name'], clanRank=no, clanIcon='', clanLeaderId=int(lead.get('uid', 0)), memberCount=len(k['members']),
                       clanTag=k['tag'], clanDesc=k['description'], company=k['company'], insertDate=k['founded'], ranking=pts)

    def member_cmd(self, u):
        from map_links import name as map_name
        return mod('ClanMemberInfoCommand', faction=int(u.get('company', 0)), mapName=map_name(int(u.get('map', 1))),
                   name=u.get('name', ''), maxPayout=payout_limit(u), insertDate=u.get('joined', ''), ep=int(u.get('ep', 0)),
                   userId=int(u.get('uid', 0)), ranksId=int(u.get('rank', 0)), rank=int(u.get('rank_no', 1)))

    def members(self, k=None):
        k = k or self.k
        if not k:
            return []
        players(self.p)                                   # the connected members' numbers
        with LOCK:
            order = sorted(k['members'].items(), key=lambda uid_member: (uid_member[0] != k['leader'], uid_member[1].get('joined', ''), uid_member[0]))
            return [self.member_cmd(u) for _, u in order]

    def member(self):
        return self.member_cmd(dict(self.k['members'].get(self.me) or {}, **live(self.p)))

    def rank_cmd(self, r):
        return mod('ClanRankInfoCommand', rankId=r['id'], clanId=self.k['id'], rankName=r['name'], rights=list(r['rights']))

    def ranks(self):
        return [self.rank_cmd(r) for r in self.k['ranks']]

    def news_cmd(self, n):
        """Client (MyClanDataVo.AddNews): if type is "user" the context is plain text; otherwise the context is a language key (%username%,
        %clanname% are replaced). The founding news is the client's "clan_found" text (live test 2026-10-17: both came out empty)."""
        k = self.k
        kind, text = ('user', n['text']) if n['type'] in ('news', 'user') else (n['type'], NEWS_KEYS.get(n['type'], n['text']))
        return mod('ClanNewsInfoCommand', type=kind, clanNewsId=n['id'], userName=n['name'], clanId=k['id'], context=text,
                   userId=n['who'], clanName=n.get('clan_name') or k['name'], insertDate=n['date'])

    def mail_cmd(self, m):
        return mod('ClanMessageInfoCommand', insertDate=m['date'], subject=m['subject'], mailText=m['text'], type=m.get('type', 0),
                   sendUserId=m['who'], textIncName='', subjectIncName='', sendUserName=m['name'], messageId=m['id'],
                   textParams='', subjectParams='')

    def mails(self, k=None):
        """The clan mail the player sees: those sent to everyone and those sent to them (except ones they deleted)."""
        k = k or self.k
        me = self.me
        return [m for m in k['messages'] if m.get('recipient') in (None, me) and me not in m.get('deleted_by', ())]

    def tax_cmd(self):
        return mod('ClanTaxInfoCommand', income=income_today(self.k),
                   logList=[mod('ClanTaxLogCommand', **x) for x in self.k['treasury_log'][:50]])

    def apply_cmd(self, b):
        u = players().get(b['name']) or {}
        return mod('ClanApplyInfoCommand', userName=b['first_name'], EP=int(u.get('ep', 0)), applyDesc=b['text'], level=int(u.get('level', 1)),
                   clanApplyId=b['id'], insertDate=b['date'], company=int(u.get('company', 0)))

    def diplo_req_cmd(self, r, k):
        other = r['to'] if r['from_clan'] == k['id'] else r['from_clan']
        o = CLANS.get(other) or {}
        return mod('ClanDiploReqInfoCommand', desc=r['text'], fromClanId=r['from_clan'], insertDate=r['date'], cdrId=r['id'],
                   clanName=o.get('name', r.get('name', '')), toClanId=r['to'], diploType=r['type'])

    def diplo_cmd(self, d):
        o = CLANS.get(d['clan']) or {}
        left = max(0, -int(-(d['end_time'] - time.time()) // 86400)) if d.get('end_time') else 0
        return mod('ClanDiploInfoCommand', clanName=o.get('name', d.get('name', '')), daysLeft=left, cdiId=d['id'], diploType=d['type'],
                   fromClanId=d['from_clan'], insertDate=d['date'], desc=d['text'])

    def all_info(self):
        k = self.k
        with LOCK:
            incoming = [self.diplo_req_cmd(r, k) for r in k['diplomacy_requests'] if r['to'] == k['id']]
            outgoing = [self.diplo_req_cmd(r, k) for r in k['diplomacy_requests'] if r['from_clan'] == k['id']]
            apps = [self.apply_cmd(b) for b in k['applications']] if self.right('hiremember', k) else []
            return mod('ClanAllInfoCommand', clanMemberInfoCommandList=self.members(k), clanTaxInfoCommand=self.tax_cmd(),
                       clanDiploReqInfoCommands=incoming, myClanDiploReqInfoCommands=outgoing,
                       clanApplyInfoListCommand=mod('ClanApplyInfoListCommand', applyClanInfoCommandList=apps),
                       clanMessageInfoCommands=[self.mail_cmd(m) for m in self.mails(k)],
                       clanDiploInfoCommands=[self.diplo_cmd(d) for d in k['diplomacy']],
                       clanRankInfoCommands=self.ranks(), clanInfoCommand=self.info(k),
                       clanNewsInfoCommands=[self.news_cmd(n) for n in k['clan_news']], companyDateInfoCommand=self.company())

    def tag_cmd(self):
        pl = self.p.d['pilot']
        return ('ClanTagChangedCommand', {'clanTag': pl.get('clanTag', ''), 'clanId': pl.get('clanId', 0), 'userId': self.p.user_id})

    def no_clan(self):
        """Clanless window: the clans they applied to and the ones that rejected."""
        me = self.me
        with LOCK:
            order = ranking()
            applied = [self.info(c, order) for c in CLANS.values() if any(b['name'] == me for b in c['applications'])]
            rejected = [c['id'] for c in CLANS.values() if me in c['rejected']]
        return ('LoginInitMyApplyCommand', {'applyClanList': applied, 'foundCost': FOUNDING_COST, 'companyDateInfoCommand': self.company(),
                                            'rejectApplyClanList': rejected})

    def nametag(self, k=None):
        k = k or self.k
        return mod('ClanNameTagInfoCommand', tag=k['tag'], id=k['id'], name=k['name'])

    # -------------------------------------------------------- helpers
    def next_id(self, k=None):
        k = k or self.k
        with LOCK:
            k['order'] = k.get('order', 1) + 1
            return k['order']

    def add_news(self, kind, text, k=None, who=None, other=''):
        k = k or self.k
        pl = (who or self.p).d['pilot']
        with LOCK:
            n = {'id': self.next_id(k), 'type': kind, 'name': pl.get('userName', ''), 'who': (who or self.p).user_id, 'text': text[:500],
                 'date': stamp()}
            if other:
                n['clan_name'] = other                         # %clanname%: the other clan in the diplomacy
            k['clan_news'].insert(0, n)
            del k['clan_news'][50:]
        return n

    def changed(self, k=None, push=True, extra=()):
        """The main record changed: copies, the ship and chat of those whose tag changed, open windows (the other members)."""
        k = k or self.k
        moved = changed(k, (self.p,) + tuple(extra))
        for x in moved:
            self.tag_changed(x)
        if push:
            self.push(k)

    def tag_changed(self, x):
        """x's clan or tag changed: the tag to their own client, the room and tag to their chat."""
        if x is self.p:
            if self.on_change:
                self.on_change()
            return
        s = (people().get(name(x)) or None)
        o = getattr(s.session, 'social', None) if s is not None and s.session is not None else None
        if o is not None:
            s.send([o.clan.tag_cmd()], 'clan tag')
            o.clan_changed()

    def push(self, k, extra=None, skip_self=True):
        """The current clan to the clan's other connected members (open window); extra: name -> extra messages."""
        for a, s in people().items():
            if (skip_self and a == self.me) or a not in k['members'] or s.session is None:
                continue
            o = getattr(s.session, 'social', None)
            if o is None or o.clan.k is not k:
                continue
            s.send([('LoginInitClanCommand', {'clanAllInfoCommand': o.clan.all_info()})] + list((extra or {}).get(a, ())), 'clan')

    def push_clan(self, cid):
        k = CLANS.get(cid)
        if k:
            self.push(k, skip_self=False)

    def kick_out(self, a):
        """The client of a connected player who dropped from the clan (removed, clan deleted): clanless window, ship tag, chat room."""
        s = people().get(a)
        if s is None:
            return
        _copy(None, s.profile)
        o = getattr(s.session, 'social', None) if s.session is not None else None
        if o is not None:
            s.send([o.clan.no_clan(), o.clan.tag_cmd()], 'left the clan')
            o.clan_changed()

    @staticmethod
    def valid_tag(tag):
        return 1 <= len(tag) <= 4 and all(c.isalnum() or c in '-_.!?*+' for c in tag) and not is_reserved(tag)

    @staticmethod
    def taken(name, tag, skip=None):
        """The name or tag is in another clan -> text key or None."""
        with LOCK:
            for c in CLANS.values():
                if c is skip:
                    continue
                if c['name'].strip().lower() == name.strip().lower():
                    return 'clan_errmsg_clanname_exists'
                if c['tag'].strip().lower() == tag.strip().lower():
                    return 'err_clantag_exist'
        return None

    # -------------------------------------------------------- requests
    def handle(self, name, f):
        k = self.k
        if name == 'CompanyHierarchyRequest':
            return [self.hierarchy()]
        if name == 'ChangeClanFirmaRequest':           # after the reply the session takes the player to the new company's X-1 (game.py)
            return self.switch_company(f)[0]
        if name == 'LoginInitClanRequest':
            return [('LoginInitClanCommand', {'clanAllInfoCommand': self.all_info()})] if k else [self.no_clan()]
        if name == 'ClanFilterSearchRequest':
            return [self.search(f)]
        if name == 'ClanSearchNameTagRequest':
            q = str(f.get('lookup', '')).strip().lower()
            with LOCK:
                hit = [self.nametag(c) for c in CLANS.values() if q and (q in c['tag'].lower() or q in c['name'].lower())]
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
        """ClanFilterSearchRequest: the clans on the server (name/tag, company; by ranking; start/range page)."""
        q = str(f.get('lookup', '')).strip().lower()
        fac = int(f.get('factionType') or 0)
        with LOCK:
            order = ranking()
            lst = [c for c, _ in order if (not q or q in c['tag'].lower() or q in c['name'].lower())
                   and (not fac or not c['company'] or fac == c['company'])]
            if f.get('desc'):
                lst.reverse()
            start, n = max(0, int(f.get('start') or 0)), int(f.get('range') or 20) or 20
            return ('ClanFilterSearchInfoCommand', {'list': [self.info(c, order) for c in lst[start:start + n]], 'count': len(lst)})

    def no_clan_reply(self, name, f):
        """Member requests coming while clanless: the client's "you are not in a clan" text."""
        e = err('err_clan_user_not_in_clan')
        replies = {'LeaveClanRequest': ('LeaveClanCommand', {'errorMsg': e, 'success': False}),
                   'DeleteClanRequest': ('DeleteClanCommand', {'success': False, 'errorMsg': e}),
                   'DelClanRequest': ('DelClanCommand', {'success': False, 'errorMsg': e}),
                   'ApplyAcceptRequest': ('ApplyAcceptCommand', {'command': None, 'errorMsg': e, 'success': False,
                                                                 'applyId': int(f.get('applyId') or 0)}),
                   'ApplyDeclineRequest': ('ApplyDeclineCommand', {'errorMsg': e, 'success': False, 'applyId': int(f.get('applyId') or 0)})}
        r = replies.get(name)
        self.log('   clan request while clanless: %s' % name)
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
        if is_banned(cname) or is_banned(tag):                  # Game Rules 7 (official forum 131990)
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
            k = CLANS[cid] = {'id': cid, 'tag': tag, 'name': cname, 'description': desc, 'founded': stamp(), 'purchase': 0,
                                'recruit_info': 0, 'tax': 0, 'treasury': 0, 'treasury_log': [], 'ts': '',
                                'company': int(self.p.d['pilot'].get('factionId', 0)), 'clan_news': [], 'messages': [],
                                'ranks': [], 'order': 1, 'leader': me, 'key': secrets.token_hex(8), 'version': 0,
                                'members': {me: dict(live(self.p), rank=0, joined=stamp())}, 'applications': [], 'rejected': [],
                                'diplomacy': [], 'diplomacy_requests': [], 'income': 0}
            for c in CLANS.values():                      # their applications to other clans are dropped
                c['applications'] = [b for b in c['applications'] if b['name'] != me]
            self.add_news('found', cname, k)
        self.changed(k, push=False)
        self.log('   clan founded: [%s] %s (%d)' % (tag, cname, cid))
        msgs = reply(True, 'empty', cid) + [('JoinClanCommand', {'clanAllInfoCommand': self.all_info()}), self.tag_cmd()]
        return msgs + (self.m.money_msgs() if self.m else [])

    def apply(self, name, f):
        """ApplyClanRequest {clanId, message}: the application goes to the window of the clan's authorized members; DeleteClanApplyRequest
        {applyId}: withdrawal."""
        me, cid = self.me, int(f.get('clanId') or 0)
        if name == 'DeleteClanApplyRequest':
            aid = int(f.get('applyId') or 0)
            with LOCK:
                hit = [(c, b) for c in CLANS.values() for b in c['applications'] if b['name'] == me and b['id'] == aid]
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
            if any(b['name'] == me for b in c['applications']):
                return reply(False, 'err_clan_apply')
            if c['company'] and int(c['company']) != int(self.p.d['pilot'].get('factionId', 0)):     # clan bound to a company
                return reply(False, 'err_clan_other_fractionID')
            if len(c['members']) >= MAX_MEMBERS:
                return reply(False, 'err_clan_full')
        import inventory as INV
        if INV.spend(self.p, {'currency_credits': APPLICATION_FEE}, 'clan_hl_clan_bewerbung') is None:
            return reply(False, 'clan_errmsg_user_not_enough_money')
        with LOCK:
            self.p.d.setdefault('clan_application_fees', {})[str(cid)] = APPLICATION_FEE
            self.p.dirty = True
            b = {'id': _no(), 'name': me, 'first_name': self.p.d['pilot'].get('userName', ''), 'text': str(f.get('message', ''))[:1000],
                 'date': stamp()}
            c['applications'].append(b)
            if me in c['rejected']:
                c['rejected'].remove(me)
        self.changed(c)
        self.log('   clan application: %s -> [%s] %s' % (b['first_name'], c['tag'], c['name']))
        return reply(True, 'err_clan_apply_send', b['id']) + (self.m.money_msgs() if self.m else [])

    def switch_company(self, f):
        """ChangeClanFirmaRequest: the player changing company (the clan window's COMPANY tab, with or without a clan; client
        ClanSubViewCompany "Switch company"). Before, the clan's company was changing, and there was no reply when clanless: the company did
        not change (user 2026-10-24). Rules from the client's texts: only in X-1 (err_changing_company_tips), with no open quest
        (the quests' targets depend on the company: err_clan_firmchange_closeQuest), 5,000 U; the new company recognizes half the honor,
        negative honor stays (changeFactionText). On success the client refreshes its own company and the company chat room
        (UpdateChangeClanFirmaCommand); the session takes the player to the new company's X-1 station. A one-member clan's company changes
        together with the leader.
        -> (messages, X-1 to go to or None)"""
        pl = self.p.d['pilot']
        old, firm = int(pl.get('factionId', 0)), int(f.get('company') or 0)

        def reply(ok, key):
            return [('ChangeClanFirmaCommand', {'success': ok, 'firm': int(pl.get('factionId', 0)), 'companyDateInfoCommand': self.company(),
                                                'errorMsg': err(key)})]
        if firm not in X1 or firm == old:
            return reply(False, 'firmChange_notavailable'), None
        if int(self.p.d['position'].get('mapId', 0)) not in X1.values():
            return reply(False, 'err_changing_company_tips'), None
        if (self.p.d.get('quests') or {}).get('active'):
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
                k['members'][self.me]['company'] = firm
                if int(k.get('company') or 0) == old and len(k['members']) <= 1:
                    k['company'] = firm
            self.changed(k)
        self.log('   company changed: %d -> %d (honor %d -> %d)' % (old, firm, hon, pl['honourPoints']))
        return reply(True, 'firmChange_done'), X1[firm]

    def member_request(self, name, f):
        k = self.k
        if name == 'ChangeClanDescriptionRequest':
            desc = str(f.get('desc', ''))
            if k['leader'] != self.me:
                return [('ChangeClanDescriptionCommand', {'success': False, 'errorMsg': err('err_clan_no_access'), 'desc': k['description']})]
            ok = len(desc) <= 2000
            if ok:
                with LOCK:
                    k['description'] = desc
                self.changed(k)
            return [('ChangeClanDescriptionCommand', {'success': ok, 'errorMsg': err('success_clan_change_descr' if ok else
                                                                                     'clan_errmsg_desc_to_long'), 'desc': k['description']})]
        if name == 'EditClanInfoRequest':
            return self.edit_info(f)
        if name == 'ChangeClanTaxRequest':
            tax = int(f.get('tax') or 0)
            if not self.right('tax', k):
                return [('ChangeClanTaxCommand', {'tax': k['tax'], 'success': False, 'errorMsg': err('err_clan_noRights')})]
            ok = 0 <= tax <= MAX_TAX
            if ok:
                with LOCK:
                    k['tax'] = tax
                self.changed(k)
            return [('ChangeClanTaxCommand', {'tax': k['tax'], 'success': ok,
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
            return [('ClanNewsListCommand', {'newsList': [self.news_cmd(n) for n in k['clan_news']]})]
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
        """EditClanInfoRequest (the leader's info form): name, tag, TS, recruitment and company affiliation (newFraction: 0 all companies,
        1-3 company; it was ignored, the affiliation did not change: user 2026-10-24)."""
        k = self.k
        tag, cname = str(f.get('clanTag', k['tag'])).strip(), str(f.get('clanName', k['name'])).strip()
        company = int(f.get('newFraction', k['company']) or 0)
        reply = lambda ok, key='empty', **a: [('EditClanInfoCommand', {'success': ok, 'clanId': k['id'], 'clanInfoCommand': self.info(),
                                                                       'errorMsg': err(key, **a)})]
        if k['leader'] != self.me:
            return reply(False, 'err_clan_no_access')
        if not tag or not cname:
            return reply(False, 'clan_errmsg_required', _NAME_=_res('clan_name' if not cname else 'clan_tag'))
        if not self.valid_tag(tag):
            return reply(False, 'clan_errmsg_clantag_not_allowed')
        if len(cname) > 50:
            return reply(False, 'clan_errmsg_to_long')
        renamed = (tag, cname) != (k['tag'], k['name'])
        if renamed and (is_banned(cname) or is_banned(tag)):
            return reply(False, 'clan_name_not_allowed')
        if renamed and SET.get('clan_cooldown') and time.time() < k.get('name_changed_at', 0) + COOLDOWN_SEC:
            return reply(False, 'err_clannameChange2Days')
        busy = self.taken(cname, tag, skip=k)
        if busy:
            return [('EditClanInfoCommand', {'success': False, 'clanId': k['id'], 'clanInfoCommand': self.info(), 'errorMsg': text(busy)})]
        with LOCK:
            if renamed:
                k['name_changed_at'] = time.time()
            k.update(tag=tag, name=cname, ts=str(f.get('clanTS', k['ts']))[:100], purchase=int(f.get('recruitingStatus') or 0),
                     recruit_info=int(f.get('recuritingInfo') or 0), company=company if company in (0,) + tuple(X1) else k['company'])
        self.changed(k)
        return reply(True) + [self.tag_cmd()]

    def answer(self, name, f):
        """Reply to an application (hiremember): on acceptance the player becomes a member (JoinClanCommand if connected, tag, clan room),
        on rejection it appears among the rejecters in the window they applied from."""
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
            other = next((c for c in CLANS.values() if b['name'] in c['members']), None)
            if accept and other is not None:
                return reply(False, err('clan_user_in_clan'))
            if accept and len(k['members']) >= MAX_MEMBERS:
                k['applications'].append(b)
                return reply(False, err('err_clan_full'))
            if accept:
                u = players().get(b['name']) or {'name': b['first_name']}
                k['members'][b['name']] = dict(u, rank=0, joined=stamp())
                for c in CLANS.values():
                    c['applications'] = [x for x in c['applications'] if x['name'] != b['name']]
                    if b['name'] in c['rejected'] and c is k:
                        c['rejected'].remove(b['name'])
            elif b['name'] not in k['rejected']:
                k['rejected'].append(b['name'])
        s = people().get(b['name'])
        self.changed(k, extra=(s.profile,) if s is not None and accept else ())
        self.log('   clan application %s: %s -> [%s]' % ('accept' if accept else 'reject', b['first_name'], k['tag']))
        if s is not None:                                 # the connected applicant's fee: refunded at once on rejection (offline: next login)
            refund_fee(s.profile)
        o = getattr(s.session, 'social', None) if s is not None and s.session is not None else None
        if o is not None:
            s.send([('JoinClanCommand', {'clanAllInfoCommand': o.clan.all_info()}), o.clan.tag_cmd()] if accept else [o.clan.no_clan()],
                     'clan application')
            if not accept and o.clan.m:
                s.send(o.clan.m.money_msgs(), 'application fee')
        return reply(True, err() if accept else err('err_clan_decline'))

    def change_leader(self, f):
        k, uid = self.k, int(f.get('newLeaderId') or 0)
        a = self.member_name(k, uid)
        reply = lambda ok, e: [('ChangeClanLeaderCommand', {'success': ok, 'stack': e, 'command': self.info(), 'newLeaderId': uid})]
        if k['leader'] != self.me:
            return reply(False, err('err_clan_noRights'))
        if a is None:
            return reply(False, err('err_clan_user_not_in_clan'))
        if a == self.me:
            return reply(False, err('err_clan_you_are_leader'))
        with LOCK:
            k['leader'] = a
            n = self.add_news('leader', '', k)
            n.update(name=k['members'][a].get('name', ''), who=uid)
        self.changed(k)
        self.log('   clan leader: %s' % k['members'][a].get('name'))
        return reply(True, err('success_clan_changeLeader'))

    def remove_member(self, f):
        k, uid = self.k, int(f.get('removeUserID') or 0)
        a = self.member_name(k, uid)
        reply = lambda ok, e: [('DeleteClanMemberCommand', {'removeUserID': uid, 'success': ok, 'errorMsg': e})]
        if not self.right('firemember', k):
            return reply(False, err('err_clan_noRights'))
        if a is None:
            return reply(False, err('err_clan_user_not_in_clan'))
        if a == k['leader'] or a == self.me:
            return reply(False, err('err_clan_you_are_leader' if a == k['leader'] else 'err_clan_noRights'))
        with LOCK:
            u = k['members'].pop(a)
        extra = self.cbs.member_left(k, a) if self.cbs else []      # forum 127469: the modules return to their inventory
        self.changed(k)
        self.kick_out(a)
        self.log('   removed from clan: %s' % u.get('name'))
        return reply(True, err('clan_remove_member')) + extra

    def leave(self):
        k = self.k
        if k['leader'] == self.me:
            return [('LeaveClanCommand', {'errorMsg': text('err_clan_noleave'), 'success': False})]
        with LOCK:
            k['members'].pop(self.me, None)
            self.add_news('left', '', k)
        extra = self.cbs.member_left(k, self.me) if self.cbs else []
        self.p.d['clan_left_at'] = time.time()            # no founding/joining a new clan for 48 hours (blocked)
        self.p.dirty = True
        self.changed(k)                                   # their own copy is dropped (not a member)
        self.log('   left clan: [%s]' % k['tag'])
        return [('LeaveClanCommand', {'errorMsg': text('clan_leave_clan_success'), 'success': True}), self.no_clan(), self.tag_cmd()] + extra

    def rank_request(self, name, f):
        k = self.k
        lst = lambda: mod('ClanRankListCommand', ranks=self.ranks())
        if name == 'ClanRankListRequest':
            return [('ClanRankListCommand', {'ranks': self.ranks()})]
        if name == 'DeleteMyRankRequest':
            with LOCK:
                k['members'][self.me]['rank'] = 0
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
            if any(r['name'].lower() == rname.lower() for r in k['ranks']):
                return [('ClanNewRankCommand', {'command': lst(), 'errorMsg': err('err_clan_rankExist'), 'success': False})]
            if len(k['ranks']) >= 10:
                return [('ClanNewRankCommand', {'command': lst(), 'errorMsg': err('err_clan_maxRank', XXX=10), 'success': False})]
            with LOCK:
                k['ranks'].append({'id': self.next_id(k), 'name': rname[:30], 'rights': []})
            self.changed(k)
            return [('ClanNewRankCommand', {'command': lst(), 'errorMsg': err('clan_new_rank_insert', XXX=rname[:30]), 'success': True})]
        if name == 'ClanDeleteRankRequest':
            rid = int(f.get('deleteRankId') or 0)
            ok = any(r['id'] == rid for r in k['ranks'])
            with LOCK:
                k['ranks'] = [r for r in k['ranks'] if r['id'] != rid]
                for u in k['members'].values():
                    if u.get('rank') == rid:
                        u['rank'] = 0
            self.changed(k)
            return [('ClanDeleteRankCommand', {'clanRankListCommand': lst(), 'success': ok,
                                               'errorMsg': err() if ok else err('err_clan_no_rank')})]
        if name == 'EditClanRanksRequest':
            by_id = {r['id']: r for r in k['ranks']}
            with LOCK:
                for r in f.get('ranks') or []:
                    cur = by_id.get(int(r.get('rankId') or 0))
                    if cur:
                        cur['name'] = str(r.get('rankName', cur['name']))[:30] or cur['name']
                        cur['rights'] = [x for x in r.get('rights') or [] if x in RIGHTS]
            self.changed(k)
            return [('EditClanRanksCommand', {'command': lst(), 'errorMsg': err('success_clan_edit_rank'), 'success': True})]
        if name == 'EditClanMemberRequest':
            rid, uid = int(f.get('rankId') or 0), int(f.get('memberId') or 0)
            a = self.member_name(k, uid)
            ok = a is not None and (rid == 0 or any(r['id'] == rid for r in k['ranks']))
            if ok:
                with LOCK:
                    k['members'][a]['rank'] = rid
                self.changed(k)
            u = k['members'].get(a) if a else None
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
                m = {'id': self.next_id(k), 'subject': subject[:50], 'text': text[:5000], 'who': self.p.user_id,
                     'name': pl.get('userName', ''), 'date': stamp(), 'type': 0 if to else 1, 'recipient': to, 'deleted_by': []}
                k['messages'].insert(0, m)
                del k['messages'][200:]
            self.changed(k)
            return [(cmd, {'errorMsg': err('clan_msg_send'), 'success': True, 'clanMessageInfoCommand': self.mail_cmd(m)})]
        if name in ('ClanDeleteMessageRequest', 'ClanDeleteAllMessageRequest'):
            mid = int(f.get('messageId') or 0)
            with LOCK:
                mine = [m for m in self.mails(k) if name == 'ClanDeleteAllMessageRequest' or m['id'] == mid]
                for m in mine:
                    m.setdefault('deleted_by', []).append(self.me)
                k['messages'] = [m for m in k['messages'] if not ((m.get('recipient') and m['recipient'] in m['deleted_by'])
                                                                   or set(k['members']) <= set(m.get('deleted_by', ())))]
            self.changed(k, push=False)
            if name == 'ClanDeleteAllMessageRequest':
                return [('ClanDeleteAllMessageCommand', {'errorMsg': err('clan_msg_all_delete'), 'success': True})]
            return [('ClanDeleteMessageCommand', {'messageId': mid, 'errorMsg': err('clan_msg_delete') if mine else err(),
                                                  'success': bool(mine)})]
        return []

    def payout(self, f):
        """From the treasury to a member (payout right; 10% of the credits given is deleted): at once if connected, otherwise at their
        next login (bagla)."""
        k, pl = self.k, self.p.d['pilot']
        amount, uid = int(f.get('amount') or 0), int(f.get('payoutUserId') or 0)
        a = self.member_name(k, uid) if uid else self.me
        fail = lambda e: [('PayoutClanCommand', {'success': False, 'errorMsg': err(e), 'clanTaxLogCommand': None, 'clanInfoCommand': self.info()})]
        if not self.right('payout', k):
            return fail('err_clan_noRights')
        if a is None:
            return fail('err_clan_user_not_in_clan')
        if amount <= 0 or amount > k['treasury']:
            return fail('err_clan_no_money')
        u = k['members'][a]
        left = payout_limit(u)
        if amount > left:
            return [('PayoutClanCommand', {'success': False, 'clanTaxLogCommand': None, 'clanInfoCommand': self.info(),
                                           'errorMsg': err('clan_message_error_payout_userMax_reached', _AMOUNT_='{:,}'.format(left),
                                                           _CURRENCY_=_res('currency_credits'))})]
        net = amount * (100 - PAYOUT_FEE) // 100            # the fee on the amount leaving the treasury is deleted
        log = {'balanceUserId': int(u.get('uid', 0)), 'credits': amount, 'insertDate': stamp(), 'toName': u.get('name', ''),
               'fromName': pl.get('userName', ''), 'moneyType': 'payout', 'reason': str(f.get('reason', ''))[:100]}
        s = people().get(a) if a != self.me else None
        with LOCK:
            if amount > k['treasury'] or amount > payout_limit(u):   # so the treasury does not go negative if two authorized members pay at once
                return fail('err_clan_no_money')
            k['treasury'] -= amount
            wk = u.setdefault('payment_week', {})
            week = time.strftime('%G-%V')
            for old in [x for x in wk if x != week]:
                del wk[old]
            wk[week] = int(wk.get(week, 0)) + amount
            k['treasury_log'].insert(0, log)
            del k['treasury_log'][200:]
            if a != self.me and s is None:
                u['pending'] = int(u.get('pending', 0)) + net
        if a == self.me:
            self.p.gain(credits=net, reason='clan_hl_auszahlungen', detail=k['name'])
        elif s is not None:
            s.profile.gain(credits=net, reason='clan_hl_auszahlungen', detail=k['name'])
            o = s.session
            if o is not None and getattr(o, 'shop', None) is not None:
                s.send(o.shop.money_msgs(), 'clan payment')
        self.changed(k)
        return [('PayoutClanCommand', {'success': True, 'errorMsg': err('success_clan_payout'),
                                       'clanTaxLogCommand': mod('ClanTaxLogCommand', **log), 'clanInfoCommand': self.info()})] + \
            (self.m.money_msgs() if self.m and a == self.me else [])

    def delete(self, name):
        k = self.k
        cmd = 'DeleteClanCommand' if name == 'DeleteClanRequest' else 'DelClanCommand'
        if k['leader'] != self.me:
            return [(cmd, {'success': False, 'errorMsg': err('err_clan_noRights')})]
        extra = self.cbs.clan_disbanded(k) if self.cbs else []          # forum 127469: the station is destroyed, the asteroid empties
        with LOCK:
            CLANS.pop(k['id'], None)
            DELETED[k['id']] = k['key']
            others = [a for a in k['members'] if a != self.me]
            for c in CLANS.values():                   # its diplomacy and requests
                c['diplomacy'] = [d for d in c['diplomacy'] if d['clan'] != k['id']]
                c['diplomacy_requests'] = [r for r in c['diplomacy_requests'] if k['id'] not in (r['from_clan'], r['to'])]
            peers = {d['clan'] for d in k['diplomacy']} | {r['from_clan'] for r in k['diplomacy_requests']} | {r['to'] for r in k['diplomacy_requests']}
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
        self.log('   clan deleted: [%s] %s' % (k['tag'], k['name']))
        return [(cmd, {'success': True, 'errorMsg': err()}), ('ClearClanCommand', {'clanId': k['id']}), self.no_clan(), self.tag_cmd()] + extra

    # -------------------------------------------------------- diplomacy
    def diplo(self, name, f):
        k = self.k
        if name == 'ClanNewDiplomacyRequest':
            return self.diplo_new(k, f)
        did = int(f.get('diploId') or 0)
        if name == 'ClanEditDiploOfferRequest':
            return self.diplo_answer(k, did, str(f.get('status', '')))
        if name == 'ClanDeleteOpenDiploRequest':
            with LOCK:
                r = next((x for x in k['diplomacy_requests'] if x['id'] == did and x['from_clan'] == k['id']), None)
                ok = r is not None and self.right(DIPLO_RIGHTS.get(r['type'], 'diplo_start'), k)
                if ok:
                    self._diplo_drop(r)
            if ok:
                self.changed(k)
                self.diplo_sync(r['to'])
            return [('ClanDeleteOpenDiploCommand', {'diploId': did, 'success': ok,
                                                    'errorMsg': err('diplo_request_delete' if ok else 'err_diplo_default')})]
        with LOCK:      # ClanDeleteDiploRequest: alliance/non-aggression ends; a war too, by either side (the client's "End war", diplo_stop_war)
            d = next((x for x in k['diplomacy'] if x['id'] == did), None)
            if d is None or not self.right('diplo_end', k):
                e = 'err_clan_noRights' if d is not None else 'err_diplo_default'
            else:
                e = None
                o = CLANS.get(d['clan'])
                for c in (k, o):
                    if c:
                        c['diplomacy'] = [x for x in c['diplomacy'] if x['id'] != did]
                if d['type'] == 3:          # it used to answer "You're already at war with this clan." (player report 2026-11-02)
                    if o:
                        self.add_news('peace', '', o, other=k['name'])        # "The X clan ended the war with your clan."
                    self.add_news('peace2', '', k, other=(o or {}).get('name', ''))   # "Your clan ended the war with the X clan."
        if e:
            return [('ClanDeleteDiploCommand', {'diploId': did, 'baseStackCommand': err(e), 'success': False})]
        self.changed(k)
        self.diplo_sync(d['clan'])
        return [('ClanDeleteDiploCommand', {'diploId': did, 'baseStackCommand': err('diplo_end_success'), 'success': True})]

    def _diplo_drop(self, r):
        for cid in (r['from_clan'], r['to']):
            c = CLANS.get(cid)
            if c:
                c['diplomacy_requests'] = [x for x in c['diplomacy_requests'] if x['id'] != r['id']]

    def _diplo_set(self, a, b, kind, did, desc, frm):
        """Diplomacy between two clans (type 0: removed)."""
        for c, o in ((a, b), (b, a)):
            c['diplomacy'] = [x for x in c['diplomacy'] if x['clan'] != o['id']]
            if kind:
                c['diplomacy'].append({'id': did, 'clan': o['id'], 'name': o['name'], 'type': kind, 'date': stamp(), 'text': desc,
                                       'from_clan': frm})

    def diplo_sync(self, cid):
        """The other clan's copies and open windows; the two clans' ships again depending on the viewer (ortak_harita: the relation is in
        the signature)."""
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
            cur = next((d for d in k['diplomacy'] if d['clan'] == tid), None)
            if form == 3 and cur is not None and cur['type'] == 3:
                return fail('err_diplo_war_is_running')
            if form in (1, 2, 3) and cur is not None:
                return fail('err_diplo_isRunning', XXX=_res('diplo_status%d' % cur['type']))
            if form == 0 and (cur is None or cur['type'] != 3):
                return fail('err_diplo_default')
            if any(r['from_clan'] == k['id'] and r['to'] == tid for r in k['diplomacy_requests']):
                return fail('err_diplo_applyIsRunning')
            if any(r['from_clan'] == tid and r['to'] == k['id'] for r in k['diplomacy_requests']):
                return fail('err_clan_diploRequest_exist')
            if form == 3 and sum(d['type'] == 3 and d['from_clan'] == k['id'] for d in k['diplomacy']) >= MAX_WARS:
                return fail('err_diplo_default')
            if form == 3 and k['treasury'] < WAR_COST:
                # the cost is from the clan treasury (the client's text also says "your clan does not have enough credits"); the player
                # thought it was their own credits (player report 2026-10-30): the amount in the treasury and the required amount follow
                # in the message
                from shop import stack_extra
                return [('ClanNewDiplomacyCommand', {'errorMsg': stack_extra('err_clan_no_money', ' ({:,} / {:,} Credits)'.format(
                                                                          int(k['treasury']), WAR_COST)),
                                                     'success': False, 'clanDiploReqInfoCommand': None})]
            did = _no()
            if form == 3:                                   # war at once: the cost from the treasury, 10 days
                k['treasury'] -= WAR_COST
                self._diplo_set(k, t, 3, did, desc, k['id'])
                for c in (k, t):
                    c['diplomacy'][-1]['end_time'] = time.time() + WAR_DAYS * 86400
                self.add_news('war2', '', k, other=t['name'])
                self.add_news('war', '', t, other=k['name'])
                r = {'id': did, 'from_clan': k['id'], 'to': tid, 'type': 3, 'date': stamp(), 'text': desc}
            else:
                r = {'id': did, 'from_clan': k['id'], 'to': tid, 'type': form, 'date': stamp(), 'text': desc}
                k['diplomacy_requests'].append(r)
                t['diplomacy_requests'].append(dict(r))
            cmd = self.diplo_req_cmd(r, k)
        self.changed(k, push=form == 3)
        self.diplo_sync(tid)
        self.log('   diplomacy: [%s] -> [%s] type %d' % (k['tag'], t['tag'], form))
        out = [('ClanNewDiplomacyCommand', {'errorMsg': err('clan_newDiploOffer' if form != 3 else 'empty'), 'success': True,
                                            'clanDiploReqInfoCommand': cmd})]
        if form == 3:                                       # the client adds the reply to the requests: for war to the diplomacies (the whole list)
            out.append(('LoginInitClanCommand', {'clanAllInfoCommand': self.all_info()}))
        return out

    def diplo_answer(self, k, did, status):
        """ClanEditDiploOfferRequest {status 'allow'/'deny'}: reply to an incoming request (on 'allow' the client moves the request to the
        diplomacies)."""
        allow = status == 'allow'
        fail = lambda key: [('ClanEditDiploOfferCommand', {'status': status, 'success': False, 'clanDiploInfoCommand': None,
                                                           'stack': err(key), 'clanDiploReqInfoCommand': None})]
        with LOCK:
            r = next((x for x in k['diplomacy_requests'] if x['id'] == did and x['to'] == k['id']), None)
            if r is None:
                return fail('err_diplo_default')
            if not self.right(DIPLO_RIGHTS.get(r['type'], 'diplo_start'), k):
                return fail('err_clan_noRights')
            o = CLANS.get(r['from_clan'])
            req = self.diplo_req_cmd(r, k)
            self._diplo_drop(r)
            info = None
            if allow and o is not None:
                self._diplo_set(k, o, r['type'], did, r['text'], o['id'])
                if r['type'] == 0:                          # war ended
                    self.add_news('peace', '', o, other=k['name'])
                    self.add_news('peace2', '', k, other=o['name'])
                else:
                    info = self.diplo_cmd(next(d for d in k['diplomacy'] if d['clan'] == o['id']))
            oname = (o or {}).get('name', '')
        self.changed(k, push=False)
        if o is not None:
            self.diplo_sync(o['id'])
        key = ('diplo_new_allow' if allow else 'diplo_new_deny')
        args = {'XXX': oname, 'YYY': _res('diplo_status%d' % r['type'])} if allow else {'XXX': oname}
        out = [('ClanEditDiploOfferCommand', {'status': status, 'success': True, 'clanDiploInfoCommand': info, 'stack': err(key, **args),
                                              'clanDiploReqInfoCommand': req})]
        if allow and info is None:
            out.append(('LoginInitClanCommand', {'clanAllInfoCommand': self.all_info()}))
        return out

    # -------------------------------------------------------- chat
    def rooms(self):
        k = self.p.d.get('clan')
        return [('clan', 'clan', str(k['id']))] if k else []
