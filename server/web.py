"""Local web server: imitates the web login of the DarkOrbit Unity client (links.php, login.php, maps.php).

Usage: python -I web.py <log_folder> [--profile=<path>]   (--profile: the save slot's profile; given by the panel and live tests;
must match game.py. If not given, the active slot's, paths.py)
HTTP: 8090 (embedded browser), 80 (unityApi). Records every unknown request.
Guest of a friend server (the panel's "Play with Friends", panel/friends.py): with --remote=<address:8081> --chat=<address:7771>
--session=<key> --uid=<id> the client enters the game and chat on the friend's server (the session key finds the profile there;
the id is given by the server). --address: the local address to listen on (default 127.0.0.1). On macOS 80 and 843 are opened on 0.0.0.0 and only connections from this
computer are accepted (platform_compat.py: macOS does not open ports below 1024 on 127.0.0.1 for non-root).
Multi-client (panel/multi_client.py): the extra client is opened with http://127.0.0.1:8090/?session=<key>#darkorbit://; the key is asked of the game server
(GET /yerel/oturum: the save's profile and its id on the server), the login page writes it to the dosid cookie, the client comes to login.php with the
PHPSESSID cookie: id, ship, map, language and 2D are that save's. An unknown extra key does not fall to the main player (the main client
would): the login page gives a warning, login.php returns a failure.
"""
import sys, os, re, threading, socket, time, json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote
from urllib.request import ProxyHandler, Request, build_opener, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)              # with -I the script's folder is not on the path
import platform_compat as CP                         # noqa: E402
CP.certificates()                         # macOS: root certificates for CDN images (HTTPS)
log_dir = [a for a in sys.argv[1:] if not a.startswith('--')][0]


def arg(name, default=None):
    return next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--%s=' % name)), default)


PROFILE_PATH = arg('profile')
os.makedirs(log_dir, exist_ok=True)
lock = threading.Lock()
SESSION = arg('session', 'localtest')
BASE_URL = arg('address', '127.0.0.1')
CHAT_HOST = arg('chat', '127.0.0.1:7771')
UID = arg('uid')


def log(name, text):
    with lock:
        with open(os.path.join(log_dir, name), 'a', encoding='utf8') as fh:
            fh.write(time.strftime('%H:%M:%S ') + text + '\n')


BASE = 'http://%s/' % BASE_URL


def default_profile():
    import paths
    return paths.profile_path()


def profile(path=None):
    """If the game server's profile exists, the user id, ship, map and 2D choice come from it."""
    p = path or PROFILE_PATH or default_profile()
    try:
        d = json.load(open(p, encoding='utf8'))
        use2d = bool(((d.get('settings') or {}).get('displaySettingsModule') or {}).get('displayUse2d'))
        return d['pilot']['userId'], d['ship']['typeId'], d['position']['mapId'], use2d
    except (OSError, KeyError, ValueError):
        return 1, 'ship_goliath', 1, False


def web_settings_path(path=None):
    """The web side's settings (the language chosen on the login screen) in a separate file next to the profile: the game server writes the profile."""
    p = path or PROFILE_PATH or default_profile()
    return os.path.join(os.path.dirname(os.path.abspath(p)), 'web_settings.json')


