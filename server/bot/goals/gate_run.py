"""Kapı koşusu: kurulu Galaksi Kapısına girer, dalgaları bitirir (bot/galaxy_gates.py). Kapıdayken bot kapı haritasındadır (senin
haritandan kalkar); süre ve başarı gücünden; bitince ödül ve üsse dönüş."""
from ..brain import Goal, target
from .. import galaxy_gates as GT
from .. import catalog as K
from .. import abstract_sim as S


@target
class GateRun(Goal):
    name = 'kapi'
    permission = 'kapi'
    min_sec = 3600 * 3          # kapıdayken başka işe geçmez

    def eligible(self, bot, b):
        return bot.level >= 10 and GT.can_run(bot) is not None

    def points(self, bot, b):
        return 0.9 + 0.4 * bot.o('hirs') + 0.2 * bot.o('rekabet') - 0.5 * bot.mood['yorgunluk']

    def start(self, bot, b):
        k = GT.can_run(bot)
        success, duration = GT.run_result(bot, k, bot.r)
        bot.plan.update(kapi=k, basari=success, bitis=b.now + duration, sure=duration)
        game_map = GT.KAPI[k].get('harita')
        if game_map:
            S.jump_to(bot, game_map, b.y)                    # kapı haritası: senin haritandan kalkar
        bot.event('kapiya_girdi', kapi=GT.KAPI[k]['ad'])

    def abstract(self, bot, dt, y):
        if bot.plan.get('bitti') or y.now < bot.plan.get('bitis', 0):
            return
        k = bot.plan.get('kapi')
        st = GT.state(bot)
        if k in st['kurulu']:
            st['kurulu'].remove(k)
            st['parca'].pop(k, None)
        if k == 'kronos':
            st['kronos'] = 0
        if bot.plan.get('basari'):
            GT.grant_reward(bot, k, y.speed(bot))
            GT.record_duration(bot.k, k, bot.plan.get('sure') or 0)
        else:
            bot.ist('kapi_kayip')
            bot.event('kapi_kaybetti', kapi=GT.KAPI[k]['ad'])
        S.jump_to(bot, K.ev(bot.firma), y)                 # kapının çıkışı: X-1
        bot.plan['bitti'] = True

    def concrete(self, bot, g, w, now):
        return False

    def finished(self, bot, b):
        return bot.plan.get('bitti', False)
