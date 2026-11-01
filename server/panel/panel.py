"""DarkOrbit local server management panel: starts the game, manages settings, saves and servers.

Launch: "OpenOrbit Panel.pyw" in the main directory (double-click; no console) or python server/panel/panel.py.
The panel opens a local web UI on 127.0.0.1:8077 and shows it in an app window of Edge (or Chrome if absent) (no address bar,
no internet needed). When the window closes: if the game is running it waits until the client closes (setting), then closes the servers
the panel opened and exits. If the panel is already open, a second launch only reopens the window.
API: /api/... (JSON). Requests must carry the page's token (X-Panel-Token): this stops other sites from sending requests
to the panel from the browser. Binds to 127.0.0.1 only.
Paths: paths.py (save/slots, save/panel.json, save/settings.json, logs/).
Language: the languages in lang.py (texts are written in English, those of the other languages are in ui/<code>.json). On first launch the
UI opens the setup wizard: language, game folder, first pilot, game settings (panel.json 'lang', 'setup_done'). If the game is not found
on the computer, the wizard's game folder step starts downloading it (client_download.py; from the Client page too). BepInEx, which loads
the client's fixes, is also installed into the client folder (client_patch.py: in the wizard's game folder step, once the client is
downloaded, from the Client page, or on the first PLAY). Multi-client (multi_client.py): after PLAY, extra clients with the other saves on
the same server (with at least two saves and the setting on, the server is opened in multi-session mode); while an extra client is open,
actions that restart the server are rejected, and the servers close when the last client closes. Update (updater.py): a little after
launch and every UPDATE_SEC the latest version on GitHub is checked; if the panel setting 'update' is auto and no game,
servers, download or other job is running, it is installed, then the panel restarts (the new process takes the same port, the open window
refreshes the page). Linux and macOS: the client is opened with Wine or Proton (client_runner.py, the Client page's Wine / Proton card);
on macOS, Automatic is the Wine + DXMT the panel installs itself (wine_engine.py: downloaded on the first PLAY, while the client
downloads, or from the Client page; on Apple Silicon the panel also has Rosetta 2 installed). The window is in Chrome, Edge, Chromium or
Brave; file dialogs are tkinter on Linux (zenity if absent), AppleScript on macOS (Tk works there only on the main thread); the shortcut
is a .desktop on Linux, an app bundle (.app) on macOS. """
import datetime, json, os, re, secrets, shlex, shutil, subprocess, sys, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(PANEL_DIR)
ROOT = os.path.dirname(SERVER)
sys.path.insert(0, SERVER)
sys.path.insert(0, PANEL_DIR)
import platform_compat                   # noqa: E402
platform_compat.certificates()           # macOS: if python.org Python's root certificate is missing, the system's bundle (before HTTPS; the servers inherit it)
import paths as PTH          # noqa: E402
import save_migration as SM  # noqa: E402
import settings as SET             # noqa: E402
import lang as D               # noqa: E402
from lang import t as _        # noqa: E402
import client as IST         # noqa: E402
import client_runner as RUN     # noqa: E402
import client_patch as PATCH   # noqa: E402
import processes as PR         # noqa: E402
from saves import Saves, SaveError, COMPANIES  # noqa: E402
from config import PanelConfig  # noqa: E402
from protocol_builds import Adapter  # noqa: E402
from client_download import Downloader, DownloadError  # noqa: E402
from updater import Updater, UpdateError  # noqa: E402
from friends import Friend, FriendError  # noqa: E402
from multi_client import MultiClient, MultiClientError  # noqa: E402
import worlds as WLD          # noqa: E402
import bots as BT            # noqa: E402  (Bots page: bot packs)
import llm_setup as LLMS     # noqa: E402  (language model of the Advanced bot mode)
import discord_rp as DRP       # noqa: E402  (Discord Rich Presence)
from bot import llm_provider as PRV  # noqa: E402  (the language model's provider: built-in or the user's choice)

VERSION = '1.0'
DISCORD = 'https://discord.com/invite/openorbit'   # community server (Panel page, README); permanent invite
DONATE_URL = 'https://buymeacoffee.com/kaanumay'       # support link (bottom of the sidebar)
DONATE_API_URL = 'https://app.buymeacoffee.com/api/creators/slug/kaanumay/coffees?web=1&page=1&per_page=20'   # recent supporters
PORT = 8077
UI_DIR = os.path.join(PANEL_DIR, 'ui')
TEMPLATES = os.path.join(PTH.SAVE, 'settings_templates.json')
BROWSER_PROFILE = os.path.join(os.environ.get('LOCALAPPDATA') or PTH.SAVE, 'DarkOrbitPanel', 'browser')
LOGS = ('gs.log', 'http.log', 'client.log', 'game_console.log', 'web_console.log', 'panel.log', 'errors.log', 'unknown.log') + (
    () if os.name == 'nt' else ('wine.log',))      # Linux and macOS: output of Wine / Proton (processes.open_client)
EXTRA_LOG = re.compile(r'client_[a-z0-9_]{1,40}\.log')          # logs of the multi-client's extra clients (multi_client.py)
HEARTBEAT_SEC = 180                      # if the browser window cannot be watched: if this many requests do not arrive the window is considered closed (monotonic:
                                    # time spent asleep on macOS and Linux is not counted)
