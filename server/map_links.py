"""Map links: the portals in the client's own spacemap-config.xml (data/spacemap-config.xml).

Each portal: the map it is on (ref), the map it leads to (leadsToMap) and its position on the 315x210 hint map.
The in-game position is scaled to the standard map size (21000x13100) and snapped to DarkOrbit's portal grid;
verified with the save: 2-1 (2000,11500) -> 2-2, 2-2 (18500,2000) -> 2-1, (2000,11500) -> 2-3, (18500,11500) -> 2-4.
Portal id = 150000167 + key (matches 150000182/183/177/184 in the save one to one).
"""
import math, os, random, re

import map_layout as ML

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'data', 'spacemap-config.xml')
GATE_ID_BASE = 150000167
MAP_W, MAP_H = 21000, 13100
JUMP_RADIUS = 600          # save: (2514,11402) is near, (2504,11050) is not -> roughly between 520 and 670
JUMP_DELAY_SEC = 3.05       # save: JumpInitiatedCommand -> JumpToServerCommand 3.05 s
GATE_PEACE_RADIUS = 1000   # save: at 818 units from the 2-1 portal BeaconCommand.inPeaceArea is true, at 1171 false (except GG gates)
# the client's help (dmz_position_p, dmz_warning_p): the portal DMZ exists only on one's own company's maps; none on the war maps (4-1..4-4),
# on 4-5 15 s after passing through the portal
NO_DMZ_MAPS = {'4-1', '4-2', '4-3', '4-4'}
DMZ_AFTER_JUMP_SEC = {'4-5': 15}
# Demilitarized zone around the pilot's own company Mission Control (quest giver). Matters for the stand-alone X-5 beacons; the X-1 and
# X-8 ones already sit inside the station's zone (peaceRadius 1800, giver 1080 units from the centre). The wikis give no radius and no
# recording covers X-5, so it uses the measured portal DMZ (GATE_PEACE_RADIUS). A foreign Mission Control is not usable (world.start)
# and gives no protection, like a foreign station. Black Light Mission Controls have none: "All BL maps feature Demilitarised zones on
# the portals but not on the mission control centre" (darkorbit.fandom.com/wiki/Demilitarized_zone); 4-X battle maps have none either.
GIVER_PEACE_RADIUS = GATE_PEACE_RADIUS


def giver_dmz(map_id):
    """Does a quest giver on this map have a demilitarized zone?"""
    n = name(map_id)
    return n not in NO_DMZ_MAPS and n not in DMZ_AFTER_JUMP_SEC and not n.startswith('BL-')
NAMES = {}
LEVELS = {}                # the client's maps-config.xml: map -> (habitant, foreign) required level (own / other company)
SCALE = {}                 # the client's maps-config.xml: the maps with scaleFactor 2 (4-4, 4-5, 5-1, 5-3) are twice as large


def _snap_x(x):
    if x < 80:
        return 2000
    if x > 235:
        return 18500
    return int(round(x * MAP_W / 315 / 100.0)) * 100


def _snap_y(y):
    if y < 60:
        return 2000
    if y > 150:
        return 11500
    return int(round(y * MAP_H / 210 / 100.0)) * 100


