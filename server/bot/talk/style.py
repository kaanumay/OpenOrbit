"""Turns an expanded line into the messages a bot actually sends, in its own stable way of typing (persona.py):
case habit, its abbreviations, dropped accents, question mark habit, final punctuation, emoticon, elongated words, a typo now and
then and its correction in the next message ("*lazer"), and a thought sent as two messages (the grammar's // split point)."""
import re

from . import lexicon as LX

_NEIGHBOR = dict(zip('qwertyuiopasdfghjklzxcvbnm', ('wa', 'qes', 'wrd', 'etf', 'ryg', 'tuh', 'yij', 'uok', 'ipl', 'ol', 'qsz', 'awdx',
                                                     'sefc', 'drgv', 'fthb', 'gyjn', 'hukm', 'jil', 'kol', 'asx', 'zsdc', 'xdfv',
                                                     'cfgb', 'vghn', 'bhjm', 'njk')))
_WORD = re.compile(r'[^\W\d_]{4,}', re.U)
_VOWEL_END = re.compile(r'\b([^\W\d_]{1,4}?)([aeiouıüöäoyа-яё])\b', re.U | re.I)
_QLIKE = re.compile(r'(\bm[ıiuü](s[ıiuü]n(.z)?|y[ıiuü]z|d[ıiuü]r)?\s*$|\b(var m[ıi]|yok mu|ne oldu|nerde|nerede)\s*$|'
                    r'^\s*(who|what|where|which|how|why|anyone|any1|does|do you|is it|are you|can i|wer|wo|wie|warum|quien|qué|que|donde|dónde|'
                    r'como|cómo|qui|quoi|où|comment|kto|gdzie|jak|czy|quem|onde|cadê|кто|что|где|как|почему)\b)', re.I)
_LAUGH_END = re.compile(r'(sj|sk|js|kd|asd|xd|haha|ahah|lol|lmao|rofl|kek|hah|[:;][dDpP)(]|\^\^)\w*\W*$', re.I)
_CAPS_KEEP = re.compile(r'\b(EIC|MMO|VRU|LF-?\d|MP-?\d|CBS|GG|PVP|PVE|EP|XP)\b')


def _is_laugh(text):
    from . import nlu as NLU
    f = NLU.fold(text)
    return bool(f) and (bool(NLU.LAUGH.match(f)) or (len(f.split()) == 1 and bool(NLU._SMASH.match(f))))


def _lower(text, lang):
    if lang == 'tr':
        text = text.replace('I', 'ı').replace('İ', 'i')
    return text.lower()


def _typo(word, r):
    i = r.randrange(1, len(word) - 1)
    k = r.random()
    if k < 0.4:                                            # two letters swapped
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if k < 0.65:                                           # a letter dropped
        return word[:i] + word[i + 1:]
    if k < 0.8:                                            # a letter doubled
        return word[:i] + word[i] + word[i:]
    c = word[i].lower()
    if c in _NEIGHBOR:                                     # a neighbouring key
        return word[:i] + r.choice(_NEIGHBOR[c]) + word[i + 1:]
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def messages(text, persona, r, question=False, lang=None, protect=()):
    """-> [message, ...] (usually one). protect: words never altered (names, maps)."""
    lang = lang or persona.lang
    parts = [p.strip() for p in text.split('//') if p.strip()]
    if len(parts) > 1 and r.random() >= persona.split:
        parts = [', '.join(parts) if r.random() < 0.7 else ' '.join(parts)]
    out = []
    table = LX.ascii_table(lang) if persona.ascii and r.random() < 0.95 else None
    keep = {w.lower() for w in protect if w}
    for n, line in enumerate(parts):
        last = n == len(parts) - 1
        for a, b in persona.abbreviations.items():
            line = re.sub(r'(?<!\w)%s(?!\w)' % re.escape(a), b, line, flags=re.I)
        if table:
            line = line.translate(table)
        if persona.case == 'lower':
            caps = _CAPS_KEEP.findall(line) if r.random() < 0.3 else ()
            line = _lower(line, lang)
            for c in caps:
                line = line.replace(c.lower(), c, 1)
        elif line and persona.case in ('sentence', 'proper') and line[0].isalpha():
            line = line[0].upper() + line[1:]
        if persona.elong and r.random() < persona.elong * 0.35:
            m = list(_VOWEL_END.finditer(line))
            if m:
                x = r.choice(m)
                if x.group(0).lower() not in keep:
                    line = line[:x.end()] + x.group(2) * r.randint(1, 3) + line[x.end():]
        q = (last and question) or bool(_QLIKE.search(line))     # "kaç oldu bakan var mı" is a question even inside a statement act
        if line.endswith('?') and r.random() > persona.qmark:
            line = line.rstrip('?').rstrip()
        elif q and not line.endswith('?') and r.random() < persona.qmark * 0.8:
            line += '?'
        elif last and not q and line[-1:].isalnum() and len(line) > 3 and not _LAUGH_END.search(line) and r.random() < persona.punct:
            line += '.' if persona.case != 'lower' or r.random() < 0.6 else r.choice(('!', '..', '...'))
        line = re.sub(r'(?i)\b(lol|xd|haha|kek|lmao|jaja|kkk)\b(\s+\1\b)+', r'\1', line)
        sad = tuple(x.lower() for x in (LX.lex(lang, 'sad') or ()) if x)
        if last and line[-1:] not in ')(!' and not _LAUGH_END.search(line) and not line.rstrip('.!').lower().endswith(sad) \
                and r.random() < persona.emoji * 0.45:
            emo = persona.pick('emo', lang, r)
            if emo:
                line += ' ' + emo
        fixed = None
        if r.random() < persona.error:
            words = [w for w in _WORD.findall(line) if w.lower() not in keep and not _is_laugh(w)]
            if words:
                w = r.choice(words)
                t = _typo(w, r)
                if t != w:
                    line = line.replace(w, t, 1)
                    if r.random() < persona.fix:
                        fixed = r.choice(('*' + w, '*' + w, w + '*'))
                        if persona.case == 'lower':
                            fixed = _lower(fixed, lang)
        if _is_laugh(line.strip()):
            line = line.lower()                                  # "Lkdsjfl" / "Hahaha": nobody shift-types a laugh
        out.append(line)
        if fixed:
            out.append(fixed)
    return [m for m in out if m.strip()]
