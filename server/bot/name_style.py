"""Name style on real servers (player request 2026-10-31: "the names look like something an AI would invent"). The ratios were counted from the 1,618 names of the
9 servers in dostats.info (tr3 de2 pl3 ru1 es1 fr1 int1 gbl6 mx1): 52% of the names have a non-ASCII letter, 25% are only letters
and digits, 6% end with a [CLAN] tag; the most common decorations are -»...«-, -=...=-, .:...:., **...**, ツ, ᵀᴹ, look-alikes in place of letters (Λ Σ Я И Ø
Ł Ð), small caps (ᴀʙᴄ), ㅤ in place of a space. The generator decorates the ASCII name (personality.generate_name) in this style; sade() undoes the decoration
(it recognizes "-»Ajαх«-" in chat when someone addresses "Ajax").
"""
import re
import unicodedata

# decoration ratio of the language's names (close to the share of non-ASCII names on its server)
STYLE_RATE = {'tr': 0.5, 'de': 0.6, 'pl': 0.45, 'ru': 0.55, 'es': 0.4, 'fr': 0.45, 'pt': 0.4, 'en': 0.45}

WRAPS = ((15, '-»', '«-'), (6, '-=', '=-'), (4, '.:', ':.'), (2, '.::', '::.'), (5, '**', '**'), (5, '*', '*'), (4, '#', ''),
         (2, '×', '×'), (2, '==', '=='), (2, '--', '--'), (4, '-', '-'), (1, '((', '))'), (1, '..', '..'), (2, '★', '★'),
         (1, '亗', '亗'), (1, 'ッ', 'ッ'), (1, '【', '】'), (1, '「', '」'), (1, '_', '_'), (1, '˘°*', '*°˘'), (1, '٠', '٠'),
         (1, '•', '•'), (1, '†', '†'))
SUFFIXES = ((4, 'ツ'), (3, 'ᵀᴹ'), (3, '™'), (1, '彡'), (1, '☆'), (1, '®'), (1, '亗'))
SEPARATORS = ('ㅤ', 'ㅤ', '　', '×', '_', '.', '•', '-')          # between two words
# capital look-alikes (Λ Σ Я ...) and fancy lowercase (α є я ...); small caps (ᴀ ʙ ᴄ)
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

# sade(): fancy letter -> Latin (the tables above + Cyrillic)
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
    """Replace letters with look-alikes: capital look-alikes if all are capitals, otherwise fancy lowercase; sometimes small caps."""
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
    """Decorate the ASCII name as on real servers (at the language's ratio; an undecorated name comes back as is). tag: clan tag suggestion
    (for the [TAG] suffix)."""
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
        if len(part) > 1 and r.random() < 0.3:              # between words: ㅤ, ×, _ ...
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
    """Is case-insensitive comparison safe for this name (the game matches names with .lower()): "ß".upper() is "SS", "İ".lower()
    becomes two letters; such a name is not found when typed in capitals."""
    return name.upper().lower() == name.lower() and len(name.lower()) == len(name)


def plain(name):
    """Drop the decoration, a Latin lowercase skeleton: "-»Ajαх×Ħøø«-" -> "ajaxhoo"; "DarkHunter" -> "darkhunter"."""
    out = []
    for c in str(name):
        g = _REVERSE.get(c) or _REVERSE.get(c.lower())
        if g is None:
            g = unicodedata.normalize('NFKD', c)
            g = ''.join(x for x in g if not unicodedata.combining(x))
        out.append(g.lower())
    return re.sub(r'[^a-z0-9]', '', ''.join(out))


def is_mentioned(name, msg):
    """Does this name appear in the message: the full name or (for a decorated name) its skeleton, on a word boundary."""
    m = str(msg).lower()
    if re.search(r'(?<!\w)%s(?!\w)' % re.escape(str(name).lower()), m):
        return True
    s = plain(name)
    if len(s) < 3 or s == str(name).lower():
        return False
    return any(plain(w) == s or len(s) >= 5 and plain(w).startswith(s) for w in re.split(r'\s+', m) if w)
