"""Keşif: seviyesi yeni bir haritanın kapısını açınca oraya bir göz atmak (merak; sabırsız ve hırslı botlar daha çok)."""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


def new_maps(bot):
    seen = set(bot.k.get('gorulen', [])) | {bot.game_map}
    return [m for m in K.MAPS if m not in seen and K.can_enter(m, bot.firma, bot.level)
            and (K.H.company(m) in (None, bot.firma) or bot.o('risk') > 0.6)]


@target
class Exploration(Goal):
    name = 'kesif'
    min_sec = 60

    def eligible(self, bot, b):
        return bool(new_maps(bot))

    def points(self, bot, b):
        return 0.12 + 0.25 * (1 - bot.o('sabir')) + 0.15 * bot.o('hirs')

    def start(self, bot, b):
        maps = new_maps(bot)
        maps.sort(key=lambda m: len(K.route(bot.game_map, m, bot.firma, bot.level) or range(99)))
        bot.plan['harita'] = maps[0]
        if not S.go(bot, maps[0], b.y, b.now):
            bot.k.setdefault('gorulen', []).append(maps[0])
            bot.plan['bitti'] = True

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        S.farm(bot, dt, y)
        if bot.game_map == bot.plan.get('harita'):
            bot.plan.setdefault('vardi', 0)
            bot.plan['vardi'] += dt
            if bot.plan['vardi'] > 120:
                bot.plan['bitti'] = True

    def finished(self, bot, b):
        return bot.plan.get('bitti', False)
