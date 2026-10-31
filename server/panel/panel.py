"""DarkOrbit yerel sunucu yönetim paneli: oyunu başlatır, ayarları, kayıtları ve sunucuları yönetir.

Başlatma: ana dizindeki "OpenOrbit Panel.pyw" (çift tıkla; konsolsuz) ya da python server/panel/panel.py.
Panel 127.0.0.1:8077'de yerel bir web arayüzü açar ve onu Edge'in (yoksa Chrome'un) uygulama penceresinde gösterir (adres çubuğu
yok, internet gerekmez). Pencere kapanınca: oyun sürüyorsa istemci kapanana dek bekler (ayar), sonra panelin açtığı sunucuları
kapatıp çıkar. Panel zaten açıksa ikinci başlatma yalnız pencereyi yeniden açar.
API: /api/... (JSON). İstekler sayfadaki belirteci (X-Panel-Belirteci) taşımalı: başka sitelerin tarayıcıdan panele istek
göndermesini engeller. Yalnız 127.0.0.1'e bağlanır.
Yollar: yollar.py (save/kayitlar, save/panel.json, save/ayarlar.json, logs/).
Dil: dil.py'deki diller (metinler Türkçe yazılır, öbür dillerdekiler arayuz/<kod>.json). İlk açılışta arayüz kurulum sihirbazını
açar: dil, oyun klasörü, ilk pilot, oyun ayarları (panel.json 'dil', 'kurulum_tamam'). Oyun bilgisayarda bulunamazsa sihirbazın oyun
klasörü adımı onu indirmeye başlar (indirme.py; İstemci sayfasından da). İstemcinin düzeltmelerini yükleyen BepInEx de
istemci klasörüne kurulur (istemci_yama.py: sihirbazın oyun klasörü adımında, istemci inince, İstemci sayfasından ya da ilk OYNA'da).
Çoklu istemci (coklu.py): OYNA'dan sonra öteki kayıtlarla ek istemciler aynı sunucuda (en az iki kayıt ve ayar açıksa sunucu çok
oturumlu açılır); ek istemci açıkken sunucuyu yeniden başlatan işler reddedilir, sunucular son istemci kapanınca kapanır.
Güncelleme (guncelleme.py): açılıştan biraz sonra ve GUNCELLEME_SN'de bir GitHub'daki son sürüm denetlenir; panel ayarı 'guncelleme'
otomatikse ve oyun, sunucular, indirme ya da başka bir iş sürmüyorsa kurulur, ardından panel yeniden başlar (yeni süreç aynı portu
alır, açık pencere sayfayı yeniler).
Linux ve macOS: istemci Wine ya da Proton ile açılır (calistirici.py, İstemci sayfasının Wine / Proton kartı); macOS'ta Otomatik
panelin kendi kurduğu Wine + DXMT'dir (wine_motoru.py: ilk OYNA'da, istemci indirilirken ya da İstemci sayfasından iner; Apple
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
import uyum                   # noqa: E402
uyum.sertifikalar()           # macOS: python.org Python'unun kök sertifikası yoksa sistemin paketi (HTTPS'ten önce; sunucular devralır)
import yollar as YOL          # noqa: E402
import ayar as AY             # noqa: E402
import dil as D               # noqa: E402
from dil import t as _        # noqa: E402
import istemci as IST         # noqa: E402
import calistirici as CAL     # noqa: E402
import istemci_yama as YAMA   # noqa: E402
import surecler as SR         # noqa: E402
from kayitlar import Kayitlar, KayitHatasi, FIRMALAR  # noqa: E402
from yapilandirma import PanelConfig  # noqa: E402
from protokol import Uyarlayici  # noqa: E402
from indirme import Indirici, IndirmeHatasi  # noqa: E402
from guncelleme import Guncelleyici, GuncellemeHatasi  # noqa: E402
from arkadas import Arkadas, ArkadasHatasi  # noqa: E402
from coklu import Coklu, CokluHatasi  # noqa: E402
import dunyalar as DW          # noqa: E402
import botlar as BT            # noqa: E402  (Botlar sayfası: bot paketleri)
import llm_kurulum as LLMK     # noqa: E402  (Gelişmiş bot kipinin dil modeli)
import discord_rp as DRP       # noqa: E402  (Discord Rich Presence)
from bot import llm_saglayici as SG  # noqa: E402  (dil modelinin sağlayıcısı: dahili ya da kullanıcının seçtiği)

SURUM = '1.0'
DISCORD = 'https://discord.com/invite/openorbit'   # topluluk sunucusu (Panel sayfası, README); kalıcı davet
BAGIS = 'https://buymeacoffee.com/kaanumay'       # destek bağlantısı (kenar çubuğunun en altı)
PORT = 8077
ARAYUZ = os.path.join(PANEL_DIR, 'arayuz')
SABLONLAR = os.path.join(YOL.SAVE, 'ayar_sablonlari.json')
TARAYICI_PROFILI = os.path.join(os.environ.get('LOCALAPPDATA') or YOL.SAVE, 'DarkOrbitPanel', 'tarayici')
GUNLUKLER = ('gs.log', 'http.log', 'client.log', 'oyun_konsol.log', 'web_konsol.log', 'panel.log', 'errors.log', 'unknown.log') + (
    () if os.name == 'nt' else ('wine.log',))      # Linux ve macOS: Wine'ın / Proton'un çıktısı (surecler.istemci_ac)
EK_GUNLUK = re.compile(r'client_[a-z0-9_]{1,40}\.log')          # çoklu istemcinin ek istemcilerinin günlükleri (coklu.py)
NABIZ_SN = 180                      # tarayıcı penceresi izlenemiyorsa: bu kadar istek gelmezse pencere kapandı sayılır (monotonic:
                                    # macOS ve Linux'ta uykuda geçen süre sayılmaz)
DEVIR_SN = 10                       # tarayıcı süreci bundan önce çıkarsa pencereyi açık bir sürece devretmiştir (watch_window)
GUNCELLEME_SN = 6 * 3600            # GitHub'da yeni sürüm denetimi aralığı (başarısızsa bir saat sonra yeniden)
ETKINLIK_ACIKLAMA = {
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
GUNLER = {'tr': ('Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'), 'en': ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'),
          'de': ('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'), 'es': ('lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'),
          'fr': ('lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'), 'pl': ('pon', 'wt', 'śr', 'czw', 'pt', 'sob', 'niedz'),
          'pt': ('seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'), 'ru': ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')}
AYLAR = {'tr': ('Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'),
         'en': ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'),
         'de': ('Jan.', 'Feb.', 'März', 'Apr.', 'Mai', 'Juni', 'Juli', 'Aug.', 'Sept.', 'Okt.', 'Nov.', 'Dez.'),
         'es': ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sept', 'oct', 'nov', 'dic'),
         'fr': ('janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'),
         'pl': ('sty', 'lut', 'mar', 'kwi', 'maj', 'cze', 'lip', 'sie', 'wrz', 'paź', 'lis', 'gru'),
         'pt': ('jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'),
         'ru': ('янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек')}

os.makedirs(YOL.LOGS, exist_ok=True)
_log_lock = threading.Lock()


def log(text):
    with _log_lock:
        try:
            with open(os.path.join(YOL.LOGS, 'panel.log'), 'a', encoding='utf8') as fh:
                fh.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
        except OSError:
            pass


CFG = PanelConfig(YOL.PANEL)
D.bagla(lambda: CFG.get('dil'))
YON = SR.Yonetici(YOL.LOGS, log)
KAY = Kayitlar(CFG, python=SR.python_exe())
ARK = Arkadas(CFG, KAY, YON, log, SURUM)                        # Arkadaşlarınla Oyna: Host ve Join (arkadas.py)
COK = Coklu(CFG, KAY, YON, lambda: ARK.anahtar, YOL.LOGS, log)  # çoklu istemci: öteki kayıtlarla ek istemciler (coklu.py)
KAY.in_use = lambda slot: (YON.running() and YON.slot == slot) or ARK.kullanimda(slot) or COK.kullanimda(slot)
UYAR = Uyarlayici(ROOT, SR.python_exe(), log, SR.NO_WINDOW)    # yeni istemciye protokol uyarlaması (protokol.py)
UPD = Guncelleyici(ROOT, YOL.SAVE, log)                          # GitHub'dan güncelleme (guncelleme.py)
MOT = CAL.motor()                                                # macOS: panelin kurduğu Wine + DXMT (wine_motoru.py)
MOT.log = log
YAM = YAMA.Yamaci(log)                                           # istemcinin düzeltmelerini yükleyen BepInEx (istemci_yama.py)
TOKEN = secrets.token_hex(16)
STATE = {'oyna': {'calisiyor': False, 'adimlar': [], 'hata': None, 'bitti': None, 'sadece_sunucu': False},
         'nabiz': time.monotonic(), 'pencere_kapandi': False, 'pencere_izleniyor': False, 'son_yedek': 0.0, 'kapaniyor': False,
         'sonraki_denetim': time.time() + 8, 'guncellendi': '--guncellendi' in sys.argv, 'srv': None, 'acilis': time.time()}


def rp_kaynak():
    """Discord Rich Presence'ın kaynağı (discord_rp.py) -> (canlı durum ya da None, panelin durumu)."""
    canli = read_json(os.path.join(YOL.LOGS, 'canli_durum.json'), None) if YON.running() else None
    if canli and time.time() - canli.get('zaman', 0) > 15:
        canli = None
    if YON.client_alive():
        return canli, 'oyunda' if canli and canli.get('bagli') else 'arkadas' if ARK.m['durum'] == 'oyunda' else 'giris'
    return None, 'baslatiliyor' if STATE['oyna']['calisiyor'] else 'panel'


RP = DRP.Sunum(CFG, rp_kaynak, _, log)


class Hata(Exception):
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


def world_id(slot, arkadas=False):
    """Sunucunun dünyası: arkadaş sunucusunda Host'un seçtiği (panel ayarı arkadas_dunya), yoksa kaydın varsayılan dünyası."""
    secim = CFG.get('arkadas_dunya') if arkadas else None
    if secim and DW.var(secim):
        return secim
    return KAY.meta(slot).get('dunya') if slot else None


def world_file(slot, arkadas=False):
    """Sunucunun dünya dosyası (Dünya Editörü; DO_DUNYA) ya da None (standart dünya, silinmiş dünya)."""
    return DW.dosya_yolu(world_id(slot, arkadas))


def bot_file(slot, arkadas=False):
    """Sunucunun bot paketi (Botlar sayfası; DO_BOT): kaydın dünyasına atanmış paket ya da None."""
    return BT.dosya_yolu(BT.dunya_paketi(world_id(slot, arkadas) or DW.STANDART))


def world_info(wid):
    """Oyna sayfasının dünya çipi: {id, ad, kapak, degisiklik}; silinmiş dünya standart sayılır."""
    try:
        w = DW.ozet(wid if wid and DW.var(wid) else DW.STANDART)
    except DW.DunyaHatasi:
        w = DW.ozet(DW.STANDART)
    return {'id': w['id'], 'ad': w['ad'], 'kapak': w['kapak'], 'degisiklik': 0 if w['standart'] else w['degisiklik'], 'standart': w['standart']}


def world_users():
    """Dünya -> onu varsayılan yapan kayıtlar [{id, ad, pilot}]."""
    out = {}
    for k in KAY.list():
        w = k.get('dunya') if k.get('dunya') and DW.var(k.get('dunya')) else DW.STANDART
        out.setdefault(w, []).append({'id': k['id'], 'ad': k.get('ad'), 'pilot': k.get('pilot')})
    return out


def settings_file(slot=None):
    """Oyun ayarlarının dosyası: kaydın kendi ayarları (etkin kayıt; kayıt yoksa eski ortak dosya)."""
    slot = slot or KAY.active()
    return KAY.settings(slot) if slot else YOL.AYARLAR


def game_settings():
    return AY.read(settings_file())


def client_folder():
    return IST.resolve(CFG.get('istemci_klasoru'))


