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
import copy, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
DELETE = '$delete'
VIRTUAL = {'shop': {'products': {}}}      # shop.py: {lootId: {price, currency ('C' | 'U'), on_sale}}
LIVE = ('shop', 'social.json')        # applied while the game is running: shop prices and sales, auction lots
_WORLD = None
_MTIME = None                            # modification time of the world file that was read
_SKIPPED = []                            # patches that could not be applied (file, path): for the log


def world():
    """The selected world (OO_WORLD) or {} (standard). The standard one if it cannot be read."""
    global _WORLD, _MTIME
    if _WORLD is None:
        p, _WORLD = os.environ.get('OO_WORLD'), {}
        try:
            if p:
                _MTIME = os.path.getmtime(p)
                with open(p, encoding='utf8') as fh:
                    _WORLD = json.load(fh)
        except (OSError, ValueError):
            pass
        if not isinstance(_WORLD, dict):
            _WORLD = {}
    return _WORLD


def refresh():
    """Re-reads the world file if it changed after being read -> the LIVE files that changed (empty if none)."""
    global _WORLD
    p = os.environ.get('OO_WORLD')
    if not p or _WORLD is None:
        return []
    try:
        t = os.path.getmtime(p)
    except OSError:
        return []
    if t == _MTIME:
        return []
    old = (_WORLD.get('patches') or {})
    _WORLD = None
    new_ = (world().get('patches') or {})
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
            _SKIPPED.append((file, route))
    return n


def raw(file):
    """Its state in the standard world (without patches)."""
    if file in VIRTUAL:
        return copy.deepcopy(VIRTUAL[file])
    with open(os.path.join(DATA, file), encoding='utf8') as fh:
        return json.load(fh)


def load(file, patches=None):
    """data/<file> + the world's (the selected world's if not given) patches to that file."""
    d = raw(file)
    apply(d, (world().get('patches') or {}).get(file) if patches is None else patches, file)
    return d


def summary():
    """Log line: the selected world's name, the patch count and the skipped ones."""
    w = world()
    if not w:
        return 'dünya: standart'
    n = sum(len(v or {}) for v in (w.get('patches') or {}).values())
    return 'dünya: %s (%d değişiklik%s)' % (w.get('name') or '?', n, ', atlanan: %s' % _SKIPPED if _SKIPPED else '')
