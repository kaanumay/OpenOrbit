"""Eternal Black Light (roadmap stage 8; the client's EternalBlacklight* commands; data data/pve_modes.json "ebl").

The Eternal CPU (from the shortcut bar) opens the gate on the company's X-BL map (level 17). Endless waves: one round is 51 waves, 6 rooms
(460-465; five of them 10 waves each, the sixth Strokelight Barrage); when the round ends it starts over, with the aliens' values and rewards x1.8. One life:
when you die the run ends, and the Blacklight Shard reward of the tier of the last completed wave (and from wave 26 a chance of Indoctrine Accelerator)
is given. Checkpoints (after waves 10, 20, 30, 40, 50 and 51): a booster point (1; 2 at 51), continue and an exit portal; you can leave and
later continue where you left off (no new CPU needed). Boosters (the client's BoosterType: 0 cooldown, 1 damage, 2 laser damage,
3 rocket damage, 4 laser accuracy, 5 HP, 6 shield, 7 speed): three options in the window (EternalBlacklightBoosterInfoCommand), a choice costs one point
(EternalBlacklightChooseOptionRequest {choosenOption}); the chance of the chosen type appearing again decreases; active only on this mode's maps,
reset when the run ends. Uridium at most 75,000 per run (after that aliens give no uridium). Ranking: furthest wave (single
player: only the player; the Hall of Fame's EternalGate list).
In the profile: pve.ebl {gate, run {wave, points, option [3], weight {type: multiplier}, active {type: %}, uridium, start}, best, best_at}.
"""
import json, math, os, random, time

