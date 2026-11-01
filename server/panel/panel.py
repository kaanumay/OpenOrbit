"""DarkOrbit yerel sunucu yönetim paneli: oyunu başlatır, ayarları, kayıtları ve sunucuları yönetir.

Başlatma: ana dizindeki "OpenOrbit Panel.pyw" (çift tıkla; konsolsuz) ya da python server/panel/panel.py.
Panel 127.0.0.1:8077'de yerel bir web arayüzü açar ve onu Edge'in (yoksa Chrome'un) uygulama penceresinde gösterir (adres çubuğu
yok, internet gerekmez). Pencere kapanınca: oyun sürüyorsa istemci kapanana dek bekler (ayar), sonra panelin açtığı sunucuları
kapatıp çıkar. Panel zaten açıksa ikinci başlatma yalnız pencereyi yeniden açar.
API: /api/... (JSON). İstekler sayfadaki belirteci (X-Panel-Belirteci) taşımalı: başka sitelerin tarayıcıdan panele istek
göndermesini engeller. Yalnız 127.0.0.1'e bağlanır.
Yollar: paths.py (save/kayitlar, save/panel.json, save/ayarlar.json, logs/).
Dil: lang.py'deki diller (metinler Türkçe yazılır, öbür dillerdekiler arayuz/<kod>.json). İlk açılışta arayüz kurulum sihirbazını
açar: dil, oyun klasörü, ilk pilot, oyun ayarları (panel.json 'dil', 'kurulum_tamam'). Oyun bilgisayarda bulunamazsa sihirbazın oyun
klasörü adımı onu indirmeye başlar (client_download.py; İstemci sayfasından da). İstemcinin düzeltmelerini yükleyen BepInEx de
istemci klasörüne kurulur (client_patch.py: sihirbazın oyun klasörü adımında, istemci inince, İstemci sayfasından ya da ilk OYNA'da).
Çoklu istemci (multi_client.py): OYNA'dan sonra öteki kayıtlarla ek istemciler aynı sunucuda (en az iki kayıt ve ayar açıksa sunucu çok
oturumlu açılır); ek istemci açıkken sunucuyu yeniden başlatan işler reddedilir, sunucular son istemci kapanınca kapanır.
Güncelleme (updater.py): açılıştan biraz sonra ve GUNCELLEME_SN'de bir GitHub'daki son sürüm denetlenir; panel ayarı 'guncelleme'
otomatikse ve oyun, sunucular, indirme ya da başka bir iş sürmüyorsa kurulur, ardından panel yeniden başlar (yeni süreç aynı portu
alır, açık pencere sayfayı yeniler).
Linux ve macOS: istemci Wine ya da Proton ile açılır (client_runner.py, İstemci sayfasının Wine / Proton kartı); macOS'ta Otomatik
panelin kendi kurduğu Wine + DXMT'dir (wine_engine.py: ilk OYNA'da, istemci indirilirken ya da İstemci sayfasından iner; Apple
Silicon'da Rosetta 2'yi de panel kurdurur). Pencere Chrome, Edge, Chromium ya da Brave'de; dosya pencereleri Linux'ta tkinter (yoksa
zenity), macOS'ta AppleScript (Tk orada yalnız ana iş parçacığında çalışır); kısayol Linux'ta .desktop, macOS'ta uygulama paketi (.app).
"""
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
platform_compat.certificates()           # macOS: python.org Python'unun kök sertifikası yoksa sistemin paketi (HTTPS'ten önce; sunucular devralır)
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
import bots as BT            # noqa: E402  (Botlar sayfası: bot paketleri)
import llm_setup as LLMS     # noqa: E402  (Gelişmiş bot kipinin dil modeli)
import discord_rp as DRP       # noqa: E402  (Discord Rich Presence)
from bot import llm_provider as PRV  # noqa: E402  (dil modelinin sağlayıcısı: dahili ya da kullanıcının seçtiği)

VERSION = '1.0'
DISCORD = 'https://discord.com/invite/openorbit'   # topluluk sunucusu (Panel sayfası, README); kalıcı davet
DONATE_URL = 'https://buymeacoffee.com/kaanumay'       # destek bağlantısı (kenar çubuğunun en altı)
DONATE_API_URL = 'https://app.buymeacoffee.com/api/creators/slug/kaanumay/coffees?web=1&page=1&per_page=20'   # son destekçiler
PORT = 8077
UI_DIR = os.path.join(PANEL_DIR, 'ui')
TEMPLATES = os.path.join(PTH.SAVE, 'settings_templates.json')
BROWSER_PROFILE = os.path.join(os.environ.get('LOCALAPPDATA') or PTH.SAVE, 'DarkOrbitPanel', 'browser')
LOGS = ('gs.log', 'http.log', 'client.log', 'oyun_konsol.log', 'web_konsol.log', 'panel.log', 'errors.log', 'unknown.log') + (
    () if os.name == 'nt' else ('wine.log',))      # Linux ve macOS: Wine'ın / Proton'un çıktısı (surecler.istemci_ac)
EXTRA_LOG = re.compile(r'client_[a-z0-9_]{1,40}\.log')          # çoklu istemcinin ek istemcilerinin günlükleri (coklu.py)
HEARTBEAT_SEC = 180                      # tarayıcı penceresi izlenemiyorsa: bu kadar istek gelmezse pencere kapandı sayılır (monotonic:
                                    # macOS ve Linux'ta uykuda geçen süre sayılmaz)
HANDOVER_SEC = 10                       # tarayıcı süreci bundan önce çıkarsa pencereyi açık bir sürece devretmiştir (watch_window)
UPDATE_SEC = 6 * 3600            # GitHub'da yeni sürüm denetimi aralığı (başarısızsa bir saat sonra yeniden)
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
D.bind(lambda: CFG.get('dil'))
MANAGER = PR.Manager(PTH.LOGS, log)
SAV = Saves(CFG, python=PR.python_exe())
FRD = Friend(CFG, SAV, MANAGER, log, VERSION)                        # Arkadaşlarınla Oyna: Host ve Join (arkadas.py)
MULTI = MultiClient(CFG, SAV, MANAGER, lambda: FRD.key, PTH.LOGS, log)  # çoklu istemci: öteki kayıtlarla ek istemciler (coklu.py)
SAV.in_use = lambda slot: (MANAGER.running() and MANAGER.slot == slot) or FRD.in_use(slot) or MULTI.in_use(slot)
ADAPTER = Adapter(ROOT, PR.python_exe(), log, PR.NO_WINDOW)    # yeni istemciye protokol uyarlaması (protokol.py)
UPD = Updater(ROOT, PTH.SAVE, log)                          # GitHub'dan güncelleme (guncelleme.py)
ENG = RUN.engine()                                                # macOS: panelin kurduğu Wine + DXMT (wine_motoru.py)
ENG.log = log
PATCHER = PATCH.Patcher(log)                                           # istemcinin düzeltmelerini yükleyen BepInEx (istemci_yama.py)
TOKEN = secrets.token_hex(16)
STATE = {'play': {'running': False, 'steps': [], 'hata': None, 'finished': None, 'server_only': False},
         'heartbeat': time.monotonic(), 'window_closed': False, 'window_watched': False, 'last_backup': 0.0, 'closing': False,
         'next_check': time.time() + 8, 'updated': bool({'--updated', '--guncellendi'} & set(sys.argv)), 'srv': None, 'opening': time.time()}


def rp_source():
    """Discord Rich Presence'ın kaynağı (discord_rp.py) -> (canlı durum ya da None, panelin durumu)."""
    live = read_json(os.path.join(PTH.LOGS, 'canli_durum.json'), None) if MANAGER.running() else None
    if live and time.time() - live.get('time', 0) > 15:
        live = None
    if MANAGER.client_alive():
        return live, 'in_game' if live and live.get('connected') else 'arkadas' if FRD.m['durum'] == 'in_game' else 'giris'
    return None, 'starting' if STATE['play']['running'] else 'panel'


RP = DRP.Presence(CFG, rp_source, _, log)


class Error(Exception):
    """Kullanıcıya gösterilen hata."""


# ------------------------------------------------------------------ yardımcılar
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
    """Sunucunun dünyası: arkadaş sunucusunda Host'un seçtiği (panel ayarı arkadas_dunya), yoksa kaydın varsayılan dünyası."""
    choice = CFG.get('friend_world') if friend else None
    if choice and WLD.var(choice):
        return choice
    return SAV.meta(slot).get('world') if slot else None


def world_file(slot, friend=False):
    """Sunucunun dünya dosyası (Dünya Editörü; OO_WORLD) ya da None (standart dünya, silinmiş dünya)."""
    return WLD.file_path(world_id(slot, friend))


def bot_file(slot, friend=False):
    """Sunucunun bot paketi (Botlar sayfası; OO_BOT): kaydın dünyasına atanmış paket ya da None."""
    return BT.file_path(BT.world_pack(world_id(slot, friend) or WLD.STANDARD))


def world_info(wid):
    """Oyna sayfasının dünya çipi: {id, ad, kapak, degisiklik}; silinmiş dünya standart sayılır."""
    try:
        w = WLD.summary(wid if wid and WLD.var(wid) else WLD.STANDARD)
    except WLD.WorldError:
        w = WLD.summary(WLD.STANDARD)
    return {'id': w['id'], 'ad': w['ad'], 'cover': w['cover'], 'changes': 0 if w['standard'] else w['changes'], 'standard': w['standard']}


def world_users():
    """Dünya -> onu varsayılan yapan kayıtlar [{id, ad, pilot}]."""
    out = {}
    for k in SAV.list():
        w = k.get('world') if k.get('world') and WLD.var(k.get('world')) else WLD.STANDARD
        out.setdefault(w, []).append({'id': k['id'], 'ad': k.get('ad'), 'pilot': k.get('pilot')})
    return out


def settings_file(slot=None):
    """Oyun ayarlarının dosyası: kaydın kendi ayarları (etkin kayıt; kayıt yoksa eski ortak dosya)."""
    slot = slot or SAV.active()
    return SAV.settings(slot) if slot else PTH.SETTINGS


def game_settings():
    return SET.read(settings_file())


def client_folder():
    return IST.resolve(CFG.get('client_folder'))


# ------------------------------------------------------------------ oyun menüleri (Mağaza)
# Oyun açıkken panel oyunu oyun sunucusunun yerel kanalından değiştirir (server/panel_kanali.py; anahtar günlük klasöründe).
# Görseller istemcinin BepInEx eklentisinin dökümü (eklenti/Gorseller.cs: <istemci>/BepInEx/openorbit/gorsel), /oyun_gorsel/ altında.
def is_pack_running(pid):
    """Bot paketi şu an çalışan oyunda mı."""
    return bool(MANAGER.running() and getattr(MANAGER, 'bot', None) and BT.file_path(pid)
                and MANAGER.bot[0] == os.path.normcase(BT.file_path(pid)))


def game_channel(route, body=None):
    k = read_json(os.path.join(PTH.LOGS, 'panel_kanali.json'), None)
    if not k or not MANAGER.running():
        raise Error(_('The game is not running.'))
    req = Request('http://127.0.0.1:%d%s' % (k['port'], route), data=None if body is None else json.dumps(body).encode('utf8'),
                  headers={'X-Anahtar': k['anahtar'], 'Content-Type': 'application/json'})
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
    """Eklentinin döktüğü atlas sayfası, dizin ya da ad dosyası -> yol (yoksa None)."""
    if not re.fullmatch(r'[\w.-]+\.(png|json)', name) or not client_folder():
        return None
    p = os.path.join(client_folder(), 'BepInEx', 'openorbit', 'images', name)      # eklentinin döktüğü klasör
    return p if os.path.isfile(p) else None


