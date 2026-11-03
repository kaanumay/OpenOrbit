"""Auto Mode page's API (ui/pilot.js): the settings file pilot.json next to the active save slot's profile, and the status the game server's
bot writes (<log folder>/pilot_status_<slot>.json, with the live map; server/pilot/system.py). No channel to the game is needed: the bot
re-reads the file when it changes (within a second).
  GET  /api/pilot            {config, status, online, ammo, rockets}
  POST /api/pilot            {config: {...}} save settings: a card's block ({'pet': {'gear': 2}}) is merged into what is saved, the other
                             keys replace theirs (lists, the per-map alien / priority lists and the map's areas whole); enabled and the
                             profiles are kept
  POST /api/pilot/start|stop
  POST /api/pilot/profile    {action: save | load | delete, name}  settings profiles (config.profile_action) """
import json, os, threading, time

import paths as PTH
from pilot import config as C

ONLINE_SEC = 5                      # the status is older than this: the game server is not running
MERGED = set(C.BLOCKS) | {k for k, spec in C.TOP.items() if spec[0] == 'block'}      # settings saved one value at a time (a card's block)
_AMMO, _ROCKETS = [], []
_LOCK = threading.Lock()            # the panel's server answers requests on several threads: one read-modify-write at a time


def _cfg_path():
    return C.path_for(PTH.profile_path())


def _ammo():
    """The laser ammo and the rockets of items.json (the panel's lists)."""
    if not _AMMO:
        try:
            with open(os.path.join(PTH.DATA, 'items.json'), encoding='utf8') as fh:
                d = json.load(fh)
            _AMMO.extend(sorted(d.get('laser_ammo') or {}))
            _ROCKETS.extend(sorted(d.get('rockets') or {}))
        except (OSError, ValueError):
            pass
    return _AMMO


def state():
    st = C.read_json(C.status_path(PTH.LOGS, PTH.profile_path()))
    st = st if isinstance(st, dict) else {}
    try:
        online = bool(st) and time.time() - float(st.get('updated') or 0) <= ONLINE_SEC
    except (TypeError, ValueError):
        online = False
    return dict(config=C.load(_cfg_path()), status=st if online else None, online=online, ammo=_ammo(), rockets=_ROCKETS)


def handles(path):
    return path == '/api/pilot' or path.startswith('/api/pilot/')


def get(path, q):
    if path != '/api/pilot':
        raise ValueError('Unknown request: %s' % path)
    return state()


def merge(cur, patch):
    """The saved settings with the panel's changes: a block is merged key by key, every other setting is replaced."""
    new = dict(cur)
    for k, v in patch.items():
        new[k] = dict(cur.get(k) or {}, **v) if k in MERGED and isinstance(v, dict) else v
    new['enabled'], new['profiles'] = cur['enabled'], cur['profiles']
    return new


def post(path, b):
    with _LOCK:
        p = _cfg_path()
        cur = C.load(p)
        if path == '/api/pilot':
            patch = b.get('config')
            if not isinstance(patch, dict):
                raise ValueError('The settings must be an object.')
            C.save(p, merge(cur, patch))
        elif path == '/api/pilot/profile':
            C.save(p, C.profile_action(cur, b.get('action'), b.get('name')))
        elif path in ('/api/pilot/start', '/api/pilot/stop'):
            cur['enabled'] = path.endswith('/start')
            C.save(p, cur)
        else:
            raise ValueError('Unknown request: %s' % path)
    return state()
