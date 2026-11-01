"""PvP avı: düşman firmanın oyuncularını aramak (4-X, başka firmanın haritaları). Karşılaşmaları yonetici.pvp_tick çözer; avdaki bot
saldırgan sayılır. Öfke (az önce öldürüldü) ve kin (hafızada onu öldüren) avı çeker: intikam."""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


def find_target(y, name):
    """Av emrindeki kişi: botlardan ya da gerçek oyunculardan (ad büyük/küçük harf ayrımsız) -> (ad, firma, harita ya da None
    (çevrimdışı), klan, insan mı) ya da None."""
    a = str(name or '').strip().lower()
    if not a:
        return None
    x = y.name_index.get(a)
    if x is not None:
        return x.name, x.firma, (x.game_map if x.online else None), x.k.get('klan'), False
    import community as TP
    import clan as KL
    k = TP.find(name=a)
    if k is None:
        return None
    kl = KL.clan_of(k.profile)
    return (k.name, int(k.profile.d['pilot'].get('factionId') or 0),
            int(k.profile.d['konum'].get('mapId', 0)) or None if k.session is not None else None, kl['id'] if kl else None, True)


def order_grudge(bot, name, now):
    """Klan emriyle (klan_emir) verilen av ya da klan odağı: bu kişiye kin gibi davranılır (govde.pvp_hedefi 'kin' terimine eklenir)."""
    a = bot.k.get('av_emri')
    name = str(name).lower()
    if a and now < a['bitis'] and a['ad'] == name:
        return 1.0
    f = bot.k.get('klan_odagi')
    if f and now < f['bitis']:
        import clan as KL
        c = KL.CLANS.get(f['klan'])
        if c is not None and name in c['uyeler']:
            return 0.8
    return 0.0


def order_target(bot, y, now):
    """Sürmekte olan av emrinin (ya da klan odağının) çevrimiçi hedefi -> (ad, harita) ya da None."""
    a = bot.k.get('av_emri')
    if a and now < a['bitis']:
        t = find_target(y, a['ad'])
        if t is not None and t[2] and t[1] != bot.firma and K.route(bot.game_map, t[2], bot.firma, bot.level):
            return t[0], t[2]
    f = bot.k.get('klan_odagi')
    if f and now < f['bitis']:
        import clan as KL
        c = KL.CLANS.get(f['klan'])
        for u in (c or {}).get('uyeler', ()):
            t = find_target(y, u)
            if t is not None and t[2] and t[1] != bot.firma and K.route(bot.game_map, t[2], bot.firma, bot.level):
                return t[0], t[2]
    return None


