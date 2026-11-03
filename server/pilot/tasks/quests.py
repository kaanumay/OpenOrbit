"""Quest mode (pilot.json quests): the active quests lead the bot (act/quests.py says what each condition asks: aliens to destroy on their
maps, a map to visit, a point to reach, a distance to fly, a time to spend, bonus boxes, an ore, any alien, the quest giver). Only a goal of
aliens hunts (kill: the quest's aliens and nothing else; grind: the Hunt list of the map); every other goal only fights back. With accept,
when no active quest can be played and a slot is free, the bot flies to a quest giver and takes the highest-level quest it can play. When no
quest can be played nor taken, the mode ends (Pilot.mode_end: its 'then', stop or another mode).
A chosen quest (quests.qid; 0: automatic) is the only one played, no other is taken; when it is done (or no longer accepted, or cannot be
played) the mode ends the same way."""

REFRESH_SEC = 1.0             # the quests are read again this often (a condition done: its aliens are not hunted a moment longer)
BLOCK_SEC = 300.0             # no quest to take at the giver: not asked again for this long
HANDED_SEC = 10.0             # after handing a quest in, before the next look at the giver
HUNTS = ('kill', 'grind', 'pvp')     # the goals that take new targets (inside a galaxy gate every goal fights its waves)
PALLADIUM = 8
ASSET_OUT = 700               # the quest counts an arrival within 500 of the object
RADIATION_OUT = 300           # this far past a map edge the ship is in the radiation zone (World.radiation: outside the map)


def clear(pilot):
    pilot.quest_goal = pilot.quest_maps = pilot.quest_aliens = None
    pilot.quest_rules = None


def update(pilot, now):
    """Every second: the quest's goal, its maps and aliens, the active quests' restrictions."""
    from . import modes as MODES
    if MODES.current(pilot) != 'quest':
        clear(pilot)
        return
    if pilot.homing or now - pilot.quest_at < REFRESH_SEC:
        return
    pilot.quest_at = now
    qid = pilot.cfg['quests']['qid']
    if qid and not pilot.act.quest_active(qid):          # the chosen quest is done (or was cancelled, or failed)
        done = pilot.act.quest_done(qid) or qid in pilot.quests_finished      # a challenge done goes to its score, not the done list
        clear(pilot)
        pilot.mode_end('quest_done' if done else 'quest_gone')
        return
    pilot.quest_skip = {k: t for k, t in pilot.quest_skip.items() if t > now}
    g = pilot.act.quest_goal(qid or None, now, pilot.quest_skip)
    old = pilot.quest_goal
    if (g and (g['qid'], g['cid'])) != (old and (old['qid'], old['cid'])):
        if g:
            pilot.note('Quest: {0} ({1}).', g['name'], 'q_' + g['kind'])
        else:
            pilot.note('No quest to play.')
        pilot.drop_target(only_ours=True)               # the last goal's target is not this one's
    if (g and (g['qid'], g['cid'])) != (old and (old['qid'], old['cid'])):
        pilot.asset_out = False
    pilot.quest_goal = g
    pilot.quest_rules = pilot.act.rules()
    if g is None:
        pilot.quest_maps = pilot.quest_aliens = None
        return
    pilot.quest_maps = g['maps'] or (pilot.cfg['travel']['maps'] if g['kind'] == 'grind' else None)
    pilot.quest_aliens = g.get('by_map') if g['kind'] == 'kill' else None


def hunts(pilot):
    g = pilot.quest_goal
    return bool(g) and g['kind'] in HUNTS and not (pilot.quest_rules or {}).get('no_laser')


def aliens(pilot, map_id):
    """The aliens the quest hunts on this map: its kill conditions' (on one of their maps; elsewhere the goal's), [] for any alien
    (grind: the Hunt list of the map, empty: all)."""
    g = pilot.quest_goal
    if g['kind'] == 'kill':
        return (pilot.quest_aliens or {}).get(map_id) or g['aliens']
    return pilot.cfg['aliens'].get(str(map_id), [])


