"""Galaxy gates end to end (pilot.json gates): the chosen gate is built in the Galaxy Gate Generator when its parts are missing (spins:
the free energy first, then uridium within build_budget per session), prepared, lives are bought up to min_lives (within life_budget),
the ship flies to the gate's portal on X-1 and jumps in; inside, the waves are fought and the next wave's portal is taken
(system.fight_or_collect). After a death the bot repairs at the base (tasks/recover) and goes back in. When the gate is completed (or cannot
be played: not built, no life, no route) the mode ends (Pilot.mode_end: its 'then', stop or another mode); with repeat a completed gate
starts again (built again if build_budget allows).
Quests mode plays a gate the same way (run(): a quest asking to finish a gate, or to destroy aliens that only gates have); there a gate
that cannot be played only sets the quest's step aside.
leave_lives: once a death brings the gate's lives down to this, the bot does not go back in (the gate keeps its wave, lives and parts)
and the mode ends with its 'then' (another mode or stop) - a ship not strong enough for the gate does not burn every life.
Warning (the server's rule): when the last life is lost the gate and its parts are gone."""

SPINS = 100                   # spins asked at once (the generator's largest amount; it stops by itself once the gate is built)


def lives(pilot, key):
    """Buy lives up to min_lives -> whether the gate has at least one life."""
    c, act = pilot.cfg['gates'], pilot.act
    info = act.gate_info(key)
    while info and info['ready'] and info['lives'] < c['min_lives'] and info['lives_bought'] < info['max_bought']:
        price = info['life_price']
        if price < 0 or price > c['life_budget'] - pilot.stats['spent_uridium_gates'] or price > act.money('uridium'):
            break
        paid = act.gate_buy_life(key)
        if paid is None:
            break
        pilot.stats.add('spent_uridium', paid)
        pilot.stats.add('spent_uridium_gates', paid)
        pilot.note('{0}: life bought ({1} U).', info['name'], paid)
        info = act.gate_info(key)
    return bool(info) and info['lives'] > 0


def build_left(pilot):
    """Uridium left for gate spins in this session."""
    return max(0, pilot.cfg['gates']['build_budget'] - pilot.stats['spent_uridium_build'])


def build(pilot, key):
    """Spins in the generator until the gate is built, the free energy first, then uridium within build_budget -> whether it is built."""
    act = pilot.act
    info = act.gate_info(key)
    while info and not info['built'] and info['producible']:
        n = min(SPINS, info['energy'] + build_left(pilot) // max(1, info['spin_price']))
        if n <= 0 or (n > info['energy'] and act.money('uridium') < (n - info['energy']) * info['spin_price']):
            break
        paid = act.gate_spin(key, n)
        if paid is None:
            break
        pilot.stats.add('spent_uridium', paid)
        pilot.stats.add('spent_uridium_build', paid)
        info = act.gate_info(key)
        pilot.note('{0}: {1}/{2} parts ({3} U spent on spins).', info['name'], info['parts'], info['need'], paid)
    return bool(info) and info['built']


def can_build(pilot, key):
    """The gate is built, ready, or can be built with the spins the budget and the free energy allow (a rough check: at least one spin)."""
    info = pilot.act.gate_info(key)
    if not info:
        return False
    if info['ready'] or info['built']:
        return True
    return info['producible'] and (info['energy'] > 0 or build_left(pilot) >= info['spin_price'] <= pilot.act.money('uridium'))


def run(pilot, s, now, key, end):
    """One step toward gate `key`, off its map: build, prepare, buy lives, fly to the X-1 portal and jump -> a label (it took the ship) or
    None (inside: the waves). end(reason): the gate cannot be played (gate_none, gate_done, gate_not_built, gate_lives, gate_no_route)."""
    act = pilot.act
    if act.in_gate():
        if act.in_gate(key):
            lives(pilot, key)
        return None                                 # inside: the waves and the next wave's portal
    info = act.gate_info(key)
    if info is None:                                # a gate that no longer exists (World Editor) or no gate book
        end('gate_none')
        return 'gate_trip'
    if not info['ready']:
        if not info['built'] and not build(pilot, key):
            pilot.note('{0}: {1}/{2} parts, the gate cannot be prepared.', info['name'], act.gate_info(key)['parts'], info['need'])
            end('gate_not_built')
            return 'gate_trip'
        if not act.gate_prepare(key):
            end('gate_not_built')
            return 'gate_trip'
        pilot.note('{0} prepared.', info['name'])
    if not lives(pilot, key):
        end('gate_lives')
        return 'gate_trip'
    left = pilot.cfg['gates']['leave_lives']
    if left and act.gate_info(key)['lives'] <= left:      # too many deaths for this ship: the gate (and its parts) is kept for later
        end('gate_lives_low')
        return 'gate_trip'
    home = act.gate_home()
    if s['map'] != home:
        st = act.travel_to(home, now)
        if st == 'no_route':
            end('gate_no_route')
        return 'gate_trip'
    g = act.gate_entry(key)
    if g is None:                                   # prepared but no portal on X-1: the builder's PREPARE puts it back (Gates.setup)
        act.gate_prepare(key)
        g = act.gate_entry(key)
    if g is None:                                   # still none: the gate cannot be entered from here
        end('gate_no_route')
        return 'gate_trip'
    if act.enter_portal(g, now) == 'jumping':
        pilot.note('Entering the {0}.', info['name'])
    return 'gate_trip'


def goal(pilot, s, now):
    """Galaxy gate mode, off the gate map -> a label (it took the ship) or None."""
    key = pilot.cfg['gates']['key']
    if not key:
        pilot.mode_end('gate_none')
        return 'gate_trip'
    if pilot.gate_done and not pilot.act.in_gate():
        pilot.gate_done = False
        info = pilot.act.gate_info(key)
        if not pilot.cfg['gates']['repeat'] or info is None or not can_build(pilot, key):
            pilot.mode_end('gate_done')
            return 'gate_trip'
        pilot.note('{0} completed: playing it again.', info['name'])
    return run(pilot, s, now, key, pilot.mode_end)
