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
TEMPLATES = os.path.join(PTH.SAVE, 'ayar_sablonlari.json')
BROWSER_PROFILE = os.path.join(os.environ.get('LOCALAPPDATA') or PTH.SAVE, 'DarkOrbitPanel', 'tarayici')
LOGS = ('gs.log', 'http.log', 'client.log', 'oyun_konsol.log', 'web_konsol.log', 'panel.log', 'errors.log', 'unknown.log') + (
    () if os.name == 'nt' else ('wine.log',))      # Linux ve macOS: Wine'ın / Proton'un çıktısı (surecler.istemci_ac)
EXTRA_LOG = re.compile(r'client_[a-z0-9_]{1,40}\.log')          # çoklu istemcinin ek istemcilerinin günlükleri (coklu.py)
HEARTBEAT_SEC = 180                      # tarayıcı penceresi izlenemiyorsa: bu kadar istek gelmezse pencere kapandı sayılır (monotonic:
                                    # macOS ve Linux'ta uykuda geçen süre sayılmaz)
HANDOVER_SEC = 10                       # tarayıcı süreci bundan önce çıkarsa pencereyi açık bir sürece devretmiştir (watch_window)
UPDATE_SEC = 6 * 3600            # GitHub'da yeni sürüm denetimi aralığı (başarısızsa bir saat sonra yeniden)
EVENT_DESCRIPTIONS = {
    'yukseltme_saati': "Assembly'de ekipman yükseltmesi %25 daha az uridyum.",
    'dispatch_gunu': 'Dispatch gönderimlerinin etkinlik günü.',
    'kapi_hafta_sonu': 'Galaksi Kapısı enerjisi %15 indirimli.',
    'kronos_gunu': 'Kronos kapısının parçası iki kat gelir.',
    'altin_kutu': "Haritalarda Altın Booty Box'lar çıkar.",
    'halloween': "X-2..X-8'de Curcubitor'lar ve Boss Curcubitor, Candy Corn kutuları, balkabakları, Trial of Terrors kapısı "
                 "(X-4; karanlık haritalar), Battle Pass.",
    'agatus': "Spinel'ler ve Agatus; etkinlik paraları ve Assembly tarifleri.",
    'hitac': "Underling'ler ve Underboss; Hitac ana gemisi haritadan haritaya dolaşır.",
    'immortal_union': 'Lanatum, Styxus ve Charopos; etkinlik paraları.',
    'protegit': "Chaos Protegit'ler; etkinlik paraları.",
    'kis': "Ice Meteoroid'ler, hediye kutuları ve Santa.",
    'thanksgiving': 'Thanksgiving Box ve Roast Turkey Cargo Box.',
    'thanksgiving_buz': "Ice Meteoroid'ler ve Super Ice Meteoroid (Şükran Günü'nden 3 gün önce - 5 Aralık).",
    'sukran_gg_cift': "Şükran Günü'nden pazartesiye Galaksi Kapısı çift ödülü (Pazar kuralının yanında).",
    'kardan_adam': 'Yeni yıl Snowman penceresi (WIZ-X).',
    'plutus': 'Gauntlet of Plutus kapısı (Easy X-1, Normal X-8; günde bir).',
    'labirent': "Frozen Labyrinth: X-1'den 16 haritalık labirent, Labyrinth Key'ler ve Synk.",
    'galactic_strife': 'Battle Pass (görevler uzaylılarla) ve anahtar değişiminde Arios ve Neikos tasarımları.',
    'dogum_gunu': 'Birthday Gate (X-1).',
    'empyrian': 'Empyrian kutuları; anahtarlar Galaksi Kapısı ödülünden.',
    'prosperous': 'Prosperous kutuları; anahtarlar Galaksi Kapısı ödülünden.',
    'bahar': 'Bahar yumurtaları ve kutuları.',
    'chaos_omen': 'Chaos Omen harita etkinliği (Protegit Pandemonium öncesi).',
    'gg_cift_odul': 'Galaksi Kapılarının EP, onur, Xenomit, log diski, kupon ve Assembly kaynağı ödülleri ile şanslı ödül '
                    'olasılığı iki kat (Dispatch hariç).',
    'lf4_gunu': 'Delta, Epsilon, Lambda ve Kuiper kapılarından LF-4 ya da 10.000 UCB-100 şansı.',
    'lf4_gelismis': "Delta'dan LF-4-HP, Kappa'dan LF-4-PD, Zeta'dan LF-4-MD şansı.",
    'gg_hafta_sonu_1': ('Delta, Epsilon, Kuiper ve Lambda kapılarından tasarım ve lazer paketi şansı; Zeta ve Kappa '
                        "kapılarından etkinlik tasarımı şansı."),
    'gg_hafta_sonu_3': ('Delta, Epsilon, Kuiper ve Lambda kapılarından tasarım ve lazer paketi şansı; Zeta ve Kappa '
                        "kapılarından etkinlik tasarımı şansı."),
    'gg_hafta_sonu_4': ('Delta, Epsilon, Kuiper ve Lambda kapılarından tasarım ve lazer paketi şansı; Zeta ve Kappa '
                        "kapılarından etkinlik tasarımı şansı."),
    'nova_hafta_sonu': 'Delta, Epsilon, Lambda ve Kuiper kapıları N.E.U. verir.',
    'obsidian_booty': "Haritalarda Obsidian Booty Box'lar çıkar.",
    'rb_booty': "Haritalarda kırmızı ve mavi Booty Box'lar çıkar.",
    'apocalypse_booty': "Haritalarda Apocalypse Booty Box'lar çıkar.",
    'fever': 'Listedeki gemilere güçlenme; yalnız Gauntlet of Plutus, Mimesis Mutiny, Protegit sürerken ve Black Light Fever haftalarında.',
    'fever_black_light': 'Black Light Fever haftaları: Fever yalnız BL haritalarında.',
    'astral_ascension': 'Battle Pass (2022 koşusu) ve anahtar değişimi.',
    'spacecup': 'Battle Pass (2022 koşusu; Spaceball ve PvP yok) ve anahtar değişimi.',
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
STATE = {'oyna': {'calisiyor': False, 'adimlar': [], 'hata': None, 'bitti': None, 'sadece_sunucu': False},
         'nabiz': time.monotonic(), 'pencere_kapandi': False, 'pencere_izleniyor': False, 'son_yedek': 0.0, 'kapaniyor': False,
         'sonraki_denetim': time.time() + 8, 'guncellendi': '--guncellendi' in sys.argv, 'srv': None, 'acilis': time.time()}


def rp_source():
    """Discord Rich Presence'ın kaynağı (discord_rp.py) -> (canlı durum ya da None, panelin durumu)."""
    live = read_json(os.path.join(PTH.LOGS, 'canli_durum.json'), None) if MANAGER.running() else None
    if live and time.time() - live.get('zaman', 0) > 15:
        live = None
    if MANAGER.client_alive():
        return live, 'oyunda' if live and live.get('bagli') else 'arkadas' if FRD.m['durum'] == 'oyunda' else 'giris'
    return None, 'baslatiliyor' if STATE['oyna']['calisiyor'] else 'panel'


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
    choice = CFG.get('arkadas_dunya') if friend else None
    if choice and WLD.var(choice):
        return choice
    return SAV.meta(slot).get('dunya') if slot else None


def world_file(slot, friend=False):
    """Sunucunun dünya dosyası (Dünya Editörü; DO_DUNYA) ya da None (standart dünya, silinmiş dünya)."""
    return WLD.file_path(world_id(slot, friend))


def bot_file(slot, friend=False):
    """Sunucunun bot paketi (Botlar sayfası; DO_BOT): kaydın dünyasına atanmış paket ya da None."""
    return BT.file_path(BT.world_pack(world_id(slot, friend) or WLD.STANDARD))


def world_info(wid):
    """Oyna sayfasının dünya çipi: {id, ad, kapak, degisiklik}; silinmiş dünya standart sayılır."""
    try:
        w = WLD.summary(wid if wid and WLD.var(wid) else WLD.STANDARD)
    except WLD.WorldError:
        w = WLD.summary(WLD.STANDARD)
    return {'id': w['id'], 'ad': w['ad'], 'kapak': w['kapak'], 'degisiklik': 0 if w['standart'] else w['degisiklik'], 'standart': w['standart']}


def world_users():
    """Dünya -> onu varsayılan yapan kayıtlar [{id, ad, pilot}]."""
    out = {}
    for k in SAV.list():
        w = k.get('dunya') if k.get('dunya') and WLD.var(k.get('dunya')) else WLD.STANDARD
        out.setdefault(w, []).append({'id': k['id'], 'ad': k.get('ad'), 'pilot': k.get('pilot')})
    return out


def settings_file(slot=None):
    """Oyun ayarlarının dosyası: kaydın kendi ayarları (etkin kayıt; kayıt yoksa eski ortak dosya)."""
    slot = slot or SAV.active()
    return SAV.settings(slot) if slot else PTH.SETTINGS


def game_settings():
    return SET.read(settings_file())


def client_folder():
    return IST.resolve(CFG.get('istemci_klasoru'))


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
        raise Error(_('Oyun açık değil.'))
    req = Request('http://127.0.0.1:%d%s' % (k['port'], route), data=None if body is None else json.dumps(body).encode('utf8'),
                  headers={'X-Anahtar': k['anahtar'], 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=10) as r:
            return json.load(r)
    except HTTPError as e:
        if e.code == 409:
            raise Error(_('Oyuna giriş yapınca açılır.'))
        raise Error(_('Oyun sunucusu isteği reddetti (%s).', e.code))
    except OSError:
        raise Error(_('Oyun sunucusuna bağlanılamadı.'))


def game_image(name):
    """Eklentinin döktüğü atlas sayfası, dizin ya da ad dosyası -> yol (yoksa None)."""
    if not re.fullmatch(r'[\w.-]+\.(png|json)', name) or not client_folder():
        return None
    p = os.path.join(client_folder(), 'BepInEx', 'openorbit', 'gorsel', name)      # eklentinin döktüğü klasör (P4'te adı eklentiyle birlikte değişir)
    return p if os.path.isfile(p) else None


def _downloaded(path):
    """İndirme bitti: kullanılan istemci geçersizse ya da güncelleniyorsa yeni klasör kullanılsın (kendiliğinden bulunuyorsa ayar boş
    kalır); güncellemede eski klasör silinir."""
    old = STATE.pop('istemci_eski', None)
    if old or not IST.check(client_folder())['gecerli']:
        auto = IST.resolve(None)
        same = auto and os.path.normcase(os.path.normpath(auto)) == os.path.normcase(os.path.normpath(path))
        CFG.update({'istemci_klasoru': None if same else path})
    if old:
        delete_old_client(old, path)
    PATCHER.start(path)                                   # istemcinin düzeltmeleri için BepInEx (istemci_yama.py)


def delete_old_client(old, new_):
    """İstemci güncellemesi: eski sürümün klasörünü sil. Yalnız arşivden açılmış DarkOrbit_Version… klasörü: resmî kurulumu kendi
    başlatıcısı günceller, ona dokunulmaz."""
    if (os.path.normcase(os.path.normpath(old)) == os.path.normcase(os.path.normpath(new_))
            or not re.match(r'DarkOrbit_Version\d', os.path.basename(os.path.normpath(old))) or not IST.check(old)['gecerli']):
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
    return int(100 * st['alinan'] / st['toplam']) if st['toplam'] else 0


_dialog_lock = threading.Lock()


def dialog(kind, **kw):
    """Yerel dosya/klasör penceresi (tkinter; panelin önünde açılır) -> seçilen yol ya da ''. macOS'ta AppleScript, Linux'ta tkinter
    yoksa zenity."""
    with _dialog_lock:
        if sys.platform == 'darwin':
            q = lambda s: '"%s"' % str(s).replace('\\', '\\\\').replace('"', '\\"')
            ask = '%s with prompt %s' % ({'klasor': 'choose folder', 'ac': 'choose file', 'kaydet': 'choose file name'}[kind],
                                         q(kw.get('title', '')))
            if kind == 'kaydet' and kw.get('initialfile'):
                ask += ' default name ' + q(kw['initialfile'])
            if kw.get('initialdir') and os.path.isdir(kw['initialdir']):
                ask += ' default location POSIX file ' + q(kw['initialdir'])
            return subprocess.run(['osascript', '-e', 'POSIX path of (%s)' % ask], capture_output=True, text=True).stdout.strip()
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            if os.name == 'nt' or not shutil.which('zenity'):
                raise Error(_('Dosya penceresi için tkinter gerekir (Debian/Ubuntu: sudo apt install python3-tk).'))
            a = ['zenity', '--file-selection', '--title=%s' % kw.get('title', '')]
            a += {'klasor': ['--directory'], 'ac': [], 'kaydet': ['--save']}[kind]
            if kw.get('initialfile') or kw.get('initialdir'):
                a.append('--filename=%s' % os.path.join(kw.get('initialdir') or '', kw.get('initialfile') or ''))
            return subprocess.run(a, capture_output=True, text=True).stdout.strip()
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        try:
            fn = {'klasor': filedialog.askdirectory, 'ac': filedialog.askopenfilename, 'kaydet': filedialog.asksaveasfilename}[kind]
            return fn(parent=root, **kw) or ''
        finally:
            root.destroy()


def open_folder(path):
    if not os.path.exists(path):
        raise Error(_('Klasör yok: %s', path))
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
    sel = game_settings().get('etkinlikler') or {}
    out = []
    for key, e in CAL.EVENTS.items():
        yearly = 'donemler' in e
        if yearly:                                      # önümüzdeki yılın dönemleri (takvim.upcoming; bitiş günü dahil)
            spans = CAL.upcoming(key, now)
            when = ', '.join(_period_text(a, b - datetime.timedelta(days=1), lang) for a, b in spans[:4]) + (
                ' …' if len(spans) > 4 else '') or _('Takvimde yeni dönemi yok')
        else:
            days = e.get('gunler', range(7))
            when = (_('Her gün') if len(list(days)) == 7 else ', '.join(DAYS[lang][d] for d in days))
            hrs = e.get('saatler')
            if hrs:
                when += ' ' + ', '.join('%02d:00–%02d:00' % (a, b) for a, b in hrs)
            if e.get('ay_haftasi'):
                when += ' ' + _('(ayın %s. haftası)', '/'.join(map(str, e['ay_haftasi'])))
            if e.get('hafta_dongu'):
                when += ' ' + _('(%s haftada bir)', e['hafta_dongu'][0])
        per = CAL.period(key, now)
        nxt = None
        if yearly and not per:
            best = next((s for s, f in spans if s > t), None)
            nxt = (best - t).days + 1 if best else None
        st = sel.get(key)
        out.append({'anahtar': key, 'ad': _(e.get('ad', key)), 'tur': 'yillik' if yearly else 'haftalik', 'zaman': when,
                    'takvimde': per is not None, 'kalan_sn': int(per[1] - now) if per else None, 'sonraki_gun': nxt,
                    'durum': st, 'etkin': (st == 'acik') if st else per is not None,
                    'aciklama': _(EVENT_DESCRIPTIONS.get(key, '')),
                    'cakisan': sorted(_(CAL.EVENTS[j].get('ad', j)) for j in CAL.CONFLICTS[key])})
    # çakışma (takvim.resolve): aynı anda açık çakışanlardan elle açılan, yoksa önce başlayan kalır
    rows = {x['anahtar']: x for x in out}
    on = {k for k, x in rows.items() if x['etkin']}
    keep = CAL.resolve(on, lambda k: (rows[k]['durum'] != 'acik', (CAL.period(k, now) or (0,))[0], k))
    for k in on - keep:
        rows[k]['etkin'] = False
        rows[k]['bastiran'] = next(rows[j]['ad'] for j in sorted(keep, key=lambda j: rows[j]['ad']) if j in CAL.CONFLICTS[k])
    out.sort(key=lambda x: (x['tur'] != 'yillik', not x['etkin'], x['ad'].lower()))
    return out


SESSION_NAMES = {'vortex': 'Vortex seansı', 'dunya_patronu': 'Patron savaşı', 'kristallon': 'Apotheosis penceresi',
                'mimesis': 'Mimesis seferi', 'unvan_avi': 'Prestige unvanı avı', 'uzayli': 'Etkinlik uzaylıları',
                'kutu': 'Etkinlik kutuları', 'harita': 'Harita etkinliği'}


def api_calendar(q):
    """Etkinlik takvimi (event_schedule.py): [bas, bit) içindeki takvim ve etkin aralıklar, seanslar, şimdiki ya da sonraki dönem."""
    import event_schedule as CC
    now = time.time()
    try:
        a, b = float(q.get('bas')), float(q.get('bit'))
    except (TypeError, ValueError):
        raise Error(_('Geçersiz tarih aralığı.'))
    if not 0 < b - a <= 62 * 86400:
        raise Error(_('Geçersiz tarih aralığı.'))
    hep = bool(game_settings().get('seans_hep_acik'))
    evs = event_list()
    c = CC.schedule(a, b, hep, {e['anahtar']: e['durum'] for e in evs})
    out = []
    for e in evs:
        x = c[e['anahtar']]
        session = [dict(s, ad=_(SESSION_NAMES[s['kimlik'] if s['tur'] == 'seans' else s['tur']])) for s in x['seanslar']]
        out.append(dict(e, araliklar=x['araliklar'], etkin_araliklar=x['etkin'], seanslar=session,
                        sonraki=CC.next_(e['anahtar'], now, 400 if e['tur'] == 'yillik' else 70)))
    return {'simdi': now, 'bas': a, 'bit': b, 'hep_acik': hep, 'etkinlikler': out}


def settings_summary(values):
    """Varsayılandan farklı oyun ayarları [{'ad', 'deger'}] (Oyna sayfasının çipleri; ayar.summary'nin panel dilindeki hâli)."""
    d = SET.clean(values)
    out = []
    for s in SET.SCHEMA:
        v = d.get(s['anahtar'], s['varsayilan'])
        if v == s['varsayilan']:
            continue
        if s['tur'] == 'carpan':
            text = 'x%g' % v
        elif s['tur'] == 'bool':
            text = _('açık') if v else _('kapalı')
        elif s['tur'] == 'sayi':
            text = ('%d %s' % (v, _(s['birim']) if s.get('birim') else '')).strip()
        else:
            text = _(s['secenekler'][v])
        out.append({'ad': SET.full_name(s, _), 'deger': text})
    return out


def set_events(body):
    vals = game_settings()
    ev = dict(vals.get('etkinlikler') or {})
    import event_calendar as CAL
    if 'hepsi' in body:
        to = body['hepsi']
        for k, e in CAL.EVENTS.items():
            if body.get('tur') and body['tur'] != ('yillik' if 'donemler' in e else 'haftalik'):
                continue
            if to in SET.EVENT_STATES:
                ev[k] = to
            else:
                ev.pop(k, None)
    for k, v in (body.get('degisiklik') or {}).items():
        if k not in CAL.EVENTS:
            continue
        if v in SET.EVENT_STATES:
            ev[k] = v
        else:
            ev.pop(k, None)
        if v == 'acik':                             # çakışan elle açıklar takvime döner (takvim.CONFLICTS)
            for j in CAL.CONFLICTS[k]:
                if ev.get(j) == 'acik':
                    ev.pop(j)
    vals['etkinlikler'] = ev
    SET.write(settings_file(), vals)
    return event_list()


# ------------------------------------------------------------------ uyarılar ve durum
def try_migrate():
    """Eski tek kayıt (save/profil.json) varsa yuvaya taşı; portlar açıksa (o profille açılmış bir sunucu olabilir) sonraya."""
    if not os.path.isfile(PTH.LEGACY_PROFILE) or MANAGER.running():
        return None
    table = PR.listeners()
    if any(PR.listening(p, table) for p in (8081, 8090)):
        if not STATE.get('tasima_bekliyor'):
            log('eski kayıt taşınmadı: oyun portları açık (Baslat.bat ile açılmış bir sunucu kullanıyor olabilir)')
        STATE['tasima_bekliyor'] = True
        return None
    STATE['tasima_bekliyor'] = False
    moved = SAV.migrate()
    if moved:
        log('eski kayıt (save/profil.json) yuvaya taşındı: %s' % moved)
    return moved


def warnings(folder=False):
    out = []
    if STATE.get('tasima_bekliyor'):
        out.append({'tur': 'uyari', 'metin': _('Eski kaydın (server/save/profil.json) kayıt yuvasına taşınması bekliyor: önce dışarıda açık '
                                               'olan sunucuyu kapatın (Sunucu > Portlar).'), 'sayfa': 'sunucu'})
    if FRD.active():
        out.append({'tur': 'uyari', 'metin': _('Arkadaşının sunucusundasın (%s): Oyna kapalı. Ayrılmak için Arkadaşlarınla Oyna sayfası.',
                                               FRD.m['adres']), 'sayfa': 'arkadas'})
    slot = SAV.active()
    if not slot:
        out.append({'tur': 'hata', 'metin': _('Henüz kayıt yok: Kayıtlar sayfasından yeni bir kayıt oluşturun.'), 'sayfa': 'kayitlar'})
    c = IST.check(client_folder() if folder is False else folder)
    if not c['gecerli'] and DL.running():
        out.append({'tur': 'uyari', 'metin': _('Oyun istemcisi indiriliyor: %%%d. Bitince oynayabilirsin.', _dl_pct(DL.state())),
                    'sayfa': 'istemci'})
    elif not c['gecerli']:
        out.append({'tur': 'hata', 'metin': _('Oyun istemcisi bulunamadı: %s İstemci sayfasından klasörü seçin ya da oyunu indirin.',
                                              ' '.join(c['sorunlar'])), 'sayfa': 'istemci'})
    elif c['eski']:                                                  # yeni sürüm çıktı: tek tıkla güncellenir (/api/istemci/guncelle)
        dl, sup = DL.state(), IST.supported()
        run = bool(STATE.get('istemci_eski')) and dl['calisiyor']
        text = (_('Oyun %s sürümüne güncelleniyor: %%%d. Bitince eski sürüm silinir ve BepInEx yeniden kurulur.', sup, _dl_pct(dl))
                 if run else _('DarkOrbit %s sürümü çıktı, istemcin %s: güncellemezsen oyun düzgün çalışmaz. Güncelle yenisini indirip '
                               'kurar, eskisini siler.', sup, c['surum']))
        if STATE.get('istemci_eski') and dl['durum'] == 'hata':
            text += ' ' + dl['hata']
        out.append({'tur': 'hata', 'metin': text, 'ilerleme': _dl_pct(dl) if run else None, 'indirme': dl if run else None,
                    'sayfa': 'istemci',
                    'eylem': {'metin': _('Güncelle'), 'api': '/api/istemci/guncelle', 'calisiyor': run,
                              'calisiyor_metin': _('Güncelleniyor…')}})
    elif not c['uyumlu']:
        out.append({'tur': 'uyari', 'metin': c['sorunlar'][-1], 'sayfa': 'istemci'})
    error = RUN.find(CFG)['hata']                                      # Linux ve macOS: Wine ya da Proton (Apple Silicon'da Rosetta)
    if error:
        w = {'tur': 'hata', 'metin': error, 'sayfa': 'istemci'}
        if RUN.rosetta_error():
            ros = ENG.state()['rosetta']
            w['eylem'] = {'metin': _("Rosetta'yı kur"), 'api': '/api/rosetta/kur', 'calisiyor': ros['durum'] == 'kuruluyor'}
            if ros['hata']:
                w['metin'] += ' ' + ros['hata']
        out.append(w)
    m = ENG.state() if sys.platform == 'darwin' else None
    if m and m['calisiyor']:
        out.append({'tur': 'uyari', 'metin': _('Wine ve DXMT indiriliyor: %%%d. Bitince oynayabilirsin.',
                                               int(100 * m['alinan'] / m['toplam']) if m['toplam'] else 0), 'sayfa': 'istemci'})
    elif m and m['durum'] == 'hata':
        out.append({'tur': 'hata', 'metin': _("Panelin Wine'ı kurulamadı: %s", m['hata']), 'sayfa': 'istemci'})
    error = PR.port_80_problem()
    if error:
        out.append({'tur': 'hata', 'metin': error, 'sayfa': 'sunucu'})
    missing = [n for n in PTH.TEMPLATES if not PTH.template(n)]       # kendi kaydın ya da paylaşılabilir kopya (data/defaults)
    if missing:
        out.append({'tur': 'uyari', 'metin': _('Giriş şablonları eksik (%s): oyun en küçük girişle açılır, bazı pencereler ve mağaza '
                                               'boş kalabilir.', ', '.join(missing)), 'sayfa': 'sunucu'})
    u = UPD.state()
    if u['durum'] in ('indiriliyor', 'kuruluyor'):
        out.append({'tur': 'uyari', 'metin': _('Panel güncelleniyor; bitince kendiliğinden yeniden başlar.'), 'sayfa': 'panel'})
    elif u['durum'] == 'var' and CFG.get('guncelleme') != 'kapali':
        auto = CFG.get('guncelleme') == 'otomatik' and CFG.get('kurulum_tamam')
        out.append({'tur': 'uyari', 'metin': _('Yeni sürüm var (%s): oyun ve sunucular kapanınca kendiliğinden kurulur.', u['son']['surum'][:7])
                    if auto else _('Yeni sürüm var (%s): Panel sayfasından kurabilirsin.', u['son']['surum'][:7]), 'sayfa': 'panel'})
    elif u['durum'] == 'kuruldu':
        out.append({'tur': 'uyari', 'metin': _('Güncelleme kuruldu: oyun ve sunucular kapanınca panel yeniden başlar.'), 'sayfa': 'panel'})
    alive = MANAGER.servers_alive()
    table = PR.listeners()
    foreign = [p for name, ports in PR.PORTS.items() for p in ports if not alive.get(name) and PR.listening(p, table)]
    if foreign:
        out.append({'tur': 'uyari', 'metin': _('Panelin açmadığı bir süreç oyun portlarını tutuyor (%s). Önceki oturumdan kalan bir '
                                               'sunucu olabilir: Sunucu sayfasından inceleyin.', ', '.join(map(str, foreign))),
                    'sayfa': 'sunucu'})
    for name, s in MANAGER.servers.items():
        if s.crashed:
            out.append({'tur': 'hata', 'metin': _('%s sunucusu beklenmedik biçimde kapandı (çıkış kodu %s). Ayrıntı: Sunucu > Günlükler > '
                                                  '%s_konsol.log', _({'oyun': 'Oyun', 'web': 'Web'}[name]), s.proc.poll(), name),
                        'sayfa': 'sunucu'})
    return out


def status():
    STATE['nabiz'] = time.monotonic()
    STATE['pencere_kapandi'] = False                  # bir pencere yine soruyor (ikinci başlatmanın açtığı da)
    if STATE.get('tasima_bekliyor'):
        try_migrate()
    slot = SAV.active()
    try:
        active = SAV.summary(slot) if slot else None
    except (OSError, SaveError):
        active = None
    if active:
        active['dunya_bilgi'] = world_info(active.get('dunya'))
    vals = game_settings()
    ev = [e['ad'] for e in event_list() if e['etkin'] and e['tur'] == 'yillik']
    slots = SAV.slots()
    folder = client_folder()                     # istemci klasörü araması (glob) bir kez: uyarılar ve yanıt
    return {'surecler': MANAGER.status(), 'aktif': active, 'kayit_sayisi': len(slots),
            'ayar_ozet': settings_summary(vals), 'etkinlikler': ev,
            'uyarilar': warnings(folder), 'oyna': STATE['oyna'], 'istemci_klasoru': folder,
            'arkadas': {'host': MANAGER.running() and MANAGER.friend, 'misafir': FRD.m['durum'], 'adres': FRD.m['adres']},
            'coklu': multi_status(slots),
            'panel': {'surum': VERSION, 'pencere_kapandi': STATE['pencere_kapandi'], 'dil': CFG.get('dil'), 'platform': sys.platform,
                      'kurulum_tamam': CFG.get('kurulum_tamam'), 'guncellendi': STATE['guncellendi'],
                      'acik_sn': int(time.time() - STATE['acilis'])}}


# ------------------------------------------------------------------ çoklu istemci (coklu.py)
def multi_env():
    """Çoklu istemcinin oyun sunucusu ayarları (DO_COK_OYUNCULU; cok_oyunculu.configure): yalnız bu bilgisayar, misafir yok."""
    return json.dumps({'adres': '127.0.0.1', 'misafir': False, 'anahtar': FRD.key, 'kod': VERSION, 'yerel': FRD.local})


def multi_wanted(slot):
    """OYNA sunucuyu çok oturumlu açsın mı: ayar açık ve en az iki kayıt var (tek kaydı olanın sunucusu tek oyunculu kalır), ya da
    sunucu bu kayıtla zaten öyle açık."""
    return bool(CFG.get('coklu_istemci') and len(SAV.slots()) > 1) or (MANAGER.running() and MANAGER.multi and MANAGER.slot == slot)


def multi_status(slots):
    """Oyna sayfasının Çoklu istemci kartı: açık ek istemciler, son kapanışlar ve ek istemcide açılabilecek kayıtlar."""
    live = read_json(os.path.join(PTH.LOGS, 'canli_durum.json'), None) if MULTI.live() else None
    out = dict(MULTI.state(live), ayar=CFG.get('coklu_istemci'), en_cok=CFG.get('coklu_en_cok'), kayit_sayisi=len(slots),
               sunucu=MANAGER.running() and (MANAGER.multi or MANAGER.friend), ana=MANAGER.slot if MANAGER.running() else None, kayitlar=[])
    if out['ayar'] and len(slots) > 1:
        for s in slots:
            try:
                k = SAV.summary(s)
            except (OSError, SaveError):
                continue
            out['kayitlar'].append({'id': s, 'ad': k['ad'], 'pilot': k.get('pilot'), 'seviye': k.get('seviye'), 'firma': k.get('firma'),
                                    'bozuk': k.get('bozuk'), 'ek': MULTI.in_use(s), 'arkadas': FRD.in_use(s)})
    return out


def open_extra(b):
    """Çoklu istemci: başka bir kayıtla ek istemci. Sunucu çok oturumlu açık olmalı; tek oyunculu açıksa ve oyun kapalıysa öyle
    yeniden başlatılır."""
    slot = str(b.get('kayit') or '')
    if not slot or not SAV.exists(slot):
        raise Error(_('Kayıt bulunamadı.'))
    if not CFG.get('coklu_istemci'):
        raise Error(_('Çoklu istemci kapalı: İstemci sayfasından açabilirsin.'))
    if FRD.active():
        raise Error(_('Arkadaşının sunucusundayken ek istemci açılamaz.'))
    if STATE['oyna']['calisiyor']:
        raise Error(_('Başlatma sürüyor.'))
    if not MANAGER.running():
        raise Error(_('Önce OYNA ile oyunu (ya da yalnız sunucuyu) başlat: ek istemciler aynı sunucuya bağlanır.'))
    if FRD.in_use(slot):
        raise Error(_('Bu kayıt arkadaşının sunucusunda kullanılıyor.'))
    if not (MANAGER.multi or MANAGER.friend):
        if MANAGER.client_alive() or MULTI.live():
            raise Error(_('Sunucu tek oyunculu açıldı: ek istemci için oyunu kapatıp yeniden OYNA\'ya bas.'))
        log('çoklu istemci: sunucu çok oturumlu yeniden başlatılıyor')
        MANAGER.start_servers(SAV.profile(MANAGER.slot), settings_file(MANAGER.slot), control=bool(SET.read(settings_file(MANAGER.slot)).get('kontrol')), slot=MANAGER.slot,
                          multi=multi_env(), world=world_file(MANAGER.slot), bot=bot_file(MANAGER.slot))
    return MULTI.open_(slot, client_folder(), MANAGER.slot)


def clients_closed():
    """Ana istemci ya da bir ek istemci kapandı: hepsi kapandıysa panelin davranışı (sunucuları kapat, pencere kapandıysa çık). Ana
    istemci bu sunucu oturumunda açılmadıysa (yalnız sunucu) ya da erken kapandıysa sunucular açık kalır."""
    if MANAGER.client_alive() or MULTI.live():
        return                                        # bir istemci sürüyor: sunucular açık kalır
    game, last = MANAGER.servers.get('oyun'), MANAGER.last_client
    if not (game and game.alive and MANAGER.client_started and MANAGER.client_started >= game.start and last and not last['erken']):
        return
    if CFG.get('istemci_kapaninca') == 'kapat':
        MANAGER.stop_servers()
    if STATE['pencere_kapandi']:
        threading.Thread(target=shutdown, daemon=True).start()


MULTI.on_exit = clients_closed


# ------------------------------------------------------------------ oyna
def _step(text, state='calisiyor'):
    o = STATE['oyna']
    if o['adimlar'] and o['adimlar'][-1]['durum'] == 'calisiyor':
        o['adimlar'][-1]['durum'] = 'tamam'
    o['adimlar'].append({'metin': text, 'durum': state, 'zaman': time.strftime('%H:%M:%S')})


def launch(server_only=False, friend=False):
    o = STATE['oyna']
    try:
        _step(_('Denetleniyor'))
        if FRD.active():
            raise Error(_('Arkadaşının sunucusundasın: önce oradan ayrıl.'))
        if friend and MANAGER.running() and not MANAGER.friend and MANAGER.client_alive():
            raise Error(_('Önce oyunu kapat: sunucu arkadaş sunucusu olarak yeniden başlamalı.'))
        slot = SAV.active()
        if not slot:
            raise Error(_('Önce Kayıtlar sayfasından bir kayıt oluşturun.'))
        if MULTI.in_use(slot):
            raise Error(_('Etkin kayıt bir ek istemcide açık: önce o istemciyi kapat ya da başka bir kaydı etkin yap.'))
        folder = client_folder()
        if not server_only:
            c = IST.check(folder)
            if STATE.get('istemci_eski') and DL.running():
                raise Error(_('Oyun %s sürümüne güncelleniyor (%%%d). Bitince oynayabilirsin.', IST.supported(), _dl_pct(DL.state())))
            if not c['gecerli'] and DL.running():
                raise Error(_('Oyun istemcisi henüz iniyor (%%%d). Bitince oynayabilirsin.', _dl_pct(DL.state())))
            if not c['gecerli']:
                raise Error(_('İstemci klasörü geçersiz: %s', ' '.join(c['sorunlar'])))
            if MANAGER.client_alive():
                raise Error(_('Oyun zaten açık.'))
            others = IST.running_clients(MULTI.pids())                     # panelin ek istemcileri sayılmaz
            if others:
                raise Error(_('Başka bir DarkOrbit istemcisi açık (süreç %s). Önce onu kapatın.', ', '.join(map(str, others))))
            r = RUN.find(CFG)
            if r['tur'] == 'motor' and not r['hata'] and not r['yol']:      # macOS: panelin Wine'ı ilk OYNA'da iner (wine_motoru.py)
                _step(_('Wine ve DXMT indiriliyor'))
                ENG.wait(lambda pct: STATE['oyna']['adimlar'][-1].update(metin=_('Wine ve DXMT indiriliyor: %%%d', pct)))
            if not PATCH.installed(folder):                   # istemcinin düzeltmeleri: BepInEx sihirbazda kurulmadıysa ilk OYNA'da
                _step(_('BepInEx kuruluyor'))
                if not PATCHER.wait(folder, lambda pct: o['adimlar'][-1].update(metin=_('BepInEx kuruluyor: %%%d', pct))):
                    o['adimlar'][-1].update(metin=_('BepInEx kurulamadı, oyun düzeltmeler olmadan açılır: %s',
                                                    PATCHER.state(folder)['hata']), durum='hata')
            cmd, env = IST.command(CFG, folder, os.path.join(PTH.LOGS, 'client.log'))     # Wine / Proton yoksa sunucular açılmadan hata
            if PATCH.installed(folder) and not PATCH.ready(folder):  # BepInEx'in interop derlemeleri oyundan önce (istemci_yama.isit)
                _step(_('BepInEx ilk açılışa hazırlanıyor (yarım dakika kadar)'))
                if not PATCH.warm_up(folder, cmd, env, PTH.LOGS, lambda d: o['adimlar'][-1].update(ilerleme=d)):
                    o['adimlar'][-1].update(metin=_('BepInEx hazırlanamadı, oyun yine de açılıyor'), durum='hata')
        prof = SAV.profile(slot)
        same = MANAGER.running() and MANAGER.slot == slot
        friend = friend or (MANAGER.running() and MANAGER.friend)    # açık arkadaş sunucusu Oyna ile kapanmaz (misafirler düşmesin)
        friend_env = FRD.host_env() if friend else None
        multi = None if friend else (multi_env() if multi_wanted(slot) else None)
        restart = MANAGER.needs_restart(prof, friend_env, multi, world_file(slot, friend), bot_file(slot, friend))
        if restart and MULTI.live():
            raise Error(_('Ek istemciler açıkken sunucu yeniden başlatılamaz: önce onları kapatın.'))
        if CFG.get('yedek_acilista') and not same:
            _step(_('Kayıt yedekleniyor'))
            SAV.backup(slot, 'oto', _('Oyna (açılış)'))
            STATE['son_yedek'] = time.time()
        if not MANAGER.running() and CFG.get('gunluk_dondur'):
            import launcher
            launcher.rotate_logs(PTH.LOGS, names=('gs.log', 'http.log', 'client.log', 'oyun_konsol.log', 'web_konsol.log',
                                                'panel.log'))
        _step((_('Arkadaş sunucusu başlatılıyor') if friend else _('Sunucular başlatılıyor'))
              if not MANAGER.running() or restart else _('Sunucular açık'))
        MANAGER.start_servers(prof, settings_file(slot), control=bool(SET.read(settings_file(slot)).get('kontrol')), slot=slot, friend=friend_env,
                          multi=multi, world=world_file(slot, friend), bot=bot_file(slot, friend))
        if not server_only:
            _step(_('Oyun açılıyor'))
            try:                                      # dünyanın görev başlıkları (eklentinin GorevMetinleri yaması okur)
                WLD.write_texts(folder, world_id(slot, friend))
            except OSError as e:
                log('görev metinleri yazılamadı: %s' % e)
            write_legacy_upgrade(folder, slot)
            MANAGER.start_client(folder, cmd, env)
            if MANAGER.multi or MANAGER.friend:              # birden çok istemci olabilir: pencereler pilotun adıyla ayırt edilsin
                PR.window_title(MANAGER.client.pid, 'DarkOrbit — %s' % SAV.summary(slot).get('pilot', slot))
            m = SAV.meta(slot)
            SAV.set_meta(slot, son_oynama=time.strftime('%Y-%m-%d %H:%M:%S'), oynama_sayisi=int(m.get('oynama_sayisi') or 0) + 1)
        _step(_('Hazır') if server_only else _('Oyun açıldı: iyi uçuşlar!'), 'tamam')
        o['bitti'] = time.time()
    except (Error, SaveError, RuntimeError, OSError) as e:
        o['hata'] = str(e)
        _step(str(e), 'hata')
        log('oyna hatası: %s' % e)
    except Exception as e:
        o['hata'] = _('Beklenmeyen hata: %r', e)
        _step(o['hata'], 'hata')
        log('oyna hatası: %s' % traceback.format_exc())
    finally:
        o['calisiyor'] = False


def start_launch(server_only=False, friend=False):
    o = STATE['oyna']
    if o['calisiyor']:
        raise Error(_('Başlatma sürüyor.'))
    o.update(calisiyor=True, adimlar=[], hata=None, bitti=None, sadece_sunucu=bool(server_only))
    threading.Thread(target=launch, args=(server_only, friend), daemon=True).start()
    return o


def join_friend(b):
    """Arkadaşlarınla Oyna > Join: denetimler panelde (istemci, açık oyun ve sunucular), katılma arka planda (friends.py)."""
    if STATE['oyna']['calisiyor']:
        raise Error(_('Başlatma sürüyor.'))
    slot = str(b.get('kayit') or '') or SAV.active()
    if not slot or not SAV.exists(slot):
        raise Error(_('Önce Kayıtlar sayfasından bir kayıt oluşturun.'))
    folder = client_folder()
    c = IST.check(folder)
    if not c['gecerli']:
        raise Error(_('İstemci klasörü geçersiz: %s', ' '.join(c['sorunlar'])))
    if MANAGER.client_alive() or IST.running_clients():
        raise Error(_('Oyun zaten açık.'))
    if MANAGER.running():
        raise Error(_('Önce kendi sunucunu durdur (Oyna > Sunucuyu durdur).'))
    cmd, env = IST.command(CFG, folder, os.path.join(PTH.LOGS, 'client.log'))

    def open_client():
        MANAGER.start_client(folder, cmd, env)
        m = SAV.meta(slot)
        SAV.set_meta(slot, son_oynama=time.strftime('%Y-%m-%d %H:%M:%S'), oynama_sayisi=int(m.get('oynama_sayisi') or 0) + 1)
    return FRD.killer(str(b.get('adres') or ''), str(b.get('sifre') or ''), slot, c['surum'] or IST.supported(), open_client)


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
    busy = (MANAGER.running() or MANAGER.client_alive() or STATE['oyna']['calisiyor'] or DL.running() or ADAPTER.state()['calisiyor']
            or FRD.active() or MULTI.live() or ENG.running() or PATCHER.running() or LLM.running())
    return not busy and not (strict and IST.running_clients())


def update_tick(now):
    """GitHub denetimi (GUNCELLEME_SN'de bir), otomatik kurulum ve kurulumdan sonra yeniden başlatma (boştayken)."""
    mode = CFG.get('guncelleme')
    st = UPD.state()
    if st['calisiyor']:
        return
    if st['durum'] == 'kuruldu':
        if idle(strict=True):
            restart()
        return
    if mode == 'kapali':
        return
    if now >= STATE['sonraki_denetim']:
        st = UPD.check()
        STATE['sonraki_denetim'] = now + (3600 if st['durum'] == 'hata' else UPDATE_SEC)
    if st['durum'] == 'var' and mode == 'otomatik' and CFG.get('kurulum_tamam') and idle(strict=True):
        UPD.install_async()


def restart():
    """Güncellemeden sonra yeniden başla: yeni süreç (pencere açmadan) eski kapanınca aynı portu alır; açık pencere sayfayı yeniler."""
    STATE['kapaniyor'] = True
    args = [sys.executable, os.path.join(PANEL_DIR, 'panel.py'), '--pencere-yok', '--guncellendi', '--port=%d' % PORT]
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
    while not STATE['kapaniyor']:
        time.sleep(5)
        try:
            update_tick(time.time())
            iv = CFG.get('yedek_aralik_dk')
            if MANAGER.client_alive() and MANAGER.slot and iv and time.time() - STATE['son_yedek'] >= iv * 60:
                SAV.backup(MANAGER.slot, 'oto', _('Oyun sırasında'))
                STATE['son_yedek'] = time.time()
            MULTI.backup(iv)                           # ek istemcilerin kayıtları
            if not STATE['pencere_izleniyor'] and time.monotonic() - STATE['nabiz'] > HEARTBEAT_SEC and not STATE['pencere_kapandi']:
                STATE['pencere_kapandi'] = True
                log('panel penceresi kapandı (sayfa artık sormuyor)')
                if CFG.get('pencere_kapaninca') == 'kapat':
                    MANAGER.stop_client()
                    MULTI.close_all(wait=8)
            if STATE['pencere_kapandi'] and not MANAGER.client_alive() and not MULTI.live() and not STATE['oyna']['calisiyor']:
                shutdown()
        except Exception:
            log('zamanlayıcı hatası: %s' % traceback.format_exc())


def wait_for_client(sec=8):
    """stop_client yalnız sinyal gönderir: istemci kapanana dek bekle (yoksa shutdown sunucuları açık bırakıp çıkıyordu)."""
    last = time.time() + sec
    while MANAGER.client_alive() and time.time() < last:
        time.sleep(0.2)


def shutdown():
    if STATE['kapaniyor']:
        return
    STATE['kapaniyor'] = True
    log('panel kapanıyor')
    try:
        DL.cancel()                                   # indirme: açılmış dosyalar kalır, sonra kaldığı yerden
        ENG.cancel()
        if not MANAGER.client_alive() and not MULTI.live():
            FRD.shutdown()                             # arkadaşın sunucusundaysa ayrılınır (son hâl kayda)
            MANAGER.stop_servers()
        w = STATE.get('pencere')
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
    os.makedirs(BROWSER_PROFILE, exist_ok=True)
    return subprocess.Popen([b, '--app=%s' % url, '--user-data-dir=%s' % BROWSER_PROFILE, '--window-size=1360,880',
                             '--no-first-run', '--no-default-browser-check', '--disable-features=Translate,msEdgeSidebarV2',
                             '--disable-background-mode', '--disable-sync', '--lang=%s' % D.LANGUAGES[D.current()][1]])


def watch_window(proc):
    STATE['pencere'] = proc
    if sys.platform == 'darwin':
        # macOS'ta pencere kapanınca tarayıcı (öteki uygulamalar gibi) Dock'ta açık kalır: süreç beklenemez. Kapanış sayfanın
        # kapanış işaretinden ve nabzından anlaşılır (/api/kapandi, ticker; tarayıcıdan çıkılınca da işaret gelir); panel kapanınca
        # bu süreç de kapanır (shutdown)
        return
    STATE['pencere_izleniyor'] = True
    t0 = time.time()
    proc.wait()
    STATE['pencere_izleniyor'] = False
    if time.time() - t0 < HANDOVER_SEC:
        # aynı profil klasörüyle açık bir tarayıcı süreci varsa yeni süreç pencereyi ona devredip hemen çıkar (18, 20 ve 22 Ekim:
        # panel açılır açılmaz "kapandı" sayılıp kapanıyordu): pencere açık, kapanışı sayfanın nabzından anlaşılır (ticker)
        STATE['nabiz'] = time.monotonic()
        log('panel penceresi açık bir tarayıcı sürecine devredildi; nabızla izleniyor')
        return
    log('panel penceresi kapandı')
    if CFG.get('pencere_kapaninca') == 'kapat':
        MANAGER.stop_client()
        MULTI.close_all(wait=8)                   # ek istemcilerin son kaydı sunucuya bırakılsın
        wait_for_client()
        shutdown()
    STATE['pencere_kapandi'] = True


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
        p, old = os.path.join(desktop_dir(), SHORTCUT), os.path.join('arayuz', 'simge.ico').encode('utf-16-le')
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
            'Categories=Game;\n' % (_('OpenOrbit yerel sunucu paneli'), sys.executable, script, ROOT, os.path.join(UI_DIR, 'icon.png')))
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
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:DO_KISAYOL); $s.TargetPath=$env:DO_HEDEF; "
          "$s.Arguments=('\"'+$env:DO_BETIK+'\"'); $s.WorkingDirectory=$env:DO_KOK; $s.IconLocation=($env:DO_SIMGE+',0'); "
          "$s.Description=$env:DO_ACIKLAMA; $s.Save()")
    env = dict(os.environ, DO_KISAYOL=lnk, DO_HEDEF=target, DO_BETIK=script, DO_KOK=ROOT, DO_SIMGE=icon,
               DO_ACIKLAMA=_('OpenOrbit yerel sunucu paneli'))
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True, env=env,
                       timeout=30, creationflags=PR.NO_WINDOW, encoding='utf8', errors='replace')
    if r.returncode or not os.path.isfile(lnk):
        raise Error(_('Kısayol oluşturulamadı: %s', r.stderr.strip()[-300:]))
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
    if s.get('secenekler'):
        out['secenekler'] = [_(x) for x in s['secenekler']]
    if s.get('secenek_aciklama'):
        out['secenek_aciklama'] = [_(x) for x in s['secenek_aciklama']]
    if s.get('birim'):
        out['birim'] = _(s['birim'])
    return out