def _load():
    gates = {}
    mc = os.path.join(HERE, 'data', 'maps-config.xml')
    if os.path.exists(mc):
        # the definitions inside the comment do not exist in the client (the client reads with a real XML parser): the old Frozen Labyrinth block (430-445,
        # scaleFactor 2) is inside a comment, the active definitions are Escort and Eternal Gate (21000x13100). When the comment was read, 430-445 were
        # thought to be twice as large (Ö4 research, belgeler/wiki/etkinlikler/mimesis_mutiny.json)
        text = re.sub(r'<!--.*?-->', '', open(mc, encoding='utf8').read(), flags=re.S)
        for mid, scale_factor in re.findall(r'<map id="(\d+)"[^>]*scaleFactor="([\d.]+)"', text):
            SCALE[int(mid)] = float(scale_factor)
        for mid, body in re.findall(r'<map id="(\d+)"[^>]*>(.*?)</map>', text, re.S):
            lv = re.search(r'<level [^>]*habitant="(\d+)"[^>]*foreign="(\d+)"', body)
            if lv:
                LEVELS[int(mid)] = (int(lv.group(1)), int(lv.group(2)))
    if not os.path.exists(SRC):
        return gates
    text = open(SRC, encoding='utf8').read()
    for m in re.finditer(r'<jumpgate key="(\d+)" ref="(\d+)">(.*?)</jumpgate>', text, re.S):
        key, ref, body = int(m.group(1)), int(m.group(2)), m.group(3)
        pos = re.search(r'<position x="(\d+)" y="(\d+)"', body)
        to = re.search(r'<leadsToMap>(\d+)</leadsToMap>', body)
        if not pos or not to:
            continue
        scale_factor = SCALE.get(ref, 1.0) if SCALE.get(ref, 1.0) > 1 else 1.0
        g = dict(gateId=GATE_ID_BASE + key, key=key, x=int(_snap_x(int(pos.group(1))) * scale_factor), y=int(_snap_y(int(pos.group(2))) * scale_factor),
                 target=int(to.group(1)))
        fac, own = re.search(r'<faction>(\w+)</faction>', body), re.search(r'<visibleOwnFaction>(\w+)</visibleOwnFaction>', body)
        if fac:
            g['company'] = FACTIONS.get(fac.group(1))
        if fac and own and own.group(1) == 'true':
            g['only_company'] = FACTIONS.get(fac.group(1))       # on 5-X each company's own portal (visible only to that company)
        gates.setdefault(ref, []).append(g)
    for m in re.finditer(r'^\s*(\d+)\s+(\d-\d|\d-BL|BL-\d)\s*$', text, re.M):
        NAMES[int(m.group(1))] = m.group(2)
    return gates


FACTIONS = {'mmo': 1, 'eic': 2, 'vru': 3}
PLAYER_FACTION = None        # the player's company (game.py at login): filter for company-only portals
GATES = _load()
# maps that are in the client's maps-config.xml but not in spacemap-config.xml (roadmap stage 4): 5-4 (Darksilver pirates),
# Cubikon Graveyard ("???"), LoW (Lord of War)
EXTRA_NAMES = {94: '5-4', 42: '???', 200: 'LoW'}
for _m, _n in EXTRA_NAMES.items():
    NAMES.setdefault(_m, _n)
SPECIAL = {42, 200}              # Cubikon Graveyard, LoW: not in the jump CPU list; the exit from the graveyard is with the jump CPU
# the tutorial portal of 2-1 in the save (designId 55; the client's hint "This Jump Gate takes you to Tutorial."): there is no tutorial map
# on the server, the jump said "Jump not possible". Not sent after level 10 (user report 2026-10-24)
TUTORIAL_GATE, TUTORIAL_MAX_LEVEL = 150000774, 10
# portals the server adds (wiki): 5-4's portal is on 5-2 (entry takes a Silver Booty Key; the client's text
# msg_hidden_pirate_map_no_silverkey; official server record: one portal per company as on 5-X), the return from 5-4 to 5-2; LoW's
# portal is on X-3 (low.py).
# (map, key, x, y, target, extra fields); portal id GATE_ID_BASE + key (the client's keys go up to 920042)
_SILVER = {'fee': 'silver_key', 'tooltip': 'ttip_jumpgate_hiddenPirateMap'}
# LoW portal: official server record 2026-10-27, on 1-3 and 2-3 (2000, 2000), on 3-3 (18500, 2000); design 34
LOW_DESIGN = 34
LOW_START = (1000, 11800)       # arrival point on entering LoW: the lower left corner of the map (wiki "lower left corner"; emu-dark LowPortal.cs)
EXTRA_GATES = [(92, 990006, 18500, 11500, 94, dict(_SILVER, company=1, only_company=1)),
               (92, 990001, 18500, 11500, 94, dict(_SILVER, company=2, only_company=2)),
               (92, 990007, 18500, 11500, 94, dict(_SILVER, company=3, only_company=3)),
               (94, 990002, 4000, 13000, 92, {}),
               (3, 990003, 2000, 2000, 200, {'low': True, 'arrival': LOW_START, 'design': LOW_DESIGN}),
               (7, 990004, 2000, 2000, 200, {'low': True, 'arrival': LOW_START, 'design': LOW_DESIGN}),
               (11, 990005, 18500, 2000, 200, {'low': True, 'arrival': LOW_START, 'design': LOW_DESIGN})]
