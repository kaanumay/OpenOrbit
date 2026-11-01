"""Rehber (istemcinin Kişiler penceresi, ContactsComponentSystem; posta penceresinin kişiler sekmesi): arkadaşlık isteği, kabul,
ret, isteği geri alma, arkadaşı silme, engelleme ve "davetleri engelle".

Arkadaş sunucusunda istekler öteki oyuncunun kaydına da yazılır (bağlı değilse kaydı sunucuda durdukça); tek oyunculuda yalnız
oyuncunun kendisi var. Rehber profilde ada göre tutulur (misafirin sunucudaki kimliği her katılmada başka): arkadas, gelen (bekleyen
istek), giden (gönderilen istek), reddeden (isteği reddedilen), engelli. Pencerenin satırı (ContactListEntryModule) oyuncunun
kimliğiyle; sunucuda olmayan kişiye addan türetilen sabit kimlik verilir (sahte_kimlik). Bir kişi birden çok türde olabilir
(ContactListEntryTypeCommand.contactEntryTypes).
İstemci her istekten sonra pencereyi kilitler, ContactUiUnblockCommand gelince açar. Listedeki değişiklik: kaldırılanlar
ContactListRemoveContactsCommand, eklenen ve değişenler ContactListUpdateContactsCommand (gelen istekte istemci bildirim gösterir);
çevrimiçi, harita ve seviye GUNCELLEME_SN'de bir yoklanır. Günlük metinleri istemcinin (log_msg_contact_*).
"""
import threading, time, zlib
import community as TP
from cbs import stm

UPDATE_SEC = 2.0
REQUESTS = {'ContactRequest', 'ContactListRequest', 'ContactListSettingsModule', 'ContactListBlockInvitationsModule'}
# ContactRequest.contactRequestType
CREATE, ACCEPT, REJECT, DELETE_REQUEST, REMOVE_FRIEND, BLOCK, UNBLOCK = range(7)
# ContactListEntryTypeModule.entryType
FRIEND, CLAN, INCOMING, OUTGOING, REJECTED, BLOCKED = range(6)
LISTS = (('friend', FRIEND), ('incoming', INCOMING), ('outgoing', OUTGOING), ('declined', REJECTED), ('blocked', BLOCKED))
FILTER = {'showClanMembers': True, 'showRequests': True, 'showFriends': True, 'showBlacklistPlayers': False}

LOCK = threading.RLock()
LAST = {}                      # oyuncu kimliği -> {satır kimliği: (ad, ContactListEntryModule)}: istemcinin son gördüğü liste
_thread = None


def mod(_cls, **f):
    return dict(_=_cls, **f)


def save(p):
    import name_log as NL
    NL.apply_profile(p)                                  # panelde adı değişen ya da silinen botlar (ad_kaydi.py)
    with p.lock:
        return _registry(p)


def _registry(p):
    """Profilin rehberi (p.lock altında)."""
    r = p.d.setdefault('contacts', {})
    for target_name, _ in LISTS:
        r.setdefault(target_name, [])
    r.setdefault('invite_block', False)
    r.setdefault('filters', dict(FILTER))
    return r


def _var(lst, target_name):
    return any(x.lower() == target_name.lower() for x in lst)


def _add(p, entries, target_name):
    with p.lock:
        lst = _registry(p)[entries]
        if not _var(lst, target_name):
            lst.append(target_name)
            p.dirty = True


def _remove(p, entries, target_name):
    with p.lock:
        lst = _registry(p)[entries]
        remaining = [x for x in lst if x.lower() != target_name.lower()]
        if len(remaining) != len(lst):
            lst[:] = remaining
            p.dirty = True


def fake_id(target_name):
    """Sunucuda olmayan kişinin satır kimliği (addan; misafirlerin 2,0-2,1 milyar aralığının ve gerçek kimliklerin dışında)."""
    return 2150000000 + zlib.crc32(target_name.lower().encode('utf8')) % 100000000


