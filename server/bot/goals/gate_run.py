"""Kapı koşusu: kurulu Galaksi Kapısına girer, dalgaları bitirir (bot/galaxy_gates.py). Kapıdayken bot kapı haritasındadır (senin
haritandan kalkar); süre ve başarı gücünden; bitince ödül ve üsse dönüş."""
from ..brain import Goal, target
from .. import galaxy_gates as GT
from .. import catalog as K
from .. import abstract_sim as S


@target
class GateRun(Goal):
    name = 'gate'
    permission = 'gate'
    min_sec = 3600 * 3          # kapıdayken başka işe geçmez

    def eligible(self, bot, b):
        return bot.level >= 10 and GT.can_run(bot) is not None

    def points(self, bot, b):
        return 0.9 + 0.4 * bot.o('ambition') + 0.2 * bot.o('rekabet') - 0.5 * bot.mood['fatigue']

    def start(self, bot, b):
        k = GT.can_run(bot)
        success, duration = GT.run_result(bot, k, bot.r)
        bot.plan.update(gate=k, success=success, end_time=b.now + duration, sure=duration)
        game_map = GT.KAPI[k].get('map')
        if game_map:
            S.jump_to(bot, game_map, b.y)                    # kapı haritası: senin haritandan kalkar
        bot.event('entered_gate', gate=GT.KAPI[k]['name'])

    def abstract(self, bot, dt, y):
        if bot.plan.get('finished') or y.now < bot.plan.get('end_time', 0):
            return
        k = bot.plan.get('gate')
        st = GT.state(bot)
        if k in st['built']:
            st['built'].remove(k)
            st['part'].pop(k, None)
        if k == 'kronos':
            st['kronos'] = 0
        if bot.plan.get('success'):
            GT.grant_reward(bot, k, y.speed(bot))
            GT.record_duration(bot.k, k, bot.plan.get('sure') or 0)
        else:
            bot.ist('gate_lost')
            bot.event('gate_lost', gate=GT.KAPI[k]['name'])
        S.jump_to(bot, K.ev(bot.firma), y)                 # kapının çıkışı: X-1
        bot.plan['finished'] = True

    def concrete(self, bot, g, w, now):
        return False

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