def _downloaded(path):
    """İndirme bitti: kullanılan istemci geçersizse ya da güncelleniyorsa yeni klasör kullanılsın (kendiliğinden bulunuyorsa ayar boş
    kalır); güncellemede eski klasör silinir."""
    old = STATE.pop('old_client', None)
    if old or not IST.check(client_folder())['valid']:
        auto = IST.resolve(None)
        same = auto and os.path.normcase(os.path.normpath(auto)) == os.path.normcase(os.path.normpath(path))
        CFG.update({'client_folder': None if same else path})
    if old:
        delete_old_client(old, path)
    PATCHER.start(path)                                   # istemcinin düzeltmeleri için BepInEx (istemci_yama.py)


def delete_old_client(old, new_):
    """İstemci güncellemesi: eski sürümün klasörünü sil. Yalnız arşivden açılmış DarkOrbit_Version… klasörü: resmî kurulumu kendi
    başlatıcısı günceller, ona dokunulmaz."""
    if (os.path.normcase(os.path.normpath(old)) == os.path.normcase(os.path.normpath(new_))
            or not re.match(r'DarkOrbit_Version\d', os.path.basename(os.path.normpath(old))) or not IST.check(old)['valid']):
        log('eski istemci silinmedi: %s' % old)
        return
    try:
        shutil.rmtree(old)
        log('eski istemci silindi: %s' % old)
    except OSError as e:
        log('eski istemci silinemedi: %s: %r' % (old, e))


DL = Downloader(ROOT, IST.check, log, on_done=_downloaded)       # oyun istemcisini indirme (indirme.py)
LLM = LLMS.LlmSetup(log)                                       # botların dil modeli (llm_kurulum.py)


def _dl_pct(st):
    return int(100 * st['claimed'] / st['toplam']) if st['toplam'] else 0


_dialog_lock = threading.Lock()


def dialog(kind, **kw):
    """Yerel dosya/klasör penceresi (tkinter; panelin önünde açılır) -> seçilen yol ya da ''. macOS'ta AppleScript, Linux'ta tkinter
    yoksa zenity."""
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


# ------------------------------------------------------------------ etkinlikler
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
        yearly = 'donemler' in e
        if yearly:                                      # önümüzdeki yılın dönemleri (takvim.upcoming; bitiş günü dahil)
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
        out.append({'anahtar': key, 'ad': _(e.get('ad', key)), 'tur': 'yearly' if yearly else 'weekly', 'time': when,
                    'in_calendar': per is not None, 'time_left_sec': int(per[1] - now) if per else None, 'next_day': nxt,
                    'durum': st, 'etkin': (st == 'on') if st else per is not None,
                    'aciklama': _(EVENT_DESCRIPTIONS.get(key, '')),
                    'conflicting': sorted(_(CAL.EVENTS[j].get('ad', j)) for j in CAL.CONFLICTS[key])})
    # çakışma (takvim.resolve): aynı anda açık çakışanlardan elle açılan, yoksa önce başlayan kalır
    rows = {x['anahtar']: x for x in out}
    on = {k for k, x in rows.items() if x['etkin']}
    keep = CAL.resolve(on, lambda k: (rows[k]['durum'] != 'on', (CAL.period(k, now) or (0,))[0], k))
    for k in on - keep:
        rows[k]['etkin'] = False
        rows[k]['suppressed_by'] = next(rows[j]['ad'] for j in sorted(keep, key=lambda j: rows[j]['ad']) if j in CAL.CONFLICTS[k])
    out.sort(key=lambda x: (x['tur'] != 'yearly', not x['etkin'], x['ad'].lower()))
    return out


SESSION_NAMES = {'vortex': 'Vortex session', 'world_boss': 'Boss fight', 'kristallon': 'Apotheosis window',
                'mimesis': 'Mimesis run', 'title_hunt': 'Prestige title hunt', 'alien': 'Event aliens',
                'kutu': 'Event boxes', 'harita': 'Map event'}


def api_calendar(q):
    """Etkinlik takvimi (event_schedule.py): [bas, bit) içindeki takvim ve etkin aralıklar, seanslar, şimdiki ya da sonraki dönem."""
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
    c = CC.schedule(a, b, hep, {e['anahtar']: e['durum'] for e in evs})
    out = []
    for e in evs:
        x = c[e['anahtar']]
        session = [dict(s, ad=_(SESSION_NAMES[s['kimlik'] if s['tur'] == 'session' else s['tur']])) for s in x['sessions']]
        out.append(dict(e, ranges=x['ranges'], active_ranges=x['etkin'], sessions=session,
                        next=CC.next_(e['anahtar'], now, 400 if e['tur'] == 'yearly' else 70)))
    return {'now': now, 'start': a, 'bit': b, 'always_open': hep, 'events': out}


def settings_summary(values):
    """Varsayılandan farklı oyun ayarları [{'ad', 'deger'}] (Oyna sayfasının çipleri; ayar.summary'nin panel dilindeki hâli)."""
    d = SET.clean(values)
    out = []
    for s in SET.SCHEMA:
        v = d.get(s['anahtar'], s['default'])
        if v == s['default']:
            continue
        if s['tur'] == 'carpan':
            text = 'x%g' % v
        elif s['tur'] == 'bool':
            text = _('on') if v else _('off')
        elif s['tur'] == 'sayi':
            text = ('%d %s' % (v, _(s['unit']) if s.get('unit') else '')).strip()
        else:
            text = _(s['options'][v])
        out.append({'ad': SET.full_name(s, _), 'value': text})
    return out


def set_events(body):
    vals = game_settings()
    ev = dict(vals.get('events') or {})
    import event_calendar as CAL
    if 'hepsi' in body:
        to = body['hepsi']
        for k, e in CAL.EVENTS.items():
            if body.get('tur') and body['tur'] != ('yearly' if 'donemler' in e else 'weekly'):
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
        if v == 'on':                             # çakışan elle açıklar takvime döner (takvim.CONFLICTS)
            for j in CAL.CONFLICTS[k]:
                if ev.get(j) == 'on':
                    ev.pop(j)
    vals['events'] = ev
    SET.write(settings_file(), vals)
    return event_list()


# ------------------------------------------------------------------ uyarılar ve durum
def try_migrate():
    """Eski tek kayıt (save/profil.json) varsa yuvaya taşı; portlar açıksa (o profille açılmış bir sunucu olabilir) sonraya."""
    if not os.path.isfile(PTH.LEGACY_PROFILE) or MANAGER.running():
        return None
    table = PR.listeners()
    if any(PR.listening(p, table) for p in (8081, 8090)):
        if not STATE.get('migration_pending'):
            log('eski kayıt taşınmadı: oyun portları açık (Baslat.bat ile açılmış bir sunucu kullanıyor olabilir)')
        STATE['migration_pending'] = True
        return None
    STATE['migration_pending'] = False
    moved = SAV.migrate()
    if moved:
        log('eski kayıt (save/profil.json) yuvaya taşındı: %s' % moved)
    return moved


def warnings(folder=False):
    out = []
    if STATE.get('migration_pending'):
        out.append({'tur': 'warning', 'metin': _('The old save (server/save/profil.json) is waiting to be moved into a save slot: first close the '
                                                 'server running outside the panel (Server > Ports).'), 'page': 'sunucu'})
    if migration_error():
        out.append({'tur': 'hata', 'metin': migration_error(), 'page': 'saves'})
    if FRD.active():
        out.append({'tur': 'warning', 'metin': _("You are on a friend's server (%s): Play is unavailable. Leave from the Play with Friends page.",
                                               FRD.m['address']), 'page': 'arkadas'})
    slot = SAV.active()
    if not slot:
        out.append({'tur': 'hata', 'metin': _('No saves yet: create a new save on the Saves page.'), 'page': 'saves'})
    c = IST.check(client_folder() if folder is False else folder)
    if not c['valid'] and DL.running():
        out.append({'tur': 'warning', 'metin': _('Downloading the game client: %d%%. You can play when it is done.', _dl_pct(DL.state())),
                    'page': 'client'})
    elif not c['valid']:
        out.append({'tur': 'hata', 'metin': _('Game client not found: %s Choose its folder or download the game on the Client page.',
                                              ' '.join(c['issues'])), 'page': 'client'})
    elif c['eski']:                                                  # yeni sürüm çıktı: tek tıkla güncellenir (/api/istemci/guncelle)
        dl, sup = DL.state(), IST.supported()
        run = bool(STATE.get('old_client')) and dl['running']
        text = (_('Updating the game to version %s: %d%%. When it is done the old version is deleted and BepInEx is reinstalled.', sup, _dl_pct(dl))
                 if run else _("DarkOrbit version %s is out and your client is %s: the game won't work properly unless you update. "
                               'Update downloads and installs the new one and deletes the old one.', sup, c['surum']))
        if STATE.get('old_client') and dl['durum'] == 'hata':
            text += ' ' + dl['hata']
        out.append({'tur': 'hata', 'metin': text, 'progress': _dl_pct(dl) if run else None, 'download': dl if run else None,
                    'page': 'client',
                    'action': {'metin': _('Update'), 'api': '/api/istemci/update', 'running': run,
                              'running_text': _('Updating…')}})
    elif not c['compatible']:
        out.append({'tur': 'warning', 'metin': c['issues'][-1], 'page': 'client'})
    error = RUN.find(CFG)['hata']                                      # Linux ve macOS: Wine ya da Proton (Apple Silicon'da Rosetta)
    if error:
        w = {'tur': 'hata', 'metin': error, 'page': 'client'}
        if RUN.rosetta_error():
            ros = ENG.state()['rosetta']
            w['action'] = {'metin': _("Install Rosetta"), 'api': '/api/rosetta/kur', 'running': ros['durum'] == 'installing'}
            if ros['hata']:
                w['metin'] += ' ' + ros['hata']
        out.append(w)
    m = ENG.state() if sys.platform == 'darwin' else None
    if m and m['running']:
        out.append({'tur': 'warning', 'metin': _('Downloading Wine and DXMT: %d%%. You can play when it is done.',
                                               int(100 * m['claimed'] / m['toplam']) if m['toplam'] else 0), 'page': 'client'})
    elif m and m['durum'] == 'hata':
        out.append({'tur': 'hata', 'metin': _("The panel's Wine could not be installed: %s", m['hata']), 'page': 'client'})
    error = PR.port_80_problem()
    if error:
        out.append({'tur': 'hata', 'metin': error, 'page': 'sunucu'})
    missing = [n for n in PTH.TEMPLATES if not PTH.template(n)]       # kendi kaydın ya da paylaşılabilir kopya (data/defaults)
    if missing:
        out.append({'tur': 'warning', 'metin': _('Login templates are missing (%s): the game starts with a minimal login, some windows and the shop '
                                                 'may be empty.', ', '.join(missing)), 'page': 'sunucu'})
    u = UPD.state()
    if u['durum'] in ('downloading', 'installing'):
        out.append({'tur': 'warning', 'metin': _('The panel is updating; it restarts by itself when done.'), 'page': 'panel'})
    elif u['durum'] == 'exists' and CFG.get('update') != 'off':
        auto = CFG.get('update') == 'auto' and CFG.get('setup_done')
        out.append({'tur': 'warning', 'metin': _('New version available (%s): it installs by itself when the game and servers are closed.', u['last']['surum'][:7])
                    if auto else _('New version available (%s): you can install it on the Panel page.', u['last']['surum'][:7]), 'page': 'panel'})
    elif u['durum'] == 'installed':
        out.append({'tur': 'warning', 'metin': _('Update installed: the panel restarts when the game and servers are closed.'), 'page': 'panel'})
    alive = MANAGER.servers_alive()
    table = PR.listeners()
    foreign = [p for name, ports in PR.PORTS.items() for p in ports if not alive.get(name) and PR.listening(p, table)]
    if foreign:
        out.append({'tur': 'warning', 'metin': _("A process the panel didn't start is holding the game ports (%s). It may be a server left over from "
                                                 'a previous session: check the Server page.', ', '.join(map(str, foreign))),
                    'page': 'sunucu'})
    for name, s in MANAGER.servers.items():
        if s.crashed:
            out.append({'tur': 'hata', 'metin': _('The %s server closed unexpectedly (exit code %s). Details: Server > Logs > %s_konsol.log', _({'oyun': 'Game', 'web': 'Web'}[name]), s.proc.poll(), name),
                        'page': 'sunucu'})
    return out