for _m, _k, _x, _y, _to, _extra in EXTRA_GATES:
    GATES.setdefault(_m, []).append(dict(gateId=GATE_ID_BASE + _k, key=_k, x=_x, y=_y, target=_to, **_extra))
# the portals of the pirate and Black Light maps are at their places in the layout (the place snapped to the hint grid is rough); the arrival point is
# tied to the portal (5-X: next to the broken portal at the target; random from 5-3 to 4-4): map_layout.json
for _m, _gs in GATES.items():
    for _g in _gs:
        _p, _v = ML.gate_pos(_m, _g['key']), ML.arrival(_m, _g['key'])
        if _p:
            _g['x'], _g['y'] = _p
        if _v:
            _g['arrival'] = _v
# portals of the pirate maps (official server record 2026-10-25): from 4-5 to 5-1 and each company's portal on 5-X are design 51, its company is decoration
# (decoratorAssetTypes); on 5-X another company's is invisible on the minimap and without a balloon, cannot be jumped (gates). The arrival at the target is the same company's one-way
# portal (design 52, always invisible; map_layout.json arrival_portals). 'design': 'designId' only on the ones added later
# (world.resend announces them again)
PIRATE_MAPS = {91, 92, 93}
ENTRY_DESIGN, ONE_WAY_DESIGN = 51, 52
ONE_WAY_GATE_BASE = GATE_ID_BASE + 991000        # id of the one-way portals: + map x 10 + company
for _m, _gs in GATES.items():
    for _g in _gs:
        if _g.get('company') and (_m in PIRATE_MAPS or _g['target'] in PIRATE_MAPS):
            _g.update(design=ENTRY_DESIGN, decorations=[_g['company']])
# maps-config says 1 for 5-X; wiki says level 12 (belgeler/wiki/maps.md)
for _m, _n in NAMES.items():
    if _n.startswith('5-'):
        LEVELS[_m] = (12, 12)


# maps with stations -> company: X-1 (home="n" in the client's maps-config.xml) and X-8 (wiki: Home Base)
STATION_MAPS = {1: 1, 5: 2, 9: 3, 20: 1, 24: 2, 28: 3}
FACTION_NAME = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
# respawn place after dying on a map without a station: on level 12+ and upper maps (X-5 ... X-8, 4-4, 4-5) the company's X-8 (3-8 for VRU), otherwise X-1
# (fandom 4-4, Base, Uppers: "level 12 or higher ... respawn on X-8"; one never respawns at 5-2's pirate base)
X8_HOME = {1: 20, 2: 24, 3: 28}
UPPERS = ('X-5', 'X-6', 'X-7', 'X-8', '4-4', '4-5')
# X-8's base is an outpost: the client's AssetType COMPANY_HQ_OUTPOST 47, HANGAR_OUTPOST 49, ORE_TRADE_OUTPOST 51, INSTANT_REPAIR_OUTPOST
# 54, STATION_TURRET_*_OUTPOST 56/58 (lib_assets *_outpost_<company>, texts "Corporate Outpost", "Outpost Hangar" ...; X-8 is not in the save)
OUTPOST = {46: 47, 48: 49, 50: 51, 53: 54, 55: 56, 57: 58}
OUTPOST_MAPS = {20, 24, 28}
TPL_CENTER = (19000, 2000)          # center of the 2-1 station in the save (SpaceStationCommand)
CORNERS = [(19000, 2000), (2000, 2000), (19000, 11100), (2000, 11100)]
# the place of the station and the structure in the game (center); on a map not listed, the corner farthest from the portals. 2-8: top middle (official server
# record 2026-10-25); 1-8 left, 3-8 middle of the right edge (fandom 1-8/3-8; Kalaazu and the 2009 emulator y 6000); the 5-2 market in the middle (fandom 5-2,
# darkorbitwiki map image). 5-2's pirate station and X-BL's quest giver are in map_layout.json (structure)
STATION_POS = {24: (10500, 2000), 20: (2000, 6750), 28: (19000, 6750), 9: (19000, 11500)}
# rotation of the base layout relative to that of 2-1 (degrees; on X-8 added to the outpost's rotation). Official server record 2026-10-27: on 1-1 the hangar is
# east of the center, south of the quest giver; on 3-1 north of the quest giver; 1-8, 3-8 also 270 / 90 degrees; 2-1, 2-8 as in the save
STATION_TURN = {1: 270, 9: 90, 20: 270, 28: 90}
# the outpost's layout is the main base's rotated by -45 degrees (official server record: on 2-8 the buildings are 763 units diagonally from the center, 16 small
# turrets on a 1,800-unit circle starting from (1800, 0); on 2-1 the buildings are 1,080 units vertically). 1-8 and 3-8 were not measured: the same
OUTPOST_TURN = -math.pi / 4


