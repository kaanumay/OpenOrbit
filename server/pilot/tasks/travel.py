"""Travelling between the running mode's maps (tasks/modes.maps: Hunt's travel.maps, Mining's mining.maps, the quest's maps; empty: the
map where the bot started). Off the current map of the list the bot flies there through the portals (bot/catalog.route); when that map has
had nothing to do for the mode's leave_empty_sec it moves on to the next map of the list. A map marked unsafe (enemy pilots) is skipped until
its time is up."""

TRAVEL_LOG_SEC = 30


def hunt_maps(pilot, now):
    from . import modes as MODES
    return MODES.maps(pilot, now)


def goal(pilot, s, now):
    """Fly to the hunting map when the ship is elsewhere -> a label, or None when it is there (or there is no list / no route)."""
    maps = hunt_maps(pilot, now)
    if not maps:
        return None
    if pilot.hunt_map not in maps:
        pilot.hunt_map = s['map'] if s['map'] in maps else pilot.act.nearest_of(maps)
    if pilot.hunt_map is None or pilot.hunt_map == s['map']:
        return None
    st = pilot.act.travel_to(pilot.hunt_map, now)
    if st == 'no_route':
        pilot.note('No route to {0}: staying here.', pilot.act.map_name(pilot.hunt_map))
        pilot.hunt_map = s['map']
        return None
    if now - pilot.travel_logged >= TRAVEL_LOG_SEC:
        pilot.travel_logged = now
        pilot.note('Flying to {0}.', pilot.act.map_name(pilot.hunt_map))
    return 'travel'


def idle(pilot, s, now):
    """Nothing to do on this map: after the mode's leave_empty_sec, the next map of the list -> whether the bot moved on."""
    from . import modes as MODES
    wait = MODES.leave_empty_sec(pilot)
    maps = hunt_maps(pilot, now)
    if not wait or len(maps) < 2 or s['map'] not in maps:
        pilot.empty_since = None
        return False
    if pilot.empty_since is None:
        pilot.empty_since = now
        return False
    if now - pilot.empty_since < wait:
        return False
    pilot.empty_since = None
    pilot.hunt_map = maps[(maps.index(s['map']) + 1) % len(maps)]
    pilot.note('Nothing left to do here: on to {0}.', pilot.act.map_name(pilot.hunt_map))
    return True


def busy(pilot):
    """Something to hunt: the empty-map timer starts again."""
    pilot.empty_since = None
