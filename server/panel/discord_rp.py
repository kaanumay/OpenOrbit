"""Discord Rich Presence (Panel sayfası > Discord Rich Presence): oyuncunun Discord profilinde oyunun anlık hâli.

Panel açık Discord istemcisine yerel IPC'yle bağlanır (Windows: \\\\.\\pipe\\discord-ipc-N; Linux ve macOS: $XDG_RUNTIME_DIR,
$TMPDIR ya da /tmp altında discord-ipc-N soketi; Flatpak ve Snap Discord'unun klasörleri de denenir). Ek paket gerekmez.
Durum oyun sunucusunun canlı durum dosyasından (live_status.py) okunur; oyuncu Panel sayfasında neyin görüneceğini seçer
(config.py rp_* anahtarları). Görseller uygulamanın Developer Portal'daki Rich Presence varlıkları (Orders.md OP-018; adları
teslim dosyalarınınki); panelin önizlemesi aynı adlarla ui/images/discord/*.webp.

Discord etkinlik güncellemesini 20 saniyede 5 kez sınırlar: yalnız değişince ve en sık ARALIK_SN'de bir gönderilir.
"""
import json, os, socket, struct, threading, time, uuid

APPLY_WHEN = '1565840028163248218'
LOGO = 'oo_rp_logo'
BADGE = 'oo_rp_badge_%s_r2'                    # firma amblemi (küçük görsel)
GITHUB = 'https://github.com/kaanumay/OpenOrbit'
INTERVAL_SEC = 15
FIRMA = {1: 'mmo', 2: 'eic', 3: 'vru'}


def region(game_map, gate):
    """Haritanın büyük görseli: firmanın bölgesi, ortak savaş bölgesi (4-X), üst haritalar (5-X, BL), kapılar."""
    n = str(game_map or '')
    if gate:
        b = 'gate'
    elif len(n) >= 3 and n[1] == '-' and n[0] in '12345':
        b = {'1': 'mmo', '2': 'eic', '3': 'vru', '4': 'battle', '5': 'upper'}[n[0]]
    else:
        b = 'upper' if n.startswith('BL') else 'gate'
    return 'oo_rp_region_' + b


def ship_name(loot):
    return str(loot or '').replace('ship_', '', 1).replace('_', ' ').title() or None


def event(live, setting, _, state):
    """Panelin durumu -> SET_ACTIVITY'nin etkinliği (None: gösterilecek bir şey yok). Önizleme de bunu gösterir.
    canli: canli_durum.json (oyun sunucusu açıksa); durum: 'oyunda' | 'arkadas' (arkadaşın sunucusunda) | 'giris' | 'baslatiliyor'
    | 'panel'."""
    a = lambda k: setting.get('rp_' + k)
    if state != 'in_game' or not live:
        if state == 'panel' and not a('in_panel'):
            return None
        parent, sub = {'giris': (_('Giriş ekranında'), _('Uzaya çıkmak üzere')), 'starting': (_('Oyun başlatılıyor…'), _('Uzaya çıkmak üzere')),
                    'arkadas': (_('Arkadaşının sunucusunda'), _('Birlikte oynuyor'))}.get(state, (_('Panelde'), _('Oyuna hazırlanıyor')))
        e = {'details': parent, 'state': sub,
             'assets': {'large_image': LOGO, 'large_text': 'OpenOrbit'}}
    else:
        pl, gm, location, world_info = live.get('pilot', {}), live.get('gemi', {}), live.get('position', {}), live.get('world') or {}
        parent = [('[%s] ' % pl['klan'] if a('klan') and pl.get('klan') else '') + ((pl.get('ad') or '') if a('pilot') else '')]
        if a('gemi') and ship_name(gm.get('ad')):
            parent.append(ship_name(gm['ad']))
        if a('seviye'):
            parent.append(_('Seviye %s', pl.get('seviye', 1)))
        gate = world_info.get('kapi')
        if not a('durum'):
            status = None
        elif world_info.get('dead'):
            status = _('Gemisi parçalandı')
        elif gate:
            status = ' · '.join(str(x) for x in (gate.get('ad'), gate.get('dalga')) if x)
        elif world_info.get('in_combat'):
            status = _('Savaşta: %s', world_info['hedef']) if world_info.get('hedef') else _('Savaşta')
        elif world_info.get('safe'):
            status = _('Güvenli bölgede')
        else:
            status = _('Uzayda uçuyor')
        sub = [x for x in (location.get('harita') if a('harita') else None, status) if x]
        firma = FIRMA.get(pl.get('firma'))
        e = {'details': ' · '.join(x.strip() for x in parent if x.strip()) or _('Uzayda'),
             'state': ' · '.join(sub) or _('Oyunda'),
             'assets': {'large_image': region(location.get('harita'), gate) if a('harita') else LOGO,
                        'large_text': (_('%s haritası', location['harita']) if a('harita') and location.get('harita') else 'OpenOrbit')}}
        if a('firma') and firma:
            e['assets'].update(small_image=BADGE % firma, small_text=firma.upper())
        if a('sure') and live.get('session_start'):
            e['timestamps'] = {'start': int(live['session_start'])}
        friends = live.get('arkadas')
        if a('grup') and friends and friends.get('guests'):
            e['party'] = {'id': 'openorbit-%s' % (pl.get('ad') or 'host'), 'size': [len(friends['guests']) + 1, friends['max_count'] + 1]}
    e.update(details_url=GITHUB, state_url=GITHUB)       # kartın yazıları ve görselleri tıklanınca GitHub sayfası
    e['assets'].update({k + '_url': GITHUB for k in ('large', 'small') if k + '_image' in e['assets']})
    if a('buttons'):
        e['buttons'] = [{'label': _("Discord'a katıl")[:32], 'url': 'https://discord.com/invite/openorbit'},
                        {'label': _('OpenOrbit (GitHub)')[:32], 'url': GITHUB}]
    for k in ('details', 'state'):                     # Discord: 2-128 karakter
        e[k] = e[k][:128].ljust(2)
    return e


