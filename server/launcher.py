"""Komut satırı başlatıcısı (geliştirici yedeği; oyun normalde yönetim panelinden açılır: "OpenOrbit Panel.pyw", server/panel/):
profil yedeği, günlük döndürme, web ve oyun sunucuları, orijinal istemci.

- Profil: panelin etkin kayıt yuvası (paths.py; save/kayitlar/<yuva>/profil.json), yoksa eski save/profil.json. İki sunucuya da
  --profile, oyun sunucusuna --settings (kaydın oyun ayarları; yoksa eski save/ayarlar.json) verilir.
- Profil yedeği: <yuva>/yedek/oto_YYYYmmdd_HHMMSS.json (eski düzende save/yedek/profil_…); en yeni YEDEK_SAYISI kalır.
- Günlük döndürme: logs/gs.log, http.log, client.log büyükse .1, .2, .3'e kayar (açık bir sunucu dosyayı tutuyorsa atlanır).
- Sunucular: 8081 (oyun) ve 8090 (web) zaten dinleniyorsa yeniden başlatılmaz, onlar kullanılır ve sonda kapatılmaz.
- İstemci: DarkOrbit_Version1.1.116\\DarkOrbit.exe yalnız başlatma argümanıyla (resmi sunuculara bağlanmaz, dosyalar değişmez).
  İstemci kapanınca bu başlatıcının açtığı sunucular kapanır. İstemci hemen kapanırsa (başka pencere açtıysa) sunucular açık kalır.
Kullanım: python -I launcher.py [oyun sunucusu seçenekleri: --no-popups, --invulnerable …]
"""
import glob, os, shutil, socket, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths as PTH  # noqa: E402
LOGS = os.path.join(HERE, 'logs')
SAVE = os.path.join(HERE, 'save')
CLIENT = os.path.join(HERE, '..', 'DarkOrbit_Version1.1.116', 'DarkOrbit.exe')
CLIENT_ARGS = ['http://127.0.0.1:8090/#darkorbit://', '-screen-fullscreen', '0', '-screen-width', '1440', '-screen-height', '900']
BACKUP_COUNT = 10
LOG_SIZE_LIMIT = 5 * 1024 * 1024
LOG_COPIES = 3
EARLY_EXIT_SEC = 15


def backup_profile(save_dir=SAVE, keep=BACKUP_COUNT, now=None, prefix='profile'):
    """Profilin zaman damgalı yedeği; eskiler silinir -> yedeğin yolu ya da None. Kayıt yuvasında prefix 'oto' (panelin adı)."""
    src = os.path.join(save_dir, 'profile.json')
    if not os.path.exists(src):
        return None
    dst_dir = os.path.join(save_dir, 'backups')
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, '%s_%s.json' % (prefix, time.strftime('%Y%m%d_%H%M%S', time.localtime(now))))
    shutil.copy2(src, dst)
    for old in sorted(glob.glob(os.path.join(dst_dir, '%s_*.json' % prefix)))[:-keep]:
        os.remove(old)
    return dst


def rotate_logs(log_dir=LOGS, limit=LOG_SIZE_LIMIT, copies=LOG_COPIES, names=('gs.log', 'http.log', 'client.log')):
    """Büyük günlükleri kaydır (gs.log -> gs.1.log …) -> kaydırılanların adları. Dosya kullanımdaysa (açık sunucu) atlanır."""
    done = []
    for name in names:
        path = os.path.join(log_dir, name)
        if not os.path.exists(path) or os.path.getsize(path) < limit:
            continue
        base, ext = os.path.splitext(path)
        try:
            for i in range(copies - 1, 0, -1):
                if os.path.exists('%s.%d%s' % (base, i, ext)):
                    os.replace('%s.%d%s' % (base, i, ext), '%s.%d%s' % (base, i + 1, ext))
            os.replace(path, '%s.1%s' % (base, ext))
            done.append(name)
        except OSError:
            pass                                     # açık sunucu dosyayı tutuyor: bir dahaki başlatmaya
    return done


def listening(port, host='127.0.0.1'):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def start_servers(extra, profile=None):
    """Dinlenmeyen sunucuları başlat -> başlatılan süreçler."""
    procs = []
    p = ['--profile=%s' % profile] if profile else []
    os.makedirs(LOGS, exist_ok=True)
    kw = {}
    if os.name == 'nt':                               # kendi küçültülmüş pencerelerinde (eski Baslat.bat'taki gibi)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7                            # SW_SHOWMINNOACTIVE
        kw = dict(creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)
    if not listening(8090):
        procs.append(subprocess.Popen([sys.executable, '-I', os.path.join(HERE, 'web.py'), LOGS] + p, **kw))
    if not listening(8081):
        procs.append(subprocess.Popen([sys.executable, '-I', os.path.join(HERE, 'game.py'), LOGS] + p + ['--settings=%s' % PTH.settings_path()]
                                      + extra, **kw))
    for _ in range(50):                               # sunucular dinlemeye başlayana dek (en çok ~5 sn)
        if listening(8081) and listening(8090):
            break
        time.sleep(0.1)
    return procs


def main():
    extra = [a for a in sys.argv[1:] if a.startswith('--')]
    prof = PTH.profile_path()
    slot = PTH.active_slot()
    b = backup_profile(os.path.dirname(prof), prefix='auto' if slot else 'profile')
    print('kayıt: %s' % (slot or 'eski save/profil.json'))
    print('profil yedeği: %s' % (b or 'profil yok (ilk açılış)'))
    r = rotate_logs()
    if r:
        print('günlükler döndürüldü: %s' % ', '.join(r))
    procs = start_servers(extra, prof)
    print('sunucular: %s' % ('başlatıldı' if procs else 'zaten açık, onlar kullanılıyor'))
    t0 = time.time()
    client = subprocess.Popen([CLIENT] + CLIENT_ARGS + ['-logFile', os.path.join(LOGS, 'client.log')], cwd=os.path.dirname(CLIENT))
    client.wait()
    if time.time() - t0 < EARLY_EXIT_SEC:
        print('İstemci hemen kapandı; sunucular açık kalıyor (kapatmak için pencerelerini kapatın).')
        return
    for p in procs:
        p.terminate()
    print('istemci kapandı; %s' % ('başlatılan sunucular kapatıldı' if procs else 'sunucular önceden açıktı, açık bırakıldı'))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
