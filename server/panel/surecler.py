"""Sunucu ve istemci süreçleri (panel).

  web   web.py: 80, 8090 (web girişi; 843, 9339, 8082 sahte TCP)
  oyun  game.py: 8081 (oyun), 7771 (sohbet), 8099 (kontrol kanalı, ayarla)
Arkadaş sunucusu (Arkadaşlarınla Oyna > Host): oyun sunucusu --cok-oyunculu ve DO_COK_OYUNCULU ortam değişkeniyle (arkadas.py).
Çoklu istemci (coklu.py): oyun sunucusu yine --cok-oyunculu ile, yalnız bu bilgisayardan ve misafirsiz (coklu ortamı).
Misafir (Join): yalnız web.py, arkadaşın sunucusunu gösteren argümanlarla (start_guest_web); oyun sunucusu açılmaz.
Sunucular konsolsuz (CREATE_NO_WINDOW) çalışır; çıktıları logs/<ad>_konsol.log'a (çökme izi orada). Oyun sunucusu --durdur=<dosya>
ile durdurulur: dosya belirince profili kaydedip çıkar (zorla kapatmada son kaydedilmemiş saniyeler gitmesin); yanıt vermezse
sonlandırılır. Portu başka süreç tutuyorsa (önceki oturumdan kalan sunucu, başka program) kim olduğu bulunur; panel yalnız bu
projenin web.py / game.py süreçlerini kapatabilir.
Linux ve macOS: port tablosu /proc/net/tcp ya da lsof, süreç bilgisi ps; istemci Wine ya da Proton ile kendi süreç grubunda
(istemci_ac, calistirici.py). Linux 1024'ten küçük portları yalnız root'a açar: istemci web API'sini 80'den bekliyor (istemcinin
config.txt'si, değiştirilmez), port_80_sorunu kullanıcıya bir kerelik izin komutunu söyler. macOS'ta bir şey gerekmez: düşük portlar
0.0.0.0'da açılır, yalnız yerel bağlantılar kabul edilir (uyum.py).
"""
import json, os, secrets, signal, socket, subprocess, sys, threading, time

from dil import t as _

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(PANEL_DIR)
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
PORT_80_KOMUTU = 'echo net.ipv4.ip_unprivileged_port_start=80 | sudo tee /etc/sysctl.d/90-openorbit.conf && sudo sysctl --system'
PORTS = {'web': (8090, 80), 'oyun': (8081, 7771, 8098)}
PORT_ADLARI = {8090: 'Web girişi', 80: 'Web API', 8081: 'Oyun', 7771: 'Sohbet', 8098: 'Panel yönetim kanalı', 8099: 'Kontrol kanalı'}
SCRIPTS = {'web': 'web.py', 'oyun': 'game.py'}
ERKEN_KAPANMA_SN = 15


def python_exe():
    """Sunucular için python.exe (panel pythonw.exe ile açıldıysa yanındaki python.exe)."""
    d, b = os.path.split(sys.executable)
    if b.lower() == 'pythonw.exe' and os.path.exists(os.path.join(d, 'python.exe')):
        return os.path.join(d, 'python.exe')
    return sys.executable


def listeners():
    """Dinleyen TCP soketleri {port: pid} (Windows TCP tablosu: GetExtendedTcpTable; Linux /proc/net/tcp; macOS lsof). Porta
    bağlanılmaz: bağlanmak oyun sunucusunda sahte bir oturum açıp günlüğe 'connect/disconnect' yazdırıyordu. Okunamazsa None; pid
    bilinmiyorsa 0 (Linux'ta başka kullanıcının süreci)."""
    if sys.platform.startswith('linux'):
        return _linux_listeners()
    if os.name != 'nt':
        return _lsof_listeners()
    import ctypes
    from ctypes import wintypes
    size = wintypes.DWORD(0)
    fn = ctypes.windll.iphlpapi.GetExtendedTcpTable
    fn(None, ctypes.byref(size), False, 2, 3, 0)                      # AF_INET, TCP_TABLE_OWNER_PID_LISTENER
    for _ in range(3):
        buf = ctypes.create_string_buffer(size.value + 4096)
        size = wintypes.DWORD(len(buf))
        if fn(buf, ctypes.byref(size), False, 2, 3, 0) == 0:
            break
    else:
        return None
    n = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(wintypes.DWORD * 6))
    out = {}
    for i in range(n):
        r = rows[i]
        out.setdefault(socket.ntohs(r[2] & 0xFFFF), r[5])
    return out


