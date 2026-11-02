"""Auto Mode decisions: pure functions over a snapshot of the map (act/base.Base.snapshot builds it), so they can be tested without a client.

Snapshot: {'hero': (x, y), 'R': laser range, 'hp', 'hp_max', 'shield', 'shield_max', 'bounds': (w, h), 'map': id, 'in_peace': bool,
           'npcs': [{'id', 'tip', 'name', 'x', 'y', 'px', 'py' (predicted position), 'engaged' (chasing/firing at the hero), 'aggressive',
                     'notice' (aggression distance), 'fire_range', 'hp', 'hp_max', 'ok' (attackable), 'allowed' (in the hunt list)}],
           'boxes': [{'hash', 'x', 'y', 'kind'}], 'safe': [(x, y, radius)], 'ores': [{'hash', 'tip', 'x', 'y'}]}
Order of priorities in decide(): an alien attacking the hero, the current target, a nearby box, a new target, patrol.
Movement in a fight: kiting at the edge of the laser range (kite_min..kite_max of R): stay still inside the band, otherwise the best point of a
ring around the target, scored by the threats (aliens attacking the hero, aggressive aliens nearby), the map edges and the distance to fly."""
import math, random

EDGE = 400                  # keep this far from the map edge (radiation)
RING_POINTS = 16
DANGER_W, PATH_W = 4000, 1500   # a point's score: its depth in threat zones and the depth of the way there, against the distance to fly


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def threats(s, cfg, target_id):
    """[(x, y, radius)] to keep away from: aliens attacking the hero (their firing range), aggressive ones not attacking yet (their notice distance)."""
    m = cfg['threat_margin']
    out = []
    for n in s['npcs']:
        if n['id'] == target_id or not n['ok']:
            continue
        if n['engaged']:
            out.append((n['x'], n['y'], n['fire_range'] + m))
        elif cfg['avoid_aggressive'] and n['aggressive']:
            out.append((n['x'], n['y'], n['notice'] + m))
    return out


def _depth(d, r):
    """How deep a point at distance d is inside a zone of radius r (0 outside, 1 at the centre)."""
    return (r - d) / r if 0 <= d < r else 0.0


def danger(x, y, thr):
    """0 outside every threat zone; grows toward the zones' centers."""
    return sum(_depth(dist(x, y, tx, ty), r) for tx, ty, r in thr)


