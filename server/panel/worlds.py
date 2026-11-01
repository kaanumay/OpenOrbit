"""The World Editor's store and sections (panel.py's /api/dunya... endpoints; user request 2026-10-28, belgeler/DUNYA_EDITORU.md).

World: a layer of changes placed on top of the standard game data (server/data), save/worlds/<id>.json:
  {version, name, description, cover, created, update, patches: {file: {JSON Pointer: full value | {"$delete": true}}}}
The server applies it with game_data.py (OO_WORLD). The standard world ("standard") is read-only: changes made on it are written to the draft
(save/worlds/_draft.json), "Save as new world" turns the draft into a world.
Only allowed paths are written (PATHS); values are cleaned by type (so the game server does not open with corrupt data).
Sections (the editor's views): standard value + the world's + a changed marker; map, quest and shop details are separate.
"""
import base64, copy, datetime, hashlib, json, os, re, threading, zlib

import paths as PTH
import save_migration as SM
import game_data as DATA
from lang import t as _

STANDARD = 'standard'
COVERS = ('standard', 'nebula', 'crimson', 'ice', 'mining', 'crystal', 'toxic', 'void')
VERSION = 1
NAME_LENGTH, DESCRIPTION_LENGTH = 40, 240
NEW_QUEST = 900000              # new quests' ids start here (the game's quests < 900000; root state and condition ids are in a separate range)
NEW_ALIEN = 'custom_'            # key of new alien types (custom_1, custom_2 ...)
COUNT_MAX = 300                # most of one type on a map
# section -> list of (file, path prefix): change count and "revert section to standard"
SECTIONS = {
    'maps': [('npc.json', '/maps/'), ('map_layout.json', '/maps/'), ('items.json', '/ores/')],
    'alien_spawns': [('npc.json', '/types/')],
    'quests': [('quests.json', '/quests/'), ('quest_extras.json', '/quests/')],
    'shop': [('shop', '/products/')],
    'auction': [('social.json', '/auction/')],
    'boxes': [('npc.json', '/bonus_box'), ('boxes.json', '/boxes/')],
    'gates': [('gates.json', '/gates/')],
    'events': [('events.json', '/events/')],
    'economy': [('levels.json', '/levels'), ('ranks.json', '/')],
}
PATHS = [(d, re.compile(r)) for d, r in (
    ('npc.json', r'^/types/[^/]+$'), ('npc.json', r'^/maps/[^/]+/(npc|bonus_boxes)$'), ('map_layout.json', r'^/maps/[^/]+$'),
    ('quests.json', r'^/quests/\d+$'), ('quest_extras.json', r'^/quests/\d+$'), ('shop', r'^/products/[^/]+$'),
    ('social.json', r'^/auction/lots$'), ('npc.json', r'^/bonus_(boxes|box_4x)$'), ('boxes.json', r'^/boxes/[^/]+$'),
    ('gates.json', r'^/gates/[^/]+$'), ('events.json', r'^/events/[^/]+$'),
    ('levels.json', r'^/levels$'), ('ranks.json', r'^/(formula|thresholds)$'), ('items.json', r'^/ores/maps/[^/]+$'), ('items.json', r'^/ores/respawn_sec$'))]
GATE_REWARD = ('ep', 'honor', 'uridium', 'xenomit', 'log_disk', 'voucher')           # the edited numbers of a gate reward
GATE_ALIEN = ('count', 'hp', 'shield', 'damage', 'speed')                       # the edited values of a wave alien
PACKAGE = 'package'                                                             # loot.PACKAGE: a row with several items in a box reward
NPC_NUMBERS = ('hp', 'shield', 'damage', 'speed')
REWARD = ('ep', 'honor', 'credits', 'uridium')
# quest condition types (quest.py, quest_tracker.py): what the editor understands -> the meaning of the match
CONDITION = {6: 'npc', 27: 'npc', 34: 'map', 67: 'item', 51: 'none', 55: 'none', 52: 'ore', 28: 'none', 53: 'none', 62: 'none',
         35: 'none', 42: 'none', 2: 'duration', 3: 'duration', 63: 'duration', 13: 'none', 12: 'none', 7: 'none', 9: 'none', 80: 'gate'}
SUB_MAP = 77
QUEST_TEMPLATES = {          # a new quest's goal type -> (condition type, display, match)
    'hunt': (6, 6), 'collect': (67, 67), 'exploring': (34, 34), 'sell': (52, 52), 'box': (55, 55), 'cargo': (51, 51),
}
_LOCK = threading.Lock()


class WorldError(ValueError):
    """Error shown to the user (panel.py returns 400)."""


def folder():
    return os.path.join(PTH.SAVE, 'worlds')


def _route(did):
    if did == STANDARD:
        return os.path.join(folder(), '_draft.json')
    if not isinstance(did, str) or not re.fullmatch(r'[a-z0-9_]{1,40}', did):
        raise WorldError(_('World not found.'))
    return os.path.join(folder(), did + '.json')


