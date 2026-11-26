"""Auto Mode decisions: pure functions over a snapshot of the map (act/base.Base.snapshot builds it), so they can be tested without a client.

Snapshot: {'hero': (x, y), 'R': laser range, 'hp', 'hp_max', 'shield', 'shield_max', 'bounds': (w, h), 'map': id, 'in_peace': bool,
           'npcs': [{'id', 'tip', 'name', 'x', 'y', 'px', 'py' (predicted position), 'engaged' (chasing/firing at the hero), 'aggressive',
                     'notice' (aggression distance), 'fire_range', 'hp', 'hp_max', 'ok' (attackable), 'allowed' (a target of the hunt),
                     'forbidden' (an active quest fails if it is destroyed: never fired at), 'priority' (taken first)}],
           'boxes': [{'hash', 'x', 'y', 'kind'}], 'safe': [(x, y, radius)], 'ores': [{'hash', 'tip', 'x', 'y'}]}
Order of priorities in decide(): a hunted alien attacking the hero, the main target (the current one; attacked, the best of the hunt) that
the ship flies to while firing at the aliens attacking it on the way (defend_shot), (defend, no target of the hunt) an alien attacking the
hero, a nearby box, a new target, patrol.
Movement in a fight: kiting at the edge of the laser range (kite_min..kite_max of R): stay still inside the band, otherwise the best point of a
ring around the target, scored by the threats (aliens attacking the hero, aggressive aliens nearby), the map edges and the distance to fly.
Areas drawn on the panel's map (cfg 'work': one rectangle, 'avoid': rectangles; Pilot.hunt_cfg puts this map's in): new targets, boxes and
ore are taken only inside the work area and never inside an area to avoid; movement keeps out of the areas to avoid and inside the work area
(the same weight as a threat zone). cfg 'ignore': alien ids left alone for now (no damage for a while, Pilot.track_target); 'ignore_boxes':
box hashes the ship could not collect.
Walls (snapshot 'way', 'walled', 'clear'; only on a map with walls, act/base.wall_view): targets and boxes are compared by the distance
really flown around the walls (a near one behind a wall comes after a farther one in direct reach), movement points are never inside a wall
and a point the ship cannot fly straight to costs more.
Immobile aliens (Mindfire Behemoth, Invoke XVI: 'static'; snapshot 'statics', their firing range plus the margin): always a threat zone, not
fought in. A target that can be fired at from outside its zone is (kite_point keeps out of it); one deep inside needs a lure
(tasks/lure.py), only when can_lure (HP and the immobile alien's shots), and comes after the others."""
import math, random

EDGE = 400                  # keep this far from the map edge (radiation)
RING_POINTS = 16
DANGER_W, PATH_W = 4000, 1500   # a point's score: its depth in threat zones and the depth of the way there, against the distance to fly
PRIORITY_W = 4000           # a priority alien counts as this much closer than it is
WAY_CHECK = 6               # on a map with walls: the distance flown around them is worked out for this many best candidates
LURE_HP = 70                # % HP: below it the ship does not go into an immobile alien's zone to draw a target out
LURE_HITS = 4               # a lure only if HP + shield take this many shots of the immobile alien (Mindfire Behemoth: 145k)
LURE_W = 6000               # a target only a lure can reach counts as this much farther
DIP_HP, DIP_HITS = 70, 20   # a dip into a short rocket range (rocket_band): HP at this % or more, HP + shield for this many of the target's shots
DIP_IN, DIP_OUT = 0.96, 0.995    # the dip's band, share of the rocket's range (just inside it: the least time in the alien's range)


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def walled(s, x, y):
    """The point is inside a wall (a map with walls only)."""
    f = s.get('walled')
    return bool(f) and f(x, y)


def wall_cost(s, ax, ay, bx, by):
    """1 when a wall stands on the straight line a -> b (the ship flies around it), else 0."""
    f = s.get('clear')
    return 0 if not f or f(ax, ay, bx, by) else 1


def by_way(s, items, key):
    """The best of items by key(item, distance): by the straight distance, then (a map with walls) the WAY_CHECK best again by the
    distance really flown."""
    if not items:
        return None
    hx, hy = s['hero']
    ranked = sorted(items, key=lambda it: key(it, dist(it['x'], it['y'], hx, hy)))
    way = s.get('way')
    if not way:
        return ranked[0]
    return min(ranked[:WAY_CHECK], key=lambda it: key(it, way(it['x'], it['y'])))


