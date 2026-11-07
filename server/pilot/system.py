"""Auto Mode: the server flies the player's own ship (fights aliens kiting at the edge of the laser range, collects boxes, flees to a safe
zone and repairs at low HP, hunts on a list of maps, comes back after a death, stops on its own conditions). The panel's Auto Mode page
(panel/pilot_panel.py, panel/ui/pilot.js) writes the settings to pilot.json next to the save slot's profile and reads the bot's status from
<log folder>/pilot_status_<slot>.json; no other channel is needed. The status also carries the live map (act/radar.py: the ship, the aliens,
other pilots, boxes, ore, portals; the ship's trail and where it destroyed aliens), written every second whether the bot runs or not.

Kept apart from the rest of the server (a local feature): the session adds it as an extra-events system (game.py, one line: ExtraEvents.add),
which gives attach(world) on every map load, tick(now) every second, event(kind, kw) and on_kill(world, npc, x, y). On attach the bot
  - runs its loop as a World timer (world.later), every STEP seconds, under the world lock: a new World (map change, respawn) restarts it
    and the old one's timers die with it;
  - wraps that world's on_move: a MoveRequest that does not answer one of the bot's orders is the player's own click and pauses the bot.
Decisions: brain.py (pure) and tasks/ (one module per feature); the World and the session's systems are read and driven only by the act/
package.

Operating modes (tasks/modes.py): Hunt, Galaxy gate, Quests, Mining; the mode says what the bot may do (hunt, boxes, harvest, sell) and
what its errand is. One step: paused (dead -> tasks/recover, jumping, the client's own autopilot, a manual move) / stop conditions /
combat support and resupply / enemy pilots / low HP (flee, repair) / the mode's errand (going home, the gate trip, selling, the quest giver,
the mode's maps) and the aliens attacking the ship (defend, clear_path) / new targets and boxes if the mode hunts / the gate's next wave /
ore if the mode harvests / an empty map (next map of the list) / patrol.
A target that loses no HP / shield for stuck_sec while in range, and a box still there after BOX_SEC of trying, are left alone for a while
(the bot used to fire forever at an alien it could not hurt and to circle a box it could not take).
Activities (self.mode, the panel's status): fight, box, roam, idle, flee, repair, hide, ore, gate (next wave), and the errands travel, home,
sell, quest, gate_trip."""
import math, time, traceback
from collections import deque

import paths as PTH

from . import act as A
from . import brain as B
from . import config as C
from .stats import Stats, text
from .tasks import economy as ECON, modes as MODES, players as PLAYERS, quests as QUESTS, recover as RECOVER, stop as STOP, support as SUPPORT
from .tasks import gates as GATES, lure as LURE, travel as TRAVEL

STEP = 0.25
CATALOG_SEC = 10              # the panel's lists (maps, owned items) are refreshed this often
IGNORE_SEC = 60               # a target that took no damage is left alone this long
BOX_PROGRESS = 100            # getting this much closer to the box restarts its BOX_SEC timer
BOX_SEC = 20                  # flying to the same box this long without taking it: the box is skipped
BOX_IGNORE_SEC = 300
TRAIL = 300                   # the ship's trail on the panel's map: one point a second (5 minutes)
TRAIL_STEP = 40               # a new point only after this many units of flight
MARKS = 60                    # where aliens were destroyed / the ship died, on this map
QUEST_FLEE_HP, QUEST_RESUME_HP = 50, 95         # an active quest fails on death: the ship flees at half its HP
AWAY_RESUME = 25              # with no safe zone on the map, back to work this many % above the flee threshold