def goal(pilot, s, now):
    """Going to a quest giver (to hand a quest in, or to take a new one) or to the quest's point -> a label while on the way."""
    c = pilot.cfg['quests']
    if now < pilot.quest_block or not pilot.quest_at:
        return None
    g, act = pilot.quest_goal, pilot.act
    if g is not None and g['kind'] in STEPS:
        return STEPS[g['kind']](pilot, s, g, now)
    if g is not None and g['sell']:
        label = sell(pilot, s, g, now)
        if label:
            return label
    hand_in = bool(g) and g['kind'] == 'giver'
    if g is None and (not c['accept'] or c['qid'] or act.quest_slots() <= 0):      # a chosen quest: no other is taken
        pilot.mode_end('no_quest')                  # nothing to play and nothing to take
        return 'quest'
    if not hand_in and g is not None:
        return None
    st = act.go_to_giver(now)
    if st == 'no_route':
        pilot.quest_block = now + BLOCK_SEC
        if not hand_in:
            pilot.mode_end('no_quest')
        return None
    if st != 'here':
        return 'quest'
    if hand_in:
        act.hand_in()
        pilot.note('Quest handed in: {0}.', g['name'])
        pilot.quest_block = now + HANDED_SEC
    else:
        qid = act.accept_quest()
        if qid:
            pilot.note('Quest taken: {0}.', act.quest_name(qid))
        else:
            pilot.note('No quest to take here.')
            pilot.quest_block = now + BLOCK_SEC
            pilot.mode_end('no_quest')
    pilot.quest_at = 0.0                            # read the quests again at once
    return None


def skip(pilot, g, now, sec=BLOCK_SEC):
    """The goal's step cannot be played for now (a gate that cannot be built, a portal refused ...): the other steps and quests go first."""
    pilot.quest_skip[(g['qid'], g['cid'])] = now + sec
    pilot.quest_at = 0.0


def gate(pilot, s, g, now):
    """A galaxy gate to finish, or the aliens only a gate has: the gate's run (tasks/gates.run; built with the Galaxy gate settings' spin
    budget) -> its label, or None inside."""
    from . import gates as GATES
    if pilot.gate_done and not pilot.act.in_gate():
        pilot.gate_done = False
    return GATES.run(pilot, s, now, g['gate'], lambda reason: skip(pilot, g, now))


def ore(pilot, s, g, now):
    """An ore goal: its ores refined as they come (Shop.refine), loaded into a part at once for an upgrade quest; Palladium filling the
    cargo goes to the 5-2 trader -> 'quest_trade' on the way there, else None (the harvest and the cargo sale of the mode)."""
    act = pilot.act
    if g['refine'] is not None:
        act.refine(g['refine'])
    if g['upgrade'] is not None and act.p.ore_count(g['ore']) > 0:
        act.ore_upgrade(g['upgrade'], g['ore'], g['need'])
        pilot.quest_at = 0.0
        return None
    if g['sell']:
        return sell(pilot, s, g, now)
    if g['ore'] != PALLADIUM or act.cargo_free() >= 1:
        return None
    st = act.trade_palladium(now)
    if st == 'no_route':
        skip(pilot, g, now)
        return None
    return None if st == 'here' else 'quest_trade'


def sell(pilot, s, g, now):
    """A sale quest: once the cargo holds what is left to sell (or is full), to the station (Palladium: the 5-2 trader) -> a label on the
    way, else None."""
    act = pilot.act
    ore = g['ore']
    have = act.p.ore_count(ore) if ore is not None else sum(act.ore_counts().values())
    if have <= 0 or (have < g['need'] and act.cargo_free() >= 1):
        return None
    if ore == PALLADIUM:
        st = act.trade_palladium(now)
    else:
        st = act.go_to_station(now, act.sell_maps())
        if st == 'here':
            act.sell_all()
    if st == 'no_route':
        skip(pilot, g, now)
        return None
    if st == 'here':
        pilot.quest_at = 0.0
        return None
    return 'sell'


