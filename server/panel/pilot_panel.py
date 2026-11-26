"""Auto Mode page's API (ui/pilot.js): the settings file pilot.json next to the active save slot's profile, and the status the game server's
bot writes (<log folder>/pilot_status_<slot>.json, with the live map; server/pilot/system.py). No channel to the game is needed: the bot
re-reads the file when it changes (within a second).
  GET  /api/pilot            {config, status, online, ammo, rockets}
  POST /api/pilot            {config: {...}} save settings: a card's block ({'pet': {'gear': 2}}) is merged into what is saved, the other
                             keys replace theirs (lists, the per-map alien / priority lists and the map's areas whole); enabled and the
                             profiles are kept
  POST /api/pilot/start|stop
  POST /api/pilot/profile    {action: save | load | delete, name}  settings profiles (config.profile_action)
  GET  /api/pilot/saves      [{id, name, pilot, enabled, online, state, active}] every save's Auto Mode (fork)
Every request takes an optional save (slot: ?slot= or the body's slot; default the active save): each save has its own pilot.json, and on a
multi-client server every session runs the bot of its own save, so Auto Mode can be on for one save and off for another. """
import json, os, threading, time

import paths as PTH
from pilot import config as C

ONLINE_SEC = 5                      # the status is older than this: the game server is not running
MERGED = set(C.BLOCKS) | {k for k, spec in C.TOP.items() if spec[0] == 'block'}      # settings saved one value at a time (a card's block)
_AMMO, _ROCKETS = [], []
_LOCK = threading.Lock()            # the panel's server answers requests on several threads: one read-modify-write at a time


def _slot(slot):
    """A save of save/slots (default: the active save) -> its id. Only an existing slot folder's own name (no path)."""
    slot = str(slot or '').strip() or PTH.active_slot()
    if not slot or os.path.basename(slot) != slot or slot.startswith('.') or not os.path.isfile(PTH.profile_path(slot)):
        raise ValueError('Save not found.')
    return slot


def _cfg_path(slot=None):
    return C.path_for(PTH.profile_path(_slot(slot)))


def _online(st):
    try:
        return bool(st) and time.time() - float(st.get('updated') or 0) <= ONLINE_SEC
    except (TypeError, ValueError):
        return False


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


def state(slot=None):
    slot = _slot(slot)
    st = C.read_json(C.status_path(PTH.LOGS, PTH.profile_path(slot)))
    st = st if isinstance(st, dict) else {}
    online = _online(st)
    return dict(config=C.load(_cfg_path(slot)), status=st if online else None, online=online, ammo=_ammo(), rockets=_ROCKETS, slot=slot)


def saves():
    """Every save's Auto Mode: on/off, whether its pilot is in the game now (the bot's status file is fresh) and what the bot is doing."""
    root, active = os.path.dirname(PTH.slot_dir('x')), PTH.active_slot()
    out = []
    for slot in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        prof = PTH.profile_path(slot)
        if not os.path.isfile(prof):
            continue
        meta = C.read_json(os.path.join(os.path.dirname(prof), 'slot.json'))
        meta = meta if isinstance(meta, dict) else {}
        st = C.read_json(C.status_path(PTH.LOGS, prof))
        st = st if isinstance(st, dict) else {}
        on = _online(st)
        out.append({'id': slot, 'name': meta.get('name') or slot, 'enabled': bool(C.load(C.path_for(prof)).get('enabled')), 'online': on,
                    'state': st.get('state') if on else None, 'active': slot == active})
    out.sort(key=lambda x: (not x['active'], x['name'].lower()))
    return out


def handles(path):
    return path == '/api/pilot' or path.startswith('/api/pilot/')


def get(path, q):
    if path == '/api/pilot/saves':
        return {'saves': saves()}
    if path != '/api/pilot':
        raise ValueError('Unknown request: %s' % path)
    return state(q.get('slot'))


def merge(cur, patch):
    """The saved settings with the panel's changes: a block is merged key by key, every other setting is replaced."""
    new = dict(cur)
    for k, v in patch.items():
        new[k] = dict(cur.get(k) or {}, **v) if k in MERGED and isinstance(v, dict) else v
    new['enabled'], new['profiles'] = cur['enabled'], cur['profiles']
    return new


def post(path, b):
    with _LOCK:
        p = _cfg_path(b.get('slot'))
        cur = C.load(p)
        if path == '/api/pilot':
            patch = b.get('config')
            if not isinstance(patch, dict):
                raise ValueError('The settings must be an object.')
            C.save(p, dict(merge(cur, patch), enabled=C.load(p)['enabled']))     # the bot may have stopped itself since cur was read
        elif path == '/api/pilot/profile':
            C.save(p, dict(C.profile_action(cur, b.get('action'), b.get('name')), enabled=C.load(p)['enabled']))
        elif path in ('/api/pilot/start', '/api/pilot/stop'):
            cur['enabled'] = path.endswith('/start')
            C.save(p, cur)
        else:
            raise ValueError('Unknown request: %s' % path)
    return state(b.get('slot'))
