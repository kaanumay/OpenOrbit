"""Soyut benzetim: oyuncunun haritasında olmayan botların yolculuğu, kasılması, ölümü ve bot-bot karşılaşmaları (istatistiksel).

Sonuçlar katalog.harita_degerlendir'in beklenen değerlerinden gürültüyle çekilir: aynı güçteki iki bot aynı sürede birbirine yakın
ama aynı olmayan ilerleme yapar (şans, dikkat, "o gün iyi oynadı"). Botun gün içindeki verimi de kişiliğiyle oynar: sabırlı bot
düzenli, sabırsız bot dalgalı kasar.
"""
import math, time

import map_links as H
from . import catalog as K
from . import personality as PS

BONUS_URIDIUM_PER_HOUR = 220          # bonus kutularından saatte uridyum (seviye başına artar; 1-x'te ~200, yukarıda daha çok kutu)
BOX_URIDIUM = 170 / 19.0                 # bonus kutusunun ortalama uridyumu (dunya.CFG['bonus_kutu']: 19 eşit olasılıklı içerik)
DEATH_WAIT = (25, 70)       # öldükten sonra doğmaya dek (ölüm ekranı, tamir seçimi, üsse dönüş)


def go(bot, target, y=None, now=None):
    """Portal yolunu kurar -> yol var mı. Yolda her harita ATLAMA_SN'de bir (hıza göre) geçilir."""
    now = now or (y.now if y is not None else time.time())
    target = int(target)
    if target == bot.game_map:
        bot.en_route = None
        return True
    route = K.route(bot.game_map, target, bot.firma, bot.level)
    if not route:
        bot.en_route = None
        return False
    if len(route) > 3 and bot.body is None:              # atlama CPU'su: uzun yolu tek atlamada üsse (somutta govde.portala)
        from . import extras as EX
        cpu = EX.jump(bot, target)
        if cpu and EX.use(bot, cpu):
            jump_to(bot, target, y)
            bot.en_route = None
            bot.ist('atlama_cpu')
            return True
    bot.en_route = route[1:]
    bot.en_route_time = now + jump_duration(bot)
    return True


def jump_duration(bot):
    return K.JUMP_SEC * bot.r.uniform(0.7, 1.3) * 320.0 / max(200, bot.value()['hiz'])


def journey(bot, y, now=None):
    """Yoldaysa sıradaki atlama zamanı geldiyse atlar -> hâlâ yolda mı."""
    if not bot.en_route:
        return False
    now = now or (y.now if y is not None else time.time())
    if bot.body is not None:            # somut: gemi portala uçar, atlamayı govde yapar
        return True
    if now >= bot.en_route_time:
        jump_to(bot, bot.en_route.pop(0), y)
        bot.en_route_time = now + jump_duration(bot)
    return bool(bot.en_route)


def jump_to(bot, target, y):
    old = bot.k['harita']
    bot.k['harita'] = int(target)
    bot.k['x'] = bot.k['y'] = 0
    seen = bot.k.setdefault('gorulen', [])
    if int(target) not in seen:
        seen.append(int(target))
    if y is not None:
        y.map_changed(bot, old)


def _collect_boxes(bot, dt, speed):
    """Mermisi yok: kasamaz, oyuncu gibi bonus kutusu toplar (kutudan cephane ve kredi gelir; parası bitmiş bot böyle toparlanır)."""
    from . import weapons as WP
    k = dt / 3600.0 * speed * 0.5 * (1 - 0.35 * bot.mood['yorgunluk'])
    box = BONUS_URIDIUM_PER_HOUR * (1 + bot.level / 6.0) * k * x1_cut(bot)
    bot.reward('kutu', uridyum=box)
    WP.box_ammo(bot, box / BOX_URIDIUM)


