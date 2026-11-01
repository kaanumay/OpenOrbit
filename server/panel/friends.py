"""Arkadaşlarınla Oyna (panel): arkadaş sunucusu kurma (Host) ve arkadaşın sunucusuna katılma (Join).

Host: panel oyun sunucusunu --multiplayer ile başlatır (server/multiplayer.py): oyun (TCP 8081) ve sohbet (TCP 7771) bütün
ağlardan dinlenir, oyuncu kendi kaydıyla oyuna girer. Misafirler kayıtlarını oyun portundan gönderir; sunucu onları yalnız bellekte
tutar (bu bilgisayarın Kayıtlar sayfasında görünmez). Bağlı misafirler oyun sunucusunun canli_durum.json'undan; misafiri çıkarma
/yonetim/kick ile (yalnız bu bilgisayardan, panelin bu açılıştaki yönetim anahtarıyla).
Join: seçilen kayıt yedeklenir ve arkadaşın sunucusuna gönderilir (POST /misafir/giris), web.py o sunucuyu gösterecek biçimde
(--remote) başlar, istemci açılır. Oyun sürerken sunucudaki her yeni sürüm (uzun yoklama, GET /misafir/profil) kendi kayıt yuvasına
yazılır; istemci kapanınca (ya da Ayrıl) son hâl alınıp yazılır (POST /misafir/cikis) ve web sunucusu kapanır. Kayıt hep misafirin
bilgisayarında kalır. Oturum yarım kalırsa (panel kapandı, elektrik gitti) yuvanın kayit.json'undaki 'arkadas' bilgisiyle bir
sonraki katılmada sunucudaki son hâl alınır; yerel kayıt o arada değiştiyse (tek başına oynandı) dokunulmaz.
"""
import gzip, json, os, re, secrets, socket, threading, time, zlib
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from lang import t as _

GAME_PORT = 8081
CHAT_PORT = 7771
PROTOCOL = 2                    # server/multiplayer.PROTOCOL: hesap gönderiminin sürümü (test_cok_oyunculu denetler)
LONG_POLL_SEC = 25                   # uzun yoklamanın süresi
RESPONSE_LIMIT = 64 * 1024 * 1024
PUBLIC_IP_SERVICE = 'https://api.ipify.org'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None               # yönlendirme izlenmez (oturum ve anahtar başka adrese gitmesin): 3xx yanıt HTTPError olur


OPENER = build_opener(ProxyHandler({}), _NoRedirect())   # yerel ağdaki sunucuya sistemin vekil sunucusu (proxy) üzerinden gidilmesin


class FriendError(Exception):
    """Kullanıcıya gösterilen hata."""


# ------------------------------------------------------------------ adresler
def resolve_address(text):
    """'192.168.1.20', '85.100.20.30:8081', 'ev.ornek.com' -> (adres, port)."""
    s = re.sub(r'^[a-z]+://', '', (text or '').strip(), flags=re.I).split('/')[0]
    m = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9.\-]*)(?::(\d{1,5}))?', s)
    if not m or not 0 < int(m.group(2) or GAME_PORT) < 65536:
        raise FriendError(_("Invalid address: enter your friend's IP address or domain name (e.g. 192.168.1.20 or 85.100.20.30)."))
    return m.group(1), int(m.group(2) or GAME_PORT)


def ip_kind(ip):
    """yerel (ev ağı / ZeroTier), radmin (Radmin VPN), tailscale, baglanti (yalnız bağlantı-yerel), genel."""
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
    """Bu bilgisayarın IPv4 adresleri (varsayılan yolunki önce) -> [{'ip', 'tur'}]."""
    out = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))               # UDP: paket gitmez, yalnız yerel adres seçilir
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
    """İnternetteki adres (yalnız istenince; GENEL_IP_HIZMETI'ne sorulur)."""
    try:
        ip = OPENER.open(PUBLIC_IP_SERVICE, timeout=6).read(64).decode('ascii', 'replace').strip()
    except (OSError, ValueError):
        raise FriendError(_('Public IP not found: no internet connection or the service did not reply.'))
    if not re.fullmatch(r'\d{1,3}(\.\d{1,3}){3}', ip):
        raise FriendError(_('Public IP not found: no internet connection or the service did not reply.'))
    return ip


