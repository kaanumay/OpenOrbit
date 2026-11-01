"""Botun kişiliği: kalıcı özellikler, arketip, oyun alışkanlığı, yazım üslubu, ad; dinamik ruh hâli ve kişilere karşı hafıza.

Kadro paket oluşturulurken bir kez üretilir (kadro_uret, tohumlu ve belirlenimci): aynı paket her açılışta aynı botları verir.
Özellikler 0-1 arası; arketip ortalamaları verir, her bota gürültü eklenir (aynı arketipten iki bot aynı değil). Karar motoru
(brain.py) hedefleri bu özelliklerle ve ruh hâliyle puanlar.
"""
import math, random, re, time

from . import name_style as NS

TRAITS = ('saldirganlik', 'rekabet', 'sosyallik', 'sabir', 'risk', 'sadakat', 'yardimseverlik', 'konuskanlik', 'tutumluluk',
              'hirs')

# arketip -> (nüfustaki payı, özellik ortalamaları, açıklama). Paylar gerçek bir sunucunun kabaca dağılımı: çoğunluk uzaylı kasar,
# az sayıda avcı ve lider; "rahat" oyuncular haftada birkaç saat girip yavaş ilerler.
ARCHETYPES = {
    'kasici':  (0.27, dict(saldirganlik=.35, rekabet=.50, sosyallik=.35, sabir=.85, risk=.30, sadakat=.60, yardimseverlik=.50,
                           konuskanlik=.30, tutumluluk=.60, hirs=.75), 'PvE kasıcı'),
    'avci':    (0.14, dict(saldirganlik=.90, rekabet=.90, sosyallik=.45, sabir=.40, risk=.80, sadakat=.50, yardimseverlik=.30,
                           konuskanlik=.55, tutumluluk=.35, hirs=.70), 'PvP avcısı'),
    'sosyal':  (0.14, dict(saldirganlik=.30, rekabet=.35, sosyallik=.90, sabir=.50, risk=.40, sadakat=.80, yardimseverlik=.80,
                           konuskanlik=.90, tutumluluk=.50, hirs=.40), 'sosyal'),
    'tuccar':  (0.08, dict(saldirganlik=.20, rekabet=.55, sosyallik=.55, sabir=.70, risk=.35, sadakat=.50, yardimseverlik=.40,
                           konuskanlik=.50, tutumluluk=.85, hirs=.60), 'tüccar'),
    'gorevci': (0.16, dict(saldirganlik=.40, rekabet=.45, sosyallik=.40, sabir=.70, risk=.45, sadakat=.55, yardimseverlik=.60,
                           konuskanlik=.35, tutumluluk=.55, hirs=.65), 'görevci'),
    'rahat':   (0.17, dict(saldirganlik=.30, rekabet=.20, sosyallik=.50, sabir=.35, risk=.50, sadakat=.40, yardimseverlik=.55,
                           konuskanlik=.50, tutumluluk=.30, hirs=.25), 'rahat'),
    'lider':   (0.04, dict(saldirganlik=.55, rekabet=.75, sosyallik=.85, sabir=.60, risk=.55, sadakat=.90, yardimseverlik=.70,
                           konuskanlik=.75, tutumluluk=.60, hirs=.85), 'lider'),
}

# arketipin oyuna ayırdığı zaman (çevrimiçi olma eğilimi çarpanı) ve oynarken verimi (dikkat, optimizasyon)
ACTIVITY = {'kasici': (1.3, 1.15), 'avci': (1.2, 1.0), 'sosyal': (1.0, 0.8), 'tuccar': (0.9, 0.95), 'gorevci': (1.0, 1.0),
            'rahat': (0.55, 0.7), 'lider': (1.3, 1.0)}

# oyun alışkanlığı: saat -> çevrimiçi olma eğilimi (0-1) ve oturum uzunluğu (dakika, en az-en çok)
HABITS = {
    'aksamci':   (0.40, [0.15] * 7 + [0.2] * 5 + [0.3] * 5 + [0.8] * 5 + [0.5] * 2, (40, 150)),
    'gece_kusu': (0.20, [0.7] * 4 + [0.2] * 8 + [0.25] * 6 + [0.5] * 3 + [0.85] * 3, (60, 240)),
    'gunduzcu':  (0.20, [0.05] * 8 + [0.6] * 10 + [0.4] * 4 + [0.1] * 2, (30, 120)),
    'tutkun':    (0.20, [0.5] * 8 + [0.7] * 16, (120, 420)),
}

EMOTIONS = ('ofke', 'moral', 'sikilma', 'yorgunluk', 'ozguven')
EMOTION_BASELINE = dict(ofke=0.0, moral=0.6, sikilma=0.0, yorgunluk=0.0, ozguven=0.5)
EMOTION_DECAY_SEC = dict(ofke=600, moral=1800, sikilma=900, yorgunluk=1e9, ozguven=1200)    # dengeye dönüş süresi (yarı ömür)


