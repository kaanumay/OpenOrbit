"""Duel: a response to a player (from another company) who challenged in chat: go to the meeting map, find them and attack. The decision is made by
interaction._duel (aggression, rivalry, anger, level difference); this goal is chosen with an intent (brain.force). It ends when one of them dies
(ship.player_died / killed) or when the player does not show up at the meeting (the intent's duration). If the player changes map the bot follows
(if it is a map it can enter and has a route)."""
import math

from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


def rival(bot):
    import community as TP
    name = bot.plan.get('name')
    return TP.find(name=name) if name else None


@target
class Duel(Goal):
    name = 'duel'
    permission = 'pvp'
    min_sec = 300

    def eligible(self, bot, b):
        n = bot.k.get('intent') or {}
        return n.get('target') == self.name and bool((n.get('plan') or {}).get('name'))

    def points(self, bot, b):
        return 0.5 + 0.4 * bot.o('rekabet')

    def start(self, bot, b):
        bot.plan.update((bot.k.get('intent') or {}).get('plan') or {})
        if not S.go(bot, bot.plan['map'], b.y, b.now):
            bot.plan['finished'] = True

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        o = rival(bot)
        if o is None or o.session is None:
            bot.plan['finished'] = True                     # the player left
            return
        m = int(o.profile.d['position'].get('mapId', 0))
        if m != bot.game_map and m in K.MAPS and K.can_enter(m, bot.firma, bot.level) and K.route(bot.game_map, m, bot.firma,
                                                                                                     bot.level):
            bot.plan['map'] = m
            S.go(bot, m, y)                             # changed map: follow
        elif K.map_npcs(bot.game_map) and bot.r.random() < 0.3:
            S.farm(bot, dt * 0.3, y)                      # kills a few aliens while waiting

    def concrete(self, bot, g, w, now):
        """If the rival is a hero of this world it flies toward them; once in sight ship.pvp_target picks them (duel target first)."""
        if g.target is not None or str(bot.plan.get('name', '')).lower() != str(w.p.d['pilot'].get('userName', '')).lower():
            return False
        if w.hero_dead:
            return False
        hx, hy = w.hero_pos(now)
        nx, ny = g.mover.pos(now)
        if math.hypot(hx - nx, hy - ny) > 500:
            from .. import ship as G
            G._go_to(w, g, hx + bot.r.uniform(-200, 200), hy + bot.r.uniform(-200, 200), now)
            return True
        return False

    def finished(self, bot, b):
        n = bot.k.get('intent') or {}
        return bot.plan.get('finished', False) or n.get('target') != self.name
