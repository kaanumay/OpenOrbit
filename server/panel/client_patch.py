"""İstemcinin düzeltmeleri BepInEx ile: panel BepInEx 6'yı (Unity IL2CPP, 32 bit) istemci klasörüne kurar ve
eklenti/OpenOrbitPatch.dll'i BepInEx/plugins'e koyar. Yamalar (müzayede sayacı, rütbe penceresi, mağaza tutarı) eklentinin kaynağında:
eklenti/Patches.cs. README'deki "istemci yamalanmaz" kuralının kullanıcı onaylı istisnası (2026-10-24; BepInEx'e geçiş 2026-10-25,
önceki bellek yamalarının yerine).

İstemcinin kendi dosyaları değişmez; yanına BepInEx'in dosyaları eklenir (winhttp.dll, doorstop_config.ini, .doorstop_version,
changelog.txt, BepInEx/, dotnet/). Doorstop ayarda kapalı: panel istemciyi --doorstop-enabled true ile açar (istemci.komut), aynı
istemci başka yoldan (resmî başlatıcı) açılırsa BepInEx yüklenmez. Linux ve macOS'ta Wine ve Proton öntanımlı olarak kendi yerleşik
winhttp.dll'ini yüklediği için çalıştırıcı WINEDLLOVERRIDES'a winhttp=n,b ekler (calistirici.dll_override): önce oyun klasöründeki
Doorstop winhttp.dll yüklenir, o da sistemin yerleşik winhttp.dll'ine yönlendirir. BepInEx'in konsol penceresi ve interop
derlemelerinin önceden yüklenmesi kapalı (BepInEx/config/BepInEx.cfg; ayar()).
Eklentinin kopyası her açılışta paneldekiyle aynı mı diye bakılır (panel güncellenince yenilenir).

Kurulum: kurulum sihirbazının oyun klasörü adımında, istemci indirilince, İstemci sayfasından ya da ilk OYNA'da. BepInEx arşivi ve
Unity'nin temel kitaplıkları (BepInEx ilk açılışta indirirdi; önceden konunca ilk açılış da internetsiz) belleğe iner, SHA-256'ları
tutarsa açılır; bitince KAYIT yazılır (yarım kurulum kurulu sayılmaz). BepInEx istemcinin kodundan interop derlemelerini üretir (yarım
dakika kadar): panel bunu ilk OYNA'da oyundan önce penceresiz bir açılışta yaptırır (isit), sonraki açılışlar hızlı. Kurulamazsa oyun
düzeltmeler olmadan açılır.
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
# BepInEx bleeding edge (builds.bepinex.dev): be.788 (2026-09-01) 1.1.115'te denendi (Unity 2022.3.58, IL2CPP metadata v31).
# Değiştirince sha256 de değişir; kurulu eskisinin üstüne yeniden kurulur.
BEPINEX = {'name': 'BepInEx 6.0.0-be.788',
           'url': 'https://builds.bepinex.dev/projects/bepinex_be/788/BepInEx-Unity.IL2CPP-win-x86-6.0.0-be.788%2B5b766a3.zip',
           'sha256': 'd5954a5993ec39cd1133603d85bff93875d30b6411b712cc13dcf03c8e08a4d3', 'size': 31440336}
UNITY = {'name': 'Unity 2022.3.58', 'url': 'https://unity.bepinex.dev/libraries/2022.3.58.zip',
         'sha256': '37b5b6d5f3a8761ecd8415302f0283e86c552c822a456faaec33aae533ba32ae', 'size': 1898155,
         'route': 'BepInEx/unity-libs/2022.3.58.zip'}
PLUGIN = os.path.join(PANEL_DIR, 'plugin', 'OpenOrbitPatch.dll')
PLUGIN_PATH = 'BepInEx/plugins/OpenOrbitPatch.dll'
OLD_PLUGIN_PATH = 'BepInEx/plugins/OpenOrbitYama.dll'      # 2026-11-01'den önceki adı (İngilizce geçiş)
SETTINGS = 'BepInEx/config/BepInEx.cfg'
INSTALL_MARKER = 'BepInEx/openorbit.json'        # kurulumun bittiğini ve sürümünü söyler
INTEROP = 'BepInEx/interop/assembly-hash.txt'   # BepInEx interop derlemelerini üretince en son bunu yazar
ARGS = ['--doorstop-enabled', 'true']
WARMUP = ['-batchmode', '-nographics']           # interop üretimi için penceresiz açılış (isit)
STARTED = 'BepInEx/ErrorLog.log'                # BepInEx açılışta yazar (ısınmanın ilk aşaması biter)
INTEROP_FILES = 101                              # interop klasörünün dosyaları (be.788, 1.1.115: 99 derleme ve 2 .db)


def route(folder, rel):
    return os.path.join(folder, *rel.split('/'))


def installed(folder):
    """BepInEx bu klasöre kurulmuş mu (kurulum bitmiş, sürümü güncel)?"""
    return _registry(folder).get('bepinex') == BEPINEX['sha256'] and os.path.isfile(os.path.join(folder, 'winhttp.dll'))


def plugin(folder):
    """Eklentinin kopyası paneldekinden farklıysa (yoksa) yenile."""
    with open(PLUGIN, 'rb') as fh:
        new_ = fh.read()
    old = route(folder, OLD_PLUGIN_PATH)        # adı değişmeden önceki kopya: iki eklenti birden yüklenip yamalar iki kez uygulanmasın
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
    """BepInEx.cfg'de interop derlemelerinin önceden yüklenmesini kapat. Açıkken (BepInEx'in öntanımlısı) interop'lar yeni
    üretildikten sonraki ilk bir iki açılışta istemci ilk sahneyi yüklemeden takılıyordu (Windows beyaz ekran, Proton kod 1; 2026-10-28,
    kapalıyken 4/4 açıldı); eklenti gereken derlemeleri kendisi yükler. Öteki ayarlara dokunulmaz."""
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
    """Oyun kodunun (GameAssembly.dll) boyutu ve zamanı: istemci yerinde güncellenirse interop'lar yeniden üretilmeli."""
    try:
        st = os.stat(os.path.join(folder, 'GameAssembly.dll'))
    except OSError:
        return None
    return '%d-%d' % (st.st_size, int(st.st_mtime))


