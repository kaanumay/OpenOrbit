"""Reading a chat message: its language, acts (greeting, question, insult, "are you a bot" ...), topics (ship, laser, age ...),
question type and entities (maps, ships, lasers, aliens, companies, numbers, names of bots).

Cues come from talk/lang/<code>.json nlu (every language's cues are tried on every message; the language with the most hits is the
message's language). Game entities are the same in every language and live here.
"""
import re, unicodedata

from . import lexicon as LX

MAP = re.compile(r'(?<![\w-])([1-5])\s*[-xX/]\s*([1-8xX]|bl)(?![\d])', re.I)
SHIP_ALIAS = {'goliath': ('goliath', 'goli', 'golli'), 'vengeance': ('vengeance', 'venge', 'vengi', 'veng', 'venga'),
              'leonov': ('leonov', 'leo', 'leonof'), 'bigboy': ('bigboy', 'big boy', 'bigb'), 'nostromo': ('nostromo', 'nosto', 'nostro'),
              'piranha': ('piranha', 'pira', 'piranya'), 'liberator': ('liberator', 'libe', 'libo'), 'phoenix': ('phoenix', 'fönix', 'phonix', 'fenix'),
              'aegis': ('aegis',), 'citadel': ('citadel', 'cita'), 'spearhead': ('spearhead', 'spear'), 'solace': ('solace',),
              'diminisher': ('diminisher', 'dimi'), 'sentinel': ('sentinel',), 'spectrum': ('spectrum',), 'venom': ('venom',),
              'cyborg': ('cyborg',), 'tartarus': ('tartarus',), 'pusat': ('pusat',), 'yamato': ('yamato',), 'defcom': ('defcom',)}
LASER = re.compile(r'\b(lf|mp|sl|sll)\s*-?\s*(0?[1-4])\b', re.I)
ALIEN_ALIAS = {'streuner': ('streuner', 'stru', 'streu', 'streuneri'), 'lordakia': ('lordakia', 'lorda', 'lordak'),
               'saimon': ('saimon', 'saimo'), 'mordon': ('mordon',), 'devolarium': ('devolarium', 'devo', 'devolar'),
               'sibelon': ('sibelon',), 'sibelonit': ('sibelonit', 'sibelo'), 'lordakium': ('lordakium',), 'kristallin': ('kristallin', 'kristal'),
               'kristallon': ('kristallon',), 'cubikon': ('cubikon', 'kubikon'), 'protegit': ('protegit',), 'boss': ('boss', 'bosslar', 'bosses', 'bossu')}
COMPANY = re.compile(r'\b(mmo|eic|vru|mars|earth|venus)\b', re.I)
COMPANY_NO = {'mmo': 1, 'mars': 1, 'eic': 2, 'earth': 2, 'vru': 3, 'venus': 3}
NUMBER = re.compile(r'(?<![\w-])(\d{1,4})(?![\w-])')
LAUGH = re.compile(r'^(\W*(x+d+|xd|lo+l+|lmao+|rofl|kek|ha(ha)+h?|a?h(ah)+a?|he(he)+|sj(sj)+s?|s(js)+j?|as[dfgh]{2,}\w*|jaja+|ja(ja)+|'
                   r'хаха+|ахах\w*|kk+|rs(rs)+|mdr|ptdr|:d+|xdd+|:p|\^\^)\W*)+$', re.I)
_SMASH = re.compile(r'^[asdfghjklşi]{6,}$', re.I)


_LETTERS = str.maketrans({'ß': 'ss', 'ł': 'l', 'ø': 'o', 'đ': 'd', 'æ': 'ae', 'œ': 'oe'})     # letters NFKD does not split


def fold(text):
    """Lowercase without accents (ı -> i, ş -> s, ä -> a): cues match messages typed with or without accents."""
    text = text.replace('İ', 'i').replace('I', 'i').replace('ı', 'i').lower().translate(_LETTERS)
    return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))


def _alias_re(table):
    pairs = sorted(((a, k) for k, v in table.items() for a in v), key=lambda x: -len(x[0]))
    rx = re.compile(r'(?<!\w)(%s)(?:[a-z]{0,4})?(?!\w)' % '|'.join(re.escape(fold(a)) for a, _ in pairs))
    return rx, {fold(a): k for a, k in pairs}


SHIP_RE, SHIP_OF = _alias_re(SHIP_ALIAS)
ALIEN_RE, ALIEN_OF = _alias_re(ALIEN_ALIAS)


