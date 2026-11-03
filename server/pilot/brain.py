"""Auto Mode decisions: pure functions over a snapshot of the map (act/base.Base.snapshot builds it), so they can be tested without a client.

Snapshot: {'hero': (x, y), 'R': laser range, 'hp', 'hp_max', 'shield', 'shield_max', 'bounds': (w, h), 'map': id, 'in_peace': bool,
           'npcs': [{'id', 'tip', 'name', 'x', 'y', 'px', 'py' (predicted position), 'engaged' (chasing/firing at the hero), 'aggressive',
                     'notice' (aggression distance), 'fire_range', 'hp', 'hp_max', 'ok' (attackable), 'allowed' (in the hunt list),
                     'priority' (taken first)}],
           'boxes': [{'hash', 'x', 'y', 'kind'}], 'safe': [(x, y, radius)], 'ores': [{'hash', 'tip', 'x', 'y'}]}
Order of priorities in decide(): an alien attacking the hero, the current target, a nearby box, a new target, patrol.
Movement in a fight: kiting at the edge of the laser range (kite_min..kite_max of R): stay still inside the band, otherwise the best point of a
ring around the target, scored by the threats (aliens attacking the hero, aggressive aliens nearby), the map edges and the distance to fly.
Areas drawn on the panel's map (cfg 'work': one rectangle, 'avoid': rectangles; Pilot.hunt_cfg puts this map's in): new targets, boxes and
ore are taken only inside the work area and never inside an area to avoid; movement keeps out of the areas to avoid and inside the work area
(the same weight as a threat zone). cfg 'ignore': alien ids left alone for now (no damage for a while, Pilot.track_target); 'ignore_boxes':
box hashes the ship could not collect."""
import math, random

EDGE = 400                  # keep this far from the map edge (radiation)
RING_POINTS = 16
DANGER_W, PATH_W = 4000, 1500   # a point's score: its depth in threat zones and the depth of the way there, against the distance to fly
PRIORITY_W = 4000           # a priority alien counts as this much closer than it is


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


def in_rect(x, y, r, margin=0):
    return r[0] - margin <= x <= r[2] + margin and r[1] - margin <= y <= r[3] + margin


def takes(x, y, cfg):
    """A target, box or ore at (x, y) may be taken: inside the work area (if one is drawn) and in no area to avoid."""
    w = cfg.get('work')
    return (not w or in_rect(x, y, w)) and not any(in_rect(x, y, a) for a in cfg.get('avoid') or ())


def _rect_depth(x, y, r):
    """0 outside the rectangle, from 0.25 at its edge to 1 toward its middle."""
    if not in_rect(x, y, r):
        return 0.0
    half = max(1.0, min(r[2] - r[0], r[3] - r[1]) / 2)
    return min(1.0, 0.25 + min(x - r[0], r[2] - x, y - r[1], r[3] - y) / half)


def area_cost(x, y, cfg):
    """How much a point breaks the drawn areas: inside an area to avoid, or outside the work area (growing with the distance)."""
    out = sum(_rect_depth(x, y, a) for a in cfg.get('avoid') or ())
    w = cfg.get('work')
    if w and not in_rect(x, y, w):
        dx = max(w[0] - x, 0, x - w[2])
        dy = max(w[1] - y, 0, y - w[3])
        out += 0.25 + min(1.0, math.hypot(dx, dy) / 3000)
    return out


def path_area_cost(ax, ay, bx, by, cfg, steps=8):
    """The share of the straight line a -> b inside the areas to avoid."""
    if not cfg.get('avoid'):
        return 0.0
    return sum(1 for i in range(1, steps + 1) if any(in_rect(ax + (bx - ax) * i / steps, ay + (by - ay) * i / steps, a)
                                                     for a in cfg['avoid'])) / steps


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
    ignore = cfg.get('ignore') or ()
    attackers = [n for n in s['npcs'] if n['ok'] and n['engaged'] and n['id'] not in ignore and (defend or (hunt and n['allowed']))]
    cur = by_id.get(current_id)
    if (cur is not None and cur['ok'] and cur['id'] not in ignore
            and ((cur['engaged'] and (defend or (hunt and cur['allowed']))) or (hunt and not attackers))):
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
    near = [n for n in s['npcs'] if n['ok'] and n['aggressive'] and not n['engaged'] and n['id'] not in (cfg.get('ignore') or ())
            and dist(n['x'], n['y'], hx, hy) <= n['notice'] + cfg['threat_margin']]
    return nearest(near, hx, hy)