HANDOVER_SEC = 10                       # if the browser process exits before this, it handed the window over to a running process (watch_window)
UPDATE_SEC = 6 * 3600            # interval of the new-version check on GitHub (again after an hour if it fails)
EVENT_DESCRIPTIONS = {
    'upgrade_hour': "Equipment upgrades in the Assembly cost 25% less uridium.",
    'dispatch_day': 'Event day for Dispatch missions.',
    'gate_weekend': 'Galaxy Gate energy is 15% off.',
    'kronos_day': 'Kronos gate parts drop twice as often.',
    'gold_booty_box': "Golden Booty Boxes appear on the maps.",
    'halloween': "Curcubitors and the Boss Curcubitor on X-2..X-8, Candy Corn boxes, pumpkins, the Trial of Terrors "
                 "gate (X-4; dark maps), Battle Pass.",
    'agatus': "Spinels and Agatus; event currency and Assembly recipes.",
    'hitac': "Underlings and the Underboss; the Hitac mothership roams from map to map.",
    'immortal_union': 'Lanatum, Styxus and Charopos; event currency.',
    'protegit': "Chaos Protegits; event currency.",
    'winter': "Ice Meteoroids, gift boxes and Santa.",
    'thanksgiving': 'Thanksgiving Box and Roast Turkey Cargo Box.',
    'thanksgiving_ice': "Ice Meteoroids and the Super Ice Meteoroid (from 3 days before Thanksgiving to 5 December).",
    'thanksgiving_gg_double': "Galaxy Gate double rewards from Thanksgiving to Monday (in addition to the Sunday rule).",
    'snowman': 'New year Snowman window (WIZ-X).',
    'plutus': 'Gauntlet of Plutus gate (Easy X-1, Normal X-8; once a day).',
    'labyrinth': "Frozen Labyrinth: a 16-map maze from X-1, Labyrinth Keys and Synk.",
    'galactic_strife': 'Battle Pass (objectives against aliens) and Arios and Neikos designs in the key exchange.',
    'birthday': 'Birthday Gate (X-1).',
    'empyrian': 'Empyrian boxes; keys come from Galaxy Gate rewards.',
    'prosperous': 'Prosperous boxes; keys come from Galaxy Gate rewards.',
    'spring': 'Spring eggs and boxes.',
    'chaos_omen': 'Chaos Omen map event (before Protegit Pandemonium).',
    'gg_double_reward': 'Galaxy Gate EP, honor, Xenomit, log disk, voucher and Assembly resource rewards and lucky reward '
                        'chances are doubled (not for Dispatch).',
    'lf4_day': 'Chance of an LF-4 or 10,000 UCB-100 from the Delta, Epsilon, Lambda and Kuiper gates.',
    'lf4_enhanced': "Chance of an LF-4-HP from Delta, LF-4-PD from Kappa and LF-4-MD from Zeta.",
    'gg_weekend_1': ('Chance of a design or laser package from the Delta, Epsilon, Kuiper and Lambda gates; chance of an '
                     'event design from the Zeta and Kappa gates.'),
    'gg_weekend_3': ('Chance of a design or laser package from the Delta, Epsilon, Kuiper and Lambda gates; chance of an '
                     'event design from the Zeta and Kappa gates.'),
    'gg_weekend_4': ('Chance of a design or laser package from the Delta, Epsilon, Kuiper and Lambda gates; chance of an '
                     'event design from the Zeta and Kappa gates.'),
    'nova_weekend': 'The Delta, Epsilon, Lambda and Kuiper gates give N.E.U.',
    'obsidian_booty': "Obsidian Booty Boxes appear on the maps.",
    'rb_booty': "Red and Blue Booty Boxes appear on the maps.",
    'apocalypse_booty': "Apocalypse Booty Boxes appear on the maps.",
    'fever': 'A boost for the listed ships; only while Gauntlet of Plutus, Mimesis Mutiny or Protegit runs, and during the Black Light Fever weeks.',
    'fever_black_light': 'Black Light Fever weeks: Fever only on the BL maps.',
    'astral_ascension': 'Battle Pass (2022 run) and key exchange.',
    'spacecup': 'Battle Pass (2022 run; no Spaceball or PvP) and key exchange.',
}
DAYS = {'tr': ('Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'), 'en': ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'),
          'de': ('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'), 'es': ('lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'),
          'fr': ('lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'), 'pl': ('pon', 'wt', 'śr', 'czw', 'pt', 'sob', 'niedz'),
          'pt': ('seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'), 'ru': ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')}
MONTHS = {'tr': ('Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'),
         'en': ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'),
         'de': ('Jan.', 'Feb.', 'März', 'Apr.', 'Mai', 'Juni', 'Juli', 'Aug.', 'Sept.', 'Okt.', 'Nov.', 'Dez.'),
         'es': ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sept', 'oct', 'nov', 'dic'),
         'fr': ('janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'),
         'pl': ('sty', 'lut', 'mar', 'kwi', 'maj', 'cze', 'lip', 'sie', 'wrz', 'paź', 'lis', 'gru'),
         'pt': ('jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'),
         'ru': ('янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек')}

os.makedirs(PTH.LOGS, exist_ok=True)
_log_lock = threading.Lock()


def log(text):
    with _log_lock:
        try:
            with open(os.path.join(PTH.LOGS, 'panel.log'), 'a', encoding='utf8') as fh:
                fh.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
        except OSError:
            pass


CFG = PanelConfig(PTH.PANEL)
D.bind(lambda: CFG.get('lang'))
MANAGER = PR.Manager(PTH.LOGS, log)
SAV = Saves(CFG, python=PR.python_exe())
FRD = Friend(CFG, SAV, MANAGER, log, VERSION)                        # Play with Friends: Host and Join (friends.py)
MULTI = MultiClient(CFG, SAV, MANAGER, lambda: FRD.key, PTH.LOGS, log)  # multi-client: extra clients with the other saves (multi_client.py)
SAV.in_use = lambda slot: (MANAGER.running() and MANAGER.slot == slot) or FRD.in_use(slot) or MULTI.in_use(slot)
ADAPTER = Adapter(ROOT, PR.python_exe(), log, PR.NO_WINDOW)    # protocol adaptation to a new client (protocol_builds.py)
UPD = Updater(ROOT, PTH.SAVE, log)                          # update from GitHub (updater.py)
ENG = RUN.engine()                                                # macOS: the Wine + DXMT the panel installs (wine_engine.py)
ENG.log = log
PATCHER = PATCH.Patcher(log)                                           # BepInEx, which loads the client's fixes (client_patch.py)
TOKEN = secrets.token_hex(16)
STATE = {'play': {'running': False, 'steps': [], 'error': None, 'finished': None, 'server_only': False},
         'heartbeat': time.monotonic(), 'window_closed': False, 'window_watched': False, 'last_backup': 0.0, 'closing': False,
         'next_check': time.time() + 8, 'updated': bool({'--updated', '--guncellendi'} & set(sys.argv)), 'srv': None, 'opening': time.time()}


def rp_source():
    """Source of Discord Rich Presence (discord_rp.py) -> (live status or None, the panel's state)."""
    live = read_json(os.path.join(PTH.LOGS, 'live_status.json'), None) if MANAGER.running() else None
    if live and time.time() - live.get('time', 0) > 15:
        live = None
    if MANAGER.client_alive():
        return live, 'in_game' if live and live.get('connected') else 'friend' if FRD.m['state'] == 'in_game' else 'entry'
    return None, 'starting' if STATE['play']['running'] else 'panel'


RP = DRP.Presence(CFG, rp_source, _, log)


class Error(Exception):
    """Error shown to the user."""


# ------------------------------------------------------------------ helpers
def read_json(path, default):
    try:
        with open(path, encoding='utf8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def world_id(slot, friend=False):
    """The server's world: on a friend server the one the Host chose (panel setting friend_world), otherwise the save's default world."""
    choice = CFG.get('friend_world') if friend else None
    if choice and WLD.var(choice):
        return choice
    return SAV.meta(slot).get('world') if slot else None


def world_file(slot, friend=False):
    """The server's world file (World Editor; OO_WORLD) or None (standard world, deleted world)."""
    return WLD.file_path(world_id(slot, friend))


def bot_file(slot, friend=False):
    """The server's bot pack (Bots page; OO_BOT): the pack assigned to the save's world or None."""
    return BT.file_path(BT.world_pack(world_id(slot, friend) or WLD.STANDARD))


def world_info(wid):
    """The Play page's world chip: {id, name, cover, changes}; a deleted world counts as standard."""
    try:
        w = WLD.summary(wid if wid and WLD.var(wid) else WLD.STANDARD)
    except WLD.WorldError:
        w = WLD.summary(WLD.STANDARD)
    return {'id': w['id'], 'name': w['name'], 'cover': w['cover'], 'changes': 0 if w['standard'] else w['changes'], 'standard': w['standard']}


def world_users():
    """World -> the saves that make it their default [{id, ad, pilot}]."""
    out = {}
    for k in SAV.list():
        w = k.get('world') if k.get('world') and WLD.var(k.get('world')) else WLD.STANDARD
        out.setdefault(w, []).append({'id': k['id'], 'name': k.get('name'), 'pilot': k.get('pilot')})
    return out


def settings_file(slot=None):
    """The game settings file: the save's own settings (the active save; the old shared file if there is no save)."""
    slot = slot or SAV.active()
    return SAV.settings(slot) if slot else PTH.SETTINGS


def game_settings():
    return SET.read(settings_file())


def client_folder():
    return IST.resolve(CFG.get('client_folder'))


# ------------------------------------------------------------------ in-game menus (Shop)
# While the game is open the panel changes the game through the game server's local channel (server/panel_channel.py; the key is in the log
# folder). The visuals are the dump of the client's BepInEx plugin (plugin/Images.cs: <client>/BepInEx/openorbit/images), under
# /game_images/.
def is_pack_running(pid):
    """Is the bot pack in the running game now."""
    return bool(MANAGER.running() and getattr(MANAGER, 'bot', None) and BT.file_path(pid)
                and MANAGER.bot[0] == os.path.normcase(BT.file_path(pid)))


def game_channel(route, body=None):
    k = read_json(os.path.join(PTH.LOGS, 'panel_channel.json'), None)
    if not k or not MANAGER.running():
        raise Error(_('The game is not running.'))
    req = Request('http://127.0.0.1:%d%s' % (k['port'], route), data=None if body is None else json.dumps(body).encode('utf8'),
                  headers={'X-Anahtar': k['key'], 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=10) as r:
            return json.load(r)
    except HTTPError as e:
        if e.code == 409:
            raise Error(_('Opens once you have logged in to the game.'))
        raise Error(_('The game server refused the request (%s).', e.code))
    except OSError:
        raise Error(_('Could not connect to the game server.'))


def game_image(name):
    """The atlas page, index or name file dumped by the plugin -> path (None if absent)."""
    if not re.fullmatch(r'[\w.-]+\.(png|json)', name) or not client_folder():
        return None
    p = os.path.join(client_folder(), 'BepInEx', 'openorbit', 'images', name)      # folder dumped by the plugin
    return p if os.path.isfile(p) else None


def _downloaded(path):
    """Download finished: if the client in use is invalid or being updated, the new folder is used (if it is found automatically the
    setting stays empty); on update the old folder is deleted."""
    old = STATE.pop('old_client', None)
    if old or not IST.check(client_folder())['valid']:
        auto = IST.resolve(None)
        same = auto and os.path.normcase(os.path.normpath(auto)) == os.path.normcase(os.path.normpath(path))
        CFG.update({'client_folder': None if same else path})
    if old:
        delete_old_client(old, path)
    PATCHER.start(path)                                   # BepInEx for the client's fixes (client_patch.py)


def delete_old_client(old, new_):
    """Client update: delete the old version's folder. Only a DarkOrbit_Version… folder extracted from an archive: the official install is
    updated by its own launcher, and is not touched."""
    if (os.path.normcase(os.path.normpath(old)) == os.path.normcase(os.path.normpath(new_))
            or not re.match(r'DarkOrbit_Version\d', os.path.basename(os.path.normpath(old))) or not IST.check(old)['valid']):
        log('old client not deleted: %s' % old)
        return
    try:
        shutil.rmtree(old)
        log('old client deleted: %s' % old)
    except OSError as e:
        log('old client could not be deleted: %s: %r' % (old, e))


DL = Downloader(ROOT, IST.check, log, on_done=_downloaded)       # downloading the game client (client_download.py)
LLM = LLMS.LlmSetup(log)                                       # the bots' language model (llm_setup.py)


def _dl_pct(st):
    return int(100 * st['claimed'] / st['total']) if st['total'] else 0


_dialog_lock = threading.Lock()


def dialog(kind, **kw):
    """Local file/folder dialog (tkinter; opens in front of the panel) -> the chosen path or ''. AppleScript on macOS, zenity on Linux if
    tkinter is missing."""
    with _dialog_lock:
        if sys.platform == 'darwin':
            q = lambda s: '"%s"' % str(s).replace('\\', '\\\\').replace('"', '\\"')
            ask = '%s with prompt %s' % ({'folder': 'choose folder', 'ac': 'choose file', 'save': 'choose file name'}[kind],
                                         q(kw.get('title', '')))
            if kind == 'save' and kw.get('initialfile'):
                ask += ' default name ' + q(kw['initialfile'])
            if kw.get('initialdir') and os.path.isdir(kw['initialdir']):
                ask += ' default location POSIX file ' + q(kw['initialdir'])
            return subprocess.run(['osascript', '-e', 'POSIX path of (%s)' % ask], capture_output=True, text=True).stdout.strip()
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            if os.name == 'nt' or not shutil.which('zenity'):
                raise Error(_('The file dialog needs tkinter (Debian/Ubuntu: sudo apt install python3-tk).'))
            a = ['zenity', '--file-selection', '--title=%s' % kw.get('title', '')]
            a += {'folder': ['--directory'], 'ac': [], 'save': ['--save']}[kind]
            if kw.get('initialfile') or kw.get('initialdir'):
                a.append('--filename=%s' % os.path.join(kw.get('initialdir') or '', kw.get('initialfile') or ''))
            return subprocess.run(a, capture_output=True, text=True).stdout.strip()
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        try:
            fn = {'folder': filedialog.askdirectory, 'ac': filedialog.askopenfilename, 'save': filedialog.asksaveasfilename}[kind]
            return fn(parent=root, **kw) or ''
        finally:
            root.destroy()


def open_folder(path):
    if not os.path.exists(path):
        raise Error(_("Folder doesn't exist: %s", path))
    if os.name == 'nt':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])


# ------------------------------------------------------------------ events
def _period_text(a, b, lang):
    (ma, da), (mb, db) = (a.month, a.day), (b.month, b.day)
    months = MONTHS[lang]
    if lang == 'en':
        return '%s %d – %s %d' % (months[ma - 1], da, months[mb - 1], db)
    return '%d%s %s – %d%s %s' % (da, '.' * (lang == 'de'), months[ma - 1], db, '.' * (lang == 'de'), months[mb - 1])


def event_list():
    import event_calendar as CAL
    lang = D.current()
    now = time.time()
    t = datetime.datetime.fromtimestamp(now)
    sel = game_settings().get('events') or {}
    out = []
    for key, e in CAL.EVENTS.items():
        yearly = 'periods' in e
        if yearly:                                      # the periods of the coming year (event_calendar.upcoming; end day included)
            spans = CAL.upcoming(key, now)
            when = ', '.join(_period_text(a, b - datetime.timedelta(days=1), lang) for a, b in spans[:4]) + (
                ' …' if len(spans) > 4 else '') or _('No upcoming dates')
        else:
            days = e.get('days', range(7))
            when = (_('Every day') if len(list(days)) == 7 else ', '.join(DAYS[lang][d] for d in days))
            hrs = e.get('hours')
            if hrs:
                when += ' ' + ', '.join('%02d:00–%02d:00' % (a, b) for a, b in hrs)
            if e.get('nth_of_month'):
                when += ' ' + _('(week %s of the month)', '/'.join(map(str, e['nth_of_month'])))
            if e.get('week_cycle'):
                when += ' ' + _('(every %s weeks)', e['week_cycle'][0])
        per = CAL.period(key, now)
        nxt = None
        if yearly and not per:
            best = next((s for s, f in spans if s > t), None)
            nxt = (best - t).days + 1 if best else None
        st = sel.get(key)
        out.append({'key': key, 'name': _(e.get('name', key)), 'type': 'yearly' if yearly else 'weekly', 'time': when,
                    'in_calendar': per is not None, 'time_left_sec': int(per[1] - now) if per else None, 'next_day': nxt,
                    'state': st, 'enabled': (st == 'on') if st else per is not None,
                    'description': _(EVENT_DESCRIPTIONS.get(key, '')),
                    'conflicting': sorted(_(CAL.EVENTS[j].get('name', j)) for j in CAL.CONFLICTS[key])})
    # conflict (event_calendar.resolve): of those open at the same time, the one opened by hand stays, otherwise the one that started first
    rows = {x['key']: x for x in out}
    on = {k for k, x in rows.items() if x['enabled']}
    keep = CAL.resolve(on, lambda k: (rows[k]['state'] != 'on', (CAL.period(k, now) or (0,))[0], k))
    for k in on - keep:
        rows[k]['enabled'] = False
        rows[k]['suppressed_by'] = next(rows[j]['name'] for j in sorted(keep, key=lambda j: rows[j]['name']) if j in CAL.CONFLICTS[k])
    out.sort(key=lambda x: (x['type'] != 'yearly', not x['enabled'], x['name'].lower()))
    return out


SESSION_NAMES = {'vortex': 'Vortex session', 'world_boss': 'Boss fight', 'kristallon': 'Apotheosis window',
                'mimesis': 'Mimesis run', 'title_hunt': 'Prestige title hunt', 'alien': 'Event aliens',
                'box': 'Event boxes', 'map': 'Map event'}


def api_calendar(q):
    """Event calendar (event_schedule.py): the calendar and active ranges within [bas, bit), sessions, the current or next period."""
    import event_schedule as CC
    now = time.time()
    try:
        a, b = float(q.get('start')), float(q.get('bit'))
    except (TypeError, ValueError):
        raise Error(_('Invalid date range.'))
    if not 0 < b - a <= 62 * 86400:
        raise Error(_('Invalid date range.'))
    hep = bool(game_settings().get('session_always_open'))
    evs = event_list()
    c = CC.schedule(a, b, hep, {e['key']: e['state'] for e in evs})
    out = []
    for e in evs:
        x = c[e['key']]
        session = [dict(s, name=_(SESSION_NAMES[s['uid'] if s['type'] == 'session' else s['type']])) for s in x['sessions']]
        out.append(dict(e, ranges=x['ranges'], active_ranges=x['enabled'], sessions=session,
                        next=CC.next_(e['key'], now, 400 if e['type'] == 'yearly' else 70)))
    return {'now': now, 'start': a, 'bit': b, 'always_open': hep, 'events': out}


def settings_summary(values):
    """Game settings that differ from the default [{'name', 'value'}] (the Play page's chips; settings.summary in the panel's language)."""
    d = SET.clean(values)
    out = []
    for s in SET.SCHEMA:
        v = d.get(s['key'], s['default'])
        if v == s['default']:
            continue
        if s['type'] == 'multiplier':
            text = 'x%g' % v
        elif s['type'] == 'bool':
            text = _('on') if v else _('off')
        elif s['type'] == 'number':
            text = ('%d %s' % (v, _(s['unit']) if s.get('unit') else '')).strip()
        else:
            text = _(s['options'][v])
        out.append({'name': SET.full_name(s, _), 'value': text})
    return out


def set_events(body):
    vals = game_settings()
    ev = dict(vals.get('events') or {})
    import event_calendar as CAL
    if 'all' in body:
        to = body['all']
        for k, e in CAL.EVENTS.items():
            if body.get('type') and body['type'] != ('yearly' if 'periods' in e else 'weekly'):
                continue
            if to in SET.EVENT_STATES:
                ev[k] = to
            else:
                ev.pop(k, None)
    for k, v in (body.get('changes') or {}).items():
        if k not in CAL.EVENTS:
            continue
        if v in SET.EVENT_STATES:
            ev[k] = v
        else:
            ev.pop(k, None)
        if v == 'on':                             # conflicting ones opened by hand go back to the calendar (event_calendar.CONFLICTS)
            for j in CAL.CONFLICTS[k]:
                if ev.get(j) == 'on':
                    ev.pop(j)
    vals['events'] = ev
    SET.write(settings_file(), vals)
    return event_list()


# ------------------------------------------------------------------ warnings and status
def try_migrate():
    """If there is an old single save (save/profil.json), move it to a slot; if the ports are open (it may be a server opened with that
    profile), later."""
    if not os.path.isfile(PTH.LEGACY_PROFILE) or MANAGER.running():
        return None
    table = PR.listeners()
    if any(PR.listening(p, table) for p in (8081, 8090)):
        if not STATE.get('migration_pending'):
            log('old save not moved: game ports are open (a server opened with Baslat.bat may be in use)')
        STATE['migration_pending'] = True
        return None
    STATE['migration_pending'] = False
    moved = SAV.migrate()
    if moved:
        log('old save (save/profil.json) moved to a slot: %s' % moved)
    return moved


def warnings(folder=False):
    out = []
    if STATE.get('migration_pending'):
        out.append({'type': 'warning', 'text': _('The old save (server/save/profil.json) is waiting to be moved into a save slot: first close the '
                                                 'server running outside the panel (Server > Ports).'), 'page': 'server'})
    if migration_error():
        out.append({'type': 'error', 'text': migration_error(), 'page': 'saves'})
    if FRD.active():
        out.append({'type': 'warning', 'text': _("You are on a friend's server (%s): Play is unavailable. Leave from the Play with Friends page.",
                                               FRD.m['address']), 'page': 'friend'})
    slot = SAV.active()
    if not slot:
        out.append({'type': 'error', 'text': _('No saves yet: create a new save on the Saves page.'), 'page': 'saves'})
    c = IST.check(client_folder() if folder is False else folder)
    if not c['valid'] and DL.running():
        out.append({'type': 'warning', 'text': _('Downloading the game client: %d%%. You can play when it is done.', _dl_pct(DL.state())),
                    'page': 'client'})
    elif not c['valid']:
        out.append({'type': 'error', 'text': _('Game client not found: %s Choose its folder or download the game on the Client page.',
                                              ' '.join(c['issues'])), 'page': 'client'})
    elif c['old']:                                                  # a new version is out: updated with one click (/api/istemci/guncelle)
        dl, sup = DL.state(), IST.supported()
        run = bool(STATE.get('old_client')) and dl['running']
        text = (_('Updating the game to version %s: %d%%. When it is done the old version is deleted and BepInEx is reinstalled.', sup, _dl_pct(dl))
                 if run else _("DarkOrbit version %s is out and your client is %s: the game won't work properly unless you update. "
                               'Update downloads and installs the new one and deletes the old one.', sup, c['version']))
        if STATE.get('old_client') and dl['state'] == 'error':
            text += ' ' + dl['error']
        out.append({'type': 'error', 'text': text, 'progress': _dl_pct(dl) if run else None, 'download': dl if run else None,
                    'page': 'client',
                    'action': {'text': _('Update'), 'api': '/api/client/update', 'running': run,
                              'running_text': _('Updating…')}})
    elif not c['compatible']:
        out.append({'type': 'warning', 'text': c['issues'][-1], 'page': 'client'})
    error = RUN.find(CFG)['error']                                      # Linux and macOS: Wine or Proton (Rosetta on Apple Silicon)
    if error:
        w = {'type': 'error', 'text': error, 'page': 'client'}
        if RUN.rosetta_error():
            ros = ENG.state()['rosetta']
            w['action'] = {'text': _("Install Rosetta"), 'api': '/api/rosetta/install', 'running': ros['state'] == 'installing'}
            if ros['error']:
                w['text'] += ' ' + ros['error']
        out.append(w)
    m = ENG.state() if sys.platform == 'darwin' else None
    if m and m['running']:
        out.append({'type': 'warning', 'text': _('Downloading Wine and DXMT: %d%%. You can play when it is done.',
                                               int(100 * m['claimed'] / m['total']) if m['total'] else 0), 'page': 'client'})
    elif m and m['state'] == 'error':
        out.append({'type': 'error', 'text': _("The panel's Wine could not be installed: %s", m['error']), 'page': 'client'})
    error = PR.port_80_problem()
    if error:
        out.append({'type': 'error', 'text': error, 'page': 'server'})
    missing = [n for n in PTH.TEMPLATES if not PTH.template(n)]       # your own record or the shareable copy (data/defaults)
    if missing:
        out.append({'type': 'warning', 'text': _('Login templates are missing (%s): the game starts with a minimal login, some windows and the shop '
                                                 'may be empty.', ', '.join(missing)), 'page': 'server'})
    u = UPD.state()
    if u['state'] in ('downloading', 'installing'):
        out.append({'type': 'warning', 'text': _('The panel is updating; it restarts by itself when done.'), 'page': 'panel'})
    elif u['state'] == 'exists' and CFG.get('update') != 'off':
        auto = CFG.get('update') == 'auto' and CFG.get('setup_done')
        out.append({'type': 'warning', 'text': _('New version available (%s): it installs by itself when the game and servers are closed.', u['last']['version'][:7])
                    if auto else _('New version available (%s): you can install it on the Panel page.', u['last']['version'][:7]), 'page': 'panel'})
    elif u['state'] == 'installed':
        out.append({'type': 'warning', 'text': _('Update installed: the panel restarts when the game and servers are closed.'), 'page': 'panel'})
    alive = MANAGER.servers_alive()
    table = PR.listeners()
    foreign = [p for name, ports in PR.PORTS.items() for p in ports if not alive.get(name) and PR.listening(p, table)]
    if foreign:
        out.append({'type': 'warning', 'text': _("A process the panel didn't start is holding the game ports (%s). It may be a server left over from "
                                                 'a previous session: check the Server page.', ', '.join(map(str, foreign))),
                    'page': 'server'})
    for name, s in MANAGER.servers.items():
        if s.crashed:
            out.append({'type': 'error', 'text': _('The %s server closed unexpectedly (exit code %s). Details: Server > Logs > %s_console.log', _({'game': 'Game', 'web': 'Web'}[name]), s.proc.poll(), name),
                        'page': 'server'})
    return out


def status():
    STATE['heartbeat'] = time.monotonic()
    STATE['window_closed'] = False                  # a window is asking again (the one opened by a second launch too)
    if STATE.get('migration_pending'):
        try_migrate()
    slot = SAV.active()
    try:
        active = SAV.summary(slot) if slot else None
    except (OSError, SaveError):
        active = None
    if active:
        active['world_info'] = world_info(active.get('world'))
    vals = game_settings()
    ev = [e['name'] for e in event_list() if e['enabled'] and e['type'] == 'yearly']
    slots = SAV.slots()
    folder = client_folder()                     # client folder search (glob) once: warnings and the response
    return {'processes': MANAGER.status(), 'active': active, 'save_count': len(slots),
            'settings_summary': settings_summary(vals), 'events': ev,
            'warnings': warnings(folder), 'play': STATE['play'], 'client_folder': folder,
            'friend': {'host': MANAGER.running() and MANAGER.friend, 'guest': FRD.m['state'], 'address': FRD.m['address']},
            'multi': multi_status(slots),
            'panel': {'version': VERSION, 'window_closed': STATE['window_closed'], 'lang': CFG.get('lang'), 'platform': sys.platform,
                      'setup_done': CFG.get('setup_done'), 'updated': STATE['updated'],
                      'uptime_sec': int(time.time() - STATE['opening'])}}


# ------------------------------------------------------------------ multi-client (multi_client.py)
def multi_env():
    """The multi-client's game server settings (OO_MULTIPLAYER; multiplayer.configure): this computer only, no guests."""
    return json.dumps({'address': '127.0.0.1', 'guest': False, 'key': FRD.key, 'code': VERSION, 'local': FRD.local})


def multi_wanted(slot):
    """Should PLAY open the server in multi-session mode: the setting is on and there are at least two saves (the server of one with a
    single save stays single player), or the server is already open that way with this save."""
    return bool(CFG.get('multi_client') and len(SAV.slots()) > 1) or (MANAGER.running() and MANAGER.multi and MANAGER.slot == slot)


def multi_status(slots):
    """The Play page's Multi-client card: open extra clients, recent closings and the saves that can be opened in an extra client."""
    live = read_json(os.path.join(PTH.LOGS, 'live_status.json'), None) if MULTI.live() else None
    out = dict(MULTI.state(live), setting=CFG.get('multi_client'), max_count=CFG.get('multi_client_max'), save_count=len(slots),
               server=MANAGER.running() and (MANAGER.multi or MANAGER.friend), main=MANAGER.slot if MANAGER.running() else None, saves=[])
    if out['setting'] and len(slots) > 1:
        for s in slots:
            try:
                k = SAV.summary(s)
            except (OSError, SaveError):
                continue
            out['saves'].append({'id': s, 'name': k['name'], 'pilot': k.get('pilot'), 'level': k.get('level'), 'company': k.get('company'),
                                    'corrupt': k.get('corrupt'), 'extra': MULTI.in_use(s), 'friend': FRD.in_use(s)})
    return out


def open_extra(b):
    """Multi-client: an extra client with another save. The server must be open in multi-session mode; if it is open as single player and
    the game is closed it is restarted that way."""
    slot = str(b.get('record') or '')
    if not slot or not SAV.exists(slot):
        raise Error(_('Save not found.'))
    if not CFG.get('multi_client'):
        raise Error(_('Multi-client is off: you can turn it on on the Client page.'))
    if FRD.active():
        raise Error(_("You can't open an extra client while on a friend's server."))
    if STATE['play']['running']:
        raise Error(_('Launch in progress.'))
    if not MANAGER.running():
        raise Error(_('First start the game (or just the server) with PLAY: extra clients connect to the same server.'))
    if FRD.in_use(slot):
        raise Error(_("This save is in use on a friend's server."))
    if not (MANAGER.multi or MANAGER.friend):
        if MANAGER.client_alive() or MULTI.live():
            raise Error(_('The server started in single-player mode: for an extra client, close the game and press PLAY again.'))
        log('multi-client: restarting the server in multi-session mode')
        MANAGER.start_servers(SAV.profile(MANAGER.slot), settings_file(MANAGER.slot), control=bool(SET.read(settings_file(MANAGER.slot)).get('control')), slot=MANAGER.slot,
                          multi=multi_env(), world=world_file(MANAGER.slot), bot=bot_file(MANAGER.slot))
    return MULTI.open_(slot, client_folder(), MANAGER.slot)


def clients_closed():
    """The main client or an extra client closed: the panel's behavior if all have closed (close the servers, exit if the window closed).
    If the main client was not opened in this server session (server only) or closed early, the servers stay open."""
    if MANAGER.client_alive() or MULTI.live():
        return                                        # a client is running: the servers stay open
    game, last = MANAGER.servers.get('game'), MANAGER.last_client
    if not (game and game.alive and MANAGER.client_started and MANAGER.client_started >= game.started_at and last and not last['early']):
        return
    if CFG.get('when_client_closes') == 'close':
        MANAGER.stop_servers()
    if STATE['window_closed']:
        threading.Thread(target=shutdown, daemon=True).start()


MULTI.on_exit = clients_closed


# ------------------------------------------------------------------ play
def _step(text, state='running'):
    o = STATE['play']
    if o['steps'] and o['steps'][-1]['state'] == 'running':
        o['steps'][-1]['state'] = 'done'
    o['steps'].append({'text': text, 'state': state, 'time': time.strftime('%H:%M:%S')})


def launch(server_only=False, friend=False):
    o = STATE['play']
    try:
        _step(_('Checking'))
        if FRD.active():
            raise Error(_("You are on a friend's server: leave it first."))
        if friend and MANAGER.running() and not MANAGER.friend and MANAGER.client_alive():
            raise Error(_('Close the game first: the server must restart as a friend server.'))
        slot = SAV.active()
        if not slot:
            raise Error(_('Create a save on the Saves page first.'))
        if MULTI.in_use(slot):
            raise Error(_('The active save is open in an extra client: close that client first or make another save active.'))
        folder = client_folder()
        SM.migrate_client(folder, log)                  # files in the old version's client folder (visual dump, texts)
        if not server_only:
            c = IST.check(folder)
            if STATE.get('old_client') and DL.running():
                raise Error(_('Updating the game to version %s (%d%%). You can play when it is done.', IST.supported(), _dl_pct(DL.state())))
            if not c['valid'] and DL.running():
                raise Error(_('The game client is still downloading (%d%%). You can play when it is done.', _dl_pct(DL.state())))
            if not c['valid']:
                raise Error(_('Invalid client folder: %s', ' '.join(c['issues'])))
            if MANAGER.client_alive():
                raise Error(_('The game is already running.'))
            others = IST.running_clients(MULTI.pids())                     # the panel's extra clients do not count
            if others:
                raise Error(_('Another DarkOrbit client is running (process %s). Close it first.', ', '.join(map(str, others))))
            r = RUN.find(CFG)
            if r['type'] == 'engine' and not r['error'] and not r['route']:      # macOS: the panel's Wine is downloaded on the first PLAY (wine_engine.py)
                _step(_('Downloading Wine and DXMT'))
                ENG.wait(lambda pct: STATE['play']['steps'][-1].update(text=_('Downloading Wine and DXMT: %d%%', pct)))
            if not PATCH.installed(folder):                   # the client's fixes: on the first PLAY if BepInEx was not installed in the wizard
                _step(_('Installing BepInEx'))
                if not PATCHER.wait(folder, lambda pct: o['steps'][-1].update(text=_('Installing BepInEx: %d%%', pct))):
                    o['steps'][-1].update(text=_('BepInEx could not be installed; the game opens without the fixes: %s',
                                                    PATCHER.state(folder)['error']), state='error')
            cmd, env = IST.command(CFG, folder, os.path.join(PTH.LOGS, 'client.log'))     # if there is no Wine / Proton, an error before the servers open
            if PATCH.installed(folder) and not PATCH.ready(folder):  # BepInEx's interop assemblies before the game (client_patch.warm_up)
                _step(_('Preparing BepInEx for the first launch (about half a minute)'))
                if not PATCH.warm_up(folder, cmd, env, PTH.LOGS, lambda d: o['steps'][-1].update(progress=d)):
                    o['steps'][-1].update(text=_("BepInEx couldn't be prepared, starting the game anyway"), state='error')
        prof = SAV.profile(slot)
        same = MANAGER.running() and MANAGER.slot == slot
        friend = friend or (MANAGER.running() and MANAGER.friend)    # an open friend server is not closed by Play (so guests are not dropped)
        friend_env = FRD.host_env() if friend else None
        multi = None if friend else (multi_env() if multi_wanted(slot) else None)
        restart = MANAGER.needs_restart(prof, friend_env, multi, world_file(slot, friend), bot_file(slot, friend))
        if restart and MULTI.live():
            raise Error(_("The server can't be restarted while extra clients are open: close them first."))
        if CFG.get('backup_on_launch') and not same:
            _step(_('Backing up the save'))
            SAV.backup(slot, 'auto', _('Play (launch)'))
            STATE['last_backup'] = time.time()
        if not MANAGER.running() and CFG.get('rotate_logs'):
            import launcher
            launcher.rotate_logs(PTH.LOGS, names=('gs.log', 'http.log', 'client.log', 'game_console.log', 'web_console.log',
                                                'panel.log'))
        _step((_('Starting the friend server') if friend else _('Starting the servers'))
              if not MANAGER.running() or restart else _('Servers running'))
        MANAGER.start_servers(prof, settings_file(slot), control=bool(SET.read(settings_file(slot)).get('control')), slot=slot, friend=friend_env,
                          multi=multi, world=world_file(slot, friend), bot=bot_file(slot, friend))
        if not server_only:
            _step(_('Opening the game'))
            try:                                      # the world's quest titles (read by the plugin's QuestTexts patch)
                WLD.write_texts(folder, world_id(slot, friend))
            except OSError as e:
                log('quest texts could not be written: %s' % e)
            write_legacy_upgrade(folder, slot)
            MANAGER.start_client(folder, cmd, env)
            if MANAGER.multi or MANAGER.friend:              # there can be several clients: windows are told apart by the pilot's name
                PR.window_title(MANAGER.client.pid, 'DarkOrbit — %s' % SAV.summary(slot).get('pilot', slot))
            m = SAV.meta(slot)
            SAV.set_meta(slot, last_played=time.strftime('%Y-%m-%d %H:%M:%S'), play_count=int(m.get('play_count') or 0) + 1)
        _step(_('Ready') if server_only else _('Game started: have a good flight!'), 'done')
        o['finished'] = time.time()
    except (Error, SaveError, RuntimeError, OSError) as e:
        o['error'] = str(e)
        _step(str(e), 'error')
        log('play error: %s' % e)
    except Exception as e:
        o['error'] = _('Unexpected error: %r', e)
        _step(o['error'], 'error')
        log('play error: %s' % traceback.format_exc())
    finally:
        o['running'] = False


def migration_error():
    """The message shown to the user if the saves could not be migrated to the new format (paths.MIGRATION_ERROR), otherwise None."""
    return _('Your saves could not be moved to the new format (%s). The backup of the old saves is under '
             'server/save (v1_backup_*.zip); the servers will not start.', PTH.MIGRATION_ERROR) if PTH.MIGRATION_ERROR else None


def start_launch(server_only=False, friend=False):
    o = STATE['play']
    if migration_error():
        raise Error(migration_error())
    if o['running']:
        raise Error(_('Launch in progress.'))
    o.update(running=True, steps=[], error=None, finished=None, server_only=bool(server_only))
    threading.Thread(target=launch, args=(server_only, friend), daemon=True).start()
    return o


def join_friend(b):
    """Play with Friends > Join: checks in the panel (client, open game and servers), joining in the background (friends.py)."""
    if migration_error():
        raise Error(migration_error())
    if STATE['play']['running']:
        raise Error(_('Launch in progress.'))
    slot = str(b.get('record') or '') or SAV.active()
    if not slot or not SAV.exists(slot):
        raise Error(_('Create a save on the Saves page first.'))
    folder = client_folder()
    c = IST.check(folder)
    if not c['valid']:
        raise Error(_('Invalid client folder: %s', ' '.join(c['issues'])))
    if MANAGER.client_alive() or IST.running_clients():
        raise Error(_('The game is already running.'))
    if MANAGER.running():
        raise Error(_('First stop your own server (Play > Stop server).'))
    cmd, env = IST.command(CFG, folder, os.path.join(PTH.LOGS, 'client.log'))

    def open_client():
        MANAGER.start_client(folder, cmd, env)
        m = SAV.meta(slot)
        SAV.set_meta(slot, last_played=time.strftime('%Y-%m-%d %H:%M:%S'), play_count=int(m.get('play_count') or 0) + 1)
    return FRD.killer(str(b.get('address') or ''), str(b.get('password') or ''), slot, c['version'] or IST.supported(), open_client)


def on_client_exit(early):
    if FRD.client_closed():                         # leaves the friend's server, the guest's web server closes
        return
    if early:
        return
    clients_closed()                              # if extra clients are running the servers stay open


MANAGER.on_client_exit = on_client_exit


def idle(strict=False):
    """Can an update be installed: game, servers, launch, client download, protocol tool stopped (strict: no DarkOrbit client the panel
    did not open either; tasklist works)."""
    busy = (MANAGER.running() or MANAGER.client_alive() or STATE['play']['running'] or DL.running() or ADAPTER.state()['running']
            or FRD.active() or MULTI.live() or ENG.running() or PATCHER.running() or LLM.running())
    return not busy and not (strict and IST.running_clients())


def update_tick(now):
    """GitHub check (every GUNCELLEME_SN), automatic install and restart after installation (when idle)."""
    mode = CFG.get('update')
    st = UPD.state()
    if st['running']:
        return
    if st['state'] == 'installed':
        if idle(strict=True):
            restart()
        return
    if mode == 'off':
        return
    if now >= STATE['next_check']:
        st = UPD.check()
        STATE['next_check'] = now + (3600 if st['state'] == 'error' else UPDATE_SEC)
    if st['state'] == 'exists' and mode == 'auto' and CFG.get('setup_done') and idle(strict=True):
        UPD.install_async()


def restart():
    """Restart after an update: the new process (without opening a window) takes the same port when the old one closes; the open window
    refreshes the page."""
    STATE['closing'] = True
    args = [sys.executable, os.path.join(PANEL_DIR, 'panel.py'), '--no-window', '--updated', '--port=%d' % PORT]
    log('panel updated: restarting')
    try:
        if os.name == 'nt':
            subprocess.Popen(args, cwd=ROOT, close_fds=True, creationflags=0x00000008 | 0x00000200)   # DETACHED, new process group
        else:
            subprocess.Popen(args, cwd=ROOT, close_fds=True, start_new_session=True)
        if STATE['srv']:
            STATE['srv'].server_close()
    finally:
        os._exit(0)


def ticker():
    """Periodic backup while the game runs; exit if the window closed and no work remains; update (update_tick)."""
    while not STATE['closing']:
        time.sleep(5)
        try:
            update_tick(time.time())
            iv = CFG.get('backup_interval_min')
            if MANAGER.client_alive() and MANAGER.slot and iv and time.time() - STATE['last_backup'] >= iv * 60:
                SAV.backup(MANAGER.slot, 'auto', _('During the game'))
                STATE['last_backup'] = time.time()
            MULTI.backup(iv)                           # saves of the extra clients
            if not STATE['window_watched'] and time.monotonic() - STATE['heartbeat'] > HEARTBEAT_SEC and not STATE['window_closed']:
                STATE['window_closed'] = True
                log('panel window closed (the page no longer asks)')
                if CFG.get('when_window_closes') == 'close':
                    MANAGER.stop_client()
                    MULTI.close_all(wait=8)
            if STATE['window_closed'] and not MANAGER.client_alive() and not MULTI.live() and not STATE['play']['running']:
                shutdown()
        except Exception:
            log('timer error: %s' % traceback.format_exc())


def wait_for_client(sec=8):
    """stop_client only sends a signal: wait until the client closes (otherwise shutdown left the servers open and exited)."""
    last = time.time() + sec
    while MANAGER.client_alive() and time.time() < last:
        time.sleep(0.2)


def shutdown():
    if STATE['closing']:
        return
    STATE['closing'] = True
    log('panel shutting down')
    try:
        DL.cancel()                                   # download: extracted files stay, then it resumes from where it left off
        ENG.cancel()
        if not MANAGER.client_alive() and not MULTI.live():
            FRD.shutdown()                             # if on the friend's server, leave (final state to the save)
            MANAGER.stop_servers()
        w = STATE.get('windowed')
        if w and w.poll() is None:                    # the app window the panel opened closes too
            w.terminate()
    finally:
        os._exit(0)


# ------------------------------------------------------------------ window
def browser():
    """A browser that can open an app window (--app): Edge or Chrome (Chromium and Brave too on Linux and macOS) or None."""
    if sys.platform == 'darwin':
        cands = ['/Applications/%s.app/Contents/MacOS/%s' % (a, a) for a in ('Microsoft Edge', 'Google Chrome', 'Chromium', 'Brave Browser')]
    elif os.name != 'nt':
        cands = [shutil.which(n) for n in ('microsoft-edge', 'microsoft-edge-stable', 'google-chrome', 'google-chrome-stable',
                                           'chromium', 'chromium-browser', 'brave-browser')]
    else:
        cands = []
        for env in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
            base = os.environ.get(env)
            if base:
                cands += [os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                          os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe')]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def open_window(url):
    """App window (Edge/Chrome --app, the panel's own browser profile) -> a process that can be watched or None."""
    b = browser()
    if not b:
        import webbrowser
        webbrowser.open(url)
        return None
    old = os.path.join(os.path.dirname(BROWSER_PROFILE), 'tarayici')      # old name (before 2026-11-01): so window size and permissions stay
    if os.path.isdir(old) and not os.path.exists(BROWSER_PROFILE):
        try:
            os.replace(old, BROWSER_PROFILE)
        except OSError:
            pass                                        # old window open: opens with the new profile
    os.makedirs(BROWSER_PROFILE, exist_ok=True)
    return subprocess.Popen([b, '--app=%s' % url, '--user-data-dir=%s' % BROWSER_PROFILE, '--window-size=1360,880',
                             '--no-first-run', '--no-default-browser-check', '--disable-features=Translate,msEdgeSidebarV2',
                             '--disable-background-mode', '--disable-sync', '--lang=%s' % D.LANGUAGES[D.current()][1]])


def watch_window(proc):
    STATE['windowed'] = proc
    if sys.platform == 'darwin':
        # on macOS when the window closes the browser (like other apps) stays open in the Dock: the process cannot be waited on. Closing
        # is detected from the page's close mark and heartbeat (/api/kapandi, ticker; the mark also arrives when the browser is quit);
        # when the panel closes this process closes too (shutdown)
        return
    STATE['window_watched'] = True
    t0 = time.time()
    proc.wait()
    STATE['window_watched'] = False
    if time.time() - t0 < HANDOVER_SEC:
        # if a browser process is open with the same profile folder, the new process hands the window over to it and exits at once (18, 20
        # and 22 Oct: as soon as the panel opened it was considered "closed" and shut down): the window is open, its closing is detected
        # from the page's heartbeat (ticker)
        STATE['heartbeat'] = time.monotonic()
        log('panel window handed over to a running browser process; watching by heartbeat')
        return
    log('panel window closed')
    if CFG.get('when_window_closes') == 'close':
        MANAGER.stop_client()
        MULTI.close_all(wait=8)                   # so the extra clients' final save is released to the server
        wait_for_client()
        shutdown()
    STATE['window_closed'] = True


SHORTCUT, OLD_SHORTCUT = 'OpenOrbit.lnk', 'DarkOrbit.lnk'   # old: one placed before 2026-10-24 (opens the removed "DarkOrbit Panel.pyw")


def desktop_dir():
    """Desktop folder (also if moved to OneDrive; on Linux what xdg-user-dir says)."""
    if os.name != 'nt':
        try:
            d = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            d = ''
        return d if os.path.isdir(d) else os.path.join(os.path.expanduser('~'), 'Desktop')
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)      # CSIDL_DESKTOPDIRECTORY
    return buf.value or os.path.join(os.path.expanduser('~'), 'Desktop')


def old_shortcut():
    """Path of the old-named shortcut on the desktop or None: only one whose target is this panel's old launcher "DarkOrbit Panel.pyw"
    (not the game's own DarkOrbit shortcut). The shortcut is not changed automatically; when the user presses "Create shortcut" the new
    one is put in place."""
    p = os.path.join(desktop_dir(), OLD_SHORTCUT)
    try:
        with open(p, 'rb') as fh:
            return p if 'DarkOrbit Panel.pyw'.encode('utf-16-le') in fh.read() else None
    except OSError:
        return None


def mac_shortcut(script):
    """macOS: OpenOrbit.app on the desktop (a small app bundle that starts the panel in the background; no Terminal window opens, it does
    not stay in the Dock; the icon is the panel's, with sips and iconutil) -> its path. The OpenOrbit.command put by old versions is
    removed."""
    app = os.path.join(desktop_dir(), 'OpenOrbit.app')
    if os.path.isdir(app):
        shutil.rmtree(app)
    for d in ('MacOS', 'Resources'):
        os.makedirs(os.path.join(app, 'Contents', d))
    exe = os.path.join(app, 'Contents', 'MacOS', 'OpenOrbit')
    with open(exe, 'w', encoding='utf8', newline='\n') as fh:
        fh.write('#!/bin/sh\ncd %s && nohup %s %s >/dev/null 2>&1 &\n' % (shlex.quote(ROOT), shlex.quote(sys.executable),
                                                                         shlex.quote(script)))
    os.chmod(exe, 0o755)
    icon = _mac_icon(os.path.join(app, 'Contents', 'Resources', 'OpenOrbit.icns'))
    plist = {'CFBundleName': 'OpenOrbit', 'CFBundleDisplayName': 'OpenOrbit', 'CFBundleIdentifier': 'io.github.kaanumay.openorbit',
             'CFBundleExecutable': 'OpenOrbit', 'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': VERSION,
             'LSUIElement': True}
    if icon:
        plist['CFBundleIconFile'] = 'OpenOrbit.icns'
    import plistlib
    with open(os.path.join(app, 'Contents', 'Info.plist'), 'wb') as fh:
        plistlib.dump(plist, fh)
    old = os.path.join(desktop_dir(), 'OpenOrbit.command')
    try:
        with open(old, encoding='utf8') as fh:
            if shlex.quote(script) in fh.read():
                os.remove(old)
    except OSError:
        pass
    subprocess.run(['touch', app], capture_output=True)      # so Finder refreshes the icon
    return app


def _mac_icon(out):
    """The panel's icon (arayuz/icon.png, 512x512) -> .icns; None if it fails (the app opens with the generic icon)."""
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as tmp:
            big, iconset = os.path.join(UI_DIR, 'icon.png'), os.path.join(tmp, 'OpenOrbit.iconset')
            run = lambda *a: subprocess.run(list(a), capture_output=True, timeout=30).returncode == 0
            os.makedirs(iconset)
            for n in (16, 32, 128, 256, 512):
                for k, suffix in ((1, ''), (2, '@2x')):
                    run('sips', '-z', str(n * k), str(n * k), big, '--out', os.path.join(iconset, 'icon_%dx%d%s.png' % (n, n, suffix)))
            return out if run('iconutil', '-c', 'icns', iconset, '-o', out) else None
    except (OSError, subprocess.SubprocessError):
        return None


def refresh_shortcut(create=None):
    """If the desktop shortcut points to the icon path from before 2026-11-01 (server/panel/arayuz/simge.*; arayuz -> ui in the English
    migration) it is recreated; if absent or up to date it is not touched -> was it renewed."""
    if sys.platform == 'darwin':                      # OpenOrbit.app copies the icon into itself
        return False
    if os.name == 'nt':
        p, old = os.path.join(desktop_dir(), SHORTCUT), os.path.join('ui', 'simge.ico').encode('utf-16-le')
    else:
        p, old = os.path.join(desktop_dir(), 'openorbit.desktop'), b'arayuz/simge.png'
    if not os.path.isfile(p):
        return False
    try:
        with open(p, 'rb') as fh:
            if old not in fh.read():
                return False
        (create or create_shortcut)()
        log('shortcut renewed (icon path)')
        return True
    except Exception as e:                            # the panel works without a shortcut too
        log('shortcut could not be renewed: %s' % e)
        return False


def unix_shortcut():
    """Linux: openorbit.desktop on the desktop and in the application menu; macOS: OpenOrbit.app on the desktop (mac_shortcut) -> the path
    of the one on the desktop."""
    script = os.path.join(ROOT, 'OpenOrbit Panel.pyw')
    os.makedirs(desktop_dir(), exist_ok=True)
    if sys.platform == 'darwin':
        return mac_shortcut(script)
    text = ('[Desktop Entry]\nType=Application\nName=OpenOrbit\nComment=%s\nExec="%s" "%s"\nPath=%s\nIcon=%s\nTerminal=false\n'
            'Categories=Game;\n' % (_('OpenOrbit local server panel'), sys.executable, script, ROOT, os.path.join(UI_DIR, 'icon.png')))
    menu = os.path.join(os.path.expanduser('~'), '.local', 'share', 'applications')
    os.makedirs(menu, exist_ok=True)
    for d in (menu, desktop_dir()):
        p = os.path.join(d, 'openorbit.desktop')
        with open(p, 'w', encoding='utf8', newline='\n') as fh:
            fh.write(text)
        os.chmod(p, 0o755)
    if shutil.which('gio'):                           # GNOME does not open a desktop shortcut without treating it as "trusted"
        subprocess.run(['gio', 'set', p, 'metadata::trusted', 'true'], capture_output=True, timeout=10)
    return p


def create_shortcut():
    """OpenOrbit shortcut on the desktop; an old-named shortcut (old_shortcut), if any, is removed -> the path of the new shortcut."""
    if os.name != 'nt':
        return unix_shortcut()
    target = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    if not os.path.isfile(target):
        target = sys.executable
    script = os.path.join(ROOT, 'OpenOrbit Panel.pyw')
    icon = os.path.join(UI_DIR, 'icon.ico')
    lnk = os.path.join(desktop_dir(), SHORTCUT)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:OO_SHORTCUT); $s.TargetPath=$env:OO_TARGET; "
          "$s.Arguments=('\"'+$env:OO_SCRIPT+'\"'); $s.WorkingDirectory=$env:OO_ROOT; $s.IconLocation=($env:OO_ICON+',0'); "
          "$s.Description=$env:OO_DESCRIPTION; $s.Save()")
    env = dict(os.environ, OO_SHORTCUT=lnk, OO_TARGET=target, OO_SCRIPT=script, OO_ROOT=ROOT, OO_ICON=icon,
               OO_DESCRIPTION=_('OpenOrbit local server panel'))
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True, env=env,
                       timeout=30, creationflags=PR.NO_WINDOW, encoding='utf8', errors='replace')
    if r.returncode or not os.path.isfile(lnk):
        raise Error(_('The shortcut could not be created: %s', r.stderr.strip()[-300:]))
    old = old_shortcut()
    if old:
        os.remove(old)
        log('old shortcut removed: %s' % old)
    return lnk