# ------------------------------------------------------------ liste
def lines(p, people):
    """Rehberin satırları: kimlik -> (ad, ContactListEntryModule)."""
    import clan as KL
    r = save(p)
    names = {}
    for entries, kind in LISTS:
        for target_name in r[entries]:
            names.setdefault(target_name.lower(), [target_name, []])[1].append(kind)
    c = KL.clan_of(p)                                    # klan üyeleri (istemcinin "Clan members" süzgeci)
    for low, u in (c or {}).get('members', {}).items():
        if low != KL.name(p):
            names.setdefault(low, [u.get('name', low), []])[1].append(CLAN)
    by_name = {k.name.lower(): k for k in people.values()}
    out = {}
    for low, (target_name, kinds) in names.items():
        k = by_name.get(low)
        uid = k.uid if k is not None else fake_id(target_name)
        attrs = [mod('ContactListEntryAttributeNameModule', userName=k.name if k is not None else target_name),
                 mod('ContactListEntryAttributeOnlineModule', online=k is not None and k.session is not None)]
        if k is not None:
            pl = k.profile.d['pilot']
            attrs += [mod('ContactListEntryAttributeMapModule', currentMap=int(k.profile.d['position'].get('mapId', 0))),
                      mod('ContactListEntryAttributeLevelModule', level=int(pl.get('level', 1))),
                      mod('ContactListEntryAttributeClanTagModule', clanTag=str(pl.get('clanTag', ''))),
                      mod('ContactListEntryAttributeClanModule', clanId=int(pl.get('clanId', 0) or 0)),
                      mod('ContactListEntryAttributeClanRelationModule', clanRelation=mod('ClanRelationModule', type=KL.relation(p, k.profile)))]
        out[uid] = (target_name, mod('ContactListEntryModule',
                            typeCommand=mod('ContactListEntryTypeCommand', userId=uid,
                                            contactEntryTypes=[mod('ContactListEntryTypeModule', entryType=t) for t in sorted(kinds)]),
                            attributeCommand=mod('ContactListEntryAttributeCommand', userId=uid, attributes=attrs)))
    return out


def login_cmd(p):
    """Girişteki ContactListInitializationCommand (kayıttaki boş listenin yerine)."""
    r = save(p)
    with LOCK:
        cur = lines(p, TP.all_())
        LAST[p.user_id] = cur
    launch()
    return ('ContactListInitializationCommand', {
        'blockInvitations': mod('ContactListBlockInvitationsModule', blockAllInvitations=bool(r['invite_block'])),
        'filterSettings': mod('ContactListSettingsModule', **dict(FILTER, **r['filters'])),
        'contactsCommand': mod('ContactListUpdateContactsCommand', contacts=[e for _, e in cur.values()])})


def refresh(k, people=None):
    """Oyuncunun istemcisindeki listeyi profildekine getiren mesajlar (değişen yoksa boş)."""
    with LOCK:
        cur = lines(k.profile, people if people is not None else TP.all_())
        old = LAST.get(k.uid)
        if old is None:                  # liste henüz gönderilmedi (giriş demeti gitmeden)
            return []
        LAST[k.uid] = cur
    msgs = []
    gone = sorted(set(old) - set(cur))
    if gone:
        msgs.append(('ContactListRemoveContactsCommand', {'contactUserIds': gone}))
    changed = [e for uid, (_, e) in cur.items() if old.get(uid, (None, None))[1] != e]
    if changed:
        msgs.append(('ContactListUpdateContactsCommand', {'contacts': changed}))
    return msgs


def forget(uid):
    """Oyuncunun bağlantısı kapandı: sonraki girişte liste baştan gider."""
    with LOCK:
        LAST.pop(uid, None)


