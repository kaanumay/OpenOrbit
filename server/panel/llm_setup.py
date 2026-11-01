"""Gelişmiş bot kipinin dil modeli kurulumu (Botlar sayfası > Gelişmiş kip): llama.cpp'nin llama-server'ı ve Qwen3 4B Q4_K_M.

save/llm/ altına iner: llama-<sürüm>/ (sunucu), Qwen3-4B-Q4_K_M.gguf (model, ~2,5 GB; yarım kalırsa kaldığı yerden sürer),
kurulum.json (sunucunun yolu, özetler, testin sonucu). İki dosyanın SHA-256'sı indirilirken doğrulanır. "Test et" sunucuyu açıp
kısa bir soru sorar (bot/llm_sunucu.test); yanıt gelince kurulum tamamdır. Durum: yok, indiriliyor, kuruluyor, kurulu, hazir (test
geçti), hata, durdu.
"""
import hashlib, json, os, platform, shutil, sys, tarfile, threading, time, zipfile

import paths as PTH
from lang import t as _
from client_download import HttpFile, DownloadError, Cancelled

VERSION = 'b11981'
_GH = 'https://github.com/ggml-org/llama.cpp/releases/download/%s/' % VERSION
SERVERS = {   # platform -> arşiv (Vulkan: NVIDIA, AMD ve Intel ekran kartlarında; yoksa işlemcide çalışır)
    'win-x64': dict(url=_GH + 'llama-%s-bin-win-vulkan-x64.zip' % VERSION, size=37346388,
                    sha256='29419511baa97ccb001111a24de4a9e1d62251075749e2a8be56219b51dc21ce'),
    'linux-x64': dict(url=_GH + 'llama-%s-bin-ubuntu-vulkan-x64.tar.gz' % VERSION, size=35475421,
                      sha256='5fca386f7256e496cfd1edefe63c00082267e1394c6136b6946a2d70003d3666'),
    'mac-arm64': dict(url=_GH + 'llama-%s-bin-macos-arm64.tar.gz' % VERSION, size=16463687,
                      sha256='c5827eba94fe4eb9068a82eab5c25a943dbd2022efe5144d1af817e8b396b45a'),
    'mac-x64': dict(url=_GH + 'llama-%s-bin-macos-x64.tar.gz' % VERSION, size=12208100,
                    sha256='0d9e5c5bbeca9beda692e4a46560e83b2385dc79683bd949126b10e34c2ca7ce'),
}
MODEL = dict(ad='Qwen3-4B-Q4_K_M.gguf', url='https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf',
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
    """Toplam bellek (GB) ya da None."""
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
        self.t = {'durum': 'none'}

    @staticmethod
    def _empty(state):
        return {'durum': state, 'running': False, 'claimed': 0, 'toplam': 0, 'hiz': 0, 'time_left_sec': None, 'hata': None, 'part': None}

    def folder(self):
        return os.path.join(PTH.SAVE, 'llm')

    def save(self):
        try:
            with open(os.path.join(self.folder(), 'install.json'), encoding='utf8') as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return None
        ok = d.get('surum') == VERSION and d.get('model') == MODEL['sha256'] and os.path.isfile(d.get('sunucu') or '') \
            and os.path.isfile(os.path.join(self.folder(), MODEL['ad']))
        return d if ok else None

    def state(self):
        with self.lock:
            d = json.loads(json.dumps(self.d))
            t = dict(self.t)
        k = self.save()
        if not d['running'] and k:
            d['durum'] = 'hazir' if k.get('test_ok') else 'built'
        if not d['running'] and not k and d['durum'] in ('none', 'built', 'hazir'):
            d['durum'] = 'none'
            p = os.path.join(self.folder(), MODEL['ad'] + '.part')
            d['partial'] = os.path.getsize(p) if os.path.isfile(p) else 0
        pk = platform_key()
        d.update(test=t, size=MODEL['size'] + (SERVERS[pk]['size'] if pk else 0), platform=pk, destekli=bool(pk),
                 memory_gb=memory_gb(), min_memory_gb=MIN_MEMORY_GB, cores=os.cpu_count(), model=MODEL['ad'], surum=VERSION,
                 last_test=k.get('test') if k else None)
        return d

    def running(self):
        with self.lock:
            return self.d['running'] or self.t.get('durum') == 'running'

    # ------------------------------------------------------------ kurulum
    def start(self):
        with self.lock:
            if not self.d['running'] and not self.save():
                pk = platform_key()
                if not pk:
                    raise DownloadError(_("There is no ready-made language model server for this computer's processor."))
                self.stop.clear()
                self.d = dict(self._empty('downloading'), running=True, toplam=MODEL['size'] + SERVERS[pk]['size'])
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
            self.d, self.t = self._empty('none'), {'durum': 'none'}
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
                self.d['hiz'] = int((self.d['claimed'] - b0) / (now - t0))
                remaining = max(0, self.d['toplam'] - self.d['claimed'])
                self.d['time_left_sec'] = int(remaining / self.d['hiz']) if self.d['hiz'] > 0 else None

    def _download(self, url, target, size, sha):
        """Dosyayı hedefe (yarım .part'tan sürerek) indir, SHA-256'yı doğrula."""
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
            self.log('dil modeli sunucusu indiriliyor: %s' % s['url'])
            with self.lock:
                self.d['part'] = 'llama-server'
            if not os.path.isfile(archive):
                self._download(s['url'], archive, s['size'], s['sha256'])
            else:
                self._count(s['size'])
            with self.lock:
                self.d['part'] = MODEL['ad']
            model = os.path.join(k, MODEL['ad'])
            if not os.path.isfile(model):
                self.log('dil modeli indiriliyor: %s' % MODEL['url'])
                self._download(MODEL['url'], model, MODEL['size'], MODEL['sha256'])
            else:
                self._count(MODEL['size'])
            with self.lock:
                self.d.update(durum='installing', part=None)
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
                json.dump({'surum': VERSION, 'sunucu': server, 'model': MODEL['sha256'], 'test_ok': False,
                           'time': time.strftime('%Y-%m-%d %H:%M:%S')}, fh, indent=1)
            with self.lock:
                self.d.update(durum='built', claimed=self.d['toplam'], time_left_sec=0)
            self.log('dil modeli kuruldu: %s' % server)
        except Cancelled:
            with self.lock:
                self.d['durum'] = 'stopped'
        except DownloadError as e:
            with self.lock:
                self.d.update(durum='hata', hata=str(e))
            self.log('dil modeli kurulamadı: %s' % e)
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
            with self.lock:
                self.d.update(durum='hata', hata=_('Could not write the file or the archive is corrupt: %s', e))
            self.log('dil modeli kurulamadı: %r' % e)
        finally:
            with self.lock:
                self.d['running'], self.d['hiz'], self.d['part'] = False, 0, None

    # ------------------------------------------------------------ test
    def test(self):
        with self.lock:
            if self.t.get('durum') == 'running':
                return self.state()
            if not self.save():
                raise DownloadError(_('Install the language model first.'))
            self.t = {'durum': 'running', 'start': time.time()}
        threading.Thread(target=self._test, daemon=True).start()
        return self.state()

    def test_remote(self):
        """Seçili uzak sağlayıcının testi (bot/llm_saglayici.test): kısa bir soru, Türkçe yanıt."""
        from bot import llm_provider as PRV
        c = PRV.selected()
        if PRV.PROVIDERS[c['kimlik']]['anahtar'] and not c['anahtar']:
            raise DownloadError(_('Enter the API key first.'))
        if not c['model']:
            raise DownloadError(_('Choose a model first.'))
        with self.lock:
            if self.t.get('durum') == 'running':
                return self.state()
            self.t = {'durum': 'running', 'start': time.time(), 'provider': c['kimlik']}
        threading.Thread(target=self._test_remote, args=(c['kimlik'],), daemon=True).start()
        return self.state()

    def _test_remote(self, uid):
        from bot import llm_provider as PRV
        try:
            r = PRV.test(self.log)
            with self.lock:
                self.t = dict(r, durum='ok' if r['ok'] else 'hata', provider=uid,
                              hata=None if r['ok'] else _('The model did not give the expected reply.'))
            self.log('dil modeli sağlayıcı testi: %s' % r)
        except Exception as e:
            with self.lock:
                self.t = {'durum': 'hata', 'hata': str(e), 'provider': uid}
            self.log('dil modeli sağlayıcı testi başarısız: %r' % e)

    def _test(self):
        from bot import llm_server as LS
        try:
            r = LS.test(self.log)
            k = self.save() or {}
            k.update(test_ok=bool(r['ok']), test=dict(r, time=time.strftime('%Y-%m-%d %H:%M:%S')))
            with open(os.path.join(self.folder(), 'install.json'), 'w', encoding='utf8') as fh:
                json.dump(k, fh, indent=1, ensure_ascii=False)
            with self.lock:
                self.t = dict(r, durum='ok' if r['ok'] else 'hata', hata=None if r['ok'] else _('The model did not give the expected reply.'))
            self.log('dil modeli testi: %s' % r)
        except Exception as e:
            with self.lock:
                self.t = {'durum': 'hata', 'hata': str(e)}
            self.log('dil modeli testi başarısız: %r' % e)
