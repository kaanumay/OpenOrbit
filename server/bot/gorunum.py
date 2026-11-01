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

from eski_protokol import legacy
from . import katalog as K

FORMASYON = {'drone_formation_default': 0, 'drone_formation_f-01-tu': 1, 'drone_formation_f-02-ar': 2,
             'drone_formation_f-04-st': 4, 'drone_formation_f-05-pi': 5}
ASGARI_DRON = {'drone_formation_f-02-ar': 4, 'drone_formation_f-05-pi': 6}
# (unvan, istatistik, eşik): oyunun başarımları (data/basarimlar.json achievement_destroy_aliens, _experience, _honor)
UNVANLAR = (('title_achievement_honor-2', 'onur', 2500000), ('title_achievement_experience-2', 'ep', 10000000000),
            ('title_achievement_destroy_aliens-2', 'npc', 1000000), ('title_achievement_honor-1', 'onur', 450000),
            ('title_achievement_experience-1', 'ep', 100000000), ('title_achievement_destroy_aliens-1', 'npc', 1000))


def _sabit(bot, tuz):
    return zlib.crc32(('%s|%s' % (tuz, bot.ad)).encode())


def gosteris(bot):
    """Gösterişe düşkünlük (0-1): tutumlu olmayan, rekabetçi ve sosyal olan."""
    return max(0.0, min(1.0, 0.5 * (1 - bot.o('tutumluluk')) + 0.3 * bot.o('rekabet') + 0.2 * bot.o('sosyallik')))


def _alabilir(bot, para, fiyat):
    """Birikiminin küçük bir payıysa (tutumluya göre 4-10 katı varsa)."""
    return bot.k['kredi' if para == 'C' else 'uridyum'] >= fiyat * (4 + 6 * bot.o('tutumluluk'))


# ------------------------------------------------------------------------------------------------------------ satın alma
def kozmetik_tasarimlar(gemi):
    return sorted(l for l, f in K.fiyatlar().items() if l.startswith(gemi + '_design_') and l not in K.ESYA['tasarimlar'])


def dron_sayisi(bot):
    return sum(bot.k['ekip'].get('dron', {}).values())


def dron_dizisi(bot):
    """Dronların loot'ları, dizgideki sırayla (loot adına göre)."""
    return [d for d, k in sorted(bot.k['ekip'].get('dron', {}).items()) for _ in range(k) if d in K.ESYA['dronlar']]


def dron_kimlikleri(bot):
    """Her dron için istemcinin (tasarım, görünüm) kimlikleri (0 standart), dron_dizisi sırasıyla."""
    dt = bot.k['ekip'].get('dron_tasarim') or {}
    t, g = dt.get('tasarim') or [], dt.get('gorunum') or []
    tas = K.ESYA['dron_tasarimlari']
    out = []
    for i, _ in enumerate(dron_dizisi(bot)):
        out.append((tas.get(t[i] if i < len(t) else '', {}).get('id', 0), tas.get(g[i] if i < len(g) else '', {}).get('id', 0)))
    return out


def dron_tercihi(bot):
    """Bonuslu dron tasarımı: saldırgan Havoc, temkinli Hercules."""
    return 'drone_designs_havoc' if bot.o('saldirganlik') >= 0.5 else 'drone_designs_hercules'


def dron_gorunumleri():
    """Mağazada satılan kozmetik dron görünümleri (etkinlik fiyatlı pahalılar hariç: en çok 100.000)."""
    tas = K.ESYA['dron_tasarimlari']
    return sorted(l for l, v in tas.items() if v.get('yuva') == 'visual' and K.fiyat(l) and K.fiyat(l)[1] <= 100000
                  and not v.get('etkinlik_basina'))


def dron_alisveris(bot):
    """Bir dron daha: önce bonuslu tasarım (parası yetince; üçte biri parası yetmeyince öbür bonuslu tasarımla karıştırır), sonra
    bazen kozmetik görünüm. Çağrı başına en çok bir alım."""
    n = len(dron_dizisi(bot))
    if not n:
        return
    dt = bot.k['ekip'].setdefault('dron_tasarim', {})
    tas, gor = dt.setdefault('tasarim', []), dt.setdefault('gorunum', [])
    del tas[n:], gor[n:]
    tas += [''] * (n - len(tas))
    gor += [''] * (n - len(gor))
    ist = dron_tercihi(bot)
    karisik = _sabit(bot, 'dron') % 3 == 0
    sira = [ist] + ([x for x in ('drone_designs_havoc', 'drone_designs_hercules') if x != ist] if karisik else [])
    for i in range(n):
        if tas[i]:
            continue
        for loot in sira:
            f = K.fiyat(loot)
            if f and _alabilir(bot, *f) and bot.ode(*f):
                tas[i] = loot
                bot.olay('yeni_tasarim', esya=loot)
                bot.ekip_degisti()
                return
        break                                            # parası yetmedi: sıradaki dron beklesin, kozmetiğe geç
    secenek = dron_gorunumleri()
    if secenek and bot.r.random() < 0.5 * gosteris(bot):
        loot = secenek[_sabit(bot, 'gorunum') % len(secenek)]
        f = K.fiyat(loot)
        for i in range(n):
            if not gor[i] and f and _alabilir(bot, *f) and bot.ode(*f):
                gor[i] = loot
                bot.olay('yeni_tasarim', esya=loot)
                return


