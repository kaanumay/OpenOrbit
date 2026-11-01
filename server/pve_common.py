"""Shared parts of the endless and rogue-lite PvE modes (roadmap Stage 8): the wave run on the mode map, per-instance
strengthening of aliens, screen messages and personal ranking rows.

Run (as the world's gate; world.py calls on_death on a death, tick in the loop): waves in order, each wave made of sub-waves
([[NPC type, count] ...]); when a sub-wave is cleared the next one comes, and when a wave ends the mode's wave_done says what happens ('pause' timed wait,
'ongoing' the next at once, 'halt' the mode manages itself: gate choice, ending ...). The mode object's interface:
  key, name                            for the log and messages
  waves(), wave_count()                the wave list (each {'name', 'groups': [[[type, count], ...], ...], 'scale'?})
  scale(n, wave_index, spec)           strengthens a spawned alien (HP, shield, damage, reward)
  wave_started(i), wave_done(i, now)   events; wave_done -> 'pause' | 'ongoing' | 'halt'
  on_death() -> remaining HP or None, revive()
Persistent alien (group row, third item True): takes no damage while the others live (boss protection).
"""
import math, random, time

import settings as SET
import galaxy_gates as KAPI


def scale_npc(n, hp=1.0, dmg=1.0, reward=1.0, extra=None):
    """Strengthens the alien for this instance: a copy of the type's values (the type is shared, the instance separate)."""
    d = dict(n.d)
    d['hp'] = max(1, int(d['hp'] * hp))
    d['shield'] = int(d['shield'] * hp)
    d['damage'] = int(d['damage'] * dmg)
    d['reward'] = {k: int(v * reward) for k, v in d['reward'].items()}
    d['cargo'] = {k: int(v * reward) for k, v in d.get('cargo', {}).items() if int(v * reward) > 0}
    if extra:
        d.update(extra)
    n.d = d
    n.hp, n.shield = d['hp'], d['shield']
    return n


def screen(text, big=False):
    return KAPI.screen(text, big=big)


def rank_module(name, p, value, when='', **extra):
    """Single-player ranking row (the player themselves; 0 if rank is 1 or there is no value)."""
    return dict(_=name, name=p.d['pilot'].get('userName', ''), rank=1 if value else 0, **extra)


class Run:
    """The wave run on the mode map (a generalization of galaxy_gates.Run). phase: intro, fight, next (between sub-waves), break (pause),
    hold (the mode is holding), done, dead."""

    def __init__(self, world, mode, start=0, intro_sec=6, break_sec=10, sub_sec=3):
        self.w, self.m = world, mode
        self.key = mode.key
        self.i = start
        self.sub = 0
        self.npcs, self.keep = set(), set()
        self.exposed = False
        k = SET.multiplier('wave_wait')                      # panel: wave waits
        self.break_sec, self.sub_sec = break_sec * k, sub_sec * k
        self.counted = None
        self.left = None
        self.phase, self.t = 'intro', time.time() + intro_sec * k
        self.started = None                 # the moment the wave started (duration measurement)

    # compatible with galaxy_gates.Run (world.py, alien.py: k.npcs, k.key, on_death, revive)
    def wave(self):
        return self.m.waves()[self.i]

    def begin(self, i, delay=None):
        """Move on to wave i (after a pause or at once)."""
        self.i, self.sub, self.counted, self.exposed = i, 0, None, False
        self.npcs.clear()
        self.keep.clear()
        self.phase, self.t = ('break', time.time() + delay) if delay else ('intro', time.time())

    def countdown(self, now):
        left = int(math.ceil(self.t - now))
        if left in (10, 5, 3, 2, 1) and left != self.counted:
            self.counted = left
            self.w.send([screen('Wave %d begins in %d seconds' % (self.i + 1, left))])

    def tick(self, now):
        w = self.w
        if hasattr(self.m, 'tick') and not w.hero_dead and self.phase in ('fight', 'next', 'break', 'hold'):
            self.m.tick(now)                    # the mode's own rules (the Voidmare missile, the escorted ship ...)
        if w.hero_dead or w.jumping or self.phase in ('done', 'dead', 'hold'):
            return
        if self.phase == 'fight':
            alive = sum(1 for i in self.npcs - self.keep if i in w.npcs)
            if alive:
                if alive <= 3 and alive != self.left:
                    self.left = alive
                    w.send([screen('Aliens left: %d' % alive)])
                return
            if self.sub + 1 < len(self.wave()['groups']):
                self.sub += 1
                self.phase, self.t = 'next', now + self.sub_sec
                return
            if any(i in w.npcs for i in self.keep):
                if not self.exposed:
                    self.exposed = True
                    w.send([screen('The guardian is vulnerable now!', big=True)])
                return
            self.npcs.clear()
            self.keep.clear()
            nxt = self.m.wave_done(self.i, now)
            if nxt == 'halt':
                self.phase = 'hold'
            elif self.i + 1 >= self.m.wave_count():
                self.phase = 'done'
            else:
                self.begin(self.i + 1, self.break_sec if nxt == 'pause' else 0.5)
            return
        if now < self.t:
            if self.phase == 'break':
                self.countdown(now)
            return
        if self.phase in ('intro', 'break'):
            self.started = now
            self.m.wave_started(self.i)
        self.spawn(now)
        self.left = None
        self.phase = 'fight'

    def spawn(self, now):
        w = self.w
        hx, hy = w.hero_pos(now)
        for j, row in enumerate(self.wave()['groups'][self.sub]):
            tip, count = row[0], row[1]
            keep = len(row) > 2 and row[2]
            if tip not in w.CFG_TYPES:
                w.log('   %s: unknown type %s' % (self.m.name, tip))
                continue
            angle, dist = random.uniform(0, 2 * math.pi), random.uniform(1100, 1500)
            cx = min(max(hx + math.cos(angle) * dist, 500), w.map_w - 500)
            cy = min(max(hy + math.sin(angle) * dist, 500), w.map_h - 500)
            lair = self.m.lair(j) if hasattr(self.m, 'lair') else None      # ambush: waits at a fixed point (echoes.lair)
            if lair:
                cx, cy = lair[:2]
                lair = {'r': lair[2], 'on': False}                   # the group's shared ambush state: when one is attacked, all
            if not keep:
                count = SET.count('wave_aliens', count)            # panel: the alien count in the waves (one protector)
            for x, y in KAPI.spread(cx, cy, count, w.map_w, w.map_h):
                n = w.spawn_npc_at(tip, x, y, prep=lambda n: self.m.scale(n, self.i, self.wave()), wave=True)   # strengthened and reported
                n.gate, n.engaged, n.hunt = True, True, True
                if lair:
                    n.engaged, n.hunt, n.ambush = False, False, lair
                n.next_think = now
                self.npcs.add(n.id)
                if keep:
                    self.keep.add(n.id)
                    n.invulnerable = lambda: any(j in self.w.npcs for j in self.npcs - self.keep)

    def on_death(self):
        if self.phase in ('done',):
            return None
        left = self.m.on_death()
        self.before_death = self.phase
        self.phase = 'dead'
        return left

    def revive(self):
        if self.phase == 'dead':
            self.phase = getattr(self, 'before_death', 'fight')