def static_zones(npcs, margin):
    """The firing zones of the immobile aliens that are not targets of the hunt: [(x, y, radius)]."""
    return [(n['x'], n['y'], n['fire_range'] + margin) for n in npcs if n.get('static') and not n['allowed']]


def threats(s, cfg, target_id):
    """[(x, y, radius)] to keep away from: aliens attacking the hero (their firing range), aggressive ones not attacking yet (their notice
    distance), the immobile ones always (their firing range)."""
    return [z for i, z in _threats(s, cfg) if i != target_id]      # an alien that cannot be attacked still shoots


def _threats(s, cfg):
    """threats() of every alien, with its id: [(id, (x, y, radius))]."""
    m = cfg['threat_margin']
    out = []
    for n in s['npcs']:
        if n.get('static') and not n['allowed']:
            out.append((n['id'], (n['x'], n['y'], n['fire_range'] + m)))
        elif n['engaged']:
            out.append((n['id'], (n['x'], n['y'], n['fire_range'] + m)))
        elif cfg['avoid_aggressive'] and n['aggressive']:
            out.append((n['id'], (n['x'], n['y'], n['notice'] + m)))
    return out


def danger_but(s, cfg):
    """-> f(x, y, id): danger(x, y, threats(s, cfg, id)), the same sum term by term (in the same order), from a grid of the zones: a zone
    whose cell is not next to the point's is farther than its radius (it adds exactly 0), so a call costs the nearby zones only
    (pick_target scores every alien: threats() for each was O(n²), 5 ms for 300 aliens)."""
    thr = _threats(s, cfg)
    cell = max([z[2] for _, z in thr], default=0) + 1.0      # wider than every radius (the float division keeps its margin)
    grid = {}
    for k, (i, (x, y, r)) in enumerate(thr):
        grid.setdefault((math.floor(x / cell), math.floor(y / cell)), []).append(k)

    def f(x, y, uid):
        cx, cy = math.floor(x / cell), math.floor(y / cell)
        near = sorted(k for dx in (-1, 0, 1) for dy in (-1, 0, 1) for k in grid.get((cx + dx, cy + dy), ()))
        return sum(_depth(dist(x, y, tx, ty), r) for i, (tx, ty, r) in (thr[k] for k in near) if i != uid)
    return f


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
    defend=False: the aliens attacking the hero are not fought for that reason (only if they are targets of the hunt).
    The hunt's own aliens attacking come first, then the hunt's main target (the current one while it can be fought, else the best one):
    the ship flies to it and (defend on) fires at the aliens attacking it on the way (defend_shot). With no target of the hunt the aliens
    attacking the ship are fought back (defend on) as they come."""
    hx, hy = s['hero']
    by_id = {n['id']: n for n in s['npcs']}
    ignore = cfg.get('ignore') or ()

    def fightable(n):
        return n is not None and n['ok'] and n['id'] not in ignore and not n.get('forbidden')

    attackers = [n for n in s['npcs'] if fightable(n) and n['engaged'] and (defend or (hunt and n['allowed']))]
    cur = by_id.get(current_id)
    cur = cur if fightable(cur) else None
    own = [n for n in attackers if hunt and n['allowed']]
    if own:
        return 'fight', cur if cur in own else nearest(own, hx, hy)
    if hunt and cur is not None and cur['allowed']:
        return 'fight', cur                                  # the main target, kept until destroyed (defend_shot: the attackers on the way)
    if hunt and attackers:
        main = pick_target(s, cfg)                           # attacked with no target yet: the best of the hunt becomes the main one
        if main is not None:
            return 'fight', main
    if attackers:
        return 'fight', cur if cur in attackers else nearest(attackers, hx, hy)
    if cur is not None and hunt:
        return 'fight', cur                                  # a target the player picked by hand stays while nothing attacks
    thr = threats(s, cfg, None)
    box = pick_box(s, cfg, thr) if boxes else None
    if box is not None:
        return 'box', box
    t = pick_target(s, cfg) if hunt else None
    if t is not None:
        return 'fight', t
    return 'roam', None


def defend_shot(s, cfg, main, shot_id, defend=True):
    """What the lasers fire at while the ship flies to its main target: the main target once it is within laser range, else (defend) an
    alien attacking the ship within range (the one already fired at while it stays in range, else the nearest), else the main target
    still (out of range the lasers do not fire: the ship keeps flying to it, locked on it)."""
    hx, hy = s['hero']
    R = s['R']
    if dist(hx, hy, main['x'], main['y']) <= R or not defend:
        return main
    ignore = cfg.get('ignore') or ()
    near = [n for n in s['npcs'] if n['ok'] and n['engaged'] and n['id'] != main['id'] and n['id'] not in ignore
            and not n.get('forbidden') and dist(hx, hy, n['x'], n['y']) <= R]
    keep = next((n for n in near if n['id'] == shot_id), None)
    return keep or nearest(near, hx, hy) or main


def pick_aggressive(s, cfg):
    """On the way somewhere (clear_path): the nearest aggressive alien close enough to engage the ship (its notice distance plus the
    margin), whatever the hunt list says; None if there is none."""
    hx, hy = s['hero']
    near = [n for n in s['npcs'] if n['ok'] and n['aggressive'] and not n['engaged'] and n['id'] not in (cfg.get('ignore') or ()) and not n.get('forbidden')
            and dist(n['x'], n['y'], hx, hy) <= n['notice'] + cfg['threat_margin']]
    return nearest(near, hx, hy)


def pick_target(s, cfg):
    """The allowed alien with the best score: its distance, plus (avoid_aggressive) a penalty for standing inside other aggressive aliens'
    zones. A group next to the ship is taken before a lone alien across the map (player report: it killed one of four Lordakium sitting
    side by side near aggressive aliens, then flew off to a "clear" one far away); a clear target nearly as close is still preferred.
    Only inside the drawn work area and outside the areas to avoid; a priority alien counts as PRIORITY_W closer. Behind walls: by_way."""
    ignore = cfg.get('ignore') or ()
    cand = [n for n in s['npcs'] if n['ok'] and n['allowed'] and n['id'] not in ignore and takes(n['x'], n['y'], cfg)]

    zones = s.get('statics') or ()
    if zones:                                       # inside an immobile alien's zone: from outside it, else a lure (enough HP)
        cand = [n for n in cand if not needs_lure(s, cfg, n) or can_lure(s, cfg, n)]
    other = danger_but(s, cfg) if cfg['avoid_aggressive'] and cand else None     # = danger(x, y, threats(s, cfg, id))

    def score(n, d):
        d -= PRIORITY_W if n.get('priority') else 0
        if zones and danger(n['x'], n['y'], zones):
            d += DANGER_W * danger(n['x'], n['y'], zones) + (LURE_W if needs_lure(s, cfg, n) else 0)
        return d + DANGER_W * other(n['x'], n['y'], n['id']) if cfg['avoid_aggressive'] else d
    return by_way(s, cand, score)


def in_statics(s, x, y):
    return any(dist(x, y, zx, zy) < r for zx, zy, r in s.get('statics') or ())


def outside_spot(s, cfg, t):
    """The point of the firing band around t (kite_min..kite_max of the laser range) nearest to the ship, outside every immobile alien's
    zone and every wall, or None."""
    R, (hx, hy) = s['R'], s['hero']
    best, best_d = None, None
    for f in (cfg['kite_min'] + cfg['kite_max']) / 2, cfg['kite_max'], cfg['kite_min']:
        for k in range(RING_POINTS * 2):
            a = 2 * math.pi * k / (RING_POINTS * 2)
            x, y = t['x'] + math.cos(a) * f * R, t['y'] + math.sin(a) * f * R
            if in_bounds(x, y, s['bounds']) and not in_statics(s, x, y) and not walled(s, x, y):
                d = dist(x, y, hx, hy)
                if best_d is None or d < best_d:
                    best, best_d = (x, y), d
    return best


def can_lure(s, cfg, t):
    """The ship may go into the zone around t: HP at LURE_HP or more, and HP + shield take LURE_HITS shots of every immobile alien
    whose zone t is in."""
    m = cfg['threat_margin']
    hit = max((n.get('damage', 0) for n in s['npcs'] if n.get('static') and not n['allowed']
               and dist(t['x'], t['y'], n['x'], n['y']) < n['fire_range'] + m), default=0)
    return hp_pct(s) >= LURE_HP and s['hp'] + s.get('shield', 0) >= LURE_HITS * hit


def needs_lure(s, cfg, t):
    """t sits in an immobile alien's zone so deep that it cannot be fired at from outside (an immobile alien itself is never drawn out)."""
    return not t.get('static') and in_statics(s, t['x'], t['y']) and outside_spot(s, cfg, t) is None


