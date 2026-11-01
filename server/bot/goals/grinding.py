"""Alien grinding: go to the map that best fits its strength and personality and kill aliens there (the game's main loop)."""
from ..brain import Goal, target
from .. import personality as PS
from .. import abstract_sim as S


@target
class Farming(Goal):
    name = 'grinding'
    min_sec = 300

    def eligible(self, bot, b):
        return bool(b.game_map)

    def points(self, bot, b):
        o = bot.traits
        p = 0.35 + 0.35 * o['ambition'] + 0.25 * o['patience'] + (0.2 if bot.archetype == 'grinder' else 0)
        from .. import weapons as WP
        if not WP.has_laser(bot):
            p *= 0.3                                      # no ammo: can only collect bonus boxes (sells cargo first, rests)
        return p * (1 - 0.5 * bot.mood['fatigue']) * (1 - 0.3 * bot.mood['boredom'])

    def start(self, bot, b):
        plan = (bot.k.get('intent') or {}).get('plan') or {}
        m = plan.get('map')
        if not m:
            # by benefit among the first three candidates: so that everyone does not pile onto the same "best" map
            first = b.game_map[:3]
            peak = first[0][0] or 1
            m = PS.softmax_pick([(x[1], x[0] / peak) for x in first], 0.15, bot.r)
        bot.plan['map'] = int(m)
        S.go(bot, m, b.y, b.now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        S.farm(bot, dt, y)

    def finished(self, bot, b):
        # its map is no longer suitable (strength rose or fell): if not in the top five, it should reconsider
        m = bot.plan.get('map')
        return bool(b.game_map) and m is not None and not bot.en_route and m not in [x[1] for x in b.game_map[:5]]
