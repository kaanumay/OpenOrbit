"""Normal kipin sohbeti: duruma ve kişiliğe göre kalıp cümleler, botun yazım üslubu ve oyuncunun mesajlarına basit yanıtlar.

Gelişmiş kipte LLM (llm.py) konuşur; LLM yoksa ya da yetişemezse buradaki kalıplar yedektir. Kalıplar kısa ve gerçek sohbet
kanallarındaki gibi: çoğu tek satır, küçük harf, kısaltmalı. uslupla() botun üslubunu uygular (kisilik.kisilik_uret: kucuk_harf,
noktalama, kisaltma, emoji, hata, buyuk_harf).
"""
import random, re

from .dil_verisi import DILLER, KODLAR

# durum -> {dil: satırlar}, dil -> kısaltmalar: bot/diller/<kod>.json (dil_verisi)
KALIPLAR = {}
for _kod, _d in DILLER.items():
    for _durum, _satirlar in _d.get('kaliplar', {}).items():
        KALIPLAR.setdefault(_durum, {})[_kod] = _satirlar
DIYALOG = {k: d.get('diyaloglar', []) for k, d in DILLER.items()}   # dil -> [konuşma]; konuşma = [tur]; tur = [alternatif satırlar]
KISALTMA = {k: [tuple(x) for x in d.get('kisaltma', ())] for k, d in DILLER.items()}
ASCII = {k: (str.maketrans(d['ascii']) if d.get('ascii') else None, d.get('ascii_oran', 0.0)) for k, d in DILLER.items()}
EMOJI = (':D', ':)', 'xD', '^^', ':P', ';)', 'xd')


def dil(bot):
    d = bot.k['kisilik'].get('dil')
    return d if d in DILLER else 'en'


def kalip(bot, durum, **f):
    """Durumun kalıplarından biri (botun dilinde), alanları doldurulmuş, üslubu uygulanmış -> metin ya da None."""
    k = KALIPLAR.get(durum)
    if not k:
        return None
    d = dil(bot)
    metin = bot.r.choice(k.get(d) or k['en'])
    try:
        metin = metin.format(**f)
    except (KeyError, IndexError):
        return None
    return uslupla(metin, bot.k['kisilik'].get('uslup') or {}, bot.r, d)


def diyalog(bot):
    """Botun dilinde rastgele bir kısa konuşma (turlar: ilk satır soru/laf, sonrakiler yanıt) ya da None."""
    k = DIYALOG.get(dil(bot)) or DIYALOG.get('en')
    return bot.r.choice(k) if k else None


def diyalog_satiri(bot, tur, **f):
    """Konuşmanın bir turundan (alternatifli satırlar) botun satırı, alanlar doldurulmuş, üslup uygulanmış -> metin ya da None."""
    try:
        metin = bot.r.choice(tur).format(**f)
    except (KeyError, IndexError):
        return None
    return uslupla(metin, bot.k['kisilik'].get('uslup') or {}, bot.r, dil(bot))


def uslupla(metin, u, r=random, d='tr'):
    """Botun yazım üslubu: kısaltmalar, Türkçe karakter düşürme, küçük/BÜYÜK harf, noktalama, emoji, yazım hatası."""
    if r.random() < u.get('kisaltma', 0.4):
        for a, b in KISALTMA.get(d, ()):
            metin = re.sub(r'\b%s\b' % re.escape(a), b, metin)
    tablo, oran = ASCII.get(d, (None, 0.0))
    if tablo and r.random() < oran:
        metin = metin.translate(tablo)             # çoğu oyuncu aksanlı harf yazmaz (Türkçe karakter, umlaut ...)
    if r.random() < u.get('kucuk_harf', 0.6):
        metin = metin.lower().replace('i̇', 'i')     # "İ".lower() noktalı i'ye (i + birleşen nokta) dönüyordu
    elif metin and r.random() < 0.5:
        metin = metin[0].upper() + metin[1:]
    if r.random() < u.get('buyuk_harf', 0.05) * 0.25:      # BAĞIRAN satır çok nadir (kullanıcı bildirimi 2026-10-29)
        metin = metin.upper()
    if r.random() < u.get('noktalama', 0.3) and metin[-1:].isalnum():
        metin += r.choice(('.', '!', '...'))
    if r.random() < u.get('emoji', 0.3) * 0.6 and not metin.endswith(EMOJI):
        metin += ' ' + r.choice(EMOJI)
    if r.random() < u.get('hata', 0.08) and len(metin) > 4:
        i = r.randrange(1, len(metin) - 2)
        if metin[i - 1].isalpha() and metin[i].isalpha() and metin[i + 1].isalpha() and metin[i + 2:i + 3].isalpha():
            # yalnız uzun sözcüğün içinde: "eic" -> "iec", "2-1" gibi kısa adlar bozulmaz
            metin = metin[:i] + metin[i + 1] + metin[i] + metin[i + 2:]
    return metin


