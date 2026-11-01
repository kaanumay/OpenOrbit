"""Exploration: when its level opens the gate to a new map, taking a look there (curiosity; impatient and ambitious bots more)."""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


def new_maps(bot):
    seen = set(bot.k.get('seen', [])) | {bot.game_map}
    return [m for m in K.MAPS if m not in seen and K.can_enter(m, bot.firma, bot.level)
            and (K.H.company(m) in (None, bot.firma) or bot.o('risk') > 0.6)]


@target
class Exploration(Goal):
    name = 'exploring'
    min_sec = 60

    def eligible(self, bot, b):
        return bool(new_maps(bot))

    def points(self, bot, b):
        return 0.12 + 0.25 * (1 - bot.o('patience')) + 0.15 * bot.o('ambition')

    def start(self, bot, b):
        maps = new_maps(bot)
        maps.sort(key=lambda m: len(K.route(bot.game_map, m, bot.firma, bot.level) or range(99)))
        bot.plan['map'] = maps[0]
        if not S.go(bot, maps[0], b.y, b.now):
            bot.k.setdefault('seen', []).append(maps[0])
            bot.plan['finished'] = True

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        S.farm(bot, dt, y)
        if bot.game_map == bot.plan.get('map'):
            bot.plan.setdefault('arrived', 0)
            bot.plan['arrived'] += dt
            if bot.plan['arrived'] > 120:
                bot.plan['finished'] = True

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
