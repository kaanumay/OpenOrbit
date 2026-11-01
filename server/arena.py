"""Difficulty-select arena gates (roadmap Stage 8; data data/pve_modes.json <- tools/pve_modes.py): Voyagers' Ascent and
Trinity Trials.

Their common flow: a portal in X-1 and X-8; jumping to the portal (J) opens the client's gate window (VoyagersGateWindowCommand /
TrinityTrialsGateWindowCommand: difficulties, free entry, token); the window's entry request (VoyagersGateEnterRequest {isFree,
instanceLevel} / TrinityTrialsGateEnterRequest {attributeType, difficulty}) -> jump to the gate map; 20 waves (pve_ortak.Kosu);
when the player dies the run ends (no respawn on the mode map). Daily entries per map (X-1 and X-8 separate): 1 free (VIP badge +1 / +2),
extra ones with a token (Voyagers' Oath Token, Trinity Token). Pass (gecis.Gecis): free and VIP rewards from the points of the finishes.
Voyagers' Ascent: 5 difficulties (opens when the previous one is finished with 3 stars); 1-3 stars by time (15/10/5 min); star rewards
and pass points; 3 stars give one extra free entry; the token drops only on finishing. Voidmare: takes no damage for 5 s and, if the
player is within 500 units, fires a missile worth 5% of HP every second.
Trinity Trials: Hellfire (thermal, Monday/Wednesday/Friday) and Genome (corrosive, Tuesday/Thursday/Saturday), both on Sunday; a difficulty
opens with the level of the OS module (1/6/11/21/31); every 5 waves Quantum Prism, Xyralith and pass points; on finishing, equipment (count
and probability by difficulty, the reward description in the save; 5% cannon, 95% breaker; attribute from the OS level's table). OS module
(Orbital Sweeper): upgraded with Quantum Prism, the time is skipped with Xyralith (TrinityTrialsDropLevelCommand / OptionalRequest).
Note: in this client version the particle weapon (cannon, breaker, bullet) system is not in the protocol (roadmap Stage 9): dropped
equipment stays in storage. Singularity Drive / Gravity Lens are missing too: Voyagers' SD/CGL rewards are in storage.
In the profile: pve {voyagers|trinity: {gun, entries {X-1: n}, bonus, open (Voyagers), os {level, end, target} (Trinity), best …}}.
"""
import datetime, json, math, os, random, time

import settings as SET
import mode_passes as GC
import map_links as H
import galaxy_gates as GALAXY
import pve_common as PS

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'pve_modes.json'), encoding='utf8'))
PORTAL_BASE = 153900000