def map_world(map_id, tpl):
    """World messages {'entry', 'ready'} ('_m' key) for a map not in the save: portals from the client's spacemap-config.xml.
    On maps with stations the 2-1 station in the save (tpl) is moved to its place in the game (STATION_POS), otherwise to the corner farthest
    from the portals (X-8's outpost with rotation: OUTPOST_TURN); company, object ids and zone names vary by map. The quest giver is
    moved too (its design and name by the map's company: quest_giver; its company 0 as in the save). On 5-X all companies' portals go
    (another's invisible) and the one-way arrival portals."""
    gs = gates(map_id)
    gate_msgs = [dict(jumpgate_create(g, PLAYER_FACTION)[1], _m='JumpgateCreateCommand') for g in GATES.get(int(map_id), [])] + \
                [dict(jumpgate_create(dict(gateId=ONE_WAY_GATE_BASE + int(map_id) * 10 + f, x=x, y=y, designId=ONE_WAY_DESIGN,
                                           decorations=[f], invisible=True))[1], _m='JumpgateCreateCommand')
                 for x, y, f in ML.one_way_gates(map_id)]
    fac = STATION_MAPS.get(int(map_id))
    if not fac or not tpl:
        entry, ready = structure(map_id, tpl, gs) if tpl else ([], [])
        if int(map_id) in LOW_STATION:
            w, h = map_size(map_id)
            ready.append({'_m': 'SpaceStationCommand', 'posX': w // 2, 'posY': h // 2, 'peaceRadius': 0, 'id': 0,
                          'type': LOW_STATION[int(map_id)]})
        return {'entry': entry, 'ready': ready + gate_msgs + ML.poi_msgs(map_id)}
    cx, cy = STATION_POS.get(int(map_id)) or max(CORNERS, key=lambda c: min((math.hypot(c[0] - g['x'], c[1] - g['y']) for g in gs),
                                                                            default=0))
    turn = (OUTPOST_TURN if int(map_id) in OUTPOST_MAPS else 0) + math.radians(STATION_TURN.get(int(map_id), 0))
    cos, sin = math.cos(turn), math.sin(turn)

    def place(x, y):
        ox, oy = x - TPL_CENTER[0], y - TPL_CENTER[1]
        return int(round(cx + ox * cos - oy * sin)), int(round(cy + ox * sin + oy * cos))

    base = 151000000 + int(map_id) * 100
    ids, entry, ready = {}, [], []
    for m in tpl.get('entry', []):
        if m['_m'] == 'AssetCreateCommand':                    # including the quest giver (34): return to quests at every main station
            ids[m['assetId']] = base + len(ids)
            x, y = place(m['posX'], m['posY'])
            a = quest_giver(dict(m, posX=x, posY=y, factionId=m['factionId'] if m['type']['typeValue'] == QUEST_GIVER else fac,
                                 assetId=ids[m['assetId']]), map_id)
            if int(map_id) in OUTPOST_MAPS and a['type']['typeValue'] in OUTPOST:
                a['type'] = dict(a['type'], typeValue=OUTPOST[a['type']['typeValue']])
            entry.append(a)
    for m in tpl.get('entry', []):
        if m['_m'] == 'MapAssetActionAvailableCommand' and m['mapAssetId'] in ids:
            entry.append(dict(m, mapAssetId=ids[m['mapAssetId']]))
    for m in tpl.get('ready', []):
        if m['_m'] == 'SpaceStationCommand':
            ready.append(dict(m, posX=cx, posY=cy, type=fac))
        elif m['_m'] == 'MapAddPOICommand':
            pid = m['poiId']
            if pid.startswith(('mapAssetRangeZone-', 'questGiver_')):       # the object's approach zone
                old = int(re.split('[-_]', pid)[-1])
                if old not in ids:
                    continue
                pid = pid[:-len(str(old))] + str(ids[old])
            else:
                pid = pid.replace('EIC', FACTION_NAME[fac])
            sc = list(m['shapeCoordinates'])
            sc[0], sc[1] = place(sc[0], sc[1])
            ready.append(dict(m, poiId=pid, shapeCoordinates=sc))
    return {'entry': entry, 'ready': ready + gate_msgs}


