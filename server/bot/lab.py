"""Arıtma ve laboratuvar: kargodaki ham cevherden Prometid, Duranium, Promerium arıtıp lazere, rokete ve kalkana yüklemek
(oyuncu gibi: magaza.upgrade, items.json laboratuvar).

Tarifler (birim başına): Prometid 20 Prometium + 10 Endurium, Duranium 10 Endurium + 20 Terbium, Promerium 10 Prometid + 10
Duranium + 1 Xenomit. Yükleme: lazer (0) ve roket (1) Prometid +%15, Promerium +%30, Seprom +%60; kalkan (2) Duranium +%10,
Promerium +%20. Bir birim cevher lazerde 10 mermi, rokette 10 roket, kalkanda 1 dakika yeter.
bot.k['lab'] {parça: [cevher, kalan]}: kalan mermi / roket / saniye. Aynı cevher eklenir, başka cevher öncekini siler (oyundaki gibi).

Kim yükseltir: hırslı, rekabetçi ya da tutumsuz botlar (izin 'lab', 4. seviyeden); tutumlu bot cevherini satar. Arıtılmış cevher
satışta ham hâlinden ucuz olduğu için yalnız yükleyeceği kadar arıtılır.
"""
from . import catalog as K

LAB = K.ITEMS['lab']
RECIPES = {int(u): {int(t): n for t, n in g.items()} for u, g in LAB['recipes'].items()}      # 4, 5, 6
BONUS = {int(p): {int(c): v for c, v in g.items()} for p, g in LAB['bonuses'].items()}
UNIT = {int(p): v for p, v in LAB['unit'].items()}
LAZER, ROCKET, SHIELD = 0, 1, 2
PROMETID, DURANIUM, PROMERIUM = 4, 5, 6


def lab_data(bot):
    return bot.k.setdefault('lab', {})


def bonus(bot, part):
    """Parçanın şimdiki laboratuvar bonusu (0: yüklü değil ya da bitti)."""
    v = lab_data(bot).get(str(part))
    return BONUS[part].get(int(v[0]), 0.0) if v and v[1] > 0 else 0.0


def spend(bot, part, n):
    """Yükten n birim (mermi, roket ya da saniye) harcar; biterse yük kalkar."""
    y = lab_data(bot)
    v = y.get(str(part))
    if not v:
        return
    v[1] -= n
    if v[1] <= 0:
        del y[str(part)]


def _cargo(bot):
    return bot.k.setdefault('kargo', {})


def refine(bot, product, count):
    """Kargodaki girdilerden en çok adet birim arıtır -> arıtılan."""
    cargo = _cargo(bot)
    recipe = RECIPES[product]
    n = min([count] + [cargo.get(str(t), 0) // g for t, g in recipe.items()])
    if n <= 0:
        return 0
    for t, g in recipe.items():
        cargo[str(t)] -= g * n
        if cargo[str(t)] <= 0:
            del cargo[str(t)]
    cargo[str(product)] = cargo.get(str(product), 0) + n
    bot.ist('aritma', n)
    return n


def load(bot, part, ore, count):
    """Kargodan parçaya adet birim cevher yükler (aynı cevher eklenir, başkası öncekini siler) -> yüklenen."""
    cargo = _cargo(bot)
    count = min(count, cargo.get(str(ore), 0))
    if count <= 0:
        return 0
    cargo[str(ore)] -= count
    if cargo[str(ore)] <= 0:
        del cargo[str(ore)]
    y = lab_data(bot)
    duration = count * UNIT[part] * (LAB.get('minute_sec', 60) if part >= 2 else 1)
    v = y.get(str(part))
    y[str(part)] = [ore, (v[1] if v and int(v[0]) == ore else 0) + duration]
    bot.ist('lab_yukleme', count)
    return count


def will_upgrade(bot):
    if not bot.permission.get('lab', True) or bot.level < 4:
        return False
    return bot.o('hirs') * 0.5 + bot.o('rekabet') * 0.3 + (1 - bot.o('tutumluluk')) * 0.4 > 0.55


def _is_promerium_good(bot, need):
    """Kargoyla Promerium yolu (+%30) Prometid yolundan (+%15) çok mu kazandırır (bonus x mermi): kargonun kopyasında dener."""
    original, counter = dict(_cargo(bot)), bot.k['istat'].get('aritma', 0)
    try:
        refine(bot, PROMETID, need * 10)
        refine(bot, DURANIUM, need * 10)
        prom = refine(bot, PROMERIUM, need)
        bot.k['kargo'] = dict(original)
        prometid = refine(bot, PROMETID, need)
    finally:
        bot.k['kargo'] = original
        bot.k['istat']['aritma'] = counter
    return BONUS[LAZER][PROMERIUM] * prom > BONUS[LAZER][PROMETID] * prometid


def decision(bot, hourly_ammo):
    """Kargodaki cevherle laboratuvar: yükü azaldıysa arıtıp yükler (lazer önce, sonra kalkan ve roket). Satıştan önce çağrılır:
    kalan cevher satılır."""
    if not will_upgrade(bot):
        return
    cargo = _cargo(bot)
    target = hourly_ammo * (1 + bot.o('hirs'))                     # yaklaşık bir-iki saatlik mermi
    v = lab_data(bot).get(str(LAZER))
    if not v or v[1] < target * 0.3:
        need = int(target / UNIT[LAZER]) + 1
        if cargo.get('3', 0) > 0 and _is_promerium_good(bot, need):     # Xenomit varsa ve daha çok kazandırıyorsa Promerium (+%30)
            refine(bot, PROMETID, need * 10)
            refine(bot, DURANIUM, need * 10)
            if refine(bot, PROMERIUM, need):
                load(bot, LAZER, PROMERIUM, need)
        else:
            refine(bot, PROMETID, need)
            load(bot, LAZER, PROMETID, need)
    v = lab_data(bot).get(str(SHIELD))
    if bot.o('risk') < 0.6 and (not v or v[1] < 1800):
        refine(bot, DURANIUM, 60)
        load(bot, SHIELD, DURANIUM, 60)                           # bir saatlik kalkan
    v = lab_data(bot).get(str(ROCKET))
    if bot.permission.get('roket', True) and (not v or v[1] < 50):
        refine(bot, PROMETID, 10)
        load(bot, ROCKET, PROMETID, 10)
