"""Gerçek sunuculardaki ad üslubu (oyuncu isteği 2026-10-31: "adlar yapay zekânın uyduracağı gibi"). Oranlar dostats.info'daki
9 sunucunun (tr3 de2 pl3 ru1 es1 fr1 int1 gbl6 mx1) 1.618 adından sayıldı: adların %52'sinde ASCII dışı harf var, %25'i yalnız harf
ve rakam, %6'sının sonunda [KLAN] etiketi; en sık süsler -»...«-, -=...=-, .:...:., **...**, ツ, ᵀᴹ, harf yerine benzeri (Λ Σ Я И Ø
Ł Ð), küçük büyük harf (ᴀʙᴄ), boşluk yerine ㅤ. Üretici ASCII adı (kisilik.ad_uret) bu üslupla süsler; sade() süsü geri alır
(sohbette "Ajax"a seslenen "-»Ajαх«-"ı anar).
"""
import re
import unicodedata

# dilin adlarının süslenme oranı (sunucusundaki ASCII dışı ad payına yakın)
STYLE_RATE = {'tr': 0.5, 'de': 0.6, 'pl': 0.45, 'ru': 0.55, 'es': 0.4, 'fr': 0.45, 'pt': 0.4, 'en': 0.45}

WRAPS = ((15, '-»', '«-'), (6, '-=', '=-'), (4, '.:', ':.'), (2, '.::', '::.'), (5, '**', '**'), (5, '*', '*'), (4, '#', ''),
         (2, '×', '×'), (2, '==', '=='), (2, '--', '--'), (4, '-', '-'), (1, '((', '))'), (1, '..', '..'), (2, '★', '★'),
         (1, '亗', '亗'), (1, 'ッ', 'ッ'), (1, '【', '】'), (1, '「', '」'), (1, '_', '_'), (1, '˘°*', '*°˘'), (1, '٠', '٠'),
         (1, '•', '•'), (1, '†', '†'))
SUFFIXES = ((4, 'ツ'), (3, 'ᵀᴹ'), (3, '™'), (1, '彡'), (1, '☆'), (1, '®'), (1, '亗'))
SEPARATORS = ('ㅤ', 'ㅤ', '　', '×', '_', '.', '•', '-')          # iki sözcük arası
# büyük harf benzerleri (Λ Σ Я ...) ve süslü küçükler (α є я ...); küçük büyük harf (ᴀ ʙ ᴄ)
UPPER_LOOKALIKES = {'A': 'ΛΔ', 'B': 'β', 'C': 'Ç', 'D': 'ÐĐ', 'E': 'ΣΞ', 'G': 'Ģ', 'H': 'Ħ', 'I': 'Ι', 'K': 'Ķ', 'L': 'Ł', 'N': 'И',
         'O': 'ØΘ', 'R': 'Я', 'S': 'ŞŠ', 'T': 'ŦƬ', 'U': 'Ц', 'W': 'Ш', 'Y': '¥', 'Z': 'Ź'}
LOWER_LOOKALIKES = {'a': 'α', 'b': 'в', 'c': '¢', 'e': 'єε', 'h': 'н', 'i': 'ι', 'k': 'кĸ', 'l': 'łℓ', 'm': 'м', 'n': 'ηи', 'o': 'σø',
         'p': 'ρ', 'r': 'я', 's': 'ѕ', 't': 'т', 'u': 'υ', 'w': 'ω', 'y': 'у', 'x': 'х'}
SMALL_CAPS = dict(zip('abcdefghijklmnopqrstuvwxyz', 'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘqʀꜱᴛᴜᴠᴡxʏᴢ'))
CYRILLIC = (('shch', 'щ'), ('sh', 'ш'), ('ch', 'ч'), ('zh', 'ж'), ('kh', 'х'), ('ts', 'ц'), ('yu', 'ю'), ('ya', 'я'), ('yo', 'ё'),
         ('a', 'а'), ('b', 'б'), ('v', 'в'), ('g', 'г'), ('d', 'д'), ('e', 'е'), ('z', 'з'), ('i', 'и'), ('y', 'й'), ('k', 'к'),
         ('l', 'л'), ('m', 'м'), ('n', 'н'), ('o', 'о'), ('p', 'п'), ('r', 'р'), ('s', 'с'), ('t', 'т'), ('u', 'у'), ('f', 'ф'),
         ('h', 'х'), ('c', 'к'), ('w', 'в'), ('x', 'кс'), ('j', 'дж'))
MAX_LEN = 20

# sade(): süslü harf -> Latin (yukarıdaki tablolar + Kiril)
_REVERSE = {}
for _l, _s in list(UPPER_LOOKALIKES.items()) + list(LOWER_LOOKALIKES.items()):
    for _c in _s:
        _REVERSE.setdefault(_c, _l.lower())