def _read_file(p):
    try:
        with open(p, encoding='utf8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write_file(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def var(did):
    return did == STANDARD or (isinstance(did, str) and re.fullmatch(r'[a-z0-9_]{1,40}', did) and os.path.isfile(_route(did)))


def read(did):
    """The world (standard: with the draft's patches). DunyaHatasi if missing."""
    if did == STANDARD:
        d = _read_file(_route(did)) or {}
        return {'id': STANDARD, 'name': _('Standard world'), 'description': _("The game's own content. It can't be edited: save your changes as a new world."),
                'cover': 'standard', 'standard': True, 'patches': d.get('patches') or {}}
    d = _read_file(_route(did))
    if d is None:
        raise WorldError(_('World not found.'))
    d.setdefault('patches', {})
    d['id'] = did
    return d


def _save(did, d):
    d = {k: v for k, v in d.items() if k not in ('id', 'standard')}
    if did != STANDARD:
        d['update'] = _now()
    d['version'] = VERSION
    _write_file(_route(did), d)


def file_path(did):
    """The world file to give the server (OO_WORLD); None for the standard or a non-existent world."""
    return _route(did) if did and did != STANDARD and var(did) else None


def counts(patches):
    """Number of changes per section."""
    out = {b: 0 for b in SECTIONS}
    for file, patch_count in (patches or {}).items():
        for y in patch_count or {}:
            b = section_of(file, y)
            if b:
                out[b] += 1
    return out


def section_of(file, route):
    return next((b for b, ps in SECTIONS.items() for d, p in ps if d == file and route.startswith(p)), None)


def summary(did, users=None):
    d = read(did)
    n = counts(d['patches'])
    return {'id': did, 'name': d.get('name') or did, 'description': d.get('description', ''), 'cover': d.get('cover') if d.get('cover') in COVERS else 'nebula',
            'standard': did == STANDARD, 'created': d.get('created'), 'update': d.get('update'),
            'changes': sum(n.values()), 'sections': n, 'users': (users or {}).get(did, [])}


def entries(users=None):
    """The standard world first, then custom worlds (most recently updated first)."""
    out = []
    if os.path.isdir(folder()):
        for f in os.listdir(folder()):
            did = f[:-5] if f.endswith('.json') else None
            if did and not did.startswith('_') and re.fullmatch(r'[a-z0-9_]{1,40}', did):
                try:
                    out.append(summary(did, users))
                except WorldError:
                    pass
    out.sort(key=lambda w: w['update'] or '', reverse=True)
    return [summary(STANDARD, users)] + out


def _clean_name(name):
    name = ' '.join(str(name or '').split())[:NAME_LENGTH]
    if not name:
        raise WorldError(_('Give the world a name.'))
    return name


def _new_id(name):
    tr = str.maketrans('çğıöşüâîûÇĞİÖŞÜ', 'cgiosuaiuCGIOSU')
    k = re.sub(r'[^a-z0-9]+', '_', name.translate(tr).lower()).strip('_')[:30] or 'world'
    if k == STANDARD:
        k = 'world'
    did, n = k, 2
    while os.path.exists(_route(did)):
        did, n = '%s_%d' % (k, n), n + 1
    return did


def create(name, description='', cover='nebula', source=None, from_draft=False):
    """New world: empty (standard), a copy of the source world, or from the standard world's draft (the draft is deleted afterwards)."""
    with _LOCK:
        name = _clean_name(name)
        patches = {}
        if from_draft:
            patches = read(STANDARD)['patches']
        elif source and source != STANDARD:
            patches = copy.deepcopy(read(source)['patches'])
        did = _new_id(name)
        _save(did, {'name': name, 'description': str(description or '')[:DESCRIPTION_LENGTH], 'cover': cover if cover in COVERS[1:] else 'nebula',
                      'created': _now(), 'patches': patches})
        if from_draft:
            discard_draft()
        return did


def update(did, name=None, description=None, cover=None):
    if did == STANDARD:
        raise WorldError(_("The standard world can't be changed."))
    with _LOCK:
        d = read(did)
        if name is not None:
            d['name'] = _clean_name(name)
        if description is not None:
            d['description'] = str(description)[:DESCRIPTION_LENGTH]
        if cover is not None and cover in COVERS[1:]:
            d['cover'] = cover
        _save(did, d)


def remove(did):
    if did == STANDARD:
        raise WorldError(_("The standard world can't be deleted."))
    p = _route(did)
    if not os.path.isfile(p):
        raise WorldError(_('World not found.'))
    os.makedirs(os.path.join(folder(), '_trash'), exist_ok=True)
    os.replace(p, os.path.join(folder(), '_trash', '%s_%s.json' % (did, datetime.datetime.now().strftime('%Y%m%d%H%M%S'))))


def duplicate(did, name=None):
    d = read(did)
    return create(name or _('{0} (copy)').format(d.get('name') or did)[:NAME_LENGTH], d.get('description', ''), d.get('cover', 'nebula'),
                   source=did if did != STANDARD else None, from_draft=False) if did != STANDARD else \
        create(name or _('New world'), '', 'nebula')


CODE_PREFIX = 'OODUNYA1:'


def data_signature(files):
    """Summary of the standard data files (which game data a shared world was prepared with): {file: first 12 of the sha1}."""
    out = {}
    for f in files:
        p = os.path.join(DATA.DATA, f)
        if f not in DATA.VIRTUAL and os.path.isfile(p):
            with open(p, 'rb') as fh:
                out[f] = hashlib.sha1(fh.read()).hexdigest()[:12]
    return out


def export(did):
    """The world to share: name, description, cover, patches; the data it was prepared with (data_signature) and section counts (warning on import)."""
    d = read(did)
    return {'openorbit_world': VERSION, 'name': d.get('name'), 'description': d.get('description', ''), 'cover': d.get('cover', 'nebula'),
            'date': _now(), 'data': data_signature(d['patches']), 'sections': counts(d['patches']), 'patches': d['patches']}


def code(did):
    """Share code: OODUNYA1: + base64(zlib(world)); pasted to Discord or chat."""
    raw_ = json.dumps(export(did), ensure_ascii=False, separators=(',', ':')).encode('utf8')
    return CODE_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw_, 9)).decode('ascii')


def from_code(text):
    text = ''.join(str(text or '').split())
    if not text.startswith(CODE_PREFIX):
        raise WorldError(_('This is not an OpenOrbit world code.'))
    try:
        return json.loads(zlib.decompress(base64.urlsafe_b64decode(text[len(CODE_PREFIX):] + '=' * (-len(text) % 4))).decode('utf8'))
    except (ValueError, zlib.error):
        raise WorldError(_('The world code is corrupt or was copied incompletely.'))


def import_(data):
    """Adds the shared world as a new world -> (id, report). Disallowed paths are skipped, every value passes through the editor's filter
    (corrupt ones are skipped); the report says if the world was prepared with other game data."""
    if isinstance(data, dict):
        data = SM.migrate_world(data)                 # a world shared in an old version: data file names and paths to the new names
    if not isinstance(data, dict) or 'patches' not in data or not isinstance(data['patches'], dict):
        raise WorldError(_('This file is not an OpenOrbit world.'))
    if int(data.get('openorbit_world') or 1) > VERSION:
        raise WorldError(_('This world was prepared with a newer version of the panel: update the panel first.'))
    cleared, skipped = {}, 0
    for file, patch_count in data['patches'].items():
        for y, v in (patch_count or {}).items() if isinstance(patch_count, dict) else ():
            if allowed(file, y):
                cleared.setdefault(file, {})[y] = v
            else:
                skipped += 1
    did = create(data.get('name') or _('Imported world'), data.get('description', ''), data.get('cover', 'nebula'))
    issues = []
    with _LOCK:
        d = read(did)
        d['patches'] = cleared
        _save(did, d)                          # as they are first, so the filter sees the world's own types (ozel_*)
        order = sorted(((f, y) for f, patch_count in cleared.items() for y in patch_count), key=lambda x: (x[0] != 'npc.json' or not x[1].startswith('/types/'), x))
        for f, y in order:
            try:
                cleared[f][y] = clean_up(did, f, y, cleared[f][y])
            except (WorldError, KeyError, IndexError, TypeError, ValueError, AttributeError, ArithmeticError) as e:
                del cleared[f][y]
                issues.append('%s %s: %s' % (f, y, e))
        d['patches'] = {f: patch_count for f, patch_count in cleared.items() if patch_count}
        _save(did, d)
    now = data_signature(data.get('data') or {})
    differs = sorted(f for f, h in (data.get('data') or {}).items() if now.get(f) != h)
    return did, {'changes': sum(len(v) for v in d['patches'].values()), 'skipped': skipped + len(issues), 'issues': issues[:12],
                 'data_differs': differs, 'date': data.get('date')}


