"""Drawing a target out of an immobile alien's firing zone (Mindfire Behemoth, Invoke XVI; brain.static_zones). A target that can be fired
at from outside the zone is fought from there (brain.kite_point). One sitting deeper: with the HP at brain.LURE_HP or more, the ship goes
in just as far as the target notices it or the lasers reach it (whichever is farther from the target), and once the target goes after
the ship, flies straight out; the target follows and is fought outside. MAX_INSIDE seconds in the zone without the target following is a
failed try (out again, PAUSE before the next); after TRIES failed tries the target is left alone for GIVE_UP seconds. Lower HP: the target
is left alone for LOW_HP_SEC and the bot looks for another one."""
import math

from .. import brain as B

MAX_INSIDE = 6.0
PAUSE = 3.0
TRIES = 2
GIVE_UP = 60.0
LOW_HP_SEC = 15.0
OUT = 200                     # the way out ends this far past the zone's edge
IN = 0.95                     # how close to the trigger distance the ship goes (a little inside it)


def exit_point(s, x, y):
    """Out of the zone(s) the point is in: straight away from the nearest zone's center, OUT past its edge."""
    zones = [z for z in s.get('statics') or () if B.dist(x, y, z[0], z[1]) < z[2]]
    if not zones:
        return None
    zx, zy, r = min(zones, key=lambda z: z[2] - B.dist(x, y, z[0], z[1]))
    d = B.dist(x, y, zx, zy)
    a = math.atan2(y - zy, x - zx) if d else 0.0
    return zx + math.cos(a) * (r + OUT), zy + math.sin(a) * (r + OUT)


def run(pilot, s, cfg, it, now):
    """-> True when the lure took the ship (no kiting this step), else False (the target can be fought from outside, or no zone)."""
    if not s.get('statics') or not B.needs_lure(s, cfg, it):
        pilot.lure = None
        return False
    act = pilot.act
    lure = pilot.lure
    if lure is None or lure['id'] != it['id']:
        lure = pilot.lure = dict(id=it['id'], tries=0, since=None, rest=0.0)
        if B.hp_pct(s) >= B.LURE_HP:
            pilot.note('{0} is inside an immobile alien\'s zone: drawing it out.', it['name'])
    hx, hy = s['hero']
    inside = B.in_statics(s, hx, hy)
    out = exit_point(s, hx, hy) if inside else None
    if it['engaged']:                               # it goes after the ship: out of the zone, it follows
        lure['since'] = None
        if out:
            act.move_to(out[0], out[1], now)
        return True
    if inside:
        lure['since'] = lure['since'] or now
        if now - lure['since'] > MAX_INSIDE:
            lure['tries'] += 1
            lure['since'], lure['rest'] = None, now + PAUSE
            if lure['tries'] >= TRIES:
                return leave(pilot, it, now, GIVE_UP, '{0} does not leave the immobile alien\'s zone: left alone for a while.')
            pilot.note('{0} did not follow: out of the zone, another try.', it['name'])
    else:
        lure['since'] = None
    if B.hp_pct(s) < B.LURE_HP and not inside:
        return leave(pilot, it, now, LOW_HP_SEC, '{0} is inside an immobile alien\'s zone: HP too low to draw it out.')
    if now < lure['rest'] or B.hp_pct(s) < B.LURE_HP:
        if out:
            act.move_to(out[0], out[1], now)
        return True
    reach = max(it['notice'] if it['aggressive'] else 0, s['R'] * cfg['kite_max']) * IN
    d = B.dist(hx, hy, it['x'], it['y'])
    if d > reach:                                   # in, only as far as needed
        f = reach / d
        act.move_to(it['x'] + (hx - it['x']) * f, it['y'] + (hy - it['y']) * f, now)
    return True


def leave(pilot, it, now, sec, msg):
    pilot.ignored[it['id']] = now + sec
    pilot.note(msg, it['name'])
    pilot.lure = None
    pilot.drop_target()
    return True
