"""The panel's language (chosen in the setup wizard on first launch; save/panel.json 'dil', changed from the Panel page).

Texts are written in English in the code (the source language); those of the other languages are in ui/<code>.json, the key being the
English text itself (like gettext; Turkish included: ui/tr.json). The UI (panel.js T()) and Python (t()) use the same dictionaries. A text
missing from the dictionary stays English: a partial translation is usable too. Format: %s in Python texts, {0} {1} … in the UI. Missing
translations or ones whose format does not match are caught by test/test_panel_lang.py.

New language: add it to LANGUAGES, write ui/<code>.json. Missing texts: python lang.py <code>
"""
import json, os, sys, threading

# code -> (name in its own language, locale for date/number format)
LANGUAGES = {
    'tr': ('Türkçe', 'tr-TR'),
    'en': ('English', 'en-US'),
    'de': ('Deutsch', 'de-DE'),
    'es': ('Español', 'es-ES'),
    'fr': ('Français', 'fr-FR'),
    'pl': ('Polski', 'pl-PL'),
    'pt': ('Português (Brasil)', 'pt-BR'),
    'ru': ('Русский', 'ru-RU'),
}
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui')
DICTIONARY = os.path.join(UI_DIR, 'tr.json')          # every message id has a Turkish translation
_selected = None                  # the panel binds: () -> a code from DILLER | None
_dictionary = {}
_lock = threading.Lock()


def bind(fn):
    """Bind the function that returns the selected language (panel: CFG.get('dil'))."""
    global _selected
    _selected = fn


def current():
    try:
        d = _selected() if _selected else None
    except Exception:
        d = None
    return d if d in LANGUAGES else 'tr'


def mapping(code='en'):
    with _lock:
        if code not in _dictionary:
            try:
                with open(os.path.join(UI_DIR, code + '.json'), encoding='utf8') as fh:
                    _dictionary[code] = json.load(fh)
            except (OSError, ValueError):
                _dictionary[code] = {}
        return _dictionary[code]


def entries():
    """The UI's language choice: code, name, locale and the ratio of translated texts (relative to the Turkish dictionary: every text has
    its Turkish)."""
    full = len(mapping('tr')) or 1
    return [{'code': k, 'name': name, 'local': local,
             'coverage': 100 if k in ('tr', 'en') else min(100, round(100 * len(mapping(k)) / full))}
            for k, (name, local) in LANGUAGES.items()]


def t(text, *args):
    """The text in the selected language (itself if absent: English); formatted with % if args is given."""
    lang = current()
    if text and lang != 'en':
        text = mapping(lang).get(text) or text
    return text % args if args else text


if __name__ == '__main__':      # for translators: the texts missing in a language (key = English text, JSON)
    code = sys.argv[1] if len(sys.argv) > 1 else ''
    if code not in LANGUAGES or code == 'en':
        sys.exit('usage: python lang.py <%s>' % '|'.join(k for k in LANGUAGES if k != 'en'))
    sys.stdout.reconfigure(encoding='utf-8')
    have = mapping(code)
    json.dump({k: k for k in mapping('tr') if k not in have}, sys.stdout, ensure_ascii=False, indent=0)
    print()
