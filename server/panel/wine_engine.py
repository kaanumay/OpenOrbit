"""macOS: the panel itself installs the Wine that opens the client (runner 'engine', what Automatic picks on macOS). An open-source Wine build
(ENGINE) and DXMT (a layer that translates Direct3D 11 to Metal, github.com/3Shain/dxmt) are downloaded into save/wine_engine/; the user installs nothing.
On Apple Silicon only Rosetta 2 is needed (Wine x86_64): the panel's button installs it with macOS's admin dialog (install_rosetta).

Why these two: the client is 32-bit and Direct3D 11 only (Unity 2022.3). Because macOS's OpenGL stays at 4.1, Wine's own D3D11
(wined3d) does not start; DXVK does not work in 32-bit on MoltenVK (GitHub issue #7). DXMT works but Wine's winemac.drv must expose the
functions DXMT wants (macdrv_functions) (WineHQ's plain macOS builds do not), and because the embedded browser (Vuplex) opens a shared
D3D11 texture, Wine 10.18 or newer is required (D3DKMT; Vuplex crashes on Wine 10.0-based engines). ENGINE meets both.

Archives are not saved to disk: they are unpacked while streaming from HTTP (client_download.HttpFile; a dropped connection resumes from the same byte). SHA-256 is
computed while streaming, and if it does not match everything unpacked is deleted. From the archive only what is under 'root' is taken. DXMT's builtin DLLs
are copied into the engine's lib/wine/<arch>/ folders: in every prefix d3d11, dxgi and d3d10core become DXMT (no DLL is put in the prefix, no override
is needed). The install is assembled in a temporary folder and takes its name when done: a half install is not used. One job at a time.
"""
import functools, hashlib, json, os, platform, shutil, subprocess, sys, tarfile, threading, time

from lang import t as _
from client_download import CHUNK, HttpFile, DownloadError, Cancelled

MAC = sys.platform == 'darwin'
# ENGINE: the Wine runtime of frankea/Whisky: CrossOver's open-source Wine (winecx) based on Wine 11.16, built with CI on GitHub
# (github.com/frankea/winecx-gptk); only Wine is taken from the archive. On 2026-10-25 the client (including the Vuplex login) opened with it on
# an Apple M4 / macOS 27. Sikarugir's Wine 11.0 and Wine Staging 11.8 + DXMT also expose DXMT's functions (not tried).
# When changed, the sha256 changes too; the old engine is deleted on the new install.
ENGINE = {'name': 'Wine 11.16 (winecx)', 'version': 'whisky-4.6.4-beta.1',
         'url': 'https://github.com/frankea/Whisky/releases/download/v4.6.4-beta.1/Libraries.tar.gz',
         'sha256': 'c8e6a10dfeb54fc16d3dd3382ee2e9d2cec3eb1f5641613cad8b07903818cb12', 'size': 481348675, 'root': 'Libraries/Wine'}
DXMT = {'name': 'DXMT 0.80', 'version': '0.80', 'url': 'https://github.com/3Shain/dxmt/releases/download/v0.80/dxmt-v0.80-builtin.tar.gz',
        'sha256': '8f260e36b5739e68f3bad613381441385c4dc7b85b78ba8de653d5a6a264529d', 'size': 18681669, 'root': 'v0.80'}
DXMT_ARCHS = ('x86_64-unix', 'x86_64-windows', 'i386-windows')
MIN_MACOS = (14, 0)                # DXMT: macOS 14 Sonoma
INSTALL_MARKER = 'install.json'                  # says that the install is finished and its versions


@functools.lru_cache(maxsize=1)
def apple_silicon():
    """Is this an Apple Silicon Mac (even if Python runs as x86_64 under Rosetta)?"""
    if not MAC:
        return False
    try:
        return subprocess.run(['sysctl', '-n', 'hw.optional.arm64'], capture_output=True, text=True, timeout=5).stdout.strip() == '1'
    except (OSError, subprocess.SubprocessError):
        return platform.machine() == 'arm64'