import settings as SET
import galaxy_gates as KAPI
import rankings as RK
import pve_common as PS

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'pve_modes.json'), encoding='utf8')).get('ebl')
PORTAL = 156900000           # + 0 X-BL gate, + 1 continue, + 2 exit


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Ebl:
    key, name = 'ebl', 'Eternal Black Light'

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.D = D
        self.world = None

    @staticmethod
    def maps():
        return D['maps'] if D else []

    @property
    def st(self):
        return self.p.d.setdefault('pve', {}).setdefault('ebl', {})

    @property
    def run(self):
        return self.st.get('run')

    # ------------------------------------------------------------ CPU and gate
    def own_bl(self, map_id):
        import map_links as H
        name = H.name(map_id)                      # the server's name is BL-1/2/3 (1-BL ... in the client)
        return name == 'BL-%s' % self.p.d['pilot'].get('factionId')

    def use_cpu(self, map_id):
        if not self.own_bl(map_id) or self.st.get('gate') or self.run or self.p.d['pilot'].get('level', 1) < D['level']:
            return None
        if self.p.use_ammo(D['cpu']) is None:
            return None
        with self.p.lock:
            self.st['gate'] = True
            self.p.dirty = True
        self.log('   Eternal CPU: gate at X-BL')
        return [KAPI.screen('The Eternal Black Light gate has opened.', big=True), self.info_cmd()]

    def portals(self, map_id):
        import map_links as H
        if not self.own_bl(map_id) or not (self.st.get('gate') or self.run):
            return []
        w, h = H.map_size(map_id)
        return [dict(gateId=PORTAL, x=w // 2, y=h // 2 - 1500, target=0, designId=D['portal'], gate='ebl', windowed='ebl')]

    def gate_jump(self):
        """Jumped to the X-BL gate: if there is no run one starts, if there is one it goes to the room it was in -> (target, messages)."""
        if not self.run:
            with self.p.lock:
                self.st['run'] = dict(wave=0, points=0, option=[], weight={}, active={}, uridium=0, start=time.time())
                self.st['gate'] = False
                self.p.dirty = True
            self.log('   Eternal Black Light: run started')
        return self.room_map(), []

    # ------------------------------------------------------------ waves
    def wave_in_lap(self, done=None):
        """The next wave (1-51) and round (1...): from the number of completed waves."""
        done = self.run['wave'] if done is None else done
        return done % D['type'] + 1, done // D['type'] + 1

    def room_map(self):
        w, lap = self.wave_in_lap()
        room = D['waves'][w - 1]['room']
        return D['maps'][room - 1]

    def waves(self):
        """This room's remaining waves (run order: from the completed count)."""
        w, lap = self.wave_in_lap(self.start_done)
        room = D['waves'][w - 1]['room']
        return [x for x in D['waves'] if x['room'] == room and int(x['name']) >= w]

    def wave_count(self):
        return len(self.waves())

    def scale(self, n, i, wave):
        w, lap = self.wave_in_lap(self.start_done + i)
        f = D['kind_multiplier'] ** (lap - 1)
        k = wave.get('multiplier', 1.0)
        PS.scale_npc(n, f * k, f * k, f * k)
        r = self.run
        if r['uridium'] >= D['uridium_limit']:
            n.d['reward']['uridium'] = 0                  # the run's uridium limit
        else:
            r['uridium'] += n.d['reward']['uridium']
        return n

    def attach(self, world):
        self.world = world
        if not self.run:
            world.add_gate(self.exit_portal(world))
            return None
        if int(world.map_id) != int(self.room_map()):
            # the room's last wave is finished (room transitions are at checkpoints): exited and re-entered at a checkpoint. The portals
            # went with the world; the run continued in the old room with wave 11 and no exit (live test H77). Portals again, no wave
            self.checkpoint_gates(world)
            world.send([self.info_cmd(), self.booster_cmd(), self.rank_cmd()])
            return None
        self.start_done = self.run['wave']
        world.gate = PS.Run(world, self, break_sec=2)
        world.send([self.info_cmd(), self.booster_cmd()])
        return world.gate

    def wave_started(self, i):
        w, lap = self.wave_in_lap(self.start_done + i)
        self.world.send([KAPI.screen('Eternal Black Light - Wave %d (lap %d)' % ((lap - 1) * D['type'] + w, lap), big=True)])

    def wave_done(self, i, now):
        r = self.run
        with self.p.lock:
            r['wave'] += 1
            done = r['wave']
            record = done > self.st.get('best', 0)
            if record:
                self.st['best'] = done
                self.st['best_at'] = int(time.time() * 1000)
            self.p.dirty = True
        self.p.ach('gate_wave', type='ETERNAL_GATE', wave=done)       # achievement: "Reach wave N in the Eternal Gate"
        if record:
            self.p.ach('record_ebl')                  # champion achievement: the only player in the ranking, personal record first
        w = (done - 1) % D['type'] + 1
        pts = D['control'].get(str(w))
        self.world.send([('EternalBlacklightWaveInfoCommand', self.wave_info())])
        if not pts:
            return 'ongoing'
        with self.p.lock:
            r['points'] += pts
            self.p.dirty = True
        if not r['option']:
            self.roll()
        self.checkpoint(done, pts)
        return 'halt'

    def checkpoint_gates(self, w):
        x, y = w.map_w // 2, w.map_h // 2
        w.add_gate(dict(gateId=PORTAL + 1, x=x - 1200, y=y, target=self.room_map(), designId=D['portal'], gate='ebl', arrival=(10500, 6550)))
        w.add_gate(self.exit_portal(w, side=True))

    def checkpoint(self, done, pts):
        w = self.world
        self.checkpoint_gates(w)
        w.send([KAPI.screen('Checkpoint! +%d booster point%s. Continue or leave (your progress is kept).' % (pts, 's' if pts > 1 else ''),
                            big=True), self.booster_cmd(), self.info_cmd(), self.rank_cmd()])
        self.log('   EBL checkpoint: wave %d, +%d points' % (done, pts))

    def exit_portal(self, world, side=False):
        bl = {1: 306, 2: 307, 3: 308}.get(self.p.d['pilot'].get('factionId'), 306)
        return dict(gateId=PORTAL + 2, x=world.map_w // 2 + (1200 if side else 0), y=world.map_h // 2, target=bl, designId=1, gate='ebl',
                    exit=True)

    def on_death(self):
        """One life: the run ends, the reward of the tier of the last completed wave."""
        r = self.run
        if not r:
            return 0
        done = r['wave']
        tier = next((t for t in D['death_reward'] if t['min_value'] <= done <= t['max_count']), None)
        msgs = []
        if tier and done:
            msgs += self.m.prize(D['part'], tier['part'])
            if tier['iac'] and random.random() < SET.chance('drop', D['iac'][2], 'mod'):
                msgs += self.m.prize(D['iac'][0], D['iac'][1])
        with self.p.lock:
            self.st['run'] = None
            self.p.dirty = True
        self.log('   EBL ended: %d waves; %s' % (done, '%d Blacklight Shard' % tier['part'] if tier and done else 'no reward'))
        if self.m:
            msgs += self.m.apply_stats()             # boosters are gone
        self.world.send(msgs + [KAPI.screen('Eternal Black Light ended at wave %d.' % done, big=True), self.info_cmd(), self.rank_cmd()])
        return 0

    def revive(self):
        pass

    # ------------------------------------------------------------ boosters
    def roll(self):
        """Three options: type by weight (the weight of the chosen ones decreases), tier 60/30/10."""
        r = self.run
        pool = list(D['boosters'])
        out = []
        for _ in range(3):
            weights = [r['weight'].get(str(b['type']), 1.0) for b in pool]
            b = random.choices(pool, weights)[0]
            pool.remove(b)
            vals = b['values']
            tier = random.choices(range(len(vals)), D['booster_tier'][:len(vals)])[0]
            out.append([b['type'], vals[tier]])
        r['option'] = out

    def choose(self, f):
        """EternalBlacklightChooseOptionRequest {choosenOption} -> mesajlar."""
        r = self.run
        if not r or r['points'] <= 0 or not r['option']:
            return [self.booster_cmd()]
        i = int(f.get('choosenOption') or 0)
        i = i - 1 if 1 <= i <= 3 else i               # the client may send 0-2 or 1-3
        if not 0 <= i < len(r['option']):
            return [self.booster_cmd()]
        t, v = r['option'][i]
        with self.p.lock:
            r['active'][str(t)] = r['active'].get(str(t), 0) + v
            r['weight'][str(t)] = r['weight'].get(str(t), 1.0) * D['booster_decay']
            r['points'] -= 1
            self.roll()
            self.p.dirty = True
        self.log('   EBL booster: type %d +%d%% (total %d%%)' % (t, v, r['active'][str(t)]))
        return (self.m.apply_stats() if self.m else []) + [self.booster_cmd()]

    def mods(self, map_id):
        """The boosters' bonuses while on this mode's map (into profile.mods)."""
        r = self.run
        if not r or int(map_id) not in D['maps']:
            return {}
        keys = {b['type']: b['key'] for b in D['boosters']}
        return {keys[int(t)]: v / 100.0 for t, v in r['active'].items() if int(t) in keys}

    # ------------------------------------------------------------ indicators
    def wave_info(self):
        r = self.run or {}
        return dict(furthestWave=int(self.st.get('best', 0)), currentWave=int(r.get('wave', 0)))

    def booster_cmd(self):
        r = self.run or {}
        opts = (r.get('option') or []) + [[0, 0]] * 3
        b = lambda t, v: mod('EternalBlacklightBoosterCommand', value=int(v), boosterType=int(t))
        return ('EternalBlacklightBoosterInfoCommand', dict(
            option1=b(*opts[0]), option2=b(*opts[1]), option3=b(*opts[2]),
            skillPointInfo=mod('EternalBlacklightSkillPointInfoCommand', skillPoint=int(r.get('points', 0))),
            currentBooster=[b(int(t), v) for t, v in sorted((r.get('active') or {}).items())]))

    def info_cmd(self):
        return ('EternalBlacklightInfoCommand', dict(
            waveInfo=mod('EternalBlacklightWaveInfoCommand', **self.wave_info()),
            cpuInfoCommand=mod('EternalBlacklightCpuInfoCommand', cpuCount=int(self.p.ammo(D['cpu']))),
            boosterInfoCommand=mod('EternalBlacklightBoosterInfoCommand', **self.booster_cmd()[1])))

    def when(self):
        """The Rank tab's TIME column: the client writes the text as is; the raw ms stamp "1792220704339" used to show (H76).
        The format is like the logbook dates in the save."""
        t = self.st.get('best_at')
        if not t:
            return ''
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(t) / (1000.0 if float(t) > 1e11 else 1.0)))

    def rank_cmd(self):
        """Rank tab: players on the server (furthest wave)."""
        import community as TP
        row = lambda r: mod('EternalBlacklightRankModule', waves=int(r[2]), name=r[1].d['pilot'].get('userName', ''), rank=r[0],
                            lastUpdateTime=self.when() if r[1] is self.p else '')
        top, me = TP.ranking(self.p, lambda x: int(((x.d.get('pve') or {}).get('ebl') or {}).get('best', 0)))
        info = mod('EternalBlacklightRankInfoCommand', topRankers=[row(r) for r in top], myRank=row(me))
        # the Rank tab only recognizes the event wrapper (like Astral's RogueLiteRankEventInfoCommand); without isEventEnabled
        # "No ranking boards are available at the moment." (live test H76)
        return ('EternalBlacklightRankingEventInfoCommand', dict(playerRankRanges=RK.ranges(RK.EBL), rankInfoCommand=info,
                                                                isEventEnabled=True))
