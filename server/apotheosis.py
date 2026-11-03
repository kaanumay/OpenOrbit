"""Kristallon Apotheosis (client 1.1.115; data data/major_content.json 'kristallon_apotheosis' <- tools/version_115.py).

On the calendar (21 Oct 2026 - end of 2027: official server record), Monday to Saturday, there are three collection windows (08-10,
14-16, 20-22; always open in two-hour slices with the panel's "Session events always open" setting): in X-2..X-8 the target points are
collected by killing event aliens (Icy, Kristallon, Boss Kristallon copies; points by map class). When the target is reached the
aliens withdraw and a portal (design 307) opens in 1-1 / 2-1 / 3-1: on map 510 there is a 5 min wait, then Emperor Kristallon
(EMPEROR_KRISTALLON_BOSS_2, npcId 518) stays for 30 min. Its attacks use the client's effects (VisualModifierCommand, the client's
VisualModifierAssemblyHelper):
  phase 1 (100-66%): rift (159, active; additionalAttribute "x1|y1|x2|y2": a line from the boss through the player's position and
          beyond; the client detonates it after 2.1 + 2 s): the ship on the line takes 20% of its HP
  phase 2 (66-33%): + ice (158, attribute player; 2.2 s): damage and slowdown to the player in range (the client draws it on the player)
  phase 3 (33-0%): + radiation (160 on the player, "x|y" safe point: guide arrow): when the time runs out, damage outside the safe area
Dying does not end the fight (back to the base; the portal can be re-entered while open, the boss keeps its remaining HP). On defeat:
participation reward (row of the boss level), defeat reward (one item from the table), 20 Apotheosis Booty Box (with a key; loot.py
APOTHEOSIS), last hit (title, 1 key), boss level +1 (max 12). If it escapes, only the participation reward (if the damage exceeded 1% of
the boss's HP). The week resets on Monday (level 1); the rewards of the previous week's virtual ranking (from the defeat count) are
given at that moment.
Window (menu item 'apotheosis', UIDarkMatterWar in the client): on opening, ApotheosisProgressRequest -> ApotheosisProgressCommand
{phase 0 WAITING / 1 COLLECTING / 2 BOSS, currentPoints / totalPoints, remainingSeconds, hpPercent, bossLevel, participation / defeat /
last-hit rewards (LootProbabilityModule), weekly ranking}. The key counter in the HUD is "0|A|BKAPO|n".
In the profile: apotheosis {week, level, points, window, state (collecting / boss / done), boss_hp, defeats, participation, last_hit, damage}.
"""
import datetime, json, math, os, random, time

import settings as SET
import world as world_module
import event_gate as EKP
import map_links as H
import galaxy_gates as GALAXY
import pve_common as PS
import event_calendar as CAL
from world_boss import mod, rewards, scale, seg_dist
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'major_content.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('kristallon_apotheosis', {})
EVENT = D.get('event', 'kristallon_apotheosis')
MAP = D.get('map', 510)
PORTAL_ID = EKP.PORTAL_BASE + 97           # boss portal in 1-1 / 2-1 / 3-1
EXIT_ID = EKP.PORTAL_BASE + 98             # return to the base on the map
BOSS = 'apo_emperor'
ICE, RIFT, GUIDE = 158, 159, 160
WAITING, COLLECTING, FIGHT = 0, 1, 2       # ApotheosisProgressCommand.phase (the client's Phase enum)
SLICE = 2 * 3600                           # session_always_open: window slice
KEY = 'resource_booty-key-apotheosis'


def _register():
    T = world_module.CFG['types']
    for rows in D.get('collecting', {}).values():
        for tip, _, _ in rows:
            if tip in T:
                # model: for types whose type key is the model itself (79, 35), the copy's name ("apo_79") was not drawn in the client
                T['apo_' + tip] = dict({k: v for k, v in T[tip].items() if k not in ('maps', 'event')}, model=T[tip].get('model', tip))
    if D.get('boss'):
        T[BOSS] = dict(D['boss'])


_register()


def active(now=None):
    return EVENT in CAL.active(now)


