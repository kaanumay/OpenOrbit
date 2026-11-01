"""Sunucu ve istemci süreçleri (panel).

  web   web.py: 80, 8090 (web girişi; 843, 9339, 8082 sahte TCP)
  oyun  game.py: 8081 (oyun), 7771 (sohbet), 8099 (kontrol kanalı, ayarla)
Arkadaş sunucusu (Arkadaşlarınla Oyna > Host): oyun sunucusu --multiplayer ve OO_MULTIPLAYER ortam değişkeniyle (friends.py).
Çoklu istemci (multi_client.py): oyun sunucusu yine --multiplayer ile, yalnız bu bilgisayardan ve misafirsiz (coklu ortamı).
Misafir (Join): yalnız web.py, arkadaşın sunucusunu gösteren argümanlarla (start_guest_web); oyun sunucusu açılmaz.
Sunucular konsolsuz (CREATE_NO_WINDOW) çalışır; çıktıları logs/<ad>_konsol.log'a (çökme izi orada). Oyun sunucusu --stop-file=<dosya>
ile durdurulur: dosya belirince profili kaydedip çıkar (zorla kapatmada son kaydedilmemiş saniyeler gitmesin); yanıt vermezse
sonlandırılır. Portu başka süreç tutuyorsa (önceki oturumdan kalan sunucu, başka program) kim olduğu bulunur; panel yalnız bu
projenin web.py / game.py süreçlerini kapatabilir.
Linux ve macOS: port tablosu /proc/net/tcp ya da lsof, süreç bilgisi ps; istemci Wine ya da Proton ile kendi süreç grubunda
(istemci_ac, client_runner.py). Linux 1024'ten küçük portları yalnız root'a açar: istemci web API'sini 80'den bekliyor (istemcinin
config.txt'si, değiştirilmez), port_80_sorunu kullanıcıya bir kerelik izin komutunu söyler. macOS'ta bir şey gerekmez: düşük portlar
0.0.0.0'da açılır, yalnız yerel bağlantılar kabul edilir (platform_compat.py).
"""
import json, os, signal, socket, subprocess, sys, threading, time

from lang import t as _

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(PANEL_DIR)
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
PORT_80_COMMAND = 'echo net.ipv4.ip_unprivileged_port_start=80 | sudo tee /etc/sysctl.d/90-openorbit.conf && sudo sysctl --system'
PORTS = {'web': (8090, 80), 'game': (8081, 7771)}
PORT_NAMES = {8090: 'Web login', 80: 'Web API', 8081: 'Game', 7771: 'Chat', 8099: 'Control channel'}
SCRIPTS = {'web': 'web.py', 'game': 'game.py'}
EARLY_EXIT_SEC = 15


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


def port_80_problem():
    """Linux 80 portunu (istemcinin web API'si) bu kullanıcıya açmıyorsa kullanıcıya gösterilecek metin, yoksa None. Port doluysa
    None: onu başlatmadaki port denetimi söyler. macOS'ta web.py 80'i 0.0.0.0'da açar (platform_compat.py): denetim de orada."""
    if os.name == 'nt':
        return None
    mac = sys.platform == 'darwin'
    with socket.socket() as s:
        try:
            s.bind(('0.0.0.0' if mac else '127.0.0.1', 80))
        except PermissionError:
            if mac:
                return _("macOS didn't allow port 80, and the game's web login uses it (macOS 10.14 or newer is needed).")
            return _("Linux opens port 80 only to root, and the game's web login uses it. Run this once in a terminal (it stays set): %s",
                     PORT_80_COMMAND)
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
            name, command = ps('comm='), ps('args=')
        except (OSError, subprocess.SubprocessError):
            name = command = ''
        return {'pid': pid, 'name': os.path.basename(name) or '?', 'command': command}
    try:
        cmd = ('$p = Get-CimInstance Win32_Process -Filter "ProcessId=%d"; if ($p) { $p.Name; $p.CommandLine }' % int(pid))
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd], capture_output=True, text=True,
                           timeout=15, creationflags=NO_WINDOW, encoding='utf8', errors='replace')
        lines = r.stdout.splitlines()
        return {'pid': pid, 'name': lines[0].strip() if lines else '?', 'command': lines[1].strip() if len(lines) > 1 else ''}
    except Exception:
        return {'pid': pid, 'name': '?', 'command': ''}


def is_our_server(info):
    """Bu projenin web.py / game.py süreci mi (komut satırından)?"""
    c = (info.get('command') or '').lower().replace('/', '\\')
    return 'python' in (info.get('name') or '').lower() and any(os.path.join(SERVER, s).lower() in c or
                                                             ('\\server\\%s' % s) in c for s in SCRIPTS.values())