def _registry(folder):
    try:
        with open(route(folder, INSTALL_MARKER), encoding='utf8') as fh:
            return SM.migrate_obj(json.load(fh))         # eski sürümün yazdığı işaret (anahtarlar yeni adlara)
    except (OSError, ValueError):
        return {}


def generated(folder):
    """BepInEx interop derlemelerini üretmiş mi?"""
    return os.path.isfile(route(folder, INTEROP))


def ready(folder):
    """Interop'lar bu istemci kodu için üretilmiş mi? Isınmanın kaydettiği parmak izi yoksa (önceki panel sürümünün kurulumu)
    GameAssembly.dll interop'lardan yeniyse istemci güncellenmiş sayılır."""
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
    """Isınmanın ilerlemesi -> {'asama': 0 istemci açılıyor, 1 derlemeler üretiliyor, 2 dosyalar yazılıyor, 3 bitti; 'yuzde', 'gecen_sn'}.
    BepInEx üretim bitene kadar günlüğünü diske yazmıyor (Windows ve Wine, 2026-10-28): aşamalar dosyalardan (BASLADI, interop
    klasörü). Üretim içeriden görünmez: yüzde süreyle yavaşlayarak ilerler, yazmada dosya sayısıyla. gorulen: isit'in tuttuğu durum."""
    now = time.time()
    try:
        started = os.path.getmtime(route(folder, STARTED)) >= start - 1   # önceki açılışınki sayılmaz
    except OSError:
        started = False
    try:
        written = len(os.listdir(route(folder, 'BepInEx/interop')))
    except OSError:
        written = 0
    stage = 3 if generated(folder) else 2 if written else 1 if started or now - start > 10 else 0
    t = now - seen.setdefault(stage, now)
    sub = seen.setdefault('write', seen.get('percent', 0)) if stage == 2 else 0   # yazma, gösterilenden sıçramadan sürer
    percent = (100 if stage == 3 else sub + (99 - sub) * min(1, written / INTEROP_FILES) if stage == 2
             else 10 + 80 * (1 - math.exp(-t / 25)) if stage == 1 else 9 * (1 - math.exp(-t / 4)))
    seen['percent'] = max(seen.get('percent', 0), int(percent))
    return {'stage': stage, 'percent': seen['percent'], 'elapsed_sec': int(now - start)}


