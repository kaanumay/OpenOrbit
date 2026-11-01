"""Alışveriş: parası yeten en verimli yükseltmeyi almak ya da büyük bir hedef için biriktirmek.

Adaylar katalogdan (lazer, kalkan/hız jeneratörü, dron, gemi): her biri için yeni donanımın güç artışı / fiyat (kredi karşılığı,
1 U = kur kredisi). Tutumlu bot biriktirdiği büyük hedef (Goliath gibi) varken küçük alımlara para harcamaz; dürtüsel bot ara
sıra en iyisi olmayan bir şey de alır (insan hatası).
"""
from ..brain import Goal, target
from .. import catalog as K
from .. import personality as PS

EXCHANGE_RATE = 100                 # 1 uridyum kaç kredi (fiyatlar.json kur)
MAX_TRIP_ITEMS = 15           # bir alışveriş seferinde en çok bu kadar eşya
try:
    import json, os
    EXCHANGE_RATE = json.load(open(os.path.join(K.HERE, 'data', 'prices.json'), encoding='utf8')).get('kur', EXCHANGE_RATE)
except (OSError, ValueError):
    pass


def candidates(bot):
    """[(güç artışı, para, fiyat, loot)]: yuvası olan ya da gemisi daha iyi her alım. Donanım değişene dek botta saklanır."""
    if bot._candidates is None:
        bot._candidates = _candidates(bot)
    return bot._candidates


def _candidates(bot):
    e = bot.k['gear']
    shield_share = bot.shield_share()
    base_values = K.values(e, shield_share)
    base = base_values['power']
    slot = K.outfit(e, shield_share)
    out = []

    def attempt(loot, owner=0, filler=None, force=False):
        f = K.price(loot, owner)
        if not f or f[1] <= 0:
            return
        y = {a: dict(v) if isinstance(v, dict) else v for a, v in e.items()}
        if loot.startswith('ship_'):
            y['gemi'] = loot
        else:
            group = 'lazer' if loot in K.ITEMS['lasers'] else 'kalkan' if loot in K.ITEMS['shield_generators'] else \
                'hiz' if loot in K.ITEMS['speed_generators'] else 'drone'
            y[group][loot] = y[group].get(loot, 0) + 1
        if filler:                                        # dronun boş yuvaları sonra alınacak lazerle dolar
            y['lazer'][filler[0]] = y['lazer'].get(filler[0], 0) + filler[1]
        new_values = K.values(y, shield_share)
        increase = new_values['power'] - base + 0.02 * (new_values['hiz'] - base_values['hiz']) * (0.5 + bot.o('risk'))    # hız güçte yok: kaçmaya, avlanmaya yarar
        if loot.startswith('ship_'):                     # zevk: sevdiği gemi ailesine yakınlık (herkes aynı gemiye yakınsamasın)
            increase *= 1.35 if PS.taste(bot.k['personality']) in loot else 0.9
        if filler:                                        # verim lazerlerin parasıyla birlikte (dronun fiyatına düşen pay)
            lf = K.price(filler[0])
            credit_equiv = lambda c: c[1] * (EXCHANGE_RATE if c[0] == 'U' else 1)
            increase *= credit_equiv(f) / (credit_equiv(f) + filler[1] * credit_equiv(lf))
        if increase > 1e-6 or force:                       # zorla: klan emri (daha iyi olmasa da istenen gemi/eşya)
            out.append((max(increase, 1e-3), f[0], f[1], loot))

    # lazer: yuva boşsa ya da en zayıfından iyiyse; fiyat/hasar sırasıyla ilk birkaç
    lasers = K.lasers()
    for loot in sorted(lasers, key=lasers.get):
        if len(slot['lazer']) < slot['laser_slots'] or lasers[loot] > min(slot['lazer'] or [0]):
            attempt(loot)
    for loot in K.shield_generators():
        attempt(loot)
    for loot in K.speed_generators():
        attempt(loot)
    # dron yalnız lazer yuvası açar: yedek lazer yoksa artışı 0 sayılıyor, Flax hiç alınmıyordu (oyuncu bildirimi 2026-10-31);
    # boş yuvası eldeki en iyi (satın alınabilen) lazerle dolmuş sayılır
    backup = sum(e.get('lazer', {}).values()) - len(slot['lazer'])
    best = max((l for l in e.get('lazer', {}) if l in lasers), key=lasers.get, default=None)
    for loot, d in K.ITEMS['drones'].items():
        n = e.get('drone', {}).get(loot, 0)
        if sum(e.get('drone', {}).values()) < K.ITEMS['max_drones'] and K.price(loot, n):
            missing = max(0, d.get('yuva', 1) - backup)
            attempt(loot, n, (best, missing) if best and missing else None)
    current = K.ITEMS['ships'].get(e['gemi'], {})
    for loot, g in K.ships().items():
        if loot != e['gemi'] and g['hp'] + 20000 * (g['laser'] + g['generators']) > current.get('hp', 0) + 20000 * (
                current.get('laser', 0) + current.get('generators', 0)):
            attempt(loot)
    wanted = bot.k.get('savings')
    if wanted and not any(c[3] == wanted for c in out) and (wanted.startswith('ship_') or any(
            wanted in K.ITEMS[g] for g in ('lasers', 'shield_generators', 'speed_generators', 'drones'))):
        attempt(wanted, e.get('drone', {}).get(wanted, 0), force=True)
    from .. import extras as EX
    out += EX.candidates(bot)                               # CPU'lar ve onarım robotları (faydası güç payı olarak)
    from .. import technology as TECH
    out += TECH.candidates(bot)                               # roket fırlatıcısı
    return out


