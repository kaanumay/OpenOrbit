"""Profile tool (the panel runs it in a separate process, to avoid loading server modules into the panel's process).

  python -I profile_tool.py new <profile.json> <pilot name> <company 1|2|3> [--credits=N] [--uridium=N] [--level=N] [--honor=N]
                                 [--laser=N] [--rocket=N]
      new profile from the seed (data/login.json, else the default pilot): pilot name, company, a station on the company's home map (X-1);
      optional starting values: credits, uridium, level (its EP is the level's threshold, data/levels.json), honor, count of LCB-10 and R-310
  python -I profile_tool.py home_base <profile.json>
      move the ship to its company's home station (rescue from a broken map or one it is stuck on)
  python -I profile_tool.py give <profile.json> <JSON [[lootId, count], ...]>
      give items, ships, drones, ammo, resources, boosters (the game's reward path: shop.reward; Ö2)
  python -I profile_tool.py reset <profile.json> <section,section>
      reset state: hints, ui (window and bar positions), game_settings, active_quests, history (logbook and account
      history)
  python -I profile_tool.py seasons <profile.json> <season length in days>
      the Season Pass seasons and their state (season.catalog)
  python -I profile_tool.py season <profile.json> <season id> <season length in days>
      play that season (season.switch_state: the running one is paused with its progress and time; a finished one cannot be picked)
  python -I profile_tool.py entries
      the lootIds that can be given (the client's item data and the server's item tables)
Output: on the last line JSON {'ok': true, ...} or {'ok': false, 'error': '...'}.
"""
import json, os, sys, time

SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER)
DATA = os.path.join(SERVER, 'data')
HOME_MAP = {1: 1, 2: 5, 3: 9}             # game.py HOME_MAP: company -> X-1
START_AMMO = {'laser': 'ammunition_laser_lcb-10', 'rocket': 'ammunition_rocket_r-310'}     # starting ammo of a new save (in the seed too)


def _load(name):
    import paths as PTH
    p = PTH.template(name) if name in PTH.TEMPLATES else os.path.join(DATA, name)     # template: your own save, else a shareable copy
    return json.load(open(p, encoding='utf8')) if p and os.path.exists(p) else {}


def station_pos(map_id):
    """The position of the map's station (like game.Sablonlar.station) or None."""
    import map_links as H
    maps = _load('maps.json')
    rec = maps.get(str(map_id))
    if rec is None:
        rec = H.map_world(map_id, maps.get('5'))
    for m in rec.get('ready', []):
        if m['_m'] == 'SpaceStationCommand' and m.get('type') not in H.DECOR_STATION_TYPES:
            return int(m['posX']), int(m['posY'])
    return None


def level_ep(level):
    """The level's EP threshold (data/levels.json; clipped to the highest level) -> (level, EP)."""
    table = _load('levels.json').get('levels') or [[1, 0]]
    lv = max(table[0][0], min(int(level), table[-1][0]))
    return lv, next(need for l, need in table if l == lv)


def new_(path, pilot, company, credits=None, uridium=None, level=None, honor=None, laser=None, rocket=None, progressive=False, campaign=False):
    if os.path.exists(path):
        raise ValueError('A profile already exists at this path.')
    from player_profile import Profile
    company = int(company)
    pr = Profile(_load('login.json').get('seed'), path)
    pl = pr.d['pilot']
    pl['userName'] = pilot
    pl['factionId'] = company
    if credits is not None:
        pl['credits'] = credits
    if uridium is not None:
        pl['uridium'] = uridium
    if level is not None:                                  # the level is computed from EP (the game does the same): EP is the level's threshold
        pl['level'], pl['ep'] = level_ep(level)
    if honor is not None:
        pl['honourPoints'] = honor
    for key, n in (('laser', laser), ('rocket', rocket)):
        if n is not None:
            pr.d['ammunition'][START_AMMO[key]] = n
    mid = HOME_MAP[company]
    pos = station_pos(mid)
    if pos:
        pr.d['position'] = {'mapId': mid, 'x': pos[0], 'y': pos[1]}
    pr.d['created'] = time.strftime('%Y-%m-%d %H:%M:%S')
    if progressive:                                          # Season Pass in order from the first season (season.py)
        pr.d['progressive'] = True
    if campaign:                                            # starter campaign: the "Level N" quests (for quest.CAMPAIGN_SEC)
        pr.d['campaign'] = int(time.time())
    pr.save(force=True)
    return {'map': mid, 'position': pos, 'template': bool(_load('login.json'))}


def home_base(path):
    d = json.load(open(path, encoding='utf8'))
    mid = HOME_MAP.get(d['pilot'].get('factionId'), 5)
    pos = station_pos(mid)
    if not pos:
        raise ValueError("The home station's position was not found.")
    d['position'] = {'mapId': mid, 'x': pos[0], 'y': pos[1]}
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return {'map': mid, 'position': pos}


def seasons(path, days):
    import season as SZN
    d = json.load(open(path, encoding='utf8'))
    return SZN.catalog(d.get('season') or {}, length=int(days) * 86400)


def season(path, sid, days):
    import season as SZN
    d = json.load(open(path, encoding='utf8'))
    how = SZN.switch_state(d.setdefault('season', {}), sid, time.time())
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return dict(SZN.catalog(d['season'], length=int(days) * 86400), how=how)


