"""İstemciyi Windows dışında açan katman (panel): orijinal istemci 32 bitlik bir Windows programı (DarkOrbit.exe, Unity); Linux ve
macOS'ta Wine ya da Proton ile açılır. Windows'ta komut yalnız exe ve argümanlarıdır.

Panel ayarları (config.py):
  calistirici       otomatik | motor | wine | proton | ozel. otomatik: Linux'ta Proton (umu-run ya da Steam'in Proton'u), yoksa Wine;
                    macOS'ta motor. motor (yalnız macOS): panelin kendi kurduğu Wine + DXMT (wine_engine.py; ilk OYNA'da ya da İstemci
                    sayfasından iner): macOS'ta düz Wine oyunun Direct3D 11'ini çizemiyor. Proton yalnız Linux'ta.
  calistirici_yolu  wine: wine programı; proton: Proton klasörü (içinde proton betiği olan); ozel: istemcinin önüne eklenecek komut
                    (ör. CrossOver'ın wine'ı --bottle ile). Boşsa kendiliğinden bulunur (ozel'de gerekli).
  wine_onek         Wine öneki (WINEPREFIX) ya da Proton'un veri klasörü (STEAM_COMPAT_DATA_PATH). Boşsa save/wine ya da save/proton:
                    istemci öteki Wine programlarından ayrı bir önekte; önek ilk açılışta kurulur (yarım dakika kadar sürebilir).
Apple Silicon'da Wine (x86_64) Rosetta 2 ister: yoksa bul() hata verir, panel kurdurur (wine_motoru.rosetta_kur).
Proton Steam'siz açılır: umu-run kuruluysa onunla (Steam Linux Runtime kabında; PROTONPATH bulunan Proton, yoksa umu kendi Proton'unu
indirir), değilse "proton run" ile (STEAM_COMPAT_CLIENT_INSTALL_PATH Steam'in klasörü; Steam yoksa veri klasörü). Fiil "run": ek
istemciler (multi_client.py) aynı önekte birlikte açılır (waitforexitandrun öncekinin kapanmasını beklerdi). Proton'da istemci S:
sürücüsünden açılır (Steam'deki PROTON_SET_GAME_DRIVE; S: istemci klasörünün üstü): bildirilen, Z:'den açılınca gömülü Chromium
(Vuplex) çalışmıyor. Wine'da (motor da) panel önekte S:'yi kendisi bağlar (oyun_surucusu). İstemciye verilen öteki dosya yolları Z:
sürücüsünden (Wine ve Proton öneklerinde Unix kökü). Wine'ın çıktısı logs/wine.log'a (surecler.istemci_ac).
Proton'un DXVK'sı 32 bitlik istemcide Direct3D 11'i 32 bitlik Vulkan'la açar: bilgisayarda o yoksa (vulkan32) istemci "d3d11: failed
to create factory" ile çöküyordu (bildirilen, Steam'siz Proton 11; Steam'in kabı yükleyiciyi kendisi getirir). O zaman Proton yeni
WoW64 kipinde açılır (PROTON_USE_WOW64=1, Proton 10 ve sonrası): 32 bitlik istemci 64 bitlik Vulkan'ı kullanır.
"""
import functools, glob, json, os, re, shlex, shutil, subprocess, sys

from lang import t as _

WINDOWS, LINUX, MAC = os.name == 'nt', sys.platform.startswith('linux'), sys.platform == 'darwin'   # testler değiştirir


def default_prefix(kind):
    """save/wine ya da save/proton (motor da save/wine'ı kullanır; yollar burada içe aktarılır: client.py'yi yalnız panel/ yoluyla
    içe aktaranlar var)."""
    import paths
    return os.path.join(paths.SAVE, 'wine' if kind == 'engine' else kind)


_engine = None


def engine():
    """Panelin Wine motoru (wine_motoru.WineMotoru; panel ve çalıştırıcı aynı nesneyi kullanır)."""
    global _engine
    if _engine is None:
        import paths
        from wine_engine import WineEngine
        _engine = WineEngine(paths.SAVE)
    return _engine


def win_path(p):
    """Wine'daki Windows programına verilecek dosya yolu (Z: Unix kökü); Windows'ta aynen."""
    return p if WINDOWS else 'Z:' + os.path.abspath(p).replace('/', '\\')


GAME_DRIVE = 's:'