def pick_box(s, cfg, thr):
    hx, hy = s['hero']
    ignore = cfg.get('ignore_boxes') or ()
    boxes = [b for b in s['boxes'] if cfg['boxes'].get(b['kind']) and dist(b['x'], b['y'], hx, hy) <= cfg['box_radius']
             and danger(b['x'], b['y'], thr) == 0 and b['hash'] not in ignore and takes(b['x'], b['y'], cfg)
             and not walled(s, b['x'], b['y'])]
    return by_way(s, boxes, lambda b, d: d)


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
        if not in_bounds(x, y, s['bounds']) or walled(s, x, y) or in_statics(s, x, y):
            continue
        score = ((danger(x, y, thr) + area_cost(x, y, cfg) + wall_cost(s, hx, hy, x, y)) * DANGER_W
                 + (path_danger(hx, hy, x, y, thr) + path_area_cost(hx, hy, x, y, cfg)) * PATH_W + dist(hx, hy, x, y))
        if best_score is None or score < best_score:
            best, best_score = (x, y), score
    if best is None and s.get('statics'):              # the ideal ring is in an immobile alien's zone: the band's edge outside it
        best = outside_spot(s, cfg, t)
    if best is None:                                   # target at the map edge: straight toward it, up to the ideal distance
        f = max(0.0, d - ideal) / d if d else 0.0
        best = (hx + (t['x'] - hx) * f, hy + (t['y'] - hy) * f)
    return best


