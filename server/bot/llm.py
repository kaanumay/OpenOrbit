"""Gelişmiş kip: botların sohbeti ve stratejik kararları yerel dil modeliyle (llm_sunucu: llama-server + Qwen3 4B, düşünme kapalı).

Model oyunun döngüsünü hiç bekletmez: işler öncelikli kuyruğa girer, işçiler (llm_toplu kadar; sunucunun paralel yuvaları) sırayla
yürütür, sonuç gelince bota uygulanır. Kuyruk dolarsa ya da model kapalıysa yönetici Normal kipin kalıplarına döner (sohbet_motoru).

Dahili model yalnız İngilizce çalışır (Qwen3 4B Türkçede zayıf; kullanıcı 2026-10-29): istemler İngilizce, botlar İngilizce konuşur.
Kullanıcı başka bir sağlayıcı seçtiyse (llm_saglayici: OpenAI, Claude, Gemini, Ollama ...) istemler yine İngilizce ama her bot kendi
sohbet dilinde konuşur (COK_DILLI: persona "Chats in Turkish", süzgeç aksanlı harfi susturmaz, üslup botun dilinde).
Güçlü sağlayıcıda (GUCLU: dahili model değil) gerçekçilik katmanı açılır: geniş sohbet geçmişi, anı defteri (ani.py: kişilerle yaşanan
önemli olaylar, izlenimler), konuşma bitince modelin özeti, anılardan doğan sonuçlar (söz, intikam, teşekkür ... vakti gelince bot konuyu
açar ve eyleme geçer) ve botlar arası dedikodu (oyuncunun itibarı yayılır).
Botun iç durumu modele sayı olarak verilmez (kredi, güç): verilince model onları sohbete döküyordu ("kredi 438, 3-1'de
kasilma"); durum niteliksel anlatılır, sistem istemi gerçek oyuncu satırı örnekleri verir.

İşler (öncelik sırasıyla):
  fisilti     oyuncu bota fısıldadı: bot kişiliğiyle yanıtlar, isterse bir araç kullanır (grup daveti, yardıma gitme, takip ...)
  oda         oyuncu kanala yazdı: dinleyen birkaç bottan hangilerinin yanıt vereceği ve ne diyeceği TEK istekte (toplu)
  olay        botun önemli anı (seni öldürdü, öldü, gemi aldı): kısa tepki
  karar       birkaç botun durumu ve seçenekleri TEK istekte: model hedef seçer (beyin'e niyet olarak; araçlarla)
  bot_sohbet  aynı kanaldaki 2-3 bot kendi aralarında kısa bir konuşma yapar (dünya canlı dursun)
Bütün yanıtlar JSON şemasıyla istenir (llama-server dilbilgisiyle zorlar): araç adları şemada enum, bot adları da.
"""
import heapq, itertools, re, threading, time, traceback, unicodedata

import harita as H
from . import ad_uslup as AU
from . import ajan as AJ
from . import ani as ANI
from . import araclar as AR
from . import etkilesim as ET
from . import beyin as B
from . import katalog as K
from . import konusma as KN
from . import llm_saglayici as SG
from . import yonetici_uyari as YU
from . import llm_sunucu as LS

FISILTI, ODA, OLAY, KARAR, BOT_SOHBET = 0, 1, 2, 3, 4
POSTA = OLAY                      # posta acele değil: kuyruk dolarsa kalıpla yanıtlanır
KARAR_HEDEFLERI = ('kasilma', 'gorev', 'pvp', 'alisveris', 'dinlenme')
FIRMA = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
KANAL = {'global': 'global', 'firma': 'company', 'klan': 'clan', 'grup': 'group'}
OZELLIK_AD = {'saldirganlik': 'aggressive', 'rekabet': 'competitive', 'sosyallik': 'sociable', 'sabir': 'patient', 'risk': 'risk-taking',
              'sadakat': 'loyal', 'yardimseverlik': 'helpful', 'konuskanlik': 'chatty', 'tutumluluk': 'thrifty', 'hirs': 'ambitious'}
HEDEF_AD = {'kasilma': 'farming aliens', 'gorev': 'doing quests', 'pvp': 'hunting enemy players', 'alisveris': 'shopping',
            'dinlenme': 'taking a break at base', 'kesif': 'checking out a new map', 'grup': 'playing in a group',
            'yardim': 'going to help someone', 'basit': 'farming aliens'}
ARKETIP_AD = {'kasici': 'a grinder who mostly farms aliens', 'avci': 'a PvP hunter', 'sosyal': 'a social player who loves to chat',
              'tuccar': 'a trader who watches the auction', 'gorevci': 'a quest player', 'rahat': 'a casual player',
              'lider': 'a natural clan leader'}
SISTEM = ("You are a real human player of a DarkOrbit-like space MMO, typing in the in-game chat. Never say or hint that you are a "
          "bot or an AI and never break character. Write like a real gamer in a game chat: short (usually 2-10 words), casual, "
          "mostly lowercase, simple words, occasional slang only when it really fits. React to what was ACTUALLY said, like a person: "
          "answer the request or question, joke, agree, disagree or ask back. Give game tips ONLY when someone asks a game question, "
          "and then only true facts you were given (never invent maps, aliens or items). When you are told what you DECIDED (accept, "
          "decline, invite, come, apply ...), say exactly that decision in your own words and never promise anything else. Vary your "
          "wording: never copy the shape of earlier lines (if others wrote 'map + alien', you write something else). NEVER read out "
          "stats or internal state (no credit or uridium amounts, no power numbers, no 'currently farming' status reports). Never "
          "start a line with filler like 'np', 'lol no' or 'ty' unless it really is a reply to thanks or a joke. No ALL CAPS, no "
          "hashtags, emoticons rarely. "
          "Trash talk stays light and about the game (ships, skills, losing fights): never tell anyone to hurt or kill themselves, "
          "no slurs, nothing about real-life harm. You are a player, not an assistant: never offer help like customer service ('how can i assist you'), people just "
          "chat. The three companies MMO, EIC and VRU are rivals at war: every pilot is loyal to his own company, mocks the others "
          "and never agrees to fight his own company or to help another company against it (inside one company people are "
          "teammates). Every pilot sounds different. Only mention shared past events that appear in the memories or chat you were "
          "given; never invent things you did together. Always write in English. Output only the requested JSON.")
# başka sağlayıcıda: her pilot kendi dilinde (persona'daki "Chats in ...")
SISTEM_COK = SISTEM.replace('Always write in English.', "Each pilot writes in his own chat language, given as 'Chats in ...' in his "
                            "description (English if none is given), the casual way native gamers type in that language; game names "
                            "(maps like 2-3, ships, aliens, MMO, EIC, VRU) stay as they are.")
COK_DILLI = False                 # Beyin kurulunca: seçili sağlayıcı dahili model değilse
GUCLU = False                     # aynı koşul: hızlı, geniş bağlamlı model (anı defteri, sonuçlar, dedikodu, geniş geçmiş)
DIL_AD = {'tr': 'Turkish', 'en': 'English', 'de': 'German', 'es': 'Spanish', 'fr': 'French', 'pl': 'Polish', 'pt': 'Portuguese',
          'ru': 'Russian'}
_YABANCI = re.compile(r'[^\x00-\x7f -⯿\U0001f000-\U0001faff️]')   # İngilizce dışı harf: satır susar
_SIMGE = re.compile(r'[^\x20-\x7e]')            # emoji ve süs: atılır, satır kalır
_EMOJI = re.compile('[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d]')    # çok dilli kipte yalnız bunlar atılır
_ZARARLI = re.compile(r'\b(kys|kill (your|ur)self|killyourself|shoot (your|ur)self|hang (your|ur)self|end (your|ur) life|'
                      r'better off dead|wish (you|u) (were )?dead|hope (you|u) die|'
                      r'(go )?die\b|suicide|cancer|retard\w*|f[a4]g\w*|n[i1]gg\w*|whore|slut|rape\w*|nazi|hitler)', re.I)


def _katla(s):
    """Karşılaştırma için: küçük harf, aksanlar düşer (oyuncular çoğu zaman aksansız yazar: "olsene", "matate")."""
    s = str(s or '').lower().replace('ı', 'i').replace('ß', 'ss').replace('ł', 'l')
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _dil_ifadesi(sozler, ek=False):
    """ek: sözcüğün ardından ek gelebilir (Türkçe "gemiyi", "lazerler", "haritada": oyun sözcükleri; önce tanınmıyordu)."""
    sozler = sorted({_katla(w) for w in sozler if w}, key=len, reverse=True)
    sonu = '' if ek else r'(?!\w)'
    return re.compile(r'(?<!\w)(%s)' % '|'.join(w if '\\' in w else re.escape(w) for w in sozler) + sonu) if sozler else None


# öteki dillerin zararlı ifadeleri (kendine zarar, ölüm dileği, ağır hakaret: bot/diller/<kod>.json zararli); botlar o dillerde de
# konuşur (COK_DILLI), İngilizce süzgeç onları görmez
_ZARARLI_DIL = _dil_ifadesi([w for d in KN.DILLER.values() for w in d.get('zararli', ())])
# mesaj türleri öteki dillerde (bot/diller/<kod>.json tepki): kutlama, veda, dönüş, yoklama; oyun sözcükleri soruyu oyun sorusu yapar
_TEPKI_DIL = {t: _dil_ifadesi([w for d in KN.DILLER.values() for w in d.get('tepki', {}).get(t, ())], ek=t == 'oyun')
              for t in ('kutlama', 'veda', 'donus', 'yoklama', 'oyun')}


# İngilizceye özgü sözcükler (oyun argosu gg, lol, inv, np, ty sayılmaz); öteki dillerde de geçenler o dilde sayılmaz
_EN_SOZ = frozenset(('the', 'to', 'my', 'you', 'your', 'im', "i'm", 'and', 'with', 'heading', 'coming', 'way', 'save', 'what', 'how',
                     'why', 'where', 'just', 'got', 'going', 'gonna', 'wanna', 'this', 'that', 'are', 'is', 'its', "it's", 'was', 'will',
                     'can', 'for', 'of', 'be', 'have', 'has', 'do', 'dont', "don't", 'yeah', 'yes', 'guys', 'lets', "let's", 'here',
                     'there', 'some', 'any', 'when', 'who', 'right', 'now', 'all', 'on', 'at', 'in', 'it', 'i', 'we', 'me', 'a', 'so',
                     'am', 'u', 'ur', 'be', 'see', 'hey', 'sure', 'fine', 'bro', 'dude', 'man', 'not', 'no', 'too', 'only', 'also'))
_EN_ORTAK = {'de': {'in', 'was', 'so', 'am', 'man', 'hey', 'bro', 'no'}, 'es': {'a', 'me', 'no', 'bro', 'hey', 'man'},
             'pt': {'a', 'me', 'no', 'bro', 'hey', 'man', 'do'}, 'fr': {'a', 'me', 'on', 'hey', 'bro', 'man'},
             'pl': {'a', 'no', 'hey', 'bro', 'do'}, 'tr': {'hey', 'bro', 'man'}, 'ru': set()}


_TEK_SOZ = re.compile(r'^\s*(gg|lol|lel|xd+|haha+|hah|ah+|kek|ok|okey|tamam|tmm|k|wp|ez|rofl|lmao|:d|:\)|\^\^|aynen|sjsj|ahaha+)'
                      r'[\s!.?:)]*$', re.I)