# ------------------------------------------------------------------ oyun menüleri (Mağaza)
# Oyun açıkken panel oyunu oyun sunucusunun yerel kanalından değiştirir (server/panel_kanali.py; anahtar günlük klasöründe).
# Görseller istemcinin BepInEx eklentisinin dökümü (eklenti/Gorseller.cs: <istemci>/BepInEx/openorbit/gorsel), /oyun_gorsel/ altında.
def paket_acik(pid):
    """Bot paketi şu an çalışan oyunda mı."""
    return bool(YON.running() and getattr(YON, 'bot', None) and BT.dosya_yolu(pid)
                and YON.bot[0] == os.path.normcase(BT.dosya_yolu(pid)))


def oyun_kanali(yol, govde=None):
    k = read_json(os.path.join(YOL.LOGS, 'panel_kanali.json'), None)
    if not k or not YON.running():
        raise Hata(_('Oyun açık değil.'))
    req = Request('http://127.0.0.1:%d%s' % (k['port'], yol), data=None if govde is None else json.dumps(govde).encode('utf8'),
                  headers={'X-Anahtar': k['anahtar'], 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=10) as r:
            return json.load(r)
    except HTTPError as e:
        if e.code == 409:
            raise Hata(_('Oyuna giriş yapınca açılır.'))
        raise Hata(_('Oyun sunucusu isteği reddetti (%s).', e.code))
    except OSError:
        raise Hata(_('Oyun sunucusuna bağlanılamadı.'))


def oyun_gorsel(ad):
    """Eklentinin döktüğü atlas sayfası, dizin ya da ad dosyası -> yol (yoksa None)."""
    if not re.fullmatch(r'[\w.-]+\.(png|json)', ad) or not client_folder():
        return None
    p = os.path.join(client_folder(), 'BepInEx', 'openorbit', 'gorsel', ad)
    return p if os.path.isfile(p) else None


def _downloaded(path):
    """İndirme bitti: kullanılan istemci geçersizse ya da güncelleniyorsa yeni klasör kullanılsın (kendiliğinden bulunuyorsa ayar boş
    kalır); güncellemede eski klasör silinir."""
    eski = STATE.pop('istemci_eski', None)
    if eski or not IST.check(client_folder())['gecerli']:
        auto = IST.resolve(None)
        same = auto and os.path.normcase(os.path.normpath(auto)) == os.path.normcase(os.path.normpath(path))
        CFG.update({'istemci_klasoru': None if same else path})
    if eski:
        eski_istemciyi_sil(eski, path)
    YAM.start(path)                                   # istemcinin düzeltmeleri için BepInEx (istemci_yama.py)


def eski_istemciyi_sil(eski, yeni):
    """İstemci güncellemesi: eski sürümün klasörünü sil. Yalnız arşivden açılmış DarkOrbit_Version… klasörü: resmî kurulumu kendi
    başlatıcısı günceller, ona dokunulmaz."""
    if (os.path.normcase(os.path.normpath(eski)) == os.path.normcase(os.path.normpath(yeni))
            or not re.match(r'DarkOrbit_Version\d', os.path.basename(os.path.normpath(eski))) or not IST.check(eski)['gecerli']):
        log('eski istemci silinmedi: %s' % eski)
        return
    try:
        shutil.rmtree(eski)
        log('eski istemci silindi: %s' % eski)
    except OSError as e:
        log('eski istemci silinemedi: %s: %r' % (eski, e))


DL = Indirici(ROOT, IST.check, log, on_done=_downloaded)       # oyun istemcisini indirme (indirme.py)
LLM = LLMK.LlmKurulum(log)                                       # botların dil modeli (llm_kurulum.py)


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
                raise Hata(_('Dosya penceresi için tkinter gerekir (Debian/Ubuntu: sudo apt install python3-tk).'))
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
        raise Hata(_('Klasör yok: %s', path))
    if os.name == 'nt':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])


# ------------------------------------------------------------------ etkinlikler
def _period_text(a, b, lang):
    (ma, da), (mb, db) = (a.month, a.day), (b.month, b.day)
    months = AYLAR[lang]
    if lang == 'en':
        return '%s %d – %s %d' % (months[ma - 1], da, months[mb - 1], db)
    return '%d%s %s – %d%s %s' % (da, '.' * (lang == 'de'), months[ma - 1], db, '.' * (lang == 'de'), months[mb - 1])


def event_list():
    import takvim as TK
    lang = D.current()
    now = time.time()
    t = datetime.datetime.fromtimestamp(now)
    sel = game_settings().get('etkinlikler') or {}
    out = []
    for key, e in TK.EVENTS.items():
        yearly = 'donemler' in e
        if yearly:                                      # önümüzdeki yılın dönemleri (takvim.upcoming; bitiş günü dahil)
            spans = TK.upcoming(key, now)
            when = ', '.join(_period_text(a, b - datetime.timedelta(days=1), lang) for a, b in spans[:4]) + (
                ' …' if len(spans) > 4 else '') or _('Takvimde yeni dönemi yok')
        else:
            days = e.get('gunler', range(7))
            when = (_('Her gün') if len(list(days)) == 7 else ', '.join(GUNLER[lang][d] for d in days))
            hrs = e.get('saatler')
            if hrs:
                when += ' ' + ', '.join('%02d:00–%02d:00' % (a, b) for a, b in hrs)
            if e.get('ay_haftasi'):
                when += ' ' + _('(ayın %s. haftası)', '/'.join(map(str, e['ay_haftasi'])))
            if e.get('hafta_dongu'):
                when += ' ' + _('(%s haftada bir)', e['hafta_dongu'][0])
        per = TK.period(key, now)
        nxt = None
        if yearly and not per:
            best = next((s for s, f in spans if s > t), None)
            nxt = (best - t).days + 1 if best else None
        st = sel.get(key)
        out.append({'anahtar': key, 'ad': _(e.get('ad', key)), 'tur': 'yillik' if yearly else 'haftalik', 'zaman': when,
                    'takvimde': per is not None, 'kalan_sn': int(per[1] - now) if per else None, 'sonraki_gun': nxt,
                    'durum': st, 'etkin': (st == 'acik') if st else per is not None,
                    'aciklama': _(ETKINLIK_ACIKLAMA.get(key, '')),
                    'cakisan': sorted(_(TK.EVENTS[j].get('ad', j)) for j in TK.CONFLICTS[key])})
    # çakışma (takvim.resolve): aynı anda açık çakışanlardan elle açılan, yoksa önce başlayan kalır
    rows = {x['anahtar']: x for x in out}
    on = {k for k, x in rows.items() if x['etkin']}
    keep = TK.resolve(on, lambda k: (rows[k]['durum'] != 'acik', (TK.period(k, now) or (0,))[0], k))
    for k in on - keep:
        rows[k]['etkin'] = False
        rows[k]['bastiran'] = next(rows[j]['ad'] for j in sorted(keep, key=lambda j: rows[j]['ad']) if j in TK.CONFLICTS[k])
    out.sort(key=lambda x: (x['tur'] != 'yillik', not x['etkin'], x['ad'].lower()))
    return out


SEANS_ADLARI = {'vortex': 'Vortex seansı', 'dunya_patronu': 'Patron savaşı', 'kristallon': 'Apotheosis penceresi',
                'mimesis': 'Mimesis seferi', 'unvan_avi': 'Prestige unvanı avı', 'uzayli': 'Etkinlik uzaylıları',
                'kutu': 'Etkinlik kutuları', 'harita': 'Harita etkinliği'}


def api_calendar(q):
    """Etkinlik takvimi (takvim_cizelge.py): [bas, bit) içindeki takvim ve etkin aralıklar, seanslar, şimdiki ya da sonraki dönem."""
    import takvim_cizelge as TC
    now = time.time()
    try:
        a, b = float(q.get('bas')), float(q.get('bit'))
    except (TypeError, ValueError):
        raise Hata(_('Geçersiz tarih aralığı.'))
    if not 0 < b - a <= 62 * 86400:
        raise Hata(_('Geçersiz tarih aralığı.'))
    hep = bool(game_settings().get('seans_hep_acik'))
    evs = event_list()
    c = TC.cizelge(a, b, hep, {e['anahtar']: e['durum'] for e in evs})
    out = []
    for e in evs:
        x = c[e['anahtar']]
        seans = [dict(s, ad=_(SEANS_ADLARI[s['kimlik'] if s['tur'] == 'seans' else s['tur']])) for s in x['seanslar']]
        out.append(dict(e, araliklar=x['araliklar'], etkin_araliklar=x['etkin'], seanslar=seans,
                        sonraki=TC.sonraki(e['anahtar'], now, 400 if e['tur'] == 'yillik' else 70)))
    return {'simdi': now, 'bas': a, 'bit': b, 'hep_acik': hep, 'etkinlikler': out}


def settings_summary(values):
    """Varsayılandan farklı oyun ayarları [{'ad', 'deger'}] (Oyna sayfasının çipleri; ayar.summary'nin panel dilindeki hâli)."""
    d = AY.clean(values)
    out = []
    for s in AY.SCHEMA:
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
        out.append({'ad': AY.tam_ad(s, _), 'deger': text})
    return out


def set_events(body):
    vals = game_settings()
    ev = dict(vals.get('etkinlikler') or {})
    import takvim as TK
    if 'hepsi' in body:
        to = body['hepsi']
        for k, e in TK.EVENTS.items():
            if body.get('tur') and body['tur'] != ('yillik' if 'donemler' in e else 'haftalik'):
                continue
            if to in AY.ETKINLIK_DURUMLARI:
                ev[k] = to
            else:
                ev.pop(k, None)
    for k, v in (body.get('degisiklik') or {}).items():
        if k not in TK.EVENTS:
            continue
        if v in AY.ETKINLIK_DURUMLARI:
            ev[k] = v
        else:
            ev.pop(k, None)
        if v == 'acik':                             # çakışan elle açıklar takvime döner (takvim.CONFLICTS)
            for j in TK.CONFLICTS[k]:
                if ev.get(j) == 'acik':
                    ev.pop(j)
    vals['etkinlikler'] = ev
    AY.write(settings_file(), vals)
    return event_list()


# ------------------------------------------------------------------ uyarılar ve durum
def try_migrate():
    """Eski tek kayıt (save/profil.json) varsa yuvaya taşı; portlar açıksa (o profille açılmış bir sunucu olabilir) sonraya."""
    if not os.path.isfile(YOL.ESKI_PROFIL) or YON.running():
        return None
    table = SR.listeners()
    if any(SR.listening(p, table) for p in (8081, 8090)):
        if not STATE.get('tasima_bekliyor'):
            log('eski kayıt taşınmadı: oyun portları açık (Baslat.bat ile açılmış bir sunucu kullanıyor olabilir)')
        STATE['tasima_bekliyor'] = True
        return None
    STATE['tasima_bekliyor'] = False
    moved = KAY.migrate()
    if moved:
        log('eski kayıt (save/profil.json) yuvaya taşındı: %s' % moved)
    return moved