def kill(pid):
    if os.name != 'nt':
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass
        return
    subprocess.run(['taskkill', '/PID', str(int(pid)), '/T', '/F'], capture_output=True, timeout=15, creationflags=NO_WINDOW)


def open_client(folder, cmd, env, logs):
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


def close_client(proc):
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


def window_title(pid, text, duration=120):
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

        end = time.time() + duration
        while time.time() < end:
            dmg = find()
            if dmg:
                for wait in (1, 4, 10, 20, 30):
                    time.sleep(wait)
                    for h in find():
                        buf = ctypes.create_unicode_buffer(256)
                        u.GetWindowTextW(h, buf, 256)
                        if buf.value != text:
                            u.SetWindowTextW(h, text)
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


def bot_signature(bot):
    """Bot paketinin (yol, içerik özeti): paket değişince sunucu yeniden başlar (botların ilerlemesi durum.json'da, sayılmaz)."""
    if not bot:
        return None
    import hashlib
    try:
        with open(bot, 'rb') as fh:
            return os.path.normcase(bot), hashlib.sha1(fh.read()).hexdigest()
    except OSError:
        return None


def world_signature(world):
    """Dünyanın (yol, içerik özeti): oyun açıldıktan sonra değişen dünya sunucuyu yeniden başlatır; oyun açıkken uygulanan
    değişiklikler (veri.CANLI: mağaza, açık artırma) sayılmaz. Standart: None."""
    if not world:
        return None
    import hashlib
    import game_data as DATA
    try:
        with open(world, encoding='utf8') as fh:
            y = {k: v for k, v in (json.load(fh).get('patches') or {}).items() if k not in DATA.LIVE}
        return os.path.normcase(world), hashlib.sha1(json.dumps(y, sort_keys=True).encode()).hexdigest()
    except (OSError, ValueError, AttributeError):
        return os.path.normcase(world), None