def write_legacy_upgrade(folder=None, slot=None):
    """Eski yükseltme sisteminin uridyum bedelleri istemcinin BepInEx klasörüne (eklentinin EskiYukseltme yaması Assembly'nin
    tariflerini bunlarla değiştirir; kapalıyken {}: istemcinin kendi malzemeleri). OYNA'da ve ayarlar kaydedilince."""
    folder = folder or client_folder()
    if not folder or not os.path.isdir(os.path.join(folder, 'BepInEx')):
        return
    import upgrades as UPG
    v = SET.read(settings_file(slot))
    t = UPG.legacy_table(v.get('eski_yukseltme', SET.DEFAULTS['eski_yukseltme']),
                      v.get('eski_yukseltme_fiyat', SET.DEFAULTS['eski_yukseltme_fiyat']))
    try:
        WLD._write_file(os.path.join(folder, 'BepInEx', 'openorbit', 'eski_yukseltme.json'), t)
    except OSError as e:
        log('eski yükseltme bedelleri yazılamadı: %s' % e)


def api_settings():
    ready = {k: dict(p, ad=_(p['ad']), aciklama=_(p['aciklama'])) for k, p in SET.PRESETS.items()}
    slot = SAV.active()
    return {'sema': [_schema_row(s) for s in SET.SCHEMA], 'gruplar': [{'anahtar': k, 'ad': _(a)} for k, a in SET.GROUPS],
            'degerler': game_settings(), 'varsayilan': SET.DEFAULTS, 'hazir': ready, 'sablonlar': read_json(TEMPLATES, {}),
            'sunucu_acik': MANAGER.running(), 'kayit': slot, 'kayit_adi': SAV.meta(slot).get('ad', slot) if slot else None,
            'kayitlar': [{'id': s, 'ad': SAV.meta(s).get('ad', s)} for s in SAV.slots() if s != slot]}


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
    sel = CFG.get('istemci_klasoru')
    used = client_folder()
    return {'secili': sel, 'kullanilan': used, 'kontrol': IST.check(used), 'adaylar': IST.candidates(),
            'cozunurlukler': IST.RESOLUTIONS, 'ekran': screen_size(), 'ayarlar': CFG.all(),
            'komut': launch_command(), 'calistirici': RUN.summary(CFG), 'desteklenen': IST.supported(),
            'protokol': ADAPTER.state(), 'indirme': DL.state(), 'yama': PATCHER.state(used)}


