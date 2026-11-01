"""Client fixes with BepInEx: the panel installs BepInEx 6 (Unity IL2CPP, 32 bit) into the client folder and
puts plugin/OpenOrbitPatch.dll into BepInEx/plugins. The patches (auction counter, rank window, shop amount) are in the plugin's source:
plugin/Patches.cs. A user-approved exception (2026-10-24; moved to BepInEx on 2026-10-25, replacing the
earlier memory patches) to the README's "the client is not patched" rule.

The client's own files do not change; BepInEx's files are added next to them (winhttp.dll, doorstop_config.ini, .doorstop_version,
changelog.txt, BepInEx/, dotnet/). Doorstop is off in the config: the panel starts the client with --doorstop-enabled true (client.command), if the same
client is started another way (the official launcher) BepInEx is not loaded. On Linux and macOS, because Wine and Proton load their own built-in
winhttp.dll by default, the runner adds winhttp=n,b to WINEDLLOVERRIDES (client_runner.dll_override): first the Doorstop winhttp.dll in the game folder is
loaded, which in turn redirects to the system's built-in winhttp.dll. BepInEx's console window and the preloading of the interop
assemblies are off (BepInEx/config/BepInEx.cfg; setting()).
On every start it checks whether the plugin's copy is the same as the panel's (renewed when the panel is updated).

Installation: in the setup wizard's game-folder step, when the client is downloaded, from the Client page or at the first PLAY. The BepInEx archive and
Unity's base libraries (BepInEx used to download them on first start; once placed beforehand the first start needs no internet either) are downloaded to memory and unpacked if their SHA-256
matches; when done INSTALL_MARKER is written (a half installation does not count as installed). BepInEx generates the interop assemblies from the client's code (about half
a minute): at the first PLAY, before the game, the panel has this done in a windowless start (warm_up), later starts are fast. If it cannot be installed the game
starts without the fixes.
"""
import hashlib, http.client, io, json, math, os, shutil, subprocess, sys, threading, time, zipfile
from urllib.request import Request, urlopen

import processes as PR
if os.path.dirname(os.path.dirname(os.path.abspath(__file__))) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import save_migration as SM
from lang import t as _
from client_download import CHUNK, TIMEOUT, DownloadError, Cancelled, safe_path

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
# BepInEx bleeding edge (builds.bepinex.dev): be.788 (2026-09-01) tried on 1.1.115 (Unity 2022.3.58, IL2CPP metadata v31).
# When changed the sha256 changes too; it is reinstalled over the installed older one.
BEPINEX = {'name': 'BepInEx 6.0.0-be.788',
           'url': 'https://builds.bepinex.dev/projects/bepinex_be/788/BepInEx-Unity.IL2CPP-win-x86-6.0.0-be.788%2B5b766a3.zip',
           'sha256': 'd5954a5993ec39cd1133603d85bff93875d30b6411b712cc13dcf03c8e08a4d3', 'size': 31440336}
UNITY = {'name': 'Unity 2022.3.58', 'url': 'https://unity.bepinex.dev/libraries/2022.3.58.zip',
         'sha256': '37b5b6d5f3a8761ecd8415302f0283e86c552c822a456faaec33aae533ba32ae', 'size': 1898155,
         'route': 'BepInEx/unity-libs/2022.3.58.zip'}
PLUGIN = os.path.join(PANEL_DIR, 'plugin', 'OpenOrbitPatch.dll')
PLUGIN_PATH = 'BepInEx/plugins/OpenOrbitPatch.dll'
OLD_PLUGIN_PATH = 'BepInEx/plugins/OpenOrbitYama.dll'      # its name before 2026-11-01 (English transition)
SETTINGS = 'BepInEx/config/BepInEx.cfg'
INSTALL_MARKER = 'BepInEx/openorbit.json'        # says that the installation finished, and its version
INTEROP = 'BepInEx/interop/assembly-hash.txt'   # written last, when BepInEx has generated the interop assemblies
ARGS = ['--doorstop-enabled', 'true']
WARMUP = ['-batchmode', '-nographics']           # windowless start to generate the interops (warm_up)
STARTED = 'BepInEx/ErrorLog.log'                # BepInEx writes it at startup (the first stage of the warm-up ends)
INTEROP_FILES = 101                              # files of the interop folder (be.788, 1.1.115: 99 assemblies and 2 .db)


