"""Walls (map_layout.json obstacles: 5-1, 5-2, 5-3, the Black Light maps, LoW, DSE 3): the client stops the ship at a wall's edge, so the
bot flies around them. A grid of CELL units, a cell blocked when it touches a wall widened by PAD; A* on it (8 directions, no corner cut),
then the path is pulled tight (straight lines between the corners that see each other). Pure: map_layout gives the walls.
zones: circles (x, y, radius) avoided the same way, on any map: the firing range of the immobile aliens (Mindfire Behemoth, Invoke XVI;
brain.static_zones). A zone the goal is in does not count for that way (the portal, the alien hunted there); a ship inside one flies out
by the nearest way.
  route()   the corners to fly through, up to the target (or the reachable place nearest to it);
  length()  how far the ship really flies to a point (a target or box behind a wall is farther than it looks; cached a few seconds)."""
import heapq, math, time

import map_layout as ML

CELL = 200
PAD = 60                      # the ship is a point for the client's collision: the margin of the aliens' own paths (map_layout.NAV_PAD)
MAX_STEPS = 30000             # A* gives up beyond this many cells (no path: the reachable cell nearest to the target)
LENGTH_SEC = 3.0              # length() results are kept this long, for a ship within the same FROM_CELL square
FROM_CELL = 800
DETOUR = 1.5
OUT = 150                     # out of a zone: this far past its edge
_GRIDS, _LENGTHS = {}, {}


def has(map_id, zones=()):
    return bool(zones) or bool(ML.walls(map_id))