def path_danger(ax, ay, bx, by, thr):
    """How deep the straight line a -> b goes into the threat zones."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    out = 0.0
    for tx, ty, r in thr:
        f = max(0.0, min(1.0, ((tx - ax) * dx + (ty - ay) * dy) / l2)) if l2 else 0.0
        out += _depth(dist(ax + f * dx, ay + f * dy, tx, ty), r)
    return out


def in_bounds(x, y, bounds, edge=EDGE):
    w, h = bounds
    return edge <= x <= w - edge and edge <= y <= h - edge


def nearest(items, x, y):
    return min(items, key=lambda k: dist(k['x'], k['y'], x, y)) if items else None


def decide(s, cfg, current_id, hunt=True, boxes=True, defend=True):
    """-> ('fight', npc) | ('box', box) | ('roam', None). hunt=False (on the way somewhere, or a mode that does not hunt): only aliens
    attacking the hero (and the current target while it fights back) and nearby boxes; no new target. boxes=False: no box.
    defend=False: the aliens attacking the hero are not fought for that reason (only if they are targets of the hunt)."""
    hx, hy = s['hero']
    by_id = {n['id']: n for n in s['npcs']}
    attackers = [n for n in s['npcs'] if n['ok'] and n['engaged'] and (defend or (hunt and n['allowed']))]
    cur = by_id.get(current_id)
    if cur is not None and cur['ok'] and ((cur['engaged'] and (defend or (hunt and cur['allowed']))) or (hunt and not attackers)):
        return 'fight', cur                                  # keep the target, unless something else attacks while it does not
    if attackers:
        return 'fight', nearest(attackers, hx, hy)
    thr = threats(s, cfg, None)
    box = pick_box(s, cfg, thr) if boxes else None
    if box is not None:
        return 'box', box
    t = pick_target(s, cfg) if hunt else None
    if t is not None:
        return 'fight', t
    return 'roam', None


def pick_aggressive(s, cfg):
    """On the way somewhere (clear_path): the nearest aggressive alien close enough to engage the ship (its notice distance plus the
    margin), whatever the hunt list says; None if there is none."""
    hx, hy = s['hero']
    near = [n for n in s['npcs'] if n['ok'] and n['aggressive'] and not n['engaged']
            and dist(n['x'], n['y'], hx, hy) <= n['notice'] + cfg['threat_margin']]
    return nearest(near, hx, hy)


def pick_target(s, cfg):
    """The allowed alien with the best score: its distance, plus (avoid_aggressive) a penalty for standing inside other aggressive aliens'
    zones. A group next to the ship is taken before a lone alien across the map (player report: it killed one of four Lordakium sitting
    side by side near aggressive aliens, then flew off to a "clear" one far away); a clear target nearly as close is still preferred."""
    hx, hy = s['hero']
    cand = [n for n in s['npcs'] if n['ok'] and n['allowed']]
    if not cand:
        return None
    if not cfg['avoid_aggressive']:
        return nearest(cand, hx, hy)
    return min(cand, key=lambda n: dist(n['x'], n['y'], hx, hy) + DANGER_W * danger(n['x'], n['y'], threats(s, cfg, n['id'])))


def pick_box(s, cfg, thr):
    hx, hy = s['hero']
    boxes = [b for b in s['boxes'] if cfg['boxes'].get(b['kind']) and dist(b['x'], b['y'], hx, hy) <= cfg['box_radius']
             and danger(b['x'], b['y'], thr) == 0]
    return nearest(boxes, hx, hy)


def kite_point(s, cfg, t, thr):
    """Where to fly while firing at t, or None to stay: inside the band and out of every threat zone, no move."""
    hx, hy = s['hero']
    R = s['R']
    rmin, rmax = cfg['kite_min'] * R, cfg['kite_max'] * R
    d = dist(hx, hy, t['x'], t['y'])
    if rmin <= d <= rmax and danger(hx, hy, thr) == 0:
        return None
    ideal = (rmin + rmax) / 2
    tx, ty = t['px'], t['py']                      # where the target will be: the ship arrives there a little later
    base = math.atan2(hy - ty, hx - tx)
    best, best_score = None, None
    for k in range(RING_POINTS):
        a = base + 2 * math.pi * k / RING_POINTS
        x, y = tx + math.cos(a) * ideal, ty + math.sin(a) * ideal
        if not in_bounds(x, y, s['bounds']):
            continue
        score = danger(x, y, thr) * DANGER_W + path_danger(hx, hy, x, y, thr) * PATH_W + dist(hx, hy, x, y)
        if best_score is None or score < best_score:
            best, best_score = (x, y), score
    if best is None:                                   # target at the map edge: straight toward it, up to the ideal distance
        f = max(0.0, d - ideal) / d if d else 0.0
        best = (hx + (t['x'] - hx) * f, hy + (t['y'] - hy) * f)
    return best


def safe_point(s):
    """A point inside the nearest safe zone (station, portal), toward the hero; None if the map has none."""
    hx, hy = s['hero']
    if not s['safe']:
        return None
    x, y, r = min(s['safe'], key=lambda z: dist(z[0], z[1], hx, hy) - z[2])
    d = dist(hx, hy, x, y)
    if d <= r * 0.5:
        return hx, hy
    f = (r * 0.4) / d if d else 0.0
    return x + (hx - x) * f, y + (hy - y) * f


def roam_point(s, cfg, rnd=random):
    """A far patrol point away from the threats."""
    hx, hy = s['hero']
    thr = threats(s, cfg, None)
    best, best_score = None, None
    for _ in range(12):
        a, r = rnd.uniform(0, 2 * math.pi), rnd.uniform(2500, 6000)
        x = max(EDGE + 200, min(s['bounds'][0] - EDGE - 200, hx + math.cos(a) * r))
        y = max(EDGE + 200, min(s['bounds'][1] - EDGE - 200, hy + math.sin(a) * r))
        score = danger(x, y, thr) * DANGER_W + path_danger(hx, hy, x, y, thr) * PATH_W
        if best_score is None or score < best_score:
            best, best_score = (x, y), score
    return best


def hp_pct(s):
    return 100.0 * s['hp'] / s['hp_max'] if s['hp_max'] else 100.0
