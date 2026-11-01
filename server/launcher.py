"""Command-line launcher (developer fallback; the game is normally opened from the management panel: "OpenOrbit Panel.pyw", server/panel/):
profile backup, log rotation, web and game servers, the original client.

- Profile: the panel's active save slot (paths.py; save/slots/<slot>/profile.json), otherwise the old save/profile.json. Both servers get
  --profile, the game server gets --settings (the save's game settings; otherwise the old save/settings.json).
- Profile backup: <slot>/backups/auto_YYYYmmdd_HHMMSS.json (in the old layout save/backups/profile_...); the newest BACKUP_COUNT are kept.
- Log rotation: logs/gs.log, http.log, client.log, if large, shift to .1, .2, .3 (skipped if a running server holds the file).
- Servers: if 8081 (game) and 8090 (web) are already being listened on, they are not restarted, those are used and not shut down at the end.
- Client: DarkOrbit_Version1.1.116\\DarkOrbit.exe only with a launch argument (it does not connect to the official servers, files are not changed).
  When the client closes, the servers this launcher opened close. If the client closes immediately (it opened another window), the servers stay open.
Usage: python -I launcher.py [game server options: --no-popups, --invulnerable ...]
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
    """A timestamped backup of the profile; old ones are deleted -> the backup's path or None. In the save slot the prefix is 'oto' (the panel's name)."""
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
    """Rotate large logs (gs.log -> gs.1.log ...) -> the names of those rotated. Skipped if the file is in use (running server)."""
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
            pass                                     # a running server holds the file: until the next launch
    return done


def listening(port, host='127.0.0.1'):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def start_servers(extra, profile=None):
    """Start the servers that are not being listened on -> the started processes."""
    procs = []
    p = ['--profile=%s' % profile] if profile else []
    os.makedirs(LOGS, exist_ok=True)
    kw = {}
    if os.name == 'nt':                               # in their own minimized windows (as in the old Baslat.bat)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7                            # SW_SHOWMINNOACTIVE
        kw = dict(creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)
    if not listening(8090):
        procs.append(subprocess.Popen([sys.executable, '-I', os.path.join(HERE, 'web.py'), LOGS] + p, **kw))
    if not listening(8081):
        procs.append(subprocess.Popen([sys.executable, '-I', os.path.join(HERE, 'game.py'), LOGS] + p + ['--settings=%s' % PTH.settings_path()]
                                      + extra, **kw))
    for _ in range(50):                               # until the servers start listening (at most ~5 s)
        if listening(8081) and listening(8090):
            break
        time.sleep(0.1)
    return procs


def main():
    extra = [a for a in sys.argv[1:] if a.startswith('--')]
    prof = PTH.profile_path()
    slot = PTH.active_slot()
    b = backup_profile(os.path.dirname(prof), prefix='auto' if slot else 'profile')
    print('save: %s' % (slot or 'old save/profil.json'))
    print('profile backup: %s' % (b or 'no profile (first run)'))
    r = rotate_logs()
    if r:
        print('logs rotated: %s' % ', '.join(r))
    procs = start_servers(extra, prof)
    print('servers: %s' % ('started' if procs else 'already running, using those'))
    t0 = time.time()
    client = subprocess.Popen([CLIENT] + CLIENT_ARGS + ['-logFile', os.path.join(LOGS, 'client.log')], cwd=os.path.dirname(CLIENT))
    client.wait()
    if time.time() - t0 < EARLY_EXIT_SEC:
        print('The client closed immediately; the servers stay open (close their windows to shut them down).')
        return
    for p in procs:
        p.terminate()
    print('client closed; %s' % ('started servers shut down' if procs else 'servers were already running, left open'))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