def discard_draft():
    p = _route(STANDARD)
    if os.path.isfile(p):
        os.remove(p)


# ------------------------------------------------------------------ yamalar
def allowed(file, route):
    return any(d == file and r.match(route) for d, r in PATHS)


def patch(did, file, route, value):
    """A change to the world (to the draft on standard): a full value. If equal to the standard value the patch is removed."""
    if not allowed(file, route):
        raise WorldError(_("This content can't be edited."))
    value = clean_up(did, file, route, value)
    with _LOCK:
        d = read(did)
        patch_count = d['patches'].setdefault(file, {})
        if value == default_value(file, route):
            patch_count.pop(route, None)
        else:
            patch_count[route] = value
        if not patch_count:
            d['patches'].pop(file, None)
        _save(did, d)


def revert(did, file=None, route=None, section=None):
    """Reverts one change (file + path) or all of a section's changes to standard."""
    with _LOCK:
        d = read(did)
        for f in list(d['patches']):
            for y in list(d['patches'][f] or {}):
                if (section and section_of(f, y) == section) or (f == file and y == route):
                    del d['patches'][f][y]
            if not d['patches'][f]:
                del d['patches'][f]
        _save(did, d)


_RAW = {}


def raw(file):
    """Standard data (cached)."""
    if file not in _RAW:
        _RAW[file] = DATA.raw(file)
    return _RAW[file]


def _get(data, route):
    for p in DATA.path_parts(route):
        if isinstance(data, list):
            data = data[int(p)]
        elif isinstance(data, dict) and p in data:
            data = data[p]
        else:
            return None
    return data


def default_value(file, route):
    return _get(raw(file), route)


def world_data(did, file):
    """The file's state in the world (standard + patches; a copy)."""
    v = copy.deepcopy(raw(file))
    DATA.apply(v, read(did)['patches'].get(file) or {}, file)
    return v


def _int(v, sub=0, parent=10 ** 9):
    try:
        return max(sub, min(parent, int(round(float(v)))))
    except (TypeError, ValueError, OverflowError):      # 1e999 / Infinity (imported world code)
        raise WorldError(_('A number was expected.'))


def clean_up(did, file, route, v):
    """Brings the value to the form the game will read; a value that does not fit raises DunyaHatasi."""
    part = DATA.path_parts(route)
    if isinstance(v, dict) and v.get(DATA.DELETE):
        if file == 'npc.json' and part[0] == 'types' and not part[1].startswith(NEW_ALIEN):
            raise WorldError(_("The game's own aliens can't be deleted; you can remove them from spawn lists."))
        if file in ('quests.json', 'quest_extras.json') and int(part[1]) < NEW_QUEST:
            raise WorldError(_("The game's own quests can't be deleted; you can switch them off."))
        return {DATA.DELETE: True}
    if file == 'npc.json' and part[0] == 'types':
        if not isinstance(v, dict):
            raise WorldError(_('Alien data is corrupt.'))
        v = dict(v)
        v['name'] = ' '.join(str(v.get('name') or '').split())[:60] or '?'
        for k in NPC_NUMBERS:
            v[k] = _int(v.get(k, 0), 0, 50_000_000 if k in ('hp', 'shield') else 1_000_000 if k == 'damage' else 2000)
        v['aggressive'] = bool(v.get('aggressive'))
        v['reward'] = {k: _int((v.get('reward') or {}).get(k, 0), 0, 10 ** 9) for k in REWARD}
        v['cargo'] = {str(_int(k, 0, 99)): _int(n, 0, 100_000) for k, n in (v.get('cargo') or {}).items() if _int(n, 0, 100_000) > 0}
        if part[1].startswith(NEW_ALIEN) and not v.get('model'):
            raise WorldError(_('The new alien needs a model.'))
        return v
    if file == 'npc.json' and part[0] == 'maps':
        types = world_data(did, 'npc.json')['types']
        if len(part) == 3 and part[2] == 'bonus_boxes':
            return _int(v, 0, 300)
        if len(part) == 3 and part[2] == 'npc':
            if not isinstance(v, list):
                raise WorldError(_('The spawn list is corrupt.'))
            out = []
            for g in v:
                tip = str(g.get('tip'))
                if tip not in types:
                    continue
                e = {'tip': tip, 'count': _int(g.get('count', 1), 0, COUNT_MAX)}
                b = g.get('region')
                if isinstance(b, list) and len(b) == 3:
                    e['region'] = [_int(b[0], 0, 42000), _int(b[1], 0, 26200), _int(b[2], 200, 15000)]
                out.append(e)
            return out
        raise WorldError(_("This content can't be edited."))
    if file == 'map_layout.json':
        if not isinstance(v, dict):
            raise WorldError(_('The map layout is corrupt.'))
        v = copy.deepcopy(v)
        if 'safe' in v:
            v['safe'] = [[_int(a, 0, 42000), _int(b, 0, 26200), _int(r, 100, 6000)] for a, b, r in v['safe']]
        if 'lairs' in v:
            v['lairs'] = {str(t): [[_int(a, 0, 42000), _int(b, 0, 26200)] for a, b in pts] for t, pts in v['lairs'].items() if pts}
        if 'portals' in v:
            v['portals'] = {str(k): [_int(p[0], 0, 42000), _int(p[1], 0, 26200)] for k, p in v['portals'].items()}
        return v
    if file in ('quests.json', 'quest_extras.json'):
        if not isinstance(v, dict) or 'root' not in v:
            raise WorldError(_('Quest data is corrupt.'))
        v = copy.deepcopy(v)
        v['level'] = _int(v.get('level', 1), 0, 40)
        v['rewards'] = [[str(l), _int(n, 1, 10 ** 9)] for l, n in v.get('rewards', []) if str(l)]
        v['previous'] = [_int(x, 0) for x in v.get('previous', [])]
        for k, n in (('title', 80), ('description', 600)):          # text shown in the game (the plugin's QuestTexts patch)
            t = ' '.join(str(v.get(k) or '').split()) if k == 'title' else str(v.get(k) or '').strip()
            if t:
                v[k] = t[:n]
            else:
                v.pop(k, None)
        return v
    if file == 'shop':
        if not isinstance(v, dict):
            raise WorldError(_('Product data is corrupt.'))
        out = {}
        if v.get('price') is not None:
            out['price'] = _int(v['price'], 0, 10 ** 10)
            out['currency'] = 'C' if v.get('currency') == 'C' else 'U'
        if v.get('on_sale') is False:
            out['on_sale'] = False
        return out
    if file == 'npc.json' and part[0] in ('bonus_boxes', 'bonus_box_4x'):
        out = [[str(l), _int(n, 1, 10 ** 7)] for l, n in (v if isinstance(v, list) else []) if str(l)]
        if not out:
            raise WorldError(_('A bonus box needs at least one reward.'))
        return out
    if file == 'boxes.json':
        return _clean_box(part[1], v)
    if file == 'gates.json':
        return _clean_gate(part[1], v, world_data(did, 'npc.json')['types'])
    if file == 'levels.json':
        base = raw('levels.json')['levels']
        ep = [_int(x[1] if isinstance(x, list) else x, 0, 10 ** 20) for x in (v if isinstance(v, list) else [])]
        # the browser rounds numbers above 2^53 (last levels ~10^18): a value within the rounding margin is the standard
        ep = [b[1] if abs(n - b[1]) <= b[1] * 1e-12 else n for n, b in zip(ep, base)]
        if len(ep) != len(base) or ep[0] != 0 or any(b <= a for a, b in zip(ep, ep[1:])):
            raise WorldError(_('Level thresholds must start at zero and increase.'))
        return [[lv, n] for (lv, _), n in zip(base, ep)]
    if file == 'ranks.json' and part[0] == 'thresholds':
        base = raw('ranks.json')['thresholds']
        n = [_int(x, 0, 10 ** 12) for x in (v if isinstance(v, list) else [])]
        if len(n) != len(base) or n[0] != 0 or any(b <= a for a, b in zip(n, n[1:])):
            raise WorldError(_('Rank thresholds must start at zero and increase.'))
        return n
    if file == 'ranks.json' and part[0] == 'formula':
        base = raw('ranks.json')['formula']
        try:
            return {k: max(-10 ** 6, min(10 ** 6, float(v.get(k, d)))) for k, d in base.items()}
        except (AttributeError, TypeError, ValueError):
            raise WorldError(_('A number was expected.'))
    if file == 'events.json':
        return _clean_event(part[1], v, world_data(did, 'npc.json')['types'])
    if file == 'items.json':
        if part[-1] == 'respawn_sec':
            lo, hi = sorted(_int(x, 1, 86400) for x in (v if isinstance(v, list) and len(v) == 2 else [15, 30]))
            return [lo, hi]
        kinds = raw('items.json')['ores']['kinds']
        out = {str(t): _int(n, 0, 1000) for t, n in (v or {}).items() if str(t) in kinds}
        return out or {'0': 0}                   # all 0: no ore on the map (an empty dictionary would fall back to the class's value)
    if file == 'social.json':
        if not isinstance(v, list):
            raise WorldError(_('The lot list is corrupt.'))
        out = []
        for l in v:
            loot, kind = str(l[0]), l[2] if l[2] in ('hour', 'day', 'week') else 'hour'
            out.append([loot, str(l[1] or 'other'), kind, _int(l[3], 1, 10 ** 7), bool(l[4]), _int(l[5], 0, 10 ** 9)])
        seen = set()
        return [l for l in out if (l[2], l[0]) not in seen and not seen.add((l[2], l[0]))]      # the lot key (type, item) is unique
    return v