def _linux_listeners():
    """Linux: dinleyen soketler (durum 0A) /proc/net/tcp ve tcp6'dan; pid soketin inode'u /proc/<pid>/fd'de aranarak."""
    inodes = {}
    for f in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(f) as fh:
                for line in fh.readlines()[1:]:
                    p = line.split()
                    if p[3] == '0A':
                        inodes.setdefault(int(p[9]), int(p[1].rsplit(':', 1)[1], 16))
        except (OSError, IndexError, ValueError):
            continue
    out = dict.fromkeys(inodes.values(), 0)
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            fds = os.listdir('/proc/%s/fd' % pid)
        except OSError:
            continue
        for fd in fds:
            try:
                link = os.readlink('/proc/%s/fd/%s' % (pid, fd))
            except OSError:
                continue
            port = inodes.get(int(link[8:-1])) if link.startswith('socket:[') else None
            if port is not None and not out[port]:
                out[port] = int(pid)
    return out


def _lsof_listeners():
    """macOS: lsof'un dinleyen TCP soketleri (yalnız bu kullanıcının süreçleri)."""
    try:
        r = subprocess.run(['lsof', '-nP', '-iTCP', '-sTCP:LISTEN', '-Fpn'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out, pid = {}, 0
    for line in r.stdout.splitlines():
        if line.startswith('p') and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith('n') and line.rsplit(':', 1)[-1].isdigit():
            out.setdefault(int(line.rsplit(':', 1)[1]), pid)
    return out


def port_80_sorunu():
    """Linux 80 portunu (istemcinin web API'si) bu kullanıcıya açmıyorsa kullanıcıya gösterilecek metin, yoksa None. Port doluysa
    None: onu başlatmadaki port denetimi söyler. macOS'ta web.py 80'i 0.0.0.0'da açar (uyum.py): denetim de orada."""
    if os.name == 'nt':
        return None
    mac = sys.platform == 'darwin'
    with socket.socket() as s:
        try:
            s.bind(('0.0.0.0' if mac else '127.0.0.1', 80))
        except PermissionError:
            if mac:
                return _('macOS 80 portunu açmaya izin vermedi; oyunun web girişi bu portta (macOS 10.14 ya da daha yenisi gerekir).')
            return _("Linux 80 portunu yalnız root'a açıyor; oyunun web girişi bu portta. Terminalde bir kez çalıştır (kalıcı): %s",
                     PORT_80_KOMUTU)
        except OSError:
            pass
    return None


def listening(port, table=None):
    """Port dinleniyor mu (bağlanmadan; tablo yoksa bağlanarak)."""
    t = table if table is not None else listeners()
    if t is not None:
        return port in t
    with socket.socket() as s:
        s.settimeout(0.25)
        return s.connect_ex(('127.0.0.1', port)) == 0


def port_owners(ports):
    """{port: pid} dinleyen süreçler (TCP tablosu, yoksa netstat)."""
    t = listeners()
    if t is not None:
        return {p: pid for p, pid in t.items() if p in ports}
    try:
        r = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
    except Exception:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        # dinleyen soket: yabancı adres *:0 (durum sözcüğü Windows diline göre değişir)
        if len(parts) >= 5 and parts[0] == 'TCP' and parts[2].endswith(':0'):
            try:
                port = int(parts[1].rsplit(':', 1)[1])
                pid = int(parts[-1])
            except (ValueError, IndexError):
                continue
            if port in ports and pid:
                out.setdefault(port, pid)
    return out


def process_info(pid):
    """{'pid', 'ad', 'komut'} (Windows PowerShell CIM, Linux ve macOS ps; bulunamazsa ad '?')."""
    if os.name != 'nt':
        ps = lambda k: subprocess.run(['ps', '-p', str(int(pid)), '-o', k], capture_output=True, text=True, timeout=10).stdout.strip()
        try:
            ad, komut = ps('comm='), ps('args=')
        except (OSError, subprocess.SubprocessError):
            ad = komut = ''
        return {'pid': pid, 'ad': os.path.basename(ad) or '?', 'komut': komut}
    try:
        cmd = ('$p = Get-CimInstance Win32_Process -Filter "ProcessId=%d"; if ($p) { $p.Name; $p.CommandLine }' % int(pid))
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd], capture_output=True, text=True,
                           timeout=15, creationflags=NO_WINDOW, encoding='utf8', errors='replace')
        lines = r.stdout.splitlines()
        return {'pid': pid, 'ad': lines[0].strip() if lines else '?', 'komut': lines[1].strip() if len(lines) > 1 else ''}
    except Exception:
        return {'pid': pid, 'ad': '?', 'komut': ''}


