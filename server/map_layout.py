"""Map layout (data/map_layout.json): the pirate maps (5-1, 5-2, 5-3) and the Black Light maps (1-BL, 2-BL, 3-BL).

Obstacles go to the client as MapAddPOICommand NO_ACCESS rectangles: the client stops the ship at the edge (PoiZoneManager.CheckCollisions,
'NOA' zones) and draws them on the map with their design (asteroid/scrap) and hatched on the minimap. For shapes other than circles the
shapeCoordinates are flat (x, y) pairs (MapAddPoiCommandHandler.Handle); a rectangle's four corners are (x0,y0),(x1,y0),(x1,y1),(x0,y1),
in the official server's order. On the server side: spawn, ore and mine positions are outside the obstacles; on a roaming map (X-BL)
aliens walk around the obstacles with A* on a grid (on pirate maps the aliens go straight as before: fandom "aliens ... go through
them"); portal positions and the arrival point on the target map; the Palladium area (ShieldDamage POI); mine fields (Mines POIs); safe
zones (the 5-2 pirate base).
"""
import heapq, json, math, os, random
import game_data as DATA

HERE = os.path.dirname(os.path.abspath(__file__))
_D = DATA.load('map_layout.json')
MAPS = {int(k): v for k, v in _D['maps'].items()}
_WALLS = {m: [tuple(e[1:5]) for e in d.get('obstacles', [])] for m, d in MAPS.items()}
MINE = _D['mine']
NO_ACCESS, SHIELD_DAMAGE, MINES = 5, 3, 10     # POIType (official server record: Palladium area "ShieldDamage", mine field "Mines1")
POLYGON, RECTANGLE = 1, 2                       # the client's ShapeType (CIRCLE 0, POLYGON 1, RECTANGLE 2)
NEBULA = 5                                      # POIDesign: the Palladium area's fog
CELL = 200                                      # cell of the roaming grid
SHIP_PAD = 150                                  # margin an alien keeps from obstacles when spawning
NAV_PAD = 60                                    # margin when roaming: keep 2-BL's 300-unit passage on the left edge open (the player's
                                                # ship hits an obstacle as a point, passes through the narrow passage)


def of(map_id):
    return MAPS.get(int(map_id), {})


def walls(map_id):
    """Obstacle rectangles [(x0, y0, x1, y1)]."""
    return _WALLS.get(int(map_id), [])


def _poi(pid, ptype, design, rect, shape=RECTANGLE, coords=None):
    x0, y0, x1, y1 = rect
    return {'_m': 'MapAddPOICommand', 'inverted': False, 'poiTypeSpecification': '',
            'poiType': {'_': 'POITypeModule', 'typeValue': ptype}, 'shape': shape, 'active': True,
            'design': {'_': 'POIDesignModule', 'designValue': design}, 'poiId': pid,
            'shapeCoordinates': coords or [int(x0), int(y0), int(x1), int(y0), int(x1), int(y1), int(x0), int(y1)]}


def poi_msgs(map_id):
    """The zones in the map's ready bundle: obstacles (polygons as they are), the Palladium area, mine fields and other zones
    (the 5-2 station's Equippable Zone) (map_links.map_world)."""
    d = of(map_id)
    out = [_poi(e[0], NO_ACCESS, e[5], e[1:5], *((POLYGON, e[6]) if len(e) > 6 else ())) for e in d.get('obstacles', [])]
    if 'palladium' in d:
        out.append(_poi(d['palladium']['id'], SHIELD_DAMAGE, NEBULA, d['palladium']['area']))
    out += [_poi('Mines%d' % (i + 1), MINES, 0, r) for i, r in enumerate(d.get('mine_fields', []))]
    out += [_poi(pid, t, design, (0, 0, 0, 0), shape, coords) for pid, t, shape, design, coords in d.get('zones', [])]
    return out