def game_drive(prefix, exe, link=True):
    """Wine öneğinde S: istemci klasörünün üstüne bağlanır (Proton'un PROTON_SET_GAME_DRIVE'ı gibi; yoldaki boşluklar da kalkar) ->
    istemcinin Windows yolu (S:\\<klasör>\\DarkOrbit.exe). kur: bağı kur (yoksa yalnız yol). Yeni önekte dosdevices Wine'ın kurduğu
    gibi açılır (Wine onu yalnız yoksa doldurur: c: -> ../drive_c, z: -> /). S: başka bir şeyse Z: yolu."""
    game = os.path.dirname(os.path.abspath(exe))
    route = '%s\\%s\\%s' % (GAME_DRIVE.upper(), os.path.basename(game), os.path.basename(exe))
    if not link:
        return route
    dev = os.path.join(prefix, 'dosdevices')
    s = os.path.join(dev, GAME_DRIVE)
    target = os.path.dirname(game)
    try:
        if not os.path.isdir(dev):
            os.makedirs(os.path.join(prefix, 'drive_c'), exist_ok=True)
            os.makedirs(dev)
            os.symlink('../drive_c', os.path.join(dev, 'c:'))
            os.symlink('/', os.path.join(dev, 'z:'))
        if os.path.islink(s) and os.readlink(s) != target:
            os.remove(s)
        if not os.path.lexists(s):
            os.symlink(target, s)
        return route if os.path.islink(s) else win_path(exe)
    except OSError:
        return win_path(exe)


def steam_folders():
    """Steam'in kurulu olduğu klasörler (yerel paket, Flatpak, Snap)."""
    home, out = os.path.expanduser('~'), []
    for p in ('.steam/root', '.steam/steam', '.local/share/Steam', '.var/app/com.valvesoftware.Steam/data/Steam',
              'snap/steam/common/.local/share/Steam'):
        d = os.path.realpath(os.path.join(home, p))
        if d not in out and os.path.isdir(os.path.join(d, 'steamapps')):
            out.append(d)
    return out


def _version_key(name):
    """Proton - Experimental en yeni; ötekiler adlarındaki sayılarla (Proton 9.0, GE-Proton10-3)."""
    return (999,) if 'experimental' in name.lower() else tuple(int(x) for x in re.findall(r'\d+', name)) or (0,)


def protons():
    """Bulunan Proton kurulumları [{'ad', 'yol', 'steam'}], en yeni önce: Steam kütüphanelerindeki Proton'lar (steamapps/common) ve ek
    uyumluluk araçları (compatibilitytools.d: GE-Proton …). Linux dışında boş."""
    if not LINUX:
        return []
    dirs = []
    for steam in steam_folders():
        libs = [steam]
        try:
            with open(os.path.join(steam, 'steamapps', 'libraryfolders.vdf'), encoding='utf8', errors='replace') as fh:
                libs += re.findall(r'"path"\s+"([^"]+)"', fh.read())
        except OSError:
            pass
        for lib in libs:
            dirs += [(d, steam) for d in glob.glob(os.path.join(lib, 'steamapps', 'common', 'Proton*'))]
        dirs += [(d, steam) for d in glob.glob(os.path.join(steam, 'compatibilitytools.d', '*'))]
    dirs += [(d, None) for d in glob.glob('/usr/share/steam/compatibilitytools.d/*')]
    seen, out = set(), []
    for d, steam in dirs:
        d = os.path.realpath(d)
        if d not in seen and os.path.isfile(os.path.join(d, 'proton')):
            seen.add(d)
            out.append({'ad': os.path.basename(d), 'route': d, 'steam': steam})
    out.sort(key=lambda p: _version_key(p['ad']), reverse=True)
    return out


def wines():
    """Bulunan wine programları: PATH ve bilinen yerler (macOS'ta Wine uygulamaları ve Homebrew; Finder'dan açılınca PATH kısa)."""
    cands = [shutil.which('wine')]
    if MAC:
        for apps in ('/Applications', os.path.expanduser('~/Applications')):
            cands += ['%s/Wine %s.app/Contents/Resources/wine/bin/wine' % (apps, k) for k in ('Stable', 'Devel', 'Staging', 'Crossover')]
        cands += ['/opt/homebrew/bin/wine', '/usr/local/bin/wine']
    seen, out = set(), []
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK) and os.path.realpath(c) not in seen:
            seen.add(os.path.realpath(c))
            out.append(c)
    return out