def _clean_box(kind, v):
    """Keyed box: count on the maps, respawn, map classes and reward table (row: [item, amount | [min, max],
    weight]; a package row as it is). The other fields (key, calendar, messages) from the standard."""
    base = raw('boxes.json')['boxes'].get(kind)
    if base is None or not isinstance(v, dict):
        raise WorldError(_('Box not found.'))
    out = copy.deepcopy(base)
    classes = raw('boxes.json')['maps']
    if 'count' in v:
        out['count'] = _int(v['count'], 0, 100)
    if 'renew_sec' in v and isinstance(v['renew_sec'], list) and len(v['renew_sec']) == 2:
        out['renew_sec'] = sorted(_int(x, 10, 86400) for x in v['renew_sec'])
    if 'maps' in v:
        out['maps'] = [m for m in v['maps'] if m in classes]
    if 'reward' in v and base.get('reward'):
        rows = []
        for r in v['reward'] if isinstance(v['reward'], list) else []:
            if not isinstance(r, list) or len(r) != 3:
                continue
            w = max(0.0, min(1e6, float(r[2] or 0)))
            if w <= 0:
                continue
            if r[0] == PACKAGE:
                if any(b[0] == PACKAGE and b[1] == r[1] for b in base['reward']):
                    rows.append([PACKAGE, r[1], w])
                continue
            n = sorted(_int(x, 1, 10 ** 7) for x in r[1]) if isinstance(r[1], list) and len(r[1]) == 2 else _int(r[1], 1, 10 ** 7)
            rows.append([str(r[0]), n, w])
        if not rows:
            raise WorldError(_('A box needs at least one reward.'))
        out['reward'] = rows
    return out


def _groups(groups, i, old, new_):
    """Scales alien i's counts in the wave's subgroups proportionally from old to new (each row at least 1; total new)."""
    place = [(g, k) for g, grp in enumerate(groups) for k, (j, n) in enumerate(grp) if j == i]
    if not place or old <= 0:
        return
    new_ = max(new_, len(place))
    pay = [max(1, round(groups[g][k][1] * new_ / old)) for g, k in place]
    diff = new_ - sum(pay)
    order = sorted(range(len(pay)), key=lambda x: -pay[x])
    while diff:
        for x in order:
            if diff > 0:
                pay[x] += 1
                diff -= 1
            elif diff < 0 and pay[x] > 1:
                pay[x] -= 1
                diff += 1
            if not diff:
                break
    for (g, k), n in zip(place, pay):
        groups[g][k] = [i, n]


