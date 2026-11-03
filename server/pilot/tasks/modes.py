"""Operating modes (pilot.json mode): what the bot is there for. One at a time; the shared features (safety, abilities and P.E.T., ammo
resupply, enemy pilots, after a death, stop conditions) run in every mode.
  hunt    hunts the chosen aliens on the Hunt maps (travel), collects boxes; ore between fights and selling if the ore block says so
  gate    a galaxy gate end to end (tasks/gates.py); off the gate map it does not hunt, it only fights back
  quest   the active quests lead the bot (tasks/quests.py): their aliens, maps, points, ore, the quest giver; it hunts only for them
  mining  harvests the chosen ores on the Mining maps and sells the cargo at the base; it does not hunt, it only fights back
A mode with nothing left to do (gate done / not built / out of lives, no quest to play) goes on with its 'then' setting: stop, or another
mode (Pilot.mode_end; the running mode is Pilot.run_mode, the chosen one stays in the settings). Inside any gate map the waves are fought."""
from . import economy as ECON, gates as GATES, quests as QUESTS, stop as STOP, travel as TRAVEL

NAMES = {'hunt': 'Hunt', 'gate': 'Galaxy gate', 'quest': 'Quests', 'mining': 'Mining'}
THEN_BLOCK = {'gate': 'gates', 'quest': 'quests'}         # the modes that can end, and where their 'then' is


def current(pilot):
    return pilot.run_mode or pilot.cfg['mode']


def allows(pilot, what):
    """What the running mode lets the bot do: hunt (new targets), boxes, harvest, sell, roam."""
    if pilot.act.in_gate():
        return what in ('hunt', 'boxes', 'roam')            # a gate / mode map: its waves
    m, c = current(pilot), pilot.cfg
    if m == 'hunt':
        return what in ('hunt', 'boxes', 'roam') or (what == 'harvest' and c['ore']['harvest']) or (what == 'sell' and c['ore']['sell'])
    if m == 'quest':                                        # only a goal of aliens hunts; an ore goal harvests and sells, cargo boxes sell
        g = pilot.quest_goal
        return (what in ('boxes', 'roam') or (what == 'hunt' and QUESTS.hunts(pilot))
                or (what == 'harvest' and bool(g) and g['kind'] == 'ore')
                or (what == 'sell' and bool(g) and (g['kind'] == 'ore' or g['box'] == 'cargo')))
    if m == 'mining':
        return what in ('harvest', 'sell', 'roam')
    return False                                            # gate mode off the gate map: only its trip


def ore_settings(pilot):
    """The ore settings of the running mode: Mining's own block, else Hunt's (ore); a quest's ore goal harvests only its ore."""
    m, g = current(pilot), pilot.quest_goal
    if m == 'quest' and g and g['kind'] == 'ore':
        return dict(pilot.cfg['ore'], types=g['harvest'] or [g['ore']])
    return pilot.cfg['mining'] if m == 'mining' else pilot.cfg['ore']


def maps(pilot, now):
    """The running mode's maps (in order), without the ones avoided for a while (enemy pilots) unless nothing else is left."""
    m, c = current(pilot), pilot.cfg
    start = [pilot.start_map] if pilot.start_map else []
    if m == 'hunt':
        out = c['travel']['maps'] or start
    elif m == 'quest':
        out = pilot.quest_maps or []
    elif m == 'mining':
        out = c['mining']['maps'] or start
    else:
        out = []
    ok = [x for x in out if pilot.unsafe.get(x, 0) <= now and pilot.act.can_enter(x)]
    return ok or [x for x in out if pilot.act.can_enter(x)]


def leave_empty_sec(pilot):
    m = current(pilot)
    return pilot.cfg['travel']['leave_empty_sec'] if m == 'hunt' else pilot.cfg['mining']['leave_empty_sec'] if m == 'mining' else 0


def goal(pilot, s, now):
    """The running mode's errand (it moves the ship) -> its label, or None."""
    if pilot.homing:
        return STOP.home(pilot, s, now)
    m = current(pilot)
    if m == 'gate':
        return GATES.goal(pilot, s, now)
    if pilot.act.in_gate():
        return None
    if allows(pilot, 'sell'):
        label = ECON.sell_goal(pilot, s, now)
        if label:
            return label
    if m == 'quest':
        label = QUESTS.goal(pilot, s, now)
        if label:
            return label
    return TRAVEL.goal(pilot, s, now)
