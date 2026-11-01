"""Klan emirleri (oyuncu isteği 2026-10-31): klanındaki botlara klan sohbetinden (ya da fısıltıyla) iş verirsin, gerçek bir klan gibi.

  odak    "everyone farm / do quests / go pvp / do gates / sell ore", "herkes görev yapsın"   -> o işe 2 saat ağırlık (beyin niyeti)
  git     "defend 4-4", "3 of you go to 2-4", "herkes 4-5'e"                               -> o haritaya gider, düşmanla dövüşür
  gel     "come help me", "regroup", "recall", "yanıma gelin"                              -> senin haritana gelir
  us      "defend our base / cbs / station"                                                -> klanın istasyonunun haritası (cbs.py)
  al      "get lf-3", "buy iris", "sg3n-b02 alın"                                          -> onu biriktirip alır (alisveris birikim)
  gemi    "use goliath", "fly vengeance", "goliath'a geçin"                               -> o gemiyi biriktirir, alınca uçar; zevki o olur
  yapi    "full shield", "full speed", "balanced"                                          -> jeneratörleri kalkana/hıza dağıtır (kalkan_payi)
  avla    "hunt Kaan", "x destroyed me, find them", "kill <ad>", "<ad>'i avlayın"            -> o kişiyi arar ve saldırır (30 dk)
  klan_odak "focus [TAG]", "prioritize <klan>", "focus clan X over Y"                      -> 2 saat o klanın üyeleri kin gibi öncelik
  dur     "stop", "dismissed", "serbest"                                                   -> emirler kalkar
"N of you" / "3 kişi" sayısı: en sadık N bot. Uyma olasılığı sadakat, sana ilişki ve liderlik (lider sensen) ile; yorgun bot
reddedebilir. Yanıt kısa kalıp (emir_tamam, emir_ret, geliyorum). İzin 'klan_emir'.
"""
import re

import harita as H
from . import beyin as B
from . import katalog as K
from . import konusma as KN

ODAK_SN = 7200
GIT_SN = 1800
US_SN = 3600
_SAYI_SOZ = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'bir': 1, 'iki': 2, 'üç': 3, 'uc': 3, 'dört': 4, 'dort': 4,
             'beş': 5, 'bes': 5}
_SAYI = re.compile(r'\b(\d{1,2}|one|two|three|four|five|bir|iki|üç|uc|dört|dort|beş|bes)\s+(of\s+)?(you|u|ya|guys|kişi\w*|kisi\w*|'
                   r'tane\w*|biriniz|kişiniz)\b', re.I)
_DUR = re.compile(r"\b(stop|dismissed|as you were|at ease|carry on|free now|cancel|nevermind|serbest|bırakın|birakin|dağılın|"
                  r"dagilin|iptal)\b", re.I)
_GEL = re.compile(r"\b(come (to me|here|back|help)|help me|regroup|recall|rally|back to me|to me|bana gel\w*|yan[ıi]ma gel\w*|"
                  r"gelin|toplan\w*|yard[ıi]m edin)\b", re.I)
_SAVUN = re.compile(r'\b(defend|protect|guard|hold|savun\w*|koru\w*|go to|go|head to|move to|git\w*|gidin|gelin)\b', re.I)
_US = re.compile(r'\b(base|cbs|station|battle ?station|[üu]s(s[üu]m[üu]z|[üu]m[üu]z|s[üu])?|istasyon\w*)\b', re.I)
_ODAK = (('kapi', re.compile(r'\b(gates?|gg|galaxy gates?|kap[ıi]\w*|alpha|beta|gamma|delta|epsilon|zeta|kappa|lambda|kuiper|'
                             r'hades)\b', re.I)),
         ('gorev', re.compile(r'\b(quests?|missions?|g[öo]rev\w*)\b', re.I)),
         ('pvp', re.compile(r'\b(pvp|hunt\w*|enem(y|ies)|kill (players|enemies)|d[üu][şs]man\w*|avla\w*)\b', re.I)),
         ('satis', re.compile(r'\b(sell\w*|ore|cargo|cevher\w*|kargo\w*)\b', re.I)),
         ('mod', re.compile(r'\b(events?|etkinli\w*)\b', re.I)),
         ('kasilma', re.compile(r'\b(farm\w*|grind\w*|npcs?|aliens?|uzayl[ıi]\w*|kas[ıi]n|kas[ıi]l\w*|kasma\w*)\b', re.I)))
