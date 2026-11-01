"""Gelişmiş kip: botların sohbeti ve stratejik kararları yerel dil modeliyle (llm_sunucu: llama-server + Qwen3 4B, düşünme kapalı).

Model oyunun döngüsünü hiç bekletmez: işler öncelikli kuyruğa girer, işçiler (llm_toplu kadar; sunucunun paralel yuvaları) sırayla
yürütür, sonuç gelince bota uygulanır. Kuyruk dolarsa ya da model kapalıysa yönetici Normal kipin kalıplarına döner (sohbet_motoru).

Dahili model yalnız İngilizce çalışır (Qwen3 4B Türkçede zayıf; kullanıcı 2026-10-29): istemler İngilizce, botlar İngilizce konuşur.
Kullanıcı başka bir sağlayıcı seçtiyse (llm_saglayici: OpenAI, Claude, Gemini, Ollama ...) istemler yine İngilizce ama her bot kendi
sohbet dilinde konuşur (COK_DILLI: persona "Chats in Turkish", süzgeç aksanlı harfi susturmaz, üslup botun dilinde).
Güçlü sağlayıcıda (GUCLU: dahili model değil) gerçekçilik katmanı açılır: geniş sohbet geçmişi, anı defteri (memories.py: kişilerle yaşanan
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

import map_links as H
from . import name_style as NS
from . import agent as AGT
from . import memories as MEM
from . import agent_tools as TL
from . import interaction as IX
from . import brain as B
from . import catalog as K
from . import speech as SPC
from . import llm_provider as PRV
from . import admin_warnings as AW
from . import llm_server as LS

WHISPER, ROOM, EVENT, DECISION, BOT_CHAT = 0, 1, 2, 3, 4
MAIL = EVENT                      # posta acele değil: kuyruk dolarsa kalıpla yanıtlanır
DECISION_GOALS = ('kasilma', 'gorev', 'pvp', 'alisveris', 'dinlenme')
FIRMA = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
CHANNEL = {'global': 'global', 'firma': 'company', 'klan': 'clan', 'grup': 'group'}
TRAIT_NAME = {'saldirganlik': 'aggressive', 'rekabet': 'competitive', 'sosyallik': 'sociable', 'sabir': 'patient', 'risk': 'risk-taking',
              'sadakat': 'loyal', 'yardimseverlik': 'helpful', 'konuskanlik': 'chatty', 'tutumluluk': 'thrifty', 'hirs': 'ambitious'}
GOAL_NAME = {'kasilma': 'farming aliens', 'gorev': 'doing quests', 'pvp': 'hunting enemy players', 'alisveris': 'shopping',
            'dinlenme': 'taking a break at base', 'kesif': 'checking out a new map', 'grup': 'playing in a group',
            'yardim': 'going to help someone', 'basit': 'farming aliens'}
ARCHETYPE_NAME = {'kasici': 'a grinder who mostly farms aliens', 'avci': 'a PvP hunter', 'sosyal': 'a social player who loves to chat',
              'tuccar': 'a trader who watches the auction', 'gorevci': 'a quest player', 'rahat': 'a casual player',
              'lider': 'a natural clan leader'}
SYSTEM_PROMPT = ("You are a real human player of a DarkOrbit-like space MMO, typing in the in-game chat. Never say or hint that you are a "
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
SYSTEM_MULTI = SYSTEM_PROMPT.replace('Always write in English.', "Each pilot writes in his own chat language, given as 'Chats in ...' in his "
                            "description (English if none is given), the casual way native gamers type in that language; game names "
                            "(maps like 2-3, ships, aliens, MMO, EIC, VRU) stay as they are.")
MULTILINGUAL = False                 # Beyin kurulunca: seçili sağlayıcı dahili model değilse
STRONG = False                     # aynı koşul: hızlı, geniş bağlamlı model (anı defteri, sonuçlar, dedikodu, geniş geçmiş)
LANG_NAME = {'tr': 'Turkish', 'en': 'English', 'de': 'German', 'es': 'Spanish', 'fr': 'French', 'pl': 'Polish', 'pt': 'Portuguese',
          'ru': 'Russian'}
_FOREIGN = re.compile(r'[^\x00-\x7f -⯿\U0001f000-\U0001faff️]')   # İngilizce dışı harf: satır susar
_SYMBOL = re.compile(r'[^\x20-\x7e]')            # emoji ve süs: atılır, satır kalır
_EMOJI = re.compile('[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d]')    # çok dilli kipte yalnız bunlar atılır
_HARMFUL = re.compile(r'\b(kys|kill (your|ur)self|killyourself|shoot (your|ur)self|hang (your|ur)self|end (your|ur) life|'
                      r'better off dead|wish (you|u) (were )?dead|hope (you|u) die|'
                      r'(go )?die\b|suicide|cancer|retard\w*|f[a4]g\w*|n[i1]gg\w*|whore|slut|rape\w*|nazi|hitler)', re.I)


def _normalize(s):
    """Karşılaştırma için: küçük harf, aksanlar düşer (oyuncular çoğu zaman aksansız yazar: "olsene", "matate")."""
    s = str(s or '').lower().replace('ı', 'i').replace('ß', 'ss').replace('ł', 'l')
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _lang_expr(promises, extra=False):
    """ek: sözcüğün ardından ek gelebilir (Türkçe "gemiyi", "lazerler", "haritada": oyun sözcükleri; önce tanınmıyordu)."""
    promises = sorted({_normalize(w) for w in promises if w}, key=len, reverse=True)
    tail = '' if extra else r'(?!\w)'
    return re.compile(r'(?<!\w)(%s)' % '|'.join(w if '\\' in w else re.escape(w) for w in promises) + tail) if promises else None


# öteki dillerin zararlı ifadeleri (kendine zarar, ölüm dileği, ağır hakaret: bot/languages/<kod>.json zararli); botlar o dillerde de
# konuşur (COK_DILLI), İngilizce süzgeç onları görmez
_HARMFUL_LANG = _lang_expr([w for d in SPC.LANGUAGES.values() for w in d.get('zararli', ())])
# mesaj türleri öteki dillerde (bot/languages/<kod>.json tepki): kutlama, veda, dönüş, yoklama; oyun sözcükleri soruyu oyun sorusu yapar
_REACTION_LANG = {t: _lang_expr([w for d in SPC.LANGUAGES.values() for w in d.get('reaction', {}).get(t, ())], extra=t == 'oyun')
              for t in ('kutlama', 'veda', 'donus', 'yoklama', 'oyun')}


# İngilizceye özgü sözcükler (oyun argosu gg, lol, inv, np, ty sayılmaz); öteki dillerde de geçenler o dilde sayılmaz
_EN_WORDS = frozenset(('the', 'to', 'my', 'you', 'your', 'im', "i'm", 'and', 'with', 'heading', 'coming', 'way', 'save', 'what', 'how',
                     'why', 'where', 'just', 'got', 'going', 'gonna', 'wanna', 'this', 'that', 'are', 'is', 'its', "it's", 'was', 'will',
                     'can', 'for', 'of', 'be', 'have', 'has', 'do', 'dont', "don't", 'yeah', 'yes', 'guys', 'lets', "let's", 'here',
                     'there', 'some', 'any', 'when', 'who', 'right', 'now', 'all', 'on', 'at', 'in', 'it', 'i', 'we', 'me', 'a', 'so',
                     'am', 'u', 'ur', 'be', 'see', 'hey', 'sure', 'fine', 'bro', 'dude', 'man', 'not', 'no', 'too', 'only', 'also'))
_EN_COMMON = {'de': {'in', 'was', 'so', 'am', 'man', 'hey', 'bro', 'no'}, 'es': {'a', 'me', 'no', 'bro', 'hey', 'man'},
             'pt': {'a', 'me', 'no', 'bro', 'hey', 'man', 'do'}, 'fr': {'a', 'me', 'on', 'hey', 'bro', 'man'},
             'pl': {'a', 'no', 'hey', 'bro', 'do'}, 'tr': {'hey', 'bro', 'man'}, 'ru': set()}


_ONE_WORD = re.compile(r'^\s*(gg|lol|lel|xd+|haha+|hah|ah+|kek|ok|okey|tamam|tmm|k|wp|ez|rofl|lmao|:d|:\)|\^\^|aynen|sjsj|ahaha+)'
                      r'[\s!.?:)]*$', re.I)
_LEVEL_ANNOUNCE = re.compile(r'\b(lv|lvl|level|seviye|stufe|nivel|niveau|poziom|уровень)\s*\.?\s*\d+|\b\d+\s*\.?\s*(seviye|lvl|level)|'
                            r'seviye atlad|level ?up|leveled|lvl ?up', re.I)
_GREETING_START = re.compile(r'^\s*(selam(lar)?|slm|merhaba|mrb|hi|hello|hey|yo|hallo|hola|salut|cze[sś][cć]|ol[aá]|привет)'
                         r'(\s+(millet|all|everyone|guys|herkes|arkada[sş]lar|leute|chicos|les gars|ludzie|pessoal|народ))?[\s!.,:]*',
                         re.I)


def is_english(text, lang):
    """Satır İngilizce mi (botun dili İngilizce değilken): İngilizceye özgü sözcüklerin oranı. "on my way to 2-1, save me a target"
    evet; "eic tabii ki, 2-1e gelyrm" ve "gg ez" hayır."""
    if lang == 'en':
        return False
    words = re.findall(r"[a-z']+", str(text or '').lower())
    if len(words) < 3 or re.search(r'[^\x00-\x7f]', str(text)):
        return False                                     # kısa argo ya da kendi harfleri olan satır
    avg = _EN_COMMON.get(lang, set())
    n = sum(1 for w in words if w in _EN_WORDS and w not in avg)
    return n >= 3 and n >= 0.45 * len(words)


def harmful(text):
    return bool(_HARMFUL.search(str(text or '')) or (_HARMFUL_LANG and _HARMFUL_LANG.search(_normalize(text))))


def lang_note(b):
    """Çok dilli kipte botun sohbet dili (persona'nın sonuna)."""
    if not MULTILINGUAL:
        return ''
    d = SPC.lang(b)
    return ' Chats in %s (always, even with people who write in another language).' % LANG_NAME.get(d, SPC.LANGUAGES.get(d, {}).get('ad', d))


def _mood(mood):
    if mood['ofke'] > 0.5:
        return 'angry'
    if mood['moral'] < 0.35:
        return 'frustrated'
    if mood['yorgunluk'] > 0.6:
        return 'tired'
    if mood['moral'] > 0.8:
        return 'in a great mood'
    return 'relaxed'


def chat_persona(b, y=None):
    """Sohbet için kısa tarif: kimlik, gemi, harita, ruh hâli, kişilerle ilişkisi ve son 10 dakikanın olayları (uzun tarif modeli
    her satırda işinden, parasından söz ettiriyordu)."""
    now = y.now if y is not None else time.time()
    relation = ['%s (%s)' % (e['ad'], 'friend' if e['d'] > 0 else 'holds a grudge') for e in
              sorted(b.memory.d.values(), key=lambda e: -abs(e['d']))[:3] if abs(e['d']) >= 0.2]
    events = [x for x in (event_text(o) for o in b.events[-6:] if o['tur'] not in ('dedim', 'arac') and now - o['t'] < 600) if x]
    return '%s: %s, level %d, flies a %s, on %s (%s), %s.%s%s%s' % (
        b.name, FIRMA[b.firma], b.level, b.k['ekip']['gemi'].replace('ship_', '').replace('-', ' '), H.name(b.game_map),
        GOAL_NAME.get(b.target.name, 'flying around') if b.target is not None else 'flying around', _mood(b.mood), _social(b),
        (' Knows: %s.' % ', '.join(relation)) if relation else '', (' Just now he %s.' % '; '.join(events[-2:])) if events else '') + \
        lang_note(b)


def _social(b):
    """Grubu ve klanı (sorulunca doğru söylesin; "grubun var mı", "klanın ne")."""
    out = ''
    try:
        import group as GR
        import clan as KL
        import community as TP
        g = GR.group_of(b.uid)
        if g is not None:
            people = TP.all_()
            out += ' In a group with %s.' % ', '.join(people[u].name for u in g.members if u != b.uid and u in people)
        k = KL.clan_of(b.profile) if b.profile is not None else None
        if k is not None:
            out += ' Clan [%s] %s%s.' % (k['etiket'], k['ad'], ' (he is the leader)' if k['lider'] == b.name.lower() else '')
    except Exception:
        pass
    return out


def persona(b, y=None):
    """Botun modele tarifi (İngilizce, sayısız): kimlik, gemi, harita, işi, kişiliği, ruh hâli, ilişkileri, son olayları."""
    en = sorted(b.traits.items(), key=lambda x: -x[1])
    dominant = ', '.join(TRAIT_NAME[k] for k, v in en[:3])
    weak = ', '.join(TRAIT_NAME[k] for k, v in en[-2:])
    target = GOAL_NAME.get(b.target.name, 'idle') if b.target is not None else 'idle'
    currency = 'rich' if b.k['kredi'] > 2000000 else 'broke' if b.k['kredi'] < 20000 else 'saving up'
    relation = ['%s (%s)' % (e['ad'], 'friend' if e['d'] > 0 else 'holds a grudge') for e in
              sorted(b.memory.d.values(), key=lambda e: -abs(e['d']))[:4] if abs(e['d']) >= 0.15]
    events = [x for x in (event_text(o) for o in b.events[-6:] if o['tur'] not in ('dedim', 'arac')) if x]
    ev = '%d-1 to %d-4' % (b.firma, b.firma) if b.level < 10 else '%d-1 to %d-8 and 4-x' % (b.firma, b.firma)
    return ("%s: %s pilot, level %d (own company maps: %s; other companies' maps are enemy territory), flies a %s, on map %s, "
            '%s, %s. Plays like %s. Personality: %s; not very %s. Mood: %s.%s%s') % (
        b.name, FIRMA[b.firma], b.level, ev, b.k['ekip']['gemi'].replace('ship_', '').replace('-', ' '), H.name(b.game_map), target, currency,
        ARCHETYPE_NAME.get(b.archetype, 'a normal player'), dominant, weak, _mood(b.mood),
        (' People: %s.' % ', '.join(relation)) if relation else '', (' Recently: %s.' % '; '.join(events)) if events else '') + lang_note(b) + \
        _memories_note(b, y) + AW.note(b, y.now if y is not None else None)


def _memories_note(b, y):
    """Güçlü kipte botun en değerli anıları (kin, söz, dostluk): kararları ve tepkileri etkilesin."""
    if not STRONG:
        return ''
    now = y.now if y is not None else b.hour()
    mems = MEM.important(b, now)
    return (' Strong memories: %s.' % '; '.join('%s (%s)' % (a['ozet'], MEM.time_ago(now - a['t'])) for a in mems)) if mems else ''


def event_text(o):
    t = o['tur']
    return {'olum': 'got killed by %s' % (o.get('killer') or 'aliens'), 'oyuncu_oldurdum': 'killed the player %s' % o.get('ad'),
            'oldurdum': 'killed the player %s' % o.get('victim'), 'seviye': 'reached level %s' % o.get('seviye'),
            'yeni_gemi': 'bought a %s' % str(o.get('esya', '')).replace('ship_', ''), 'gorev_bitti': 'finished a quest',
            'klan_kurdu': 'founded the clan %s' % o.get('ad'), 'klana_girdi': 'joined the clan %s' % o.get('klan'),
            'gruba_girdi': 'grouped up with %s' % o.get('ad'), 'kacti': 'fled from map %s' % o.get('harita'),
            'patron_oldurdum': 'killed the boss alien %s' % o.get('ad'),
            'tanik': ('saw %s kill the boss %s right next to you' % (o.get('kim'), o.get('ad')) if o.get('sub') == 'patron'
                      else 'saw %s get destroyed right next to you' % o.get('ad'))}.get(t, '')


def _clean_name(name):
    return re.sub(r'[^A-Za-z ]', '', str(name)).strip()


def _map_aliens(m):
    names = []
    for v, n in sorted(K.map_npcs(m), key=lambda x: -x[1]):
        a = _clean_name(v['ad'])
        if a and a not in names:
            names.append(a)
    return names[:4]


def game_info(f):
    """Modelin oyun bilgisi, f firmasının oyuncusu için (soru soranın firması: yanıt ona göre doğru olsun). Veriden üretilir
    (Dünya Editörü'nün değişiklikleri dahil)."""
    f = f if f in FIRMA else 1
    maps = [(f - 1) * 4 + i for i in range(1, 5)] + [16 + (f - 1) * 4 + i for i in range(1, 5)] + [13, 14, 15, 16, 29]
    row = ['%s: %s' % (H.name(m), ', '.join(a)) for m in maps for a in [[x for x in _map_aliens(m) if 'Boss' not in x]]
             if a]
    boss = ['%s (%s)' % (H.name(m), ', '.join(sorted({_clean_name(v['ad']) for v, n in K.map_npcs(m) if 'Boss' in v['ad']})[:3]))
              for m in maps if any('Boss' in v['ad'] for v, n in K.map_npcs(m))]
    row.append('BOSS aliens are on ' + '; '.join(boss[:6]))
    return ('GAME FACTS for a %s player (use them, never invent): %s players start on %d-1, MMO starts on 1-1, EIC on 2-1, VRU on 3-1; '
            'every company has its own maps (MMO 1-x, EIC 2-x, VRU 3-x), other companies\' maps are enemy land. %s home maps: %d-1 '
            'to %d-4 for beginners, %d-5 to %d-8 later; 4-1 to 4-5 are shared PvP maps. Aliens: %s. Ships: phoenix (start) -> '
            'piranha, nostromo, bigboy (credits) -> leonov, vengeance, goliath (uridium). Lasers, weakest to strongest: LF-1, MP-1 (credits), LF-2, LF-3 '
            '(uridium). Quests come from the quest giver on your base map and give lots of EP; uridium comes from bonus boxes, quests '
            'and aliens. You level up by killing aliens and finishing quests.') % (
        FIRMA[f], FIRMA[f], f, FIRMA[f], f, f, f, f, '; '.join(row))


QUESTION = re.compile(r'\?\s*$|^\s*(how|what|where|why|who|when|which|can|could|anyone|any|is|are|do|does|did|should|wanna|u|you)\b', re.I)
GAME = re.compile(r'\b(map|alien|npc|streuner|lordakia|saimon|mordon|sibelon|boss|quest|ship|laser|lf|goliath|bigboy|phoenix|piranha|'
                  r'nostromo|vengeance|leonov|uri|uridium|credit|level|lvl|clan|group|ep|honor|drone|iris|flax|shield|gen|portal|'
                  r'gate|pvp|farm|start|begin|new|noob|mmo|eic|vru|[1-5]-[1-8x])(e?s)?\b', re.I)    # çoğullar da (bosses, maps)
KINDS = (
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


def TP_firma(name):
    import community as TP
    k = TP.find(name=name)
    return int(k.profile.d['pilot'].get('factionId', 0)) if k is not None else 0


WHERE_QUESTION = re.compile(r'\b(where|which map|what map|map|maps|wo|nerede|hangi harita)\b', re.I)
MAP_SUFFIX = re.compile(r'\s*\b(for|on|in|at|from)\s+[1-5]-[1-8](\s*(,|/|and|or|&)\s*([1-5]-)?[1-8])*', re.I)


SHIPS = ('phoenix', 'liberator', 'piranha', 'nostromo', 'bigboy', 'leonov', 'vengeance', 'goliath', 'aegis', 'citadel', 'spearhead',
           'solace', 'diminisher', 'sentinel', 'spectrum', 'venom', 'cyborg', 'hammerclaw', 'berserker', 'tartarus', 'pusat')


def short_info(f):
    """Kendiliğinden sohbetlerin (bot_sohbet, grup lafı, özel fısıltı) kısa ve doğru oyun bilgisi: model gemi ve harita
    uyduruyordu ("viking", "corsair"; EIC botu VRU'nun 3-5'ine "yeni uzaylı" için çağırıyordu)."""
    f = f if f in FIRMA else 1
    return ('Facts (never invent other ships, maps or aliens): a %s pilot plays on %d-1 to %d-8, MMO maps are 1-x, EIC 2-x, VRU 3-x '
            '(the other companies\' maps are enemy land), 4-1 to 4-5 are shared PvP maps. Ships: %s.') % (
        FIRMA[f], f, f, ', '.join(SHIPS))


def foreign_map(b, text):
    """Satır başka firmanın haritasından söz ediyor mu (kendiliğinden sohbette: botlar düşman haritasına gezi önermez)."""
    return any(int(a) != b.firma for a, _ in re.findall(r'\b([1-3])-([1-8])\b', str(text or '')))


def is_question(msg):
    return bool(QUESTION.search(msg))


def side(b, fac, name):
    """Pilotun konuşana göre tarafı (küçük model firmaları karıştırıyordu: VRU botu EIC'nin "VRU ile savaşalım" çağrısına katıldı)."""
    if not fac:
        return ''
    if b.firma == fac:
        return 'He is %s like %s: a teammate, he sides with %s.' % (FIRMA[b.firma], name, FIRMA[b.firma])
    return 'He is %s, %s is %s: on the rival side; he always sides with %s against %s.' % (
        FIRMA[b.firma], name, FIRMA.get(fac, '?'), FIRMA[b.firma], FIRMA.get(fac, '?'))


FIRMA_NO = {'mmo': 1, 'mars': 1, 'eic': 2, 'earth': 2, 'vru': 3, 'venus': 3}
COMPANY_NAME = re.compile(r'\b(mmo|eic|vru|mars|earth|venus)\b', re.I)


def company_note(msg, fac, candidate):
    """Mesajda firmalardan söz ediliyorsa (çağrı, övünme, sataşma) her tarafın nasıl tepki vereceğini açıkça yazar."""
    if not COMPANY_NAME.search(msg) or not fac:
        return ''
    friendly = [b.name for b in candidate if b.firma == fac]
    enemy = [b.name for b in candidate if b.firma != fac]
    out = ' The message is about the companies.'
    names = {FIRMA[FIRMA_NO[m.lower()]] for m in COMPANY_NAME.findall(msg)} - {FIRMA.get(fac)}
    if names and message_kind(msg) == 'satasma':
        out += ' It insults %s: %s pilots feel insulted and hit back at %s (never at their own company).' % (
            ' and '.join(sorted(names)), ' and '.join(sorted(names)), FIRMA.get(fac, '?'))
    if friendly:
        out += ' His teammates (%s) may agree with him.' % ', '.join(friendly)
    if enemy:
        out += (' Pilots of the other companies (%s) take it as coming from an enemy: they defend their own company, mock or '
                'threaten him back, and never agree to fight their own company.' % ', '.join(enemy))
    return out


def map_note(msg, fac):
    """Soruda başka firmanın haritası geçiyorsa modele açık not (küçük model "EIC'yim, 1-1'de nasıl başlarım"a 1-1 diyordu)."""
    out = []
    for a, b_ in re.findall(r'\b([1-3])\s*-\s*([1-8])\b', msg):
        owner = int(a)
        if fac and owner != fac:
            out.append(' Note: %s-%s belongs to %s, it is enemy land for a %s player; %s players start on %d-1.' % (
                a, b_, FIRMA[owner], FIRMA.get(fac, '?'), FIRMA.get(fac, '?'), fac))
    return ''.join(out[:1])


_FILLER = {'i', 'u', 'you', 'a', 'the', 'is', 'it', 'to', 'and', 'on', 'in', 'for', 'of', 'lol', 're', 'm', 's', 'im', 'just', 'but'}


def _similar(a, b):
    """İki satır aynı şeyi mi söylüyor: eşit ya da anlamlı sözcüklerinin çoğu ortak (aynı ipucunu ikinci kez vermek)."""
    if a.lower() == b.lower():
        return True
    x = set(re.findall(r'[\w-]+', a.lower())) - _FILLER
    y = set(re.findall(r'[\w-]+', b.lower())) - _FILLER
    return len(x) >= 3 and len(y) >= 3 and len(x & y) / len(x | y) >= 0.55


def message_kind(msg):
    """Oyuncunun mesajının türü: tepki rehberi (TEPKI) için. İstekler (grup, klan, arkadaşlık, gel) 'istek': kararı interaction.py
    verir ("who wants to group up?" oyun sorusu sayılıp harita ipucu alıyordu)."""
    n, _ = SPC.intent(msg)
    if n in IX.INTENTS and n != 'yardim':
        return 'istek'
    for name, rx in KINDS:
        if rx.search(msg):
            return name
    k = _normalize(msg)
    for name in ('kutlama', 'veda', 'yoklama', 'donus'):             # öteki diller (bot/languages tepki)
        rx = _REACTION_LANG[name]
        if rx and rx.search(k) and (name != 'donus' or (len(k.split()) <= 3 and not re.search(r'[1-5]\s*-\s*[1-8]', msg))):
            # ("2-3'e geldim" dönüş değil, varış)
            return name
    if n == 'tesekkur':
        return 'tesekkur'
    if n == 'hakaret':
        return 'satasma'
    if is_question(msg) or n == 'soru':
        game = GAME.search(msg) or (_REACTION_LANG['oyun'] and _REACTION_LANG['oyun'].search(k))
        return 'soru_oyun' if game else 'soru_kisisel'
    if n == 'selam':
        return 'selam'
    return 'ifade'


REACTION = {
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


FALLBACK = {'donus': ('wb', 'wb man', 'welcome back'), 'selam': ('hey', 'yo', 'hi'), 'kutlama': ('ty', 'thx', 'thanks man'),
         'yoklama': ('here', 'yo', 'yep'), 'soru_kisisel': ('lol idk', 'haha', 'not telling :p'),
         'satasma': ('lol ok', 'cry more', 'says the guy in a phoenix', 'k')}     # model yanıtı süzgece takılırsa


def shared_history(b, name):
    """Botun o kişiyle geçmişi: hafızadaki olay sayıları ("dün birlikte gruplandık", "beni öldürmüştü"); güçlü kipte anılar ve
    izlenim de."""
    return _numbers(b, name) + (MEM.text(b, name, b.hour()) if STRONG else '')


def _numbers(b, name):
    e = b.memory.d.get(str(name).lower())
    if not e:
        return ''
    out = []
    for kind, text in (('grup', 'grouped up %d times'), ('birlikte_avlandik', 'farmed together %d times'),
                       ('yardim_ettim', 'you helped him %d times'), ('yardim_etti', 'he helped you %d times'),
                       ('oldurdu_beni', 'he killed you %d times'), ('oldurdum', 'you killed him %d times'),
                       ('meydan', 'he challenged you to a duel'), ('arkadas', 'you are friends'),
                       ('hakaret', 'he insulted you %d times'), ('sohbet', 'chatted %d times')):
        k = e['n'].get(kind, 0)
        if k:
            out.append(text % k if '%d' in text else text)
    return (' Your history with %s: %s.' % (e['ad'], ', '.join(out[:5]))) if out else ''


def chat_history(y, channel=None, names=(), n=6, sec=180, exclude=None, route=None):
    """Bağlam: aynı kanalın (ya da kişilerin fısıltılarının) son n satırı, son sn saniyeden; en yeni mesaj (haric) hariç. Güçlü
    kipte üç kat satır, dört kat süre (geniş bağlam). yol: odanın kendisi (firma, klan, grup kanalları firmaya/klana/gruba göre ayrı:
    önce MMO botu EIC'nin firma kanalındaki "geldim ne kaçırdım"a kendi kanalında yanıt verdi; sohbet denemesi 2026-10-30)."""
    if STRONG:
        n, sec = n * 3, sec * 4
    names = {a.lower() for a in names}
    out = [x for x in y.history if y.now - x[0] <= sec and (x[2] == channel and (not route or len(x) < 5 or x[4] in (None, route)) if channel else
                                                          (str(x[2]).startswith('fisilti') and (x[1].lower() in names or
                                                           any(a in str(x[2]).lower() for a in names))))]
    if exclude and out and out[-1][3] == exclude:
        out = out[:-1]
    return '\n'.join('%s: %s' % (x[1], x[3]) for x in out[-n:]) or '(nothing)'


def style(b):
    """Botun yazış tarzı (kişilikten): modele her pilotun başka konuşması için."""
    o = b.traits
    rude = b.__dict__.get('rude', 1)                     # paketin kaba sohbet ayarı (0 kapalı ... 3 çok sert)
    if b.__dict__.get('moderator'):
        t = 'a calm chat moderator of the server, polite, keeps the chat clean'
    elif rude >= 2 and o['saldirganlik'] > 0.75 - 0.15 * rude:
        t = 'toxic and provocative, trash talks other pilots and companies hard (still no slurs or real-life threats)'
    elif o['saldirganlik'] > 0.7 and o['yardimseverlik'] < 0.4:
        t = 'a bit toxic and sarcastic, loves trash talk' if rude else 'competitive but always polite, never trash talks'
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


def addressed_bots(y, channel, msg, listener):
    """Oyuncunun konuştuğu bot(lar): adı geçen; yoksa "you/u", kutlama, teşekkür ya da kısa tepkiyse bu kanalda az önce (90 sn)
    konuşan son bot. Genel sorular kimseye değildir."""
    named = [b for b in listener if NS.is_mentioned(b.name, msg)]
    if named:
        return named
    last = [x for x in y.history[-15:] if x[2] == channel and y.now - x[0] < 90 and str(x[1]).lower() in y.name_index
           and (len(x) < 5 or not listener or x[1].lower() in {b.name.lower() for b in listener})]      # o kanalı duyanlardan
    kind = message_kind(msg)
    if re.search(r'\b(guys|all|anyone|anybody|everyone|everybody|ppl|people|someone|somebody|yall|y\'all)\b', msg, re.I) \
            or COMPANY_NAME.search(msg) or kind == 'yoklama':
        return []                                            # herkese ya da bir firmaya ("MMO noobs" son konuşana değil)
    if last and (re.search(r'\b(you|u|your|ur|yours)\b', msg, re.I) or kind in ('kutlama', 'tesekkur')
                or (len(msg.split()) <= 3 and kind not in ('soru_oyun', 'selam', 'veda'))):
        b = y.name_index.get(str(last[-1][1]).lower())
        return [b] if b is not None and b.online else []
    return []


TOPICS = ('asks if anyone is farming on his map', 'complains about a boss or a hard alien', 'asks which ship to buy next',
           'brags about a kill or a new level', 'asks if any clan is recruiting', 'warns about enemy players on a map',
           'jokes about losing his ship again', 'asks for a group to do quests', 'says he is saving uridium for something big',
           'complains that he is tired after work or school', 'says he is eating something while playing', 'asks what music people '
           'listen to while farming', 'says it is late and he should sleep but one more quest', 'asks how long people have been '
           'playing this game', 'teases another company (MMO, EIC, VRU)', 'asks who is the strongest player on the server',
           'laughs about a funny thing that happened on a map', 'asks if anyone wants to duel for fun', 'says the weekend is finally '
           'here', 'asks if lasers or shields matter more')


def pick_topic(b, y):
    """Botlar arası sohbetin açılış konusu: botun son olayından (varsa) ya da geniş bir konu listesinden (oyun içi ve dışı). Güçlü
    kipte bazen bir oyuncu hakkındaki anısı (dedikodu: dinleyenler duyar, ani.duydu)."""
    if STRONG:
        a = MEM.pick_gossip(b, y.now, b.r)
        if a is not None and b.r.random() < 0.4:
            b._gossip = a
            return 'he tells the others about the player %s (%s): "%s"' % (a['kim'], MEM.time_ago(y.now - a['t']), a['ozet'])
    last = [o for o in b.events[-5:] if o['tur'] in ('olum', 'seviye', 'yeni_gemi', 'oldurdum', 'gorev_bitti', 'klana_girdi')
           and y.now - o['t'] < 900]
    if last and b.r.random() < 0.4:
        return 'he mentions that he just %s' % event_text(last[-1])
    return 'he ' + b.r.choice(TOPICS)


class Brain:
    def __init__(self, y, log=print):
        self.y, self.log = y, log
        self.slot = int(y.setting('llm_toplu', 4) or 4)
        global MULTILINGUAL, STRONG
        self.server = PRV.client(self.slot, log)              # dahili model ya da kullanıcının sağlayıcısı
        MULTILINGUAL = STRONG = not isinstance(self.server, LS.Server)
        self.ready = False
        self.queue = []
        self.counter = itertools.count()
        self.condition = threading.Condition()
        self.running = True
        self.last_bot_chat = time.time() + 60
        self.last_decision = 0.0
        self.last_event = 0.0
        self.stats = {'istek': 0, 'hata': 0, 'sure': 0.0, 'dropped': 0}
        self.muted = []             # süzgeçte atılan model satırları
        self.conversations = {}             # güçlü kip: (bot, oyuncu) -> {b, ad, bas, son, n}: bitince anıya özetlenir
        self.request_times = []           # son bir saatteki bütün isteklerin anları (llm_saatlik: sohbet, anı, karar hepsi)
        self.usage_trace = []           # [(an, sağlayıcının token sayacının kopyası)] dakikada bir: son bir saatin kullanımı
        self.last_follow = 0.0

    # ------------------------------------------------------------ yaşam
    def launch(self):
        threading.Thread(target=self._open, name='llm-acilis', daemon=True).start()

    def _open(self):
        for wait in (30, 60, 120, 240, 480, None):        # geçici hata (429, 5xx, ağ) tek denemede bütün oturumu kapatmasın
            try:
                self.server.launch()
                break
            except Exception as e:
                code = getattr(e, 'code', None)
                permanent = isinstance(self.server, LS.Server) or code is not None and 400 <= code < 500 and code not in (408, 429)   # yerel model ya da anahtar/model yanlış
                if permanent or wait is None or not self.running:
                    self.log('   botlar: dil modeli açılamadı, Normal kip gibi sürüyor: %s' % e)
                    return
                self.log('   botlar: dil modeli açılamadı (%s), %d sn sonra yeniden denenecek' % (e, wait))
                time.sleep(wait)
        if not self.running:
            return
        self.ready = True
        for i in range(self.slot):
            threading.Thread(target=self._worker, name='llm-%d' % i, daemon=True).start()
        self.log('   botlar: dil modeli hazır (%s, %d yuva)' % (('port %d' % self.server.port) if self.server.port else self.server.name,
                                                               self.slot))

    def stop(self):
        self.running = False
        with self.condition:
            self.condition.notify_all()
        self.server.stop()

    # ------------------------------------------------------------ bütçe ve kullanım
    def at_limit(self):
        """Saatlik istek sınırına (llm_saatlik; 0 sınırsız) gelindi mi: gelindiyse yeni iş alınmaz (sohbet kalıplara, kararlar
        kurallı motora döner)."""
        if isinstance(self.server, LS.Server):
            return False                                   # dahili model ücretsiz: sınır yalnız uzak sağlayıcıda
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < 3600]
        limit = self.y.setting('llm_saatlik', 200) or 0
        return bool(limit) and len(self.request_times) >= limit

    def _usage_tick(self, now):
        if self.usage_trace and now - self.usage_trace[-1][0] < 60:
            return
        self.usage_trace.append((now, dict(getattr(self.server, 'usage', {}))))
        while len(self.usage_trace) > 1 and now - self.usage_trace[1][0] >= 3600:
            self.usage_trace.pop(0)

    def summary(self):
        """Panelin kullanım satırı (durum.json'a yazılır): son bir saatin istekleri ve tokenleri, sınır, sağlayıcı."""
        now = dict(getattr(self.server, 'usage', {}))
        once = self.usage_trace[0][1] if self.usage_trace else {}
        hour = {k: now.get(k, 0) - once.get(k, 0) for k in ('istek', 'girdi', 'onbellek', 'cikti')}
        duration = (time.time() - self.usage_trace[0][0]) if self.usage_trace else 0
        return {'saat': hour, 'duration_min': round(duration / 60), 'toplam': now, 'sinir': self.y.setting('llm_saatlik', 200) or 0,
                'at_limit': self.at_limit(), 'provider': getattr(self.server, 'name', ''), 'hazir': self.ready}

    def add(self, priority, job):
        if self.at_limit():
            self.stats['sinir'] = self.stats.get('sinir', 0) + 1
            return False
        with self.condition:
            if len(self.queue) >= self.slot * 3 and priority >= EVENT:
                self.stats['dropped'] += 1
                return False
            heapq.heappush(self.queue, (priority, next(self.counter), job))
            self.condition.notify()
        return True

    def _worker(self):
        while self.running:
            with self.condition:
                while self.running and not self.queue:
                    self.condition.wait(1.0)
                if not self.running:
                    return
                _, _, job = heapq.heappop(self.queue)
            if time.time() - job.get('t', time.time()) > 90:      # bayatladı (oyuncu çoktan unuttu)
                with self.y.lock:
                    for k in ('iptal', 'yedek'):              # ajanın uyanma sebebi geri; sohbet işi kalıp yanıtla (hiç yanıtsız kalmasın)
                        if job.get(k):
                            try:
                                job[k]()
                            except Exception:
                                self.log('   botlar: bayat iş geri alınamadı:\n' + traceback.format_exc(limit=3))
                            break
                continue
            try:
                job['fn'](job)
            except Exception:
                self.stats['hata'] += 1
                self.log('   botlar: dil modeli işi başarısız:\n' + traceback.format_exc(limit=3))
                backup = job.get('yedek')
                if backup:
                    with self.y.lock:
                        backup()

    def ask(self, user, schema, max_count=220, temperature=0.85, system=None):
        self.stats['istek'] += 1
        self.request_times.append(time.time())
        system = (system or (SYSTEM_MULTI if MULTILINGUAL else SYSTEM_PROMPT)) + AW.system_note()      # yönetici varken (yonetici_uyari.py)
        if MULTILINGUAL and system.startswith((SYSTEM_PROMPT, SYSTEM_MULTI)):                # sonda hatırlatma: model İngilizce yazan oyuncuya İngilizce yanıt veriyordu (Qwen3 denemesi)
            user += "\n\nEvery line is written ONLY in that pilot's own chat language ('Chats in ...'), whatever language others use."
        try:
            r, duration = self.server.ask(system, user, schema=schema, max_count=max_count, temperature=temperature)
        except ValueError:                                   # yanıt sınırda kesildi ya da bozuk JSON: bir kez daha, daha sakin
            self.stats['regenerate'] = self.stats.get('regenerate', 0) + 1
            r, duration = self.server.ask(system, user, schema=schema, max_count=int(max_count * 1.5), temperature=0.6)
        self.stats['sure'] += duration
        return r

    # ------------------------------------------------------------ yöneticinin kancaları
    def chat(self, y, g, now):
        """Gelen mesaj modele mi (True) yoksa kalıplara mı."""
        if not self.ready or not y.setting('llm_sohbet', True) or not y.permission('sohbet'):
            return False
        if g[0] == 'fisilti':
            b, msg, who = g[1], g[2], g[3]
            return self.add(WHISPER, {'t': now, 'fn': self._whisper, 'bot': b, 'msg': msg, 'kim': who,
                                       'yedek': lambda: y.template_whisper(b, msg, who, y.now)})
        route, msg, who = g[1], g[2], g[3]
        from .chat_engine import channel_name
        channel = channel_name(route)
        if channel is None or str(who.get('userId', '')).lower() in y.name_index:
            return True
        return self.add(ROOM, {'t': now, 'fn': self._room, 'kanal': channel, 'msg': msg, 'kim': who, 'yol': route,
                               'yedek': lambda: y.template_room(route, msg, who, y.now)})

    def event(self, y, b, o, now):
        """Botun önemli anı: bazen modele (kısa tepki), değilse kalıplara (False)."""
        if not self.ready or not y.setting('llm_sohbet', True) or o['tur'] not in ('olum', 'oyuncu_oldurdum', 'yeni_gemi', 'seviye',
                                                                                  'tanik', 'patron_oldurdum'):
            return False
        human = o.get('killer') or o.get('ad')
        if o['tur'] in ('olum', 'oyuncu_oldurdum') and (not human or str(human).lower() in y.name_index):
            return False
        if o['tur'] == 'tanik':
            human = None                                    # tanıklık: firma sohbetine, fısıltı değil
        chance = 0.35 + 0.5 * b.o('konuskanlik')
        if o['tur'] in ('seviye', 'yeni_gemi'):
            chance *= 0.3                                      # gerçek oyuncu her seviyeyi ilan etmez
        if b.r.random() > chance or now - self.last_event < 20:
            return True                                     # bu sefer susar (olay tepkileri sohbeti doldurmasın)
        self.last_event = now
        return self.add(EVENT, {'t': now, 'fn': self._event, 'bot': b, 'olay': o})

    def mailer(self, y, b, r, k):
        """Bota gelen postaya model yanıtı (toplum.posta_yanitla) -> kuyruğa girdi mi (girmediyse kalıp)."""
        if not y.setting('llm_sohbet', True):
            return False
        return self.add(MAIL, {'t': y.now, 'fn': self._mail, 'bot': b, 'posta': r, 'decision': k})

    def special(self, y, b, name, purpose):
        """Botun oyuncuya kendiliğinden fısıltısı (sohbet_motoru.ozel_baslat) -> kuyruğa girdi mi."""
        if not y.setting('llm_sohbet', True):
            return False
        return self.add(EVENT, {'t': y.now, 'fn': self._private, 'bot': b, 'ad': name, 'amac': purpose})

    def group_banter_line(self, y, b, name):
        if not y.setting('llm_sohbet', True):
            return False
        return self.add(EVENT, {'t': y.now, 'fn': self._group_talk, 'bot': b, 'ad': name})

    def tick(self, now):
        """Yöneticinin tick'inden: botlar arası sohbet ve stratejik kararlar (seyrek, kuyruk boşken)."""
        self._usage_tick(now)
        if not self.ready or len(self.queue) > self.slot:
            return
        y = self.y
        is_open = [b for b in y.bots if b.online and b.dead_until <= now]
        human_wrote = any(now - x[0] < 60 and str(x[1]).lower() not in y.name_index for x in y.history[-10:])
        if y.setting('llm_sohbet', True) and y.permission('sohbet') and now >= self.last_bot_chat and len(is_open) >= 2 and not human_wrote:
            self.last_bot_chat = now + 120 + 240 * (1 - min(1.0, len(is_open) / 30))
            self.add(BOT_CHAT, {'t': now, 'fn': self._bot_chat})
        if STRONG:
            self._memories_tick(y, now)
            if y.setting('llm_ajan', True):
                self._agent_tick(y, now, is_open)              # araç döngüsü (ajan.py) tek adımlık kararın yerine
                return
        minutes = y.setting('llm_karar_dk', 10) or 0
        if minutes and now - self.last_decision >= 20:
            # oyuncunun haritasındakiler (gözünün önünde) iki kat sık düşünür
            order = [b for b in is_open if now - getattr(b, '_llm_decision', 0) >= minutes * 60 * (0.5 if b.body is not None else 1.0)]
            if order:
                self.last_decision = now
                sec = sorted(order, key=lambda b: getattr(b, '_llm_decision', 0))[:3]
                for b in sec:
                    b._llm_decision = now
                self.add(DECISION, {'t': now, 'fn': self._decision, 'botlar': sec})

    # ------------------------------------------------------------ işler
    def _whisper(self, job):
        y, b, msg, who = self.y, job['bot'], job['msg'], job['kim']
        name = who.get('userId', '')
        fac = int(who.get('factionId') or 0) or b.firma
        schema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 90}}, 'required': ['metin']}
        rel = b.memory.relation(name)
        # Rica (grup, yardım) kararını kişiliğe dayalı karar motoru verir, eylemi o uygular; model yalnız kararı botun ağzından
        # söyler. Küçük model "olur" deyip daveti unutuyordu (canlı 2026-10-29): söz ve eylem böyle hep tutarlı.
        intent, game_map = SPC.intent(msg)
        bid = IX.offer_reply(b, name, msg, y.now)       # "gruplaşalım mı?" -> "sure": grup isteği
        if bid:
            intent = bid
        kind = 'istek' if bid else message_kind(msg)
        decision = ''
        with y.lock:
            if intent in IX.INTENTS and intent != 'yardim':
                dec = IX.decision(y, b, intent, name, who, game_map, msg, y.now)
                if dec is not None:
                    decision = dec['not']
                    job['decision'] = dec
            elif intent == 'yardim':
                incoming = y.help_call(name, who, game_map, [b], 'firma', y.now, silent=True)
                decision = ('You decided to HELP: you are flying to him now. Say it in your own words.' if incoming else
                         'You decided NOT to help (too far, too weak or busy). Say it in your own words.')
        k = ('%sYou are %s. %s Your style: %s.\nYou feel %s about %s (a %s player).\n\nEarlier private messages (context only, '
             'maybe already answered):\n%s\n\nNEWEST private message from %s: "%s"\n\n%s %s Reply ONLY to this newest message with '
             'one short line (metin), like a real person. Never echo his words.') % (
            (game_info(fac) + '\n\n') if kind == 'soru_oyun' else '', b.name, chat_persona(b, y), style(b),
            'friendly' if rel > 0.2 else 'annoyed' if rel < -0.2 else 'neutral', name + shared_history(b, name),
            FIRMA.get(fac, '?'), chat_history(y, names=[b.name, name], exclude=msg, n=10, sec=1800), name, msg,
            '' if decision else REACTION.get(kind, ''), decision)
        r = self.ask(k, schema, temperature=0.6)
        with y.lock:
            b.memory.event(name, 'sohbet', y.now)
            text = self._text(b, r.get('metin'), echo=msg)
            if text:
                y.speak(b, 'fisilti', text, recipient=name, now=y.now, priority=True)
            self._spoke(b, name, y.now)
            if job.get('decision'):
                IX.apply(y, b, job['decision'], delay=SPC.typing_time(text or 'ok', b) + b.r.uniform(1, 3))

    def _room(self, job):
        y, channel, msg, who = self.y, job['kanal'], job['msg'], job['kim']
        name = who.get('userId', '')
        fac = int(who.get('factionId') or 0)
        intent, game_map = SPC.intent(msg)
        kind = message_kind(msg)
        with y.lock:
            listener = y.listeners(channel, who)
            addressed = addressed_bots(y, channel, msg, listener)
            if not addressed and _ONE_WORD.match(msg) and (not listener or listener[0].r.random() < 0.85):
                return                                   # kimseye yazılmamış "gg", "lol", "xd": gerçek sohbette çoğu kez yanıtsız
                                                         # ("gg"ye "o senin iyi oynadığın içindi" denmesin; sohbet denemesi 2026-10-30)
            extra = sorted([b for b in listener if b not in addressed], key=lambda b: -b.o('konuskanlik') * b.r.random())[:5 - len(addressed)]
            candidate = (addressed + extra)[:5]
            # yardım çağrısı: kimin gideceğini karar motoru seçer (kişilik, güç, yol) ve gönderir; model gidenlere söyletir
            responders = y.help_call(name, who, game_map, listener, channel, y.now, silent=True) if intent == 'yardim' else []
            candidate = (responders + [b for b in candidate if b not in responders])[:5]
            decisions = []                                # istek (grup, klan, arkadaş, gel): kim ne karar verdi
            if kind == 'istek':
                if addressed:
                    decisions = [(b, IX.decision(y, b, intent, name, who, game_map, msg, y.now)) for b in addressed[:1]]
                elif intent in ('grup', 'klan', 'gorev', 'duello', 'ozel', 'kapi'):
                    decisions = [(b, b.__dict__.pop('_request_decision', None) or IX.decision(y, b, intent, name, who, game_map, msg, y.now))
                                for b in y.open_call(intent, name, who, game_map, msg, listener, y.now)]
                elif intent == 'takip' and channel == 'grup':      # grup sohbetinde "follow me / come 2-4": grubun botları
                    decisions = [(b, IX.decision(y, b, intent, name, who, game_map, msg, y.now)) for b in listener[:3]]
                decisions = [(b, dec) for b, dec in decisions if dec is not None]
                if not decisions and intent == 'duello':
                    kind = 'meydan'                       # kimse kabul etmedi: laf atışması (TEPKI meydan)
                elif not decisions:
                    return                               # kimse üstlenmedi: gerçek sohbetteki gibi sessizlik
                for b, dec in decisions:
                    IX.apply(y, b, dec, delay=b.r.uniform(6, 12))     # yanıtı yazdıktan sonra (model ~2 sn + yazma)
                candidate = [b for b, _ in decisions] or candidate
            m = COMPANY_NAME.search(msg) if kind == 'yoklama' else None
            if m:                                        # "any eic online?": yalnız o firmanın pilotları "buradayım" der
                f = FIRMA_NO[m.group(1).lower()]
                candidate = [b for b in listener if b.firma == f][:3]
            elif fac and not addressed and COMPANY_NAME.search(msg):
                # başka firmadan söz ediliyor ("MMO noobs", "VRU is the best"): o firmanın pilotları ve bir takım arkadaşı tepki verir
                mentioned = {FIRMA_NO[x.lower()] for x in COMPANY_NAME.findall(msg)} - {fac}
                to_them = [b for b in candidate if b.firma in mentioned] + [b for b in listener if b.firma in mentioned and b not in candidate]
                candidate = (to_them[:2] + [b for b in candidate if b.firma == fac][:1]) or candidate
            history = chat_history(y, channel, exclude=msg, route=job.get('yol'))
        if not candidate:
            return
        # kim yanıtlayabilir: hitap edilen (yalnız o), yardıma gidenler, yoksa en çok iki pilot
        responder = responders or (candidate if decisions else None) or addressed or candidate
        max_count = min(3, len(responders)) if responders else len(decisions) if decisions else len(addressed) if addressed else \
            1 if kind in ('veda', 'tesekkur', 'donus', 'ara') else 2
        min_value = 1 if (responders or decisions or addressed or kind in ('soru_oyun', 'soru_kisisel', 'donus', 'selam', 'yoklama')) else 0
        schema = {'type': 'object', 'properties': {'yanitlar': {'type': 'array', 'minItems': min_value, 'maxItems': max_count, 'items': {
            'type': 'object', 'properties': {'bot': {'type': 'string', 'enum': [b.name for b in responder]},
                                             'metin': {'type': 'string', 'maxLength': 90}},
            'required': ['bot', 'metin']}}}, 'required': ['yanitlar']}
        if responders:
            m = H.name(responders[0].k['intent']['plan']['harita']) if (responders[0].k.get('intent') or {}).get('plan') else 'there'
            rule = ('These pilots decided to fly to %s to fight the enemy players (not aliens) attacking %s; each says in his own '
                     'words and his own chat language that he is coming: %s.') % (m, name, ', '.join(b.name for b in responders))
        elif intent == 'yardim':
            rule = 'Nobody can go help this time; at most one pilot answers (too far or busy).'
        elif decisions:
            rule = 'It is a request. Each of these pilots answers it with his decision, in his own words:\n%s' % '\n'.join(
                '- %s: %s' % (b.name, dec['not']) for b, dec in decisions)
        else:
            rule = REACTION[kind] + map_note(msg, fac)
            if addressed:
                rule += ' %s is talking to %s, so %s answers him directly.' % (name, addressed[0].name, addressed[0].name)
        k = ('%sPilots in the %s chat:%s\n%s\n\nEarlier chat (context only, it may already be answered - do not go back to old '
             'topics):\n%s\n\nNEWEST message, from %s (a %s player): "%s"\n\n%s Reply ONLY to this newest message. Each answer is one '
             'short line in that pilot\'s own style. Never repeat or echo what someone already said.') % (
            (game_info(fac or candidate[0].firma) + '\n\n') if kind == 'soru_oyun' else '', CHANNEL.get(channel, channel),
            ' (they are all in the same group as %s: his teammates right now)' % name if channel == 'grup' else '',
            '\n'.join('- %s Style: %s. %s%s' % (chat_persona(b, y), style(b), side(b, fac, name),
                                              MEM.text(b, name, y.now) if STRONG else '') for b in candidate), history, name,
            FIRMA.get(fac, '?'), msg, rule + company_note(msg, fac, candidate))
        r = self.ask(k, schema, max_count=320, temperature=0.65 if kind.startswith('soru') or addressed else 0.85)
        with y.lock:
            order = 0
            for x in (r.get('yanitlar') or [])[:3]:
                b = y.name_index.get(str(x.get('bot', '')).lower())
                text = x.get('metin')
                if kind == 'soru_oyun' and not WHERE_QUESTION.search(msg):
                    text = MAP_SUFFIX.sub('', str(text or ''))   # "is goliath worth it" -> "...worth it" (küçük model harita ekliyordu)
                text = self._text(b, text, echo=msg) if b is not None else ''
                if b is None or not b.online or not text:
                    continue
                b.memory.event(name, 'ovgu' if kind == 'kutlama' else 'hakaret' if kind == 'satasma' and addressed else 'sohbet', y.now)
                is_whisper = any(kb is b and dec.get('fisilti') for kb, dec in decisions)
                y.speak(b, 'fisilti' if is_whisper else channel, text, recipient=name if is_whisper else None, now=y.now + order * b.r.uniform(2, 6),
                        priority=True)
                if addressed or decisions or responders:
                    self._spoke(b, name, y.now)              # doğrudan konuşma (genel yanıt değil): sonunda anıya özetlenir
                order += 1
            backup = FALLBACK.get(kind)
            # yanıt gerekiyordu ama hepsi süzgece takıldı: kısa doğal karşılık (yedekler İngilizce)
            if not order and min_value and backup and not responders and (not MULTILINGUAL or SPC.lang(responder[0]) == 'en'):
                b = responder[0]
                y.speak(b, channel, b.r.choice(backup), now=y.now, priority=True)

    def _event(self, job):
        y, b, o = self.y, job['bot'], job['olay']
        schema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 90},
                                                 'kanal': {'type': 'string', 'enum': ['fisilti', 'firma', 'global', 'hicbiri']}},
                'required': ['metin', 'kanal']}
        who = o.get('killer') or o.get('ad') or ''
        k = ('You are %s.\n%s\nThis just happened: you %s.\nDo you type something about it? kanal: fisilti = private message to %s, '
             'firma = company chat, global = global chat, hicbiri = say nothing (often the most realistic). metin: one short line.') % (
            b.name, persona(b, y), event_text(o), who or '-')
        r = self.ask(k, schema, max_count=80)
        channel = r.get('kanal')
        text = self._text(b, r.get('metin'))
        if channel == 'hicbiri' or not text or (channel == 'fisilti' and not who):
            return
        with y.lock:
            y.speak(b, channel, text, recipient=who if channel == 'fisilti' else None, now=y.now)

    def _mail(self, job):
        y, b, r, dec = self.y, job['bot'], job['posta'], job.get('decision')
        name = r['sender']
        schema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 240}}, 'required': ['metin']}
        contents = '%s %s' % (r.get('konu', ''), r.get('metin', ''))
        game = message_kind(contents) == 'soru_oyun' or (is_question(contents) and GAME.search(contents))
        fac = int(TP_firma(name) or b.firma)
        # (boolean "yanıtla" alanı kaldırıldı: model reddi "yanıtlama" sanıp iyi metni de atıyordu)
        k = ('%sYou are %s. %s Your style: %s.\nYou feel %s about %s.\n\n%s sent you an in-game MAIL.\nSubject: "%s"\nText: "%s"\n\n%s'
             'Write your answer mail (metin): 1-3 short casual sentences (at least 6 words; give a reason if you say no), like a '
             'gamer writing a quick mail, no greeting formulas like "Dear", no signature. Real players answer personal mails; only '
             'for spam or nonsense leave metin empty.') % (
            (game_info(fac) + '\n\n') if game else '', b.name, chat_persona(b, y), style(b),
            'friendly' if b.memory.relation(name) > 0.2 else 'neutral', name + shared_history(b, name), name, str(r.get('konu', ''))[:60],
            str(r.get('metin', ''))[:600],
            (dec['not'] + ' ') if dec else '')
        x = self.ask(k, schema, max_count=160, temperature=0.7)
        text = ' '.join(str(x.get('metin') or '').split())
        if len(text.split()) < 4 or (not MULTILINGUAL and _FOREIGN.search(text)) or harmful(text):
            if not dec:
                return
            from . import society
            text = society.mail_template(b, dec)                # karar varsa sessiz kalmaz
            if not text:
                return
        with y.lock:
            TL.call(y, b, 'posta_gonder', {'ad': name, 'konu': 'Re: ' + str(r.get('konu', ''))[:46], 'metin': text})

    def _private(self, job):
        y, b, name, purpose = self.y, job['bot'], job['ad'], job['amac']
        ne = {'ozel_selam': 'he just came online: greet him (a short wb / hey)',
              'ozel_grup': 'you want to group up with him: ask him (you are on %s doing %s)' % (
                  H.name(b.game_map), GOAL_NAME.get(b.target.name, 'farming aliens') if b.target is not None else 'farming aliens'),
              'ozel_sohbet': 'you just feel like chatting: ask him something casual (how it goes, his gear, his plans)'}[purpose]
        schema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 80}}, 'required': ['metin']}
        k = ('You are %s. %s Your style: %s.\nYou are friends with %s.%s\n\nEarlier private messages:\n%s\n\nYou start a private '
             'chat with him: %s. One short line (metin), like a real friend in a game, not a status report. %s') % (
            b.name, chat_persona(b, y), style(b), name, shared_history(b, name), chat_history(y, names=[b.name, name], n=6, sec=3600), ne,
            short_info(b.firma))
        r = self.ask(k, schema, max_count=60, temperature=0.85)
        with y.lock:
            text = r.get('metin') if not foreign_map(b, r.get('metin')) else ''
            text = self._text(b, text) or SPC.template(b, purpose, ad=name, harita=H.name(b.game_map))
            y.speak(b, 'fisilti', text, recipient=name, now=y.now)

    def _group_talk(self, job):
        y, b, name = self.y, job['bot'], job['ad']
        schema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 80}}, 'required': ['metin']}
        k = ('You are %s. %s Your style: %s.\nYou are in a group with %s, playing together right now.%s\n\nRecent group chat:\n%s\n\n'
             'Write one short line in the group chat to him, like a real teammate: where to go next, a quick comment on the '
             'farming or a boss, a joke, a short question. Not a status report, nothing already said. %s') % (
            b.name, chat_persona(b, y), style(b), name, shared_history(b, name), chat_history(y, 'grup', n=6, sec=900), short_info(b.firma))
        r = self.ask(k, schema, max_count=60, temperature=0.9)
        with y.lock:
            text = self._text(b, r.get('metin')) if not foreign_map(b, r.get('metin')) else ''
            if text:
                y.speak(b, 'grup', text, now=y.now)

    def _bot_chat(self, job):
        from .chat_engine import channel_path
        y = self.y
        with y.lock:
            is_open = [b for b in y.bots if b.online and b.dead_until <= y.now]
            if len(is_open) < 2:
                return
            r0 = is_open[0].r
            channel = 'global' if r0.random() < 0.3 and len({b.firma for b in is_open}) > 1 else 'firma'
            if channel == 'global':                         # global: farklı firmalardan, firmalar arası atışma olağan
                companies = r0.sample(sorted({b.firma for b in is_open}), 2)
                group = [max((b for b in is_open if b.firma == f), key=lambda b: b.o('konuskanlik') * b.r.random()) for f in companies]
                group += sorted([b for b in is_open if b not in group], key=lambda b: -b.o('konuskanlik') * b.r.random())[:1]
            else:
                fac = r0.choice([1, 2, 3])
                group = [b for b in is_open if b.firma == fac] or is_open
                group = sorted(group, key=lambda b: -b.o('konuskanlik') * b.r.random())[:3]
            if len(group) < 2:
                return
            group[0].__dict__.pop('_gossip', None)
            topic = pick_topic(group[0], y)
        schema = {'type': 'object', 'properties': {'satirlar': {'type': 'array', 'minItems': 2, 'maxItems': 5, 'items': {
            'type': 'object', 'properties': {'bot': {'type': 'string', 'enum': [b.name for b in group]}, 'metin': {'type': 'string', 'maxLength': 90}},
            'required': ['bot', 'metin']}}}, 'required': ['satirlar']}
        k = ('%s\n\nThese pilots are in the %s chat%s:\n%s\n\nLast lines in the chat (do NOT continue or repeat these, '
             'they are old):\n%s\n\nWrite a NEW short natural exchange between them (2-5 lines, a few words each). %s starts it: %s. '
             'The others react to what was actually said (answer, joke, disagree, ask back) - a real back-and-forth in their own '
             'styles, not separate statements. Never status reports.') % (
            short_info(group[0].firma) if channel == 'firma' else short_info(0).split(': a ')[0] + ': MMO maps are 1-x, EIC 2-x, VRU '
                                                                   '3-x, 4-x are shared PvP maps. Ships: ' + ', '.join(SHIPS) + '.',
            'same company' if channel == 'firma' else 'global',
            '' if channel == 'firma' else ' (players of rival companies: light banter between companies is normal, everyone stays '
                                        'loyal to his own)',
            '\n'.join('- %s Style: %s.' % (chat_persona(b, y), style(b)) for b in group),
            chat_history(y, channel, n=4, sec=120, route=channel_path(group[0], channel)), group[0].name, topic)
        r = self.ask(k, schema, max_count=320, temperature=0.95)
        with y.lock:
            t = y.now
            for x in r.get('satirlar') or []:
                b = y.name_index.get(str(x.get('bot', '')).lower())
                text = self._text(b, x.get('metin')) if b is not None else ''
                if b is None or not b.online or not text or (channel == 'firma' and foreign_map(b, text)):
                    continue
                t += b.r.uniform(4, 14)
                y.speak(b, channel, text, now=t)
            a = group[0].__dict__.pop('_gossip', None)
            if a is not None and t > y.now:                  # anlattı: dinleyenler duydu (oyuncunun itibarı yayılır)
                for d in group[1:]:
                    MEM.hear_gossip(d, group[0], a, y.now)

    def _decision(self, job):
        """Stratejik karar (sohbet yazmaz: model buradaki "söz"leri durum raporuna çeviriyordu; sohbet bot_sohbet'te)."""
        y = self.y
        bots = [b for b in job['botlar'] if b.online]
        if not bots:
            return
        lines = []
        with y.lock:
            for b in bots:
                bg = B.Context(b, y, y.now)
                points = sorted(((h.name, round(h.points(b, bg), 2)) for h in B.GOALS.values()
                               if h.name in DECISION_GOALS and B.allowed(h, y) and h.eligible(b, bg)), key=lambda x: -x[1])
                maps = ', '.join(H.name(m) for f, m, _ in bg.game_map[:4])
                lines.append('- %s\n  Options with gut-feeling scores: %s\n  Good farming maps: %s' % (
                    persona(b, y), ', '.join('%s %.2f' % x for x in points), maps or '-'))
        schema = {'type': 'object', 'properties': {'kararlar': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'bot': {'type': 'string', 'enum': [b.name for b in bots]}, 'hedef': {'type': 'string', 'enum': list(DECISION_GOALS)},
            'harita': {'type': 'string', 'maxLength': 8}}, 'required': ['bot', 'hedef', 'harita']}}}, 'required': ['kararlar']}
        k = ('For each pilot choose what he does in the next 10-20 minutes (kasilma = farm aliens, gorev = quests, pvp = hunt enemy '
             'players, alisveris = buy upgrades, dinlenme = take a break at base), realistically for his personality, mood and recent '
             'events (the scores are gut feelings, not orders). For kasilma put one of his listed maps in harita, otherwise leave it '
             'empty.\n\n%s') % '\n'.join(lines)
        r = self.ask(k, schema, max_count=240, temperature=0.7)
        with y.lock:
            for x in r.get('kararlar') or []:
                b = y.name_index.get(str(x.get('bot', '')).lower())
                if b is None or not b.online:
                    continue
                tool = {'kasilma': 'npc_avla', 'gorev': 'gorev_yap', 'pvp': 'pvp_avla', 'alisveris': 'alisveris_yap',
                        'dinlenme': 'dinlen'}.get(x.get('hedef'))
                if tool:
                    TL.call(y, b, tool, {'harita': x.get('harita')} if tool == 'npc_avla' and x.get('harita') else {})

    # ------------------------------------------------------------ ajan (güçlü kip; ajan.py)
    def _nearby(self, y, now):
        """Oyuncunun dünyasına yakın botlar (ayrıntı düzeyi): haritasında ya da oyuncuyla aynı haritada, oyuncuyla ilişkisi, anısı
        ya da süren konuşması olanlar. Bunlar tam sıklıkta ve olaylarla düşünür; ötekiler seyrek (kurallı motor oynatır, oyuncu
        farkı görmez). 30 sn önbellek."""
        if now - self.__dict__.get('_nearby_time', 0) < 30:
            return self._near
        try:
            human = y.online_humans()
        except Exception:
            human = []
        names = {k.name.lower() for k in human}
        maps = {int(k.profile.d['position'].get('mapId', 0)) for k in human}
        speakers = {a for a, _ in self.conversations}
        self._near = {id(b) for b in y.bots if b.body is not None or b.game_map in maps or b.name.lower() in speakers
                       or any(abs(b.memory.relation(a, now)) >= 0.15 for a in names)
                       or any(a['kim'].lower() in names for a in b.k.get('memories') or ())}
        self._nearby_time = now
        return self._near

    def _agent_tick(self, y, now, is_open):
        """Kim düşünsün: olay, hatırlatıcı ya da süre (llm_karar_dk; oyuncunun haritasındakiler iki kat sık, oyuncudan uzak botlar
        dört kat seyrek ve olaysız). Beş saniyede en çok iki bot; saatlik istek sınırı (llm_saatlik) aşılınca kurallı motor
        sürer."""
        if now - self.last_decision < 5:
            return
        self.last_decision = now
        if self.at_limit():
            return
        minutes = y.setting('llm_karar_dk', 10) or 0
        nearby = self._nearby(y, now)
        n = 0
        for b in is_open:
            if now - b.__dict__.get('_agent_busy', 0) < 180:
                continue                                   # düşünüyor
            if '_llm_karar' not in b.__dict__:               # ilk düşünme anları dağılsın (hepsi birden açılışta düşünmesin)
                b._llm_decision = now - b.r.uniform(0, 0.8) * minutes * 60
            far = id(b) not in nearby
            refund = AGT.wake_state(b)                    # iş kuyruğa giremez ya da bayatlarsa sebep kaybolmasın
            reason = AGT.wakers(y, b, now, events=not far)
            multiplier = 0.5 if b.body is not None else 4.0 if far else 1.0
            # (kendine hatırlatıcı kurmuş bot ne zaman düşüneceğini seçmiş: ayrıca dönemsel düşünmez)
            if not reason and minutes and not b.k.get('hatirlatici') and now - b._llm_decision >= minutes * 60 * multiplier:
                reason = 'time to look at how things are going and decide what to do next'
            if not reason:
                continue
            b._llm_decision = b._agent_busy = now
            if not self.add(DECISION, {'t': now, 'fn': self._agent, 'bot': b, 'reason': reason, 'iptal': refund}):
                b._agent_busy = 0
                refund()
                return
            n += 1
            if n >= 2:
                return

    def _agent(self, job):
        b, y = job['bot'], self.y
        try:
            if b.online:
                AGT.think(self, b, job['reason'], int(y.setting('llm_ajan_adim', AGT.STEPS) or AGT.STEPS))
        finally:
            b._agent_busy = 0

    # ------------------------------------------------------------ anılar (güçlü kip; ani.py)
    def _spoke(self, b, name, now):
        """Bot bir oyuncuyla doğrudan konuştu: konuşma 150 sn susunca anıya özetlenir (_ani_ozet)."""
        if not STRONG or not name or str(name).lower() in self.y.name_index:
            return
        e = self.conversations.setdefault((b.name.lower(), str(name).lower()), {'b': b, 'ad': str(name), 'bas': now, 'n': 0})
        e['son'] = now
        e['n'] += 1

    def _memories_tick(self, y, now):
        for key, e in list(self.conversations.items()):
            if now - e['son'] >= 150:
                del self.conversations[key]
                self.add(EVENT, {'t': now, 'fn': self._memory_summary, 'bot': e['b'], 'ad': e['ad'], 'bas': e['bas']})
        if now - self.last_follow < 20:
            return
        self.last_follow = now
        is_open = {k.name.lower() for k in y.online_humans()}
        for b, a in MEM.due_followups(y, now, is_open)[:2]:
            if self.add(EVENT, {'t': now, 'fn': self._follow, 'bot': b, 'ani': a}):
                a['takip']['bitti'] = True                   # bir kez (iş kuyruğa girdi)

    def _memory_summary(self, job):
        """Biten konuşma -> botun anısı (tek cümle), kişi hakkındaki izlenim ve varsa sonucu (takip)."""
        y, b, name = self.y, job['bot'], job['ad']
        lower = {b.name.lower(), name.lower()}
        with y.lock:
            lines = [x for x in y.history if x[0] >= job['bas'] - 120 and str(x[1]).lower() in lower and (
                not str(x[2]).startswith('fisilti') or str(x[2]).split(':', 1)[-1].lower() in lower)]
            dump = '\n'.join('%s%s: %s' % (x[1], ' (private)' if str(x[2]).startswith('fisilti') else ' (%s chat)' % x[2], x[3])
                              for x in lines[-40:])
            once = shared_history(b, name)
            who = persona(b, y)
        if not dump:
            return
        schema = {'type': 'object', 'properties': {
            'kaydet': {'type': 'boolean'}, 'ozet': {'type': 'string', 'maxLength': 200},
            'duygu': {'type': 'number'}, 'onem': {'type': 'integer', 'enum': [1, 2, 3]}, 'izlenim': {'type': 'string', 'maxLength': 240},
            'takip': {'type': 'object', 'properties': {
                'amac': {'type': 'string', 'enum': ['yok'] + list(MEM.PURPOSES)}, 'dakika': {'type': 'integer'},
                'arac': {'type': 'string', 'enum': list(MEM.FOLLOWUP_TOOLS)}, 'harita': {'type': 'string', 'maxLength': 8}},
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
             'only write to him. harita: the agreed map (like 4-4) or empty.') % (b.name, who, name, once or ' nothing', name, dump, name,
                                                                             name, name)
        r = self.ask(k, schema, max_count=240, temperature=0.4)
        with y.lock:
            MEM.write_impression(b, name, r.get('izlenim'), y.now)
            summary = ' '.join(str(r.get('ozet') or '').split())
            if not r.get('kaydet') or not summary:
                return
            t = r.get('takip') or {}
            try:
                emotion, importance = float(r.get('duygu') or 0), int(r.get('onem') or 1)
                tk = MEM.set_followup(t.get('amac'), y.now, int(t.get('dakika') or 10), t.get('arac'), t.get('harita'))
            except (TypeError, ValueError):
                emotion, importance, tk = 0.0, 1, None
            MEM.add(b, name, summary, 'konusma', emotion, importance, y.now, followup=tk, merge=False)

    def _follow(self, job):
        """Anının sonucu: bot oyuncuya konuyu açan bir fısıltı yazar, gerekirse eyleme geçer (düello, davet, takip, yardım)."""
        y, b, a = self.y, job['bot'], job['ani']
        t, name = a['takip'], a['kim']
        ne = {'soz': 'follow up on what you two agreed, now it is time', 'intikam': 'you are coming for revenge: tell him so (short '
              'trash talk, in character, no real hate)', 'tesekkur': 'thank him for it, casually', 'rekabet': 'poke him about your '
              'rivalry', 'merak': 'ask him what you wanted to ask'}[t['amac']]
        game_map = t.get('harita') or ''
        if t['arac'] in ('duello', 'yardima_git', 'takip_et') and not game_map:
            import community as TP
            person = TP.find(name=name)
            game_map = H.name(int(person.profile.d['position'].get('mapId', 0))) if person is not None else ''
        tool = t['arac']
        if tool in ('duello', 'yardima_git', 'takip_et'):     # ulaşamayacağı yere "geliyorum" demesin (canlı: MMO botu EIC'nin 2-1'ine)
            m = TL._game_map(game_map) if game_map else None
            if m is None or not K.can_enter(m, b.firma, b.level) or not K.route(b.game_map, m, b.firma, b.level):
                tool = 'yok'
                ne += ('. He is on %s right now, where you cannot get to him: say you will deal with it another time (or ask him '
                       'to come somewhere you both can go)' % (game_map or 'an unknown map'))
        action = {'duello': 'You are flying to %s to fight him right now.' % game_map, 'grup_davet': 'You are inviting him to your '
                 'group right now.', 'takip_et': 'You are flying to his map %s right now.' % game_map, 'yardima_git': 'You are '
                 'coming to help him on %s right now.' % game_map, 'yok': ''}.get(tool, '')
        schema = {'type': 'object', 'properties': {'metin': {'type': 'string', 'maxLength': 90}}, 'required': ['metin']}
        with y.lock:
            k = ('You are %s. %s Your style: %s.\nAbout %s:%s\n\nEarlier private messages:\n%s\n\nYou start a private chat with %s '
                 'because of this memory: "%s" (%s). Purpose: %s. %s One short line (metin), like a real player who remembers him; '
                 'mention the memory naturally, not word for word.') % (
                b.name, chat_persona(b, y), style(b), name, shared_history(b, name), chat_history(y, names=[b.name, name], n=10, sec=7200),
                name, a['ozet'], MEM.time_ago(y.now - a['t']), ne, action)
        r = self.ask(k, schema, max_count=80, temperature=0.8)
        with y.lock:
            text = self._text(b, r.get('metin'))
            if text:
                y.speak(b, 'fisilti', text, recipient=name, now=y.now)
            if tool != 'yok':
                arg = {'ad': name}
                if tool in ('duello', 'yardima_git') and game_map:
                    arg['harita'] = game_map
                y.actions.append((y.now + SPC.typing_time(text or 'ok', b) + b.r.uniform(1, 3), b, (tool, arg)))
            t['result'] = text or ''

    # ------------------------------------------------------------ yardımcılar
    def _text(self, b, text, echo=None):
        out = self._filter_text(b, text, echo)
        if not out and str(text or '').strip():
            self.muted.append(str(text)[:80])      # tanı (tools/bot_sohbet_deneme.py)
            del self.muted[:-50]
        return out

    def _filter_text(self, b, text, echo=None):
        """Modelin satırı -> sohbete gidecek metin ya da '' (boş, rakamlı durum raporu ya da İngilizce dışı ise susar). Üslubun yalnız
        hafif kısmı uygulanır (küçük harf, kısaltma, nadir yazım hatası); büyük harf ve emoji eklenmez."""
        text = ' '.join(str(text or '').split())[:140]
        text = re.sub(r'''[\s'"}\]{\[,]+$''', '', re.sub(r'''^[\s'"{\[]+''', '', text))     # JSON artığı ('} ...)
        if not MULTILINGUAL and _FOREIGN.search(text):
            return ''
        if MULTILINGUAL and is_english(text, SPC.lang(b)):
            return ''                                        # Türkçe konuşan bot İngilizce yazdı (oyuncu bildirimi 2026-10-30)
        text = ' '.join((_EMOJI if MULTILINGUAL else _SYMBOL).sub('', text).split())
        if not text or re.search(r'\d{3,}\s*(k\b|credits?|cr\b|uri\b|uridium|ep\b|exp\b|xp\b|honou?r|power|hp\b|dmg|damage)|'
                                  r'\b(credits?|uridium|uri|ep|honou?r|power)\s*:?\s*\d{3,}', text, re.I):
            return ''                                        # durum sayıları (yaş, yıl gibi sayılar serbest)
        if re.search(r'\b(mood|personality|plays like|not very|own company maps|pilot, level|game facts|newest message)\b', text, re.I):
            return ''                                        # modelin botun tarifini ya da istemin sözcüklerini sohbete dökmesi
        if len(text.split()) > 16:
            return ''                                        # sohbette kimse paragraf yazmaz
        if '_' in text and any(a in text for a in TL.TOOLS) or re.search(r'\b(assist|assistance|how can i help)\b', text, re.I):
            return ''                                        # araç adı ya da asistan dili
        if harmful(text):
            return ''                                        # kendine zarar, ölüm dileği, ağır hakaret: oyun içi atışma bunlarsız
        if _LEVEL_ANNOUNCE.search(text) and not (echo and re.search(r'seviye|level|lvl|ka[çc]', str(echo), re.I)):
            if b.__dict__.get('_level_announce') == b.level or b.level < 6:
                return ''                                    # bu seviyeyi zaten duyurdu (olay tepkisi + ajan: iki kez "lv2 oldum"); ilk
                #                                              seviyeleri kimse ilan etmez (taze pakette dört bot bir dakikada "lvl 2 oldum")
            b._level_announce = b.level
        sel = _GREETING_START.match(text)
        if sel and any(str(x[1]) == b.name and _GREETING_START.match(str(x[3])) and self.y.now - x[0] < 1200 for x in self.y.history[-80:]):
            text = text[sel.end():].strip()               # bu bot az önce selam verdi: her satıra "selam millet!" diye başlamaz
            if len(text.split()) < 2:                       # (sohbet denemesi 2026-10-30)
                return ''
        previous = [str(x[3]) for x in self.y.history[-25:] if str(x[3]) != echo] + self.y.pending_texts()
        # (yanıtlanan mesajın kendisi yankı denetimine kalır: "VRU is the best company? you're an EIC noob" gibi alıntılı yanıt geçer)      # yazılmayı bekleyenler de
        if any(_similar(text, x) for x in previous):
            return ''                                        # az önce biri (aşağı yukarı) aynısını yazdı
        if echo:                                            # yankı: oyuncunun sözcüklerinin çoğunu tekrarlıyor
            a, c = set(re.findall(r'[^\W\d_]+', text.lower())), set(re.findall(r'[^\W\d_]+', echo.lower()))
            if len(c) >= 3 and len(a) >= 2 and len(a & c) >= 0.7 * len(a):
                return ''                                        # başkası az önce aynısını yazdı: gerçek oyuncular tekrarlamaz
        text = re.sub(r'\bmmo+t?\b', 'mmo', re.sub(r'\bvru[d]\b', 'vru', re.sub(r'\biec\b', 'eic', text, flags=re.I), flags=re.I),
                       flags=re.I)                           # modelin firma adlarını bozması (mmoo, iec)
        u = dict(b.k['kisilik'].get('uslup') or {})
        u.update(emoji=0.0, punctuation=0.0, uppercase=0.0, hata=u.get('hata', 0.05) * 0.4)
        return SPC.apply_style(text, u, b.r, SPC.lang(b) if MULTILINGUAL else 'en')