def status():
    STATE['heartbeat'] = time.monotonic()
    STATE['window_closed'] = False                  # bir pencere yine soruyor (ikinci başlatmanın açtığı da)
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
    ev = [e['ad'] for e in event_list() if e['etkin'] and e['tur'] == 'yearly']
    slots = SAV.slots()
    folder = client_folder()                     # istemci klasörü araması (glob) bir kez: uyarılar ve yanıt
    return {'processes': MANAGER.status(), 'active': active, 'save_count': len(slots),
            'settings_summary': settings_summary(vals), 'events': ev,
            'warnings': warnings(folder), 'play': STATE['play'], 'client_folder': folder,
            'arkadas': {'host': MANAGER.running() and MANAGER.friend, 'guest': FRD.m['durum'], 'address': FRD.m['address']},
            'multi': multi_status(slots),
            'panel': {'surum': VERSION, 'window_closed': STATE['window_closed'], 'dil': CFG.get('dil'), 'platform': sys.platform,
                      'setup_done': CFG.get('setup_done'), 'updated': STATE['updated'],
                      'uptime_sec': int(time.time() - STATE['opening'])}}


# ------------------------------------------------------------------ çoklu istemci (coklu.py)
def multi_env():
    """Çoklu istemcinin oyun sunucusu ayarları (OO_MULTIPLAYER; cok_oyunculu.configure): yalnız bu bilgisayar, misafir yok."""
    return json.dumps({'address': '127.0.0.1', 'guest': False, 'anahtar': FRD.key, 'code': VERSION, 'local': FRD.local})


def multi_wanted(slot):
    """OYNA sunucuyu çok oturumlu açsın mı: ayar açık ve en az iki kayıt var (tek kaydı olanın sunucusu tek oyunculu kalır), ya da
    sunucu bu kayıtla zaten öyle açık."""
    return bool(CFG.get('multi_client') and len(SAV.slots()) > 1) or (MANAGER.running() and MANAGER.multi and MANAGER.slot == slot)


def multi_status(slots):
    """Oyna sayfasının Çoklu istemci kartı: açık ek istemciler, son kapanışlar ve ek istemcide açılabilecek kayıtlar."""
    live = read_json(os.path.join(PTH.LOGS, 'canli_durum.json'), None) if MULTI.live() else None
    out = dict(MULTI.state(live), ayar=CFG.get('multi_client'), max_count=CFG.get('multi_client_max'), save_count=len(slots),
               sunucu=MANAGER.running() and (MANAGER.multi or MANAGER.friend), main=MANAGER.slot if MANAGER.running() else None, saves=[])
    if out['ayar'] and len(slots) > 1:
        for s in slots:
            try:
                k = SAV.summary(s)
            except (OSError, SaveError):
                continue
            out['saves'].append({'id': s, 'ad': k['ad'], 'pilot': k.get('pilot'), 'seviye': k.get('seviye'), 'firma': k.get('firma'),
                                    'corrupt': k.get('corrupt'), 'ek': MULTI.in_use(s), 'arkadas': FRD.in_use(s)})
    return out


def open_extra(b):
    """Çoklu istemci: başka bir kayıtla ek istemci. Sunucu çok oturumlu açık olmalı; tek oyunculu açıksa ve oyun kapalıysa öyle
    yeniden başlatılır."""
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
        log('çoklu istemci: sunucu çok oturumlu yeniden başlatılıyor')
        MANAGER.start_servers(SAV.profile(MANAGER.slot), settings_file(MANAGER.slot), control=bool(SET.read(settings_file(MANAGER.slot)).get('control')), slot=MANAGER.slot,
                          multi=multi_env(), world=world_file(MANAGER.slot), bot=bot_file(MANAGER.slot))
    return MULTI.open_(slot, client_folder(), MANAGER.slot)


def clients_closed():
    """Ana istemci ya da bir ek istemci kapandı: hepsi kapandıysa panelin davranışı (sunucuları kapat, pencere kapandıysa çık). Ana
    istemci bu sunucu oturumunda açılmadıysa (yalnız sunucu) ya da erken kapandıysa sunucular açık kalır."""
    if MANAGER.client_alive() or MULTI.live():
        return                                        # bir istemci sürüyor: sunucular açık kalır
    game, last = MANAGER.servers.get('oyun'), MANAGER.last_client
    if not (game and game.alive and MANAGER.client_started and MANAGER.client_started >= game.start and last and not last['early']):
        return
    if CFG.get('when_client_closes') == 'close':
        MANAGER.stop_servers()
    if STATE['window_closed']:
        threading.Thread(target=shutdown, daemon=True).start()


MULTI.on_exit = clients_closed


# ------------------------------------------------------------------ oyna
def _step(text, state='running'):
    o = STATE['play']
    if o['steps'] and o['steps'][-1]['durum'] == 'running':
        o['steps'][-1]['durum'] = 'tamam'
    o['steps'].append({'metin': text, 'durum': state, 'time': time.strftime('%H:%M:%S')})


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
        SM.migrate_client(folder, log)                  # eski sürümün istemci klasöründeki dosyaları (görsel dökümü, metinler)
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
            others = IST.running_clients(MULTI.pids())                     # panelin ek istemcileri sayılmaz
            if others:
                raise Error(_('Another DarkOrbit client is running (process %s). Close it first.', ', '.join(map(str, others))))
            r = RUN.find(CFG)
            if r['tur'] == 'engine' and not r['hata'] and not r['route']:      # macOS: panelin Wine'ı ilk OYNA'da iner (wine_motoru.py)
                _step(_('Downloading Wine and DXMT'))
                ENG.wait(lambda pct: STATE['play']['steps'][-1].update(metin=_('Downloading Wine and DXMT: %d%%', pct)))
            if not PATCH.installed(folder):                   # istemcinin düzeltmeleri: BepInEx sihirbazda kurulmadıysa ilk OYNA'da
                _step(_('Installing BepInEx'))
                if not PATCHER.wait(folder, lambda pct: o['steps'][-1].update(metin=_('Installing BepInEx: %d%%', pct))):
                    o['steps'][-1].update(metin=_('BepInEx could not be installed; the game opens without the fixes: %s',
                                                    PATCHER.state(folder)['hata']), durum='hata')
            cmd, env = IST.command(CFG, folder, os.path.join(PTH.LOGS, 'client.log'))     # Wine / Proton yoksa sunucular açılmadan hata
            if PATCH.installed(folder) and not PATCH.ready(folder):  # BepInEx'in interop derlemeleri oyundan önce (istemci_yama.isit)
                _step(_('Preparing BepInEx for the first launch (about half a minute)'))
                if not PATCH.warm_up(folder, cmd, env, PTH.LOGS, lambda d: o['steps'][-1].update(progress=d)):
                    o['steps'][-1].update(metin=_("BepInEx couldn't be prepared, starting the game anyway"), durum='hata')
        prof = SAV.profile(slot)
        same = MANAGER.running() and MANAGER.slot == slot
        friend = friend or (MANAGER.running() and MANAGER.friend)    # açık arkadaş sunucusu Oyna ile kapanmaz (misafirler düşmesin)
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
            launcher.rotate_logs(PTH.LOGS, names=('gs.log', 'http.log', 'client.log', 'oyun_konsol.log', 'web_konsol.log',
                                                'panel.log'))
        _step((_('Starting the friend server') if friend else _('Starting the servers'))
              if not MANAGER.running() or restart else _('Servers running'))
        MANAGER.start_servers(prof, settings_file(slot), control=bool(SET.read(settings_file(slot)).get('control')), slot=slot, friend=friend_env,
                          multi=multi, world=world_file(slot, friend), bot=bot_file(slot, friend))
        if not server_only:
            _step(_('Opening the game'))
            try:                                      # dünyanın görev başlıkları (eklentinin GorevMetinleri yaması okur)
                WLD.write_texts(folder, world_id(slot, friend))
            except OSError as e:
                log('görev metinleri yazılamadı: %s' % e)
            write_legacy_upgrade(folder, slot)
            MANAGER.start_client(folder, cmd, env)
            if MANAGER.multi or MANAGER.friend:              # birden çok istemci olabilir: pencereler pilotun adıyla ayırt edilsin
                PR.window_title(MANAGER.client.pid, 'DarkOrbit — %s' % SAV.summary(slot).get('pilot', slot))
            m = SAV.meta(slot)
            SAV.set_meta(slot, last_played=time.strftime('%Y-%m-%d %H:%M:%S'), play_count=int(m.get('play_count') or 0) + 1)
        _step(_('Ready') if server_only else _('Game started: have a good flight!'), 'tamam')
        o['finished'] = time.time()
    except (Error, SaveError, RuntimeError, OSError) as e:
        o['hata'] = str(e)
        _step(str(e), 'hata')
        log('oyna hatası: %s' % e)
    except Exception as e:
        o['hata'] = _('Unexpected error: %r', e)
        _step(o['hata'], 'hata')
        log('oyna hatası: %s' % traceback.format_exc())
    finally:
        o['running'] = False


def migration_error():
    """Kayıtlar yeni biçime taşınamadıysa (paths.MIGRATION_ERROR) kullanıcıya gösterilen ileti, yoksa None."""
    return _('Your saves could not be moved to the new format (%s). The backup of the old saves is under '
             'server/save (v1_backup_*.zip); the servers will not start.', PTH.MIGRATION_ERROR) if PTH.MIGRATION_ERROR else None


def start_launch(server_only=False, friend=False):
    o = STATE['play']
    if migration_error():
        raise Error(migration_error())
    if o['running']:
        raise Error(_('Launch in progress.'))
    o.update(running=True, steps=[], hata=None, finished=None, server_only=bool(server_only))
    threading.Thread(target=launch, args=(server_only, friend), daemon=True).start()
    return o


def join_friend(b):
    """Arkadaşlarınla Oyna > Join: denetimler panelde (istemci, açık oyun ve sunucular), katılma arka planda (friends.py)."""
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
    return FRD.killer(str(b.get('address') or ''), str(b.get('password') or ''), slot, c['surum'] or IST.supported(), open_client)


def on_client_exit(early):
    if FRD.client_closed():                         # arkadaşın sunucusundan ayrılınır, misafirin web sunucusu kapanır
        return
    if early:
        return
    clients_closed()                              # ek istemciler sürüyorsa sunucular açık kalır