def _clean_gate(key, v, types=None):
    """Galaxy Gate: part, HP, reward counts, ammo reward, probability and amount of lucky rewards, the waves' alien values
    (when a count changes the subgroups scale proportionally). The wave and alien list structure from the standard (galaxy_gates.py's counters depend on it)."""
    base = raw('gates.json')['gates'].get(key)
    if base is None or not isinstance(v, dict):
        raise WorldError(_('Gate not found.'))
    out = copy.deepcopy(base)
    for k in ('part', 'hp'):
        if k in v:
            out[k] = _int(v[k], 1, 10000)
    o, value_reward = out['reward'], v.get('reward') or {}
    for k in GATE_REWARD:
        if k in value_reward and k in o:
            o[k] = _int(value_reward[k], 0, 10 ** 10)
    if isinstance(value_reward.get('ammunition'), dict):
        o['ammunition'] = {str(l): _int(n, 1, 10 ** 8) for l, n in value_reward['ammunition'].items() if str(l)}
    for i, x in enumerate(value_reward.get('chance') or []):
        if i < len(o.get('chance', [])) and isinstance(x, dict):
            if 'probability' in x:
                o['chance'][i]['probability'] = max(0.0, min(1.0, float(x['probability'])))
            if 'count' in x and isinstance(o['chance'][i].get('count'), int):
                o['chance'][i]['count'] = _int(x['count'], 1, 10 ** 7)
    for n, value_wave in enumerate(v.get('waves') or []):
        if n >= len(out['waves']) or not isinstance(value_wave, dict):
            continue
        w = out['waves'][n]
        for i, va in enumerate(value_wave.get('alien_spawns') or []):
            if i >= len(w['alien_spawns']) or not isinstance(va, dict):
                continue
            a = w['alien_spawns'][i]
            kind = str(va.get('type') or a['type'])
            # only keys that are a client ship type (galaxy_gates.register_npcs sends the type as the model: no "custom_1", "event_...")
            if kind != a['type'] and not a.get('permanent') and a['type'] != 'player' and kind.isdigit() and kind in (types or {}):
                t = types[kind]                          # replace the alien with another type: the type's values, the count and place in the wave stay the same
                a.update(type=kind, name=re.sub(r'^[-=\[\]:.{}\s]+|[-=\[\]:.{}\s]+$', '', t['name']) or kind, display_name=t['name'],
                         npc_id=t.get('npc_id', a.get('npc_id')), hp=t['hp'], shield=t['shield'], damage=t['damage'], speed=t['speed'],
                         reward=dict(t.get('reward') or {}), cargo=dict(t.get('cargo') or {}))
                a.pop('behavior', None)
            for k in GATE_ALIEN:
                if k not in va:
                    continue
                new_ = _int(va[k], 1 if k == 'count' else 0, 50_000_000)
                if k == 'count':
                    old = sum(c for grp in w['groups'] for j, c in grp if j == i)
                    _groups(w['groups'], i, old, new_)
                    new_ = sum(c for grp in w['groups'] for j, c in grp if j == i) or new_
                a[k] = new_
            if isinstance(va.get('reward'), dict):
                a['reward'] = {k: _int(va['reward'].get(k, a['reward'].get(k, 0)), 0, 10 ** 9) for k in REWARD}
    return out


MAP_CLASSES = tuple('X-%d' % n for n in range(1, 9))      # map classes of the map events


def _date(x):
    """Period end: 'YYYY-MM-DD' or every year 'MM-DD' (event_calendar._spans)."""
    x = str(x or '').strip()
    for style in ('%Y-%m-%d', '%m-%d'):
        try:
            datetime.datetime.strptime(x if style == '%Y-%m-%d' else '2024-' + x, '%Y-%m-%d')
            return x
        except ValueError:
            pass
    raise WorldError(_('Invalid date: %s', x))


def event_classes(h, types):
    """The selectable classes of a map event: those whose aliens and boss have a type specific to that class (etk_<name>_x<n>)."""
    kinds = [a['type'] for a in h.get('alien_spawns', [])] + list((h.get('boss') or {}).get('kinds', []))
    return [m for m in MAP_CLASSES if all(t.replace('{x}', 'x' + m[2:]) in types for t in kinds)]


def _clean_event(key, v, types):
    """Event: the state in the world (world_status: on | off | else the calendar), periods ([start, end] + the standard row's tail: hours,
    'tek'), the map section (maps, alien counts, map quotas, boss count and duration). The other fields from the standard."""
    base = raw('events.json')['events'].get(key)
    if base is None or not isinstance(v, dict):
        raise WorldError(_('Event not found.'))
    out = copy.deepcopy(base)
    if v.get('world_status') in ('on', 'off'):
        out['world_status'] = v['world_status']
    if isinstance(v.get('periods'), list) and 'periods' in base:
        queue = {(r[0], r[1]): r[2:] for r in base['periods']}
        rows = []
        for r in v['periods']:
            if isinstance(r, list) and len(r) >= 2:
                a, b = _date(r[0]), _date(r[1])
                if len(a) != len(b):
                    raise WorldError(_('Both ends of the period must use the same format (with a year or every year).'))
                rows.append([a, b] + list(queue.get((r[0], r[1]), [])))
        out['periods'] = rows
    h, value_map = out.get('map'), v.get('map')
    if h and isinstance(value_map, dict):
        if isinstance(value_map.get('maps'), list):
            permission = event_classes(h, types)          # those other than X-n (Sunburst's 4-X) as they are
            h['maps'] = [m for m in MAP_CLASSES if m in value_map['maps'] and m in permission] + [m for m in h['maps'] if m not in MAP_CLASSES]
        for i, a in enumerate(value_map.get('alien_spawns') or []):
            if i < len(h.get('alien_spawns', [])) and isinstance(a, dict) and 'count' in a:
                h['alien_spawns'][i]['count'] = _int(a['count'], 0, 200)
        if isinstance(value_map.get('quota'), dict) and 'quota' in h:
            h['quota'] = dict({m: n for m, n in h['quota'].items() if m not in MAP_CLASSES},
                             **{m: _int(value_map['quota'].get(m, h['quota'].get(m, max(h['quota'].values(), default=20))), 0, 10000)
                                for m in MAP_CLASSES if m in h['maps']})
        if isinstance(value_map.get('boss'), dict) and h.get('boss'):
            for k, parent in (('count', 50), ('duration_sec', 86400)):
                if k in value_map['boss']:
                    h['boss'][k] = _int(value_map['boss'][k], 0 if k == 'count' else 60, parent)
    return out


# ------------------------------------------------------------------ sections
def _server():
    """The server's map and shop modules (the panel does not load them at first start: only when the World Editor opens)."""
    import map_links as H
    return H


def npc_icon(tip, t):
    m = str(t.get('model') or tip)
    return 'npc_%s_icon' % m if m.isdigit() else None


def _kinds(x):
    """Alien types in behaviors ('type' fields of spawn_on_death, summon_on_hit ...)."""
    if isinstance(x, dict):
        return ([x['type']] if isinstance(x.get('type'), str) else []) + [t for v in x.values() for t in _kinds(v)]
    return [t for v in x for t in _kinds(v)] if isinstance(x, list) else []


def aliens(did):
    w = read(did)
    npc = world_data(did, 'npc.json')
    base = raw('npc.json')['types']
    import alien as U
    used_in = {}
    for mid, m in npc['maps'].items():
        for g in m.get('npc', []) + m.get('scheduled', []):          # zamanli: timed Black Light strays
            if map_name(mid) not in used_in.get(g['tip'], []):
                used_in.setdefault(g['tip'], []).append(map_name(mid))
    order = list(used_in)                 # those spawned on death and those summoned (Blighted Gygerthrall, Lordakium spore) on their ancestor's maps
    for tip in order:
        for sub in _kinds(U.of(npc['types'].get(tip, {}))):
            if sub in npc['types']:
                missing = [x for x in used_in[tip] if x not in used_in.get(sub, [])]
                if missing:
                    used_in.setdefault(sub, []).extend(missing)
                    order.append(sub)
    patch_count = w['patches'].get('npc.json') or {}
    out = []
    for tip, t in npc['types'].items():
        out.append({'tip': tip, 'name': t['name'], 'hp': t['hp'], 'shield': t['shield'], 'damage': t['damage'], 'speed': t['speed'],
                    'aggressive': t['aggressive'], 'reward': t.get('reward') or {}, 'cargo': t.get('cargo') or {}, 'icon': npc_icon(tip, t),
                    'model': t.get('model'), 'npc_id': t.get('npc_id'), 'event': bool(t.get('event')) or tip.startswith('event_'), 'used_in': used_in.get(tip, []),
                    'changed': DATA.build_path('types', tip) in patch_count, 'new': tip not in base,
                    'standard': {k: base[tip].get(k) for k in ('name', 'hp', 'shield', 'damage', 'speed', 'aggressive', 'reward', 'cargo')} if tip in base else None,
                    'full': t})
    return out