def _compile():
    """cue -> [(lang, regex)]: one regex per language and cue (words are folded; a word ending in * matches as a prefix)."""
    out = {}
    for lang, d in LX.DATA.items():
        for cue, words in (d.get('nlu') or {}).items():
            alts = []
            for w in words:
                if w.startswith('re:'):                       # fold the letters but keep escapes (\W must not become \w)
                    alts.append(''.join(x if x.startswith('\\') else fold(x) for x in re.split(r'(\\.)', w[3:])))
                    continue
                w = fold(w)
                if w.endswith('*'):
                    alts.append(re.escape(w[:-1]) + r'\w*')
                else:
                    alts.append(re.escape(w))
            if alts:
                out.setdefault(cue, []).append((lang, re.compile(r'(?<!\w)(%s)(?!\w)' % '|'.join(alts))))
    return out


CUES = _compile()
ACTS = ('greet', 'bye', 'back', 'brb', 'thanks', 'congrats', 'yes', 'no', 'insult', 'botq', 'rollcall', 'complain', 'howareyou', 'sorry',
        'wow', 'sad', 'newbie', 'brag', 'agree', 'ask', 'blame', 'helpq', 'wish', 'likeq', 'presence')
TOPICS = ('ship', 'laser', 'shield', 'drone', 'pet', 'map', 'alien', 'boss', 'quest', 'uri', 'credits', 'honor', 'level', 'clan', 'company',
          'gate', 'pvp', 'lag', 'event', 'age', 'origin', 'job', 'playtime', 'food', 'sleep', 'music', 'football', 'weather', 'doing',
          'realname', 'tired', 'school', 'start', 'best', 'money', 'game', 'quiet', 'ore', 'ammo', 'bored')
FACT_CUES = ('get', 'price', 'what', 'sell', 'make', 'reward', 'xp')       # what a question about a thing wants to know (facts.py)
QTYPES = ('q_which', 'q_worth', 'q_where', 'q_how', 'q_why', 'q_when', 'q_howmuch', 'q_who', 'q_what', 'q_yn')     # priority order


class Msg:
    def __init__(self, text):
        self.text = text
        self.f = fold(text)
        self.acts, self.topics, self.qtype, self.langs = set(), set(), None, {}
        self.question = False
        self.you = self.all = self.me = self.after = self.inherited = self.sure = self.fav = self.want = False
        self.entities, self.fq = [], set()
        self.maps, self.ships, self.lasers, self.aliens, self.companies, self.numbers, self.names = [], [], [], [], [], [], []
        self.laugh = False
        self.lang = None

    def __repr__(self):
        return 'Msg(%r lang=%s acts=%s topics=%s q=%s/%s you=%s all=%s)' % (self.text, self.lang, sorted(self.acts), sorted(self.topics),
                                                                          self.question, self.qtype, self.you, self.all)

    @property
    def main(self):
        """The leading act: what the message mainly does."""
        a = self.acts
        for k in ('botq', 'insult', 'brb', 'back', 'bye', 'congrats', 'thanks', 'sorry'):
            if k in a and not (self.question and k in ('back', 'bye') and len(self.f.split()) > 4):
                return k
        if 'greet' in a and (len(self.f.split()) <= 4 or not self.question):
            return 'howareyou' if 'howareyou' in a else 'greet'
        if 'howareyou' in a:
            return 'howareyou'
        if 'rollcall' in a:
            return 'rollcall'
        if 'wish' in a and not self.question:                 # "kolay gelsin", "gl hf"
            return 'wish'
        for k in ('blame', 'helpq', 'likeq'):                  # "nobody came", "anyone coming?", "anyone like fries?"
            if k in a:
                return k
        if self.question:
            return 'question'
        for k in ('complain', 'brag', 'newbie', 'sad', 'wow', 'yes', 'no', 'agree'):
            if k in a:
                return k
        if self.laugh:
            return 'laugh'
        return 'statement'

    @property
    def topic(self):
        """The leading topic (the most specific one)."""
        for k in ('howareyou', 'age', 'origin', 'job', 'school', 'playtime', 'realname', 'doing', 'boss', 'alien', 'laser', 'ammo', 'ship', 'drone',
                  'pet', 'ore',
                  'shield', 'gate', 'quest', 'uri', 'credits', 'money', 'honor', 'level', 'clan', 'pvp', 'company', 'start', 'lag', 'event',
                  'food', 'sleep', 'tired', 'bored', 'music', 'football', 'weather', 'quiet', 'map', 'best', 'game'):
            if k in self.topics:
                return k
        return None


