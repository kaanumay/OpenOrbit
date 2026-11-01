"""Oyun istemcisi (orijinal Unity istemcisi): klasör doğrulama, kendiliğinden bulma, sürüm, başlatma argümanları.

Klasör: içinde DarkOrbit.exe ve DarkOrbit_Data/ olan klasör (DarkOrbit_Version1.1.116 gibi). Panel ayarı boşsa proje kökündeki
en yeni sürüm klasörü kullanılır; güncelleme gelirse ya da klasör taşınırsa panelden seçilir. Bilgisayarda yoksa panel indirir
(client_download.py; yarım indirmenin geçici klasörü aday sayılmaz). Sunucu 1.1.116'nın protokolüyle
yazıldı (data/protocol*.json istemcinin kodundan): başka sürümde panel uyarır.
İstemci dosyaları değiştirilmez; yalnız başlatma argümanı verilir (yerel web girişi 127.0.0.1:8090). İstemcinin yanına
kurulan BepInEx (client_patch.py) istemcinin düzeltmelerini yükler, kuruluysa argümanla açılır. Linux ve macOS'ta istemci Wine ya da
Proton ile açılır (client_runner.py).
"""
import glob, os, re, subprocess

import client_runner as RUN
import client_patch as PATCH
from lang import t as _
from client_download import TEMP

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(PANEL_DIR)
ROOT = os.path.dirname(SERVER)
EXE = 'DarkOrbit.exe'
DATA_DIR = 'DarkOrbit_Data'
SUPPORTED = '1.1.116'          # etkin protokolün sürümü yoksa (server/data/protokol/surum.txt; protokol_guncelle.py yazar)
VERSION_FILE = os.path.join(SERVER, 'data', 'protocols', 'version.txt')


def supported():
    """Sunucunun etkin protokolünün istemci sürümü: surum.txt ile DESTEKLENEN'in yenisi. surum.txt (protokol aracı yazar) panel
    güncellemesinde korunur; güncelleme yeni sürümün protokolünü getirdiyse eskide kalır (2026-10-28: 1.1.115 yazan kopyada
    1.1.116 güncelleme uyarısı çıkmıyordu)."""
    try:
        v = open(VERSION_FILE, encoding='utf8').read().strip()
    except OSError:
        v = ''
    return max(v or SUPPORTED, SUPPORTED, key=vkey)


def vkey(v):
    return tuple(int(x) for x in (v or '0.0.0').split('.'))
LOGIN_URL = 'http://127.0.0.1:8090/#darkorbit://'
RESOLUTIONS = [(1280, 720), (1366, 768), (1440, 900), (1600, 900), (1680, 1050), (1920, 1080), (2560, 1440), (3840, 2160)]


def bundle_version(folder):
    """Oyunun kendi sürümü (Unity PlayerSettings.bundleVersion) DarkOrbit_Data/globalgamemanagers'tan: 4 bayt LE uzunluk + metin,
    ardından sıfır dolgu. Unity motorunun sürümü (2022.3.58f1) aynı dosyada ama uzunluk öneki o biçimde değil; bilinmiyorsa None."""
    try:
        with open(os.path.join(folder, DATA_DIR, 'globalgamemanagers'), 'rb') as fh:
            d = fh.read()
    except OSError:
        return None
    for m in re.finditer(rb'(?<!\d)\d{1,3}\.\d{1,4}\.\d{1,4}', d):
        n = m.end() - m.start()
        if m.start() >= 4 and d[m.start() - 4:m.start()] == n.to_bytes(4, 'little') and d[m.end():m.end() + 1] in (b'', b'\0'):
            return m.group(0).decode()
    return None