def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


# ------------------------------------------------------------------------------------------------------------ adlar
_LEET = {'a': '4', 'e': '3', 'i': '1', 'o': '0', 's': '5', 't': '7'}
_NUMBERS = ('1', '7', '13', '23', '34', '35', '06', '16', '41', '42', '61', '69', '77', '88', '99', '007', '123', '1903', '1905',
            '1907', '1453', '2000', '2003', '2005', '2010', '666', '777', '1923', '01', '07', '27', '33', '38', '55', '21')
NAME_PATTERN = re.compile(r'^[^\x00-\x20/|<>\\"\x7f\u200b-\u200f\u2028\u2029]{3,20}$')   # gerçek sunucular gibi süslü adlar
#                                                  (ad_uslup.py); boşluk, / | < > \ " ve görünmez karakterler yok


def _leet(s, r, ratio):
    return ''.join(_LEET[c.lower()] if c.lower() in _LEET and r.random() < ratio else c for c in s)


def generate_name(r, lang='karisik'):
    """Gerçek bir MMO sunucusundaki kullanıcı adlarına benzeyen ad, dilin kendi adlarıyla (bot/languages/<kod>.json adlar: parçalar
    ve ağırlıklı desenler; 'karisik': dosyaların ağırlığıyla bir dil)."""
    from .language_data import LANGUAGES, pick_mixed
    d = LANGUAGES.get(lang) or LANGUAGES[pick_mixed(r)]
    a = d['adlar']
    pattern = r.choices([x[1] for x in a['patterns']], weights=[x[0] for x in a['patterns']])[0]
    s = re.sub(r'\{([^}]+)\}', lambda m: _part(m.group(1), a['parcalar'], r), pattern)
    s = re.sub(r'[^A-Za-z0-9_.\-]', '', s)
    return s[:20] if len(s) >= 3 else s + r.choice(a['parcalar'].get('sayi') or _NUMBERS)


def _part(name, parts, r):
    """Desen alanı: {liste}, {liste_k} küçük, {a|b} iki listeden, {liste?} yarı yarıya boş, {leet:liste}."""
    leet = name.startswith('leet:')
    name = name[5:] if leet else name
    empty = name.endswith('?')
    name = name.rstrip('?')
    lower = name.endswith('_k')
    name = name[:-2] if lower else name
    if empty and r.random() < 0.5:
        return ''
    s = r.choice([x for a in name.split('|') for x in parts.get(a, ())] or [''])
    if leet:
        s = _leet(s, r, 0.6)
    return s.lower() if lower else s


# ------------------------------------------------------------------------------------------------------------ kadro
def _choice(r, table):
    """{anahtar: (pay, ...)} ya da {anahtar: pay} -> paya göre bir anahtar."""
    ks = list(table)
    ws = [table[k][0] if isinstance(table[k], tuple) else table[k] for k in ks]
    return r.choices(ks, ws)[0]


def generate_personality(r, archetype=None, lang='tr'):
    """Bir botun kalıcı kişiliği: arketip, özellikler (ortalama + gürültü), alışkanlık, üslup, sohbet dili."""
    a = archetype or _choice(r, ARCHETYPES)
    avg = ARCHETYPES[a][1]
    traits = {k: round(clamp(r.gauss(avg[k], 0.14), 0.02, 0.98), 2) for k in TRAITS}
    take = _choice(r, HABITS)
    talk = traits['konuskanlik']
    style = dict(
        lowercase=round(clamp(r.gauss(0.6, 0.25)), 2),       # her şeyi küçük harfle yazar
        punctuation=round(clamp(r.gauss(0.3, 0.25)), 2),        # cümle sonu noktalama
        abbreviation=round(clamp(r.gauss(0.5, 0.25)), 2),         # "slm", "nbr", "tmm", "gg", "np"
        emoji=round(clamp(r.gauss(0.3 + talk * 0.2, 0.2)), 2),  # ":D", "xD", "^^"
        hata=round(clamp(r.gauss(0.08, 0.06), 0, 0.3), 2),    # yazım hatası
        uppercase=round(clamp(r.gauss(0.05 + traits['saldirganlik'] * 0.1, 0.05), 0, 0.4), 2),   # BAĞIRIR
    )
    return dict(arketip=a, ozellik=traits, habit=take, uslup=style, dil=lang,
                reaction_sec=round(clamp(r.gauss(0.9, 0.35), 0.35, 2.0), 2))   # insan tepki süresi (sn): somut savaşta gecikme