def is_our_server(info):
    """Bu projenin web.py / game.py süreci mi (komut satırından)?"""
    c = (info.get('komut') or '').lower().replace('/', '\\')
    return 'python' in (info.get('ad') or '').lower() and any(os.path.join(SERVER, s).lower() in c or
                                                             ('\\server\\%s' % s) in c for s in SCRIPTS.values())


def kill(pid):
    if os.name != 'nt':
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass
        return
    subprocess.run(['taskkill', '/PID', str(int(pid)), '/T', '/F'], capture_output=True, timeout=15, creationflags=NO_WINDOW)


def istemci_ac(folder, cmd, env, logs):
    """İstemciyi aç -> Popen. Linux ve macOS'ta (Wine/Proton) kendi süreç grubunda (istemci_kapat bütün grubu kapatsın: Proton'da
    istemci açılan sürecin torunu); önek klasörü yoksa açılır, Wine'ın çıktısı logs/wine.log'a."""
    if os.name == 'nt':
        return subprocess.Popen(cmd, cwd=folder, env=env)
    for k in ('WINEPREFIX', 'STEAM_COMPAT_DATA_PATH'):
        if env and env.get(k):
            os.makedirs(env[k], exist_ok=True)
    with open(os.path.join(logs, 'wine.log'), 'a', encoding='utf8') as fh:
        wow64 = 'PROTON_USE_WOW64=%s ' % env['PROTON_USE_WOW64'] if env and env.get('PROTON_USE_WOW64') else ''
        fh.write('\n==== %s %s%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), wow64, ' '.join(cmd)))
        fh.flush()
        return subprocess.Popen(cmd, cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True)


def istemci_kapat(proc):
    """istemci_ac'ın açtığı istemciyi kapat (Linux ve macOS'ta süreç grubunu)."""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        proc.terminate()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        pass


def pencere_basligi(pid, metin, sure=120):
    """Sürecin oyun penceresi (UnityWndClass) belirince başlığını değiştirir (birden çok istemcide pencereler ayırt edilsin); arka
    planda, pencere çıkmazsa sure saniye sonra bırakır. Başlık bir dakika daha denetlenir (istemci yeniden yazarsa)."""
    if os.name != 'nt':
        return

    def run():
        import ctypes
        from ctypes import wintypes as wt
        u = ctypes.WinDLL('user32', use_last_error=True)
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.SetWindowTextW.argtypes = [wt.HWND, wt.LPCWSTR]
        proto = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def find():
            found = []

            def cb(h, _l):
                p = wt.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(p))
                if p.value == pid:
                    cls = ctypes.create_unicode_buffer(64)
                    u.GetClassNameW(h, cls, 64)
                    if cls.value == 'UnityWndClass':
                        found.append(h)
                return True
            u.EnumWindows(proto(cb), 0)
            return found

        end = time.time() + sure
        while time.time() < end:
            hs = find()
            if hs:
                for wait in (1, 4, 10, 20, 30):
                    time.sleep(wait)
                    for h in find():
                        buf = ctypes.create_unicode_buffer(256)
                        u.GetWindowTextW(h, buf, 256)
                        if buf.value != metin:
                            u.SetWindowTextW(h, metin)
                return
            time.sleep(1)
    threading.Thread(target=run, daemon=True).start()