# structures outside stations (wiki maps: Mission Control on X-5 and X-BL, Trader on 5-2); the quest giver of the 2-1 station in the save
# (AssetCreateCommand type 34) or its refinery (50) is copied, to the corner farthest from the portals. No Clan Battle Stations (no clans).
# X-4 (1-4, 2-4, 3-4): player report 2026-10-27, Mission Control exists in the real game (its place is not in the source: a point far from the portals,
# adaptation; the model is X-5's marker)
STRUCTURES = {4: 34, 8: 34, 12: 34, 17: 34, 21: 34, 25: 34, 306: 34, 307: 34, 308: 34, 92: 50}
# appearance of the structure: the refinery (50) is drawn in the client with the "refinery_home_<company>" model, it was not visible at all without a company (5-2) (live trial
# 2026-10-17). 5-2's Trader is the client's "station_6" pirate station (lib_assets: "big sausage pirate station", minimap_piratestation on the minimap):
# SpaceStationCommand type 6 (its safe zone is in map_layout.json); trade point ORE_TRADE_INVISIBLE (52,
# "refinery_invisible_0": no model, but it has a click icon and a minimap icon). Decorative station: not a repair/respawn place
# (game.Templates.station skips it).
STRUCTURE_STATION = {92: 6}
STRUCTURE_ASSET_TYPE = {92: 52}
# the pirate HQ in the middle of LoW (low.json: a healing zone around it after the first relay, the boss spawns here): the client's "station_4" LoW station
# (SpaceStationCommand type 4, healthStation on the minimap). Decorative station: no safe zone, not a repair/respawn place.
LOW_STATION = {200: 4}
DECOR_STATION_TYPES = set(STRUCTURE_STATION.values()) | set(LOW_STATION.values())


def structure(map_id, tpl, gs):
    """The only structure of a map without a station -> (entry messages, ready messages)."""
    kind = STRUCTURES.get(int(map_id))
    src = next((m for m in tpl.get('entry', []) if m['_m'] == 'AssetCreateCommand' and m['type']['typeValue'] == kind), None)
    if not kind or not src:
        return [], []
    spots = CORNERS + [(10500, 6550), (10500, 2000), (10500, 11100), (2000, 6550), (19000, 6550)]   # corners, edge middles, center
    cx, cy = ML.structure_pos(map_id) or STATION_POS.get(int(map_id)) or max(spots, key=lambda c: min((math.hypot(c[0] - g['x'], c[1] - g['y']) for g in gs),
                                                                          default=0))
    aid = 151000000 + int(map_id) * 100 + 90
    pos, radius = ML.structure_asset(map_id)      # 5-2: the trade point is next to the station
    ax, ay = pos or (cx, cy)
    entry = [quest_giver(dict(src, assetId=aid, posX=ax, posY=ay, factionId=src['factionId'] if kind == QUEST_GIVER else company(map_id) or 0),
                         map_id)]
    if int(map_id) in STRUCTURE_ASSET_TYPE:
        entry[0]['type'] = dict(src['type'], typeValue=STRUCTURE_ASSET_TYPE[int(map_id)])
    ready = []
    if int(map_id) in STRUCTURE_STATION:          # safe zone of the 5-2 pirate base (map_layout.json safe; world.in_peace)
        peace = next((r for x, y, r in ML.safe_zones(map_id) if (x, y) == (cx, cy)), 0)
        ready.append({'_m': 'SpaceStationCommand', 'posX': cx, 'posY': cy, 'peaceRadius': peace, 'id': 0,
                      'type': STRUCTURE_STATION[int(map_id)]})
    for m in tpl.get('ready', []):                # approach zone (the quest giver's is questGiver_<id>)
        if m['_m'] == 'MapAddPOICommand' and m['poiId'] in ('mapAssetRangeZone-%d' % src['assetId'], 'questGiver_%d' % src['assetId']):
            sc = list(m['shapeCoordinates'])
            sc[0], sc[1], sc[2] = ax, ay, radius or sc[2]
            ready.append(dict(m, poiId=m['poiId'].replace(str(src['assetId']), str(aid)), shapeCoordinates=sc))
    return entry, ready