_YAPI = (('kalkan', re.compile(r'\b(full|all|max)\s*(shields?|shd|kalkan)|\b(tam|full)\s*kalkan', re.I)),
         ('hiz', re.compile(r'\b(full|all|max)\s*(speed|spd|h[ıi]z)|\b(tam|full)\s*h[ıi]z', re.I)),
         ('denge', re.compile(r'\b(balanced|half|hybrid|dengeli|yar[ıi] yar[ıi]ya)\b', re.I)))
_GEMI_FIIL = re.compile(r'\b(use|fly|switch|ride|change to|kullan\w*|u[çc]un|ge[çc]in|binin)\b', re.I)
_AL = re.compile(r'\b(get|buy|equip|grab|save (up )?for|al[ıi]n|alsın|biriktir\w*|tak[ıi]n)\b', re.I)
YAPI_PAYI = {'kalkan': 0.95, 'hiz': 0.3, 'denge': 0.6}
AV_SN = GIT_SN
KLAN_ODAK_SN = ODAK_SN
_AD = r"([\w.\-]{2,20}?)"
_AV_EN = re.compile(r"\b(?:hunt|kill|get|find|destroy|attack|chase|murder|take out|go after)\s+(?:down\s+)?(?:the\s+)?(?:player\s+)?([\w.\-]{2,20})", re.I)
_AV_EN_KISI = re.compile(r"\b([\w.\-]{2,20})\s+(?:just\s+)?(?:destroyed|killed|shot|ganked|attacked|blew up|murdered|got)\s+me\b", re.I)
_AV_TR = re.compile(_AD + r"(?:['’][a-zçğıöşü]*)?\s+(?:avla\w*|bulun|bul|öldür\w*|oldur\w*|yakalay\w*|gebert\w*|vurun)\b", re.I)
_AV_TR_KISI = re.compile(_AD + r"\s+beni\s+(?:öldürdü|oldurdu|vurdu|patlattı|patlatti)\b", re.I)
_AV_KISI_FIIL = re.compile(r"\b(destroyed|killed|shot|ganked|attacked|blew up|murdered)\s+me\b|\bbeni\s+(öldürdü|oldurdu|vurdu|"
                           r"patlatt[ıi])", re.I)
_AV_FIIL = re.compile(r"\b(hunt|kill|get|find|destroy|chase|avla\w*|bulun|bul|öldür\w*|oldur\w*)\b", re.I)
_AV_YOK = {'enemies', 'enemy', 'players', 'player', 'aliens', 'alien', 'npcs', 'npc', 'them', 'him', 'her', 'it', 'the', 'all', 'everyone',
           'anyone', 'someone', 'somebody', 'us', 'you', 'me', 'my', 'our', 'some', 'any', 'those', 'these', 'that', 'this', 'down', 'pvp',
           'pve', 'more', 'on', 'in', 'at', 'to', 'out', 'ready', 'up', 'a', 'an', 'one', 'ones', 'now', 'there', 'here', 'lf-3', 'beni',
           'onu', 'onlari', 'hepsini', 'herkesi', 'dusmanlari', 'düşmanları', 'bir', 'bunu', 'şunu', 'sunu', 'bu', 'o', 'şu', 'su'}
_KLAN_ODAK = re.compile(r"\b(focus|prioriti[sz]e|target|go for|[öo]ncelik\w*|odaklan\w*|hedef al\w*)\b", re.I)
_KLAN_SONRA = re.compile(r"\b(over|instead of|rather than|before|not|then|yerine|ya[çc]|ama)\b", re.I)


