"""Play with friends: the friend server and the guests' accounts (the panel's "Play with Friends" page, panel/friends.py).

Server: the panel starts game.py with --multiplayer. The game (8081) and chat (7771) ports listen on all networks; the web login
(80, 8090) stays local: each player logs in from the web.py on their own computer (a guest's points at this server with --remote). Settings
come from an environment variable (OO_MULTIPLAYER, JSON; so they do not show on the command line): password (join password; empty: none),
max_count (guest count), anahtar (the panel's management key), code (the panel's version: the guest's panel compares it), address (the listen
address; default 0.0.0.0, 127.0.0.1 in a live test on a single computer: so the firewall prompt does not appear). Players on the same
normal map share the aliens, boxes and ores and see each other (shared_maps.py); chat is shared.

Account upload: before entering the game, the guest's panel sends its save over the game port by HTTP (game.handle hands over here if the
first bytes are "GET "/"POST"; the game client's first packet starts with a length).
  GET  /misafir/bilgi                     the server's name, pilot, players, is a password needed, is there room
  POST /misafir/giris {version, password, anahtar, address, profile}  -> {session, uid, version, ongoing}
       The save is kept in the server's memory, not written to disk: it does not show on the server's Saves page. The player id is
       replaced with a temporary id so that it is unique on the server (most saves start with the same id from the seed), and reverts to
       the old one when given back (in the id fields: convert_ids). Logging in again with the same key (connection lost, panel reopened)
       continues the session and the latest state on the server. address: the address the guest uses to connect to this server (the chat's
  address comes from it). GET  /misafir/profil?session=&anahtar=&version=N&wait=25
       long poll: when a version newer than N of the save arrives (it saves every 10 s when the game changes; GuestProfile.save) or when
       the time is up -> {version, connected, finished, profile (if new)}. The guest's panel writes every new version to its own save slot.
  POST /misafir/cikis {session, anahtar}   -> the final state; the session ends (the game connection closes if the game is open), the save
is deleted shortly after Bodies are JSON; they may also be compressed with "Content-Encoding: gzip", and the response is compressed for
whoever sends "Accept-Encoding: gzip". Management (only from 127.0.0.1, with the panel's key): POST /yonetim/kick {anahtar, session}: kick
the guest. At login (LoginRequest) the client sends the sessionID given by the web login: for a guest it is the session key (find), for the
server's own player it is web.py's SESSION (SETTINGS['local']: the token the panel produced for this launch; only from this computer).
Wrong join passwords are limited per address (after ATTEMPT_LIMIT attempts a LOCK_SEC lock, 429).
When the server is shut down (the panel's "Stop") the guests' final state is published and given to pending polls (shutdown).

Multi-client (clients opened with the other saves on this computer after the panel's PLAY; panel/multi_client.py): the server is opened in
the same mode, accepts no guests (OO_MULTIPLAYER guest: false, address 127.0.0.1); on Host together with guests. Only from 127.0.0.1:
  POST /yerel/ekle {anahtar, record, route}  -> {session, uid, ongoing}: the slot's profile.json is loaded as an extra player (LocalProfile:
       written directly to the file; if its id equals another player's on the server, a stable temporary id per save in memory).
       If the same slot is added again (the client was reopened) the session continues. The main save, the same pilot name and a full
  server are rejected. POST /yerel/cikar {anahtar, session}     -> if connected the game connection closes, the final state is written, the
  slot is released GET  /yerel/oturum?session=              -> {uid, route, record}: web.py gives the extra client's login with this
"""
import collections, gzip, hmac, json, os, random, re, secrets, socket, threading, time, zlib
from urllib.parse import parse_qs, urlparse

import player_profile as PF
import paths as PTH

PROTOCOL = 2                    # version of the account upload: must be the same as the guest's panel (2: English save keys, 2026-11-01)
UID_LOWER, UID_UPPER = 2000000000, 2100000000     # the guests' temporary ids on the server (int32; do not mix with save ids)
BODY_LIMIT = 8 * 1024 * 1024   # account upload (saves ~0.4 MB); read before the password
ATTEMPT_LIMIT, LOCK_SEC = 5, 60  # wrong password per address: after this many attempts, a lock of this many seconds
HEADER_LIMIT = 64 * 1024
WAIT_MAX = 30
IDLE_SEC = 30 * 60              # not connected and not polling: the save is released after this long (the data is in the guest's panel)
END_SEC = 120                  # an ended session's final state can still be taken for this much longer (so a session that ends between polls is not lost)
CHAT_PORT = 7771