_SEVIYE_DUYURU = re.compile(r'\b(lv|lvl|level|seviye|stufe|nivel|niveau|poziom|уровень)\s*\.?\s*\d+|\b\d+\s*\.?\s*(seviye|lvl|level)|'
                            r'seviye atlad|level ?up|leveled|lvl ?up', re.I)
_SELAM_BASI = re.compile(r'^\s*(selam(lar)?|slm|merhaba|mrb|hi|hello|hey|yo|hallo|hola|salut|cze[sś][cć]|ol[aá]|привет)'
                         r'(\s+(millet|all|everyone|guys|herkes|arkada[sş]lar|leute|chicos|les gars|ludzie|pessoal|народ))?[\s!.,:]*',
                         re.I)


def ingilizce_mi(metin, dil):
    """Satır İngilizce mi (botun dili İngilizce değilken): İngilizceye özgü sözcüklerin oranı. "on my way to 2-1, save me a target"
    evet; "eic tabii ki, 2-1e gelyrm" ve "gg ez" hayır."""
    if dil == 'en':
        return False
    soz = re.findall(r"[a-z']+", str(metin or '').lower())
    if len(soz) < 3 or re.search(r'[^\x00-\x7f]', str(metin)):
        return False                                     # kısa argo ya da kendi harfleri olan satır
    ort = _EN_ORTAK.get(dil, set())
    n = sum(1 for w in soz if w in _EN_SOZ and w not in ort)
    return n >= 3 and n >= 0.45 * len(soz)


def zararli(metin):
    return bool(_ZARARLI.search(str(metin or '')) or (_ZARARLI_DIL and _ZARARLI_DIL.search(_katla(metin))))


def dil_notu(b):
    """Çok dilli kipte botun sohbet dili (persona'nın sonuna)."""
    if not COK_DILLI:
        return ''
    d = KN.dil(b)
    return ' Chats in %s (always, even with people who write in another language).' % DIL_AD.get(d, KN.DILLER.get(d, {}).get('ad', d))


def _ruh(ruh):
    if ruh['ofke'] > 0.5:
        return 'angry'
    if ruh['moral'] < 0.35:
        return 'frustrated'
    if ruh['yorgunluk'] > 0.6:
        return 'tired'
    if ruh['moral'] > 0.8:
        return 'in a great mood'
    return 'relaxed'


def sohbet_personasi(b, y=None):
    """Sohbet için kısa tarif: kimlik, gemi, harita, ruh hâli, kişilerle ilişkisi ve son 10 dakikanın olayları (uzun tarif modeli
    her satırda işinden, parasından söz ettiriyordu)."""
    now = y.now if y is not None else time.time()
    iliski = ['%s (%s)' % (e['ad'], 'friend' if e['d'] > 0 else 'holds a grudge') for e in
              sorted(b.hafiza.d.values(), key=lambda e: -abs(e['d']))[:3] if abs(e['d']) >= 0.2]
    olaylar = [x for x in (olay_metni(o) for o in b.olaylar[-6:] if o['tur'] not in ('dedim', 'arac') and now - o['t'] < 600) if x]
    return '%s: %s, level %d, flies a %s, on %s (%s), %s.%s%s%s' % (
        b.ad, FIRMA[b.firma], b.seviye, b.k['ekip']['gemi'].replace('ship_', '').replace('-', ' '), H.name(b.harita),
        HEDEF_AD.get(b.hedef.ad, 'flying around') if b.hedef is not None else 'flying around', _ruh(b.ruh), _sosyal(b),
        (' Knows: %s.' % ', '.join(iliski)) if iliski else '', (' Just now he %s.' % '; '.join(olaylar[-2:])) if olaylar else '') + \
        dil_notu(b)


def _sosyal(b):
    """Grubu ve klanı (sorulunca doğru söylesin; "grubun var mı", "klanın ne")."""
    out = ''
    try:
        import grup as GR
        import klan as KL
        import topluluk as TP
        g = GR.grubu(b.uid)
        if g is not None:
            kisiler = TP.hepsi()
            out += ' In a group with %s.' % ', '.join(kisiler[u].ad for u in g.uyeler if u != b.uid and u in kisiler)
        k = KL.klani(b.profil) if b.profil is not None else None
        if k is not None:
            out += ' Clan [%s] %s%s.' % (k['etiket'], k['ad'], ' (he is the leader)' if k['lider'] == b.ad.lower() else '')
    except Exception:
        pass
    return out


def persona(b, y=None):
    """Botun modele tarifi (İngilizce, sayısız): kimlik, gemi, harita, işi, kişiliği, ruh hâli, ilişkileri, son olayları."""
    en = sorted(b.ozellik.items(), key=lambda x: -x[1])
    baskin = ', '.join(OZELLIK_AD[k] for k, v in en[:3])
    zayif = ', '.join(OZELLIK_AD[k] for k, v in en[-2:])
    hedef = HEDEF_AD.get(b.hedef.ad, 'idle') if b.hedef is not None else 'idle'
    para = 'rich' if b.k['kredi'] > 2000000 else 'broke' if b.k['kredi'] < 20000 else 'saving up'
    iliski = ['%s (%s)' % (e['ad'], 'friend' if e['d'] > 0 else 'holds a grudge') for e in
              sorted(b.hafiza.d.values(), key=lambda e: -abs(e['d']))[:4] if abs(e['d']) >= 0.15]
    olaylar = [x for x in (olay_metni(o) for o in b.olaylar[-6:] if o['tur'] not in ('dedim', 'arac')) if x]
    ev = '%d-1 to %d-4' % (b.firma, b.firma) if b.seviye < 10 else '%d-1 to %d-8 and 4-x' % (b.firma, b.firma)
    return ("%s: %s pilot, level %d (own company maps: %s; other companies' maps are enemy territory), flies a %s, on map %s, "
            '%s, %s. Plays like %s. Personality: %s; not very %s. Mood: %s.%s%s') % (
        b.ad, FIRMA[b.firma], b.seviye, ev, b.k['ekip']['gemi'].replace('ship_', '').replace('-', ' '), H.name(b.harita), hedef, para,
        ARKETIP_AD.get(b.arketip, 'a normal player'), baskin, zayif, _ruh(b.ruh),
        (' People: %s.' % ', '.join(iliski)) if iliski else '', (' Recently: %s.' % '; '.join(olaylar)) if olaylar else '') + dil_notu(b) + \
        _anilar_notu(b, y) + YU.notu(b, y.now if y is not None else None)


def _anilar_notu(b, y):
    """Güçlü kipte botun en değerli anıları (kin, söz, dostluk): kararları ve tepkileri etkilesin."""
    if not GUCLU:
        return ''
    now = y.now if y is not None else b.saat()
    la = ANI.onemli(b, now)
    return (' Strong memories: %s.' % '; '.join('%s (%s)' % (a['ozet'], ANI.ne_zaman(now - a['t'])) for a in la)) if la else ''


def olay_metni(o):
    t = o['tur']
    return {'olum': 'got killed by %s' % (o.get('katil') or 'aliens'), 'oyuncu_oldurdum': 'killed the player %s' % o.get('ad'),
            'oldurdum': 'killed the player %s' % o.get('kurban'), 'seviye': 'reached level %s' % o.get('seviye'),
            'yeni_gemi': 'bought a %s' % str(o.get('esya', '')).replace('ship_', ''), 'gorev_bitti': 'finished a quest',
            'klan_kurdu': 'founded the clan %s' % o.get('ad'), 'klana_girdi': 'joined the clan %s' % o.get('klan'),
            'gruba_girdi': 'grouped up with %s' % o.get('ad'), 'kacti': 'fled from map %s' % o.get('harita'),
            'patron_oldurdum': 'killed the boss alien %s' % o.get('ad'),
            'tanik': ('saw %s kill the boss %s right next to you' % (o.get('kim'), o.get('ad')) if o.get('alt') == 'patron'
                      else 'saw %s get destroyed right next to you' % o.get('ad'))}.get(t, '')


def _temiz_ad(ad):
    return re.sub(r'[^A-Za-z ]', '', str(ad)).strip()


def _harita_uzaylilari(m):
    adlar = []
    for v, n in sorted(K.harita_npcleri(m), key=lambda x: -x[1]):
        a = _temiz_ad(v['ad'])
        if a and a not in adlar:
            adlar.append(a)
    return adlar[:4]


def oyun_bilgisi(f):
    """Modelin oyun bilgisi, f firmasının oyuncusu için (soru soranın firması: yanıt ona göre doğru olsun). Veriden üretilir
    (Dünya Editörü'nün değişiklikleri dahil)."""
    f = f if f in FIRMA else 1
    haritalar = [(f - 1) * 4 + i for i in range(1, 5)] + [16 + (f - 1) * 4 + i for i in range(1, 5)] + [13, 14, 15, 16, 29]
    satir = ['%s: %s' % (H.name(m), ', '.join(a)) for m in haritalar for a in [[x for x in _harita_uzaylilari(m) if 'Boss' not in x]]
             if a]
    patron = ['%s (%s)' % (H.name(m), ', '.join(sorted({_temiz_ad(v['ad']) for v, n in K.harita_npcleri(m) if 'Boss' in v['ad']})[:3]))
              for m in haritalar if any('Boss' in v['ad'] for v, n in K.harita_npcleri(m))]
    satir.append('BOSS aliens are on ' + '; '.join(patron[:6]))
    return ('GAME FACTS for a %s player (use them, never invent): %s players start on %d-1, MMO starts on 1-1, EIC on 2-1, VRU on 3-1; '
            'every company has its own maps (MMO 1-x, EIC 2-x, VRU 3-x), other companies\' maps are enemy land. %s home maps: %d-1 '
            'to %d-4 for beginners, %d-5 to %d-8 later; 4-1 to 4-5 are shared PvP maps. Aliens: %s. Ships: phoenix (start) -> '
            'piranha, nostromo, bigboy (credits) -> leonov, vengeance, goliath (uridium). Lasers, weakest to strongest: LF-1, MP-1 (credits), LF-2, LF-3 '
            '(uridium). Quests come from the quest giver on your base map and give lots of EP; uridium comes from bonus boxes, quests '
            'and aliens. You level up by killing aliens and finishing quests.') % (
        FIRMA[f], FIRMA[f], f, FIRMA[f], f, f, f, f, '; '.join(satir))


SORU = re.compile(r'\?\s*$|^\s*(how|what|where|why|who|when|which|can|could|anyone|any|is|are|do|does|did|should|wanna|u|you)\b', re.I)
OYUN = re.compile(r'\b(map|alien|npc|streuner|lordakia|saimon|mordon|sibelon|boss|quest|ship|laser|lf|goliath|bigboy|phoenix|piranha|'
                  r'nostromo|vengeance|leonov|uri|uridium|credit|level|lvl|clan|group|ep|honor|drone|iris|flax|shield|gen|portal|'
                  r'gate|pvp|farm|start|begin|new|noob|mmo|eic|vru|[1-5]-[1-8x])(e?s)?\b', re.I)    # çoğullar da (bosses, maps)