def income(bot):
    """Saatlik tahmini kazanç {'C': kredi, 'U': uridyum}: bulunduğu haritada kasarsa (katalog.harita_degerlendir)."""
    d = bot.value()
    try:
        r = K.evaluate_map(int(bot.game_map), d['dps'], d['ehp'], 0.5)
    except (KeyError, ValueError, TypeError):
        return {'C': 0.0, 'U': 0.0}
    return {'C': r['credits_per_hour'], 'U': r['uridium_per_hour'] + 25}           # +25: bonus kutuları, görev ödülleri


def candidate(bot):
    """-> (şimdi alınacak (artis, para, fiyat, loot) ya da None, biriktirilen hedef ya da None).

    Gerçek oyuncu gibi hedefli: yakında (tutumluluğa göre 1-2,5 saatlik kazançla) ulaşabileceği en verimli yükseltme hedeftir;
    parası yetiyorsa onu alır. Yetmiyorsa ancak hedef kadar verimli (en az %70) küçük bir alım yapar, yoksa biriktirir. Önceden
    yeten en verimli şeyi hemen alıyordu: SLL-01'e (50.000 C) para biriktirirken sırayla 2.000-8.000 C'lik hız jeneratörleri
    ve MP-1 alıp tek yuvalı Phoenix'te birbirinin yerine koyuyordu (paket analizi 2026-10-29)."""
    all_candidates = candidates(bot)
    if not all_candidates:
        return None, None
    m = bot.game_settings.multiplier('shop_price')                  # profilin mağaza fiyatı çarpanı
    if m != 1.0:
        all_candidates = [(a, p, f * m, l) for a, p, f, l in all_candidates]
    currency = {'C': bot.k['kredi'], 'U': bot.k['uridyum']}
    currency['C'] = max(0, currency['C'] - bot.clan_savings())                     # klan kuracak: kuruluş bedelini biriktirir
    credit_equiv = lambda c: c[2] * (EXCHANGE_RATE if c[1] == 'U' else 1)
    # verim: artış / (fiyat + servetin çeyreği): az parada kredi başına verim, çok parada artışın büyüklüğü öne geçer (zengin bot
    # 80M kredi ve 2M uridyumla +3,4 güçlü Apis yerine 2.000 C'lik +0,04'lük hız jeneratörünü seçiyordu; Laya denemesi 2026-10-31)
    wealth = currency['C'] + currency['U'] * EXCHANGE_RATE
    efficiency = lambda c: c[0] / max(1.0, credit_equiv(c) + 0.25 * wealth) * 1e5
    t = bot.o('frugality')
    hedefi = next((c for c in all_candidates if c[3] == bot.k.get('savings')), None)
    if hedefi is not None:                       # kendi seçtiği biriktirme hedefi (ajanın biriktir aracı): yalnız onu alır
        if currency[hedefi[1]] >= hedefi[2]:
            return hedefi, hedefi
        # hedefin birikimini geciktirmeyen alımlar serbest (başka para birimi ya da hedefin üstünde kalan para): önceden yalnız
        # hedefe bakıyordu, 80.000 U'luk gemiye biriktiren bot 66M kredisiyle kalkan/motor almadan duruyordu (oyuncu bildirimi 2026-11-01)
        free = [c for c in all_candidates if c[1] != hedefi[1] and currency[c[1]] >= c[2] * (1 + 0.3 * bot.o('frugality'))
                   or c[1] == hedefi[1] and currency[c[1]] - c[2] >= hedefi[2]]
        return max(free, key=lambda c: c[0], default=None), hedefi
    affordable = [c for c in all_candidates if currency[c[1]] >= c[2] * (1 + 0.3 * t)]        # tutumlu bot biraz yedek bırakır
    g = income(bot)
    horizon = 1.0 + 1.5 * t
    reachable = [c for c in all_candidates if c[2] * (1 + 0.3 * t) <= currency[c[1]] + g[c[1]] * horizon]
    target_candidate = max(reachable, key=efficiency, default=None)
    # uzak biriktirme hedefi (panel, sohbet): parası yetmeyen en büyük artış
    remaining = [c for c in all_candidates if c not in affordable]
    savings = max(remaining, key=lambda c: c[0] * (0.5 + t) - credit_equiv(c) / 5e6, default=None)
    if target_candidate is not None and target_candidate not in affordable:
        savings = target_candidate
    if not affordable:
        return None, savings
    if bot.r.random() < 0.05 * (1 - t):                                     # dürtüsel alım (insan hatası)
        return bot.r.choice(affordable), savings
    if target_candidate is None or target_candidate in affordable:
        return max(affordable, key=efficiency), savings
    iyi = [c for c in affordable if efficiency(c) >= 0.7 * efficiency(target_candidate)]
    return (max(iyi, key=efficiency) if iyi else None), savings