def gate_pos(map_id, key):
    """The portal's position in the layout or None (while map_links.GATES loads)."""
    p = of(map_id).get('portals', {}).get(str(key))
    return tuple(p) if p else None


def arrival(map_id, key):
    """The portal's arrival point on the target map: (x, y), 'random' or None (next to the return portal)."""
    v = of(map_id).get('arrival', {}).get(str(key))
    return tuple(v) if isinstance(v, list) else v


def one_way_gates(map_id):
    """The map's one-way arrival portals [(x, y, company)] (5-X: design 52; map_links.map_world)."""
    return [tuple(v) for v in of(map_id).get('arrival_portals', [])]


def design_pos(map_id, design):
    """The position of a gate or mode portal on this map (by design; official server record: 2-1, 2-8) or None (world.fit_gate)."""
    p = of(map_id).get('design_spot', {}).get(str(design))
    return tuple(p) if p else None


def structure_pos(map_id):
    p = of(map_id).get('structure')
    return tuple(p) if p else None


def structure_asset(map_id):
    """The position of the structure's entity (the 5-2 trade point) and the radius of its approach zone -> ((x, y) or None, radius or
    None)."""
    d = of(map_id)
    return (tuple(d['structure_asset']) if 'structure_asset' in d else None), d.get('structure_radius')


def lairs(map_id):
    """The type's fixed spawn points (lairs): {type: [[x, y], …]}."""
    return of(map_id).get('lairs', {})


def safe_zones(map_id):
    return of(map_id).get('safe', [])


def gate_peace_radius(map_id, default):
    return of(map_id).get('portal_safe', default)


def in_safe(map_id, x, y, margin=0):
    """Is it in the layout's safe zone (the 5-2 pirate base)."""
    return any(math.hypot(x - cx, y - cy) <= r + margin for cx, cy, r in safe_zones(map_id))


def blocked(map_id, x, y, pad=0):
    return any(x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad for x0, y0, x1, y1 in walls(map_id))


def _seg_hits(ax, ay, bx, by, r):
    """Does the line segment cross the rectangle (Liang-Barsky)."""
    x0, y0, x1, y1 = r
    dx, dy = bx - ax, by - ay
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def clear(map_id, ax, ay, bx, by, pad=SHIP_PAD):
    return not any(_seg_hits(ax, ay, bx, by, (x0 - pad, y0 - pad, x1 + pad, y1 + pad)) for x0, y0, x1, y1 in walls(map_id))


def free_spot(map_id, rect, pad=SHIP_PAD, tries=40):
    """A random point in the rectangle outside obstacles, or None."""
    x0, y0, x1, y1 = rect
    for _ in range(tries):
        x, y = int(random.uniform(x0, x1)), int(random.uniform(y0, y1))     # the point being checked is the given point (rounding must not exceed the margin)
        if not blocked(map_id, x, y, pad):
            return x, y
    return None


def navigates(map_id):
    return bool(of(map_id).get('roaming'))


_GRIDS = {}


