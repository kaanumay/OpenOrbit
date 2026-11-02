"""Language model setup for advanced bot mode (Bots page > Advanced mode): llama.cpp's llama-server and Qwen3 4B Q4_K_M.

Downloads under save/llm/: llama-<version>/ (the server), Qwen3-4B-Q4_K_M.gguf (the model, ~2.5 GB; if interrupted it resumes where it left off),
install.json (the server's path, digests, the test result). The SHA-256 of both files is verified while downloading. "Test" starts the server and asks
a short question (bot/llm_server.test); when an answer arrives the setup is complete. State: none, installing, built, ready (test
passed), error, stopped.
"""
import hashlib, json, os, platform, shutil, sys, tarfile, threading, time, zipfile

import paths as PTH
from lang import t as _
from client_download import HttpFile, DownloadError, Cancelled

VERSION = 'b11981'
_GH = 'https://github.com/ggml-org/llama.cpp/releases/download/%s/' % VERSION
SERVERS = {   # platform -> archive (Vulkan: on NVIDIA, AMD and Intel graphics cards; otherwise it runs on the CPU)
    'win-x64': dict(url=_GH + 'llama-%s-bin-win-vulkan-x64.zip' % VERSION, size=37346388,
                    sha256='29419511baa97ccb001111a24de4a9e1d62251075749e2a8be56219b51dc21ce'),
    'linux-x64': dict(url=_GH + 'llama-%s-bin-ubuntu-vulkan-x64.tar.gz' % VERSION, size=35475421,
                      sha256='5fca386f7256e496cfd1edefe63c00082267e1394c6136b6946a2d70003d3666'),
    'mac-arm64': dict(url=_GH + 'llama-%s-bin-macos-arm64.tar.gz' % VERSION, size=16463687,
                      sha256='c5827eba94fe4eb9068a82eab5c25a943dbd2022efe5144d1af817e8b396b45a'),
    'mac-x64': dict(url=_GH + 'llama-%s-bin-macos-x64.tar.gz' % VERSION, size=12208100,
                    sha256='0d9e5c5bbeca9beda692e4a46560e83b2385dc79683bd949126b10e34c2ca7ce'),
}
MODEL = dict(name='Qwen3-4B-Q4_K_M.gguf', url='https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf',
             size=2497280256, sha256='7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5')
CHUNK = 1 << 20
MIN_MEMORY_GB = 8


def platform_key():
    m = platform.machine().lower()
    if sys.platform == 'win32':
        return 'win-x64' if m in ('amd64', 'x86_64') else None
    if sys.platform == 'darwin':
        return 'mac-arm64' if m in ('arm64', 'aarch64') else 'mac-x64'
    return 'linux-x64' if m in ('x86_64', 'amd64') else None


def memory_gb():
    """Total memory (GB) or None."""
    try:
        if sys.platform == 'win32':
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong), ('ullTotalPhys', ctypes.c_ulonglong),
                            ('ullAvailPhys', ctypes.c_ulonglong), ('ullTotalPageFile', ctypes.c_ulonglong),
                            ('ullAvailPageFile', ctypes.c_ulonglong), ('ullTotalVirtual', ctypes.c_ulonglong),
                            ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / 2 ** 30, 1)
        return round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2 ** 30, 1)
    except (OSError, ValueError, AttributeError):
        return None