class Process:
    """Panelin açtığı bir sunucu süreci."""

    def __init__(self, name, cmd, console, stop_file=None, env=None):
        self.name, self.cmd, self.console, self.stop_file, self.env = name, cmd, console, stop_file, env
        self.proc = None
        self.started_at = None
        self.stopped = False

    def start(self):
        os.makedirs(os.path.dirname(self.console), exist_ok=True)
        if self.stop_file and os.path.exists(self.stop_file):
            os.remove(self.stop_file)
        fh = open(self.console, 'a', encoding='utf8')
        fh.write('\n==== %s başlatıldı: %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), ' '.join(self.cmd[1:])))
        fh.flush()
        env = dict(os.environ, PYTHONIOENCODING='utf8', PYTHONUNBUFFERED='1', **(self.env or {}))
        self.proc = subprocess.Popen(self.cmd, cwd=SERVER, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW, env=env)
        fh.close()
        self.started_at = time.time()
        self.stopped = False
        return self

    @property
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    @property
    def crashed(self):
        """Panel durdurmadan kapandı mı (çıkış kodu)?"""
        return self.proc is not None and self.proc.poll() is not None and not self.stopped

    def stop(self, timeout=6.0):
        if not self.alive:
            return
        self.stopped = True
        if self.stop_file:
            with open(self.stop_file, 'w') as fh:
                fh.write('stop')
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
            return {'state': 'off'}
        code = self.proc.poll()
        if code is None:
            return {'state': 'on', 'pid': self.proc.pid, 'sure_sn': int(time.time() - self.started_at)}
        return {'state': 'off' if self.stopped else 'crashed', 'exit_code': code}


class Manager:
    """Sunucular ve istemci: başlatma sırası, durum, istemci kapanınca yapılacaklar."""

    def __init__(self, logs, log=print):
        self.logs, self.log = logs, log
        self.lock = threading.RLock()
        self.servers = {}                 # ad -> Surec
        self.profile = None                  # açık sunucuların profil yolu
        self.slot = None
        self.friend = False                # oyun sunucusu arkadaş sunucusu olarak açık (Host)
        self.multi = False                  # oyun sunucusu çoklu istemci için çok oturumlu açık (yalnız bu bilgisayar; coklu.py)
        self.guest = False                # yalnız misafirin web sunucusu açık (Join)
        self.world = None                   # açık sunucuların dünyası (dunya_imzasi; standart: None)
        self.client = None                 # Popen
        self.client_started = None
        self.last_client = None             # {'sure_sn', 'erken', 'kod'}
        self.on_client_exit = None          # panel bağlar: (erken) -> None

    # ------------------------------------------------------------ sunucular
    def servers_alive(self):
        return {name: s.alive for name, s in self.servers.items()}

    def running(self):
        """Panelin açtığı oyun sunucusu çalışıyor mu?"""
        s = self.servers.get('game')
        return bool(s and s.alive)

    def foreign_ports(self):
        """Panelin açmadığı süreçlerin tuttuğu portlar -> [{'port', 'ad', 'pid', 'surec', 'komut', 'bizim'}]."""
        ours = {s.proc.pid for s in self.servers.values() if s.alive}
        table = listeners()
        busy = [p for p in PORT_NAMES if listening(p, table)]
        if not busy:
            return []
        owners = {p: pid for p, pid in table.items() if p in busy} if table is not None else port_owners(set(busy))
        out = []
        for port in busy:
            pid = owners.get(port)
            if pid in ours:
                continue
            info = process_info(pid) if pid else {'pid': None, 'name': '?', 'command': ''}
            out.append({'port': port, 'name': _(PORT_NAMES[port]), 'pid': pid, 'process': info['name'], 'command': info['command'][:300],
                        'ours': is_our_server(info)})
        return out

    def needs_restart(self, profile, friend=None, multi=None, world=None, bot=None):
        """Açık sunucular bu kayıt ve kiple yeniden başlamalı mı (başka kayıt, Host ya da çoklu istemci kipi, başka dünya ya da
        dünya açıldıktan sonra değişti, başka bot paketi ya da paket değişti)."""
        return self.running() and ((self.profile and os.path.normcase(self.profile) != os.path.normcase(profile))
                                   or self.friend != bool(friend) or (not friend and self.multi != bool(multi))
                                   or self.world != world_signature(world) or getattr(self, 'bot', None) != bot_signature(bot))

    def start_servers(self, profile, settings, control=False, slot=None, friend=None, multi=None, world=None, bot=None):
        """Web ve oyun sunucusu (açık değilse) -> başlatılanların adları. Port doluysa ya da sunucu açılmazsa RuntimeError.
        arkadas: arkadaş sunucusunun ayarları (OO_MULTIPLAYER; verilmezse tek oyunculu); coklu: çoklu istemcinin ayarları
        (OO_MULTIPLAYER, misafirsiz; arkadaş sunucusu zaten çok oturumlu); dunya: Dünya Editörü'nün dünya dosyası (OO_WORLD;
        verilmezse standart dünya); bot: dünyanın bot paketi (OO_BOT; Botlar sayfası)."""
        env_json = friend or multi
        with self.lock:
            if self.guest:
                raise RuntimeError(_("You are on a friend's server: leave it first."))
            if self.needs_restart(profile, friend, multi, world, bot):
                self.stop_servers()                               # başka kayıt ya da kip: yeniden başlat
            started = []
            py = python_exe()
            for name in ('web', 'game'):
                s = self.servers.get(name)
                if s and s.alive:
                    continue
                if name == 'web' and port_80_problem():
                    raise RuntimeError(port_80_problem())
                busy = [p for p in PORTS[name] if listening(p)]
                if busy:
                    raise RuntimeError(_('Port %s (%s) is held by another process. Close it on the Server page or quit that program.',
                                         '/'.join(map(str, busy)), _(PORT_NAMES[busy[0]])))
                cmd = [py, '-I', os.path.join(SERVER, SCRIPTS[name]), self.logs, '--profile=%s' % profile]
                stop_file = None
                env = {'OO_WORLD': world} if world else None
                if name == 'web' and env_json:       # sunucunun kendi oyuncusunun oturumu (cok_oyunculu AYAR['yerel'])
                    cmd.append('--session=%s' % json.loads(env_json)['local'])
                if name == 'game':
                    stop_file = os.path.join(self.logs, '.durdur_oyun')
                    cmd += ['--settings=%s' % settings, '--stop-file=%s' % stop_file] + (['--control'] if control else [])
                    if env_json:
                        cmd.append('--multiplayer')
                        env = dict(env or {}, OO_MULTIPLAYER=env_json)
                    if bot:
                        env = dict(env or {}, OO_BOT=bot)
                self.servers[name] = Process(name, cmd, os.path.join(self.logs, '%s_konsol.log' % name), stop_file, env).start()
                started.append(name)
            self.profile, self.slot, self.friend, self.multi = profile, slot, bool(friend), bool(multi and not friend)
            self.world = world_signature(world)
            self.bot = bot_signature(bot)
            deadline = time.time() + 20
            while time.time() < deadline:
                if all(listening(PORTS[name][0]) for name in ('web', 'game')):
                    break
                dead = [name for name in ('web', 'game') if not self.servers[name].alive]
                if dead:
                    lines = tail(self.servers[dead[0]].console, 12)
                    raise RuntimeError(_('The %s server closed while starting:\n%s', _({'web': 'Web', 'game': 'Game'}[dead[0]]),
                                         '\n'.join(lines)))
                time.sleep(0.15)
            else:
                raise RuntimeError(_("The servers didn't start listening within 20 seconds (check the logs)."))
            if started:
                self.log('sunucular başlatıldı: %s (%s)%s' % (', '.join(started), profile, ' — arkadaş sunucusu' if friend else
                                                               ' — çoklu istemci' if multi else ''))
            return started

    def start_guest_web(self, profile, slot, args):
        """Misafir: yalnız web.py, arkadaşın sunucusunu gösteren argümanlarla (friends.py). Kendi sunucuların açıksa RuntimeError."""
        with self.lock:
            if any(s.alive for s in self.servers.values()):
                raise RuntimeError(_('First stop your own server (Play > Stop server).'))
            if port_80_problem():
                raise RuntimeError(port_80_problem())
            busy = [p for p in PORTS['web'] if listening(p)]
            if busy:
                raise RuntimeError(_('Port %s (%s) is held by another process. Close it on the Server page or quit that program.',
                                     '/'.join(map(str, busy)), _(PORT_NAMES[busy[0]])))
            cmd = [python_exe(), '-I', os.path.join(SERVER, SCRIPTS['web']), self.logs, '--profile=%s' % profile] + list(args)
            self.servers['web'] = s = Process('web', cmd, os.path.join(self.logs, 'web_konsol.log')).start()
            self.profile, self.slot, self.guest = profile, slot, True
            deadline = time.time() + 15
            while not listening(PORTS['web'][0]):
                if not s.alive or time.time() > deadline:
                    self.stop_servers()
                    raise RuntimeError(_('The %s server closed while starting:\n%s', _('Web'), '\n'.join(tail(s.console, 12))))
                time.sleep(0.15)
            self.log('misafirin web sunucusu başlatıldı (%s)' % profile)

    def stop_servers(self):
        with self.lock:
            for name in ('game', 'web'):
                s = self.servers.get(name)
                if s:
                    s.stop()
            self.log('sunucular durduruldu')
            self.profile = self.slot = self.world = None
            self.friend = self.multi = self.guest = False

    # ------------------------------------------------------------ istemci
    def client_alive(self):
        return self.client is not None and self.client.poll() is None

    def start_client(self, folder, cmd, env=None):
        """cmd, env: istemci.komut (Linux ve macOS'ta Wine ya da Proton ile)."""
        with self.lock:
            if self.client_alive():
                raise RuntimeError(_('The client is already running.'))
            self.client = open_client(folder, cmd, env, self.logs)
            self.client_started = time.time()
            self.last_client = None
            self.log('istemci başlatıldı: %s' % ' '.join(cmd))
            threading.Thread(target=self._watch_client, args=(self.client,), daemon=True).start()

    def _watch_client(self, proc):
        code = proc.wait()
        stop = time.time() - (self.client_started or time.time())
        early = stop < EARLY_EXIT_SEC
        self.last_client = {'sure_sn': int(stop), 'early': early, 'code': code, 'time': time.strftime('%H:%M:%S')}
        self.log('istemci kapandı (%d sn, kod %s)%s' % (stop, code, ' — erken kapandı, sunucular açık kalır' if early else ''))
        if self.on_client_exit:
            try:
                self.on_client_exit(early)
            except Exception as e:
                self.log('istemci kapanış işlemi hatası: %r' % e)

    def stop_client(self):
        if self.client_alive():
            close_client(self.client)

    # ------------------------------------------------------------ durum
    def status(self):
        srv = {name: (s.status() if s else {'state': 'off'}) for name, s in ((a, self.servers.get(a)) for a in ('web', 'game'))}
        table = listeners()
        for name, st in srv.items():
            st['ports'] = {p: listening(p, table) for p in PORTS[name]}
        cl = {'state': 'on' if self.client_alive() else 'off'}
        if self.client_alive():
            cl.update(pid=self.client.pid, sure_sn=int(time.time() - self.client_started))
        cl['last'] = self.last_client
        return {'servers': srv, 'client': cl, 'profile': self.profile, 'record': self.slot,
                'control_channel': listening(8099, table), 'friend': self.friend, 'multi': self.multi, 'guest': self.guest}