def tail(path, lines=200, max_bytes=512 * 1024):
    """Dosyanın son satırları (büyük günlükte yalnız sonu okunur)."""
    try:
        with open(path, 'rb') as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read()
    except OSError:
        return []
    text = data.decode('utf8', 'replace').splitlines()
    if size > max_bytes:
        text = text[1:]
    return text[-lines:]


class Surec:
    """Panelin açtığı bir sunucu süreci."""

    def __init__(self, ad, cmd, konsol, durdur=None, ortam=None):
        self.ad, self.cmd, self.konsol, self.durdur, self.ortam = ad, cmd, konsol, durdur, ortam
        self.proc = None
        self.basla = None
        self.durduruldu = False

    def start(self):
        os.makedirs(os.path.dirname(self.konsol), exist_ok=True)
        if self.durdur and os.path.exists(self.durdur):
            os.remove(self.durdur)
        fh = open(self.konsol, 'a', encoding='utf8')
        fh.write('\n==== %s başlatıldı: %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), ' '.join(self.cmd[1:])))
        fh.flush()
        env = dict(os.environ, PYTHONIOENCODING='utf8', PYTHONUNBUFFERED='1', **(self.ortam or {}))
        self.proc = subprocess.Popen(self.cmd, cwd=SERVER, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW, env=env)
        fh.close()
        self.basla = time.time()
        self.durduruldu = False
        return self

    @property
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    @property
    def crashed(self):
        """Panel durdurmadan kapandı mı (çıkış kodu)?"""
        return self.proc is not None and self.proc.poll() is not None and not self.durduruldu

    def stop(self, timeout=6.0):
        if not self.alive:
            return
        self.durduruldu = True
        if self.durdur:
            with open(self.durdur, 'w') as fh:
                fh.write('durdur')
            try:
                self.proc.wait(timeout)
                return
            except subprocess.TimeoutExpired:
                pass
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            kill(self.proc.pid)

    def status(self):
        if self.proc is None:
            return {'durum': 'kapali'}
        code = self.proc.poll()
        if code is None:
            return {'durum': 'acik', 'pid': self.proc.pid, 'sure_sn': int(time.time() - self.basla)}
        return {'durum': 'kapali' if self.durduruldu else 'coktu', 'cikis_kodu': code}


class Yonetici:
    """Sunucular ve istemci: başlatma sırası, durum, istemci kapanınca yapılacaklar."""

    def __init__(self, logs, log=print):
        self.logs, self.log = logs, log
        self.lock = threading.RLock()
        self.sunucular = {}                 # ad -> Surec
        self.profil = None                  # açık sunucuların profil yolu
        self.slot = None
        self.arkadas = False                # oyun sunucusu arkadaş sunucusu olarak açık (Host)
        self.coklu = False                  # oyun sunucusu çoklu istemci için çok oturumlu açık (yalnız bu bilgisayar; coklu.py)
        self.misafir = False                # yalnız misafirin web sunucusu açık (Join)
        self.istemci = None                 # Popen
        self.istemci_basla = None
        self.istemci_son = None             # {'sure_sn', 'erken', 'kod'}
        self.on_client_exit = None          # panel bağlar: (erken) -> None
        self.yonetim_anahtar = secrets.token_urlsafe(32)

    # ------------------------------------------------------------ sunucular
    def servers_alive(self):
        return {ad: s.alive for ad, s in self.sunucular.items()}

    def running(self):
        """Panelin açtığı oyun sunucusu çalışıyor mu?"""
        s = self.sunucular.get('oyun')
        return bool(s and s.alive)

    def foreign_ports(self):
        """Panelin açmadığı süreçlerin tuttuğu portlar -> [{'port', 'ad', 'pid', 'surec', 'komut', 'bizim'}]."""
        ours = {s.proc.pid for s in self.sunucular.values() if s.alive}
        table = listeners()
        busy = [p for p in PORT_ADLARI if listening(p, table)]
        if not busy:
            return []
        owners = {p: pid for p, pid in table.items() if p in busy} if table is not None else port_owners(set(busy))
        out = []
        for port in busy:
            pid = owners.get(port)
            if pid in ours:
                continue
            info = process_info(pid) if pid else {'pid': None, 'ad': '?', 'komut': ''}
            out.append({'port': port, 'ad': _(PORT_ADLARI[port]), 'pid': pid, 'surec': info['ad'], 'komut': info['komut'][:300],
                        'bizim': is_our_server(info)})
        return out

    def needs_restart(self, profil, arkadas=None, coklu=None):
        """Açık sunucular bu kayıt ve kiple yeniden başlamalı mı (başka kayıt, Host ya da çoklu istemci kipi değişti)."""
        return self.running() and ((self.profil and os.path.normcase(self.profil) != os.path.normcase(profil))
                                   or self.arkadas != bool(arkadas) or (not arkadas and self.coklu != bool(coklu)))

    def start_servers(self, profil, ayarlar, kontrol=False, slot=None, arkadas=None, coklu=None):
        """Web ve oyun sunucusu (açık değilse) -> başlatılanların adları. Port doluysa ya da sunucu açılmazsa RuntimeError.
        arkadas: arkadaş sunucusunun ayarları (DO_COK_OYUNCULU; verilmezse tek oyunculu); coklu: çoklu istemcinin ayarları
        (DO_COK_OYUNCULU, misafirsiz; arkadaş sunucusu zaten çok oturumlu)."""
        ortam_json = arkadas or coklu
        with self.lock:
            if self.misafir:
                raise RuntimeError(_('Arkadaşının sunucusundasın: önce oradan ayrıl.'))
            if self.needs_restart(profil, arkadas, coklu):
                self.stop_servers()                               # başka kayıt ya da kip: yeniden başlat
            started = []
            py = python_exe()
            for ad in ('web', 'oyun'):
                s = self.sunucular.get(ad)
                if s and s.alive:
                    continue
                if ad == 'web' and port_80_sorunu():
                    raise RuntimeError(port_80_sorunu())
                busy = [p for p in PORTS[ad] if listening(p)]
                if busy:
                    raise RuntimeError(_('%s portu (%s) başka bir süreçte açık. Sunucu sayfasından kapatın ya da o programı kapatın.',
                                         '/'.join(map(str, busy)), _(PORT_ADLARI[busy[0]])))
                cmd = [py, '-I', os.path.join(SERVER, SCRIPTS[ad]), self.logs, '--profil=%s' % profil]
                durdur = None
                ortam = None
                if ad == 'web' and ortam_json:       # sunucunun kendi oyuncusunun oturumu (cok_oyunculu AYAR['yerel'])
                    cmd.append('--oturum=%s' % json.loads(ortam_json)['yerel'])
                if ad == 'oyun':
                    durdur = os.path.join(self.logs, '.durdur_oyun')
                    cmd += ['--ayarlar=%s' % ayarlar, '--durdur=%s' % durdur] + (['--kontrol'] if kontrol else [])
                    ortam = {'DO_YONETIM_ANAHTAR': self.yonetim_anahtar}
                    if ortam_json:
                        cmd.append('--cok-oyunculu')
                        ortam['DO_COK_OYUNCULU'] = ortam_json
                self.sunucular[ad] = Surec(ad, cmd, os.path.join(self.logs, '%s_konsol.log' % ad), durdur, ortam).start()
                started.append(ad)
            self.profil, self.slot, self.arkadas, self.coklu = profil, slot, bool(arkadas), bool(coklu and not arkadas)
            deadline = time.time() + 20
            while time.time() < deadline:
                if all(listening(PORTS[ad][0]) for ad in ('web', 'oyun')):
                    break
                dead = [ad for ad in ('web', 'oyun') if not self.sunucular[ad].alive]
                if dead:
                    lines = tail(self.sunucular[dead[0]].konsol, 12)
                    raise RuntimeError(_('%s sunucusu açılırken kapandı:\n%s', _({'web': 'Web', 'oyun': 'Oyun'}[dead[0]]),
                                         '\n'.join(lines)))
                time.sleep(0.15)
            else:
                raise RuntimeError(_('Sunucular 20 saniyede dinlemeye başlamadı (günlükleri inceleyin).'))
            if started:
                self.log('sunucular başlatıldı: %s (%s)%s' % (', '.join(started), profil, ' — arkadaş sunucusu' if arkadas else
                                                               ' — çoklu istemci' if coklu else ''))
            return started

    def start_guest_web(self, profil, slot, args):
        """Misafir: yalnız web.py, arkadaşın sunucusunu gösteren argümanlarla (arkadas.py). Kendi sunucuların açıksa RuntimeError."""
        with self.lock:
            if any(s.alive for s in self.sunucular.values()):
                raise RuntimeError(_('Önce kendi sunucunu durdur (Oyna > Sunucuyu durdur).'))
            if port_80_sorunu():
                raise RuntimeError(port_80_sorunu())
            busy = [p for p in PORTS['web'] if listening(p)]
            if busy:
                raise RuntimeError(_('%s portu (%s) başka bir süreçte açık. Sunucu sayfasından kapatın ya da o programı kapatın.',
                                     '/'.join(map(str, busy)), _(PORT_ADLARI[busy[0]])))
            cmd = [python_exe(), '-I', os.path.join(SERVER, SCRIPTS['web']), self.logs, '--profil=%s' % profil] + list(args)
            self.sunucular['web'] = s = Surec('web', cmd, os.path.join(self.logs, 'web_konsol.log')).start()
            self.profil, self.slot, self.misafir = profil, slot, True
            deadline = time.time() + 15
            while not listening(PORTS['web'][0]):
                if not s.alive or time.time() > deadline:
                    self.stop_servers()
                    raise RuntimeError(_('%s sunucusu açılırken kapandı:\n%s', _('Web'), '\n'.join(tail(s.konsol, 12))))
                time.sleep(0.15)
            self.log('misafirin web sunucusu başlatıldı (%s)' % profil)

    def stop_servers(self):
        with self.lock:
            for ad in ('oyun', 'web'):
                s = self.sunucular.get(ad)
                if s:
                    s.stop()
            self.log('sunucular durduruldu')
            self.profil = self.slot = None
            self.arkadas = self.coklu = self.misafir = False

    # ------------------------------------------------------------ istemci
    def client_alive(self):
        return self.istemci is not None and self.istemci.poll() is None

    def start_client(self, folder, cmd, env=None):
        """cmd, env: istemci.komut (Linux ve macOS'ta Wine ya da Proton ile)."""
        with self.lock:
            if self.client_alive():
                raise RuntimeError(_('İstemci zaten açık.'))
            self.istemci = istemci_ac(folder, cmd, env, self.logs)
            self.istemci_basla = time.time()
            self.istemci_son = None
            self.log('istemci başlatıldı: %s' % ' '.join(cmd))
            threading.Thread(target=self._watch_client, args=(self.istemci,), daemon=True).start()

    def _watch_client(self, proc):
        code = proc.wait()
        dur = time.time() - (self.istemci_basla or time.time())
        early = dur < ERKEN_KAPANMA_SN
        self.istemci_son = {'sure_sn': int(dur), 'erken': early, 'kod': code, 'zaman': time.strftime('%H:%M:%S')}
        self.log('istemci kapandı (%d sn, kod %s)%s' % (dur, code, ' — erken kapandı, sunucular açık kalır' if early else ''))
        if self.on_client_exit:
            try:
                self.on_client_exit(early)
            except Exception as e:
                self.log('istemci kapanış işlemi hatası: %r' % e)

    def stop_client(self):
        if self.client_alive():
            istemci_kapat(self.istemci)

    # ------------------------------------------------------------ durum
    def status(self):
        srv = {ad: (s.status() if s else {'durum': 'kapali'}) for ad, s in ((a, self.sunucular.get(a)) for a in ('web', 'oyun'))}
        table = listeners()
        for ad, st in srv.items():
            st['portlar'] = {p: listening(p, table) for p in PORTS[ad]}
        cl = {'durum': 'acik' if self.client_alive() else 'kapali'}
        if self.client_alive():
            cl.update(pid=self.istemci.pid, sure_sn=int(time.time() - self.istemci_basla))
        cl['son'] = self.istemci_son
        return {'sunucular': srv, 'istemci': cl, 'profil': self.profil, 'kayit': self.slot,
                'kontrol_kanali': listening(8099, table), 'arkadas': self.arkadas, 'coklu': self.coklu, 'misafir': self.misafir}
