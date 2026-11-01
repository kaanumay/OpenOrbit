"""Plutus' Experiments (Plutus Experiment Event, February 2019; roadmap ETKINLIKLER-34, URETIM-8; data in data/event_gates.json 'experiment'
<- tools/event_gates.py, source belgeler/wiki/etkinlikler/plutus_deney.json).

Three risks: Low (your own X-1 maps), Medium (X-5), High (4-4; PvE instead of PvP). While the event runs, on the map the player is on, if the cooldown
(Low and Medium 20 min, High 30 min; "shot included") has elapsed, a beacon tower (Plutus Beacon) spawns nearby. The first shot at the tower starts a
35 s timer (the client's Plutus texts: first shot, at 10 s "the more damage, the better the alien", at 35 s); depending on the damage the tower took,
the alien of that risk tier appears (Saimon Aberration ... Devolarium Aberration; Kristallin Oddity ... Uber Kristallon Oddity; Awakened Lordakium,
Overlord, Devourer). If no shot is fired within 2 minutes the tower escapes ("escaped"); the cooldown still runs. When the alien is destroyed, a box drops by
the tier of the damage dealt to it (BEACON_LOW_RISK_BOX_0-11, MED_0-12, HIGH_1-8): progress points, Tarnom (Low/Medium), Opitite (Medium/High) and lucky items
(BRB-2, Backup Shield 2, the Hecate ship, the Dusklight Hecate design; in High's top tier BRB-2 and Backup Shield 2 are certain).
Tarnom and Opitite are materials of Assembly's 13 recipes (they came out of assembly.NO_SOURCE). The reward of the progress point thresholds (1,000 -> 15,000 CC-D,
5,000 -> 10,000 Seprom, 10,000 -> 15,000 CC-C, 20,000 -> 96 DMG-DLB + 96 SHD-DLB, 50,000 -> NPC Nuke): since the client's progress window is dead, it is given
once, automatically, when the threshold is reached.
Plutus' Experiments is not in the calendar: it runs in the Gauntlet of Plutus window (or the calendar's 'plutus_experiment' event if there is one).
In the profile: plutus_experiment {last: {risk: time of the last beacon}, pp, claimed: [thresholds given]}. A system of extra_events.ExtraEvents (attach, tick,
on_kill).
"""
import math, random, time

import settings as SET
import world as world_module
import event_gate as EKP
import map_links as H
import galaxy_gates as GALAXY
import event_calendar as CAL

D = EKP.D.get('experiment') or {}
EVENT = 'plutus_experiment' if 'plutus_experiment' in CAL.EVENTS else D.get('event', 'plutus')
BEACON = (D.get('beacon') or {}).get('type', 'experiment_beacon')
PREFIX = 'experiment_'


def type_name(risk, i):
    return '%s%s_%d' % (PREFIX, risk, i)


def _register():
    if not D:
        return
    world_module.CFG['types'][BEACON] = {k: v for k, v in D['beacon'].items() if k != 'type'}
    for key, r in D['risks'].items():
        for i, a in enumerate(r['alien_spawns']):
            world_module.CFG['types'][type_name(key, i)] = EKP._tip(a)


_register()


def active(now=None):
    return EVENT in CAL.active(now)


def risk_of(world, faction):
    """Which risk's map this map is (Low: your own X-1s, Medium: your own X-5s, High: 4-4); None if none."""
    m = int(world.map_id)
    for key, r in D.get('risks', {}).items():
        want = r['map_class']
        if (H.name(m) == want) if want == '4-4' else (H.map_class(m) == want and H.company(m) == faction):
            return key
    return None


def tier(risk, dealt):
    """The box tier of the damage dealt to the alien (the highest lower bound passed; no box below the lowest bound) or None."""
    got = [t for t in D['risks'][risk]['boxes'] if dealt >= t['from_']]
    return got[-1] if got else None


