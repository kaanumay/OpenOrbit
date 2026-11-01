"""A bot's personality: lasting traits, archetype, play habit, writing style, name; dynamic mood and memory of other people.

The roster is generated once when the pack is created (generate_roster, seeded and deterministic): the same pack gives the same bots on
every start. Traits are 0-1; the archetype gives the averages and noise is added per bot (two bots of one archetype are never identical).
The decision engine (brain.py) scores goals with these traits and the mood.
"""
import math, random, re, time

from . import name_style as NS

TRAITS = ('aggression', 'rekabet', 'sociability', 'patience', 'risk', 'loyalty', 'helpfulness', 'talkativeness', 'frugality',
              'ambition')

# archetype -> (share of the population, trait averages, description). The shares roughly follow a real server's distribution: most
# players grind aliens, a few are hunters and leaders; "casual" players log in for a few hours a week and progress slowly.
ARCHETYPES = {
    'grinder':  (0.27, dict(aggression=.35, rekabet=.50, sociability=.35, patience=.85, risk=.30, loyalty=.60, helpfulness=.50,
                           talkativeness=.30, frugality=.60, ambition=.75), 'PvE kasıcı'),
    'hunter':    (0.14, dict(aggression=.90, rekabet=.90, sociability=.45, patience=.40, risk=.80, loyalty=.50, helpfulness=.30,
                           talkativeness=.55, frugality=.35, ambition=.70), 'PvP avcısı'),
    'social':  (0.14, dict(aggression=.30, rekabet=.35, sociability=.90, patience=.50, risk=.40, loyalty=.80, helpfulness=.80,
                           talkativeness=.90, frugality=.50, ambition=.40), 'social'),
    'trader':  (0.08, dict(aggression=.20, rekabet=.55, sociability=.55, patience=.70, risk=.35, loyalty=.50, helpfulness=.40,
                           talkativeness=.50, frugality=.85, ambition=.60), 'tüccar'),
    'quester': (0.16, dict(aggression=.40, rekabet=.45, sociability=.40, patience=.70, risk=.45, loyalty=.55, helpfulness=.60,
                           talkativeness=.35, frugality=.55, ambition=.65), 'görevci'),
    'casual':   (0.17, dict(aggression=.30, rekabet=.20, sociability=.50, patience=.35, risk=.50, loyalty=.40, helpfulness=.55,
                           talkativeness=.50, frugality=.30, ambition=.25), 'casual'),
    'leader':   (0.04, dict(aggression=.55, rekabet=.75, sociability=.85, patience=.60, risk=.55, loyalty=.90, helpfulness=.70,
                           talkativeness=.75, frugality=.60, ambition=.85), 'leader'),
}

# the time the archetype gives the game (online-tendency multiplier) and its efficiency while playing (attention, optimization)
ACTIVITY = {'grinder': (1.3, 1.15), 'hunter': (1.2, 1.0), 'social': (1.0, 0.8), 'trader': (0.9, 0.95), 'quester': (1.0, 1.0),
            'casual': (0.55, 0.7), 'leader': (1.3, 1.0)}

# play habit: hour -> online tendency (0-1) and session length (minutes, min-max)
HABITS = {
    'evening':   (0.40, [0.15] * 7 + [0.2] * 5 + [0.3] * 5 + [0.8] * 5 + [0.5] * 2, (40, 150)),
    'night_owl': (0.20, [0.7] * 4 + [0.2] * 8 + [0.25] * 6 + [0.5] * 3 + [0.85] * 3, (60, 240)),
    'daytime':  (0.20, [0.05] * 8 + [0.6] * 10 + [0.4] * 4 + [0.1] * 2, (30, 120)),
    'devoted':    (0.20, [0.5] * 8 + [0.7] * 16, (120, 420)),
}

EMOTIONS = ('anger', 'morale', 'boredom', 'fatigue', 'confidence')
EMOTION_BASELINE = dict(anger=0.0, morale=0.6, boredom=0.0, fatigue=0.0, confidence=0.5)
EMOTION_DECAY_SEC = dict(anger=600, morale=1800, boredom=900, fatigue=1e9, confidence=1200)    # time to return to baseline (half-life)


def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


# ------------------------------------------------------------------------------------------------------------ names
_LEET = {'a': '4', 'e': '3', 'i': '1', 'o': '0', 's': '5', 't': '7'}
_NUMBERS = ('1', '7', '13', '23', '34', '35', '06', '16', '41', '42', '61', '69', '77', '88', '99', '007', '123', '1903', '1905',
            '1907', '1453', '2000', '2003', '2005', '2010', '666', '777', '1923', '01', '07', '27', '33', '38', '55', '21')