def av_adi(s, bilinen=None, adlar=()):
    """Av emrindeki kişi adı ("hunt Kaan", "x destroyed me, find them", "Kaan'ı avlayın") ya da None. bilinen(ad): öyle biri var mı
    (olağan sohbet "herkes düşman avlasın" emir sanılmasın diye; verilmezse her ad kabul). adlar: çevrimiçi bilinen adlar; av fiili
    varken metinde geçen en uzun ad (oyuncu adlarında #, *, (), boşluk, sembol olur: "#Platonik", "亗TÜRK亗"; canlı 2026-11-01)."""
    adaylar = [m.group(1) for rx in (_AV_EN, _AV_TR) for m in rx.finditer(s)]
    fiil = _AV_FIIL.search(s) or _AV_KISI_FIIL.search(s)
    if _AV_FIIL.search(s):
        adaylar += [m.group(1) for rx in (_AV_EN_KISI, _AV_TR_KISI) for m in [rx.search(s)] if m]
    for a in adaylar:
        if a.lower() not in _AV_YOK and not KN.HARITA.fullmatch(a) and (bilinen is None or bilinen(a)):
            return a
    if fiil:
        kucuk = s.lower()
        for a in sorted((str(x) for x in adlar if len(str(x).strip()) >= 3), key=len, reverse=True):
            i = kucuk.find(a.lower())
            if i >= 0 and not (i and kucuk[i - 1].isalnum()) and not kucuk[i + len(a):i + len(a) + 1].isalnum():
                return a
    return None


def klan_bul(s, kendi=None):
    """Metinde geçen klan (etiket [TAG] ya da adı), "X over Y" ise X; kendi klanın hariç -> klan kaydı ya da None."""
    import klan as KL
    sonra = _KLAN_SONRA.search(s)
    s = s[:sonra.start()] if sonra and sonra.start() > 2 else s
    en = None
    with KL.LOCK:
        klanlar = [c for c in KL.KLANLAR.values() if c['id'] != kendi]
    for c in klanlar:
        for rx in (r'\[\s*%s\s*\]' % re.escape(c.get('etiket', '') or '\0'),
                   (r'(?<![\w])%s(?![\w])' % re.escape(c['etiket'])) if len(c.get('etiket', '')) >= 3 else None,
                   (r'(?<![\w])%s(?![\w])' % re.escape(c['ad'])) if len(c.get('ad', '')) >= 3 else None):
            m = re.search(rx, s, re.I) if rx else None
            if m and (en is None or m.start() < en[0]):
                en = (m.start(), c)
    return en[1] if en else None


def _esyalar():
    """Kısa ad -> loot: "lf-3", "sg3n-b02", "iris", "goliath" (tasarımsız gemiler)."""
    out = {}
    for grup in ('lazerler', 'kalkan_jeneratorleri', 'hiz_jeneratorleri', 'dronlar'):
        for loot in K.ESYA[grup]:
            out.setdefault(loot.rsplit('_', 1)[-1].lower(), loot)
    for loot in K.gemiler():
        out.setdefault(loot[len('ship_'):].lower(), loot)
    return out


_ESYA = None


def esya_bul(metin):
    global _ESYA
    if _ESYA is None:
        _ESYA = _esyalar()
        _ESYA['rx'] = re.compile(r'(?<![\w-])(%s)(?![\w-])' % '|'.join(re.escape(k) for k in sorted(_ESYA, key=len, reverse=True)), re.I)
    m = _ESYA['rx'].search(metin)
    return _ESYA[m.group(1).lower()] if m else None