class Pilot:
    def __init__(self, session, log=print):
        self.session, self.log = session, log
        self.p = session.profile
        self.cfg_path = C.path_for(self.p.path)
        self.status_file = C.status_path(PTH.LOGS, self.p.path)
        self.cfg, self.cfg_mtime = C.load(self.cfg_path), self._mtime()
        self.world = None
        self.act = None
        self.running = False            # enabled and started (the panel's Start)
        self.state, self.reason = 'off', ''
        self.stats = Stats()
        self.catalog, self.catalog_at = {}, 0.0
        self.cfg_mode = None            # the mode chosen in the settings when run_mode was set
        self.trail, self.marks, self.trail_map = deque(maxlen=TRAIL), deque(maxlen=MARKS), None
        self.reset_run(0.0)

    def reset_run(self, now):
        """Everything one run of the bot (Start .. Stop) keeps."""
        self.mode = None                # the activity (see the module's docstring)
        self.target = None              # the main target (the ship flies to it)
        self.shot = None                # what the lasers fire at: the main target, or an alien attacking the ship on the way
        self.pause_until = 0.0
        self.view = {}                  # the last step's view for the status file (written outside the world lock)
        self.base_ammo = None           # the normal laser ammo to come back to after an RSB-75 / RCB-140 shot
        self.sab_low = False            # the shield fell below sab.start_pct and is not back to sab.stop_pct yet
        self.sab_prev = None            # the ammo selected before SAB-50 (None: SAB-50 is not the bot's choice)
        self.start_map = None           # the map where the bot started (the mode's map when its list is empty)
        self.unsafe = {}                # map -> until when it is avoided (enemy pilots)
        self.travel_logged = 0.0
        self.dead_at, self.revive_at = None, 0.0
        self.homing = ''                # a stop reason: flying home before stopping
        self.support_at, self.config_at, self.pet_at = 0.0, 0.0, 0.0
        self.sell_block, self.supply_at, self.supply_fail = 0.0, 0.0, {}
        self.danger_until = 0.0         # enemy pilots seen: hidden until then
        self.no_shelter = None          # the map already noted as having no safe zone to hide in
        self.ended = set()              # the modes that ended in this run (a 'then' back to one of them stops the bot: no ping-pong)
        self.quests_finished = set()    # the quests completed in this run (the 'quest' event)
        self.ignored, self.box_ignored = {}, {}         # alien id / box hash -> until when it is left alone
        self.track = None               # (target id, lowest HP + shield seen, since when): track_target
        self.lure = None                # drawing a target out of an immobile alien's zone (tasks/lure.py)
        self.box_track = None           # (box hash, since when, shortest distance seen): track_box
        self.set_mode(None)

    def set_mode(self, mode):
        """The running mode (tasks/modes.py); what one mode keeps."""
        self.run_mode = mode
        self.errand = ''                # going somewhere (travel, home, sell, quest, gate_trip): see fight_or_collect
        self.hunt_map, self.empty_since, self.gate_done = None, None, False
        self.quest_goal = self.quest_maps = self.quest_aliens = None      # Quests mode: the quest's goal, maps, aliens (tasks/quests.py)
        self.quest_rules = None                                           # and the active quests' restrictions
        self.quest_skip = {}                                              # (quest, condition) -> until when it is set aside
        self.act_at, self.asset_out = 0.0, False                          # a one-off action's last try; out of a station object's reach
        self.quest_at = self.quest_block = 0.0

    # ------------------------------------------------------------ extra-events hooks
    def attach(self, world):
        self.world = world
        self.act = A.Actions(world, self.cfg['move_mode'], self.session)
        self.act.gate_ok = lambda key: GATES.can_build(self, key)          # Quests mode: a gate it may build and play
        self.target = None
        self.track = self.box_track = None
        self.ignored.clear()                        # alien ids / box hashes restart with every World
        self.box_ignored.clear()
        self.empty_since = None                     # a new map: its own empty-map timer
        if not getattr(world, '_pilot_hooked', False):
            world._pilot_hooked = True
            orig = world.on_move

            def on_move(f, _orig=orig, _w=world):
                self.client_move(_w, f)
                return _orig(f)
            world.on_move = on_move
            world.later(STEP, lambda: self.loop(world))
        return []

    def tick(self, now):
        m = self._mtime()
        if m != self.cfg_mtime:
            self.cfg_mtime = m
            self.cfg = C.load(self.cfg_path)
        if self.running:
            self.stats.sample(now)
        try:
            C.write_json(self.status_file, self.status(now))
        except OSError:
            pass
        return []

    def event(self, kind, kw):
        if kind == 'quest' and self.running:
            self.quests_finished.add(int(kw.get('id', 0)))
        if self.running:
            self.stats.event(kind, kw)
            if kind == 'gate' and not kw.get('dispatch'):
                self.gate_done = True
                self.stats.add('gates')
        return []

    def on_kill(self, world, n, x, y):
        """An alien the hero destroyed (World.kill_hooks): a mark on the panel's map."""
        if world is self.world:
            self.mark('kill', x, y)
        return []

    # ------------------------------------------------------------ helpers for the tasks
    def note(self, key, *args):
        """A line in the server log and in the panel's journal: key is an English template with {0} placeholders (pilot.js PIL_NOTES
        translates it), args its values."""
        self.log('   auto mode: %s' % text(key, args))
        self.stats.note(key, args)

    def mark(self, kind, x, y):
        self.marks.append([kind, int(x), int(y), int(time.time())])

    def drop_target(self, only_ours=False):
        """Stop firing. only_ours: only if the bot's own target is being fired at (a manual attack of the player stays)."""
        ours = [t for t in (self.target, self.shot) if t is not None]
        if ours and (not only_ours or any(self.act.attacking(t) for t in ours)):
            self.act.stop_attack()
        self.target = self.shot = None

    def stop(self, reason, home=True):
        """Stop the bot on its own (a stop condition, death, a mode's end): with go_home it first flies to the base (tasks/stop.home)."""
        if not self.cfg['enabled']:
            return                                  # already stopped in this step: the first reason stays
        if home and reason != 'dead' and self.cfg['stop']['go_home']:
            if not self.homing:
                self.homing = reason
                self.note('Stopping: {0} Flying to the base first.', reason)
            return                                  # on the way home: another reason does not cut the trip short
        self.homing = ''
        self.stats.d['stop_reason'] = reason
        self.note('Stopped: {0}', reason)
        self.cfg = dict(self.cfg, enabled=False)
        try:                                        # only the switch: settings the panel saved meanwhile stay
            C.save(self.cfg_path, dict(C.load(self.cfg_path), enabled=False))
            self.cfg_mtime = self._mtime()
        except OSError:
            pass

    def mode_end(self, reason):
        """The running mode has nothing left to do (gate done / not built / out of lives / out of reach, no quest): its 'then' setting,
        stop (going home first with go_home) or another mode (not one that already ended in this run)."""
        mode = MODES.current(self)
        self.ended.add(mode)
        block = MODES.THEN_BLOCK.get(mode)
        then = self.cfg[block]['then'] if block else 'stop'
        if then == 'stop' or then in self.ended:
            return self.stop(reason)
        self.note('{0} mode: {1} Switching to {2}.', mode, reason, then)
        self.set_mode(then)

    # ------------------------------------------------------------ loop
    def loop(self, world):
        if world is not self.world:
            return                                  # an old map: its loop ends
        try:
            self.step(time.time())
        except Exception:
            self.log('   auto mode: error\n%s' % traceback.format_exc())
        world.later(STEP, lambda: self.loop(world))

    def client_move(self, world, f):
        """A MoveRequest arrived (under no lock; the world takes its own)."""
        if not self.running or world is not self.world or self.act is None:
            return
        now = time.time()
        tx, ty = f.get('targetX', 0), f.get('targetY', 0)
        if self.act.ours(tx, ty, now):
            return
        if math.hypot(tx - f.get('positionX', tx), ty - f.get('positionY', ty)) <= A.base.OWN_MOVE_DIST:
            return                                  # the client stops where it stands after a jump: not the player's click
        self.pause_until = now + self.cfg['pause_sec']
        if self.cfg['pause_sec']:
            self.log('   auto mode: paused (manual move)')

    def start(self, now):
        self.running = True
        self.stats.reset(now)
        self.reset_run(now)
        self.start_map = self.act.map_id()
        self.cfg_mode = self.cfg['mode']
        self.set_mode(self.cfg['mode'])
        self.act.set_ammo(self.cfg['laser_ammo'])
        self.act.set_rocket(self.cfg['rocket_ammo'])
        self.note('Started in {0} mode.', self.run_mode)

    def halt(self):
        self.running = False
        self.state, self.reason = 'off', ''
        self.drop_target(only_ours=True)
        self.normal_ammo()
        self.mode, self.homing, self.view = None, '', {}
        self.set_mode(None)
        if not self.stats['stop_reason']:
            self.note('Stopped.')

    def step(self, now):
        cfg, act = self.cfg, self.act
        act.mode = cfg['move_mode']
        if not cfg['enabled']:
            if self.running:
                self.halt()
            return
        if not self.running:
            self.start(now)
        elif cfg['mode'] != self.cfg_mode:              # another mode chosen in the panel while running
            self.cfg_mode = cfg['mode']
            self.set_mode(cfg['mode'])
            self.ended.clear()
            self.drop_target(only_ours=True)
            self.note('{0} mode chosen.', self.run_mode)
        why = act.busy()
        if why == 'dead':
            self.state, self.reason, self.mode, self.target = 'paused', 'dead', None, None
            return RECOVER.dead(self, now)
        self.dead_at = None
        if why is None and act.client_autopilot():
            why = 'client_autopilot'                # the client's own AutoTactic is flying: the two must not fight over the ship
        if why is None and now < self.pause_until:
            why = 'manual'
        if why:
            self.state, self.reason = 'paused', why
            if why == 'manual':
                pick = act.player_target()          # the player picked a target by hand: keep it on resume (not the attacker fired at)
                if pick is not None and pick != self.shot:
                    self.target = pick
            return
        self.state, self.reason = 'running', ''
        act.follow(now)                             # around a wall: on to the next corner
        if not self.homing:
            r = STOP.check(self, now)
            if r:
                self.stop(r)
        QUESTS.update(self, now)                    # Quests mode: the quest's aliens and maps (its end can stop the bot)
        if not self.cfg['enabled']:
            return
        hunt = self.hunt_cfg(now)
        s = act.snapshot(now, hunt)
        hp = B.hp_pct(s)
        SUPPORT.run(self, s, now)                   # abilities, technologies, config, P.E.T. (uses the last step's target)
        ECON.supply(self, now)                      # ammo resupply
        self.view = dict(target=None)
        label = PLAYERS.run(self, s, now)           # enemy pilots: hide / leave the map / stop
        if label:
            self.mode, self.errand = label, ''
            return
        if self.mode in ('flee', 'repair') or hp < hunt['flee_hp']:
            resume = hunt['resume_hp']
            if self.no_shelter == s['map']:         # no safe zone (a galaxy gate, LoW, an enemy map): the attackers follow and the
                resume = min(resume, hunt['flee_hp'] + AWAY_RESUME)     # robot repairs only between their shots (live test, Alpha's last
            if hp >= resume:                        # wave: 9 minutes of running from six Protegits at 54 % HP, the wave never moved)
                self.mode = None
                self.note('Repaired: back to work.')
            else:
                return self.safety(s, hunt, now)
        self.fight_or_collect(s, hunt, now)

    def hunt_cfg(self, now):
        """The settings for this map: the aliens to hunt (this map's list, empty: all), its priority aliens, its drawn areas and what is
        left alone for now (brain.py). 'hunting': whether the mode takes new targets at all. Quests mode (tasks/quests.py): the quest's
        aliens, its restrictions (forbidden aliens, no laser: no fight at all, no rocket, no death: flees earlier), the boxes and the
        patrol its goal needs."""
        m = str(self.act.map_id())
        z = self.cfg['zones'].get(m) or {}
        for d in (self.ignored, self.box_ignored):
            if len(d) > 200:
                for k in [k for k, t in d.items() if t <= now]:
                    del d[k]
        out = dict(self.cfg, aliens=self.cfg['aliens'].get(m, []), priority=self.cfg['priority'].get(m, []), hunting=MODES.allows(self, 'hunt'),
                   forbid=(), work=z.get('work'), avoid=z.get('avoid') or [],
                   ignore={k for k, t in self.ignored.items() if t > now}, ignore_boxes={k for k, t in self.box_ignored.items() if t > now})
        g, r = self.quest_goal, self.quest_rules
        if MODES.current(self) == 'quest' and g and r is not None:
            out.update(forbid=r['forbid'], aliens=QUESTS.aliens(self, int(m)) if out['hunting'] else [])
            if r['no_laser']:
                out.update(defend=False, clear_path=False)
            if r['no_laser'] or g.get('hidden'):
                out['sab'] = dict(out['sab'], enabled=False)
            if r['no_rocket'] or r['no_laser']:
                out.update(rockets=False, launcher=False)
            if r['no_death']:
                out.update(flee_hp=max(out['flee_hp'], QUEST_FLEE_HP), resume_hp=max(out['resume_hp'], QUEST_RESUME_HP))
            if g['box']:
                out['boxes'] = dict(out['boxes'], **{'cargo' if g['box'] == 'steal' else g['box']: True})     # stolen boxes are cargo boxes
            if g['kind'] in ('travel', 'boxes', 'ore', 'pvp'):
                out['roam'] = True                  # a distance to fly, boxes, ore or pilots to find: the patrol is the work
            if g['kind'] == 'pvp':
                out['pvp'] = g['pvp']
                out['steal'] = g['box'] == 'steal'
            if g['action'] == 'rockets':
                out['rockets'] = True
            if g.get('hidden'):                     # flying cloaked: a shot would reveal the ship
                out.update(defend=False, clear_path=False, rockets=False, launcher=False)
            if g['kind'] == 'die':                  # a quest that wants the ship destroyed: no flight, no fight back
                out.update(flee_hp=0, resume_hp=5, defend=False, clear_path=False)
        return out

    def safety(self, s, cfg, now):
        act = self.act
        if self.mode not in ('flee', 'repair'):
            self.mode = 'flee'
            self.note('Low HP ({0} %): going to a safe zone.', int(B.hp_pct(s)))
        self.drop_target()
        self.normal_ammo()
        if s['in_peace']:
            self.mode = 'repair'
            if not act.repair(now) and not act.can_heal(now):
                self.reason = 'no_repair_robot'
            return
        p = B.safe_point(s)
        if p is None:                               # no safe zone on this map: away from the aliens, repair once nothing attacks
            p = B.away_point(s, cfg)
            if p is None:
                self.mode = 'repair'
                if not act.repair(now) and not act.can_heal(now):
                    self.reason = 'no_repair_robot'
                return
            if self.no_shelter != s['map']:
                self.no_shelter = s['map']
                self.note('No safe zone on this map: flying away from the aliens.')
        act.move_to(p[0], p[1], now)

    def track_target(self, s, it, d, now):
        """The target lost no HP / shield for stuck_sec while in range (out of range or in a safe zone the clock waits): it is left alone
        for IGNORE_SEC -> whether it was dropped."""
        sec = self.cfg['stuck_sec']
        hp = it['hp'] + it.get('shield', 0)
        t = self.track
        if t is None or t[0] != it['id'] or hp < t[1] or d > s['R'] * 1.15 or s['in_peace']:
            self.track = (it['id'], hp if t is None or t[0] != it['id'] else min(hp, t[1]), now)
            return False
        if not sec or now - t[2] < sec:
            return False
        self.ignored[it['id']] = now + IGNORE_SEC
        self.track = None
        self.note('{0} took no damage for {1} s: left alone for a while.', it['name'], sec)
        self.drop_target()
        return True

    def track_box(self, h, d, now):
        """Flying to the same box for BOX_SEC without getting closer (d: its distance): the box is skipped -> whether it was."""
        if self.box_track is None or self.box_track[0] != h or d < self.box_track[2] - BOX_PROGRESS:
            self.box_track = (h, now, d)
            return False
        if now - self.box_track[1] < BOX_SEC:
            return False
        self.box_ignored[h] = now + BOX_IGNORE_SEC
        self.box_track = None
        self.note('Could not take a box: skipped.')
        return True

    def fight_or_collect(self, s, cfg, now):
        """The mode's errand (going home, the gate trip, selling, quest giver, another map) takes the ship before any new target or box.
        On the way (clear_path off, the default) the ship keeps going and leaves the aliens behind at the portal; with clear_path the
        aggressive aliens attacking it or about to engage it are destroyed first. Off an errand, the aliens attacking the ship are fought
        back (defend), then come the mode's targets and boxes."""
        act = self.act
        if self.target is not None and not act.target_alive(self.target):
            self.target = None
        if act.w.opening and act.w.opening['h'] in act.w.boxes:
            self.mode = 'box'                       # a booty box is opening: stay on it for the opening time (moving off cancels it)
            return

        def errand():
            label = MODES.goal(self, s, now)
            self.errand = label or ''
            if label:
                self.drop_target()
                self.mode = label
            return bool(label) or not self.cfg['enabled']

        def hunt():
            return B.decide(s, cfg, self.target, hunt=MODES.allows(self, 'hunt'), boxes=MODES.allows(self, 'boxes'), defend=cfg['defend'])

        if not cfg['clear_path']:
            if errand():
                return
            kind, it = hunt()
        else:
            on_way = bool(self.errand)              # the last step's errand: on the way, the aggressive aliens first
            kind, it = B.decide(s, cfg, self.target, hunt=False, boxes=False, defend=cfg['defend'] or on_way)
            if kind != 'fight' and on_way:
                a = B.pick_aggressive(s, cfg)
                if a is not None:
                    kind, it = 'fight', a
            if kind != 'fight':
                if errand():
                    return
                kind, it = hunt()
        if kind == 'fight':
            hx, hy = s['hero']
            d = B.dist(hx, hy, it['x'], it['y'])
            if self.track_target(s, it, d, now):
                return
            TRAVEL.busy(self)
            self.box_track = None
            self.mode, self.target = 'fight', it['id']
            shot = B.defend_shot(s, cfg, it, self.shot, cfg['defend'])    # the main target out of range: an attacker in range meanwhile
            leech = self.sab_target(s, cfg, it)
            if leech is not None:                   # SAB-50: the main target in range while it has shield, else a shielded attacker in range
                if leech['id'] != it['id']:
                    self.track = None               # the main target takes no damage meanwhile: not a stuck target
                fire = leech
                self.sab_ammo()
            else:
                fire = shot
                self.leave_sab()
            self.shot = fire['id']
            act.attack(fire['id'])
            if not LURE.run(self, s, cfg, it, now):     # deep in an immobile alien's zone: drawn out of it first
                p = B.kite_point(s, cfg, it, B.threats(s, cfg, it['id']))    # the ship flies to the main target
                if p:
                    act.move_to(p[0], p[1], now)
            if leech is None and not self.sab_low:  # SAB-50 phase: no RSB-75 / RCB-140 until the shield is back up
                self.slow_ammo(B.dist(hx, hy, fire['x'], fire['y']) <= s['R'], now)
            if cfg['rockets']:
                act.fire_rocket(it['id'], d, now)
            if cfg['launcher'] and d <= s['R']:
                act.fire_launcher(it['id'], now)
            self.view['target'] = dict(id=it['id'], tip=it['tip'], name=it['name'], hp=it['hp'], hp_max=it['hp_max'], shield=it.get('shield', 0),
                                       shield_max=it.get('shield_max', 0), dist=int(d), range=int(s['R']))
            return
        self.drop_target()
        self.leave_sab()
        self.track = None
        if kind == 'box':
            if self.track_box(it['hash'], B.dist(*s['hero'], it['x'], it['y']), now):
                return
            TRAVEL.busy(self)
            self.mode = 'box'
            act.collect(it['hash'], now)               # flies onto the box, takes it there
            return
        self.box_track = None
        qg = self.quest_goal if MODES.current(self) == 'quest' else None
        playing = MODES.current(self) == 'gate' or (qg and qg['kind'] in ('gate', 'egate'))
        g = act.gate_portal() if playing else None      # Galaxy gate mode or a quest's gate: in another mode the player picks
        if g is not None:                           # galaxy gate, wave over: on to the next wave
            if self.mode != 'gate':
                self.note('Wave cleared: going to the next wave portal.')
            self.mode = 'gate'
            if not act.jump_from(g):
                act.move_to(g['x'], g['y'], now)
            return
        if ECON.harvest(self, s, cfg, now):
            TRAVEL.busy(self)
            self.mode = 'ore'
            return
        if TRAVEL.idle(self, s, now):
            self.errand = 'travel'
            return
        if cfg['roam'] and MODES.allows(self, 'roam'):
            if self.mode != 'roam' or not act.flying(now):
                p = B.roam_point(s, cfg)
                if p:
                    act.move_to(p[0], p[1], now)
            self.mode = 'roam'
        else:
            self.mode = 'idle'

    def slow_ammo(self, in_range, now):
        """RSB-75 / RCB-140 (pilot.json slow_ammo): selected as soon as their cooldown ends while the target is in range (the server
        fires them at once on selection, World.slow_ammo_shot), then back to the normal ammo for the next 3 s."""
        act = self.act
        cur = act.laser_ammo()
        if cur not in C.SLOW_AMMO:
            self.base_ammo = cur
            if in_range:
                for loot in self.cfg['slow_ammo']:
                    if act.slow_ready(loot, now):
                        act.set_ammo(loot)
                        return
        elif act.slow_fired(cur, now) or cur not in self.cfg['slow_ammo']:
            self.normal_ammo()

    def sab_target(self, s, cfg, it):
        """SAB-50 (pilot.json sab): once the ship's shield falls below start_pct and until it is back to stop_pct, the alien to drain ->
        the main target while it has shield (within laser range), else the nearest alien attacking the ship within laser range that has
        shield; None: the normal fight (the option is off, the ship has no shield, no SAB-50 in stock, or no shielded alien around)."""
        c = cfg['sab']
        if not c['enabled'] or not s['shield_max'] or not self.act.has_ammo(C.SAB_AMMO):
            self.sab_low = False
            return None
        pct = 100.0 * s['shield'] / s['shield_max']
        if pct < c['start_pct'] and not self.sab_low:
            self.sab_low = True
            self.note('Shield low ({0} %): SAB-50 on the shielded aliens.', int(pct))
        elif pct >= c['stop_pct'] and self.sab_low:
            self.sab_low = False
            self.note('Shield back to {0} %: normal ammo.', int(pct))
        if not self.sab_low:
            return None
        hx, hy = s['hero']
        if it.get('shield', 0) > 0 and B.dist(hx, hy, it['x'], it['y']) <= s['R']:
            return it
        ignore = cfg.get('ignore') or ()
        near = [n for n in s['npcs'] if n['ok'] and n['engaged'] and n.get('shield', 0) > 0 and n['id'] not in ignore
                and not n.get('forbidden') and B.dist(hx, hy, n['x'], n['y']) <= s['R']]
        return B.nearest(near, hx, hy)

    def sab_ammo(self):
        """SAB-50 selected, remembering the normal ammo to come back to (not an RSB-75 / RCB-140 shot)."""
        act = self.act
        cur = act.laser_ammo()
        if cur == C.SAB_AMMO:
            return
        if self.sab_prev is None:
            self.sab_prev = self.base_ammo if cur in C.SLOW_AMMO or not cur else cur
        act.set_ammo(C.SAB_AMMO)

    def leave_sab(self):
        """Back from SAB-50 to the ammo selected before it (else the setting's), if the bot chose it."""
        act = self.act
        prev, self.sab_prev = self.sab_prev, None
        if act is None or prev is None or act.laser_ammo() != C.SAB_AMMO:
            return
        for loot in (prev, self.cfg['laser_ammo']):
            if loot and loot != C.SAB_AMMO and act.has_ammo(loot):
                act.set_ammo(loot)
                return

    def normal_ammo(self):
        """Back from SAB-50, RSB-75 / RCB-140 to the normal ammo (the one selected before, else the setting's)."""
        act = self.act
        self.leave_sab()
        if act is None or act.laser_ammo() not in C.SLOW_AMMO:
            return
        for loot in (self.base_ammo, self.cfg['laser_ammo']):
            if loot not in C.SLOW_AMMO and act.has_ammo(loot):
                act.set_ammo(loot)
                return

    # ------------------------------------------------------------ status for the panel
    def status(self, now):
        w, act = self.world, self.act
        out = dict(updated=now, state=self.state if self.cfg['enabled'] else 'off', reason=self.reason, mode=self.mode,
                   pause_left=max(0, int(self.pause_until - now)) if self.reason == 'manual' else 0,
                   stats=self.stats.view(now), move_mode=self.cfg['move_mode'], map=None, map_aliens=[], errand=self.errand,
                   hunt_map=act.map_name(self.hunt_map) if act is not None and self.hunt_map else None, homing=self.homing,
                   quest=self.quest_goal and dict(name=self.quest_goal['name'], kind=self.quest_goal['kind']),
                   run_mode=MODES.current(self) if self.running else None, radar=None, **self.view)
        if w is not None and act is not None:
            try:
                with w.lock:
                    out.update(map=act.map_name(), map_id=act.map_id(), map_aliens=act.map_aliens(), **act.wallet(now))
                    out['radar'] = self.radar(now)
                    if now - self.catalog_at >= CATALOG_SEC or not self.catalog:
                        self.catalog_at = now
                        self.catalog = dict(maps=act.map_list(), gates=act.gates_catalog(), quests=act.active_quests(),
                                            **act.combat_catalog(), **act.economy_catalog())
            except Exception:
                self.log('   auto mode: status error\n%s' % traceback.format_exc())
        out['catalog'] = self.catalog
        return out

    def radar(self, now):
        """The live map with the ship's trail, the marks and what the bot is up to (its target, the portal and maps it heads for)."""
        r = self.act.radar(now, self.hunt_cfg(now))
        if r['map'] != self.trail_map:              # another map: its own trail and marks
            self.trail_map = r['map']
            self.trail.clear()
            self.marks.clear()
        x, y = r['hero']['x'], r['hero']['y']
        if not self.trail or math.hypot(x - self.trail[-1][0], y - self.trail[-1][1]) >= TRAIL_STEP:
            self.trail.append([x, y])
        r.update(trail=list(self.trail), marks=list(self.marks),
                 intent=dict(target=self.target, **self.act.heading(now)) if self.running else {})
        r['hero']['way'] = self.act.way(now) if self.running else None       # the corners left around the walls
        return r

    def _mtime(self):
        return C.mtime(self.cfg_path)
