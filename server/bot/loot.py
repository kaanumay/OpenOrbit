"""Ganimet: anahtarlı kutular, anahtarlar, boosterlar, uzaylıların ek ganimeti ve Assembly (oyuncunun kuralları: loot.py,
dunya.extra_loot, assembly.py, booster.py).

  kutu      haritadaki anahtarlı kutuyu türünün anahtarıyla açar; yeşil kutunun anahtarı yoksa uridyumla alır (oyuncudaki
            autoBuyGreenBootyKeys) ama yalnız kutunun beklenen değeri anahtarın fiyatından yüksekse ve kişiliğe göre (tutumlu bot
            uridyumunu harcamaz); ödül kutunun tablosundan ağırlıkla
  ek        uzaylının ek ganimeti (npc.json ek_odul: Scrapium, Mucosum, günlük dosyası …) stoğa
  assembly  o an görünür tariflerden (tek oyunculu: kayıttaki hepsi; etkinlik parası isteyenler etkinlik sürerken ya da elde para
            varken) malzemesi elde olan ve sonucu harcadığından değerli olanı üretir: anahtar, teknoloji eşyası, cephane, ekipman
  booster   10 saat (booster verisi); EP, onur, kaynak, hasar, can, kalkan payları, türün tavanıyla
Değerler kredi karşılığı (1 U = 100 C): para yüzünden, cephane ve eşya mağaza fiyatından, anahtar kutusunun beklenen değerinden.
"""
import json, os, random

from . import catalog as K

EXCHANGE_RATE = 100
import loot as LOOT                                   # noqa: E402  (oyunun ganimet modülü: kutular, haritalar, takvim)

RECIPES = json.load(open(os.path.join(K.HERE, 'data', 'recipes.json'), encoding='utf8'))['tarifler']
BOOSTER = K.ITEMS['boosterlar']
ORE_LOOT = {v: int(k) for k, v in K.ITEMS['cevherler']['turler'].items()}     # resource_ore_* -> kargo cevheri
CURRENCY = {'currency_credits': 'kredi', 'currency_uridium': 'uridyum', 'currency_experience': 'ep', 'currency_honour': 'onur'}
_ev = {}


def stock(bot):
    from . import weapons as WP
    return WP.stock(bot)


# ------------------------------------------------------------------------------------------------------------ değer
def value(loot, n=1, depth=0):
    """Eşyanın bota yaklaşık değeri (kredi)."""
    if loot in CURRENCY:
        return n * {'kredi': 1, 'uridyum': EXCHANGE_RATE, 'ep': 0.3, 'onur': 3}[CURRENCY[loot]]
    if loot in ORE_LOOT:
        return n * K.ore_prices(0).get(ORE_LOOT[loot], 0)
    if loot.startswith('resource_booty-key') and depth < 1:
        kind = LOOT.KEYS.get(loot)
        return n * box_value(kind, depth + 1) if kind else 0
    if loot.startswith('booster_'):
        return n * 3000
    f = K.price(loot)
    if f and f[1] > 0:
        v = n * f[1] * (EXCHANGE_RATE if f[0] == 'U' else 1)
        return v * 0.3 if loot.startswith(('ship_', 'equipment_', 'drone_')) else v     # ganimetten gelen eşya: işine yaramazsa satış değeri
    return 0


def box_value(kind, depth=0):
    """Kutunun beklenen değeri (ödül tablosunun ağırlıklı ortalaması)."""
    if kind in _ev:
        return _ev[kind]
    rows = LOOT.BOXES[kind].get('odul') or []
    total = sum(r[2] for r in rows) or 1
    v = 0.0
    for loot, n, w in rows:
        if loot == LOOT.PACKAGE:
            v += w * sum(value(l, c, depth) for l, c in n)
        else:
            v += w * value(loot, n, depth)
    _ev[kind] = v / total
    return _ev[kind]