LOCAL_LOWER, LOCAL_UPPER = 2100000000, 2147000000     # temporary ids of the extra players (separate from the guests')
LOCAL_MAX = 16               # the server's limit (the panel's own limit is smaller: coklu_en_cok)

SETTINGS = {'on': False, 'password': '', 'max_count': 4, 'anahtar': None, 'code': '', 'address': '0.0.0.0', 'local': '', 'guest': True}
COND = threading.Condition()
GUESTS = {}                 # session key -> Guest
LOCAL_PLAYERS = {}                   # session key -> LocalPlayer (the multi-client's extra players)
FAILED = {}                     # address -> [wrong password count, end of the lock]
log = print


def equal(a, b):
    """Comparison of secret values (constant time; a non-ASCII character in a str used to raise TypeError)."""
    return hmac.compare_digest(str(a or '').encode('utf8'), str(b or '').encode('utf8'))


def configure(raw, logger=print):
    """game.main: if opened with --multiplayer (raw: the OO_MULTIPLAYER environment variable)."""
    global log
    log = logger
    try:
        d = json.loads(raw or '{}')
    except ValueError:
        d = {}
    # local: the session of the server's own player (the panel produces it on every launch, and gives it to its own web.py too). The fixed
    # 'localtest' was a passwordless login on a server opened through a tunnel (connections appear from 127.0.0.1)
    SETTINGS.update(on=True, password=str(d.get('password') or ''), max_count=max(1, min(16, int(d.get('max_count') or 4))),
                anahtar=d.get('anahtar') or None, code=str(d.get('code') or ''), address=str(d.get('address') or '0.0.0.0'),
                local=str(d.get('local') or '') or secrets.token_urlsafe(24), guest=bool(d.get('guest', True)))


def is_local(sid):
    """Is LoginRequest's sessionID the server's own player's."""
    return bool(SETTINGS['local']) and equal(sid, SETTINGS['local'])


def is_open():
    return SETTINGS['on']


# ------------------------------------------------------------------ guests
def convert_ids(x, old, new_):
    """Replaces the player ids in the save (in place): pilot, clan news and message ('kim'), mail (sender_id, alici_idler),
    auction, clan account (balanceUserId). Only in fields whose name is an id: money and counters are not touched."""
    if isinstance(x, dict):
        for k, v in x.items():
            has_id = k == 'who' or k.lower().endswith(('id', 'ids', 'idler'))
            if has_id and v == old and not isinstance(v, bool):
                x[k] = new_
            elif has_id and isinstance(v, list):
                x[k] = [new_ if (e == old and not isinstance(e, bool)) else e for e in v]
                for e in x[k]:
                    convert_ids(e, old, new_)
            else:
                convert_ids(v, old, new_)
    elif isinstance(x, list):
        for e in x:
            convert_ids(e, old, new_)


class GuestProfile(PF.Profile):
    """The guest's save: in memory instead of a file; every save (the game's 10 s save) publishes a new version (to the long poll)."""

    def __init__(self, seed, d, guest):
        self.guest = guest
        super().__init__(seed, path=os.path.join(PTH.LOGS, 'misafir_yok.json'), d=PF.SM.migrate_obj(d))   # the path is never written; the save of a guest with an old version to the new format

    def save(self, force=False):
        with self.lock:
            if not (self.dirty or force):
                return
            for k in range(5):                    # the session writes to the profile without a lock (like Profil.save)
                try:
                    text = json.dumps(self.d, ensure_ascii=False)
                    break
                except RuntimeError:
                    if k == 4:
                        raise
                    time.sleep(0.01)
            self.dirty = False
        self.guest.publish(text)