# ------------------------------------------------------------------ API
def screen_size():
    if sys.platform == 'darwin':                      # the main screen's point resolution (what Wine shows; half the pixels on Retina)
        try:
            r = subprocess.run(['system_profiler', 'SPDisplaysDataType', '-json'], capture_output=True, text=True, timeout=10)
            for gpu in json.loads(r.stdout).get('SPDisplaysDataType', []):
                for d in gpu.get('spdisplays_ndrvs', []):
                    m = re.match(r'\s*(\d+)\s*x\s*(\d+)', d.get('_spdisplays_resolution', ''))
                    if m and d.get('spdisplays_main') == 'spdisplays_yes':
                        return [int(m.group(1)), int(m.group(2))]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return None
    try:
        import ctypes
        u = ctypes.windll.user32
        u.SetProcessDPIAware()
        return [u.GetSystemMetrics(0), u.GetSystemMetrics(1)]
    except Exception:
        return None


def _schema_row(s):
    out = dict(s, name=_(s['name']), description=_(s['description']))
    if s.get('options'):
        out['options'] = [_(x) for x in s['options']]
    if s.get('option_description'):
        out['option_description'] = [_(x) for x in s['option_description']]
    if s.get('unit'):
        out['unit'] = _(s['unit'])
    return out


def write_legacy_upgrade(folder=None, slot=None):
    """Uridium costs of the old upgrade system into the client's BepInEx folder (the plugin's EskiYukseltme patch replaces the Assembly's
    recipes with them; {} when off: the client's own ingredients). On PLAY and when settings are saved."""
    folder = folder or client_folder()
    if not folder or not os.path.isdir(os.path.join(folder, 'BepInEx')):
        return
    import upgrades as UPG
    v = SET.read(settings_file(slot))
    t = UPG.legacy_table(v.get('legacy_upgrade', SET.DEFAULTS['legacy_upgrade']),
                      v.get('legacy_upgrade_price', SET.DEFAULTS['legacy_upgrade_price']))
    try:
        WLD._write_file(os.path.join(folder, 'BepInEx', 'openorbit', 'legacy_upgrade.json'), t)
    except OSError as e:
        log('old upgrade costs could not be written: %s' % e)


