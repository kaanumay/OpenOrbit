"""Yardım: sohbette yardım çağrısı (ya da fısıltıyla rica) üzerine o haritaya gidip düşmanlara saldırmak. Kim gideceğine
yonetici karar verir (yardımseverlik, firma, güç, ilişki; Gelişmiş kipte LLM); bu hedef niyetle (beyin.zorla) seçilir."""
import math

from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


@target
class Helping(Goal):
    name = 'yardim'
    permission = 'yardim'
    min_sec = 240

    def eligible(self, bot, b):
        n = bot.k.get('niyet') or {}
        return n.get('hedef') == self.name and bool((n.get('plan') or {}).get('harita'))

    def points(self, bot, b):
        return 0.3 + 0.5 * bot.o('yardimseverlik')

    def start(self, bot, b):
        plan = (bot.k.get('niyet') or {}).get('plan') or {}
        bot.plan.update(plan)
        if not S.go(bot, plan['harita'], b.y, b.now):
            bot.plan['bitti'] = True

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        if K.map_npcs(bot.game_map):
            S.farm(bot, dt * 0.5, y)

    def concrete(self, bot, g, w, now):
        """Yardım isteyen bu dünyanın kahramanıysa yanına git (düşmanla savaş govde'nin PvP aklında: avdaymış gibi)."""
        if g.target is not None or bot.plan.get('ad', '').lower() != str(w.p.d['pilot'].get('userName', '')).lower():
            return False
        hx, hy = w.hero_pos(now)
        nx, ny = g.mover.pos(now)
        if math.hypot(hx - nx, hy - ny) > 600:
            from .. import ship as G
            G._go_to(w, g, hx + bot.r.uniform(-250, 250), hy + bot.r.uniform(-250, 250), now)
            return True
        return False

    def finished(self, bot, b):
        return bot.plan.get('bitti', False)