def _grid(map_id, w, h):
    key = (int(map_id), w, h)
    if key not in _GRIDS:
        nx, ny = int(math.ceil(w / CELL)), int(math.ceil(h / CELL))
        g = [[False] * nx for _ in range(ny)]
        for x0, y0, x1, y1 in walls(map_id):
            for cy in range(max(0, int((y0 - NAV_PAD) // CELL)), min(ny, int((y1 + NAV_PAD) // CELL) + 1)):
                for cx in range(max(0, int((x0 - NAV_PAD) // CELL)), min(nx, int((x1 + NAV_PAD) // CELL) + 1)):
                    g[cy][cx] = True
        _GRIDS[key] = (g, nx, ny)
    return _GRIDS[key]


def _nearest_free(g, nx, ny, c):
    cx, cy = c
    for r in range(1, max(nx, ny)):
        for dy in range(-r, r + 1):
            for dx in (-r, r) if abs(dy) != r else range(-r, r + 1):
                x, y = cx + dx, cy + dy
                if 0 <= x < nx and 0 <= y < ny and not g[y][x]:
                    return x, y
    return c


def waypoint(map_id, w, h, ax, ay, bx, by):
    """Roaming: the first waypoint of the path to the target (the target itself if there is no obstacle). 8-direction A* on the grid, the
    path is shortened up to the first non-visible point; if the target is inside an obstacle, to the nearest free cell, if there is no
    path, to the cell nearest the target that can be reached (does not go through a wall)."""
    if clear(map_id, ax, ay, bx, by, NAV_PAD):
        return bx, by
    g, nx, ny = _grid(map_id, w, h)
    cell = lambda x, y: (min(nx - 1, max(0, int(x // CELL))), min(ny - 1, max(0, int(y // CELL))))
    center = lambda c: (c[0] * CELL + CELL / 2, c[1] * CELL + CELL / 2)
    s, t = cell(ax, ay), cell(bx, by)
    if g[s[1]][s[0]]:
        return center(_nearest_free(g, nx, ny, s))       # inside an obstacle (spawn place, pushed): get out to the nearest free space
    if g[t[1]][t[0]]:
        t = _nearest_free(g, nx, ny, t)
        bx, by = center(t)
    came, cost = {s: None}, {s: 0.0}
    todo = [(0.0, s)]
    near = s                                              # the cell nearest the target that was reached
    while todo:
        _, c = heapq.heappop(todo)
        if c == t:
            break
        if math.hypot(t[0] - c[0], t[1] - c[1]) < math.hypot(t[0] - near[0], t[1] - near[1]):
            near = c
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            n = (c[0] + dx, c[1] + dy)
            if not (0 <= n[0] < nx and 0 <= n[1] < ny) or g[n[1]][n[0]]:
                continue
            if dx and dy and (g[c[1]][n[0]] or g[n[1]][c[0]]):
                continue                                  # does not cut through a corner
            k = cost[c] + (1.4142 if dx and dy else 1.0)
            if k < cost.get(n, 1e18):
                cost[n], came[n] = k, c
                heapq.heappush(todo, (k + math.hypot(t[0] - n[0], t[1] - n[1]), n))
    if t not in came:
        t = near                                          # no path: to the place nearest the target on this side of the wall
        bx, by = center(t)
    path = [t]
    while came[path[-1]] is not None:
        path.append(came[path[-1]])
    path.reverse()                                        # s ... t
    best = center(path[1]) if len(path) > 1 else (bx, by)
    for c in path[1:]:
        p = center(c)
        if not clear(map_id, ax, ay, *p, pad=NAV_PAD):
            break
        best = p
    if best == center(t) and clear(map_id, ax, ay, bx, by, NAV_PAD):
        return bx, by
    return best


def mine_spots(map_id, gates, n=None):
    """Positions of mines scattered over the mine fields: outside obstacles and portals (MINE['count'] per field)."""
    out = []
    for rect in of(map_id).get('mine_fields', []):
        for _ in range(MINE['count'] if n is None else n):
            p = free_spot(map_id, _in_map(map_id, rect), pad=100)
            if p and all(math.hypot(p[0] - g['x'], p[1] - g['y']) > MINE['portal_far'] for g in gates):
                out.append(p)
    return out


def _in_map(map_id, r):
    """The part of a mine field inside the map (the fields in the record spill outside the map: y -1,000..28,000 in 5-1)."""
    import map_links as H
    w, h = H.map_size(map_id)
    return max(r[0], 0), max(r[1], 0), min(r[2], w), min(r[3], h)


def mine_field_of(map_id, x, y):
    """The part inside the map of the mine field containing (x, y) or None (the exploded mine's replacement is in the same field)."""
    r = next((r for r in of(map_id).get('mine_fields', []) if r[0] <= x <= r[2] and r[1] <= y <= r[3]), None)
    return r and _in_map(map_id, r)
