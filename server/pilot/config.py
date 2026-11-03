"""Auto Mode settings: defaults, validation, the file the panel writes (pilot.json next to the save slot's profile.json) and the status
file the bot writes for the panel (<log folder>/pilot_status_<slot>.json). Standard library only: the panel imports it too."""
import json, os

WHEN = ('hp', 'shield', 'fight', 'big', 'always')
# operating modes (tasks/modes.py): one at a time; a mode with nothing left to do goes on with its 'then' (stop, or another mode)
MODES = ('hunt', 'gate', 'quest', 'mining')
THEN = ('stop', 'hunt', 'quest', 'mining')


def _item_rules(v):
    """[{item: ability_* / tech_*, when: WHEN, value: number}] (at most 20)."""
    out = []
    for r in v[:20]:
        if not isinstance(r, dict) or not str(r.get('item', '')).startswith(('ability_', 'tech_')):
            continue
        out.append(dict(item=str(r['item']), when=r.get('when') if r.get('when') in WHEN else 'fight',
                        value=_num(r.get('value'), 50, 0, 10 ** 9, int)))
    return out


def _supply_rules(v):
    """[{loot: ammunition_*, below: stock, amount: to buy}] (at most 12)."""
    out = []
    for r in v[:12]:
        if not isinstance(r, dict) or not str(r.get('loot', '')).startswith('ammunition_'):
            continue
        out.append(dict(loot=str(r['loot']), below=_num(r.get('below'), 1000, 0, 10 ** 8, int),
                        amount=_num(r.get('amount'), 10000, 1, 10 ** 7, int)))
    return out


MOVE_MODES = ('hero_move', 'server')
SLOW_AMMO = ('ammunition_laser_rcb-140', 'ammunition_laser_rsb-75')    # in order of preference (x7, then x6)


def _laser_ammo(v):
    v = v if isinstance(v, str) else ''
    return v if v.startswith('ammunition_laser_') else ''


def _rocket_ammo(v):
    v = v if isinstance(v, str) else ''
    return v if v.startswith(('ammunition_rocket_', 'ammunition_specialammo_')) else ''


def _aliens(v):
    """The hunt lists, one per map: {map id: sorted type keys}. The list of before (one for every map) is dropped: it hid aliens of
    other maps."""
    out = {}
    for m, tips in (v.items() if isinstance(v, dict) else []):
        if str(m).isdigit() and isinstance(tips, list):
            keep = sorted({str(x) for x in tips if isinstance(x, (str, int)) and not isinstance(x, bool)})
            if keep:
                out[str(m)] = keep
    return dict(list(out.items())[:60])


MAP_MAX = 42000               # the largest map side (map_layout positions go up to 42000 x 26200)
MAX_AVOID = 8


def _rect(v):
    """[x0, y0, x1, y1] ordered, inside the map's limits and at least 200 units a side, or None."""
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return None
    try:
        x0, y0, x1, y1 = (max(0, min(MAP_MAX, int(a))) for a in v)
    except (TypeError, ValueError, OverflowError):
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return [x0, y0, x1, y1] if x1 - x0 >= 200 and y1 - y0 >= 200 else None


def _zones(v):
    """The areas drawn on the Auto Mode map, one entry per map: {map id: {'work': rect (targets, boxes and ore only inside, patrol inside),
    'avoid': [rect] (never entered, nothing taken inside)}}. A map with neither is dropped."""
    out = {}
    for m, z in (v.items() if isinstance(v, dict) else []):
        if not str(m).isdigit() or not isinstance(z, dict):
            continue
        e = {}
        work = _rect(z.get('work'))
        if work:
            e['work'] = work
        avoid = [r for r in (_rect(a) for a in (z.get('avoid') if isinstance(z.get('avoid'), list) else [])[:MAX_AVOID]) if r]
        if avoid:
            e['avoid'] = avoid
        if e:
            out[str(m)] = e
    return dict(list(out.items())[:60])


