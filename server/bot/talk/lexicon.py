"""The chat engine's language data: talk/lang/<code>.json (one file per language, same keys in every language).

  lex     class -> words (address words, laughs, ok, thanks ...): a persona keeps its own favorites (persona.pick)
  acts    act -> patterns (grammar.py): everything a bot can say
  nlu     cue -> words or regex fragments: reading a message (nlu.py); cues of every language are tried on every message
  bio     life facts a persona draws once: cities, occupations by age
  english share of the language's players who also chat in English
The abbreviations and the accent dropping ratio come from the bot language file (bot/languages/<code>.json).
"""
import json, os

from ..language_data import LANGUAGES

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lang')


def _load():
    out = {}
    for f in sorted(os.listdir(FOLDER)):
        if f.endswith('.json'):
            with open(os.path.join(FOLDER, f), encoding='utf8') as h:
                out[f[:-5]] = json.load(h)
    return out


DATA = _load()
LANGS = tuple(k for k in DATA if k in LANGUAGES)


def lex(lang, cls):
    return (DATA.get(lang) or DATA['en']).get('lex', {}).get(cls) or DATA['en'].get('lex', {}).get(cls)


def act(lang, name):
    """The patterns of an act in the language (English if the language lacks it)."""
    d = DATA.get(lang) or DATA['en']
    return d.get('acts', {}).get(name) or DATA['en']['acts'].get(name)


def has_act(lang, name):
    return bool((DATA.get(lang) or {}).get('acts', {}).get(name))


def ascii_table(lang):
    d = LANGUAGES.get(lang) or {}
    return str.maketrans(d['ascii']) if d.get('ascii') else None


def ascii_ratio(lang):
    return (LANGUAGES.get(lang) or {}).get('ascii_ratio', 0.0)


def english_share(lang):
    return 1.0 if lang == 'en' else (DATA.get(lang) or {}).get('english', 0.5)


def abbreviations(lang):
    """[(word, abbreviation)]: the bot language file's list plus the engine's own."""
    base = [tuple(x) for x in (LANGUAGES.get(lang) or {}).get('abbreviation', ())]
    return base + [tuple(x) for x in (DATA.get(lang) or {}).get('abbreviation', ()) if tuple(x) not in base]


def bio(lang, r):
    """Life facts of a persona: age, occupation, city, playing since (year), returning player."""
    d = (DATA.get(lang) or DATA['en']).get('bio') or DATA['en']['bio']
    age = int(max(14, min(44, round(r.gauss(23.5, 6.5)))))
    if age < 18:
        occ = 'school'
    elif age < 24:
        occ = r.choices(('uni', 'work', 'none', 'army'), weights=(55, 32, 9, 4 if lang in ('tr', 'ru') else 0))[0]
    else:
        occ = r.choices(('work', 'none', 'uni'), weights=(80, 10, 10))[0]
    since = min(2026, max(2008, int(r.triangular(2008, 2025, 2011))))
    c = r.choice(d['cities'])
    city, city_from = (c[0], c[1]) if isinstance(c, list) else (c, c)
    return dict(age=age, occ=occ, job=r.choice(d['jobs']) if occ == 'work' else '', city=city, city_from=city_from, since=since,
                returning=since < 2018 and r.random() < 0.55, night=r.random() < 0.45)