def norm(zones):
    """Zones as a stable key (to the 50 units)."""
    return tuple(sorted((int(x) // 50 * 50, int(y) // 50 * 50, int(r) // 50 * 50) for x, y, r in zones))


def in_zone(x, y, zones):
    return any(math.hypot(x - zx, y - zy) < r for zx, zy, r in zones)


def _seg_dist(cx, cy, ax, ay, bx, by):
    """The distance from (cx, cy) to the segment a -> b."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    f = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / l2)) if l2 else 0.0
    return math.hypot(ax + f * dx - cx, ay + f * dy - cy)


def clear(map_id, ax, ay, bx, by, zones=()):
    """The straight line a -> b touches no wall and goes into no zone."""
    return ML.clear(map_id, ax, ay, bx, by, PAD) and not any(_seg_dist(x, y, ax, ay, bx, by) < r for x, y, r in zones)


def blocked(map_id, x, y, zones=()):
    return ML.blocked(map_id, x, y, PAD) or in_zone(x, y, zones)


def _grid(map_id, w, h, zones=()):
    key = (int(map_id), int(w), int(h), zones)
    if key not in _GRIDS:
        if len(_GRIDS) > 40:
            _GRIDS.clear()
        nx, ny = int(math.ceil(w / CELL)), int(math.ceil(h / CELL))
        if zones:
            g = [row[:] for row in _grid(map_id, w, h)[0]]
        else:
            g = [[False] * nx for _ in range(ny)]
            for x0, y0, x1, y1 in ML.walls(map_id):
                for cy in range(max(0, int((y0 - PAD) // CELL)), min(ny, int((y1 + PAD) // CELL) + 1)):
                    for cx in range(max(0, int((x0 - PAD) // CELL)), min(nx, int((x1 + PAD) // CELL) + 1)):
                        g[cy][cx] = True
        for zx, zy, r in zones:                           # a cell whose square comes inside the circle
            for cy in range(max(0, int((zy - r) // CELL)), min(ny, int((zy + r) // CELL) + 1)):
                for cx in range(max(0, int((zx - r) // CELL)), min(nx, int((zx + r) // CELL) + 1)):
                    qx = max(cx * CELL, min(zx, cx * CELL + CELL))
                    qy = max(cy * CELL, min(zy, cy * CELL + CELL))
                    if math.hypot(qx - zx, qy - zy) < r:
                        g[cy][cx] = True
        _GRIDS[key] = (g, nx, ny)
    return _GRIDS[key]


def _free_near(g, nx, ny, c, seen=None):
    """The free cell nearest to c (c itself when free); seen(cell) -> whether the point can fly straight to it (the nearest one in
    sight first, else the nearest one)."""
    if not g[c[1]][c[0]]:
        return c
    first = None
    for r in range(1, max(nx, ny)):
        for dy in range(-r, r + 1):
            for dx in (-r, r) if abs(dy) != r else range(-r, r + 1):
                x, y = c[0] + dx, c[1] + dy
                if 0 <= x < nx and 0 <= y < ny and not g[y][x]:
                    if seen is None or seen((x, y)):
                        return x, y
                    first = first or (x, y)
        if first is not None and r >= 3:
            return first
    return first or c


def _center(c):
    return c[0] * CELL + CELL / 2, c[1] * CELL + CELL / 2


def _cells(map_id, w, h, ax, ay, bx, by, zones=()):
    """A* from a's cell to b's -> (the cells s .. t, whether t is b's own cell)."""
    g, nx, ny = _grid(map_id, w, h, zones)
    cell = lambda x, y: (min(nx - 1, max(0, int(x // CELL))), min(ny - 1, max(0, int(y // CELL))))
    s = _free_near(g, nx, ny, cell(ax, ay), lambda c: clear(map_id, ax, ay, *_center(c), zones))
    goal = cell(bx, by)
    t = _free_near(g, nx, ny, goal, lambda c: clear(map_id, bx, by, *_center(c), zones))
    came, cost = {s: None}, {s: 0.0}
    todo, near, steps = [(0.0, s)], s, 0
    while todo and steps < MAX_STEPS:
        _, c = heapq.heappop(todo)
        steps += 1
        if c == t:
            break
        if math.hypot(t[0] - c[0], t[1] - c[1]) < math.hypot(t[0] - near[0], t[1] - near[1]):
            near = c
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            n = (c[0] + dx, c[1] + dy)
            if not (0 <= n[0] < nx and 0 <= n[1] < ny) or g[n[1]][n[0]]:
                continue
            if dx and dy and (g[c[1]][n[0]] or g[n[1]][c[0]]):
                continue                                  # no cutting through a wall's corner
            k = cost[c] + (1.4142 if dx and dy else 1.0)
            if k < cost.get(n, 1e18):
                cost[n], came[n] = k, c
                heapq.heappush(todo, (k + math.hypot(t[0] - n[0], t[1] - n[1]), n))
    if t not in came:
        t = near
    path = [t]
    while came[path[-1]] is not None:
        path.append(came[path[-1]])
    path.reverse()
    return path, t == goal


def own(zones, bx, by):
    """The zones for a way to b: the one b is in does not count."""
    return norm(z for z in zones if not in_zone(bx, by, (z,)))


def route(map_id, w, h, ax, ay, bx, by, zones=()):
    """The points to fly through from a to b: [b] when the line is clear, else the corners of the way around the walls (and zones),
    ending at b (or, when b is inside a wall or out of reach, at the free place nearest to it)."""
    zones = own(zones, bx, by)
    pre = []
    for _ in range(3):                                    # inside a zone: first straight out of it, away from its center
        z = next((z for z in zones if in_zone(ax, ay, (z,))), None)
        if z is None:
            break
        zx, zy, r = z
        a = math.atan2(ay - zy, ax - zx) if (ax, ay) != (zx, zy) else 0.0
        ax, ay = zx + math.cos(a) * (r + OUT), zy + math.sin(a) * (r + OUT)
        pre.append((ax, ay))
    if pre:
        return pre + route(map_id, w, h, ax, ay, bx, by, zones)
    if clear(map_id, ax, ay, bx, by, zones):
        return [(bx, by)]
    cells, _ = _cells(map_id, w, h, ax, ay, bx, by, zones)
    pts = [_center(c) for c in cells]
    if not blocked(map_id, bx, by, zones) and clear(map_id, pts[-1][0], pts[-1][1], bx, by, zones):
        pts.append((bx, by))                              # the goal itself, in sight of the last cell
    out, here = [], (ax, ay)
    i = 0
    while i < len(pts):                                   # pulled tight: from here, the farthest point still in sight
        j = i
        while j + 1 < len(pts) and clear(map_id, here[0], here[1], *pts[j + 1], zones):
            j += 1
        out.append(pts[j])
        here, i = pts[j], j + 1
    return out


def length(map_id, w, h, ax, ay, bx, by, now=None, deadline=None, zones=()):
    """The distance the ship flies from a to b around the walls and zones (straight when nothing is in the way). deadline
    (time.perf_counter): past it, a way not worked out yet counts as DETOUR times the straight line (the bot's step stays short under the
    world lock)."""
    straight = math.hypot(bx - ax, by - ay)
    zones = own(zones, bx, by)
    if clear(map_id, ax, ay, bx, by, zones):
        return straight
    now = time.time() if now is None else now
    key = (int(map_id), int(ax // FROM_CELL), int(ay // FROM_CELL), int(bx // CELL), int(by // CELL), zones)
    hit = _LENGTHS.get(key)
    if hit and now - hit[1] <= LENGTH_SEC:
        return hit[0]
    if deadline is not None and time.perf_counter() > deadline:
        return straight * DETOUR
    if len(_LENGTHS) > 500:
        for k in [k for k, v in _LENGTHS.items() if now - v[1] > LENGTH_SEC]:
            del _LENGTHS[k]
    d, here = 0.0, (ax, ay)
    for p in route(map_id, w, h, ax, ay, bx, by, zones):
        d += math.hypot(p[0] - here[0], p[1] - here[1])
        here = p
    d += math.hypot(bx - here[0], by - here[1]) * 3     # not reachable all the way: the rest counts three times
    _LENGTHS[key] = (d, now)
    return d