def web_settings(path=None):
    try:
        d = json.load(open(web_settings_path(path), encoding='utf8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def stored_lang(path=None):
    """The saved login language (validated) or None."""
    import re
    lang = str(web_settings(path).get('lang') or '')
    return lang if re.fullmatch(r'[a-z]{2}(_[a-z]{2})?', lang) else None


# ------------------------------------------------------------------ multi-client: sessions of the extra clients
SESSION_RE = re.compile(r'[A-Za-z0-9_\-]{16,64}')
_extra = {}                                # session -> (time asked, {'uid', 'route', 'record'} or None)
_direct = build_opener(ProxyHandler({}))   # so the system's proxy is not used to reach the game server


def extra_session(sid):
    """The extra session of multi-client: asked of the game server (GET /yerel/oturum; kept for a short time) -> {'uid', 'route', 'record'}
    or None. As a guest of a friend's server (--uid) there is no extra session."""
    if not sid or sid == SESSION or UID or not SESSION_RE.fullmatch(sid):
        return None
    now = time.time()
    with lock:
        c = _extra.get(sid)
    if c and now - c[0] < (60 if c[1] else 2):
        return c[1]
    try:
        with _direct.open('http://%s/yerel/oturum?session=%s' % (GAME_SERVER, quote(sid)), timeout=3) as r:
            d = json.loads(r.read().decode('utf8'))
        v = {'uid': int(d['uid']), 'route': str(d['route']), 'record': str(d.get('record') or '')}
    except Exception:                   # 404 (unknown), the server is single-player or closed
        v = None
    with lock:
        _extra[sid] = (now, v)
    return v


def session(sid):
    """The request's session -> (session, profile path, id on the server or None) or None: an empty or the main key goes to the main player,
    any other to the extra client (None if unknown: it does not fall to the main player)."""
    if not sid or sid == SESSION:
        return SESSION, PROFILE_PATH or default_profile(), int(UID) if UID else None
    e = extra_session(sid)
    return (sid, e['route'], e['uid']) if e else None


def cookie(h, name):
    """The request's cookie (None if missing)."""
    for part in (h.headers.get('Cookie') or '').split(';'):
        k, _, v = part.strip().partition('=')
        if k == name:
            return v.strip()
    return None


def set_lang(body, sid=None):
    """When the language is chosen on the login screen the client (LaunchShow.DropdownValueChanged) sends POST /unityApi/setLang.php "lang=tr".
    It was not stored, the language went back to English on every start (live test H88, user report): now it is in web_settings.json; the login
    page gives it as the lang cookie (the client takes the language from there, redirect_page) and as the lang field of the web login."""
    import re
    from urllib.parse import parse_qs
    lang = (parse_qs(body.decode('utf8', 'replace')).get('lang') or [''])[0].strip().lower()
    o = session(sid) if sid else None
    path = o[1] if o else None          # extra client: next to its own save; an unknown key writes nothing
    if re.fullmatch(r'[a-z]{2}(_[a-z]{2})?', lang) and (o or not sid):
        d = dict(web_settings(path), lang=lang)
        p = web_settings_path(path)
        with lock:
            with open(p + '.tmp', 'w', encoding='utf8') as fh:
                json.dump(d, fh, ensure_ascii=False, indent=1)
            os.replace(p + '.tmp', p)
    return 'text/plain', ''


def login_node(o=None):
    """o: (session, profile path, id on the server) — if not given, the main player (session())."""
    # the field types of DarkOrbit.LoginNodeData were verified with il2types.py (long/bool/Uri/ServerInfo/Hangars)
    now = int(time.time())
    sid, path, uid = o or (SESSION, None, int(UID) if UID else None)
    user_id, ship, map_id, use2d = profile(path)
    user_id = uid or user_id
    lang = stored_lang(path) or 'en'
    hangar = {'modelId': 10, 'slotNumber': 1, 'mapId': map_id, 'hangarId': 1, 'shipName': ship.replace('ship_', '').title(), 'tooltipIcon': '',
              'shipDestroyed': False, 'shipId': ship, 'hangarActive': True}
    return {
        'gameclientHash': 'local', 'chatHost': CHAT_HOST, 'profileXmlHash': '1', 'loadingscreenHash': '1',
        'pid': 175, 'opid': 0, 'sessionID': sid, 'userID': user_id, 'platform': 'client',
        'loadingscreenAssetsXmlHash': '1', 'showAdvertisingHint': False, 'useHash': 0, 'resourceJumpGateXmlHash': '1',
        'browser': 'unity', 'host': BASE, 'useDeviceFonts': 0, 'theme': BASE, 'mapID': map_id, 'lang': lang,
        'itemXmlHash': '1', 'eventStreamContext': '', 'resourcesXmlHash': '1', 'allowChat': 0, 'nextAction': 'internalWebGL',
        'requestScheme': 'http', 'resources3dparticlesXmlHash': '1', 'cdn': BASE, 'resourceEventsXmlHash': '1',
        'gameclientAllowedInitDelay': 0, 'gameclientPath': 'spacemap/', 'helpLink': BASE, 'basePath': 'spacemap',
        # serverInfo: the client (GameLoadingManager.StartGame) parses the time as "h:mm tt / hh:mm tt / H:mm / HH:mm" and the date as "dd.MM.yyyy"
        # and sets the game time; a time with seconds and an ISO date cannot be parsed, the HUD time started from 08:47 on every login
        # (live test N1 -> H78)
        'fullscreen': 0, 'serverInfo': {'timeStamp': now, 'serverDate': time.strftime('%d.%m.%Y'), 'instanceName': 'Local',
                                        'serverTime': time.strftime('%H:%M')},
        # display2d: the client sets the 2D/3D mode from here on every login (GameLoadingManager.UpdateWebData -> Settings, 1 = 3D, 2 = 2D;
        # the same encoding as local force2D). It always went as 1: choosing 2D in the settings and re-entering opened 3D (live test H73,
        # user report). The choice is written to the profile on the game server with DisplaySettingsRequest.displayUse2d
        'sharedImages': BASE + 'do_img/', 'display2d': 2 if use2d else 1, 'resourceachievementsXmlHash': '1', 'loadingClaim': '',
        'resources3dXmlHash': '1', 'hangars': {'data': {'faction': '1', 'hangars': [hangar]}}, 'autoStartEnabled': 1,
        'boardLink': BASE, 'crossdomainHash': '1', 'userProfileImage': '',
    }


INFO = {      # Settings -> Support / Account Center ... (official forum 127724, 150766): a local info page in place of the official sites (adaptation)
    'forum': ('Forum', 'Bu yerel sunucunun forumu yok. Oyun kuralları ve açıklamalar için belgeler/forum_tr klasörüne bak.'),
    'help': ('Yardım', 'Oyun içi yardım için panelin "Nasıl Oynanır" bölümüne bak.'),
    'credits': ('Emeği geçenler', 'OpenOrbit: tek oyunculu yerel sunucu.'),
    'imprint': ('Künye', 'OpenOrbit: tek oyunculu yerel sunucu; ticari bir hizmet değildir.'),
    'support': ('Destek', 'Destek bileti yerine panelin günlüklerine (server/logs) bak; sohbetteki /report raporları '
                'server/logs/sohbet_raporlari.jsonl dosyasına yazılır.'),
    'accountCenter': ('Hesap Merkezi', 'Hesap ayarları (ad, şifre, bülten) yerel profilde tutulur; pilot adını oyundaki Pilot Profili '
                      'penceresinden değiştirebilirsin.'),
}


def links():
    return {k: BASE + 'bilgi/' + k for k in INFO}


def info_page(kind):
    title, text = INFO.get(kind, ('OpenOrbit', ''))
    return ('<!doctype html><html><head><meta charset="utf-8"><title>%s</title></head><body style="background:#000;color:#9cf;'
            'font-family:Verdana;padding:24px"><h2>%s</h2><p>%s</p></body></html>' % (title, title, text))


_browser = {}                          # extra session -> the moment the browser came to internalWebGL (its login.php has not come yet)
BROWSER_SEC = 10


def request_session(h, entry=False):
    """The session of login.php and setLang.php: the PHPSESSID cookie. The client reads the cookie from the embedded browser's storage; because the clients share the same
    browser folder (Vuplex chromium-cache), on an extra client the read occasionally comes back empty, even if the browser's own request carried
    the cookie: the extra client was entering as the main player (live test 2026-10-30). If the cookie is empty, the extra session that came to internalWebGL within the last BROWSER_SEC and
    has not logged in yet (login: login.php, the matching record drops)."""
    sid, now = cookie(h, 'PHPSESSID'), time.time()
    with lock:
        if not sid:
            fresh = [(t, s) for s, t in _browser.items() if now - t < BROWSER_SEC]
            sid = max(fresh)[1] if fresh else sid
        if entry and sid:
            _browser.pop(sid, None)
    return sid


def login(sid=None):
    """sid: the request's PHPSESSID cookie (the extra client's session or the main player's)."""
    o = session(sid)
    if o is None:                       # unknown extra session (the server restarted, the client was not opened from the panel): not the main player
        return {'success': 0, 'message': 'Session expired: close this game client and open it again from the DarkOrbit panel.'}
    # LoginDataNew { [JsonProperty("data")] string LoginData } -> the JSON text inside is parsed a second time as LoginNodeData
    n = login_node(o)
    return dict(n, success=1, message='', data=json.dumps(n), loginData=json.dumps(n))


GAME_SERVER = arg('remote', '127.0.0.1:8081')
_MAP_IDS = None


def maps_xml():
    # Map ids from the client's own maps-config.xml (extracted from the Unity package)
    global _MAP_IDS
    if _MAP_IDS is None:
        import re
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'maps-config.xml')
        try:
            _MAP_IDS = sorted(set(int(x) for x in re.findall(r'<map id="(\d+)"', open(src, encoding='utf8').read())))
        except OSError:
            _MAP_IDS = list(range(1, 30))
    body = ''.join('<map id="%d"><gameserverIP>%s</gameserverIP></map>' % (i, GAME_SERVER) for i in _MAP_IDS)
    return '<?xml version="1.0" encoding="UTF-8"?><maps>' + body + '</maps>'


# The Gate window's "rewards" guide (client: UIGalaxyGatesSystem.LoadXmlDataGate -> GalaxyGatesRewardInfo). Each child of the root element
# is a gate (name = the gate's name in the client: alpha ... hades, streuner), the items inside: id = lootId, chance = probability
# class 1-5 ("dispatch_tooltip_description_dropChance-N": very low ... very high), min = count (icon tier). The values are the completion rewards in
# data/gates.json (the game's own values; the panel's multipliers are not applied).
GATE_LOOT = {'xenomit': 'resource_ore_xenomit', 'log_disk': 'resource_logfile', 'voucher': 'resource_repairvoucher',
             'energy': 'resource_extra-energy', 'abr': 'resource_collectable_axion-beam-regulator',
             'schism': 'resource_collectable_schism', 'green_key': 'resource_booty-key'}


def chance_class(p):
    return 5 if p >= 1 else 4 if p >= 0.5 else 3 if p >= 0.2 else 2 if p >= 0.05 else 1


def gate_rewards_xml():
    from xml.sax.saxutils import quoteattr
    import game_data as DATA          # the selected world's gates (OO_WORLD)
    try:
        gates = DATA.load('gates.json')['kapilar']
    except (OSError, ValueError, KeyError):
        gates = {}
    out = []
    for key, g in gates.items():
        R = g.get('reward') or {}
        rows = [('currency_experience', R.get('ep', 0), 1.0), ('currency_honour', R.get('honor', 0), 1.0),
                ('currency_uridium', R.get('uridium', 0), 1.0)]
        rows += [(loot, n, 1.0) for loot, n in sorted((R.get('ammunition') or {}).items())]
        rows += [(GATE_LOOT[k], R.get(k, 0), 1.0) for k in ('xenomit', 'log_disk', 'voucher', 'energy')]
        rows += [(GATE_LOOT.get(k, k), n, 1.0) for k, n in sorted((R.get('booty') or {}).items())]
        for s in R.get('chance', []):
            if s.get('item') == 'ore_pack':        # forum 129125: the gate's ore pack, its items by weight
                rows += [(loot, n[0], s.get('probability', 0) * w) for loot, n, w in s['package']]
                continue
            opts = s.get('options') if s.get('item') == 'design_choice' else [s.get('item')]
            rows += [(loot, s.get('count', 1), s.get('probability', 0) / max(1, len(opts))) for loot in opts or []]
            # one of the three resources that come with Diametrion (gate.finish 'together'): the guide's "min" field is the minimum amount (ranges like 70-80 and 8-14 cannot be
            # written), the chance class from the probability split three ways
            rows += [(loot, n[0] if isinstance(n, list) else n, s.get('probability', 0) / len(s['together'])) for loot, n in s.get('together', [])]
        items = ''.join('<item id=%s chance="%d" min="%d"/>' % (quoteattr(loot), chance_class(p), n) for loot, n, p in rows
                        if loot and n)
        out.append('<gate name=%s>%s</gate>' % (quoteattr(key), items))
    return '<?xml version="1.0" encoding="UTF-8"?><ggRewards>' + ''.join(out) + '</ggRewards>'


def galaxy_trek_xml(kind):
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)          # with -I the script's folder is not on the path
    import galaxy_trek as GTR
    return GTR.planets_xml() if kind == 'planet' else GTR.rewards_xml()


