"""Botun görünüşü: gemi tasarımı, dronları ve formasyonu, unvanı, kapı halkaları. Oyuncunun öteki oyunculara giden mesajlarıyla
(game.gorunum): ShipCreateCommand.typeId ve galaxyGatesDone, "0|n|t" unvan, "0|n|d" dronlar.

Tasarım ve formasyon oyuncu gibi mağaza fiyatıyla alınır: birikiminin küçük bir payıysa, gösterişe düşkünlüğüne göre. Tasarım
yalnız kozmetik olanlardan (bonuslu tasarımlar gücü değiştirir; güç hesabı tasarım bilmez). Formasyon kişiliğe göre kalıcı:
saldırgan Arrow/Pincer, temkinli Turtle, kasıcı Star. Unvan oyunun başarım eşiklerinden (uzaylı, EP, onur); gösterip
göstermemek kişiliğe bağlı. Seçimler bot kaydında (ekip['tasarim'], k['formasyon'], k['formasyonlar']).

Dron tasarımları (oyuncudaki gibi dron başına, mağaza fiyatıyla): bonuslu Havoc (saldırgan: tüm dronlar Havoc ise +%10 dron lazeri) ve
Hercules (temkinli: +%20 can), ayrıca kozmetik görünümler. Bot kaydında ekip['dron_tasarim'] = {'tasarim': [loot], 'gorunum': [loot]},
dronların sıralı dizilimine (loot adına göre, dizgideki sıra) göre; tüm dronlar aynı bonuslu tasarımdaysa güç hesabına katılır
(katalog.degerler). Bazı botlar birini toplar (eşleşen takım), bazıları parası yetmeyince öbürüyle karıştırır.
"""
import math, zlib

from legacy_protocol import legacy
from . import catalog as K

FORMATION = {'drone_formation_default': 0, 'drone_formation_f-01-tu': 1, 'drone_formation_f-02-ar': 2,
             'drone_formation_f-04-st': 4, 'drone_formation_f-05-pi': 5}
MIN_DRONES = {'drone_formation_f-02-ar': 4, 'drone_formation_f-05-pi': 6}
# (unvan, istatistik, eşik): oyunun başarımları (data/basarimlar.json achievement_destroy_aliens, _experience, _honor)
TITLES = (('title_achievement_honor-2', 'honor', 2500000), ('title_achievement_experience-2', 'ep', 10000000000),
            ('title_achievement_destroy_aliens-2', 'npc', 1000000), ('title_achievement_honor-1', 'honor', 450000),
            ('title_achievement_experience-1', 'ep', 100000000), ('title_achievement_destroy_aliens-1', 'npc', 1000))


def _stable_hash(bot, salt):
    return zlib.crc32(('%s|%s' % (salt, bot.name)).encode())


def showiness(bot):
    """Gösterişe düşkünlük (0-1): tutumlu olmayan, rekabetçi ve sosyal olan."""
    return max(0.0, min(1.0, 0.5 * (1 - bot.o('frugality')) + 0.3 * bot.o('rekabet') + 0.2 * bot.o('sociability')))


def _can_afford(bot, currency, price):
    """Birikiminin küçük bir payıysa (tutumluya göre 4-10 katı varsa)."""
    return bot.k['credits' if currency == 'C' else 'uridium'] >= price * (4 + 6 * bot.o('frugality'))


# ------------------------------------------------------------------------------------------------------------ satın alma
def cosmetic_designs(ship):
    return sorted(l for l, f in K.prices().items() if l.startswith(ship + '_design_') and l not in K.ITEMS['designs'])


def drone_count(bot):
    return sum(bot.k['gear'].get('drone', {}).values())


def drone_sequence(bot):
    """Dronların loot'ları, dizgideki sırayla (loot adına göre)."""
    return [d for d, k in sorted(bot.k['gear'].get('drone', {}).items()) for _ in range(k) if d in K.ITEMS['drones']]


def drone_ids(bot):
    """Her dron için istemcinin (tasarım, görünüm) kimlikleri (0 standart), dron_dizisi sırasıyla."""
    dt = bot.k['gear'].get('drone_design') or {}
    t, g = dt.get('design') or [], dt.get('appearance') or []
    designs = K.ITEMS['drone_designs']
    out = []
    for i, _ in enumerate(drone_sequence(bot)):
        out.append((designs.get(t[i] if i < len(t) else '', {}).get('id', 0), designs.get(g[i] if i < len(g) else '', {}).get('id', 0)))
    return out


def drone_preference(bot):
    """Bonuslu dron tasarımı: saldırgan Havoc, temkinli Hercules."""
    return 'drone_designs_havoc' if bot.o('aggression') >= 0.5 else 'drone_designs_hercules'


def drone_looks():
    """Mağazada satılan kozmetik dron görünümleri (etkinlik fiyatlı pahalılar hariç: en çok 100.000)."""
    designs = K.ITEMS['drone_designs']
    return sorted(l for l, v in designs.items() if v.get('slot') == 'visual' and K.price(l) and K.price(l)[1] <= 100000
                  and not v.get('per_event'))