def api_settings():
    ready = {k: dict(p, name=_(p['name']), description=_(p['description'])) for k, p in SET.PRESETS.items()}
    slot = SAV.active()
    return {'schema': [_schema_row(s) for s in SET.SCHEMA], 'groups': [{'key': k, 'name': _(a)} for k, a in SET.GROUPS],
            'values': game_settings(), 'default': SET.DEFAULTS, 'ready': ready, 'templates': read_json(TEMPLATES, {}),
            'server_running': MANAGER.running(), 'record': slot, 'save_name': SAV.meta(slot).get('name', slot) if slot else None,
            'saves': [{'id': s, 'name': SAV.meta(s).get('name', s)} for s in SAV.slots() if s != slot]}


def launch_command():
    """The launch command shown on the Client page (with Wine or Proton on Linux and macOS; only the client's if not found)."""
    if os.name == 'nt':
        folder = client_folder()
        return ['DarkOrbit.exe'] + IST.args(CFG, 'logs\\client.log') + (PATCH.ARGS if folder and PATCH.installed(folder) else [])
    try:
        return IST.command(CFG, client_folder() or ROOT, os.path.join(PTH.LOGS, 'client.log'), prepare=False)[0]
    except RuntimeError:
        return [IST.EXE] + IST.args(CFG, 'logs/client.log')


