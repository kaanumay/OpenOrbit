"""The bots' play in the team modes and open-map PvP events (Team Deathmatch, Sector Control, Capture the Beacon, Spaceball): the mode
files keep the rules, this module steers the drafted bots' ships. Each function takes the mode's object first (the call left in the
mode file passes self). A think function returns True when it moved the ship (the body's default combat in bot/ship.think is skipped),
False to let the default combat (approach n.target, fire) run. bot/ship.think fires at n.target on its own every step, so a tactic that
moves the ship itself still shoots whatever it set as the target (fighting while holding a point, shooting while flying).

Team planning (who goes where, the shared focus target) runs once a second per match on a snapshot of the pilots (the world loop must
not scan every ship per bot per step); each pilot follows a changed order only after its own reaction time, and pilots differ by
personality (patience, aggression, sociability, risk) and skill: nobody plays perfectly. Ship abilities through bot/abilities.py's face
(kinds, support_wish, request): everything also works when it returns nothing. Team callouts for the chat: n.bot.event('team', sub=...)
at most once per SAY_SEC per bot (bot/talk turns them into chat).
Measured with tools/behavior_lab/match_lab.py (belgeler/gelistirme/2026-11-23-etkinlik/TT.md)."""
import math, random

import map_links as H
from . import abilities as AB
from . import playstyle as PL

# behaviour parameters of the bots (not game values: the reason is in the comment)
PLAN_SEC = 1.0           # a team re-plans about once a second (BRIF rule 13: team planning at most about once a second)
SAY_SEC = 20.0           # a bot's team callout at most this often (PLAN: BK's rate)
NEAR = 1500              # an ally / enemy this close is in the same fight (PLAN's metric radius)
STACK = 160              # waiting ships keep about this far apart (a ship's sprite is about 100-150 units wide)
LEAN_SEC = 6.0           # the last seconds of a countdown in which some pilots turn toward the exit side
CAPTURE_MIN = 2          # pilots sent to an uncontested point: one more than needed, so one death does not stop the capture
CONTEST_NEAR = 900       # enemies this far outside a point's radius count as contesting it (they arrive within a few seconds)
HYST = 0.6               # an assignment a pilot already has costs this share: plans do not flip every second
LATE_EARLY = 120         # the last minutes: this long before the 5x bleed the plan already plays for the points
REPAIRED = 0.92          # a pilot back at the start area leaves at this HP+shield share (the start area repairs fast)
REGROUP_MIN = 2          # pilots ready at the start area that leave together (no trickling in one by one)
HEALER_REACH = 2500      # a hurt pilot flies to a healer ally this close instead of to the start area
FOCUS_REACH = 2500       # Team Deathmatch: enemies this close to the team's anchor can become the focus target
CHASE_EXTRA = 1400       # how far past its point an aggressive, unskilled pilot still chases (the human mistake)
LOW_HP = 0.10            # pulls out of a fight below this HP+shield share (+ up to 0.2 for a careful pilot): late enough that fights end in kills
NOTICE = 0.15            # the least chance per think step (about a second) to notice the low HP; the rest comes with survival skill
FINISH = 600            # an enemy below 30% is chased this much past the pilot's leash (finishing a fleeing ship, as players do)
SPEED_FAR = 3000        # a point this far away is worth a speed ability when it is contested
CARRIER_HUNT = 4         # Capture the Beacon: at most this many bots of a map hunt the beacon carrier (the world's cost stays small)
PUSH_MIN_SEC = 35        # Sector Control: a decided push is kept this long (a team commits to an attack; no flip-flopping)
PUSH_STAGE = 700         # the push gathers this far outside the point's radius, on the side of its own start area
PUSH_TRAVEL = 15.0       # seconds of flight that weigh as much as one more defender when choosing a push (take what can be held)
PUSH_STAGE_SEC = 20     # it goes in at the latest after this long, even if not everyone has come
RAID_NOTICE = 6000      # Capture the Beacon: home bots this far from the raiders notice the raid (the minimap shows the beacon's state)
RAID_ESCORTS = 2        # Capture the Beacon: at most this many escorts in a raid party


# ------------------------------------------------------------------------------------------------ shared helpers
def say(n, sub, now, **f):
    """A team callout (bot event 'team') at most once per SAY_SEC per bot (on the bot: a new ship after a respawn keeps the pause)."""
    b = n.bot
    if now - b.__dict__.get('tt_said', -1e9) < SAY_SEC:
        return False
    b.tt_said = now
    b.event('team', sub=sub, **f)
    return True


def _rng(n, key):
    return random.Random('%s|%s' % (n.bot.name, key))


def _offset(n, key, cx, cy, r):
    """The bot's own spot in a circle (stable per bot and place: they do not all fly to the centre)."""
    q = _rng(n, key)
    a, d = q.uniform(0, 2 * math.pi), r * math.sqrt(q.uniform(0.05, 1.0))
    return cx + math.cos(a) * d, cy + math.sin(a) * d


def _clamp(x, y, cx, cy, r):
    d = math.hypot(x - cx, y - cy)
    if d <= r or d == 0:
        return x, y
    return cx + (x - cx) * r / d, cy + (y - cy) * r / d


def low_hp(b):
    """The HP+shield share at which the pilot pulls out of a fight (a careful pilot earlier, a reckless one late)."""
    return LOW_HP + 0.2 * (1 - b.o('risk'))


def notices(b):
    """At one think step, does the pilot notice in the heat of the fight that it must pull out? (survival skill: the unaware stay too long)"""
    return random.random() < NOTICE + (1 - NOTICE) * PL.skill(b, 'survival')


def _lag(n):
    return n.bot.k['personality']['reaction_sec']


def adopt(n, task, now):
    """The pilot follows a changed order after its own reaction (it reads the situation; it does not get the plan instantly)."""
    cur = n.__dict__.get('tt_task')
    if task == cur:
        n.tt_next = None
        return cur
    if cur is None:
        n.tt_task, n.tt_next = task, None
        return task
    pend = n.__dict__.get('tt_next')
    if pend is None or pend[0] != task:
        pend = n.tt_next = (task, now + _lag(n) * random.uniform(0.4, 2.2) * (1.6 - PL.skill(n.bot, 'pvp')))
    if now >= pend[1]:
        n.tt_task, n.tt_next = task, None
        return task
    return cur


def _hero_ratio(w):
    g = w.p.d['ship']
    return (g.get('hitPoints', 0) + g.get('shield', 0)) / max(1, g.get('hitMax', 1) + g.get('shieldMax', 0))


