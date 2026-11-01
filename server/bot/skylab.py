"""Botların Skylab'ı: oyuncununkiyle aynı tablolar ve kurallar (data/skylab.json; oyunun skylab.py'si), soyut ve tembel hesap.

Durum bot.k['skylab'] = {'mod': {modül: seviye}, 'depo': {cevher: adet}, 'son': an, 'insa': [modül, bitiş] | None, 'tasima': an}
  üretim     toplayıcılar ham cevher, Xeno modülü Xenomit, rafineriler depodaki girdilerden sırayla (Prometid/Duranium ->
             Promerium -> Seprom); depo sınırı depo modülünün seviyesinden; çalışan modüllerin enerjisi güneşi aşamaz (aşan
             modül en son kurulan sırayla kapalı sayılır)
  yükseltme  kredi + depodan P/E/T kaynağı, süreli (tek iş); taban modülü tavan, Promerium rafinerisi Xeno modülünü geçemez
  taşıma     cevher başına 7,2 sn (saatte 500): bot istasyonda satış yaparken birikmiş taşıma hakkı kadar cevher gemiye gelir
             (değerliler önce), satılır ya da laboratuvara gider (lab.py)
Yükseltme sırası gerçek oyuncunun sırası: toplayıcılar, enerji yetmezse güneş, depo dolarsa depo, sonra rafineriler ve Xeno.
"""
import json, os

from . import catalog as K

S = json.load(open(os.path.join(K.HERE, 'data', 'skylab.json'), encoding='utf8'))
ROW = S['seviyeler']
MOD = S['moduller']
COSTS = S['maliyetler']
ORES = S['cevherler']                       # skylab cevheri -> [ad, depo sütunu, kargo cevheri]
COLLECTORS = S['toplayicilar']              # modül -> cevher
REFINERIES = S['rafineriler']               # modül -> [ürün, girdiler, sütun]
REFINE_ORDER = ('PROMETID_REFINERY', 'DURANIUM_REFINERY', 'PROMERIUM_REFINERY', 'SEPROM_REFINERY')
XENO = S['xeno']
TRANSPORT_SEC = S['tasima']['birim_sn']
RESOURCES = ('1', '2', '3')                    # yükseltmenin kaynakları: Prometium, Endurium, Terbium (her birinden 'kaynak' kadar)
STEP_SEC = 1800.0
ORDER = ('PROMETIUM_COLLECTOR', 'ENDURIUM_COLLECTOR', 'TERBIUM_COLLECTOR', 'PROMETID_REFINERY', 'DURANIUM_REFINERY',
        'XENO_MODULE', 'PROMERIUM_REFINERY', 'SEPROM_REFINERY')


def row(lv):
    return ROW[max(1, min(len(ROW), lv)) - 1]


def state(bot, now):
    st = bot.k.get('skylab')
    if st is None:
        st = bot.k['skylab'] = {'mod': {m: lv for m, (lv, _) in S['baslangic']['moduller'].items()},
                                'depo': {o: float(n) for o, n in S['baslangic']['depo'].items()}, 'son': now, 'insa': None,
                                'tasima': now}
    return st


def level(st, m):
    return st['mod'].get(m, 0)


def energy(m, lv):
    return row(lv)['enerji'] if lv > 0 and m != 'SOLAR_MODULE' else 0


def workers(st):
    """Enerjisi yeten modüller (güneş, taban, depo, taşıma hep açık; ötekiler SIRA'yla, güneş biterse sonrakiler kapalı)."""
    solar = row(level(st, 'SOLAR_MODULE'))['gunes']
    spent = sum(energy(m, level(st, m)) for m in ('BASE_MODULE', 'STORAGE_MODULE'))
    is_open = set()
    for m in ORDER:
        e = energy(m, level(st, m))
        if level(st, m) > 0 and spent + e <= solar:
            is_open.add(m)
            spent += e
    return is_open


def capacity(st, ore):
    return row(level(st, 'STORAGE_MODULE'))['depo'][ORES[ore][1]]


def production(st, m):
    lv = level(st, m)
    if lv <= 0:
        return 0
    if m in COLLECTORS:
        return row(lv)['uretim']['ham']
    if m in REFINERIES:
        return row(lv)['uretim'][REFINERIES[m][2]]
    if m == 'XENO_MODULE':
        return row(lv)['uretim'][XENO['sutun']]
    return 0


def produce(st, hour, multiplier=1.0):
    dep = st['depo']
    is_open = workers(st)

    def add(ore, n):
        dep[ore] = min(capacity(st, ore), dep.get(ore, 0) + n)
    for m, ore in COLLECTORS.items():
        if m in is_open:
            add(ore, production(st, m) * hour * multiplier)
    if 'XENO_MODULE' in is_open:
        add(XENO['cevher'], production(st, 'XENO_MODULE') * hour * multiplier)
    for m in REFINE_ORDER:
        if m not in is_open:
            continue
        output, input_, _ = REFINERIES[m]
        n = min([production(st, m) * hour * multiplier, capacity(st, output) - dep.get(output, 0)] + [dep.get(o, 0) / k for o, k in input_.items()])
        if n <= 0:
            continue
        for o, k in input_.items():
            dep[o] = max(0.0, dep.get(o, 0) - n * k)
        add(output, n)


