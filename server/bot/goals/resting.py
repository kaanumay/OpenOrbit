"""Resting: standing at base or in a safe place, chatting, "afk". Tired, low-ambition or social bots choose it; tiredness does not drop
(it grows with session time), boredom and anger fade."""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


@target
class Resting(Goal):
    name = 'resting'
    min_sec = 120

    def points(self, bot, b):
        o = bot.traits
        return 0.06 + 0.5 * bot.mood['fatigue'] + 0.15 * (1 - o['ambition']) + 0.1 * o['sociability'] * bot.mood['boredom'] \
            + 0.2 * max(0.0, 0.4 - bot.mood['morale'])

    def start(self, bot, b):
        if bot.r.random() < 0.6:
            S.go(bot, K.ev(bot.company), b.y, b.now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        bot.mood.it(boredom=-dt / 900.0, anger=-dt / 1200.0, morale=dt / 3600.0 * 0.2)
