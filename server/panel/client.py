"""The game client (the original Unity client): folder validation, automatic discovery, version, launch arguments.

Folder: the folder holding DarkOrbit.exe and DarkOrbit_Data/ (like DarkOrbit_Version1.1.117). If the panel setting is empty, the newest
version folder in the project root is used; if an update arrives or the folder is moved, it is chosen from the panel. If it is not on the
computer the panel downloads it (client_download.py; the temporary folder of a half-finished download is not a candidate). The server was
written for the protocol of 1.1.117 (data/protocol*.json from the client's code); 1.1.116 has the same protocol (COMPATIBLE): it plays and
the panel only suggests the update. With another version the panel warns.
The client's files are not changed; only a launch argument is passed (local web login 127.0.0.1:8090). The BepInEx installed next to the
client (client_patch.py) loads the client's fixes, and if installed it is launched with the argument. On Linux and macOS the client is
opened with Wine or Proton (client_runner.py).
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
SUPPORTED = '1.1.117'          # if the active protocol has no version (server/data/protocols/version.txt; written by protocol_update.py)
COMPATIBLE = ('1.1.116',)      # older clients with the same protocol as SUPPORTED: they play, the panel suggests the update without forcing it
VERSION_FILE = os.path.join(SERVER, 'data', 'protocols', 'version.txt')


def supported():
    """The client version of the server's active protocol: the newer of version.txt and SUPPORTED. version.txt (written by the protocol tool) is kept
    in a panel update; if the update brought the new version's protocol it stays old (2026-10-28: a copy saying 1.1.115 did not
    show the 1.1.116 update warning)."""
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
    """The game's own version (Unity PlayerSettings.bundleVersion) from DarkOrbit_Data/globalgamemanagers: 4-byte LE length + text,
    then zero padding. The Unity engine's version (2022.3.58f1) is in the same file but the length prefix is not in that format; None if unknown."""
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
    """Version: from the folder name (DarkOrbit_Version1.1.117), otherwise from the game's data (bundle_version; the official install is in the "DarkOrbit Unity"
    folder), otherwise from the exe's file version (if it is the Unity engine's version, e.g. 2022.3.58, it does not count); None if unknown."""
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
        if ms >> 16 >= 2000:                      # Unity's year-style engine version, not the game's
            return None
        return '%d.%d.%d' % (ms >> 16, ms & 0xFFFF, ls >> 16)
    except Exception:
        return None


def check(folder):
    """Validate the folder -> {'valid', 'route', 'exe', 'data', 'version', 'compatible', 'issues' [...], 'size_mb'} plus a flag for a folder
    older than the supported version (the panel updates; a compatible old one only gets the suggestion)."""
    out = {'route': folder or '', 'valid': False, 'exe': False, 'data': False, 'version': None, 'compatible': False, 'old': False,
           'issues': []}
    if not folder:
        out['issues'].append(_('No client folder selected.'))
        return out
    if not os.path.isdir(folder):
        out['issues'].append(_('Folder not found.'))
        return out
    out['exe'] = os.path.isfile(os.path.join(folder, EXE))
    out['data'] = os.path.isdir(os.path.join(folder, DATA_DIR))
    if not out['exe']:
        out['issues'].append(_('The folder has no %s.', EXE))
    if not out['data']:
        out['issues'].append(_('The folder has no %s folder.', DATA_DIR))
    out['valid'] = out['exe'] and out['data']
    if out['valid']:
        out['version'] = version_of(folder)
        out['compatible'] = out['version'] == supported() or (out['version'] in COMPATIBLE and supported() == SUPPORTED)
        out['old'] = bool(out['version']) and vkey(out['version']) < vkey(supported())
        if out['version'] and not out['compatible']:
            out['issues'].append(_('The server was written for version %s; if the protocol differs in version %s, the login or some '
                                   'windows may not work.', supported(), out['version']))
        out['metadata'] = os.path.isfile(os.path.join(folder, DATA_DIR, 'il2cpp_data', 'Metadata', 'global-metadata.dat'))
    return out


def candidates():
    """Possible client folders: project root, Program Files, LocalAppData, desktop, Downloads (newest version first)."""
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
    out.sort(key=lambda c: (c['compatible'], vkey(c['version'])), reverse=True)
    return out


def resolve(configured):
    """The folder in the setting, otherwise the best folder found (may be None)."""
    if configured:
        return configured
    c = candidates()
    return c[0]['route'] if c else None


def args(cfg, log_file, session=None, window=False):
    """Unity launch arguments (from the panel settings). session: the extra client of multi-client (the web.py login page finds its
    record via ?session=); window: a window mode independent of the setting (extra clients)."""
    a = [LOGIN_URL.replace('/#', '/?session=%s#' % session) if session else LOGIN_URL]
    mode = 'windowed' if window else cfg.get('window_mode')
    if mode == 'fullscreen':
        a += ['-screen-fullscreen', '1', '-window-mode', 'exclusive']
    elif mode == 'borderless':                       # borderless fullscreen window (Unity 2019.3+)
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
    """The client's launch command and environment -> (command, environment): on Windows DarkOrbit.exe directly, on Linux and macOS with Wine or Proton
    (client_runner.py; prepare: install the client's driver in the prefix). If BepInEx is installed, also the arguments that enable it (client_patch.py).
    RuntimeError if no runner is found."""
    return RUN.command(cfg, os.path.join(folder, EXE), args(cfg, RUN.win_path(log_file), session, window) + PATCH.arguments(folder),
                     prepare)


# the Wine process's command line has a Windows path: Z:\...\DarkOrbit.exe or S:\<folder>\DarkOrbit.exe ... (the commands that open Wine or Proton,
# not steam.exe)
WINE_CLIENT = re.compile(r'"?[a-z]:\\(?:(?!\.exe).)*\\%s\b' % re.escape(EXE.lower()))


def running_clients(exclude=()):
    """IDs of the running DarkOrbit.exe processes (including those the panel did not open); exclude: processes not to count. On Linux and macOS the excluded
    process group is not counted either (processes.open_client creates the group with the process it opens: in Proton the client is its grandchild)."""
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
