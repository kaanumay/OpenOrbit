"""Auto Mode: the server flies the player's own ship (fights aliens kiting at the edge of the laser range, collects boxes, flees to a safe
zone and repairs at low HP, hunts on a list of maps, comes back after a death, stops on its own conditions). The panel's Auto Mode page
(panel/pilot_panel.py, panel/ui/pilot.js) writes the settings to pilot.json next to the save slot's profile and reads the bot's status from
<log folder>/pilot_status.json; no other channel is needed.

Kept apart from the rest of the server (a local feature): the session adds it as an extra-events system (game.py, one line: ExtraEvents.add),
which gives attach(world) on every map load, tick(now) every second and event(kind, kw). On attach the bot
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
Activities (self.mode, the panel's status): fight, box, roam, idle, flee, repair, hide, ore, gate (next wave), and the errands travel, home,
sell, quest, gate_trip."""
import time, traceback

import paths as PTH

from . import act as A
from . import brain as B
from . import config as C
from .stats import Stats
from .tasks import economy as ECON, modes as MODES, players as PLAYERS, quests as QUESTS, recover as RECOVER, stop as STOP, support as SUPPORT
from .tasks import travel as TRAVEL

STEP = 0.25
CATALOG_SEC = 10              # the panel's lists (maps, owned items) are refreshed this often


