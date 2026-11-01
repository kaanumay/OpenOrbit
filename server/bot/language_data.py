"""Bot languages: bot/languages/<code>.json (one file per language; adding a file is enough for a new language).

A language file:
  code, name (the language's own name), weight (the share of bots in that language in a "mixed" roster)
  names      parts {entries: [...]} and patterns [[weight, pattern]]: a pattern may use {entries}, {list_k} (lowercase), {a|b} (from two lists),
             {list?} (empty half the time), {leet:list}. Names follow the game's name rule (Latin letters, digits, _ . -).
  templates  state -> lines (chat of the Normal mode; speech.template). Fields: {name} {map} {level} {ship} {tag} {clan}
             {leader} {who} {item}.
  abbreviation  [[word, abbreviation]] (the bot's style), ascii {letter: replacement} and ascii_ratio (players dropping accents)
  intent     intent -> words: the intent of the player's message in that language (speech.intent; tr/en ones are in the phrases in speech)
  reaction   congrats, farewell, welcome_back, roll_call -> phrases and game -> game words: the message type in Advanced mode
             (llm message type; en's are in llm.TYPES)
  harmful    phrases for self-harm, death wishes, severe insults (may be a regex): the model stays silent if its line is one of these
             (llm harmful check; en's are in llm._HARMFUL). It also holds unaccented spellings (the comparison drops accents).
"""
import json, os

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'languages')
ORDER = ('tr', 'en', 'de', 'es', 'fr', 'pl', 'pt', 'ru')        # the panel's order (same as the panel's languages)


def _load():
    out = {}
    for f in sorted(os.listdir(FOLDER)):
        if f.endswith('.json'):
            with open(os.path.join(FOLDER, f), encoding='utf8') as h:
                d = json.load(h)
            out[d['code']] = d
    return out


LANGUAGES = _load()
CODES = tuple(k for k in ORDER if k in LANGUAGES) + tuple(sorted(k for k in LANGUAGES if k not in ORDER))


def pick_mixed(r):
    """A language in the 'mixed' roster: by the files' weights."""
    return r.choices(CODES, weights=[LANGUAGES[k].get('weight', 5) for k in CODES])[0]