def today(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()


def loot_prob(loot, a):
    lo, hi = (a[0], a[1]) if isinstance(a, list) else (a, a)
    return dict(_='LootProbabilityModule', lootId=loot, minLootAmount=int(lo), maxLootAmount=int(hi), probabilityPercentage=100.0)


class Arena:
    """Common base of Voyagers and Trinity. Subclass: key, name, D, window(), enter_map(), finish …"""
    key = name = ''
    slot = 0

    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                       # shop (rewards)
        self.send = None                    # message to the session
        self.run = None                     # run in progress: {difficulty, entry (X-1/X-8), free, start}
        self.reward_pass = GC.Pass(profile, self.key, self.D['reward_pass'], badge=self.D.get('vip'))

    @property
    def st(self):
        s = self.p.d.setdefault('pve', {}).setdefault(self.key, {})
        if s.get('day') != today():
            s.update(day=today(), entries={})
            self.p.dirty = True
        return s

    def vip(self):
        return self.p.resource(self.D['vip']) > 0

    def free_max(self):
        return self.D['free'] + (self.D['vip_extra'] if self.vip() else 0)

    def free_used(self, where):
        if SET.get('no_entry_limit'):                  # panel: free entries do not run out
            return 0
        return self.st['entries'].get(where, 0)

    def free_left(self, where):
        return max(0, self.free_max() - self.free_used(where)) + self.st.get('bonus', 0)

    def tokens(self):
        return self.p.resource(self.D['token'])

    # ------------------------------------------------------------ portal
    def portals(self, map_id, station):
        cls = H.map_class(map_id)
        if cls not in self.D['entry'] or H.company(map_id) != self.p.d['pilot'].get('factionId'):
            return []
        # side by side at the top center of the map (official server record: Trinity Trials portal in 2-1 at (10700, 3000)); if the base
        # is at the top center (2-8) bottom center
        x, y = GALAXY.MAP_W // 2 + 200 - (2 - self.slot) * 1400, 3000
        if station and math.hypot(x - station['posX'], y - station['posY']) < 2500:
            y = GALAXY.MAP_H - y
        return [dict(gateId=PORTAL_BASE + self.slot, x=x, y=y, target=0,
                     designId=self.D['portal'], gate=self.key, windowed=self.key, entry=cls)]

    # ------------------------------------------------------------ run
    def start(self, difficulty, where, free, dest):
        self.run = dict(difficulty=difficulty, entry=where, free=free, start=None, map=dest, wave=0)
        self.log('   %s: difficulty %d (%s, %s)' % (self.name, difficulty, where, 'free' if free else 'token'))

    def use_entry(self):
        """Cost of entry: if free, the day's allowance (otherwise the bonus), else one token."""
        r = self.run
        with self.p.lock:
            if r['free']:
                if self.free_used(r['entry']) < self.free_max():
                    self.st['entries'][r['entry']] = self.free_used(r['entry']) + 1
                else:
                    self.st['bonus'] = max(0, self.st.get('bonus', 0) - 1)
            self.p.dirty = True
        if not r['free']:
            self.p.add_resource(self.D['token'], -1)

    def can_enter(self, where, free):
        return self.free_left(where) > 0 if free else self.tokens() > 0

    def waves(self):
        return self.wave_list(self.run['difficulty'])

    def wave_count(self):
        return len(self.waves())

    def scale(self, n, i, wave):
        return n

    def wave_started(self, i):
        if i == 0 and self.run and self.run['start'] is None:
            self.run['start'] = time.time()
        self.run['wave'] = i
        self.world.send([GALAXY.screen('%s - Wave %d/%d' % (self.name, i + 1, self.wave_count()), big=True)])

    def on_death(self):
        """Death on the mode map: the run ends (re-entry required)."""
        self.log('   %s: player destroyed, run over (wave %d)' % (self.name, (self.run or {}).get('wave', 0) + 1))
        self.failed()
        self.run = None
        return 0

    def failed(self):
        pass

    def revive(self):
        pass

    def exit_portal(self, world):
        x, y = world.map_w // 2, world.map_h // 2
        home = GALAXY.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5)
        return dict(gateId=PORTAL_BASE + 50 + self.slot, x=x, y=y, target=home, designId=1, gate=self.key, exit=True,
                    arrival='station')

    def attach(self, world):
        """Mode map opened: the waves if there is a run, otherwise only the exit."""
        self.world = world
        if not self.run:
            world.add_gate(self.exit_portal(world))
            return None
        world.gate = PS.Run(world, self, break_sec=4)
        return world.gate

    def grant(self, loot, n):
        if loot.startswith('currency_') and self.world:
            kw = {'currency_uridium': 'uridium', 'currency_credits': 'credits', 'currency_experience': 'ep', 'currency_honour': 'honor'}
            return self.world.grant_loot(loot, n, 'mod')
        return self.m.reward(loot, n) if self.m else []

    def grant_rows(self, rows):
        msgs, got = [], []
        for loot, a in rows:
            n = random.randint(a[0], a[1]) if isinstance(a, list) else a
            msgs += self.grant(loot, n)
            got.append('%s x%d' % (loot, n))
        return msgs, got

    def pass_claim(self, f, cmd_name):
        out = self.reward_pass.claim(int(f.get('rewardLevel', 0)), bool(f.get('isVip')), self.reward)
        if out is None:
            self.log('   %s pass: cannot be taken (level %s)' % (self.name, f.get('rewardLevel')))
            out = []
        return out + [self.reward_pass.cmd(cmd_name)]

    def reward(self, loot, n):
        return self.m.reward(loot, n) if self.m else []


