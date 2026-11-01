"""Grup: bir gruba girince liderin (ya da gruptaki oyuncunun) haritasına gidip yanında avlanmak; liderin saldırdığına saldırır.
Kabul toplum.davetler'de (niyet olarak bu hedef güçlenir); bağlılık sürdükçe (niyet süresi) seçilir, sonra bot sıkılıp ayrılabilir."""
import math

from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


def leader(bot):
    """Gruptaki takip edilecek kişi (insan oyuncu önce, yoksa lider) -> topluluk.Kisi ya da None."""
    import group as GR
    import community as TP
    g = GR.group_of(bot.uid)
    if g is None:
        return None
    people = TP.all_()
    members = [people.get(u) for u in g.members if u != bot.uid]
    members = [k for k in members if k is not None and k.session is not None]
    human = [k for k in members if k.uid < 1800000000 or k.uid >= 1900000000]
    return (human or [people.get(g.leader)] or [None])[0] if (human or members) else None


@target
class Group(Goal):
    name = 'grup'
    permission = 'grup'
    min_sec = 300

    def eligible(self, bot, b):
        return leader(bot) is not None

    def points(self, bot, b):
        return 0.5 + 0.4 * bot.o('sociability') + 0.3 * bot.o('loyalty')

    def start(self, bot, b):
        self._head_to(bot, b.y, b.now)

    def _head_to(self, bot, y, now=None):
        k = leader(bot)
        if k is None:
            bot.plan['finished'] = True
            return
        m = int(k.profile.d['position'].get('mapId', bot.game_map))
        bot.plan.update(lider=k.uid, harita=m)
        if m in K.MAPS and K.can_enter(m, bot.firma, bot.level):
            S.go(bot, m, y, now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        k = leader(bot)
        if k is None:
            bot.plan['finished'] = True
            return
        if int(k.profile.d['position'].get('mapId', 0)) != bot.game_map:
            self._head_to(bot, y)
            return
        S.farm(bot, dt, y)

    def concrete(self, bot, g, w, now):
        """Liderin yanında kal; lider bu dünyanın kahramanıysa ve saldırıyorsa onun hedefine saldır."""
        uid = bot.plan.get('lider')
        if uid != w.hid or w.hero_dead:
            return False
        if w.attacking and w.target in w.npcs and w.npcs[w.target].bot is None:
            g.target = w.target
        from .. import ship as G
        if g.target is None and G.is_gate_world(w):        # kapı dolgusu: kahramana en yakın uzaylıya (dalgayı birlikte temizler)
            hx, hy = w.hero_pos(now)
            nearby = [(math.hypot(hx - p[0], hy - p[1]), u) for u, m in list(w.npcs.items())
                     if m.bot is None and m.alive for p in (m.mover.pos(now),)]
            nearby = [x for x in nearby if x[0] < 2200]
            if nearby:
                g.target = min(nearby)[1]
        hx, hy = w.hero_pos(now)
        nx, ny = g.mover.pos(now)
        if g.target is None and math.hypot(hx - nx, hy - ny) > 700:
            from .. import ship as G
            G._go_to(w, g, hx + bot.r.uniform(-300, 300), hy + bot.r.uniform(-300, 300), now)
            return True
        return False

    def finished(self, bot, b):
        return bot.plan.get('finished', False) or leader(bot) is None
