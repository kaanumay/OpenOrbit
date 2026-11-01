"""Advanced mode: the bots' chat and strategic decisions with a local language model (llm_server: llama-server + Qwen3 4B, thinking off).

The model never holds up the game loop: jobs go into a priority queue, workers (as many as llm_batch; the server's parallel slots) run them in turn,
and when the result arrives it is applied to the bot. If the queue is full or the model is off, the manager falls back to Normal mode's templates (chat_engine).

The built-in model works in English only (Qwen3 4B is weak in Turkish; user 2026-10-29): prompts are in English, bots speak English.
If the user chose another provider (llm_provider: OpenAI, Claude, Gemini, Ollama ...) prompts are still in English but each bot speaks in its own
chat language (MULTILINGUAL: persona "Chats in Turkish", the filter does not silence accented letters, the style is in the bot's language).
With a strong provider (STRONG: not the built-in model) the realism layer turns on: wide chat history, a memory book (memories.py: important
events and impressions with people), the model's summary when a conversation ends, consequences born of memories (a promise, revenge, thanks ... when the time comes the bot
brings up the subject and acts) and gossip between bots (the player's reputation spreads).
The bot's inner state is not given to the model as numbers (credits, power): when given, the model poured them into chat ("kredi 438, 3-1'de
kasilma"); the state is described qualitatively, the system prompt gives examples of real player lines.

Jobs (in order of priority):
  whisper     the player whispered to the bot: the bot replies in its personality, and uses a tool if it wants (group invite, going to help, follow ...)
  room        the player wrote to a channel: which of the few listening bots will reply and what they will say, in ONE request (batch)
  event       an important moment for the bot (killed you, died, bought a ship): a short reaction
  decision    the state and options of several bots in ONE request: the model picks a target (as an intent to brain; with tools)
  bot_chat    2-3 bots in the same channel have a short talk among themselves (so the world feels alive)
All replies are requested with a JSON schema (llama-server enforces it with a grammar): tool names are an enum in the schema, and so are bot names.
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
MAIL = EVENT                      # mail is not urgent: if the queue is full it is answered with a template
DECISION_GOALS = ('grinding', 'quest', 'pvp', 'shopping', 'resting')
COMPANY = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
CHANNEL = {'global': 'global', 'company': 'company', 'clan': 'clan', 'group': 'group'}
TRAIT_NAME = {'aggression': 'aggressive', 'rivalry': 'competitive', 'sociability': 'sociable', 'patience': 'patient', 'risk': 'risk-taking',
              'loyalty': 'loyal', 'helpfulness': 'helpful', 'talkativeness': 'chatty', 'frugality': 'thrifty', 'ambition': 'ambitious'}
GOAL_NAME = {'grinding': 'farming aliens', 'quest': 'doing quests', 'pvp': 'hunting enemy players', 'shopping': 'shopping',
            'resting': 'taking a break at base', 'exploring': 'checking out a new map', 'group': 'playing in a group',
            'assist': 'going to help someone', 'simple': 'farming aliens'}
ARCHETYPE_NAME = {'grinder': 'a grinder who mostly farms aliens', 'hunter': 'a PvP hunter', 'social': 'a social player who loves to chat',
              'trader': 'a trader who watches the auction', 'quester': 'a quest player', 'casual': 'a casual player',
              'leader': 'a natural clan leader'}
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
# with another provider: each pilot in its own language ("Chats in ..." in the persona)
SYSTEM_MULTI = SYSTEM_PROMPT.replace('Always write in English.', "Each pilot writes in his own chat language, given as 'Chats in ...' in his "
                            "description (English if none is given), the casual way native gamers type in that language; game names "
                            "(maps like 2-3, ships, aliens, MMO, EIC, VRU) stay as they are.")
MULTILINGUAL = False                 # when the Brain is set up: if the selected provider is not the built-in model
STRONG = False                     # same condition: a fast, wide-context model (memory book, consequences, gossip, wide history)
LANG_NAME = {'tr': 'Turkish', 'en': 'English', 'de': 'German', 'es': 'Spanish', 'fr': 'French', 'pl': 'Polish', 'pt': 'Portuguese',
          'ru': 'Russian'}
_FOREIGN = re.compile(r'[^\x00-\x7f -⯿\U0001f000-\U0001faff️]')   # non-English letter: the line is silenced
_SYMBOL = re.compile(r'[^\x20-\x7e]')            # emoji and decoration: dropped, the line stays
_EMOJI = re.compile('[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d]')    # in multilingual mode only these are dropped
_HARMFUL = re.compile(r'\b(kys|kill (your|ur)self|killyourself|shoot (your|ur)self|hang (your|ur)self|end (your|ur) life|'
                      r'better off dead|wish (you|u) (were )?dead|hope (you|u) die|'
                      r'(go )?die\b|suicide|cancer|retard\w*|f[a4]g\w*|n[i1]gg\w*|whore|slut|rape\w*|nazi|hitler)', re.I)


def _normalize(s):
    """For comparison: lowercase, accents dropped (players often write without accents: "olsene", "matate")."""
    s = str(s or '').lower().replace('ı', 'i').replace('ß', 'ss').replace('ł', 'l')
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _lang_expr(promises, extra=False):
    """extra: a suffix may follow the word (Turkish "gemiyi", "lazerler", "haritada": game words; they were not recognized before)."""
    promises = sorted({_normalize(w) for w in promises if w}, key=len, reverse=True)
    tail = '' if extra else r'(?!\w)'
    return re.compile(r'(?<!\w)(%s)' % '|'.join(w if '\\' in w else re.escape(w) for w in promises) + tail) if promises else None


# harmful expressions of the other languages (self-harm, death wish, heavy insults: bot/languages/<code>.json harmful); bots also speak
# those languages (MULTILINGUAL), the English filter does not see them
_HARMFUL_LANG = _lang_expr([w for d in SPC.LANGUAGES.values() for w in d.get('harmful', ())])
# message types in the other languages (bot/languages/<code>.json reaction): congratulation, farewell, return, check-in; game words make the question a game question
_REACTION_LANG = {t: _lang_expr([w for d in SPC.LANGUAGES.values() for w in d.get('reaction', {}).get(t, ())], extra=t == 'game')
              for t in ('congrats', 'farewell', 'welcome_back', 'roll_call', 'game')}


# words specific to English (game slang gg, lol, inv, np, ty do not count); those that also occur in the other languages do not count as that language
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
    """Whether the line is English (when the bot's language is not English): the share of English-specific words. "on my way to 2-1, save me a target"
    yes; "eic tabii ki, 2-1e gelyrm" and "gg ez" no."""
    if lang == 'en':
        return False
    words = re.findall(r"[a-z']+", str(text or '').lower())
    if len(words) < 3 or re.search(r'[^\x00-\x7f]', str(text)):
        return False                                     # a short slang line or one with its own letters
    avg = _EN_COMMON.get(lang, set())
    n = sum(1 for w in words if w in _EN_WORDS and w not in avg)
    return n >= 3 and n >= 0.45 * len(words)


def harmful(text):
    return bool(_HARMFUL.search(str(text or '')) or (_HARMFUL_LANG and _HARMFUL_LANG.search(_normalize(text))))


def lang_note(b):
    """In multilingual mode, the bot's chat language (at the end of the persona)."""
    if not MULTILINGUAL:
        return ''
    d = SPC.lang(b)
    return ' Chats in %s (always, even with people who write in another language).' % LANG_NAME.get(d, SPC.LANGUAGES.get(d, {}).get('name', d))


def _mood(mood):
    if mood['anger'] > 0.5:
        return 'angry'
    if mood['morale'] < 0.35:
        return 'frustrated'
    if mood['fatigue'] > 0.6:
        return 'tired'
    if mood['morale'] > 0.8:
        return 'in a great mood'
    return 'relaxed'


def chat_persona(b, y=None):
    """A short description for chat: identity, ship, map, mood, relationship with people and the events of the last 10 minutes (a long description made the model
    talk about its job and money in every line)."""
    now = y.now if y is not None else time.time()
    relation = ['%s (%s)' % (e['name'], 'friend' if e['d'] > 0 else 'holds a grudge') for e in
              sorted(b.memory.d.values(), key=lambda e: -abs(e['d']))[:3] if abs(e['d']) >= 0.2]
    events = [x for x in (event_text(o) for o in b.events[-6:] if o['type'] not in ('said', 'tool') and now - o['t'] < 600) if x]
    return '%s: %s, level %d, flies a %s, on %s (%s), %s.%s%s%s' % (
        b.name, COMPANY[b.company], b.level, b.k['gear']['ship'].replace('ship_', '').replace('-', ' '), H.name(b.game_map),
        GOAL_NAME.get(b.target.name, 'flying around') if b.target is not None else 'flying around', _mood(b.mood), _social(b),
        (' Knows: %s.' % ', '.join(relation)) if relation else '', (' Just now he %s.' % '; '.join(events[-2:])) if events else '') + \
        lang_note(b)


def _social(b):
    """The group and clan (so it answers correctly when asked; "grubun var mı", "klanın ne")."""
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
            out += ' Clan [%s] %s%s.' % (k['tag'], k['name'], ' (he is the leader)' if k['leader'] == b.name.lower() else '')
    except Exception:
        pass
    return out


def persona(b, y=None):
    """The bot's description to the model (English, numberless): identity, ship, map, job, personality, mood, relationships, recent events."""
    en = sorted(b.traits.items(), key=lambda x: -x[1])
    dominant = ', '.join(TRAIT_NAME[k] for k, v in en[:3])
    weak = ', '.join(TRAIT_NAME[k] for k, v in en[-2:])
    target = GOAL_NAME.get(b.target.name, 'idle') if b.target is not None else 'idle'
    currency = 'rich' if b.k['credits'] > 2000000 else 'broke' if b.k['credits'] < 20000 else 'saving up'
    relation = ['%s (%s)' % (e['name'], 'friend' if e['d'] > 0 else 'holds a grudge') for e in
              sorted(b.memory.d.values(), key=lambda e: -abs(e['d']))[:4] if abs(e['d']) >= 0.15]
    events = [x for x in (event_text(o) for o in b.events[-6:] if o['type'] not in ('said', 'tool')) if x]
    ev = '%d-1 to %d-4' % (b.company, b.company) if b.level < 10 else '%d-1 to %d-8 and 4-x' % (b.company, b.company)
    return ("%s: %s pilot, level %d (own company maps: %s; other companies' maps are enemy territory), flies a %s, on map %s, "
            '%s, %s. Plays like %s. Personality: %s; not very %s. Mood: %s.%s%s') % (
        b.name, COMPANY[b.company], b.level, ev, b.k['gear']['ship'].replace('ship_', '').replace('-', ' '), H.name(b.game_map), target, currency,
        ARCHETYPE_NAME.get(b.archetype, 'a normal player'), dominant, weak, _mood(b.mood),
        (' People: %s.' % ', '.join(relation)) if relation else '', (' Recently: %s.' % '; '.join(events)) if events else '') + lang_note(b) + \
        _memories_note(b, y) + AW.note(b, y.now if y is not None else None)


def _memories_note(b, y):
    """In strong mode the bot's most valuable memories (grudge, promise, friendship): so they affect decisions and reactions."""
    if not STRONG:
        return ''
    now = y.now if y is not None else b.hour()
    mems = MEM.important(b, now)
    return (' Strong memories: %s.' % '; '.join('%s (%s)' % (a['summary'], MEM.time_ago(now - a['t'])) for a in mems)) if mems else ''


def event_text(o):
    t = o['type']
    return {'death': 'got killed by %s' % (o.get('killer') or 'aliens'), 'i_killed_player': 'killed the player %s' % o.get('name'),
            'i_killed': 'killed the player %s' % o.get('victim'), 'level': 'reached level %s' % o.get('level'),
            'new_ship': 'bought a %s' % str(o.get('item', '')).replace('ship_', ''), 'quest_done': 'finished a quest',
            'clan_founded': 'founded the clan %s' % o.get('name'), 'joined_clan': 'joined the clan %s' % o.get('clan'),
            'joined_group': 'grouped up with %s' % o.get('name'), 'fled': 'fled from map %s' % o.get('map'),
            'i_killed_boss': 'killed the boss alien %s' % o.get('name'),
            'witness': ('saw %s kill the boss %s right next to you' % (o.get('who'), o.get('name')) if o.get('sub') == 'boss'
                      else 'saw %s get destroyed right next to you' % o.get('name'))}.get(t, '')


def _clean_name(name):
    return re.sub(r'[^A-Za-z ]', '', str(name)).strip()


def _map_aliens(m):
    names = []
    for v, n in sorted(K.map_npcs(m), key=lambda x: -x[1]):
        a = _clean_name(v['name'])
        if a and a not in names:
            names.append(a)
    return names[:4]


def game_info(f):
    """The model's game knowledge, for the player of company f (the asker's company: so the answer is right for them). Generated from the data
    (including the World Editor's changes)."""
    f = f if f in COMPANY else 1
    maps = [(f - 1) * 4 + i for i in range(1, 5)] + [16 + (f - 1) * 4 + i for i in range(1, 5)] + [13, 14, 15, 16, 29]
    row = ['%s: %s' % (H.name(m), ', '.join(a)) for m in maps for a in [[x for x in _map_aliens(m) if 'Boss' not in x]]
             if a]
    boss = ['%s (%s)' % (H.name(m), ', '.join(sorted({_clean_name(v['name']) for v, n in K.map_npcs(m) if 'Boss' in v['name']})[:3]))
              for m in maps if any('Boss' in v['name'] for v, n in K.map_npcs(m))]
    row.append('BOSS aliens are on ' + '; '.join(boss[:6]))
    return ('GAME FACTS for a %s player (use them, never invent): %s players start on %d-1, MMO starts on 1-1, EIC on 2-1, VRU on 3-1; '
            'every company has its own maps (MMO 1-x, EIC 2-x, VRU 3-x), other companies\' maps are enemy land. %s home maps: %d-1 '
            'to %d-4 for beginners, %d-5 to %d-8 later; 4-1 to 4-5 are shared PvP maps. Aliens: %s. Ships: phoenix (start) -> '
            'piranha, nostromo, bigboy (credits) -> leonov, vengeance, goliath (uridium). Lasers, weakest to strongest: LF-1, MP-1 (credits), LF-2, LF-3 '
            '(uridium). Quests come from the quest giver on your base map and give lots of EP; uridium comes from bonus boxes, quests '
            'and aliens. You level up by killing aliens and finishing quests.') % (
        COMPANY[f], COMPANY[f], f, COMPANY[f], f, f, f, f, '; '.join(row))


QUESTION = re.compile(r'\?\s*$|^\s*(how|what|where|why|who|when|which|can|could|anyone|any|is|are|do|does|did|should|wanna|u|you)\b', re.I)
GAME = re.compile(r'\b(map|alien|npc|streuner|lordakia|saimon|mordon|sibelon|boss|quest|ship|laser|lf|goliath|bigboy|phoenix|piranha|'
                  r'nostromo|vengeance|leonov|uri|uridium|credit|level|lvl|clan|group|ep|honor|drone|iris|flax|shield|gen|portal|'
                  r'gate|pvp|farm|start|begin|new|noob|mmo|eic|vru|[1-5]-[1-8x])(e?s)?\b', re.I)    # plurals too (bosses, maps)
KINDS = (
    ('congrats', re.compile(r'\b(gz|gratz|grats|congrats|congratulations|well done|nice one|nice|wp|good job|gj)\b', re.I)),
    ('thanks', re.compile(r'\b(ty|thx|thanks|thank you|tyvm)\b', re.I)),
    ('farewell', re.compile(r'\b(bye|cya|gn|good night|gtg|g2g|see ya|see you|later all)\b', re.I)),
    ('welcome_back', re.compile(r'^\s*(back|im back|i\'m back|re|bk)\b', re.I)),
    ('search', re.compile(r'\b(brb|afk|one sec|1 sec)\b', re.I)),
    ('roll_call', re.compile(r"\b(any(one|body)?|who'?s|who is)\b.*\b(online|on|here|around|alive|awake)\b", re.I)),
    ('challenge', re.compile(r'\b(duel|duels|1v1|1 v 1|1vs1|fight me|pvp me|come fight|who wants to fight)\b', re.I)),
    ('greeting', re.compile(r'^\s*(hi|hello|hey|yo|sup|hiya|howdy|morning|evening)\b', re.I)),
    ('taunt', re.compile(r'\b(noob|noobs|nub|trash|ez|loser|bad|suck|sucks|idiot|stupid|cry|crying|scrub|bot|bots|weak)\b', re.I)),
)


def TP_company(name):
    import community as TP
    k = TP.find(name=name)
    return int(k.profile.d['pilot'].get('factionId', 0)) if k is not None else 0


WHERE_QUESTION = re.compile(r'\b(where|which map|what map|map|maps|wo|nerede|hangi harita)\b', re.I)
MAP_SUFFIX = re.compile(r'\s*\b(for|on|in|at|from)\s+[1-5]-[1-8](\s*(,|/|and|or|&)\s*([1-5]-)?[1-8])*', re.I)


SHIPS = ('phoenix', 'liberator', 'piranha', 'nostromo', 'bigboy', 'leonov', 'vengeance', 'goliath', 'aegis', 'citadel', 'spearhead',
           'solace', 'diminisher', 'sentinel', 'spectrum', 'venom', 'cyborg', 'hammerclaw', 'berserker', 'tartarus', 'pusat')


def short_info(f):
    """Short and correct game knowledge for spontaneous chats (bot_sohbet, group remark, private whisper): the model made up ships and maps
    ("viking", "corsair"; an EIC bot called a VRU bot to 3-5 for a "new alien")."""
    f = f if f in COMPANY else 1
    return ('Facts (never invent other ships, maps or aliens): a %s pilot plays on %d-1 to %d-8, MMO maps are 1-x, EIC 2-x, VRU 3-x '
            '(the other companies\' maps are enemy land), 4-1 to 4-5 are shared PvP maps. Ships: %s.') % (
        COMPANY[f], f, f, ', '.join(SHIPS))


def foreign_map(b, text):
    """Whether the line talks about another company's map (in spontaneous chat: bots do not suggest a trip to an enemy map)."""
    return any(int(a) != b.company for a, _ in re.findall(r'\b([1-3])-([1-8])\b', str(text or '')))


def is_question(msg):
    return bool(QUESTION.search(msg))


def side(b, fac, name):
    """The pilot's side relative to the speaker (the small model mixed up companies: a VRU bot joined an EIC call "VRU ile savaşalım")."""
    if not fac:
        return ''
    if b.company == fac:
        return 'He is %s like %s: a teammate, he sides with %s.' % (COMPANY[b.company], name, COMPANY[b.company])
    return 'He is %s, %s is %s: on the rival side; he always sides with %s against %s.' % (
        COMPANY[b.company], name, COMPANY.get(fac, '?'), COMPANY[b.company], COMPANY.get(fac, '?'))


COMPANY_NO = {'mmo': 1, 'mars': 1, 'eic': 2, 'earth': 2, 'vru': 3, 'venus': 3}
COMPANY_NAME = re.compile(r'\b(mmo|eic|vru|mars|earth|venus)\b', re.I)


def company_note(msg, fac, candidate):
    """If companies are mentioned in the message (a call, boasting, a taunt) it writes explicitly how each side will react."""
    if not COMPANY_NAME.search(msg) or not fac:
        return ''
    friendly = [b.name for b in candidate if b.company == fac]
    enemy = [b.name for b in candidate if b.company != fac]
    out = ' The message is about the companies.'
    names = {COMPANY[COMPANY_NO[m.lower()]] for m in COMPANY_NAME.findall(msg)} - {COMPANY.get(fac)}
    if names and message_kind(msg) == 'taunt':
        out += ' It insults %s: %s pilots feel insulted and hit back at %s (never at their own company).' % (
            ' and '.join(sorted(names)), ' and '.join(sorted(names)), COMPANY.get(fac, '?'))
    if friendly:
        out += ' His teammates (%s) may agree with him.' % ', '.join(friendly)
    if enemy:
        out += (' Pilots of the other companies (%s) take it as coming from an enemy: they defend their own company, mock or '
                'threaten him back, and never agree to fight their own company.' % ', '.join(enemy))
    return out


def map_note(msg, fac):
    """An explicit note to the model if another company's map appears in the question (the small model answered "EIC'yim, 1-1'de nasıl başlarım" with 1-1)."""
    out = []
    for a, b_ in re.findall(r'\b([1-3])\s*-\s*([1-8])\b', msg):
        owner = int(a)
        if fac and owner != fac:
            out.append(' Note: %s-%s belongs to %s, it is enemy land for a %s player; %s players start on %d-1.' % (
                a, b_, COMPANY[owner], COMPANY.get(fac, '?'), COMPANY.get(fac, '?'), fac))
    return ''.join(out[:1])


_FILLER = {'i', 'u', 'you', 'a', 'the', 'is', 'it', 'to', 'and', 'on', 'in', 'for', 'of', 'lol', 're', 'm', 's', 'im', 'just', 'but'}


def _similar(a, b):
    """Whether two lines say the same thing: equal or most of their meaningful words in common (giving the same hint a second time)."""
    if a.lower() == b.lower():
        return True
    x = set(re.findall(r'[\w-]+', a.lower())) - _FILLER
    y = set(re.findall(r'[\w-]+', b.lower())) - _FILLER
    return len(x) >= 3 and len(y) >= 3 and len(x & y) / len(x | y) >= 0.55


def message_kind(msg):
    """The type of the player's message: for the reaction guide (REACTION). Requests (group, clan, friendship, come) are 'request': interaction.py
    decides ("who wants to group up?" used to count as a game question and got a map hint)."""
    n, _ = SPC.intent(msg)
    if n in IX.INTENTS and n != 'assist':
        return 'request'
    for name, rx in KINDS:
        if rx.search(msg):
            return name
    k = _normalize(msg)
    for name in ('congrats', 'farewell', 'roll_call', 'welcome_back'):             # other languages (bot/languages reaction)
        rx = _REACTION_LANG[name]
        if rx and rx.search(k) and (name != 'welcome_back' or (len(k.split()) <= 3 and not re.search(r'[1-5]\s*-\s*[1-8]', msg))):
            # ("2-3'e geldim" is not a return, it is an arrival)
            return name
    if n == 'thanks':
        return 'thanks'
    if n == 'insult':
        return 'taunt'
    if is_question(msg) or n == 'question':
        game = GAME.search(msg) or (_REACTION_LANG['game'] and _REACTION_LANG['game'].search(k))
        return 'question_game' if game else 'question_personal'
    if n == 'greeting':
        return 'greeting'
    return 'phrase'


REACTION = {
    'congrats': 'It congratulates someone. Only the congratulated pilot answers, with a short natural thanks (maybe one tiny '
               'detail); nobody else talks.',
    'thanks': 'It thanks someone. The thanked pilot may answer briefly (np, anytime ...) or nobody.',
    'farewell': 'Someone is leaving. 0-1 pilot says bye casually (like: gn, night man, cya, bye bye). Nothing else.',
    'welcome_back': 'HE (the writer) is back after a short break, not you. One pilot welcomes him back (wb, wb man ...); if he asks what he missed, that pilot says it in a few words '
             '(like: not much, same old, nothing really) - never repeat old answers.',
    'search': 'He goes away for a moment (brb / afk). Usually nobody answers; at most one says k or np.',
    'roll_call': 'He asks who is online. One or two pilots (of the company he names, if he names one) answer that they are here, '
               'in a few words (here, yo, yep whats up ...). No game tips.',
    'greeting': 'A greeting. 0-2 pilots greet back casually (like: hey, yo whats up, hi man, sup), maybe ask how it is going. No '
             'game advice.',
    'challenge': 'He challenges people to a fight / duel. Pilots of OTHER companies may accept or taunt back (name a map to meet '
              'only if it is enemy land for both or a 4-x map); his teammates may joke or cheer. Short, in character, no tips.',
    'taunt': 'It is a taunt or insult. If someone is targeted he reacts in character: hot-headed pilots trash talk back, calm '
               'ones laugh it off or ignore; short, no real hate.',
    'question_game': 'It is a question about the game. One pilot answers it correctly FOR THE ASKER (his company!) with concrete map or '
                 'alien names from the GAME FACTS, as a short tip (one or two names, never a long list); a second one may add a '
                 'small different tip. Answer exactly what was asked, no unrelated remarks. Mention a map only if he asks WHERE '
                 'something is (for "is X worth it" or "which is better" give an opinion, not maps).',
    'question_personal': 'It is a personal or random question (not about the game). Answer like a normal person chatting: short, honest '
                    'or jokey, from your own life (work, school, food, sleep, music, weather ...). Do not mention the game, maps or '
                    'your level at all.',
    'request': 'It is a request to the pilots (group, clan, friend, come over). Only the pilots told below answer, exactly with their '
             'decision.',
    'phrase': 'It is a statement. React naturally if it interests your pilot (agree, joke, disagree, ask back) or say nothing; at '
             'most 2 pilots.',
}


FALLBACK = {'welcome_back': ('wb', 'wb man', 'welcome back'), 'greeting': ('hey', 'yo', 'hi'), 'congrats': ('ty', 'thx', 'thanks man'),
         'roll_call': ('here', 'yo', 'yep'), 'question_personal': ('lol idk', 'haha', 'not telling :p'),
         'taunt': ('lol ok', 'cry more', 'says the guy in a phoenix', 'k')}     # if the model's reply gets caught by the filter


def shared_history(b, name):
    """The bot's history with that person: counts of events in memory ("dün birlikte gruplandık", "beni öldürmüştü"); in strong mode the memories and
    impression too."""
    return _numbers(b, name) + (MEM.text(b, name, b.hour()) if STRONG else '')


def _numbers(b, name):
    e = b.memory.d.get(str(name).lower())
    if not e:
        return ''
    out = []
    for kind, text in (('group', 'grouped up %d times'), ('hunted_together', 'farmed together %d times'),
                       ('i_helped', 'you helped him %d times'), ('helped_me', 'he helped you %d times'),
                       ('killed_me', 'he killed you %d times'), ('i_killed', 'you killed him %d times'),
                       ('challenge', 'he challenged you to a duel'), ('friend', 'you are friends'),
                       ('insult', 'he insulted you %d times'), ('chat', 'chatted %d times')):
        k = e['n'].get(kind, 0)
        if k:
            out.append(text % k if '%d' in text else text)
    return (' Your history with %s: %s.' % (e['name'], ', '.join(out[:5]))) if out else ''


def chat_history(y, channel=None, names=(), n=6, sec=180, exclude=None, route=None):
    """Context: the last n lines of the same channel (or of the people's whispers), from the last sec seconds; except the newest message (exclude). In strong
    mode three times the lines, four times the time (wide context). route: the room itself (company, clan, group channels are separate by company/clan/group:
    before, the MMO bot answered EIC's "geldim ne kaçırdım" in the company channel in its own channel; chat trial 2026-10-30)."""
    if STRONG:
        n, sec = n * 3, sec * 4
    names = {a.lower() for a in names}
    out = [x for x in y.history if y.now - x[0] <= sec and (x[2] == channel and (not route or len(x) < 5 or x[4] in (None, route)) if channel else
                                                          (str(x[2]).startswith('whisper') and (x[1].lower() in names or
                                                           any(a in str(x[2]).lower() for a in names))))]
    if exclude and out and out[-1][3] == exclude:
        out = out[:-1]
    return '\n'.join('%s: %s' % (x[1], x[3]) for x in out[-n:]) or '(nothing)'


def style(b):
    """The bot's writing style (from personality): so each pilot talks differently to the model."""
    o = b.traits
    rude = b.__dict__.get('rude', 1)                     # the pack's coarse chat setting (0 off ... 3 very harsh)
    if b.__dict__.get('moderator'):
        t = 'a calm chat moderator of the server, polite, keeps the chat clean'
    elif rude >= 2 and o['aggression'] > 0.75 - 0.15 * rude:
        t = 'toxic and provocative, trash talks other pilots and companies hard (still no slurs or real-life threats)'
    elif o['aggression'] > 0.7 and o['helpfulness'] < 0.4:
        t = 'a bit toxic and sarcastic, loves trash talk' if rude else 'competitive but always polite, never trash talks'
    elif o['talkativeness'] < 0.3:
        t = 'quiet, answers with very few words'
    elif o['sociability'] > 0.7:
        t = 'friendly and chatty, jokes a lot'
    elif o['helpfulness'] > 0.7:
        t = 'helpful, likes to give tips'
    elif o['rivalry'] > 0.7:
        t = 'tryhard and competitive, a little cocky'
    else:
        t = 'laid-back and casual'
    return t


def addressed_bots(y, channel, msg, listener):
    """The bot(s) the player is talking to: those named; if none, for "you/u", congratulation, thanks or a short reaction, the last bot that spoke in this channel
    a moment ago (90 s). General questions are not to anyone."""
    named = [b for b in listener if NS.is_mentioned(b.name, msg)]
    if named:
        return named
    last = [x for x in y.history[-15:] if x[2] == channel and y.now - x[0] < 90 and str(x[1]).lower() in y.name_index
           and (len(x) < 5 or not listener or x[1].lower() in {b.name.lower() for b in listener})]      # from those who hear that channel
    kind = message_kind(msg)
    if re.search(r'\b(guys|all|anyone|anybody|everyone|everybody|ppl|people|someone|somebody|yall|y\'all)\b', msg, re.I) \
            or COMPANY_NAME.search(msg) or kind == 'roll_call':
        return []                                            # to everyone or to a company ("MMO noobs" not to the last speaker)
    if last and (re.search(r'\b(you|u|your|ur|yours)\b', msg, re.I) or kind in ('congrats', 'thanks')
                or (len(msg.split()) <= 3 and kind not in ('question_game', 'greeting', 'farewell'))):
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
    """The opening topic of a chat between bots: from the bot's last event (if any) or a wide topic list (in game and out). In strong
    mode sometimes its memory about a player (gossip: listeners hear it, memories.hear_gossip)."""
    if STRONG:
        a = MEM.pick_gossip(b, y.now, b.r)
        if a is not None and b.r.random() < 0.4:
            b._gossip = a
            return 'he tells the others about the player %s (%s): "%s"' % (a['who'], MEM.time_ago(y.now - a['t']), a['summary'])
    last = [o for o in b.events[-5:] if o['type'] in ('death', 'level', 'new_ship', 'i_killed', 'quest_done', 'joined_clan')
           and y.now - o['t'] < 900]
    if last and b.r.random() < 0.4:
        return 'he mentions that he just %s' % event_text(last[-1])
    return 'he ' + b.r.choice(TOPICS)


class Brain:
    def __init__(self, y, log=print):
        self.y, self.log = y, log
        self.slot = int(y.setting('llm_batch', 4) or 4)
        global MULTILINGUAL, STRONG
        self.server = PRV.client(self.slot, log)              # the built-in model or the user's provider
        MULTILINGUAL = STRONG = not isinstance(self.server, LS.Server)
        self.ready = False
        self.queue = []
        self.counter = itertools.count()
        self.condition = threading.Condition()
        self.running = True
        self.last_bot_chat = time.time() + 60
        self.last_decision = 0.0
        self.last_event = 0.0
        self.stats = {'request': 0, 'error': 0, 'duration': 0.0, 'dropped': 0}
        self.muted = []             # model lines dropped by the filter
        self.conversations = {}             # strong mode: (bot, player) -> {b, name, start, last, n}: summarized into a memory when finished
        self.request_times = []           # the moments of all requests in the last hour (llm_hourly: chat, memory, decision, all)
        self.usage_trace = []           # [(moment, copy of the provider's token counter)] once a minute: the usage of the last hour
        self.last_follow = 0.0

    # ------------------------------------------------------------ lifecycle
    def launch(self):
        threading.Thread(target=self._open, name='llm-startup', daemon=True).start()

    def _open(self):
        for wait in (30, 60, 120, 240, 480, None):        # a transient error (429, 5xx, network) should not close the whole session on a single attempt
            try:
                self.server.launch()
                break
            except Exception as e:
                code = getattr(e, 'code', None)
                permanent = isinstance(self.server, LS.Server) or code is not None and 400 <= code < 500 and code not in (408, 429)   # local model, or the key/model is wrong
                if permanent or wait is None or not self.running:
                    self.log('   bots: language model could not be started, continuing like Normal mode: %s' % e)
                    return
                self.log('   bots: language model could not be started (%s), will retry in %d s' % (e, wait))
                time.sleep(wait)
        if not self.running:
            return
        self.ready = True
        for i in range(self.slot):
            threading.Thread(target=self._worker, name='llm-%d' % i, daemon=True).start()
        self.log('   bots: language model ready (%s, %d slots)' % (('port %d' % self.server.port) if self.server.port else self.server.name,
                                                               self.slot))

    def stop(self):
        self.running = False
        with self.condition:
            self.condition.notify_all()
        self.server.stop()

    # ------------------------------------------------------------ budget and usage
    def at_limit(self):
        """Whether the hourly request limit (llm_hourly; 0 unlimited) has been reached: if so no new job is taken (chat goes back to templates, decisions
        to the rule-based engine)."""
        if isinstance(self.server, LS.Server):
            return False                                   # the built-in model is free: the limit applies only to a remote provider
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < 3600]
        limit = self.y.setting('llm_hourly', 200) or 0
        return bool(limit) and len(self.request_times) >= limit

    def _usage_tick(self, now):
        if self.usage_trace and now - self.usage_trace[-1][0] < 60:
            return
        self.usage_trace.append((now, dict(getattr(self.server, 'usage', {}))))
        while len(self.usage_trace) > 1 and now - self.usage_trace[1][0] >= 3600:
            self.usage_trace.pop(0)

    def summary(self):
        """The panel's usage line (written to state.json): the requests and tokens of the last hour, the limit, the provider."""
        now = dict(getattr(self.server, 'usage', {}))
        once = self.usage_trace[0][1] if self.usage_trace else {}
        hour = {k: now.get(k, 0) - once.get(k, 0) for k in ('request', 'input', 'cache', 'output')}
        duration = (time.time() - self.usage_trace[0][0]) if self.usage_trace else 0
        return {'hour': hour, 'duration_min': round(duration / 60), 'total': now, 'cap': self.y.setting('llm_hourly', 200) or 0,
                'at_limit': self.at_limit(), 'provider': getattr(self.server, 'name', ''), 'ready': self.ready}

    def add(self, priority, job):
        if self.at_limit():
            self.stats['cap'] = self.stats.get('cap', 0) + 1
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
            if time.time() - job.get('t', time.time()) > 90:      # gone stale (the player has long forgotten)
                with self.y.lock:
                    for k in ('cancelled', 'backup'):              # the agent's wake-up reason back; a chat job answers with a template (so there is never no reply)
                        if job.get(k):
                            try:
                                job[k]()
                            except Exception:
                                self.log('   bots: could not take back the stale job:\n' + traceback.format_exc(limit=3))
                            break
                continue
            try:
                job['fn'](job)
            except Exception:
                self.stats['error'] += 1
                self.log('   bots: language model job failed:\n' + traceback.format_exc(limit=3))
                backup = job.get('backup')
                if backup:
                    with self.y.lock:
                        backup()

    def ask(self, user, schema, max_count=220, temperature=0.85, system=None):
        self.stats['request'] += 1
        self.request_times.append(time.time())
        system = (system or (SYSTEM_MULTI if MULTILINGUAL else SYSTEM_PROMPT)) + AW.system_note()      # while an admin is present (admin_warnings.py)
        if MULTILINGUAL and system.startswith((SYSTEM_PROMPT, SYSTEM_MULTI)):                # a reminder at the end: the model answered a player writing in English in English (Qwen3 trial)
            user += "\n\nEvery line is written ONLY in that pilot's own chat language ('Chats in ...'), whatever language others use."
        try:
            r, duration = self.server.ask(system, user, schema=schema, max_count=max_count, temperature=temperature)
        except ValueError:                                   # the reply was cut off at the limit or the JSON is broken: once more, calmer
            self.stats['regenerate'] = self.stats.get('regenerate', 0) + 1
            r, duration = self.server.ask(system, user, schema=schema, max_count=int(max_count * 1.5), temperature=0.6)
        self.stats['duration'] += duration
        return r

    # ------------------------------------------------------------ the manager's hooks
    def chat(self, y, g, now):
        """Whether the incoming message goes to the model (True) or to the templates."""
        if not self.ready or not y.setting('llm_chat', True) or not y.permission('chat'):
            return False
        if g[0] == 'whisper':
            b, msg, who = g[1], g[2], g[3]
            return self.add(WHISPER, {'t': now, 'fn': self._whisper, 'bot': b, 'msg': msg, 'who': who,
                                       'backup': lambda: y.template_whisper(b, msg, who, y.now)})
        route, msg, who = g[1], g[2], g[3]
        from .chat_engine import channel_name
        channel = channel_name(route)
        if channel is None or str(who.get('userId', '')).lower() in y.name_index:
            return True
        return self.add(ROOM, {'t': now, 'fn': self._room, 'channel': channel, 'msg': msg, 'who': who, 'route': route,
                               'backup': lambda: y.template_room(route, msg, who, y.now)})

    def event(self, y, b, o, now):
        """The bot's important moment: sometimes to the model (a short reaction), otherwise to the templates (False)."""
        if not self.ready or not y.setting('llm_chat', True) or o['type'] not in ('death', 'i_killed_player', 'new_ship', 'level',
                                                                                  'witness', 'i_killed_boss'):
            return False
        human = o.get('killer') or o.get('name')
        if o['type'] in ('death', 'i_killed_player') and (not human or str(human).lower() in y.name_index):
            return False
        if o['type'] == 'witness':
            human = None                                    # witness: to the company chat, not a whisper
        chance = 0.35 + 0.5 * b.o('talkativeness')
        if o['type'] in ('level', 'new_ship'):
            chance *= 0.3                                      # a real player does not announce every level
        if b.r.random() > chance or now - self.last_event < 20:
            return True                                     # stays silent this time (event reactions should not fill the chat)
        self.last_event = now
        return self.add(EVENT, {'t': now, 'fn': self._event, 'bot': b, 'incident': o})

    def mailer(self, y, b, r, k):
        """A model reply to mail sent to the bot (society.reply_mail) -> whether it entered the queue (if not, a template)."""
        if not y.setting('llm_chat', True):
            return False
        return self.add(MAIL, {'t': y.now, 'fn': self._mail, 'bot': b, 'mailer': r, 'decision': k})

    def special(self, y, b, name, purpose):
        """The bot's spontaneous whisper to the player (chat_engine.start_private) -> whether it entered the queue."""
        if not y.setting('llm_chat', True):
            return False
        return self.add(EVENT, {'t': y.now, 'fn': self._private, 'bot': b, 'name': name, 'purpose': purpose})

    def group_banter_line(self, y, b, name):
        if not y.setting('llm_chat', True):
            return False
        return self.add(EVENT, {'t': y.now, 'fn': self._group_talk, 'bot': b, 'name': name})

    def tick(self, now):
        """From the manager's tick: chat between bots and strategic decisions (rare, when the queue is empty)."""
        self._usage_tick(now)
        if not self.ready or len(self.queue) > self.slot:
            return
        y = self.y
        is_open = [b for b in y.bots if b.online and b.dead_until <= now]
        human_wrote = any(now - x[0] < 60 and str(x[1]).lower() not in y.name_index for x in y.history[-10:])
        if y.setting('llm_chat', True) and y.permission('chat') and now >= self.last_bot_chat and len(is_open) >= 2 and not human_wrote:
            self.last_bot_chat = now + 120 + 240 * (1 - min(1.0, len(is_open) / 30))
            self.add(BOT_CHAT, {'t': now, 'fn': self._bot_chat})
        if STRONG:
            self._memories_tick(y, now)
            if y.setting('llm_agent', True):
                self._agent_tick(y, now, is_open)              # the tool loop (agent.py) in place of the single-step decision
                return
        minutes = y.setting('llm_decision_min', 10) or 0
        if minutes and now - self.last_decision >= 20:
            # those on the player's map (in sight) think twice as often
            order = [b for b in is_open if now - getattr(b, '_llm_decision', 0) >= minutes * 60 * (0.5 if b.body is not None else 1.0)]
            if order:
                self.last_decision = now
                sec = sorted(order, key=lambda b: getattr(b, '_llm_decision', 0))[:3]
                for b in sec:
                    b._llm_decision = now
                self.add(DECISION, {'t': now, 'fn': self._decision, 'bots': sec})

    # ------------------------------------------------------------ jobs
    def _whisper(self, job):
        y, b, msg, who = self.y, job['bot'], job['msg'], job['who']
        name = who.get('userId', '')
        fac = int(who.get('factionId') or 0) or b.company
        schema = {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 90}}, 'required': ['text']}
        rel = b.memory.relation(name)
        # The decision on a request (group, help) is made by the personality-based decision engine, which carries out the action; the model only says the decision in the bot's voice.
        # The small model said "olur" and forgot the invite (live 2026-10-29): this way word and action always agree.
        intent, game_map = SPC.intent(msg)
        bid = IX.offer_reply(b, name, msg, y.now)       # "gruplaşalım mı?" -> "sure": a group request
        if bid:
            intent = bid
        kind = 'request' if bid else message_kind(msg)
        decision = ''
        with y.lock:
            if intent in IX.INTENTS and intent != 'assist':
                dec = IX.decision(y, b, intent, name, who, game_map, msg, y.now)
                if dec is not None:
                    decision = dec['not']
                    job['decision'] = dec
            elif intent == 'assist':
                incoming = y.help_call(name, who, game_map, [b], 'company', y.now, silent=True)
                decision = ('You decided to HELP: you are flying to him now. Say it in your own words.' if incoming else
                         'You decided NOT to help (too far, too weak or busy). Say it in your own words.')
        k = ('%sYou are %s. %s Your style: %s.\nYou feel %s about %s (a %s player).\n\nEarlier private messages (context only, '
             'maybe already answered):\n%s\n\nNEWEST private message from %s: "%s"\n\n%s %s Reply ONLY to this newest message with '
             'one short line (text), like a real person. Never echo his words.') % (
            (game_info(fac) + '\n\n') if kind == 'question_game' else '', b.name, chat_persona(b, y), style(b),
            'friendly' if rel > 0.2 else 'annoyed' if rel < -0.2 else 'neutral', name + shared_history(b, name),
            COMPANY.get(fac, '?'), chat_history(y, names=[b.name, name], exclude=msg, n=10, sec=1800), name, msg,
            '' if decision else REACTION.get(kind, ''), decision)
        r = self.ask(k, schema, temperature=0.6)
        with y.lock:
            b.memory.event(name, 'chat', y.now)
            text = self._text(b, r.get('text'), echo=msg)
            if text:
                y.speak(b, 'whisper', text, recipient=name, now=y.now, priority=True)
            self._spoke(b, name, y.now)
            if job.get('decision'):
                IX.apply(y, b, job['decision'], delay=SPC.typing_time(text or 'ok', b) + b.r.uniform(1, 3))

    def _room(self, job):
        y, channel, msg, who = self.y, job['channel'], job['msg'], job['who']
        name = who.get('userId', '')
        fac = int(who.get('factionId') or 0)
        intent, game_map = SPC.intent(msg)
        kind = message_kind(msg)
        with y.lock:
            listener = y.listeners(channel, who)
            addressed = addressed_bots(y, channel, msg, listener)
            if not addressed and _ONE_WORD.match(msg) and (not listener or listener[0].r.random() < 0.85):
                return                                   # a "gg", "lol", "xd" written to no one: often unanswered in real chat
                                                         # (so "gg" is not answered with "o senin iyi oynadığın içindi"; chat trial 2026-10-30)
            extra = sorted([b for b in listener if b not in addressed], key=lambda b: -b.o('talkativeness') * b.r.random())[:5 - len(addressed)]
            candidate = (addressed + extra)[:5]
            # a call for help: the decision engine chooses who will go (personality, power, route) and sends them; the model makes those who go say it
            responders = y.help_call(name, who, game_map, listener, channel, y.now, silent=True) if intent == 'assist' else []
            candidate = (responders + [b for b in candidate if b not in responders])[:5]
            decisions = []                                # a request (group, clan, friend, come): who decided what
            if kind == 'request':
                if addressed:
                    decisions = [(b, IX.decision(y, b, intent, name, who, game_map, msg, y.now)) for b in addressed[:1]]
                elif intent in ('group', 'clan', 'quest', 'duel', 'special', 'gate'):
                    decisions = [(b, b.__dict__.pop('_request_decision', None) or IX.decision(y, b, intent, name, who, game_map, msg, y.now))
                                for b in y.open_call(intent, name, who, game_map, msg, listener, y.now)]
                elif intent == 'followup' and channel == 'group':      # "follow me / come 2-4" in a group chat: the group's bots
                    decisions = [(b, IX.decision(y, b, intent, name, who, game_map, msg, y.now)) for b in listener[:3]]
                decisions = [(b, dec) for b, dec in decisions if dec is not None]
                if not decisions and intent == 'duel':
                    kind = 'challenge'                       # nobody accepted: banter (REACTION 'challenge')
                elif not decisions:
                    return                               # nobody took it on: silence, as in real chat
                for b, dec in decisions:
                    IX.apply(y, b, dec, delay=b.r.uniform(6, 12))     # after writing the reply (model ~2 s + typing)
                candidate = [b for b, _ in decisions] or candidate
            m = COMPANY_NAME.search(msg) if kind == 'roll_call' else None
            if m:                                        # "any eic online?": only that company's pilots say "buradayım"
                f = COMPANY_NO[m.group(1).lower()]
                candidate = [b for b in listener if b.company == f][:3]
            elif fac and not addressed and COMPANY_NAME.search(msg):
                # another company is mentioned ("MMO noobs", "VRU is the best"): that company's pilots and a teammate react
                mentioned = {COMPANY_NO[x.lower()] for x in COMPANY_NAME.findall(msg)} - {fac}
                to_them = [b for b in candidate if b.company in mentioned] + [b for b in listener if b.company in mentioned and b not in candidate]
                candidate = (to_them[:2] + [b for b in candidate if b.company == fac][:1]) or candidate
            history = chat_history(y, channel, exclude=msg, route=job.get('route'))
        if not candidate:
            return
        # who can answer: the one addressed (only them), those going to help, otherwise at most two pilots
        responder = responders or (candidate if decisions else None) or addressed or candidate
        max_count = min(3, len(responders)) if responders else len(decisions) if decisions else len(addressed) if addressed else \
            1 if kind in ('farewell', 'thanks', 'welcome_back', 'search') else 2
        min_value = 1 if (responders or decisions or addressed or kind in ('question_game', 'question_personal', 'welcome_back', 'greeting', 'roll_call')) else 0
        schema = {'type': 'object', 'properties': {'replies': {'type': 'array', 'minItems': min_value, 'maxItems': max_count, 'items': {
            'type': 'object', 'properties': {'bot': {'type': 'string', 'enum': [b.name for b in responder]},
                                             'text': {'type': 'string', 'maxLength': 90}},
            'required': ['bot', 'text']}}}, 'required': ['replies']}
        if responders:
            m = H.name(responders[0].k['intent']['plan']['map']) if (responders[0].k.get('intent') or {}).get('plan') else 'there'
            rule = ('These pilots decided to fly to %s to fight the enemy players (not aliens) attacking %s; each says in his own '
                     'words and his own chat language that he is coming: %s.') % (m, name, ', '.join(b.name for b in responders))
        elif intent == 'assist':
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
            (game_info(fac or candidate[0].company) + '\n\n') if kind == 'question_game' else '', CHANNEL.get(channel, channel),
            ' (they are all in the same group as %s: his teammates right now)' % name if channel == 'group' else '',
            '\n'.join('- %s Style: %s. %s%s' % (chat_persona(b, y), style(b), side(b, fac, name),
                                              MEM.text(b, name, y.now) if STRONG else '') for b in candidate), history, name,
            COMPANY.get(fac, '?'), msg, rule + company_note(msg, fac, candidate))
        r = self.ask(k, schema, max_count=320, temperature=0.65 if kind.startswith('question') or addressed else 0.85)
        with y.lock:
            order = 0
            for x in (r.get('replies') or [])[:3]:
                b = y.name_index.get(str(x.get('bot', '')).lower())
                text = x.get('text')
                if kind == 'question_game' and not WHERE_QUESTION.search(msg):
                    text = MAP_SUFFIX.sub('', str(text or ''))   # "is goliath worth it" -> "...worth it" (the small model added a map)
                text = self._text(b, text, echo=msg) if b is not None else ''
                if b is None or not b.online or not text:
                    continue
                b.memory.event(name, 'praise' if kind == 'congrats' else 'insult' if kind == 'taunt' and addressed else 'chat', y.now)
                is_whisper = any(kb is b and dec.get('whisper') for kb, dec in decisions)
                y.speak(b, 'whisper' if is_whisper else channel, text, recipient=name if is_whisper else None, now=y.now + order * b.r.uniform(2, 6),
                        priority=True)
                if addressed or decisions or responders:
                    self._spoke(b, name, y.now)              # direct conversation (not a general reply): summarized into a memory at the end
                order += 1
            backup = FALLBACK.get(kind)
            # a reply was needed but all were caught by the filter: a short natural response (the fallbacks are English)
            if not order and min_value and backup and not responders and (not MULTILINGUAL or SPC.lang(responder[0]) == 'en'):
                b = responder[0]
                y.speak(b, channel, b.r.choice(backup), now=y.now, priority=True)

    def _event(self, job):
        y, b, o = self.y, job['bot'], job['incident']
        schema = {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 90},
                                                 'channel': {'type': 'string', 'enum': ['whisper', 'company', 'global', 'none']}},
                'required': ['text', 'channel']}
        who = o.get('killer') or o.get('name') or ''
        k = ('You are %s.\n%s\nThis just happened: you %s.\nDo you type something about it? channel: whisper = private message to %s, '
             'company = company chat, global = global chat, none = say nothing (often the most realistic). text: one short line.') % (
            b.name, persona(b, y), event_text(o), who or '-')
        r = self.ask(k, schema, max_count=80)
        channel = r.get('channel')
        text = self._text(b, r.get('text'))
        if channel == 'none' or not text or (channel == 'whisper' and not who):
            return
        with y.lock:
            y.speak(b, channel, text, recipient=who if channel == 'whisper' else None, now=y.now)

    def _mail(self, job):
        y, b, r, dec = self.y, job['bot'], job['mailer'], job.get('decision')
        name = r['sender']
        schema = {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 240}}, 'required': ['text']}
        contents = '%s %s' % (r.get('subject', ''), r.get('text', ''))
        game = message_kind(contents) == 'question_game' or (is_question(contents) and GAME.search(contents))
        fac = int(TP_company(name) or b.company)
        # (the boolean "yanıtla" field was removed: the model took a refusal for "do not reply" and dropped the good text too)
        k = ('%sYou are %s. %s Your style: %s.\nYou feel %s about %s.\n\n%s sent you an in-game MAIL.\nSubject: "%s"\nText: "%s"\n\n%s'
             'Write your answer mail (text): 1-3 short casual sentences (at least 6 words; give a reason if you say no), like a '
             'gamer writing a quick mail, no greeting formulas like "Dear", no signature. Real players answer personal mails; only '
             'for spam or nonsense leave text empty.') % (
            (game_info(fac) + '\n\n') if game else '', b.name, chat_persona(b, y), style(b),
            'friendly' if b.memory.relation(name) > 0.2 else 'neutral', name + shared_history(b, name), name, str(r.get('subject', ''))[:60],
            str(r.get('text', ''))[:600],
            (dec['not'] + ' ') if dec else '')
        x = self.ask(k, schema, max_count=160, temperature=0.7)
        text = ' '.join(str(x.get('text') or '').split())
        if len(text.split()) < 4 or (not MULTILINGUAL and _FOREIGN.search(text)) or harmful(text):
            if not dec:
                return
            from . import society
            text = society.mail_template(b, dec)                # if there is a decision it does not stay silent
            if not text:
                return
        with y.lock:
            TL.call(y, b, 'send_mail', {'name': name, 'subject': 'Re: ' + str(r.get('subject', ''))[:46], 'text': text})

    def _private(self, job):
        y, b, name, purpose = self.y, job['bot'], job['name'], job['purpose']
        ne = {'private_greeting': 'he just came online: greet him (a short wb / hey)',
              'private_group': 'you want to group up with him: ask him (you are on %s doing %s)' % (
                  H.name(b.game_map), GOAL_NAME.get(b.target.name, 'farming aliens') if b.target is not None else 'farming aliens'),
              'private_chat': 'you just feel like chatting: ask him something casual (how it goes, his gear, his plans)'}[purpose]
        schema = {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 80}}, 'required': ['text']}
        k = ('You are %s. %s Your style: %s.\nYou are friends with %s.%s\n\nEarlier private messages:\n%s\n\nYou start a private '
             'chat with him: %s. One short line (text), like a real friend in a game, not a status report. %s') % (
            b.name, chat_persona(b, y), style(b), name, shared_history(b, name), chat_history(y, names=[b.name, name], n=6, sec=3600), ne,
            short_info(b.company))
        r = self.ask(k, schema, max_count=60, temperature=0.85)
        with y.lock:
            text = r.get('text') if not foreign_map(b, r.get('text')) else ''
            text = self._text(b, text) or SPC.template(b, purpose, name=name, map=H.name(b.game_map))
            y.speak(b, 'whisper', text, recipient=name, now=y.now)

    def _group_talk(self, job):
        y, b, name = self.y, job['bot'], job['name']
        schema = {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 80}}, 'required': ['text']}
        k = ('You are %s. %s Your style: %s.\nYou are in a group with %s, playing together right now.%s\n\nRecent group chat:\n%s\n\n'
             'Write one short line in the group chat to him, like a real teammate: where to go next, a quick comment on the '
             'farming or a boss, a joke, a short question. Not a status report, nothing already said. %s') % (
            b.name, chat_persona(b, y), style(b), name, shared_history(b, name), chat_history(y, 'group', n=6, sec=900), short_info(b.company))
        r = self.ask(k, schema, max_count=60, temperature=0.9)
        with y.lock:
            text = self._text(b, r.get('text')) if not foreign_map(b, r.get('text')) else ''
            if text:
                y.speak(b, 'group', text, now=y.now)

    def _bot_chat(self, job):
        from .chat_engine import channel_path
        y = self.y
        with y.lock:
            is_open = [b for b in y.bots if b.online and b.dead_until <= y.now]
            if len(is_open) < 2:
                return
            r0 = is_open[0].r
            channel = 'global' if r0.random() < 0.3 and len({b.company for b in is_open}) > 1 else 'company'
            if channel == 'global':                         # global: from different companies, banter between companies is normal
                companies = r0.sample(sorted({b.company for b in is_open}), 2)
                group = [max((b for b in is_open if b.company == f), key=lambda b: b.o('talkativeness') * b.r.random()) for f in companies]
                group += sorted([b for b in is_open if b not in group], key=lambda b: -b.o('talkativeness') * b.r.random())[:1]
            else:
                fac = r0.choice([1, 2, 3])
                group = [b for b in is_open if b.company == fac] or is_open
                group = sorted(group, key=lambda b: -b.o('talkativeness') * b.r.random())[:3]
            if len(group) < 2:
                return
            group[0].__dict__.pop('_gossip', None)
            topic = pick_topic(group[0], y)
        schema = {'type': 'object', 'properties': {'lines': {'type': 'array', 'minItems': 2, 'maxItems': 5, 'items': {
            'type': 'object', 'properties': {'bot': {'type': 'string', 'enum': [b.name for b in group]}, 'text': {'type': 'string', 'maxLength': 90}},
            'required': ['bot', 'text']}}}, 'required': ['lines']}
        k = ('%s\n\nThese pilots are in the %s chat%s:\n%s\n\nLast lines in the chat (do NOT continue or repeat these, '
             'they are old):\n%s\n\nWrite a NEW short natural exchange between them (2-5 lines, a few words each). %s starts it: %s. '
             'The others react to what was actually said (answer, joke, disagree, ask back) - a real back-and-forth in their own '
             'styles, not separate statements. Never status reports.') % (
            short_info(group[0].company) if channel == 'company' else short_info(0).split(': a ')[0] + ': MMO maps are 1-x, EIC 2-x, VRU '
                                                                   '3-x, 4-x are shared PvP maps. Ships: ' + ', '.join(SHIPS) + '.',
            'same company' if channel == 'company' else 'global',
            '' if channel == 'company' else ' (players of rival companies: light banter between companies is normal, everyone stays '
                                        'loyal to his own)',
            '\n'.join('- %s Style: %s.' % (chat_persona(b, y), style(b)) for b in group),
            chat_history(y, channel, n=4, sec=120, route=channel_path(group[0], channel)), group[0].name, topic)
        r = self.ask(k, schema, max_count=320, temperature=0.95)
        with y.lock:
            t = y.now
            for x in r.get('lines') or []:
                b = y.name_index.get(str(x.get('bot', '')).lower())
                text = self._text(b, x.get('text')) if b is not None else ''
                if b is None or not b.online or not text or (channel == 'company' and foreign_map(b, text)):
                    continue
                t += b.r.uniform(4, 14)
                y.speak(b, channel, text, now=t)
            a = group[0].__dict__.pop('_gossip', None)
            if a is not None and t > y.now:                  # told: the listeners heard (the player's reputation spreads)
                for d in group[1:]:
                    MEM.hear_gossip(d, group[0], a, y.now)

    def _decision(self, job):
        """Strategic decision (writes no chat: the model turned the "söz"s here into status reports; chat is in bot_chat)."""
        y = self.y
        bots = [b for b in job['bots'] if b.online]
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
        schema = {'type': 'object', 'properties': {'decisions': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'bot': {'type': 'string', 'enum': [b.name for b in bots]}, 'target': {'type': 'string', 'enum': list(DECISION_GOALS)},
            'map': {'type': 'string', 'maxLength': 8}}, 'required': ['bot', 'target', 'map']}}}, 'required': ['decisions']}
        k = ('For each pilot choose what he does in the next 10-20 minutes (grinding = farm aliens, quest = quests, pvp = hunt enemy '
             'players, shopping = buy upgrades, resting = take a break at base), realistically for his personality, mood and recent '
             'events (the scores are gut feelings, not orders). For grinding put one of his listed maps in map, otherwise leave it '
             'empty.\n\n%s') % '\n'.join(lines)
        r = self.ask(k, schema, max_count=240, temperature=0.7)
        with y.lock:
            for x in r.get('decisions') or []:
                b = y.name_index.get(str(x.get('bot', '')).lower())
                if b is None or not b.online:
                    continue
                tool = {'grinding': 'hunt_npcs', 'quest': 'do_quest', 'pvp': 'hunt_pvp', 'shopping': 'go_shopping',
                        'resting': 'rest'}.get(x.get('target'))
                if tool:
                    TL.call(y, b, tool, {'map': x.get('map')} if tool == 'hunt_npcs' and x.get('map') else {})

    # ------------------------------------------------------------ agent (strong mode; agent.py)
    def _nearby(self, y, now):
        """Bots close to the player's world (level of detail): those on its map or on the same map as the player, with a relationship with the player, a memory
        or an ongoing conversation. These think at full frequency and on events; the others rarely (the rule-based engine plays them, the player
        does not notice the difference). 30 s cache."""
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
                       or any(a['who'].lower() in names for a in b.k.get('memories') or ())}
        self._nearby_time = now
        return self._near

    def _agent_tick(self, y, now, is_open):
        """Who should think: an event, a reminder or time (llm_decision_min; those on the player's map twice as often, bots far from the player
        four times as rarely and without events). At most two bots in five seconds; once the hourly request limit (llm_hourly) is exceeded the rule-based engine
        continues."""
        if now - self.last_decision < 5:
            return
        self.last_decision = now
        if self.at_limit():
            return
        minutes = y.setting('llm_decision_min', 10) or 0
        nearby = self._nearby(y, now)
        n = 0
        for b in is_open:
            if now - b.__dict__.get('_agent_busy', 0) < 180:
                continue                                   # thinking
            if '_llm_decision' not in b.__dict__:               # so the first thinking moments are spread out (not all thinking at once at start)
                b._llm_decision = now - b.r.uniform(0, 0.8) * minutes * 60
            far = id(b) not in nearby
            refund = AGT.wake_state(b)                    # if the job cannot enter the queue or goes stale, the reason should not be lost
            reason = AGT.wakers(y, b, now, events=not far)
            multiplier = 0.5 if b.body is not None else 4.0 if far else 1.0
            # (a bot that set itself a reminder has chosen when to think: it does not also think periodically)
            if not reason and minutes and not b.k.get('reminder') and now - b._llm_decision >= minutes * 60 * multiplier:
                reason = 'time to look at how things are going and decide what to do next'
            if not reason:
                continue
            b._llm_decision = b._agent_busy = now
            if not self.add(DECISION, {'t': now, 'fn': self._agent, 'bot': b, 'reason': reason, 'cancelled': refund}):
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
                AGT.think(self, b, job['reason'], int(y.setting('llm_agent_steps', AGT.STEPS) or AGT.STEPS))
        finally:
            b._agent_busy = 0

    # ------------------------------------------------------------ memories (strong mode; memories.py)
    def _spoke(self, b, name, now):
        """A bot talked directly with a player: when the conversation is silent for 150 s it is summarized into a memory (_memory_summary)."""
        if not STRONG or not name or str(name).lower() in self.y.name_index:
            return
        e = self.conversations.setdefault((b.name.lower(), str(name).lower()), {'b': b, 'name': str(name), 'start': now, 'n': 0})
        e['last'] = now
        e['n'] += 1

    def _memories_tick(self, y, now):
        for key, e in list(self.conversations.items()):
            if now - e['last'] >= 150:
                del self.conversations[key]
                self.add(EVENT, {'t': now, 'fn': self._memory_summary, 'bot': e['b'], 'name': e['name'], 'start': e['start']})
        if now - self.last_follow < 20:
            return
        self.last_follow = now
        is_open = {k.name.lower() for k in y.online_humans()}
        for b, a in MEM.due_followups(y, now, is_open)[:2]:
            if self.add(EVENT, {'t': now, 'fn': self._follow, 'bot': b, 'memory_log': a}):
                a['followup']['finished'] = True                   # once (the job entered the queue)

    def _memory_summary(self, job):
        """A finished conversation -> the bot's memory (one sentence), the impression of the person and, if any, its consequence (follow-up)."""
        y, b, name = self.y, job['bot'], job['name']
        lower = {b.name.lower(), name.lower()}
        with y.lock:
            lines = [x for x in y.history if x[0] >= job['start'] - 120 and str(x[1]).lower() in lower and (
                not str(x[2]).startswith('whisper') or str(x[2]).split(':', 1)[-1].lower() in lower)]
            dump = '\n'.join('%s%s: %s' % (x[1], ' (private)' if str(x[2]).startswith('whisper') else ' (%s chat)' % x[2], x[3])
                              for x in lines[-40:])
            once = shared_history(b, name)
            who = persona(b, y)
        if not dump:
            return
        schema = {'type': 'object', 'properties': {
            'save': {'type': 'boolean'}, 'summary': {'type': 'string', 'maxLength': 200},
            'emotion': {'type': 'number'}, 'importance': {'type': 'integer', 'enum': [1, 2, 3]}, 'impression': {'type': 'string', 'maxLength': 240},
            'followup': {'type': 'object', 'properties': {
                'purpose': {'type': 'string', 'enum': ['none'] + list(MEM.PURPOSES)}, 'minutes': {'type': 'integer'},
                'tool': {'type': 'string', 'enum': list(MEM.FOLLOWUP_TOOLS)}, 'map': {'type': 'string', 'maxLength': 8}},
                'required': ['purpose', 'minutes', 'tool', 'map']}},
            'required': ['save', 'summary', 'emotion', 'importance', 'impression', 'followup']}
        k = ('You are %s.\n%s\nWhat you already knew about %s:%s\n\nThis conversation with %s just ended:\n%s\n\nWrite a private '
             'note for your own memory, always in English. save: false if it was only small talk with nothing worth remembering. '
             'summary: ONE short concrete sentence, first person (what happened, what was said or agreed, places, times), like "%s '
             'asked me how to farm on 2-3, I promised to show him later". emotion: how you feel about %s now, from -1 (hate) to 1 '
             '(really like). importance: 1 small, 2 notable, 3 big. impression: your overall impression of %s in one sentence, from '
             'everything you know (update the old one). followup: only if something is left to do later, else purpose none: promise = a '
             'plan or promise you both agreed on (meet, duel, group up, help), revenge = you want to get back at him, thanks = '
             'you want to thank him later, rivalry = a rivalry to continue, curiosity = you want to ask him something later. minutes: '
             'in how many minutes it should happen (from what was said; 10 if nothing was said). tool: what you do then: duel = '
             'fight him, group_invite = invite him to your group, follow = fly to his map, go_help = help him on his map, none = '
             'only write to him. map: the agreed map (like 4-4) or empty.') % (b.name, who, name, once or ' nothing', name, dump, name,
                                                                             name, name)
        r = self.ask(k, schema, max_count=240, temperature=0.4)
        with y.lock:
            MEM.write_impression(b, name, r.get('impression'), y.now)
            summary = ' '.join(str(r.get('summary') or '').split())
            if not r.get('save') or not summary:
                return
            t = r.get('followup') or {}
            try:
                emotion, importance = float(r.get('emotion') or 0), int(r.get('importance') or 1)
                tk = MEM.set_followup(t.get('purpose'), y.now, int(t.get('minutes') or 10), t.get('tool'), t.get('map'))
            except (TypeError, ValueError):
                emotion, importance, tk = 0.0, 1, None
            MEM.add(b, name, summary, 'speech', emotion, importance, y.now, followup=tk, merge=False)

    def _follow(self, job):
        """A memory's consequence: the bot writes the player a whisper that brings up the subject, and acts if needed (duel, invite, follow, help)."""
        y, b, a = self.y, job['bot'], job['memory_log']
        t, name = a['followup'], a['who']
        ne = {'promise': 'follow up on what you two agreed, now it is time', 'revenge': 'you are coming for revenge: tell him so (short '
              'trash talk, in character, no real hate)', 'thanks': 'thank him for it, casually', 'rivalry': 'poke him about your '
              'rivalry', 'curiosity': 'ask him what you wanted to ask'}[t['purpose']]
        game_map = t.get('map') or ''
        if t['tool'] in ('duel', 'go_help', 'follow') and not game_map:
            import community as TP
            person = TP.find(name=name)
            game_map = H.name(int(person.profile.d['position'].get('mapId', 0))) if person is not None else ''
        tool = t['tool']
        if tool in ('duel', 'go_help', 'follow'):     # should not say "geliyorum" to a place it cannot reach (live: the MMO bot to EIC's 2-1)
            m = TL._game_map(game_map) if game_map else None
            if m is None or not K.can_enter(m, b.company, b.level) or not K.route(b.game_map, m, b.company, b.level):
                tool = 'none'
                ne += ('. He is on %s right now, where you cannot get to him: say you will deal with it another time (or ask him '
                       'to come somewhere you both can go)' % (game_map or 'an unknown map'))
        action = {'duel': 'You are flying to %s to fight him right now.' % game_map, 'group_invite': 'You are inviting him to your '
                 'group right now.', 'follow': 'You are flying to his map %s right now.' % game_map, 'go_help': 'You are '
                 'coming to help him on %s right now.' % game_map, 'none': ''}.get(tool, '')
        schema = {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 90}}, 'required': ['text']}
        with y.lock:
            k = ('You are %s. %s Your style: %s.\nAbout %s:%s\n\nEarlier private messages:\n%s\n\nYou start a private chat with %s '
                 'because of this memory: "%s" (%s). Purpose: %s. %s One short line (text), like a real player who remembers him; '
                 'mention the memory naturally, not word for word.') % (
                b.name, chat_persona(b, y), style(b), name, shared_history(b, name), chat_history(y, names=[b.name, name], n=10, sec=7200),
                name, a['summary'], MEM.time_ago(y.now - a['t']), ne, action)
        r = self.ask(k, schema, max_count=80, temperature=0.8)
        with y.lock:
            text = self._text(b, r.get('text'))
            if text:
                y.speak(b, 'whisper', text, recipient=name, now=y.now)
            if tool != 'none':
                arg = {'name': name}
                if tool in ('duel', 'go_help') and game_map:
                    arg['map'] = game_map
                y.actions.append((y.now + SPC.typing_time(text or 'ok', b) + b.r.uniform(1, 3), b, (tool, arg)))
            t['result'] = text or ''

    # ------------------------------------------------------------ helpers
    def _text(self, b, text, echo=None):
        out = self._filter_text(b, text, echo)
        if not out and str(text or '').strip():
            self.muted.append(str(text)[:80])      # diagnostics (tools/bot_chat_trial.py)
            del self.muted[:-50]
        return out

    def _filter_text(self, b, text, echo=None):
        """The model's line -> text that goes to chat, or '' (silent if empty, a numeric status report or not English). Only the light part of the style
        is applied (lowercase, abbreviation, rare typo); no capitals or emoji are added."""
        text = ' '.join(str(text or '').split())[:140]
        text = re.sub(r'''[\s'"}\]{\[,]+$''', '', re.sub(r'''^[\s'"{\[]+''', '', text))     # JSON residue ('} ...)
        if not MULTILINGUAL and _FOREIGN.search(text):
            return ''
        if MULTILINGUAL and is_english(text, SPC.lang(b)):
            return ''                                        # a Turkish-speaking bot wrote in English (player report 2026-10-30)
        text = ' '.join((_EMOJI if MULTILINGUAL else _SYMBOL).sub('', text).split())
        if not text or re.search(r'\d{3,}\s*(k\b|credits?|cr\b|uri\b|uridium|ep\b|exp\b|xp\b|honou?r|power|hp\b|dmg|damage)|'
                                  r'\b(credits?|uridium|uri|ep|honou?r|power)\s*:?\s*\d{3,}', text, re.I):
            return ''                                        # status numbers (numbers like age, year are free)
        if re.search(r'\b(mood|personality|plays like|not very|own company maps|pilot, level|game facts|newest message)\b', text, re.I):
            return ''                                        # the model pouring the bot's description or the prompt's words into chat
        if len(text.split()) > 16:
            return ''                                        # nobody writes paragraphs in chat
        if '_' in text and any(a in text for a in TL.TOOLS) or re.search(r'\b(assist|assistance|how can i help)\b', text, re.I):
            return ''                                        # a tool name or assistant language
        if harmful(text):
            return ''                                        # self-harm, death wish, heavy insults: in-game banter has none of these
        if _LEVEL_ANNOUNCE.search(text) and not (echo and re.search(r'seviye|level|lvl|ka[çc]', str(echo), re.I)):
            if b.__dict__.get('_level_announce') == b.level or b.level < 6:
                return ''                                    # already announced this level (event reaction + agent: "lv2 oldum" twice); nobody announces the first
                #                                              levels (in a fresh pack four bots said "lvl 2 oldum" within a minute)
            b._level_announce = b.level
        sel = _GREETING_START.match(text)
        if sel and any(str(x[1]) == b.name and _GREETING_START.match(str(x[3])) and self.y.now - x[0] < 1200 for x in self.y.history[-80:]):
            text = text[sel.end():].strip()               # this bot just said hello: not every line starts with "selam millet!"
            if len(text.split()) < 2:                       # (chat trial 2026-10-30)
                return ''
        previous = [str(x[3]) for x in self.y.history[-25:] if str(x[3]) != echo] + self.y.pending_texts()
        # (the replied message itself is left to the echo check: a quoted reply like "VRU is the best company? you're an EIC noob" passes)      # pending ones too
        if any(_similar(text, x) for x in previous):
            return ''                                        # someone just wrote (roughly) the same
        if echo:                                            # echo: repeating most of the player's words
            a, c = set(re.findall(r'[^\W\d_]+', text.lower())), set(re.findall(r'[^\W\d_]+', echo.lower()))
            if len(c) >= 3 and len(a) >= 2 and len(a & c) >= 0.7 * len(a):
                return ''                                        # someone else just wrote the same: real players do not repeat
        text = re.sub(r'\bmmo+t?\b', 'mmo', re.sub(r'\bvru[d]\b', 'vru', re.sub(r'\biec\b', 'eic', text, flags=re.I), flags=re.I),
                       flags=re.I)                           # the model garbling company names (mmoo, iec)
        u = dict(b.k['personality'].get('style') or {})
        u.update(emoji=0.0, punctuation=0.0, uppercase=0.0, error=u.get('error', 0.05) * 0.4)
        return SPC.apply_style(text, u, b.r, SPC.lang(b) if MULTILINGUAL else 'en')