class LlmSetup:
    def __init__(self, log=print, opener=None):
        self.log, self.opener = log, opener
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.d = self._empty('none')
        self.samples = []
        self.t = {'state': 'none'}

    @staticmethod
    def _empty(state):
        return {'state': state, 'running': False, 'claimed': 0, 'total': 0, 'speed': 0, 'time_left_sec': None, 'error': None, 'part': None}

    def folder(self):
        return os.path.join(PTH.SAVE, 'llm')

    def save(self):
        try:
            with open(os.path.join(self.folder(), 'install.json'), encoding='utf8') as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return None
        ok = d.get('version') == VERSION and d.get('model') == MODEL['sha256'] and os.path.isfile(d.get('server') or '') \
            and os.path.isfile(os.path.join(self.folder(), MODEL['name']))
        return d if ok else None

    def state(self):
        with self.lock:
            d = json.loads(json.dumps(self.d))
            t = dict(self.t)
        k = self.save()
        if not d['running'] and k:
            d['state'] = 'ready' if k.get('test_ok') else 'built'
        if not d['running'] and not k and d['state'] in ('none', 'built', 'ready'):
            d['state'] = 'none'
            p = os.path.join(self.folder(), MODEL['name'] + '.part')
            d['partial'] = os.path.getsize(p) if os.path.isfile(p) else 0
        pk = platform_key()
        d.update(test=t, size=MODEL['size'] + (SERVERS[pk]['size'] if pk else 0), platform=pk, supported=bool(pk),
                 memory_gb=memory_gb(), min_memory_gb=MIN_MEMORY_GB, cores=os.cpu_count(), model=MODEL['name'], version=VERSION,
                 last_test=k.get('test') if k else None)
        return d

    def running(self):
        with self.lock:
            return self.d['running'] or self.t.get('state') == 'running'

    # ------------------------------------------------------------ setup
    def start(self):
        with self.lock:
            if not self.d['running'] and not self.save():
                pk = platform_key()
                if not pk:
                    raise DownloadError(_("There is no ready-made language model server for this computer's processor."))
                self.stop.clear()
                self.d = dict(self._empty('downloading'), running=True, total=MODEL['size'] + SERVERS[pk]['size'])
                self.samples = []
                threading.Thread(target=self._run, args=(pk,), daemon=True).start()
        return self.state()

    def cancel(self):
        self.stop.set()
        return self.state()

    def remove(self):
        if self.running():
            raise DownloadError(_('Setup or test in progress.'))
        shutil.rmtree(self.folder(), ignore_errors=True)
        with self.lock:
            self.d, self.t = self._empty('none'), {'state': 'none'}
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
                remaining = max(0, self.d['total'] - self.d['claimed'])
                self.d['time_left_sec'] = int(remaining / self.d['speed']) if self.d['speed'] > 0 else None

    def _download(self, url, target, size, sha):
        """Download the file to the target (resuming from a partial .part), verify the SHA-256."""
        part = target + '.part'
        digest = hashlib.sha256()
        var = os.path.getsize(part) if os.path.isfile(part) else 0
        if var > size:
            os.remove(part)
            var = 0
        if var:
            with open(part, 'rb') as fh:
                while True:
                    b = fh.read(CHUNK * 8)
                    if not b:
                        break
                    digest.update(b)
            self._count(var)
        kw = {'opener': self.opener} if self.opener else {}
        f = HttpFile(url, self.stop, self._count, **kw)
        try:
            if f.size != size:
                raise DownloadError(_("The downloaded file's size differs from what was expected: try again."))
            f.seek(var)
            with open(part, 'ab') as out:
                while f.tell() < f.size:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    digest.update(b)
                    out.write(b)
        finally:
            f.close()
        if digest.hexdigest() != sha:
            os.remove(part)
            raise DownloadError(_('%s is not the expected file (SHA-256 mismatch): try again.', os.path.basename(target)))
        os.replace(part, target)

    def _run(self, pk):
        k = self.folder()
        try:
            os.makedirs(k, exist_ok=True)
            empty = shutil.disk_usage(k).free
            need = MODEL['size'] * 1.1 + 300 * 2 ** 20
            if empty < need:
                raise DownloadError(_('Not enough disk space: %.1f GB needed, %.1f GB free.', need / 2 ** 30, empty / 2 ** 30))
            s = SERVERS[pk]
            archive = os.path.join(k, os.path.basename(s['url']))
            self.log('language model server downloading: %s' % s['url'])
            with self.lock:
                self.d['part'] = 'llama-server'
            if not os.path.isfile(archive):
                self._download(s['url'], archive, s['size'], s['sha256'])
            else:
                self._count(s['size'])
            with self.lock:
                self.d['part'] = MODEL['name']
            model = os.path.join(k, MODEL['name'])
            if not os.path.isfile(model):
                self.log('language model downloading: %s' % MODEL['url'])
                self._download(MODEL['url'], model, MODEL['size'], MODEL['sha256'])
            else:
                self._count(MODEL['size'])
            with self.lock:
                self.d.update(state='installing', part=None)
            target = os.path.join(k, 'llama-' + VERSION)
            if os.path.isdir(target):
                shutil.rmtree(target)
            if archive.endswith('.zip'):
                with zipfile.ZipFile(archive) as z:
                    for n in z.namelist():
                        from client_download import safe_path
                        safe_path(target, n)
                    z.extractall(target)
            else:
                with tarfile.open(archive) as tf:
                    for m in tf.getmembers():
                        if m.name.startswith('/') or '..' in m.name.split('/'):
                            raise DownloadError(_('Invalid path in the archive: %s', m.name))
                    tf.extractall(target)
            name = 'llama-server.exe' if sys.platform == 'win32' else 'llama-server'
            server = next((os.path.join(r, name) for r, _d, fs in os.walk(target) if name in fs), None)
            if not server:
                raise DownloadError(_('No %s in the archive.', name))
            if sys.platform != 'win32':
                os.chmod(server, 0o755)
            os.remove(archive)
            with open(os.path.join(k, 'install.json'), 'w', encoding='utf8') as fh:
                json.dump({'version': VERSION, 'server': server, 'model': MODEL['sha256'], 'test_ok': False,
                           'time': time.strftime('%Y-%m-%d %H:%M:%S')}, fh, indent=1)
            with self.lock:
                self.d.update(state='built', claimed=self.d['total'], time_left_sec=0)
            self.log('language model installed: %s' % server)
        except Cancelled:
            with self.lock:
                self.d['state'] = 'stopped'
        except DownloadError as e:
            with self.lock:
                self.d.update(state='error', error=str(e))
            self.log('language model could not be installed: %s' % e)
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
            with self.lock:
                self.d.update(state='error', error=_('Could not write the file or the archive is corrupt: %s', e))
            self.log('language model could not be installed: %r' % e)
        finally:
            with self.lock:
                self.d['running'], self.d['speed'], self.d['part'] = False, 0, None

    # ------------------------------------------------------------ test
    def test(self):
        with self.lock:
            if self.t.get('state') == 'running':
                return self.state()
            if not self.save():
                raise DownloadError(_('Install the language model first.'))
            self.t = {'state': 'running', 'start': time.time()}
        threading.Thread(target=self._test, daemon=True).start()
        return self.state()

    def test_remote(self):
        """Test of the selected remote provider (bot/llm_provider.test): a short question, an answer in Turkish."""
        from bot import llm_provider as PRV
        c = PRV.selected()
        if PRV.PROVIDERS[c['uid']]['key'] and not c['key']:
            raise DownloadError(_('Enter the API key first.'))
        if not c['model']:
            raise DownloadError(_('Choose a model first.'))
        with self.lock:
            if self.t.get('state') == 'running':
                return self.state()
            self.t = {'state': 'running', 'start': time.time(), 'provider': c['uid']}
        threading.Thread(target=self._test_remote, args=(c['uid'],), daemon=True).start()
        return self.state()

    def _test_remote(self, uid):
        from bot import llm_provider as PRV
        try:
            r = PRV.test(self.log)
            with self.lock:
                self.t = dict(r, state='ok' if r['ok'] else 'error', provider=uid,
                              error=None if r['ok'] else _('The model did not give the expected reply.'))
            self.log('language model provider test: %s' % r)
        except Exception as e:
            with self.lock:
                self.t = {'state': 'error', 'error': _(str(e)), 'provider': uid}
            self.log('language model provider test failed: %r' % e)

    def _test(self):
        from bot import llm_server as LS
        try:
            r = LS.test(self.log)
            k = self.save() or {}
            k.update(test_ok=bool(r['ok']), test=dict(r, time=time.strftime('%Y-%m-%d %H:%M:%S')))
            with open(os.path.join(self.folder(), 'install.json'), 'w', encoding='utf8') as fh:
                json.dump(k, fh, indent=1, ensure_ascii=False)
            with self.lock:
                self.t = dict(r, state='ok' if r['ok'] else 'error', error=None if r['ok'] else _('The model did not give the expected reply.'))
            self.log('language model test: %s' % r)
        except Exception as e:
            with self.lock:
                self.t = {'state': 'error', 'error': _(str(e))}
            self.log('language model test failed: %r' % e)