def farm(bot, dt, y, target_kind=None):
    """dt saniye uzaylı kasma: kazanç, görev ilerlemesi, kargo, cephane tüketimi, ölüm. hedef_tip: görevin istediği uzaylı (yalnız onu
    kovalar: daha yavaş). Cephane ve roket stoktan (weapons.py): dayanıklı uzaylıya x2/x3, roket varsa onun hasarı da; mermi biterse
    o kadar az kasar."""
    from . import weapons as WP
    speed = y.speed(bot) if y is not None else 1.0
    d = bot.value()
    courage = max(0.0, min(1.0, 0.3 + 0.6 * bot.o('risk') + 0.2 * bot.mood['ozguven'] - 0.3))
    r = K.evaluate_map(bot.game_map, d['dps'], d['ehp'], courage)
    if not r['hedefler']:
        if not WP.pick_laser(bot) and not WP.pick_rocket(bot):
            _collect_boxes(bot, dt, speed)        # gücüne uygun uzaylı olmayan haritada da (yoksa mermisiz bot orada hiç toparlanmıyordu)
        return
    nv = K.npc_value(target_kind) if target_kind else None
    ehp_avg = nv['ehp'] if nv else sum(K.npc_value(t)['ehp'] * v for t, v in r['oldurme'].items()) / max(1e-9, sum(r['oldurme'].values()))
    lasers, rocket, dps, laser_dps = WP.grind_plan(bot, ehp_avg)
    if not lasers and not rocket:
        _collect_boxes(bot, dt, speed)
        return
    from . import lab as LB
    ehp = d['ehp'] * (1 + 0.5 * LB.bonus(bot, LB.SHIELD))      # kalkan yükü (kalkan payı ~yarısı)
    if abs(dps - d['dps']) > 1e-6 or ehp != d['ehp']:
        r = K.evaluate_map(bot.game_map, dps, ehp, courage)
        if not r['hedefler']:
            return
    # verim: gürültülü (sabırsız bot dalgalı), yorgunken düşük
    efficiency = max(0.2, bot.r.gauss(PS.ACTIVITY[bot.archetype][1], 0.12 + 0.2 * (1 - bot.o('sabir')))) * (1 - 0.35 * bot.mood['yorgunluk'])
    from . import extras as EX
    efficiency *= 1 + 0.04 * EX.repair_level(bot)          # onarım robotu: toparlanmaya daha az zaman
    k = dt / 3600.0 * speed * efficiency
    kills = r['oldurme']
    if target_kind and target_kind in kills:
        kills = {target_kind: kills[target_kind] * 1.6}      # yalnız istediğini kovalar: o türden daha çok
        ratio = sum(kills.values()) / max(1e-9, sum(r['oldurme'].values()))
        k_reward = k * min(1.0, ratio)
    else:
        k_reward = k
    # mermi ve roket: öldürülecek canlar kadar (oyuncu her atışta lazer sayısı kadar mermi harcar)
    afforded = WP.consume(bot, sum(K.npc_value(t)['ehp'] * v * k for t, v in kills.items()), lasers, rocket, dps, laser_dps)
    from . import lab as LB
    LB.spend(bot, LB.SHIELD, dt)                         # kalkan yükü dakikayla
    k, k_reward = k * afforded, k_reward * afforded
    lv = bot.level
    x1 = x1_cut(bot)
    bot.reward('npc', ep=r['saat_ep'] * k_reward * x1, kredi=r['saat_kredi'] * k_reward * x1, uridyum=r['saat_uridyum'] * k_reward * x1,
             onur=r['saat_onur'] * k_reward)
    box = BONUS_URIDIUM_PER_HOUR * (1 + lv / 6.0) * k * x1
    bot.reward('kutu', uridyum=box)
    WP.box_ammo(bot, box / BOX_URIDIUM)                # bonus kutularının cephanesi ve kredisi
    total = 0
    for tip, hour in kills.items():
        n = _poisson(bot.r, hour * k)
        if n:
            total += n
            from . import society as TB
            bot.ist('npc_puan', TB.npc_rank_points(tip) * n)
            from . import loot as LT
            LT.extra_loot(bot, tip, n)                   # Scrapium, Mucosum, günlük dosyası …
            if bot.permission.get('kargo', True):             # kargo kutuları: sabırlı oyuncu hepsini toplar, aceleci çoğunu bırakır
                take = (0.55 + 0.4 * bot.o('sabir')) * bot.game_settings.multiplier('toplama', 'kargo') * (1 + LT.booster_share(bot, 'COLLECT_RESOURCES'))
                bot.add_cargo({t: int(v * n * take) for t, v in K.npc_cargo(tip, bot.level, bot.game_map).items()})
            if y is not None:
                y.npc_killed(bot, tip, n)
    if total:
        bot.ist('npc', total)
        bot.mood.it(moral=0.002 * total)
    from . import loot as LT, events as IX
    LT.abstract(bot, dt, y)                                 # haritanın anahtarlı kutuları
    IX.abstract(bot, dt, y, dps)                            # etkinlik uzaylıları, düşmeleri ve kutuları
    if bot.r.random() < r['olum_saat'] * dt / 3600.0 * (0.6 + 0.8 * (1 - bot.o('sabir')) * 0.5):
        death(bot, y, reason='npc', now=y.now if y is not None else None)


