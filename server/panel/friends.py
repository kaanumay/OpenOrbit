"""Play with Friends (panel): setting up a friend server (Host) and joining a friend's server (Join).

Host: the panel starts the game server with --multiplayer (server/multiplayer.py): the game (TCP 8081) and chat (TCP 7771) are listened on all
networks, the player enters the game with their own save. Guests send their saves through the game port; the server keeps them only in memory
(they do not appear on this computer's Saves page). Connected guests come from the game server's live_status.json; removing a guest is
via /yonetim/kick (only from this computer, with the panel's admin key for this start).
Join: the selected save is backed up and sent to the friend's server (POST /misafir/giris), web.py starts in a way that shows that server
(--remote), the client opens. While the game runs, every new version on the server (long poll, GET /misafir/profil) is written to its own
save slot; when the client closes (or Leave) the final state is fetched and written (POST /misafir/cikis) and the web server shuts down. The save always stays
on the guest's computer. If the session is left half-finished (the panel closed, power cut), the next join fetches the final state on the server using the 'friend' info
in the slot's slot.json; if the local save changed in the meantime (played alone), it is not touched.
"""
import gzip, json, os, re, secrets, socket, threading, time, zlib
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from lang import t as _, remote

GAME_PORT = 8081
CHAT_PORT = 7771
PROTOCOL = 2                    # server/multiplayer.PROTOCOL: version of the account submission (test_multi_player checks it)
LONG_POLL_SEC = 25                   # duration of the long poll
RESPONSE_LIMIT = 64 * 1024 * 1024
PUBLIC_IP_SERVICE = 'https://api.ipify.org'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None               # redirects are not followed (so the session and key do not go to another address): a 3xx reply becomes an HTTPError


OPENER = build_opener(ProxyHandler({}), _NoRedirect())   # so the system's proxy is not used to reach a server on the local network


class FriendError(Exception):
    """Error shown to the user."""


# ------------------------------------------------------------------ adresler
def resolve_address(text):
    """'192.168.1.20', '85.100.20.30:8081', 'home.example.com' -> (address, port)."""
    s = re.sub(r'^[a-z]+://', '', (text or '').strip(), flags=re.I).split('/')[0]
    m = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9.\-]*)(?::(\d{1,5}))?', s)
    if not m or not 0 < int(m.group(2) or GAME_PORT) < 65536:
        raise FriendError(_("Invalid address: enter your friend's IP address or domain name (e.g. 192.168.1.20 or 85.100.20.30)."))
    return m.group(1), int(m.group(2) or GAME_PORT)


def ip_kind(ip):
    """local (home network / ZeroTier), radmin (Radmin VPN), tailscale, link (link-local only), public."""
    a = [int(x) for x in ip.split('.')]
    if a[0] == 26:
        return 'radmin'
    if a[0] == 100 and 64 <= a[1] < 128:
        return 'tailscale'
    if a[0] == 10 or (a[0] == 172 and 16 <= a[1] < 32) or (a[0] == 192 and a[1] == 168):
        return 'local'
    if a[0] == 169 and a[1] == 254:
        return 'connection'
    return 'general'


def local_ips():
    """This computer's IPv4 addresses (the default route's first) -> [{'ip', 'tur'}]."""
    out = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))               # UDP: no packet is sent, only the local address is chosen
            out.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = ai[4][0]
            if ip not in out:
                out.append(ip)
    except OSError:
        pass
    return [{'ip': ip, 'type': ip_kind(ip)} for ip in out if not ip.startswith(('127.', '0.'))]


def public_ip():
    """The address on the internet (only on request; PUBLIC_IP_SERVICE is asked)."""
    try:
        ip = OPENER.open(PUBLIC_IP_SERVICE, timeout=6).read(64).decode('ascii', 'replace').strip()
    except (OSError, ValueError):
        raise FriendError(_('Public IP not found: no internet connection or the service did not reply.'))
    if not re.fullmatch(r'\d{1,3}(\.\d{1,3}){3}', ip):
        raise FriendError(_('Public IP not found: no internet connection or the service did not reply.'))
    return ip