def _units(g, w, now):
    """The match's pilots now (one snapshot per plan): {uid: dict(id, c, x, y, r: HP+shield share, n: ship or None for the player,
    hid: cloaked, att: hit by how many in 4 s, pw: power, sp: speed)}."""
    out = {}
    if not w.hero_dead and not g.player.get('removed'):
        hx, hy = w.hero_pos(now)
        out[w.hid] = dict(id=w.hid, c=g.own, x=hx, y=hy, r=_hero_ratio(w), n=None, hid=w.hidden(now), att=0, pw=1.0, sp=0)
    for m in w.npcs.values():
        if m.bot is None or not m.alive or m.id not in g.stats:
            continue
        x, y = m.mover.pos(now)
        d = m.bot.value()
        go = m.movement if m.movement is not None and m.mover.t1 > now else (x, y)
        out[m.id] = dict(id=m.id, c=m.bot.company, x=x, y=y, r=(m.hp + m.shield) / max(1, d['hp'] + d['shield']), n=m,
                         hid=bool(m.__dict__.get('hidden')), att=sum(1 for t in m.attacker.values() if now - t < 4), pw=d['power'],
                         sp=m.speed(), go=go)
    if out.get(w.hid):
        mates = [u['pw'] for u in out.values() if u['n'] is not None]
        out[w.hid]['pw'] = sum(mates) / len(mates) if mates else 1.0
    return out


def _alive(w, u):
    return (not w.hero_dead) if u['n'] is None else u['n'].alive


def _attackable(w, n, u, now):
    from bot import ship as BS
    if u['n'] is None:
        return BS.can_attack_player(w, n, w, now)
    return BS.can_attack_bot(w, n, u['n'], now)