def stage(risk, dealt):
    """The rank of the alien that appears by the damage dealt to the tower (the strongest whose threshold is passed)."""
    return max(i for i, a in enumerate(D['risks'][risk]['alien_spawns']) if a['threshold'] <= dealt)


class PlutusExperiment:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.enc = None                  # the ongoing encounter: {risk, tower, spawned, first, tooltip, warning, alien}

    @property
    def st(self):
        return self.p.d.setdefault('plutus_experiment', dict(last={}, pp=0, claimed=[]))

    # ------------------------------------------------------------ cooldown
    def cooldown_left(self, risk, now):
        if SET.get('no_entry_limit'):                       # panel: no daily/yearly/one-time and no cooldown
            return 0
        return max(0.0, self.st['last'].get(risk, 0) + D['risks'][risk]['cooldown_sec'] - now)

    @staticmethod
    def cooldown_msg(left):
        if left >= 60:
            return GALAXY.screen('key:msg_npc_spawning_beacon_cd_min', MINUTES=int(math.ceil(left / 60.0)))
        return GALAXY.screen('key:msg_npc_spawning_beacon_cd_sec', SECONDS=int(math.ceil(left)))

    # ------------------------------------------------------------ map and time
    def attach(self, world):
        self.world, self.enc = world, None
        if not D or not active():
            return []
        risk = risk_of(world, self.p.d['pilot'].get('factionId'))
        left = self.cooldown_left(risk, time.time()) if risk else 0
        return [self.cooldown_msg(left)] if left > 0 else []

    def tick(self, now):
        w = self.world
        if not D or not w:
            return []
        if not active(now):
            return self.end(w) if self.enc else []
        risk = risk_of(w, self.p.d['pilot'].get('factionId'))
        if not risk or w.hero_dead:
            return []
        if self.enc is None:
            return self.spawn_beacon(w, risk, now) if self.cooldown_left(risk, now) <= 0 else []
        return self.step(w, now)

    def end(self, w):
        """Event ended: the tower and the ongoing alien go away."""
        e, self.enc = self.enc, None
        msgs = []
        with w.lock:
            for i in (e['tower'], e.get('alien')):
                n = w.npcs.get(i) if i else None
                if n:
                    msgs += w.remove_npc(n)
        return msgs

    def spawn_beacon(self, w, risk, now):
        hx, hy = w.hero_pos(now)
        a, d = random.uniform(0, 2 * math.pi), random.uniform(500, 900)
        x = min(max(hx + math.cos(a) * d, 500), w.map_w - 500)
        y = min(max(hy + math.sin(a) * d, 500), w.map_h - 500)
        with w.lock:
            n = w.spawn_npc_at(BEACON, x, y)
            n.dealt = 0
            n.damage_hook = lambda dmg, n=n: self.beacon_hit(n, dmg)
        with self.p.lock:
            self.st['last'][risk] = now
            self.p.dirty = True
        self.enc = dict(risk=risk, tower=n.id, spawned=now, first=None, tooltip=False, warning=False, alien=None)
        self.log('   Plutus’ Experiments: %s beacon tower spawned (%d, %d)' % (D['risks'][risk]['name'], x, y))
        return [GALAXY.screen('key:msg_npc_spawning_beacon_high_risk_spawn') if risk == 'high'
                else GALAXY.screen('A %s beacon has spawned.' % D['risks'][risk]['name'])]

    @staticmethod
    def beacon_hit(n, dmg):
        """The tower cannot be destroyed: the damage it takes is counted, its HP is restored (the damage hook of world.hit_npc)."""
        n.dealt += dmg
        n.hp, n.shield = n.d['hp'], n.d['shield']

    def step(self, w, now):
        e, msgs = self.enc, []
        with w.lock:
            if e['alien']:                                  # the alien appeared: the encounter ends when it is destroyed (the box is in on_kill)
                n = w.npcs.get(e['alien'])
                if n is None or not n.alive:
                    self.enc = None
                return msgs
            b = w.npcs.get(e['tower'])
            if b is None:
                self.enc = None
                return msgs
            if e['first'] is None:
                if b.dealt > 0:
                    e['first'] = now
                    msgs.append(GALAXY.screen('key:msg_npc_spawning_beacon_first_shot'))
                elif now >= e['spawned'] + D['fire_sec']:       # not shot within 2 minutes: it escapes
                    msgs += w.remove_npc(b) + [GALAXY.screen('key:msg_npc_spawning_beacon_escaped')]
                    self.enc = None
                return msgs
            t = now - e['first']
            if not e['tooltip'] and t >= D['hint_sec']:
                e['tooltip'] = True
                msgs.append(GALAXY.screen('key:msg_npc_spawning_beacon_10_sec'))
            if not e['warning'] and t >= D['wave_sec'] - 10:       # the 35th second of the 45 s timer (forum 143093)
                e['warning'] = True
                msgs.append(GALAXY.screen('key:msg_npc_spawning_beacon_35_sec'))
            if t >= D['wave_sec']:
                msgs += self.release(w, b, e)
        return msgs

    def release(self, w, b, e):
        """35 s elapsed: the alien appears by the damage the tower took, the tower leaves."""
        risk = e['risk']
        i = stage(risk, b.dealt)
        x, y = b.mover.pos(time.time())
        msgs = w.remove_npc(b)
        n = w.spawn_npc_at(type_name(risk, i), x, y, wave=True)
        n.gate, n.hunt, n.dealt = True, True, 0
        n.damage_hook = lambda dmg, n=n: setattr(n, 'dealt', n.dealt + dmg)
        e['alien'] = n.id
        self.log('   Plutus’ Experiments: tower took %d damage -> %s' % (b.dealt, D['risks'][risk]['alien_spawns'][i]['name']))
        return msgs

    # ------------------------------------------------------------ reward
    def on_kill(self, w, npc, x, y):
        """The experiment alien was destroyed: the box of the tier of the damage dealt to it drops (reward when the box is collected: collect)."""
        if not npc.tip.startswith(PREFIX) or npc.tip == BEACON:
            return []
        risk = npc.tip[len(PREFIX):].rsplit('_', 1)[0]
        t = tier(risk, min(getattr(npc, 'dealt', 0), npc.d['hp'] + npc.d['shield']))
        if t:
            h = w.drop_box(t['type'], x, y, None, 900)
            w.boxes[h]['al'] = lambda b, t=t: self.collect(w, t)
            self.log('   Plutus’ Experiments: %s dropped (%d damage)' % (t['type'], npc.dealt))
        return []

    def collect(self, w, t):
        """Box collected: the certain rows (Tarnom, Opitite, BRB-2 and Backup Shield 2 in High's top tier), lucky items, progress points."""
        msgs = []
        for loot, n in t['guaranteed']:
            msgs += w.grant_loot(loot, n)
        for loot, n, chance in t['chance']:
            if random.random() < SET.chance('drop', chance, 'event'):
                msgs += w.grant_loot(loot, n)
        return msgs + self.add_points(w, t['pp'])

    def add_points(self, w, n):
        """Progress points: added; the reward of every row whose threshold is reached is given once."""
        st = self.st
        with self.p.lock:
            st['pp'] += n
            due = [r for r in D['point_exchange'] if st['pp'] >= r['points'] and r['points'] not in st['claimed']]
            st['claimed'] += [r['points'] for r in due]
            self.p.dirty = True
        msgs = [GALAXY.screen('Progression points: +%d (%d)' % (n, st['pp']))]
        for r in due:
            for loot, k in r['reward']:
                msgs += w.grant_loot(loot, k)
            msgs.append(GALAXY.screen('Progression reward (%d points) received.' % r['points'], big=True))
            self.log('   Plutus’ Experiments: %d point reward' % r['points'])
        return msgs