@target
class PvpHunt(Goal):
    name = 'pvp'
    permission = 'pvp'
    min_sec = 240

    def eligible(self, bot, b):
        from .. import admin_warnings as AW
        from .. import weapons as WP
        return bot.level >= (b.setting('pvp_seviye', 6) or 1) and bot.value()['guc'] >= 8 and not AW.active(bot, 'pvp', b.now)             and WP.has_laser(bot)                         # cephanesiz oyuncu avlanmaz

    def points(self, bot, b):
        o = bot.traits
        p = 0.1 + 0.55 * o['saldirganlik'] * o['rekabet'] + (0.35 if bot.archetype == 'avci' else 0)
        p += 0.45 * bot.mood['ofke'] * o['saldirganlik']
        p *= 0.6 + 0.6 * bot.mood['ozguven']
        if b.y is not None and bot.memory.grudges() and b.y.online_name(bot.memory.grudges()):
            p += 0.25 * o['saldirganlik']
        if b.y is not None and b.y.prime(b.now):
            p *= float(b.setting('prime_pvp', 2.0) or 1.0)           # akşam yoğun saati: PvP canlanır
        return p

    def start(self, bot, b):
        y = b.y
        target_map = None
        grudge = y.online_name(bot.memory.grudges()) if y is not None else None
        order = order_target(bot, y, b.now) if y is not None else None
        if order is not None:
            target_map = order[1]                           # klan emri: söylenen kişiyi (ya da odaktaki klanın üyesini) bulmaya gider
            bot.plan['av'] = order[0]
            grudge = order
        elif grudge is not None and K.route(bot.game_map, grudge.game_map, bot.firma, bot.level):
            target_map = grudge.game_map                        # intikam: onu öldüreni bulmaya gider
            bot.plan['av'] = grudge.name
        elif y is not None:
            # düşmanların olduğu, gidilebilen ve çok güçlü düşmanı olmayan harita
            power = bot.value()['guc']
            candidates = []
            for m, enemy in y.enemy_population(bot).items():
                if not enemy or not K.can_enter(m, bot.firma, bot.level) or not K.route(bot.game_map, m, bot.firma, bot.level):
                    continue
                threat = max(d.value()['guc'] for d in enemy) / max(1.0, power)
                candidates.append((len(enemy) - 2.5 * max(0.0, threat - 1.0 - bot.o('risk')), m))
            if candidates:
                target_map = max(candidates)[1]
        if (y is not None and grudge is None and y.prime(b.now) and b.setting('buyuk_savas', True) and bot.r.random() < 0.75
                and K.can_enter(y.front(b.now), bot.firma, bot.level) and K.route(bot.game_map, y.front(b.now), bot.firma, bot.level)):
            target_map = y.front(b.now)                    # büyük savaş: firmalar yoğun saatin cephesinde toplanır
            call = y.__dict__.setdefault('front_call', {})
            key = (bot.firma, int(b.now // 3600))
            if key not in call and bot.o('konuskanlik') + bot.o('saldirganlik') > 1.0:
                call[key] = bot.name
                import map_links as H
                from .. import speech as SPC
                y.speak(bot, 'firma', SPC.template(bot, 'savas_cagri', harita=H.name(target_map)), now=b.now + bot.r.uniform(3, 20))
        if target_map is None:
            target_map = next((m for m in (13 + bot.firma - 1, 16, 29) if K.can_enter(m, bot.firma, bot.level)), bot.game_map)
        bot.plan['harita'] = int(target_map)
        S.go(bot, target_map, y, b.now)

    def concrete(self, bot, g, w, now):
        """Haritada av (klan emri ya da intikam): avlanan bu haritadaysa görmese de ona doğru uçar, görüşe girince govde.pvp_hedefi
        saldırır (emir_kini ve kin onu öne alır); başka haritaya geçtiyse peşinden gider (canlı 2026-11-01: bot avın haritasına
        varıp orada uzaylı kesiyordu). Dövüşteyken, yolda ve avsızken govde'nin olağan davranışı."""
        from .. import ship as BG
        y = BG.MGR.ACTIVE
        order = order_target(bot, y, now) if y is not None else None
        if order is not None:
            bot.plan['av'] = order[0]                      # süren emir önce gelir (zaten PvP'deyken verilen emirde basla yeniden çalışmaz)
        name = str(bot.plan.get('av') or '').lower()
        if not name or g.target is not None or bot.en_route or any(now - t < 6 for t in g.attacker.values()):
            return False
        uid = next((m.id for m in w.npcs.values() if m.alive and m.bot is not None and m.bot.name.lower() == name), None)
        if uid is None:
            uid = next((o.hid for o in ([w] + list(w.shared.members if w.shared is not None else [])) if o.running and not o.hero_dead
                        and str(o.p.d['pilot'].get('userName', '')).lower() == name), None)
        if uid is None:
            t = find_target(y, name) if y is not None else None
            if (t is not None and t[2] and t[2] != bot.game_map and now >= bot.__dict__.get('_hunt_trail', 0)
                    and K.route(bot.game_map, t[2], bot.firma, bot.level)):
                bot._hunt_trail = now + 30
                bot.plan['harita'] = int(t[2])
                S.go(bot, t[2], y, now)                  # av başka haritaya geçti: peşinden
                return True
            return False
        t = BG.pvp_target(w, g, now)
        if t is not None:
            g.target = t                                   # görüşte: saldırır (savaş govde'de)
            return False
        pos = BG._position(w, uid, now)
        if pos is None:
            return False
        BG._go_to(w, g, pos[0], pos[1], now, threshold=300)
        return True

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        if K.map_npcs(bot.game_map) and bot.r.random() < 0.5:
            S.farm(bot, dt * 0.5, y)        # beklerken uzaylı da keser (yarı verim)