def read(text, bot_names=()):
    """-> Msg. bot_names: names that may be mentioned (decorated names are matched by name_style)."""
    m = Msg(text)
    f = m.f
    if bot_names:
        from .. import name_style as NS
        from . import facts as FA
        words = [w for w in re.findall(r'[a-z0-9]+', f) if len(w) >= 4 and w not in _stop() and w not in SHIP_OF and w not in ALIEN_OF
                 and not FA.find(w)]                            # "alpha" is the gate, not AlphaHammer16
        hit = []
        m.names = [n for n in bot_names if NS.is_mentioned(n, text)]
        if not m.names:                                         # a short name only when no full name is written ("akinci" in Yalniz_Akinci)
            m.names = [n for n in bot_names if _short_mention(n, words, hit)]
        for n in m.names:                                      # the rest is read without the names in it
            for v in sorted({fold(str(n)), fold(NS.plain(n) or '')} | set(hit), key=len, reverse=True):
                if len(v) >= 3:
                    f = re.sub(r'(?<![a-z0-9])%s(?![a-z0-9])' % re.escape(v), ' ', f)
    for cue, rows in CUES.items():
        for lang, rx in rows:
            if rx.search(f):
                m.langs[lang] = m.langs.get(lang, 0) + (0.5 if cue == 'stop' else 1)
                if cue in ACTS:
                    m.acts.add(cue)
                elif cue in TOPICS:
                    m.topics.add(cue)
                elif cue in QTYPES:
                    if m.qtype is None or QTYPES.index(cue) < QTYPES.index(m.qtype):
                        m.qtype = cue
                elif cue == 'me':
                    m.me = True
                elif cue == 'after':
                    m.after = True
                elif cue == 'you':
                    m.you = True
                elif cue == 'all':
                    m.all = True
                elif cue == 'sure':
                    m.sure = True
                elif cue == 'fav':
                    m.fav = True
                elif cue == 'want':
                    m.want = True
                elif cue in FACT_CUES:
                    m.fq.add(cue)
    if m.langs:
        m.lang = max(m.langs, key=lambda k: (m.langs[k], k == 'en'))
    m.question = text.rstrip().endswith('?') or m.qtype is not None or 'ask' in m.acts or \
        ((m.you or m.all) and bool(m.topics & {'age', 'origin', 'job', 'school', 'playtime', 'realname', 'level', 'ship', 'clan', 'doing', 'music',
                                                'food', 'sleep', 'tired', 'football', 'weather'}))
    for a, b in MAP.findall(text):
        m.maps.append('%s-%s' % (a, b.upper() if b.isalpha() else b))
    m.ships = list(dict.fromkeys(SHIP_OF[x] for x in SHIP_RE.findall(f) if x in SHIP_OF))
    m.lasers = list(dict.fromkeys(('%s-%d' % (a.upper(), int(n))) for a, n in LASER.findall(f)))
    m.aliens = list(dict.fromkeys(ALIEN_OF[x] for x in ALIEN_RE.findall(f) if x in ALIEN_OF))
    m.companies = list(dict.fromkeys(COMPANY_NO[x.lower()] for x in COMPANY.findall(f)))
    m.numbers = [int(x) for x in NUMBER.findall(MAP.sub(' ', f))]
    if m.ships:
        m.topics.add('ship')
    if m.lasers:
        m.topics.add('laser')
    if m.aliens:
        m.topics.add('boss' if m.aliens == ['boss'] else 'alien')
    if m.maps:
        m.topics.add('map')
    if m.companies:
        m.topics.add('company')
    from . import facts as FA
    m.entities = [k for k in FA.find(f) if FA.BY_KEY[k]['kind'] != 'gate' or m.fq or m.qtype or m.want]      # 'delta force': not a gate
    m.topics |= FA.topics_of(m.entities)
    if m.entities and (m.want or m.fq):                         # "lf4 istiyorum", "x4 fiyatı": a question even without "?"
        m.question = True
    words = f.split()
    m.laugh = bool(LAUGH.match(f)) or (len(words) == 1 and bool(_SMASH.match(f)))
    return m


_STOP = []


def _stop():
    """Common words of every language (never taken for the start of a name)."""
    if not _STOP:
        _STOP.append({fold(w) for d in LX.DATA.values() for w in (d.get('nlu') or {}).get('stop', ())})
    return _STOP[0]


def _short_mention(name, words, hit=None):
    """A name written the short way players write it: "elif" for elifkasirga, "kasirga" for ==Kasirga_tr==. hit: gets the words used."""
    from .. import name_style as NS
    s = re.sub(r'[^a-z0-9]', '', fold(NS.plain(name) or str(name)))
    w = [x for x in words if s.startswith(x)] if len(s) >= 5 else []
    if hit is not None:
        hit.extend(w)
    return bool(w)