def rocket_band(s, cfg, t, thr, reach):
    """A rocket ready whose range (reach) falls short of the kiting band (R-310: 450, the aliens' own firing range, while the band starts
    at 0.80 x 600 = 480): the band moved just inside that range for the shot (DIP_IN..DIP_OUT of reach) when the target is an aggressive
    alien (it chases the ship into its range anyway: kiting does not keep its fire off, a passive one stays out of range and a dip would
    only add hits; SW4 measurement), the ship takes its fire easily (HP at DIP_HP % or more, HP + shield for DIP_HITS of its shots) and
    no other alien's zone covers the target (thr: the threats but t); cfg otherwise. Once the rocket is gone the band is the normal one
    again: the ship backs off."""
    R, (hx, hy) = s['R'], s['hero']
    if not reach or reach >= cfg['kite_min'] * R or dist(hx, hy, t['x'], t['y']) <= reach:
        return cfg
    if (not t.get('aggressive') or hp_pct(s) < DIP_HP or s['hp'] + s.get('shield', 0) < DIP_HITS * t.get('damage', 0)
            or danger(t['x'], t['y'], [(x, y, r + reach) for x, y, r in thr])):     # no point within reach of t in another's zone
        return cfg
    return dict(cfg, kite_min=DIP_IN * reach / R, kite_max=DIP_OUT * reach / R)


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


ROAM_CELL = 2000              # patrol (fork): the map is covered in cells this big; a visited cell is avoided for ROAM_FORGET seconds
ROAM_FORGET = 600
ROAM_VISIT_W = 3000          # a patrol point's score: the cost of a recently visited cell (fading with time)


def roam_cell(x, y):
    return int(x // ROAM_CELL), int(y // ROAM_CELL)


def roam_point(s, cfg, rnd=random, visited=None, now=0.0):
    """A patrol point away from the threats (inside the work area when one is drawn, out of the areas to avoid). The candidates are spread
    over the whole map (or work area), not around the ship: drawn around the ship and clamped to the map, they piled up in the corner the
    ship was in and the patrol stayed there (user report: the quest patrol in the lower right corner). visited ({cell: time}, roam_cell):
    the cells the ship has flown through lately cost more, so the patrol goes to the parts of the map it has not seen."""
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
    span = max(hi_x - lo_x, hi_y - lo_y)
    near = min(2500, span / 3)                     # not right next to the ship (a small work area: a third of it)
    for _ in range(16):
        x, y = rnd.uniform(lo_x, hi_x), rnd.uniform(lo_y, hi_y)
        if dist(hx, hy, x, y) < near or walled(s, x, y):
            continue
        score = ((danger(x, y, thr) + area_cost(x, y, cfg)) * DANGER_W
                 + (path_danger(hx, hy, x, y, thr) + path_area_cost(hx, hy, x, y, cfg) + wall_cost(s, hx, hy, x, y)) * PATH_W)
        if visited:
            t = visited.get(roam_cell(x, y))
            if t is not None and now - t < ROAM_FORGET:
                score += ROAM_VISIT_W * (1 - (now - t) / ROAM_FORGET)
        score += rnd.uniform(0, 200)                  # ties: not always the same point
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
        if walled(s, x, y):
            continue
        d = min(dist(x, y, n['x'], n['y']) for n in att) - 2000 * area_cost(x, y, cfg)
        if best_d is None or d > best_d:
            best, best_d = (x, y), d
    return best


def hp_pct(s):
    return 100.0 * s['hp'] / s['hp_max'] if s['hp_max'] else 100.0