def warnings():
    out = []
    if STATE.get('tasima_bekliyor'):
        out.append({'tur': 'uyari', 'metin': _('Eski kaydın (server/save/profil.json) kayıt yuvasına taşınması bekliyor: önce dışarıda açık '
                                               'olan sunucuyu kapatın (Sunucu > Portlar).'), 'sayfa': 'sunucu'})
    if ARK.aktif():
        out.append({'tur': 'uyari', 'metin': _('Arkadaşının sunucusundasın (%s): Oyna kapalı. Ayrılmak için Arkadaşlarınla Oyna sayfası.',
                                               ARK.m['adres']), 'sayfa': 'arkadas'})
    slot = KAY.active()
    if not slot:
        out.append({'tur': 'hata', 'metin': _('Henüz kayıt yok: Kayıtlar sayfasından yeni bir kayıt oluşturun.'), 'sayfa': 'kayitlar'})
    c = IST.check(client_folder())
    if not c['gecerli'] and DL.running():
        out.append({'tur': 'uyari', 'metin': _('Oyun istemcisi indiriliyor: %%%d. Bitince oynayabilirsin.', _dl_pct(DL.state())),
                    'sayfa': 'istemci'})
    elif not c['gecerli']:
        out.append({'tur': 'hata', 'metin': _('Oyun istemcisi bulunamadı: %s İstemci sayfasından klasörü seçin ya da oyunu indirin.',
                                              ' '.join(c['sorunlar'])), 'sayfa': 'istemci'})
    elif c['eski']:                                                  # yeni sürüm çıktı: tek tıkla güncellenir (/api/istemci/guncelle)
        dl, sup = DL.state(), IST.supported()
        run = bool(STATE.get('istemci_eski')) and dl['calisiyor']
        metin = (_('Oyun %s sürümüne güncelleniyor: %%%d. Bitince eski sürüm silinir ve BepInEx yeniden kurulur.', sup, _dl_pct(dl))
                 if run else _('DarkOrbit %s sürümü çıktı, istemcin %s: güncellemezsen oyun düzgün çalışmaz. Güncelle yenisini indirip '
                               'kurar, eskisini siler.', sup, c['surum']))
        if STATE.get('istemci_eski') and dl['durum'] == 'hata':
            metin += ' ' + dl['hata']
        out.append({'tur': 'hata', 'metin': metin, 'ilerleme': _dl_pct(dl) if run else None, 'indirme': dl if run else None,
                    'sayfa': 'istemci',
                    'eylem': {'metin': _('Güncelle'), 'api': '/api/istemci/guncelle', 'calisiyor': run,
                              'calisiyor_metin': _('Güncelleniyor…')}})
    elif not c['uyumlu']:
        out.append({'tur': 'uyari', 'metin': c['sorunlar'][-1], 'sayfa': 'istemci'})
    hata = CAL.bul(CFG)['hata']                                      # Linux ve macOS: Wine ya da Proton (Apple Silicon'da Rosetta)
    if hata:
        w = {'tur': 'hata', 'metin': hata, 'sayfa': 'istemci'}
        if CAL.rosetta_hatasi():
            ros = MOT.state()['rosetta']
            w['eylem'] = {'metin': _("Rosetta'yı kur"), 'api': '/api/rosetta/kur', 'calisiyor': ros['durum'] == 'kuruluyor'}
            if ros['hata']:
                w['metin'] += ' ' + ros['hata']
        out.append(w)
    m = MOT.state() if sys.platform == 'darwin' else None
    if m and m['calisiyor']:
        out.append({'tur': 'uyari', 'metin': _('Wine ve DXMT indiriliyor: %%%d. Bitince oynayabilirsin.',
                                               int(100 * m['alinan'] / m['toplam']) if m['toplam'] else 0), 'sayfa': 'istemci'})
    elif m and m['durum'] == 'hata':
        out.append({'tur': 'hata', 'metin': _("Panelin Wine'ı kurulamadı: %s", m['hata']), 'sayfa': 'istemci'})
    hata = SR.port_80_sorunu()
    if hata:
        out.append({'tur': 'hata', 'metin': hata, 'sayfa': 'sunucu'})
    missing = [n for n in YOL.SABLONLAR if not YOL.sablon(n)]       # kendi kaydın ya da paylaşılabilir kopya (data/varsayilan)
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
    alive = YON.servers_alive()
    table = SR.listeners()
    foreign = [p for ad, ports in SR.PORTS.items() for p in ports if not alive.get(ad) and SR.listening(p, table)]
    if foreign:
        out.append({'tur': 'uyari', 'metin': _('Panelin açmadığı bir süreç oyun portlarını tutuyor (%s). Önceki oturumdan kalan bir '
                                               'sunucu olabilir: Sunucu sayfasından inceleyin.', ', '.join(map(str, foreign))),
                    'sayfa': 'sunucu'})
    for ad, s in YON.sunucular.items():
        if s.crashed:
            out.append({'tur': 'hata', 'metin': _('%s sunucusu beklenmedik biçimde kapandı (çıkış kodu %s). Ayrıntı: Sunucu > Günlükler > '
                                                  '%s_konsol.log', _({'oyun': 'Oyun', 'web': 'Web'}[ad]), s.proc.poll(), ad),
                        'sayfa': 'sunucu'})
    return out


def status():
    STATE['nabiz'] = time.monotonic()
    STATE['pencere_kapandi'] = False                  # bir pencere yine soruyor (ikinci başlatmanın açtığı da)
    if STATE.get('tasima_bekliyor'):
        try_migrate()
    slot = KAY.active()
    try:
        aktif = KAY.summary(slot) if slot else None
    except (OSError, KayitHatasi):
        aktif = None
    if aktif:
        aktif['dunya_bilgi'] = world_info(aktif.get('dunya'))
    vals = game_settings()
    ev = [e['ad'] for e in event_list() if e['etkin'] and e['tur'] == 'yillik']
    slots = KAY.slots()
    return {'surecler': YON.status(), 'aktif': aktif, 'kayit_sayisi': len(slots),
            'ayar_ozet': settings_summary(vals), 'etkinlikler': ev,
            'uyarilar': warnings(), 'oyna': STATE['oyna'], 'istemci_klasoru': client_folder(),
            'arkadas': {'host': YON.running() and YON.arkadas, 'misafir': ARK.m['durum'], 'adres': ARK.m['adres']},
            'coklu': coklu_durumu(slots),
            'panel': {'surum': SURUM, 'pencere_kapandi': STATE['pencere_kapandi'], 'dil': CFG.get('dil'), 'platform': sys.platform,
                      'kurulum_tamam': CFG.get('kurulum_tamam'), 'guncellendi': STATE['guncellendi'],
                      'acik_sn': int(time.time() - STATE['acilis'])}}


# ------------------------------------------------------------------ çoklu istemci (coklu.py)
def coklu_ortam():
    """Çoklu istemcinin oyun sunucusu ayarları (DO_COK_OYUNCULU; cok_oyunculu.configure): yalnız bu bilgisayar, misafir yok."""
    return json.dumps({'adres': '127.0.0.1', 'misafir': False, 'anahtar': ARK.anahtar, 'kod': SURUM, 'yerel': ARK.yerel})


def coklu_istenir(slot):
    """OYNA sunucuyu çok oturumlu açsın mı: ayar açık ve en az iki kayıt var (tek kaydı olanın sunucusu tek oyunculu kalır), ya da
    sunucu bu kayıtla zaten öyle açık."""
    return bool(CFG.get('coklu_istemci') and len(KAY.slots()) > 1) or (YON.running() and YON.coklu and YON.slot == slot)


def coklu_durumu(slots):
    """Oyna sayfasının Çoklu istemci kartı: açık ek istemciler, son kapanışlar ve ek istemcide açılabilecek kayıtlar."""
    canli = read_json(os.path.join(YOL.LOGS, 'canli_durum.json'), None) if COK.canli() else None
    out = dict(COK.durum(canli), ayar=CFG.get('coklu_istemci'), en_cok=CFG.get('coklu_en_cok'), kayit_sayisi=len(slots),
               sunucu=YON.running() and (YON.coklu or YON.arkadas), ana=YON.slot if YON.running() else None, kayitlar=[])
    if out['ayar'] and len(slots) > 1:
        for s in slots:
            try:
                k = KAY.summary(s)
            except (OSError, KayitHatasi):
                continue
            out['kayitlar'].append({'id': s, 'ad': k['ad'], 'pilot': k.get('pilot'), 'seviye': k.get('seviye'), 'firma': k.get('firma'),
                                    'bozuk': k.get('bozuk'), 'ek': COK.kullanimda(s), 'arkadas': ARK.kullanimda(s)})
    return out


def open_extra(b):
    """Çoklu istemci: başka bir kayıtla ek istemci. Sunucu çok oturumlu açık olmalı; tek oyunculu açıksa ve oyun kapalıysa öyle
    yeniden başlatılır."""
    slot = str(b.get('kayit') or '')
    if not slot or not KAY.exists(slot):
        raise Hata(_('Kayıt bulunamadı.'))
    if not CFG.get('coklu_istemci'):
        raise Hata(_('Çoklu istemci kapalı: İstemci sayfasından açabilirsin.'))
    if ARK.aktif():
        raise Hata(_('Arkadaşının sunucusundayken ek istemci açılamaz.'))
    if STATE['oyna']['calisiyor']:
        raise Hata(_('Başlatma sürüyor.'))
    if not YON.running():
        raise Hata(_('Önce OYNA ile oyunu (ya da yalnız sunucuyu) başlat: ek istemciler aynı sunucuya bağlanır.'))
    if ARK.kullanimda(slot):
        raise Hata(_('Bu kayıt arkadaşının sunucusunda kullanılıyor.'))
    if not (YON.coklu or YON.arkadas):
        if YON.client_alive() or COK.canli():
            raise Hata(_('Sunucu tek oyunculu açıldı: ek istemci için oyunu kapatıp yeniden OYNA\'ya bas.'))
        log('çoklu istemci: sunucu çok oturumlu yeniden başlatılıyor')
        YON.start_servers(KAY.profile(YON.slot), settings_file(YON.slot), kontrol=bool(AY.read(settings_file(YON.slot)).get('kontrol')), slot=YON.slot,
                          coklu=coklu_ortam(), dunya=world_file(YON.slot), bot=bot_file(YON.slot))
    return COK.ac(slot, client_folder(), YON.slot)


def istemciler_kapandi():
    """Ana istemci ya da bir ek istemci kapandı: hepsi kapandıysa panelin davranışı (sunucuları kapat, pencere kapandıysa çık). Ana
    istemci bu sunucu oturumunda açılmadıysa (yalnız sunucu) ya da erken kapandıysa sunucular açık kalır."""
    if YON.client_alive() or COK.canli():
        return                                        # bir istemci sürüyor: sunucular açık kalır
    oyun, son = YON.sunucular.get('oyun'), YON.istemci_son
    if not (oyun and oyun.alive and YON.istemci_basla and YON.istemci_basla >= oyun.basla and son and not son['erken']):
        return
    if CFG.get('istemci_kapaninca') == 'kapat':
        YON.stop_servers()
    if STATE['pencere_kapandi']:
        threading.Thread(target=shutdown, daemon=True).start()


COK.on_exit = istemciler_kapandi


# ------------------------------------------------------------------ oyna
def _step(text, durum='calisiyor'):
    o = STATE['oyna']
    if o['adimlar'] and o['adimlar'][-1]['durum'] == 'calisiyor':
        o['adimlar'][-1]['durum'] = 'tamam'
    o['adimlar'].append({'metin': text, 'durum': durum, 'zaman': time.strftime('%H:%M:%S')})


