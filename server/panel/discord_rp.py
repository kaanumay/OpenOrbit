"""Discord Rich Presence (Panel page > Discord Rich Presence): the game's live state on the player's Discord profile.

The panel connects to the open Discord client over local IPC (Windows: \\\\.\\pipe\\discord-ipc-N; Linux and macOS: the discord-ipc-N socket under
$XDG_RUNTIME_DIR, $TMPDIR or /tmp; the folders of Flatpak and Snap Discord are tried too). No extra package is needed.
The state is read from the game server's live status file (live_status.py); the player chooses on the Panel page what is shown
(config.py rp_* keys). The images are the app's Rich Presence assets in the Developer Portal (Orders.md OP-018; the names are
those of the delivered files); the panel's preview uses the same names with ui/images/discord/*.webp.

Discord limits activity updates to 5 per 20 seconds: it is sent only on change and at most once per ARALIK_SN.
"""
import json, os, socket, struct, threading, time, uuid

APPLY_WHEN = '1565840028163248218'
LOGO = 'oo_rp_logo'
BADGE = 'oo_rp_badge_%s_r2'                    # company emblem (small image)
GITHUB = 'https://github.com/kaanumay/OpenOrbit'
INTERVAL_SEC = 15
COMPANY = {1: 'mmo', 2: 'eic', 3: 'vru'}


def region(game_map, gate):
    """The map's large image: the company's region, the shared battle region (4-X), upper maps (5-X, BL), gates."""
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
    """The panel's state -> the SET_ACTIVITY activity (None: nothing to show). The preview shows this too.
    live: live_status.json (if the game server is running); state: 'in_game' | 'friend' (on a friend's server) | 'entry' | 'starting'
    | 'panel'."""
    a = lambda k: setting.get('rp_' + k)
    if state != 'in_game' or not live:
        if state == 'panel' and not a('in_panel'):
            return None
        parent, sub = {'entry': (_('At the login screen'), _('About to launch')), 'starting': (_('Starting the game…'), _('About to launch')),
                    'friend': (_("On a friend's server"), _('Playing together'))}.get(state, (_('In the panel'), _('Getting ready to play')))
        e = {'details': parent, 'state': sub,
             'assets': {'large_image': LOGO, 'large_text': 'OpenOrbit'}}
    else:
        pl, gm, location, world_info = live.get('pilot', {}), live.get('ship', {}), live.get('position', {}), live.get('world') or {}
        parent = [('[%s] ' % pl['clan'] if a('clan') and pl.get('clan') else '') + ((pl.get('name') or '') if a('pilot') else '')]
        if a('ship') and ship_name(gm.get('name')):
            parent.append(ship_name(gm['name']))
        if a('level'):
            parent.append(_('Level %s', pl.get('level', 1)))
        gate = world_info.get('gate')
        if not a('state'):
            status = None
        elif world_info.get('dead'):
            status = _('Ship destroyed')
        elif gate:
            status = ' · '.join(str(x) for x in (gate.get('name'), gate.get('wave')) if x)
        elif world_info.get('in_combat'):
            status = _('In combat: %s', world_info['target']) if world_info.get('target') else _('In combat')
        elif world_info.get('safe'):
            status = _('In a safe zone')
        else:
            status = _('Flying through space')
        sub = [x for x in (location.get('map') if a('map') else None, status) if x]
        company = COMPANY.get(pl.get('company'))
        e = {'details': ' · '.join(x.strip() for x in parent if x.strip()) or _('In space'),
             'state': ' · '.join(sub) or _('In game'),
             'assets': {'large_image': region(location.get('map'), gate) if a('map') else LOGO,
                        'large_text': (_('%s map', location['map']) if a('map') and location.get('map') else 'OpenOrbit')}}
        if a('company') and company:
            e['assets'].update(small_image=BADGE % company, small_text=company.upper())
        if a('duration') and live.get('session_start'):
            e['timestamps'] = {'start': int(live['session_start'])}
        friends = live.get('friend')
        if a('group') and friends and friends.get('guests'):
            e['party'] = {'id': 'openorbit-%s' % (pl.get('name') or 'host'), 'size': [len(friends['guests']) + 1, friends['max_count'] + 1]}
    e.update(details_url=GITHUB, state_url=GITHUB)       # clicking the card's texts and images opens the GitHub page
    e['assets'].update({k + '_url': GITHUB for k in ('large', 'small') if k + '_image' in e['assets']})
    if a('buttons'):
        e['buttons'] = [{'label': _("Join Discord")[:32], 'url': 'https://discord.com/invite/openorbit'},
                        {'label': _('OpenOrbit (GitHub)')[:32], 'url': GITHUB}]
    for k in ('details', 'state'):                     # Discord: 2-128 characters
        e[k] = e[k][:128].ljust(2)
    return e


class Connection:
    """The Discord client's IPC: handshake, then sending a frame (opcode, length, JSON) and reading the reply."""

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
                raise OSError('discord closed')
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
    """In the background: connects to Discord while the setting is on, sends the activity when it changes; clears the activity when it closes."""

    def __init__(self, setting, source, t, log=print):
        self.setting, self.source, self.t, self.log = setting, source, t, log       # source: () -> (live, state)
        self.b = Connection()
        self.last = None                         # the activity last sent to Discord
        self.last_time = 0.0
        self.trial = 0.0
        self.state = 'off'                   # off | discord_not_running | connected | error
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
                self.state, self.error, self.last = 'error', str(e), None

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
            if time.monotonic() - self.trial < 30 and self.state in ('discord_not_running', 'error'):
                return
            self.trial = time.monotonic()
            if not self.b.open_():
                self.state = 'discord_not_running'
                return
            self.last, self.error = None, None
            self.log('discord rich presence: connected')
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