MANAGER.on_client_exit = on_client_exit


def idle(strict=False):
    """Güncelleme kurulabilir mi: oyun, sunucular, başlatma, istemci indirmesi, protokol aracı durmuş (strict: panelin
    açmadığı DarkOrbit istemcisi de yok; tasklist çalışır)."""
    busy = (MANAGER.running() or MANAGER.client_alive() or STATE['play']['running'] or DL.running() or ADAPTER.state()['running']
            or FRD.active() or MULTI.live() or ENG.running() or PATCHER.running() or LLM.running())
    return not busy and not (strict and IST.running_clients())


def update_tick(now):
    """GitHub denetimi (GUNCELLEME_SN'de bir), otomatik kurulum ve kurulumdan sonra yeniden başlatma (boştayken)."""
    mode = CFG.get('update')
    st = UPD.state()
    if st['running']:
        return
    if st['durum'] == 'installed':
        if idle(strict=True):
            restart()
        return
    if mode == 'off':
        return
    if now >= STATE['next_check']:
        st = UPD.check()
        STATE['next_check'] = now + (3600 if st['durum'] == 'hata' else UPDATE_SEC)
    if st['durum'] == 'exists' and mode == 'auto' and CFG.get('setup_done') and idle(strict=True):
        UPD.install_async()


def restart():
    """Güncellemeden sonra yeniden başla: yeni süreç (pencere açmadan) eski kapanınca aynı portu alır; açık pencere sayfayı yeniler."""
    STATE['closing'] = True
    args = [sys.executable, os.path.join(PANEL_DIR, 'panel.py'), '--no-window', '--updated', '--port=%d' % PORT]
    log('panel güncellendi: yeniden başlatılıyor')
    try:
        if os.name == 'nt':
            subprocess.Popen(args, cwd=ROOT, close_fds=True, creationflags=0x00000008 | 0x00000200)   # DETACHED, yeni süreç grubu
        else:
            subprocess.Popen(args, cwd=ROOT, close_fds=True, start_new_session=True)
        if STATE['srv']:
            STATE['srv'].server_close()
    finally:
        os._exit(0)


def ticker():
    """Oyun sürerken aralıklı yedek; pencere kapandıysa ve iş kalmadıysa çıkış; güncelleme (update_tick)."""
    while not STATE['closing']:
        time.sleep(5)
        try:
            update_tick(time.time())
            iv = CFG.get('backup_interval_min')
            if MANAGER.client_alive() and MANAGER.slot and iv and time.time() - STATE['last_backup'] >= iv * 60:
                SAV.backup(MANAGER.slot, 'auto', _('During the game'))
                STATE['last_backup'] = time.time()
            MULTI.backup(iv)                           # ek istemcilerin kayıtları
            if not STATE['window_watched'] and time.monotonic() - STATE['heartbeat'] > HEARTBEAT_SEC and not STATE['window_closed']:
                STATE['window_closed'] = True
                log('panel penceresi kapandı (sayfa artık sormuyor)')
                if CFG.get('when_window_closes') == 'close':
                    MANAGER.stop_client()
                    MULTI.close_all(wait=8)
            if STATE['window_closed'] and not MANAGER.client_alive() and not MULTI.live() and not STATE['play']['running']:
                shutdown()
        except Exception:
            log('zamanlayıcı hatası: %s' % traceback.format_exc())


def wait_for_client(sec=8):
    """stop_client yalnız sinyal gönderir: istemci kapanana dek bekle (yoksa shutdown sunucuları açık bırakıp çıkıyordu)."""
    last = time.time() + sec
    while MANAGER.client_alive() and time.time() < last:
        time.sleep(0.2)


def shutdown():
    if STATE['closing']:
        return
    STATE['closing'] = True
    log('panel kapanıyor')
    try:
        DL.cancel()                                   # indirme: açılmış dosyalar kalır, sonra kaldığı yerden
        ENG.cancel()
        if not MANAGER.client_alive() and not MULTI.live():
            FRD.shutdown()                             # arkadaşın sunucusundaysa ayrılınır (son hâl kayda)
            MANAGER.stop_servers()
        w = STATE.get('windowed')
        if w and w.poll() is None:                    # panelin açtığı uygulama penceresi de kapansın
            w.terminate()
    finally:
        os._exit(0)


# ------------------------------------------------------------------ pencere
def browser():
    """Uygulama penceresini (--app) açabilen tarayıcı: Edge ya da Chrome (Linux ve macOS'ta Chromium ve Brave de) ya da None."""
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
    """Uygulama penceresi (Edge/Chrome --app, panelin kendi tarayıcı profili) -> izlenebilen süreç ya da None."""
    b = browser()
    if not b:
        import webbrowser
        webbrowser.open(url)
        return None
    old = os.path.join(os.path.dirname(BROWSER_PROFILE), 'tarayici')      # eski adı (2026-11-01 öncesi): pencere boyutu, izinler kalsın
    if os.path.isdir(old) and not os.path.exists(BROWSER_PROFILE):
        try:
            os.replace(old, BROWSER_PROFILE)
        except OSError:
            pass                                        # eski pencere açık: yeni profille açılır
    os.makedirs(BROWSER_PROFILE, exist_ok=True)
    return subprocess.Popen([b, '--app=%s' % url, '--user-data-dir=%s' % BROWSER_PROFILE, '--window-size=1360,880',
                             '--no-first-run', '--no-default-browser-check', '--disable-features=Translate,msEdgeSidebarV2',
                             '--disable-background-mode', '--disable-sync', '--lang=%s' % D.LANGUAGES[D.current()][1]])


def watch_window(proc):
    STATE['windowed'] = proc
    if sys.platform == 'darwin':
        # macOS'ta pencere kapanınca tarayıcı (öteki uygulamalar gibi) Dock'ta açık kalır: süreç beklenemez. Kapanış sayfanın
        # kapanış işaretinden ve nabzından anlaşılır (/api/kapandi, ticker; tarayıcıdan çıkılınca da işaret gelir); panel kapanınca
        # bu süreç de kapanır (shutdown)
        return
    STATE['window_watched'] = True
    t0 = time.time()
    proc.wait()
    STATE['window_watched'] = False
    if time.time() - t0 < HANDOVER_SEC:
        # aynı profil klasörüyle açık bir tarayıcı süreci varsa yeni süreç pencereyi ona devredip hemen çıkar (18, 20 ve 22 Ekim:
        # panel açılır açılmaz "kapandı" sayılıp kapanıyordu): pencere açık, kapanışı sayfanın nabzından anlaşılır (ticker)
        STATE['heartbeat'] = time.monotonic()
        log('panel penceresi açık bir tarayıcı sürecine devredildi; nabızla izleniyor')
        return
    log('panel penceresi kapandı')
    if CFG.get('when_window_closes') == 'close':
        MANAGER.stop_client()
        MULTI.close_all(wait=8)                   # ek istemcilerin son kaydı sunucuya bırakılsın
        wait_for_client()
        shutdown()
    STATE['window_closed'] = True


SHORTCUT, OLD_SHORTCUT = 'OpenOrbit.lnk', 'DarkOrbit.lnk'   # eski: 2026-10-24'ten önce konan (kaldırılan "DarkOrbit Panel.pyw"yi açar)


def desktop_dir():
    """Masaüstü klasörü (OneDrive'a taşınmışsa da; Linux'ta xdg-user-dir'in söylediği)."""
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
    """Masaüstündeki eski adlı kısayolun yolu ya da None: yalnız hedefi bu panelin eski başlatıcısı "DarkOrbit Panel.pyw" olan
    (oyunun kendi DarkOrbit kısayolu değil). Kısayol kendiliğinden değiştirilmez; kullanıcı "Kısayol oluştur"a basınca yenisi konur."""
    p = os.path.join(desktop_dir(), OLD_SHORTCUT)
    try:
        with open(p, 'rb') as fh:
            return p if 'DarkOrbit Panel.pyw'.encode('utf-16-le') in fh.read() else None
    except OSError:
        return None


def mac_shortcut(script):
    """macOS: masaüstüne OpenOrbit.app (paneli arka planda başlatan küçük uygulama paketi; Terminal penceresi açılmaz, Dock'ta
    kalmaz; simge panelinki, sips ve iconutil ile) -> yolu. Eski sürümlerin koyduğu OpenOrbit.command kaldırılır."""
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
    subprocess.run(['touch', app], capture_output=True)      # Finder simgeyi yenilesin
    return app


def _mac_icon(out):
    """Panelin simgesi (arayuz/icon.png, 512x512) -> .icns; olmazsa None (uygulama genel simgeyle açılır)."""
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
    """Masaüstü kısayolu 2026-11-01'den önceki simge yolunu (server/panel/arayuz/simge.*; İngilizce geçişte arayuz -> ui) gösteriyorsa
    yeniden oluşturulur; yoksa ya da güncelse dokunulmaz -> yenilendi mi."""
    if sys.platform == 'darwin':                      # OpenOrbit.app simgeyi kendi içine kopyalar
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
        log('kısayol yenilendi (simge yolu)')
        return True
    except Exception as e:                            # kısayol olmadan da panel çalışır
        log('kısayol yenilenemedi: %s' % e)
        return False


def unix_shortcut():
    """Linux: masaüstüne ve uygulama menüsüne openorbit.desktop; macOS: masaüstüne OpenOrbit.app (mac_shortcut) -> masaüstündekinin
    yolu."""
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
    if shutil.which('gio'):                           # GNOME masaüstündeki kısayolu "güvenilir" saymadan açmıyor
        subprocess.run(['gio', 'set', p, 'metadata::trusted', 'true'], capture_output=True, timeout=10)
    return p


def create_shortcut():
    """Masaüstüne OpenOrbit kısayolu; eski adlı kısayol (old_shortcut) varsa kaldırılır -> yeni kısayolun yolu."""
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
        log('eski kısayol kaldırıldı: %s' % old)
    return lnk


# ------------------------------------------------------------------ API
def screen_size():
    if sys.platform == 'darwin':                      # ana ekranın nokta çözünürlüğü (Wine'ın gösterdiği; Retina'da piksel yarısı)
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
    out = dict(s, ad=_(s['ad']), aciklama=_(s['aciklama']))
    if s.get('options'):
        out['options'] = [_(x) for x in s['options']]
    if s.get('option_description'):
        out['option_description'] = [_(x) for x in s['option_description']]
    if s.get('unit'):
        out['unit'] = _(s['unit'])
    return out


def write_legacy_upgrade(folder=None, slot=None):
    """Eski yükseltme sisteminin uridyum bedelleri istemcinin BepInEx klasörüne (eklentinin EskiYukseltme yaması Assembly'nin
    tariflerini bunlarla değiştirir; kapalıyken {}: istemcinin kendi malzemeleri). OYNA'da ve ayarlar kaydedilince."""
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
        log('eski yükseltme bedelleri yazılamadı: %s' % e)


def api_settings():
    ready = {k: dict(p, ad=_(p['ad']), aciklama=_(p['aciklama'])) for k, p in SET.PRESETS.items()}
    slot = SAV.active()
    return {'schema': [_schema_row(s) for s in SET.SCHEMA], 'gruplar': [{'anahtar': k, 'ad': _(a)} for k, a in SET.GROUPS],
            'values': game_settings(), 'default': SET.DEFAULTS, 'hazir': ready, 'templates': read_json(TEMPLATES, {}),
            'server_running': MANAGER.running(), 'record': slot, 'save_name': SAV.meta(slot).get('ad', slot) if slot else None,
            'saves': [{'id': s, 'ad': SAV.meta(s).get('ad', s)} for s in SAV.slots() if s != slot]}


