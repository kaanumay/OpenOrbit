"""Assist: on a help call in chat (or a request by whisper), go to that map and attack the enemies. Who goes is decided by
yonetici (helpfulness, company, strength, relationship; in Advanced mode the LLM); this is chosen as a goal intent (beyin.zorla)."""
import math

from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


@target
class Helping(Goal):
    name = 'assist'
    permission = 'assist'
    min_sec = 240

    def eligible(self, bot, b):
        n = bot.k.get('intent') or {}
        return n.get('target') == self.name and bool((n.get('plan') or {}).get('map'))

    def points(self, bot, b):
        return 0.3 + 0.5 * bot.o('helpfulness')

    def start(self, bot, b):
        plan = (bot.k.get('intent') or {}).get('plan') or {}
        bot.plan.update(plan)
        if not S.go(bot, plan['map'], b.y, b.now):
            bot.plan['finished'] = True

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        if K.map_npcs(bot.game_map):
            S.farm(bot, dt * 0.5, y)

    def concrete(self, bot, g, w, now):
        """If the one asking for help is this world's hero, go to them (fighting the enemy is in govde's PvP logic: as if hunting)."""
        if g.target is not None or bot.plan.get('name', '').lower() != str(w.p.d['pilot'].get('userName', '')).lower():
            return False
        hx, hy = w.hero_pos(now)
        nx, ny = g.mover.pos(now)
        if math.hypot(hx - nx, hy - ny) > 600:
            from .. import ship as G
            G._go_to(w, g, hx + bot.r.uniform(-250, 250), hy + bot.r.uniform(-250, 250), now)
            return True
        return False

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