# ------------------------------------------------------------------------------------------------------------ ödül
def give(bot, loot, n):
    """Ödülü bota: para kazanç, cevher kargoya, booster etkin, eşya ve cephane bot.ekle, gerisi (anahtar, kaynak) stoğa."""
    if loot in CURRENCY:
        bot.reward('kutu', **{CURRENCY[loot]: n})
    elif loot in ORE_LOOT:
        bot.add_cargo({ORE_LOOT[loot]: n})
    elif loot.startswith('booster_'):
        booster(bot, loot)
    elif loot.startswith(('ship_', 'equipment_', 'ammunition_', 'tech_', 'drone_')) and bot.add(loot, n):
        pass
    else:
        s = stock(bot)
        s[loot] = s.get(loot, 0) + int(n)


def booster(bot, loot):
    """Booster 10 saat: k['booster'] {tür: [değer, bitiş]} (aynı türden ikincisi süreyi uzatır)."""
    b = bot.k.setdefault('booster', {})
    now = bot.hour()
    for kind, v in (BOOSTER['turler'].get(loot) or {}).items():
        e = b.get(kind)
        end_time = max(now, e[1] if e else now) + BOOSTER['sure_sn']
        b[kind] = [min(BOOSTER['tavan'].get(kind, v), v), end_time]
    bot.loadout_changed()


def booster_share(bot, kind):
    e = (bot.k.get('booster') or {}).get(kind)
    return e[0] / 100.0 if e and e[1] > bot.hour() else 0.0


def extra_loot(bot, tip, n=1):
    """Uzaylının ek ganimeti (toplanabilir kaynaklar, günlük dosyası) stoğa."""
    import world as WD
    for loot, spec in ((K.NPC['tipler'].get(str(tip)) or {}).get('ek_odul') or {}).items():
        c = sum(WD.extra_count(spec) for _ in range(min(int(n), 20))) * (n / min(int(n), 20) if n > 20 else 1)
        if c > 0:
            give(bot, loot, int(c))


# ------------------------------------------------------------------------------------------------------------ kutular
def key_item(kind):
    return LOOT.BOXES[kind]['anahtar']


def can_open(bot, kind):
    """Kutuyu açabilir mi / açmaya değer mi: anahtarı varsa evet; yeşil kutu için anahtar alabilir (uridyumu ve kişiliği izin
    veriyorsa ve kutu fiyatından değerliyse). Anahtar alınırsa stoğa eklenir."""
    if not bot.permission.get('ganimet', True):
        return False
    key = key_item(kind)
    if stock(bot).get(key, 0) > 0:
        return True
    f = K.price(key)
    if key != LOOT.GREEN_KEY or not f or not bot.permission.get('magaza', True):
        return False
    price = f[1] * bot.game_settings.multiplier('magaza_fiyat')
    t = bot.o('tutumluluk')
    if box_value(kind) < price * EXCHANGE_RATE * (0.8 + 0.8 * t) or bot.k['uridyum'] < price * (2 + 4 * t):
        return False
    if not bot.pay('U', price):
        return False
    stock(bot)[key] = stock(bot).get(key, 0) + 1
    bot.ist('anahtar_alim')
    return True


def open_box(bot, kind, rng=random):
    """Anahtar harcanır, tablodan ağırlıkla bir ödül -> [(loot, adet)]."""
    s = stock(bot)
    key = key_item(kind)
    if s.get(key, 0) <= 0:
        return []
    s[key] -= 1
    if not s[key]:
        del s[key]
    rows = LOOT.BOXES[kind].get('odul') or []
    if not rows:
        return []
    r = rng.choices(rows, weights=[x[2] for x in rows])[0]
    out = list(r[1]) if r[0] == LOOT.PACKAGE else [(r[0], r[1])]
    for loot, n in out:
        give(bot, loot, n)
    bot.ist('kutu_acti')
    bot.event('kutu_acti', kutu=LOOT.BOXES[kind]['ad'])
    return out