class Guest:
    def __init__(self, token, key, uid, original_uid, address, ip):
        self.token, self.key, self.uid, self.original_uid = token, key, uid, original_uid
        self.address, self.ip = address, ip
        self.profile = None
        self.text = None             # JSON of the last published save (with the id on the server)
        self.version = 0
        self.session = None           # connected game session (game.Session)
        self.entry = time.time()
        self.last = time.time()        # last poll or connection
        self.finished = False            # finished: cannot enter the game; the final state can be taken for BITIS_SN
        self.end_time = 0.0

    def publish(self, text):
        with COND:
            self.text, self.version = text, self.version + 1
            COND.notify_all()

    def export(self):
        """The save with the guest's own id (the guest's panel writes it to its slot)."""
        d = json.loads(self.text)
        convert_ids(d, self.uid, self.original_uid)
        return d

    def summary(self):
        p = self.profile.d if self.profile else {}
        pl = p.get('pilot') or {}
        return {'session': self.token[:8], 'name': pl.get('userName', '?'), 'level': pl.get('level', 1), 'ip': self.ip,
                'connected': self.session is not None, 'entry': int(self.entry)}


def _new_uid(full):
    while True:
        u = random.randrange(UID_LOWER, UID_UPPER)
        if u not in full:
            return u


def valid_profile(d):
    """Can the uploaded save be played -> error text or None."""
    if not isinstance(d, dict):
        return 'kayıt bir JSON nesnesi değil'
    pl, g, k = d.get('pilot'), d.get('ship'), d.get('position')
    if not (isinstance(pl, dict) and isinstance(g, dict) and isinstance(k, dict)):
        return 'kayıtta pilot, gemi ya da konum yok'
    if not isinstance(pl.get('userId'), int) or isinstance(pl.get('userId'), bool) or not str(pl.get('userName') or '').strip():
        return 'pilotun kimliği ya da adı yok'
    if not all(isinstance(k.get(a), (int, float)) for a in ('mapId', 'x', 'y')):
        return 'kayıttaki konum geçersiz'
    return None


def login(body, ip, seed, server_uid, main=None):
    """POST /misafir/giris -> (status code, response). main: the server's own profile (its name cannot be the same as another player's)."""
    if int(body.get('version') or 0) != PROTOCOL:
        return 409, {'error': 'version', 'message': 'Hesap gönderiminin sürümü farklı (sunucu %d): ikiniz de paneli güncelleyin.' % PROTOCOL}
    if SETTINGS['password']:
        now = time.time()
        with COND:
            h = FAILED.get(ip)
            if h and h[1] > now:
                return 429, {'error': 'wait', 'message': 'Çok fazla yanlış şifre: %d saniye sonra yeniden dene.' % (h[1] - now + 1)}
        if not equal(body.get('password'), SETTINGS['password']):
            with COND:
                h = FAILED.setdefault(ip, [0, 0])
                h[0] += 1
                if h[0] >= ATTEMPT_LIMIT:
                    h[:] = [0, now + LOCK_SEC]
                    log('friends: wrong password limit for %s, %d s lock' % (ip, LOCK_SEC))
            return 403, {'error': 'password', 'message': 'Katılma şifresi yanlış.'}
        with COND:
            FAILED.pop(ip, None)
    key = str(body.get('anahtar') or '')
    if len(key) < 16:
        return 400, {'error': 'anahtar', 'message': 'Misafir anahtarı eksik.'}
    with COND:
        old = next((m for m in GUESTS.values() if equal(m.key, key) and not m.finished), None)
        if old:                                  # logging in again: the latest state on the server continues
            old.last, old.ip = time.time(), ip
            old.address = str(body.get('address') or old.address)
            log('guest returned: %s (%s)' % (old.summary()['name'], ip))
            return 200, {'session': old.token, 'uid': old.uid, 'version': old.version, 'ongoing': True}
        if sum(1 for m in GUESTS.values() if not m.finished) >= SETTINGS['max_count']:
            return 503, {'error': 'full', 'message': 'Sunucu dolu (en çok %d misafir).' % SETTINGS['max_count']}
    d = body.get('profile')
    err = valid_profile(d)
    if err:
        return 400, {'error': 'profile', 'message': 'Kayıt geçersiz: %s.' % err}
    name = str((d.get('pilot') or {}).get('userName') or '').strip().lower()
    with COND:
        names = {_name(m.profile) for m in GUESTS.values() if not m.finished and m.profile is not None} |             {_name(y.profile) for y in LOCAL_PLAYERS.values()} | ({_name(main)} if main is not None else set())
    if name in names:                               # chat, mail, group, directory and clan find the player by name (like add_local)
        return 409, {'error': 'name', 'message': 'Sunucuda "%s" adlı bir pilot zaten var: aynı adla iki oyuncu sohbette, postada, grupta ve '
                                            'klanda karışır. Pilot adını değiştirip yeniden katıl.' % d['pilot']['userName']}
    with COND:
        uid = _new_uid({server_uid} | {m.uid for m in GUESTS.values()} | {y.uid for y in LOCAL_PLAYERS.values()})
        m = Guest(secrets.token_urlsafe(18), key, uid, d['pilot']['userId'], str(body.get('address') or ''), ip)
        convert_ids(d, m.original_uid, uid)
        m.profile = GuestProfile(seed, d, m)
        m.publish(json.dumps(m.profile.d, ensure_ascii=False))
        GUESTS[m.token] = m
    log('guest joined: %s (%s), id on the server %d' % (d['pilot'].get('userName'), ip, uid))
    return 200, {'session': m.token, 'uid': uid, 'version': m.version, 'ongoing': False}