for _l, _c in SMALL_CAPS.items():
    _REVERSE.setdefault(_c, _l)
for _l, _c in CYRILLIC:
    if len(_c) == 1:
        _REVERSE.setdefault(_c, _l)
_REVERSE.update({'ж': 'zh', 'ш': 'sh', 'щ': 'shch', 'ч': 'ch', 'ц': 'ts', 'ю': 'yu', 'я': 'ya', 'ё': 'yo', 'ы': 'y', 'э': 'e',
              'х': 'h', 'ł': 'l', 'ø': 'o', 'ß': 'b', 'ı': 'i', 'đ': 'd', 'ð': 'd', 'ŧ': 't', 'ħ': 'h'})


def _sec(r, table):
    return r.choices([x[1:] if len(x) > 2 else x[1] for x in table], weights=[x[0] for x in table])[0]


def _split_words(name):
    """"DarkHunter_77" -> ['Dark', 'Hunter', '77']."""
    return [s for s in re.split(r'[_.\-]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])', name) if s]


def _swap_letters(s, r):
    """Harfleri benzerleriyle değiştir: hepsi büyükse büyük benzerler, değilse süslü küçükler; bazen küçük büyük harf."""
    choice = r.random()
    if choice < 0.2:
        return ''.join(SMALL_CAPS.get(c.lower(), c) for c in s)
    ratio = r.uniform(0.35, 0.9)
    out = []
    for c in s:
        table = UPPER_LOOKALIKES if c.isupper() else LOWER_LOOKALIKES
        out.append(r.choice(table[c]) if c in table and r.random() < ratio else c)
    return ''.join(out)


def to_cyrillic(s):
    s, out = s.lower(), ''
    while s:
        for l, c in CYRILLIC:
            if s.startswith(l):
                out += c
                s = s[len(l):]
                break
        else:
            out += s[0]
            s = s[1:]
    return out


def decorate(name, r, lang='en', tag=None):
    """ASCII adı gerçek sunuculardaki gibi süsle (dilin oranında; süslenmeyen ad olduğu gibi döner). etiket: klan etiketi önerisi
    ([TAG] soneki için)."""
    if r.random() >= STYLE_RATE.get(lang, 0.45):
        return name
    for _ in range(6):
        s = name
        part = _split_words(s)
        if lang == 'ru' and r.random() < 0.45:
            s = to_cyrillic(s)
            if r.random() < 0.5:
                s = s.capitalize()
        elif r.random() < 0.55:
            if r.random() < 0.35:
                s = s.upper()
            s = _swap_letters(s, r)
        if len(part) > 1 and r.random() < 0.3:              # sözcük arası: ㅤ, ×, _ ...
            search = r.choice(SEPARATORS)
            n = len(part[0])
            s = s[:n] + search + s[n:]
        if r.random() < 0.55:
            on, last = _sec(r, WRAPS)
            s = on + s + last
        if r.random() < 0.18:
            s += _sec(r, SUFFIXES)
        if tag and r.random() < 0.1:
            s += '[%s]' % tag
        if 3 <= len(s) <= MAX_LEN and is_case_safe(s):
            return s
    return name


def is_case_safe(name):
    """Büyük/küçük harf ayrımsız karşılaştırma bu adda güvenli mi (oyun adları .lower() ile eşler): "ß".upper() "SS", "İ".lower()
    iki harf olur; böyle ad "BÜYÜK" yazılınca bulunamaz."""
    return name.upper().lower() == name.lower() and len(name.lower()) == len(name)


def plain(name):
    """Süsü at, Latin küçük harf iskelet: "-»Ajαх×Ħøø«-" -> "ajaxhoo"; "DarkHunter" -> "darkhunter"."""
    out = []
    for c in str(name):
        g = _REVERSE.get(c) or _REVERSE.get(c.lower())
        if g is None:
            g = unicodedata.normalize('NFKD', c)
            g = ''.join(x for x in g if not unicodedata.combining(x))
        out.append(g.lower())
    return re.sub(r'[^a-z0-9]', '', ''.join(out))


def is_mentioned(name, msg):
    """Mesajda bu ad geçiyor mu: tam ad ya da (süslü adda) iskeleti, sözcük sınırıyla."""
    m = str(msg).lower()
    if re.search(r'(?<!\w)%s(?!\w)' % re.escape(str(name).lower()), m):
        return True
    s = plain(name)
    if len(s) < 3 or s == str(name).lower():
        return False
    return any(plain(w) == s or len(s) >= 5 and plain(w).startswith(s) for w in re.split(r'\s+', m) if w)
