"""Panelin dili (ilk açılışta kurulum sihirbazında seçilir; save/panel.json 'dil', Panel sayfasından değişir).

Metinler kodda Türkçe yazılır; öbür dillerinki arayuz/<kod>.json'da, anahtar Türkçe metnin kendisi (gettext gibi). Arayüz (panel.js
T()) ve Python (t()) aynı sözlükleri kullanır. Sözlükte olmayan metin önce İngilizceye, o da yoksa Türkçeye düşer: yarım bir çeviri de
kullanılabilir. Biçim: Python metinlerinde %s, arayüzde {0} {1} … Eksik ya da biçimi tutmayan çevirileri test/test_panel_lang.py yakalar.

Yeni dil: DILLER'e ekle, arayuz/<kod>.json'u yaz. Eksik metinler (İngilizceleriyle): python lang.py <kod>
"""
import json, os, sys, threading

# kod -> (kendi dilinde adı, tarih/sayı biçimi için yerel ayar)
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
DICTIONARY = os.path.join(UI_DIR, 'en.json')
_selected = None                  # panel bağlar: () -> DILLER'den bir kod | None
_dictionary = {}
_lock = threading.Lock()


def bind(fn):
    """Seçili dili veren işlevi bağla (panel: CFG.get('dil'))."""
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
    """Arayüzün dil seçimi: kod, ad, yerel ayar ve çevrilmiş metin oranı (İngilizce sözlüğe göre)."""
    full = len(mapping('en')) or 1
    return [{'code': k, 'ad': name, 'local': local,
             'coverage': 100 if k in ('tr', 'en') else min(100, round(100 * len(mapping(k)) / full))}
            for k, (name, local) in LANGUAGES.items()]


def t(text, *args):
    """Metnin seçili dildeki hâli (yoksa İngilizcesi, o da yoksa Türkçesi); args varsa % ile biçimlenir."""
    lang = current()
    if text and lang != 'tr':
        text = mapping(lang).get(text) or mapping('en').get(text, text)
    return text % args if args else text


if __name__ == '__main__':      # çevirmenler için: bir dilde eksik metinler, İngilizceleriyle (JSON)
    code = sys.argv[1] if len(sys.argv) > 1 else ''
    if code not in LANGUAGES or code == 'tr':
        sys.exit('kullanım: python lang.py <%s>' % '|'.join(k for k in LANGUAGES if k != 'tr'))
    sys.stdout.reconfigure(encoding='utf-8')
    have = mapping(code)
    json.dump({k: v for k, v in mapping('en').items() if k not in have}, sys.stdout, ensure_ascii=False, indent=0)
    print()
