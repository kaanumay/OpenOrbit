"""Galaksi Kapıları: üretici (enerji, çekiliş, parça, çarpan) ve kapı koşusu (oyuncunun kuralları ve tabloları: galaxy_gates.py,
data/gates.json).

  enerji    bonus kutularından ve ödüllerden (resource_extra-energy) gelir; yoksa çekiliş başına 100 U (kapıcı ve zengin botlar)
  çekiliş   olasılıklar oyunun: cephane 67, Xenomit 12, kupon 3, parça 13, Nano Hull 4, günlük diski 1; Alpha/Beta/Gamma'nın
            parçası üçünden birine; kopya parça çarpanı artırır (en çok 5), oyunun "kopya eksiğe" payıyla
  koşu      kapı kurulunca bot (gücü yetiyorsa) kapı haritasına geçer (senin haritandan kalkar); süre ve başarı dalgaların
            uzaylılarından: toplam can / botun hasarı, alınan hasar / botun canı x can hakkı. Başarırsa kapının ödülü ve
            uzaylılarının öldürme ödülleri; başaramazsa kapı (parçalarıyla) kaybolur. Kronos parçası öteki kapılardan.
Durum bot.k['kapi'] = {'parca': {kapı: adet}, 'kurulu': [kapı …], 'carpan': n, 'kronos': adet}.
"""
import json, math, os, random

from . import catalog as K

D = json.load(open(os.path.join(K.HERE, 'data', 'gates.json'), encoding='utf8'))
KAPI = D['kapilar']
ABG = ('alpha', 'beta', 'gamma')
ORDER = ('alpha', 'beta', 'gamma', 'lambda', 'hades', 'delta', 'epsilon', 'kappa', 'zeta', 'streuner')
ENERGY = 'resource_extra-energy'
PROBABILITY = {c: w for c, w in D['olasilik']}            # 1 cephane, 2 kaynak, 3 kupon, 4 parça, 5 özel, 6 log
_difficulty = {}


def state(bot):
    return bot.k.setdefault('kapi', {'parca': {}, 'kurulu': [], 'carpan': 0, 'kronos': 0})


def stock(bot):
    from . import weapons as WP
    return WP.stock(bot)


def difficulty(gate):
    """Kapının dalgaları -> ([(dalganın toplam can+kalkanı, aynı anda vuranların saniyede hasarı)], öldürme ödülleri)."""
    if gate in _difficulty:
        return _difficulty[gate]
    import ast
    waves = KAPI[gate].get('dalgalar') or []
    if isinstance(waves, str):
        waves = ast.literal_eval(waves)
    out, reward = [], {}
    for d in waves:
        ehp = dps = 0.0
        for u in d.get('uzaylilar', []):
            n = u.get('adet', 1)
            ehp += n * (u.get('hp', 0) + u.get('kalkan', 0))
            dps += min(n, 2) * u.get('hasar', 0) * K.COMBAT['npc_isabet'] * 0.6 / K.NPC_INTERVAL  # oyuncu tek tek çeker, menzilden kaçar
            for k, v in (u.get('odul') or {}).items():
                reward[k] = reward.get(k, 0) + v * n
        out.append((ehp, dps))
    _difficulty[gate] = (out, reward)
    return _difficulty[gate]


def estimate(bot, gate):
    """Koşu tahmini -> (süre sn, beklenen ölüm sayısı). Kapıda oyuncular en iyi cephanesini kullanır (stoktaki en güçlü x2-x4);
    dalga arasında kalkan dolar ve onarılır."""
    from . import weapons as WP
    waves, _ = difficulty(gate)
    d = bot.value()
    s = WP.stock(bot)
    multiplier = max([WP.multiplier(c) for c in ('ammunition_laser_ucb-100', WP.MCB50, WP.MCB25, WP.LCB) if s.get(c, 0) > 1000] or [1])
    dps = max(1.0, d['dps'] * multiplier * 1.15)                 # roketler
    duration = death = 0.0
    for ehp, incoming_dps in waves:
        t = ehp / dps
        duration += t
        death += t * incoming_dps / max(1.0, d['ehp'] * 3)
    return duration, death


# ------------------------------------------------------------------------------------------------------------ üretici
def draw(bot, gate, n):
    """n çekiliş (önce enerji, sonra 100 U) -> yapılan."""
    st = state(bot)
    s = stock(bot)
    crafted = 0
    for _ in range(n):
        if s.get(ENERGY, 0) > 0:
            s[ENERGY] -= 1
        elif not bot.pay('U', D['enerji_fiyati'] * bot.game_settings.multiplier('magaza_fiyat')):
            break
        crafted += 1
        _draw(bot, st, gate)
        if gate in st['kurulu'] or (gate in ABG and all(k in st['kurulu'] for k in ABG)):
            break
    if s.get(ENERGY) == 0:
        s.pop(ENERGY, None)
    if crafted:
        bot.ist('kapi_cekilis', crafted)
    return crafted