def formasyon_tercihi(bot):
    """Kişiliğe göre istenen formasyon (dron sayısı yetenlerden ilki)."""
    n = dron_sayisi(bot)
    if not n:
        return 'drone_formation_default'
    if bot.o('saldirganlik') > 0.65:
        sira = ('drone_formation_f-05-pi', 'drone_formation_f-02-ar')
    elif bot.o('risk') < 0.35:
        sira = ('drone_formation_f-01-tu',)
    elif bot.o('hirs') > 0.6:
        sira = ('drone_formation_f-04-st', 'drone_formation_f-02-ar')
    else:
        sira = ('drone_formation_f-02-ar', 'drone_formation_f-01-tu')
    return next((f for f in sira if n >= ASGARI_DRON.get(f, 0)), 'drone_formation_default')


def alisveris(bot, now):
    """Yarım saatte bir: tasarım ve formasyon (mağaza izni ve parası yetiyorsa)."""
    if now < bot.__dict__.get('_kozmetik_t', 0) or not bot.izin.get('magaza', True):
        return
    bot._kozmetik_t = now + 1800
    e = bot.k['ekip']
    tas = e.get('tasarim')
    if not tas or not tas.startswith(e['gemi'] + '_design_'):
        secenek = kozmetik_tasarimlar(e['gemi'])
        if secenek and bot.r.random() < 0.4 * gosteris(bot):
            loot = secenek[_sabit(bot, e['gemi']) % len(secenek)]          # her botun zevki: aynı gemide hep aynı tasarımı ister
            f = K.fiyat(loot)
            if f and _alabilir(bot, *f) and bot.ode(*f):
                e['tasarim'] = loot
                bot.olay('yeni_tasarim', esya=loot)
    dron_alisveris(bot)
    sahip = bot.k.setdefault('formasyonlar', ['drone_formation_default'])
    ist = formasyon_tercihi(bot)
    if ist not in sahip:
        f = K.fiyat(ist)
        if f and _alabilir(bot, *f) and bot.ode(*f):
            sahip.append(ist)
    if ist in sahip:
        bot.k['formasyon'] = ist
    elif bot.k.get('formasyon') not in sahip or dron_sayisi(bot) < ASGARI_DRON.get(bot.k.get('formasyon'), 0):
        bot.k['formasyon'] = 'drone_formation_default'


# ------------------------------------------------------------------------------------------------------------ görünüş
def tip(bot):
    """ShipCreateCommand.typeId: giyilen tasarım ya da gemi."""
    e = bot.k['ekip']
    t = e.get('tasarim')
    return t if t and t.startswith(e['gemi'] + '_design_') else e['gemi']


def halkalar(bot):
    """galaxyGatesDone: tamamladığı kapıların bitleri (kapi.RINGS)."""
    import kapi as KP
    return sum(KP.RINGS.get(k, 0) for k in set((bot.k.get('kapi') or {}).get('tamam', ())))


def dron_seviyesi(bot):
    """Dronlar uzaylı öldürdükçe seviye atlar (oyunda dron puanı): 200, 800, 1.800, 3.200, 5.000 uzaylıda 2-6."""
    return 1 + min(5, int(math.sqrt(bot.k['istat'].get('npc', 0) / 200.0)))


def unvan(bot):
    """Kazandığı en üst unvan; göstermeyi seçmeyen (gösterişsiz) bot için None."""
    if gosteris(bot) < 0.35:
        return None
    st = {'onur': bot.k['onur'], 'ep': bot.k['ep'], 'npc': bot.k['istat'].get('npc', 0)}
    return next((u for u, a, esik in UNVANLAR if st[a] >= esik), None)


def mesajlar(n):
    """Gemiyle birlikte giden unvan ve dron mesajları (game.gorunum gibi)."""
    import basarim as BS
    b = n.bot
    out = []
    u = unvan(b)
    if u in BS.TITLES:
        out.append(legacy('0|n|t|%d|%d|%s' % (n.id, BS.TITLES[u], u)))
    dronlar = dron_dizisi(b)
    if dronlar:
        sv = dron_seviyesi(b)
        govde = '|'.join('%d|%d|%d|%d' % (K.ESYA['dronlar'][d]['tur'], sv, t, g) for d, (t, g) in zip(dronlar, dron_kimlikleri(b)))
        f = FORMASYON.get(b.k.get('formasyon') or '', 0)
        out.append(legacy('0|n|d|%d|%d|%s' % (n.id, f, govde)))
    return out