def extra_logs():
    """Ek istemcilerin günlükleri (logs/client_<kayıt>.log)."""
    try:
        return tuple(sorted(f for f in os.listdir(PTH.LOGS) if EXTRA_LOG.fullmatch(f)))
    except OSError:
        return ()


def slot_arg(q):
    sid = q.get('id')
    if not sid or not SAV.exists(sid):
        raise Error(_('Kayıt bulunamadı.'))
    return sid


def profile_values(sid):
    d = read_json(SAV.profile(sid), {})
    pl, g = d.get('pilot') or {}, d.get('gemi') or {}
    return {'pilot': pl.get('userName', ''), 'kredi': pl.get('credits', 0), 'uridyum': pl.get('uridium', 0),
            'onur': pl.get('honourPoints', 0), 'ep': pl.get('ep', 0), 'seviye': pl.get('level', 1),
            'can': g.get('hitPoints', 0), 'can_azami': g.get('hitMax', 0), 'kalkan': g.get('shield', 0),
            'kalkan_azami': g.get('shieldMax', 0), 'firma': COMPANIES.get(pl.get('factionId'), '?'),
            'kullanimda': SAV.in_use(sid)}


def worlds_status():
    users = world_users()
    return {'liste': WLD.entries(users), 'kapaklar': WLD.COVERS, 'sunucu_acik': MANAGER.running(),
            'sunucu_dunyasi': MANAGER.world[0] if MANAGER.running() and MANAGER.world else None, 'kayitlar': [
                {'id': k['id'], 'ad': k.get('ad'), 'pilot': k.get('pilot'), 'firma': k.get('firma'), 'seviye': k.get('seviye'),
                 'dunya': k.get('dunya') if k.get('dunya') and WLD.var(k.get('dunya')) else WLD.STANDARD, 'aktif': k.get('aktif')}
                for k in SAV.list()]}


