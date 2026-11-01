"""Selling: when the cargo is full, return to its own station (X-1 or X-8) and sell the ore to the refinery (in the game, trading happens only at the station).

When it counts as full depends on personality: a patient, frugal player fills to the brim, an impatient one returns at half. In concrete mode the ship
flies to the station and sells when it arrives; in abstract mode it sells on reaching the station map.
"""
import math

from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S

SELL_DISTANCE = 600


def threshold(bot):
    """It returns to sell once the cargo reaches this much."""
    return min(1.0, 0.55 + 0.3 * bot.o('patience') + 0.15 * bot.o('frugality'))


def nearest_station(bot):
    """The sell map with the shortest route."""
    return min(K.sell_maps(bot.firma), key=lambda m: len(K.route(bot.game_map, m, bot.firma, bot.level) or range(99)))


def danger(bot, g, w, now):
    """Whether it turns to fight while heading home with a full cargo: if a player or bot is hitting it, or its HP is below half. It
    ignores harassment by aliens and keeps flying (live test 2026-10-29: at 2-1 the attacking aliens hit it one after another and it
    never reached the station)."""
    last = [u for u, t in g.attacker.items() if now - t < 6]
    if any(u not in w.npcs or w.npcs[u].bot is not None for u in last):
        return True
    d = bot.value()
    return bool(last) and (g.hp + g.shield) / max(1, d['can'] + d['kalkan']) < 0.5


@target
class Selling(Goal):
    name = 'selling'
    permission = 'cargo'
    min_sec = 30

    def eligible(self, bot, b):
        return bot.cargo_fill() >= threshold(bot)

    def points(self, bot, b):
        return 0.6 + 1.2 * min(1.0, bot.cargo_fill()) + 0.2 * bot.o('frugality')

    def start(self, bot, b):
        from .. import extras as EX
        if EX.use(bot, EX.HM7):                       # HM-7: sells where it is without going to the station (100 rights)
            bot.sell_cargo()
            bot.plan['finished'] = True
            return
        bot.plan['map'] = nearest_station(bot)
        S.go(bot, bot.plan['map'], b.y, b.now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        if bot.game_map == bot.plan.get('map'):
            bot.sell_cargo()
            bot.plan['finished'] = True
        else:
            if not S.go(bot, bot.plan.get('map') or nearest_station(bot), y):
                bot.plan['finished'] = True                 # no route to the station: gives up (cannot try forever)

    def concrete(self, bot, g, w, now):
        if bot.en_route or bot.game_map != bot.plan.get('map') or danger(bot, g, w, now):
            return False                                  # flies to the portal or responds to a player/danger (govde)
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