def route(folder, rel):
    return os.path.join(folder, *rel.split('/'))


def installed(folder):
    """Is BepInEx installed in this folder (installation finished, version current)?"""
    return _registry(folder).get('bepinex') == BEPINEX['sha256'] and os.path.isfile(os.path.join(folder, 'winhttp.dll'))


def plugin(folder):
    """Renew the plugin's copy if it differs from the panel's (or is missing)."""
    with open(PLUGIN, 'rb') as fh:
        new_ = fh.read()
    old = route(folder, OLD_PLUGIN_PATH)        # the copy from before the rename: so that two plugins are not loaded at once and the patches applied twice
    if os.path.isfile(old):
        os.remove(old)
    p = route(folder, PLUGIN_PATH)
    try:
        with open(p, 'rb') as fh:
            if fh.read() == new_:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as fh:
        fh.write(new_)


def setting(folder):
    """In BepInEx.cfg turn off preloading of the interop assemblies. When on (BepInEx's default), in the first one or two starts after the interops were freshly
    generated the client hung before loading the first scene (white screen on Windows, Proton code 1; 2026-10-28,
    4/4 started with it off); the plugin loads the assemblies it needs itself. Other settings are not touched."""
    p = route(folder, SETTINGS)
    try:
        with open(p, 'rb') as fh:
            old = fh.read()
    except OSError:
        old = b''
    if b'PreloadIL2CPPInteropAssemblies = false' in old:
        return
    if b'PreloadIL2CPPInteropAssemblies = true' in old:
        new_ = old.replace(b'PreloadIL2CPPInteropAssemblies = true', b'PreloadIL2CPPInteropAssemblies = false', 1)
    else:
        new_ = old + b'\n[IL2CPP]\n\nPreloadIL2CPPInteropAssemblies = false\n'
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as fh:
        fh.write(new_)


def fingerprint(folder):
    """Size and time of the game code (GameAssembly.dll): if the client is updated in place the interops must be regenerated."""
    try:
        st = os.stat(os.path.join(folder, 'GameAssembly.dll'))
    except OSError:
        return None
    return '%d-%d' % (st.st_size, int(st.st_mtime))


def _registry(folder):
    try:
        with open(route(folder, INSTALL_MARKER), encoding='utf8') as fh:
            return SM.migrate_obj(json.load(fh))         # the marker written by the older version (keys to the new names)
    except (OSError, ValueError):
        return {}


def generated(folder):
    """Has BepInEx generated the interop assemblies?"""
    return os.path.isfile(route(folder, INTEROP))


def ready(folder):
    """Were the interops generated for this client code? If there is no fingerprint recorded by the warm-up (installation by an earlier panel version)
    the client counts as updated if GameAssembly.dll is newer than the interops."""
    if not generated(folder):
        return False
    trace = _registry(folder).get('warmup')
    if trace:
        return trace == fingerprint(folder)
    try:
        return os.path.getmtime(os.path.join(folder, 'GameAssembly.dll')) <= os.path.getmtime(route(folder, INTEROP))
    except OSError:
        return True