def x1_cut(bot):
    """Kendi X-1'inde yüksek seviyede ödül azalır (npc.json x1_odul; dunya.World.grant_loot)."""
    if H.map_class(bot.game_map) != 'X-1' or H.company(bot.game_map) != bot.firma:
        return 1.0
    return next((k for l, k in reversed(K.COMBAT['x1_odul']) if bot.level >= l), 1.0)


def pick_repair(bot, y, killer=None):
    """Ölüm ekranında oyuncunun seçeceği gibi: 'istasyon' (ücretsiz, üsse döner), 'portal' (500 U, aynı haritanın en yakın
    portalında) ya da 'yerinde' (1.000 U, canın %10'u ve 10 sn koruma). Pahalılar ancak uridyumu bolsa: yerinde sabırsızlık ve
    intikam hırsıyla, portal evden uzaklıkla ve cömertlikle. Ödenen uridyum düşer."""
    m = bot.game_map
    if m not in K.MAPS or y is not None and y.mode == 'basit':
        return 'istasyon'
    route = K.route(m, K.ev(bot.firma), bot.firma, bot.level)
    far = len(route) - 1 if route else 0
    if far < 1:
        return 'istasyon'                           # zaten evinde: istasyon tamiri hem ücretsiz hem yakın
    C, k, frugality = K.ITEMS['olum_ekrani'], bot.game_settings.multiplier('tamir_ucreti'), bot.o('tutumluluk')
    for kind, price, urge in (('yerinde', C['yerinde_uridyum'] * k,
                               0.12 * (1 - bot.o('sabir')) + (0.3 * bot.mood['ofke'] if killer else 0.0)),
                              ('portal', C['portal_uridyum'] * k, 0.1 * far * (1.2 - frugality))):
        if bot.k['uridyum'] >= price * (3 + 5 * frugality) and bot.r.random() < urge:     # birikimin küçük bir payıysa öder
            bot.earn(uridyum=-int(round(price)))
            return kind
    return 'istasyon'


def death(bot, y, reason='npc', killer=None, now=None):
    """Bot öldü: ruh hâli, istatistik, oyuncunun ölüm ekranındaki gibi tamir seçimi (tamir_sec). İstasyonda tamir: bir süre
    sonra firmanın üssünde (X-1 ya da seviyesine göre X-8) istasyonun çevresinde; portal ve yerinde tamir: aynı haritada, kısa
    sürede. Kargo kalır (oyuncu da ölünce kargosunu kaybetmez)."""
    now = now or (y.now if y is not None else time.time())
    bot.ist('olum')
    bot.mood.it(ofke=0.35 if killer else 0.15, moral=-0.15, ozguven=-0.12)
    if killer:
        bot.memory.event(killer, 'oldurdu_beni', now)
    repair = pick_repair(bot, y, killer)
    bot.event('olum', now, neden=reason, katil=killer, harita=H.name(bot.game_map), tamir=repair)
    bot.en_route = None
    bot.dead_until = now + bot.r.uniform(*DEATH_WAIT)
    if y is not None and y.mode == 'basit':
        y.bot_died(bot, killer)
        bot.next_decision = bot.dead_until
        return                                      # basit kip: aynı haritada yeniden doğar
    if repair != 'istasyon':
        bot.dead_until = now + bot.r.uniform(5, 15)    # ölüm ekranında hemen seçti
        x, yy = bot.k.get('x') or 0, bot.k.get('y') or 0
        if repair == 'portal':
            g = min(H.gates(bot.game_map, bot.firma) or [{'x': x, 'y': yy}], key=lambda g: math.hypot(g['x'] - x, g['y'] - yy))
            bot.k['x'], bot.k['y'] = int(g['x'] + bot.r.uniform(-150, 150)), int(g['y'] + bot.r.uniform(-150, 150))
        else:
            bot.in_place_repair = True                  # gövde %10 canla ve 10 sn korumayla doğar (govde.tick)
        if y is not None:
            y.bot_died(bot, killer)
        bot.next_decision = bot.dead_until
        return
    bot.k['x'] = bot.k['y'] = None                    # üste: ölüm yerinde değil istasyonun çevresinde doğar
    ev = H.x8_home(bot.firma, bot.level, bot.game_map) if bot.level >= 12 else None
    target = int(ev) if ev else K.ev(bot.firma)
    if y is not None:
        y.bot_died(bot, killer)
    if target != bot.game_map:
        jump_to(bot, target, y)
    bot.next_decision = bot.dead_until


