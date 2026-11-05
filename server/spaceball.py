"""Spaceball (darkorbitwiki events/space-ball, 2022-08-10; fandom Spaceball; the client's SpaceBall* handlers and window). Research:
belgeler/arastirma/PVP_MODLARI.md section 4.

Real rules kept: the ball is on 4-4 (a green dot on the minimap); the companies shoot it to bring it to their own portal on 4-4, the one to
their X-5; a goal drops cargo boxes (FROM_SPACEBALL) at that portal for whoever is quicker (the wiki's prize list: 457 SAB-50, 241 UCB-100,
48 PLT-2021, 149 uridium, 10 extra energy, 3 repair vouchers, 2 jump vouchers); the company that wins the day gets bonuses for the next day
(the wiki's examples: +10% EP, +5% cargo selling, +2% bonus boxes); the client's window shows each company's goals and the speed arrows of
the company the ball is heading for; "%COMPANY% has just scored a goal!".
Adaptation (data/extra_events.json "_adaptation"): the ball heads for the portal of the company that dealt the most damage in the last
10 seconds, faster the bigger its lead (speed 1-3); the bot pilots on 4-4 shoot it too; one box per prize; the day's winner is the company
with the most goals (a tie: nobody); the model by season (summer 442, winter 443, football 444).
"""
import collections, math, random, time

import event_calendar as CAL
import game_data as DATA
import map_links as H
from legacy_protocol import stm

EVENT = 'spaceball'
D = DATA.load('extra_events.json').get('spaceball', {})
COMPANIES = (1, 2, 3)
NAMES = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
X5 = {1: 17, 2: 21, 3: 25}                        # the companies' X-5 (1-5, 2-5, 3-5): their portals on 4-4 are the goals


def active(now=None):
    return bool(D) and CAL.is_active(EVENT, now)


def day(now=None):
    return time.strftime('%Y-%m-%d', time.localtime(now or time.time()))


def state(p, now=None):
    st = p.d.setdefault('spaceball', {})
    st.setdefault('scores', {'1': 0, '2': 0, '3': 0})
    return st


def roll_day(p, company, now=None):
    """A new day: yesterday's company with the most goals gets the next day's bonus (wiki); the scores start over."""
    st = state(p, now)
    today = day(now)
    if st.get('day') == today:
        return False
    if st.get('day'):
        sc = st['scores']
        top = max(sc.values())
        leaders = [c for c, v in sc.items() if v == top]
        if top > 0 and len(leaders) == 1 and int(leaders[0]) == company:
            st['bonus_until'] = (now or time.time()) + 24 * 3600
    st.update(day=today, scores={'1': 0, '2': 0, '3': 0})
    p.dirty = True
    return True


def company_mods(p):
    """The day's winning company bonus (wiki's examples): +10% EP, +5% cargo selling, +2% bonus box content."""
    if time.time() >= p.d.get('spaceball', {}).get('bonus_until', 0):
        return {}
    b = D.get('company_bonus', {})
    return {'ep': b.get('ep', 0.1), 'ore_price': b.get('ore_price', 0.05), 'bonus_box_extra': b.get('bonus_box', 0.02)}


def model(now=None):
    m = time.localtime(now or time.time()).tm_mon
    return '444' if m in (6, 7) else '443' if m in (11, 12, 1, 2) else '442'


def goals(map_id):
    """The goal portals on 4-4: company -> (x, y, gate id) of its portal to its X-5."""
    out = {}
    for c, dest in X5.items():
        for g in H.gates(int(map_id), c):
            if int(g['target']) == dest:
                out[c] = (g['x'], g['y'], g.get('id', dest))
    return out