@functools.lru_cache(maxsize=8)
def wine_version(wine):
    try:
        return subprocess.run([wine, '--version'], capture_output=True, text=True, timeout=15).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


LIB32 = ('/usr/lib32', '/usr/lib/i386-linux-gnu', '/usr/lib', '/lib32', '/lib/i386-linux-gnu')     # Arch, Debian, Fedora …
ICD_FOLDERS = ('/etc/vulkan/icd.d', '/usr/share/vulkan/icd.d', '/usr/local/share/vulkan/icd.d')


def _elf32(p):
    try:
        with open(p, 'rb') as fh:
            return fh.read(5) == b'\x7fELF\x01'
    except OSError:
        return False


def vulkan32():
    """Bilgisayarda 32 bitlik Vulkan var mı: yükleyici (libvulkan.so.1) ve kütüphanesi 32 bitlik bir sürücü (icd.d'deki json'ın
    library_path'i: tam yol ya da LIB32'de aranan ad)."""
    if not any(_elf32(os.path.join(d, 'libvulkan.so.1')) for d in LIB32):
        return False
    for j in sorted(f for d in ICD_FOLDERS for f in glob.glob(os.path.join(d, '*.json'))):
        try:
            with open(j, encoding='utf8') as fh:
                lib = json.load(fh)['ICD']['library_path']
            paths = [lib] if os.path.isabs(lib) else [os.path.join(d, lib) for d in LIB32]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if any(_elf32(p) for p in paths):
            return True
    return False


def rosetta_error():
    """Apple Silicon'da Rosetta 2 yoksa kullanıcıya gösterilecek metin (Wine x86_64), yoksa None."""
    from wine_engine import has_rosetta
    if not MAC or has_rosetta():
        return None
    return _("Rosetta 2 is not installed: on Apple Silicon the Wine that opens the game runs with it. Install it "
             "on the Client page (your administrator password is asked).")


def find(cfg):
    """Kullanılacak çalıştırıcı -> {'tur': yerel|motor|wine|proton|ozel, 'yol', 'ad', 'onek', 'umu', 'steam', 'hata'}. yol: wine
    programı, Proton klasörü ya da özel komut (motor kurulmadıysa None: OYNA kurar); hata: istemci açılamaz (kullanıcıya gösterilir)."""
    r = {'tur': 'local', 'route': None, 'ad': None, 'prefix': None, 'umu': None, 'steam': None, 'hata': None}
    if WINDOWS:
        return r
    choice, route, prefix = cfg.get('runner'), cfg.get('runner_path').strip(), cfg.get('wine_prefix').strip()
    umu = shutil.which('umu-run') if LINUX else None
    if choice == 'auto':
        choice = 'engine' if MAC else 'proton' if LINUX and (umu or protons()) else 'wine'
    r['tur'] = choice
    if choice == 'ozel':
        r.update(route=route, prefix=os.path.expanduser(prefix) if prefix else None)
        if not route:
            r['hata'] = _('The custom command is empty: enter it in the Wine / Proton card on the Client page.')
        return r
    r['prefix'] = os.path.expanduser(prefix) if prefix else default_prefix(choice)
    if choice == 'engine':
        if not MAC:
            r['hata'] = _("The panel's Wine is for macOS only: choose Automatic or Wine.")
            return r
        m = engine()
        r.update(route=m.wine(), ad=m.name(), hata=rosetta_error())
        return r
    if choice == 'proton':
        if not LINUX:
            r['hata'] = _("Proton runs only on Linux: choose Wine.")
            return r
        found = protons()
        p = found[0] if found else None
        if route:
            d = os.path.expanduser(route)
            d = os.path.dirname(d) if os.path.basename(d) == 'proton' else d
            if not os.path.isfile(os.path.join(d, 'proton')):
                r['hata'] = _('Proton not found: there is no proton script in %s.', d)
                return r
            p = next((x for x in found if x['route'] == os.path.realpath(d)), {'ad': os.path.basename(d), 'route': d, 'steam': None})
        if not p and not umu:
            r['hata'] = _("Proton not found: install a Proton version in Steam (Library > Tools) or choose Wine.")
            return r
        steam = (p and p['steam']) or next(iter(steam_folders()), None)
        r.update(route=p and p['route'], ad=p['ad'] if p else 'UMU-Proton', umu=umu, steam=steam)
        return r
    w = shutil.which(os.path.expanduser(route)) if route else next(iter(wines()), None)
    if not w:
        if route:
            r['hata'] = _('Wine not found: %s', route)
        elif not LINUX:
            r['hata'] = _("Wine not found: choose Automatic (the panel installs the Wine that opens the game) or enter the path of the wine program.")
        elif cfg.get('runner') == 'auto':
            r['hata'] = _("Neither Wine nor Proton was found: install a Proton version in Steam (Library > Tools) or install "
                          "Wine (e.g. sudo apt install wine).")
        else:
            r['hata'] = _("Wine not found: install Wine (e.g. sudo apt install wine) or choose Proton.")
        return r
    r.update(route=w, ad=wine_version(w) or 'wine', hata=rosetta_error())
    return r