ROUTES = {
    '/spacemap/xml/maps.php': lambda h: ('text/xml', maps_xml()),
    '/unityApi/events/spaceSearch.php': lambda h: ('text/xml;charset=UTF-8', galaxy_trek_xml('planet')),    # Galaxy Trek (stage 3)
    '//unityApi/events/spaceSearch.php': lambda h: ('text/xml;charset=UTF-8', galaxy_trek_xml('planet')),
    '/unityApi/events/ssRewards.php': lambda h: ('text/xml;charset=UTF-8', galaxy_trek_xml('reward')),
    '//unityApi/events/ssRewards.php': lambda h: ('text/xml;charset=UTF-8', galaxy_trek_xml('reward')),
    '/unityApi/guide/ggRewards.php': lambda h: ('text/xml;charset=UTF-8', gate_rewards_xml()),
    '/unityApi/links.php': lambda h: ('application/json', json.dumps(links())),
    '/unityApi/login.php': lambda h: ('application/json', json.dumps(login(request_session(h, entry=True)))),
    '/unityApi/setLang.php': lambda h: set_lang(h.body, request_session(h)),
    '/unityApi/agent.php': lambda h: ('text/plain', ''),          # the client's event-tracking notification (e.g. Unity_ChangeLanguagetr)
}

CDN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cdn')
CDN_TYPES = {'.xml': 'application/xml', '.php': 'text/xml;charset=UTF-8', '.png': 'image/png', '.jpg': 'image/jpeg',
             '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp', '.json': 'application/json', '.webm': 'video/webm'}