def _guest(q):
    """The guest holding the session and key, or None."""
    with COND:
        m = GUESTS.get(str(q.get('session') or ''))
    if m and equal(m.key, q.get('anahtar')):
        return m
    return None


def poll_profile(q):
    """GET /misafir/profil: waits until a version newer than N arrives or the time runs out."""
    m = _guest(q)
    if not m:
        return 404, {'error': 'session', 'message': 'Bu sunucuda böyle bir misafir oturumu yok.'}
    try:
        have, wait = int(q.get('version') or 0), min(WAIT_MAX, max(0.0, float(q.get('wait') or 0)))
    except ValueError:
        return 400, {'error': 'request'}
    end = time.time() + wait
    with COND:
        while m.version <= have and not m.finished and time.time() < end:
            COND.wait(max(0.05, end - time.time()))
        m.last = time.time()
        out = {'version': m.version, 'connected': m.session is not None, 'finished': m.finished}
        new_ = m.version > have
    if new_:
        out['profile'] = m.export()
    return 200, out


def exit(q, close_session):
    """POST /misafir/cikis: if connected the game connection closes, the final state is given, the save is deleted."""
    m = _guest(q)
    if not m:
        return 404, {'error': 'session', 'message': 'Bu sunucuda böyle bir misafir oturumu yok.'}
    if not m.finished:
        finish(m, close_session, 'misafir ayrıldı')
    return 200, {'version': m.version, 'profile': m.export(), 'finished': True}


def finish(m, close_session, reason):
    s = m.session
    if s is not None:
        close_session(s)                           # publishes the last save as the session closes (game.Session.run)
        end = time.time() + 5
        while m.session is not None and time.time() < end:
            time.sleep(0.05)
    if m.profile:
        m.profile.save(force=True)
    with COND:
        m.finished, m.end_time = True, time.time()
        COND.notify_all()
    log('guest session ended (%s): %s' % (reason, m.summary()['name']))


def find(sid):
    """LoginRequest's sessionID -> guest (None if absent)."""
    with COND:
        m = GUESTS.get(str(sid or ''))
        return m if m and not m.finished else None


def entries():
    with COND:
        return [m for m in GUESTS.values() if not m.finished]


def tick(close_session):
    """Guest sessions that are not connected and have not been polled for a long time end, the saves of ended ones are released
    (game.autosave). Extra players too: released when the panel client closes (remove_local); if the panel closed, an extra player that
    does not connect is released after BOSTA_SN."""
    now = time.time()
    for m in entries():
        if m.session is None and now - m.last > IDLE_SEC:
            finish(m, close_session, 'uzun süre bağlanmadı')
    with COND:
        for k in [k for k, m in GUESTS.items() if m.finished and now - m.end_time > END_SEC]:
            del GUESTS[k]
    for y in local_players():
        if y.session is None and now - y.last > IDLE_SEC:
            finish_local(y, close_session, 'uzun süre bağlanmadı')


def shutdown(wait=2.0):
    """The server is closing: the guests' final state is published, polls are answered as finished; a short time for the panels to take it."""
    ms = entries()
    for m in ms:
        if m.profile:
            m.profile.save(force=True)
    with COND:
        for m in ms:
            m.finished, m.end_time = True, time.time()
        COND.notify_all()
    if ms:
        time.sleep(wait)


