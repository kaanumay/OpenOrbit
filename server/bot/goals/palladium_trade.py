"""Palladium trade: with enough Palladium (bot/palladium.py) the bot flies to the pirate trader on 5-2 and turns it into gate energy, which
the Galaxy Gate generator spends before uridium. In abstract mode it trades on reaching 5-2, in concrete mode at the trader structure."""
import math

from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S
from .. import palladium as PD
from .selling import SELL_DISTANCE, danger


def _reachable(bot):
    return K.can_enter(PD.MARKET, bot.company, bot.level) and K.route(bot.game_map, PD.MARKET, bot.company, bot.level) is not None


@target
class PalladiumTrade(Goal):
    name = 'palladium_trade'
    permission = 'gate'
    min_sec = 30

    def eligible(self, bot, b):
        return bot.permission.get('cargo', True) and PD.trade_due(bot) and _reachable(bot)

    def points(self, bot, b):
        # above selling (0.6 .. 2.0) when the hold is mostly Palladium: otherwise it would carry it home to storage first
        share = PD.held(bot) / max(1, K.cargo_capacity(bot.k['gear']))
        return 0.9 + 1.4 * min(1.0, share) + 0.3 * bot.o('ambition')

    def start(self, bot, b):
        bot.plan['map'] = PD.MARKET
        S.go(bot, PD.MARKET, b.y, b.now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        if bot.game_map == PD.MARKET:
            PD.trade(bot)
            bot.plan['finished'] = True
        elif not S.go(bot, PD.MARKET, y):
            bot.plan['finished'] = True                   # no route to 5-2: gives up

    def concrete(self, bot, g, w, now):
        if bot.en_route or bot.game_map != PD.MARKET or danger(bot, g, w, now):
            return False
        import map_layout as ML
        pos, _r = ML.structure_asset(w.map_id)              # the 5-2 trader next to the pirate station
        s = pos or ((w.station['posX'], w.station['posY']) if w.station else None)
        if s is None:
            PD.trade(bot)
            bot.plan['finished'] = True
            return True
        from .. import ship as BG
        nx, ny = g.mover.pos(now)
        if math.hypot(s[0] - nx, s[1] - ny) > SELL_DISTANCE:
            BG._route(w, g, s[0], s[1], now, threshold=300)
            return True
        PD.trade(bot)
        bot.plan['finished'] = True
        return True

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