def drone_shopping(bot):
    """Bir dron daha: önce bonuslu tasarım (parası yetince; üçte biri parası yetmeyince öbür bonuslu tasarımla karıştırır), sonra
    bazen kozmetik görünüm. Çağrı başına en çok bir alım."""
    n = len(drone_sequence(bot))
    if not n:
        return
    dt = bot.k['gear'].setdefault('drone_design', {})
    designs, looks = dt.setdefault('design', []), dt.setdefault('appearance', [])
    del designs[n:], looks[n:]
    designs += [''] * (n - len(designs))
    looks += [''] * (n - len(looks))
    ist = drone_preference(bot)
    mixed = _stable_hash(bot, 'drone') % 3 == 0
    order = [ist] + ([x for x in ('drone_designs_havoc', 'drone_designs_hercules') if x != ist] if mixed else [])
    for i in range(n):
        if designs[i]:
            continue
        for loot in order:
            f = K.price(loot)
            if f and _can_afford(bot, *f) and bot.pay(*f):
                designs[i] = loot
                bot.event('new_design', item=loot)
                bot.loadout_changed()
                return
        break                                            # parası yetmedi: sıradaki dron beklesin, kozmetiğe geç
    option = drone_looks()
    if option and bot.r.random() < 0.5 * showiness(bot):
        loot = option[_stable_hash(bot, 'appearance') % len(option)]
        f = K.price(loot)
        for i in range(n):
            if not looks[i] and f and _can_afford(bot, *f) and bot.pay(*f):
                looks[i] = loot
                bot.event('new_design', item=loot)
                return


def formation_preference(bot):
    """Kişiliğe göre istenen formasyon (dron sayısı yetenlerden ilki)."""
    n = drone_count(bot)
    if not n:
        return 'drone_formation_default'
    if bot.o('aggression') > 0.65:
        order = ('drone_formation_f-05-pi', 'drone_formation_f-02-ar')
    elif bot.o('risk') < 0.35:
        order = ('drone_formation_f-01-tu',)
    elif bot.o('ambition') > 0.6:
        order = ('drone_formation_f-04-st', 'drone_formation_f-02-ar')
    else:
        order = ('drone_formation_f-02-ar', 'drone_formation_f-01-tu')
    return next((f for f in order if n >= MIN_DRONES.get(f, 0)), 'drone_formation_default')


def shopping(bot, now):
    """Yarım saatte bir: tasarım ve formasyon (mağaza izni ve parası yetiyorsa)."""
    if now < bot.__dict__.get('_cosmetic_t', 0) or not bot.permission.get('shop', True):
        return
    bot._cosmetic_t = now + 1800
    e = bot.k['gear']
    designs = e.get('design')
    if not designs or not designs.startswith(e['ship'] + '_design_'):
        option = cosmetic_designs(e['ship'])
        if option and bot.r.random() < 0.4 * showiness(bot):
            loot = option[_stable_hash(bot, e['ship']) % len(option)]          # her botun zevki: aynı gemide hep aynı tasarımı ister
            f = K.price(loot)
            if f and _can_afford(bot, *f) and bot.pay(*f):
                e['design'] = loot
                bot.event('new_design', item=loot)
    drone_shopping(bot)
    owner = bot.k.setdefault('formations', ['drone_formation_default'])
    ist = formation_preference(bot)
    if ist not in owner:
        f = K.price(ist)
        if f and _can_afford(bot, *f) and bot.pay(*f):
            owner.append(ist)
    if ist in owner:
        bot.k['formation'] = ist
    elif bot.k.get('formation') not in owner or drone_count(bot) < MIN_DRONES.get(bot.k.get('formation'), 0):
        bot.k['formation'] = 'drone_formation_default'


# ------------------------------------------------------------------------------------------------------------ görünüş
def tip(bot):
    """ShipCreateCommand.typeId: giyilen tasarım ya da gemi."""
    e = bot.k['gear']
    t = e.get('design')
    return t if t and t.startswith(e['ship'] + '_design_') else e['ship']


def rings(bot):
    """galaxyGatesDone: tamamladığı kapıların bitleri (kapi.RINGS)."""
    import galaxy_gates as GT
    return sum(GT.RINGS.get(k, 0) for k in set((bot.k.get('gate') or {}).get('done', ())))


def drone_level(bot):
    """Dronlar uzaylı öldürdükçe seviye atlar (oyunda dron puanı): 200, 800, 1.800, 3.200, 5.000 uzaylıda 2-6."""
    return 1 + min(5, int(math.sqrt(bot.k['stats'].get('npc', 0) / 200.0)))


def title(bot):
    """Kazandığı en üst unvan; göstermeyi seçmeyen (gösterişsiz) bot için None."""
    if showiness(bot) < 0.35:
        return None
    st = {'honor': bot.k['honor'], 'ep': bot.k['ep'], 'npc': bot.k['stats'].get('npc', 0)}
    return next((u for u, a, threshold in TITLES if st[a] >= threshold), None)


def messages(n):
    """Gemiyle birlikte giden unvan ve dron mesajları (game.gorunum gibi)."""
    import achievement as BS
    b = n.bot
    out = []
    u = title(b)
    if u in BS.TITLES:
        out.append(legacy('0|n|t|%d|%d|%s' % (n.id, BS.TITLES[u], u)))
    drones = drone_sequence(b)
    if drones:
        lv = drone_level(b)
        body = '|'.join('%d|%d|%d|%d' % (K.ITEMS['drones'][d]['type'], lv, t, g) for d, (t, g) in zip(drones, drone_ids(b)))
        f = FORMATION.get(b.k.get('formation') or '', 0)
        out.append(legacy('0|n|d|%d|%d|%s' % (n.id, f, body)))
    return out