# ------------------------------------------------------------------ multi-client: the other saves on this computer
class LocalProfile(PF.Profile):
    """The extra player's save: the file of its own slot (written like Profil). If its id equals another player's on the server (saves
    start with the seed's id) it gets a stable temporary id per save in memory; it is written to the file with the real id (_metin)."""

    def __init__(self, seed, path, full, save):
        self.temporary = None
        super().__init__(seed, path=path)
        self.original_uid = self.user_id
        if self.original_uid in full:
            n = LOCAL_UPPER - LOCAL_LOWER
            u = LOCAL_LOWER + zlib.crc32(save.encode('utf8')) % n
            while u in full:
                u = LOCAL_LOWER + (u - LOCAL_LOWER + 1) % n
            self.temporary = u
            convert_ids(self.d, self.original_uid, u)

    def _text(self):
        if self.temporary is None:
            return super()._text()
        d = json.loads(json.dumps(self.d, ensure_ascii=False))
        convert_ids(d, self.temporary, self.original_uid)
        return json.dumps(d, ensure_ascii=False, indent=1)


class LocalPlayer:
    def __init__(self, token, save, route, profile):
        self.token, self.save, self.route, self.profile = token, save, route, profile
        self.session = None           # connected game session (game.Session)
        self.entry = self.last = time.time()
        self.finished = False            # being released: cannot enter; removed from the register when the connection closes (game.Session.run)

    @property
    def uid(self):
        return self.profile.user_id

    def summary(self):
        pl = self.profile.d.get('pilot') or {}
        return {'session': self.token[:8], 'record': self.save, 'name': pl.get('userName', '?'), 'level': pl.get('level', 1),
                'uid': self.uid, 'connected': self.session is not None, 'entry': int(self.entry)}


def _same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _name(profile):
    return str(((profile.d if profile else {}).get('pilot') or {}).get('userName') or '').strip().lower()


def add_local(body, seed, main):
    """POST /yerel/ekle -> (status code, response). main: the server's own profile (game.PROFILE)."""
    save, route = str(body.get('record') or ''), str(body.get('route') or '')
    if not re.fullmatch(r'[a-z0-9_]{1,40}', save) or os.path.basename(route) != 'profile.json' or not os.path.isfile(route):
        return 400, {'error': 'record', 'message': 'Kayıt bulunamadı.'}
    if not os.path.normcase(os.path.realpath(route)).startswith(os.path.normcase(os.path.realpath(PTH.SAVES)) + os.sep):
        return 400, {'error': 'record', 'message': 'Kayıt, kayıt klasöründe değil.'}
    if _same_path(route, main.path):
        return 409, {'error': 'main', 'message': 'Bu kayıt ana istemcide açık.'}
    with COND:
        old = next((y for y in LOCAL_PLAYERS.values() if _same_path(y.route, route)), None)
        if old and old.finished:
            return 409, {'error': 'closing', 'message': 'Bu kaydın önceki istemcisi kapanıyor: birkaç saniye sonra yeniden dene.'}
        if old:                                  # client reopened: the session on the server continues
            old.last = time.time()
            return 200, {'session': old.token, 'uid': old.uid, 'ongoing': True}
        if sum(1 for y in LOCAL_PLAYERS.values() if not y.finished) >= LOCAL_MAX:
            return 503, {'error': 'full', 'message': 'Sunucuda en çok %d ek istemci açılabilir.' % LOCAL_MAX}
        full = {main.user_id} | {m.uid for m in GUESTS.values() if not m.finished} | {y.uid for y in LOCAL_PLAYERS.values()}
    try:
        p = LocalProfile(seed, route, full, save)
    except (OSError, ValueError, KeyError, TypeError) as e:
        return 400, {'error': 'profile', 'message': 'Kayıt okunamadı: %s' % e}
    err = valid_profile(p.d)
    if err:
        return 400, {'error': 'profile', 'message': 'Kayıt geçersiz: %s.' % err}
    with COND:
        names = {_name(main)} | {_name(m.profile) for m in GUESTS.values() if not m.finished} | {_name(y.profile) for y in LOCAL_PLAYERS.values()}
        if _name(p) in names:                       # chat, mail, group and directory find the player by name
            return 409, {'error': 'name', 'message': 'Sunucuda "%s" adlı bir pilot zaten var: aynı adla iki oyuncu sohbette, postada ve '
                                                'grupta karışır. Bu kaydın pilot adını değiştir.' % p.d['pilot']['userName']}
        if any(_same_path(y.route, route) for y in LOCAL_PLAYERS.values()):
            return 409, {'error': 'closing', 'message': 'Bu kayıt az önce açıldı.'}
        y = LocalPlayer(secrets.token_urlsafe(18), save, route, p)
        LOCAL_PLAYERS[y.token] = y
    log('extra player: %s (save %s), id on the server %d%s' % (p.d['pilot'].get('userName'), save, y.uid,
                                                             ' (temporary; real %d)' % p.original_uid if p.temporary else ''))
    return 200, {'session': y.token, 'uid': y.uid, 'ongoing': False}