# ------------------------------------------------------------------------------------------------------------ niyet
_SELAM = re.compile(r'\b(selam|slm|sa|merhaba|mrb|hi|hello|hey|yo|selamun|naber|nbr)\b', re.I)
# çıplak "gel/gelsene" yardım değil ("niye eic'e katılmıyorsun gelsene": takılma; önce botlar 2-1'e savaşa koşuyordu, oyuncu
# bildirimi 2026-10-30); haritayla "2-1e gelsene" takip (_GEL)
_YARDIM = re.compile(r'(yard[ıi]m|help|destek|imdat|kurtar|sald[ıi]r[ıi]yor|vuruyor|attack)', re.I)
_GEL = re.compile(r'\bgel(in|sene|senize|ir ?misin|ebilir ?misin)?\b', re.I)
_GRUP = re.compile(r'\b(grup|group|party|parti|team|tak[ıi]m|together|team up|duo|join me|birlikte|beraber)\b', re.I)
_KLAN = re.compile(r'\b(clan|clans|klan|klana|klanin|klanım|klanim|guild|recruit\w*)\b', re.I)
_ARKADAS = re.compile(r'\b(add me|add u|adding (you|u)|friend ?req\w*|be friends|friend me|ekle beni|arkada[sş] ?ol\w*|arkada[sş]l[ıi]k)\b',
                      re.I)
_TAKIP = re.compile(r"\b(come (to|here|over|with)|follow me|where (are|r) (you|u)|where u at|wya|meet (me|at|on)|nerdesin|neredesin|"
                    r"gel (buraya|yan[ıi]ma)|beni takip)\b", re.I)
_DUELLO = re.compile(r'\b(duel|duels|duello|1v1|1 v 1|1vs1|fight me|pvp me|come fight|who wants to fight|kapışalım|kapisalim|'
                     r'kapış|dövüşelim|dovusalim|vs at)\b', re.I)
_KAPI = re.compile(r"\b(lf\d?m?|looking for|need|needs|fill\w*|join|who|anyone|inv\w*|come|lazım|lazim|gelen|kim|var m[ıi])\b.*"
                   r"\b(hades|(?-i:LoW|LOW)|legends? of war|qz|quarantine|gates?|kap[ıi]\w*|zeta|kappa|lambda|kuiper|kronos|delta|epsilon)\b|"
                   r"\b(hades|(?-i:LoW|LOW)|qz|kap[ıi]\w*)\s+(i[çc]in|fill\w*|lf\w*)\b", re.I)
_GOREV = re.compile(r'\b(quest|quests|mission|missions|g[öo]rev\w*)\b', re.I)
# yardım isteğinde düşman oyuncu işareti: yoksa ve görevden söz ediliyorsa görev yardımıdır (gruplanma), PvP yardımı değil
_PVP = re.compile(r'\b(attack\w*|camp\w*|enem\w*|gank\w*|kill(ing|s)? me|hunting me|pvp|player|players|mmo|eic|vru|'
                  r'sald[ıi]r\w*|vuruyor|kurtar|d[üu][şs]man)\b', re.I)
_OZEL = re.compile(r'\b(pm me|dm me|msg me|message me|whisper me|private message|private msg|send me (a )?(pm|dm|msg|message)|'
                   r'pm at|[öo]zelden yaz|[öo]zel mesaj|fısılda|fisilda)\b', re.I)