TURLER = (
    ('kutlama', re.compile(r'\b(gz|gratz|grats|congrats|congratulations|well done|nice one|nice|wp|good job|gj)\b', re.I)),
    ('tesekkur', re.compile(r'\b(ty|thx|thanks|thank you|tyvm)\b', re.I)),
    ('veda', re.compile(r'\b(bye|cya|gn|good night|gtg|g2g|see ya|see you|later all)\b', re.I)),
    ('donus', re.compile(r'^\s*(back|im back|i\'m back|re|bk)\b', re.I)),
    ('ara', re.compile(r'\b(brb|afk|one sec|1 sec)\b', re.I)),
    ('yoklama', re.compile(r"\b(any(one|body)?|who'?s|who is)\b.*\b(online|on|here|around|alive|awake)\b", re.I)),
    ('meydan', re.compile(r'\b(duel|duels|1v1|1 v 1|1vs1|fight me|pvp me|come fight|who wants to fight)\b', re.I)),
    ('selam', re.compile(r'^\s*(hi|hello|hey|yo|sup|hiya|howdy|morning|evening)\b', re.I)),
    ('satasma', re.compile(r'\b(noob|noobs|nub|trash|ez|loser|bad|suck|sucks|idiot|stupid|cry|crying|scrub|bot|bots|weak)\b', re.I)),
)


def TP_firma(ad):
    import topluluk as TP
    k = TP.bul(ad=ad)
    return int(k.profil.d['pilot'].get('factionId', 0)) if k is not None else 0


NEREDE_SORU = re.compile(r'\b(where|which map|what map|map|maps|wo|nerede|hangi harita)\b', re.I)
HARITA_EKI = re.compile(r'\s*\b(for|on|in|at|from)\s+[1-5]-[1-8](\s*(,|/|and|or|&)\s*([1-5]-)?[1-8])*', re.I)


GEMILER = ('phoenix', 'liberator', 'piranha', 'nostromo', 'bigboy', 'leonov', 'vengeance', 'goliath', 'aegis', 'citadel', 'spearhead',
           'solace', 'diminisher', 'sentinel', 'spectrum', 'venom', 'cyborg', 'hammerclaw', 'berserker', 'tartarus', 'pusat')


def kisa_bilgi(f):
    """Kendiliğinden sohbetlerin (bot_sohbet, grup lafı, özel fısıltı) kısa ve doğru oyun bilgisi: model gemi ve harita
    uyduruyordu ("viking", "corsair"; EIC botu VRU'nun 3-5'ine "yeni uzaylı" için çağırıyordu)."""
    f = f if f in FIRMA else 1
    return ('Facts (never invent other ships, maps or aliens): a %s pilot plays on %d-1 to %d-8, MMO maps are 1-x, EIC 2-x, VRU 3-x '
            '(the other companies\' maps are enemy land), 4-1 to 4-5 are shared PvP maps. Ships: %s.') % (
        FIRMA[f], f, f, ', '.join(GEMILER))


def yabanci_harita(b, metin):
    """Satır başka firmanın haritasından söz ediyor mu (kendiliğinden sohbette: botlar düşman haritasına gezi önermez)."""
    return any(int(a) != b.firma for a, _ in re.findall(r'\b([1-3])-([1-8])\b', str(metin or '')))


def soru_mu(msg):
    return bool(SORU.search(msg))


def taraf(b, fac, ad):
    """Pilotun konuşana göre tarafı (küçük model firmaları karıştırıyordu: VRU botu EIC'nin "VRU ile savaşalım" çağrısına katıldı)."""
    if not fac:
        return ''
    if b.firma == fac:
        return 'He is %s like %s: a teammate, he sides with %s.' % (FIRMA[b.firma], ad, FIRMA[b.firma])
    return 'He is %s, %s is %s: on the rival side; he always sides with %s against %s.' % (
        FIRMA[b.firma], ad, FIRMA.get(fac, '?'), FIRMA[b.firma], FIRMA.get(fac, '?'))


FIRMA_NO = {'mmo': 1, 'mars': 1, 'eic': 2, 'earth': 2, 'vru': 3, 'venus': 3}
FIRMA_ADI = re.compile(r'\b(mmo|eic|vru|mars|earth|venus)\b', re.I)


def firma_notu(msg, fac, aday):
    """Mesajda firmalardan söz ediliyorsa (çağrı, övünme, sataşma) her tarafın nasıl tepki vereceğini açıkça yazar."""
    if not FIRMA_ADI.search(msg) or not fac:
        return ''
    dost = [b.ad for b in aday if b.firma == fac]
    dusman = [b.ad for b in aday if b.firma != fac]
    out = ' The message is about the companies.'
    adlar = {FIRMA[FIRMA_NO[m.lower()]] for m in FIRMA_ADI.findall(msg)} - {FIRMA.get(fac)}
    if adlar and mesaj_turu(msg) == 'satasma':
        out += ' It insults %s: %s pilots feel insulted and hit back at %s (never at their own company).' % (
            ' and '.join(sorted(adlar)), ' and '.join(sorted(adlar)), FIRMA.get(fac, '?'))
    if dost:
        out += ' His teammates (%s) may agree with him.' % ', '.join(dost)
    if dusman:
        out += (' Pilots of the other companies (%s) take it as coming from an enemy: they defend their own company, mock or '
                'threaten him back, and never agree to fight their own company.' % ', '.join(dusman))
    return out


def harita_notu(msg, fac):
    """Soruda başka firmanın haritası geçiyorsa modele açık not (küçük model "EIC'yim, 1-1'de nasıl başlarım"a 1-1 diyordu)."""
    out = []
    for a, b_ in re.findall(r'\b([1-3])\s*-\s*([1-8])\b', msg):
        sahip = int(a)
        if fac and sahip != fac:
            out.append(' Note: %s-%s belongs to %s, it is enemy land for a %s player; %s players start on %d-1.' % (
                a, b_, FIRMA[sahip], FIRMA.get(fac, '?'), FIRMA.get(fac, '?'), fac))
    return ''.join(out[:1])


_DOLGU = {'i', 'u', 'you', 'a', 'the', 'is', 'it', 'to', 'and', 'on', 'in', 'for', 'of', 'lol', 're', 'm', 's', 'im', 'just', 'but'}


def _benzer(a, b):
    """İki satır aynı şeyi mi söylüyor: eşit ya da anlamlı sözcüklerinin çoğu ortak (aynı ipucunu ikinci kez vermek)."""
    if a.lower() == b.lower():
        return True
    x = set(re.findall(r'[\w-]+', a.lower())) - _DOLGU
    y = set(re.findall(r'[\w-]+', b.lower())) - _DOLGU
    return len(x) >= 3 and len(y) >= 3 and len(x & y) / len(x | y) >= 0.55


def mesaj_turu(msg):
    """Oyuncunun mesajının türü: tepki rehberi (TEPKI) için. İstekler (grup, klan, arkadaşlık, gel) 'istek': kararı etkilesim.py
    verir ("who wants to group up?" oyun sorusu sayılıp harita ipucu alıyordu)."""
    n, _ = KN.niyet(msg)
    if n in ET.NIYETLER and n != 'yardim':
        return 'istek'
    for ad, rx in TURLER:
        if rx.search(msg):
            return ad
    k = _katla(msg)
    for ad in ('kutlama', 'veda', 'yoklama', 'donus'):             # öteki diller (bot/diller tepki)
        rx = _TEPKI_DIL[ad]
        if rx and rx.search(k) and (ad != 'donus' or (len(k.split()) <= 3 and not re.search(r'[1-5]\s*-\s*[1-8]', msg))):
            # ("2-3'e geldim" dönüş değil, varış)
            return ad
    if n == 'tesekkur':
        return 'tesekkur'
    if n == 'hakaret':
        return 'satasma'
    if soru_mu(msg) or n == 'soru':
        oyun = OYUN.search(msg) or (_TEPKI_DIL['oyun'] and _TEPKI_DIL['oyun'].search(k))
        return 'soru_oyun' if oyun else 'soru_kisisel'
    if n == 'selam':
        return 'selam'
    return 'ifade'


TEPKI = {
    'kutlama': 'It congratulates someone. Only the congratulated pilot answers, with a short natural thanks (maybe one tiny '
               'detail); nobody else talks.',
    'tesekkur': 'It thanks someone. The thanked pilot may answer briefly (np, anytime ...) or nobody.',
    'veda': 'Someone is leaving. 0-1 pilot says bye casually (like: gn, night man, cya, bye bye). Nothing else.',
    'donus': 'HE (the writer) is back after a short break, not you. One pilot welcomes him back (wb, wb man ...); if he asks what he missed, that pilot says it in a few words '
             '(like: not much, same old, nothing really) - never repeat old answers.',
    'ara': 'He goes away for a moment (brb / afk). Usually nobody answers; at most one says k or np.',
    'yoklama': 'He asks who is online. One or two pilots (of the company he names, if he names one) answer that they are here, '
               'in a few words (here, yo, yep whats up ...). No game tips.',
    'selam': 'A greeting. 0-2 pilots greet back casually (like: hey, yo whats up, hi man, sup), maybe ask how it is going. No '
             'game advice.',
    'meydan': 'He challenges people to a fight / duel. Pilots of OTHER companies may accept or taunt back (name a map to meet '
              'only if it is enemy land for both or a 4-x map); his teammates may joke or cheer. Short, in character, no tips.',
    'satasma': 'It is a taunt or insult. If someone is targeted he reacts in character: hot-headed pilots trash talk back, calm '
               'ones laugh it off or ignore; short, no real hate.',
    'soru_oyun': 'It is a question about the game. One pilot answers it correctly FOR THE ASKER (his company!) with concrete map or '
                 'alien names from the GAME FACTS, as a short tip (one or two names, never a long list); a second one may add a '
                 'small different tip. Answer exactly what was asked, no unrelated remarks. Mention a map only if he asks WHERE '
                 'something is (for "is X worth it" or "which is better" give an opinion, not maps).',
    'soru_kisisel': 'It is a personal or random question (not about the game). Answer like a normal person chatting: short, honest '
                    'or jokey, from your own life (work, school, food, sleep, music, weather ...). Do not mention the game, maps or '
                    'your level at all.',
    'istek': 'It is a request to the pilots (group, clan, friend, come over). Only the pilots told below answer, exactly with their '
             'decision.',
    'ifade': 'It is a statement. React naturally if it interests your pilot (agree, joke, disagree, ask back) or say nothing; at '
             'most 2 pilots.',
}


YEDEK = {'donus': ('wb', 'wb man', 'welcome back'), 'selam': ('hey', 'yo', 'hi'), 'kutlama': ('ty', 'thx', 'thanks man'),
         'yoklama': ('here', 'yo', 'yep'), 'soru_kisisel': ('lol idk', 'haha', 'not telling :p'),
         'satasma': ('lol ok', 'cry more', 'says the guy in a phoenix', 'k')}     # model yanıtı süzgece takılırsa


def ortak_gecmis(b, ad):
    """Botun o kişiyle geçmişi: hafızadaki olay sayıları ("dün birlikte gruplandık", "beni öldürmüştü"); güçlü kipte anılar ve
    izlenim de."""
    return _sayilar(b, ad) + (ANI.metin(b, ad, b.saat()) if GUCLU else '')


def _sayilar(b, ad):
    e = b.hafiza.d.get(str(ad).lower())
    if not e:
        return ''
    out = []
    for tur, metin in (('grup', 'grouped up %d times'), ('birlikte_avlandik', 'farmed together %d times'),
                       ('yardim_ettim', 'you helped him %d times'), ('yardim_etti', 'he helped you %d times'),
                       ('oldurdu_beni', 'he killed you %d times'), ('oldurdum', 'you killed him %d times'),
                       ('meydan', 'he challenged you to a duel'), ('arkadas', 'you are friends'),
                       ('hakaret', 'he insulted you %d times'), ('sohbet', 'chatted %d times')):
        k = e['n'].get(tur, 0)
        if k:
            out.append(metin % k if '%d' in metin else metin)
    return (' Your history with %s: %s.' % (e['ad'], ', '.join(out[:5]))) if out else ''