def finish_local(y, close_session, reason):
    """Release the extra player: its connection closes, the final state is written to the slot, removed from the register (if the
    connection does not close in 5 s the session does the exit)."""
    with COND:
        y.finished = True
    s = y.session
    if s is not None:
        close_session(s)                           # writes the final state as the session closes (game.Session.run)
        end = time.time() + 5
        while y.session is not None and time.time() < end:
            time.sleep(0.05)
    try:
        y.profile.save(force=True)
    except Exception as e:                        # noqa: BLE001 (file locked: the session has written the final save)
        log('extra player final save could not be written: %r' % e)
    with COND:
        if y.session is None:
            LOCAL_PLAYERS.pop(y.token, None)
    log('extra player released (%s): %s' % (reason, y.summary()['name']))


def remove_local(b, close_session):
    """POST /yerel/cikar."""
    with COND:
        y = LOCAL_PLAYERS.get(str(b.get('session') or ''))
    if not y:
        return 404, {'error': 'session', 'message': 'Bu sunucuda böyle bir ek oyuncu yok.'}
    finish_local(y, close_session, 'istemci kapandı')
    return 200, {'done': True}


def find_local(sid):
    """LoginRequest's sessionID -> extra player (None if absent or being released)."""
    with COND:
        y = LOCAL_PLAYERS.get(str(sid or ''))
        return y if y and not y.finished else None


def local_players():
    with COND:
        return [y for y in LOCAL_PLAYERS.values() if not y.finished]


# ------------------------------------------------------------------ send queue
class SendQueue:
    """The send queue of each connection on the friend server: sending under the world lock does not wait for the network (a slow guest
    must not stop the other players' loop). Order is kept; if the backlog exceeds SINIR the connection closes."""
    LIMIT = 16 * 1024 * 1024

    def __init__(self, sock):
        self.sock = sock
        self.cond = threading.Condition()
        self.parts = collections.deque()
        self.size = 0
        self.closed = False
        self.finish = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def put(self, data):
        with self.cond:
            if self.closed or self.finish:
                raise ConnectionError('connection closed')
            self.parts.append(data)
            self.size += len(data)
            if self.size > self.LIMIT:
                self._cut()
                raise ConnectionError('send queue full (client is not reading)')
            self.cond.notify()

    def run(self):
        while True:
            with self.cond:
                while not self.parts and not self.closed and not self.finish:
                    self.cond.wait()
                if self.closed:
                    return
                if not self.parts:             # finish: the rest has gone, the connection closes
                    self._cut(shutdown=True)
                    return
                data = b''.join(self.parts)
                self.parts.clear()
                self.size = 0
            try:
                self.sock.sendall(data)
            except OSError:
                with self.cond:
                    self._cut()
                return

    def close(self):
        """Close the connection when the queued items are gone (exit, kicking a guest)."""
        with self.cond:
            self.finish = True
            self.cond.notify()

    def _cut(self, shutdown=False):
        self.closed = True
        self.cond.notify_all()                   # let the waiting calis wake up (it used to get stuck on overflow)
        try:
            if shutdown:
                self.sock.shutdown(socket.SHUT_RDWR)
            else:
                self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------------------ HTTP (on the game port)
def is_http(first):
    return first[:4] in (b'GET ', b'POST', b'HEAD')