# ====================================================================== Voyagers' Ascent
class Voyagers(Arena):
    key, name, D, slot = 'voyagers', "Voyagers' Ascent", D['voyagers'], 1

    def opened(self):
        return max(1, min(len(self.D['difficulties']), self.st.get('on', 1)))

    def wave_list(self, d):
        return self.D['difficulties'][d - 1]['waves']

    def window(self, where):
        s = self.D['star_sec']
        stars = [dict(_='VoyagersGateStarRewardCommand', instanceLevel=i + 1,
                      star1Loots=[loot_prob(l, a) for l, a in z['rewards']['1']],
                      star2Loots=[loot_prob(l, a) for l, a in z['rewards']['2']],
                      star3Loots=[loot_prob(l, a) for l, a in z['rewards']['3']]) for i, z in enumerate(self.D['difficulties'])]
        return ('VoyagersGateWindowCommand', dict(
            maxOpenLevel=self.opened(), Star1Seconds=s[2], Star2Seconds=s[1], Star3Seconds=s[0], curLootAmount=int(self.tokens()),
            lootId=self.D['token'], maxFreeNum=self.free_max() + self.st.get('bonus', 0),
            freeChallengedNum=self.free_used(where), starRewardLoots=stars))

    def enter(self, f, where):
        """VoyagersGateEnterRequest -> (target map, arrival) or (None, messages)."""
        lvl, free = int(f.get('instanceLevel') or 1), bool(f.get('isFree'))
        if not 1 <= lvl <= self.opened() or not self.can_enter(where, free):
            self.log('   Voyagers: cannot enter (difficulty %d / open %d, %s)' % (lvl, self.opened(), 'free' if free else 'token'))
            return None, [self.window(where), GALAXY.screen('You cannot enter this difficulty right now.')]
        self.start(lvl, where, free, self.D['map'])
        return self.D['map'], None

    def wave_done(self, i, now):
        if i + 1 >= self.wave_count():
            self.complete(now)
            return 'halt'
        return 'ongoing'

    def complete(self, now):
        r, w = self.run, self.world
        secs = int(now - (r['start'] or now))
        lim = self.D['star_sec']
        stars = 3 if secs <= lim[0] else 2 if secs <= lim[1] else 1 if secs <= lim[2] else 0
        z = self.D['difficulties'][r['difficulty'] - 1]
        self.use_entry()
        msgs, got = [], []
        if stars:
            msgs, got = self.grant_rows(z['rewards'][str(stars)])
            self.reward_pass.add(z['points'][str(stars)])
        with self.p.lock:
            s = self.st
            best = s.setdefault('best', {})
            if stars > best.get(str(r['difficulty']), 0):
                best[str(r['difficulty'])] = stars
            if stars == 3:
                s['bonus'] = s.get('bonus', 0) + 1                  # 3 stars: one extra free entry
                if r['difficulty'] == s.get('on', 1) and r['difficulty'] < len(self.D['difficulties']):
                    s['on'] = r['difficulty'] + 1
            self.p.dirty = True
        self.p.ach('gate', type='VOYAGERS_GATE')
        msgs += [GALAXY.screen('key:log_msg_gg_completed_voyagersascentrial', big=True),          # the client's text; time and stars
                 GALAXY.screen("Voyagers' Ascent %s completed in %s: %d star%s" % (z['name'], fmt(secs), stars, '' if stars == 1 else 's'))]
        w.add_gate(self.exit_portal(w))
        w.send(msgs + [self.reward_pass.cmd('VoyagersPassCommand')])
        self.log('   Voyagers %s: %d s, %d stars; %s' % (z['name'], secs, stars, ', '.join(got) or '-'))
        self.run = None

    def tick(self, now):
        """Voidmare: invulnerable for 5 s and, if the player is within 500 units, 5% of HP per second."""
        w = self.world
        if w.hero_dead:
            return
        hx, hy = w.hero_pos(now)
        for n in list(w.npcs.values()):
            v = n.d.get('behavior', {}).get('fuse_if_untouched')
            if not v or not n.alive or not n.engaged:
                continue
            nx, ny = n.mover.pos(now)
            if now - max(n.last_hit, getattr(n, 'born', now - 10)) < v['sec'] or math.hypot(hx - nx, hy - ny) > v['range']:
                continue
            if now < getattr(n, 'next_missile', 0):
                continue
            n.next_missile = now + 1.0
            dmg = int(self.p.d['ship'].get('hitMax', 0) * v['ratio'])
            w.send(w.hurt_hero(dmg, n, atype=2, now=now))


def fmt(secs):
    return '%d:%02d' % divmod(int(secs), 60)


# ====================================================================== Trinity Trials
RARITY_NAMES = ['Common', 'Uncommon', 'Rare', 'Epic', 'Masterpiece', 'Legendary', 'Ultimate']