def world_arg(q):
    did = q.get('dunya') or WLD.STANDARD
    if not WLD.var(did):
        raise Error(_('Dünya bulunamadı.'))
    return did


def world_get(path, q):
    if path == '/api/dunyalar':
        return worlds_status()
    if path == '/api/dunya':
        did = world_arg(q)
        is_open = bool(MANAGER.running() and MANAGER.world and WLD.file_path(did) and MANAGER.world[0] == os.path.normcase(WLD.file_path(did)))
        # yeniden_gerekli: sunucu açıldıktan sonra oyun açıkken uygulanamayan bir değişiklik yapıldı (mağaza ve açık artırma canlı)
        return dict(WLD.summary(did, world_users()), sunucu_bu_dunyada=is_open,
                    yeniden_gerekli=is_open and PR.world_signature(WLD.file_path(did)) != MANAGER.world)
    if path == '/api/dunya/bolum':
        did, section = world_arg(q), q.get('bolum')
        if section == 'uzaylilar':
            return {'uzaylilar': WLD.aliens(did)}
        if section == 'haritalar':
            return {'haritalar': WLD.maps(did)}
        if section == 'gorevler':
            return {'gorevler': WLD.quests(did)}
        if section == 'magaza':
            return {'kategoriler': WLD.shop(did), 'gorsel': bool(game_image('dizin.json'))}
        if section == 'muzayede':
            return WLD.auction(did)
        if section == 'kutular':
            return WLD.boxes(did)
        if section == 'kapilar':
            return {'kapilar': WLD.gates(did)}
        if section == 'ekonomi':
            return WLD.economy(did)
        if section == 'etkinlikler':
            return {'etkinlikler': WLD.events(did), 'siniflar': WLD.MAP_CLASSES}
        raise Error(_('Bilinmeyen bölüm.'))
    if path == '/api/dunya/harita':
        return WLD.game_map(world_arg(q), q.get('id'))
    if path == '/api/dunya/gorev':
        return WLD.quest(world_arg(q), q.get('id'))
    if path == '/api/dunya/esyalar':
        return {'esyalar': WLD.item_list()}
    raise Error(_('Bilinmeyen istek.'))