def map_name(mid):
    H = _server()
    return H.NAMES.get(int(mid)) or str(mid)


def _company(name):
    return {'1': 'mmo', '2': 'eic', '3': 'vru'}.get(name[0]) if re.match(r'^\d-\d$', name) and name[0] in '123' else \
        'bl' if name.startswith('BL') else 'pirate' if name.startswith('5-') else 'combat' if name.startswith('4-') else 'other'


def maps(did):
    w = read(did)
    npc = world_data(did, 'npc.json')
    patch_count = set((w['patches'].get('npc.json') or {})) | set('~' + y for y in (w['patches'].get('map_layout.json') or {}))
    ores = set(w['patches'].get('items.json') or {})
    out = []
    for mid, m in npc['maps'].items():
        name = map_name(mid)
        changed = any(y in patch_count for y in (DATA.build_path('maps', mid, 'npc'), DATA.build_path('maps', mid, 'bonus_boxes'),
                                       '~' + DATA.build_path('maps', mid))) or DATA.build_path('ores', 'maps', name) in ores
        out.append({'id': mid, 'name': name, 'company': _company(name), 'alien': sum(g['count'] for g in m.get('npc', [])),
                    'type': len(m.get('npc', [])), 'bonus_boxes': m.get('bonus_boxes', 0), 'changed': changed})
    order = lambda x: ({'mmo': 0, 'eic': 1, 'vru': 2, 'combat': 3, 'pirate': 4, 'bl': 5}.get(x['company'], 6), x['name'])
    return sorted(out, key=order)


def game_map(did, mid):
    """The map editor's canvas: size, spawn list, portals, station, layout (safe zones, lairs, obstacles)."""
    H = _server()
    mid = str(mid)
    npc = world_data(did, 'npc.json')
    if mid not in npc['maps']:
        raise WorldError(_('Map not found.'))
    m = npc['maps'][mid]
    layout = world_data(did, 'map_layout.json')['maps'].get(mid) or {}
    layout0 = raw('map_layout.json')['maps'].get(mid) or {}
    w, h = H.map_size(int(mid)) if hasattr(H, 'map_size') else (H.MAP_W, H.MAP_H)
    portals = []
    for g in H.GATES.get(int(mid), []):
        p = (layout.get('portals') or {}).get(str(g['key']))
        portals.append({'key': g['key'], 'x': p[0] if p else g['x'], 'y': p[1] if p else g['y'], 'target': map_name(g['target']),
                          'company': g.get('only_company'), 'moved': bool(p) and p != (layout0.get('portals') or {}).get(str(g['key']))})
    ist = None
    if int(mid) in H.STATION_MAPS:
        gs = H.GATES.get(int(mid), [])
        ist = list(H.STATION_POS.get(int(mid)) or max(H.CORNERS, key=lambda c: min((((c[0] - g['x']) ** 2 + (c[1] - g['y']) ** 2) ** .5 for g in gs), default=0)))
    types = npc['types']
    base = raw('npc.json')['maps'].get(mid) or {}
    return {'id': mid, 'name': map_name(mid), 'company': _company(map_name(mid)), 'size': [w, h],
            'npc': [dict(g, name=types.get(g['tip'], {}).get('name', g['tip']), icon=npc_icon(g['tip'], types.get(g['tip'], {})),
                         aggressive=types.get(g['tip'], {}).get('aggressive', False)) for g in m.get('npc', [])],
            'bonus_boxes': m.get('bonus_boxes', 0), 'portals': portals, 'station': ist, 'structure': layout.get('structure'),
            'safe': layout.get('safe', []), 'lairs': layout.get('lairs', {}), 'obstacles': [e[1:5] for e in layout.get('obstacles', [])],
            'layout': layout, 'standard': {'npc': base.get('npc', []), 'bonus_boxes': base.get('bonus_boxes', 0), 'layout': layout0},
            'changed': {'npc': m.get('npc', []) != base.get('npc', []), 'bonus_boxes': m.get('bonus_boxes', 0) != base.get('bonus_boxes', 0),
                        'layout': layout != layout0},
            'ore': ores(did, mid)}


# ---- quests
def _quest_file(qid):
    return 'quests.json' if str(qid) in raw('quests.json')['quests'] else 'quest_extras.json'


def _all_quests(did):
    a = world_data(did, 'quests.json')['quests']
    b = world_data(did, 'quest_extras.json')['quests']
    return {**{k: ('quests.json', v) for k, v in a.items()}, **{k: ('quest_extras.json', v) for k, v in b.items()}}


def conditions(root):
    """The quest's conditions (the tree's leaves, in order): [{id, type, display, matches, target, sub: [{type, matches}]}]."""
    out = []

    def walk(case):
        for el in case.get('modifier', []):
            c = el.get('condition') or {}
            if c.get('id'):
                out.append({'id': c['id'], 'type': c['type'], 'display': c.get('displayType', c['type']), 'matches': list(c.get('matches', [])),
                            'target': c.get('targetValue', 0), 'sub': [{'type': s['type'], 'matches': list(s.get('matches', []))}
                                                                     for s in c.get('subConditions', [])]})
            q = el.get('questCase') or {}
            if q.get('id'):
                walk(q)
    walk(root)
    return out


def _quest_summary(qid, q, file, patch_count, root_count=None):
    k = conditions(q['root'])
    return {'id': int(qid), 'name': q.get('name', str(qid)), 'level': q.get('level', 1), 'kinds': q.get('kinds', []),
            'source': 'main' if file == 'quests.json' else 'extra', 'conditions': [{'type': c['type'], 'target': c['target'], 'matches': c['matches'][:3]} for c in k],
            'rewards': q.get('rewards', []), 'off': bool(q.get('off')), 'new': int(qid) >= NEW_QUEST,
            'changed': DATA.build_path('quests', qid) in patch_count, 'event': bool(q.get('event')), 'pool': bool(q.get('pool'))}


def quests(did):
    w = read(did)
    patch_count = set(w['patches'].get('quests.json') or {}) | set(w['patches'].get('quest_extras.json') or {})
    return sorted((_quest_summary(qid, q, file, patch_count) for qid, (file, q) in _all_quests(did).items()), key=lambda g: (g['level'], g['id']))


