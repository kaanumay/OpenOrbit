"""Normal mode chat: template sentences by situation and personality, the bot's writing style, and simple replies to the player's messages.

In advanced mode the LLM (llm.py) talks; if there is no LLM or it cannot keep up, the templates here are the fallback. The templates are short and like
real chat channels: mostly one line, lowercase, abbreviated. apply_style() applies the bot's style (personality.generate_personality: lowercase,
punctuation, abbreviation, emoji, error, uppercase).
"""
import random, re

from .language_data import LANGUAGES, CODES

# situation -> {lang: lines}, lang -> abbreviations: bot/languages/<code>.json (language_data)
TEMPLATES = {}
for _code, _d in LANGUAGES.items():
    for _state, _lines in _d.get('templates', {}).items():
        TEMPLATES.setdefault(_state, {})[_code] = _lines
DIALOGUE = {k: d.get('dialogues', []) for k, d in LANGUAGES.items()}   # lang -> [conversation]; conversation = [turn]; turn = [alternative lines]
ABBREVIATIONS = {k: [tuple(x) for x in d.get('abbreviation', ())] for k, d in LANGUAGES.items()}
ASCII = {k: (str.maketrans(d['ascii']) if d.get('ascii') else None, d.get('ascii_ratio', 0.0)) for k, d in LANGUAGES.items()}
EMOJI = (':D', ':)', 'xD', '^^', ':P', ';)', 'xd')


def lang(bot):
    d = bot.k['personality'].get('lang')
    return d if d in LANGUAGES else 'en'


def template(bot, state, **f):
    """One of the situation's templates (in the bot's language), fields filled, style applied -> text or None."""
    k = TEMPLATES.get(state)
    if not k:
        return None
    d = lang(bot)
    text = bot.r.choice(k.get(d) or k['en'])
    try:
        text = text.format(**f)
    except (KeyError, IndexError):
        return None
    return apply_style(text, bot.k['personality'].get('style') or {}, bot.r, d)


def dialogue(bot):
    """A random short conversation in the bot's language (turns: the first line is a question/remark, the rest are replies) or None."""
    k = DIALOGUE.get(lang(bot)) or DIALOGUE.get('en')
    return bot.r.choice(k) if k else None


def dialogue_line(bot, kind, **f):
    """The bot's line from one turn of a conversation (lines with alternatives), fields filled, style applied -> text or None."""
    try:
        text = bot.r.choice(kind).format(**f)
    except (KeyError, IndexError):
        return None
    return apply_style(text, bot.k['personality'].get('style') or {}, bot.r, lang(bot))


def apply_style(text, u, r=random, d='tr'):
    """The bot's writing style: abbreviations, dropping Turkish characters, lower/UPPER case, punctuation, emoji, typos."""
    if r.random() < u.get('abbreviation', 0.4):
        for a, b in ABBREVIATIONS.get(d, ()):
            text = re.sub(r'\b%s\b' % re.escape(a), b, text)
    table, ratio = ASCII.get(d, (None, 0.0))
    if table and r.random() < ratio:
        text = text.translate(table)             # most players do not type accented letters (Turkish characters, umlauts ...)
    if r.random() < u.get('lowercase', 0.6):
        text = text.lower().replace('i̇', 'i')     # "İ".lower() used to turn into a dotted i (i + combining dot)
    elif text and r.random() < 0.5:
        text = text[0].upper() + text[1:]
    if r.random() < u.get('uppercase', 0.05) * 0.25:      # a SHOUTING line is very rare (user report 2026-10-29)
        text = text.upper()
    if r.random() < u.get('punctuation', 0.3) and text[-1:].isalnum():
        text += r.choice(('.', '!', '...'))
    if r.random() < u.get('emoji', 0.3) * 0.6 and not text.endswith(EMOJI):
        text += ' ' + r.choice(EMOJI)
    if r.random() < u.get('error', 0.08) and len(text) > 4:
        i = r.randrange(1, len(text) - 2)
        if text[i - 1].isalpha() and text[i].isalpha() and text[i + 1].isalpha() and text[i + 2:i + 3].isalpha():
            # only inside a long word: "eic" -> "iec", short names like "2-1" are not broken
            text = text[:i] + text[i + 1] + text[i] + text[i + 2:]
    return text


# ------------------------------------------------------------------------------------------------------------ niyet
_GREETING = re.compile(r'\b(selam|slm|sa|merhaba|mrb|hi|hello|hey|yo|selamun|naber|nbr)\b', re.I)
# bare "gel/gelsene" is not help ("niye eic'e katılmıyorsun gelsene": a lag; before, bots used to run to war at 2-1, player
# report 2026-10-30); with a map, "2-1e gelsene" is follow (_GEL)
_HELP = re.compile(r'(yard[ıi]m|help|destek|imdat|kurtar|sald[ıi]r[ıi]yor|vuruyor|attack)', re.I)
_COME = re.compile(r'\bgel(in|sene|senize|ir ?misin|ebilir ?misin)?\b', re.I)
_GROUP = re.compile(r'\b(grup|group|party|parti|team|tak[ıi]m|together|team up|duo|join me|birlikte|beraber)\b', re.I)
_CLAN = re.compile(r'\b(clan|clans|klan|klana|klanin|klanım|klanim|guild|recruit\w*)\b', re.I)
_FRIEND = re.compile(r'\b(add me|add u|adding (you|u)|friend ?req\w*|be friends|friend me|ekle beni|arkada[sş] ?ol\w*|arkada[sş]l[ıi]k)\b',
                      re.I)
_FOLLOW = re.compile(r"\b(come (to|here|over|with)|follow me|where (are|r) (you|u)|where u at|wya|meet (me|at|on)|nerdesin|neredesin|"
                    r"gel (buraya|yan[ıi]ma)|beni takip)\b", re.I)
