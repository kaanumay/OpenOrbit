"""Dinlenme: üste ya da güvenli yerde durmak, sohbet etmek, "afk". Yorgun, hırsı az ya da sosyal botlar seçer; yorgunluk azalmaz
(oturum süresiyle artar), sıkılma ve öfke söner."""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


@target
class Resting(Goal):
    name = 'dinlenme'
    min_sec = 120

    def points(self, bot, b):
        o = bot.traits
        return 0.06 + 0.5 * bot.mood['yorgunluk'] + 0.15 * (1 - o['hirs']) + 0.1 * o['sosyallik'] * bot.mood['sikilma'] \
            + 0.2 * max(0.0, 0.4 - bot.mood['moral'])

    def start(self, bot, b):
        if bot.r.random() < 0.6:
            S.go(bot, K.ev(bot.firma), b.y, b.now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        bot.mood.it(sikilma=-dt / 900.0, ofke=-dt / 1200.0, moral=dt / 3600.0 * 0.2)