def progress(folder, start, seen):
    """Warm-up progress -> {'stage': 0 client starting, 1 assemblies being generated, 2 files being written, 3 done; 'percent', 'elapsed_sec'}.
    BepInEx does not write its log to disk until generation finishes (Windows and Wine, 2026-10-28): the stages are taken from files (STARTED, the interop
    folder). Generation is invisible from inside: the percentage advances slowing down with time, while writing by the file count. seen: the state warm_up keeps."""
    now = time.time()
    try:
        started = os.path.getmtime(route(folder, STARTED)) >= start - 1   # does not count as the previous start's
    except OSError:
        started = False
    try:
        written = len(os.listdir(route(folder, 'BepInEx/interop')))
    except OSError:
        written = 0
    stage = 3 if generated(folder) else 2 if written else 1 if started or now - start > 10 else 0
    t = now - seen.setdefault(stage, now)
    sub = seen.setdefault('write', seen.get('percent', 0)) if stage == 2 else 0   # writing continues without a jump from what is shown
    percent = (100 if stage == 3 else sub + (99 - sub) * min(1, written / INTEROP_FILES) if stage == 2
             else 10 + 80 * (1 - math.exp(-t / 25)) if stage == 1 else 9 * (1 - math.exp(-t / 4)))
    seen['percent'] = max(seen.get('percent', 0), int(percent))
    return {'stage': stage, 'percent': seen['percent'], 'elapsed_sec': int(now - start)}


def warm_up(folder, cmd, env, logs, notify=None, duration=300):
    """Have the interop assemblies generated before the game in a separate, windowless start -> is it ready. If generation happens in the game's own start
    the 32-bit client's address space runs out: on Proton the game closed on the first scene with "System out of memory" (2026-10-28).
    cmd, env: client.command (with the BepInEx arguments); when generation finishes (or duration runs out) this start is closed. notify: progress()'s
    result every half second (the panel's PLAY step)."""
    start, seen = time.time(), {}
    shutil.rmtree(route(folder, 'BepInEx/interop'), ignore_errors=True)    # the old client's interops: let them be regenerated
    p = PR.open_client(folder, cmd + WARMUP, env, logs)
    last = start + duration
    while time.time() < last and p.poll() is None and not generated(folder):
        if notify:
            notify(progress(folder, start, seen))
        time.sleep(0.5)
    if notify:
        notify(progress(folder, start, seen))
    PR.close_client(p)
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        PR.kill(p.pid)
    if generated(folder):                            # ready(): if the client code changes it warms up again
        d = _registry(folder)
        d['warmup'] = fingerprint(folder)
        with open(route(folder, INSTALL_MARKER), 'w', encoding='utf8') as fh:
            json.dump(d, fh, indent=1)
    last = time.time() + 15
    while os.name != 'nt' and time.time() < last:   # Wine starts every Windows process in its own session: closing the group does not reach the client
        remaining = warmup_processes()
        if not remaining:
            break
        for pid in remaining:
            PR.kill(pid)
        time.sleep(0.5)
    return generated(folder)


def warmup_processes():
    """Linux and macOS: the open warm-up clients (DarkOrbit.exe ... -batchmode in Wine)."""
    try:
        r = subprocess.run(['ps', '-A', '-o', 'pid=', '-o', 'args='], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(s.split(None, 1)[0]) for s in r.stdout.splitlines()
            if 'darkorbit.exe' in s.lower() and ' %s ' % WARMUP[0] in s + ' ' and 'python' not in s.lower()]


def arguments(folder):
    """The arguments that start the client with BepInEx (none if not installed); the plugin's copy and the setting are renewed first."""
    if not installed(folder):
        return []
    plugin(folder)
    setting(folder)
    return list(ARGS)


