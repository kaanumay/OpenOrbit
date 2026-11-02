"""Galaxy gates end to end (pilot.json gates): the chosen gate is prepared when its parts are complete, lives are bought up to min_lives
(within the session's uridium budget), the ship flies to the gate's portal on X-1 and jumps in; inside, the waves are fought and the next
wave's portal is taken (system.fight_or_collect). After a death the bot repairs at the base (tasks/recover) and goes back in. When the gate
is completed (or cannot be played: not built, no life, no route) the mode ends (Pilot.mode_end: its 'then', stop or another mode); with
repeat a completed gate starts again if its parts are complete once more.
Warning (the server's rule): when the last life is lost the gate and its parts are gone."""


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
        pilot.note('%s: life bought (%d U)' % (info['name'], paid))
        info = act.gate_info(key)
    return bool(info) and info['lives'] > 0


def goal(pilot, s, now):
    """Galaxy gate mode, off the gate map: prepare, buy lives, fly to the X-1 portal and jump -> a label (it took the ship) or None."""
    key, act = pilot.cfg['gates']['key'], pilot.act
    if not key:
        pilot.note('Galaxy gate mode: no gate chosen')
        pilot.mode_end('gate_none')
        return 'gate_trip'
    if act.in_gate():
        if act.in_gate(key):
            lives(pilot, key)
        return None                                 # inside: the waves and the next wave's portal
    info = act.gate_info(key)
    if info is None:                                # a gate that no longer exists (World Editor) or no gate book
        pilot.mode_end('gate_none')
        return 'gate_trip'
    if pilot.gate_done:
        pilot.gate_done = False
        if not pilot.cfg['gates']['repeat'] or not info['built']:
            pilot.mode_end('gate_done')
            return 'gate_trip'
        pilot.note('%s completed: once more' % info['name'])
    if not info['ready']:
        if not info['built']:
            pilot.note('%s: parts %d/%d, the gate cannot be prepared' % (info['name'], info['parts'], info['need']))
            pilot.mode_end('gate_not_built')
            return 'gate_trip'
        if not act.gate_prepare(key):
            pilot.mode_end('gate_not_built')
            return 'gate_trip'
        pilot.note('%s prepared' % info['name'])
    if not lives(pilot, key):
        pilot.mode_end('gate_lives')
        return 'gate_trip'
    home = act.gate_home()
    if s['map'] != home:
        st = act.travel_to(home, now)
        if st == 'no_route':
            pilot.mode_end('gate_no_route')
        return 'gate_trip'
    g = act.gate_entry(key)
    if g is None:                                   # prepared but no portal on X-1: the builder's PREPARE puts it back (Gates.setup)
        act.gate_prepare(key)
        g = act.gate_entry(key)
    if g is None:                                   # still none: the gate cannot be entered from here
        pilot.mode_end('gate_no_route')
        return 'gate_trip'
    if act.enter_portal(g, now) == 'jumping':
        pilot.note('entering the %s' % info['name'])
    return 'gate_trip'