def api_client():
    sel = CFG.get('client_folder')
    used = client_folder()
    return {'selected': sel, 'used': used, 'control': IST.check(used), 'candidates': IST.candidates(),
            'resolutions': IST.RESOLUTIONS, 'screen': screen_size(), 'settings': CFG.all(),
            'command': launch_command(), 'runner': RUN.summary(CFG), 'supported': IST.supported(),
            'protokol': ADAPTER.state(), 'download': DL.state(), 'patch': PATCHER.state(used)}


def extra_logs():
    """Logs of the extra clients (logs/client_<save>.log)."""
    try:
        return tuple(sorted(f for f in os.listdir(PTH.LOGS) if EXTRA_LOG.fullmatch(f)))
    except OSError:
        return ()


def slot_arg(q):
    sid = q.get('id')
    if not sid or not SAV.exists(sid):
        raise Error(_('Save not found.'))
    return sid


def profile_values(sid):
    d = read_json(SAV.profile(sid), {})
    pl, g = d.get('pilot') or {}, d.get('ship') or {}
    return {'pilot': pl.get('userName', ''), 'credits': pl.get('credits', 0), 'uridium': pl.get('uridium', 0),
            'honor': pl.get('honourPoints', 0), 'ep': pl.get('ep', 0), 'level': pl.get('level', 1),
            'hp': g.get('hitPoints', 0), 'max_hp': g.get('hitMax', 0), 'shield': g.get('shield', 0),
            'shield_max': g.get('shieldMax', 0), 'company': COMPANIES.get(pl.get('factionId'), '?'),
            'in_use': SAV.in_use(sid)}


def worlds_status():
    users = world_users()
    return {'entries': WLD.entries(users), 'covers': WLD.COVERS, 'server_running': MANAGER.running(),
            'server_world': MANAGER.world[0] if MANAGER.running() and MANAGER.world else None, 'saves': [
                {'id': k['id'], 'name': k.get('name'), 'pilot': k.get('pilot'), 'company': k.get('company'), 'level': k.get('level'),
                 'world': k.get('world') if k.get('world') and WLD.var(k.get('world')) else WLD.STANDARD, 'active': k.get('active')}
                for k in SAV.list()]}


def world_arg(q):
    did = q.get('world') or WLD.STANDARD
    if not WLD.var(did):
        raise Error(_('World not found.'))
    return did


def world_get(path, q):
    if path == '/api/worlds':
        return worlds_status()
    if path == '/api/world':
        did = world_arg(q)
        is_open = bool(MANAGER.running() and MANAGER.world and WLD.file_path(did) and MANAGER.world[0] == os.path.normcase(WLD.file_path(did)))
        # yeniden_gerekli: after the server opened, a change that cannot be applied while the game is open was made (shop and auction are
        # live)
        return dict(WLD.summary(did, world_users()), server_in_this_world=is_open,
                    restart_needed=is_open and PR.world_signature(WLD.file_path(did)) != MANAGER.world)
    if path == '/api/world/section':
        did, section = world_arg(q), q.get('section')
        if section == 'alien_spawns':
            return {'alien_spawns': WLD.aliens(did)}
        if section == 'maps':
            return {'maps': WLD.maps(did)}
        if section == 'quests':
            return {'quests': WLD.quests(did)}
        if section == 'shop':
            return {'categories': WLD.shop(did), 'visual': bool(game_image('dizin.json'))}
        if section == 'auction':
            return WLD.auction(did)
        if section == 'boxes':
            return WLD.boxes(did)
        if section == 'gates':
            return {'gates': WLD.gates(did)}
        if section == 'economy':
            return WLD.economy(did)
        if section == 'events':
            return {'events': WLD.events(did), 'classes': WLD.MAP_CLASSES}
        raise Error(_('Unknown section.'))
    if path == '/api/world/map':
        return WLD.game_map(world_arg(q), q.get('id'))
    if path == '/api/world/quest':
        return WLD.quest(world_arg(q), q.get('id'))
    if path == '/api/world/items':
        return {'items': WLD.item_list()}
    raise Error(_('Unknown request.'))