def world_post(path, b):
    if path == '/api/kayitlar/dunya':               # kaydın varsayılan dünyası (OYNA bununla açar)
        sid, did = b.get('id'), b.get('dunya') or WLD.STANDARD
        if not sid or not SAV.exists(sid):
            raise Error(_('Kayıt bulunamadı.'))
        if not WLD.var(did):
            raise Error(_('Dünya bulunamadı.'))
        SAV.set_meta(sid, dunya=None if did == WLD.STANDARD else did)
        return worlds_status()
    if path == '/api/dunya/olustur':
        did = WLD.create(b.get('ad'), b.get('aciklama', ''), b.get('kapak', 'nebula'), source=b.get('kaynak'), from_draft=bool(b.get('taslaktan')))
        if b.get('kayit') and SAV.exists(b['kayit']):  # oluşturunca bu kaydın varsayılanı yap
            SAV.set_meta(b['kayit'], dunya=did)
        return dict(worlds_status(), yeni=did)
    if path == '/api/dunya/guncelle':
        WLD.update(b.get('id'), name=b.get('ad'), description=b.get('aciklama'), cover=b.get('kapak'))
        return worlds_status()
    if path == '/api/dunya/sil':
        did = b.get('id')
        WLD.remove(did)
        for k in SAV.list():                        # varsayılanı bu dünya olan kayıtlar standarda döner
            if k.get('dunya') == did:
                SAV.set_meta(k['id'], dunya=None)
        return worlds_status()
    if path == '/api/dunya/kopyala':
        return dict(worlds_status(), yeni=WLD.duplicate(b.get('id'), b.get('ad')))
    if path == '/api/dunya/taslak_at':
        WLD.discard_draft()
        return worlds_status()
    if path == '/api/dunya/disari':
        did = world_arg(b)
        name = re.sub(r'[^\w.-]+', '_', WLD.read(did).get('ad') or did)[:40]
        dest = dialog('kaydet', title=_('Dünyayı dışa aktar'), initialfile='%s.oodunya.json' % name, defaultextension='.json',
                      filetypes=[(_('OpenOrbit dünyası'), '*.json')])
        if not dest:
            return {'iptal': True}
        write_json(dest, WLD.export(did))
        return {'yol': dest}
    if path == '/api/dunya/kod':                    # paylaşım kodu (Discord'a yapıştırılır)
        return {'kod': WLD.code(world_arg(b))}
    if path == '/api/dunya/iceri':                  # paylaşım kodundan ya da dosyadan
        if b.get('kod'):
            data = WLD.from_code(b['kod'])
        else:
            src = dialog('ac', title=_('Dünya içe aktar'), filetypes=[(_('OpenOrbit dünyası'), '*.json'), (_('Tümü'), '*.*')])
            if not src:
                return {'iptal': True}
            data = read_json(src, None)
        did, report = WLD.import_(data)
        return dict(worlds_status(), yeni=did, rapor=report)
    if path == '/api/dunya/yama':                   # editörün değişikliği: dosya + yol -> tam değer (standartta taslağa)
        did = world_arg(b)
        WLD.patch(did, b.get('dosya'), b.get('yol'), b.get('deger'))
        return world_get('/api/dunya', {'dunya': did})
    if path == '/api/dunya/geri_al':
        did = world_arg(b)
        WLD.revert(did, b.get('dosya'), b.get('yol'), b.get('bolum'))
        return world_get('/api/dunya', {'dunya': did})
    if path == '/api/dunya/gorev':
        did = world_arg(b)
        WLD.save_quest(did, b.get('id'), b.get('degisiklik') or {})
        return WLD.quest(did, b.get('id'))
    if path == '/api/dunya/gorev_yeni':
        did = world_arg(b)
        qid = WLD.new_quest(did, b.get('ad'), b.get('seviye'), b.get('hedefler') or [], b.get('oduller') or [])
        return WLD.quest(did, qid)
    if path == '/api/dunya/sunucu_yeniden':         # editörden: dünyanın değişiklikleri için sunucuyu yeniden başlat
        return h_post('/api/sunucu/yeniden', {})
    raise Error(_('Bilinmeyen istek.'))


def bots_status():
    users = world_users()
    worlds = [{'id': w['id'], 'ad': w['ad'], 'kapak': w['kapak'], 'standart': w['standart'],
                 'pilotlar': [u.get('pilot') or u.get('ad') for u in w.get('kullananlar') or []]} for w in WLD.entries(users)]
    return {'liste': BT.entries(), 'dunyalar': worlds, 'kipler': BT.MODES, 'izinler': BT.PERMISSIONS, 'siniflar': BT.SIMPLE_CLASSES,
            'ayarlar': {k: {'tur': v[0], 'en_az': v[1], 'en_cok': v[2], 'varsayilan': v[3]} for k, v in BT.SETTINGS.items()},
            'llm_cok_dilli': PRV.multilingual(), 'sunucu_acik': MANAGER.running(), 'sunucu_paketi': getattr(MANAGER, 'bot', None) and MANAGER.bot[0], 'oyun_ayarlari': bot_game_settings()}


