"""Multi-client (panel): after PLAY, extra game clients with the other saves on this computer.

The game server is opened in multi-session mode (if the panel setting multi_client is on and there are at least two saves; on a friend
server it already is). The extra client's save is added to the server with POST /local/add (server/multiplayer.py: the server writes
directly to the slot's profile.json; if its id equals another player's, a temporary id in memory), the client is opened with
http://127.0.0.1:8090/?session=<key>#darkorbit:// (web.py asks the server for the key). When the client closes, POST /local/remove: the
final state is written, the slot is freed. Extra clients are opened in window mode, the window title is the pilot's name; their logs are
logs/client_<save>.log. The main save, a save that is open, the same pilot name and going over the limit are rejected; while an extra
client is open, actions that restart the server are blocked in the panel (panel.py). Plan and problems thought out in advance:
belgeler/COKLU_ISTEMCI.md. """
import json, os, threading, time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from lang import t as _, remote
import client as IST
import processes as PR

GAME = 'http://127.0.0.1:8081'
OPENER = build_opener(ProxyHandler({}))       # do not go to the local server through the system's proxy
EARLY_SEC = 15                                  # a client that closes before this: closed early (warning on the card)


class MultiClientError(Exception):
    """Error shown to the user."""


class MultiClient:
    def __init__(self, cfg, saves, direction, key, logs, log=print):
        """key: () -> the game server's management key (friends.Friend.key; OO_MULTIPLAYER)."""
        self.cfg, self.saves, self.direction, self.key, self.logs, self.log = cfg, saves, direction, key, logs, log
        self.lock = threading.RLock()
        self.is_open = {}                 # save -> {'proc', 'session', 'uid', 'start', 'pilot', 'daily'} ('proc' None: starting)
        self.last = {}                  # save -> last close {'sure_sn', 'early', 'code', 'time', 'end_time'}
        self.last_backup = {}            # save -> last periodic backup
        self.on_exit = None            # the panel binds: () -> None (an extra client closed)

    # ------------------------------------------------------------ game server
    def request(self, path, body):
        data = json.dumps(dict(body, key=self.key())).encode('utf8')
        req = Request(GAME + path, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with OPENER.open(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode('utf8') or '{}')
        except HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode('utf8') or '{}')
            except ValueError:
                return e.code, {}
        except (URLError, OSError, ValueError) as e:
            raise MultiClientError(_("Couldn't reach the game server (%s).", getattr(e, 'reason', e)))

    # ------------------------------------------------------------ state
    def live(self):
        """Saves of the extra clients that are open, opening or closing (a closing client's slot leaves once it is released on the server:
        so that a client reopened right away does not connect to the old session on the server and then get released with it)."""
        with self.lock:
            return list(self.is_open)

    def in_use(self, slot):
        return slot in self.live()

    def pids(self):
        with self.lock:
            return {e['proc'].pid for e in self.is_open.values() if e['proc'] is not None}

    def state(self, live=None):
        """The panel's list: extra clients (with the server's live_status.json 'yereller': connected?, map, level)."""
        lv = {y.get('record'): y for y in ((live or {}).get('local_players') or [])}
        now = time.time()
        with self.lock:
            out = []
            for s, e in self.is_open.items():
                y = lv.get(s) or {}
                out.append({'record': s, 'pilot': e['pilot'], 'pid': e['proc'].pid if e['proc'] else None,
                            'state': 'opening' if e['proc'] is None else 'on' if e['proc'].poll() is None else 'closing',
                            'duration_sec': int(now - e['start']),
                            'connected': bool(y.get('connected')), 'map': y.get('map'), 'level': y.get('level'), 'uid': e['uid']})
            return {'clients': out, 'last': dict(self.last)}

    # ------------------------------------------------------------ opening and closing
    def open_(self, slot, folder, main_slot):
        """Open the extra client (the server must be open in multi-session mode: the panel checks). -> status."""
        if slot == main_slot:
            raise MultiClientError(_('This save is open in the main client: pick another save for the extra client.'))
        if not self.saves.exists(slot):
            raise MultiClientError(_('Save not found.'))
        c = IST.check(folder)
        if not c['valid']:
            raise MultiClientError(_('Invalid client folder: %s', ' '.join(c['issues'])))
        with self.lock:
            if slot in self.live():
                raise MultiClientError(_('This save is already open in an extra client.'))
            n = self.cfg.get('multi_client_max')
            if len(self.live()) >= n:
                raise MultiClientError(_('At most %d extra clients can be open (Client > Multi-client).', n))
            self.is_open[slot] = {'proc': None, 'session': None, 'uid': None, 'start': time.time(), 'pilot': '', 'daily': None}
        out = None
        try:
            summary = self.saves.summary(slot)
            if summary.get('corrupt'):
                raise MultiClientError(_("The save can't be read (corrupt): restore it from Saves > Backups."))
            if self.cfg.get('backup_on_launch'):
                self.saves.backup(slot, 'auto', _('Extra client (start)'))
            self.last_backup[slot] = time.time()
            code, out = self.request('/local/add', {'record': slot, 'route': self.saves.profile(slot)})
            if code != 200:
                raise MultiClientError(remote(out) or out.get('message') or _("The game server didn't take the save (HTTP %s).", code))
            daily = os.path.join(self.logs, 'client_%s.log' % slot)
            import launcher
            launcher.rotate_logs(self.logs, names=(os.path.basename(daily),))
            cmd, env = IST.command(self.cfg, folder, daily, session=out['session'], window=True)
            proc = PR.open_client(folder, cmd, env, self.logs)
        except Exception:
            with self.lock:
                self.is_open.pop(slot, None)
            if out and out.get('session'):            # if it registered with the server, release it (otherwise the save was thought to be editable)
                try:
                    self.request('/local/remove', {'session': out['session']})
                except Exception:
                    pass
            raise
        pilot = summary.get('pilot') or slot
        with self.lock:
            self.is_open[slot].update(proc=proc, session=out['session'], uid=out['uid'], start=time.time(), pilot=pilot, daily=daily)
        m = self.saves.meta(slot)
        self.saves.set_meta(slot, last_played=time.strftime('%Y-%m-%d %H:%M:%S'), play_count=int(m.get('play_count') or 0) + 1)
        PR.window_title(proc.pid, 'DarkOrbit — %s' % pilot)
        self.log('extra client opened: %s (%s), process %d, id on the server %s%s' % (slot, pilot, proc.pid, out['uid'],
                                                                               ' (continuing)' if out.get('ongoing') else ''))
        threading.Thread(target=self._watch, args=(slot, proc), daemon=True).start()
        return self.state()

    def _watch(self, slot, proc):
        code = proc.wait()
        with self.lock:
            e = self.is_open.get(slot)
        stop = time.time() - (e['start'] if e else time.time())
        if e and e['session'] and self.direction.running():
            try:
                c, out = self.request('/local/remove', {'session': e['session']})
                if c not in (200, 404):
                    self.log('extra client save could not be released (%s): %s' % (c, out))
            except MultiClientError as err:
                self.log('extra client save could not be released: %s' % err)
        with self.lock:
            if self.is_open.get(slot, {}).get('proc') is proc:
                self.is_open.pop(slot, None)
            self.last[slot] = {'duration_sec': int(stop), 'early': stop < EARLY_SEC and not (e or {}).get('closed'), 'code': code,
                              'time': time.strftime('%H:%M:%S'), 'end_time': time.time()}      # one closed from the panel does not count as early
        self.log('extra client closed: %s (%d s, code %s)' % (slot, stop, code))
        if self.on_exit:
            try:
                self.on_exit()
            except Exception as err:                   # noqa: BLE001
                self.log('extra client close handler error: %r' % err)

    def close(self, slot):
        with self.lock:
            e = self.is_open.get(slot)
        if not e or e['proc'] is None:
            raise MultiClientError(_('No extra client is open with this save.'))
        if e['proc'].poll() is None:
            e['closed'] = True
            PR.close_client(e['proc'])

    def close_all(self, wait=0.0):
        """Close all extra clients; wait: waits at most this long for the closings (the final save to the server)."""
        with self.lock:
            is_open = [e for e in self.is_open.values() if e['proc'] is not None and e['proc'].poll() is None]
        for e in is_open:
            e['closed'] = True
            PR.close_client(e['proc'])
        end = time.time() + wait
        while self.live() and time.time() < end:
            time.sleep(0.1)

    def backup(self, interval_min):
        """Periodic backup of the extra clients' saves while the game runs (the panel's timer)."""
        if not interval_min:
            return
        for s in self.live():
            if time.time() - self.last_backup.get(s, 0) >= interval_min * 60:
                self.saves.backup(s, 'auto', _('During the game'))
                self.last_backup[s] = time.time()