def launch(sadece_sunucu=False, arkadas=False):
    o = STATE['oyna']
    try:
        _step(_('Denetleniyor'))
        if ARK.aktif():
            raise Hata(_('Arkadaşının sunucusundasın: önce oradan ayrıl.'))
        if arkadas and YON.running() and not YON.arkadas and YON.client_alive():
            raise Hata(_('Önce oyunu kapat: sunucu arkadaş sunucusu olarak yeniden başlamalı.'))
        slot = KAY.active()
        if not slot:
            raise Hata(_('Önce Kayıtlar sayfasından bir kayıt oluşturun.'))
        if COK.kullanimda(slot):
            raise Hata(_('Etkin kayıt bir ek istemcide açık: önce o istemciyi kapat ya da başka bir kaydı etkin yap.'))
        folder = client_folder()
        if not sadece_sunucu:
            c = IST.check(folder)
            if STATE.get('istemci_eski') and DL.running():
                raise Hata(_('Oyun %s sürümüne güncelleniyor (%%%d). Bitince oynayabilirsin.', IST.supported(), _dl_pct(DL.state())))
            if not c['gecerli'] and DL.running():
                raise Hata(_('Oyun istemcisi henüz iniyor (%%%d). Bitince oynayabilirsin.', _dl_pct(DL.state())))
            if not c['gecerli']:
                raise Hata(_('İstemci klasörü geçersiz: %s', ' '.join(c['sorunlar'])))
            if YON.client_alive():
                raise Hata(_('Oyun zaten açık.'))
            others = IST.running_clients(COK.pids())                     # panelin ek istemcileri sayılmaz
            if others:
                raise Hata(_('Başka bir DarkOrbit istemcisi açık (süreç %s). Önce onu kapatın.', ', '.join(map(str, others))))
            r = CAL.bul(CFG)
            if r['tur'] == 'motor' and not r['hata'] and not r['yol']:      # macOS: panelin Wine'ı ilk OYNA'da iner (wine_motoru.py)
                _step(_('Wine ve DXMT indiriliyor'))
                MOT.bekle(lambda pct: STATE['oyna']['adimlar'][-1].update(metin=_('Wine ve DXMT indiriliyor: %%%d', pct)))
            if not YAMA.kurulu(folder):                   # istemcinin düzeltmeleri: BepInEx sihirbazda kurulmadıysa ilk OYNA'da
                _step(_('BepInEx kuruluyor'))
                if not YAM.bekle(folder, lambda pct: o['adimlar'][-1].update(metin=_('BepInEx kuruluyor: %%%d', pct))):
                    o['adimlar'][-1].update(metin=_('BepInEx kurulamadı, oyun düzeltmeler olmadan açılır: %s',
                                                    YAM.state(folder)['hata']), durum='hata')
            cmd, env = IST.komut(CFG, folder, os.path.join(YOL.LOGS, 'client.log'))     # Wine / Proton yoksa sunucular açılmadan hata
            if YAMA.kurulu(folder) and not YAMA.hazir(folder):  # BepInEx'in interop derlemeleri oyundan önce (istemci_yama.isit)
                _step(_('BepInEx ilk açılışa hazırlanıyor (yarım dakika kadar)'))
                if not YAMA.isit(folder, cmd, env, YOL.LOGS, lambda d: o['adimlar'][-1].update(ilerleme=d)):
                    o['adimlar'][-1].update(metin=_('BepInEx hazırlanamadı, oyun yine de açılıyor'), durum='hata')
        prof = KAY.profile(slot)
        same = YON.running() and YON.slot == slot
        arkadas = arkadas or (YON.running() and YON.arkadas)    # açık arkadaş sunucusu Oyna ile kapanmaz (misafirler düşmesin)
        ark_env = ARK.host_ortam() if arkadas else None
        coklu = None if arkadas else (coklu_ortam() if coklu_istenir(slot) else None)
        restart = YON.needs_restart(prof, ark_env, coklu, world_file(slot, arkadas), bot_file(slot, arkadas))
        if restart and COK.canli():
            raise Hata(_('Ek istemciler açıkken sunucu yeniden başlatılamaz: önce onları kapatın.'))
        if CFG.get('yedek_acilista') and not same:
            _step(_('Kayıt yedekleniyor'))
            KAY.backup(slot, 'oto', _('Oyna (açılış)'))
            STATE['son_yedek'] = time.time()
        if not YON.running() and CFG.get('gunluk_dondur'):
            import baslat
            baslat.rotate_logs(YOL.LOGS, names=('gs.log', 'http.log', 'client.log', 'oyun_konsol.log', 'web_konsol.log',
                                                'panel.log'))
        _step((_('Arkadaş sunucusu başlatılıyor') if arkadas else _('Sunucular başlatılıyor'))
              if not YON.running() or restart else _('Sunucular açık'))
        YON.start_servers(prof, settings_file(slot), kontrol=bool(AY.read(settings_file(slot)).get('kontrol')), slot=slot, arkadas=ark_env,
                          coklu=coklu, dunya=world_file(slot, arkadas), bot=bot_file(slot, arkadas))
        if not sadece_sunucu:
            _step(_('Oyun açılıyor'))
            try:                                      # dünyanın görev başlıkları (eklentinin GorevMetinleri yaması okur)
                DW.metinleri_yaz(folder, world_id(slot, arkadas))
            except OSError as e:
                log('görev metinleri yazılamadı: %s' % e)
            YON.start_client(folder, cmd, env)
            if YON.coklu or YON.arkadas:              # birden çok istemci olabilir: pencereler pilotun adıyla ayırt edilsin
                SR.pencere_basligi(YON.istemci.pid, 'DarkOrbit — %s' % KAY.summary(slot).get('pilot', slot))
            m = KAY.meta(slot)
            KAY.set_meta(slot, son_oynama=time.strftime('%Y-%m-%d %H:%M:%S'), oynama_sayisi=int(m.get('oynama_sayisi') or 0) + 1)
        _step(_('Hazır') if sadece_sunucu else _('Oyun açıldı: iyi uçuşlar!'), 'tamam')
        o['bitti'] = time.time()
    except (Hata, KayitHatasi, RuntimeError, OSError) as e:
        o['hata'] = str(e)
        _step(str(e), 'hata')
        log('oyna hatası: %s' % e)
    except Exception as e:
        o['hata'] = _('Beklenmeyen hata: %r', e)
        _step(o['hata'], 'hata')
        log('oyna hatası: %s' % traceback.format_exc())
    finally:
        o['calisiyor'] = False


def start_launch(sadece_sunucu=False, arkadas=False):
    o = STATE['oyna']
    if o['calisiyor']:
        raise Hata(_('Başlatma sürüyor.'))
    o.update(calisiyor=True, adimlar=[], hata=None, bitti=None, sadece_sunucu=bool(sadece_sunucu))
    threading.Thread(target=launch, args=(sadece_sunucu, arkadas), daemon=True).start()
    return o


def join_friend(b):
    """Arkadaşlarınla Oyna > Join: denetimler panelde (istemci, açık oyun ve sunucular), katılma arka planda (arkadas.py)."""
    if STATE['oyna']['calisiyor']:
        raise Hata(_('Başlatma sürüyor.'))
    slot = str(b.get('kayit') or '') or KAY.active()
    if not slot or not KAY.exists(slot):
        raise Hata(_('Önce Kayıtlar sayfasından bir kayıt oluşturun.'))
    folder = client_folder()
    c = IST.check(folder)
    if not c['gecerli']:
        raise Hata(_('İstemci klasörü geçersiz: %s', ' '.join(c['sorunlar'])))
    if YON.client_alive() or IST.running_clients():
        raise Hata(_('Oyun zaten açık.'))
    if YON.running():
        raise Hata(_('Önce kendi sunucunu durdur (Oyna > Sunucuyu durdur).'))
    cmd, env = IST.komut(CFG, folder, os.path.join(YOL.LOGS, 'client.log'))

    def open_client():
        YON.start_client(folder, cmd, env)
        m = KAY.meta(slot)
        KAY.set_meta(slot, son_oynama=time.strftime('%Y-%m-%d %H:%M:%S'), oynama_sayisi=int(m.get('oynama_sayisi') or 0) + 1)
    return ARK.katil(str(b.get('adres') or ''), str(b.get('sifre') or ''), slot, c['surum'] or IST.supported(), open_client)


def on_client_exit(early):
    if ARK.istemci_kapandi():                         # arkadaşın sunucusundan ayrılınır, misafirin web sunucusu kapanır
        return
    if early:
        return
    istemciler_kapandi()                              # ek istemciler sürüyorsa sunucular açık kalır


YON.on_client_exit = on_client_exit


def idle(strict=False):
    """Güncelleme kurulabilir mi: oyun, sunucular, başlatma, istemci indirmesi, protokol aracı durmuş (strict: panelin
    açmadığı DarkOrbit istemcisi de yok; tasklist çalışır)."""
    busy = (YON.running() or YON.client_alive() or STATE['oyna']['calisiyor'] or DL.running() or UYAR.state()['calisiyor']
            or ARK.aktif() or COK.canli() or MOT.running() or YAM.running() or LLM.running())
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
        STATE['sonraki_denetim'] = now + (3600 if st['durum'] == 'hata' else GUNCELLEME_SN)
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
            if YON.client_alive() and YON.slot and iv and time.time() - STATE['son_yedek'] >= iv * 60:
                KAY.backup(YON.slot, 'oto', _('Oyun sırasında'))
                STATE['son_yedek'] = time.time()
            COK.yedekle(iv)                           # ek istemcilerin kayıtları
            if not STATE['pencere_izleniyor'] and time.monotonic() - STATE['nabiz'] > NABIZ_SN and not STATE['pencere_kapandi']:
                STATE['pencere_kapandi'] = True
                log('panel penceresi kapandı (sayfa artık sormuyor)')
                if CFG.get('pencere_kapaninca') == 'kapat':
                    YON.stop_client()
                    COK.hepsini_kapat(bekle=8)
            if STATE['pencere_kapandi'] and not YON.client_alive() and not COK.canli() and not STATE['oyna']['calisiyor']:
                shutdown()
        except Exception:
            log('zamanlayıcı hatası: %s' % traceback.format_exc())


def istemci_bekle(sn=8):
    """stop_client yalnız sinyal gönderir: istemci kapanana dek bekle (yoksa shutdown sunucuları açık bırakıp çıkıyordu)."""
    son = time.time() + sn
    while YON.client_alive() and time.time() < son:
        time.sleep(0.2)


def shutdown():
    if STATE['kapaniyor']:
        return
    STATE['kapaniyor'] = True
    log('panel kapanıyor')
    try:
        DL.cancel()                                   # indirme: açılmış dosyalar kalır, sonra kaldığı yerden
        MOT.cancel()
        if not YON.client_alive() and not COK.canli():
            ARK.kapanis()                             # arkadaşın sunucusundaysa ayrılınır (son hâl kayda)
            YON.stop_servers()
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
    os.makedirs(TARAYICI_PROFILI, exist_ok=True)
    return subprocess.Popen([b, '--app=%s' % url, '--user-data-dir=%s' % TARAYICI_PROFILI, '--window-size=1360,880',
                             '--no-first-run', '--no-default-browser-check', '--disable-features=Translate,msEdgeSidebarV2',
                             '--disable-background-mode', '--disable-sync', '--lang=%s' % D.DILLER[D.current()][1]])


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
    if time.time() - t0 < DEVIR_SN:
        # aynı profil klasörüyle açık bir tarayıcı süreci varsa yeni süreç pencereyi ona devredip hemen çıkar (18, 20 ve 22 Ekim:
        # panel açılır açılmaz "kapandı" sayılıp kapanıyordu): pencere açık, kapanışı sayfanın nabzından anlaşılır (ticker)
        STATE['nabiz'] = time.monotonic()
        log('panel penceresi açık bir tarayıcı sürecine devredildi; nabızla izleniyor')
        return
    log('panel penceresi kapandı')
    if CFG.get('pencere_kapaninca') == 'kapat':
        YON.stop_client()
        COK.hepsini_kapat(bekle=8)                   # ek istemcilerin son kaydı sunucuya bırakılsın
        istemci_bekle()
        shutdown()
    STATE['pencere_kapandi'] = True


KISAYOL, ESKI_KISAYOL = 'OpenOrbit.lnk', 'DarkOrbit.lnk'   # eski: 2026-10-24'ten önce konan (kaldırılan "DarkOrbit Panel.pyw"yi açar)


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
    p = os.path.join(desktop_dir(), ESKI_KISAYOL)
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
             'CFBundleExecutable': 'OpenOrbit', 'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': SURUM,
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
    """Panelin simgesi (arayuz/simge.png, 512x512) -> .icns; olmazsa None (uygulama genel simgeyle açılır)."""
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as tmp:
            big, iconset = os.path.join(ARAYUZ, 'simge.png'), os.path.join(tmp, 'OpenOrbit.iconset')
            run = lambda *a: subprocess.run(list(a), capture_output=True, timeout=30).returncode == 0
            os.makedirs(iconset)
            for n in (16, 32, 128, 256, 512):
                for k, suffix in ((1, ''), (2, '@2x')):
                    run('sips', '-z', str(n * k), str(n * k), big, '--out', os.path.join(iconset, 'icon_%dx%d%s.png' % (n, n, suffix)))
            return out if run('iconutil', '-c', 'icns', iconset, '-o', out) else None
    except (OSError, subprocess.SubprocessError):
        return None