def generate_roster(seed, count, company_distribution=(1, 1, 1), lang='karisik', existing=(), name_lang=None, special=(), pool=None):
    """Paketin kadrosu: [{no, ad, firma, kisilik}]. firma_dagilimi: (MMO, EIC, VRU) ağırlıkları. mevcut: kullanılmış adlar
    (büyük/küçük harf ayrımsız; oyuncunun ve başka botların adlarıyla çakışmasın). Aynı tohum ve girdi aynı kadroyu verir.
    ad_dili: adların dili ('karisik': dosyaların ağırlığıyla); dil: sohbet dili ('karisik': her bot adının dilinde konuşur).
    ozel: kullanıcının kendi botları [{ad, firma?, arketip?, dil?}] (oyuncu isteği 2026-10-30): kadronun başında, verilmeyen
    alanları ötekiler gibi üretilir; firması verilen, dağılımdaki o firmanın bir yerini alır.
    havuz: gerçek oyuncu adları {dil: [ad]} (bot/dostats.py): adlar önce oradan, bitince üretilir."""
    from .language_data import LANGUAGES, pick_mixed
    name_lang = name_lang or lang
    r = random.Random(seed)
    used = {str(a).lower() for a in existing}
    special = [o for o in special if str(o['ad']).lower() not in used][:count]
    total = sum(company_distribution) or 1
    # firmaları paylara göre tam sayıya böl (en büyük kalan), sonra karıştır: dağılım küçük kadroda da tutar
    shares = [count * f / total for f in company_distribution]
    number = [int(p) for p in shares]
    for i in sorted(range(3), key=lambda i: shares[i] - number[i], reverse=True)[:count - sum(number)]:
        number[i] += 1
    companies = [f + 1 for f in range(3) for _ in range(number[f])]
    r.shuffle(companies)
    for o in special:                                   # firması verilen özel bot o firmanın bir yerini alır
        if o.get('firma') in companies:
            companies.remove(o['firma'])
    remaining = iter(companies)
    out = []
    for no in range(1, count + 1):
        o = special[no - 1] if no <= len(special) else {}
        firma = o.get('firma') or next(remaining, None) or r.randint(1, 3)
        name_langs = name_lang if name_lang in LANGUAGES else pick_mixed(r)
        chat = o.get('dil') or (lang if lang in LANGUAGES else name_langs)          # karışık: adı Almanca olan Almanca konuşur
        real = [x for x in (pool or {}).get(name_langs) or [y for v in (pool or {}).values() for y in v]
                  if x.lower() not in used and NS.is_case_safe(x)]
        if o:
            name = str(o['ad'])
        elif real:
            name = r.choice(real)
        else:
            for _ in range(50):
                name = NS.decorate(generate_name(r, name_langs), r, name_langs)
                if name.lower() not in used and NAME_PATTERN.match(name) and NS.is_case_safe(name):
                    break
            else:
                name = 'Pilot%d' % r.randint(1000, 99999)
        used.add(name.lower())
        x = dict(no=no, ad=name, firma=firma, kisilik=dict(generate_personality(r, archetype=o.get('arketip'), lang=chat), name_lang=o.get('dil') or name_langs))
        if o:
            x['ozel'] = True                             # kullanıcının botu (panel: Kadro'da işaretli)
        out.append(x)
    return out


# ------------------------------------------------------------------------------------------------------------ ruh hâli
class Mood:
    """Dinamik duygular (0-1): olaylar iter, zamanla dengeye döner (üstel sönüm). Kalıcı kayıtta sözlük olarak durur."""
    __slots__ = ('d', 't')

    def __init__(self, d=None, t=None):
        self.d = dict(EMOTION_BASELINE, **(d or {}))
        self.t = t or time.time()

    def update(self, now=None):
        now = now or time.time()
        dt = max(0.0, now - self.t)
        self.t = now
        if dt <= 0:
            return
        for k, baseline in EMOTION_BASELINE.items():
            f = 0.5 ** (dt / EMOTION_DECAY_SEC[k])
            self.d[k] = baseline + (self.d[k] - baseline) * f

    def it(self, **exchange):
        for k, v in exchange.items():
            self.d[k] = clamp(self.d[k] + v)

    def __getitem__(self, k):
        return self.d[k]

    def save(self):
        return {k: round(v, 3) for k, v in self.d.items()}


# ------------------------------------------------------------------------------------------------------------ hafıza
EVENTS = {          # olay -> ilişkiye etkisi
    'oldurdu_beni': -0.35, 'oldurdum': -0.05, 'yardim_etti': 0.25, 'yardim_ettim': 0.1, 'sohbet': 0.03, 'hakaret': -0.2,
    'ovgu': 0.12, 'grup': 0.08, 'klan': 0.1, 'arkadas': 0.2, 'reddetti': -0.08, 'birlikte_avlandik': 0.05,
    'dedikodu_iyi': 0.06, 'dedikodu_kotu': -0.08,          # başka bottan duyulan (ani.duydu)
}