NAME_PATTERN = re.compile(r'^[^\x00-\x20/|<>\\"\x7f\u200b-\u200f\u2028\u2029]{3,20}$')   # fancy names like on real servers
#                                                  (name_style.py); no spaces, / | < > \ " or invisible characters


def _leet(s, r, ratio):
    return ''.join(_LEET[c.lower()] if c.lower() in _LEET and r.random() < ratio else c for c in s)


def generate_name(r, lang='mixed'):
    """A name that resembles usernames on a real MMO server, built from the language's own names (bot/languages/<code>.json names: parts
    and weighted patterns; 'mixed': a language picked by the files' weights)."""
    from .language_data import LANGUAGES, pick_mixed
    d = LANGUAGES.get(lang) or LANGUAGES[pick_mixed(r)]
    a = d['names']
    pattern = r.choices([x[1] for x in a['patterns']], weights=[x[0] for x in a['patterns']])[0]
    s = re.sub(r'\{([^}]+)\}', lambda m: _part(m.group(1), a['parts'], r), pattern)
    s = re.sub(r'[^A-Za-z0-9_.\-]', '', s)
    return s[:20] if len(s) >= 3 else s + r.choice(a['parts'].get('number') or _NUMBERS)


def _part(name, parts, r):
    """Pattern fields: {entries}, {list_k} lowercase, {a|b} from two lists, {list?} empty half the time, {leet:list}."""
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


# ------------------------------------------------------------------------------------------------------------ roster
def _choice(r, table):
    """{key: (share, ...)} or {key: share} -> a key picked by share."""
    ks = list(table)
    ws = [table[k][0] if isinstance(table[k], tuple) else table[k] for k in ks]
    return r.choices(ks, ws)[0]


def generate_personality(r, archetype=None, lang='tr'):
    """A bot's lasting personality: archetype, traits (average + noise), habit, style, chat language."""
    a = archetype or _choice(r, ARCHETYPES)
    avg = ARCHETYPES[a][1]
    traits = {k: round(clamp(r.gauss(avg[k], 0.14), 0.02, 0.98), 2) for k in TRAITS}
    take = _choice(r, HABITS)
    talk = traits['talkativeness']
    style = dict(
        lowercase=round(clamp(r.gauss(0.6, 0.25)), 2),       # writes everything in lowercase
        punctuation=round(clamp(r.gauss(0.3, 0.25)), 2),        # end-of-sentence punctuation
        abbreviation=round(clamp(r.gauss(0.5, 0.25)), 2),         # "slm", "nbr", "tmm", "gg", "np"
        emoji=round(clamp(r.gauss(0.3 + talk * 0.2, 0.2)), 2),  # ":D", "xD", "^^"
        error=round(clamp(r.gauss(0.08, 0.06), 0, 0.3), 2),    # typo
        uppercase=round(clamp(r.gauss(0.05 + traits['aggression'] * 0.1, 0.05), 0, 0.4), 2),   # SHOUTS
    )
    return dict(archetype=a, traits=traits, habit=take, style=style, lang=lang,
                reaction_sec=round(clamp(r.gauss(0.9, 0.35), 0.35, 2.0), 2))   # human reaction time (s): delay in concrete combat


def generate_roster(seed, count, company_distribution=(1, 1, 1), lang='mixed', existing=(), name_lang=None, special=(), pool=None):
    """The pack's roster: [{no, name, company, personality}]. company_distribution: (MMO, EIC, VRU) weights. existing: names already used
    (case-insensitive; must not collide with the player's and other bots' names). Same seed and input give the same roster.
    name_lang: language of the names ('mixed': by the files' weights); lang: chat language ('mixed': each bot speaks the language of its name).
    special: the user's own bots [{name, company?, archetype?, lang?}] (player request 2026-10-30): at the head of the roster, missing
    fields are generated like the others; one with a company takes a slot of that company in the distribution.
    pool: real player names {lang: [name]} (bot/dostats.py): names come from there first, then are generated once it runs out."""
    from .language_data import LANGUAGES, pick_mixed
    name_lang = name_lang or lang
    r = random.Random(seed)
    used = {str(a).lower() for a in existing}
    special = [o for o in special if str(o['name']).lower() not in used][:count]
    total = sum(company_distribution) or 1
    # split the companies into whole numbers by share (largest remainder), then shuffle: the distribution holds even in a small roster
    shares = [count * f / total for f in company_distribution]
    number = [int(p) for p in shares]
    for i in sorted(range(3), key=lambda i: shares[i] - number[i], reverse=True)[:count - sum(number)]:
        number[i] += 1
    companies = [f + 1 for f in range(3) for _ in range(number[f])]
    r.shuffle(companies)
    for o in special:                                   # a special bot with a company takes a slot of that company
        if o.get('company') in companies:
            companies.remove(o['company'])
    remaining = iter(companies)
    out = []
    for no in range(1, count + 1):
        o = special[no - 1] if no <= len(special) else {}
        firma = o.get('company') or next(remaining, None) or r.randint(1, 3)
        name_langs = name_lang if name_lang in LANGUAGES else pick_mixed(r)
        chat = o.get('lang') or (lang if lang in LANGUAGES else name_langs)          # mixed: a bot with a German name speaks German
        real = [x for x in (pool or {}).get(name_langs) or [y for v in (pool or {}).values() for y in v]
                  if x.lower() not in used and NS.is_case_safe(x)]
        if o:
            name = str(o['name'])
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
        x = dict(no=no, name=name, company=firma, personality=dict(generate_personality(r, archetype=o.get('archetype'), lang=chat), name_lang=o.get('lang') or name_langs))
        if o:
            x['special'] = True                             # the user's bot (marked in the panel's Roster)
        out.append(x)
    return out


