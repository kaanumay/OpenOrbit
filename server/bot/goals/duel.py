"""Düello: sohbette meydan okuyan oyuncuya (başka firmadan) karşılık: buluşma haritasına gidip onu bulur ve saldırır. Kararı
etkilesim._duello verir (saldırganlık, rekabet, öfke, seviye farkı), bu hedef niyetle (beyin.zorla) seçilir. Biri ölünce
(govde.oyuncu_oldu / olduruldu) ya da oyuncu buluşmaya gelmeyince (niyetin süresi) biter. Oyuncu haritayı değiştirirse peşinden
gider (girebildiği ve yolu olan bir haritaysa)."""
import math

from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


def rival(bot):
    import community as TP
    name = bot.plan.get('ad')
    return TP.find(name=name) if name else None


@target
class Duel(Goal):
    name = 'duello'
    permission = 'pvp'
    min_sec = 300

    def eligible(self, bot, b):
        n = bot.k.get('niyet') or {}
        return n.get('hedef') == self.name and bool((n.get('plan') or {}).get('ad'))

    def points(self, bot, b):
        return 0.5 + 0.4 * bot.o('rekabet')

    def start(self, bot, b):
        bot.plan.update((bot.k.get('niyet') or {}).get('plan') or {})
        if not S.go(bot, bot.plan['harita'], b.y, b.now):
            bot.plan['bitti'] = True

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        o = rival(bot)
        if o is None or o.session is None:
            bot.plan['bitti'] = True                     # oyuncu çıktı
            return
        m = int(o.profile.d['konum'].get('mapId', 0))
        if m != bot.game_map and m in K.MAPS and K.can_enter(m, bot.firma, bot.level) and K.route(bot.game_map, m, bot.firma,
                                                                                                     bot.level):
            bot.plan['harita'] = m
            S.go(bot, m, y)                             # haritayı değiştirdi: peşinden
        elif K.map_npcs(bot.game_map) and bot.r.random() < 0.3:
            S.farm(bot, dt * 0.3, y)                      # beklerken biraz uzaylı keser

    def concrete(self, bot, g, w, now):
        """Rakip bu dünyanın kahramanıysa ona doğru uçar; görüşe girince govde.pvp_hedefi onu seçer (düello hedefi önce)."""
        if g.target is not None or str(bot.plan.get('ad', '')).lower() != str(w.p.d['pilot'].get('userName', '')).lower():
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
        n = bot.k.get('niyet') or {}
        return bot.plan.get('bitti', False) or n.get('hedef') != self.name