def launch_command():
    """İstemci sayfasında gösterilen başlatma komutu (Linux ve macOS'ta Wine ya da Proton'la; bulunamadıysa yalnız istemcininki)."""
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
            'resolutions': IST.RESOLUTIONS, 'ekran': screen_size(), 'settings': CFG.all(),
            'command': launch_command(), 'runner': RUN.summary(CFG), 'supported': IST.supported(),
            'protokol': ADAPTER.state(), 'download': DL.state(), 'patch': PATCHER.state(used)}


def extra_logs():
    """Ek istemcilerin günlükleri (logs/client_<kayıt>.log)."""
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
    pl, g = d.get('pilot') or {}, d.get('gemi') or {}
    return {'pilot': pl.get('userName', ''), 'kredi': pl.get('credits', 0), 'uridyum': pl.get('uridium', 0),
            'onur': pl.get('honourPoints', 0), 'ep': pl.get('ep', 0), 'seviye': pl.get('level', 1),
            'can': g.get('hitPoints', 0), 'max_hp': g.get('hitMax', 0), 'kalkan': g.get('shield', 0),
            'shield_max': g.get('shieldMax', 0), 'firma': COMPANIES.get(pl.get('factionId'), '?'),
            'in_use': SAV.in_use(sid)}


def worlds_status():
    users = world_users()
    return {'liste': WLD.entries(users), 'covers': WLD.COVERS, 'server_running': MANAGER.running(),
            'server_world': MANAGER.world[0] if MANAGER.running() and MANAGER.world else None, 'saves': [
                {'id': k['id'], 'ad': k.get('ad'), 'pilot': k.get('pilot'), 'firma': k.get('firma'), 'seviye': k.get('seviye'),
                 'world': k.get('world') if k.get('world') and WLD.var(k.get('world')) else WLD.STANDARD, 'active': k.get('active')}
                for k in SAV.list()]}


def world_arg(q):
    did = q.get('world') or WLD.STANDARD
    if not WLD.var(did):
        raise Error(_('World not found.'))
    return did


def world_get(path, q):
    if path == '/api/dunyalar':
        return worlds_status()
    if path == '/api/dunya':
        did = world_arg(q)
        is_open = bool(MANAGER.running() and MANAGER.world and WLD.file_path(did) and MANAGER.world[0] == os.path.normcase(WLD.file_path(did)))
        # yeniden_gerekli: sunucu açıldıktan sonra oyun açıkken uygulanamayan bir değişiklik yapıldı (mağaza ve açık artırma canlı)
        return dict(WLD.summary(did, world_users()), server_in_this_world=is_open,
                    restart_needed=is_open and PR.world_signature(WLD.file_path(did)) != MANAGER.world)
    if path == '/api/dunya/section':
        did, section = world_arg(q), q.get('section')
        if section == 'alien_spawns':
            return {'alien_spawns': WLD.aliens(did)}
        if section == 'haritalar':
            return {'haritalar': WLD.maps(did)}
        if section == 'quests':
            return {'quests': WLD.quests(did)}
        if section == 'shop':
            return {'categories': WLD.shop(did), 'visual': bool(game_image('dizin.json'))}
        if section == 'auction':
            return WLD.auction(did)
        if section == 'boxes':
            return WLD.boxes(did)
        if section == 'kapilar':
            return {'kapilar': WLD.gates(did)}
        if section == 'economy':
            return WLD.economy(did)
        if section == 'events':
            return {'events': WLD.events(did), 'classes': WLD.MAP_CLASSES}
        raise Error(_('Unknown section.'))
    if path == '/api/dunya/harita':
        return WLD.game_map(world_arg(q), q.get('id'))
    if path == '/api/dunya/gorev':
        return WLD.quest(world_arg(q), q.get('id'))
    if path == '/api/dunya/esyalar':
        return {'esyalar': WLD.item_list()}
    raise Error(_('Unknown request.'))


def world_post(path, b):
    if path == '/api/kayitlar/dunya':               # kaydın varsayılan dünyası (OYNA bununla açar)
        sid, did = b.get('id'), b.get('world') or WLD.STANDARD
        if not sid or not SAV.exists(sid):
            raise Error(_('Save not found.'))
        if not WLD.var(did):
            raise Error(_('World not found.'))
        SAV.set_meta(sid, world=None if did == WLD.STANDARD else did)
        return worlds_status()
    if path == '/api/dunya/create':
        did = WLD.create(b.get('ad'), b.get('aciklama', ''), b.get('cover', 'nebula'), source=b.get('kaynak'), from_draft=bool(b.get('from_draft')))
        if b.get('record') and SAV.exists(b['record']):  # oluşturunca bu kaydın varsayılanı yap
            SAV.set_meta(b['record'], world=did)
        return dict(worlds_status(), yeni=did)
    if path == '/api/dunya/update':
        WLD.update(b.get('id'), name=b.get('ad'), description=b.get('aciklama'), cover=b.get('cover'))
        return worlds_status()
    if path == '/api/dunya/sil':
        did = b.get('id')
        WLD.remove(did)
        for k in SAV.list():                        # varsayılanı bu dünya olan kayıtlar standarda döner
            if k.get('world') == did:
                SAV.set_meta(k['id'], world=None)
        return worlds_status()
    if path == '/api/dunya/copy':
        return dict(worlds_status(), yeni=WLD.duplicate(b.get('id'), b.get('ad')))
    if path == '/api/dunya/discard_draft':
        WLD.discard_draft()
        return worlds_status()
    if path == '/api/dunya/disari':
        did = world_arg(b)
        name = re.sub(r'[^\w.-]+', '_', WLD.read(did).get('ad') or did)[:40]
        dest = dialog('save', title=_('Export world'), initialfile='%s.oodunya.json' % name, defaultextension='.json',
                      filetypes=[(_('OpenOrbit world'), '*.json')])
        if not dest:
            return {'cancelled': True}
        write_json(dest, WLD.export(did))
        return {'route': dest}
    if path == '/api/dunya/kod':                    # paylaşım kodu (Discord'a yapıştırılır)
        return {'code': WLD.code(world_arg(b))}
    if path == '/api/dunya/import':                  # paylaşım kodundan ya da dosyadan
        if b.get('code'):
            data = WLD.from_code(b['code'])
        else:
            src = dialog('ac', title=_('Import world'), filetypes=[(_('OpenOrbit world'), '*.json'), (_('All files'), '*.*')])
            if not src:
                return {'cancelled': True}
            data = read_json(src, None)
        did, report = WLD.import_(data)
        return dict(worlds_status(), yeni=did, report=report)
    if path == '/api/dunya/yama':                   # editörün değişikliği: dosya + yol -> tam değer (standartta taslağa)
        did = world_arg(b)
        WLD.patch(did, b.get('dosya'), b.get('route'), b.get('value'))
        return world_get('/api/dunya', {'world': did})
    if path == '/api/dunya/geri_al':
        did = world_arg(b)
        WLD.revert(did, b.get('dosya'), b.get('route'), b.get('section'))
        return world_get('/api/dunya', {'world': did})
    if path == '/api/dunya/gorev':
        did = world_arg(b)
        WLD.save_quest(did, b.get('id'), b.get('changes') or {})
        return WLD.quest(did, b.get('id'))
    if path == '/api/dunya/new_quest':
        did = world_arg(b)
        qid = WLD.new_quest(did, b.get('ad'), b.get('seviye'), b.get('targets') or [], b.get('rewards') or [])
        return WLD.quest(did, qid)
    if path == '/api/dunya/server_restart':         # editörden: dünyanın değişiklikleri için sunucuyu yeniden başlat
        return h_post('/api/sunucu/restart', {})
    raise Error(_('Unknown request.'))


def bots_status():
    users = world_users()
    worlds = [{'id': w['id'], 'ad': w['ad'], 'cover': w['cover'], 'standard': w['standard'],
                 'pilots': [u.get('pilot') or u.get('ad') for u in w.get('users') or []]} for w in WLD.entries(users)]
    return {'liste': BT.entries(), 'worlds': worlds, 'bot_modes': BT.MODES, 'permissions': BT.PERMISSIONS, 'classes': BT.SIMPLE_CLASSES,
            'settings': {k: {'tur': v[0], 'en_az': v[1], 'max_count': v[2], 'default': v[3]} for k, v in BT.SETTINGS.items()},
            'llm_multilingual': PRV.multilingual(), 'server_running': MANAGER.running(), 'server_pack': getattr(MANAGER, 'bot', None) and MANAGER.bot[0], 'game_settings': bot_game_settings()}


def bot_game_settings():
    """Botların oyun ayarı profilleri (bot/game_settings.py): hazır profiller ve Özel profilin alanları (oyun ayarlarının adlarıyla)."""
    from bot import game_settings as GS
    ready = [{'id': k, 'ad': SET.PRESETS[k]['ad'], 'aciklama': SET.PRESETS[k]['aciklama']} for k in GS.PROFILES if k in SET.PRESETS]
    fields = [{'anahtar': k, 'ad': SET.BY_KEY[k]['ad'], 'aciklama': SET.BY_KEY[k]['aciklama'], 'en_az': SET.BY_KEY[k].get('min', 0),
                'max_count': min(10, SET.BY_KEY[k].get('max', 10))} for k in GS.FIELDS]
    return {'hazir': ready, 'fields': fields}


def player_names():
    return [k.get('pilot') for k in SAV.list() if k.get('pilot')]


def bot_get(path, q):
    if path == '/api/botlar':
        return bots_status()
    if path == '/api/bot/llm':
        return dict(LLM.state(), provider=PRV.status())
    if path == '/api/bot/detay':                   # Kadro > bot penceresi: oyun açıkken canlı bot, kapalıyken son kayıt
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
            return dict(game_channel('/bot/detay', {'no': no}), catalog=BT.edit_catalog(), live=True)
        except Error:
            # oyun açık ama kanal yanıt vermedi: son kayıt, düzenlenemez (oyun dosyayı yeniden yazar)
            return dict(BT.bot_detail(pid, no), catalog=BT.edit_catalog(), live=False, read_only=True)
    return dict(BT.bot_detail(pid, no), catalog=BT.edit_catalog(), live=False)


