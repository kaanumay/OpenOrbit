"""World Boss 2025: Treacherous Domain / Dreadfyre Fortress (roadmap Ö4; data data/major_content.json 'world_boss').

On the calendar (17 June - 1 July) six windows a day (09, 11, 16, 19, 20, 22; 30 min; with the panel's "Sessioned events always open" setting the
portal is always open and the battle starts at login): free map 482 through the temporary portal in X-1 and X-8. The first 5 min are preparation (Harbingers; Dreadfyre Box: HP,
speed, shield or healing), then the Dreadfyre Fortress arrives and stays 20 min:
  phase 1: the Fortress takes no damage, circles around the middle of the map (collision damage to whatever is in its path); 4 Guardians fixed, magnetic field; on the first
          hit it calls Harbingers; at 1 HP it "falls". When all four have fallen
  phase 2: the Fortress can be hit; each active Guardian gives 25% damage reduction; every 30 s a Guardian rotates (one that stays up 20 s fires a homing rocket);
          the Fortress fires rockets, a radiation burst every 20 s, a ring minefield at 80%; at 50%
  phase 3: a map-wide laser (every 10 s, 3 s warning), mines at 50% and 30%, two Guardians rotate every 30 s; at 10%
  phase 4: the laser stops, radiation every 10 s, mines at 10%, four Guardians rotate and can now die.
The healing beacon in the middle heals 30,000 HP per second. If it is not killed it flees; the map closes after 5 min. Rewards: progress per battle (damage dealt to the
Fortress is 10/25/50/75/100% of its HP; each 3 times a day), 20 tiers over the event (total damage, per tier 0.5-2 times the battle's Fortress
HP; a title at the 20th), last hit (777 U, 777 Infiltrator Fragment, 777 UCB-100, Spirefall), battle ranking (single player:
a virtual rank from the share of HP removed; 1st and, if the Fortress died, Dread Overlord, top 10 Dread Warlord). HP scales with the player's power
(the equipment's sustained UCB-100 x6 damage / 60,000, 0.25-2.5). When the event ends Infiltrator Fragments go to honor (1:1).
Client: PublicWorldBossRequest {action 0} -> PublicWorldBossInfoCommand (opens window 0x82), 0.5 s later the Raid and Rank commands.
Rankings' Events page: RankingsEventsInfoRequest {rankType 0 today, 1 yesterday, 2 event} -> WorldBossRankingInfoCommand (only the
player's row: score is the damage dealt to the Fortress, rank is the best virtual battle rank of that period, timeTaken seconds: the client's FormatTime(sec)).
In the profile: world_boss {total, tier, h_ref, day, claimed {tier: count}, input, days {date: {damage, sn, order}} (today and
yesterday), event {damage, sn, order}, last (moment of the last hit)}.
"""
import datetime, json, math, os, random, threading, time

import settings as SET
import world as world_module
import event_gate as EKP
import map_links as H
import galaxy_gates as KAPI
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'major_content.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('world_boss', {})
EVENT = D.get('event', 'world_boss')
MAP = D.get('map', 482)
PORTAL_ID = EKP.PORTAL_BASE + 93           # the temporary portal in X-1 / X-8
EXIT_ID = EKP.PORTAL_BASE + 94             # return to base on the map
FORTRESS, GUARDIAN, HARBINGER = 'wb_fortress', 'wb_guardian', 'wb_harbinger'
ZONE, TELEGRAPH, BOSS_ESCAPE = 121, 122, 133                      # VisualModifierCommand (client: ring, rocket marker, escape)
LASER_PREP, LASER_CHARGE, LASER_SHOT = 134, 135, 136
POI_HEAL = 'worldBossHealingBeacon'
AMMO_BONUS = {'ammunition_laser_ucb-100': 6, 'ammunition_laser_rsb-75': 7}     # official FAQ: UCB-100 x6, RSB-75 x7 during the event
WINDOW = 30 * 60


def _register():
    for key, tip in (('dreadfyre_fortress', FORTRESS), ('dreadfyre_guardian', GUARDIAN), ('dreadfyre_harbinger', HARBINGER)):
        a = (D.get('npcs') or {}).get(key)
        if a:
            d = {k: v for k, v in a.items() if k not in ('orbit_radius',)}
            d['ammo_multiplier'] = dict(AMMO_BONUS)
            world_module.CFG['types'][tip] = d
    if FORTRESS in world_module.CFG['types']:
        world_module.CFG['types'][FORTRESS]['range'] = D['fortress_laser']['range']
        world_module.CFG['types'][FORTRESS]['damage'] = D['fortress_laser']['damage']


_register()


def active(now=None):
    return EVENT in CAL.active(now)


def _hm(s):
    h, m = s.split(':')
    return int(h), int(m)