def quest_giver(m, map_id):
    """The quest giver's model and name by the map's company and base type (only 2-1's is in the save: designId 6, Reginald
    Crowley). The client's lib_assets: questgiver_3/6/9 MMO/EIC/VRU main base (X-1), 4/7/10 outpost (X-8), 5/8/11 beacon (X-5),
    12 Black Light; names eh_character_descr_*."""
    fac, n = company(map_id), name(map_id)
    if m['type']['typeValue'] != QUEST_GIVER or not fac:
        return m
    design = 12 if n.startswith('BL-') else QUEST_GIVER_DESIGN[n[2:]] + 3 * (fac - 1)
    return dict(m, designId=design, userName=BL_QUEST_GIVER_NAME if n.startswith('BL-') else QUEST_GIVER_NAME[fac])


def gates(map_id, faction=None):
    """faction: the player's company (on the friend server each player's own; PLAYER_FACTION if not given): their own company's portals first."""
    fac = faction if faction is not None else PLAYER_FACTION
    # another company's portal is invisible but works (player report 2026-10-27: in the real game all of them can be jumped on the pirate maps);
    # one's own company's comes first: arrival() takes the return portal from the first match
    return sorted(GATES.get(int(map_id), []), key=lambda g: bool(g.get('only_company')) and fac not in (None, g['only_company']))