def unix_shortcut():
    """Linux: masaüstüne ve uygulama menüsüne openorbit.desktop; macOS: masaüstüne OpenOrbit.app (mac_shortcut) -> masaüstündekinin
    yolu."""
    script = os.path.join(ROOT, 'OpenOrbit Panel.pyw')
    os.makedirs(desktop_dir(), exist_ok=True)
    if sys.platform == 'darwin':
        return mac_shortcut(script)
    text = ('[Desktop Entry]\nType=Application\nName=OpenOrbit\nComment=%s\nExec="%s" "%s"\nPath=%s\nIcon=%s\nTerminal=false\n'
            'Categories=Game;\n' % (_('OpenOrbit yerel sunucu paneli'), sys.executable, script, ROOT, os.path.join(ARAYUZ, 'simge.png')))
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
    icon = os.path.join(ARAYUZ, 'simge.ico')
    lnk = os.path.join(desktop_dir(), KISAYOL)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:DO_KISAYOL); $s.TargetPath=$env:DO_HEDEF; "
          "$s.Arguments=('\"'+$env:DO_BETIK+'\"'); $s.WorkingDirectory=$env:DO_KOK; $s.IconLocation=($env:DO_SIMGE+',0'); "
          "$s.Description=$env:DO_ACIKLAMA; $s.Save()")
    env = dict(os.environ, DO_KISAYOL=lnk, DO_HEDEF=target, DO_BETIK=script, DO_KOK=ROOT, DO_SIMGE=icon,
               DO_ACIKLAMA=_('OpenOrbit yerel sunucu paneli'))
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True, env=env,
                       timeout=30, creationflags=SR.NO_WINDOW, encoding='utf8', errors='replace')
    if r.returncode or not os.path.isfile(lnk):
        raise Hata(_('Kısayol oluşturulamadı: %s', r.stderr.strip()[-300:]))
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


def api_settings():
    hazir = {k: dict(p, ad=_(p['ad']), aciklama=_(p['aciklama'])) for k, p in AY.HAZIR.items()}
    slot = KAY.active()
    return {'sema': [_schema_row(s) for s in AY.SCHEMA], 'gruplar': [{'anahtar': k, 'ad': _(a)} for k, a in AY.GRUPLAR],
            'degerler': game_settings(), 'varsayilan': AY.DEFAULTS, 'hazir': hazir, 'sablonlar': read_json(SABLONLAR, {}),
            'sunucu_acik': YON.running(), 'kayit': slot, 'kayit_adi': KAY.meta(slot).get('ad', slot) if slot else None,
            'kayitlar': [{'id': s, 'ad': KAY.meta(s).get('ad', s)} for s in KAY.slots() if s != slot]}


def launch_command():
    """İstemci sayfasında gösterilen başlatma komutu (Linux ve macOS'ta Wine ya da Proton'la; bulunamadıysa yalnız istemcininki)."""
    if os.name == 'nt':
        folder = client_folder()
        return ['DarkOrbit.exe'] + IST.args(CFG, 'logs\\client.log') + (YAMA.ARGUMANLAR if folder and YAMA.kurulu(folder) else [])
    try:
        return IST.komut(CFG, client_folder() or ROOT, os.path.join(YOL.LOGS, 'client.log'), hazirla=False)[0]
    except RuntimeError:
        return [IST.EXE] + IST.args(CFG, 'logs/client.log')


def api_client():
    sel = CFG.get('istemci_klasoru')
    used = client_folder()
    return {'secili': sel, 'kullanilan': used, 'kontrol': IST.check(used), 'adaylar': IST.candidates(),
            'cozunurlukler': IST.COZUNURLUKLER, 'ekran': screen_size(), 'ayarlar': CFG.all(),
            'komut': launch_command(), 'calistirici': CAL.ozet(CFG), 'desteklenen': IST.supported(),
            'protokol': UYAR.state(), 'indirme': DL.state(), 'yama': YAM.state(used)}


def ek_gunlukler():
    """Ek istemcilerin günlükleri (logs/client_<kayıt>.log)."""
    try:
        return tuple(sorted(f for f in os.listdir(YOL.LOGS) if EK_GUNLUK.fullmatch(f)))
    except OSError:
        return ()


def slot_arg(q):
    sid = q.get('id')
    if not sid or not KAY.exists(sid):
        raise Hata(_('Kayıt bulunamadı.'))
    return sid


def profile_values(sid):
    d = read_json(KAY.profile(sid), {})
    pl, g = d.get('pilot') or {}, d.get('gemi') or {}
    return {'pilot': pl.get('userName', ''), 'kredi': pl.get('credits', 0), 'uridyum': pl.get('uridium', 0),
            'onur': pl.get('honourPoints', 0), 'ep': pl.get('ep', 0), 'seviye': pl.get('level', 1),
            'can': g.get('hitPoints', 0), 'can_azami': g.get('hitMax', 0), 'kalkan': g.get('shield', 0),
            'kalkan_azami': g.get('shieldMax', 0), 'firma': FIRMALAR.get(pl.get('factionId'), '?'),
            'kullanimda': KAY.in_use(sid)}


def dunyalar_durumu():
    users = world_users()
    return {'liste': DW.liste(users), 'kapaklar': DW.KAPAKLAR, 'sunucu_acik': YON.running(),
            'sunucu_dunyasi': YON.dunya[0] if YON.running() and YON.dunya else None, 'kayitlar': [
                {'id': k['id'], 'ad': k.get('ad'), 'pilot': k.get('pilot'), 'firma': k.get('firma'), 'seviye': k.get('seviye'),
                 'dunya': k.get('dunya') if k.get('dunya') and DW.var(k.get('dunya')) else DW.STANDART, 'aktif': k.get('aktif')}
                for k in KAY.list()]}


def dunya_arg(q):
    did = q.get('dunya') or DW.STANDART
    if not DW.var(did):
        raise Hata(_('Dünya bulunamadı.'))
    return did


def dunya_get(path, q):
    if path == '/api/dunyalar':
        return dunyalar_durumu()
    if path == '/api/dunya':
        did = dunya_arg(q)
        acik = bool(YON.running() and YON.dunya and DW.dosya_yolu(did) and YON.dunya[0] == os.path.normcase(DW.dosya_yolu(did)))
        # yeniden_gerekli: sunucu açıldıktan sonra oyun açıkken uygulanamayan bir değişiklik yapıldı (mağaza ve açık artırma canlı)
        return dict(DW.ozet(did, world_users()), sunucu_bu_dunyada=acik,
                    yeniden_gerekli=acik and SR.dunya_imzasi(DW.dosya_yolu(did)) != YON.dunya)
    if path == '/api/dunya/bolum':
        did, bol = dunya_arg(q), q.get('bolum')
        if bol == 'uzaylilar':
            return {'uzaylilar': DW.uzaylilar(did)}
        if bol == 'haritalar':
            return {'haritalar': DW.haritalar(did)}
        if bol == 'gorevler':
            return {'gorevler': DW.gorevler(did)}
        if bol == 'magaza':
            return {'kategoriler': DW.magaza(did), 'gorsel': bool(oyun_gorsel('dizin.json'))}
        if bol == 'muzayede':
            return DW.muzayede(did)
        if bol == 'kutular':
            return DW.kutular(did)
        if bol == 'kapilar':
            return {'kapilar': DW.kapilar(did)}
        if bol == 'ekonomi':
            return DW.ekonomi(did)
        if bol == 'etkinlikler':
            return {'etkinlikler': DW.etkinlikler(did), 'siniflar': DW.SINIFLAR}
        raise Hata(_('Bilinmeyen bölüm.'))
    if path == '/api/dunya/harita':
        return DW.harita(dunya_arg(q), q.get('id'))
    if path == '/api/dunya/gorev':
        return DW.gorev(dunya_arg(q), q.get('id'))
    if path == '/api/dunya/esyalar':
        return {'esyalar': DW.esya_listesi()}
    raise Hata(_('Bilinmeyen istek.'))


def dunya_post(path, b):
    if path == '/api/kayitlar/dunya':               # kaydın varsayılan dünyası (OYNA bununla açar)
        sid, did = b.get('id'), b.get('dunya') or DW.STANDART
        if not sid or not KAY.exists(sid):
            raise Hata(_('Kayıt bulunamadı.'))
        if not DW.var(did):
            raise Hata(_('Dünya bulunamadı.'))
        KAY.set_meta(sid, dunya=None if did == DW.STANDART else did)
        return dunyalar_durumu()
    if path == '/api/dunya/olustur':
        did = DW.olustur(b.get('ad'), b.get('aciklama', ''), b.get('kapak', 'nebula'), kaynak=b.get('kaynak'), taslaktan=bool(b.get('taslaktan')))
        if b.get('kayit') and KAY.exists(b['kayit']):  # oluşturunca bu kaydın varsayılanı yap
            KAY.set_meta(b['kayit'], dunya=did)
        return dict(dunyalar_durumu(), yeni=did)
    if path == '/api/dunya/guncelle':
        DW.guncelle(b.get('id'), ad=b.get('ad'), aciklama=b.get('aciklama'), kapak=b.get('kapak'))
        return dunyalar_durumu()
    if path == '/api/dunya/sil':
        did = b.get('id')
        DW.sil(did)
        for k in KAY.list():                        # varsayılanı bu dünya olan kayıtlar standarda döner
            if k.get('dunya') == did:
                KAY.set_meta(k['id'], dunya=None)
        return dunyalar_durumu()
    if path == '/api/dunya/kopyala':
        return dict(dunyalar_durumu(), yeni=DW.kopyala(b.get('id'), b.get('ad')))
    if path == '/api/dunya/taslak_at':
        DW.taslak_at()
        return dunyalar_durumu()
    if path == '/api/dunya/disari':
        did = dunya_arg(b)
        ad = re.sub(r'[^\w.-]+', '_', DW.oku(did).get('ad') or did)[:40]
        dest = dialog('kaydet', title=_('Dünyayı dışa aktar'), initialfile='%s.oodunya.json' % ad, defaultextension='.json',
                      filetypes=[(_('OpenOrbit dünyası'), '*.json')])
        if not dest:
            return {'iptal': True}
        write_json(dest, DW.disari(did))
        return {'yol': dest}
    if path == '/api/dunya/kod':                    # paylaşım kodu (Discord'a yapıştırılır)
        return {'kod': DW.kod(dunya_arg(b))}
    if path == '/api/dunya/iceri':                  # paylaşım kodundan ya da dosyadan
        if b.get('kod'):
            veri = DW.koddan(b['kod'])
        else:
            src = dialog('ac', title=_('Dünya içe aktar'), filetypes=[(_('OpenOrbit dünyası'), '*.json'), (_('Tümü'), '*.*')])
            if not src:
                return {'iptal': True}
            veri = read_json(src, None)
        did, rapor = DW.iceri(veri)
        return dict(dunyalar_durumu(), yeni=did, rapor=rapor)
    if path == '/api/dunya/yama':                   # editörün değişikliği: dosya + yol -> tam değer (standartta taslağa)
        did = dunya_arg(b)
        DW.yama(did, b.get('dosya'), b.get('yol'), b.get('deger'))
        return dunya_get('/api/dunya', {'dunya': did})
    if path == '/api/dunya/geri_al':
        did = dunya_arg(b)
        DW.geri_al(did, b.get('dosya'), b.get('yol'), b.get('bolum'))
        return dunya_get('/api/dunya', {'dunya': did})
    if path == '/api/dunya/gorev':
        did = dunya_arg(b)
        DW.gorev_kaydet(did, b.get('id'), b.get('degisiklik') or {})
        return DW.gorev(did, b.get('id'))
    if path == '/api/dunya/gorev_yeni':
        did = dunya_arg(b)
        qid = DW.gorev_yeni(did, b.get('ad'), b.get('seviye'), b.get('hedefler') or [], b.get('oduller') or [])
        return DW.gorev(did, qid)
    if path == '/api/dunya/sunucu_yeniden':         # editörden: dünyanın değişiklikleri için sunucuyu yeniden başlat
        return h_post('/api/sunucu/yeniden', {})
    raise Hata(_('Bilinmeyen istek.'))


def botlar_durumu():
    users = world_users()
    dunyalar = [{'id': w['id'], 'ad': w['ad'], 'kapak': w['kapak'], 'standart': w['standart'],
                 'pilotlar': [u.get('pilot') or u.get('ad') for u in w.get('kullananlar') or []]} for w in DW.liste(users)]
    return {'liste': BT.liste(), 'dunyalar': dunyalar, 'kipler': BT.KIPLER, 'izinler': BT.IZINLER, 'siniflar': BT.BASIT_SINIFLAR,
            'ayarlar': {k: {'tur': v[0], 'en_az': v[1], 'en_cok': v[2], 'varsayilan': v[3]} for k, v in BT.AYARLAR.items()},
            'llm_cok_dilli': SG.cok_dilli(), 'sunucu_acik': YON.running(), 'sunucu_paketi': getattr(YON, 'bot', None) and YON.bot[0], 'oyun_ayarlari': bot_oyun_ayarlari()}