# Every setting: key -> (kind, default, *limits). kinds: bool; int / float (lo, hi); ints (a list of whole numbers, max length); str (max
# length); choice (allowed values); subset (allowed values, in their order: the chosen ones); rules (a cleaning function for a list of
# dicts); fn (a cleaning function for the raw value); block (a nested spec: one card's settings). A new setting is one entry here (and its
# field in the panel). 'mode', 'profiles' and 'profile' are cleaned by clean() itself.
TOP = {
    'enabled': ('bool', False),
    'move_mode': ('choice', 'hero_move', MOVE_MODES),   # 'hero_move': HeroMoveCommand, the client flies and sends its own MoveRequest
    'kite_min': ('float', 0.80, 0.3, 0.98),        # kiting band, share of the real laser range: back off below, approach above
    'kite_max': ('float', 0.95, 0.35, 0.99),
    'threat_margin': ('int', 150, 0, 2000),        # added to an alien's notice distance / firing range when keeping away from it
    'avoid_aggressive': ('bool', True),            # also keep away from aggressive aliens that are not attacking yet
    'clear_path': ('bool', False),                 # on the way to another map (or the gate, the base ...): destroy the aggressive aliens on the path
    'defend': ('bool', True),                      # on the map the mode works on: fight back against the aliens attacking the ship
    'flee_hp': ('int', 25, 0, 95),                 # % HP: stop fighting and go to a safe zone
    'resume_hp': ('int', 90, 5, 100),              # % HP: resume after the repair
    'pause_sec': ('int', 5, 0, 120),               # after a manual move
    'box_radius': ('int', 1500, 0, 20000),         # boxes farther than this are ignored
    'aliens': ('fn', {}, _aliens),                 # map id (text) -> npc.json type keys to hunt on that map; a map without a list: every alien
    'priority': ('fn', {}, _aliens),               # map id (text) -> type keys taken first when one is around (the map's star in the panel)
    'zones': ('fn', {}, _zones),                   # map id (text) -> the work area and the areas to avoid drawn on the map
    'stuck_sec': ('int', 20, 0, 600),              # the target lost no HP / shield for this long: left alone for a while (0: never)
    'boxes': ('block', None, {'bonus': ('bool', True), 'cargo': ('bool', True), 'event': ('bool', True)}),
    'laser_ammo': ('fn', '', _laser_ammo),         # lootId selected when the bot starts; empty: keep the current ammo
    'rockets': ('bool', True),                     # fire the selected rocket at the target each time it is ready (rocket range)
    'rocket_ammo': ('fn', '', _rocket_ammo),       # rocket selected when the bot starts; empty: keep the current one
    'launcher': ('bool', True),                    # fire the rocket launcher at the target once it is fully loaded
    'roam': ('bool', True),                        # patrol the map when there is nothing to do
    'slow_ammo': ('subset', [], SLOW_AMMO),        # RCB-140 / RSB-75 fired each time their shared 3 s cooldown ends, then the normal ammo again
}