def world_post(path, b):
    if path == '/api/saves/world':               # the save's default world (PLAY opens with it)
        sid, did = b.get('id'), b.get('world') or WLD.STANDARD
        if not sid or not SAV.exists(sid):
            raise Error(_('Save not found.'))
        if not WLD.var(did):
            raise Error(_('World not found.'))
        SAV.set_meta(sid, world=None if did == WLD.STANDARD else did)
        return worlds_status()
    if path == '/api/world/create':
        did = WLD.create(b.get('name'), b.get('description', ''), b.get('cover', 'nebula'), source=b.get('source'), from_draft=bool(b.get('from_draft')))
        if b.get('record') and SAV.exists(b['record']):  # when created, make it this save's default
            SAV.set_meta(b['record'], world=did)
        return dict(worlds_status(), new=did)
    if path == '/api/world/update':
        WLD.update(b.get('id'), name=b.get('name'), description=b.get('description'), cover=b.get('cover'))
        return worlds_status()
    if path == '/api/world/delete':
        did = b.get('id')
        WLD.remove(did)
        for k in SAV.list():                        # saves whose default is this world go back to standard
            if k.get('world') == did:
                SAV.set_meta(k['id'], world=None)
        return worlds_status()
    if path == '/api/world/copy':
        return dict(worlds_status(), new=WLD.duplicate(b.get('id'), b.get('name')))
    if path == '/api/world/discard_draft':
        WLD.discard_draft()
        return worlds_status()
    if path == '/api/world/export':
        did = world_arg(b)
        name = re.sub(r'[^\w.-]+', '_', WLD.read(did).get('name') or did)[:40]
        dest = dialog('save', title=_('Export world'), initialfile='%s.oodunya.json' % name, defaultextension='.json',
                      filetypes=[(_('OpenOrbit world'), '*.json')])
        if not dest:
            return {'cancelled': True}
        write_json(dest, WLD.export(did))
        return {'route': dest}
    if path == '/api/world/code':                    # share code (pasted into Discord)
        return {'code': WLD.code(world_arg(b))}
    if path == '/api/world/import':                  # from a share code or a file
        if b.get('code'):
            data = WLD.from_code(b['code'])
        else:
            src = dialog('ac', title=_('Import world'), filetypes=[(_('OpenOrbit world'), '*.json'), (_('All files'), '*.*')])
            if not src:
                return {'cancelled': True}
            data = read_json(src, None)
        did, report = WLD.import_(data)
        return dict(worlds_status(), new=did, report=report)
    if path == '/api/world/patch':                   # the editor's change: file + path -> full value (to the draft in standard)
        did = world_arg(b)
        WLD.patch(did, b.get('file'), b.get('route'), b.get('value'))
        return world_get('/api/world', {'world': did})
    if path == '/api/world/undo':
        did = world_arg(b)
        WLD.revert(did, b.get('file'), b.get('route'), b.get('section'))
        return world_get('/api/world', {'world': did})
    if path == '/api/world/quest':
        did = world_arg(b)
        WLD.save_quest(did, b.get('id'), b.get('changes') or {})
        return WLD.quest(did, b.get('id'))
    if path == '/api/world/new_quest':
        did = world_arg(b)
        qid = WLD.new_quest(did, b.get('name'), b.get('level'), b.get('targets') or [], b.get('rewards') or [])
        return WLD.quest(did, qid)
    if path == '/api/world/server_restart':         # from the editor: restart the server for the world's changes
        return h_post('/api/server/restart', {})
    raise Error(_('Unknown request.'))


def bots_status():
    users = world_users()
    worlds = [{'id': w['id'], 'name': w['name'], 'cover': w['cover'], 'standard': w['standard'],
                 'pilots': [u.get('pilot') or u.get('name') for u in w.get('users') or []]} for w in WLD.entries(users)]
    return {'entries': BT.entries(), 'worlds': worlds, 'bot_modes': BT.MODES, 'permissions': BT.PERMISSIONS, 'classes': BT.SIMPLE_CLASSES,
            'settings': {k: {'type': v[0], 'min_value': v[1], 'max_count': v[2], 'default': v[3]} for k, v in BT.SETTINGS.items()},
            'llm_multilingual': PRV.multilingual(), 'server_running': MANAGER.running(), 'server_pack': getattr(MANAGER, 'bot', None) and MANAGER.bot[0], 'game_settings': bot_game_settings()}


def bot_game_settings():
    """The bots' game settings profiles (bot/game_settings.py): ready profiles and the Custom profile's fields (with the names of the game
    settings)."""
    from bot import game_settings as GS
    ready = [{'id': k, 'name': SET.PRESETS[k]['name'], 'description': SET.PRESETS[k]['description']} for k in GS.PROFILES if k in SET.PRESETS]
    fields = [{'key': k, 'name': SET.BY_KEY[k]['name'], 'description': SET.BY_KEY[k]['description'], 'min_value': SET.BY_KEY[k].get('min', 0),
                'max_count': min(10, SET.BY_KEY[k].get('max', 10))} for k in GS.FIELDS]
    return {'ready': ready, 'fields': fields}


def player_names():
    return [k.get('pilot') for k in SAV.list() if k.get('pilot')]


def bot_get(path, q):
    if path == '/api/bots':
        return bots_status()
    if path == '/api/bot/llm':
        return dict(LLM.state(), provider=PRV.status())
    if path == '/api/bot/detail':                   # Roster > bot window: the live bot while the game is open, the last record while closed
        return bot_detail(q.get('id'), int(q.get('no') or 0))
    if path == '/api/bot':
        pid = q.get('id')
        d = BT.detail(pid)
        p = BT.file_path(pid)
        is_open = bool(MANAGER.running() and getattr(MANAGER, 'bot', None) and p and MANAGER.bot[0] == os.path.normcase(p))
        return dict(d, server_in_pack=is_open, restart_needed=is_open and PR.bot_signature(p) != MANAGER.bot)
    raise Error(_('Unknown request.'))


def bot_detail(pid, no):
    if is_pack_running(pid):
        try:
            return dict(game_channel('/bot/detail', {'no': no}), catalog=BT.edit_catalog(), live=True)
        except Error:
            # game is open but the channel did not respond: last record, cannot be edited (the game rewrites the file)
            return dict(BT.bot_detail(pid, no), catalog=BT.edit_catalog(), live=False, read_only=True)
    return dict(BT.bot_detail(pid, no), catalog=BT.edit_catalog(), live=False)


def bot_post(path, b):
    if path == '/api/bot/detail':                   # edit the bot (bot/edit.py): live while the game is open, in the file while closed
        pid, no, value = b.get('id'), int(b.get('no') or 0), b.get('changes') or {}
        if not isinstance(value, dict) or not value:
            raise Error(_('No changes.'))
        if is_pack_running(pid):
            r = game_channel('/bot/edit', {'no': no, 'changes': value})
            if r.get('error'):
                from bot import edit as ED
                raise Error(BT.edit_error(ED.EditError(r['error'], r.get('area', ''))))
            if 'traits' in value:
                BT.bot_personality(pid, no, value['traits'])
            return dict(r, catalog=BT.edit_catalog(), live=True)
        return dict(BT.edit_bot(pid, no, value), catalog=BT.edit_catalog(), live=False)
    if path == '/api/bot/llm/provider':          # provider choice: built-in model, OpenAI, Claude ... (bot/llm_provider.py)
        if b.get('uid') not in PRV.PROVIDERS:
            raise Error(_('Unknown request.'))
        if b.get('address') and not re.fullmatch(r'https?://\S+', str(b['address']).strip()):
            raise Error(_('The address must start with http:// or https://.'))
        PRV.save(b['uid'], b.get('address'), b.get('model'), b.get('key'))
        return bot_get('/api/bot/llm', {})
    if path == '/api/bot/llm/models':
        try:
            return {'models': PRV.models(b.get('uid'), b.get('address') or None, b.get('key') or None)}
        except PRV.ProviderError as e:
            raise Error(str(e))
    if path == '/api/bot/llm/test' and PRV.setting()['selected'] != PRV.LOCAL:
        try:
            return dict(LLM.test_remote(), provider=PRV.status())
        except LLMS.DownloadError as e:
            raise Error(str(e))
    if path.startswith('/api/bot/llm/'):           # language model: install, stop, delete, test
        operation = {'install': LLM.start, 'stop': LLM.cancel, 'delete': LLM.remove, 'test': LLM.test}.get(path.rsplit('/', 1)[1])
        if operation is None:
            raise Error(_('Unknown request.'))
        if path.endswith('/delete') and MANAGER.running():
            raise Error(_('Close the game first.'))
        try:
            return dict(operation(), provider=PRV.status())
        except LLMS.DownloadError as e:
            raise Error(str(e))
    if path == '/api/bot/create':
        pid = BT.create(b.get('name'), b.get('description', ''), b.get('world'), b.get('mode', 'normal'), b.get('progression', 'progressive'),
                         b.get('count', 60), b.get('lang', 'mixed'), b.get('company_distribution') or (1, 1, 1), b.get('settings') or {},
                         players=player_names(), name_lang_=b.get('name_lang'), special=b.get('special') or '', name_source=b.get('name_source'))
        return dict(bots_status(), new=pid)
    pid = b.get('id')
    if path == '/api/bot/update':
        BT.update(pid, name=b.get('name'), description=b.get('description'), mode=b.get('mode'), progression=b.get('progression'), settings=b.get('settings'))
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/assign':                      # assign the pack to the world (that world's old pack becomes unused)
        did = b.get('world') or None
        if did and not WLD.var(did):
            raise Error(_('World not found.'))
        BT.assign(pid, did)
        return bots_status()
    if path == '/api/bot/roster':
        if is_pack_running(pid) and (b.get('regenerate') or int(b.get('count') or 0) < len(BT.read(pid)['roster'])):
            raise Error(_('This pack is open in the game: close the game first.'))     # the running game rewrites the state with the old roster
        BT.roster(pid, count=b.get('count'), lang=b.get('lang'), company_distribution=b.get('company_distribution'), regenerate=bool(b.get('regenerate')),
                 players=player_names(), name_lang_=b.get('name_lang'), special=b.get('special') or '', name_source=b.get('name_source'))
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/name':
        BT.bot_name(pid, int(b.get('no') or 0), b.get('name'), players=player_names())
        if is_pack_running(pid):
            try:
                game_channel('/bot/name_log', {})           # in the game at once: bot, clans, directories
            except Error:
                pass                                       # not entered the game: applied at the next launch
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/reset':
        if is_pack_running(pid):
            raise Error(_('This pack is open in the game: close the game first.'))
        BT.reset(pid)
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/delete':
        if is_pack_running(pid):
            raise Error(_('This pack is open in the game: close the game first.'))
        BT.remove(pid)
        return bots_status()
    if path == '/api/bot/server_restart':
        return h_post('/api/server/restart', {})
    raise Error(_('Unknown request.'))


_SUPPORTERS = {'time': 0, 'names': []}


def supporters():
    """Recent supporters of the Buy Me a Coffee page (excluding hidden ones; 10 minute cache, an empty list if there is no connection)."""
    if time.time() - _SUPPORTERS['time'] > 600:
        try:
            with urlopen(Request(DONATE_API_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}), timeout=6) as r:
                data = json.load(r).get('data') or []
            _SUPPORTERS['names'] = list(dict.fromkeys(str(x.get('supporter_name') or '').strip() for x in data
                                                    if x.get('support_visibility') == 1 and x.get('supporter_name')))
            _SUPPORTERS['time'] = time.time()
        except (OSError, ValueError):
            return []                                  # offline: the strip stays hidden, retried at the next launch
    return _SUPPORTERS['names']