def dll_override(env, *extra):
    """WINEDLLOVERRIDES'a eksik girdileri ekle: Wine ve Proton yerleşik winhttp yerine önce oyun klasöründeki BepInEx Doorstop
    winhttp.dll'ini yüklesin (o da gerçek winhttp çağrılarını yerleşik system32/winhttp.dll'e yönlendirir)."""
    parts = [p for p in env.get('WINEDLLOVERRIDES', '').split(';') if p]
    names = {name.strip() for p in parts for name in p.split('=', 1)[0].split(',')}
    for input_ in extra:
        new_ = [name.strip() for name in input_.split('=', 1)[0].split(',')]
        if not names & set(new_):
            parts.append(input_)
            names.update(new_)
    env['WINEDLLOVERRIDES'] = ';'.join(parts)


def command(cfg, exe, args, prepare=True):
    """İstemcinin başlatma komutu ve ortamı -> (komut, ortam); ortam None: panelinki. Çalıştırıcı yoksa (motor kurulmadıysa da)
    RuntimeError. hazirla: önekte S: sürücüsünü kur (gösterilecek komutta False)."""
    r = find(cfg)
    if r['tur'] == 'local':
        return [exe] + args, None
    if r['hata']:
        raise RuntimeError(r['hata'])
    env = dict(os.environ)
    if r['tur'] == 'ozel':
        if r['prefix']:
            env['WINEPREFIX'] = r['prefix']
        dll_override(env, 'winhttp=n,b')
        return shlex.split(r['route']) + [exe] + args, env
    if r['tur'] in ('wine', 'engine'):
        if not r['route']:
            raise RuntimeError(_("The panel's Wine isn't installed yet: press PLAY or install it on the Client page."))
        env['WINEPREFIX'] = r['prefix']
        dll_override(env, 'mscoree,mshtml=', 'winhttp=n,b')      # yeni önekte Mono/Gecko kurulum pencereleri çıkmasın; Doorstop winhttp.dll yüklensin
        env.setdefault('WINEDEBUG', 'fixme-all')                 # wine.log yalnız hatalar
        return [r['route'], game_drive(r['prefix'], exe, prepare)] + args, env
    game = os.path.dirname(os.path.abspath(exe))     # Proton S:'yi bunlardan kurar (umu da geçirir); Steam'siz panel verir
    env.update(PROTON_SET_GAME_DRIVE='1', STEAM_COMPAT_INSTALL_PATH=game, STEAM_COMPAT_LIBRARY_PATHS=os.path.dirname(game))
    dll_override(env, 'winhttp=n,b')
    if not vulkan32():
        env.setdefault('PROTON_USE_WOW64', '1')
    if r['umu']:
        env.update(WINEPREFIX=r['prefix'], PROTON_VERB='run')
        if r['route']:
            env['PROTONPATH'] = r['route']
        return [r['umu'], exe] + args, env
    env.update(STEAM_COMPAT_DATA_PATH=r['prefix'], STEAM_COMPAT_CLIENT_INSTALL_PATH=r['steam'] or r['prefix'])
    return [os.path.join(r['route'], 'proton'), 'run', exe] + args, env


def summary(cfg):
    """İstemci sayfasının Wine / Proton kartı: seçilen ve bulunan çalıştırıcılar (Windows'ta None)."""
    if WINDOWS:
        return None
    return dict(find(cfg), platform='darwin' if MAC else sys.platform, protons=protons(), wines=wines(),
                default_prefix={k: default_prefix(k) for k in ('wine', 'proton', 'engine')}, engine=engine().state() if MAC else None)