def quest(did, qid):
    all_ = _all_quests(did)
    if str(qid) not in all_:
        raise WorldError(_('Quest not found.'))
    file, q = all_[str(qid)]
    base = raw(file)['quests'].get(str(qid))
    w = read(did)
    patch_count = set(w['patches'].get(file) or {})
    o = _quest_summary(qid, q, file, patch_count)
    o.update(previous=q.get('previous', []), conditions=conditions(q['root']), duration_sec=q.get('duration_sec'), title=q.get('title', ''), description=q.get('description', ''),
             standard={'level': base['level'], 'rewards': base.get('rewards', []), 'previous': base.get('previous', []),
                       'conditions': conditions(base['root'])} if base else None,
             names={str(x): all_[str(x)][1].get('name', str(x)) for x in q.get('previous', []) if str(x) in all_})
    return o


def save_quest(did, qid, changes):
    """The quest's editable fields: level, prerequisites, rewards, the conditions' target and match, closed, name (new quest only)."""
    all_ = _all_quests(did)
    if str(qid) not in all_:
        raise WorldError(_('Quest not found.'))
    file, q = all_[str(qid)]
    q = copy.deepcopy(q)
    d = changes or {}
    if 'level' in d:
        q['level'] = d['level']
    if 'previous' in d:
        q['previous'] = [int(x) for x in d['previous'] if str(x) in all_ and int(x) != int(qid)]
    if 'rewards' in d:
        q['rewards'] = d['rewards']
    if 'off' in d:
        if d['off']:
            q['off'] = True
        else:
            q.pop('off', None)
    if 'name' in d and int(qid) >= NEW_QUEST:
        q['name'] = ' '.join(str(d['name']).split())[:60] or q.get('name')
    for k in ('title', 'description'):
        if k in d:
            q[k] = d[k]
    if 'conditions' in d:
        new_ = {int(c['id']): c for c in d['conditions']}

        def walk(case):
            for el in case.get('modifier', []):
                c = el.get('condition') or {}
                if c.get('id') in new_:
                    y = new_[c['id']]
                    c['targetValue'] = _int(y.get('target', c.get('targetValue', 1)), 0, 10 ** 9)
                    if 'matches' in y and CONDITION.get(c['type']) in ('npc', 'map', 'item', 'ore'):
                        es = [map_match(x) if CONDITION[c['type']] == 'map' else str(x) for x in y['matches'] if str(x)]
                        c['matches'] = es or c['matches']
                    if 'map' in y:          # ON_MAP sub-condition: empty list -> on every map
                        c['subConditions'] = [s for s in c.get('subConditions', []) if s['type'] != SUB_MAP]
                        if y['map']:
                            c['subConditions'].append(_sub_map(c['id'], y['map']))
                q2 = el.get('questCase') or {}
                if q2.get('id'):
                    walk(q2)
        walk(q['root'])
    patch(did, file, DATA.build_path('quests', qid), q)


def map_match(x):
    """Map in a quest match: name "@1-1" (quest.maps_for resolves; patterns like "@own X-3" stay as they are), id as it is."""
    x = str(x)
    return x if x.startswith('@') or x.isdigit() else '@' + x


def _sub_map(cid, maps_):
    return {'_': 'QuestConditionModule', 'id': cid * 10 + 7, 'matches': [map_match(x) for x in maps_], 'type': SUB_MAP,
            'displayType': SUB_MAP, 'targetValue': 0, 'mandatory': True,
            'state': {'_': 'QuestConditionStateModule', 'currentValue': 0, 'active': True, 'completed': False}, 'subConditions': []}


def _condition(cid, kind, matches, target, map_list=None):
    return {'_': 'QuestElementModule', 'questCase': {'_': 'QuestCaseModule', 'id': 0, 'active': False, 'mandatory': False, 'ordered': False,
                                                     'mandatoryCount': 0, 'modifier': []},
            'condition': {'_': 'QuestConditionModule', 'id': cid, 'matches': [str(x) for x in matches], 'type': kind, 'displayType': kind,
                          'targetValue': target, 'mandatory': True,
                          'state': {'_': 'QuestConditionStateModule', 'currentValue': 0, 'active': True, 'completed': False},
                          'subConditions': [_sub_map(cid, map_list)] if map_list else []}}


def new_quest(did, name, level, targets, rewards):
    """New quest: goals [{type: hunt|collect|exploring|sell|box|cargo, matches: [...], target, map: [...]}] unordered, all required.
    Its in-game title is the name (title; the client has no text for it, the plugin's QuestTexts patch shows it)."""
    if not targets:
        raise WorldError(_('Add at least one objective to the quest.'))
    all_ = _all_quests(did)
    qid = max([NEW_QUEST - 1] + [int(k) for k in all_ if int(k) >= NEW_QUEST]) + 1
    root_id = 1_900_000_000 + (qid - NEW_QUEST) * 100
    mods = []
    for i, x in enumerate(targets[:8]):
        if x.get('type') not in QUEST_TEMPLATES:
            raise WorldError(_('Unknown quest objective.'))
        kind = QUEST_TEMPLATES[x['type']][0]
        es = x.get('matches') or []
        if CONDITION[kind] in ('npc', 'item', 'ore', 'map') and not es:
            raise WorldError(_('Choose what to do for each objective.'))
        if CONDITION[kind] == 'map':
            es = [map_match(m) for m in es]
        mods.append(_condition(root_id + 1 + i, kind, es, _int(x.get('target', 1), 1, 10 ** 7), x.get('map') or None))
    q = {'name': ' '.join(str(name or '').split())[:60] or _('New quest'), 'level': _int(level or 1, 1, 40), 'priority': 500, 'kinds': [2],
         'icon': 0, 'previous': [], 'source': 'world', 'pvp': False,
         'root': {'_': 'QuestCaseModule', 'id': root_id, 'active': False, 'mandatory': True, 'ordered': False, 'mandatoryCount': len(mods),
                 'modifier': mods},
         'rewards': rewards or []}
    q['title'] = q['name']
    patch(did, 'quest_extras.json', DATA.build_path('quests', qid), q)
    return qid


# ---- shop and auction
_CATALOG = {}


def catalog():
    if 'k' not in _CATALOG:
        p = PTH.template('responses.json')
        if not p:
            _CATALOG['k'] = {}
        else:
            import shop as SHP
            with open(p, encoding='utf8') as fh:
                _CATALOG['k'] = SHP.catalog(json.load(fh))
    return _CATALOG['k']


def shop(did):
    product = world_data(did, 'shop')['products']
    out = {}
    for cat, its in catalog().items():
        out[cat] = [dict(it, world=product.get(it['lootId'])) for it in its]
    return out


def auction(did):
    lot = world_data(did, 'social.json')['auction']['lots']
    base = raw('social.json')['auction']['lots']
    return {'lots': [{'loot': l[0], 'group': l[1], 'type': l[2], 'count': l[3], 'instant': l[4], 'price': l[5]} for l in lot],
            'changed': lot != base, 'default_count': len(base)}