def coz(metin, kendi_klan=None, bilinen=None, adlar=()):
    """Klan emri -> {'tur', 'harita'?, 'hedef'?, 'esya'?, 'yapi'?, 'sayi'?} ya da None (emir değil: olağan sohbet). kendi_klan: emri
    verenin klanı (klan odağında hariç); bilinen: av emrindeki adın varlığını sınayan işlev (av_adi)."""
    s = str(metin or '')
    if s.rstrip().endswith('?'):
        return None                                      # soru emir değil ("gates?" "kim kapı yapar?")
    m = _SAYI.search(s)
    sayi = (int(m.group(1)) if m.group(1).isdigit() else _SAYI_SOZ.get(m.group(1).lower())) if m else None
    e = {'sayi': sayi} if sayi else {}
    hm = KN.HARITA.search(s)
    harita = ('%s-%s' % (hm.group(1), hm.group(2).upper() if hm.group(2).isalpha() else hm.group(2))) if hm else None
    if _DUR.search(s):
        return dict(e, tur='dur')
    for ad, rx in _YAPI:
        if rx.search(s):
            return dict(e, tur='yapi', yapi=ad)
    esya = esya_bul(s) if _AL.search(s) or _GEMI_FIIL.search(s) else None     # "nice goliath" emir değil
    if esya:
        return dict(e, tur='gemi' if esya.startswith('ship_') else 'al', esya=esya)
    if _KLAN_ODAK.search(s):
        c = klan_bul(s, kendi_klan)
        if c is not None:
            return dict(e, tur='klan_odak', klan=c['id'])
    av = av_adi(s, bilinen, adlar)
    if av:
        return dict(e, tur='avla', hedef=av)
    if _SAVUN.search(s) and _US.search(s) and not harita:
        return dict(e, tur='us')
    if _GEL.search(s) and not harita:
        return dict(e, tur='gel')
    if harita and (_SAVUN.search(s) or _GEL.search(s) or re.search(r"\b(everyone|all|herkes|hepiniz)\b", s, re.I)):
        return dict(e, tur='git', harita=harita)
    if re.search(r'\b(focus|everyone|all|go|let\'?s|herkes|hepiniz|odaklan\w*|yap[ıi]n|gidin)\b', s, re.I):
        for ad, rx in _ODAK:
            if rx.search(s):
                return dict(e, tur='odak', hedef=ad)
    return None


def us_haritasi(profil):
    """Klanın kurulu (ya da kurulmakta olan) istasyonunun haritası ya da None."""
    import cbs as CB
    import klan as KL
    k = KL.klani(profil)
    for kaynak in (CB.ortak(), profil):
        if kaynak is None:
            continue
        for aid, a in ((kaynak.d.get('cbs') or {}).get('asteroitler') or {}).items():
            if (isinstance(a, dict) and a.get('sahip') != 'rakip' and a.get('durum') in ('kurulu', 'kurma')
                    and a.get('klan') in (None, (k or {}).get('id'))):
                ast = CB.AST.get(int(aid))
                if ast:
                    return int(ast['harita'])
    return None


def uyar_mi(b, ad, lider, now):
    p = 0.45 + 0.4 * b.o('sadakat') + 0.4 * b.hafiza.iliski(ad, now) + (0.15 if lider else 0) - 0.25 * b.ruh['yorgunluk']
    return b.r.random() < p


