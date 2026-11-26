"""Enemy players and player bots (pilot.json players). When one comes closer than `distance` (or, with attack_only, as soon as one fires at
the ship), the chosen reaction:
  flee  hide in the nearest safe zone (station, portal) until none has been seen for wait_sec (seen without a break for HIDE_MAX_SEC:
        the bot stops where it is); on a map with no safe zone for the player
        (another company's maps, like an enemy X-5) the bot carries on with its task (it fights back if attacked);
  map   avoid this map for avoid_min minutes and go to another of the mode's maps (no other map: flee);
  stop  stop the bot (where the ship is, or at the base with go_home);
  fight (fork) attack them: the enemy player bots become the targets (hunt_cfg pvp: act/players.pvp_targets, the game's own PvP rules)
        until none has been seen for wait_sec; the aliens wait meanwhile. Low HP still flees (safety). Players on a shared map (friend
        server) are not targeted: the bot only fights back against them."""
from .. import brain as B
from . import travel as TRAVEL

HIDE_MAX_SEC = 600            # enemy pilots seen without a break for this long while hiding: the bot stops ('players')


def run(pilot, s, now):
    """-> a label while the bot hides (it took the ship), else None."""
    c = pilot.cfg['players']
    g = pilot.quest_goal
    if not c['enabled'] or pilot.homing or (g and g['kind'] == 'pvp' and pilot.run_mode == 'quest'):
        return None                                 # a PvP quest: the enemy pilots are what the bot is after
    hx, hy = s['hero']
    near = [o for o in pilot.act.hostiles(now)
            if o['attacking'] or (not c['attack_only'] and B.dist(o['x'], o['y'], hx, hy) <= c['distance'])]
    if near:
        if now >= pilot.danger_until:
            pilot.note('Enemy pilot nearby: {0}.', ', '.join(sorted({o['name'] or '?' for o in near})))
        pilot.danger_until = now + c['wait_sec']
        action = c['action']
        if action == 'fight':
            pilot.fight_until = now + max(5, c['wait_sec'])
            return None
        if action == 'stop':
            pilot.stop('players')
            return 'hide'
        if action == 'map':
            pilot.unsafe[s['map']] = now + c['avoid_min'] * 60
            others = [m for m in TRAVEL.hunt_maps(pilot, now) if m != s['map']]
            if others:
                if pilot.hunt_map == s['map'] or pilot.hunt_map not in others:
                    pilot.hunt_map = others[0]
                    pilot.note('Leaving the map for {0}.', pilot.act.map_name(pilot.hunt_map))
                pilot.hide_since = None
                return None                         # the travel errand takes the ship away
        label = hide(pilot, s, now)
        if not label:
            pilot.hide_since = None
        elif pilot.hide_since is None:
            pilot.hide_since = now
        elif now - pilot.hide_since >= HIDE_MAX_SEC:        # an enemy camping by the safe zone: no endless hiding
            pilot.hide_since = None
            pilot.stop('players', home=False)
        return label
    pilot.hide_since = None
    if now < pilot.danger_until and c['action'] not in ('map', 'fight'):
        return hide(pilot, s, now)
    return None


def hide(pilot, s, now):
    """Into the nearest safe zone -> 'hide'; None when this map has none (the task goes on: user report, on an enemy X-5 a passing enemy
    bot sent the ship home in the middle of a quest)."""
    act = pilot.act
    if not s['in_peace'] and B.safe_point(s) is None:
        if pilot.no_shelter != s['map']:
            pilot.no_shelter = s['map']
            pilot.note('Enemy pilot nearby but no safe zone on this map: carrying on.')
        return None
    pilot.drop_target()
    if s['in_peace']:
        act.repair(now)
        return 'hide'
    p = B.safe_point(s)
    act.move_to(p[0], p[1], now)
    return 'hide'