def bot_post(path, b):
    if path == '/api/bot/detay':                   # botu düzenle (bot/duzenle.py): oyun açıkken canlı, kapalıyken dosyada
        pid, no, value = b.get('id'), int(b.get('no') or 0), b.get('changes') or {}
        if not isinstance(value, dict) or not value:
            raise Error(_('No changes.'))
        if is_pack_running(pid):
            r = game_channel('/bot/edit', {'no': no, 'changes': value})
            if r.get('hata'):
                from bot import edit as ED
                raise Error(BT.edit_error(ED.EditError(r['hata'], r.get('area', ''))))
            if 'traits' in value:
                BT.bot_personality(pid, no, value['traits'])
            return dict(r, catalog=BT.edit_catalog(), live=True)
        return dict(BT.edit_bot(pid, no, value), catalog=BT.edit_catalog(), live=False)
    if path == '/api/bot/llm/saglayici':          # sağlayıcı seçimi: dahili model, OpenAI, Claude ... (bot/llm_saglayici.py)
        if b.get('kimlik') not in PRV.PROVIDERS:
            raise Error(_('Unknown request.'))
        if b.get('address') and not re.fullmatch(r'https?://\S+', str(b['address']).strip()):
            raise Error(_('The address must start with http:// or https://.'))
        PRV.save(b['kimlik'], b.get('address'), b.get('model'), b.get('anahtar'))
        return bot_get('/api/bot/llm', {})
    if path == '/api/bot/llm/models':
        try:
            return {'models': PRV.models(b.get('kimlik'), b.get('address') or None, b.get('anahtar') or None)}
        except PRV.ProviderError as e:
            raise Error(str(e))
    if path == '/api/bot/llm/test' and PRV.setting()['selected'] != PRV.LOCAL:
        try:
            return dict(LLM.test_remote(), provider=PRV.status())
        except LLMS.DownloadError as e:
            raise Error(str(e))
    if path.startswith('/api/bot/llm/'):           # dil modeli: kur, durdur, sil, test
        operation = {'kur': LLM.start, 'stop': LLM.cancel, 'delete': LLM.remove, 'test': LLM.test}.get(path.rsplit('/', 1)[1])
        if operation is None:
            raise Error(_('Unknown request.'))
        if path.endswith('/delete') and MANAGER.running():
            raise Error(_('Close the game first.'))
        try:
            return dict(operation(), provider=PRV.status())
        except LLMS.DownloadError as e:
            raise Error(str(e))
    if path == '/api/bot/create':
        pid = BT.create(b.get('ad'), b.get('aciklama', ''), b.get('world'), b.get('mode', 'normal'), b.get('progression', 'progressive'),
                         b.get('adet', 60), b.get('dil', 'mixed'), b.get('company_distribution') or (1, 1, 1), b.get('settings') or {},
                         players=player_names(), name_lang_=b.get('name_lang'), special=b.get('ozel') or '', name_source=b.get('name_source'))
        return dict(bots_status(), yeni=pid)
    pid = b.get('id')
    if path == '/api/bot/update':
        BT.update(pid, name=b.get('ad'), description=b.get('aciklama'), mode=b.get('mode'), progression=b.get('progression'), settings=b.get('settings'))
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/assign':                      # paketi dünyaya ata (o dünyanın eski paketi boşa çıkar)
        did = b.get('world') or None
        if did and not WLD.var(did):
            raise Error(_('World not found.'))
        BT.assign(pid, did)
        return bots_status()
    if path == '/api/bot/kadro':
        if is_pack_running(pid) and (b.get('regenerate') or int(b.get('adet') or 0) < len(BT.read(pid)['roster'])):
            raise Error(_('This pack is open in the game: close the game first.'))     # çalışan oyun eski kadroyla durumu yeniden yazar
        BT.roster(pid, count=b.get('adet'), lang=b.get('dil'), company_distribution=b.get('company_distribution'), regenerate=bool(b.get('regenerate')),
                 players=player_names(), name_lang_=b.get('name_lang'), special=b.get('ozel') or '', name_source=b.get('name_source'))
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/ad':
        BT.bot_name(pid, int(b.get('no') or 0), b.get('ad'), players=player_names())
        if is_pack_running(pid):
            try:
                game_channel('/bot/ad_kaydi', {})           # oyunda hemen: bot, klanlar, rehberler
            except Error:
                pass                                       # oyuna girilmemiş: sonraki açılışta uygulanır
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/sifirla':
        if is_pack_running(pid):
            raise Error(_('This pack is open in the game: close the game first.'))
        BT.reset(pid)
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/sil':
        if is_pack_running(pid):
            raise Error(_('This pack is open in the game: close the game first.'))
        BT.remove(pid)
        return bots_status()
    if path == '/api/bot/server_restart':
        return h_post('/api/sunucu/restart', {})
    raise Error(_('Unknown request.'))


_SUPPORTERS = {'time': 0, 'adlar': []}


def supporters():
    """Buy Me a Coffee sayfasının son destekçileri (gizli olanlar hariç; 10 dakika önbellek, bağlantı yoksa boş liste)."""
    if time.time() - _SUPPORTERS['time'] > 600:
        try:
            with urlopen(Request(DONATE_API_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}), timeout=6) as r:
                data = json.load(r).get('data') or []
            _SUPPORTERS['adlar'] = list(dict.fromkeys(str(x.get('supporter_name') or '').strip() for x in data
                                                    if x.get('support_visibility') == 1 and x.get('supporter_name')))
            _SUPPORTERS['time'] = time.time()
        except (OSError, ValueError):
            return []                                  # çevrimdışı: şerit gizli kalır, sonraki açılışta yeniden denenir
    return _SUPPORTERS['adlar']


def h_get(path, q):
    if path.startswith('/api/bot'):                 # Botlar (botlar.py)
        return bot_get(path, q)
    if path.startswith('/api/dunya'):               # Dünya Editörü (dunyalar.py)
        return world_get(path, q)
    if path == '/api/supporters':                 # kenar çubuğundaki kayan destekçi şeridi
        return {'adlar': supporters()}
    if path == '/api/durum':
        return status()
    if path == '/api/ayarlar':
        return api_settings()
    if path == '/api/etkinlikler':
        return event_list()
    if path == '/api/kayitlar':
        return {'liste': SAV.list(), 'active': SAV.active(), 'trash': SAV.deleted(), 'companies': COMPANIES}
    if path == '/api/save_profile':
        return profile_values(slot_arg(q))
    if path == '/api/editor':                       # karakter editörü: kaydın taslağı (kayit_editoru.py)
        return SAV.editor_open(slot_arg(q))
    if path == '/api/editor/katalog':               # karakter editörünün eşya kataloğu
        return SAV.editor_catalog()
    if path == '/api/item_info':                   # eşya ipucunun değerleri (Hangar, Mağaza, karakter editörü)
        return {'esyalar': SAV.item_info()}
    if path == '/api/backups':
        sid = slot_arg(q)
        return {'liste': SAV.backups(sid), 'record': SAV.summary(sid), 'settings': CFG.all()}
    if path == '/api/istemci':
        return api_client()
    if path == '/api/panel_settings':
        return CFG.all()
    if path == '/api/discord_rp':                   # Discord Rich Presence: bağlantı ve profilde görünecek etkinlik (önizleme)
        return {'durum': RP.state, 'hata': RP.error, 'etkinlik': RP.preview(), 'settings': CFG.all()}
    if path == '/api/diller':
        return {'languages': D.entries()}
    if path == '/api/takvim':                       # etkinlik takvimi: ?start=&bit= (zaman damgası, en çok 62 gün)
        return api_calendar(q)
    if path == '/api/portlar':
        return MANAGER.foreign_ports()
    if path == '/api/gunluk':
        name = q.get('ad', 'gs.log')
        if name not in LOGS and not EXTRA_LOG.fullmatch(name):
            raise Error(_('Unknown log.'))
        p = os.path.join(PTH.LOGS, name)
        n = min(5000, max(50, int(q.get('row', 400))))
        return {'ad': name, 'exists': os.path.isfile(p), 'size': os.path.getsize(p) if os.path.isfile(p) else 0,
                'lines': PR.tail(p, n), 'liste': [{'ad': g, 'size': os.path.getsize(os.path.join(PTH.LOGS, g))
                                                       if os.path.isfile(os.path.join(PTH.LOGS, g)) else None}
                                                      for g in LOGS + extra_logs()]}
    if path == '/api/istemci/indirme':              # istemci indirmenin durumu (indirme.py)
        return DL.state()
    if path == '/api/motor':                        # macOS: panelin Wine'ı ve Rosetta (wine_motoru.py)
        return ENG.state()
    if path == '/api/yama':                         # istemcinin düzeltmelerini yükleyen BepInEx (istemci_yama.py)
        return PATCHER.state(client_folder())
    if path == '/api/guncelleme':                   # GitHub'dan güncelleme (guncelleme.py)
        return dict(UPD.state(), ayar=CFG.get('update'), idle=idle())
    if path == '/api/protokol':                     # protokol uyarlamasının durumu (protokol.py)
        return dict(ADAPTER.state(), etkin=IST.supported())
    if path == '/api/item_list':                 # kayıt düzenleyicinin "eşya ver" listesi
        return {'esyalar': SAV.loot_list()}
    if path == '/api/oyun/magaza':                  # oyun menüleri: mağazanın listesi ve cüzdan (panel_kanali.py)
        return dict(game_channel('/magaza'), visual=bool(game_image('dizin.json')))
    if path == '/api/oyun/hangar':                  # oyun menüleri: gemiler, config'ler, yuvalar ve envanter (?gemi=)
        return dict(game_channel('/hangar?gemi=%s' % re.sub(r'\D', '', str(q.get('gemi') or ''))), visual=bool(game_image('dizin.json')))
    if path == '/api/oyun/muzayede':                # oyun menüleri: açık artırma (lotlar, kurallar, geçmiş, olaylar)
        return dict(game_channel('/muzayede'), visual=bool(game_image('dizin.json')))
    if path == '/api/oyun/muzayede/olaylar':        # açık artırmanın yeni olayları (panelin bildirimleri)
        return game_channel('/muzayede/olaylar?last=%d' % int(q.get('last') or 0))
    if path == '/api/oyun/skylab':                  # oyun menüleri: Skylab modülleri, depo, enerji, taşıma
        return dict(game_channel('/skylab'), visual=bool(game_image('dizin.json')))
    if path == '/api/canli':                        # canlı durum (oyun sunucusunun canli_durum.json'u; canli_durum.py)
        p = os.path.join(PTH.LOGS, 'canli_durum.json')
        d = read_json(p, None)
        if not d or (not MANAGER.running() and time.time() - d.get('time', 0) > 15):    # eski dosya: sunucu kapalı
            return {'exists': False, 'server_running': MANAGER.running()}
        import event_calendar as CAL
        d['event_names'] = [_(CAL.EVENTS.get(k, {}).get('ad', k)) for k in d.get('events', [])]
        return {'exists': True, 'server_running': True, 'age': max(0, time.time() - d.get('time', 0)), 'durum': d}
    if path == '/api/arkadas':                      # Arkadaşlarınla Oyna: Host (sunucu, adresler, misafirler) ve Join (oturum)
        live = read_json(os.path.join(PTH.LOGS, 'canli_durum.json'), None) if MANAGER.running() else None
        active = SAV.active()
        return {'host': FRD.host_status(live), 'guest': FRD.state(), 'saves': SAV.list(), 'active': active,
                'client_version': IST.check(client_folder()).get('surum') or IST.supported(),
                # Host'un dünyası (Dünya Editörü): seçim ('' kaydının dünyası), seçilebilenler ve sunucunun açılacağı dünya
                'world': {'choice': CFG.get('friend_world') if WLD.var(CFG.get('friend_world') or '') else '',
                          'save_world': world_info(SAV.meta(active).get('world') if active else None), 'valid': world_info(world_id(active, True)),
                          'liste': [{'id': w['id'], 'ad': w['ad'], 'cover': w['cover'], 'standard': w['standard']} for w in WLD.entries()]}}
    if path == '/api/about':
        return {'surum': VERSION, 'python': sys.version.split()[0], 'root': ROOT, 'sunucu': SERVER, 'saves': PTH.SAVES,
                'logs': PTH.LOGS, 'settings': settings_file(), 'panel': PTH.PANEL, 'port': PORT, 'dil': D.current(), 'discord': DISCORD,
                'old_shortcut': bool(old_shortcut())}
    raise Error(_('Unknown request: %s', path))