def bot_game_settings():
    """Botların oyun ayarı profilleri (bot/game_settings.py): hazır profiller ve Özel profilin alanları (oyun ayarlarının adlarıyla)."""
    from bot import game_settings as GS
    ready = [{'id': k, 'ad': SET.PRESETS[k]['ad'], 'aciklama': SET.PRESETS[k]['aciklama']} for k in GS.PROFILES if k in SET.PRESETS]
    fields = [{'anahtar': k, 'ad': SET.BY_KEY[k]['ad'], 'aciklama': SET.BY_KEY[k]['aciklama'], 'en_az': SET.BY_KEY[k].get('min', 0),
                'en_cok': min(10, SET.BY_KEY[k].get('max', 10))} for k in GS.FIELDS]
    return {'hazir': ready, 'alanlar': fields}


def player_names():
    return [k.get('pilot') for k in SAV.list() if k.get('pilot')]


def bot_get(path, q):
    if path == '/api/botlar':
        return bots_status()
    if path == '/api/bot/llm':
        return dict(LLM.state(), saglayici=PRV.status())
    if path == '/api/bot/detay':                   # Kadro > bot penceresi: oyun açıkken canlı bot, kapalıyken son kayıt
        return bot_detail(q.get('id'), int(q.get('no') or 0))
    if path == '/api/bot':
        pid = q.get('id')
        d = BT.detail(pid)
        p = BT.file_path(pid)
        is_open = bool(MANAGER.running() and getattr(MANAGER, 'bot', None) and p and MANAGER.bot[0] == os.path.normcase(p))
        return dict(d, sunucu_bu_pakette=is_open, yeniden_gerekli=is_open and PR.bot_signature(p) != MANAGER.bot)
    raise Error(_('Bilinmeyen istek.'))


def bot_detail(pid, no):
    if is_pack_running(pid):
        try:
            return dict(game_channel('/bot/detay', {'no': no}), katalog=BT.edit_catalog(), canli=True)
        except Error:
            # oyun açık ama kanal yanıt vermedi: son kayıt, düzenlenemez (oyun dosyayı yeniden yazar)
            return dict(BT.bot_detail(pid, no), katalog=BT.edit_catalog(), canli=False, salt_okunur=True)
    return dict(BT.bot_detail(pid, no), katalog=BT.edit_catalog(), canli=False)


def bot_post(path, b):
    if path == '/api/bot/detay':                   # botu düzenle (bot/duzenle.py): oyun açıkken canlı, kapalıyken dosyada
        pid, no, value = b.get('id'), int(b.get('no') or 0), b.get('degisiklik') or {}
        if not isinstance(value, dict) or not value:
            raise Error(_('Değişiklik yok.'))
        if is_pack_running(pid):
            r = game_channel('/bot/duzenle', {'no': no, 'degisiklik': value})
            if r.get('hata'):
                from bot import edit as ED
                raise Error(BT.edit_error(ED.EditError(r['hata'], r.get('alan', ''))))
            if 'ozellik' in value:
                BT.bot_personality(pid, no, value['ozellik'])
            return dict(r, katalog=BT.edit_catalog(), canli=True)
        return dict(BT.edit_bot(pid, no, value), katalog=BT.edit_catalog(), canli=False)
    if path == '/api/bot/llm/saglayici':          # sağlayıcı seçimi: dahili model, OpenAI, Claude ... (bot/llm_saglayici.py)
        if b.get('kimlik') not in PRV.PROVIDERS:
            raise Error(_('Bilinmeyen istek.'))
        if b.get('adres') and not re.fullmatch(r'https?://\S+', str(b['adres']).strip()):
            raise Error(_('Adres http:// ya da https:// ile başlamalı.'))
        PRV.save(b['kimlik'], b.get('adres'), b.get('model'), b.get('anahtar'))
        return bot_get('/api/bot/llm', {})
    if path == '/api/bot/llm/modeller':
        try:
            return {'modeller': PRV.models(b.get('kimlik'), b.get('adres') or None, b.get('anahtar') or None)}
        except PRV.ProviderError as e:
            raise Error(str(e))
    if path == '/api/bot/llm/test' and PRV.setting()['secili'] != PRV.LOCAL:
        try:
            return dict(LLM.test_remote(), saglayici=PRV.status())
        except LLMS.DownloadError as e:
            raise Error(str(e))
    if path.startswith('/api/bot/llm/'):           # dil modeli: kur, durdur, sil, test
        operation = {'kur': LLM.start, 'durdur': LLM.cancel, 'sil': LLM.remove, 'test': LLM.test}.get(path.rsplit('/', 1)[1])
        if operation is None:
            raise Error(_('Bilinmeyen istek.'))
        if path.endswith('/sil') and MANAGER.running():
            raise Error(_('Önce oyunu kapat.'))
        try:
            return dict(operation(), saglayici=PRV.status())
        except LLMS.DownloadError as e:
            raise Error(str(e))
    if path == '/api/bot/olustur':
        pid = BT.create(b.get('ad'), b.get('aciklama', ''), b.get('dunya'), b.get('kip', 'normal'), b.get('gelisim', 'progressive'),
                         b.get('adet', 60), b.get('dil', 'karisik'), b.get('firma_dagilimi') or (1, 1, 1), b.get('ayarlar') or {},
                         players=player_names(), name_lang_=b.get('ad_dili'), special=b.get('ozel') or '', name_source=b.get('ad_kaynagi'))
        return dict(bots_status(), yeni=pid)
    pid = b.get('id')
    if path == '/api/bot/guncelle':
        BT.update(pid, name=b.get('ad'), description=b.get('aciklama'), mode=b.get('kip'), progression=b.get('gelisim'), settings=b.get('ayarlar'))
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/ata':                      # paketi dünyaya ata (o dünyanın eski paketi boşa çıkar)
        did = b.get('dunya') or None
        if did and not WLD.var(did):
            raise Error(_('Dünya bulunamadı.'))
        BT.assign(pid, did)
        return bots_status()
    if path == '/api/bot/kadro':
        if is_pack_running(pid) and (b.get('yeniden') or int(b.get('adet') or 0) < len(BT.read(pid)['kadro'])):
            raise Error(_('Bu paket oyunda açık: önce oyunu kapat.'))     # çalışan oyun eski kadroyla durumu yeniden yazar
        BT.roster(pid, count=b.get('adet'), lang=b.get('dil'), company_distribution=b.get('firma_dagilimi'), regenerate=bool(b.get('yeniden')),
                 players=player_names(), name_lang_=b.get('ad_dili'), special=b.get('ozel') or '', name_source=b.get('ad_kaynagi'))
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
            raise Error(_('Bu paket oyunda açık: önce oyunu kapat.'))
        BT.reset(pid)
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/sil':
        if is_pack_running(pid):
            raise Error(_('Bu paket oyunda açık: önce oyunu kapat.'))
        BT.remove(pid)
        return bots_status()
    if path == '/api/bot/sunucu_yeniden':
        return h_post('/api/sunucu/yeniden', {})
    raise Error(_('Bilinmeyen istek.'))


_SUPPORTERS = {'zaman': 0, 'adlar': []}


def supporters():
    """Buy Me a Coffee sayfasının son destekçileri (gizli olanlar hariç; 10 dakika önbellek, bağlantı yoksa boş liste)."""
    if time.time() - _SUPPORTERS['zaman'] > 600:
        try:
            with urlopen(Request(DONATE_API_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}), timeout=6) as r:
                data = json.load(r).get('data') or []
            _SUPPORTERS['adlar'] = list(dict.fromkeys(str(x.get('supporter_name') or '').strip() for x in data
                                                    if x.get('support_visibility') == 1 and x.get('supporter_name')))
            _SUPPORTERS['zaman'] = time.time()
        except (OSError, ValueError):
            return []                                  # çevrimdışı: şerit gizli kalır, sonraki açılışta yeniden denenir
    return _SUPPORTERS['adlar']


def h_get(path, q):
    if path.startswith('/api/bot'):                 # Botlar (botlar.py)
        return bot_get(path, q)
    if path.startswith('/api/dunya'):               # Dünya Editörü (dunyalar.py)
        return world_get(path, q)
    if path == '/api/destekciler':                 # kenar çubuğundaki kayan destekçi şeridi
        return {'adlar': supporters()}
    if path == '/api/durum':
        return status()
    if path == '/api/ayarlar':
        return api_settings()
    if path == '/api/etkinlikler':
        return event_list()
    if path == '/api/kayitlar':
        return {'liste': SAV.list(), 'aktif': SAV.active(), 'silinenler': SAV.deleted(), 'firmalar': COMPANIES}
    if path == '/api/kayit_profili':
        return profile_values(slot_arg(q))
    if path == '/api/editor':                       # karakter editörü: kaydın taslağı (kayit_editoru.py)
        return SAV.editor_open(slot_arg(q))
    if path == '/api/editor/katalog':               # karakter editörünün eşya kataloğu
        return SAV.editor_catalog()
    if path == '/api/esya_bilgi':                   # eşya ipucunun değerleri (Hangar, Mağaza, karakter editörü)
        return {'esyalar': SAV.item_info()}
    if path == '/api/yedekler':
        sid = slot_arg(q)
        return {'liste': SAV.backups(sid), 'kayit': SAV.summary(sid), 'ayarlar': CFG.all()}
    if path == '/api/istemci':
        return api_client()
    if path == '/api/panel_ayarlari':
        return CFG.all()
    if path == '/api/discord_rp':                   # Discord Rich Presence: bağlantı ve profilde görünecek etkinlik (önizleme)
        return {'durum': RP.state, 'hata': RP.error, 'etkinlik': RP.preview(), 'ayarlar': CFG.all()}
    if path == '/api/diller':
        return {'diller': D.entries()}
    if path == '/api/takvim':                       # etkinlik takvimi: ?bas=&bit= (zaman damgası, en çok 62 gün)
        return api_calendar(q)
    if path == '/api/portlar':
        return MANAGER.foreign_ports()
    if path == '/api/gunluk':
        name = q.get('ad', 'gs.log')
        if name not in LOGS and not EXTRA_LOG.fullmatch(name):
            raise Error(_('Bilinmeyen günlük.'))
        p = os.path.join(PTH.LOGS, name)
        n = min(5000, max(50, int(q.get('satir', 400))))
        return {'ad': name, 'var': os.path.isfile(p), 'boyut': os.path.getsize(p) if os.path.isfile(p) else 0,
                'satirlar': PR.tail(p, n), 'liste': [{'ad': g, 'boyut': os.path.getsize(os.path.join(PTH.LOGS, g))
                                                       if os.path.isfile(os.path.join(PTH.LOGS, g)) else None}
                                                      for g in LOGS + extra_logs()]}
    if path == '/api/istemci/indirme':              # istemci indirmenin durumu (indirme.py)
        return DL.state()
    if path == '/api/motor':                        # macOS: panelin Wine'ı ve Rosetta (wine_motoru.py)
        return ENG.state()
    if path == '/api/yama':                         # istemcinin düzeltmelerini yükleyen BepInEx (istemci_yama.py)
        return PATCHER.state(client_folder())
    if path == '/api/guncelleme':                   # GitHub'dan güncelleme (guncelleme.py)
        return dict(UPD.state(), ayar=CFG.get('guncelleme'), bosta=idle())
    if path == '/api/protokol':                     # protokol uyarlamasının durumu (protokol.py)
        return dict(ADAPTER.state(), etkin=IST.supported())
    if path == '/api/esya_listesi':                 # kayıt düzenleyicinin "eşya ver" listesi
        return {'esyalar': SAV.loot_list()}
    if path == '/api/oyun/magaza':                  # oyun menüleri: mağazanın listesi ve cüzdan (panel_kanali.py)
        return dict(game_channel('/magaza'), gorsel=bool(game_image('dizin.json')))
    if path == '/api/oyun/hangar':                  # oyun menüleri: gemiler, config'ler, yuvalar ve envanter (?gemi=)
        return dict(game_channel('/hangar?gemi=%s' % re.sub(r'\D', '', str(q.get('gemi') or ''))), gorsel=bool(game_image('dizin.json')))
    if path == '/api/oyun/muzayede':                # oyun menüleri: açık artırma (lotlar, kurallar, geçmiş, olaylar)
        return dict(game_channel('/muzayede'), gorsel=bool(game_image('dizin.json')))
    if path == '/api/oyun/muzayede/olaylar':        # açık artırmanın yeni olayları (panelin bildirimleri)
        return game_channel('/muzayede/olaylar?son=%d' % int(q.get('son') or 0))
    if path == '/api/oyun/skylab':                  # oyun menüleri: Skylab modülleri, depo, enerji, taşıma
        return dict(game_channel('/skylab'), gorsel=bool(game_image('dizin.json')))
    if path == '/api/canli':                        # canlı durum (oyun sunucusunun canli_durum.json'u; canli_durum.py)
        p = os.path.join(PTH.LOGS, 'canli_durum.json')
        d = read_json(p, None)
        if not d or (not MANAGER.running() and time.time() - d.get('zaman', 0) > 15):    # eski dosya: sunucu kapalı
            return {'var': False, 'sunucu_acik': MANAGER.running()}
        import event_calendar as CAL
        d['etkinlik_adlari'] = [_(CAL.EVENTS.get(k, {}).get('ad', k)) for k in d.get('etkinlikler', [])]
        return {'var': True, 'sunucu_acik': True, 'yas': max(0, time.time() - d.get('zaman', 0)), 'durum': d}
    if path == '/api/arkadas':                      # Arkadaşlarınla Oyna: Host (sunucu, adresler, misafirler) ve Join (oturum)
        live = read_json(os.path.join(PTH.LOGS, 'canli_durum.json'), None) if MANAGER.running() else None
        active = SAV.active()
        return {'host': FRD.host_status(live), 'misafir': FRD.state(), 'kayitlar': SAV.list(), 'aktif': active,
                'istemci_surumu': IST.check(client_folder()).get('surum') or IST.supported(),
                # Host'un dünyası (Dünya Editörü): seçim ('' kaydının dünyası), seçilebilenler ve sunucunun açılacağı dünya
                'dunya': {'secim': CFG.get('arkadas_dunya') if WLD.var(CFG.get('arkadas_dunya') or '') else '',
                          'kaydin': world_info(SAV.meta(active).get('dunya') if active else None), 'gecerli': world_info(world_id(active, True)),
                          'liste': [{'id': w['id'], 'ad': w['ad'], 'kapak': w['kapak'], 'standart': w['standart']} for w in WLD.entries()]}}
    if path == '/api/hakkinda':
        return {'surum': VERSION, 'python': sys.version.split()[0], 'kok': ROOT, 'sunucu': SERVER, 'kayitlar': PTH.SAVES,
                'gunlukler': PTH.LOGS, 'ayarlar': settings_file(), 'panel': PTH.PANEL, 'port': PORT, 'dil': D.current(), 'discord': DISCORD,
                'eski_kisayol': bool(old_shortcut())}
    raise Error(_('Bilinmeyen istek: %s', path))