class Patcher:
    def __init__(self, log=print, opener=urlopen):
        self.log, self.opener = log, opener
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.d = self._blank('none', None)

    @staticmethod
    def _blank(state, folder):
        return {'state': state, 'running': False, 'claimed': 0, 'total': BEPINEX['size'] + UNITY['size'], 'error': None,
                'folder': folder}

    def state(self, folder):
        """The state of the installation in folder (another folder's finished work does not count)."""
        with self.lock:
            d = dict(self.d)
        if not d['running'] and (not folder or not d['folder'] or os.path.normcase(os.path.abspath(d['folder']))
                                   != os.path.normcase(os.path.abspath(folder))):
            d = self._blank('none', folder)
        if not d['running'] and folder and installed(folder):
            d['state'] = 'built'
        d.update(required=True, name=BEPINEX['name'])
        return d

    def running(self):
        with self.lock:
            return self.d['running']

    def start(self, folder):
        """Install BepInEx and the plugin into the client folder (does nothing if in progress or installed) -> state."""
        with self.lock:
            if folder and not self.d['running'] and not installed(folder):
                self.stop.clear()
                self.d = dict(self._blank('downloading', folder), running=True)
                threading.Thread(target=self._run, args=(folder,), daemon=True).start()
        return self.state(folder)

    def cancel(self):
        self.stop.set()

    def wait(self, folder, step=None):
        """Wait until the installation finishes (step: (percent) -> None, progress) -> was it installed."""
        self.start(folder)
        while self.running():
            if step:
                st = self.state(folder)
                step(int(100 * st['claimed'] / st['total']))
            time.sleep(0.3)
        return installed(folder)

    def _download(self, part):
        """Download the archive to memory and verify its SHA-256 -> bytes."""
        buf = bytearray()
        try:
            with self.opener(Request(part['url'], headers={'User-Agent': 'OpenOrbit'}), timeout=TIMEOUT) as r:
                while True:
                    if self.stop.is_set():
                        raise Cancelled()
                    b = r.read(CHUNK)
                    if not b:
                        break
                    buf += b
                    with self.lock:
                        self.d['claimed'] += len(b)
        except (OSError, http.client.HTTPException) as e:
            raise DownloadError(_('Could not connect to the download server (check your internet connection): %s', e))
        if hashlib.sha256(buf).hexdigest() != part['sha256']:
            raise DownloadError(_('%s is not the expected file (SHA-256 mismatch): try again.', part['name']))
        return bytes(buf)

    def _run(self, folder):
        try:
            self.log('downloading BepInEx: %s, %s' % (BEPINEX['url'], UNITY['url']))
            archive, unity = self._download(BEPINEX), self._download(UNITY)
            with self.lock:
                self.d['state'] = 'installing'
            with zipfile.ZipFile(io.BytesIO(archive)) as z:
                for m in z.infolist():
                    p = safe_path(folder, m.filename)
                    if m.is_dir():
                        os.makedirs(p, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with z.open(m) as src, open(p, 'wb') as out:
                        shutil.copyfileobj(src, out)
            p = os.path.join(folder, 'doorstop_config.ini')      # Doorstop off: only the panel's argument starts BepInEx
            with open(p, 'rb') as fh:
                ini = fh.read()
            with open(p, 'wb') as fh:
                fh.write(ini.replace(b'enabled = true', b'enabled = false', 1))
            p = route(folder, SETTINGS)
            if not os.path.isfile(p):                           # do not open the console window (BepInEx adds the other settings)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'wb') as fh:
                    fh.write(b'[Logging.Console]\n\nEnabled = false\n')
            setting(folder)
            p = route(folder, UNITY['route'])
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as fh:
                fh.write(unity)
            plugin(folder)
            with open(route(folder, INSTALL_MARKER), 'w', encoding='utf8') as fh:
                json.dump({'bepinex': BEPINEX['sha256'], 'unity': UNITY['sha256'], 'name': BEPINEX['name'],
                           'time': time.strftime('%Y-%m-%d %H:%M:%S')}, fh, indent=1)
            with self.lock:
                self.d.update(state='built', claimed=self.d['total'])
            self.log('BepInEx installed: %s (%s)' % (BEPINEX['name'], folder))
        except Cancelled:
            with self.lock:
                self.d['state'] = 'stopped'
            self.log('BepInEx installation stopped')
        except DownloadError as e:
            with self.lock:
                self.d.update(state='error', error=str(e))
            self.log('BepInEx could not be installed: %s' % e)
        except OSError as e:
            with self.lock:
                self.d.update(state='error', error=_('Could not write a file: %s', e))
            self.log('BepInEx could not be installed: %r' % e)
        except Exception as e:
            with self.lock:
                self.d.update(state='error', error=repr(e))
            self.log('BepInEx: unexpected error: %r' % e)
        finally:
            with self.lock:
                self.d['running'] = False