def warm_up(folder, cmd, env, logs, notify=None, duration=300):
    """Interop derlemelerini oyundan önce ayrı, penceresiz bir açılışta ürettir -> hazır mı. Üretim oyunun kendi açılışında olursa
    32 bitlik istemcinin adres alanı tükeniyor: Proton'da oyun ilk sahnede "System out of memory" ile kapanıyordu (2026-10-28).
    cmd, env: istemci.komut (BepInEx argümanlarıyla); üretim bitince (ya da sure dolunca) bu açılış kapatılır. bildir: ilerleme()'nin
    sonucu yarım saniyede bir (panelin OYNA adımı)."""
    start, seen = time.time(), {}
    shutil.rmtree(route(folder, 'BepInEx/interop'), ignore_errors=True)    # eski istemcinin interop'ları: yeniden üretilsin
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
    if generated(folder):                            # hazir(): istemci kodu değişirse yeniden ısınılır
        d = _registry(folder)
        d['warmup'] = fingerprint(folder)
        with open(route(folder, INSTALL_MARKER), 'w', encoding='utf8') as fh:
            json.dump(d, fh, indent=1)
    last = time.time() + 15
    while os.name != 'nt' and time.time() < last:   # Wine her Windows sürecini kendi oturumunda açar: grubu kapatmak istemciye ulaşmaz
        remaining = warmup_processes()
        if not remaining:
            break
        for pid in remaining:
            PR.kill(pid)
        time.sleep(0.5)
    return generated(folder)


def warmup_processes():
    """Linux ve macOS: açık ısınma istemcileri (Wine'daki DarkOrbit.exe ... -batchmode)."""
    try:
        r = subprocess.run(['ps', '-A', '-o', 'pid=', '-o', 'args='], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(s.split(None, 1)[0]) for s in r.stdout.splitlines()
            if 'darkorbit.exe' in s.lower() and ' %s ' % WARMUP[0] in s + ' ' and 'python' not in s.lower()]


def arguments(folder):
    """İstemciyi BepInEx'le açan argümanlar (kurulu değilse yok); eklentinin kopyası ve ayar önce yenilenir."""
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
        """folder'daki kurulumun durumu (başka klasörün biten işi sayılmaz)."""
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
        """BepInEx'i ve eklentiyi istemci klasörüne kur (sürüyorsa ya da kuruluysa bir şey yapmaz) -> durum."""
        with self.lock:
            if folder and not self.d['running'] and not installed(folder):
                self.stop.clear()
                self.d = dict(self._blank('downloading', folder), running=True)
                threading.Thread(target=self._run, args=(folder,), daemon=True).start()
        return self.state(folder)

    def cancel(self):
        self.stop.set()

    def wait(self, folder, step=None):
        """Kurulum bitene dek bekle (adim: (yüzde) -> None, ilerleme) -> kuruldu mu."""
        self.start(folder)
        while self.running():
            if step:
                st = self.state(folder)
                step(int(100 * st['claimed'] / st['total']))
            time.sleep(0.3)
        return installed(folder)

    def _download(self, part):
        """Arşivi belleğe indir ve SHA-256'sını doğrula -> bayt."""
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
            self.log('BepInEx indiriliyor: %s, %s' % (BEPINEX['url'], UNITY['url']))
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
            p = os.path.join(folder, 'doorstop_config.ini')      # Doorstop kapalı: BepInEx'i yalnız panelin argümanı açar
            with open(p, 'rb') as fh:
                ini = fh.read()
            with open(p, 'wb') as fh:
                fh.write(ini.replace(b'enabled = true', b'enabled = false', 1))
            p = route(folder, SETTINGS)
            if not os.path.isfile(p):                           # konsol penceresi açılmasın (öteki ayarları BepInEx ekler)
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
            self.log('BepInEx kuruldu: %s (%s)' % (BEPINEX['name'], folder))
        except Cancelled:
            with self.lock:
                self.d['state'] = 'stopped'
            self.log('BepInEx kurulumu durduruldu')
        except DownloadError as e:
            with self.lock:
                self.d.update(state='error', error=str(e))
            self.log('BepInEx kurulamadı: %s' % e)
        except OSError as e:
            with self.lock:
                self.d.update(state='error', error=_('Could not write a file: %s', e))
            self.log('BepInEx kurulamadı: %r' % e)
        except Exception as e:
            with self.lock:
                self.d.update(state='error', error=repr(e))
            self.log('BepInEx: beklenmeyen hata: %r' % e)
        finally:
            with self.lock:
                self.d['running'] = False