def h_post(path, b):
    if migration_error() and path not in ('/api/kapat', '/api/guncelleme/check', '/api/guncelleme/kur'):
        raise Error(migration_error())              # kayıtlar taşınamadı: yeni kayıt, ayar ... yazılmaz (yeniden denemede çakışmasın)
    if path.startswith('/api/bot/'):                # Botlar (botlar.py)
        return bot_post(path, b)
    if path.startswith('/api/dunya') or path == '/api/kayitlar/dunya':      # Dünya Editörü (dunyalar.py)
        return world_post(path, b)
    if path == '/api/oyun/al':                      # oyun menüleri: mağazadan satın alma (istemcinin isteğiyle aynı yoldan)
        return game_channel('/magaza/al', {k: b.get(k) for k in ('lootId', 'category', 'amount', 'level')})
    if path == '/api/oyun/magaza/subscribe':            # oyun menüleri: booster aboneliği
        return game_channel('/magaza/subscribe', {'lootId': b.get('lootId'), 'category': b.get('category')})
    if path == '/api/oyun/hangar/tasi':             # oyun menüleri: envanter <-> gemi, dron ya da P.E.T. yuvası
        return game_channel('/hangar/tasi', {k: b.get(k) for k in ('gemi', 'config', 'esya', 'direction', 'hedef', 'drone', 'set')})
    if path == '/api/oyun/hangar/islem':            # oyun menüleri: config, satış, P.E.T., CPU işlemleri (panel_kanali.ISLEMLER)
        return game_channel('/hangar/islem', {k: b.get(k) for k in ('islem', 'gemi', 'config', 'target_ship', 'favorite', 'esyalar', 'drone',
                                                                    'ad', 'yuva', 'esya', 'ammunition', 'lootId')})
    if path == '/api/oyun/hangar/tasarim':          # oyun menüleri: geminin görünümü (tasarımı)
        return game_channel('/hangar/tasarim', {'gemi': b.get('gemi'), 'lootId': b.get('lootId')})
    if path == '/api/oyun/hangar/etkin':            # oyun menüleri: geminin etkinleştirilmesi (yalnız istasyonda)
        return game_channel('/hangar/etkin', {'gemi': b.get('gemi')})
    if path == '/api/oyun/skylab/islem':            # oyun menüleri: Skylab yükseltme, aç/kapa, gemiye taşıma
        return game_channel('/skylab/islem', {k: b.get(k) for k in ('modul', 'islem', 'mod', 'amounts')})
    if path.startswith('/api/oyun/muzayede/') and path.rsplit('/', 1)[1] in ('teklif', 'hepsi', 'anlik', 'oto', 'alarm'):   # açık artırma
        return game_channel('/muzayede/' + path.rsplit('/', 1)[1], {k: b.get(k) for k in ('tur', 'loot', 'price', 'lotlar', 'azami', 'gecilince', 'dk')})
    if path == '/api/oyun/skylab/robot':            # oyun menüleri: toplayıcıya robot
        return game_channel('/skylab/robot', {'modul': b.get('modul'), 'tip': b.get('tip')})
    # ---- oyun ve sunucular
    if path == '/api/oyna':
        return start_launch(b.get('server_only'))
    if path == '/api/arkadas/ayarlar':
        world = b.get('world', CFG.get('friend_world')) or ''
        if world and not WLD.var(world):
            raise Error(_('World not found.'))
        CFG.update({'friend_password': str(b.get('password') if 'password' in b else CFG.get('friend_password') or '')[:64],
                    'friend_max': b.get('max_count', CFG.get('friend_max')), 'friend_world': world})
        return h_get('/api/arkadas', {})
    if path == '/api/arkadas/host':                 # arkadaş sunucusu: Oyna gibi, oyun sunucusu --cok-oyunculu
        return start_launch(b.get('server_only'), friend=True)
    if path == '/api/arkadas/public_ip':
        return {'ip': FRD.find_public_ip()}
    if path == '/api/arkadas/kick':
        FRD.at(b.get('oturum'))
        return {}
    if path == '/api/arkadas/test':
        return FRD.attempt(str(b.get('address') or ''))
    if path == '/api/arkadas/join':
        return join_friend(b)
    if path == '/api/arkadas/leave':
        FRD.detach()
        return FRD.state()
    if path == '/api/sunucu/durdur':
        if MANAGER.client_alive():
            raise Error(_("The server can't be stopped while the game is running: close the game first."))
        if MULTI.live():
            raise Error(_("The server can't be stopped while extra clients are open: close them first."))
        MANAGER.stop_servers()
        return MANAGER.status()
    if path == '/api/sunucu/restart':
        slot = MANAGER.slot or SAV.active()
        if not slot:
            raise Error(_('No save.'))
        if MULTI.live():
            raise Error(_("The server can't be restarted while extra clients are open: close them first."))
        friend_env = FRD.host_env() if MANAGER.running() and MANAGER.friend else None       # kip korunur (Host, çoklu istemci)
        multi = None if friend_env else (multi_env() if (MANAGER.running() and MANAGER.multi) or multi_wanted(slot) else None)
        MANAGER.stop_servers()
        MANAGER.start_servers(SAV.profile(slot), settings_file(slot), control=bool(SET.read(settings_file(slot)).get('control')), slot=slot, friend=friend_env,
                          multi=multi, world=world_file(slot, bool(friend_env)), bot=bot_file(slot, bool(friend_env)))
        return MANAGER.status()
    if path == '/api/istemci/kapat':
        MANAGER.stop_client()
        return MANAGER.status()
    if path == '/api/coklu/ac':                     # çoklu istemci: başka bir kayıtla ek istemci (coklu.py)
        return open_extra(b)
    if path == '/api/coklu/kapat':
        MULTI.close(str(b.get('record') or ''))
        return MULTI.state()
    if path == '/api/coklu/close_all':
        MULTI.close_all()
        return MULTI.state()
    if path == '/api/portlar/kapat':
        pid = int(b.get('pid') or 0)
        info = PR.process_info(pid)
        if not (PR.is_our_server(info) or info['ad'].lower() == 'darkorbit.exe'):
            raise Error(_("This process (%s) is not the panel's server; the panel won't close it. Close it yourself if needed.", info['ad']))
        m = re.search(r'"--stop-file=([^"]+)"|--stop-file=(\S+)', info.get('command') or '')
        if m:                                       # önceki panelin oyun sunucusu: önce kaydedip kendisi çıksın
            try:
                open(m.group(1) or m.group(2), 'w').close()
                end = time.time() + 6
                while time.time() < end and pid in (PR.listeners() or {}).values():
                    time.sleep(0.2)
            except OSError:
                pass
        if pid in (PR.listeners() or {}).values() or not m:
            PR.kill(pid)
        log('eski süreç kapatıldı: %s %s' % (pid, info['ad']))
        time.sleep(0.5)
        return MANAGER.foreign_ports()
    # ---- oyun ayarları
    if path == '/api/ayarlar':
        vals = game_settings()
        for k, v in (b.get('values') or {}).items():
            if k in SET.BY_KEY:
                vals[k] = v
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/ayarlar/copy':             # başka bir kaydın ayarları (etkinlik seçimleri dahil) etkin kayda
        slot = SAV.active()
        if not slot:
            raise Error(_('No save.'))
        SAV.copy_settings(str(b.get('kaynak') or ''), slot)
        log('ayarlar kopyalandı: %s -> %s' % (b.get('kaynak'), slot))
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/ayarlar/sifirla':
        vals = game_settings()
        keys = b.get('keys') or list(SET.BY_KEY)
        for k in keys:
            vals.pop(k, None)
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/ayarlar/hazir':
        name = b.get('ad')
        user = read_json(TEMPLATES, {})
        preset = SET.PRESETS.get(name, {}).get('values') if name in SET.PRESETS else (user.get(name) or {}).get('values')
        if preset is None:
            raise Error(_('Preset not found.'))
        vals = {k: v for k, v in game_settings().items() if k not in SET.BY_KEY}     # etkinlik seçimleri kalır
        vals.update(preset)
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/ayarlar/save_template':
        name = (b.get('ad') or '').strip()[:40]
        if not name:
            raise Error(_('Give the template a name.'))
        user = read_json(TEMPLATES, {})
        vals = {k: v for k, v in game_settings().items() if k in SET.BY_KEY and v != SET.DEFAULTS[k]}
        user[name] = {'ad': name, 'aciklama': b.get('aciklama') or _('Your own settings'), 'values': vals}
        write_json(TEMPLATES, user)
        return api_settings()
    if path == '/api/ayarlar/delete_template':
        user = read_json(TEMPLATES, {})
        user.pop(b.get('ad'), None)
        write_json(TEMPLATES, user)
        return api_settings()
    if path == '/api/etkinlikler':
        return set_events(b)
    # ---- kayıtlar
    if path == '/api/kayitlar/yeni':
        sid = SAV.create(b.get('ad'), b.get('pilot'), b.get('firma'), b.get('kredi'), b.get('uridyum'), b.get('seviye'), b.get('onur'),
                         b.get('lazer'), b.get('roket'), bool(b.get('ilerlemeli')), b.get('settings_source') or SAV.active(),
                         campaign=bool(b.get('kampanya')))
        if b.get('set_active', True):
            SAV.set_active(sid)
        log('yeni kayıt: %s' % sid)
        return {'id': sid}
    if path == '/api/kayitlar/aktif':
        return {'id': SAV.set_active(slot_arg(b))}
    if path == '/api/kayitlar/rename':
        return SAV.rename(slot_arg(b), b.get('ad'))
    if path == '/api/kayitlar/note':
        return SAV.set_note(slot_arg(b), b.get('not'))
    if path == '/api/kayitlar/copy':
        return {'id': SAV.duplicate(slot_arg(b), b.get('ad'))}
    if path == '/api/kayitlar/sil':
        return {'dosya': SAV.delete(slot_arg(b))}
    if path == '/api/kayitlar/geri_al':
        return {'id': SAV.undelete(b.get('dosya'))}
    if path == '/api/kayitlar/empty_trash':
        return {'deleted': SAV.purge(b.get('dosya'))}
    if path == '/api/kayitlar/disari':
        sid = slot_arg(b)
        name = '%s_%s.zip' % (sid, time.strftime('%Y%m%d'))
        dest = dialog('save', title=_('Export save'), initialfile=name, defaultextension='.zip',
                      filetypes=[(_('DarkOrbit save'), '*.zip')])
        if not dest:
            return {'cancelled': True}
        SAV.export(sid, dest, bool(b.get('with_backups', True)))
        return {'route': dest}
    if path == '/api/kayitlar/import':
        src = dialog('ac', title=_('Import save'), filetypes=[(_('DarkOrbit save'), '*.zip *.json'), (_('All files'), '*.*')])
        if not src:
            return {'cancelled': True}
        return {'id': SAV.import_file(src)}
    if path == '/api/kayitlar/edit':
        return {'changed': SAV.edit(slot_arg(b), b.get('values') or {})}
    # ---- karakter editörü (taslak: Kaydet profile yazar, Vazgeç atar)
    if path == '/api/editor/uygula':
        return SAV.editor_apply(slot_arg(b), b.get('ops'))
    if path == '/api/editor/kaydet':
        sid = slot_arg(b)
        log('karakter editörü: %s kaydedildi' % sid)
        return {'backup': SAV.editor_commit(sid)}
    if path == '/api/editor/discard':
        SAV.editor_discard(slot_arg(b))
        return {}
    # ---- yedekler
    if path == '/api/backups/al':
        return {'dosya': SAV.backup(slot_arg(b), 'manual', b.get('not') or '')}
    if path == '/api/backups/restore':
        return {'safety': SAV.restore(slot_arg(b), b.get('dosya'))}
    if path == '/api/backups/sil':
        SAV.delete_backup(slot_arg(b), b.get('dosya'))
        return {}
    if path == '/api/backups/note':
        SAV.set_backup_note(slot_arg(b), b.get('dosya'), b.get('not'))
        return {}
    if path == '/api/backups/new_save':
        return {'id': SAV.backup_as_new(slot_arg(b), b.get('dosya'), b.get('ad'))}
    # ---- istemci ve panel ayarları
    if path == '/api/panel_settings':
        CFG.update({k: v for k, v in (b.get('values') or {}).items() if k != 'active_save'})
        RP.wake_up.set()                               # Discord Rich Presence ayarı değiştiyse hemen
        return api_client()
    if path == '/api/istemci/select':
        start = client_folder() or ROOT
        p = dialog('folder', title=_('Choose the DarkOrbit game folder (the one with DarkOrbit.exe and DarkOrbit_Data)'), initialdir=start)
        if not p:
            return dict(api_client(), cancelled=True)
        p = os.path.normpath(p)
        c = IST.check(p)
        if not c['valid'] and os.path.basename(p).lower() == IST.DATA_DIR.lower() and IST.check(os.path.dirname(p))['valid']:
            p = os.path.dirname(p)                    # DarkOrbit_Data seçildiyse üst klasörü
            c = IST.check(p)
        if not c['valid']:
            sub = [x for x in IST.candidates() if os.path.normcase(x['route']).startswith(os.path.normcase(p))]
            if sub:
                p, c = sub[0]['route'], sub[0]
            else:
                raise Error(_('The chosen folder is not a DarkOrbit client: %s', ' '.join(c['issues'])))
        CFG.update({'client_folder': p})
        return api_client()
    if path == '/api/istemci/use':
        p = os.path.normpath(b.get('route') or '')
        if not IST.check(p)['valid']:
            raise Error(_('The folder is not a valid client.'))
        CFG.update({'client_folder': p})
        return api_client()
    if path == '/api/istemci/otomatik':
        CFG.update({'client_folder': None})
        return api_client()
    if path == '/api/guncelleme/check':
        UPD.check()
        STATE['next_check'] = time.time() + UPDATE_SEC
        return h_get('/api/guncelleme', {})
    if path == '/api/guncelleme/kur':
        if not idle(strict=True):
            raise Error(_('First close the game, the servers and running tasks.'))
        try:
            UPD.install_async()
        except UpdateError as e:
            raise Error(str(e))
        return h_get('/api/guncelleme', {})
    if path == '/api/istemci/indir':                # oyunu indir ve proje köküne aç (sürer, kaldığı yerden)
        if RUN.find(CFG)['tur'] == 'engine':          # macOS: oyunu açacak Wine da birlikte iner
            ENG.start()
        return DL.start(CFG.get('fast_download'))
    if path == '/api/istemci/update':             # eski istemci: yeni sürümü indir, eskisini sil; BepInEx yeni klasöre yeniden kurulur
        if MANAGER.client_alive() or IST.running_clients():
            raise Error(_('Close the game first'))
        old = client_folder()
        if not IST.check(old)['eski']:
            raise Error(_('The client is already up to date.'))
        new_ = next((c['route'] for c in IST.candidates() if c['compatible']), None)
        if new_:                                    # bilgisayarda zaten var
            CFG.update({'client_folder': new_})
            delete_old_client(old, new_)
            PATCHER.start(new_)
            return DL.state()
        STATE['old_client'] = old
        return DL.start(CFG.get('fast_download'))
    if path == '/api/motor/kur':
        return ENG.start()
    if path == '/api/yama/kur':
        return PATCHER.start(client_folder())
    if path == '/api/yama/durdur':
        PATCHER.cancel()
        return PATCHER.state(client_folder())
    if path == '/api/motor/durdur':
        return ENG.cancel()
    if path == '/api/rosetta/kur':                  # macOS'un yönetici penceresi açılır
        return ENG.install_rosetta()
    if path == '/api/istemci/download_stop':
        return DL.cancel()
    if path == '/api/istemci/download_delete':            # yarım indirmenin geçici klasörü
        try:
            return DL.discard()
        except DownloadError as e:
            raise Error(str(e))
    if path == '/api/protokol/uret':                # yeni istemciden protokol üret ve farkı raporla (etkin dosyalara dokunmaz)
        try:
            return ADAPTER.generate(os.path.normpath(b.get('route') or client_folder() or ''))
        except RuntimeError as e:
            raise Error(str(e))
    if path == '/api/protokol/uygula':              # üretilen sürümü etkin yap (oyun sunucusu yeniden başlatılınca)
        if MANAGER.running():
            raise Error(_('Stop the game server first: the protocol is loaded at startup.'))
        try:
            return ADAPTER.activate(b.get('surum'))
        except RuntimeError as e:
            raise Error(str(e))
    if path == '/api/gunluk/temizle':
        name = b.get('ad')
        if name not in LOGS and not EXTRA_LOG.fullmatch(str(name or '')):
            raise Error(_('Unknown log.'))
        try:
            open(os.path.join(PTH.LOGS, name), 'w').close()
        except OSError:
            raise Error(_('The log is open in a server right now; stop the server and try again.'))
        return {}
    if path == '/api/open_folder':
        what = b.get('ne')
        paths = {'project': ROOT, 'saves': PTH.SAVES, 'logs': PTH.LOGS, 'client': client_folder() or ROOT,
                 'sunucu': SERVER}
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
    if path == '/api/discord':                      # davet varsayılan tarayıcıda (panel penceresinin profili Discord'a girişli değil)
        import webbrowser
        webbrowser.open(DISCORD)
        return {}
    if path == '/api/donate':                        # destek sayfası varsayılan tarayıcıda (Buy Me a Coffee)
        import webbrowser
        webbrowser.open(DONATE_URL)
        return {}
    if path == '/api/kisayol':
        return {'route': create_shortcut()}
    if path == '/api/kapat':
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
        except (ConnectionError, OSError):          # pencere yenilendi / kapandı: yanıtı bekleyen yok
            pass

    def _host_ok(self):
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost')

    def _api(self, fn, arg):
        if self.headers.get('X-Panel-Belirteci') != TOKEN:
            return self._send(403, {'hata': _('Invalid token: reopen the panel.')})
        try:
            out = fn(urlparse(self.path).path, arg)
        except (Error, SaveError, FriendError, MultiClientError, RuntimeError, ValueError) as e:
            return self._send(400, {'hata': str(e)})
        except Exception as e:
            log('API hatası %s: %s' % (self.path, traceback.format_exc()))
            return self._send(500, {'hata': _('Unexpected error: %r', e)})
        return self._send(200, out)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {'hata': 'host'})
        u = urlparse(self.path)
        if u.path == '/api/ping':
            return self._send(200, {'panel': 'darkorbit', 'surum': VERSION, 'pid': os.getpid()})
        if u.path.startswith('/api/'):
            return self._api(h_get, {k: v[0] for k, v in parse_qs(u.query).items()})
        if u.path.startswith('/game_images/'):
            p = game_image(u.path[len('/game_images/'):])
            if not p:
                return self._send(404, b'none', 'text/plain')
            if p.endswith('.png'):                  # atlas sayfaları büyük, değişmez; dizin ve adlar yeniden dökümde değişir: önbelleksiz
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
            return self._send(403, {'hata': 'host'})
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        if u.path == '/api/goster':                  # ikinci başlatma: pencereyi yeniden aç
            threading.Thread(target=open_window, args=('http://127.0.0.1:%d/' % PORT,), daemon=True).start()
            return self._send(200, {})
        if u.path == '/api/kapandi':                 # sayfa kapanıyor (sendBeacon): pencere izlenmiyorsa nabız erken düşsün
            if not STATE['window_watched']:
                STATE['heartbeat'] = time.monotonic() - HEARTBEAT_SEC + 8
            return self._send(200, {})
        try:
            body = json.loads(raw.decode('utf8') or '{}')
        except ValueError:
            return self._send(400, {'hata': _('Not JSON')})
        return self._api(h_post, body if isinstance(body, dict) else {})