class Connection:
    """Discord istemcisinin IPC'si: el sıkışma, sonra kare (işlem kodu, uzunluk, JSON) gönderip yanıtı okuma."""

    def __init__(self):
        self.f = None

    def _candidates(self):
        if os.name == 'nt':
            return [r'\\.\pipe\discord-ipc-%d' % i for i in range(10)]
        stems = [os.environ.get(k) for k in ('XDG_RUNTIME_DIR', 'TMPDIR', 'TMP', 'TEMP')] + ['/tmp']
        stems = [k for k in stems if k]
        stems += [os.path.join(k, s) for k in stems for s in ('app/com.discordapp.Discord', 'app/com.discordapp.DiscordCanary',
                                                                  'snap.discord', 'snap.discord-canary')]
        return [os.path.join(k, 'discord-ipc-%d' % i) for k in stems for i in range(10)]

    def open_(self):
        for route in self._candidates():
            try:
                if os.name == 'nt':
                    f = open(route, 'r+b', buffering=0)
                else:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(5)
                    s.connect(route)
                    f = s.makefile('rwb', buffering=0)
            except OSError:
                continue
            self.f = f
            try:
                op, d = self.request(0, {'v': 1, 'client_id': APPLY_WHEN})
                if d.get('evt') == 'READY':
                    return True
            except (OSError, ValueError, struct.error):
                pass
            self.close()
        return False

    def request(self, op, d):
        data = json.dumps(d).encode('utf8')
        self.f.write(struct.pack('<II', op, len(data)) + data)
        start = self._read(8)
        op, n = struct.unpack('<II', start)
        return op, json.loads(self._read(n).decode('utf8'))

    def _read(self, n):
        out = b''
        while len(out) < n:
            k = self.f.read(n - len(out))
            if not k:
                raise OSError('discord kapandı')
            out += k
        return out

    def event(self, e):
        op, d = self.request(1, {'cmd': 'SET_ACTIVITY', 'args': {'pid': os.getpid(), 'activity': e}, 'nonce': str(uuid.uuid4())})
        if op == 2 or d.get('evt') == 'ERROR':
            raise ValueError((d.get('data') or {}).get('message') or 'SET_ACTIVITY')

    def close(self):
        try:
            if self.f:
                self.f.close()
        except OSError:
            pass
        self.f = None


class Presence:
    """Arka planda: ayar açıkken Discord'a bağlanır, etkinliği değişince gönderir; kapanınca etkinliği temizler."""

    def __init__(self, setting, source, t, log=print):
        self.setting, self.source, self.t, self.log = setting, source, t, log       # kaynak: () -> (canli, durum)
        self.b = Connection()
        self.last = None                         # Discord'a en son giden etkinlik
        self.last_time = 0.0
        self.trial = 0.0
        self.state = 'off'                   # kapali | discord_yok | bagli | hata
        self.error = None
        self.wake_up = threading.Event()

    def launch(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def preview(self):
        live, state = self.source()
        return event(live, self.setting, self.t, state)

    def _loop(self):
        while True:
            self.wake_up.wait(5)
            self.wake_up.clear()
            try:
                self._step()
            except Exception as e:
                self.log('discord rich presence: %r' % e)
                self.b.close()
                self.state, self.error, self.last = 'hata', str(e), None

    def _step(self):
        if not self.setting.get('discord_rp'):
            if self.b.f:
                try:
                    self.b.event(None)
                finally:
                    self.b.close()
            self.state, self.last = 'off', None
            return
        if not self.b.f:
            if time.monotonic() - self.trial < 30 and self.state in ('discord_not_running', 'hata'):
                return
            self.trial = time.monotonic()
            if not self.b.open_():
                self.state = 'discord_not_running'
                return
            self.last, self.error = None, None
            self.log('discord rich presence: bağlandı')
        self.state = 'connected'
        e = self.preview()
        if e == self.last or time.monotonic() - self.last_time < INTERVAL_SEC:
            return
        try:
            self.b.event(e)
        except OSError:
            self.b.close()
            self.state = 'discord_not_running'
            return
        self.last, self.last_time = e, time.monotonic()