def uygula(y, b, e, ad, kisi, now):
    """Bir botta emir -> (kalıp, alanlar). Uymadıysa ('emir_ret', {})."""
    tur = e['tur']
    if tur == 'dur':
        b.k['niyet'] = None
        b.k.pop('emir', None)
        b.k.pop('av_emri', None)
        b.k.pop('klan_odagi', None)
        b.sonraki_karar = now
        return 'emir_tamam', {}
    if tur == 'yapi':
        b.k['yapi'] = e['yapi']
        b.ekip_degisti()
        return 'emir_tamam', {}
    if tur in ('al', 'gemi'):
        if b.k['ekip'].get('gemi') == e['esya']:
            return 'emir_tamam', {}
        b.k['birikim'] = e['esya']                      # alışveriş yalnız onu biriktirir (alisveris.aday)
        b._adaylar = None
        if tur == 'gemi':
            aile = e['esya'][len('ship_'):].split('-')[0]
            b.k['kisilik']['zevk'] = aile               # bundan sonra o gemi ailesini sever
        b.k['emir'] = {'tur': tur, 'esya': e['esya'], 'kim': ad, 't': now}
        return 'emir_tamam', {}
    if tur == 'odak':
        B.zorla(b, e['hedef'], plan={}, pay=1.3, sure=ODAK_SN, now=now)
        b.k['emir'] = {'tur': 'odak', 'hedef': e['hedef'], 'kim': ad, 't': now}
        return 'emir_tamam', {}
    if tur == 'avla':
        from .hedefler import pvp as PV
        t = PV.hedef_bul(y, e['hedef'])
        if t is None or t[0].lower() == ad.lower() or t[0].lower() == b.ad.lower():
            return 'emir_ret', {}
        if t[1] == b.firma:
            return 'duello_ayni', {}                    # kendi firmasına saldıramaz
        if t[3] is not None and t[3] == b.k.get('klan'):
            return 'emir_ret', {}                       # klan arkadaşı
        if not y.izin('pvp') or t[4] and not y.izin('oyuncuya_saldir') or b.seviye < (y.ayar('pvp_seviye', 6) or 1):
            return 'emir_ret', {}
        b.k['av_emri'] = {'ad': t[0].lower(), 'bitis': now + AV_SN, 'kim': ad}
        B.zorla(b, 'pvp', plan={}, pay=1.6, sure=AV_SN, now=now)
        return 'emir_av', {'ad': t[0]}
    if tur == 'klan_odak':
        import klan as KL
        c = KL.KLANLAR.get(e['klan'])
        if c is None or c['id'] == b.k.get('klan') or b.seviye < (y.ayar('pvp_seviye', 6) or 1) or not y.izin('pvp'):
            return 'emir_ret', {}
        b.k['klan_odagi'] = {'klan': c['id'], 'bitis': now + KLAN_ODAK_SN, 'kim': ad}
        B.zorla(b, 'pvp', plan={}, pay=1.0, sure=KLAN_ODAK_SN, now=now)
        return 'emir_klan_odak', {'klan': c.get('etiket') and '[%s]' % c['etiket'] or c['ad']}
    m = None
    if tur == 'git':
        from .araclar import _harita
        m = _harita(e['harita'])
    elif tur == 'gel':
        m = int(kisi.profil.d['konum'].get('mapId', 0)) if kisi is not None else None
    elif tur == 'us':
        m = us_haritasi(kisi.profil) if kisi is not None else None
        if m is None:
            return 'emir_us_yok', {}
    if not m or m not in K.HARITALAR or not K.girebilir(m, b.firma, b.seviye) or not K.yol(b.harita, m, b.firma, b.seviye):
        return 'gelemem', {}
    B.zorla(b, 'yardim', plan={'harita': int(m), 'ad': ad}, pay=1.6, sure=US_SN if tur == 'us' else GIT_SN, now=now)
    b.hafiza.olay(ad, 'yardim_ettim', now)
    return 'geliyorum', {'harita': H.name(m)}


def isle(y, kanal, msg, kim, dinleyen, now):
    """Sohbet motorundan: klan kanalındaki (ya da bota fısıltıdaki) mesaj klan emriyse uygular ve yanıtlatır -> işlendi mi."""
    if not y.izin('klan_emir') or kanal not in ('klan', 'fisilti'):
        return False
    import klan as KL
    import topluluk as TP
    from .hedefler import pvp as PV
    ad = kim.get('userId', '')
    kisi = TP.bul(ad=ad)
    kl = KL.klani(kisi.profil) if kisi is not None else None
    if kl is None or ad.lower() in y.ada:
        return False
    adlar = [b.ad for b in y.botlar if b.cevrimici] + [k.ad for k in TP.hepsi().values()]
    e = coz(msg, kl['id'], lambda a: PV.hedef_bul(y, a) is not None, adlar)
    if e is None:
        return False
    uyeler = [b for b in dinleyen if b.k.get('klan') == kl['id'] and b.cevrimici and b.olu_bitis <= now]
    if not uyeler:
        return False
    lider = kl['lider'] == ad.lower()
    sira = sorted(uyeler, key=lambda b: -(b.o('sadakat') + b.hafiza.iliski(ad, now)) * b.r.uniform(0.8, 1.2))
    kabul = 0
    for i, b in enumerate(sira):
        if e.get('sayi') and kabul >= e['sayi']:
            break
        if e['tur'] == 'dur' or uyar_mi(b, ad, lider, now):
            kalip, alan = uygula(y, b, e, ad, kisi, now)
            kabul += kalip not in ('gelemem', 'duello_ayni')
        else:
            kalip, alan = 'emir_ret', {}
        if i < 4 or kalip == 'geliyorum':                 # herkes yazmaz: ilk birkaçı ve yola çıkanlar
            y.konus(b, 'fisilti' if kanal == 'fisilti' else 'klan', KN.kalip(b, kalip, **alan), alici=ad if kanal == 'fisilti' else None,
                    now=now + b.r.uniform(0.5, 3) * (i + 1), oncelik=True)
    y.log('   botlar: klan emri %s: %s -> %d/%d bot' % (ad, e, kabul, len(uyeler)))
    return True