def bot_oyun_ayarlari():
    """Botların oyun ayarı profilleri (bot/oyun_ayari.py): hazır profiller ve Özel profilin alanları (oyun ayarlarının adlarıyla)."""
    from bot import oyun_ayari as OA
    hazir = [{'id': k, 'ad': AY.HAZIR[k]['ad'], 'aciklama': AY.HAZIR[k]['aciklama']} for k in OA.PROFILLER if k in AY.HAZIR]
    alanlar = [{'anahtar': k, 'ad': AY.BY_KEY[k]['ad'], 'aciklama': AY.BY_KEY[k]['aciklama'], 'en_az': AY.BY_KEY[k].get('min', 0),
                'en_cok': min(10, AY.BY_KEY[k].get('max', 10))} for k in OA.ALANLAR]
    return {'hazir': hazir, 'alanlar': alanlar}


def oyuncu_adlari():
    return [k.get('pilot') for k in KAY.list() if k.get('pilot')]


def bot_get(path, q):
    if path == '/api/botlar':
        return botlar_durumu()
    if path == '/api/bot/llm':
        return dict(LLM.state(), saglayici=SG.durum())
    if path == '/api/bot/detay':                   # Kadro > bot penceresi: oyun açıkken canlı bot, kapalıyken son kayıt
        return bot_detayi(q.get('id'), int(q.get('no') or 0))
    if path == '/api/bot':
        pid = q.get('id')
        d = BT.ayrinti(pid)
        p = BT.dosya_yolu(pid)
        acik = bool(YON.running() and getattr(YON, 'bot', None) and p and YON.bot[0] == os.path.normcase(p))
        return dict(d, sunucu_bu_pakette=acik, yeniden_gerekli=acik and SR.bot_imzasi(p) != YON.bot)
    raise Hata(_('Bilinmeyen istek.'))


def bot_detayi(pid, no):
    if paket_acik(pid):
        try:
            return dict(oyun_kanali('/bot/detay', {'no': no}), katalog=BT.duzenle_katalog(), canli=True)
        except Hata:
            # oyun açık ama kanal yanıt vermedi: son kayıt, düzenlenemez (oyun dosyayı yeniden yazar)
            return dict(BT.bot_detay(pid, no), katalog=BT.duzenle_katalog(), canli=False, salt_okunur=True)
    return dict(BT.bot_detay(pid, no), katalog=BT.duzenle_katalog(), canli=False)


def bot_post(path, b):
    if path == '/api/bot/detay':                   # botu düzenle (bot/duzenle.py): oyun açıkken canlı, kapalıyken dosyada
        pid, no, deg = b.get('id'), int(b.get('no') or 0), b.get('degisiklik') or {}
        if not isinstance(deg, dict) or not deg:
            raise Hata(_('Değişiklik yok.'))
        if paket_acik(pid):
            r = oyun_kanali('/bot/duzenle', {'no': no, 'degisiklik': deg})
            if r.get('hata'):
                from bot import duzenle as DZ
                raise Hata(BT.duzenleme_hatasi(DZ.DuzenlemeHatasi(r['hata'], r.get('alan', ''))))
            if 'ozellik' in deg:
                BT.bot_kisilik(pid, no, deg['ozellik'])
            return dict(r, katalog=BT.duzenle_katalog(), canli=True)
        return dict(BT.bot_duzenle(pid, no, deg), katalog=BT.duzenle_katalog(), canli=False)
    if path == '/api/bot/llm/saglayici':          # sağlayıcı seçimi: dahili model, OpenAI, Claude ... (bot/llm_saglayici.py)
        if b.get('kimlik') not in SG.SAGLAYICILAR:
            raise Hata(_('Bilinmeyen istek.'))
        if b.get('adres') and not re.fullmatch(r'https?://\S+', str(b['adres']).strip()):
            raise Hata(_('Adres http:// ya da https:// ile başlamalı.'))
        SG.kaydet(b['kimlik'], b.get('adres'), b.get('model'), b.get('anahtar'))
        return bot_get('/api/bot/llm', {})
    if path == '/api/bot/llm/modeller':
        try:
            return {'modeller': SG.modeller(b.get('kimlik'), b.get('adres') or None, b.get('anahtar') or None)}
        except SG.SaglayiciHatasi as e:
            raise Hata(str(e))
    if path == '/api/bot/llm/test' and SG.ayar()['secili'] != SG.YEREL:
        try:
            return dict(LLM.test_uzak(), saglayici=SG.durum())
        except LLMK.IndirmeHatasi as e:
            raise Hata(str(e))
    if path.startswith('/api/bot/llm/'):           # dil modeli: kur, durdur, sil, test
        islem = {'kur': LLM.start, 'durdur': LLM.cancel, 'sil': LLM.sil, 'test': LLM.test}.get(path.rsplit('/', 1)[1])
        if islem is None:
            raise Hata(_('Bilinmeyen istek.'))
        if path.endswith('/sil') and YON.running():
            raise Hata(_('Önce oyunu kapat.'))
        try:
            return dict(islem(), saglayici=SG.durum())
        except LLMK.IndirmeHatasi as e:
            raise Hata(str(e))
    if path == '/api/bot/olustur':
        pid = BT.olustur(b.get('ad'), b.get('aciklama', ''), b.get('dunya'), b.get('kip', 'normal'), b.get('gelisim', 'progressive'),
                         b.get('adet', 60), b.get('dil', 'karisik'), b.get('firma_dagilimi') or (1, 1, 1), b.get('ayarlar') or {},
                         oyuncular=oyuncu_adlari(), ad_dili_=b.get('ad_dili'), ozel=b.get('ozel') or '', ad_kaynagi=b.get('ad_kaynagi'))
        return dict(botlar_durumu(), yeni=pid)
    pid = b.get('id')
    if path == '/api/bot/guncelle':
        BT.guncelle(pid, ad=b.get('ad'), aciklama=b.get('aciklama'), kip=b.get('kip'), gelisim=b.get('gelisim'), ayarlar=b.get('ayarlar'))
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/ata':                      # paketi dünyaya ata (o dünyanın eski paketi boşa çıkar)
        did = b.get('dunya') or None
        if did and not DW.var(did):
            raise Hata(_('Dünya bulunamadı.'))
        BT.ata(pid, did)
        return botlar_durumu()
    if path == '/api/bot/kadro':
        if paket_acik(pid) and (b.get('yeniden') or int(b.get('adet') or 0) < len(BT.oku(pid)['kadro'])):
            raise Hata(_('Bu paket oyunda açık: önce oyunu kapat.'))     # çalışan oyun eski kadroyla durumu yeniden yazar
        BT.kadro(pid, adet=b.get('adet'), dil=b.get('dil'), firma_dagilimi=b.get('firma_dagilimi'), yeniden=bool(b.get('yeniden')),
                 oyuncular=oyuncu_adlari(), ad_dili_=b.get('ad_dili'), ozel=b.get('ozel') or '', ad_kaynagi=b.get('ad_kaynagi'))
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/ad':
        BT.bot_adi(pid, int(b.get('no') or 0), b.get('ad'), oyuncular=oyuncu_adlari())
        if paket_acik(pid):
            try:
                oyun_kanali('/bot/ad_kaydi', {})           # oyunda hemen: bot, klanlar, rehberler
            except Hata:
                pass                                       # oyuna girilmemiş: sonraki açılışta uygulanır
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/sifirla':
        if paket_acik(pid):
            raise Hata(_('Bu paket oyunda açık: önce oyunu kapat.'))
        BT.sifirla(pid)
        return bot_get('/api/bot', {'id': pid})
    if path == '/api/bot/sil':
        if paket_acik(pid):
            raise Hata(_('Bu paket oyunda açık: önce oyunu kapat.'))
        BT.sil(pid)
        return botlar_durumu()
    if path == '/api/bot/sunucu_yeniden':
        return h_post('/api/sunucu/yeniden', {})
    raise Hata(_('Bilinmeyen istek.'))


def h_get(path, q):
    if path.startswith('/api/bot'):                 # Botlar (botlar.py)
        return bot_get(path, q)
    if path.startswith('/api/dunya'):               # Dünya Editörü (dunyalar.py)
        return dunya_get(path, q)
    if path == '/api/durum':
        return status()
    if path == '/api/ayarlar':
        return api_settings()
    if path == '/api/etkinlikler':
        return event_list()
    if path == '/api/kayitlar':
        return {'liste': KAY.list(), 'aktif': KAY.active(), 'silinenler': KAY.deleted(), 'firmalar': FIRMALAR}
    if path == '/api/kayit_profili':
        return profile_values(slot_arg(q))
    if path == '/api/editor':                       # karakter editörü: kaydın taslağı (kayit_editoru.py)
        return KAY.editor_open(slot_arg(q))
    if path == '/api/editor/katalog':               # karakter editörünün eşya kataloğu
        return KAY.editor_catalog()
    if path == '/api/esya_bilgi':                   # eşya ipucunun değerleri (Hangar, Mağaza, karakter editörü)
        return {'esyalar': KAY.item_info()}
    if path == '/api/yedekler':
        sid = slot_arg(q)
        return {'liste': KAY.backups(sid), 'kayit': KAY.summary(sid), 'ayarlar': CFG.all()}
    if path == '/api/istemci':
        return api_client()
    if path == '/api/panel_ayarlari':
        return CFG.all()
    if path == '/api/discord_rp':                   # Discord Rich Presence: bağlantı ve profilde görünecek etkinlik (önizleme)
        return {'durum': RP.durum, 'hata': RP.hata, 'etkinlik': RP.onizleme(), 'ayarlar': CFG.all()}
    if path == '/api/diller':
        return {'diller': D.liste()}
    if path == '/api/takvim':                       # etkinlik takvimi: ?bas=&bit= (zaman damgası, en çok 62 gün)
        return api_calendar(q)
    if path == '/api/portlar':
        return YON.foreign_ports()
    if path == '/api/gunluk':
        name = q.get('ad', 'gs.log')
        if name not in GUNLUKLER and not EK_GUNLUK.fullmatch(name):
            raise Hata(_('Bilinmeyen günlük.'))
        p = os.path.join(YOL.LOGS, name)
        n = min(5000, max(50, int(q.get('satir', 400))))
        return {'ad': name, 'var': os.path.isfile(p), 'boyut': os.path.getsize(p) if os.path.isfile(p) else 0,
                'satirlar': SR.tail(p, n), 'liste': [{'ad': g, 'boyut': os.path.getsize(os.path.join(YOL.LOGS, g))
                                                       if os.path.isfile(os.path.join(YOL.LOGS, g)) else None}
                                                      for g in GUNLUKLER + ek_gunlukler()]}
    if path == '/api/istemci/indirme':              # istemci indirmenin durumu (indirme.py)
        return DL.state()
    if path == '/api/motor':                        # macOS: panelin Wine'ı ve Rosetta (wine_motoru.py)
        return MOT.state()
    if path == '/api/yama':                         # istemcinin düzeltmelerini yükleyen BepInEx (istemci_yama.py)
        return YAM.state(client_folder())
    if path == '/api/guncelleme':                   # GitHub'dan güncelleme (guncelleme.py)
        return dict(UPD.state(), ayar=CFG.get('guncelleme'), bosta=idle())
    if path == '/api/protokol':                     # protokol uyarlamasının durumu (protokol.py)
        return dict(UYAR.state(), etkin=IST.supported())
    if path == '/api/esya_listesi':                 # kayıt düzenleyicinin "eşya ver" listesi
        return {'esyalar': KAY.loot_list()}
    if path == '/api/oyun/magaza':                  # oyun menüleri: mağazanın listesi ve cüzdan (panel_kanali.py)
        return dict(oyun_kanali('/magaza'), gorsel=bool(oyun_gorsel('dizin.json')))
    if path == '/api/oyun/hangar':                  # oyun menüleri: gemiler, config'ler, yuvalar ve envanter (?gemi=)
        return dict(oyun_kanali('/hangar?gemi=%s' % re.sub(r'\D', '', str(q.get('gemi') or ''))), gorsel=bool(oyun_gorsel('dizin.json')))
    if path == '/api/oyun/muzayede':                # oyun menüleri: açık artırma (lotlar, kurallar, geçmiş, olaylar)
        return dict(oyun_kanali('/muzayede'), gorsel=bool(oyun_gorsel('dizin.json')))
    if path == '/api/oyun/muzayede/olaylar':        # açık artırmanın yeni olayları (panelin bildirimleri)
        return oyun_kanali('/muzayede/olaylar?son=%d' % int(q.get('son') or 0))
    if path == '/api/oyun/skylab':                  # oyun menüleri: Skylab modülleri, depo, enerji, taşıma
        return dict(oyun_kanali('/skylab'), gorsel=bool(oyun_gorsel('dizin.json')))
    if path == '/api/canli':                        # canlı durum (oyun sunucusunun canli_durum.json'u; canli_durum.py)
        p = os.path.join(YOL.LOGS, 'canli_durum.json')
        d = read_json(p, None)
        if not d or (not YON.running() and time.time() - d.get('zaman', 0) > 15):    # eski dosya: sunucu kapalı
            return {'var': False, 'sunucu_acik': YON.running()}
        import takvim as TK
        d['etkinlik_adlari'] = [_(TK.EVENTS.get(k, {}).get('ad', k)) for k in d.get('etkinlikler', [])]
        return {'var': True, 'sunucu_acik': True, 'yas': max(0, time.time() - d.get('zaman', 0)), 'durum': d}
    if path == '/api/arkadas':                      # Arkadaşlarınla Oyna: Host (sunucu, adresler, misafirler) ve Join (oturum)
        canli = read_json(os.path.join(YOL.LOGS, 'canli_durum.json'), None) if YON.running() else None
        aktif = KAY.active()
        return {'host': ARK.host_durumu(canli), 'misafir': ARK.durum(), 'kayitlar': KAY.list(), 'aktif': aktif,
                'istemci_surumu': IST.check(client_folder()).get('surum') or IST.supported(),
                # Host'un dünyası (Dünya Editörü): seçim ('' kaydının dünyası), seçilebilenler ve sunucunun açılacağı dünya
                'dunya': {'secim': CFG.get('arkadas_dunya') if DW.var(CFG.get('arkadas_dunya') or '') else '',
                          'kaydin': world_info(KAY.meta(aktif).get('dunya') if aktif else None), 'gecerli': world_info(world_id(aktif, True)),
                          'liste': [{'id': w['id'], 'ad': w['ad'], 'kapak': w['kapak'], 'standart': w['standart']} for w in DW.liste()]}}
    if path == '/api/hakkinda':
        return {'surum': SURUM, 'python': sys.version.split()[0], 'kok': ROOT, 'sunucu': SERVER, 'kayitlar': YOL.KAYITLAR,
                'gunlukler': YOL.LOGS, 'ayarlar': settings_file(), 'panel': YOL.PANEL, 'port': PORT, 'dil': D.current(), 'discord': DISCORD,
                'eski_kisayol': bool(old_shortcut())}
    raise Hata(_('Bilinmeyen istek: %s', path))