def _read(c):
    """-> (method, path, headers, body) or None."""
    buf = b''
    while b'\r\n\r\n' not in buf:
        d = c.recv(65536)
        if not d:
            return None
        buf += d
        if len(buf) > HEADER_LIMIT and b'\r\n\r\n' not in buf[:HEADER_LIMIT]:
            return None
    head, body = buf.split(b'\r\n\r\n', 1)
    lines = head.decode('latin-1').split('\r\n')
    try:
        method, path, _ = lines[0].split(' ', 2)
    except ValueError:
        return None
    hdr = {}
    for ln in lines[1:]:
        if ':' in ln:
            k, v = ln.split(':', 1)
            hdr[k.strip().lower()] = v.strip()
    n = int(hdr.get('content-length') or 0)
    if n < 0 or n > BODY_LIMIT:
        return None
    while len(body) < n:
        d = c.recv(min(1 << 20, n - len(body)))
        if not d:
            return None
        body += d
    if hdr.get('content-encoding') == 'gzip' and body:
        z = zlib.decompressobj(16 + zlib.MAX_WBITS)
        body = z.decompress(body, BODY_LIMIT)            # opened with a limit (compression bomb)
        if z.unconsumed_tail:
            return None
    return method, path, hdr, body


def _reply(c, code, obj, gz=False):
    data = json.dumps(obj, ensure_ascii=False).encode('utf8')
    extra = ''
    if gz and len(data) > 2048:
        data = gzip.compress(data, 6)
        extra = 'Content-Encoding: gzip\r\n'
    status = {200: 'OK', 400: 'Bad Request', 403: 'Forbidden', 404: 'Not Found', 409: 'Conflict', 429: 'Too Many Requests',
              503: 'Service Unavailable'}.get(code, 'OK')
    c.sendall(('HTTP/1.1 %d %s\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: %d\r\n%sConnection: close\r\n'
               'X-DarkOrbit: arkadas\r\n\r\n' % (code, status, len(data), extra)).encode('latin-1') + data)


def http(c, addr, game):
    """An HTTP request arriving at the game port (account upload and management). game: the game.py module."""
    try:
        c.settimeout(WAIT_MAX + 15)
        req = _read(c)
        if not req:
            return
        method, path, hdr, body = req
        u = urlparse(path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        gz = 'gzip' in hdr.get('accept-encoding', '')
        try:
            b = json.loads(body.decode('utf8') or '{}') if method == 'POST' else {}
        except ValueError:
            return _reply(c, 400, {'error': 'json'})
        if not isinstance(b, dict):
            return _reply(c, 400, {'error': 'json'})
        ip = addr[0]
        local = ip in ('127.0.0.1', '::1')
        management = local and SETTINGS['anahtar'] and equal(b.get('anahtar'), SETTINGS['anahtar'])
        if u.path.startswith('/misafir/') and not SETTINGS['guest']:
            code, out = 403, {'error': 'off', 'message': 'Bu sunucu misafir kabul etmiyor.'}
        elif u.path == '/yerel/ekle' and method == 'POST' and management:
            code, out = add_local(b, game.TEMPLATE.entry.get('seed'), game.PROFILE)
        elif u.path == '/yerel/cikar' and method == 'POST' and management:
            code, out = remove_local(b, game.close_session)
        elif u.path == '/yerel/oturum' and local:
            y = find_local(q.get('session'))
            code, out = (200, {'uid': y.uid, 'route': y.route, 'record': y.save}) if y else (404, {'error': 'session'})
        elif u.path == '/misafir/bilgi':
            code, out = 200, game.server_info()
        elif u.path == '/misafir/giris' and method == 'POST':
            code, out = login(b, ip, game.TEMPLATE.entry.get('seed'), game.PROFILE.user_id, game.PROFILE)
        elif u.path == '/misafir/profil':
            code, out = poll_profile(q)
        elif u.path == '/misafir/cikis' and method == 'POST':
            code, out = exit(b, game.close_session)
        elif u.path == '/yonetim/kick' and method == 'POST' and management:
            m = next((x for x in entries() if x.token.startswith(str(b.get('session') or '-'))), None)
            if m:
                finish(m, game.close_session, 'sunucu çıkardı')
            code, out = (200, {'done': True}) if m else (404, {'error': 'session'})
        else:
            code, out = 404, {'error': 'none'}
        if u.path not in ('/misafir/profil', '/yerel/oturum'):
            log('friends: %s %s <- %s -> %d' % (method, u.path, ip, code))
        _reply(c, code, out, gz)
    except (OSError, ValueError, zlib.error) as e:      # a broken gzip body too (it used to drop with no response)
        log('friends: request error %s: %r' % (addr[0], e))
    finally:
        try:
            c.close()
        except OSError:
            pass
