"""Uzaylı kasma: gücüne ve kişiliğine en uygun haritaya gidip orada uzaylı öldürmek (oyunun ana döngüsü)."""
from ..brain import Goal, target
from .. import personality as PS
from .. import abstract_sim as S


@target
class Farming(Goal):
    name = 'kasilma'
    min_sec = 300

    def eligible(self, bot, b):
        return bool(b.game_map)

    def points(self, bot, b):
        o = bot.traits
        p = 0.35 + 0.35 * o['hirs'] + 0.25 * o['sabir'] + (0.2 if bot.archetype == 'kasici' else 0)
        from .. import weapons as WP
        if not WP.has_laser(bot):
            p *= 0.3                                      # cephanesiz: yalnız bonus kutusu toplayabilir (önce kargo satar, dinlenir)
        return p * (1 - 0.5 * bot.mood['yorgunluk']) * (1 - 0.3 * bot.mood['sikilma'])

    def start(self, bot, b):
        plan = (bot.k.get('intent') or {}).get('plan') or {}
        m = plan.get('harita')
        if not m:
            # ilk üç aday arasından faydaya göre: herkes aynı "en iyi" haritaya yığılmasın
            first = b.game_map[:3]
            peak = first[0][0] or 1
            m = PS.softmax_pick([(x[1], x[0] / peak) for x in first], 0.15, bot.r)
        bot.plan['harita'] = int(m)
        S.go(bot, m, b.y, b.now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        S.farm(bot, dt, y)

    def finished(self, bot, b):
        # haritası artık uygun değil (güç arttı ya da azaldı): ilk beşte değilse yeniden düşünsün
        m = bot.plan.get('harita')
        return bool(b.game_map) and m is not None and not bot.en_route and m not in [x[1] for x in b.game_map[:5]]
