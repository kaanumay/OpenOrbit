"""Botların dilleri: bot/languages/<kod>.json (her dil ayrı dosya; yeni dil için bir dosya eklemek yeter).

Bir dil dosyası:
  kod, ad (dilin kendi adı), agirlik ("karışık" kadroda o dilden bot payı)
  adlar      parcalar {entries: [...]} ve desenler [[ağırlık, desen]]: desende {entries}, {liste_k} (küçük harf), {a|b} (iki listeden),
             {liste?} (yarı yarıya boş), {leet:liste}. Adlar oyunun ad kuralına uyar (Latin harf, rakam, _ . -).
  kaliplar   durum -> satırlar (Normal kipin sohbeti; konusma.kalip). Alanlar: {name} {map} {level} {ship} {tag} {clan}
             {leader} {who} {item}.
  kisaltma   [[sözcük, kısaltma]] (botun üslubu), ascii {letter: yerine} ve ascii_oran (oyuncuların aksan düşürmesi)
  niyet      niyet -> sözcükler: oyuncunun o dildeki mesajının niyeti (konusma.niyet; tr/en'inkiler konusma'daki ifadelerde)
  tepki      kutlama, veda, donus, yoklama -> ifadeler ve oyun -> oyun sözcükleri: Gelişmiş kipte mesajın türü (llm.mesaj_turu;
             en'inkiler llm.TURLER)
  zararli    kendine zarar, ölüm dileği, ağır hakaret ifadeleri (düzenli ifade olabilir): model satırı bunlardan biriyse susar
             (llm.zararli; en'inkiler llm._ZARARLI). Aksansız yazılmış biçimleri de tutar (karşılaştırma aksanları düşürür).
"""
import json, os

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'languages')
ORDER = ('tr', 'en', 'de', 'es', 'fr', 'pl', 'pt', 'ru')        # panelin sırası (panelin dilleriyle aynı)


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
    """'Karışık' kadroda bir dil: dosyaların ağırlığına göre."""
    return r.choices(CODES, weights=[LANGUAGES[k].get('weight', 5) for k in CODES])[0]