_active = {}


def active_boxes(name):
    """Haritada şimdi doğan anahtarlı kutular [(tür, adet)]: takvim hesabı ağır, dakikada bir (harita başına)."""
    import time
    t = time.time()
    e = _active.get(name)
    if e is None or t - e[0] > 60:
        e = _active[name] = (t, [(k, n) for k, n in LOOT.spawns(name) if LOOT.active(k)])
    return e[1]


def abstract(bot, dt, y):
    """Soyutta haritanın anahtarlı kutularına rastlama: kutu sayısı / yeniden doğma, haritadaki botlarla paylaşılır."""
    import map_links as H
    if not bot.permission.get('ganimet', True):
        return
    crowd = len(y.on_map.get(bot.game_map, ())) if y is not None else 1
    for kind, count in active_boxes(H.name(bot.game_map)):
        ratio = count * dt / max(60.0, sum(LOOT.BOXES[kind]['yeniden_sn']) / 2) / max(1.0, 0.3 * crowd)
        if bot.r.random() < ratio and can_open(bot, kind):
            open_box(bot, kind, bot.r)


# ------------------------------------------------------------------------------------------------------------ assembly
def _yeter(bot, parts):
    s = stock(bot)
    for p, n in parts.items():
        if p in CURRENCY:
            if bot.k[CURRENCY[p]] < n:
                return False
        elif p.startswith('equipment_'):
            if not any(p in v for v in bot.k['ekip'].values() if isinstance(v, dict)) and bot.k['ekip'].get('fircatici') != p:
                return False
        elif s.get(p, 0) < n:
            return False
    return True


def _spend(bot, parts):
    s = stock(bot)
    for p, n in parts.items():
        if p in CURRENCY:
            bot.k[CURRENCY[p]] -= n
        elif p.startswith('equipment_'):
            if bot.k['ekip'].get('fircatici') == p:
                bot.k['ekip']['fircatici'] = None
        else:
            s[p] -= n
            if not s[p]:
                del s[p]


MATERIALS = [(k, tuple(p for p in r['parcalar'] if p not in CURRENCY)) for k, r in RECIPES.items()
           if any(p not in CURRENCY for p in r['parcalar']) and 'test' not in k]      # test tarifleri oyuncuya da kapalı      # para tarifleri teknoloji.uret'te


def assembly(bot):
    """Malzemesi elde olan tariflerden en değerlisini üretir (sonucu harcadığından değerliyse; para harcayanlar teknoloji.uret'te).
    Kullanım sınırları: USABLE_ONCE bir kez. -> üretilen sonuç ya da None."""
    if not bot.permission.get('assembly', True):
        return None
    now = bot.hour()
    if now < bot.__dict__.get('_asm_t', 0):
        return None
    bot._asm_t = now + 600                               # oyuncu Assembly'ye arada bakar: 10 dakikada bir
    s = stock(bot)
    if not any(k.startswith('resource_') for k in s):
        return None
    crafted = bot.k.setdefault('assembly', {})
    en, best_score = None, 0.0
    for key, need in MATERIALS:
        if not all(p in s or p.startswith('equipment_') for p in need):
            continue
        r = RECIPES[key]
        if r['kullanim'] == 'USABLE_ONCE' and crafted.get(key):
            continue
        if not _yeter(bot, r['parcalar']):
            continue
        earnings = sum(value(l, n) for l, n in r['sonuc'].items())
        cost = sum(value(p, n) for p, n in r['parcalar'].items() if not p.startswith('resource_collectable'))
        if earnings - cost > best_score:
            en, best_score = key, earnings - cost
    if en is None:
        return None
    r = RECIPES[en]
    _spend(bot, r['parcalar'])
    for loot, n in r['sonuc'].items():
        give(bot, loot, n)
    crafted[en] = crafted.get(en, 0) + 1
    bot.ist('assembly')
    return en