def window(now=None):
    """(open, start, end, next start)."""
    now = time.time() if now is None else now
    if SET.get('session_always_open'):
        a = now - now % WINDOW
        return True, a, a + WINDOW, a + WINDOW
    t = datetime.datetime.fromtimestamp(now)
    spans = []
    for day in (-1, 0, 1):
        base = (t + datetime.timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        for a, b in D.get('windows', []):
            (ah, am), (bh, bm) = _hm(a), _hm(b)
            spans.append((base.replace(hour=ah, minute=am).timestamp(), base.replace(hour=bh, minute=bm).timestamp()))
    spans.sort()
    for a, b in spans:
        if a <= now < b:
            return True, a, b, next((x for x, _ in spans if x > a), a + 86400)
    return False, None, None, next((a for a, _ in spans if a > now), now + 86400)


def mod(_cls, **f):
    f['_'] = _cls
    return f


def rewards(rows):
    return [mod('RewardModule', lootId=l, amount=int(n)) for l, n in rows]


def title_mod(key):
    return mod('RewardTitleModule', titleKey=key) if key else None


class WorldBoss:
    REQUESTS = ('PublicWorldBossRequest', 'RankingsEventsInfoRequest')

    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.world = None
        self.run = None
        self.change_map = None
        self.titles = None
        self.send = lambda msgs: None             # the holder binds it (Raid/Rank after the window)
        self.saved = None                         # the state of a battle that continues after leaving the map (continues if returning in the same window)

    @property
    def st(self):
        d = self.p.d.setdefault('world_boss', {})
        today = datetime.date.today().isoformat()
        if d.get('day') != today:
            d.update(day=today, claimed={})
        for k, v in (('total', 0), ('tier', 0), ('h_ref', 0), ('claimed', {}), ('input', False)):
            d.setdefault(k, v)
        return d

    def h_ref(self):
        """Tier unit: the last battle's Fortress active HP (if none yet, computed from the player's power)."""
        return self.st['h_ref'] or int(scale(self.p, None) * (D['npcs']['dreadfyre_fortress']['hp'] + D['npcs']['dreadfyre_fortress']['shield']))

    def tier_need(self, k):
        row = D['tier'][k - 1]
        return int(row['multiplier'] * self.h_ref())

    # ------------------------------------------------------------ window
    def info_cmd(self, now=None):
        now = time.time() if now is None else now
        open_, a, b, nxt = window(now)
        st = self.st
        cur = min(st['tier'] + 1, len(D['tier']))
        need = self.tier_need(cur)
        have = need if st['tier'] >= len(D['tier']) else st['total']
        tiers = [mod('PublicWorldBossTier', rewardModuleList=rewards(r['rewards']), tierName='Tier %d' % r['tier'], to=r['tier'],
                     rewardTitleModule=title_mod(r.get('title')), **{'from': r['tier']}) for r in D['tier']]
        return ('PublicWorldBossInfoCommand', dict(publicWorldBossTierList=tiers, timeToNextRaidSeconds=0 if open_ else max(0, int(nxt - now)),
                                                   raiding=bool(open_ and active(now)),
                                                   timeToEventEndSeconds=int(CAL.time_left(EVENT, now)) if active(now) else 0,
                                                   currHealth=int(min(have, need)), maxHealth=int(max(1, need)), currTier=int(st['tier'])))

    def raid_cmd(self):
        run = self.run
        hp = run.fortress_max() if run else self.h_ref()
        done = run.dealt if run else 0
        return ('PublicWorldBossRaidCommand', dict(raidlist=[
            mod('PublicWorldBossRaidIntensity', currDamage=int(done), maxDamage=int(hp * r['ratio']), intensity=r['tier'],
                claim=int(self.st['claimed'].get(str(r['tier']), 0)), rewards=rewards(r['rewards']), claimLimit=r['daily'])
            for r in D['progress']]))

    def rank_cmd(self):
        return ('PublicWorldBossRankCommand', dict(ranklist=[
            mod('PublicWorldBossRankReward', rewardTitleModule=title_mod((r['titles'] or [None])[0]), to=r['e'], rewards=rewards(r['rewards']),
                **{'from': r['from_']}) for r in D['ranking']]))

    def ranking_cmd(self, kind):
        st = self.st
        day = (datetime.date.today() - datetime.timedelta(days=kind)).isoformat()
        row = (st.get('event') if kind == 2 else st.get('days', {}).get(day)) or {}
        me = mod('WorldBossRankingInfoModule', username=self.p.d['pilot'].get('userName', ''), score=min(int(row['damage']), 2 ** 31 - 1),
                 rank=int(row.get('order') or D['virtual_rank'][-1][1]), timeTaken=int(row.get('sec', 0))) if row.get('damage') else None
        return ('WorldBossRankingInfoCommand', dict(isActive=active(), titleStr='', myRank=me, prevRank=None, nextRank=None,
                                                    rankingInfoList=[me] if me else []))

    def tally(self, dmg=0, rank=None):
        """For Rankings and Hall of Fame: today's and the event's damage, time spent in battle (if the gap between hits is under 60 s), best rank."""
        now = time.time()
        st = self.st
        today = datetime.date.today()
        with self.p.lock:
            days = st.setdefault('days', {})
            for k in [k for k in days if k < (today - datetime.timedelta(days=1)).isoformat()]:
                del days[k]
            for row in (days.setdefault(today.isoformat(), {}), st.setdefault('event', {})):
                row['damage'] = row.get('damage', 0) + dmg
                if dmg and now - st.get('last', 0) < 60:
                    row['sec'] = row.get('sec', 0) + now - st['last']
                if rank:
                    row['order'] = min(row.get('order') or rank, rank)
            if dmg:
                st['last'] = now
            self.p.dirty = True

    def handle(self, name, f):
        if name == 'RankingsEventsInfoRequest':
            kind = int(f.get('rankType') or 0)
            return [self.ranking_cmd(kind)] if kind in (0, 1, 2) else []           # 3: Title Frenzy (title_hunt.py)
        later = [self.raid_cmd(), self.rank_cmd()]
        threading.Timer(0.5, lambda: self.send(later)).start()      # after the window is built (the client silently drops it otherwise)
        return [self.info_cmd()]

    # ------------------------------------------------------------ portals
    def portals(self, map_id, station):
        if int(map_id) == MAP:
            return []
        if not active() or not window()[0] or not station or H.map_class(map_id) not in D.get('entries', ['X-1', 'X-8']) \
                or H.company(map_id) != self.p.d['pilot'].get('factionId'):
            return []
        sx, sy = station['posX'], station['posY']
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2
        x, y = int(sx + (cx - sx) * 0.4), int(sy + (cy - sy) * 0.4 + 1300)
        return [dict(gateId=PORTAL_ID, x=x, y=y, target=0, designId=D.get('portal_design', 1), windowed='world_boss',
                     hint_target=MAP)]                # "This Jump Gate takes you to Treacherous Domain." (the client's map name)

    def portal_window(self, g, w, go):
        if not active() or not window()[0]:
            w.send([KAPI.screen('Treacherous Domain is closed.')])
            return
        go(MAP, (KAPI.MAP_W // 2 + random.randint(-600, 600), KAPI.MAP_H // 2 + 1500))

    # ------------------------------------------------------------ world
    def attach(self, world):
        if self.run and self.run.w is not world and self.run.phase not in ('finished', 'closed'):
            self.saved = self.run.snapshot()              # on dying and returning to base, or on leaving: the battle continues (official: re-enter while the window is open)
        self.world = world
        self.run = None
        if int(world.map_id) != MAP:
            return []
        open_, a, b, nxt = window()
        if not (open_ and active()):
            import vortex
            vortex.send_home(self, world)                  # window closed (spawned on this map at login): to base
            return []
        s = self.saved if self.saved and time.time() < self.saved['end'] else None
        self.saved = None
        if s:
            a, b = s['start'], s['end']
        elif SET.get('session_always_open'):                    # "always open": the battle starts at login (5 min preparation, 20 min boss)
            a, b = time.time(), time.time() + WINDOW
        with self.p.lock:
            self.st['input'] = True
            self.p.dirty = True
        self.run = WbRun(self, world, a, b, restore=s)
        world.gate = self.run
        return self.run.enter_msgs()

    def on_kill(self, w, npc, x, y):
        if self.run and self.run.w is w:
            return self.run.on_kill(npc, x, y)
        return []

    def add_damage(self, dmg):
        """Total damage over the event: rewards when a tier is passed (directly instead of the in-game mail)."""
        st = self.st
        msgs = []
        with self.p.lock:
            st['total'] += dmg
            self.p.dirty = True
        self.tally(dmg)
        while st['tier'] < len(D['tier']) and st['total'] >= self.tier_need(st['tier'] + 1):
            k = st['tier'] + 1
            with self.p.lock:
                st['total'] -= self.tier_need(k)
                st['tier'] = k
                self.p.dirty = True
            row = D['tier'][k - 1]
            for loot, n in row['rewards']:
                msgs += self.m.prize(loot, n)
                if loot == D.get('part', 'resource_collectable_infiltrator-fragment'):
                    self.p.ach('loot', loot=loot, amount=n)         # Treacherous Domain Pass: "Collect Infiltrator Fragments" (battle_pass.py)
            if row.get('title') and self.titles:
                msgs += self.titles(row['title'])
            msgs += legacy_line('log_msg_worldboss_tier_increase', BOSSNAME='Dreadfyre Fortress', TIER=k)
            self.log('   World Boss kademe %d' % k)
        return msgs

    def tick(self, now):
        if active(now):
            if self.st.get('period') is None:
                with self.p.lock:
                    self.st['period'] = (CAL.period(EVENT, now) or (now,))[0]
                    self.p.dirty = True
            return []
        st = self.p.d.get('world_boss')
        if not st or st.get('period') is None:
            return []
        frag = D.get('part', 'resource_collectable_infiltrator-fragment')
        n = self.p.resource(frag)
        msgs = []
        if n > 0:                                   # the event ended: the remaining fragments go to honor (official: after 24 h; no ratio, 1:1)
            self.p.add_resource(frag, -n)
            msgs += self.m.money_msgs()
            tot = self.p.gain(honor=n * D.get('fragment_honor', 1), reason='worldboss_fragments')
            msgs += legacy_line('history_msg_event_infiltrator_fragment_honor_converted', AMOUNT=n)
            self.log('   World Boss ended: %d Infiltrator Fragments to honor' % n)
        with self.p.lock:
            self.p.d['world_boss'] = {}
            self.p.dirty = True
        return msgs


def legacy_line(key, **params):
    return [legacy('0|A|STM|%s%s' % (key, ''.join('|%%%s%%|%s' % (k, v) for k, v in params.items())))]


def scale(p, w, target=None):
    """The player's power s = the equipment's sustained damage (UCB-100 x6) / 60,000, 0.25-2.5 (adaptation)."""
    g = D['power']
    if w is None:
        return 1.0
    dummy = target
    try:
        hits = [w.laser_damage('ammunition_laser_ucb-100', dummy)[0] for _ in range(6)]
        dps = sum(hits) / len(hits) * world_module.COMBAT['laser_hit_chance'] / world_module.COMBAT['laser_interval_sec']
    except Exception:
        dps = g['base_dps']
    return max(g['min_value'], min(g['maximum'], dps / float(g['base_dps'])))


class WbRun:
    """The battle in Treacherous Domain (the world's 'kapi')."""
    key = 'world_boss'

    def __init__(self, mode, world, start, end, restore=None):
        self.m, self.w = mode, world
        self.restore = restore
        self.g = {'name': 'Treacherous Domain'}
        self.start, self.end = start, end
        self.boss_at = start + D['prep_sec']
        self.escape_at = self.boss_at + D['boss_sec']
        if restore:
            self.boss_at, self.escape_at = restore['boss_at'], restore['escape_at']
        self.close_at = min(end, self.escape_at + D['closing_sec'])
        self.phase = 'prep'
        self.fortress = None
        self.guardians = []
        self.harbingers = set()
        self.dealt = 0                              # damage dealt to the Fortress in this battle
        self.paid = set()                           # progress tiers received in this battle
        self.mines_done = set()
        self.s = 1.0
        self.next = {}
        self.ended = None
        self.angle = random.uniform(0, 2 * math.pi)
        self.cx, self.cy = world.map_w // 2, world.map_h // 2
        self.laser = None
        self.heal_next = 0.0
        self.closing_sent = False

    @property
    def npcs(self):
        return {n.id for n in ([self.fortress] if self.fortress else []) + self.guardians} | self.harbingers

    def wave(self):
        return self.phase

    def enter_msgs(self):
        w = self.w
        msgs = [poi(POI_HEAL, self.cx, self.cy, D['healing_beacon']['radius'], ptype=4, design=6)]
        w.add_gate(dict(gateId=EXIT_ID, x=self.cx - 2600, y=self.cy + 2200, target=self.m.k.home() if self.m.k else 5, designId=1,
                        gate=self.key, exit=True, arrival='station'))
        r = self.restore
        if r:
            self.dealt, self.paid, self.mines_done = r['dealt'], set(r['paid']), set(r['mines'])
        if time.time() < self.boss_at:
            if not r:
                msgs.append(legacy('0|A|STM|log_msg_worldboss_event_open'))
            self.spawn_harbingers(D['harbinger_prep'])
        else:
            self.spawn_boss(r)
        return msgs

    def snapshot(self):
        """The battle's state (when the player leaves the map; when returning in the same window enter_msgs resumes it)."""
        f = self.fortress
        return dict(start=self.start, end=self.end, boss_at=self.boss_at, escape_at=self.escape_at, phase=self.phase, s=self.s,
                    dealt=self.dealt, paid=sorted(self.paid),
                    mines=sorted(self.mines_done),
                    fortress=[f.hp / float(max(1, f.d['hp'])), f.shield / float(max(1, f.d['shield']))] if f and f.alive else None,
                    guardians=[[g.alive, g.downed, g.hp / float(max(1, g.d['hp']))] for g in self.guardians])

    def fortress_max(self):
        f = self.fortress
        if f:
            return f.d['hp'] + f.d['shield']
        return self.m.h_ref()

    def fortress_left(self):
        f = self.fortress
        return (f.hp + f.shield) / float(max(1, self.fortress_max())) if f else 0.0

    # ------------------------------------------------------------ spawning
    def spot_near(self, x, y, r0, r1):
        a, r = random.uniform(0, 2 * math.pi), random.uniform(r0, r1)
        return (min(max(int(x + math.cos(a) * r), 500), self.w.map_w - 500), min(max(int(y + math.sin(a) * r), 500), self.w.map_h - 500))

    def spawn_harbingers(self, count, near=None):
        w = self.w
        for _ in range(count):
            x, y = self.spot_near(*(near or (self.cx, self.cy)), 400 if near else 2000, 900 if near else 5500)
            n = w.spawn_npc_at(HARBINGER, x, y, prep=lambda n: self.scaled(n))
            n.gate = True
            if near:
                n.engaged, n.next_think = True, 0
            self.harbingers.add(n.id)

    def scaled(self, n):
        """HP by the player's power; laser damage too (between 0.5 and 1.5; adaptation: the Harbinger swarm was too hard for a weak ship, live tour)."""
        import pve_common as PS
        PS.scale_npc(n, hp=self.s, dmg=max(0.5, min(1.5, self.s)))

    def spawn_boss(self, restore=None):
        w = self.w
        if restore and restore.get('fortress'):
            self.s = restore['s']                                # a resumed battle: the same power scale
        else:
            probe = w.spawn_npc_at(FORTRESS, self.cx, self.cy)    # target for measuring power (ammo bonus)
            self.s = scale(self.m.p, w, probe)
            w.remove_npc(probe)
        x, y = self.orbit_point()
        f = w.spawn_npc_at(FORTRESS, x, y, prep=lambda n: self.scaled(n))
        f.gate, f.engaged = True, True
        f.next_think = time.time() + 3600                          # the run manages movement (orbit)
        f.invulnerable = lambda: self.phase in ('prep', 1)
        f.damage_reduction = self.fortress_reduction
        f.damage_hook = self.fortress_hit
        self.fortress = f
        with self.m.p.lock:
            self.m.st['h_ref'] = f.d['hp'] + f.d['shield']
            self.m.p.dirty = True
        r = D['guardian_distance']
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            gx = min(max(self.cx + dx * r, 800), w.map_w - 800)
            gy = min(max(self.cy + dy * int(r * 0.7), 800), w.map_h - 800)
            g = w.spawn_npc_at(GUARDIAN, gx, gy, prep=lambda n: self.scaled(n))
            g.gate, g.engaged = True, True
            g.downed, g.summoned, g.up_since = False, False, time.time()
            g.hp_floor = 1
            g.at_floor = self.guardian_down
            g.invulnerable = (lambda gg: lambda: gg.downed)(g)
            g.damage_hook = (lambda gg: lambda dmg: self.guardian_hit(gg))(g)
            self.guardians.append(g)
        self.phase = 1
        self.next.update(rocket=0, radiation=time.time() + 20, laser=time.time() + 10, revive=time.time() + 30, move=0, ram=0,
                         field=0, seeker=0)
        if restore and restore.get('fortress'):                   # resumed battle: HP, fallen and dead Guardians, phase
            f.hp, f.shield = int(f.d['hp'] * restore['fortress'][0]), int(f.d['shield'] * restore['fortress'][1])
            saved = restore['guardians']        # those who died on the previous return had been filtered out: missing slots are dead (otherwise the extra Guardians stayed at full HP)
            saved = saved + [[False, False, 0.0]] * (len(self.guardians) - len(saved))
            for g, (alive, downed, ratio) in zip(self.guardians, saved):
                if not alive:
                    w.send(w.remove_npc(g))
                    continue
                g.downed, g.hp = downed, max(1, int(g.d['hp'] * ratio))
                if restore['phase'] == 4:
                    g.hp_floor = 0
            self.guardians = [g for g in self.guardians if g.alive]
            self.phase = restore['phase'] if restore['phase'] in (1, 2, 3, 4) else 1
            w.send([self.field_visual(g, True) for g in self.active_guardians()])
            w.log('   World Boss: battle continues (phase %s, Fortress %%%d)' % (self.phase, self.fortress_left() * 100))
            return
        w.send([legacy('0|A|STM|log_msg_worldboss_boss_appear')] + [self.field_visual(g, True) for g in self.guardians])
        w.log('   World Boss: Dreadfyre Fortress arrived (power %.2f, HP %d + %d)' % (self.s, f.hp, f.shield))

    def orbit_point(self):
        r = D['npcs']['dreadfyre_fortress'].get('orbit_radius', 2500)
        return int(self.cx + math.cos(self.angle) * r), int(self.cy + math.sin(self.angle) * r * 0.6)

    def field_visual(self, g, on):
        vm = ('VisualModifierCommand', dict(userId=g.id, modifier=ZONE, attribute=D['attacks']['magnetic']['radius'],
                                            additionalAttribute='', count=1 if on else 0, activated=on))
        g.images = {ZONE: vm} if on else {}   # again when it comes into view (world.show): the Guardian spawns out of view
        return vm

    # ------------------------------------------------------------ Guardian and Fortress rules
    def active_guardians(self):
        return [g for g in self.guardians if g.alive and not g.downed]

    def fortress_reduction(self):
        return min(1.0, D.get('guardian_shield_ratio', 0.25) * len(self.active_guardians()))

    def guardian_hit(self, g):
        if not g.summoned:
            g.summoned = True                       # calls Harbingers on the first hit
            gx, gy = g.mover.pos(time.time())
            self.spawn_harbingers(D['harbinger_summon'], near=(gx, gy))

    def guardian_down(self, g):
        if self.phase == 4:
            return
        if not g.downed:
            g.downed = True
            self.w.send([self.field_visual(g, False), KAPI.screen('A Dreadfyre Guardian has fallen.')])
            if self.phase == 1 and not self.active_guardians():
                self.phase = 2
                self.next['revive'] = time.time() + 30
                self.w.send([KAPI.screen('The Fortress is vulnerable!', big=True)])
                self.w.log('   World Boss: evre 2')

    def revive_guardians(self, count):
        down = [g for g in self.guardians if g.alive and g.downed]
        random.shuffle(down)
        msgs = []
        for g in down[:count]:
            g.downed, g.summoned, g.up_since = False, False, time.time()
            g.hp, g.shield = g.d['hp'], g.d['shield']
            msgs += [self.field_visual(g, True)]
        if msgs:
            self.w.send(msgs + [KAPI.screen('A Dreadfyre Guardian has returned!')])

    def fortress_hit(self, dmg):
        self.dealt += dmg
        msgs = self.m.add_damage(dmg)
        for r in D['progress']:                     # progress rewards: once per tier in this battle, 3 times a day
            k = r['tier']
            if k in self.paid or self.dealt < self.fortress_max() * r['ratio']:
                continue
            self.paid.add(k)
            st = self.m.st
            if st['claimed'].get(str(k), 0) >= r['daily']:
                continue
            with self.m.p.lock:
                st['claimed'][str(k)] = st['claimed'].get(str(k), 0) + 1
                self.m.p.dirty = True
            for loot, n in r['rewards']:
                msgs += self.m.m.prize(loot, n)
            msgs.append(KAPI.screen('Progress reward %d received!' % k))
        left = self.fortress_left()
        if self.phase == 2 and left <= 0.5:
            self.phase = 3
            self.next['laser'] = time.time() + 5
            msgs.append(legacy('0|A|STM|log_msg_worldboss_half_health|%%BOSSNAME%%|Dreadfyre Fortress'))
            self.w.log('   World Boss: evre 3')
        elif self.phase == 3 and left <= 0.1:
            self.phase = 4
            for g in self.guardians:
                g.hp_floor = 0                      # can now die
            self.revive_guardians(4)
            self.next['radiation'] = time.time() + 10
            msgs.append(KAPI.screen('The Guardians have returned for the last time!', big=True))
            self.w.log('   World Boss: evre 4')
        for th in D['mine_thresholds']:
            if th not in self.mines_done and left <= th and self.phase in (2, 3, 4):
                self.mines_done.add(th)
                self.mine_ring()
        if msgs:
            self.w.send(msgs)

    def mine_ring(self):
        w, f = self.w, self.fortress
        now = time.time()
        fx, fy = f.mover.pos(now)
        m = D['attacks']['mine']
        n = m.get('mine_count', 24)
        for i in range(n):
            a = 2 * math.pi * i / n
            r = random.uniform(*m.get('ring_radius', [1000, 1400]))
            w.items.alien_mine('ammunition_mine_acm-01', fx + math.cos(a) * r, fy + math.sin(a) * r, f.id, now)
        w.log('   World Boss: ring minefield')

    # ------------------------------------------------------------ loop
    def tick(self, now):
        w = self.w
        if self.phase == 'closed':
            return
        self.heal_tick(now)
        if self.phase == 'prep':
            if now >= self.boss_at:
                for i in list(self.harbingers):
                    n = w.npcs.get(i)
                    if n:
                        w.send(w.remove_npc(n))
                self.harbingers.clear()
                self.spawn_boss()
            return
        if self.phase == 'finished':
            if now >= self.close_at:
                self.close()
            return
        if now >= self.escape_at:
            self.escape()
            return
        f = self.fortress
        if not f or not f.alive:
            return
        self.move_fortress(now)
        hx, hy = w.hero_pos(now)
        if w.hero_dead:
            return
        max_hp = self.m.p.d['ship'].get('hitMax', 1)
        attacks = D['attacks']
        if now >= self.next['field']:               # Guardian magnetic field (per second)
            self.next['field'] = now + 1.0
            for g in self.active_guardians():
                gx, gy = g.mover.pos(now)
                if math.hypot(hx - gx, hy - gy) <= attacks['magnetic']['radius']:
                    w.send(w.hurt_hero(int(max_hp * attacks['magnetic']['damage_per_sec_max_hp_ratio']), g, atype=0))
        fx, fy = f.mover.pos(now)
        if now >= self.next['ram'] and math.hypot(hx - fx, hy - fy) <= attacks['collision']['contact_radius']:
            self.next['ram'] = now + attacks['collision']['interval_sec']
            w.send(w.hurt_hero(int(max_hp * attacks['collision']['damage_max_hp_ratio']), f, atype=0))
        if self.phase in (2, 3, 4):
            if now >= self.next['rocket'] and math.hypot(hx - fx, hy - fy) <= attacks['rocket']['range'] * SET.multiplier('npc_range'):
                self.next['rocket'] = now + attacks['rocket']['interval_sec']
                w.send([legacy('0|v|%d|%d|H|1|0|0' % (f.id, w.hid))])
                dmg = attacks['rocket']['damage']
                w.later(1.0, lambda: (not w.hero_dead) and w.send(w.hurt_hero(dmg, f, atype=0)))
            if now >= self.next['radiation']:
                self.next['radiation'] = now + (10 if self.phase == 4 else 20)
                self.radiation(now)
            if self.phase in (2, 3) and now >= self.next['revive']:
                self.next['revive'] = now + 30
                self.revive_guardians(1 if self.phase == 2 else 2)
            if now >= self.next['seeker']:
                self.next['seeker'] = now + 1.0
                for g in self.active_guardians():
                    if now - g.up_since >= attacks['guided']['repeat_sec']:
                        g.up_since = now
                        self.seeker(g, now)
        if self.phase == 3 and now >= self.next['laser']:
            self.next['laser'] = now + 10
            self.map_laser(now)

    def heal_tick(self, now):
        w = self.w
        if now < self.heal_next or w.hero_dead:
            return
        self.heal_next = now + 1.0
        hx, hy = w.hero_pos(now)
        if math.hypot(hx - self.cx, hy - self.cy) > D['healing_beacon']['radius']:
            return
        g = self.m.p.d['ship']
        if g.get('hitPoints', 0) >= g.get('hitMax', 0):
            return
        hp0 = g.get('hitPoints', 0)
        self.m.p.set_hull(hp=min(g['hitMax'], hp0 + D['healing_beacon']['hp_per_sec']))
        w.send([('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g.get('hitMax', 0),
                                             nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0)))])
        self.m.p.ach('wb_heal', count=g['hitPoints'] - hp0)               # World Boss achievement (recoverhp)

    def move_fortress(self, now):
        f = self.fortress
        if now < self.next['move']:
            return
        self.angle += 0.35
        x, y = self.orbit_point()
        ms = f.mover.go(x, y, max(60, f.d.get('speed', 150)), now)
        self.next['move'] = now + ms / 1000.0
        f.next_think = now + 3600
        self.w.send([('MoveCommand', dict(userId=f.id, x=int(x), y=int(y), timeToTarget=ms))])

    def radiation(self, now):
        w, f = self.w, self.fortress
        r = D['attacks']['radiation']
        w.send([('VisualModifierCommand', dict(userId=f.id, modifier=ZONE, attribute=r['radius'], additionalAttribute='', count=1,
                                               activated=True))])

        def burst():
            if not f.alive:
                return
            w.send([('VisualModifierCommand', dict(userId=f.id, modifier=ZONE, attribute=0, additionalAttribute='', count=0,
                                                   activated=False))])
            if w.hero_dead:
                return
            hx, hy = w.hero_pos()
            fx, fy = f.mover.pos(time.time())
            if math.hypot(hx - fx, hy - fy) <= r['radius']:
                w.send(w.hurt_hero(int(self.m.p.d['ship'].get('hitMax', 1) * r['damage_max_hp_ratio']), f, atype=0))
        w.later(r.get('warning_sec', 2), burst)

    def seeker(self, g, now):
        w = self.w
        s = D['attacks']['guided']
        hx, hy = w.hero_pos(now)
        gx, gy = g.mover.pos(now)
        if math.hypot(hx - gx, hy - gy) > s['range'] * SET.multiplier('npc_range'):      # panel: alien firing range
            return
        w.send([('VisualModifierCommand', dict(userId=g.id, modifier=TELEGRAPH, attribute=0,
                                               additionalAttribute='(%d,%d,0)' % (hx, hy), count=1, activated=True))])

        def hit():
            w.send([('VisualModifierCommand', dict(userId=g.id, modifier=TELEGRAPH, attribute=0, additionalAttribute='', count=0,
                                                   activated=False))])
            if not w.hero_dead and g.alive:
                ex, ey = w.hero_pos()
                if math.hypot(ex - hx, ey - hy) <= 400:               # one can escape from the marked point
                    w.send(w.hurt_hero(int(self.m.p.d['ship'].get('hitMax', 1) * s['damage_max_hp_ratio']), g, atype=0))
        w.later(1.2, hit)

    def map_laser(self, now):
        """A beam from the Fortress to the locked target, reaching the map edge: 3 s warning, then damage to the ship on the line."""
        w, f = self.w, self.fortress
        L = D['attacks']['laser']
        hx, hy = w.hero_pos(now)
        fx, fy = f.mover.pos(now)
        w.send([('VisualModifierCommand', dict(userId=f.id, modifier=LASER_PREP, attribute=w.hid, additionalAttribute='', count=1,
                                               activated=True))])

        def charge():
            if f.alive:
                w.send([('VisualModifierCommand', dict(userId=f.id, modifier=LASER_CHARGE, attribute=0, additionalAttribute='', count=1,
                                                       activated=True))])

        def shot():
            if not f.alive:
                return
            w.send([('VisualModifierCommand', dict(userId=f.id, modifier=LASER_SHOT, attribute=0,
                                                   additionalAttribute='%d|%d' % (hx, hy), count=1, activated=True))])
            if w.hero_dead:
                return
            ex, ey = w.hero_pos()
            if seg_dist(ex, ey, fx, fy, hx, hy, extend=True) <= L.get('width', 250):
                w.send(w.hurt_hero(int(self.m.p.d['ship'].get('hitMax', 1) * L['damage_max_hp_ratio']), f, atype=0))
        w.later(L.get('warning_sec', 3) - 1.0, charge)
        w.later(L.get('warning_sec', 3), shot)

    # ------------------------------------------------------------ son
    def on_kill(self, npc, x, y):
        w = self.w
        msgs = []
        if npc.id in self.harbingers:
            self.harbingers.discard(npc.id)
            if self.phase == 'prep':
                if random.random() < D.get('box_chance', 0.3):
                    self.buff_box(int(x), int(y))
                w.later(D.get('harbinger_respawn_sec', 20), lambda: self.phase == 'prep' and self.spawn_harbingers(1))
        elif self.fortress and npc.id == self.fortress.id:
            self.phase, self.ended = 'finished', 'death'
            self.close_at = min(self.end, time.time() + D['closing_sec'])
            for loot, n in D['last_hit']['rewards']:
                msgs += self.m.m.prize(loot, n)
            if self.m.titles:
                msgs += self.m.titles(D['last_hit']['title'])
            msgs.append(legacy('0|A|STM|log_msg_worldboss_boss_killed|%%USERNAME%%|%s' % self.m.p.d['pilot'].get('userName', '')))
            msgs.append(KAPI.screen('key:log_msg_gg_completed_world_boss', big=True))
            msgs += self.rank_rewards(1.0)
            self.clear_adds()
            w.log('   World Boss: Fortress yenildi')
        return msgs

    def rank_rewards(self, share):
        rank = next((r for th, r in D['virtual_rank'] if share >= th), None)
        if rank is None:
            return []
        row = next((x for x in D['ranking'] if x['from_'] <= rank <= x['e']), None)
        self.m.tally(rank=rank)
        msgs = []
        if row:
            for loot, n in row['rewards']:
                msgs += self.m.m.prize(loot, n)
            for key in row.get('titles') or []:
                if 'rank_1_' in key and self.ended != 'death':
                    continue                           # the 1st place's title only if the Fortress was defeated
                if self.m.titles:
                    msgs += self.m.titles(key)
        msgs.append(KAPI.screen('Battle rank: %d' % rank, big=True))
        self.m.log('   World Boss rank %d (share %.2f)' % (rank, share))
        return msgs

    def escape(self):
        w, f = self.w, self.fortress
        self.phase, self.ended = 'finished', 'escape'
        self.close_at = min(self.end, time.time() + D['closing_sec'])
        msgs = [legacy('0|A|STM|log_msg_worldboss_boss_escape')]
        if f and f.alive:
            msgs.append(('VisualModifierCommand', dict(userId=f.id, modifier=BOSS_ESCAPE, attribute=0, additionalAttribute='', count=1,
                                                       activated=True)))
            share = self.dealt / float(max(1, self.fortress_max()))
            w.send(msgs + self.rank_rewards(share))
            w.later(3.0, lambda: f.alive and w.send(w.remove_npc(f)))
        self.clear_adds()
        w.log('   World Boss: Fortress escaped')

    def clear_adds(self):
        """The battle ended: Guardians and Harbingers withdraw (no reward)."""
        w = self.w
        for i in [g.id for g in self.guardians] + list(self.harbingers):
            n = w.npcs.get(i)
            if n and n.alive:
                w.send(w.remove_npc(n))
        self.harbingers.clear()

    def close(self):
        w = self.w
        self.phase = 'closed'
        w.send([KAPI.screen('Treacherous Domain is closing.', big=True), ('MapRemovePOICommand', {'poiId': POI_HEAL})])
        if self.m.change_map and not w.hero_dead:
            home = self.m.k.home() if self.m.k else 5
            w.later(3.0, lambda: self.m.change_map(home, None, 'station'))

    def buff_box(self, x, y):
        w = self.w
        k = D['box']
        h = w.drop_box(k['type'], x, y, None, k['lifetime_sec'])
        w.boxes[h]['no_pet'] = True
        w.boxes[h]['al'] = lambda b: self.buff(random.choice(k['buffs']))

    def buff(self, kind):
        w, p = self.w, self.m.p
        g = p.d['ship']
        if kind == 'speed':
            w.hero_effect('speed_up', max(60, int(self.close_at - time.time())), int(g.get('speed', 300) * 1.1), source='dreadfyre')
            text = 'Speed boost!'
        elif kind == 'shield':
            p.set_hull(shield=min(g.get('shieldMax', 0), g.get('shield', 0) + int(g.get('shieldMax', 0) * 0.15)))
            text = 'Shield boost!'
        elif kind == 'hp':
            p.set_hull(hp=min(g.get('hitMax', 0), g.get('hitPoints', 0) + int(g.get('hitMax', 0) * 0.15)))
            text = 'Hull boost!'
        else:
            p.set_hull(hp=min(g.get('hitMax', 0), g.get('hitPoints', 0) + int(g.get('hitMax', 0) * 0.5)))
            text = 'Repaired!'
        return [('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g.get('hitMax', 0),
                                             nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0))),
                ('AttributeShieldUpdateCommand', {'shieldNow': int(g.get('shield', 0)), 'shieldMax': g.get('shieldMax', 0)}),
                KAPI.screen('Dreadfyre Box: ' + text)]

    def on_death(self):
        return None

    def revive(self):
        pass


def seg_dist(px, py, ax, ay, bx, by, extend=False):
    """Distance of the point to the right part of the segment (extend: the ray from a toward b)."""
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    if not L2:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * vx + (py - ay) * vy) / L2
    t = max(0.0, t) if extend else max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def poi(pid, x, y, r, ptype=4, design=6, inverted=False):
    return ('MapAddPOICommand', dict(inverted=inverted, poiTypeSpecification='', poiType=mod('POITypeModule', typeValue=ptype), shape=0,
                                     active=True, design=mod('POIDesignModule', designValue=design), poiId=pid,
                                     shapeCoordinates=[int(x), int(y), int(r)]))