def h_get(path, q):
    if path.startswith('/api/bot'):                 # Bots (bots.py)
        return bot_get(path, q)
    if path.startswith('/api/world'):               # World Editor (worlds.py)
        return world_get(path, q)
    if path == '/api/supporters':                 # the sliding supporters strip in the sidebar
        return {'names': supporters()}
    if path == '/api/status':
        return status()
    if path == '/api/settings':
        return api_settings()
    if path == '/api/events':
        return event_list()
    if path == '/api/saves':
        return {'entries': SAV.list(), 'active': SAV.active(), 'trash': SAV.deleted(), 'companies': COMPANIES}
    if path == '/api/save_profile':
        return profile_values(slot_arg(q))
    if path == '/api/editor':                       # character editor: the save's draft (save_editor.py)
        return SAV.editor_open(slot_arg(q))
    if path == '/api/editor/catalog':               # the character editor's item catalog
        return SAV.editor_catalog()
    if path == '/api/item_info':                   # values of the item tooltip (Hangar, Shop, character editor)
        return {'items': SAV.item_info()}
    if path == '/api/backups':
        sid = slot_arg(q)
        return {'entries': SAV.backups(sid), 'record': SAV.summary(sid), 'settings': CFG.all()}
    if path == '/api/client':
        return api_client()
    if path == '/api/panel_settings':
        return CFG.all()
    if path == '/api/discord_rp':                   # Discord Rich Presence: the connection and the activity to show on the profile (preview)
        return {'state': RP.state, 'error': RP.error, 'event': RP.preview(), 'settings': CFG.all()}
    if path == '/api/languages':
        return {'languages': D.entries()}
    if path == '/api/calendar':                       # event calendar: ?start=&bit= (timestamp, at most 62 days)
        return api_calendar(q)
    if path == '/api/ports':
        return MANAGER.foreign_ports()
    if path == '/api/log':
        name = q.get('name', 'gs.log')
        if name not in LOGS and not EXTRA_LOG.fullmatch(name):
            raise Error(_('Unknown log.'))
        p = os.path.join(PTH.LOGS, name)
        n = min(5000, max(50, int(q.get('row', 400))))
        return {'name': name, 'exists': os.path.isfile(p), 'size': os.path.getsize(p) if os.path.isfile(p) else 0,
                'lines': PR.tail(p, n), 'entries': [{'name': g, 'size': os.path.getsize(os.path.join(PTH.LOGS, g))
                                                       if os.path.isfile(os.path.join(PTH.LOGS, g)) else None}
                                                      for g in LOGS + extra_logs()]}
    if path == '/api/client/download_status':              # state of the client download (client_download.py)
        return DL.state()
    if path == '/api/engine':                        # macOS: the panel's Wine and Rosetta (wine_engine.py)
        return ENG.state()
    if path == '/api/patch':                         # BepInEx, which loads the client's fixes (client_patch.py)
        return PATCHER.state(client_folder())
    if path == '/api/update':                   # update from GitHub (updater.py)
        return dict(UPD.state(), setting=CFG.get('update'), idle=idle())
    if path == '/api/protocol':                     # state of the protocol adaptation (protocol_builds.py)
        return dict(ADAPTER.state(), enabled=IST.supported())
    if path == '/api/item_list':                 # the save editor's "give item" list
        return {'items': SAV.loot_list()}
    if path == '/api/game/shop':                  # in-game menus: the shop's list and wallet (panel_channel.py)
        return dict(game_channel('/shop'), visual=bool(game_image('dizin.json')))
    if path == '/api/game/hangar':                  # in-game menus: ships, configs, slots and inventory (?ship=)
        return dict(game_channel('/hangar?ship=%s' % re.sub(r'\D', '', str(q.get('ship') or ''))), visual=bool(game_image('dizin.json')))
    if path == '/api/game/auction':                # in-game menus: auction (lots, rules, history, events)
        return dict(game_channel('/auction'), visual=bool(game_image('dizin.json')))
    if path == '/api/game/auction/events':        # the auction's new events (the panel's notifications)
        return game_channel('/auction/events?last=%d' % int(q.get('last') or 0))
    if path == '/api/game/skylab':                  # in-game menus: Skylab modules, storage, energy, transfer
        return dict(game_channel('/skylab'), visual=bool(game_image('dizin.json')))
    if path == '/api/live':                        # live status (the game server's live_status.json; live_status.py)
        p = os.path.join(PTH.LOGS, 'live_status.json')
        d = read_json(p, None)
        if not d or (not MANAGER.running() and time.time() - d.get('time', 0) > 15):    # old file: the server is closed
            return {'exists': False, 'server_running': MANAGER.running()}
        import event_calendar as CAL
        d['event_names'] = [_(CAL.EVENTS.get(k, {}).get('name', k)) for k in d.get('events', [])]
        return {'exists': True, 'server_running': True, 'age': max(0, time.time() - d.get('time', 0)), 'state': d}
    if path == '/api/friend':                      # Play with Friends: Host (server, addresses, guests) and Join (session)
        live = read_json(os.path.join(PTH.LOGS, 'live_status.json'), None) if MANAGER.running() else None
        active = SAV.active()
        return {'host': FRD.host_status(live), 'guest': FRD.state(), 'saves': SAV.list(), 'active': active,
                'client_version': IST.check(client_folder()).get('version') or IST.supported(),
                # the Host's world (World Editor): the choice ('' is the save's world), the selectable ones and the world the server will open
                'world': {'choice': CFG.get('friend_world') if WLD.var(CFG.get('friend_world') or '') else '',
                          'save_world': world_info(SAV.meta(active).get('world') if active else None), 'valid': world_info(world_id(active, True)),
                          'entries': [{'id': w['id'], 'name': w['name'], 'cover': w['cover'], 'standard': w['standard']} for w in WLD.entries()]}}
    if path == '/api/about':
        return {'version': VERSION, 'python': sys.version.split()[0], 'root': ROOT, 'server': SERVER, 'saves': PTH.SAVES,
                'logs': PTH.LOGS, 'settings': settings_file(), 'panel': PTH.PANEL, 'port': PORT, 'lang': D.current(), 'discord': DISCORD,
                'old_shortcut': bool(old_shortcut())}
    raise Error(_('Unknown request: %s', path))


def h_post(path, b):
    if migration_error() and path not in ('/api/close', '/api/update/check', '/api/update/install'):
        raise Error(migration_error())              # saves could not be migrated: no new save, setting ... is written (so it does not conflict on retry)
    if path.startswith('/api/bot/'):                # Bots (bots.py)
        return bot_post(path, b)
    if path.startswith('/api/world') or path == '/api/saves/world':      # World Editor (worlds.py)
        return world_post(path, b)
    if path == '/api/game/buy':                      # in-game menus: buying from the shop (by the same route as the client's request)
        return game_channel('/shop/buy', {k: b.get(k) for k in ('lootId', 'category', 'amount', 'level')})
    if path == '/api/game/shop/subscribe':            # in-game menus: booster subscription
        return game_channel('/shop/subscribe', {'lootId': b.get('lootId'), 'category': b.get('category')})
    if path == '/api/game/hangar/move':             # in-game menus: inventory <-> ship, drone or P.E.T. slot
        return game_channel('/hangar/move', {k: b.get(k) for k in ('ship', 'config', 'item', 'direction', 'target', 'drone', 'set')})
    if path == '/api/game/hangar/action':            # in-game menus: config, sale, P.E.T., CPU operations (panel_channel.OPS)
        return game_channel('/hangar/action', {k: b.get(k) for k in ('operation', 'ship', 'config', 'target_ship', 'favorite', 'items', 'drone',
                                                                    'name', 'slot', 'item', 'ammunition', 'lootId')})
    if path == '/api/game/hangar/design':          # in-game menus: the ship's look (design)
        return game_channel('/hangar/design', {'ship': b.get('ship'), 'lootId': b.get('lootId')})
    if path == '/api/game/hangar/activate':            # in-game menus: activating the ship (only at the station)
        return game_channel('/hangar/activate', {'ship': b.get('ship')})
    if path == '/api/game/skylab/action':            # in-game menus: Skylab upgrade, on/off, transfer to the ship
        return game_channel('/skylab/action', {k: b.get(k) for k in ('module', 'operation', 'mod', 'amounts')})
    if path.startswith('/api/game/auction/') and path.rsplit('/', 1)[1] in ('bid', 'all', 'instant', 'auto', 'alarm'):   # auction
        return game_channel('/auction/' + path.rsplit('/', 1)[1], {k: b.get(k) for k in ('type', 'loot', 'price', 'lots', 'maximum', 'when_outbid', 'min')})
    if path == '/api/game/skylab/robot':            # in-game menus: robot to the collector
        return game_channel('/skylab/robot', {'module': b.get('module'), 'tip': b.get('tip')})
    # ---- game and servers
    if path == '/api/play':
        return start_launch(b.get('server_only'))
    if path == '/api/friend/settings':
        world = b.get('world', CFG.get('friend_world')) or ''
        if world and not WLD.var(world):
            raise Error(_('World not found.'))
        CFG.update({'friend_password': str(b.get('password') if 'password' in b else CFG.get('friend_password') or '')[:64],
                    'friend_max': b.get('max_count', CFG.get('friend_max')), 'friend_world': world})
        return h_get('/api/friend', {})
    if path == '/api/friend/host':                 # friend server: like Play, the game server --multiplayer
        return start_launch(b.get('server_only'), friend=True)
    if path == '/api/friend/public_ip':
        return {'ip': FRD.find_public_ip()}
    if path == '/api/friend/kick':
        FRD.at(b.get('session'))
        return {}
    if path == '/api/friend/test':
        return FRD.attempt(str(b.get('address') or ''))
    if path == '/api/friend/join':
        return join_friend(b)
    if path == '/api/friend/leave':
        FRD.detach()
        return FRD.state()
    if path == '/api/server/stop':
        if MANAGER.client_alive():
            raise Error(_("The server can't be stopped while the game is running: close the game first."))
        if MULTI.live():
            raise Error(_("The server can't be stopped while extra clients are open: close them first."))
        MANAGER.stop_servers()
        return MANAGER.status()
    if path == '/api/server/restart':
        slot = MANAGER.slot or SAV.active()
        if not slot:
            raise Error(_('No save.'))
        if MULTI.live():
            raise Error(_("The server can't be restarted while extra clients are open: close them first."))
        friend_env = FRD.host_env() if MANAGER.running() and MANAGER.friend else None       # the mode is kept (Host, multi-client)
        multi = None if friend_env else (multi_env() if (MANAGER.running() and MANAGER.multi) or multi_wanted(slot) else None)
        MANAGER.stop_servers()
        MANAGER.start_servers(SAV.profile(slot), settings_file(slot), control=bool(SET.read(settings_file(slot)).get('control')), slot=slot, friend=friend_env,
                          multi=multi, world=world_file(slot, bool(friend_env)), bot=bot_file(slot, bool(friend_env)))
        return MANAGER.status()
    if path == '/api/client/close':
        MANAGER.stop_client()
        return MANAGER.status()
    if path == '/api/multi/open':                     # multi-client: an extra client with another save (multi_client.py)
        return open_extra(b)
    if path == '/api/multi/close':
        MULTI.close(str(b.get('record') or ''))
        return MULTI.state()
    if path == '/api/multi/close_all':
        MULTI.close_all()
        return MULTI.state()
    if path == '/api/ports/close':
        pid = int(b.get('pid') or 0)
        info = PR.process_info(pid)
        if not (PR.is_our_server(info) or info['name'].lower() == 'darkorbit.exe'):
            raise Error(_("This process (%s) is not the panel's server; the panel won't close it. Close it yourself if needed.", info['name']))
        m = re.search(r'"--stop-file=([^"]+)"|--stop-file=(\S+)', info.get('command') or '')
        if m:                                       # the previous panel's game server: let it save first and exit on its own
            try:
                open(m.group(1) or m.group(2), 'w').close()
                end = time.time() + 6
                while time.time() < end and pid in (PR.listeners() or {}).values():
                    time.sleep(0.2)
            except OSError:
                pass
        if pid in (PR.listeners() or {}).values() or not m:
            PR.kill(pid)
        log('old process closed: %s %s' % (pid, info['name']))
        time.sleep(0.5)
        return MANAGER.foreign_ports()
    # ---- game settings
    if path == '/api/settings':
        vals = game_settings()
        for k, v in (b.get('values') or {}).items():
            if k in SET.BY_KEY:
                vals[k] = v
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/settings/copy':             # another save's settings (event choices included) to the active save
        slot = SAV.active()
        if not slot:
            raise Error(_('No save.'))
        SAV.copy_settings(str(b.get('source') or ''), slot)
        log('settings copied: %s -> %s' % (b.get('source'), slot))
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/settings/reset':
        vals = game_settings()
        keys = b.get('keys') or list(SET.BY_KEY)
        for k in keys:
            vals.pop(k, None)
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/settings/presets':
        name = b.get('name')
        user = read_json(TEMPLATES, {})
        preset = SET.PRESETS.get(name, {}).get('values') if name in SET.PRESETS else (user.get(name) or {}).get('values')
        if preset is None:
            raise Error(_('Preset not found.'))
        vals = {k: v for k, v in game_settings().items() if k not in SET.BY_KEY}     # event choices stay
        vals.update(preset)
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/settings/save_template':
        name = (b.get('name') or '').strip()[:40]
        if not name:
            raise Error(_('Give the template a name.'))
        user = read_json(TEMPLATES, {})
        vals = {k: v for k, v in game_settings().items() if k in SET.BY_KEY and v != SET.DEFAULTS[k]}
        user[name] = {'name': name, 'description': b.get('description') or _('Your own settings'), 'values': vals}
        write_json(TEMPLATES, user)
        return api_settings()
    if path == '/api/settings/delete_template':
        user = read_json(TEMPLATES, {})
        user.pop(b.get('name'), None)
        write_json(TEMPLATES, user)
        return api_settings()
    if path == '/api/events':
        return set_events(b)
    # ---- saves
    if path == '/api/saves/new':
        sid = SAV.create(b.get('name'), b.get('pilot'), b.get('company'), b.get('credits'), b.get('uridium'), b.get('level'), b.get('honor'),
                         b.get('laser'), b.get('rocket'), bool(b.get('progressive')), b.get('settings_source') or SAV.active(),
                         campaign=bool(b.get('campaign')))
        if b.get('set_active', True):
            SAV.set_active(sid)
        log('new save: %s' % sid)
        return {'id': sid}
    if path == '/api/saves/active':
        return {'id': SAV.set_active(slot_arg(b))}
    if path == '/api/saves/rename':
        return SAV.rename(slot_arg(b), b.get('name'))
    if path == '/api/saves/note':
        return SAV.set_note(slot_arg(b), b.get('note'))
    if path == '/api/saves/copy':
        return {'id': SAV.duplicate(slot_arg(b), b.get('name'))}
    if path == '/api/saves/delete':
        return {'file': SAV.delete(slot_arg(b))}
    if path == '/api/saves/undo':
        return {'id': SAV.undelete(b.get('file'))}
    if path == '/api/saves/empty_trash':
        return {'deleted': SAV.purge(b.get('file'))}
    if path == '/api/saves/export':
        sid = slot_arg(b)
        name = '%s_%s.zip' % (sid, time.strftime('%Y%m%d'))
        dest = dialog('save', title=_('Export save'), initialfile=name, defaultextension='.zip',
                      filetypes=[(_('DarkOrbit save'), '*.zip')])
        if not dest:
            return {'cancelled': True}
        SAV.export(sid, dest, bool(b.get('with_backups', True)))
        return {'route': dest}
    if path == '/api/saves/import':
        src = dialog('ac', title=_('Import save'), filetypes=[(_('DarkOrbit save'), '*.zip *.json'), (_('All files'), '*.*')])
        if not src:
            return {'cancelled': True}
        return {'id': SAV.import_file(src)}
    if path == '/api/saves/edit':
        return {'changed': SAV.edit(slot_arg(b), b.get('values') or {})}
    # ---- character editor (draft: Save writes to the profile, Cancel discards)
    if path == '/api/editor/apply':
        return SAV.editor_apply(slot_arg(b), b.get('ops'))
    if path == '/api/editor/save':
        sid = slot_arg(b)
        log('character editor: %s saved' % sid)
        return {'backup': SAV.editor_commit(sid)}
    if path == '/api/editor/discard':
        SAV.editor_discard(slot_arg(b))
        return {}
    # ---- backups
    if path == '/api/backups/buy':
        return {'file': SAV.backup(slot_arg(b), 'manual', b.get('note') or '')}
    if path == '/api/backups/restore':
        return {'safety': SAV.restore(slot_arg(b), b.get('file'))}
    if path == '/api/backups/delete':
        SAV.delete_backup(slot_arg(b), b.get('file'))
        return {}
    if path == '/api/backups/note':
        SAV.set_backup_note(slot_arg(b), b.get('file'), b.get('note'))
        return {}
    if path == '/api/backups/new_save':
        return {'id': SAV.backup_as_new(slot_arg(b), b.get('file'), b.get('name'))}
    # ---- client and panel settings
    if path == '/api/panel_settings':
        CFG.update({k: v for k, v in (b.get('values') or {}).items() if k != 'active_save'})
        RP.wake_up.set()                               # if the Discord Rich Presence setting changed, at once
        return api_client()
    if path == '/api/client/select':
        start = client_folder() or ROOT
        p = dialog('folder', title=_('Choose the DarkOrbit game folder (the one with DarkOrbit.exe and DarkOrbit_Data)'), initialdir=start)
        if not p:
            return dict(api_client(), cancelled=True)
        p = os.path.normpath(p)
        c = IST.check(p)
        if not c['valid'] and os.path.basename(p).lower() == IST.DATA_DIR.lower() and IST.check(os.path.dirname(p))['valid']:
            p = os.path.dirname(p)                    # if DarkOrbit_Data was chosen, its parent folder
            c = IST.check(p)
        if not c['valid']:
            sub = [x for x in IST.candidates() if os.path.normcase(x['route']).startswith(os.path.normcase(p))]
            if sub:
                p, c = sub[0]['route'], sub[0]
            else:
                raise Error(_('The chosen folder is not a DarkOrbit client: %s', ' '.join(c['issues'])))
        CFG.update({'client_folder': p})
        return api_client()
    if path == '/api/client/use':
        p = os.path.normpath(b.get('route') or '')
        if not IST.check(p)['valid']:
            raise Error(_('The folder is not a valid client.'))
        CFG.update({'client_folder': p})
        return api_client()
    if path == '/api/client/auto':
        CFG.update({'client_folder': None})
        return api_client()
    if path == '/api/update/check':
        UPD.check()
        STATE['next_check'] = time.time() + UPDATE_SEC
        return h_get('/api/update', {})
    if path == '/api/update/install':
        if not idle(strict=True):
            raise Error(_('First close the game, the servers and running tasks.'))
        try:
            UPD.install_async()
        except UpdateError as e:
            raise Error(str(e))
        return h_get('/api/update', {})
    if path == '/api/client/download':                # download the game and open it in the project root (takes a while, resumes from where it left off)
        if RUN.find(CFG)['type'] == 'engine':          # macOS: the Wine that will open the game is downloaded too
            ENG.start()
        return DL.start(CFG.get('fast_download'))
    if path == '/api/client/update':             # old client: download the new version, delete the old one; BepInEx is reinstalled into the new folder
        if MANAGER.client_alive() or IST.running_clients():
            raise Error(_('Close the game first'))
        old = client_folder()
        if not IST.check(old)['old']:
            raise Error(_('The client is already up to date.'))
        new_ = next((c['route'] for c in IST.candidates() if c['compatible']), None)
        if new_:                                    # already on the computer
            CFG.update({'client_folder': new_})
            delete_old_client(old, new_)
            PATCHER.start(new_)
            return DL.state()
        STATE['old_client'] = old
        return DL.start(CFG.get('fast_download'))
    if path == '/api/engine/install':
        return ENG.start()
    if path == '/api/patch/install':
        return PATCHER.start(client_folder())
    if path == '/api/patch/stop':
        PATCHER.cancel()
        return PATCHER.state(client_folder())
    if path == '/api/engine/stop':
        return ENG.cancel()
    if path == '/api/rosetta/install':                  # macOS's administrator dialog opens
        return ENG.install_rosetta()
    if path == '/api/client/download_stop':
        return DL.cancel()
    if path == '/api/client/download_delete':            # temporary folder of a partial download
        try:
            return DL.discard()
        except DownloadError as e:
            raise Error(str(e))
    if path == '/api/protocol/generate':                # generate the protocol from the new client and report the difference (does not touch the active files)
        try:
            return ADAPTER.generate(os.path.normpath(b.get('route') or client_folder() or ''))
        except RuntimeError as e:
            raise Error(str(e))
    if path == '/api/protocol/apply':              # make the generated version active (when the game server is restarted)
        if MANAGER.running():
            raise Error(_('Stop the game server first: the protocol is loaded at startup.'))
        try:
            return ADAPTER.activate(b.get('version'))
        except RuntimeError as e:
            raise Error(str(e))
    if path == '/api/log/clear':
        name = b.get('name')
        if name not in LOGS and not EXTRA_LOG.fullmatch(str(name or '')):
            raise Error(_('Unknown log.'))
        try:
            open(os.path.join(PTH.LOGS, name), 'w').close()
        except OSError:
            raise Error(_('The log is open in a server right now; stop the server and try again.'))
        return {}
    if path == '/api/open_folder':
        what = b.get('what')
        paths = {'project': ROOT, 'saves': PTH.SAVES, 'logs': PTH.LOGS, 'client': client_folder() or ROOT,
                 'server': SERVER}
        if what in ('record', 'backup'):
            sid = slot_arg(b)
            p = SAV.dir(sid) if what == 'record' else SAV.backup_dir(sid)
            os.makedirs(p, exist_ok=True)
            open_folder(p)
        elif what in paths:
            os.makedirs(paths[what], exist_ok=True) if what in ('saves', 'logs') else None
            open_folder(paths[what])
        else:
            raise Error(_('Unknown folder.'))
        return {}
    if path == '/api/discord':                      # the invite in the default browser (the panel window's profile is not signed in to Discord)
        import webbrowser
        webbrowser.open(DISCORD)
        return {}
    if path == '/api/donate':                        # the support page in the default browser (Buy Me a Coffee)
        import webbrowser
        webbrowser.open(DONATE_URL)
        return {}
    if path == '/api/shortcut':
        return {'route': create_shortcut()}
    if path == '/api/close':
        if (MANAGER.client_alive() or MULTI.live()) and not b.get('force'):
            raise Error(_('The game is running: close the game first.'))
        MANAGER.stop_client()
        threading.Thread(target=lambda: (MULTI.close_all(wait=8), wait_for_client(), shutdown()), daemon=True).start()
        return {}
    raise Error(_('Unknown request: %s', path))


TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
         '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.webp': 'image/webp', '.woff2': 'font/woff2'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'DarkOrbitPanel/' + VERSION

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode('utf8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        if 'Cache-Control' not in (extra or {}):
            self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        try:
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionError, OSError):          # the window was refreshed / closed: nobody is waiting for the response
            pass

    def _host_ok(self):
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost')

    def _api(self, fn, arg):
        if self.headers.get('X-Panel-Token') != TOKEN:
            return self._send(403, {'error': _('Invalid token: reopen the panel.')})
        try:
            out = fn(urlparse(self.path).path, arg)
        except (Error, SaveError, FriendError, MultiClientError, RuntimeError, ValueError) as e:
            return self._send(400, {'error': str(e)})
        except Exception as e:
            log('API error %s: %s' % (self.path, traceback.format_exc()))
            return self._send(500, {'error': _('Unexpected error: %r', e)})
        return self._send(200, out)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {'error': 'host'})
        u = urlparse(self.path)
        if u.path == '/api/ping':
            return self._send(200, {'panel': 'darkorbit', 'version': VERSION, 'pid': os.getpid()})
        if u.path.startswith('/api/'):
            return self._api(h_get, {k: v[0] for k, v in parse_qs(u.query).items()})
        if u.path.startswith('/game_images/'):
            p = game_image(u.path[len('/game_images/'):])
            if not p:
                return self._send(404, b'none', 'text/plain')
            if p.endswith('.png'):                  # atlas pages are large and do not change; the index and names change on a new dump: no cache
                return self._send(200, open(p, 'rb').read(), 'image/png', {'Cache-Control': 'max-age=3600'})
            return self._send(200, open(p, 'rb').read(), 'application/json; charset=utf-8')
        name = 'index.html' if u.path in ('/', '/index.html') else u.path.lstrip('/')
        p = os.path.normpath(os.path.join(UI_DIR, name))
        if not p.startswith(UI_DIR + os.sep) or not os.path.isfile(p):
            return self._send(404, b'none', 'text/plain')
        data = open(p, 'rb').read()
        if name == 'index.html':
            data = data.replace(b'{{BELIRTEC}}', TOKEN.encode())
        self._send(200, data, TYPES.get(os.path.splitext(p)[1], 'application/octet-stream'),
                   {'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {'error': 'host'})
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        if u.path == '/api/show':                  # second launch: reopen the window
            threading.Thread(target=open_window, args=('http://127.0.0.1:%d/' % PORT,), daemon=True).start()
            return self._send(200, {})
        if u.path == '/api/closed':                 # the page is closing (sendBeacon): so the heartbeat drops early if the window is not being watched
            if not STATE['window_watched']:
                STATE['heartbeat'] = time.monotonic() - HEARTBEAT_SEC + 8
            return self._send(200, {})
        try:
            body = json.loads(raw.decode('utf8') or '{}')
        except ValueError:
            return self._send(400, {'error': _('Not JSON')})
        return self._api(h_post, body if isinstance(body, dict) else {})


class Server(ThreadingHTTPServer):
    # HTTPServer enables SO_REUSEADDR; on Windows this lets a second process bind to the listening port too: the second launch opened a
    # second panel on the same port without seeing the open panel (live round 2). While closed it cannot bind, and has the open panel's
    # window opened (main). On macOS and Linux SO_REUSEADDR still rejects a second listener, but without it TIME_WAIT connections left
    # from the open window's requests hold the port for half a minute: after an update the new panel could not get the port and opened on
    # another port (the window cannot find it)
    allow_reuse_address = os.name != 'nt'


def main():
    global PORT
    PORT = next((int(a.split('=', 1)[1]) for a in sys.argv if a.startswith('--port=') and a.split('=', 1)[1].isdigit()), PORT)
    srv = None
    if STATE['updated']:                          # after an update: wait until the old process releases the port
        for _k in range(75):
            try:
                srv = Server(('127.0.0.1', PORT), Handler)
                break
            except OSError:
                time.sleep(0.2)
    try:
        srv = srv or Server(('127.0.0.1', PORT), Handler)
    except OSError:
        try:                                          # is the panel already open?
            with urlopen('http://127.0.0.1:%d/api/ping' % PORT, timeout=2) as r:
                if json.load(r).get('panel') == 'darkorbit':
                    for show in ('/api/show', '/api/goster'):      # /api/goster: a panel of an older version still open
                        try:
                            urlopen(Request('http://127.0.0.1:%d%s' % (PORT, show), data=b'{}', method='POST'), timeout=5).read()
                            break
                        except HTTPError as e:
                            if e.code != 404:
                                raise
                    return
        except Exception:
            pass
        srv = Server(('127.0.0.1', 0), Handler)       # the port is in use by another program: a free port
        PORT = srv.server_address[1]
    srv.daemon_threads = True
    STATE['srv'] = srv
    log('panel opened: http://127.0.0.1:%d/ (python %s)%s' % (PORT, sys.version.split()[0], ' (after update)' if STATE['updated'] else ''))
    try_migrate()
    try:
        SM.migrate_client(client_folder(), log)         # files in the old version's client folder
    except OSError as e:
        log('client folder could not be moved: %s' % e)
    threading.Thread(target=refresh_shortcut, daemon=True).start()
    if not CFG.get('active_save') and SAV.slots():
        CFG.update({'active_save': SAV.slots()[0]})
    threading.Thread(target=ticker, daemon=True).start()
    RP.launch()
    if not {'--no-window', '--pencere-yok'} & set(sys.argv):     # old names: the updater from before 2026-11-01 restarts with these
        proc = open_window('http://127.0.0.1:%d/' % PORT)
        if proc:
            threading.Thread(target=watch_window, args=(proc,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        shutdown()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log('panel could not start: %s' % traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, _('The panel could not start. Details: server\\logs\\panel.log\n\n%s',
                                                  traceback.format_exc()[-900:]), 'OpenOrbit Panel', 0x10)
        except Exception:
            pass
        raise