def pick_target(s, cfg):
    """The allowed alien with the best score: its distance, plus (avoid_aggressive) a penalty for standing inside other aggressive aliens'
    zones. A group next to the ship is taken before a lone alien across the map (player report: it killed one of four Lordakium sitting
    side by side near aggressive aliens, then flew off to a "clear" one far away); a clear target nearly as close is still preferred.
    Only inside the drawn work area and outside the areas to avoid; a priority alien counts as PRIORITY_W closer."""
    hx, hy = s['hero']
    ignore = cfg.get('ignore') or ()
    cand = [n for n in s['npcs'] if n['ok'] and n['allowed'] and n['id'] not in ignore and takes(n['x'], n['y'], cfg)]
    if not cand:
        return None

    def score(n):
        d = dist(n['x'], n['y'], hx, hy) - (PRIORITY_W if n.get('priority') else 0)
        return d + DANGER_W * danger(n['x'], n['y'], threats(s, cfg, n['id'])) if cfg['avoid_aggressive'] else d
    return min(cand, key=score)


def pick_box(s, cfg, thr):
    hx, hy = s['hero']
    ignore = cfg.get('ignore_boxes') or ()
    boxes = [b for b in s['boxes'] if cfg['boxes'].get(b['kind']) and dist(b['x'], b['y'], hx, hy) <= cfg['box_radius']
             and danger(b['x'], b['y'], thr) == 0 and b['hash'] not in ignore and takes(b['x'], b['y'], cfg)]
    return nearest(boxes, hx, hy)


def kite_point(s, cfg, t, thr):
    """Where to fly while firing at t, or None to stay: inside the band and out of every threat zone, no move."""
    hx, hy = s['hero']
    R = s['R']
    rmin, rmax = cfg['kite_min'] * R, cfg['kite_max'] * R
    d = dist(hx, hy, t['x'], t['y'])
    if rmin <= d <= rmax and danger(hx, hy, thr) == 0 and area_cost(hx, hy, cfg) == 0:
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
        score = ((danger(x, y, thr) + area_cost(x, y, cfg)) * DANGER_W
                 + (path_danger(hx, hy, x, y, thr) + path_area_cost(hx, hy, x, y, cfg)) * PATH_W + dist(hx, hy, x, y))
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
    """A far patrol point away from the threats (inside the work area when one is drawn, out of the areas to avoid)."""
    hx, hy = s['hero']
    thr = threats(s, cfg, None)
    best, best_score = None, None
    lo_x, lo_y, hi_x, hi_y = EDGE + 200, EDGE + 200, s['bounds'][0] - EDGE - 200, s['bounds'][1] - EDGE - 200
    w = cfg.get('work')
    if w:                                           # inside the work area (still off the radiation edge)
        lo_x, lo_y, hi_x, hi_y = max(lo_x, w[0] + 150), max(lo_y, w[1] + 150), min(hi_x, w[2] - 150), min(hi_y, w[3] - 150)
        if lo_x > hi_x:
            lo_x = hi_x = (w[0] + w[2]) / 2
        if lo_y > hi_y:
            lo_y = hi_y = (w[1] + w[3]) / 2
    for _ in range(12):
        a, r = rnd.uniform(0, 2 * math.pi), rnd.uniform(2500, 6000)
        x = max(lo_x, min(hi_x, hx + math.cos(a) * r))
        y = max(lo_y, min(hi_y, hy + math.sin(a) * r))
        score = ((danger(x, y, thr) + area_cost(x, y, cfg)) * DANGER_W
                 + (path_danger(hx, hy, x, y, thr) + path_area_cost(hx, hy, x, y, cfg)) * PATH_W)
        if best_score is None or score < best_score:
            best, best_score = (x, y), score
    return best


def away_point(s, cfg, rnd=random):
    """Low HP on a map with no safe zone: the point 4000 away that is farthest from the aliens attacking the hero (else the aggressive
    ones); None when no alien is a danger."""
    hx, hy = s['hero']
    att = [n for n in s['npcs'] if n['engaged']] or [n for n in s['npcs'] if n['aggressive']]
    if not att:
        return None
    best, best_d = None, None
    for _ in range(16):
        a = rnd.uniform(0, 2 * math.pi)
        x = max(EDGE + 200, min(s['bounds'][0] - EDGE - 200, hx + math.cos(a) * 4000))
        y = max(EDGE + 200, min(s['bounds'][1] - EDGE - 200, hy + math.sin(a) * 4000))
        d = min(dist(x, y, n['x'], n['y']) for n in att) - 2000 * area_cost(x, y, cfg)
        if best_d is None or d > best_d:
            best, best_d = (x, y), d
    return best


def hp_pct(s):
    return 100.0 * s['hp'] / s['hp_max'] if s['hp_max'] else 100.0