def h_post(path, b):
    if path.startswith('/api/bot/'):                # Botlar (botlar.py)
        return bot_post(path, b)
    if path.startswith('/api/dunya') or path == '/api/kayitlar/dunya':      # Dünya Editörü (dunyalar.py)
        return dunya_post(path, b)
    if path == '/api/oyun/al':                      # oyun menüleri: mağazadan satın alma (istemcinin isteğiyle aynı yoldan)
        return oyun_kanali('/magaza/al', {k: b.get(k) for k in ('lootId', 'category', 'amount', 'level')})
    if path == '/api/oyun/magaza/abone':            # oyun menüleri: booster aboneliği
        return oyun_kanali('/magaza/abone', {'lootId': b.get('lootId'), 'category': b.get('category')})
    if path == '/api/oyun/hangar/tasi':             # oyun menüleri: envanter <-> gemi, dron ya da P.E.T. yuvası
        return oyun_kanali('/hangar/tasi', {k: b.get(k) for k in ('gemi', 'konfig', 'esya', 'yon', 'hedef', 'dron', 'kume')})
    if path == '/api/oyun/hangar/islem':            # oyun menüleri: config, satış, P.E.T., CPU işlemleri (panel_kanali.ISLEMLER)
        return oyun_kanali('/hangar/islem', {k: b.get(k) for k in ('islem', 'gemi', 'konfig', 'hedef_gemi', 'favori', 'esyalar', 'dron',
                                                                    'ad', 'yuva', 'esya', 'cephane', 'lootId')})
    if path == '/api/oyun/hangar/tasarim':          # oyun menüleri: geminin görünümü (tasarımı)
        return oyun_kanali('/hangar/tasarim', {'gemi': b.get('gemi'), 'lootId': b.get('lootId')})
    if path == '/api/oyun/hangar/etkin':            # oyun menüleri: geminin etkinleştirilmesi (yalnız istasyonda)
        return oyun_kanali('/hangar/etkin', {'gemi': b.get('gemi')})
    if path == '/api/oyun/skylab/islem':            # oyun menüleri: Skylab yükseltme, aç/kapa, gemiye taşıma
        return oyun_kanali('/skylab/islem', {k: b.get(k) for k in ('modul', 'islem', 'mod', 'miktarlar')})
    if path.startswith('/api/oyun/muzayede/') and path.rsplit('/', 1)[1] in ('teklif', 'hepsi', 'anlik', 'oto', 'alarm'):   # açık artırma
        return oyun_kanali('/muzayede/' + path.rsplit('/', 1)[1], {k: b.get(k) for k in ('tur', 'loot', 'fiyat', 'lotlar', 'azami', 'gecilince', 'dk')})
    if path == '/api/oyun/skylab/robot':            # oyun menüleri: toplayıcıya robot
        return oyun_kanali('/skylab/robot', {'modul': b.get('modul'), 'tip': b.get('tip')})
    # ---- oyun ve sunucular
    if path == '/api/oyna':
        return start_launch(b.get('sadece_sunucu'))
    if path == '/api/arkadas/ayarlar':
        dunya = b.get('dunya', CFG.get('arkadas_dunya')) or ''
        if dunya and not DW.var(dunya):
            raise Hata(_('Dünya bulunamadı.'))
        CFG.update({'arkadas_sifre': str(b.get('sifre') if 'sifre' in b else CFG.get('arkadas_sifre') or '')[:64],
                    'arkadas_en_cok': b.get('en_cok', CFG.get('arkadas_en_cok')), 'arkadas_dunya': dunya})
        return h_get('/api/arkadas', {})
    if path == '/api/arkadas/host':                 # arkadaş sunucusu: Oyna gibi, oyun sunucusu --cok-oyunculu
        return start_launch(b.get('sadece_sunucu'), arkadas=True)
    if path == '/api/arkadas/genel_ip':
        return {'ip': ARK.genel_bul()}
    if path == '/api/arkadas/at':
        ARK.at(b.get('oturum'))
        return {}
    if path == '/api/arkadas/dene':
        return ARK.dene(str(b.get('adres') or ''))
    if path == '/api/arkadas/katil':
        return join_friend(b)
    if path == '/api/arkadas/ayril':
        ARK.ayril()
        return ARK.durum()
    if path == '/api/sunucu/durdur':
        if YON.client_alive():
            raise Hata(_('Oyun açıkken sunucu durdurulamaz: önce oyunu kapatın.'))
        if COK.canli():
            raise Hata(_('Ek istemciler açıkken sunucu durdurulamaz: önce onları kapatın.'))
        YON.stop_servers()
        return YON.status()
    if path == '/api/sunucu/yeniden':
        slot = YON.slot or KAY.active()
        if not slot:
            raise Hata(_('Kayıt yok.'))
        if COK.canli():
            raise Hata(_('Ek istemciler açıkken sunucu yeniden başlatılamaz: önce onları kapatın.'))
        ark_env = ARK.host_ortam() if YON.running() and YON.arkadas else None       # kip korunur (Host, çoklu istemci)
        coklu = None if ark_env else (coklu_ortam() if (YON.running() and YON.coklu) or coklu_istenir(slot) else None)
        YON.stop_servers()
        YON.start_servers(KAY.profile(slot), settings_file(slot), kontrol=bool(AY.read(settings_file(slot)).get('kontrol')), slot=slot, arkadas=ark_env,
                          coklu=coklu, dunya=world_file(slot, bool(ark_env)), bot=bot_file(slot, bool(ark_env)))
        return YON.status()
    if path == '/api/istemci/kapat':
        YON.stop_client()
        return YON.status()
    if path == '/api/coklu/ac':                     # çoklu istemci: başka bir kayıtla ek istemci (coklu.py)
        return open_extra(b)
    if path == '/api/coklu/kapat':
        COK.kapat(str(b.get('kayit') or ''))
        return COK.durum()
    if path == '/api/coklu/hepsini_kapat':
        COK.hepsini_kapat()
        return COK.durum()
    if path == '/api/portlar/kapat':
        pid = int(b.get('pid') or 0)
        info = SR.process_info(pid)
        if not (SR.is_our_server(info) or info['ad'].lower() == 'darkorbit.exe'):
            raise Hata(_('Bu süreç (%s) panelin sunucusu değil; panel kapatmaz. Gerekirse kendiniz kapatın.', info['ad']))
        m = re.search(r'"--durdur=([^"]+)"|--durdur=(\S+)', info.get('komut') or '')
        if m:                                       # önceki panelin oyun sunucusu: önce kaydedip kendisi çıksın
            try:
                open(m.group(1) or m.group(2), 'w').close()
                end = time.time() + 6
                while time.time() < end and pid in (SR.listeners() or {}).values():
                    time.sleep(0.2)
            except OSError:
                pass
        if pid in (SR.listeners() or {}).values() or not m:
            SR.kill(pid)
        log('eski süreç kapatıldı: %s %s' % (pid, info['ad']))
        time.sleep(0.5)
        return YON.foreign_ports()
    # ---- oyun ayarları
    if path == '/api/ayarlar':
        vals = game_settings()
        for k, v in (b.get('degerler') or {}).items():
            if k in AY.BY_KEY:
                vals[k] = v
        AY.write(settings_file(), vals)
        return api_settings()
    if path == '/api/ayarlar/kopyala':             # başka bir kaydın ayarları (etkinlik seçimleri dahil) etkin kayda
        slot = KAY.active()
        if not slot:
            raise Hata(_('Kayıt yok.'))
        KAY.copy_settings(str(b.get('kaynak') or ''), slot)
        log('ayarlar kopyalandı: %s -> %s' % (b.get('kaynak'), slot))
        return api_settings()
    if path == '/api/ayarlar/sifirla':
        vals = game_settings()
        keys = b.get('anahtarlar') or list(AY.BY_KEY)
        for k in keys:
            vals.pop(k, None)
        AY.write(settings_file(), vals)
        return api_settings()
    if path == '/api/ayarlar/hazir':
        name = b.get('ad')
        user = read_json(SABLONLAR, {})
        preset = AY.HAZIR.get(name, {}).get('degerler') if name in AY.HAZIR else (user.get(name) or {}).get('degerler')
        if preset is None:
            raise Hata(_('Hazır ayar bulunamadı.'))
        vals = {k: v for k, v in game_settings().items() if k not in AY.BY_KEY}     # etkinlik seçimleri kalır
        vals.update(preset)
        AY.write(settings_file(), vals)
        return api_settings()
    if path == '/api/ayarlar/sablon_kaydet':
        name = (b.get('ad') or '').strip()[:40]
        if not name:
            raise Hata(_('Şablona bir ad verin.'))
        user = read_json(SABLONLAR, {})
        vals = {k: v for k, v in game_settings().items() if k in AY.BY_KEY and v != AY.DEFAULTS[k]}
        user[name] = {'ad': name, 'aciklama': b.get('aciklama') or _('Kendi ayarın'), 'degerler': vals}
        write_json(SABLONLAR, user)
        return api_settings()
    if path == '/api/ayarlar/sablon_sil':
        user = read_json(SABLONLAR, {})
        user.pop(b.get('ad'), None)
        write_json(SABLONLAR, user)
        return api_settings()
    if path == '/api/etkinlikler':
        return set_events(b)
    # ---- kayıtlar
    if path == '/api/kayitlar/yeni':
        sid = KAY.create(b.get('ad'), b.get('pilot'), b.get('firma'), b.get('kredi'), b.get('uridyum'), b.get('seviye'), b.get('onur'),
                         b.get('lazer'), b.get('roket'), bool(b.get('ilerlemeli')), b.get('ayar_kaynagi') or KAY.active(),
                         kampanya=bool(b.get('kampanya')))
        if b.get('aktif_yap', True):
            KAY.set_active(sid)
        log('yeni kayıt: %s' % sid)
        return {'id': sid}
    if path == '/api/kayitlar/aktif':
        return {'id': KAY.set_active(slot_arg(b))}
    if path == '/api/kayitlar/adlandir':
        return KAY.rename(slot_arg(b), b.get('ad'))
    if path == '/api/kayitlar/not':
        return KAY.set_note(slot_arg(b), b.get('not'))
    if path == '/api/kayitlar/kopyala':
        return {'id': KAY.duplicate(slot_arg(b), b.get('ad'))}
    if path == '/api/kayitlar/sil':
        return {'dosya': KAY.delete(slot_arg(b))}
    if path == '/api/kayitlar/geri_al':
        return {'id': KAY.undelete(b.get('dosya'))}
    if path == '/api/kayitlar/cop_bosalt':
        return {'silinen': KAY.purge(b.get('dosya'))}
    if path == '/api/kayitlar/disari':
        sid = slot_arg(b)
        name = '%s_%s.zip' % (sid, time.strftime('%Y%m%d'))
        dest = dialog('kaydet', title=_('Kaydı dışa aktar'), initialfile=name, defaultextension='.zip',
                      filetypes=[(_('DarkOrbit kaydı'), '*.zip')])
        if not dest:
            return {'iptal': True}
        KAY.export(sid, dest, bool(b.get('yedeklerle', True)))
        return {'yol': dest}
    if path == '/api/kayitlar/iceri':
        src = dialog('ac', title=_('Kayıt içe aktar'), filetypes=[(_('DarkOrbit kaydı'), '*.zip *.json'), (_('Tümü'), '*.*')])
        if not src:
            return {'iptal': True}
        return {'id': KAY.import_file(src)}
    if path == '/api/kayitlar/duzenle':
        return {'degisen': KAY.edit(slot_arg(b), b.get('degerler') or {})}
    # ---- karakter editörü (taslak: Kaydet profile yazar, Vazgeç atar)
    if path == '/api/editor/uygula':
        return KAY.editor_apply(slot_arg(b), b.get('islemler'))
    if path == '/api/editor/kaydet':
        sid = slot_arg(b)
        log('karakter editörü: %s kaydedildi' % sid)
        return {'yedek': KAY.editor_commit(sid)}
    if path == '/api/editor/vazgec':
        KAY.editor_discard(slot_arg(b))
        return {}
    # ---- yedekler
    if path == '/api/yedekler/al':
        return {'dosya': KAY.backup(slot_arg(b), 'elle', b.get('not') or '')}
    if path == '/api/yedekler/geri_yukle':
        return {'guvenlik': KAY.restore(slot_arg(b), b.get('dosya'))}
    if path == '/api/yedekler/sil':
        KAY.delete_backup(slot_arg(b), b.get('dosya'))
        return {}
    if path == '/api/yedekler/not':
        KAY.set_backup_note(slot_arg(b), b.get('dosya'), b.get('not'))
        return {}
    if path == '/api/yedekler/yeni_kayit':
        return {'id': KAY.backup_as_new(slot_arg(b), b.get('dosya'), b.get('ad'))}
    # ---- istemci ve panel ayarları
    if path == '/api/panel_ayarlari':
        CFG.update({k: v for k, v in (b.get('degerler') or {}).items() if k != 'aktif_kayit'})
        RP.uyan.set()                               # Discord Rich Presence ayarı değiştiyse hemen
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
                raise Hata(_('Seçilen klasör bir DarkOrbit istemcisi değil: %s', ' '.join(c['sorunlar'])))
        CFG.update({'istemci_klasoru': p})
        return api_client()
    if path == '/api/istemci/kullan':
        p = os.path.normpath(b.get('yol') or '')
        if not IST.check(p)['gecerli']:
            raise Hata(_('Klasör geçerli bir istemci değil.'))
        CFG.update({'istemci_klasoru': p})
        return api_client()
    if path == '/api/istemci/otomatik':
        CFG.update({'istemci_klasoru': None})
        return api_client()
    if path == '/api/guncelleme/denetle':
        UPD.check()
        STATE['sonraki_denetim'] = time.time() + GUNCELLEME_SN
        return h_get('/api/guncelleme', {})
    if path == '/api/guncelleme/kur':
        if not idle(strict=True):
            raise Hata(_('Önce oyunu, sunucuları ve süren işleri kapatın.'))
        try:
            UPD.install_async()
        except GuncellemeHatasi as e:
            raise Hata(str(e))
        return h_get('/api/guncelleme', {})
    if path == '/api/istemci/indir':                # oyunu indir ve proje köküne aç (sürer, kaldığı yerden)
        if CAL.bul(CFG)['tur'] == 'motor':          # macOS: oyunu açacak Wine da birlikte iner
            MOT.start()
        return DL.start(CFG.get('hizli_indirme'))
    if path == '/api/istemci/guncelle':             # eski istemci: yeni sürümü indir, eskisini sil; BepInEx yeni klasöre yeniden kurulur
        if YON.client_alive() or IST.running_clients():
            raise Hata(_('Önce oyunu kapatın'))
        eski = client_folder()
        if not IST.check(eski)['eski']:
            raise Hata(_('İstemci zaten güncel.'))
        yeni = next((c['yol'] for c in IST.candidates() if c['uyumlu']), None)
        if yeni:                                    # bilgisayarda zaten var
            CFG.update({'istemci_klasoru': yeni})
            eski_istemciyi_sil(eski, yeni)
            YAM.start(yeni)
            return DL.state()
        STATE['istemci_eski'] = eski
        return DL.start(CFG.get('hizli_indirme'))
    if path == '/api/motor/kur':
        return MOT.start()
    if path == '/api/yama/kur':
        return YAM.start(client_folder())
    if path == '/api/yama/durdur':
        YAM.cancel()
        return YAM.state(client_folder())
    if path == '/api/motor/durdur':
        return MOT.cancel()
    if path == '/api/rosetta/kur':                  # macOS'un yönetici penceresi açılır
        return MOT.rosetta_kur()
    if path == '/api/istemci/indir_durdur':
        return DL.cancel()
    if path == '/api/istemci/indir_sil':            # yarım indirmenin geçici klasörü
        try:
            return DL.discard()
        except IndirmeHatasi as e:
            raise Hata(str(e))
    if path == '/api/protokol/uret':                # yeni istemciden protokol üret ve farkı raporla (etkin dosyalara dokunmaz)
        try:
            return UYAR.generate(os.path.normpath(b.get('yol') or client_folder() or ''))
        except RuntimeError as e:
            raise Hata(str(e))
    if path == '/api/protokol/uygula':              # üretilen sürümü etkin yap (oyun sunucusu yeniden başlatılınca)
        if YON.running():
            raise Hata(_('Önce oyun sunucusunu durdurun: protokol açılışta yükleniyor.'))
        try:
            return UYAR.activate(b.get('surum'))
        except RuntimeError as e:
            raise Hata(str(e))
    if path == '/api/gunluk/temizle':
        name = b.get('ad')
        if name not in GUNLUKLER and not EK_GUNLUK.fullmatch(str(name or '')):
            raise Hata(_('Bilinmeyen günlük.'))
        try:
            open(os.path.join(YOL.LOGS, name), 'w').close()
        except OSError:
            raise Hata(_('Günlük şu an bir sunucuda açık; sunucuyu durdurup yeniden deneyin.'))
        return {}
    if path == '/api/klasor_ac':
        what = b.get('ne')
        paths = {'proje': ROOT, 'kayitlar': YOL.KAYITLAR, 'gunlukler': YOL.LOGS, 'istemci': client_folder() or ROOT,
                 'sunucu': SERVER}
        if what in ('kayit', 'yedek'):
            sid = slot_arg(b)
            p = KAY.dir(sid) if what == 'kayit' else KAY.backup_dir(sid)
            os.makedirs(p, exist_ok=True)
            open_folder(p)
        elif what in paths:
            os.makedirs(paths[what], exist_ok=True) if what in ('kayitlar', 'gunlukler') else None
            open_folder(paths[what])
        else:
            raise Hata(_('Bilinmeyen klasör.'))
        return {}
    if path == '/api/discord':                      # davet varsayılan tarayıcıda (panel penceresinin profili Discord'a girişli değil)
        import webbrowser
        webbrowser.open(DISCORD)
        return {}
    if path == '/api/bagis':                        # destek sayfası varsayılan tarayıcıda (Buy Me a Coffee)
        import webbrowser
        webbrowser.open(BAGIS)
        return {}
    if path == '/api/kisayol':
        return {'yol': create_shortcut()}
    if path == '/api/kapat':
        if (YON.client_alive() or COK.canli()) and not b.get('zorla'):
            raise Hata(_('Oyun açık: önce oyunu kapatın.'))
        YON.stop_client()
        threading.Thread(target=lambda: (COK.hepsini_kapat(bekle=8), istemci_bekle(), shutdown()), daemon=True).start()
        return {}
    raise Hata(_('Bilinmeyen istek: %s', path))


TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
         '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.webp': 'image/webp', '.woff2': 'font/woff2'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'DarkOrbitPanel/' + SURUM

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
        except (Hata, KayitHatasi, ArkadasHatasi, CokluHatasi, RuntimeError, ValueError) as e:
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
            return self._send(200, {'panel': 'darkorbit', 'surum': SURUM, 'pid': os.getpid()})
        if u.path.startswith('/api/'):
            return self._api(h_get, {k: v[0] for k, v in parse_qs(u.query).items()})
        if u.path.startswith('/oyun_gorsel/'):
            p = oyun_gorsel(u.path[len('/oyun_gorsel/'):])
            if not p:
                return self._send(404, b'yok', 'text/plain')
            if p.endswith('.png'):                  # atlas sayfaları büyük, değişmez; dizin ve adlar yeniden dökümde değişir: önbelleksiz
                return self._send(200, open(p, 'rb').read(), 'image/png', {'Cache-Control': 'max-age=3600'})
            return self._send(200, open(p, 'rb').read(), 'application/json; charset=utf-8')
        name = 'index.html' if u.path in ('/', '/index.html') else u.path.lstrip('/')
        p = os.path.normpath(os.path.join(ARAYUZ, name))
        if not p.startswith(ARAYUZ + os.sep) or not os.path.isfile(p):
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
                STATE['nabiz'] = time.monotonic() - NABIZ_SN + 8
            return self._send(200, {})
        try:
            body = json.loads(raw.decode('utf8') or '{}')
        except ValueError:
            return self._send(400, {'hata': _('JSON değil')})
        return self._api(h_post, body if isinstance(body, dict) else {})


class Sunucu(ThreadingHTTPServer):
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
                srv = Sunucu(('127.0.0.1', PORT), Handler)
                break
            except OSError:
                time.sleep(0.2)
    try:
        srv = srv or Sunucu(('127.0.0.1', PORT), Handler)
    except OSError:
        try:                                          # panel zaten açık mı?
            with urlopen('http://127.0.0.1:%d/api/ping' % PORT, timeout=2) as r:
                if json.load(r).get('panel') == 'darkorbit':
                    urlopen(Request('http://127.0.0.1:%d/api/goster' % PORT, data=b'{}', method='POST'), timeout=5).read()
                    return
        except Exception:
            pass
        srv = Sunucu(('127.0.0.1', 0), Handler)       # port başka programda: boş bir port
        PORT = srv.server_address[1]
    srv.daemon_threads = True
    STATE['srv'] = srv
    log('panel açıldı: http://127.0.0.1:%d/ (python %s)%s' % (PORT, sys.version.split()[0], ' (güncellemeden sonra)' if STATE['guncellendi'] else ''))
    try_migrate()
    if not CFG.get('aktif_kayit') and KAY.slots():
        CFG.update({'aktif_kayit': KAY.slots()[0]})
    threading.Thread(target=ticker, daemon=True).start()
    RP.baslat()
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
