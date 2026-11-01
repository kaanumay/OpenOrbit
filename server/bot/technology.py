"""Teknoloji eşyaları ve roket fırlatıcısı (oyuncu gibi: Assembly tarifleri, savas_esya, technology.py).

Teknoloji eşyaları Assembly'nin para tarifleriyle üretilir (data/recipes.json: Backup Shields ve Battle Repair Bot 2.800 U,
Chain Impulse 1.800 U, Energy Leech 6.500 U, Precision Targeter 250 U); etkinlik kaynağı isteyen tarifler botlara kapalı. Stok
bot.k['stok']'ta. Kullanım:
  somut  canı %40'ın altına inince Backup Shields (kalkan) ya da Battle Repair Bot (onarım); yakında 3+ uzaylı varken Chain Impulse
  soyut  PvP karşılaşmasında Backup Shields ve Battle Repair Bot güç katar; dayanıklı uzaylıda Precision Targeter (roketler hep
         isabet) ve Energy Leech (verim)
Roket fırlatıcısı (HST-1 kredi, HST-2 uridyum): salvo kapasitesi 3/5, roket başına 1 sn dolum; ECO-10 (kredi) ya da HSTRM-01
(uridyum) ile dayanıklı uzaylıda ve PvP'de.
"""
from . import catalog as K

TECH = K.ITEMS['technology']['items']
RECIPES = {'tech_backup-shields': ('U', 2800), 'tech_battle-repair-bot': ('U', 2800), 'tech_chain-impulse': ('U', 1800),
         'tech_energy-leech': ('U', 6500), 'tech_precision-targeter': ('U', 250)}
LAUNCHER = K.ITEMS['combat_items']['launcher']
LAUNCHER_AMMO = K.ITEMS['combat_items']['launcher_ammo']
HST = ('equipment_weapon_rocketlauncher_hst-1', 'equipment_weapon_rocketlauncher_hst-2')
LAUNCHER_ROCKETS = ('ammunition_rocketlauncher_eco-10', 'ammunition_rocketlauncher_hstrm-01')


def _stock(bot):
    from . import weapons as WP
    return WP.stock(bot)


def allowed(bot):
    return bot.permission.get('technology', True)


# ------------------------------------------------------------------------------------------------------------ üretim
def produce(bot):
    """Assembly: stokta olmayan işe yarar teknoloji eşyalarını para tarifiyle üretir (8. seviyeden, uridyumu yetiyorsa)."""
    if not allowed(bot) or bot.level < 8:
        return {}
    s = _stock(bot)
    t = bot.o('frugality')
    wanted = ['tech_precision-targeter'] if bot.permission.get('rocket', True) else []
    if bot.permission.get('pvp', True) and bot.o('aggression') + bot.o('risk') > 0.8:
        wanted += ['tech_backup-shields', 'tech_battle-repair-bot']
    if bot.level >= 12:
        wanted += ['tech_chain-impulse', 'tech_energy-leech']
    out = {}
    for e in wanted:
        currency, price = RECIPES[e]
        price *= bot.game_settings.multiplier('shop_price')
        if s.get(e, 0) < 2 and bot.k['uridium'] > price * (3 + 3 * t) and bot.pay(currency, price):
            s[e] = s.get(e, 0) + 1
            out[e] = 1
            bot.ist('assembly')
    return out


def use(bot, e):
    s = _stock(bot)
    if s.get(e, 0) <= 0 or not allowed(bot):
        return False
    if not bot.game_settings.get('infinite_technology'):
        s[e] -= 1
        if not s[e]:
            del s[e]
    bot.ist('technology')
    return True


def pvp_factor(bot):
    """PvP karşılaşmasında savunma teknolojileri: her biri bir kez harcanır."""
    k = 1.0
    for e, v in (('tech_backup-shields', 0.15), ('tech_battle-repair-bot', 0.12)):
        if _stock(bot).get(e, 0) > 0 and use(bot, e):
            k += v
    return k


# ------------------------------------------------------------------------------------------------------------ fırlatıcı
def launcher(bot):
    f = bot.k['gear'].get('launcher')
    return f if f in LAUNCHER['kinds'] else None


def pick_launcher_rocket(bot):
    if not bot.permission.get('rocket', True) or not launcher(bot):
        return None
    s = _stock(bot)
    return next((r for r in reversed(LAUNCHER_ROCKETS) if s.get(r, 0) > 0), None)


def salvo(bot):
    """(kapasite, salvo arası sn)."""
    f = launcher(bot)
    capacity = LAUNCHER['kinds'][f]['capacity'] if f else 0
    return capacity, capacity * LAUNCHER['refill_sec'] + 1.3


def launcher_dps(bot, rocket):
    capacity, gap = salvo(bot)
    return LAUNCHER_AMMO[rocket]['damage'] * capacity / gap if rocket and capacity else 0.0


def candidates(bot):
    """Alışveriş adayları: fırlatıcı (roket izni, 8./10. seviyeden; faydası güç payı)."""
    if not bot.permission.get('rocket', True) or launcher(bot) == HST[1]:
        return []
    power = bot.value()['power']
    out = []
    for f, lv, pay in ((HST[0], 8, 0.12), (HST[1], 10, 0.25)):
        fi = K.price(f)
        if bot.level >= lv and fi and launcher(bot) != f:
            out.append((power * pay * (0.6 + 0.8 * bot.o('aggression')), fi[0], fi[1], f))
    return out


def resupply(bot):
    """Fırlatıcı roketi: HSTRM-01 (uridyum) zenginse, yoksa ECO-10 (kredi) -> alınan."""
    if not launcher(bot) or not bot.permission.get('rocket', True) or not bot.permission.get('shop', True):
        return {}
    s = _stock(bot)
    if sum(s.get(r, 0) for r in LAUNCHER_ROCKETS) >= 50:
        return {}
    t = bot.o('frugality')
    for r, currency, threshold in ((LAUNCHER_ROCKETS[1], 'uridium', 20000), (LAUNCHER_ROCKETS[0], 'credits', 2000000)):
        fi = K.price(r)
        if fi and bot.k[currency] > threshold * (1 + t):
            n = int(min(200, bot.k[currency] * 0.1 // fi[1]))
            if n > 0 and bot.pay(fi[0], n * fi[1]):
                s[r] = s.get(r, 0) + n
                return {r: n}
    return {}