# Settings blocks, one per feature card (same kinds as TOP).
BLOCKS = {
    'travel': {                                    # Hunt mode: the maps to hunt on
        'maps': ('ints', [], 20),                  # map ids, in order; empty: stay on the map where the bot started
        'leave_empty_sec': ('int', 90, 0, 3600),   # nothing to hunt for this long: on to the next map of the list (0: never)
    },
    'recover': {                                   # after the ship is destroyed
        'revive': ('bool', True),                  # repair at the base (free) and fly back to the hunting map
        'max_revives': ('int', 5, 0, 1000),        # in one session; one more death stops the bot
    },
    'stop': {                                      # stop conditions (0: off)
        'minutes': ('int', 0, 0, 100000),
        'kills': ('int', 0, 0, 10 ** 7),
        'ammo_below': ('int', 0, 0, 10 ** 8),      # stock of the normal laser ammo
        'go_home': ('bool', False),                # fly to the base before stopping
    },
    'support': {                                   # abilities and technologies
        'rules': ('rules', [], _item_rules),
    },
    'config_switch': {
        'enabled': ('bool', False),
        'shield_pct': ('int', 20, 0, 100),         # shield below this share: the other config if its kept shield is fuller
    },
    'pet': {
        'enabled': ('bool', False),
        'gear': ('int', 2, 1, 30),                 # pet.py gear types (2: Guard)
        'low_hp_gear': ('int', 0, 0, 30),          # 0: none
        'low_hp_pct': ('int', 30, 0, 100),
        'repair': ('bool', True),
        'repair_max': ('int', 10000, 0, 10 ** 7),  # uridium per repair
    },
    'ore': {                                       # Hunt mode: ore between fights, selling the cargo
        'harvest': ('bool', False),                # harvest ore between fights
        'types': ('ints', [], 12),                 # ore types (world.ITEMS ores.kinds); empty: all
        'radius': ('int', 3000, 0, 30000),
        'sell': ('bool', False),                   # sell the cargo at the station when it is full
        'sell_free': ('int', 0, 0, 100000),        # free cargo space at or below which the ship goes to sell
    },
    'supply': {                                    # ammo resupply
        'rules': ('rules', [], _supply_rules),
        'max_credits': ('int', 5000000, 0, 10 ** 11),     # budget per session
        'max_uridium': ('int', 0, 0, 10 ** 9),
    },
    'players': {                                   # enemy players and player bots
        'enabled': ('bool', False),
        'distance': ('int', 2000, 0, 20000),
        'attack_only': ('bool', False),            # react only when one fires at the ship
        'action': ('choice', 'flee', ('flee', 'map', 'stop')),
        'wait_sec': ('int', 60, 0, 3600),          # flee: stay hidden this long after the last sighting
        'avoid_min': ('int', 10, 1, 1440),         # map: avoid the map this long
    },
    'quests': {                                    # Quests mode: the active quests lead the hunt
        'qid': ('int', 0, 0, 10 ** 9),             # the quest to play (one of the accepted ones); 0: the first one that can be played
        'accept': ('bool', False),                 # take a new quest at a quest giver when none can be played
        'then': ('choice', 'hunt', THEN),          # no quest to play or to take
    },
    'gates': {                                     # Galaxy gate mode: a galaxy gate end to end
        'key': ('str', '', 30),                    # galaxy_gates.GATES key (alpha, beta ...)
        'min_lives': ('int', 1, 0, 10),            # buy lives up to this before going in / after a death
        'life_budget': ('int', 0, 0, 10 ** 8),     # uridium for lives per session
        'build_budget': ('int', 0, 0, 10 ** 9),    # uridium for the generator's spins per session (a gate whose parts are missing)
        'leave_lives': ('int', 0, 0, 10),          # once the gate's lives are down to this (after a death), leave it for 'then'; 0: off
        'repeat': ('bool', False),                 # once completed, again if the parts are complete again
        'then': ('choice', 'stop', THEN),          # the gate is done, not built, out of lives or out of reach
    },
    'mining': {                                    # Mining mode: ore only (no hunting)
        'maps': ('ints', [], 20),                  # empty: the map where the bot started
        'types': ('ints', [], 12),                 # empty: all
        'radius': ('int', 3000, 0, 30000),
        'sell_free': ('int', 0, 0, 100000),        # free cargo space at or below which the ship goes to sell
        'leave_empty_sec': ('int', 120, 0, 3600),  # no ore for this long: on to the next map of the list (0: never)
    },
}


def _num(v, default, lo, hi, kind=float):
    try:
        v = kind(v)
    except (TypeError, ValueError, OverflowError):
        return default
    if v != v:                                      # NaN
        return default
    return max(lo, min(hi, v))


def _clean_block(spec, d):
    d = d if isinstance(d, dict) else {}
    out = {}
    for k, (kind, default, *lim) in spec.items():
        v = d.get(k, default)
        if kind == 'bool':
            out[k] = bool(v)
        elif kind == 'int':
            out[k] = _num(v, default, lim[0], lim[1], int)
        elif kind == 'float':
            out[k] = _num(v, default, lim[0], lim[1], float)
        elif kind == 'ints':
            vals = []
            for x in v if isinstance(v, list) else []:
                try:
                    x = int(x)
                except (TypeError, ValueError, OverflowError):
                    continue
                if x not in vals:
                    vals.append(x)
            out[k] = vals[:lim[0]] if lim else vals
        elif kind == 'str':
            out[k] = str(v)[:lim[0]] if isinstance(v, (str, int)) and not isinstance(v, bool) else default
        elif kind == 'choice':
            out[k] = v if isinstance(v, str) and v in lim[0] else default
        elif kind == 'subset':
            out[k] = [a for a in lim[0] if isinstance(v, list) and a in v]
        elif kind == 'rules':
            out[k] = lim[0](v if isinstance(v, list) else [])
        elif kind == 'fn':
            out[k] = lim[0](v)
        elif kind == 'block':
            out[k] = _clean_block(lim[0], v)
    return out


