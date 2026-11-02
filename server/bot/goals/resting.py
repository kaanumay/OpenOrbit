"""Resting: standing at base or in a safe place, chatting, "afk". Tired, low-ambition or social bots choose it; tiredness does not drop
(it grows with session time), boredom and anger fade."""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


@target
class Resting(Goal):
    name = 'resting'
    min_sec = 3600            # ends by finished(): the break's own length (playstyle.rest_minutes)

    def points(self, bot, b):
        o = bot.traits
        p = 0.06 + 0.5 * bot.mood['fatigue'] + 0.15 * (1 - o['ambition']) + 0.1 * o['sociability'] * bot.mood['boredom'] \
            + 0.2 * max(0.0, 0.4 - bot.mood['morale'])
        from .. import playstyle as PL
        st = PL.state(bot)
        since = b.now - st.get('rested', 0)
        fresh = b.now - (st.get('login') or 0) < 900 and not PL.has(bot, 'afk')     # nobody logs in to go AFK at once
        return p * (0.2 + 0.8 * min(1.0, since / 2400.0)) * (0.15 if fresh else 1.0)    # just had a break: not another one soon

    def start(self, bot, b):
        from .. import playstyle as PL
        bot.plan['until'] = b.now + PL.rest_minutes(bot) * 60
        PL.state(bot)['rested'] = b.now
        if bot.r.random() < 0.6:
            S.go(bot, K.ev(bot.company), b.y, b.now)

    def finished(self, bot, b):
        return b.now >= bot.plan.get('until', 0)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        bot.mood.it(boredom=-dt / 900.0, anger=-dt / 1200.0, morale=dt / 3600.0 * 0.2)