def konusma_gecmisi(y, kanal=None, adlar=(), n=6, sn=180, haric=None, yol=None):
    """Bağlam: aynı kanalın (ya da kişilerin fısıltılarının) son n satırı, son sn saniyeden; en yeni mesaj (haric) hariç. Güçlü
    kipte üç kat satır, dört kat süre (geniş bağlam). yol: odanın kendisi (firma, klan, grup kanalları firmaya/klana/gruba göre ayrı:
    önce MMO botu EIC'nin firma kanalındaki "geldim ne kaçırdım"a kendi kanalında yanıt verdi; sohbet denemesi 2026-10-30)."""
    if GUCLU:
        n, sn = n * 3, sn * 4
    adlar = {a.lower() for a in adlar}
    out = [x for x in y.gecmis if y.now - x[0] <= sn and (x[2] == kanal and (not yol or len(x) < 5 or x[4] in (None, yol)) if kanal else
                                                          (str(x[2]).startswith('fisilti') and (x[1].lower() in adlar or
                                                           any(a in str(x[2]).lower() for a in adlar))))]
    if haric and out and out[-1][3] == haric:
        out = out[:-1]
    return '\n'.join('%s: %s' % (x[1], x[3]) for x in out[-n:]) or '(nothing)'


def tarz(b):
    """Botun yazış tarzı (kişilikten): modele her pilotun başka konuşması için."""
    o = b.ozellik
    kaba = b.__dict__.get('kaba', 1)                     # paketin kaba sohbet ayarı (0 kapalı ... 3 çok sert)
    if b.__dict__.get('moderator'):
        t = 'a calm chat moderator of the server, polite, keeps the chat clean'
    elif kaba >= 2 and o['saldirganlik'] > 0.75 - 0.15 * kaba:
        t = 'toxic and provocative, trash talks other pilots and companies hard (still no slurs or real-life threats)'
    elif o['saldirganlik'] > 0.7 and o['yardimseverlik'] < 0.4:
        t = 'a bit toxic and sarcastic, loves trash talk' if kaba else 'competitive but always polite, never trash talks'
    elif o['konuskanlik'] < 0.3:
        t = 'quiet, answers with very few words'
    elif o['sosyallik'] > 0.7:
        t = 'friendly and chatty, jokes a lot'
    elif o['yardimseverlik'] > 0.7:
        t = 'helpful, likes to give tips'
    elif o['rekabet'] > 0.7:
        t = 'tryhard and competitive, a little cocky'
    else:
        t = 'laid-back and casual'
    return t


def hitap_edilen(y, kanal, msg, dinleyen):
    """Oyuncunun konuştuğu bot(lar): adı geçen; yoksa "you/u", kutlama, teşekkür ya da kısa tepkiyse bu kanalda az önce (90 sn)
    konuşan son bot. Genel sorular kimseye değildir."""
    adi = [b for b in dinleyen if AU.anildi_mi(b.ad, msg)]
    if adi:
        return adi
    son = [x for x in y.gecmis[-15:] if x[2] == kanal and y.now - x[0] < 90 and str(x[1]).lower() in y.ada
           and (len(x) < 5 or not dinleyen or x[1].lower() in {b.ad.lower() for b in dinleyen})]      # o kanalı duyanlardan
    tur = mesaj_turu(msg)
    if re.search(r'\b(guys|all|anyone|anybody|everyone|everybody|ppl|people|someone|somebody|yall|y\'all)\b', msg, re.I) \
            or FIRMA_ADI.search(msg) or tur == 'yoklama':
        return []                                            # herkese ya da bir firmaya ("MMO noobs" son konuşana değil)
    if son and (re.search(r'\b(you|u|your|ur|yours)\b', msg, re.I) or tur in ('kutlama', 'tesekkur')
                or (len(msg.split()) <= 3 and tur not in ('soru_oyun', 'selam', 'veda'))):
        b = y.ada.get(str(son[-1][1]).lower())
        return [b] if b is not None and b.cevrimici else []
    return []


KONULAR = ('asks if anyone is farming on his map', 'complains about a boss or a hard alien', 'asks which ship to buy next',
           'brags about a kill or a new level', 'asks if any clan is recruiting', 'warns about enemy players on a map',
           'jokes about losing his ship again', 'asks for a group to do quests', 'says he is saving uridium for something big',
           'complains that he is tired after work or school', 'says he is eating something while playing', 'asks what music people '
           'listen to while farming', 'says it is late and he should sleep but one more quest', 'asks how long people have been '
           'playing this game', 'teases another company (MMO, EIC, VRU)', 'asks who is the strongest player on the server',
           'laughs about a funny thing that happened on a map', 'asks if anyone wants to duel for fun', 'says the weekend is finally '
           'here', 'asks if lasers or shields matter more')


def konu_sec(b, y):
    """Botlar arası sohbetin açılış konusu: botun son olayından (varsa) ya da geniş bir konu listesinden (oyun içi ve dışı). Güçlü
    kipte bazen bir oyuncu hakkındaki anısı (dedikodu: dinleyenler duyar, ani.duydu)."""
    if GUCLU:
        a = ANI.dedikodu_sec(b, y.now, b.r)
        if a is not None and b.r.random() < 0.4:
            b._dedikodu = a
            return 'he tells the others about the player %s (%s): "%s"' % (a['kim'], ANI.ne_zaman(y.now - a['t']), a['ozet'])
    son = [o for o in b.olaylar[-5:] if o['tur'] in ('olum', 'seviye', 'yeni_gemi', 'oldurdum', 'gorev_bitti', 'klana_girdi')
           and y.now - o['t'] < 900]
    if son and b.r.random() < 0.4:
        return 'he mentions that he just %s' % olay_metni(son[-1])
    return 'he ' + b.r.choice(KONULAR)