@target
class Shopping(Goal):
    name = 'shopping'
    permission = 'shop'
    min_sec = 5

    def eligible(self, bot, b):
        return b.shopping[0] is not None

    def points(self, bot, b):
        increase = b.shopping[0][0]
        return min(1.6, 0.45 + increase / max(1.0, bot.value()['power']) * 3 + 0.2 * bot.o('ambition'))

    def start(self, bot, b):
        # bir alışveriş seferinde parası yettikçe sırayla alır (en çok SEFER_ALIM): önceden sefer başına tek eşya alıyordu, 10M
        # kredili bot bir saatte 8 eşya alıp paranın %80'ini harcamadan duruyordu (oyuncu bildirimi 2026-10-31)
        c = b.shopping[0]
        for _ in range(MAX_TRIP_ITEMS):
            increase, currency, price, loot = c
            if not bot.pay(currency, price):
                break
            bot.add(loot)
            bot.ist('purchase')
            bot.mood.it(morale=0.12 + min(0.3, increase / max(1.0, bot.value()['power'])))
            bot.event('purchase', esya=loot, price=price, currency=currency)
            if loot.startswith('ship_'):
                bot.event('yeni_gemi', esya=loot)
            if bot.k.get('savings') == loot:
                bot.k['savings'] = None                  # biriktirdiği şeye kavuştu (ajanın biriktir aracı)
            bot._candidates = None                          # (gemi değişmese de kalan yuvalar ve para değişti)
            c = candidate(bot)[0]
            if c is None:
                break
        bot.plan['finished'] = True

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