class Spaceball:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.ball = None
        self.hits = collections.deque()      # (time, company, damage)
        self.owner, self.speed = 0, 0
        self.next_step = 0.0
        self.goal_at = {}

    def company(self):
        return int(self.p.d['pilot'].get('factionId') or 1)

    def init_cmd(self):
        sc = state(self.p)['scores']
        return ('SpaceBallInitializeScoreCommand', dict(scoreMars=int(sc['1']), scoreEarth=int(sc['2']), scoreVenus=int(sc['3']),
                                                       ownerFactionId=self.owner, speed=self.speed))

    def login_msgs(self):
        if active():
            roll_day(self.p, self.company())
            return [self.init_cmd()]
        return []

    def attach(self, world):
        self.world = world
        self.ball = None
        self.hits.clear()
        self.owner, self.speed = 0, 0
        if not active() or int(world.map_id) != D['map']:
            return []
        roll_day(self.p, self.company())
        self.goal_at = goals(world.map_id)
        x, y = D.get('start') or (world.map_w // 2, world.map_h // 2)
        world.later(1.0, lambda: self.spawn(world, x, y))
        return [self.init_cmd()]

    def spawn(self, w, x, y):
        if w is not self.world:
            return
        with w.lock:
            # the map's saved state may bring the ball back (re-entering 4-4): that one is used, never a second ball
            n = next((m for m in w.npcs.values() if m.tip == D['npc'] and m.alive), None) or w.spawn_npc_at(D['npc'], x, y, model=model())
            for m in [m for m in w.npcs.values() if m.tip == D['npc'] and m is not n]:
                w.send(w.remove_npc(m))
        n.damage_hook = lambda dmg: self.hit(self.company(), dmg)      # the player's (and the P.E.T.'s) hits
        n.company_damage = self.hit                                      # a bot pilot's hits (bot/ship.hit_npc)
        self.ball = n
        self.log('   Spaceball: the ball on %s' % H.name(w.map_id))

    def hit(self, company, dmg):
        if dmg > 0:
            self.hits.append((time.time(), int(company), int(dmg)))

    def lead(self, now):
        """The company the ball heads for and its speed (1-3) from the damage of the last seconds."""
        while self.hits and now - self.hits[0][0] > D['window_sec']:
            self.hits.popleft()
        dmg = {c: 0 for c in COMPANIES}
        for _, c, d in self.hits:
            dmg[c] = dmg.get(c, 0) + d
        top = sorted(dmg.items(), key=lambda kv: -kv[1])
        if top[0][1] <= 0 or top[0][1] == top[1][1]:
            return 0, 0
        share = (top[0][1] - top[1][1]) / float(top[0][1])
        return top[0][0], 1 + min(2, int(share * 3))

    def tick(self, now):
        w, n = self.world, self.ball
        if w is None or n is None or now < self.next_step:
            return []
        self.next_step = now + 1.0
        if not n.alive or n.id not in w.npcs:
            self.ball = None
            return []
        n.hp, n.shield = n.d['hp'], n.d['shield']         # the ball cannot be destroyed
        msgs = []
        owner, speed = self.lead(now)
        if (owner, speed) != (self.owner, self.speed):
            self.owner, self.speed = owner, speed
            msgs.append(('SpaceBallUpdateSpeedCommand', dict(factionId=owner, speed=speed)))
        bx, by = n.mover.pos(now)
        if owner and owner in self.goal_at:
            gx, gy, gid = self.goal_at[owner]
            if math.hypot(gx - bx, gy - by) <= D['goal_radius']:
                return msgs + self.goal(owner, gx, gy, gid)
            ms = n.mover.go(gx, gy, D['speeds'][speed - 1], now)
            w.send([('MoveCommand', dict(userId=n.id, x=int(gx), y=int(gy), timeToTarget=ms))])
        elif n.mover.t1 > now:
            w.stop_npc_motion(n, now)
        self.bots(w, n, now)
        return msgs

    def bots(self, w, n, now):
        """The bot pilots near the ball shoot it now and then (they push it to their own portal: the most damage leads it)."""
        bx, by = n.mover.pos(now)
        for b in list(w.npcs.values()):
            if b.bot is None or not b.alive or b.target is not None and b.target != n.id:
                continue
            x, y = b.mover.pos(now)
            if math.hypot(x - bx, y - by) <= D['bot_range'] and random.random() < D['bot_chance']:
                b.target = n.id

    def goal(self, company, gx, gy, gid):
        """A goal: the company's score, the announcement, the cargo boxes at its portal, the ball back to the middle."""
        w, n = self.world, self.ball
        st = state(self.p)
        st['scores'][str(company)] = st['scores'].get(str(company), 0) + 1
        self.p.dirty = True
        for i, (loot, amount) in enumerate(D['prizes']):
            a = 2 * math.pi * i / len(D['prizes'])
            h = w.drop_box(D['box'], int(gx + math.cos(a) * 250), int(gy + math.sin(a) * 250), None, D['box_life_sec'])
            w.boxes[h]['event'] = {'contents': [[loot, amount]], 'mod': 'all'}
        cx, cy = D.get('start') or (w.map_w // 2, w.map_h // 2)
        n.mover = type(n.mover)(cx, cy)
        self.hits.clear()
        self.owner, self.speed = 0, 0
        self.log('   Spaceball: %s scored (%d)' % (NAMES[company], st['scores'][str(company)]))
        return [('SpaceBallUpdateScoreCommand', dict(factionId=company, score=int(st['scores'][str(company)]), gateId=int(gid))),
                ('SpaceBallUpdateSpeedCommand', dict(factionId=0, speed=0)),
                ('MoveCommand', dict(userId=n.id, x=int(cx), y=int(cy), timeToTarget=0)),
                stm('msg_spaceball_company_scored', '%COMPANY%', NAMES[company])]