def arrival(src_map, dst_map, faction=None):
    """In the target map, the position of the portal that leads back to the source map (the ship lands there). faction: the player's company (gates)."""
    back = next((g for g in gates(dst_map, faction) if g['target'] == int(src_map)), None)
    if back:
        return back['x'], back['y']
    w, h = map_size(dst_map)          # one-way entry (5-1, 5-3, 4-4): the true center of the map (large maps)
    return center(dst_map) if ML.of(dst_map).get('center') else (w // 2, h // 2)


def random_arrival(map_id):
    """Random arrival point (5-3's exits lead to 4-4; emu-dark Vector.Random): far from the edges, outside the obstacles."""
    w, h = map_size(map_id)
    return ML.free_spot(map_id, (2000, 2000, w - 2000, h - 2000)) or (w // 2, h // 2)


def name(map_id):
    return NAMES.get(int(map_id), str(map_id))


def company(map_id):
    """The map's company (1 MMO, 2 EIC, 3 VRU: X-n and n-BL) or None (4-X, 5-X, gates: common)."""
    n = name(map_id)
    if n.startswith('BL-') and n[3:] in ('1', '2', '3'):         # the client's name is BL-1 (1-BL)
        return int(n[3:])
    return int(n[0]) if len(n) >= 3 and n[0] in '123' and n[1] == '-' else None


def level_required(map_id, faction):
    """The level needed to enter the map: habitant for one's own company's or a common map, foreign for another company's (maps-config;
    same as the wiki: X-1/X-2 1, X-3 2, 4-X 8-10, X-5 10, X-8 12; another company's X-1 16)."""
    import settings as SET
    if SET.get('no_level_limit'):
        return 0                          # panel: level restrictions off
    hab, foreign = LEVELS.get(int(map_id), (0, 0))
    c = company(map_id)
    return foreign if c and c != faction else hab


def map_size(map_id):
    """The map's size: standard size x the client's maps-config.xml scaleFactor (4-4, 4-5, 5-x 2; GG Hades 0.5)."""
    scale_factor = SCALE.get(int(map_id), 1.0)
    return int(MAP_W * scale_factor), int(MAP_H * scale_factor)


def map_class(map_id):
    """X-n for company maps (1-3 and 2-3 -> X-3), the others their own name."""
    n = name(map_id)
    return 'X-' + n[2:] if len(n) == 3 and n[0] in '123' and n[1] == '-' and n[2].isdigit() else n


def x8_home(faction, level, map_id):
    """The company's X-8 map to respawn at if the map where one died has no station; None (X-1) if the level is below 12 or it is not an upper map."""
    return X8_HOME.get(faction) if level >= 12 and map_class(map_id) in UPPERS else None


# station objects: become clickable when approached (save: at ~500 units MapAssetActionAvailableCommand state 0, state 1 when moving away)
STATION_ASSETS = {46: 'ttip_company_hq', 48: 'ttip_hangar', 50: 'ttip_ore_trade', 52: 'ttip_ore_trade',   # HQ, hangar, refinery (52: invisible)
                  53: 'ttip_instant_repair', 54: 'ttip_instant_repair',     # repair station (main base / outpost; Ö1)
                  47: 'ttip_company_hq', 49: 'ttip_hangar', 51: 'ttip_ore_trade'}     # X-8 outpost (OUTPOST)
REPAIR_ASSETS = (53, 54)         # InstantRepairRequest: instant repair with a repair coupon (world.instant_repair)
ASSET_RANGE = 500
QUEST_GIVER = 34                 # AssetCreateCommand.type: quest giver (save: Reginald Crowley, 2-1)
QUEST_GIVER_DESIGN = {'1': 3, '8': 4, '5': 5, '4': 5}                  # X-1, X-8, X-5: MMO'nunki; EIC +3, VRU +6 (quest_giver)
QUEST_GIVER_NAME = {1: 'Morgus Petterson', 2: 'Reginald Crowley', 3: 'Vanessa Arkadium'}
BL_QUEST_GIVER_NAME = 'Mysterious Outpost'        # official server record 2026-10-27 (2-BL)


def asset_available(asset_id, tip, near, wild=()):
    """Station object (the format in the save): state 0, active, with a hint when near; state 1, empty hint when far. wild: [(%FIELD%, text)]
    (the repair station's coupon counts)."""
    reps = [{'_': 'MessageWildcardReplacementModule', 'wildcard': k, 'replacement': str(v),
             'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': 0}} for k, v in wild]
    lines = [{'_': 'MessageKeyListWildcardModule', 'wildCardReplacements': reps, 'baseKey': tip,
              'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 5}, 'textStyle': 0}] if near else []
    return ('MapAssetActionAvailableCommand', dict(mapAssetId=asset_id, state=0 if near else 1, activatable=near,
                                                   toolTip={'_': 'MessageKeyListWildcardCommand', 'commandList': lines},
                                                   additionalInformation={'_': 'AssetInformationModule'}))


def jumpgate_create(g, faction=None):
    """faction: the player's company; on 5-X another company's portal goes invisible (official server record: not on the minimap, no balloon)."""
    hidden = g.get('invisible') or (g.get('only_company') and faction not in (None, g['only_company']))
    return ('JumpgateCreateCommand', dict(gateId=g['gateId'], factionId=0, designId=g.get('designId', g.get('design', 1)), x=g['x'],
                                          y=g['y'], isVisibleOnMinimap=not (hidden or g.get('hidden')),   # the hidden wormhole on 4-5
                                          showBubble=not hidden, decoratorAssetTypes=g.get('decorations', [])))


# Gate hints (the client's flashres keys). On gates whose target is 0 (that open a window) "%MAP%" stayed empty, the client's name for the maze
# maps is "Escort VRU 1" (live test 2026-10-18). A gate that enters a mode: the mode's own sentence; otherwise
# ttip_jumpgate + %MAP% = the name's key (type 5) or the target map's name in the client (type 6; maps-config.xml name).
MODE_TIPS = {'voyagers': 'ttip_jumpgate_voyagersascentrial', 'trinity': 'ttip_jumpgate_trinitytrials',
             'astral': 'ttip_jumpgate_astralascension', 'ebl': 'ttip_jumpgate_eternal_blacklight',
             'labyrinth': 'ttip_jumpgate_frozenLabyrinth'}
DESIGN_TIPS = {87: 'ttip_jumpgate_astralascension_weapon_1', 88: 'ttip_jumpgate_astralascension_weapon_2',          # Astral rifts
               89: 'ttip_jumpgate_astralascension_generator_1', 90: 'ttip_jumpgate_astralascension_generator_2',
               91: 'ttip_jumpgate_astralascension_ammo_1', 92: 'ttip_jumpgate_astralascension_ammo_2',
               93: 'ttip_jumpgate_astralascension_booster_1', 94: 'ttip_jumpgate_astralascension_booster_1',
               95: 'ttip_jumpgate_astralascension_upgrademodule_1', 96: 'ttip_jumpgate_astralascension_upgrademodule_2',
               97: 'ttip_jumpgate_astralascension_resource_1', 98: 'ttip_jumpgate_astralascension_resource_2',
               99: 'ttip_jumpgate_astralascension_hp_1', 100: 'ttip_jumpgate_astralascension_finalboss'}
MODE_NAMES = {'echoes': 'window_dse_title', 'plutus': 'title_plutus', 'plutus_easy': 'title_plutus', 'invasion': 'title_invasion'}
_CLIENT_MAPS = {}


def client_map_name(map_id):
    """The map name in the client's maps-config.xml (the hint's type 6 value comes from here) or None."""
    if not _CLIENT_MAPS:
        p = os.path.join(HERE, 'data', 'maps-config.xml')
        t = open(p, encoding='utf8').read() if os.path.exists(p) else ''
        _CLIENT_MAPS.update({int(i): n for i, n in re.findall(r'<map id="(\d+)"[^>]*?\bname="([^"]*)"', t)} or {0: None})
    return _CLIENT_MAPS.get(int(map_id or 0))


def gate_tip(g):
    """The portal's hint -> (key, [(placeholder value, type)]): type 5 flashres key, 6 map id, 0 plain text."""
    if g.get('tooltip'):
        return g['tooltip'], ([(str(g['hint_target']), 6)] if g.get('hint_target') else [])
    dest = int(g.get('hint_target') or g.get('target') or 0)
    if not g.get('exit') and dest not in NAMES:                       # a gate that goes outside the galaxy (into a mode, a gate)
        key = DESIGN_TIPS.get(g.get('designId')) or MODE_TIPS.get(g.get('gate'))
        if key:
            return key, []
        if MODE_NAMES.get(g.get('gate')):
            return 'ttip_jumpgate', [(MODE_NAMES[g['gate']], 5)]
    if dest and client_map_name(dest):
        return 'ttip_jumpgate', [(str(dest), 6)]
    if g.get('name'):
        return 'ttip_jumpgate', [(g['name'], 0)]
    return 'faq_jumpgate', []                                           # "Jump gate"


def gate_available(g, near):
    """On approaching/leaving a portal (the format in the save): state 0 + active, or state 1 + not active. Hint "This Jump Gate takes
    you to %MAP%.": in the save %MAP% = the target map's id, type 6 (the client writes the map's name); other gates gate_tip."""
    key, vals = gate_tip(g)
    reps = [{'_': 'MessageWildcardReplacementModule', 'wildcard': '%MAP%', 'replacement': v,
             'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': t}} for v, t in vals]
    tip = {'_': 'MessageKeyListWildcardCommand', 'commandList': [
        {'_': 'MessageKeyListWildcardModule', 'wildCardReplacements': reps, 'baseKey': key,
         'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 5}, 'textStyle': 0}]}
    return ('MapAssetActionAvailableCommand', dict(mapAssetId=g['gateId'], state=0 if near else 1, activatable=near, toolTip=tip,
                                                   additionalInformation={'_': 'AssetInformationModule'}))


def parked(map_id):
    """Can the ship be left on this map (it waits there when changed in the hangar): a known map that is not special (graveyard, LoW)."""
    return map_id in NAMES and map_id not in SPECIAL


def center(map_id):
    """The middle of the map; if the middle is blocked, the layout's 'center' (DSE 3: landing, friendly ship, return portal to the hall)."""
    w, h = map_size(map_id)
    return tuple(ML.of(map_id).get('center') or (w // 2, h // 2))