def known_loots():
    """The lootId that can be given -> type (the client's item data; the server's item tables)."""
    out = {k: (v.get('type') or '') for k, v in (_load('client_items.json').get('items') or {}).items()
           if not k.startswith(('shipId_', 'paymentItem_'))}
    es = _load('items.json')
    prefixes = {k.split('_', 1)[0] for k in out}
    for sec in ('lasers', 'laser_ammo', 'rockets', 'repair_robots', 'speed_generators', 'shield_generators', 'ships',
                'drones', 'formations', 'drone_designs', 'boosters', 'extras', 'combat_items', 'payment_packages'):
        for k in (es.get(sec) or {}):
            if isinstance(k, str) and not k.startswith('_') and k.split('_', 1)[0] in prefixes | {'package', 'deal'}:
                out.setdefault(k, sec)
    return out


def give(path, items, pr=None):
    """The game's reward path (same as quest and box rewards: shop.reward) on an offline profile: ship to the hangar, equipment to the
    inventory (equipped if there is a free slot), drone, ammo, resource, booster, design. An unknown lootId is rejected. pr: this
    profile instead of the file (not saved)."""
    import galaxy_gates as GALAXY
    import new_systems as NS
    from player_profile import Profile
    from shop import Shop
    known = known_loots()
    items = [(str(l), max(1, min(10 ** 9, int(n)))) for l, n in items]
    bad = [l for l, n in items if l not in known and not l.startswith(('ammunition_', 'resource_', 'ship_', 'drone_', 'booster_'))]
    if bad:
        raise ValueError('Unknown item: %s', ', '.join(bad))
    notes = []
    save = pr is None
    pr = pr or Profile(_load('login.json').get('seed'), path)
    m = Shop(pr, _load('responses.json'), notes.append)      # templates in the game: the HangarShipEquipmentCommand of the equipped equipment
    m.gates = GALAXY.Gates(pr, notes.append)
    m.new_ = NS.NewSystems(pr, m, notes.append)
    before = (len(pr.d.get('items', {})), len(pr.d.get('ships', {})), len(pr.d.get('drones', [])))
    for loot, n in items:
        m.reward(loot, n)
    if save:
        pr.save(force=True)
    after = (len(pr.d.get('items', {})), len(pr.d.get('ships', {})), len(pr.d.get('drones', [])))
    return {'given': [[l, n] for l, n in items], 'item': after[0] - before[0], 'ship': after[1] - before[1],
            'drone': after[2] - before[2], 'notes': [x.strip() for x in notes if x.strip()][-20:]}


RESETS = ('hints', 'ui', 'game_settings', 'active_quests', 'history')


def reset(path, parts):
    d = json.load(open(path, encoding='utf8'))
    done = reset_d(d, parts)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return {'reset_items': done}


def reset_d(d, parts):
    """Resets state in a profile dict (save_editor.py uses it on the draft too) -> the sections reset."""
    seed = _load('login.json').get('seed') or {}
    done = []
    for part in parts:
        if part == 'hints':                     # hint windows and event notifications again (tips.py)
            for k in ('tips_shown', 'hints_closed', 'event_notification'):
                d.pop(k, None)
        elif part == 'ui':                     # menu bars and window positions from the seed (UILayoutCommand)
            d['ui'] = seed.get('UILayoutCommand') or {'featureBars': []}
        elif part == 'game_settings':              # the game's Settings window (graphics, sound, gameplay) from the seed
            d['settings'] = seed.get('UserSettingsCommand') or {}
        elif part == 'active_quests':             # accepted quests are dropped (finished ones stay)
            d.setdefault('quests', {})['active'] = {}
        elif part == 'history':                     # logbook and account history are emptied
            d['logbook'], d['account_history'] = [], []
        else:
            raise ValueError('Unknown section: %s', part)
        done.append(part)
    return done


def main(argv):
    opts = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in argv if a.startswith('--') and '=' in a}
    args = [a for a in argv if not a.startswith('--')]
    if args[:1] == ['new'] and len(args) == 4:
        num = {k: int(opts[k]) for k in ('credits', 'uridium', 'level', 'honor', 'laser', 'rocket') if k in opts}
        return new_(args[1], args[2], args[3], progressive=opts.get('progressive') == '1', campaign=opts.get('campaign') == '1', **num)
    if args[:1] == ['home_base'] and len(args) == 2:
        return home_base(args[1])
    if args[:1] == ['give'] and len(args) == 3:
        return give(args[1], json.loads(args[2]))
    if args[:1] == ['reset'] and len(args) == 3:
        return reset(args[1], [x for x in args[2].split(',') if x])
    if args[:1] == ['seasons'] and len(args) == 3:
        return seasons(args[1], args[2])
    if args[:1] == ['season'] and len(args) == 4:
        return season(args[1], args[2], args[3])
    if args[:1] == ['entries'] and len(args) == 1:
        return {'items': sorted(known_loots().items())}
    raise ValueError('usage: profile_tool.py new <path> <pilot> <company> | home_base <path> | give <path> <json> | reset <path> <sections> | seasons <path> <days> | season <path> <id> <days> | entries')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    try:
        out = main(sys.argv[1:])
        print(json.dumps(dict(out, ok=True), ensure_ascii=False))
    except Exception as e:
        # ValueError(template, *values): the panel builds the message in its own language (saves.run_tool, dil.py)
        template = e.args[0] if isinstance(e, ValueError) and e.args and isinstance(e.args[0], str) else None
        msg = (template % e.args[1:] if len(e.args) > 1 else template) if template else str(e)
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, msg), 'template': template, 'arg': [str(a) for a in e.args[1:]]},
                         ensure_ascii=False))
