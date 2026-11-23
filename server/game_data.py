"""Game data and worlds (World Editor): data/<file> + the selected world's patches to that file.

World: the change layer created in the panel's World Editor (save/worlds/<id>.json). Servers take it from the OO_WORLD environment
variable (panel/processes.py); if missing, the standard world (data/ as it is). Format:
  {"name": …, "patches": {"npc.json": {"/types/84": {...}, "/maps/5/npc": [...]}, "shop": {"/products/<lootId>": {...}}}}
Patch: JSON Pointer (RFC 6901) -> full value (replacement at the entity level); {"$delete": true} deletes. A path without a parent is skipped.
Virtual files (SANAL): content with no counterpart in data/, defined only by the world (the price and sale of shop products).
Modules call load() on import: the world is chosen when the game starts. While the game is running only changes to LIVE files are applied
(refresh: re-read when the file changes; game.watch_world refreshes the shop and the auction); the others when the server restarts.
Standard library only (the panel uses it too).
"""
import copy, json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
DELETE = '$delete'
VIRTUAL = {'shop': {'products': {}}}      # shop.py: {lootId: {price, currency ('C' | 'U'), on_sale}}
LIVE = ('shop', 'social.json')        # applied while the game is running: shop prices and sales, auction lots
_WORLD = None
_MTIME = None                            # modification time of the world file that was read
_SKIPPED = []                            # patches that could not be applied (file, path): for the log
_ERROR = None                            # the world file that could not be read at start (the standard world runs until refresh reads it)
_SHARED = {}                             # file -> the one parse shared() hands to every module that only reads it


def _read(p, tries=5):
    """The world file -> (world, mtime), or None if it cannot be read: locked for a moment (a virus scanner, the panel writing) or half written;
    a few tries first. A failed read never stands for the standard world (it would have dropped every World Editor change)."""
    for k in range(tries):
        try:
            t = os.path.getmtime(p)
            with open(p, encoding='utf8') as fh:
                d = json.load(fh)
            return (d if isinstance(d, dict) else {}), t
        except (OSError, ValueError):
            if k < tries - 1:
                time.sleep(0.1)
    return None


def world():
    """The selected world (OO_WORLD) or {} (standard). The standard one if it cannot be read (summary says so; refresh tries again)."""
    global _WORLD, _MTIME, _ERROR
    if _WORLD is None:
        p, _WORLD = os.environ.get('OO_WORLD'), {}
        r = _read(p) if p else None
        if r:
            _WORLD, _MTIME = r
        elif p:
            _MTIME, _ERROR = None, p
    return _WORLD


def refresh():
    """Re-reads the world file if it changed after being read -> the LIVE files that changed (empty if none). A read that fails keeps the
    current world and is tried again at the next call."""
    global _WORLD, _MTIME, _ERROR
    p = os.environ.get('OO_WORLD')
    if not p or _WORLD is None:
        return []
    try:
        t = os.path.getmtime(p)
    except OSError:
        return []
    if t == _MTIME:
        return []
    r = _read(p, tries=1)
    if r is None:
        return []
    old = (_WORLD.get('patches') or {})
    (_WORLD, _MTIME), _ERROR = r, None
    new_ = (_WORLD.get('patches') or {})
    return [d for d in LIVE if old.get(d) != new_.get(d)]


def path_parts(route):
    """'/a/b~1c' -> ['a', 'b/c'] (JSON Pointer)."""
    return [p.replace('~1', '/').replace('~0', '~') for p in route.split('/')[1:]]


def build_path(*parts):
    return ''.join('/' + str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def apply(data, patches, file=''):
    """Applies the patches over the data (in place); the number applied. In a list parent the part is the index."""
    n = 0
    for route, value in (patches or {}).items():
        part = path_parts(route)
        if not part:
            continue
        parent = data
        try:
            for p in part[:-1]:
                parent = parent[int(p)] if isinstance(parent, list) else parent[p]
            last = part[-1]
            remove = isinstance(value, dict) and value.get(DELETE)
            if isinstance(parent, list):
                i = int(last)
                if remove:
                    del parent[i]
                elif i == len(parent):
                    parent.append(copy.deepcopy(value))
                else:
                    parent[i] = copy.deepcopy(value)
            elif isinstance(parent, dict):
                if remove:
                    parent.pop(last, None)
                else:
                    parent[last] = copy.deepcopy(value)
            else:
                raise TypeError(type(parent).__name__)
            n += 1
        except (KeyError, IndexError, ValueError, TypeError):
            if (file, route) not in _SKIPPED:     # every load() of the file (several modules, live refresh) used to add it again
                _SKIPPED.append((file, route))
    return n


def raw(file):
    """Its state in the standard world (without patches)."""
    if file in VIRTUAL:
        return copy.deepcopy(VIRTUAL[file])
    with open(os.path.join(DATA, file), encoding='utf8') as fh:
        return json.load(fh)


def shared(file):
    """raw(file) parsed once per process and shared by the modules that only read it (several modules read the same big file at import).
    Never change it or anything in it: a module that changes its table takes its own raw()/load() or copies the part it changes."""
    d = _SHARED.get(file)
    if d is None:
        d = _SHARED[file] = raw(file)
    return d


def load(file, patches=None):
    """data/<file> + the world's (the selected world's if not given) patches to that file."""
    d = raw(file)
    apply(d, (world().get('patches') or {}).get(file) if patches is None else patches, file)
    return d


def summary():
    """Log line: the selected world's name, the patch count and the skipped ones."""
    w = world()
    if not w:
        return 'world: standard' + (' (the world file could not be read: %s)' % _ERROR if _ERROR else '')
    n = sum(len(v or {}) for v in (w.get('patches') or {}).values())
    return 'world: %s (%d changes%s)' % (w.get('name') or '?', n, ', skipped: %s' % _SKIPPED if _SKIPPED else '')
