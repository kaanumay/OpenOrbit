"""Stop conditions (pilot.json stop): running time, aliens destroyed, the normal laser ammo running low. With go_home the ship first flies
to the company's station (the nearest of X-1 / X-8), then the bot stops."""
from . import economy as ECON


def check(pilot, now):
    """-> the reason to stop, or ''."""
    cfg = pilot.cfg['stop']
    st = pilot.stats
    if cfg['minutes'] and now - st['started'] >= cfg['minutes'] * 60:
        return 'time'
    if cfg['kills'] and st['kills'] >= cfg['kills']:
        return 'kills'
    if cfg['ammo_below']:
        ammo = pilot.base_ammo or pilot.cfg['laser_ammo'] or pilot.act.laser_ammo()
        if ammo and pilot.act.ammo_count(ammo) < cfg['ammo_below'] and not ECON.pending(pilot, ammo):
            return 'ammo'
    return ''


def home(pilot, s, now):
    """Going home before stopping -> a label while flying, or stops the bot once at the station."""
    st = pilot.act.go_to_station(now, pilot.act.sell_maps())
    if st in ('here', 'no_route'):
        pilot.stop(pilot.homing, home=False)
        return None
    return 'home'