def h_post(path, b):
    if path.startswith('/api/bot/'):                # Botlar (botlar.py)
        return bot_post(path, b)
    if path.startswith('/api/dunya') or path == '/api/kayitlar/dunya':      # Dünya Editörü (dunyalar.py)
        return world_post(path, b)
    if path == '/api/oyun/al':                      # oyun menüleri: mağazadan satın alma (istemcinin isteğiyle aynı yoldan)
        return game_channel('/magaza/al', {k: b.get(k) for k in ('lootId', 'category', 'amount', 'level')})
    if path == '/api/oyun/magaza/abone':            # oyun menüleri: booster aboneliği
        return game_channel('/magaza/abone', {'lootId': b.get('lootId'), 'category': b.get('category')})
    if path == '/api/oyun/hangar/tasi':             # oyun menüleri: envanter <-> gemi, dron ya da P.E.T. yuvası
        return game_channel('/hangar/tasi', {k: b.get(k) for k in ('gemi', 'konfig', 'esya', 'yon', 'hedef', 'dron', 'kume')})
    if path == '/api/oyun/hangar/islem':            # oyun menüleri: config, satış, P.E.T., CPU işlemleri (panel_kanali.ISLEMLER)
        return game_channel('/hangar/islem', {k: b.get(k) for k in ('islem', 'gemi', 'konfig', 'hedef_gemi', 'favori', 'esyalar', 'dron',
                                                                    'ad', 'yuva', 'esya', 'cephane', 'lootId')})
    if path == '/api/oyun/hangar/tasarim':          # oyun menüleri: geminin görünümü (tasarımı)
        return game_channel('/hangar/tasarim', {'gemi': b.get('gemi'), 'lootId': b.get('lootId')})
    if path == '/api/oyun/hangar/etkin':            # oyun menüleri: geminin etkinleştirilmesi (yalnız istasyonda)
        return game_channel('/hangar/etkin', {'gemi': b.get('gemi')})
    if path == '/api/oyun/skylab/islem':            # oyun menüleri: Skylab yükseltme, aç/kapa, gemiye taşıma
        return game_channel('/skylab/islem', {k: b.get(k) for k in ('modul', 'islem', 'mod', 'miktarlar')})
    if path.startswith('/api/oyun/muzayede/') and path.rsplit('/', 1)[1] in ('teklif', 'hepsi', 'anlik', 'oto', 'alarm'):   # açık artırma
        return game_channel('/muzayede/' + path.rsplit('/', 1)[1], {k: b.get(k) for k in ('tur', 'loot', 'fiyat', 'lotlar', 'azami', 'gecilince', 'dk')})
    if path == '/api/oyun/skylab/robot':            # oyun menüleri: toplayıcıya robot
        return game_channel('/skylab/robot', {'modul': b.get('modul'), 'tip': b.get('tip')})
    # ---- oyun ve sunucular
    if path == '/api/oyna':
        return start_launch(b.get('sadece_sunucu'))
    if path == '/api/arkadas/ayarlar':
        world = b.get('dunya', CFG.get('arkadas_dunya')) or ''
        if world and not WLD.var(world):
            raise Error(_('Dünya bulunamadı.'))
        CFG.update({'arkadas_sifre': str(b.get('sifre') if 'sifre' in b else CFG.get('arkadas_sifre') or '')[:64],
                    'arkadas_en_cok': b.get('en_cok', CFG.get('arkadas_en_cok')), 'arkadas_dunya': world})
        return h_get('/api/arkadas', {})
    if path == '/api/arkadas/host':                 # arkadaş sunucusu: Oyna gibi, oyun sunucusu --cok-oyunculu
        return start_launch(b.get('sadece_sunucu'), friend=True)
    if path == '/api/arkadas/genel_ip':
        return {'ip': FRD.find_public_ip()}
    if path == '/api/arkadas/at':
        FRD.at(b.get('oturum'))
        return {}
    if path == '/api/arkadas/dene':
        return FRD.attempt(str(b.get('adres') or ''))
    if path == '/api/arkadas/katil':
        return join_friend(b)
    if path == '/api/arkadas/ayril':
        FRD.detach()
        return FRD.state()
    if path == '/api/sunucu/durdur':
        if MANAGER.client_alive():
            raise Error(_('Oyun açıkken sunucu durdurulamaz: önce oyunu kapatın.'))
        if MULTI.live():
            raise Error(_('Ek istemciler açıkken sunucu durdurulamaz: önce onları kapatın.'))
        MANAGER.stop_servers()
        return MANAGER.status()
    if path == '/api/sunucu/yeniden':
        slot = MANAGER.slot or SAV.active()
        if not slot:
            raise Error(_('Kayıt yok.'))
        if MULTI.live():
            raise Error(_('Ek istemciler açıkken sunucu yeniden başlatılamaz: önce onları kapatın.'))
        friend_env = FRD.host_env() if MANAGER.running() and MANAGER.friend else None       # kip korunur (Host, çoklu istemci)
        multi = None if friend_env else (multi_env() if (MANAGER.running() and MANAGER.multi) or multi_wanted(slot) else None)
        MANAGER.stop_servers()
        MANAGER.start_servers(SAV.profile(slot), settings_file(slot), control=bool(SET.read(settings_file(slot)).get('kontrol')), slot=slot, friend=friend_env,
                          multi=multi, world=world_file(slot, bool(friend_env)), bot=bot_file(slot, bool(friend_env)))
        return MANAGER.status()
    if path == '/api/istemci/kapat':
        MANAGER.stop_client()
        return MANAGER.status()
    if path == '/api/coklu/ac':                     # çoklu istemci: başka bir kayıtla ek istemci (coklu.py)
        return open_extra(b)
    if path == '/api/coklu/kapat':
        MULTI.close(str(b.get('kayit') or ''))
        return MULTI.state()
    if path == '/api/coklu/hepsini_kapat':
        MULTI.close_all()
        return MULTI.state()
    if path == '/api/portlar/kapat':
        pid = int(b.get('pid') or 0)
        info = PR.process_info(pid)
        if not (PR.is_our_server(info) or info['ad'].lower() == 'darkorbit.exe'):
            raise Error(_('Bu süreç (%s) panelin sunucusu değil; panel kapatmaz. Gerekirse kendiniz kapatın.', info['ad']))
        m = re.search(r'"--durdur=([^"]+)"|--durdur=(\S+)', info.get('komut') or '')
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
        for k, v in (b.get('degerler') or {}).items():
            if k in SET.BY_KEY:
                vals[k] = v
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/ayarlar/kopyala':             # başka bir kaydın ayarları (etkinlik seçimleri dahil) etkin kayda
        slot = SAV.active()
        if not slot:
            raise Error(_('Kayıt yok.'))
        SAV.copy_settings(str(b.get('kaynak') or ''), slot)
        log('ayarlar kopyalandı: %s -> %s' % (b.get('kaynak'), slot))
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/ayarlar/sifirla':
        vals = game_settings()
        keys = b.get('anahtarlar') or list(SET.BY_KEY)
        for k in keys:
            vals.pop(k, None)
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/ayarlar/hazir':
        name = b.get('ad')
        user = read_json(TEMPLATES, {})
        preset = SET.PRESETS.get(name, {}).get('degerler') if name in SET.PRESETS else (user.get(name) or {}).get('degerler')
        if preset is None:
            raise Error(_('Hazır ayar bulunamadı.'))
        vals = {k: v for k, v in game_settings().items() if k not in SET.BY_KEY}     # etkinlik seçimleri kalır
        vals.update(preset)
        SET.write(settings_file(), vals)
        write_legacy_upgrade()
        return api_settings()
    if path == '/api/ayarlar/sablon_kaydet':
        name = (b.get('ad') or '').strip()[:40]
        if not name:
            raise Error(_('Şablona bir ad verin.'))
        user = read_json(TEMPLATES, {})
        vals = {k: v for k, v in game_settings().items() if k in SET.BY_KEY and v != SET.DEFAULTS[k]}
        user[name] = {'ad': name, 'aciklama': b.get('aciklama') or _('Kendi ayarın'), 'degerler': vals}
        write_json(TEMPLATES, user)
        return api_settings()
    if path == '/api/ayarlar/sablon_sil':
        user = read_json(TEMPLATES, {})
        user.pop(b.get('ad'), None)
        write_json(TEMPLATES, user)
        return api_settings()
    if path == '/api/etkinlikler':
        return set_events(b)
    # ---- kayıtlar
    if path == '/api/kayitlar/yeni':
        sid = SAV.create(b.get('ad'), b.get('pilot'), b.get('firma'), b.get('kredi'), b.get('uridyum'), b.get('seviye'), b.get('onur'),
                         b.get('lazer'), b.get('roket'), bool(b.get('ilerlemeli')), b.get('ayar_kaynagi') or SAV.active(),
                         campaign=bool(b.get('kampanya')))
        if b.get('aktif_yap', True):
            SAV.set_active(sid)
        log('yeni kayıt: %s' % sid)
        return {'id': sid}
    if path == '/api/kayitlar/aktif':
        return {'id': SAV.set_active(slot_arg(b))}
    if path == '/api/kayitlar/adlandir':
        return SAV.rename(slot_arg(b), b.get('ad'))
    if path == '/api/kayitlar/not':
        return SAV.set_note(slot_arg(b), b.get('not'))
    if path == '/api/kayitlar/kopyala':
        return {'id': SAV.duplicate(slot_arg(b), b.get('ad'))}
    if path == '/api/kayitlar/sil':
        return {'dosya': SAV.delete(slot_arg(b))}
    if path == '/api/kayitlar/geri_al':
        return {'id': SAV.undelete(b.get('dosya'))}
    if path == '/api/kayitlar/cop_bosalt':
        return {'silinen': SAV.purge(b.get('dosya'))}
    if path == '/api/kayitlar/disari':
        sid = slot_arg(b)
        name = '%s_%s.zip' % (sid, time.strftime('%Y%m%d'))
        dest = dialog('kaydet', title=_('Kaydı dışa aktar'), initialfile=name, defaultextension='.zip',
                      filetypes=[(_('DarkOrbit kaydı'), '*.zip')])
        if not dest:
            return {'iptal': True}
        SAV.export(sid, dest, bool(b.get('yedeklerle', True)))
        return {'yol': dest}
    if path == '/api/kayitlar/iceri':
        src = dialog('ac', title=_('Kayıt içe aktar'), filetypes=[(_('DarkOrbit kaydı'), '*.zip *.json'), (_('Tümü'), '*.*')])
        if not src:
            return {'iptal': True}
        return {'id': SAV.import_file(src)}
    if path == '/api/kayitlar/duzenle':
        return {'degisen': SAV.edit(slot_arg(b), b.get('degerler') or {})}
    # ---- karakter editörü (taslak: Kaydet profile yazar, Vazgeç atar)
    if path == '/api/editor/uygula':
        return SAV.editor_apply(slot_arg(b), b.get('islemler'))
    if path == '/api/editor/kaydet':
        sid = slot_arg(b)
        log('karakter editörü: %s kaydedildi' % sid)
        return {'yedek': SAV.editor_commit(sid)}
    if path == '/api/editor/vazgec':
        SAV.editor_discard(slot_arg(b))
        return {}
    # ---- yedekler
    if path == '/api/yedekler/al':
        return {'dosya': SAV.backup(slot_arg(b), 'elle', b.get('not') or '')}
    if path == '/api/yedekler/geri_yukle':
        return {'guvenlik': SAV.restore(slot_arg(b), b.get('dosya'))}
    if path == '/api/yedekler/sil':
        SAV.delete_backup(slot_arg(b), b.get('dosya'))
        return {}
    if path == '/api/yedekler/not':
        SAV.set_backup_note(slot_arg(b), b.get('dosya'), b.get('not'))
        return {}
    if path == '/api/yedekler/yeni_kayit':
        return {'id': SAV.backup_as_new(slot_arg(b), b.get('dosya'), b.get('ad'))}
    # ---- istemci ve panel ayarları
    if path == '/api/panel_ayarlari':
        CFG.update({k: v for k, v in (b.get('degerler') or {}).items() if k != 'aktif_kayit'})
        RP.wake_up.set()                               # Discord Rich Presence ayarı değiştiyse hemen
        return api_client()
    if path == '/api/istemci/sec':
        start = client_folder() or ROOT
        p = dialog('klasor', title=_('DarkOrbit oyun klasörünü seçin (içinde DarkOrbit.exe ve DarkOrbit_Data olan)'), initialdir=start)
        if not p:
            return dict(api_client(), iptal=True)
        p = os.path.normpath(p)
        c = IST.check(p)
        if not c['gecerli'] and os.path.basename(p).lower() == IST.DATA_DIR.lower() and IST.check(os.path.dirname(p))['gecerli']:
            p = os.path.dirname(p)                    # DarkOrbit_Data seçildiyse üst klasörü
            c = IST.check(p)
        if not c['gecerli']:
            sub = [x for x in IST.candidates() if os.path.normcase(x['yol']).startswith(os.path.normcase(p))]
            if sub:
                p, c = sub[0]['yol'], sub[0]
            else:
                raise Error(_('Seçilen klasör bir DarkOrbit istemcisi değil: %s', ' '.join(c['sorunlar'])))
        CFG.update({'istemci_klasoru': p})
        return api_client()
    if path == '/api/istemci/kullan':
        p = os.path.normpath(b.get('yol') or '')
        if not IST.check(p)['gecerli']:
            raise Error(_('Klasör geçerli bir istemci değil.'))
        CFG.update({'istemci_klasoru': p})
        return api_client()
    if path == '/api/istemci/otomatik':
        CFG.update({'istemci_klasoru': None})
        return api_client()
    if path == '/api/guncelleme/denetle':
        UPD.check()
        STATE['sonraki_denetim'] = time.time() + UPDATE_SEC
        return h_get('/api/guncelleme', {})
    if path == '/api/guncelleme/kur':
        if not idle(strict=True):
            raise Error(_('Önce oyunu, sunucuları ve süren işleri kapatın.'))
        try:
            UPD.install_async()
        except UpdateError as e:
            raise Error(str(e))
        return h_get('/api/guncelleme', {})
    if path == '/api/istemci/indir':                # oyunu indir ve proje köküne aç (sürer, kaldığı yerden)
        if RUN.find(CFG)['tur'] == 'motor':          # macOS: oyunu açacak Wine da birlikte iner
            ENG.start()
        return DL.start(CFG.get('hizli_indirme'))
    if path == '/api/istemci/guncelle':             # eski istemci: yeni sürümü indir, eskisini sil; BepInEx yeni klasöre yeniden kurulur
        if MANAGER.client_alive() or IST.running_clients():
            raise Error(_('Önce oyunu kapatın'))
        old = client_folder()
        if not IST.check(old)['eski']:
            raise Error(_('İstemci zaten güncel.'))
        new_ = next((c['yol'] for c in IST.candidates() if c['uyumlu']), None)
        if new_:                                    # bilgisayarda zaten var
            CFG.update({'istemci_klasoru': new_})
            delete_old_client(old, new_)
            PATCHER.start(new_)
            return DL.state()
        STATE['istemci_eski'] = old
        return DL.start(CFG.get('hizli_indirme'))
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
    if path == '/api/istemci/indir_durdur':
        return DL.cancel()
    if path == '/api/istemci/indir_sil':            # yarım indirmenin geçici klasörü
        try:
            return DL.discard()
        except DownloadError as e:
            raise Error(str(e))
    if path == '/api/protokol/uret':                # yeni istemciden protokol üret ve farkı raporla (etkin dosyalara dokunmaz)
        try:
            return ADAPTER.generate(os.path.normpath(b.get('yol') or client_folder() or ''))
        except RuntimeError as e:
            raise Error(str(e))
    if path == '/api/protokol/uygula':              # üretilen sürümü etkin yap (oyun sunucusu yeniden başlatılınca)
        if MANAGER.running():
            raise Error(_('Önce oyun sunucusunu durdurun: protokol açılışta yükleniyor.'))
        try:
            return ADAPTER.activate(b.get('surum'))
        except RuntimeError as e:
            raise Error(str(e))
    if path == '/api/gunluk/temizle':
        name = b.get('ad')
        if name not in LOGS and not EXTRA_LOG.fullmatch(str(name or '')):
            raise Error(_('Bilinmeyen günlük.'))
        try:
            open(os.path.join(PTH.LOGS, name), 'w').close()
        except OSError:
            raise Error(_('Günlük şu an bir sunucuda açık; sunucuyu durdurup yeniden deneyin.'))
        return {}
    if path == '/api/klasor_ac':
        what = b.get('ne')
        paths = {'proje': ROOT, 'kayitlar': PTH.SAVES, 'gunlukler': PTH.LOGS, 'istemci': client_folder() or ROOT,
                 'sunucu': SERVER}
        if what in ('kayit', 'yedek'):
            sid = slot_arg(b)
            p = SAV.dir(sid) if what == 'kayit' else SAV.backup_dir(sid)
            os.makedirs(p, exist_ok=True)
            open_folder(p)
        elif what in paths:
            os.makedirs(paths[what], exist_ok=True) if what in ('kayitlar', 'gunlukler') else None
            open_folder(paths[what])
        else:
            raise Error(_('Bilinmeyen klasör.'))
        return {}
    if path == '/api/discord':                      # davet varsayılan tarayıcıda (panel penceresinin profili Discord'a girişli değil)
        import webbrowser
        webbrowser.open(DISCORD)
        return {}
    if path == '/api/bagis':                        # destek sayfası varsayılan tarayıcıda (Buy Me a Coffee)
        import webbrowser
        webbrowser.open(DONATE_URL)
        return {}
    if path == '/api/kisayol':
        return {'yol': create_shortcut()}
    if path == '/api/kapat':
        if (MANAGER.client_alive() or MULTI.live()) and not b.get('zorla'):
            raise Error(_('Oyun açık: önce oyunu kapatın.'))
        MANAGER.stop_client()
        threading.Thread(target=lambda: (MULTI.close_all(wait=8), wait_for_client(), shutdown()), daemon=True).start()
        return {}
    raise Error(_('Bilinmeyen istek: %s', path))


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
            return self._send(403, {'hata': _('Geçersiz belirteç: paneli yeniden açın.')})
        try:
            out = fn(urlparse(self.path).path, arg)
        except (Error, SaveError, FriendError, MultiClientError, RuntimeError, ValueError) as e:
            return self._send(400, {'hata': str(e)})
        except Exception as e:
            log('API hatası %s: %s' % (self.path, traceback.format_exc()))
            return self._send(500, {'hata': _('Beklenmeyen hata: %r', e)})
        return self._send(200, out)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {'hata': 'host'})
        u = urlparse(self.path)
        if u.path == '/api/ping':
            return self._send(200, {'panel': 'darkorbit', 'surum': VERSION, 'pid': os.getpid()})
        if u.path.startswith('/api/'):
            return self._api(h_get, {k: v[0] for k, v in parse_qs(u.query).items()})
        if u.path.startswith('/oyun_gorsel/'):
            p = game_image(u.path[len('/oyun_gorsel/'):])
            if not p:
                return self._send(404, b'yok', 'text/plain')
            if p.endswith('.png'):                  # atlas sayfaları büyük, değişmez; dizin ve adlar yeniden dökümde değişir: önbelleksiz
                return self._send(200, open(p, 'rb').read(), 'image/png', {'Cache-Control': 'max-age=3600'})
            return self._send(200, open(p, 'rb').read(), 'application/json; charset=utf-8')
        name = 'index.html' if u.path in ('/', '/index.html') else u.path.lstrip('/')
        p = os.path.normpath(os.path.join(UI_DIR, name))
        if not p.startswith(UI_DIR + os.sep) or not os.path.isfile(p):
            return self._send(404, b'yok', 'text/plain')
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
            if not STATE['pencere_izleniyor']:
                STATE['nabiz'] = time.monotonic() - HEARTBEAT_SEC + 8
            return self._send(200, {})
        try:
            body = json.loads(raw.decode('utf8') or '{}')
        except ValueError:
            return self._send(400, {'hata': _('JSON değil')})
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
    if STATE['guncellendi']:                          # güncellemeden sonra: eski süreç portu bırakana dek bekle
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
    log('panel açıldı: http://127.0.0.1:%d/ (python %s)%s' % (PORT, sys.version.split()[0], ' (güncellemeden sonra)' if STATE['guncellendi'] else ''))
    try_migrate()
    threading.Thread(target=refresh_shortcut, daemon=True).start()
    if not CFG.get('aktif_kayit') and SAV.slots():
        CFG.update({'aktif_kayit': SAV.slots()[0]})
    threading.Thread(target=ticker, daemon=True).start()
    RP.launch()
    if '--pencere-yok' not in sys.argv:
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
            ctypes.windll.user32.MessageBoxW(0, _('Panel başlatılamadı. Ayrıntı: server\\logs\\panel.log\n\n%s',
                                                  traceback.format_exc()[-900:]), 'OpenOrbit Panel', 0x10)
        except Exception:
            pass
        raise