# ------------------------------------------------------------ istekler
def handle(k, name, f):
    """İsteği yapan oyuncu (topluluk.Kisi) -> kendisine giden yanıt; karşı tarafın listesi doğrudan yenilenir."""
    p = k.profile
    if name == 'ContactListSettingsModule':
        with p.lock:
            _registry(p)['filters'] = {x: bool(f.get(x, v)) for x, v in FILTER.items()}
            p.dirty = True
        return []
    if name == 'ContactListBlockInvitationsModule':
        with p.lock:
            _registry(p)['invite_block'] = bool(f.get('blockAllInvitations'))
            p.dirty = True
        return [('ContactListBlockInvitationsModule', {'blockAllInvitations': save(p)['invite_block']})]
    if name == 'ContactListRequest':
        # posta penceresinin kişiler sekmesi: bekleyen istekler (type 1: Accept/Decline) ve arkadaşlar (type 0: sil, posta yaz;
        # istemcide denendi 2026-10-24)
        cur = LAST.get(k.uid) or lines(p, TP.all_())
        kind_of = lambda e, t: any(x['entryType'] == t for x in e['typeCommand']['contactEntryTypes'])
        rows = sorted(cur.items(), key=lambda x: x[1][0].lower())
        lst = [mod('ContactInvitationInfoCommand', type=1, userId=uid, userName=target_name, avatarURL='') for uid, (target_name, e) in rows
               if kind_of(e, INCOMING)] + \
              [mod('ContactFriendInfoCommand', type=0, userId=uid, userName=target_name, avatarURL='') for uid, (target_name, e) in rows if kind_of(e, FRIEND)]
        start = max(0, int(f.get('startIndex') or 0))
        return [('ContactListCommand', {'contactList': lst[start:start + 15], 'total': len(lst), 'startIndex': start})]
    kind = int(f.get('contactRequestType', -1))
    target_name = str(f.get('userName') or '').strip()
    if not target_name:                                 # istemci satırdan kimliğiyle gönderiyor: son gönderilen listeden ada
        target_name = (LAST.get(k.uid) or {}).get(f.get('userId'), ('', None))[0]
    b = TP.find(name=target_name) if target_name else None
    if b is not None:
        target_name = b.name
    out, to_other = [], []
    r = save(p)
    if kind == CREATE:
        if b is None or b.uid == k.uid:
            out.append(stm('msg_grp_inv_err_candidate_nonexistant'))
        elif _var(r['friend'], target_name):
            out.append(stm('log_msg_err_already_contact', NAME=target_name))
        elif _var(r['outgoing'], target_name):
            out.append(stm('log_msg_err_already_requested', NAME=target_name))
        elif _var(r['incoming'], target_name):             # o da istek göndermiş: kabul sayılır
            return handle(k, name, dict(f, contactRequestType=ACCEPT, userName=target_name))
        else:
            _remove(p, 'declined', target_name)
            _add(p, 'outgoing', target_name)
            rb = save(b.profile)
            if not rb['invite_block'] and not _var(rb['blocked'], k.name):    # engelleyen görmez
                _add(b.profile, 'incoming', k.name)
            out.append(stm('log_msg_contact_invite_sent', NAME=target_name))
    elif kind == ACCEPT and _var(r['incoming'], target_name):
        _remove(p, 'incoming', target_name)
        _add(p, 'friend', target_name)
        out.append(stm('log_msg_contact_added', NAME=target_name))
        if b is not None:
            _remove(b.profile, 'outgoing', k.name)
            _remove(b.profile, 'declined', k.name)
            _add(b.profile, 'friend', k.name)
            to_other.append(stm('log_msg_contact_added', NAME=k.name))
    elif kind == REJECT and _var(r['incoming'], target_name):
        _remove(p, 'incoming', target_name)
        if b is not None and _var(save(b.profile)['outgoing'], k.name):
            _remove(b.profile, 'outgoing', k.name)
            _add(b.profile, 'declined', k.name)
            to_other.append(stm('log_msg_contact_declined', NAME=k.name))
    elif kind == DELETE_REQUEST:
        _remove(p, 'outgoing', target_name)
        _remove(p, 'declined', target_name)
        if b is not None:
            _remove(b.profile, 'incoming', k.name)
    elif kind == REMOVE_FRIEND and _var(r['friend'], target_name):
        _remove(p, 'friend', target_name)
        out.append(stm('log_msg_contact_removed', NAME=target_name))
        if b is not None:
            _remove(b.profile, 'friend', k.name)
    elif kind == BLOCK and target_name and target_name.lower() != k.name.lower():
        for entries in ('friend', 'incoming', 'outgoing', 'declined'):
            _remove(p, entries, target_name)
        _add(p, 'blocked', target_name)
        out.append(stm('log_msg_contact_blocked', NAME=target_name))
        if b is not None:
            for entries in ('friend', 'incoming', 'outgoing'):
                _remove(b.profile, entries, k.name)
    elif kind == UNBLOCK and _var(r['blocked'], target_name):
        _remove(p, 'blocked', target_name)
        out.append(stm('log_msg_contact_unblocked', NAME=target_name))
    people = TP.all_()
    if b is not None and b.uid != k.uid:
        b.send(to_other + refresh(b, people), 'contacts')
    return out + refresh(k, people) + [('ContactUiUnblockCommand', {})]


# ------------------------------------------------------------ çevrimiçi, harita, seviye
def update():
    people = TP.all_()
    for k in people.values():
        if k.session is not None and k.uid in LAST:
            k.send(refresh(k, people), 'contacts')


def _loop():
    while True:
        time.sleep(UPDATE_SEC)
        try:
            update()
        except Exception:
            import traceback
            traceback.print_exc()


def launch():
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, name='contacts', daemon=True)
        _thread.start()