class Pilot:
    def __init__(self, session, log=print):
        self.session, self.log = session, log
        self.p = session.profile
        self.cfg_path = C.path_for(self.p.path)
        self.status_file = C.status_path(PTH.LOGS)
        self.cfg, self.cfg_mtime = C.load(self.cfg_path), self._mtime()
        self.world = None
        self.act = None
        self.running = False            # enabled and started (the panel's Start)
        self.state, self.reason = 'off', ''
        self.stats = Stats()
        self.catalog, self.catalog_at = {}, 0.0
        self.cfg_mode = None            # the mode chosen in the settings when run_mode was set
        self.reset_run(0.0)

    def reset_run(self, now):
        """Everything one run of the bot (Start .. Stop) keeps."""
        self.mode = None                # the activity (see the module's docstring)
        self.target = None
        self.pause_until = 0.0
        self.view = {}                  # the last step's view for the status file (written outside the world lock)
        self.base_ammo = None           # the normal laser ammo to come back to after an RSB-75 / RCB-140 shot
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
        self.set_mode(None)

    def set_mode(self, mode):
        """The running mode (tasks/modes.py); what one mode keeps."""
        self.run_mode = mode
        self.errand = ''                # going somewhere (travel, home, sell, quest, gate_trip): see fight_or_collect
        self.hunt_map, self.empty_since, self.gate_done = None, None, False
        self.quest_goal = self.quest_maps = self.quest_aliens = None      # Quests mode: the quest's aliens and maps (tasks/quests.py)
        self.quest_at = self.quest_block = 0.0

    # ------------------------------------------------------------ extra-events hooks
    def attach(self, world):
        self.world = world
        self.act = A.Actions(world, self.cfg['move_mode'], self.session)
        self.target = None
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
        try:
            C.write_json(self.status_file, self.status(now))
        except OSError:
            pass
        return []

    def event(self, kind, kw):
        if self.running:
            self.stats.event(kind, kw)
            if kind == 'gate' and not kw.get('dispatch'):
                self.gate_done = True
                self.stats.add('gates')
        return []

    # ------------------------------------------------------------ helpers for the tasks
    def note(self, text):
        """A line in the server log and in the panel's journal."""
        self.log('   auto mode: %s' % text)
        self.stats.note(text)

    def drop_target(self, only_ours=False):
        """Stop firing. only_ours: only if the bot's own target is being fired at (a manual attack of the player stays)."""
        if self.target is not None and (not only_ours or self.act.attacking(self.target)):
            self.act.stop_attack()
        self.target = None

    def stop(self, reason, home=True):
        """Stop the bot on its own (a stop condition, death, a mode's end): with go_home it first flies to the base (tasks/stop.home)."""
        if not self.cfg['enabled']:
            return                                  # already stopped in this step: the first reason stays
        if home and reason != 'dead' and self.cfg['stop']['go_home']:
            if not self.homing:
                self.homing = reason
                self.note('stopping (%s): going to the base first' % reason)
            return                                  # on the way home: another reason does not cut the trip short
        self.homing = ''
        self.stats.d['stop_reason'] = reason
        self.note('stopped (%s)' % reason)
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
        self.note('%s: %s, now %s' % (MODES.NAMES[mode], reason.replace('_', ' '), MODES.NAMES[then]))
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
        if self.act.ours(f.get('targetX', 0), f.get('targetY', 0), now):
            return
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
        self.note('started: %s mode (%s)' % (MODES.NAMES[self.run_mode], self.cfg['move_mode']))

    def halt(self):
        self.running = False
        self.state, self.reason = 'off', ''
        self.drop_target(only_ours=True)
        self.normal_ammo()
        self.mode, self.homing, self.view = None, '', {}
        self.set_mode(None)
        if not self.stats['stop_reason']:
            self.note('stopped')

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
            self.note('%s mode' % MODES.NAMES[self.run_mode])
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
                self.target = act.player_target() or self.target      # the player picked a target by hand: keep it on resume
            return
        self.state, self.reason = 'running', ''
        if not self.homing:
            r = STOP.check(self, now)
            if r:
                self.stop(r)
        QUESTS.update(self, now)                    # Quests mode: the quest's aliens and maps (its end can stop the bot)
        if not self.cfg['enabled']:
            return
        hunt = self.hunt_cfg()
        s = act.snapshot(now, hunt)
        hp = B.hp_pct(s)
        SUPPORT.run(self, s, now)                   # abilities, technologies, config, P.E.T. (uses the last step's target)
        ECON.supply(self, now)                      # ammo resupply
        self.view = dict(hp=s['hp'], hp_max=s['hp_max'], target=None)
        label = PLAYERS.run(self, s, now)           # enemy pilots: hide / leave the map / stop
        if label:
            self.mode, self.errand = label, ''
            return
        if self.mode in ('flee', 'repair') or hp < cfg['flee_hp']:
            if hp >= cfg['resume_hp']:
                self.mode = None
                self.note('repaired, resuming')
            else:
                return self.safety(s, now)
        self.fight_or_collect(s, hunt, now)

    def hunt_cfg(self):
        """The settings with the aliens to hunt here: Quests mode, the active quest's; otherwise this map's list (empty: all)."""
        if self.quest_aliens:
            return dict(self.cfg, aliens=self.quest_aliens)
        return dict(self.cfg, aliens=self.cfg['aliens'].get(str(self.act.map_id()), []))

    def safety(self, s, now):
        act = self.act
        if self.mode not in ('flee', 'repair'):
            self.mode = 'flee'
            self.note('low HP (%d%%), going to a safe zone' % B.hp_pct(s))
        self.drop_target()
        self.normal_ammo()
        if s['in_peace'] or not s['safe']:
            self.mode = 'repair'
            if not act.repair(now) and not act.can_heal(now):
                self.reason = 'no_repair_robot'
            return
        p = B.safe_point(s)
        if p:
            act.move_to(p[0], p[1], now)

    def fight_or_collect(self, s, cfg, now):
        """The mode's errand (going home, the gate trip, selling, quest giver, another map) takes the ship before any new target or box.
        On the way (clear_path off, the default) the ship keeps going and leaves the aliens behind at the portal; with clear_path the
        aggressive aliens attacking it or about to engage it are destroyed first. Off an errand, the aliens attacking the ship are fought
        back (defend), then come the mode's targets and boxes."""
        act = self.act
        if self.target is not None and not act.target_alive(self.target):
            self.target = None

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
            TRAVEL.busy(self)
            self.mode, self.target = 'fight', it['id']
            act.attack(it['id'])
            p = B.kite_point(s, cfg, it, B.threats(s, cfg, it['id']))
            if p:
                act.move_to(p[0], p[1], now)
            hx, hy = s['hero']
            d = B.dist(hx, hy, it['x'], it['y'])
            self.slow_ammo(d <= s['R'], now)
            self.view['target'] = dict(name=it['name'], hp=it['hp'], hp_max=it['hp_max'], dist=int(d), range=int(s['R']))
            return
        self.drop_target()
        if kind == 'box':
            TRAVEL.busy(self)
            self.mode = 'box'
            act.collect(it['hash'])
            act.move_to(it['x'], it['y'], now)
            return
        g = act.gate_portal() if MODES.current(self) == 'gate' else None      # Galaxy gate mode only: in another mode the player picks
        if g is not None:                           # galaxy gate, wave over: on to the next wave
            if self.mode != 'gate':
                self.note('wave over, going to the next wave portal')
            self.mode = 'gate'
            if not act.jump_from(g):
                act.move_to(g['x'], g['y'], now)
            return
        if ECON.harvest(self, s, now):
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

    def normal_ammo(self):
        """Back from RSB-75 / RCB-140 to the normal ammo (the one selected before, else the setting's)."""
        act = self.act
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
                   stats=self.stats.view(), move_mode=self.cfg['move_mode'], map=None, map_aliens=[], errand=self.errand,
                   hunt_map=act.map_name(self.hunt_map) if act is not None and self.hunt_map else None, homing=self.homing,
                   quest=self.quest_goal and dict(name=self.quest_goal['name'], kind=self.quest_goal['kind']),
                   run_mode=MODES.current(self) if self.running else None, **self.view)
        if w is not None and act is not None:
            try:
                with w.lock:
                    out.update(map=act.map_name(), map_id=act.map_id(), map_aliens=act.map_aliens(), **act.wallet(now))
                    if now - self.catalog_at >= CATALOG_SEC or not self.catalog:
                        self.catalog_at = now
                        self.catalog = dict(maps=act.map_list(), gates=act.gates_catalog(), quests=act.active_quests(),
                                            **act.combat_catalog(), **act.economy_catalog())
            except Exception:
                self.log('   auto mode: status error\n%s' % traceback.format_exc())
        out['catalog'] = self.catalog
        return out

    def _mtime(self):
        return C.mtime(self.cfg_path)
