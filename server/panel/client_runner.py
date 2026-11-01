"""The layer that opens the client outside Windows (panel): the original client is a 32-bit Windows program (DarkOrbit.exe, Unity); on Linux and
macOS it is opened with Wine or Proton. On Windows the command is just the exe and its arguments.

Panel settings (config.py):
  runner            auto | engine | wine | proton | special. auto: on Linux Proton (umu-run or Steam's Proton), otherwise Wine;
                    on macOS engine. engine (macOS only): the Wine + DXMT the panel installs itself (wine_engine.py; downloaded on the first PLAY or from the Client
                    page): plain Wine on macOS cannot render the game's Direct3D 11. Proton is Linux only.
  runner_path       wine: the wine program; proton: the Proton folder (the one with the proton script in it); special: a command to prepend to the client
                    (e.g. CrossOver's wine with --bottle). If empty it is found automatically (required for special).
  wine_prefix       Wine prefix (WINEPREFIX) or Proton's data folder (STEAM_COMPAT_DATA_PATH). If empty save/wine or save/proton:
                    the client in a prefix separate from other Wine programs; the prefix is set up on the first launch (can take about half a minute).
On Apple Silicon Wine (x86_64) needs Rosetta 2: without it find() raises an error and the panel gets it installed (wine_engine.install_rosetta).
Proton is opened without Steam: with umu-run if installed (in the Steam Linux Runtime container; PROTONPATH is the Proton found, otherwise umu downloads its own
Proton), otherwise with "proton run" (STEAM_COMPAT_CLIENT_INSTALL_PATH is Steam's folder; the data folder if there is no Steam). The verb is "run": extra
clients (multi_client.py) are opened together in the same prefix (waitforexitandrun would wait for the previous one to close). Under Proton the client is
opened from the S: drive (PROTON_SET_GAME_DRIVE as in Steam; S: is the parent of the client folder): reported, the embedded Chromium
(Vuplex) does not work when opened from Z:. Under Wine (engine too) the panel maps S: in the prefix itself (game_drive). Other file paths given to the client go through the Z:
drive (the Unix root in Wine and Proton prefixes). Wine's output goes to logs/wine.log (processes.open_client).
Proton's DXVK opens Direct3D 11 in the 32-bit client with 32-bit Vulkan: if the computer does not have that (vulkan32) the client crashed with "d3d11: failed
to create factory" (reported, Proton 11 without Steam; Steam's container brings the loader itself). In that case Proton is opened in the new
WoW64 mode (PROTON_USE_WOW64=1, Proton 10 and later): the 32-bit client uses 64-bit Vulkan.
"""
import functools, glob, json, os, re, shlex, shutil, subprocess, sys

from lang import t as _

WINDOWS, LINUX, MAC = os.name == 'nt', sys.platform.startswith('linux'), sys.platform == 'darwin'   # tests change it


def default_prefix(kind):
    """save/wine or save/proton (motor uses save/wine too; the paths are imported here: some import client.py only through the panel/ path)."""
    import paths
    return os.path.join(paths.SAVE, 'wine' if kind == 'engine' else kind)


_engine = None


def engine():
    """The panel's Wine engine (wine_engine.WineEngine; the panel and the runner use the same object)."""
    global _engine
    if _engine is None:
        import paths
        from wine_engine import WineEngine
        _engine = WineEngine(paths.SAVE)
    return _engine


def win_path(p):
    """The file path to give to a Windows program in Wine (Z: Unix root); unchanged on Windows."""
    return p if WINDOWS else 'Z:' + os.path.abspath(p).replace('/', '\\')


GAME_DRIVE = 's:'


def game_drive(prefix, exe, link=True):
    """In the Wine prefix S: is mapped to the parent of the client folder (like Proton's PROTON_SET_GAME_DRIVE; spaces in the path also go away) ->
    the client's Windows path (S:\\<folder>\\DarkOrbit.exe). kur: set up the mapping (otherwise only the path). In a new prefix dosdevices is
    opened as Wine sets it up (Wine fills it only if it does not exist: c: -> ../drive_c, z: -> /). If S: is something else, the Z: path."""
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
    """Folders where Steam is installed (local package, Flatpak, Snap)."""
    home, out = os.path.expanduser('~'), []
    for p in ('.steam/root', '.steam/steam', '.local/share/Steam', '.var/app/com.valvesoftware.Steam/data/Steam',
              'snap/steam/common/.local/share/Steam'):
        d = os.path.realpath(os.path.join(home, p))
        if d not in out and os.path.isdir(os.path.join(d, 'steamapps')):
            out.append(d)
    return out


def _version_key(name):
    """Proton - Experimental is the newest; the others by the numbers in their names (Proton 9.0, GE-Proton10-3)."""
    return (999,) if 'experimental' in name.lower() else tuple(int(x) for x in re.findall(r'\d+', name)) or (0,)


def protons():
    """The Proton installations found [{'ad', 'yol', 'steam'}], newest first: the Protons in the Steam libraries (steamapps/common) and extra
    compatibility tools (compatibilitytools.d: GE-Proton ...). Empty outside Linux."""
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
            out.append({'name': os.path.basename(d), 'route': d, 'steam': steam})
    out.sort(key=lambda p: _version_key(p['name']), reverse=True)
    return out


def wines():
    """The wine programs found: PATH and known places (on macOS Wine apps and Homebrew; PATH is short when opened from Finder)."""
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
    """Is there 32-bit Vulkan on the computer: the loader (libvulkan.so.1) and a driver whose library is 32-bit (the library_path of the json in icd.d:
    a full path or a name searched in LIB32)."""
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
    """The text to show the user if Rosetta 2 is missing on Apple Silicon (Wine x86_64), otherwise None."""
    from wine_engine import has_rosetta
    if not MAC or has_rosetta():
        return None
    return _("Rosetta 2 is not installed: on Apple Silicon the Wine that opens the game runs with it. Install it "
             "on the Client page (your administrator password is asked).")