_HAKARET = re.compile(r'\b(noob|nub|ez|ezik|aptal|salak|gerizekal[ıi]|beceriksiz|loser|trash|çöp|cop|bot)\b', re.I)
# Türkçe soru sözcükleri ekleriyle ("hangisi", "nerde", "kaçıncı") ve soru eki ("değer mi", "var mı"); önce "en iyi lazer hangisi"
# soru sayılmıyordu (sohbet denemesi 2026-10-30)
_SORU = re.compile(r'\?\s*$|\b(ne|neden|niye|nas[ıi]l\w*|nere\w*|nerde\w*|hangi\w*|kim(ler)?|ka[çc](ta|[ıi]nc[ıi]|ar)?|what|how|why|where|which|who|when)\b|'
                   r'\b(m[ıiuü])(s[ıiuü]n(.z)?|y[ıiuü]m|y[ıiuü]z|d[ıiuü]r)?\b', re.I)
_TESEKKUR = re.compile(r'\b(sa[gğ]ol|te[sş]ekk|t[sş]k|eyv|thanks|thx|ty)\b', re.I)
HARITA = re.compile(r'\b([1-5])\s*[-xX/]\s*([1-8]|bl)(?![\d])', re.I)     # Türkçe ek de olur: "2-1e", "2-3'te", "1-4de"


def _dil_ifadesi(ad):
    sozler = sorted({w for d in DILLER.values() for w in d.get('niyet', {}).get(ad, ())}, key=len, reverse=True)
    return re.compile(r'(?<!\w)(%s)(?!\w)' % '|'.join(re.escape(w) for w in sozler), re.I) if sozler else None


_DIL = {ad: _dil_ifadesi(ad) for ad in ('selam', 'yardim', 'grup', 'klan', 'arkadas', 'takip', 'duello', 'gorev', 'ozel', 'hakaret',
                                        'soru', 'tesekkur', 'pvp')}


def _var(rx, ad, metin):
    """Türkçe/İngilizce ifade ya da öteki dillerin sözcükleri (bot/diller/*.json niyet)."""
    return bool(rx.search(metin)) or bool(_DIL.get(ad) and _DIL[ad].search(metin))


def niyet(metin):
    """Oyuncu mesajının kabaca niyeti: 'yardim', 'grup', 'klan', 'arkadas', 'takip', 'hakaret', 'selam', 'tesekkur', 'soru' ya da
    None; ve geçen harita adı. İsteklerin (grup, klan, arkadaşlık, takip) kararını etkilesim.py verir."""
    m = HARITA.search(metin)
    harita = ('%s-%s' % (m.group(1), m.group(2).upper() if m.group(2).isalpha() else m.group(2))) if m else None
    if _var(_TAKIP, 'takip', metin) or (harita and _GEL.search(metin) and not _var(_YARDIM, 'yardim', metin)):
        return 'takip', harita                       # "come to 2-3", "2-1e gelsene": yardım değil
    if _var(_OZEL, 'ozel', metin):
        return 'ozel', harita                        # "bana özelden yaz": yanıt fısıltıyla
    if _var(_DUELLO, 'duello', metin):
        return 'duello', harita
    if _KAPI.search(metin):
        return 'kapi', harita                        # "need fillers for hades", "lf low", "kapı için adam lazım": kapı dolgusu
    if _var(_YARDIM, 'yardim', metin) and _var(_GOREV, 'gorev', metin) and not _var(_PVP, 'pvp', metin):
        return 'gorev', harita                       # "help me with a quest": grup (grubun öldürdüğü herkesin görevine sayılır)
    for ad, rx in (('yardim', _YARDIM), ('grup', _GRUP), ('klan', _KLAN), ('arkadas', _ARKADAS), ('hakaret', _HAKARET), ('tesekkur', _TESEKKUR), ('selam', _SELAM),
                   ('soru', _SORU)):
        if _var(rx, ad, metin):
            return ad, harita
    return None, harita


def yazma_suresi(metin, bot):
    """İnsanın okuyup yazma süresi (sn): tepki + harf başına."""
    return bot.k['kisilik']['tepki_sn'] * bot.r.uniform(2.0, 5.0) + len(metin) / bot.r.uniform(3.5, 7.0)