_rosetta = {'exists': False, 'time': 0.0}


def has_rosetta():
    """Is Rosetta 2 installed (not needed on an Intel Mac or outside macOS: True)? Status polls are frequent: once found installed it is always True, otherwise
    retried every few seconds."""
    if not apple_silicon() or _rosetta['exists']:
        return True
    if time.monotonic() - _rosetta['time'] < 3:
        return False
    try:
        var = subprocess.run(['/usr/bin/arch', '-x86_64', '/usr/bin/true'], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        var = False
    _rosetta.update(exists=var, time=time.monotonic())
    return var


def macos_version():
    try:
        return tuple(int(x) for x in platform.mac_ver()[0].split('.')[:2])
    except ValueError:
        return (0, 0)


class _Digest:
    """SHA-256 of the bytes read (under the tarfile stream). tarfile reads in 10 KB pieces; reading like that over HTTPS did not exceed
    1 MB per second (with 1 MB reads it is over 40 MB/s): reads are served from a CHUNK-sized buffer (a short read is enough for streaming)."""

    def __init__(self, f):
        self.f, self.h = f, hashlib.sha256()
        self.buf, self.pos = b'', 0

    def read(self, n=-1):
        if n is None or n < 0:
            b = self.buf[self.pos:] + self.f.read()
        else:
            if self.pos >= len(self.buf):
                self.buf, self.pos = self.f.read(max(n, CHUNK)), 0
            b = self.buf[self.pos:self.pos + n]
        self.pos += len(b)
        self.h.update(b)
        return b

    def drain(self):
        while self.read(1 << 20):
            pass
        return self.h.hexdigest()


def _extract(tf, root, target):
    """Unpack what is under root/ from the tarfile stream to the target (paths stay inside the target; links too)."""
    on = root.strip('/') + '/'
    os.makedirs(target, exist_ok=True)
    real_target = os.path.realpath(target)
    for m in tf:
        if not m.name.startswith(on):
            continue
        rel = m.name[len(on):].strip('/')
        parts = [p for p in rel.split('/') if p not in ('', '.')]
        if not parts:
            continue
        if any(p == '..' for p in parts):
            raise DownloadError(_('Invalid path in the archive: %s', m.name))
        p = os.path.join(target, *parts)
        if m.isdir():
            os.makedirs(p, exist_ok=True)
        elif m.issym():
            t = os.path.normpath(os.path.join(os.path.dirname(p), m.linkname))
            if os.path.isabs(m.linkname) or not os.path.realpath(t).startswith(real_target + os.sep):
                raise DownloadError(_('Invalid link in the archive: %s', m.name))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if os.path.lexists(p):
                os.remove(p)
            os.symlink(m.linkname, p)
        elif m.islnk():                                 # hard link: its target was unpacked earlier (in order in the stream)
            src = m.linkname[len(on):] if m.linkname.startswith(on) else None
            if not src or '..' in src.split('/'):
                raise DownloadError(_('Invalid link in the archive: %s', m.name))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            shutil.copy2(os.path.join(target, *src.split('/')), p)
        elif m.isfile():
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with tf.extractfile(m) as src, open(p, 'wb') as out:
                shutil.copyfileobj(src, out, 1 << 20)
            os.chmod(p, 0o755 if m.mode & 0o111 else 0o644)


class WineEngine:
    def __init__(self, save_dir, log=print, opener=None):
        self.root = os.path.join(save_dir, 'wine_engine')
        self.log, self.opener = log, opener
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.d = self._blank('none')
        self.samples = []
        self.ros = {'state': 'vacant', 'error': None}

    @staticmethod
    def _blank(state):
        return {'state': state, 'running': False, 'claimed': 0, 'total': 0, 'speed': 0, 'time_left_sec': None, 'error': None, 'part': None}

    # ------------------------------------------------------------ installed engine
    def folder(self):
        return os.path.join(self.root, ENGINE['version'])

    def wine(self):
        """The installed engine's wine program or None (install not finished, its version old)."""
        k = self.folder()
        try:
            with open(os.path.join(k, INSTALL_MARKER), encoding='utf8') as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return None
        w = os.path.join(k, 'bin', 'wine')
        return w if d.get('engine') == ENGINE['sha256'] and d.get('dxmt') == DXMT['sha256'] and os.path.isfile(w) else None

    def name(self):
        return '%s + %s' % (ENGINE['name'], DXMT['name'])

    def state(self):
        with self.lock:
            d = json.loads(json.dumps(self.d))
            ros = dict(self.ros)
        installed = self.wine()
        if not d['running'] and installed:
            d['state'] = 'built'
        d.update(route=installed, name=self.name(), size=ENGINE['size'] + DXMT['size'], folder=self.folder(),
                 rosetta=dict(ros, required=apple_silicon(), exists=has_rosetta()),
                 macos=platform.mac_ver()[0] if MAC else None, macos_old=MAC and macos_version() < MIN_MACOS)
        return d

    def running(self):
        with self.lock:
            return self.d['running']

    # ------------------------------------------------------------ setup
    def start(self):
        """Download and install the engine and DXMT (does nothing if running or installed) -> status."""
        with self.lock:
            busy = self.d['running']
            if not busy and not self.wine():
                self.stop.clear()
                self.d = dict(self._blank('downloading'), running=True, total=ENGINE['size'] + DXMT['size'])
                self.samples = []
                threading.Thread(target=self._run, daemon=True).start()
        return self.state()

    def cancel(self):
        self.stop.set()
        return self.state()

    def _count(self, n):
        now = time.monotonic()
        with self.lock:
            self.d['claimed'] += n
            self.samples.append((now, self.d['claimed']))
            while len(self.samples) > 2 and now - self.samples[0][0] > 8:
                self.samples.pop(0)
            t0, b0 = self.samples[0]
            if now - t0 >= 1:
                self.d['speed'] = int((self.d['claimed'] - b0) / (now - t0))
                left = max(0, self.d['total'] - self.d['claimed'])
                self.d['time_left_sec'] = int(left / self.d['speed']) if self.d['speed'] > 0 else None

    def _download_extract(self, part, target):
        """Unpack the archive to the target while streaming and verify its SHA-256."""
        with self.lock:
            self.d['part'] = part['name']
        kw = {'opener': self.opener} if self.opener else {}
        f = HttpFile(part['url'], self.stop, self._count, **kw)
        try:
            src = _Digest(f)
            with tarfile.open(fileobj=src, mode='r|*') as tf:
                _extract(tf, part['root'], target)
            summary = src.drain()
        except tarfile.TarError as e:
            raise DownloadError(_('The archive arrived damaged (%s): try again.', e))
        finally:
            f.close()
        if summary != part['sha256']:
            raise DownloadError(_("The %s archive isn't the expected file (SHA-256 mismatch): try again.", part['name']))

    def _run(self):
        temporary = os.path.join(self.root, '.kuruluyor')
        try:
            if os.path.isdir(temporary):
                shutil.rmtree(temporary)
            os.makedirs(temporary)
            free = shutil.disk_usage(self.root).free
            if free < 1600 << 20:
                raise DownloadError(_('Not enough disk space: %.1f GB needed, %.1f GB free.', 1.6, free / float(1 << 30)))
            self.log('Wine engine downloading: %s, %s' % (ENGINE['url'], DXMT['url']))
            engine, dxmt = os.path.join(temporary, 'engine'), os.path.join(temporary, 'dxmt')
            self._download_extract(ENGINE, engine)
            self._download_extract(DXMT, dxmt)
            with self.lock:
                self.d.update(state='installing', part=None)
            for arch in DXMT_ARCHS:                 # DXMT builtin DLLs replace the engine's own DLLs
                src, dst = os.path.join(dxmt, arch), os.path.join(engine, 'lib', 'wine', arch)
                if not os.path.isdir(src):
                    continue
                if not os.path.isdir(dst):
                    raise DownloadError(_('The Wine build has no %s folder.', arch))
                for name in os.listdir(src):
                    shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
            if not os.path.isfile(os.path.join(engine, 'bin', 'wine')):
                raise DownloadError(_('The Wine build has no bin/wine.'))
            with open(os.path.join(engine, INSTALL_MARKER), 'w', encoding='utf8') as fh:
                json.dump({'engine': ENGINE['sha256'], 'dxmt': DXMT['sha256'], 'name': self.name(), 'time': time.strftime('%Y-%m-%d %H:%M:%S')},
                          fh, indent=1)
            target = self.folder()
            if os.path.isdir(target):
                shutil.rmtree(target)
            os.rename(engine, target)
            for old in os.listdir(self.root):           # engines of earlier versions
                p = os.path.join(self.root, old)
                if old != ENGINE['version'] and not old.startswith('.') and os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
            with self.lock:
                self.d.update(state='built', claimed=self.d['total'], time_left_sec=0)
            self.log('Wine engine installed: %s (%s)' % (self.name(), target))
        except Cancelled:
            with self.lock:
                self.d['state'] = 'stopped'
            self.log('Wine engine install stopped')
        except DownloadError as e:
            with self.lock:
                self.d.update(state='error', error=str(e))
            self.log('Wine engine could not be installed: %s' % e)
        except OSError as e:
            with self.lock:
                self.d.update(state='error', error=_('Could not write a file: %s', e))
            self.log('Wine engine could not be installed: %r' % e)
        except Exception as e:
            with self.lock:
                self.d.update(state='error', error=repr(e))
            self.log('Wine engine: unexpected error: %r' % e)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
            with self.lock:
                self.d['running'], self.d['speed'], self.d['part'] = False, 0, None

    def wait(self, step=None):
        """Wait until the install finishes (step: (percent) -> None, progress) -> the wine program. RuntimeError if it cannot be installed."""
        self.start()
        while self.running():
            if step:
                st = self.state()
                step(int(100 * st['claimed'] / st['total']) if st['total'] else 0)
            time.sleep(0.5)
        st = self.state()
        if not st['route']:
            raise RuntimeError(st['error'] or _('Wine was not installed.'))
        return st['route']

    # ------------------------------------------------------------ Rosetta 2
    def install_rosetta(self):
        """Install Rosetta 2 with macOS's admin dialog (in the background; the user types their password into that dialog) -> status."""
        if has_rosetta():
            return self.state()
        with self.lock:
            if self.ros['state'] == 'installing':
                return self.state()
            self.ros = {'state': 'installing', 'error': None}

        def run():
            command = '/usr/sbin/softwareupdate --install-rosetta --agree-to-license'
            prompt = _('OpenOrbit will install Rosetta 2 for the Wine that opens the game.')
            script = 'do shell script "%s" with administrator privileges with prompt "%s"' % (command, prompt.replace('"', "'"))
            try:
                r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=1800)
                if has_rosetta():
                    ros = {'state': 'installed', 'error': None}
                    self.log('Rosetta 2 installed')
                elif '-128' in r.stderr:
                    ros = {'state': 'vacant', 'error': _('The Rosetta installation was cancelled.')}
                else:
                    ros = {'state': 'error', 'error': _('Rosetta could not be installed: %s', (r.stderr or r.stdout).strip()[-300:])}
                    self.log('Rosetta could not be installed: %s' % (r.stderr or r.stdout).strip()[-300:])
            except (OSError, subprocess.SubprocessError) as e:
                ros = {'state': 'error', 'error': _('Rosetta could not be installed: %s', e)}
            with self.lock:
                self.ros = ros
        threading.Thread(target=run, daemon=True).start()
        return self.state()