# ------------------------------------------------------------------ arkadaşın sunucusuna HTTP (oyun portu)
def request(host, port, method, path, body=None, timeout=10):
    """-> (durum kodu, JSON). Bağlanılamazsa ya da yanıt bir arkadaş sunucusunun değilse ArkadasHatasi."""
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
            raise ValueError('başlık yok')
        out = json.loads(raw.decode('utf8'))
    except (OSError, ValueError, zlib.error):
        raise FriendError(_('%s:%d is not a DarkOrbit friend server (or the reply was cut off).', host, port))
    return code, (out if isinstance(out, dict) else {})


def _message(code, out):
    return out.get('message') or _('The server refused the request (HTTP %s).', code)


# ------------------------------------------------------------------ panel tarafı
class Friend:
    def __init__(self, cfg, saves, direction, log, code):
        self.cfg, self.saves, self.direction, self.log, self.code = cfg, saves, direction, log, code
        self.key = secrets.token_urlsafe(24)       # yönetim anahtarı (bu panel açılışında sunucuya verilir)
        self.local = secrets.token_urlsafe(24)         # sunucunun kendi oyuncusunun oturumu (oyun sunucusu ve kendi web.py'si)
        self.lock = threading.RLock()
        self.general = None
        self.m = self._empty()

    @staticmethod
    def _empty():
        return {'state': 'none', 'steps': [], 'error': None, 'address': None, 'record': None, 'server': None, 'session': None,
                'uid': None, 'version': 0, 'last_sync': None, 'connection': True, 'not': None, 'end_time': None}

    # ------------------------------------------------------------ host
    def host_env(self):
        """Oyun sunucusunun OO_MULTIPLAYER ortam değişkeni (cok_oyunculu.configure)."""
        return json.dumps({'password': self.cfg.get('friend_password'), 'max_count': self.cfg.get('friend_max'),
                           'anahtar': self.key, 'code': self.code, 'local': self.local})

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
        code, out = request('127.0.0.1', GAME_PORT, 'POST', '/yonetim/kick', {'anahtar': self.key, 'session': str(session or '')})
        if code != 200:
            raise FriendError(_('Guest not found: they may have already left.'))
        self.log('arkadaş sunucusu: misafir çıkarıldı (%s)' % str(session)[:8])

    # ------------------------------------------------------------ misafir
    def active(self):
        return self.m['state'] in ('connecting', 'in_game', 'leaving')

    def in_use(self, slot):
        return self.active() and self.m['record'] == slot

    def state(self):
        with self.lock:
            m = dict(self.m)
        m.pop('anahtar', None)
        m['last_address'] = self.cfg.get('friend_last_address')
        return m

    def attempt(self, address):
        """Arkadaşın sunucusunun bilgisi (bağlanmadan önce)."""
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
        """Katılmayı başlatır (arka planda). istemci_ac: istemciyi açan işlev (panel)."""
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
            code, r = request(host, port, 'POST', '/misafir/giris', {'version': PROTOCOL, 'password': password or '', 'anahtar': key,
                                                                    'address': host, 'profile': d}, timeout=60)
            if code != 200:
                raise FriendError(_message(code, r))
            m.update(session=r['session'], anahtar=key, uid=r['uid'], version=r['version'], file=self._file(slot))
            self._mark(slot)
            self.log('arkadaş sunucusuna katılındı: %s:%d (kayıt %s, sunucudaki kimlik %s)' % (host, port, slot, r['uid']))
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
            self.log('arkadaşa katılma hatası: %r' % e)
            if m.get('session'):
                self._finish(silent=True)
            else:
                m['state'] = 'error'

    # ------------------------------------------------------------ eşitleme
    def _file(self, slot):
        st = os.stat(self.saves.profile(slot))
        return [st.st_mtime_ns, st.st_size]

    def _mark(self, slot):
        """Yuvanın kayit.json'u: süren oturum (yarım kalırsa sonraki katılmada son hâl alınır) ve dosyanın son yazılan hâli."""
        m = self.m
        self.saves.set_meta(slot, friend={'address': m['address'], 'session': m['session'], 'anahtar': m['anahtar'], 'version': m['version'],
                                         'uid': m['original_uid'], 'file': m['file']})

    def _write(self, slot, d, version):
        """Sunucudaki yeni sürümü yuvaya yazar (eskisi ya da başka oyuncunun kaydıysa yazmaz)."""
        with self.lock:
            m = self.m
            if version <= m['version']:
                return
            if not (isinstance(d, dict) and isinstance(d.get('pilot'), dict) and isinstance(d.get('ship'), dict)
                    and isinstance(d.get('position'), dict)) or d['pilot'].get('userId') != m['original_uid']:
                self.log('arkadaş sunucusu: geçersiz kayıt sürümü %s yok sayıldı' % version)
                return
            p = self.saves.profile(slot)
            tmp = p + '.arkadas.tmp'
            with open(tmp, 'w', encoding='utf8') as fh:
                json.dump(d, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            for k in range(6):                        # panel ya da virüs tarayıcısı o an okuyorsa
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
        """Oturum sürdükçe sunucudaki yeni sürümleri yuvaya yazar (uzun yoklama)."""
        m = self.m
        while m.get('session') == session and m['state'] in ('connecting', 'in_game'):
            try:
                code, r = request(host, port, 'GET', '/misafir/profil?session=%s&anahtar=%s&version=%d&wait=%d' % (
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
                    self.log('arkadaş sunucusu: kayıt yazılamadı: %r' % e)
            if code == 404 or (code == 200 and r.get('finished')):
                m['not'] = _("Your friend's server ended the session (it shut down or removed you). Your save is on your computer in its latest state.")
                if not self.direction.client_alive():
                    self._finish()
                return
            if code != 200:
                time.sleep(3)

    # ------------------------------------------------------------ ayrılma
    def client_closed(self):
        """Panelin istemci kapanış işi: misafir oturumundaysa ayrılınır -> True (sunucuları panel kapatmaz)."""
        if not self.active() or not self.m.get('session'):
            return False
        threading.Thread(target=self._finish, daemon=True).start()
        return True

    def detach(self):
        """Ayrıl düğmesi: istemci açıksa kapatılır (kapanış işi ayrılır), değilse hemen ayrılınır."""
        if not self.active():
            raise FriendError(_("You are not on a friend's server."))
        if self.direction.client_alive():
            self.direction.stop_client()
        else:
            threading.Thread(target=self._finish, daemon=True).start()

    def shutdown(self, sec=30):
        """Panel kapanıyor: oturum sürüyorsa ayrılınır, bitene dek (en çok sn) beklenir."""
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
            code, r = request(host, port, 'POST', '/misafir/cikis', {'session': m['session'], 'anahtar': m['anahtar']}, timeout=30)
            if code == 200 and r.get('profile'):
                self._write(slot, r['profile'], int(r.get('version') or 0))
            reached = True
        except (FriendError, OSError) as e:
            self.log('arkadaş sunucusundan ayrılma: son hâl alınamadı: %r' % e)
            if not m['not']:
                m['not'] = _('Could not reach the server: your save stays as of the last sync.')
        try:
            self.direction.stop_servers()                     # misafirin web sunucusu
        finally:
            with self.lock:
                m['session'], m['end_time'] = None, time.time()
                if m['state'] == 'leaving':
                    m['state'] = 'error' if silent else 'finished'
            try:
                if reached:                              # ulaşılamadıysa kalır: sonraki katılmada son hâl alınır (_yarim_oturum)
                    self.saves.set_meta(slot, friend=None)
            except OSError:
                pass
        self.log('arkadaş sunucusundan ayrılındı (kayıt %s, sürüm %s)' % (slot, m['version']))

    def _partial_session(self, slot):
        """Yarım kalan eski oturum (kayit.json 'arkadas'): sunucuda sürüyorsa biter; yerel kayıt o günden beri değişmediyse sunucudaki
        son hâl yazılır."""
        a = self.saves.meta(slot).get('friend')
        if not isinstance(a, dict) or not a.get('session'):
            return
        self._step(_('Closing an unfinished session'))
        try:
            host, port = resolve_address(a.get('address'))
            code, r = request(host, port, 'POST', '/misafir/cikis', {'session': a['session'], 'anahtar': a.get('anahtar')}, timeout=20)
            d = r.get('profile')
            if code == 200 and d and int(r.get('version') or 0) > int(a.get('version') or 0) and self._file(slot) == a.get('file') \
                    and isinstance(d.get('pilot'), dict) and d['pilot'].get('userId') == a.get('uid'):
                self.m.update(version=int(a.get('version') or 0), original_uid=a.get('uid'))
                self._write(slot, d, int(r['version']))
                self.log('yarım kalan arkadaş oturumunun son hâli kayda yazıldı (%s)' % slot)
        except (FriendError, OSError, ValueError, TypeError) as e:
            self.log('yarım kalan arkadaş oturumu kapatılamadı: %r' % e)
        self.m['version'] = 0
        self.saves.set_meta(slot, friend=None)