class Memory:
    """Kişilere karşı ilişki (-1 kin .. 1 dostluk) ve olay sayıları. Kayıtta {ad_kucuk: {d, n: {olay: sayı}, s: son an}}.
    Uzun süre görülmeyen ilişki yavaşça sıfıra döner (unutma); en çok HAFIZA_EN_COK kişi tutulur (en eskisi düşer)."""
    MAX_COUNT = 60
    FORGET_SEC = 6 * 3600

    def __init__(self, d=None):
        self.d = d if d is not None else {}
        self.listener = None                # (ad, tür, an) -> olay kancası: güçlü sağlayıcıda anı defteri (ani.olaydan; yönetici bağlar)

    def event(self, name, kind, now=None, multiplier=1.0):
        if not str(name or '').strip():
            return 0.0                                     # kimliği bilinmeyen (adsız) biri: hatırlanacak kimse yok
        now = now or time.time()
        k = str(name).lower()
        e = self.d.setdefault(k, {'d': 0.0, 'n': {}, 's': now, 'ad': str(name)})
        self._forget(e, now)
        e['d'] = round(clamp(e['d'] + EVENTS.get(kind, 0) * multiplier, -1, 1), 3)
        e['n'][kind] = e['n'].get(kind, 0) + 1
        e['s'] = now
        if len(self.d) > self.MAX_COUNT:
            del self.d[min(self.d, key=lambda x: self.d[x]['s'])]
        if self.listener is not None:
            self.listener(name, kind, now)
        return e['d']

    def _forget(self, e, now):
        dt = now - e.get('s', now)
        if dt > 0:
            e['d'] = e['d'] * 0.5 ** (dt / self.FORGET_SEC)

    def relation(self, name, now=None):
        e = self.d.get(str(name).lower())
        if not e:
            return 0.0
        dt = (now or time.time()) - e.get('s', 0)
        return e['d'] * 0.5 ** (max(0, dt) / self.FORGET_SEC)

    def count(self, name, kind):
        e = self.d.get(str(name).lower())
        return e['n'].get(kind, 0) if e else 0

    def grudges(self, threshold=-0.3, now=None):
        return [e['ad'] for e in self.d.values() if self.relation(e['ad'], now) <= threshold]

    def allies(self, threshold=0.3, now=None):
        return [e['ad'] for e in self.d.values() if self.relation(e['ad'], now) >= threshold]


def timezone(personality):
    """Botun saat dilimi farkı (saat): çoğu sunucunun saatinde, bir kısmı komşu ülkelerde, azı uzakta. Kişilikte yoksa adından
    (eski kayıtlar için kalıcı ve belirlenimci). Herkes aynı saatte yaşasaydı gece sunucu bomboş, akşam tıklım tıklım olurdu."""
    d = personality.get('timezone_offset')
    if d is None:
        import zlib
        r = zlib.crc32(str(personality.get('_name') or personality.get('arketip')).encode()) % 100
        d = 0 if r < 55 else -1 if r < 70 else 1 if r < 82 else -2 if r < 88 else 2 if r < 93 else -7 if r < 97 else 7
        personality['timezone_offset'] = d
    return d


def taste(personality):
    """Botun kalıcı gemi zevki (gemi ailesi): herkes aynı gemiye yakınsamasın. Kişilikte yoksa adından (eski kayıtlar)."""
    z = personality.get('taste')
    if z is None:
        import zlib
        families = ('goliath', 'vengeance', 'aegis', 'citadel', 'spearhead', 'leonov', 'nostromo', 'piranha', 'bigboy', 'solace')
        z = personality['taste'] = families[zlib.crc32(('z' + str(personality.get('_name') or personality.get('arketip'))).encode()) % len(families)]
    return z


def online_tendency(personality, hour):
    """Alışkanlığa ve arketipe göre bu saatte (0-23; botun kendi saat diliminde) çevrimiçi olma eğilimi."""
    return HABITS[personality['habit']][1][int(hour + timezone(personality)) % 24] * ACTIVITY[personality['arketip']][0]


def session_min(personality, r=random):
    a, b = HABITS[personality['habit']][2]
    return r.uniform(a, b)


def softmax_pick(scores, temperature, r=random):
    """[(anahtar, puan)] -> sıcaklığa göre seçilen anahtar (sıcaklık küçükse hep en yüksek)."""
    if not scores:
        return None
    t = max(0.02, temperature)
    m = max(p for _, p in scores)
    ws = [math.exp((p - m) / t) for _, p in scores]
    return r.choices([k for k, _ in scores], ws)[0]