# ------------------------------------------------------------------------------------------------------------ mood
class Mood:
    """Dynamic emotions (0-1): events push them, over time they return to baseline (exponential decay). Stored as a dict in the save."""
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


# ------------------------------------------------------------------------------------------------------------ memory
EVENTS = {          # event -> effect on the relationship
    'killed_me': -0.35, 'i_killed': -0.05, 'helped_me': 0.25, 'i_helped': 0.1, 'sohbet': 0.03, 'insult': -0.2,
    'praise': 0.12, 'group': 0.08, 'clan': 0.1, 'friend': 0.2, 'reddetti': -0.08, 'hunted_together': 0.05,
    'gossip_good': 0.06, 'gossip_bad': -0.08,          # heard from another bot (memories.hear_gossip)
}


class Memory:
    """Relationship toward people (-1 grudge .. 1 friendship) and event counts. In the save: {lowercase name: {d, n: {incident: count}, s: last time}}.
    A relationship not seen for a long time slowly returns to zero (forgetting); at most MAX_COUNT people are kept (the oldest drops)."""
    MAX_COUNT = 60
    FORGET_SEC = 6 * 3600

    def __init__(self, d=None):
        self.d = d if d is not None else {}
        self.listener = None                # (name, kind, time) -> event hook: the memory journal on the strong provider (memories; the manager binds it)

    def event(self, name, kind, now=None, multiplier=1.0):
        if not str(name or '').strip():
            return 0.0                                     # someone with an unknown identity (nameless): nobody to remember
        now = now or time.time()
        k = str(name).lower()
        e = self.d.setdefault(k, {'d': 0.0, 'n': {}, 's': now, 'name': str(name)})
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
        return [e['name'] for e in self.d.values() if self.relation(e['name'], now) <= threshold]

    def allies(self, threshold=0.3, now=None):
        return [e['name'] for e in self.d.values() if self.relation(e['name'], now) >= threshold]


def timezone(personality):
    """The bot's time-zone offset (hours): most are on the server's time, some in neighboring countries, a few far away. If missing from the
    personality, derived from its name (permanent and deterministic for old saves). If everyone lived on the same time, the server would be empty at night and packed in the evening."""
    d = personality.get('timezone_offset')
    if d is None:
        import zlib
        r = zlib.crc32(str(personality.get('_name') or personality.get('archetype')).encode()) % 100
        d = 0 if r < 55 else -1 if r < 70 else 1 if r < 82 else -2 if r < 88 else 2 if r < 93 else -7 if r < 97 else 7
        personality['timezone_offset'] = d
    return d


def taste(personality):
    """The bot's lasting ship taste (ship family): so not everyone converges on the same ship. If missing from the personality, derived from its name (old saves)."""
    z = personality.get('taste')
    if z is None:
        import zlib
        families = ('goliath', 'vengeance', 'aegis', 'citadel', 'spearhead', 'leonov', 'nostromo', 'piranha', 'bigboy', 'solace')
        z = personality['taste'] = families[zlib.crc32(('z' + str(personality.get('_name') or personality.get('archetype'))).encode()) % len(families)]
    return z


def online_tendency(personality, hour):
    """Online tendency at this hour (0-23; in the bot's own time zone) according to habit and archetype."""
    return HABITS[personality['habit']][1][int(hour + timezone(personality)) % 24] * ACTIVITY[personality['archetype']][0]


def session_min(personality, r=random):
    a, b = HABITS[personality['habit']][2]
    return r.uniform(a, b)


def softmax_pick(scores, temperature, r=random):
    """[(key, score)] -> a key chosen by temperature (at a low temperature always the highest)."""
    if not scores:
        return None
    t = max(0.02, temperature)
    m = max(p for _, p in scores)
    ws = [math.exp((p - m) / t) for _, p in scores]
    return r.choices([k for k, _ in scores], ws)[0]