# ------------------------------------------------------------------ HTTP to the friend's server (game port)
def request(host, port, method, path, body=None, timeout=10):
    """-> (status code, JSON). FriendError if it cannot connect or the reply is not from a friend server."""
    data, hdr = None, {'Accept-Encoding': 'gzip'}
    if body is not None:
        data = gzip.compress(json.dumps(body, ensure_ascii=False).encode('utf8'), 6)
        hdr.update({'Content-Type': 'application/json', 'Content-Encoding': 'gzip'})
    req = Request('http://%s:%d%s' % (host, port, path), data=data, headers=hdr, method=method)
    try:
        r = OPENER.open(req, timeout=timeout)
        code = r.status
    except HTTPError as e:
        r, code = e, e.code
    except (URLError, OSError) as e:
        reason = getattr(e, 'reason', e)
        raise FriendError(_("Could not connect to %s:%d (%s). Is your friend's server running and are the ports open?", host, port, reason))
    try:
        raw = r.read(RESPONSE_LIMIT + 1)
        if r.headers.get('Content-Encoding') == 'gzip':
            z = zlib.decompressobj(16 + zlib.MAX_WBITS)
            raw = z.decompress(raw, RESPONSE_LIMIT)
        if r.headers.get('X-DarkOrbit') != 'arkadas':
            raise ValueError('no header')
        out = json.loads(raw.decode('utf8'))
    except (OSError, ValueError, zlib.error):
        raise FriendError(_('%s:%d is not a DarkOrbit friend server (or the reply was cut off).', host, port))
    return code, (out if isinstance(out, dict) else {})


def _message(code, out):
    return remote(out) or out.get('message') or _('The server refused the request (HTTP %s).', code)