CDN_OFFICIAL = 'https://darkorbit-22.bpsecure.com/'      # the game's images (Bigpoint's) are not in the repo: from here on the first request
cdn_missing = set()                                    # those that cannot be downloaded (no internet, not on the official CDN): not retried


def cdn_fetch(rel, p):
    """A game image (do_img/) not available locally is downloaded once from the official CDN and kept; False if it fails (the client shows no image)."""
    if not rel.startswith('do_img/') or rel in cdn_missing:
        return False
    try:
        with urlopen(Request(CDN_OFFICIAL + rel, headers={'User-Agent': 'Mozilla/5.0'}), timeout=8) as r:
            data = r.read()
    except Exception as e:
        cdn_missing.add(rel)
        log('unknown.log', 'CDN download failed: %s (%s)' % (rel, e))
        return False
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.part', 'wb') as fh:
        fh.write(data)
    os.replace(p + '.part', p)
    return True


def cdn_file(base):
    """If the client's CDN request is in the local copy (the game's images are downloaded from the official CDN on first request) -> (content type, bytes)."""
    rel = base.replace('\\', '/').lstrip('/')     # so a backslash '..' on Windows cannot escape the CDN folder
    while '//' in rel:
        rel = rel.replace('//', '/')
    if not rel or '..' in rel.split('/'):
        return None
    p = os.path.join(CDN_DIR, *rel.split('/'))
    if not os.path.isfile(p) and not cdn_fetch(rel, p):
        return None
    return CDN_TYPES.get(os.path.splitext(p)[1].lower(), 'application/octet-stream'), open(p, 'rb').read()