def _poisson(r, lam):
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(r.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= r.random()
        if p <= L:
            return k
        k += 1


# ------------------------------------------------------------------------------------------------------------ bot-bot PvP
def encounter(a, b, y, now=None):
    """İki düşman bot aynı haritada karşılaştı (yonetici.pvp_tick seçer): saldıran saldırır, öteki savaşır ya da kaçar; sonuç
    güç oranından, şanstan ve kişilikten. -> ('kazandi', kazanan, kaybeden) | ('kacti', kacan, kovalayan) | None"""
    now = now or time.time()
    from . import extras as EX
    from . import technology as TECH
    ga = max(0.5, a.value()['guc']) * EX.pvp_factor(a) * TECH.pvp_factor(a)
    gb = max(0.5, b.value()['guc']) * EX.pvp_factor(b) * TECH.pvp_factor(b)
    ratio = gb / ga                                 # >1: b daha güçlü
    if ratio < 0.6 and b.r.random() < 1 - b.o('risk') and EX.cloak(b):          # gizlenme CPU'su: görünmeden sıvışır
        b.ist('gizlendi')
        return ('kacti', b, a)
    from . import weapons as WP
    mine_choice = WP.pick_mine(b)                      # kaçan arkasına mayın bırakır: kovalayan yavaşlar
    # b kaçar mı: temkinli ve zayıfsa
    flee = ratio < 0.8 and b.r.random() < (1 - b.o('risk')) * (1 - ratio) + 0.2 * (1 - b.o('saldirganlik'))
    if flee and b.r.random() < 0.55 + 0.25 * (b.value()['hiz'] > a.value()['hiz']) + 0.15 * bool(mine_choice and WP.spend(b, mine_choice, 1)):
        b.memory.event(a.name, 'hakaret', now, multiplier=0.5)
        b.mood.it(ofke=0.1, ozguven=-0.05)
        return ('kacti', b, a)
    pa = ga ** 1.5 / (ga ** 1.5 + gb ** 1.5)       # güçlü olanın üstünlüğü doğrusal değil
    pa = 0.08 + 0.84 * pa                          # sürpriz her zaman mümkün
    winner, loser = (a, b) if a.r.random() < pa else (b, a)
    pvp_reward(winner, loser, y, now)
    death(loser, y, reason='oyuncu', killer=winner.name, now=now)
    return ('kazandi', winner, loser)


def pvp_reward(winner, loser, y, now):
    """Öldürmenin onuru ve EP'si (items.json oyuncu_oldurme: onur 100 x, EP 1.000 x kurbanın gemi puanı; kabaca seviyeyle)."""
    kill_rewards = K.ITEMS['oyuncu_oldurme']
    multiplier = max(1, loser.level // 2)
    speed = y.speed(winner) if y is not None else 1.0
    winner.reward(None, speed, ep=kill_rewards['ep_puan'] * multiplier, onur=kill_rewards['onur_puan'] * multiplier)
    winner.ist('oyuncu')
    from . import society as TB
    winner.ist('oyuncu_puan', TB.ship_rank_points(loser.k['ekip']['gemi']))
    winner.mood.it(moral=0.1, ozguven=0.08, ofke=-0.2)
    winner.memory.event(loser.name, 'oldurdum', now)
    winner.event('oldurdum', now, kurban=loser.name)