def _hm(s):
    h, m = s.split(':')
    return int(h), int(m)


def window(now=None):
    """(open, start, end, next start): Monday-Saturday windows; always_open_sessions: two-hour slices."""
    now = time.time() if now is None else now
    if SET.get('session_always_open'):
        a = now - now % SLICE
        return True, a, a + SLICE, a + SLICE
    t = datetime.datetime.fromtimestamp(now)
    spans = []
    for day in range(-1, 3):
        base = (t + datetime.timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        if base.weekday() not in D.get('days', range(7)):
            continue
        for a, b in D.get('windows', []):
            (ah, am), (bh, bm) = _hm(a), _hm(b)
            spans.append((base.replace(hour=ah, minute=am).timestamp(), base.replace(hour=bh, minute=bm).timestamp()))
    spans.sort()
    for a, b in spans:
        if a <= now < b:
            return True, a, b, next((x for x, _ in spans if x > a), a + 86400)
    return False, None, None, next((a for a, _ in spans if a > now), now + 86400)


def week_id(now=None):
    y, w, _ = datetime.date.fromtimestamp(time.time() if now is None else now).isocalendar()
    return '%d-W%02d' % (y, w)


def week_end(now=None):
    """The moment the week resets: next Monday 00:00."""
    d = datetime.date.fromtimestamp(time.time() if now is None else now)
    return datetime.datetime.combine(d + datetime.timedelta(days=7 - d.weekday()), datetime.time()).timestamp()


def probs(rows):
    return [mod('LootProbabilityModule', lootId=l, probabilityPercentage=float(p), minLootAmount=int(n), maxLootAmount=int(n))
            for l, n, p in rows]


def virtual_rank(kills):
    return next((r for need, r in D.get('virtual_rank', []) if kills >= need), None)


def rank_row(rank):
    return next((x for x in D.get('ranking', []) if rank and x['from_'] <= rank <= x['e']), None)


class Apotheosis:
    REQUESTS = ('ApotheosisProgressRequest',)

    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.world = None
        self.run = None
        self.change_map = None
        self.titles = None
        self.saved = None                       # boss state after leaving the map (it persists when the portal is re-entered while open)
        self.spawned = set()                    # this map's collection aliens

    @property
    def st(self):
        return self.p.d.setdefault('apotheosis', {})

    def level(self):
        return min(max(1, self.st.get('level', 1)), len(D['participation']))

    # ------------------------------------------------------------ state
    def ensure(self, now=None):
        """Week and window changes -> messages (the week's ranking rewards, start and end of collection)."""
        now = time.time() if now is None else now
        st, msgs = self.st, []
        wk = week_id(now)
        if st.get('week') != wk:
            if st.get('week'):
                msgs += self.week_rewards()
            with self.p.lock:
                st.update(week=wk, level=1, defeats=0, participation=0, last_hit=0, damage=0)
                self.p.dirty = True
        open_, a, b, nxt = window(now)
        if open_ and st.get('windowed') != a and st.get('state') != 'boss':      # a boss fight in progress is not reset by a new window
            with self.p.lock:
                st.update(windowed=a, points=0, state='collecting')
                self.p.dirty = True
            self.saved = None
            msgs.append(legacy('0|A|STM|kristallon_apotheosis_start_event'))
            self.log('   Kristallon Apotheosis: collection started')
        elif st.get('state') == 'collecting' and not open_:
            with self.p.lock:
                st['state'] = 'finished'
                self.p.dirty = True
            msgs.append(legacy('0|A|STM|kristallon_apotheosis_not_completed'))
        elif st.get('state') == 'boss' and now >= st.get('boss_start', 0) + D['cooldown_sec'] + D['combat_sec'] + D['closing_sec'] \
                and not (self.run and self.run.phase not in ('finished', 'closed')):
            with self.p.lock:
                st['state'] = 'finished'
                self.p.dirty = True
        return msgs

    def phase(self):
        return {'collecting': COLLECTING, 'boss': FIGHT}.get(self.st.get('state'), WAITING)

    def week_rewards(self):
        """The finished week's virtual ranking (single player: from the defeat count) -> rewards and title."""
        rank = virtual_rank(self.st.get('defeats', 0))
        row = rank_row(rank)
        if not row:
            return []
        msgs = []
        for loot, n in row['rewards']:
            msgs += self.m.prize(loot, n)
        if self.titles:
            msgs += self.titles(row['title'])
        msgs.append(GALAXY.screen('Kristallon Apotheosis weekly rank: %d' % rank, big=True))
        self.log('   Kristallon Apotheosis weekly ranking %d' % rank)
        return msgs

    # ------------------------------------------------------------ window
    def progress_cmd(self, now=None):
        now = time.time() if now is None else now
        st = self.st
        open_, a, b, nxt = window(now)
        ph = self.phase() if active(now) else WAITING
        if ph == COLLECTING:
            left = b - now
        elif ph == FIGHT:
            left = st.get('boss_start', now) + D['cooldown_sec'] + D['combat_sec'] - now
        else:
            left = (nxt if not open_ else b) - now
        lv = self.level()
        kills = st.get('defeats', 0)
        rank = virtual_rank(kills)
        row = rank_row(rank)
        me = mod('ApotheosisRankingEntryModule', userId=self.p.user_id, name=self.p.d['pilot'].get('userName', ''),
                 damage=int(st.get('damage', 0)), rewards=rewards(row['rewards']) if row else [])
        cap = D.get('weekly_limit', {})                     # official server record: participation 3, defeat 3, last hit 18
        return ('ApotheosisProgressCommand', dict(
            phase=ph, currentPoints=int(min(st.get('points', 0), D['target_points'])), totalPoints=int(D['target_points']),
            remainingSeconds=max(0, int(left)), hpPercent=int(round(self.boss_left() * 100)), bossLevel=lv,
            rewardStatusIncluded=True, nextResetTime=int(week_end(now) * 1000),     # reset moment, ms (record)
            timeToEventEndSeconds=int(CAL.time_left(EVENT, now)) if active(now) else 0,
            participationReward=mod('ApotheosisRewardModule', rewards=probs([r + [100] for r in D['participation'][lv - 1]]),
                                    claimedCount=int(st.get('participation', 0)), weeklyLimit=cap.get('participation', 0)),
            victoryReward=mod('ApotheosisRewardModule', rewards=probs(D['defeats']), claimedCount=int(kills),
                              weeklyLimit=cap.get('defeats', 0)),
            lastHitReward=mod('ApotheosisRewardModule', rewards=probs([r + [100] for r in D['last_hit']['rewards']]
                                                                       + [[D['last_hit']['title'], 1, 100]]),     # the title too (record)
                              claimedCount=int(st.get('last_hit', 0)), weeklyLimit=cap.get('last_hit', 0)),
            weeklyRanking=[me] if st.get('damage') else []))

    def boss_left(self):
        if self.run and self.run.boss and self.run.boss.alive:
            return self.run.left()
        if self.saved:
            return self.saved['ratio']
        return 1.0

    def handle(self, name, f):
        self.ensure()
        return [self.progress_cmd()]

    # ------------------------------------------------------------ collection
    def add_points(self, n):
        st = self.st
        if st.get('state') != 'collecting':
            return []
        with self.p.lock:
            st['points'] = st.get('points', 0) + n
            self.p.dirty = True
        if st['points'] < D['target_points']:
            return []
        with self.p.lock:
            st.update(state='boss', boss_start=time.time())
            self.p.dirty = True
        self.saved = None
        self.log('   Kristallon Apotheosis: target points reached, portals opened')
        return [legacy('0|A|STM|kristallon_apotheosis_start_portal'), GALAXY.screen('key:kristallon_apotheosis_start_portal', big=True)]

    def collect_rows(self, world):
        return D.get('collecting', {}).get(H.map_class(world.map_id), [])

    def spawn_collect(self, world, tip=None, pts=None, count=1):
        """Collection aliens (the map's rows; if a type is given, only `count` of that type)."""
        g = D['power'].get(H.map_class(world.map_id), 1.0)
        rows = [[tip, pts, count]] if tip else self.collect_rows(world)
        for t, p, n in rows:
            for _ in range(n):
                x, y = world.random_spot()
                npc = world.spawn_npc_at('apo_' + t, x, y, prep=lambda c: PS.scale_npc(c, hp=g, dmg=g, reward=g))
                npc.gate, npc.apo = True, (t, p)
                self.spawned.add(npc.id)

    def clear_collect(self):
        w = self.world
        if not w:
            return
        for i in list(self.spawned):
            n = w.npcs.get(i)
            if n and n.alive:
                w.send(w.remove_npc(n))
        self.spawned.clear()

    # ------------------------------------------------------------ portals
    def portals(self, map_id, station):
        if int(map_id) == MAP or not station or H.name(map_id) not in D.get('entries', []):
            return []
        self.ensure()
        if not active() or self.st.get('state') != 'boss':
            return []
        sx, sy = station['posX'], station['posY']
        cx, cy = GALAXY.MAP_W // 2, GALAXY.MAP_H // 2
        x, y = int(sx + (cx - sx) * 0.35), int(sy + (cy - sy) * 0.35 - 1200)
        return [dict(gateId=PORTAL_ID, x=x, y=y, target=0, designId=D.get('portal_design', 307), windowed='apotheosis',
                     hint_target=MAP)]

    def portal_window(self, g, w, go):
        self.ensure()
        if not active() or self.st.get('state') != 'boss':
            w.send([legacy('0|A|STM|kristallon_apotheosis_not_enabled')])
            return
        go(MAP, (GALAXY.MAP_W // 2 + random.randint(-800, 800), GALAXY.MAP_H // 2 + 2500))

    # ------------------------------------------------------------ world
    def attach(self, world):
        if self.run and self.run.w is not world and self.run.boss and self.run.boss.alive:
            self.saved = self.run.snapshot()
        self.world = world
        self.run = None
        self.spawned = set()
        msgs = self.ensure()
        if int(world.map_id) == MAP:
            if not active() or self.st.get('state') != 'boss':
                import vortex
                vortex.send_home(self, world)              # no fight (spawned on this map on login): to the base
                return msgs
            self.run = ApoRun(self, world, self.saved)
            self.saved = None
            world.gate = self.run
            return msgs + self.run.enter_msgs()
        if active() and self.st.get('state') == 'collecting' and self.collect_rows(world):
            self.spawn_collect(world)
        return msgs

    def on_kill(self, w, npc, x, y):
        if self.run and self.run.w is w:
            return self.run.on_kill(npc, x, y)
        if npc.id not in self.spawned:
            return []
        self.spawned.discard(npc.id)
        tip, pts = npc.apo
        msgs = [GALAXY.screen('Kristallon Apotheosis: +%d (%d/%d)' % (pts, min(self.st.get('points', 0) + pts, D['target_points']),
                                                                 D['target_points']))] if self.st.get('state') == 'collecting' else []
        msgs += self.add_points(pts)
        if self.st.get('state') == 'collecting':
            w.later(D.get('renew_sec', 15), lambda: self.world is w and self.st.get('state') == 'collecting'
                    and self.spawn_collect(w, tip, pts))
        else:
            self.clear_collect()
        return msgs

    def tick(self, now):
        if not active(now):
            return []
        before = self.st.get('state')
        msgs = self.ensure(now)
        w = self.world
        if w and before != self.st.get('state') and w.gate is None:
            if self.st.get('state') == 'collecting' and self.collect_rows(w):
                self.spawn_collect(w)                    # the window opened while the player was on an X-2..X-8 map
            elif before == 'collecting':
                self.clear_collect()
        return msgs

    def boss_defeated(self, last_hit=True):
        """Defeat: counters, rewards (boxes during the run; the defeat and last-hit rewards up to the weekly limit), level."""
        st, msgs = self.st, []
        lv = self.level()
        cap = D.get('weekly_limit', {})
        with self.p.lock:
            st['defeats'] = st.get('defeats', 0) + 1
            st['level'] = min(len(D['participation']), lv + 1)
            win = st['defeats'] <= cap.get('defeats', st['defeats'])
            last_hit = last_hit and st.get('last_hit', 0) < cap.get('last_hit', st.get('last_hit', 0) + 1)
            if last_hit:
                st['last_hit'] = st.get('last_hit', 0) + 1
            self.p.dirty = True
        loot, n, _ = random.choices(D['defeats'], [r[2] for r in D['defeats']])[0]
        if win:
            msgs += self.m.prize(loot, n)
        if last_hit:
            k0 = self.p.resource(KEY)
            for l, k in D['last_hit']['rewards']:
                msgs += self.m.prize(l, k)
            msgs += self.key_msgs(self.p.resource(KEY) - k0)          # amount coming with the panel's reward multiplier
            if self.titles:
                msgs += self.titles(D['last_hit']['title'])
        self.log('   Kristallon Apotheosis: boss defeated (level %d), %s' % (lv, 'defeat reward %s x%d' % (loot, n) if win else
                                                                            'weekly limit of the defeat reward reached'))
        return msgs

    def participation(self, lv):
        """Participation reward (up to the weekly limit)."""
        st, msgs = self.st, []
        with self.p.lock:
            if st.get('participation', 0) >= D.get('weekly_limit', {}).get('participation', st.get('participation', 0) + 1):
                return msgs
            st['participation'] = st.get('participation', 0) + 1
            self.p.dirty = True
        for loot, n in D['participation'][lv - 1]:
            msgs += self.m.prize(loot, n)
        return msgs

    def key_msgs(self, n):
        """Key received: the client's text (the shop's reward function sends the HUD counter)."""
        if n < 1:
            return []
        text = 'msg_booty-key-apotheosis_received_s' if n == 1 else 'msg_booty-key-apotheosis_received_p|%%AMOUNT%%|%d' % n
        return [legacy('0|A|STM|' + text)]

    def login_msgs(self):
        """The key counter in the HUD (the login tuple in the save has no BKAPO row: it came with 1.1.115)."""
        return [legacy('0|A|BKAPO|%d' % self.p.resource(KEY))]


class ApoRun:
    """Boss fight on map 510 (the world's `gate`)."""
    key = 'kristallon_apotheosis'

    def __init__(self, mode, world, restore=None):
        self.m, self.w = mode, world
        self.g = {'name': 'Kristallon Apotheosis'}
        st = mode.st
        self.boss_at = st.get('boss_start', time.time()) + D['cooldown_sec']
        if SET.get('session_always_open'):
            self.boss_at = min(self.boss_at, time.time() + 30)      # always open: short wait
        self.end = self.boss_at + D['combat_sec']
        if restore:                                  # the fight was in progress: boss right away, with its remaining HP and time
            self.boss_at, self.end = time.time(), restore['end_time']
        self.close_at = None
        self.phase = 'cooldown'
        self.boss = None
        self.s = 1.0
        self.stage = 1
        self.dealt = restore['damage'] if restore else 0
        self.restore = restore
        self.lv = mode.level()
        self.next = {}
        self.cx, self.cy = world.map_w // 2, world.map_h // 2
        self.guide = None

    def wave(self):
        return self.phase

    def enter_msgs(self):
        self.w.add_gate(dict(gateId=EXIT_ID, x=self.cx - 3000, y=self.cy + 2400, target=self.m.k.home() if self.m.k else 5,
                             designId=1, gate=self.key, exit=True, arrival='station'))
        if time.time() >= self.boss_at:
            self.spawn_boss()
            return []
        return [GALAXY.screen('Emperor Kristallon arrives in %d s.' % max(1, int(self.boss_at - time.time())), big=True)]

    def snapshot(self):
        b = self.boss
        return dict(ratio=self.left(), hp=b.hp / float(max(1, b.d['hp'])), shield=b.shield / float(max(1, b.d['shield'])),
                    damage=self.dealt, s=self.s, end_time=self.end)

    def boss_max(self):
        return self.boss.d['hp'] + self.boss.d['shield']

    def left(self):
        b = self.boss
        return (b.hp + b.shield) / float(max(1, self.boss_max())) if b else 1.0

    def spawn_boss(self):
        w, r = self.w, self.restore
        if r:
            self.s = r['s']
        else:
            probe = w.spawn_npc_at(BOSS, self.cx, self.cy)
            self.s = scale(self.m.p, w, probe) * (1 + D.get('level_multiplier', 0.15) * (self.lv - 1))
            w.remove_npc(probe)
        b = w.spawn_npc_at(BOSS, self.cx, self.cy - 800, prep=lambda n: PS.scale_npc(n, hp=self.s, dmg=max(0.5, min(1.5, self.s))))
        b.gate, b.engaged = True, True
        b.damage_hook = self.boss_hit
        if r:
            b.hp, b.shield = max(1, int(b.d['hp'] * r['hp'])), int(b.d['shield'] * r['shield'])
        self.boss = b
        self.phase = 'combat'
        now = time.time()
        self.next.update(rift=now + 8, ice=now + 12, radiation=now + 15)
        self.stage = next(i for i, th in reversed(list(enumerate(D['phases'], 1))) if self.left() <= th)
        w.send([GALAXY.screen('Emperor Kristallon has appeared!', big=True)])
        w.log('   Kristallon Apotheosis: Emperor Kristallon arrived (level %d, power %.2f, HP %d + %d)' % (self.lv, self.s, b.hp, b.shield))

    def boss_hit(self, dmg):
        self.dealt += dmg
        with self.m.p.lock:
            self.m.st['damage'] = self.m.st.get('damage', 0) + dmg
            self.m.p.dirty = True
        left = self.left()
        for i, th in enumerate(D['phases'][1:], 2):
            if self.stage < i and left <= th:
                self.stage = i
                self.w.send([GALAXY.screen('Emperor Kristallon: phase %d!' % i, big=True)])
                self.w.log('   Kristallon Apotheosis: phase %d' % i)

    # ------------------------------------------------------------ loop
    def tick(self, now):
        w = self.w
        if self.phase == 'closed':
            return
        if self.phase == 'cooldown':
            if now >= self.boss_at:
                self.spawn_boss()
            return
        if self.phase == 'finished':
            if now >= self.close_at:
                self.close()
            return
        if now >= self.end:
            self.escape()
            return
        b = self.boss
        if not b or not b.alive or w.hero_dead:
            return
        attacks = D['attacks']
        if now >= self.next['rift']:
            self.next['rift'] = now + attacks['rift']['interval_sec']
            self.rift(now)
        if self.stage >= 2 and now >= self.next['ice']:
            self.next['ice'] = now + attacks['ice']['interval_sec']
            self.ice(now)
        if self.stage >= 3 and now >= self.next['radiation'] and not self.guide:
            self.next['radiation'] = now + attacks['radiation']['interval_sec']
            self.radiation(now)

    def vm(self, uid, modifier, on, attr=0, extra=''):
        return ('VisualModifierCommand', dict(userId=uid, modifier=modifier, attribute=attr, additionalAttribute=extra,
                                              count=1 if on else 0, activated=on))

    def max_hp(self):
        return self.m.p.d['ship'].get('hitMax', 1)

    def rift(self, now):
        """Rift: a line from the boss through the player's position and beyond; the client detonates it at 4.1 s, the ship on the line
        takes damage."""
        w, b, R = self.w, self.boss, D['attacks']['rift']
        bx, by = b.mover.pos(now)
        hx, hy = w.hero_pos(now)
        d = math.hypot(hx - bx, hy - by) or 1.0
        ex, ey = bx + (hx - bx) / d * R['length'], by + (hy - by) / d * R['length']
        w.send([self.vm(b.id, RIFT, True, extra='%d|%d|%d|%d' % (bx, by, ex, ey))])

        def burst():
            w.send([self.vm(b.id, RIFT, False)])
            if b.alive and not w.hero_dead:
                px, py = w.hero_pos()
                if seg_dist(px, py, bx, by, ex, ey) <= R['width']:
                    w.send(w.hurt_hero(int(self.max_hp() * R['damage_max_hp_ratio']), b, atype=0))
        w.later(R['warning_sec'], burst)

    def ice(self, now):
        """Ice: thrown at the player in the boss's range (the client draws the explosion on the player, together with it); damage and
        slowdown after 2.2 s."""
        w, b, R = self.w, self.boss, D['attacks']['ice']
        bx, by = b.mover.pos(now)
        hx, hy = w.hero_pos(now)
        if math.hypot(hx - bx, hy - by) > R['radius']:
            return
        w.send([self.vm(b.id, ICE, True, attr=w.hid)])

        def burst():
            w.send([self.vm(b.id, ICE, False)])
            if b.alive and not w.hero_dead:
                w.send(w.hurt_hero(int(self.max_hp() * R['damage_max_hp_ratio']), b, atype=0))
                w.hero_effect('slow', R['slow'][1], R['slow'][0], source='apotheosis')
        w.later(R['warning_sec'], burst)

    def radiation(self, now):
        """Radiation: a guide on the player (arrow to the safe point); when the time runs out, the area outside the safe zone takes damage."""
        w, b, R = self.w, self.boss, D['attacks']['radiation']
        a = random.uniform(0, 2 * math.pi)
        sx = min(max(int(self.cx + math.cos(a) * 3000), 800), w.map_w - 800)
        sy = min(max(int(self.cy + math.sin(a) * 2000), 800), w.map_h - 800)
        self.guide = (sx, sy)
        w.send([self.vm(w.hid, GUIDE, True, extra='%d|%d' % (sx, sy)), GALAXY.screen('Radiation surge! Reach the safe zone.', big=True)])

        def burst():
            self.guide = None
            w.send([self.vm(w.hid, GUIDE, False)])
            if b.alive and not w.hero_dead:
                px, py = w.hero_pos()
                if math.hypot(px - sx, py - sy) > R['safe_radius']:
                    w.send(w.hurt_hero(int(self.max_hp() * R['damage_max_hp_ratio']), b, atype=0))
        w.later(R['warning_sec'], burst)

    # ------------------------------------------------------------ end
    def on_kill(self, npc, x, y):
        if not self.boss or npc.id != self.boss.id:
            return []
        w = self.w
        self.phase = 'finished'
        self.close_at = time.time() + D['closing_sec']
        msgs = self.m.participation(self.lv) + self.m.boss_defeated(last_hit=True)
        k = D['box']
        for i in range(k['count']):
            a = 2 * math.pi * i / k['count']
            r = 250 + 120 * (i % 3)
            w.drop_box(k['type'], x + math.cos(a) * r, y + math.sin(a) * r, None, k['lifetime_sec'])
        msgs += [legacy('0|A|STM|kristallon_apotheosis_finisher|%%PLAYER%%|%s' % self.m.p.d['pilot'].get('userName', '')),
                 legacy('0|A|STM|kristallon_apotheosis_completed'), GALAXY.screen('key:kristallon_apotheosis_completed', big=True)]
        with self.m.p.lock:
            self.m.st['state'] = 'finished'
            self.m.p.dirty = True
        w.log('   Kristallon Apotheosis: Emperor Kristallon defeated')
        return msgs

    def escape(self):
        w, b = self.w, self.boss
        self.phase = 'finished'
        self.close_at = time.time() + D['closing_sec']
        msgs = [GALAXY.screen('Emperor Kristallon has escaped.', big=True)]
        if b and self.dealt >= self.boss_max() * D.get('participation_threshold', 0.01):
            msgs += self.m.participation(self.lv)
        if b and b.alive:
            w.send(w.remove_npc(b))
        with self.m.p.lock:
            self.m.st['state'] = 'finished'
            self.m.p.dirty = True
        w.send(msgs)
        w.log('   Kristallon Apotheosis: boss escaped')

    def close(self):
        w = self.w
        self.phase = 'closed'
        w.send([GALAXY.screen('Kristallon Apotheosis is closing.', big=True)])
        if self.m.change_map and not w.hero_dead:
            home = self.m.k.home() if self.m.k else 5
            w.later(3.0, lambda: self.m.change_map(home, None, 'station'))

    def on_death(self):
        return None

    def revive(self):
        pass