def redirect_page(sid=None):
    """The embedded browser's first page: the session cookie and the redirect to the game login (sid: the extra client's ?session= key; a warning
    on an unknown key, it does not fall to the main player). If there is a saved login language, the client first gets the message
    "Unity_ChangeLanguage<lang>": the client listens to the page's console messages (GameLoadingManager.UpdateMessage,
    ConsoleMessageLogged -> UpdateWebData: WebGlData.message -> Settings.Language). The client's other language source is the browser's lang cookie (OpenWebLogin) but the browser
    starts without cookies on every start and the client's cookie read comes back empty; it does not use the web login's lang field either (live test H88)."""
    o = session(sid) if sid else (SESSION, None, None)
    if o is None:
        return ('<!doctype html><html><body style="background:#000;color:#f96;font-family:Verdana">Bu istemcinin oturumu sunucuda '
                'yok: istemciyi kapatıp paneldeki ek istemci düğmesiyle yeniden aç.<br>This client\'s session is not on the server: '
                'close it and open it again from the panel.</body></html>')
    lang = stored_lang(o[1])
    js = 'document.cookie="dosid=%s; path=/";' % o[0]
    js += 'var gone=false;function go(){if(!gone){gone=true;location.href="/indexInternal.es?action=internalWebGL";}}'
    if lang:
        msg = json.dumps({'success': 1, 'message': 'Unity_ChangeLanguage' + lang})
        js += ('document.cookie="lang=%s; path=/";' % lang +
               'setTimeout(function(){console.log(%s);setTimeout(go,400);},300);' % json.dumps(msg))
    else:
        js += 'go();'
    return ('<!doctype html><html><body style="background:#000;color:#9cf;font-family:Verdana">DarkOrbit yerel sunucu<script>'
            + js + '</script></body></html>')


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _all(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.body = self.rfile.read(n) if n else b''
        path = self.path.split('#')[0]
        base = path.split('?')[0]
        port = self.server.server_address[1]
        status = 200
        if base in ROUTES:
            ctype, out = ROUTES[base](self)
        elif port == 8090 and base == '/':
            q = parse_qs(path.split('?', 1)[1]) if '?' in path else {}
            ctype, out = 'text/html; charset=utf-8', redirect_page((q.get('session') or [None])[0])
        elif base.startswith('/bilgi/'):
            ctype, out = 'text/html; charset=utf-8', info_page(base[len('/bilgi/'):])
        elif 'indexInternal.es' in path:
            o = session(cookie(self, 'dosid'))
            if o and o[0] != SESSION:
                with lock:
                    _browser[o[0]] = time.time()
            ctype, out = 'text/plain', o[0] if o else 'gecersiz'
        elif cdn_file(base):
            ctype, out = cdn_file(base)
        else:                    # the client's known endpoints are above; an unknown request gets 404 instead of an empty 200 (visible in http.log)
            ctype, out, status = 'text/plain', '', 404
            log('unknown.log', '%s :%d %s body=%r' % (self.command, port, self.path, body[:500]))
        out = out.encode('utf8') if isinstance(out, str) else out
        log('http.log', '%s :%d %s cookie=%s body=%r -> %d, %d bytes %s' % (self.command, port, self.path, self.headers.get('Cookie'), body[:300], status, len(out), out[:160]))
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('X-Custom-Header', 'DarkOrbitUnity')   # GetPost rejects the login without this header
        self.send_header('Content-Length', str(len(out)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_HEAD = _all

    def log_message(self, *a):
        pass


class Server(ThreadingHTTPServer):
    filtered = False                         # a low port opened on 0.0.0.0 on macOS: only this computer (compat.listen_address)

    def verify_request(self, request, client_address):
        return not self.filtered or CP.is_local(client_address[0])

    def handle_error(self, request, client_address):
        """On a connection the client dropped, a single line in errors.log instead of http.server's stack dump (stderr)."""
        log('errors.log', 'http %s: %r' % (client_address[0], sys.exc_info()[1]))


def serve_http(port):
    address, filtered = CP.listen_address(BASE_URL, port)
    try:
        srv = Server((address, port), H)
        srv.filtered = filtered
        srv.serve_forever()
    except OSError as e:
        log('errors.log', 'http %d: %s' % (port, e))


def serve_tcp(port):
    address, filtered = CP.listen_address(BASE_URL, port)
    try:
        s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((address, port)); s.listen(5)
    except OSError as e:
        log('errors.log', 'tcp %d: %s' % (port, e)); return
    while True:
        c, addr = s.accept()
        if filtered and not CP.is_local(addr[0]):
            c.close()
            continue
        log('tcp.log', 'tcp %d connect from %s' % (port, addr))

        def rd(c=c):
            c.settimeout(300)
            try:
                while True:
                    d = c.recv(65536)
                    if not d:
                        break
                    log('tcp.log', 'tcp %d recv %d: %s' % (port, len(d), d[:256].hex()))
            except Exception as e:
                log('tcp.log', 'tcp %d closed: %s' % (port, e))
        threading.Thread(target=rd, daemon=True).start()


if __name__ == '__main__':          # when imported (tests) the server does not start
    import paths as _paths
    if _paths.MIGRATION_ERROR:      # the saves could not be moved to the new format: not half-started with the old format
        sys.exit('save migration failed: %s' % _paths.MIGRATION_ERROR)
    for p in (80, 8090):
        threading.Thread(target=serve_http, args=(p,), daemon=True).start()
    for p in (843, 9339, 8082):         # 7771: the local chat server is in the game process (chat.py)
        threading.Thread(target=serve_tcp, args=(p,), daemon=True).start()
    log('server.log', 'web started')
    while True:
        time.sleep(3600)