class Beyin:
    def __init__(self, y, log=print):
        self.y, self.log = y, log
        self.yuva = int(y.ayar('llm_toplu', 4) or 4)
        global COK_DILLI, GUCLU
        self.sunucu = SG.istemci(self.yuva, log)              # dahili model ya da kullanıcının sağlayıcısı
        COK_DILLI = GUCLU = not isinstance(self.sunucu, LS.Sunucu)
        self.hazir = False
        self.kuyruk = []
        self.sayac = itertools.count()
        self.kosul = threading.Condition()
        self.calisiyor = True
        self.son_bot_sohbet = time.time() + 60
        self.son_karar = 0.0
        self.son_olay = 0.0
        self.istatistik = {'istek': 0, 'hata': 0, 'sure': 0.0, 'dusen': 0}
        self.susturulan = []             # süzgeçte atılan model satırları
        self.konusmalar = {}             # güçlü kip: (bot, oyuncu) -> {b, ad, bas, son, n}: bitince anıya özetlenir
        self.istek_anlari = []           # son bir saatteki bütün isteklerin anları (llm_saatlik: sohbet, anı, karar hepsi)
        self.kullanim_izi = []           # [(an, sağlayıcının token sayacının kopyası)] dakikada bir: son bir saatin kullanımı
        self.son_takip = 0.0

    # ------------------------------------------------------------ yaşam
    def baslat(self):
        threading.Thread(target=self._ac, name='llm-acilis', daemon=True).start()

    def _ac(self):
        for bekle in (30, 60, 120, 240, 480, None):        # geçici hata (429, 5xx, ağ) tek denemede bütün oturumu kapatmasın
            try:
                self.sunucu.baslat()
                break
            except Exception as e:
                kod = getattr(e, 'kod', None)
                kalici = isinstance(self.sunucu, LS.Sunucu) or kod is not None and 400 <= kod < 500 and kod not in (408, 429)   # yerel model ya da anahtar/model yanlış
                if kalici or bekle is None or not self.calisiyor:
                    self.log('   botlar: dil modeli açılamadı, Normal kip gibi sürüyor: %s' % e)
                    return
                self.log('   botlar: dil modeli açılamadı (%s), %d sn sonra yeniden denenecek' % (e, bekle))
                time.sleep(bekle)
        if not self.calisiyor:
            return
        self.hazir = True
        for i in range(self.yuva):
            threading.Thread(target=self._isci, name='llm-%d' % i, daemon=True).start()
        self.log('   botlar: dil modeli hazır (%s, %d yuva)' % (('port %d' % self.sunucu.port) if self.sunucu.port else self.sunucu.ad,
                                                               self.yuva))

    def durdur(self):
        self.calisiyor = False
        with self.kosul:
            self.kosul.notify_all()
        self.sunucu.durdur()

    # ------------------------------------------------------------ bütçe ve kullanım
    def sinirda(self):
        """Saatlik istek sınırına (llm_saatlik; 0 sınırsız) gelindi mi: gelindiyse yeni iş alınmaz (sohbet kalıplara, kararlar
        kurallı motora döner)."""
        if isinstance(self.sunucu, LS.Sunucu):
            return False                                   # dahili model ücretsiz: sınır yalnız uzak sağlayıcıda
        now = time.time()
        self.istek_anlari = [t for t in self.istek_anlari if now - t < 3600]
        sinir = self.y.ayar('llm_saatlik', 200) or 0
        return bool(sinir) and len(self.istek_anlari) >= sinir

    def _kullanim_tick(self, now):
        if self.kullanim_izi and now - self.kullanim_izi[-1][0] < 60:
            return
        self.kullanim_izi.append((now, dict(getattr(self.sunucu, 'kullanim', {}))))
        while len(self.kullanim_izi) > 1 and now - self.kullanim_izi[1][0] >= 3600:
            self.kullanim_izi.pop(0)

    def ozet(self):
        """Panelin kullanım satırı (durum.json'a yazılır): son bir saatin istekleri ve tokenleri, sınır, sağlayıcı."""
        simdi = dict(getattr(self.sunucu, 'kullanim', {}))
        once = self.kullanim_izi[0][1] if self.kullanim_izi else {}
        saat = {k: simdi.get(k, 0) - once.get(k, 0) for k in ('istek', 'girdi', 'onbellek', 'cikti')}
        sure = (time.time() - self.kullanim_izi[0][0]) if self.kullanim_izi else 0
        return {'saat': saat, 'sure_dk': round(sure / 60), 'toplam': simdi, 'sinir': self.y.ayar('llm_saatlik', 200) or 0,
                'sinirda': self.sinirda(), 'saglayici': getattr(self.sunucu, 'ad', ''), 'hazir': self.hazir}

    def ekle(self, oncelik, is_):
        if self.sinirda():
            self.istatistik['sinir'] = self.istatistik.get('sinir', 0) + 1
            return False
        with self.kosul:
            if len(self.kuyruk) >= self.yuva * 3 and oncelik >= OLAY:
                self.istatistik['dusen'] += 1
                return False
            heapq.heappush(self.kuyruk, (oncelik, next(self.sayac), is_))
            self.kosul.notify()
        return True

    def _isci(self):
        while self.calisiyor:
            with self.kosul:
                while self.calisiyor and not self.kuyruk:
                    self.kosul.wait(1.0)
                if not self.calisiyor:
                    return
                _, _, is_ = heapq.heappop(self.kuyruk)
            if time.time() - is_.get('t', time.time()) > 90:      # bayatladı (oyuncu çoktan unuttu)
                with self.y.lock:
                    for k in ('iptal', 'yedek'):              # ajanın uyanma sebebi geri; sohbet işi kalıp yanıtla (hiç yanıtsız kalmasın)
                        if is_.get(k):
                            try:
                                is_[k]()
                            except Exception:
                                self.log('   botlar: bayat iş geri alınamadı:\n' + traceback.format_exc(limit=3))
                            break
                continue
            try:
                is_['fn'](is_)
            except Exception:
                self.istatistik['hata'] += 1
                self.log('   botlar: dil modeli işi başarısız:\n' + traceback.format_exc(limit=3))
                yedek = is_.get('yedek')
                if yedek:
                    with self.y.lock:
                        yedek()

    def sor(self, kullanici, sema, en_cok=220, sicaklik=0.85, sistem=None):
        self.istatistik['istek'] += 1
        self.istek_anlari.append(time.time())
        sistem = (sistem or (SISTEM_COK if COK_DILLI else SISTEM)) + YU.sistem_notu()      # yönetici varken (yonetici_uyari.py)
        if COK_DILLI and sistem.startswith((SISTEM, SISTEM_COK)):                # sonda hatırlatma: model İngilizce yazan oyuncuya İngilizce yanıt veriyordu (Qwen3 denemesi)
            kullanici += "\n\nEvery line is written ONLY in that pilot's own chat language ('Chats in ...'), whatever language others use."
        try:
            r, sure = self.sunucu.sor(sistem, kullanici, sema=sema, en_cok=en_cok, sicaklik=sicaklik)
        except ValueError:                                   # yanıt sınırda kesildi ya da bozuk JSON: bir kez daha, daha sakin
            self.istatistik['yeniden'] = self.istatistik.get('yeniden', 0) + 1
            r, sure = self.sunucu.sor(sistem, kullanici, sema=sema, en_cok=int(en_cok * 1.5), sicaklik=0.6)
        self.istatistik['sure'] += sure
        return r

    # ------------------------------------------------------------ yöneticinin kancaları
    def sohbet(self, y, g, now):
        """Gelen mesaj modele mi (True) yoksa kalıplara mı."""
        if not self.hazir or not y.ayar('llm_sohbet', True) or not y.izin('sohbet'):
            return False
        if g[0] == 'fisilti':
            b, msg, kim = g[1], g[2], g[3]
            return self.ekle(FISILTI, {'t': now, 'fn': self._fisilti, 'bot': b, 'msg': msg, 'kim': kim,
                                       'yedek': lambda: y.kalip_fisilti(b, msg, kim, y.now)})
        yol, msg, kim = g[1], g[2], g[3]
        from .sohbet_motoru import kanal_adi
        kanal = kanal_adi(yol)
        if kanal is None or str(kim.get('userId', '')).lower() in y.ada:
            return True
        return self.ekle(ODA, {'t': now, 'fn': self._oda, 'kanal': kanal, 'msg': msg, 'kim': kim, 'yol': yol,
                               'yedek': lambda: y.kalip_oda(yol, msg, kim, y.now)})

    def olay(self, y, b, o, now):
        """Botun önemli anı: bazen modele (kısa tepki), değilse kalıplara (False)."""
        if not self.hazir or not y.ayar('llm_sohbet', True) or o['tur'] not in ('olum', 'oyuncu_oldurdum', 'yeni_gemi', 'seviye',
                                                                                  'tanik', 'patron_oldurdum'):
            return False
        insan = o.get('katil') or o.get('ad')
        if o['tur'] in ('olum', 'oyuncu_oldurdum') and (not insan or str(insan).lower() in y.ada):
            return False
        if o['tur'] == 'tanik':
            insan = None                                    # tanıklık: firma sohbetine, fısıltı değil
        sik = 0.35 + 0.5 * b.o('konuskanlik')
        if o['tur'] in ('seviye', 'yeni_gemi'):
            sik *= 0.3                                      # gerçek oyuncu her seviyeyi ilan etmez
        if b.r.random() > sik or now - self.son_olay < 20:
            return True                                     # bu sefer susar (olay tepkileri sohbeti doldurmasın)
        self.son_olay = now
        return self.ekle(OLAY, {'t': now, 'fn': self._olay, 'bot': b, 'olay': o})

    def posta(self, y, b, r, k):
        """Bota gelen postaya model yanıtı (toplum.posta_yanitla) -> kuyruğa girdi mi (girmediyse kalıp)."""
        if not y.ayar('llm_sohbet', True):
            return False
        return self.ekle(POSTA, {'t': y.now, 'fn': self._posta, 'bot': b, 'posta': r, 'karar': k})

    def ozel(self, y, b, ad, amac):
        """Botun oyuncuya kendiliğinden fısıltısı (sohbet_motoru.ozel_baslat) -> kuyruğa girdi mi."""
        if not y.ayar('llm_sohbet', True):
            return False
        return self.ekle(OLAY, {'t': y.now, 'fn': self._ozel, 'bot': b, 'ad': ad, 'amac': amac})

    def grup_lafi(self, y, b, ad):
        if not y.ayar('llm_sohbet', True):
            return False
        return self.ekle(OLAY, {'t': y.now, 'fn': self._grup_lafi, 'bot': b, 'ad': ad})

    def tick(self, now):
        """Yöneticinin tick'inden: botlar arası sohbet ve stratejik kararlar (seyrek, kuyruk boşken)."""
        self._kullanim_tick(now)
        if not self.hazir or len(self.kuyruk) > self.yuva:
            return
        y = self.y
        acik = [b for b in y.botlar if b.cevrimici and b.olu_bitis <= now]
        insan_yazdi = any(now - x[0] < 60 and str(x[1]).lower() not in y.ada for x in y.gecmis[-10:])
        if y.ayar('llm_sohbet', True) and y.izin('sohbet') and now >= self.son_bot_sohbet and len(acik) >= 2 and not insan_yazdi:
            self.son_bot_sohbet = now + 120 + 240 * (1 - min(1.0, len(acik) / 30))
            self.ekle(BOT_SOHBET, {'t': now, 'fn': self._bot_sohbet})
        if GUCLU:
            self._anilar_tick(y, now)
            if y.ayar('llm_ajan', True):
                self._ajan_tick(y, now, acik)              # araç döngüsü (ajan.py) tek adımlık kararın yerine
                return
        dk = y.ayar('llm_karar_dk', 10) or 0
        if dk and now - self.son_karar >= 20:
            # oyuncunun haritasındakiler (gözünün önünde) iki kat sık düşünür
            sira = [b for b in acik if now - getattr(b, '_llm_karar', 0) >= dk * 60 * (0.5 if b.govde is not None else 1.0)]
            if sira:
                self.son_karar = now
                sec = sorted(sira, key=lambda b: getattr(b, '_llm_karar', 0))[:3]
                for b in sec:
                    b._llm_karar = now
                self.ekle(KARAR, {'t': now, 'fn': self._karar, 'botlar': sec})

    # ------------------------------------------------------------ işler
    def _fisilti(self, is_):
        y, b, msg, kim = self.y, is_['bot'], is_['msg'], is_['kim']
        ad = kim.get('userId', '')
        fac = int(kim.get('factionId') or 0) or b.firma
        sema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 90}}, 'required': ['metin']}
        rel = b.hafiza.iliski(ad)
        # Rica (grup, yardım) kararını kişiliğe dayalı karar motoru verir, eylemi o uygular; model yalnız kararı botun ağzından
        # söyler. Küçük model "olur" deyip daveti unutuyordu (canlı 2026-10-29): söz ve eylem böyle hep tutarlı.
        niyet, harita = KN.niyet(msg)
        teklif = ET.teklif_cevabi(b, ad, msg, y.now)       # "gruplaşalım mı?" -> "sure": grup isteği
        if teklif:
            niyet = teklif
        tur = 'istek' if teklif else mesaj_turu(msg)
        karar = ''
        with y.lock:
            if niyet in ET.NIYETLER and niyet != 'yardim':
                kr = ET.karar(y, b, niyet, ad, kim, harita, msg, y.now)
                if kr is not None:
                    karar = kr['not']
                    is_['karar'] = kr
            elif niyet == 'yardim':
                gelen = y.yardim_cagrisi(ad, kim, harita, [b], 'firma', y.now, sessiz=True)
                karar = ('You decided to HELP: you are flying to him now. Say it in your own words.' if gelen else
                         'You decided NOT to help (too far, too weak or busy). Say it in your own words.')
        k = ('%sYou are %s. %s Your style: %s.\nYou feel %s about %s (a %s player).\n\nEarlier private messages (context only, '
             'maybe already answered):\n%s\n\nNEWEST private message from %s: "%s"\n\n%s %s Reply ONLY to this newest message with '
             'one short line (metin), like a real person. Never echo his words.') % (
            (oyun_bilgisi(fac) + '\n\n') if tur == 'soru_oyun' else '', b.ad, sohbet_personasi(b, y), tarz(b),
            'friendly' if rel > 0.2 else 'annoyed' if rel < -0.2 else 'neutral', ad + ortak_gecmis(b, ad),
            FIRMA.get(fac, '?'), konusma_gecmisi(y, adlar=[b.ad, ad], haric=msg, n=10, sn=1800), ad, msg,
            '' if karar else TEPKI.get(tur, ''), karar)
        r = self.sor(k, sema, sicaklik=0.6)
        with y.lock:
            b.hafiza.olay(ad, 'sohbet', y.now)
            metin = self._metin(b, r.get('metin'), yanki=msg)
            if metin:
                y.konus(b, 'fisilti', metin, alici=ad, now=y.now, oncelik=True)
            self._konustu(b, ad, y.now)
            if is_.get('karar'):
                ET.uygula(y, b, is_['karar'], gecikme=KN.yazma_suresi(metin or 'ok', b) + b.r.uniform(1, 3))

    def _oda(self, is_):
        y, kanal, msg, kim = self.y, is_['kanal'], is_['msg'], is_['kim']
        ad = kim.get('userId', '')
        fac = int(kim.get('factionId') or 0)
        niyet, harita = KN.niyet(msg)
        tur = mesaj_turu(msg)
        with y.lock:
            dinleyen = y.dinleyenler(kanal, kim)
            hitap = hitap_edilen(y, kanal, msg, dinleyen)
            if not hitap and _TEK_SOZ.match(msg) and (not dinleyen or dinleyen[0].r.random() < 0.85):
                return                                   # kimseye yazılmamış "gg", "lol", "xd": gerçek sohbette çoğu kez yanıtsız
                                                         # ("gg"ye "o senin iyi oynadığın içindi" denmesin; sohbet denemesi 2026-10-30)
            ek = sorted([b for b in dinleyen if b not in hitap], key=lambda b: -b.o('konuskanlik') * b.r.random())[:5 - len(hitap)]
            aday = (hitap + ek)[:5]
            # yardım çağrısı: kimin gideceğini karar motoru seçer (kişilik, güç, yol) ve gönderir; model gidenlere söyletir
            gidenler = y.yardim_cagrisi(ad, kim, harita, dinleyen, kanal, y.now, sessiz=True) if niyet == 'yardim' else []
            aday = (gidenler + [b for b in aday if b not in gidenler])[:5]
            kararlar = []                                # istek (grup, klan, arkadaş, gel): kim ne karar verdi
            if tur == 'istek':
                if hitap:
                    kararlar = [(b, ET.karar(y, b, niyet, ad, kim, harita, msg, y.now)) for b in hitap[:1]]
                elif niyet in ('grup', 'klan', 'gorev', 'duello', 'ozel', 'kapi'):
                    kararlar = [(b, b.__dict__.pop('_istek_karari', None) or ET.karar(y, b, niyet, ad, kim, harita, msg, y.now))
                                for b in y.acik_cagri(niyet, ad, kim, harita, msg, dinleyen, y.now)]
                elif niyet == 'takip' and kanal == 'grup':      # grup sohbetinde "follow me / come 2-4": grubun botları
                    kararlar = [(b, ET.karar(y, b, niyet, ad, kim, harita, msg, y.now)) for b in dinleyen[:3]]
                kararlar = [(b, kr) for b, kr in kararlar if kr is not None]
                if not kararlar and niyet == 'duello':
                    tur = 'meydan'                       # kimse kabul etmedi: laf atışması (TEPKI meydan)
                elif not kararlar:
                    return                               # kimse üstlenmedi: gerçek sohbetteki gibi sessizlik
                for b, kr in kararlar:
                    ET.uygula(y, b, kr, gecikme=b.r.uniform(6, 12))     # yanıtı yazdıktan sonra (model ~2 sn + yazma)
                aday = [b for b, _ in kararlar] or aday
            m = FIRMA_ADI.search(msg) if tur == 'yoklama' else None
            if m:                                        # "any eic online?": yalnız o firmanın pilotları "buradayım" der
                f = FIRMA_NO[m.group(1).lower()]
                aday = [b for b in dinleyen if b.firma == f][:3]
            elif fac and not hitap and FIRMA_ADI.search(msg):
                # başka firmadan söz ediliyor ("MMO noobs", "VRU is the best"): o firmanın pilotları ve bir takım arkadaşı tepki verir
                anilan = {FIRMA_NO[x.lower()] for x in FIRMA_ADI.findall(msg)} - {fac}
                ona = [b for b in aday if b.firma in anilan] + [b for b in dinleyen if b.firma in anilan and b not in aday]
                aday = (ona[:2] + [b for b in aday if b.firma == fac][:1]) or aday
            gecmis = konusma_gecmisi(y, kanal, haric=msg, yol=is_.get('yol'))
        if not aday:
            return
        # kim yanıtlayabilir: hitap edilen (yalnız o), yardıma gidenler, yoksa en çok iki pilot
        yanitlayan = gidenler or (aday if kararlar else None) or hitap or aday
        en_cok = min(3, len(gidenler)) if gidenler else len(kararlar) if kararlar else len(hitap) if hitap else \
            1 if tur in ('veda', 'tesekkur', 'donus', 'ara') else 2
        en_az = 1 if (gidenler or kararlar or hitap or tur in ('soru_oyun', 'soru_kisisel', 'donus', 'selam', 'yoklama')) else 0
        sema = {'type': 'object', 'properties': {'yanitlar': {'type': 'array', 'minItems': en_az, 'maxItems': en_cok, 'items': {
            'type': 'object', 'properties': {'bot': {'type': 'string', 'enum': [b.ad for b in yanitlayan]},
                                             'metin': {'type': 'string', 'maxLength': 90}},
            'required': ['bot', 'metin']}}}, 'required': ['yanitlar']}
        if gidenler:
            m = H.name(gidenler[0].k['niyet']['plan']['harita']) if (gidenler[0].k.get('niyet') or {}).get('plan') else 'there'
            kural = ('These pilots decided to fly to %s to fight the enemy players (not aliens) attacking %s; each says in his own '
                     'words and his own chat language that he is coming: %s.') % (m, ad, ', '.join(b.ad for b in gidenler))
        elif niyet == 'yardim':
            kural = 'Nobody can go help this time; at most one pilot answers (too far or busy).'
        elif kararlar:
            kural = 'It is a request. Each of these pilots answers it with his decision, in his own words:\n%s' % '\n'.join(
                '- %s: %s' % (b.ad, kr['not']) for b, kr in kararlar)
        else:
            kural = TEPKI[tur] + harita_notu(msg, fac)
            if hitap:
                kural += ' %s is talking to %s, so %s answers him directly.' % (ad, hitap[0].ad, hitap[0].ad)
        k = ('%sPilots in the %s chat:%s\n%s\n\nEarlier chat (context only, it may already be answered - do not go back to old '
             'topics):\n%s\n\nNEWEST message, from %s (a %s player): "%s"\n\n%s Reply ONLY to this newest message. Each answer is one '
             'short line in that pilot\'s own style. Never repeat or echo what someone already said.') % (
            (oyun_bilgisi(fac or aday[0].firma) + '\n\n') if tur == 'soru_oyun' else '', KANAL.get(kanal, kanal),
            ' (they are all in the same group as %s: his teammates right now)' % ad if kanal == 'grup' else '',
            '\n'.join('- %s Style: %s. %s%s' % (sohbet_personasi(b, y), tarz(b), taraf(b, fac, ad),
                                              ANI.metin(b, ad, y.now) if GUCLU else '') for b in aday), gecmis, ad,
            FIRMA.get(fac, '?'), msg, kural + firma_notu(msg, fac, aday))
        r = self.sor(k, sema, en_cok=320, sicaklik=0.65 if tur.startswith('soru') or hitap else 0.85)
        with y.lock:
            sira = 0
            for x in (r.get('yanitlar') or [])[:3]:
                b = y.ada.get(str(x.get('bot', '')).lower())
                metin = x.get('metin')
                if tur == 'soru_oyun' and not NEREDE_SORU.search(msg):
                    metin = HARITA_EKI.sub('', str(metin or ''))   # "is goliath worth it" -> "...worth it" (küçük model harita ekliyordu)
                metin = self._metin(b, metin, yanki=msg) if b is not None else ''
                if b is None or not b.cevrimici or not metin:
                    continue
                b.hafiza.olay(ad, 'ovgu' if tur == 'kutlama' else 'hakaret' if tur == 'satasma' and hitap else 'sohbet', y.now)
                fis = any(kb is b and kr.get('fisilti') for kb, kr in kararlar)
                y.konus(b, 'fisilti' if fis else kanal, metin, alici=ad if fis else None, now=y.now + sira * b.r.uniform(2, 6),
                        oncelik=True)
                if hitap or kararlar or gidenler:
                    self._konustu(b, ad, y.now)              # doğrudan konuşma (genel yanıt değil): sonunda anıya özetlenir
                sira += 1
            yedek = YEDEK.get(tur)
            # yanıt gerekiyordu ama hepsi süzgece takıldı: kısa doğal karşılık (yedekler İngilizce)
            if not sira and en_az and yedek and not gidenler and (not COK_DILLI or KN.dil(yanitlayan[0]) == 'en'):
                b = yanitlayan[0]
                y.konus(b, kanal, b.r.choice(yedek), now=y.now, oncelik=True)

    def _olay(self, is_):
        y, b, o = self.y, is_['bot'], is_['olay']
        sema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 90},
                                                 'kanal': {'type': 'string', 'enum': ['fisilti', 'firma', 'global', 'hicbiri']}},
                'required': ['metin', 'kanal']}
        kim = o.get('katil') or o.get('ad') or ''
        k = ('You are %s.\n%s\nThis just happened: you %s.\nDo you type something about it? kanal: fisilti = private message to %s, '
             'firma = company chat, global = global chat, hicbiri = say nothing (often the most realistic). metin: one short line.') % (
            b.ad, persona(b, y), olay_metni(o), kim or '-')
        r = self.sor(k, sema, en_cok=80)
        kanal = r.get('kanal')
        metin = self._metin(b, r.get('metin'))
        if kanal == 'hicbiri' or not metin or (kanal == 'fisilti' and not kim):
            return
        with y.lock:
            y.konus(b, kanal, metin, alici=kim if kanal == 'fisilti' else None, now=y.now)

    def _posta(self, is_):
        y, b, r, kr = self.y, is_['bot'], is_['posta'], is_.get('karar')
        ad = r['gonderen']
        sema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 240}}, 'required': ['metin']}
        icerik = '%s %s' % (r.get('konu', ''), r.get('metin', ''))
        oyun = mesaj_turu(icerik) == 'soru_oyun' or (soru_mu(icerik) and OYUN.search(icerik))
        fac = int(TP_firma(ad) or b.firma)
        # (boolean "yanıtla" alanı kaldırıldı: model reddi "yanıtlama" sanıp iyi metni de atıyordu)
        k = ('%sYou are %s. %s Your style: %s.\nYou feel %s about %s.\n\n%s sent you an in-game MAIL.\nSubject: "%s"\nText: "%s"\n\n%s'
             'Write your answer mail (metin): 1-3 short casual sentences (at least 6 words; give a reason if you say no), like a '
             'gamer writing a quick mail, no greeting formulas like "Dear", no signature. Real players answer personal mails; only '
             'for spam or nonsense leave metin empty.') % (
            (oyun_bilgisi(fac) + '\n\n') if oyun else '', b.ad, sohbet_personasi(b, y), tarz(b),
            'friendly' if b.hafiza.iliski(ad) > 0.2 else 'neutral', ad + ortak_gecmis(b, ad), ad, str(r.get('konu', ''))[:60],
            str(r.get('metin', ''))[:600],
            (kr['not'] + ' ') if kr else '')
        x = self.sor(k, sema, en_cok=160, sicaklik=0.7)
        metin = ' '.join(str(x.get('metin') or '').split())
        if len(metin.split()) < 4 or (not COK_DILLI and _YABANCI.search(metin)) or zararli(metin):
            if not kr:
                return
            from . import toplum
            metin = toplum.posta_kalibi(b, kr)                # karar varsa sessiz kalmaz
            if not metin:
                return
        with y.lock:
            AR.cagir(y, b, 'posta_gonder', {'ad': ad, 'konu': 'Re: ' + str(r.get('konu', ''))[:46], 'metin': metin})

    def _ozel(self, is_):
        y, b, ad, amac = self.y, is_['bot'], is_['ad'], is_['amac']
        ne = {'ozel_selam': 'he just came online: greet him (a short wb / hey)',
              'ozel_grup': 'you want to group up with him: ask him (you are on %s doing %s)' % (
                  H.name(b.harita), HEDEF_AD.get(b.hedef.ad, 'farming aliens') if b.hedef is not None else 'farming aliens'),
              'ozel_sohbet': 'you just feel like chatting: ask him something casual (how it goes, his gear, his plans)'}[amac]
        sema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 80}}, 'required': ['metin']}
        k = ('You are %s. %s Your style: %s.\nYou are friends with %s.%s\n\nEarlier private messages:\n%s\n\nYou start a private '
             'chat with him: %s. One short line (metin), like a real friend in a game, not a status report. %s') % (
            b.ad, sohbet_personasi(b, y), tarz(b), ad, ortak_gecmis(b, ad), konusma_gecmisi(y, adlar=[b.ad, ad], n=6, sn=3600), ne,
            kisa_bilgi(b.firma))
        r = self.sor(k, sema, en_cok=60, sicaklik=0.85)
        with y.lock:
            metin = r.get('metin') if not yabanci_harita(b, r.get('metin')) else ''
            metin = self._metin(b, metin) or KN.kalip(b, amac, ad=ad, harita=H.name(b.harita))
            y.konus(b, 'fisilti', metin, alici=ad, now=y.now)

    def _grup_lafi(self, is_):
        y, b, ad = self.y, is_['bot'], is_['ad']
        sema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 80}}, 'required': ['metin']}
        k = ('You are %s. %s Your style: %s.\nYou are in a group with %s, playing together right now.%s\n\nRecent group chat:\n%s\n\n'
             'Write one short line in the group chat to him, like a real teammate: where to go next, a quick comment on the '
             'farming or a boss, a joke, a short question. Not a status report, nothing already said. %s') % (
            b.ad, sohbet_personasi(b, y), tarz(b), ad, ortak_gecmis(b, ad), konusma_gecmisi(y, 'grup', n=6, sn=900), kisa_bilgi(b.firma))
        r = self.sor(k, sema, en_cok=60, sicaklik=0.9)
        with y.lock:
            metin = self._metin(b, r.get('metin')) if not yabanci_harita(b, r.get('metin')) else ''
            if metin:
                y.konus(b, 'grup', metin, now=y.now)

    def _bot_sohbet(self, is_):
        from .sohbet_motoru import kanal_yolu
        y = self.y
        with y.lock:
            acik = [b for b in y.botlar if b.cevrimici and b.olu_bitis <= y.now]
            if len(acik) < 2:
                return
            r0 = acik[0].r
            kanal = 'global' if r0.random() < 0.3 and len({b.firma for b in acik}) > 1 else 'firma'
            if kanal == 'global':                         # global: farklı firmalardan, firmalar arası atışma olağan
                firmalar = r0.sample(sorted({b.firma for b in acik}), 2)
                grup = [max((b for b in acik if b.firma == f), key=lambda b: b.o('konuskanlik') * b.r.random()) for f in firmalar]
                grup += sorted([b for b in acik if b not in grup], key=lambda b: -b.o('konuskanlik') * b.r.random())[:1]
            else:
                fac = r0.choice([1, 2, 3])
                grup = [b for b in acik if b.firma == fac] or acik
                grup = sorted(grup, key=lambda b: -b.o('konuskanlik') * b.r.random())[:3]
            if len(grup) < 2:
                return
            grup[0].__dict__.pop('_dedikodu', None)
            konu = konu_sec(grup[0], y)
        sema = {'type': 'object', 'properties': {'satirlar': {'type': 'array', 'minItems': 2, 'maxItems': 5, 'items': {
            'type': 'object', 'properties': {'bot': {'type': 'string', 'enum': [b.ad for b in grup]}, 'metin': {'type': 'string', 'maxLength': 90}},
            'required': ['bot', 'metin']}}}, 'required': ['satirlar']}
        k = ('%s\n\nThese pilots are in the %s chat%s:\n%s\n\nLast lines in the chat (do NOT continue or repeat these, '
             'they are old):\n%s\n\nWrite a NEW short natural exchange between them (2-5 lines, a few words each). %s starts it: %s. '
             'The others react to what was actually said (answer, joke, disagree, ask back) - a real back-and-forth in their own '
             'styles, not separate statements. Never status reports.') % (
            kisa_bilgi(grup[0].firma) if kanal == 'firma' else kisa_bilgi(0).split(': a ')[0] + ': MMO maps are 1-x, EIC 2-x, VRU '
                                                                   '3-x, 4-x are shared PvP maps. Ships: ' + ', '.join(GEMILER) + '.',
            'same company' if kanal == 'firma' else 'global',
            '' if kanal == 'firma' else ' (players of rival companies: light banter between companies is normal, everyone stays '
                                        'loyal to his own)',
            '\n'.join('- %s Style: %s.' % (sohbet_personasi(b, y), tarz(b)) for b in grup),
            konusma_gecmisi(y, kanal, n=4, sn=120, yol=kanal_yolu(grup[0], kanal)), grup[0].ad, konu)
        r = self.sor(k, sema, en_cok=320, sicaklik=0.95)
        with y.lock:
            t = y.now
            for x in r.get('satirlar') or []:
                b = y.ada.get(str(x.get('bot', '')).lower())
                metin = self._metin(b, x.get('metin')) if b is not None else ''
                if b is None or not b.cevrimici or not metin or (kanal == 'firma' and yabanci_harita(b, metin)):
                    continue
                t += b.r.uniform(4, 14)
                y.konus(b, kanal, metin, now=t)
            a = grup[0].__dict__.pop('_dedikodu', None)
            if a is not None and t > y.now:                  # anlattı: dinleyenler duydu (oyuncunun itibarı yayılır)
                for d in grup[1:]:
                    ANI.duydu(d, grup[0], a, y.now)

    def _karar(self, is_):
        """Stratejik karar (sohbet yazmaz: model buradaki "söz"leri durum raporuna çeviriyordu; sohbet bot_sohbet'te)."""
        y = self.y
        botlar = [b for b in is_['botlar'] if b.cevrimici]
        if not botlar:
            return
        satirlar = []
        with y.lock:
            for b in botlar:
                bg = B.Baglam(b, y, y.now)
                puan = sorted(((h.ad, round(h.puan(b, bg), 2)) for h in B.HEDEFLER.values()
                               if h.ad in KARAR_HEDEFLERI and B.izinli(h, y) and h.uygun(b, bg)), key=lambda x: -x[1])
                haritalar = ', '.join(H.name(m) for f, m, _ in bg.harita[:4])
                satirlar.append('- %s\n  Options with gut-feeling scores: %s\n  Good farming maps: %s' % (
                    persona(b, y), ', '.join('%s %.2f' % x for x in puan), haritalar or '-'))
        sema = {'type': 'object', 'properties': {'kararlar': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'bot': {'type': 'string', 'enum': [b.ad for b in botlar]}, 'hedef': {'type': 'string', 'enum': list(KARAR_HEDEFLERI)},
            'harita': {'type': 'string', 'maxLength': 8}}, 'required': ['bot', 'hedef', 'harita']}}}, 'required': ['kararlar']}
        k = ('For each pilot choose what he does in the next 10-20 minutes (kasilma = farm aliens, gorev = quests, pvp = hunt enemy '
             'players, alisveris = buy upgrades, dinlenme = take a break at base), realistically for his personality, mood and recent '
             'events (the scores are gut feelings, not orders). For kasilma put one of his listed maps in harita, otherwise leave it '
             'empty.\n\n%s') % '\n'.join(satirlar)
        r = self.sor(k, sema, en_cok=240, sicaklik=0.7)
        with y.lock:
            for x in r.get('kararlar') or []:
                b = y.ada.get(str(x.get('bot', '')).lower())
                if b is None or not b.cevrimici:
                    continue
                arac = {'kasilma': 'npc_avla', 'gorev': 'gorev_yap', 'pvp': 'pvp_avla', 'alisveris': 'alisveris_yap',
                        'dinlenme': 'dinlen'}.get(x.get('hedef'))
                if arac:
                    AR.cagir(y, b, arac, {'harita': x.get('harita')} if arac == 'npc_avla' and x.get('harita') else {})

    # ------------------------------------------------------------ ajan (güçlü kip; ajan.py)
    def _yakinlar(self, y, now):
        """Oyuncunun dünyasına yakın botlar (ayrıntı düzeyi): haritasında ya da oyuncuyla aynı haritada, oyuncuyla ilişkisi, anısı
        ya da süren konuşması olanlar. Bunlar tam sıklıkta ve olaylarla düşünür; ötekiler seyrek (kurallı motor oynatır, oyuncu
        farkı görmez). 30 sn önbellek."""
        if now - self.__dict__.get('_yakin_t', 0) < 30:
            return self._yakin
        try:
            insan = y.cevrimici_insanlar()
        except Exception:
            insan = []
        adlar = {k.ad.lower() for k in insan}
        haritalar = {int(k.profil.d['konum'].get('mapId', 0)) for k in insan}
        konusan = {a for a, _ in self.konusmalar}
        self._yakin = {id(b) for b in y.botlar if b.govde is not None or b.harita in haritalar or b.ad.lower() in konusan
                       or any(abs(b.hafiza.iliski(a, now)) >= 0.15 for a in adlar)
                       or any(a['kim'].lower() in adlar for a in b.k.get('anilar') or ())}
        self._yakin_t = now
        return self._yakin

    def _ajan_tick(self, y, now, acik):
        """Kim düşünsün: olay, hatırlatıcı ya da süre (llm_karar_dk; oyuncunun haritasındakiler iki kat sık, oyuncudan uzak botlar
        dört kat seyrek ve olaysız). Beş saniyede en çok iki bot; saatlik istek sınırı (llm_saatlik) aşılınca kurallı motor
        sürer."""
        if now - self.son_karar < 5:
            return
        self.son_karar = now
        if self.sinirda():
            return
        dk = y.ayar('llm_karar_dk', 10) or 0
        yakin = self._yakinlar(y, now)
        n = 0
        for b in acik:
            if now - b.__dict__.get('_ajan_mesgul', 0) < 180:
                continue                                   # düşünüyor
            if '_llm_karar' not in b.__dict__:               # ilk düşünme anları dağılsın (hepsi birden açılışta düşünmesin)
                b._llm_karar = now - b.r.uniform(0, 0.8) * dk * 60
            uzak = id(b) not in yakin
            geri = AJ.uyandirma_durumu(b)                    # iş kuyruğa giremez ya da bayatlarsa sebep kaybolmasın
            sebep = AJ.uyandiranlar(y, b, now, olaylar=not uzak)
            carpan = 0.5 if b.govde is not None else 4.0 if uzak else 1.0
            # (kendine hatırlatıcı kurmuş bot ne zaman düşüneceğini seçmiş: ayrıca dönemsel düşünmez)
            if not sebep and dk and not b.k.get('hatirlatici') and now - b._llm_karar >= dk * 60 * carpan:
                sebep = 'time to look at how things are going and decide what to do next'
            if not sebep:
                continue
            b._llm_karar = b._ajan_mesgul = now
            if not self.ekle(KARAR, {'t': now, 'fn': self._ajan, 'bot': b, 'sebep': sebep, 'iptal': geri}):
                b._ajan_mesgul = 0
                geri()
                return
            n += 1
            if n >= 2:
                return

    def _ajan(self, is_):
        b, y = is_['bot'], self.y
        try:
            if b.cevrimici:
                AJ.dusun(self, b, is_['sebep'], int(y.ayar('llm_ajan_adim', AJ.ADIM) or AJ.ADIM))
        finally:
            b._ajan_mesgul = 0

    # ------------------------------------------------------------ anılar (güçlü kip; ani.py)
    def _konustu(self, b, ad, now):
        """Bot bir oyuncuyla doğrudan konuştu: konuşma 150 sn susunca anıya özetlenir (_ani_ozet)."""
        if not GUCLU or not ad or str(ad).lower() in self.y.ada:
            return
        e = self.konusmalar.setdefault((b.ad.lower(), str(ad).lower()), {'b': b, 'ad': str(ad), 'bas': now, 'n': 0})
        e['son'] = now
        e['n'] += 1

    def _anilar_tick(self, y, now):
        for anahtar, e in list(self.konusmalar.items()):
            if now - e['son'] >= 150:
                del self.konusmalar[anahtar]
                self.ekle(OLAY, {'t': now, 'fn': self._ani_ozet, 'bot': e['b'], 'ad': e['ad'], 'bas': e['bas']})
        if now - self.son_takip < 20:
            return
        self.son_takip = now
        acik = {k.ad.lower() for k in y.cevrimici_insanlar()}
        for b, a in ANI.vadesi_gelenler(y, now, acik)[:2]:
            if self.ekle(OLAY, {'t': now, 'fn': self._takip, 'bot': b, 'ani': a}):
                a['takip']['bitti'] = True                   # bir kez (iş kuyruğa girdi)

    def _ani_ozet(self, is_):
        """Biten konuşma -> botun anısı (tek cümle), kişi hakkındaki izlenim ve varsa sonucu (takip)."""
        y, b, ad = self.y, is_['bot'], is_['ad']
        kucuk = {b.ad.lower(), ad.lower()}
        with y.lock:
            satirlar = [x for x in y.gecmis if x[0] >= is_['bas'] - 120 and str(x[1]).lower() in kucuk and (
                not str(x[2]).startswith('fisilti') or str(x[2]).split(':', 1)[-1].lower() in kucuk)]
            dokum = '\n'.join('%s%s: %s' % (x[1], ' (private)' if str(x[2]).startswith('fisilti') else ' (%s chat)' % x[2], x[3])
                              for x in satirlar[-40:])
            once = ortak_gecmis(b, ad)
            kim = persona(b, y)
        if not dokum:
            return
        sema = {'type': 'object', 'properties': {
            'kaydet': {'type': 'boolean'}, 'ozet': {'type': 'string', 'maxLength': 200},
            'duygu': {'type': 'number'}, 'onem': {'type': 'integer', 'enum': [1, 2, 3]}, 'izlenim': {'type': 'string', 'maxLength': 240},
            'takip': {'type': 'object', 'properties': {
                'amac': {'type': 'string', 'enum': ['yok'] + list(ANI.AMACLAR)}, 'dakika': {'type': 'integer'},
                'arac': {'type': 'string', 'enum': list(ANI.TAKIP_ARACLARI)}, 'harita': {'type': 'string', 'maxLength': 8}},
                'required': ['amac', 'dakika', 'arac', 'harita']}},
            'required': ['kaydet', 'ozet', 'duygu', 'onem', 'izlenim', 'takip']}
        k = ('You are %s.\n%s\nWhat you already knew about %s:%s\n\nThis conversation with %s just ended:\n%s\n\nWrite a private '
             'note for your own memory, always in English. kaydet: false if it was only small talk with nothing worth remembering. '
             'ozet: ONE short concrete sentence, first person (what happened, what was said or agreed, places, times), like "%s '
             'asked me how to farm on 2-3, I promised to show him later". duygu: how you feel about %s now, from -1 (hate) to 1 '
             '(really like). onem: 1 small, 2 notable, 3 big. izlenim: your overall impression of %s in one sentence, from '
             'everything you know (update the old one). takip: only if something is left to do later, else amac yok: soz = a '
             'plan or promise you both agreed on (meet, duel, group up, help), intikam = you want to get back at him, tesekkur = '
             'you want to thank him later, rekabet = a rivalry to continue, merak = you want to ask him something later. dakika: '
             'in how many minutes it should happen (from what was said; 10 if nothing was said). arac: what you do then: duello = '
             'fight him, grup_davet = invite him to your group, takip_et = fly to his map, yardima_git = help him on his map, yok = '
             'only write to him. harita: the agreed map (like 4-4) or empty.') % (b.ad, kim, ad, once or ' nothing', ad, dokum, ad,
                                                                             ad, ad)
        r = self.sor(k, sema, en_cok=240, sicaklik=0.4)
        with y.lock:
            ANI.izlenim_yaz(b, ad, r.get('izlenim'), y.now)
            ozet = ' '.join(str(r.get('ozet') or '').split())
            if not r.get('kaydet') or not ozet:
                return
            t = r.get('takip') or {}
            try:
                duygu, onem = float(r.get('duygu') or 0), int(r.get('onem') or 1)
                tk = ANI.takip_kur(t.get('amac'), y.now, int(t.get('dakika') or 10), t.get('arac'), t.get('harita'))
            except (TypeError, ValueError):
                duygu, onem, tk = 0.0, 1, None
            ANI.ekle(b, ad, ozet, 'konusma', duygu, onem, y.now, takip=tk, birlestir=False)

    def _takip(self, is_):
        """Anının sonucu: bot oyuncuya konuyu açan bir fısıltı yazar, gerekirse eyleme geçer (düello, davet, takip, yardım)."""
        y, b, a = self.y, is_['bot'], is_['ani']
        t, ad = a['takip'], a['kim']
        ne = {'soz': 'follow up on what you two agreed, now it is time', 'intikam': 'you are coming for revenge: tell him so (short '
              'trash talk, in character, no real hate)', 'tesekkur': 'thank him for it, casually', 'rekabet': 'poke him about your '
              'rivalry', 'merak': 'ask him what you wanted to ask'}[t['amac']]
        harita = t.get('harita') or ''
        if t['arac'] in ('duello', 'yardima_git', 'takip_et') and not harita:
            import topluluk as TP
            kisi = TP.bul(ad=ad)
            harita = H.name(int(kisi.profil.d['konum'].get('mapId', 0))) if kisi is not None else ''
        arac = t['arac']
        if arac in ('duello', 'yardima_git', 'takip_et'):     # ulaşamayacağı yere "geliyorum" demesin (canlı: MMO botu EIC'nin 2-1'ine)
            m = AR._harita(harita) if harita else None
            if m is None or not K.girebilir(m, b.firma, b.seviye) or not K.yol(b.harita, m, b.firma, b.seviye):
                arac = 'yok'
                ne += ('. He is on %s right now, where you cannot get to him: say you will deal with it another time (or ask him '
                       'to come somewhere you both can go)' % (harita or 'an unknown map'))
        eylem = {'duello': 'You are flying to %s to fight him right now.' % harita, 'grup_davet': 'You are inviting him to your '
                 'group right now.', 'takip_et': 'You are flying to his map %s right now.' % harita, 'yardima_git': 'You are '
                 'coming to help him on %s right now.' % harita, 'yok': ''}.get(arac, '')
        sema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 90}}, 'required': ['metin']}
        with y.lock:
            k = ('You are %s. %s Your style: %s.\nAbout %s:%s\n\nEarlier private messages:\n%s\n\nYou start a private chat with %s '
                 'because of this memory: "%s" (%s). Purpose: %s. %s One short line (metin), like a real player who remembers him; '
                 'mention the memory naturally, not word for word.') % (
                b.ad, sohbet_personasi(b, y), tarz(b), ad, ortak_gecmis(b, ad), konusma_gecmisi(y, adlar=[b.ad, ad], n=10, sn=7200),
                ad, a['ozet'], ANI.ne_zaman(y.now - a['t']), ne, eylem)
        r = self.sor(k, sema, en_cok=80, sicaklik=0.8)
        with y.lock:
            metin = self._metin(b, r.get('metin'))
            if metin:
                y.konus(b, 'fisilti', metin, alici=ad, now=y.now)
            if arac != 'yok':
                arg = {'ad': ad}
                if arac in ('duello', 'yardima_git') and harita:
                    arg['harita'] = harita
                y.eylemler.append((y.now + KN.yazma_suresi(metin or 'ok', b) + b.r.uniform(1, 3), b, (arac, arg)))
            t['sonuc'] = metin or ''

    # ------------------------------------------------------------ yardımcılar
    def _metin(self, b, metin, yanki=None):
        out = self._metin_suz(b, metin, yanki)
        if not out and str(metin or '').strip():
            self.susturulan.append(str(metin)[:80])      # tanı (tools/bot_sohbet_deneme.py)
            del self.susturulan[:-50]
        return out

    def _metin_suz(self, b, metin, yanki=None):
        """Modelin satırı -> sohbete gidecek metin ya da '' (boş, rakamlı durum raporu ya da İngilizce dışı ise susar). Üslubun yalnız
        hafif kısmı uygulanır (küçük harf, kısaltma, nadir yazım hatası); büyük harf ve emoji eklenmez."""
        metin = ' '.join(str(metin or '').split())[:140]
        metin = re.sub(r'''[\s'"}\]{\[,]+$''', '', re.sub(r'''^[\s'"{\[]+''', '', metin))     # JSON artığı ('} ...)
        if not COK_DILLI and _YABANCI.search(metin):
            return ''
        if COK_DILLI and ingilizce_mi(metin, KN.dil(b)):
            return ''                                        # Türkçe konuşan bot İngilizce yazdı (oyuncu bildirimi 2026-10-30)
        metin = ' '.join((_EMOJI if COK_DILLI else _SIMGE).sub('', metin).split())
        if not metin or re.search(r'\d{3,}\s*(k\b|credits?|cr\b|uri\b|uridium|ep\b|exp\b|xp\b|honou?r|power|hp\b|dmg|damage)|'
                                  r'\b(credits?|uridium|uri|ep|honou?r|power)\s*:?\s*\d{3,}', metin, re.I):
            return ''                                        # durum sayıları (yaş, yıl gibi sayılar serbest)
        if re.search(r'\b(mood|personality|plays like|not very|own company maps|pilot, level|game facts|newest message)\b', metin, re.I):
            return ''                                        # modelin botun tarifini ya da istemin sözcüklerini sohbete dökmesi
        if len(metin.split()) > 16:
            return ''                                        # sohbette kimse paragraf yazmaz
        if '_' in metin and any(a in metin for a in AR.ARACLAR) or re.search(r'\b(assist|assistance|how can i help)\b', metin, re.I):
            return ''                                        # araç adı ya da asistan dili
        if zararli(metin):
            return ''                                        # kendine zarar, ölüm dileği, ağır hakaret: oyun içi atışma bunlarsız
        if _SEVIYE_DUYURU.search(metin) and not (yanki and re.search(r'seviye|level|lvl|ka[çc]', str(yanki), re.I)):
            if b.__dict__.get('_seviye_duyuru') == b.seviye or b.seviye < 6:
                return ''                                    # bu seviyeyi zaten duyurdu (olay tepkisi + ajan: iki kez "lv2 oldum"); ilk
                #                                              seviyeleri kimse ilan etmez (taze pakette dört bot bir dakikada "lvl 2 oldum")
            b._seviye_duyuru = b.seviye
        sel = _SELAM_BASI.match(metin)
        if sel and any(str(x[1]) == b.ad and _SELAM_BASI.match(str(x[3])) and self.y.now - x[0] < 1200 for x in self.y.gecmis[-80:]):
            metin = metin[sel.end():].strip()               # bu bot az önce selam verdi: her satıra "selam millet!" diye başlamaz
            if len(metin.split()) < 2:                       # (sohbet denemesi 2026-10-30)
                return ''
        onceki = [str(x[3]) for x in self.y.gecmis[-25:] if str(x[3]) != yanki] + self.y.bekleyen_metinler()
        # (yanıtlanan mesajın kendisi yankı denetimine kalır: "VRU is the best company? you're an EIC noob" gibi alıntılı yanıt geçer)      # yazılmayı bekleyenler de
        if any(_benzer(metin, x) for x in onceki):
            return ''                                        # az önce biri (aşağı yukarı) aynısını yazdı
        if yanki:                                            # yankı: oyuncunun sözcüklerinin çoğunu tekrarlıyor
            a, c = set(re.findall(r'[^\W\d_]+', metin.lower())), set(re.findall(r'[^\W\d_]+', yanki.lower()))
            if len(c) >= 3 and len(a) >= 2 and len(a & c) >= 0.7 * len(a):
                return ''                                        # başkası az önce aynısını yazdı: gerçek oyuncular tekrarlamaz
        metin = re.sub(r'\bmmo+t?\b', 'mmo', re.sub(r'\bvru[d]\b', 'vru', re.sub(r'\biec\b', 'eic', metin, flags=re.I), flags=re.I),
                       flags=re.I)                           # modelin firma adlarını bozması (mmoo, iec)
        u = dict(b.k['kisilik'].get('uslup') or {})
        u.update(emoji=0.0, noktalama=0.0, buyuk_harf=0.0, hata=u.get('hata', 0.05) * 0.4)
        return KN.uslupla(metin, u, b.r, KN.dil(b) if COK_DILLI else 'en')