def action(pilot, s, g, now):
    """A one-off action of the quest (laboratory upgrade, slot bar, Skylab, Assembly): done in place, not more than once a second."""
    if now - pilot.act_at < 1.0:
        return None
    pilot.act_at = now
    a, act = g['action'], pilot.act
    if a[0] == 'upgrade':
        act.ore_upgrade(a[1], a[2], g['need'])
    elif a[0] == 'slot':
        act.slot_put(a[1], a[2])
    elif a[0] == 'skylab':
        act.skylab_up(a[1], a[2])
    elif a[0] == 'craft' and act.craft(a[1], 1, now) == 'no':
        skip(pilot, g, now)
    pilot.quest_at = 0.0
    return None


def asset(pilot, s, g, now):
    """Fly to a station object (hangar, repair station ...): the quest counts the arrival within 500, so from outside that radius."""
    if s['map'] not in g['maps']:
        return None
    spot = pilot.act.asset_spot(g['action'])
    if spot is None:
        skip(pilot, g, now)
        return None
    hx, hy = s['hero']
    d = ((hx - spot[0]) ** 2 + (hy - spot[1]) ** 2) ** 0.5
    if d > ASSET_OUT:
        pilot.asset_out = True
    if not pilot.asset_out:                         # already next to it: out first, then in
        pilot.act.move_to(spot[0] + ASSET_OUT + 300, spot[1], now)
    else:
        pilot.act.move_to(spot[0], spot[1], now)
    return 'quest_point'


def egate(pilot, s, g, now):
    """The starter gate (an event gate whose portal is on X-1 while its quest runs): in through its portal, the waves inside."""
    act = pilot.act
    if act.in_gate():
        return None
    if s['map'] not in g['maps']:
        return None
    portal = act.event_gate_portal(g['gate'])
    if portal is None:
        skip(pilot, g, now)
        return None
    act.enter_portal(portal, now)
    return 'gate_trip'


def die(pilot, s, g, now):
    """A quest that wants the ship destroyed on a map: into the radiation zone in a corner of the map (no flight, no fight back)."""
    if g['maps'] and s['map'] not in g['maps']:
        return None
    pilot.act.move_to(-RADIATION_OUT, -RADIATION_OUT, now, outside=True)
    return 'quest_point'


def mine(pilot, s, g, now):
    """Lay mines: one where the ship is, then a little further for the next (mines do not stack)."""
    if g['maps'] and s['map'] not in g['maps']:
        return None
    act = pilot.act
    if act.lay_mine(now):
        pilot.quest_at = 0.0
    elif not act.flying(now):
        hx, hy = s['hero']
        act.move_to(hx + 400 if hx < s['bounds'][0] / 2 else hx - 400, hy, now)
    return 'quest_point'


def radiation(pilot, s, g, now):
    """A distance to fly in the radiation zone: along the map's edge, from one corner to the other (the flee threshold still applies)."""
    if g['maps'] and s['map'] not in g['maps']:
        return None
    act = pilot.act
    if not act.flying(now):
        hy, h = s['hero'][1], s['bounds'][1]
        act.move_to(-RADIATION_OUT, h - RADIATION_OUT if hy < h / 2 else RADIATION_OUT, now, outside=True)
    return 'quest_point'


def travel(pilot, s, g, now):
    """A distance to fly: in the radiation zone along the edge, cloaked (the cloak CPU; no shot, it would reveal the ship), else the
    patrol of the mode."""
    if g['radiation']:
        return radiation(pilot, s, g, now)
    if g['hidden'] and (not g['maps'] or s['map'] in g['maps']) and not pilot.act.p.d.get('cpu_hidden'):
        pilot.act.w.items.cloak(now)
    return None


def point(pilot, s, g, now):
    """A coordinate to reach: on its map, onto the point (the quest counts it within its radius, once a second) -> 'quest_point', or None
    off the map (the mode's travel takes the ship there)."""
    if s['map'] not in g['maps']:
        return None
    x, y, r = g['point']
    hx, hy = s['hero']
    if (hx - x) ** 2 + (hy - y) ** 2 > (r * 0.5) ** 2:
        pilot.act.move_to(x, y, now)
    return 'quest_point'


STEPS = {'point': point, 'ore': ore, 'gate': gate, 'act': action, 'asset': asset, 'egate': egate, 'die': die, 'mine': mine,
         'travel': travel}