def _draw(bot, st, gate):
    from . import weapons as WP
    r = bot.r
    cat = r.choices(list(PROBABILITY), weights=list(PROBABILITY.values()))[0]
    if cat == 4:
        k = r.choice([x for x in ABG if x not in st['kurulu']] or [gate]) if gate in ABG else gate
        total = KAPI[k]['parca']
        var = st['parca'].get(k, 0)
        missing = (total - var) / total
        new_ = r.random() < missing + (1 - missing) * 0.5 or st['carpan'] >= D['azami_carpan']
        if new_:
            earn = 1 + (st['carpan'] if st['carpan'] >= D['azami_carpan'] else 0)
            st['carpan'] = 0 if earn > 1 else st['carpan']
            st['parca'][k] = min(total, var + earn)
            if st['parca'][k] >= total and k not in st['kurulu']:
                st['kurulu'].append(k)
                bot.event('kapi_kuruldu', kapi=KAPI[k]['ad'])
        else:
            st['carpan'] = min(D['azami_carpan'], st['carpan'] + 1)
        return
    if cat == 1:
        loot, _, count = r.choice(D['cephane'])
        WP.add(bot, loot, count)
    elif cat == 2:
        bot.k.setdefault('kargo', {})
        bot.k['kargo']['3'] = bot.k['kargo'].get('3', 0) + r.randint(*D['xenomit'])
    elif cat == 3:
        stock(bot)['resource_jumpvoucher'] = stock(bot).get('resource_jumpvoucher', 0) + 1
    elif cat == 6:
        stock(bot)['resource_logfile'] = stock(bot).get('resource_logfile', 0) + 1


def target_gate(bot):
    """Parça toplanacak kapı: kurulmamış ve botun tahminen geçebileceği ilk kapı (oyuncuların sırası: ABG, sonra öteki)."""
    st = state(bot)
    for k in ORDER:
        if k in st['kurulu'] or KAPI[k].get('uretilmez'):
            continue
        duration, death = estimate(bot, k)
        if death < KAPI[k]['can'] * 1.5:
            return k
    return None


def generator(bot):
    """Karar anında: enerjisi varsa çeker; kapıcı ve zengin bot uridyumla da (izin 'kapi', 10. seviyeden)."""
    if not bot.permission.get('kapi', True) or bot.level < 10:
        return 0
    k = target_gate(bot)
    if not k:
        return 0
    n = stock(bot).get(ENERGY, 0)
    t = bot.o('tutumluluk')
    if bot.o('hirs') + bot.o('rekabet') > 1.1 and bot.k['uridyum'] > D['enerji_fiyati'] * 300 * (1 + 2 * t):
        n += int(bot.k['uridyum'] * 0.15 // D['enerji_fiyati'])
    return draw(bot, k, min(n, 200)) if n else 0


# ------------------------------------------------------------------------------------------------------------ koşu
def run_result(bot, gate, rng=random):
    """Koşunun sonucu -> (başardı mı, süre sn)."""
    duration, death = estimate(bot, gate)
    death = rng.gauss(death, 0.3 * death + 0.2)
    return death < KAPI[gate]['can'], duration * rng.uniform(1.1, 1.6) + 120


def grant_reward(bot, gate, speed=1.0):
    """Kapının tamamlama ödülü ve uzaylılarının öldürme ödülleri; Kronos parçası."""
    from . import weapons as WP
    o = KAPI[gate].get('odul') or {}
    if isinstance(o, str):
        import ast
        o = ast.literal_eval(o)
    _, aliens = difficulty(gate)
    bot.reward('gorev', speed, ep=o.get('ep', 0) + aliens.get('ep', 0), onur=o.get('onur', 0) + aliens.get('onur', 0),
             uridyum=o.get('uridyum', 0) + aliens.get('uridyum', 0), kredi=aliens.get('kredi', 0))
    for loot, n in (o.get('cephane') or {}).items():
        WP.add(bot, loot, n)
    if o.get('xenomit'):
        bot.k.setdefault('kargo', {})
        bot.k['kargo']['3'] = bot.k['kargo'].get('3', 0) + o['xenomit']
    s = stock(bot)
    for loot, n in (('resource_logfile', o.get('log_disk', 0)), ('resource_jumpvoucher', o.get('kupon', 0)),
                    ('resource_booty-key', (o.get('ganimet') or {}).get('yesil_anahtar', 0))):
        if n:
            s[loot] = s.get(loot, 0) + n
    st = state(bot)
    if gate != 'kronos':
        st['kronos'] = min(KAPI['kronos']['parca'], st['kronos'] + 1)
        if st['kronos'] >= KAPI['kronos']['parca'] and 'kronos' not in st['kurulu']:
            st['kurulu'].append('kronos')
    if gate not in st.setdefault('tamam', []):
        st['tamam'].append(gate)                      # kapı halkası (gorunum.halkalar)
    bot.ist('kapi_tamam')
    bot.event('kapi_tamam', kapi=KAPI[gate]['ad'])


def record_duration(save, key, sec):
    """Kapının tamamlanma süresi (istatistik; oyuncu isteği 2026-10-30) -> kayit['kapi_sureleri'][key] {en_iyi, son, sayi} (sn)."""
    d = save.setdefault('kapi_sureleri', {}).setdefault(key, {'en_iyi': 0, 'son': 0, 'sayi': 0})
    sec = int(max(1, sec))
    d.update(son=sec, sayi=d['sayi'] + 1, en_iyi=min(d['en_iyi'], sec) if d['en_iyi'] else sec)
    return d


def can_run(bot):
    """Kurulu ve geçilebilir kapı ya da None."""
    st = state(bot)
    for k in st['kurulu']:
        if estimate(bot, k)[1] < KAPI[k]['can']:
            return k
    return None