def _old_mode(d):
    """Settings from before the modes: the galaxy gate / quest switches become the mode."""
    for block, mode in (('gates', 'gate'), ('quests', 'quest')):
        b = d.get(block)
        if isinstance(b, dict) and b.get('enabled'):
            return mode
    return 'hunt'


def clean(d):
    """A valid settings dict from anything (missing or wrong values take the default)."""
    d = d if isinstance(d, dict) else {}
    out = _clean_block(TOP, d)
    out['mode'] = d.get('mode') if isinstance(d.get('mode'), str) and d.get('mode') in MODES else _old_mode(d)
    for name, spec in BLOCKS.items():
        out[name] = _clean_block(spec, d.get(name))
    profs = d.get('profiles')
    out['profiles'] = {str(n)[:40]: settings(p) for n, p in list(profs.items())[:MAX_PROFILES]
                       if str(n).strip() and isinstance(p, dict)} if isinstance(profs, dict) else {}
    prof = d.get('profile')
    out['profile'] = prof if isinstance(prof, str) and prof in out['profiles'] else ''
    if out['kite_max'] < out['kite_min'] + 0.03:
        out['kite_max'] = min(0.99, out['kite_min'] + 0.03)
    if out['resume_hp'] <= out['flee_hp']:
        out['resume_hp'] = min(100, out['flee_hp'] + 5)
    return out


MAX_PROFILES = 30
NOT_IN_PROFILE = ('enabled', 'profiles', 'profile')


def settings(d):
    """The settings a profile keeps: everything but the on/off switch and the profiles themselves."""
    c = clean(dict(d if isinstance(d, dict) else {}, profiles={}, profile=''))
    return {k: v for k, v in c.items() if k not in NOT_IN_PROFILE}


def profile_action(cur, action, name):
    """The panel's profile buttons on the current settings -> the new settings. save: the current settings under name (and it becomes the
    active profile); load: name's settings replace the current ones (Start/Stop and the profiles stay); delete."""
    name = str(name or '').strip()[:40]
    if not name:
        raise ValueError('A profile needs a name.')
    out = dict(cur, profiles=dict(cur.get('profiles') or {}))
    if action == 'save':
        if name not in out['profiles'] and len(out['profiles']) >= MAX_PROFILES:
            raise ValueError('Too many profiles.')
        out['profiles'][name] = settings(cur)
        out['profile'] = name
    elif action == 'load':
        if name not in out['profiles']:
            raise ValueError('Unknown profile: %s' % name)
        out.update(out['profiles'][name])
        out['profile'] = name
    elif action == 'delete':
        out['profiles'].pop(name, None)
        if out.get('profile') == name:
            out['profile'] = ''
    else:
        raise ValueError('Unknown action: %s' % action)
    return clean(out)


def mtime(path):
    """The settings file's modification time (None if absent): the bot re-reads the file when it changes."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def path_for(profile_path):
    return os.path.join(os.path.dirname(os.path.abspath(profile_path)), 'pilot.json')


def status_path(log_dir, profile_path):
    """One status file per save slot: on a multi-session server (extra clients, friend server) every session runs its own bot."""
    slot = os.path.basename(os.path.dirname(os.path.abspath(profile_path)))
    return os.path.join(log_dir, 'pilot_status_%s.json' % slot)


def read_json(path):
    try:
        with open(path, encoding='utf8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load(path):
    return clean(read_json(path))


def save(path, d):
    d = clean(d)
    write_json(path, d)
    return d