def version_of(folder):
    """Sürüm: klasör adından (DarkOrbit_Version1.1.116), yoksa oyunun verisinden (bundle_version; resmî kurulum "DarkOrbit Unity"
    klasöründe), yoksa exe'nin dosya sürümünden (Unity motorunun sürümüyse, ör. 2022.3.58, sayılmaz); bilinmiyorsa None."""
    m = re.search(r'(\d+\.\d+\.\d+)', os.path.basename(os.path.normpath(folder)))
    if m:
        return m.group(1)
    v = bundle_version(folder)
    if v:
        return v
    try:
        import ctypes
        from ctypes import wintypes
        exe = os.path.join(folder, EXE)
        size = ctypes.windll.version.GetFileVersionInfoSizeW(exe, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(exe, 0, size, buf)
        p, n = ctypes.c_void_p(), wintypes.UINT()
        ctypes.windll.version.VerQueryValueW(buf, '\\', ctypes.byref(p), ctypes.byref(n))
        ffi = ctypes.cast(p, ctypes.POINTER(wintypes.DWORD * 13)).contents
        ms, ls = ffi[2], ffi[3]
        if ms >> 16 >= 2000:                      # Unity'nin yıl biçimli motor sürümü, oyunun değil
            return None
        return '%d.%d.%d' % (ms >> 16, ms & 0xFFFF, ls >> 16)
    except Exception:
        return None


def check(folder):
    """Klasörü doğrula -> {'gecerli', 'yol', 'exe', 'veri', 'surum', 'uyumlu', 'eski' (desteklenenden eski: panel günceller),
    'sorunlar' [...], 'boyut_mb'}."""
    out = {'yol': folder or '', 'valid': False, 'exe': False, 'veri': False, 'surum': None, 'compatible': False, 'eski': False,
           'issues': []}
    if not folder:
        out['issues'].append(_('İstemci klasörü seçilmedi.'))
        return out
    if not os.path.isdir(folder):
        out['issues'].append(_('Klasör bulunamadı.'))
        return out
    out['exe'] = os.path.isfile(os.path.join(folder, EXE))
    out['veri'] = os.path.isdir(os.path.join(folder, DATA_DIR))
    if not out['exe']:
        out['issues'].append(_('Klasörde %s yok.', EXE))
    if not out['veri']:
        out['issues'].append(_('Klasörde %s klasörü yok.', DATA_DIR))
    out['valid'] = out['exe'] and out['veri']
    if out['valid']:
        out['surum'] = version_of(folder)
        out['compatible'] = out['surum'] == supported()
        out['eski'] = bool(out['surum']) and vkey(out['surum']) < vkey(supported())
        if out['surum'] and not out['compatible']:
            out['issues'].append(_('Sunucu %s sürümü için yazıldı; %s sürümünde protokol farklıysa giriş ya da bazı pencereler '
                                     'çalışmayabilir.', supported(), out['surum']))
        out['metadata'] = os.path.isfile(os.path.join(folder, DATA_DIR, 'il2cpp_data', 'Metadata', 'global-metadata.dat'))
    return out


def candidates():
    """Olası istemci klasörleri: proje kökü, Program Files, LocalAppData, masaüstü, İndirilenler (en yeni sürüm önce)."""
    pats = [os.path.join(ROOT, 'DarkOrbit*'), os.path.join(ROOT, '*', 'DarkOrbit*')]
    for env in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA', 'APPDATA'):
        base = os.environ.get(env)
        if base:
            pats += [os.path.join(base, 'DarkOrbit*'), os.path.join(base, 'Bigpoint', '*'), os.path.join(base, 'DarkOrbit*', '*')]
    home = os.path.expanduser('~')
    for sub in ('Desktop', 'Downloads', 'Masaüstü', 'İndirilenler', 'Documents'):
        pats += [os.path.join(home, sub, 'DarkOrbit*'), os.path.join(home, sub, 'DarkOrbit*', 'DarkOrbit*')]
    seen, out = set(), []
    for pat in pats:
        for d in glob.glob(pat):
            d = os.path.normpath(d)
            key = d.lower()
            if key in seen or not os.path.isdir(d) or TEMP.lower() in key.split(os.sep):
                continue
            seen.add(key)
            c = check(d)
            if c['valid']:
                out.append(c)
    out.sort(key=lambda c: (c['compatible'], vkey(c['surum'])), reverse=True)
    return out


def resolve(configured):
    """Ayardaki klasör, yoksa bulunan en uygun klasör (None olabilir)."""
    if configured:
        return configured
    c = candidates()
    return c[0]['yol'] if c else None


def args(cfg, log_file, session=None, window=False):
    """Unity başlatma argümanları (panel ayarlarından). oturum: çoklu istemcinin ek istemcisi (web.py giriş sayfası ?oturum= ile
    kaydını bulur); pencere: ayardan bağımsız pencere kipi (ek istemciler)."""
    a = [LOGIN_URL.replace('/#', '/?oturum=%s#' % session) if session else LOGIN_URL]
    mode = 'pencere' if window else cfg.get('window_mode')
    if mode == 'tam_ekran':
        a += ['-screen-fullscreen', '1', '-window-mode', 'exclusive']
    elif mode == 'kenarliksiz':                       # kenarlıksız tam ekran pencere (Unity 2019.3+)
        a += ['-screen-fullscreen', '1', '-window-mode', 'borderless']
    else:
        a += ['-screen-fullscreen', '0']
    a += ['-screen-width', str(cfg.get('width')), '-screen-height', str(cfg.get('height'))]
    if cfg.get('monitor'):
        a += ['-monitor', str(cfg.get('monitor'))]
    extra = (cfg.get('extra_args') or '').strip()
    if extra:
        import shlex
        a += shlex.split(extra, posix=False)
    a += ['-logFile', log_file]
    return a


def command(cfg, folder, log_file, session=None, window=False, prepare=True):
    """İstemcinin başlatma komutu ve ortamı -> (komut, ortam): Windows'ta DarkOrbit.exe doğrudan, Linux ve macOS'ta Wine ya da Proton
    ile (client_runner.py; hazirla: önekte istemcinin sürücüsünü kur). BepInEx kuruluysa onu etkinleştiren argümanlar da (client_patch.py).
    Çalıştırıcı bulunamazsa RuntimeError."""
    return RUN.command(cfg, os.path.join(folder, EXE), args(cfg, RUN.win_path(log_file), session, window) + PATCH.arguments(folder),
                     prepare)


# Wine sürecinin komut satırı Windows yolu: Z:\...\DarkOrbit.exe ya da S:\<klasör>\DarkOrbit.exe … (Wine'ı ya da Proton'u açan
# komutlar, steam.exe değil)
WINE_CLIENT = re.compile(r'"?[a-z]:\\(?:(?!\.exe).)*\\%s\b' % re.escape(EXE.lower()))


def running_clients(exclude=()):
    """Açık DarkOrbit.exe süreçlerinin kimlikleri (panelin açmadıkları dahil); haric: sayılmayacak süreçler. Linux ve macOS'ta haric
    süreç grubu da sayılmaz (surecler.istemci_ac grubu açtığı süreçle kurar: Proton'da istemci onun torunu)."""
    if os.name != 'nt':
        try:
            r = subprocess.run(['ps', '-A', '-o', 'pid=', '-o', 'pgid=', '-o', 'args='], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return []
        out = []
        for line in r.stdout.splitlines():
            p = line.split(None, 2)
            if len(p) == 3 and WINE_CLIENT.match(p[2].lower()) and int(p[0]) not in exclude and int(p[1]) not in exclude:
                out.append(int(p[0]))
        return out
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq %s' % EXE, '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                           timeout=10, creationflags=0x08000000)
        return [p for p in (int(line.split('","')[1]) for line in r.stdout.splitlines() if line.startswith('"%s"' % EXE)) if p not in exclude]
    except Exception:
        return []