def item_list():
    """The item picker's list: the client's items (client_items.json) + currencies."""
    ist = raw('client_items.json')['items']
    return sorted(set(ist) | {'currency_credits', 'currency_uridium', 'currency_honour', 'currency_experience'})


# ---- boxes and loot, galaxy gates, ores
def boxes(did):
    """Contents of bonus boxes (equal-probability rows) and keyed boxes (weighted reward table, maps, count)."""
    npc = world_data(did, 'npc.json')
    base = raw('npc.json')
    k = world_data(did, 'boxes.json')
    kb = raw('boxes.json')['boxes']
    out = []
    for kind, b in k['boxes'].items():
        if not b.get('reward'):                    # Battle Pass Box (per event), those whose contents are elsewhere
            continue
        out.append({'type': kind, 'name': b['name'], 'key': b['key'], 'maps': b['maps'], 'count': b['count'], 'renew_sec': b['renew_sec'],
                    'calendar': b.get('calendar'), 'reward': b['reward'], 'changed': b != kb.get(kind), 'spawns': bool(b['maps'] and b['count'])})
    return {'bonus': npc['bonus_boxes'], 'bonus_4x': npc['bonus_box_4x'], 'bonus_changed': npc['bonus_boxes'] != base['bonus_boxes'],
            'bonus_4x_changed': npc['bonus_box_4x'] != base['bonus_box_4x'], 'boxes': out, 'classes': list(raw('boxes.json')['maps'])}


def gates(did):
    k = world_data(did, 'gates.json')['gates']
    kb = raw('gates.json')['gates']
    out = []
    for key, g in k.items():
        o = g['reward']
        out.append({'key': key, 'name': g['name'], 'part': g['part'], 'hp': g['hp'], 'changed': g != kb.get(key),
                    'reward': {x: o.get(x) for x in GATE_REWARD if x in o}, 'ammunition': o.get('ammunition') or {},
                    'chance': [{'item': x['item'], 'count': x.get('count'), 'probability': x.get('probability', 0), 'package': x['item'] == 'ore_pack'}
                             for x in o.get('chance', [])],
                    'standard': {'part': kb[key]['part'], 'hp': kb[key]['hp'], 'reward': {x: kb[key]['reward'].get(x) for x in GATE_REWARD}} if key in kb else None,
                    'waves': [{'name': w['name'], 'alien_spawns': [{'type': a['type'], 'name': a.get('display_name') or a.get('name'), 'count': a['count'], 'hp': a['hp'],
                                                               'changed_kind': key in kb and i < len(kb[key]['waves'][n]['alien_spawns']) and a['type'] != kb[key]['waves'][n]['alien_spawns'][i]['type'],
                                                               'fixed': bool(a.get('permanent')) or a['type'] == 'player',
                                                               'shield': a['shield'], 'damage': a['damage'], 'speed': a['speed'], 'permanent': bool(a.get('permanent')),
                                                               'min_value': sum(1 for grp in w['groups'] for j, _ in grp if j == i),
                                                               'icon': npc_icon(a['type'], {})}
                                                              for i, a in enumerate(w['alien_spawns'])]} for n, w in enumerate(g['waves'])]})
    return out


def ores(did, mid):
    """The map's ores: the map class's if there is no map-specific value (world); types and respawn time."""
    H = _server()
    c = world_data(did, 'items.json')['ores']
    name, klass = map_name(mid), H.map_class(int(mid))
    special = c['maps'].get(name) if name != klass else None
    return {'count': special if special is not None else c['maps'].get(klass, {}), 'special': special is not None, 'class_name': klass, 'name': name,
            'kinds': c['kinds'], 'renew_sec': c['respawn_sec'], 'respawn_default': raw('items.json')['ores']['respawn_sec'],
            'route': DATA.build_path('ores', 'maps', name)}


# ---- in-game quest texts (plugin: GorevMetinleri.cs)
TEXT_FILE = os.path.join('BepInEx', 'openorbit', 'quest_texts.json')


def quest_texts(did):
    """The titles and descriptions to show in the game for the world's quests: {"<quest>": {baslik, aciklama}}."""
    out = {}
    for qid, (_, q) in _all_quests(did).items():
        m = {k: q[k] for k in ('title', 'description') if q.get(k)}
        if m:
            out[qid] = m
    return out


def write_texts(client, did):
    """PLAY: the world's quest texts into the client's BepInEx folder (empty in the standard world: so the previous world's do not remain)."""
    if not client or not os.path.isdir(os.path.join(client, 'BepInEx')):
        return 0
    m = quest_texts(did) if did and did != STANDARD and var(did) else {}
    _write_file(os.path.join(client, TEXT_FILE), m)
    return len(m)


# ---- events
def events(did):
    e = world_data(did, 'events.json')['events']
    events_raw = raw('events.json')['events']
    types = world_data(did, 'npc.json')['types']
    out = []
    for key, x in e.items():
        h = x.get('map')
        game_map = None
        if h:
            game_map = {'maps': h.get('maps', []), 'quota': h.get('quota', {}),
                      'alien_spawns': [{'type': a['type'], 'count': a['count'], 'name': (types.get(a['type'].replace('{x}', 'x2')) or types.get(a['type'].replace('{x}', 'x3')) or {}).get('name', a['type']),
                                     'icon': npc_icon(a['type'], types.get(a['type'].replace('{x}', 'x2')) or {})} for a in h.get('alien_spawns', [])],
                      'boss': {k: h['boss'][k] for k in ('count', 'duration_sec') if k in h['boss']} if h.get('boss') else None,
                      'selectable': event_classes(h, types)}
        kind = 'map' if h else 'yearly' if 'periods' in x else 'weekly'
        out.append({'key': key, 'name': x.get('name', key), 'type': kind, 'periods': [r[:2] for r in x.get('periods', [])] if 'periods' in x else None,
                    'days': x.get('days'), 'hours': x.get('hours'), 'world_status': x.get('world_status', 'calendar'), 'map': game_map,
                    'changed': x != events_raw.get(key)})
    return sorted(out, key=lambda x: ({'map': 0, 'yearly': 1, 'weekly': 2}[x['type']], x['name'].lower()))


# ---- rewards and economy
RANK_FORMULA = ('ep', 'honor', 'level', 'npc', 'quest', 'player', 'ship', 'day', 'friendly', 'death_by_enemy', 'death_by_radiation', 'phoenix')


def economy(did):
    lv, raw_levels = world_data(did, 'levels.json')['levels'], raw('levels.json')['levels']
    r, rb = world_data(did, 'ranks.json'), raw('ranks.json')
    return {'levels': lv, 'levels_default': raw_levels, 'formula': r['formula'], 'formula_default': rb['formula'], 'thresholds': r['thresholds'],
            'thresholds_default': rb['thresholds'], 'ranks': [x['name'] for x in r['ranks']]}