def advance(bot, now):
    """Son hesaptan bu yana üretim ve biten yükseltme (soyut, adım adım) -> durum."""
    st = state(bot, now)
    t = max(st['son'], now - 24 * 3600)                 # uzun boşlukta en çok bir günlük üretim (telafi sınırı gibi)
    k = bot.game_settings.multiplier('skylab_uretim')
    while t < now:
        end_time = st['insa'][1] if st.get('insa') else None
        nxt = min(now, t + STEP_SEC, end_time if end_time and end_time > t else now)
        produce(st, (nxt - t) / 3600.0, k)
        t = nxt
        if st.get('insa') and st['insa'][1] <= t:
            m = st['insa'][0]
            st['mod'][m] = level(st, m) + 1
            st['insa'] = None
            bot.event('skylab', modul=m, seviye=st['mod'][m])
    st['son'] = now
    return st


# ------------------------------------------------------------------------------------------------------------ yükseltme
def cost(st, m):
    g, lv = MOD[m]['grup'], level(st, m)
    if not g or lv >= MOD[m]['azami']:
        return None
    return COSTS[g][lv]


def upgradable(st, m):
    if cost(st, m) is None or st.get('insa'):
        return False
    if m != 'BASE_MODULE' and level(st, m) + 1 > level(st, 'BASE_MODULE'):
        return False
    if m == 'PROMERIUM_REFINERY' and level(st, m) + 1 > level(st, 'XENO_MODULE'):
        return False
    return True


def next_up(st):
    """Gerçek oyuncunun sırası: enerji yetmiyorsa güneş, depo doluysa depo; taban tavana dayandıysa taban; sonra SIRA'daki en
    düşük seviyeli (toplayıcılar önce)."""
    solar = row(level(st, 'SOLAR_MODULE'))['gunes']
    need = sum(energy(m, level(st, m)) for m in st['mod'] if m != 'SOLAR_MODULE')
    if need > solar * 0.9 and upgradable(st, 'SOLAR_MODULE'):
        return 'SOLAR_MODULE'
    if any(st['depo'].get(o, 0) > 0.9 * capacity(st, o) for o in st['depo']) and upgradable(st, 'STORAGE_MODULE'):
        return 'STORAGE_MODULE'
    candidates = [m for m in ORDER if upgradable(st, m)]
    if not candidates:
        return 'BASE_MODULE' if upgradable(st, 'BASE_MODULE') else None
    m = min(candidates, key=lambda m: (level(st, m) + (2 if m in REFINERIES or m == 'XENO_MODULE' else 0), ORDER.index(m)))
    if level(st, m) >= level(st, 'BASE_MODULE') and upgradable(st, 'BASE_MODULE'):
        return 'BASE_MODULE'
    return m


def invest(bot, now):
    """Skylab'ı yükseltir (izin 'skylab', 3. seviyeden; tek iş): sıradaki modülün kredisi bütçeye (kredinin bir payı, tutumlu
    daha çok yatırır: uzun vadeli kazanç) ve kaynağı depoya yetiyorsa -> başlatılan modül ya da None."""
    if not bot.permission.get('skylab', True) or bot.level < 3:
        return None
    st = advance(bot, now)
    m = next_up(st)
    c = cost(st, m) if m else None
    if not c:
        return None
    credits = c['kredi'] * bot.game_settings.multiplier('hizmet_fiyat', 'skylab')
    if bot.k['kredi'] < credits * (2.5 - bot.o('tutumluluk') - 0.5 * bot.o('sabir')) or any(st['depo'].get(o, 0) < c['kaynak'] for o in RESOURCES):
        return None
    if not bot.pay('C', credits):
        return None
    for o in RESOURCES:
        st['depo'][o] -= c['kaynak']
    st['insa'] = [m, now + c['sure_sn']]
    bot.ist('skylab_yukseltme')
    return m


# ------------------------------------------------------------------------------------------------------------ taşıma
VALUE = {'14': 0, '13': 1, '4': 2, '11': 3, '12': 4, '3': 5, '2': 6, '1': 7}       # önce değerli: Seprom, Promerium, Xenomit …


def carry(bot, now, max_count):
    """İstasyonda: son taşımadan bu yana hakkı kadar (saatte 3600/7,2) cevher depodan kargoya (değerliler önce; en_cok birim)
    -> taşınan {kargo cevheri: adet}."""
    if not bot.permission.get('skylab', True):
        return {}
    st = advance(bot, now)
    right = min(max_count, (now - st.get('tasima', now)) / TRANSPORT_SEC)
    st['tasima'] = now
    out = {}
    for ore in sorted(st['depo'], key=lambda o: VALUE.get(o, 9)):
        n = int(min(right, st['depo'][ore]))
        if n <= 0:
            continue
        st['depo'][ore] -= n
        right -= n
        cargo = ORES[ore][2]
        out[cargo] = out.get(cargo, 0) + n
    for t, n in out.items():
        bot.k['kargo'][str(t)] = bot.k['kargo'].get(str(t), 0) + n
    if out:
        bot.ist('skylab_tasima', sum(out.values()))
    return out