_DUEL = re.compile(r'\b(duel|duels|duello|1v1|1 v 1|1vs1|fight me|pvp me|come fight|who wants to fight|kapışalım|kapisalim|'
                     r'kapış|dövüşelim|dovusalim|vs at)\b', re.I)
_GATE = re.compile(r"\b(lf\d?m?|looking for|need|needs|fill\w*|join|who|anyone|inv\w*|come|lazım|lazim|gelen|kim|var m[ıi])\b.*"
                   r"\b(hades|(?-i:LoW|LOW)|legends? of war|qz|quarantine|gates?|kap[ıi]\w*|zeta|kappa|lambda|kuiper|kronos|delta|epsilon)\b|"
                   r"\b(hades|(?-i:LoW|LOW)|qz|kap[ıi]\w*)\s+(i[çc]in|fill\w*|lf\w*)\b", re.I)
_QUEST = re.compile(r'\b(quest|quests|mission|missions|g[öo]rev\w*)\b', re.I)
# in a help request, the enemy player marker: if absent and a quest is mentioned, it is quest help (grouping), not PvP help
_PVP = re.compile(r'\b(attack\w*|camp\w*|enem\w*|gank\w*|kill(ing|s)? me|hunting me|pvp|player|players|mmo|eic|vru|'
                  r'sald[ıi]r\w*|vuruyor|kurtar|d[üu][şs]man)\b', re.I)
_PRIVATE = re.compile(r'\b(pm me|dm me|msg me|message me|whisper me|private message|private msg|send me (a )?(pm|dm|msg|message)|'
                   r'pm at|[öo]zelden yaz|[öo]zel mesaj|fısılda|fisilda)\b', re.I)
_INSULT = re.compile(r'\b(noob|nub|ez|ezik|aptal|salak|gerizekal[ıi]|beceriksiz|loser|trash|çöp|cop|bot)\b', re.I)
# Turkish question words with their suffixes ("hangisi", "nerde", "kaçıncı") and the question suffix ("değer mi", "var mı");
# before, "en iyi lazer hangisi" was not counted as a question (chat trial 2026-10-30)
_QUESTION = re.compile(r'\?\s*$|\b(ne|neden|niye|nas[ıi]l\w*|nere\w*|nerde\w*|hangi\w*|kim(ler)?|ka[çc](ta|[ıi]nc[ıi]|ar)?|what|how|why|where|which|who|when)\b|'
                   r'\b(m[ıiuü])(s[ıiuü]n(.z)?|y[ıiuü]m|y[ıiuü]z|d[ıiuü]r)?\b', re.I)
_THANKS = re.compile(r'\b(sa[gğ]ol|te[sş]ekk|t[sş]k|eyv|thanks|thx|ty)\b', re.I)
MAP_RE = re.compile(r'\b([1-5])\s*[-xX/]\s*([1-8]|bl)(?![\d])', re.I)     # a Turkish suffix is fine too: "2-1e", "2-3'te", "1-4de"


def _lang_expr(name):
    promises = sorted({w for d in LANGUAGES.values() for w in d.get('intent', {}).get(name, ())}, key=len, reverse=True)
    return re.compile(r'(?<!\w)(%s)(?!\w)' % '|'.join(re.escape(w) for w in promises), re.I) if promises else None


_LANG = {name: _lang_expr(name) for name in ('greeting', 'assist', 'group', 'clan', 'friend', 'followup', 'duel', 'quest', 'special', 'insult',
                                        'question', 'thanks', 'pvp')}


def _var(rx, name, text):
    """A Turkish/English expression or words of the other languages (bot/languages/*.json intent)."""
    return bool(rx.search(text)) or bool(_LANG.get(name) and _LANG[name].search(text))


def intent(text):
    """The rough intent of the player's message: 'assist', 'group', 'clan', 'friend', 'followup', 'duel', 'quest', 'special', 'gate', 'insult', 'greeting', 'thanks',
    'question' or None; and the map name mentioned. Requests (group, clan, friendship, follow) are decided by interaction.py."""
    m = MAP_RE.search(text)
    game_map = ('%s-%s' % (m.group(1), m.group(2).upper() if m.group(2).isalpha() else m.group(2))) if m else None
    if _var(_FOLLOW, 'followup', text) or (game_map and _COME.search(text) and not _var(_HELP, 'assist', text)):
        return 'followup', game_map                       # "come to 2-3", "2-1e gelsene": not help
    if _var(_PRIVATE, 'special', text):
        return 'special', game_map                        # "bana özelden yaz": the reply goes by whisper
    if _var(_DUEL, 'duel', text):
        return 'duel', game_map
    if _GATE.search(text):
        return 'gate', game_map                        # "need fillers for hades", "lf low", "kapı için adam lazım": gate filler
    if _var(_HELP, 'assist', text) and _var(_QUEST, 'quest', text) and not _var(_PVP, 'pvp', text):
        return 'quest', game_map                       # "help me with a quest": group (counts toward the quest of everyone the group kills)
    for name, rx in (('assist', _HELP), ('group', _GROUP), ('clan', _CLAN), ('friend', _FRIEND), ('insult', _INSULT), ('thanks', _THANKS), ('greeting', _GREETING),
                   ('question', _QUESTION)):
        if _var(rx, name, text):
            return name, game_map
    return None, game_map


def typing_time(text, bot):
    """A human's reading and typing time (sec): reaction + per letter."""
    return bot.k['personality']['reaction_sec'] * bot.r.uniform(2.0, 5.0) + len(text) / bot.r.uniform(3.5, 7.0)