class Server(ThreadingHTTPServer):
    # HTTPServer SO_REUSEADDR açıyor; Windows'ta bu, dinlenen porta ikinci bir süreci de bağlatıyor: ikinci başlatma açık paneli
    # görmeden aynı portta ikinci bir panel açıyordu (canlı tur 2). Kapalıyken bağlanamaz, açık panelin penceresini açtırır (main).
    # macOS ve Linux'ta SO_REUSEADDR ikinci dinleyiciyi yine reddeder ama o olmadan açık pencerenin isteklerinden kalan TIME_WAIT
    # bağlantıları portu yarım dakika tutuyor: güncellemeden sonra yeni panel portu alamayıp başka bir porta açılıyordu (pencere onu
    # bulamaz)
    allow_reuse_address = os.name != 'nt'


def main():
    global PORT
    PORT = next((int(a.split('=', 1)[1]) for a in sys.argv if a.startswith('--port=') and a.split('=', 1)[1].isdigit()), PORT)
    srv = None
    if STATE['updated']:                          # güncellemeden sonra: eski süreç portu bırakana dek bekle
        for _k in range(75):
            try:
                srv = Server(('127.0.0.1', PORT), Handler)
                break
            except OSError:
                time.sleep(0.2)
    try:
        srv = srv or Server(('127.0.0.1', PORT), Handler)
    except OSError:
        try:                                          # panel zaten açık mı?
            with urlopen('http://127.0.0.1:%d/api/ping' % PORT, timeout=2) as r:
                if json.load(r).get('panel') == 'darkorbit':
                    urlopen(Request('http://127.0.0.1:%d/api/goster' % PORT, data=b'{}', method='POST'), timeout=5).read()
                    return
        except Exception:
            pass
        srv = Server(('127.0.0.1', 0), Handler)       # port başka programda: boş bir port
        PORT = srv.server_address[1]
    srv.daemon_threads = True
    STATE['srv'] = srv
    log('panel açıldı: http://127.0.0.1:%d/ (python %s)%s' % (PORT, sys.version.split()[0], ' (güncellemeden sonra)' if STATE['updated'] else ''))
    try_migrate()
    try:
        SM.migrate_client(client_folder(), log)         # eski sürümün istemci klasöründeki dosyaları
    except OSError as e:
        log('istemci klasörü taşınamadı: %s' % e)
    threading.Thread(target=refresh_shortcut, daemon=True).start()
    if not CFG.get('active_save') and SAV.slots():
        CFG.update({'active_save': SAV.slots()[0]})
    threading.Thread(target=ticker, daemon=True).start()
    RP.launch()
    if not {'--no-window', '--pencere-yok'} & set(sys.argv):     # eski adlar: 2026-11-01'den önceki güncelleyici bunlarla yeniden başlatır
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
        log('panel başlatılamadı: %s' % traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, _('The panel could not start. Details: server\\logs\\panel.log\n\n%s',
                                                  traceback.format_exc()[-900:]), 'OpenOrbit Panel', 0x10)
        except Exception:
            pass
        raise
