"""A bot's lasting chat persona: writing habits and life facts, the same every session (seeded by the bot's name).

A real player types the same way every time: always lowercase or always a capital first letter, the same laugh (sjsjsj, xd, lol), the same
address word (kanka, bro), the same few abbreviations. Re-rolling all of that per line was the strongest bot tell of the old templates.
The persona starts from the personality's style numbers (personality.generate_personality) so existing bots keep their character.
"""
import hashlib, random

from . import lexicon as LX

_cache = {}


def seed_of(*parts):
    return int(hashlib.md5('|'.join(str(p) for p in parts).encode('utf8')).hexdigest()[:12], 16)


class Persona:
    def __init__(self, b):
        k = b.k['personality']
        u = k.get('style') or {}
        o = k.get('traits') or {}
        self.lang = k.get('lang') if k.get('lang') in LX.LANGS else 'en'
        r = random.Random(seed_of('persona', b.name.lower()))
        self.name = b.name
        self.r = r
        low = u.get('lowercase', 0.6)
        self.case = 'lower' if r.random() < 0.25 + 0.7 * low else 'sentence' if r.random() < 0.8 else 'proper'
        self.punct = max(0.0, min(0.9, u.get('punctuation', 0.3) * r.uniform(0.2, 1.0)))   # a final dot / exclamation
        self.qmark = r.uniform(0.15, 0.95)                    # writes "?" at the end of a question
        self.emoji = max(0.0, min(0.6, u.get('emoji', 0.3) * r.uniform(0.2, 0.9)))
        self.error = max(0.0, min(0.25, u.get('error', 0.08) * r.uniform(0.6, 1.4)))
        self.fix = r.uniform(0.15, 0.7)                       # corrects a typo in the next line ("*lazer")
        self.abbr = max(0.0, min(1.0, u.get('abbreviation', 0.5)))
        self.ascii = r.random() < LX.ascii_ratio(self.lang)  # does not type the accented letters (ı ş ğ ü, ä ö ü ß ...)
        self.elong = r.uniform(0.0, 0.35)                     # "yaaa", "nooo"
        self.verbose = max(0.05, min(0.95, 0.25 + 0.6 * o.get('talkativeness', 0.5) + r.gauss(0, 0.12)))
        self.split = r.uniform(0.05, 0.45) * (0.5 + o.get('talkativeness', 0.5))
        self.cps = max(2.6, min(9.5, r.gauss(5.2, 1.4)))     # typing speed, characters per second
        self.english = r.random() < LX.english_share(self.lang)   # also answers English messages (in English)
        self.helpful = o.get('helpfulness', 0.5)
        self.social = o.get('sociability', 0.5)
        self.talk = o.get('talkativeness', 0.5)
        self.aggr = o.get('aggression', 0.5)
        self.favorites = {}
        self.abbreviations = {a: v for a, v in LX.abbreviations(self.lang) if r.random() < self.abbr}
        self.bio = LX.bio(self.lang, r)
        self.opinion = random.Random(seed_of('opinion', b.name.lower()))   # stable opinions ("is goliath worth it")

    def pick(self, cls, lang=None, r=None):
        """A word of the lexicon class: the persona's 1-3 favorites most of the time, any other now and then."""
        lang = lang or self.lang
        words = LX.lex(lang, cls)
        if not words:
            return None
        key = (lang, cls)
        fav = self.favorites.get(key)
        if fav is None:
            rr = random.Random(seed_of('fav', self.name.lower(), lang, cls))
            fav = self.favorites[key] = rr.sample(words, min(len(words), rr.choice((1, 2, 2, 3))))
        r = r or random
        return r.choice(fav) if r.random() < 0.82 else r.choice(words)

    def opinion_of(self, topic, choices):
        """A stable opinion: the same bot gives the same verdict on the same question."""
        rr = random.Random(seed_of('op', self.name.lower(), topic))
        return rr.choice(choices)


def of(b):
    p = _cache.get(b.uid)
    lang = b.k['personality'].get('lang')
    if p is None or p.name != b.name or p.lang != (lang if lang in LX.LANGS else 'en'):
        p = _cache[b.uid] = Persona(b)
    return p