def _roles(units, comps):
    """Roles from the ship and the pilot: healer / support (heal or shield allies), tank (taunt, or defence on a tough hull), flanker (cloak,
    speed ability, or a fast hull), the line. Without abilities they come from the hull's speed and HP against the team and the pilot."""
    out = {}
    for c in comps:
        mine = [u for u in units.values() if u['c'] == c and u['n'] is not None]
        if not mine:
            continue
        sp = sorted(u['sp'] for u in mine)[len(mine) // 2] or 1
        hp = sorted(u['n'].bot.value()['hp'] for u in mine)[len(mine) // 2] or 1
        for u in mine:
            n, ks = u['n'], AB.kinds(u['n'])
            b = n.bot
            if ks & {'heal_ally', 'shield_ally'}:
                r = 'healer'
            elif 'taunt' in ks or 'defense' in ks and b.value()['hp'] >= hp:
                r = 'tank'
            elif ks & {'cloak', 'speed'} or u['sp'] >= sp * 1.15 and b.o('aggression') > 0.4:
                r = 'flanker'
            elif b.value()['hp'] >= hp * 1.25 and b.o('aggression') > 0.5:
                r = 'tank'
            else:
                r = 'line'
            out[u['id']] = r
    return out


def _healer(P, n, nx, ny):
    """The nearest ally with an ally heal / shield (BY's abilities) within HEALER_REACH, or None."""
    best = None
    for u in P['u'].values():
        m = u['n']
        if m is None or m is n or u['c'] != n.bot.company or P['role'].get(u['id']) != 'healer':
            continue
        d = math.hypot(u['x'] - nx, u['y'] - ny)
        if d <= HEALER_REACH and (best is None or d < best[0]):
            best = (d, u)
    return best and best[1]


def _shoot(w, n, P, nx, ny, now, reach=None, near=None, focus=None):
    """Picks the target: the focus when it is in reach, otherwise the nearest enemy in laser range (and, near=(x, y, r), inside that
    circle); None when there is nobody. The ship's own fire step shoots it."""
    from bot import ship as BS
    reach = reach or BS.LASER_RANGE
    if focus is not None:
        u = P['u'].get(focus)
        if u is not None and _alive(w, u) and math.hypot(u['x'] - nx, u['y'] - ny) <= reach + 300 and _attackable(w, n, u, now):
            return focus
    best = None
    for u in P['u'].values():
        if u['c'] == n.bot.company or u['hid'] or not _alive(w, u):
            continue
        d = math.hypot(u['x'] - nx, u['y'] - ny)
        if d > reach or near is not None and math.hypot(u['x'] - near[0], u['y'] - near[1]) > near[2] + (FINISH if u['r'] < 0.3 else 0):
            continue
        if best is None or d < best[0]:
            best = (d, u)
    if best is not None and _attackable(w, n, best[1], now):
        return best[1]['id']
    return None


def wait(w, n, now, cx, cy, r, mates, toward=None, end=None):
    """Alive waiting inside a circle (the start area in the countdown, waiting for others after a respawn, a quiet point): some drift
    around, some reposition, a few stay put, they do not stack on one spot, some turn toward the exit side as the countdown ends; never
    outside the circle. By personality: patience stays, sociability drifts toward the others, aggression leans out first."""
    from bot import ship as BS
    b = n.bot
    key = (int(cx), int(cy))
    st = n.__dict__.get('tt_wait')
    if st is None or st['c'] != key:
        st = n.tt_wait = dict(c=key, next=now + random.uniform(0.3, 2.5) * _lag(n), lean=None)
        if end is not None and toward is not None:
            st['lean'] = end - LEAN_SEC * random.uniform(0.3, 1.0) if random.random() < 0.2 + 0.6 * b.o('aggression') else None
    nx, ny = n.mover.pos(now)
    if math.hypot(nx - cx, ny - cy) > r:                   # outside (spawned at the edge, pushed): back inside first
        x, y = _clamp(*_offset(n, key, cx, cy, r * 0.7), cx, cy, r * 0.8)
        BS._go_to(w, n, x, y, now)
        st['next'] = now + 2.0
        return
    if st['lean'] is not None and now >= st['lean']:
        st['lean'] = None
        a = math.atan2(toward[1] - cy, toward[0] - cx) + random.uniform(-0.6, 0.6)
        d = r * random.uniform(0.55, 0.85)
        BS._go_to(w, n, cx + math.cos(a) * d, cy + math.sin(a) * d, now)
        st['next'] = (end or now) + 1.0
        return
    if now < st['next']:
        return
    pat = b.o('patience')
    crowded = any(math.hypot(nx - p[0], ny - p[1]) < STACK * 0.6 for p in mates)
    # live 2026-11-23: with longer pauses and short hops 0-3 of 29 ships were moving at any moment of the countdown, it still looked
    # frozen; now about a quarter of them are under way and the patient ones stand
    if not crowded and random.random() < 0.05 + 0.45 * pat:     # stays where it is for a while (not on top of another ship)
        BS._stop(w, n, now)
        st['next'] = now + random.uniform(2, 6) * (0.6 + pat)
        return
    best = None
    soc = b.o('sociability')
    mx = my = None
    if mates and random.random() < soc:
        mx, my = sum(p[0] for p in mates) / len(mates), sum(p[1] for p in mates) / len(mates)
    for _ in range(4):
        a = random.uniform(0, 2 * math.pi) if mx is None else math.atan2(my - ny, mx - nx) + random.uniform(-1.0, 1.0)
        d = random.uniform(250, max(350, r * 0.9))
        x, y = _clamp(nx + math.cos(a) * d, ny + math.sin(a) * d, cx, cy, r * 0.85)
        gap = min((math.hypot(x - p[0], y - p[1]) for p in mates), default=1e9)
        if best is None or gap > best[0]:
            best = (gap, x, y)
        if gap >= STACK * 2:
            break
    _, x, y = best
    BS._go_to(w, n, x, y, now)
    st['next'] = now + math.hypot(x - nx, y - ny) / max(100, n.speed()) + random.uniform(0.3, 3) * (0.6 + pat)


def _mates(P, n):
    """Where the bot's mates are and where they are going (two waiting ships do not pick the same spot)."""
    out = []
    for u in P['u'].values():
        if u['c'] == n.bot.company and u['n'] is not n:
            out.append((u['x'], u['y']))
            if u.get('go') and u['go'] != (u['x'], u['y']):
                out.append(u['go'])
    return out


# ------------------------------------------------------------------------------------------------ Team Deathmatch
def tdm_plan(g, w, now):
    """Per team, once a second: the anchor (where the team is), the direction of the enemy, the focus target (the weakest, a healer, one
    out of position), allies under focus to peel for, retreat when outnumbered near the anchor (with hysteresis), the rally point."""
    import team_deathmatch as TDM
    P = g.__dict__.get('_tt')
    if P is not None and now < P['t']:
        return P
    prev = P['p'] if P else {}
    units = _units(g, w, now)
    P = g._tt = dict(t=now + PLAN_SEC, u=units, p={}, role=_roles(units, (g.own, g.opp)))
    zr = TDM.D['start_zone_radius']
    for c, o in ((g.own, g.opp), (g.opp, g.own)):
        sx, sy = g.spawn(c)
        ex, ey = g.spawn(o)
        mine = [u for u in units.values() if u['c'] == c]
        foes = [u for u in units.values() if u['c'] == o and not u['hid']]
        out = [u for u in mine if math.hypot(u['x'] - sx, u['y'] - sy) > zr] or mine
        ax, ay = (sum(u['x'] for u in out) / len(out), sum(u['y'] for u in out) / len(out)) if out else (sx, sy)
        seen = [u for u in foes if math.hypot(u['x'] - ax, u['y'] - ay) <= FOCUS_REACH * 1.6]
        fx, fy = (sum(u['x'] for u in seen) / len(seen), sum(u['y'] for u in seen) / len(seen)) if seen else (ex, ey)
        dd = math.hypot(fx - ax, fy - ay) or 1.0
        dx, dy = (fx - ax) / dd, (fy - ay) / dd
        ms = sum(u['r'] * u['pw'] for u in mine if math.hypot(u['x'] - ax, u['y'] - ay) <= NEAR)
        fs = sum(u['r'] * u['pw'] for u in foes if math.hypot(u['x'] - ax, u['y'] - ay) <= NEAR + 500)
        was = prev.get(c, {})
        retreat = fs > 0 and ms / fs < (0.85 if was.get('retreat') else 0.55)
        pw = sum(u['pw'] for u in foes) / len(foes) if foes else 1.0
        best, keep = None, None
        for u in foes:
            d = math.hypot(u['x'] - ax, u['y'] - ay)
            if d > FOCUS_REACH:
                continue
            alone = not any(v is not u and math.hypot(v['x'] - u['x'], v['y'] - u['y']) < 800 for v in foes)
            s = u['r'] * u['pw'] / pw - (0.35 if P['role'].get(u['id']) == 'healer' else 0) - (0.25 if alone else 0) + d / 4000.0
            if u['id'] == was.get('focus'):
                keep = s
            if best is None or s < best[0]:
                best = (s, u['id'])
        focus = was.get('focus') if keep is not None and best is not None and keep <= best[0] + 0.25 else best and best[1]
        peel = []
        for u in mine:
            if u['n'] is not None and u['att'] >= 2 and u['r'] < 0.6:
                hitters = [a for a, t in u['n'].attacker.items() if now - t < 4 and a in units and units[a]['c'] == o]
                if hitters:
                    peel.append((u['id'], u['x'], u['y'], hitters))
        P['p'][c] = dict(anchor=(ax, ay), dir=(dx, dy), enemy=(fx, fy), focus=focus, retreat=retreat, peel=peel, seen=bool(seen),
                         new_focus=focus != was.get('focus'), rally=(ax - dx * 1200, ay - dy * 1200))
        if retreat and not was.get('retreat'):
            lead = min((u for u in mine if u['n'] is not None), key=lambda u: math.hypot(u['x'] - ax, u['y'] - ay), default=None)
            if lead is not None:
                say(lead['n'], 'retreat', now)
    return P


def tdm_think(g, w, n, now):
    """A drafted bot in Team Deathmatch: alive in the start phase; after a respawn it waits for others at the spawn (no feeding one by
    one); the team shares a focus target, peels for an ally under focus, pulls back together when outnumbered; the healer stays behind
    the front near the most hurt ally, the tank goes first, flankers come from the side, the line focuses."""
    import team_deathmatch as TDM
    from bot import ship as BS
    if g.over:
        return True
    b = n.bot
    c = b.company
    P = tdm_plan(g, w, now)
    sx, sy = g.spawn(c)
    zr = TDM.D['start_zone_radius']
    if now < g.attack_at:
        n.target = None
        wait(w, n, now, sx, sy, zr * 0.8, _mates(P, n), toward=g.spawn(g.opp if c == g.own else g.own), end=g.attack_at)
        return True
    T = P['p'].get(c)
    if T is None:
        return False
    nx, ny = n.mover.pos(now)
    ax, ay = T['anchor']
    dx, dy = T['dir']
    d = b.value()
    ratio = (n.hp + n.shield) / max(1, d['hp'] + d['shield'])
    # after a respawn: wait at the spawn for others (or until the team fights near it)
    if n.__dict__.get('tt_spawned') is None:
        n.tt_spawned = now
        n.tt_regroup = now + random.uniform(4, 12) * (0.6 + b.o('patience')) if g.stats.get(n.id, {}).get('deaths') else 0
    if now < n.tt_regroup and math.hypot(nx - sx, ny - sy) <= zr:
        ready = sum(1 for u in P['u'].values() if u['c'] == c and u['n'] is not None and u['n'] is not n
                    and math.hypot(u['x'] - sx, u['y'] - sy) <= zr)
        if ready < REGROUP_MIN - 1 and math.hypot(ax - sx, ay - sy) > 2500:
            n.target = _shoot(w, n, P, nx, ny, now)
            wait(w, n, now, sx, sy, zr * 0.7, _mates(P, n))
            return True
        n.tt_regroup = 0
        say(n, 'regroup', now)
    role = P['role'].get(n.id, 'line')
    # badly hurt: to a healer, else behind the team; shoots what is in range on the way
    low = low_hp(b)
    if ratio < low and notices(b) or n.__dict__.get('tt_back') and ratio < low + 0.25 and T['seen']:
        n.tt_back = True
        n.target = _shoot(w, n, P, nx, ny, now)
        h = _healer(P, n, nx, ny)
        if h is not None:
            say(n, 'need_heal', now)
            BS._go_to(w, n, h['x'] - dx * 200, h['y'] - dy * 200, now, threshold=150)
        else:
            BS._go_to(w, n, ax - dx * 700, ay - dy * 700, now, threshold=150)
        return True
    n.tt_back = False
    # the target: peel for an ally under focus, the team's focus, the nearest in range
    tgt = None
    if role != 'healer':
        for uid, px, py, hitters in T['peel']:
            if uid != n.id and math.hypot(px - nx, py - ny) <= NEAR:
                hu = P['u'].get(hitters[0])
                if hu is not None and _alive(w, hu) and _attackable(w, n, hu, now):
                    tgt = hitters[0]
                    if role == 'tank':
                        AB.request(w, n, 'taunt', now)
                    break
        if tgt is None:
            tgt = _shoot(w, n, P, nx, ny, now, reach=1800 if role != 'flanker' else 2200, focus=T['focus'])
    else:
        tgt = _shoot(w, n, P, nx, ny, now)
    if tgt is not None and tgt != n.target and tgt == T['focus']:
        AB.request(w, n, 'burst', now, target=tgt)
    n.target = tgt
    if sum(1 for t in n.attacker.values() if now - t < 4) >= 2:
        AB.request(w, n, 'defense', now)
    if T['retreat']:
        rx, ry = T['rally']
        BS._go_to(w, n, *_offset(n, 'rally', rx, ry, 400), now, threshold=200)
        return True
    if role == 'healer':
        wish = AB.support_wish(w, n, now)
        if wish is not None:
            _, hx, hy, reach = wish
            if math.hypot(hx - nx, hy - ny) > reach * 0.8:
                BS._go_to(w, n, hx, hy, now, threshold=150)
            return True
        BS._go_to(w, n, *_offset(n, 'back', ax - dx * 450, ay - dy * 450, 300), now, threshold=200)
        return True
    if role == 'tank':                                     # a taunt ready and an ally under fire: covers it
        wish = AB.support_wish(w, n, now)
        if wish is not None and math.hypot(wish[1] - nx, wish[2] - ny) > wish[3] * 0.8:
            BS._go_to(w, n, wish[1], wish[2], now, threshold=150)
            return True
    if tgt is not None:
        u = P['u'][tgt]
        pos = (u['x'], u['y']) if u['n'] is None else u['n'].mover.pos(now)
        if role == 'flanker':
            side = _rng(n, 'side').choice((-1, 1))
            px, py = pos[0] - dy * side * 450, pos[1] + dx * side * 450
            if math.hypot(px - nx, py - ny) > 250 and math.hypot(pos[0] - nx, pos[1] - ny) > BS.LASER_RANGE * 0.8:
                BS._go_to(w, n, px, py, now, threshold=150)
                return True
        BS.approach(w, n, pos, now)
        return True
    # no enemy in reach: the team moves as a group toward the enemy (those ahead of the anchor wait for the others)
    ahead = (nx - ax) * dx + (ny - ay) * dy
    if ahead > 700:
        BS._stop(w, n, now)
        return True
    step = 300 if role == 'tank' else -150 if role == 'line' else 0
    tx, ty = _offset(n, 'form', ax + dx * (900 + step), ay + dy * (900 + step), 450)
    if not T['seen']:
        mx, my = w.map_w / 2.0, w.map_h / 2.0
        tx, ty = _offset(n, 'form', ax + (mx - ax) * 0.5 + dx * 600, ay + (my - ay) * 0.5 + dy * 600, 450)
    if math.hypot(ax - nx, ay - ny) > 1200:
        tx, ty = _offset(n, 'form', ax, ay, 450)
    BS._go_to(w, n, tx, ty, now, threshold=200)
    return True


# ------------------------------------------------------------------------------------------------ Sector Control
def statistics_mean(v):
    return sum(v) / len(v) if v else 0.0


def _reserve(g, c, units, free, cost, P):
    """A reserve when ahead: up to two hold the held point nearest the enemies (taken out of free)."""
    mine_held = [i for i, s in enumerate(g.sectors) if s['owner'] == c]
    foes = [u for u in units.values() if u['c'] != c]
    if mine_held and foes:
        fx, fy = sum(u['x'] for u in foes) / len(foes), sum(u['y'] for u in foes) / len(foes)
        i = min(mine_held, key=lambda i: math.hypot(g.sectors[i]['x'] - fx, g.sectors[i]['y'] - fy))
        for u in sorted(free, key=lambda u: cost(u, i))[:2]:
            P['a'][u['id']] = (i, 'guard')
            free.remove(u)


def sc_plan(g, w, now):
    """Per company, once a second: how many pilots each control point needs (uncontested: CAPTURE_MIN; contested: more than the enemy
    there, or given up; a held point under attack: defended if winnable), who goes where (cheapest by travel time, the current order
    preferred), a reserve when ahead, all-in when bleeding or in the last minutes, the player's point first; the focus target per point."""
    import sector_control as SC
    D = SC.D
    P = g.__dict__.get('_tt')
    if P is not None and now < P['t']:
        return P
    prev = P['a'] if P else {}
    push0 = P.get('push', {}) if P else {}
    own0 = P['own'] if P else {s['id']: s['owner'] for s in g.sectors}
    R = D['sector_radius']
    units = _units(g, w, now)
    live = [c for c in g.companies if c not in g.out]
    P = g._tt = dict(t=now + PLAN_SEC, u=units, a={}, focus={}, own={s['id']: s['owner'] for s in g.sectors}, role=_roles(units, live),
                     push={})
    info = []
    for s in g.sectors:
        inside, near = {c: 0 for c in SC.COMPANIES}, {c: 0 for c in SC.COMPANIES}
        for u in units.values():
            if u['hid']:
                continue
            d = math.hypot(u['x'] - s['x'], u['y'] - s['y'])
            inside[u['c']] += d <= R
            near[u['c']] += d <= R + CONTEST_NEAR
        info.append((inside, near))
    for i, s in enumerate(g.sectors):                      # callouts: a point taken / lost
        was = own0.get(s['id'], 0)
        if s['owner'] != was:
            for c, sub in ((s['owner'], 'point_taken'), (was, 'point_lost')):
                if c:
                    u = min((u for u in units.values() if u['c'] == c and u['n'] is not None),
                            key=lambda u: math.hypot(u['x'] - s['x'], u['y'] - s['y']), default=None)
                    if u is not None:
                        say(u['n'], sub, now, point=i + 1)
    held = g.held()
    late = now - g.started_at >= D['late_sec'] - LATE_EARLY
    hero = units.get(w.hid)
    lead = max(live, key=lambda c: (held.get(c, 0), g.tickets[c])) if live else None
    last = min(live, key=lambda c: (held.get(c, 0), g.tickets[c])) if live else None      # the weakest: not the one to beat down
    for c in live:
        others = [o for o in live if o != c]
        top = max((held.get(o, 0) for o in others), default=0)
        tix = max((g.tickets[o] for o in others), default=0)
        ahead = held.get(c, 0) > top and g.tickets[c] >= tix
        behind = held.get(c, 0) < top or held.get(c, 0) == top and g.tickets[c] < tix
        bleeding = held.get(c, 0) < top and (late or g.tickets[c] < tix * 0.8)
        bonus = SC.underdog(held, c) > 0
        mine = [u for u in units.values() if u['c'] == c and u['n'] is not None]
        tasks = []
        hero_at = None
        for i, s in enumerate(g.sectors):
            inside, near = info[i]
            foe = max(near[o] for o in SC.COMPANIES if o != c)
            if c == g.own and hero is not None and math.hypot(hero['x'] - s['x'], hero['y'] - s['y']) <= R + 800:
                hero_at = i
            if s['owner'] == c:
                if foe:
                    # one more than the enemies inside, one watcher for those only near (often passing by the middle point): a point
                    # on everybody's way must not bind the whole team; the winnable defence first (pressed from two sides)
                    need = max(inside[o] for o in SC.COMPANIES if o != c) + 1
                    tasks.append([3.0 - 0.05 * foe, i, need, 'defend', foe])
                elif ahead and not bleeding:
                    tasks.append([1.0, i, 1, 'guard', 0])
                continue
            if s['owner'] and foe and i != hero_at:
                continue                                   # a guarded enemy point: the grouped push below, not a trickle
            need = (foe + (0 if bonus else 1)) if foe else CAPTURE_MIN
            prio = (2.5 if s['owner'] else 2.2) - 0.2 * foe   # an enemy's point also stops its bleed on us; a free one is cheaper
            if s['prog_owner'] == c and s['progress'] > 0:
                prio += 0.3                                # half captured: finish it
            if late and not ahead:
                prio += 0.5
            if i == hero_at:
                prio, need = (5.0, max(need, 2)) if foe else (4.0, max(need - 1, 2))      # the player went for it: pilots join / help
            tasks.append([prio, i, max(1, need), 'take', foe])
        free = []
        for u in mine:
            m = u['n']
            if u['hid']:
                continue                                   # cloaked: does not count for a capture, hunts (below)
            if m.__dict__.get('tt_repair') or u['r'] < low_hp(m.bot):
                continue
            free.append(u)
        noise = {u['id']: random.uniform(0.85, 1.2) for u in mine}

        def cost(u, i):
            s = g.sectors[i]
            k = HYST if prev.get(u['id'], (None,))[0] == i else 1.0
            if P['role'].get(u['id']) == 'tank' and s['owner'] == c:
                k *= 0.8                                   # the tank holds what we have
            return math.hypot(u['x'] - s['x'], u['y'] - s['y']) / max(100.0, u['sp']) * k * noise[u['id']]
        tie = {i: random.random() for i in range(len(g.sectors))}      # equal tasks: no fixed order by the points' numbers (it favoured a side)
        tasks.sort(key=lambda t: (-t[0], tie[t[1]]))
        for t in tasks:
            prio, i, need, kind, foe = t
            if not free:
                break
            was = sum(1 for u in mine if prev.get(u['id'], (None,))[0] == i)
            slack = (1 if was else 0) + (1 if kind == 'defend' and held.get(c, 0) <= 1 else 0)     # the last point is fought for
            if need > len(free) + slack and not bleeding:
                t[2] = -1                                  # not winnable with who is free: given up (kept one pilot longer if we were there)
                continue
            pick = sorted(free, key=lambda u: cost(u, i))[:need]
            for u in pick:
                P['a'][u['id']] = (i, kind)
                free.remove(u)
            t[2] = 0
        rest = [t for t in tasks if t[3] in ('take', 'defend') and t[2] >= 0] or [t for t in tasks if t[2] >= 0]
        if ahead and free and not bleeding:                # a reserve when ahead: up to two hold the held point nearest the enemies
            _reserve(g, c, units, free, cost, P)
        # the push: everybody still free attacks one guarded enemy point together (staged outside it until enough are there), the
        # leader's points first (in a three-way match a team attacks whoever is ahead), kept for a while once decided
        cand = [i for i, s in enumerate(g.sectors) if s['owner'] not in (0, c)
                and not any(P['a'].get(u['id'], (None,))[0] == i for u in mine)]
        if cand and len(free) >= 2:
            def foes(i):
                return max(info[i][1][o] for o in SC.COMPANIES if o != c)

            def score(i):
                s = g.sectors[i]
                go = statistics_mean([math.hypot(u['x'] - s['x'], u['y'] - s['y']) / max(100.0, u['sp']) for u in free])
                return foes(i) + go / PUSH_TRAVEL - (2.0 if s['owner'] == lead else 0) + (1.0 if s['owner'] == last and last != lead else 0) \
                    - (1.0 if bonus else 0)
            was = push0.get(c)
            i = None
            if was and was['i'] in cand and now - was['since'] < PUSH_MIN_SEC and foes(was['i']) <= len(free) + 2:
                i = was['i']
            else:
                best = min(cand, key=lambda i: score(i) + 0.3 * tie[i])
                if len(free) >= foes(best) + (0 if bonus else 1) - (1 if behind else 0) + (1 if ahead else 0) or bleeding:
                    i = best
            if i is not None:
                s = g.sectors[i]
                keep = was is not None and was['i'] == i
                hx, hy = g.spawn(c)
                d = math.hypot(hx - s['x'], hy - s['y']) or 1.0
                rx, ry = s['x'] + (hx - s['x']) / d * (R + PUSH_STAGE), s['y'] + (hy - s['y']) / d * (R + PUSH_STAGE)
                there = sum(1 for u in free if math.hypot(u['x'] - rx, u['y'] - ry) <= 900 or math.hypot(u['x'] - s['x'], u['y'] - s['y']) <= R + 300)
                since = was['since'] if keep else now
                go = keep and was['go'] or there >= max(2, min(len(free), foes(i) + 1, math.ceil(0.6 * len(free)))) \
                    or now - since > PUSH_STAGE_SEC
                P['push'][c] = dict(i=i, since=since, go=go, rally=(rx, ry))
                for u in free:
                    P['a'][u['id']] = (i, 'push')
                free = []
        if not rest:
            rest = [[1.0, i, 1, 'guard', 0] for i in range(len(g.sectors))]
        for u in free:                     # the rest strengthen the tasks they reach first, a free point before a crowded fight
            top_p = max(min(3.0, t[0]) for t in rest)      # the player's point got its pilots above: the rest do not all pile onto it
            best = min((t for t in rest if min(3.0, t[0]) >= top_p - 0.8), key=lambda t: cost(u, t[1]) * (1 + 0.4 * t[4]))
            P['a'][u['id']] = (best[1], best[3])
        if tasks:
            target = max(tasks, key=lambda t: (t[0], -t[1]))
            for u in mine:
                if u['hid'] and not (u['n'].__dict__.get('tt_repair')):
                    P['a'][u['id']] = (target[1], 'hunt')
        for i, s in enumerate(g.sectors):                  # the focus at each point: a healer first, then the weakest inside the radius
            cand = [u for u in units.values() if u['c'] != c and not u['hid'] and math.hypot(u['x'] - s['x'], u['y'] - s['y']) <= R + 300]
            if cand:
                P['focus'][(c, i)] = min(cand, key=lambda u: u['r'] * u['pw'] - (1e9 if P['role'].get(u['id']) == 'healer' else 0))['id']
    return P


def sc_think(g, w, n, now):
    """A drafted bot in Sector Control: alive in the countdown (inside the start area); then its company's plan: a control point to take,
    defend or guard (or, cloaked, to hunt at); it fights at the point and stays in the radius while it fights, shoots on the way without
    chasing; badly hurt to a healer ally or to the start area repair, and back with others."""
    import sector_control as SC
    from bot import ship as BS
    D = SC.D
    if g.over:
        return True
    b = n.bot
    c = b.company
    P = sc_plan(g, w, now)
    sx, sy = g.spawn(c)
    hr = D['home_radius']
    R = D['sector_radius']
    if now < g.attack_at:
        n.target = None
        near = min(g.sectors, key=lambda s: math.hypot(s['x'] - sx, s['y'] - sy))
        wait(w, n, now, sx, sy, hr * 0.8, _mates(P, n), toward=(near['x'], near['y']), end=g.attack_at)
        return True
    nx, ny = n.mover.pos(now)
    d = b.value()
    ratio = (n.hp + n.shield) / max(1, d['hp'] + d['shield'])
    at_home = math.hypot(nx - sx, ny - sy) <= hr * 0.8
    if n.__dict__.get('tt_spawned') is None:               # a respawn waits for others at the start area (not on the first spawn)
        n.tt_spawned = now
        if g.stats.get(n.id, {}).get('deaths'):
            n.tt_regroup = now + random.uniform(3, 10) * (0.6 + b.o('patience'))
    # badly hurt: a healer ally near, otherwise the start area (it repairs 10,000 HP a second)
    if n.__dict__.get('tt_repair') or ratio < low_hp(b) and notices(b):
        if n.hp >= REPAIRED * d['hp'] and (at_home or ratio >= REPAIRED):     # the start area repairs the hull; the shield comes back on the way
            n.tt_repair = False
            n.tt_regroup = now + random.uniform(1, 4) * (0.6 + b.o('patience'))      # back out soon, with whoever is ready
        else:
            n.tt_repair = True
            n.target = _shoot(w, n, P, nx, ny, now)
            h = None if at_home else _healer(P, n, nx, ny)
            if h is not None and math.hypot(sx - nx, sy - ny) > math.hypot(h['x'] - nx, h['y'] - ny) + 1000:
                say(n, 'need_heal', now)
                BS._go_to(w, n, h['x'], h['y'], now, threshold=200)
            elif not at_home:
                BS._route(w, n, *_offset(n, 'home', sx, sy, hr * 0.5), now)
            else:
                wait(w, n, now, sx, sy, hr * 0.7, _mates(P, n))
            return True
    if now < n.__dict__.get('tt_regroup', 0) and at_home:
        ready = sum(1 for u in P['u'].values() if u['c'] == c and u['n'] is not None and u['n'] is not n
                    and not u['n'].__dict__.get('tt_repair') and math.hypot(u['x'] - sx, u['y'] - sy) <= hr)
        if ready < REGROUP_MIN - 1:
            n.target = _shoot(w, n, P, nx, ny, now)
            wait(w, n, now, sx, sy, hr * 0.7, _mates(P, n))
            return True
        say(n, 'regroup', now)
    n.tt_regroup = 0
    task = adopt(n, P['a'].get(n.id), now)
    if task is None:
        task = (min(range(len(g.sectors)), key=lambda i: math.hypot(g.sectors[i]['x'] - nx, g.sectors[i]['y'] - ny)), 'take')
    i, kind = task
    s = g.sectors[i]
    dist = math.hypot(s['x'] - nx, s['y'] - ny)
    leash = R + 1500 if kind == 'hunt' else R + 250 + CHASE_EXTRA * b.o('aggression') * (1 - PL.skill(b, 'pvp')) ** 2
    focus = P['focus'].get((c, i))
    pu = P['push'].get(c) if kind == 'push' else None
    if pu is not None and pu['i'] == i and not pu['go'] and dist > R + 300:      # the push gathers outside the point first
        rx, ry = pu['rally']
        n.target = _shoot(w, n, P, nx, ny, now)
        if math.hypot(rx - nx, ry - ny) > 500:
            BS._route(w, n, *_offset(n, 'rally', rx, ry, 300), now)
        else:
            wait(w, n, now, rx, ry, 450, _mates(P, n))
        return True
    if dist > R * 0.9 and kind != 'hunt':                  # on the way: shoots what is in range, does not stop to chase
        tgt = _shoot(w, n, P, nx, ny, now)
        n.target = tgt
        if dist > SPEED_FAR and (kind == 'defend' or P['focus'].get((c, i))):
            AB.request(w, n, 'speed', now)
        if kind in ('take', 'push') and dist < R * 3:
            say(n, 'push', now, point=i + 1)
        elif kind == 'defend' and dist < R * 3:
            say(n, 'defend', now, point=i + 1)
        BS._route(w, n, *_offset(n, ('pt', i), s['x'], s['y'], R * 0.55), now)
        return True
    tgt = _shoot(w, n, P, nx, ny, now, reach=BS.LASER_RANGE + 250, near=(s['x'], s['y'], leash), focus=focus)
    if tgt is not None and tgt != n.target and tgt == focus:
        AB.request(w, n, 'burst', now, target=tgt)
    n.target = tgt
    if sum(1 for t in n.attacker.values() if now - t < 4) >= 2:
        AB.request(w, n, 'defense', now)
    if tgt is not None:
        u = P['u'][tgt]
        pos = (u['x'], u['y']) if u['n'] is None else u['n'].mover.pos(now)
        if sum(1 for v in P['u'].values() if v['c'] != c and math.hypot(v['x'] - nx, v['y'] - ny) < 600) >= 3:
            AB.request(w, n, 'area', now)
        if kind == 'hunt':
            BS.approach(w, n, pos, now)
            return True
        # fights at the point: at its distance from the target, but inside the radius (a capture needs it there); a fleeing wreck is
        # followed a little way out by the aggressive ones
        a = math.atan2(ny - pos[1], nx - pos[0]) + random.uniform(-0.4, 0.4)
        want = 300 + 250 * (1 - b.o('aggression'))
        keep = R * 0.8 + (FINISH * b.o('aggression') if u['r'] < 0.3 else 0)
        x, y = _clamp(pos[0] + math.cos(a) * want, pos[1] + math.sin(a) * want, s['x'], s['y'], keep)
        if math.hypot(x - nx, y - ny) > 150:
            BS._go_to(w, n, x, y, now, threshold=150)
        return True
    if role_heal(P, n):                                    # a healer at its point: next to the ally who needs it
        wish = AB.support_wish(w, n, now)
        if wish is not None:
            _, hx, hy, reach = wish
            if math.hypot(hx - nx, hy - ny) > reach * 0.8:
                BS._go_to(w, n, *_clamp(hx, hy, s['x'], s['y'], R * 0.9), now, threshold=150)
            return True
    if kind == 'hunt':
        BS._route(w, n, *_offset(n, ('pt', i), s['x'], s['y'], R), now)
        return True
    wait(w, n, now, s['x'], s['y'], R * 0.6, _mates(P, n))      # holding / capturing with nobody to fight: alive, spread out
    return True


def role_heal(P, n):
    return P['role'].get(n.id) == 'healer'


# ------------------------------------------------------------------------------------------------ Capture the Beacon
def ctb_raid_tick(c, w, now):
    import capture_beacon as CB
    carrier_watch(c, w, now)
    me = c.company()
    if int(w.map_id) != CB.X2[me]:
        return []
    r = c.raider
    if r is None:
        if now >= c.next_raid:
            c.next_raid = now + random.uniform(*CB.D['raid_sec'])
            return c.start_raid(w, now)
        return []
    if now > r['until'] or not r['bot'].online:
        return c.end_raid(w)
    raid_watch(c, w, r, now)
    return []


def raid_watch(c, w, r, now):
    """The X-2's own company bots notice the raid (once a second): at most CARRIER_HUNT of those near the raiders (the nearest first, by
    aggression and helpfulness) go for the carrier once it has the beacon, before that for the raider nearest the beacon's place."""
    import capture_beacon as CB
    import bot.manager as MGR
    from bot import ship as BS
    if now < c.__dict__.get('tt_raid_watch', 0):
        return
    c.tt_raid_watch = now + PLAN_SEC
    y = MGR.ACTIVE
    if y is None or not y.permission('pvp'):
        return
    raiders = [x.body for x in [r['bot']] + r.get('party', []) if x.body is not None and x.body.alive]
    if not raiders:
        return
    car = r['bot'].body if r['bot'].body in raiders else None
    zx, zy = CB.zone(r['beacon'])
    goal = car if r['carrying'] and car is not None else min(
        raiders, key=lambda m: math.hypot(m.mover.pos(now)[0] - zx, m.mover.pos(now)[1] - zy))
    gx, gy = goal.mover.pos(now)
    me = c.company()
    cand = []
    for m in w.npcs.values():
        if m.bot is None or not m.alive or m.bot.company != me:
            continue
        g = m.bot.target
        if g is not None and g.name in ('gate', 'mod', 'duel', 'pvp_match', 'group'):
            continue
        mx, my = m.mover.pos(now)
        d = math.hypot(mx - gx, my - gy)
        if d < RAID_NOTICE:
            cand.append((d, m))
    on = sum(1 for d, m in cand if m.target == goal.id)
    for d, m in sorted(cand, key=lambda x: x[0]):
        if on >= CARRIER_HUNT:
            break
        if m.target == goal.id:
            continue
        if (m.target is None or m.target not in w.npcs or w.npcs[m.target].bot is None
                or r['carrying'] and goal is car and random.random() < 0.2 + 0.5 * PL.skill(m.bot, 'pvp')) \
                and random.random() < 0.3 + 0.35 * m.bot.o('aggression') + 0.35 * m.bot.o('helpfulness') and BS.can_attack_bot(w, m, goal, now):
            # (a skilled pilot leaves the escort it fights for the carrier)
            m.target = goal.id
            on += 1
            if r['carrying']:
                say(m, 'carrier', now)


def carrier_watch(c, w, now):
    """The player carries an enemy beacon: the bots of the beacon's company on this map hunt the carrier (at most CARRIER_HUNT, the nearest
    first, by aggression), the bots of the player's company near the player go for the hunters. Once a second."""
    import capture_beacon as CB
    import bot.manager as MGR
    from bot import ship as BS
    if c.carrying is None or w.hero_dead or now < c.__dict__.get('tt_watch', 0):
        return
    c.tt_watch = now + PLAN_SEC
    y = MGR.ACTIVE
    if y is None or not y.permission('pvp'):
        return
    home, _ = CB.parts(c.carrying)
    me = c.company()
    hx, hy = w.hero_pos(now)
    hunters, helpers = [], []
    for m in w.npcs.values():
        if m.bot is None or not m.alive:
            continue
        goal = m.bot.target
        if goal is not None and goal.name in ('gate', 'mod', 'duel', 'pvp_match', 'group'):
            continue
        mx, my = m.mover.pos(now)
        d = math.hypot(mx - hx, my - hy)
        if m.bot.company == home and d < 4000 and y.permission('attack_player'):
            hunters.append((d, m))
        elif m.bot.company == me and d < 3000:
            helpers.append((d, m))
    hunters.sort(key=lambda x: x[0])
    on = []
    for d, m in hunters:
        if len(on) >= CARRIER_HUNT:
            break
        if m.target == w.hid or random.random() < 0.3 + 0.6 * m.bot.o('aggression'):
            if BS.can_attack_player(w, m, w, now):
                m.target = w.hid
                on.append(m)
                say(m, 'carrier', now)
    for d, m in helpers[:CARRIER_HUNT]:
        if m.target is not None and m.target in w.npcs and w.npcs[m.target].bot is not None:
            continue
        foe = min(on, key=lambda h: math.hypot(*(a - b for a, b in zip(h.mover.pos(now), m.mover.pos(now)))), default=None)
        if foe is not None and BS.can_attack_bot(w, m, foe, now) and random.random() < 0.4 + 0.5 * m.bot.o('helpfulness'):
            m.target = foe.id


def ctb_start_raid(c, w, now):
    """A raid on the player's X-2: a carrier and (by what bots fit) up to RAID_ESCORTS escorts of the same company that screen it."""
    import capture_beacon as CB
    import team_deathmatch as TDM
    enemy = random.choice([x for x in CB.COMPANIES if x != c.company()])
    b = CB.beacon(c.company(), enemy)
    if c.where.get(b):
        return []
    band = {'min_level': CB.D['min_level'], 'max_level': 999}
    bots = TDM.pick_bots(enemy, band, CB.D['min_level'] + 5, now, set())
    if not bots:
        return []
    bot = bots[0]
    k = min(RAID_ESCORTS, len(bots) - 1, int(random.random() * (1 + RAID_ESCORTS * (0.3 + bot.o('sociability')))))
    party = bots[1:1 + max(0, k)]
    TDM.draft_bots([bot] + party, int(w.map_id), now, 1800)
    c.raider = dict(bot=bot, beacon=b, carrying=False, until=now + CB.D['raid_max_sec'], world=w, party=party)
    TDM.hold(c, lambda: w, lambda: c.end_raid(None))          # logout / disconnect on the X-2: the raiders are released
    c.log('   CTB: %s (%s) raids for beacon %d with %d escorts' % (bot.name, CB.NAMES[enemy], b, len(party)))
    return []


def ctb_end_raid(c, w):
    import team_deathmatch as TDM
    r, c.raider = c.raider, None
    msgs = []
    if r is None:
        return msgs
    TDM.unhold(c)
    body = r['bot'].body
    if body is not None:
        body.images.pop('ctb', None)
    if r['carrying']:
        c.where[r['beacon']] = 0
        msgs += [('CTBBeaconReleasedCommand', dict(userId=r['bot'].uid, beaconId=r['beacon'])),
                 ('CTBBeaconPositionCommand', dict(beaconId=r['beacon'], mapId=0))]
    TDM.release_bots(w, [(x, {}) for x in [r['bot']] + r.get('party', [])], int(r['bot'].k['map']), 'ctb_done')
    return msgs


def ctb_think(c, w, n, now):
    """The raid party: the carrier flies to the beacon's place and takes it (the cloak and speed rules apply to it too), then runs to the
    nearest portal; before the pickup it fights back only when no escort is with it. The escorts fly beside the carrier and fight whoever
    comes near it."""
    import capture_beacon as CB
    from bot import ship as BS
    D = CB.D
    r = c.raider
    if r is None:
        return False
    party = r.get('party', [])
    nx, ny = n.mover.pos(now)
    if n.bot is not r['bot']:
        if n.bot not in party:
            return False
        car = r['bot'].body
        if car is None or not car.alive:
            return False
        cx, cy = car.mover.pos(now)
        best = None
        for m in w.npcs.values():                          # whoever is near the carrier, a bot or the player's company
            if m.bot is None or not m.alive or m.bot.company == n.bot.company:
                continue
            mx, my = m.mover.pos(now)
            dd = math.hypot(mx - cx, my - cy)
            if dd < 1000 and (best is None or dd < best[0]) and BS.can_attack_bot(w, n, m, now):
                best = (dd, m.id, (mx, my))
        if not w.hero_dead and int(c.p.d['pilot'].get('factionId') or 0) != n.bot.company:
            hx, hy = w.hero_pos(now)
            dd = math.hypot(hx - cx, hy - cy)
            if dd < 1000 and (best is None or dd < best[0]) and BS.can_attack_player(w, n, w, now):
                best = (dd, w.hid, (hx, hy))
        if best is not None and math.hypot(best[2][0] - cx, best[2][1] - cy) < 1000:
            n.target = best[1]
            BS.approach(w, n, best[2], now)
            return True
        n.target = None
        BS._go_to(w, n, *_offset(n, 'escort', cx, cy, 350), now, threshold=150)
        return True
    attacked = any(now - t < 4 for t in n.attacker.values())
    if not r['carrying']:
        escorted = any(x.body is not None and x.body.alive and math.hypot(x.body.mover.pos(now)[0] - nx, x.body.mover.pos(now)[1] - ny) < 1200
                       for x in party)
        if attacked and not escorted:
            return False
        zx, zy = CB.zone(r['beacon'])
        if math.hypot(nx - zx, ny - zy) <= D['zone_radius'] * 0.7:
            r['carrying'] = True
            c.where[r['beacon']] = int(w.map_id)
            n.__dict__.pop('hidden', None)
            n.effect.add('slow', 3600, D['carrier_slow'], 'ctb', now)
            cap = ('CTBBeaconCapturedCommand', dict(userId=n.id, beaconId=r['beacon']))
            n.images['ctb'] = cap                         # the beacon on the ship again when it comes into view (world.show)
            w.send([cap, ('CTBBeaconPositionCommand', dict(beaconId=r['beacon'], mapId=int(w.map_id)))])
            c.log('   CTB: %s took beacon %d' % (n.bot.name, r['beacon']))
            say(n, 'carrier', now)
        else:
            BS._go_to(w, n, zx, zy, now)
        return True
    if attacked:
        AB.request(w, n, 'speed', now)
    gates = H.gates(int(w.map_id), n.bot.company)
    gt = min(gates, key=lambda gt: math.hypot(gt['x'] - nx, gt['y'] - ny))
    if math.hypot(gt['x'] - nx, gt['y'] - ny) <= 200:
        st = CB.state(c.p)
        st['scores'][str(n.bot.company)] += 1    # it reaches its X-2 and delivers it (the beacon goes home)
        c.p.dirty = True
        r['carrying'] = False
        c.where[r['beacon']] = 0
        n.images.pop('ctb', None)
        w.send([('CTBBeaconReleasedCommand', dict(userId=n.id, beaconId=r['beacon'])),
                ('CTBBeaconPositionCommand', dict(beaconId=r['beacon'], mapId=0)), c.score_cmd()])
        c.log('   CTB: %s escaped with beacon %d' % (n.bot.name, r['beacon']))
        w.send(c.end_raid(w))
        return True
    BS._go_to(w, n, gt['x'], gt['y'], now)
    return True


def ctb_bot_died(c, w, t, killer_uid):
    """The carrier was destroyed: the beacon goes home, the raid is over; an escort's death is a normal one (it leaves the party)."""
    r = c.raider
    if r is None:
        return None
    if t.bot is r['bot']:
        w.send(c.end_raid(w))
    elif t.bot in r.get('party', []):
        r['party'].remove(t.bot)
    return None


# ------------------------------------------------------------------------------------------------ Spaceball
SB_JOIN_SEC = (60, 180)  # how long a bot's choice to play (or not) for the ball holds before it decides again


def spaceball_bots(s, w, n, now):
    """Once a second: the bots on 4-4 decide by personality whether they play (not everyone on the map is pulled in; busy ones never);
    the players fly to the ball and shoot it (an alien they were grinding is dropped, a pilot fight is not); when another company leads
    the push, part of them near the ball (the aggressive ones) attack the leaders' shooters instead, the others keep shooting; the
    company that takes the lead calls it out."""
    import spaceball as SB
    from bot import ship as BS
    bx, by = n.mover.pos(now)
    owner = s.owner
    shooters = collections_by_company(w, n, now)
    for b in list(w.npcs.values()):
        if b.bot is None or not b.alive:
            continue
        x, y = b.mover.pos(now)
        d = math.hypot(x - bx, y - by)
        st = b.__dict__.get('tt_ball')
        if st is None or now >= st[1]:
            goal = b.bot.target
            busy = goal is not None and goal.name in ('gate', 'mod', 'duel', 'pvp_match', 'group', 'resting')
            k = b.bot
            want = 0.15 + 0.35 * k.o('sociability') + 0.25 * k.o('aggression') + 0.15 * k.o('ambition')
            plays = not busy and not k.en_route and random.random() < want
            st = b.tt_ball = (plays, now + random.uniform(*SB_JOIN_SEC))
            if not plays and b.target == n.id:
                b.target = None                            # its time with the ball is over
        if not st[0]:
            continue
        mine = b.bot.company
        t = w.npcs.get(b.target) if b.target is not None else None
        if t is not None and t is not n and t.alive and t.bot is not None:
            continue                                       # busy with a pilot: the body handles that fight (an alien it drops)
        if d <= SB.D['bot_range'] and owner and owner != mine and random.random() < 0.25 + 0.5 * b.bot.o('aggression'):
            foes = shooters.get(owner, [])
            foe = min(foes, key=lambda m: math.hypot(m.mover.pos(now)[0] - x, m.mover.pos(now)[1] - y), default=None)
            if foe is not None and BS.can_attack_bot(w, b, foe, now):
                b.target = foe.id                          # the push is theirs: hit their shooters
                continue
        if b.target != n.id and (d > SB.D['bot_range'] or random.random() < SB.D['bot_chance'] * (1.5 if owner == mine else 1.0)):
            # (a player far away flies to the ball: the body approaches its target)
            b.target = n.id
            if owner == mine:
                say(b, 'goal_push', now)


def collections_by_company(w, ball, now):
    out = {}
    for m in w.npcs.values():
        if m.bot is not None and m.alive and m.target == ball.id:
            out.setdefault(m.bot.company, []).append(m)
    return out