def find(cfg):
    """The runner to use -> {'type': local|engine|wine|proton|special, 'route', 'name', 'prefix', 'umu', 'steam', 'error'}. route: the wine
    program, the Proton folder or the custom command (None if the engine is not installed: PLAY installs it); error: the client cannot be opened (shown to the user)."""
    r = {'type': 'local', 'route': None, 'name': None, 'prefix': None, 'umu': None, 'steam': None, 'error': None}
    if WINDOWS:
        return r
    choice, route, prefix = cfg.get('runner'), cfg.get('runner_path').strip(), cfg.get('wine_prefix').strip()
    umu = shutil.which('umu-run') if LINUX else None
    if choice == 'auto':
        choice = 'engine' if MAC else 'proton' if LINUX and (umu or protons()) else 'wine'
    r['type'] = choice
    if choice == 'special':
        r.update(route=route, prefix=os.path.expanduser(prefix) if prefix else None)
        if not route:
            r['error'] = _('The custom command is empty: enter it in the Wine / Proton card on the Client page.')
        return r
    r['prefix'] = os.path.expanduser(prefix) if prefix else default_prefix(choice)
    if choice == 'engine':
        if not MAC:
            r['error'] = _("The panel's Wine is for macOS only: choose Automatic or Wine.")
            return r
        m = engine()
        r.update(route=m.wine(), name=m.name(), error=rosetta_error())
        return r
    if choice == 'proton':
        if not LINUX:
            r['error'] = _("Proton runs only on Linux: choose Wine.")
            return r
        found = protons()
        p = found[0] if found else None
        if route:
            d = os.path.expanduser(route)
            d = os.path.dirname(d) if os.path.basename(d) == 'proton' else d
            if not os.path.isfile(os.path.join(d, 'proton')):
                r['error'] = _('Proton not found: there is no proton script in %s.', d)
                return r
            p = next((x for x in found if x['route'] == os.path.realpath(d)), {'name': os.path.basename(d), 'route': d, 'steam': None})
        if not p and not umu:
            r['error'] = _("Proton not found: install a Proton version in Steam (Library > Tools) or choose Wine.")
            return r
        steam = (p and p['steam']) or next(iter(steam_folders()), None)
        r.update(route=p and p['route'], name=p['name'] if p else 'UMU-Proton', umu=umu, steam=steam)
        return r
    w = shutil.which(os.path.expanduser(route)) if route else next(iter(wines()), None)
    if not w:
        if route:
            r['error'] = _('Wine not found: %s', route)
        elif not LINUX:
            r['error'] = _("Wine not found: choose Automatic (the panel installs the Wine that opens the game) or enter the path of the wine program.")
        elif cfg.get('runner') == 'auto':
            r['error'] = _("Neither Wine nor Proton was found: install a Proton version in Steam (Library > Tools) or install "
                          "Wine (e.g. sudo apt install wine).")
        else:
            r['error'] = _("Wine not found: install Wine (e.g. sudo apt install wine) or choose Proton.")
        return r
    r.update(route=w, name=wine_version(w) or 'wine', error=rosetta_error())
    return r


def dll_override(env, *extra):
    """Add the missing entries to WINEDLLOVERRIDES: so that Wine and Proton load the BepInEx Doorstop winhttp.dll in the game folder before the built-in
    winhttp (which in turn forwards the real winhttp calls to the built-in system32/winhttp.dll)."""
    parts = [p for p in env.get('WINEDLLOVERRIDES', '').split(';') if p]
    names = {name.strip() for p in parts for name in p.split('=', 1)[0].split(',')}
    for input_ in extra:
        new_ = [name.strip() for name in input_.split('=', 1)[0].split(',')]
        if not names & set(new_):
            parts.append(input_)
            names.update(new_)
    env['WINEDLLOVERRIDES'] = ';'.join(parts)


def command(cfg, exe, args, prepare=True):
    """The client's launch command and environment -> (command, environment); environment None: the panel's. RuntimeError if there is no runner
    (also if the engine is not installed). prepare: set up the S: drive in the prefix (False in the command to be shown)."""
    r = find(cfg)
    if r['type'] == 'local':
        return [exe] + args, None
    if r['error']:
        raise RuntimeError(r['error'])
    env = dict(os.environ)
    if r['type'] == 'special':
        if r['prefix']:
            env['WINEPREFIX'] = r['prefix']
        dll_override(env, 'winhttp=n,b')
        return shlex.split(r['route']) + [exe] + args, env
    if r['type'] in ('wine', 'engine'):
        if not r['route']:
            raise RuntimeError(_("The panel's Wine isn't installed yet: press PLAY or install it on the Client page."))
        env['WINEPREFIX'] = r['prefix']
        dll_override(env, 'mscoree,mshtml=', 'winhttp=n,b')      # so that Mono/Gecko installer windows do not appear in a new prefix; so that Doorstop winhttp.dll is loaded
        env.setdefault('WINEDEBUG', 'fixme-all')                 # wine.log only errors
        return [r['route'], game_drive(r['prefix'], exe, prepare)] + args, env
    game = os.path.dirname(os.path.abspath(exe))     # Proton sets up S: from these (umu passes them too); without Steam the panel supplies them
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
    """The Wine / Proton card of the Client page: the selected and found runners (None on Windows)."""
    if WINDOWS:
        return None
    return dict(find(cfg), platform='darwin' if MAC else sys.platform, protons=protons(), wines=wines(),
                default_prefix={k: default_prefix(k) for k in ('wine', 'proton', 'engine')}, engine=engine().state() if MAC else None)