class Trinity(Arena):
    key, name, D, slot = 'trinity', 'Trinity Trials', D['trinity'], 2

    def os_state(self, now=None):
        """OS module: an upgrade whose time has run out is completed."""
        now = time.time() if now is None else now
        o = self.p.d.setdefault('pve', {}).setdefault(self.key + '_os', {'level': 1})
        if o.get('end_time') and now >= o['end_time']:
            with self.p.lock:
                o['level'] = o.pop('target', o['level'] + 1)
                o.pop('end_time', None)
                self.p.dirty = True
            self.log('   Trinity OS module: level %d' % o['level'])
        return o

    def os_level(self):
        return self.os_state()['level']

    def opened(self):
        lv = self.os_level()
        return max(i + 1 for i, z in enumerate(self.D['difficulties']) if lv >= z['os_level'])

    def arenas_today(self, now=None):
        wd = datetime.date.fromtimestamp(time.time() if now is None else now).weekday()
        return [int(a) for a, days in self.D['days'].items() if wd in days]

    def wave_list(self, d):
        return self.D['difficulties'][d - 1]['arenas'][str(self.run['arena'])]

    def window(self, where, now=None):
        today_ = self.arenas_today(now)
        free = self.free_left(where) > 0
        # openAttributes: only the arenas open today (the client writes "open today" for all of them in the header and puts them in the
        # selection list); param1 is the free entry in that arena: if it is "0" and there is no token, Go Now opens the shop (client:
        # UITrinityTrialsGateTipsSystem; live test H51: a closed arena came selected, and it went to the shop even with a free entry)
        return ('TrinityTrialsGateWindowCommand', dict(
            isFree=free, curLootAmount=int(self.tokens()), lootId=self.D['token'],
            attributeType=today_[0] if today_ else 1, openDifficulty=self.opened(),
            openAttributes=[dict(_='TupleTwoModule', param0=str(a), param1='1' if free else '0') for a in today_]))

    def enter(self, f, where, now=None):
        attr, lvl = int(f.get('attributeType') or 1), int(f.get('difficulty') or 1)
        free = self.free_left(where) > 0
        if attr not in self.arenas_today(now) or not 1 <= lvl <= self.opened() or not self.can_enter(where, free):
            self.log('   Trinity: cannot enter (arena %d today %s, difficulty %d / %d)' % (attr, self.arenas_today(now), lvl, self.opened()))
            return None, [self.window(where, now), GALAXY.screen('This arena or difficulty is not available right now.')]
        dest = self.D['maps'][str(attr)][lvl - 1]
        self.start(lvl, where, free, dest)
        self.run['arena'] = attr
        self.use_entry()                           # Trinity: the entry allowance is spent on entering
        return dest, None

    def wave_done(self, i, now):
        n = i + 1
        z = self.D['difficulties'][self.run['difficulty'] - 1]
        msgs = []
        if str(n) in z['milestones']:                # every 5 waves Quantum Prism, Xyralith, pass points
            k = z['milestones'][str(n)]
            msgs += self.grant(self.D['qp'], k['qp']) + self.grant(self.D['xy'], k['xy'])
            if k['points']:
                self.reward_pass.add(k['points'])
            msgs.append(GALAXY.screen('Wave %d reward: %d Quantum Prism, %d Xyralith, %d pass points' % (n, k['qp'], k['xy'], k['points'])))
        if n >= self.wave_count():
            msgs += self.complete(z)
            self.world.send(msgs)
            return 'halt'
        self.world.send(msgs)
        return 'pause' if n % 5 == 0 else 'ongoing'

    def roll_rarity(self):
        row = self.D['os'][self.os_level() - 1]['rarity']
        return random.choices(range(7), row)[0]

    def drop(self):
        """Finish equipment: count by difficulty (reward description), each 5% cannon / 95% breaker, attribute from the OS table."""
        z = self.D['difficulties'][self.run['difficulty'] - 1]
        counts, weights = zip(*z['drop'])
        n = random.choices(counts, weights)[0] if sum(weights) >= 100 else (counts[0] if random.random() * 100 < weights[0] else 0)
        eq = self.D['items'][str(self.run['arena'])]
        out = []
        for _ in range(n):
            r = self.roll_rarity()
            out.append(eq['top'][r] if random.random() < self.D['cannon_share'] else eq['breaker'][min(r, len(eq['breaker']) - 1)])
        return out

    def complete(self, z):
        w = self.world
        msgs = []
        got = self.drop()
        for loot in got:
            msgs += self.grant(loot, 1)
        self.p.ach('gate', type='TRINITY_GATE')
        msgs += [GALAXY.screen('key:log_msg_gg_completed_trinitytrials', big=True),
                 GALAXY.screen('Trinity Trials %s completed! Equipment: %d' % (z['name'], len(got)))]
        w.add_gate(self.exit_portal(w))
        self.log('   Trinity %s finished: %s' % (z['name'], ', '.join(got) or 'no equipment'))
        self.run = None
        return msgs + [self.reward_pass.cmd('TrinityTrialsPassCommand')]

    # ------------------------------------------------------------ OS module
    def drop_level_cmd(self, now=None):
        now = time.time() if now is None else now
        o = self.os_state(now)
        lv = o['level']
        rows = self.D['os']
        mx = lv >= len(rows)
        nxt = rows[min(lv, len(rows) - 1)]
        cur = rows[lv - 1]
        left = int(max(0, o['end_time'] - now)) if o.get('end_time') else 0
        building = bool(o.get('end_time'))          # while an upgrade is running the window shows the skip cost (Xyralith); official screen: "Xyralith 9/9"
        skip = self.skip_cost(left)
        cost_id = self.D['xy'] if building else self.D['qp']
        q = lambda r: [dict(_='TupleTwoModule', param0=str(i + 1), param1='%.1f' % v) for i, v in enumerate(r['rarity'])]
        return ('TrinityTrialsDropLevelCommand', dict(
            costLootAmount=skip if building else (0 if mx else nxt['cost']), currentLevel=lv, nextLevel=min(lv + 1, len(rows)), building=bool(o.get('end_time')),
            max=mx, skipConsume=skip, currentLevelQualityRandomList=q(cur), totalBuildSeconds=0 if mx else nxt['duration_sec'],
            lootAmount=int(self.p.resource(cost_id)), nextLevelQualityRandomList=q(nxt), buildSeconds=left, costLootId=cost_id))

    def skip_cost(self, left):
        return int(math.ceil(left / 1000.0)) * self.D['skip_per_minute'] if left else 0      # official screen: 2:29:50 left -> 9 Xyralith (1 per 1000 s)

    def drop_level_optional(self, f, now=None):
        """Upgrade (Quantum Prism) or skip the time (Xyralith) -> messages."""
        from shop import stack_msg
        now = time.time() if now is None else now
        o = self.os_state(now)
        ok = False
        # the window's state determines the action (the costLootId sent by the client is ignored): upgrade if none is running, skip if one is
        if not o.get('end_time') and o['level'] < len(self.D['os']):
            row = self.D['os'][o['level']]
            if self.p.resource(self.D['qp']) >= row['cost']:
                self.p.add_resource(self.D['qp'], -row['cost'])
                with self.p.lock:
                    o.update(target=o['level'] + 1, end_time=now + row['duration_sec'])
                    self.p.dirty = True
                ok = True
                self.log('   Trinity OS: %d -> %d started (%d s)' % (o['level'], o['target'], row['duration_sec']))
        elif o.get('end_time'):
            cost = self.skip_cost(o['end_time'] - now)
            if self.p.resource(self.D['xy']) >= cost:
                self.p.add_resource(self.D['xy'], -cost)
                with self.p.lock:
                    o['end_time'] = now
                    self.p.dirty = True
                self.os_state(now)
                ok = True
                self.log('   Trinity OS: %d skipped with Xyralith' % cost)
        stack = stack_msg('eqt_error_generic') if not ok else dict(_='BaseStackCommand', type=0, enumBaseKey=0, stringBasekey='',
                                                                    argsList=[])
        return [('TrinityTrialsDropLevelOptionalCommand', dict(success=ok, stack=stack)), self.drop_level_cmd(now)]

    def ui(self, f, now=None):
        """TrinityTrialsUIRequest {optionalType: 0 INIT, 1 PASS, 2 DROP_LEVEL} (the responses in the save)."""
        t = int(f.get('optionalType') or 0)
        if t == 1:
            return [self.reward_pass.cmd('TrinityTrialsPassCommand', now)]
        if t == 2:
            return [self.drop_level_cmd(now)]
        return [self.reward_pass.cmd('TrinityTrialsPassCommand', now),
                ('TrinityTrialsRewardDescriptionCommand', dict(rewardDescriptionList=[dict(x) for x in self.D['reward_description']])),
                self.drop_level_cmd(now)]

    def reward(self, loot, n):
        """The pass's packages (package_trinity-*): their contents."""
        if loot in self.D['packages']:
            out = []
            for l, k in self.D['packages'][loot]:
                out += self.m.reward(l, k * n) if self.m else []
            return out
        return super().reward(loot, n)