# ------------------------------------------------------------------ panel side
class Friend:
    def __init__(self, cfg, saves, direction, log, code):
        self.cfg, self.saves, self.direction, self.log, self.code = cfg, saves, direction, log, code
        self.key = secrets.token_urlsafe(24)       # admin key (given to the server on this panel start)
        self.local = secrets.token_urlsafe(24)         # the session of the server's own player (the game server and its own web.py)
        self.lock = threading.RLock()
        self.general = None
        self.m = self._empty()

    @staticmethod
    def _empty():
        return {'state': 'none', 'steps': [], 'error': None, 'address': None, 'record': None, 'server': None, 'session': None,
                'uid': None, 'version': 0, 'last_sync': None, 'connection': True, 'not': None, 'end_time': None}

    # ------------------------------------------------------------ host
    def host_env(self):
        """The game server's OO_MULTIPLAYER environment variable (multiplayer.configure)."""
        return json.dumps({'password': self.cfg.get('friend_password'), 'max_count': self.cfg.get('friend_max'),
                           'key': self.key, 'code': self.code, 'local': self.local})

    def host_status(self, live):
        is_open = self.direction.running() and self.direction.friend
        friends = (live or {}).get('friend') or {}
        return {'on': is_open, 'ips': local_ips(), 'public_ip': self.general, 'game_port': GAME_PORT, 'chat_port': CHAT_PORT,
                'password': self.cfg.get('friend_password'), 'max_count': self.cfg.get('friend_max'),
                'guests': friends.get('guests', []) if is_open else []}

    def find_public_ip(self):
        self.general = public_ip()
        return self.general

    def at(self, session):
        if not (self.direction.running() and self.direction.friend):
            raise FriendError(_('The friend server is not running.'))
        code, out = request('127.0.0.1', GAME_PORT, 'POST', '/yonetim/kick', {'key': self.key, 'session': str(session or '')})
        if code != 200:
            raise FriendError(_('Guest not found: they may have already left.'))
        self.log('friend server: guest removed (%s)' % str(session)[:8])

    # ------------------------------------------------------------ guest
    def active(self):
        return self.m['state'] in ('connecting', 'in_game', 'leaving')

    def in_use(self, slot):
        return self.active() and self.m['record'] == slot

    def state(self):
        with self.lock:
            m = dict(self.m)
        m.pop('key', None)
        m['last_address'] = self.cfg.get('friend_last_address')
        return m

    def attempt(self, address):
        """Info about the friend's server (before connecting)."""
        host, port = resolve_address(address)
        code, info = request(host, port, 'GET', '/misafir/bilgi', timeout=6)
        if code != 200 or info.get('sunucu') != 'darkorbit':
            raise FriendError(_('%s:%d is not a DarkOrbit friend server (or the reply was cut off).', host, port))
        info.update(address='%s:%d' % (host, port), compatible=info.get('protokol') == PROTOCOL)
        return info

    def _step(self, text, state='running'):
        a = self.m['steps']
        if a and a[-1]['state'] == 'running':
            a[-1]['state'] = 'done'
        a.append({'text': text, 'state': state, 'time': time.strftime('%H:%M:%S')})

    def killer(self, address, password, slot, client_version, open_client):
        """Starts joining (in the background). open_client: the function that opens the client (panel)."""
        host, port = resolve_address(address)
        with self.lock:
            if self.active():
                raise FriendError(_("You are already on a friend's server."))
            self.m = self._empty()
            self.m.update(state='connecting', address='%s:%d' % (host, port), record=slot)
        self.cfg.update({'friend_last_address': address.strip()})
        threading.Thread(target=self._join, args=(host, port, password, slot, client_version, open_client), daemon=True).start()
        return self.state()

    def _join(self, host, port, password, slot, client_version, open_client):
        m = self.m
        try:
            self._step(_("Checking your friend's server"))
            info = self.attempt('%s:%d' % (host, port))
            m['server'] = info
            if not info['compatible']:
                raise FriendError(_("Your friend's panel is a different version (account upload %s, yours %s): both of you should update the panel.",
                                      info.get('protokol'), PROTOCOL))
            if info.get('client') and info['client'] != client_version:
                raise FriendError(_("Game versions differ: your friend's server %s, your client %s.", info['client'], client_version))
            if not info.get('place'):
                raise FriendError(_('Server full (at most %s guests).', info.get('max_count')))
            self._partial_session(slot)
            self._step(_('Backing up the save'))
            self.saves.backup(slot, 'auto', _("Before joining a friend's server"))
            with open(self.saves.profile(slot), encoding='utf8') as fh:
                d = json.load(fh)
            m['original_uid'] = d['pilot']['userId']
            self._step(_('Uploading account'))
            key = secrets.token_urlsafe(24)
            code, r = request(host, port, 'POST', '/misafir/giris', {'version': PROTOCOL, 'password': password or '', 'key': key,
                                                                    'address': host, 'profile': d}, timeout=60)
            if code != 200:
                raise FriendError(_message(code, r))
            m.update(session=r['session'], key=key, uid=r['uid'], version=r['version'], file=self._file(slot))
            self._mark(slot)
            self.log('joined friend server: %s:%d (save %s, id on the server %s)' % (host, port, slot, r['uid']))
            self._step(_('Preparing web login'))
            self.direction.start_guest_web(self.saves.profile(slot), slot, [
                '--remote=%s:%d' % (host, port), '--chat=%s:%d' % (host, CHAT_PORT), '--session=%s' % r['session'], '--uid=%d' % r['uid']])
            threading.Thread(target=self._sync, args=(host, port, slot, r['session'], key), daemon=True).start()
            self._step(_('Opening the game'))
            open_client()
            m['state'] = 'in_game'
            self._step(_("You are on your friend's server: have a good flight!"), 'done')
        except Exception as e:
            m['error'] = str(e) if isinstance(e, (FriendError, RuntimeError, OSError)) else _('Unexpected error: %r', e)
            self._step(m['error'], 'error')
            self.log('error joining friend: %r' % e)
            if m.get('session'):
                self._finish(silent=True)
            else:
                m['state'] = 'error'

    # ------------------------------------------------------------ syncing
    def _file(self, slot):
        st = os.stat(self.saves.profile(slot))
        return [st.st_mtime_ns, st.st_size]

    def _mark(self, slot):
        """The slot's slot.json: the ongoing session (if left half-finished the next join fetches the final state) and the last written state of the file."""
        m = self.m
        self.saves.set_meta(slot, friend={'address': m['address'], 'session': m['session'], 'key': m['key'], 'version': m['version'],
                                         'uid': m['original_uid'], 'file': m['file']})

    def _write(self, slot, d, version):
        """Writes the new version on the server to the slot (not if it is older or another player's save)."""
        with self.lock:
            m = self.m
            if version <= m['version']:
                return
            if not (isinstance(d, dict) and isinstance(d.get('pilot'), dict) and isinstance(d.get('ship'), dict)
                    and isinstance(d.get('position'), dict)) or d['pilot'].get('userId') != m['original_uid']:
                self.log('friend server: invalid save version %s ignored' % version)
                return
            p = self.saves.profile(slot)
            tmp = p + '.arkadas.tmp'
            with open(tmp, 'w', encoding='utf8') as fh:
                json.dump(d, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            for k in range(6):                        # if the panel or an antivirus scanner is reading it at that moment
                try:
                    os.replace(tmp, p)
                    break
                except PermissionError:
                    if k == 5:
                        raise
                    time.sleep(0.2)
            m['version'], m['last_sync'], m['file'] = version, time.time(), self._file(slot)
            if m.get('session'):
                self._mark(slot)

    def _sync(self, host, port, slot, session, key):
        """While the session lasts, writes the new versions on the server to the slot (long poll)."""
        m = self.m
        while m.get('session') == session and m['state'] in ('connecting', 'in_game'):
            try:
                code, r = request(host, port, 'GET', '/misafir/profil?session=%s&key=%s&version=%d&wait=%d' % (
                    quote(session), quote(key), m['version'], LONG_POLL_SEC), timeout=LONG_POLL_SEC + 20)
            except FriendError:
                m['connection'] = False
                time.sleep(3)
                continue
            m['connection'] = True
            if m.get('session') != session or m['state'] == 'leaving':
                return
            if code == 200 and r.get('profile'):
                try:
                    self._write(slot, r['profile'], int(r.get('version') or 0))
                except OSError as e:
                    self.log('friend server: could not write save: %r' % e)
            if code == 404 or (code == 200 and r.get('finished')):
                m['not'] = _("Your friend's server ended the session (it shut down or removed you). Your save is on your computer in its latest state.")
                if not self.direction.client_alive():
                    self._finish()
                return
            if code != 200:
                time.sleep(3)

    # ------------------------------------------------------------ leaving
    def client_closed(self):
        """The panel's client-close job: if in a guest session, leave -> True (the panel does not shut the servers down)."""
        if not self.active() or not self.m.get('session'):
            return False
        threading.Thread(target=self._finish, daemon=True).start()
        return True

    def detach(self):
        """Leave button: if the client is open it is closed (the close job leaves), otherwise leave immediately."""
        if not self.active():
            raise FriendError(_("You are not on a friend's server."))
        if self.direction.client_alive():
            self.direction.stop_client()
        else:
            threading.Thread(target=self._finish, daemon=True).start()

    def shutdown(self, sec=30):
        """The panel is closing: if a session is running, leave and wait until it finishes (at most sn seconds)."""
        if self.active() and self.m.get('session') and self.m['state'] != 'leaving':
            self._finish()
        end = time.time() + sec
        while self.active() and time.time() < end:
            time.sleep(0.1)

    def _finish(self, silent=False):
        m = self.m
        with self.lock:
            if m['state'] == 'leaving' or not m.get('session'):
                return
            m['state'] = 'leaving'
        slot = m['record']
        host, port = resolve_address(m['address'])
        reached = False
        try:
            code, r = request(host, port, 'POST', '/misafir/cikis', {'session': m['session'], 'key': m['key']}, timeout=30)
            if code == 200 and r.get('profile'):
                self._write(slot, r['profile'], int(r.get('version') or 0))
            reached = True
        except (FriendError, OSError) as e:
            self.log('leaving friend server: could not fetch final state: %r' % e)
            if not m['not']:
                m['not'] = _('Could not reach the server: your save stays as of the last sync.')
        try:
            self.direction.stop_servers()                     # the guest's web server
        finally:
            with self.lock:
                m['session'], m['end_time'] = None, time.time()
                if m['state'] == 'leaving':
                    m['state'] = 'error' if silent else 'finished'
            try:
                if reached:                              # if unreachable it stays: the next join fetches the final state (_half_session)
                    self.saves.set_meta(slot, friend=None)
            except OSError:
                pass
        self.log('left friend server (save %s, version %s)' % (slot, m['version']))

    def _partial_session(self, slot):
        """An old half-finished session (slot.json 'arkadas'): if it is still running on the server it ends; if the local save has not changed since then,
        the final state on the server is written."""
        a = self.saves.meta(slot).get('friend')
        if not isinstance(a, dict) or not a.get('session'):
            return
        self._step(_('Closing an unfinished session'))
        try:
            host, port = resolve_address(a.get('address'))
            code, r = request(host, port, 'POST', '/misafir/cikis', {'session': a['session'], 'key': a.get('key')}, timeout=20)
            d = r.get('profile')
            if code == 200 and d and int(r.get('version') or 0) > int(a.get('version') or 0) and self._file(slot) == a.get('file') \
                    and isinstance(d.get('pilot'), dict) and d['pilot'].get('userId') == a.get('uid'):
                self.m.update(version=int(a.get('version') or 0), original_uid=a.get('uid'))
                self._write(slot, d, int(r['version']))
                self.log('final state of the half-finished friend session written to the save (%s)' % slot)
        except (FriendError, OSError, ValueError, TypeError) as e:
            self.log('could not close the half-finished friend session: %r' % e)
        self.m['version'] = 0
        self.saves.set_meta(slot, friend=None)
