"""Satış: kargo dolunca kendi istasyonuna (X-1 ya da X-8) dönüp cevherleri rafineriye satmak (oyunda ticaret yalnız istasyonda).

Ne zaman dolu sayıldığı kişiliğe bağlı: sabırlı ve tutumlu oyuncu ağzına kadar doldurur, aceleci yarısında döner. Somutta gemi
istasyona uçar, yanına varınca satar; soyutta istasyon haritasına varınca satar.
"""
import math

from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S

SELL_DISTANCE = 600


def threshold(bot):
    """Kargonun bu kadarı dolunca satmaya döner."""
    return min(1.0, 0.55 + 0.3 * bot.o('patience') + 0.15 * bot.o('frugality'))


def nearest_station(bot):
    """Satış haritalarından yolu en kısa olanı."""
    return min(K.sell_maps(bot.firma), key=lambda m: len(K.route(bot.game_map, m, bot.firma, bot.level) or range(99)))


def danger(bot, g, w, now):
    """Dolu kargoyla eve dönerken dövüşe döner mi: bir oyuncu ya da bot vuruyorsa ya da can yarının altındaysa. Uzaylıların
    tacizini umursamaz, uçmaya devam eder (canlı test 2026-10-29: 2-1'de saldırgan uzaylılar sırayla vurdukça istasyona hiç
    varamıyordu)."""
    last = [u for u, t in g.attacker.items() if now - t < 6]
    if any(u not in w.npcs or w.npcs[u].bot is not None for u in last):
        return True
    d = bot.value()
    return bool(last) and (g.hp + g.shield) / max(1, d['can'] + d['kalkan']) < 0.5


@target
class Selling(Goal):
    name = 'selling'
    permission = 'kargo'
    min_sec = 30

    def eligible(self, bot, b):
        return bot.cargo_fill() >= threshold(bot)

    def points(self, bot, b):
        return 0.6 + 1.2 * min(1.0, bot.cargo_fill()) + 0.2 * bot.o('frugality')

    def start(self, bot, b):
        from .. import extras as EX
        if EX.use(bot, EX.HM7):                       # HM-7: istasyona gitmeden, olduğu yerde satar (100 hak)
            bot.sell_cargo()
            bot.plan['finished'] = True
            return
        bot.plan['harita'] = nearest_station(bot)
        S.go(bot, bot.plan['harita'], b.y, b.now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        if bot.game_map == bot.plan.get('harita'):
            bot.sell_cargo()
            bot.plan['finished'] = True
        else:
            if not S.go(bot, bot.plan.get('harita') or nearest_station(bot), y):
                bot.plan['finished'] = True                 # istasyona yol yok: vazgeçer (sonsuza dek denemez)

    def concrete(self, bot, g, w, now):
        if bot.en_route or bot.game_map != bot.plan.get('harita') or danger(bot, g, w, now):
            return False                                  # portala uçar ya da oyuncuya/tehlikeye karşılık verir (govde)
        from .. import ship as BG
        s = w.station
        if not s:
            bot.sell_cargo()
            bot.plan['finished'] = True
            return True
        nx, ny = g.mover.pos(now)
        if math.hypot(s['posX'] - nx, s['posY'] - ny) > SELL_DISTANCE:
            BG._route(w, g, s['posX'], s['posY'], now, threshold=300)
            return True
        bot.sell_cargo()
        bot.plan['finished'] = True
        return True

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
