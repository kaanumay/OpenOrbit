"""Bots and the admin (admin_mode.py; user request 2026-10-30): they recognize the admin, heed the admin's warnings in chat, and react
on seeing the admin.

Warning: if the admin's room message or whisper contains a warning word (in eight languages: "stop", "warning", "kes", "yeter", "hör auf" ...)
the topic comes from the words: chat (spam, swearing, caps), pvp (killing, preying on newbies, camping), box (cargo box, loot stealing); with
no topic it is general (chat and PvP, short). Warned bots: those named; if none is named, those listening to the channel. The effect is
timed (doubles with repetition, up to 8 times):
  chat    30 min   conversation mostly falls silent (replies only), no retaliation against insults
  pvp     4 h      does not attack players or bots, does not go out PvP hunting
  box     24 h     does not take someone else's cargo box
The named bot briefly apologizes (in Advanced mode the language model: system prompt and persona note; otherwise a stock phrase). In its
memory a "warned" event with the admin. They return a greeting from the admin; on seeing the admin on the map, one of them says so in
company chat (one per map per COMMENT_SEC).
"""
import re, time, unicodedata

import map_links as H
import admin_mode as YM
from . import name_style as NS
from . import speech as SPC

DURATION_MIN = {'sohbet': 30, 'pvp': 240, 'box': 1440}
GENERAL = {'sohbet': 30, 'pvp': 60}
COMMENT_SEC = 900
SIGHT = 1600


def _normalize(s):
    s = str(s or '').lower().replace('ı', 'i').replace('ß', 'ss').replace('ł', 'l')
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _stem_regex(stems):
    return re.compile(r'(?<!\w)(%s)' % '|'.join(re.escape(_normalize(k)) for k in sorted(stems, key=len, reverse=True)))


# a strong word alone is a warning; a weak one ("dont", "yapma", "pare") only together with a topic word (the admin's ordinary chat,
# "dont worry guys", must not punish anyone)
STRONG = _stem_regex([
    'warn', 'ban', 'mute', 'rules', 'last time', 'cut it out', 'not allowed', 'uyari', 'uyariyorum', 'son kez', 'kural', 'sustur',
    'yasak', 'verwarn', 'regel', 'advertencia', 'regla', 'avertissement', 'regle', 'interdit', 'ostrzez', 'zasad', 'aviso', 'regra',
    'proibido', 'предупрежд', 'правил', 'бан', 'нельзя'])
WEAK = _stem_regex([
    'stop', 'quit', 'dont', "don't", 'do not', 'no more', 'behave', 'enough', 'kes', 'yapma', 'yapmayin', 'birak', 'durdur', 'yeter',
    'dikkat edin', 'etme', 'etmeyin', 'olmaz', 'calmayin', 'almayin', 'saldirmayin', 'oldurmeyin', 'yazmayin', 'atmayin', 'hor auf', 'hoer auf', 'hort auf', 'lass das', 'stopp', 'deja', 'dejen', 'basta', 'arrete', 'przestan', 'dosc',
    'pare', 'parem', 'chega', 'прекрат', 'хватит', 'стоп'])
TOPICS = {
    'sohbet': _stem_regex(['spam', 'flood', 'caps', 'insult', 'swear', 'curs', 'toxic', 'rude', 'offensive', 'language', 'chat', 'kufur',
                      'hakaret', 'buyuk harf', 'kaba', 'argo', 'sohbet', 'beleidig', 'schimpf', 'flame', 'insult', 'groser', 'grossier',
                      'obraz', 'wyzwisk', 'xing', 'спам', 'флуд', 'мат', 'оскорб', 'капс', 'чат']),
    'pvp': _stem_regex(['kill', 'attack', 'grief', 'camp', 'newbie', 'noob', 'low level', 'lowbie', 'gank', 'pk', 'oldur', 'saldir', 'kesme',
                   'yeni oyuncu', 'acemi', 'dusuk seviye', 'avla', 'kamp', 'tot', 'angreif', 'neuling', 'anfanger', 'matar', 'atacar',
                   'novato', 'campear', 'tuer', 'attaqu', 'debutant', 'zabija', 'atak', 'nowi', 'nowicjusz', 'kampi', 'campar',
                   'убива', 'атак', 'нович', 'кемп']),
    'box': _stem_regex(['box', 'cargo', 'loot', 'steal', 'kutu', 'kargo', 'ganimet', 'cal', 'kiste', 'beute', 'klau', 'stehl', 'caja',
                    'botin', 'robar', 'caisse', 'butin', 'vol', 'skrzyn', 'lup', 'krad', 'caixa', 'saque', 'roub', 'ящик', 'карго',
                    'лут', 'ворова', 'краж']),
}


def topics(text):
    """Is it a warning -> its topics (an empty result means not a warning; with no topic {'general'})."""
    k = _normalize(text)
    talk = {name for name, phrase in TOPICS.items() if phrase.search(k)}
    if STRONG.search(k):
        return talk or {'general'}
    return talk if WEAK.search(k) else set()


def active(b, topic, now=None):
    """Is the bot under the admin's warning on this topic."""
    u = b.k.get('warning') or {}
    return (now or time.time()) < u.get(topic, 0)


def warn(b, talk, now, name=''):
    """Apply the warning (durations grow with repetition) -> the topics applied."""
    u = b.k.setdefault('warning', {})
    u['number'] = n = int(u.get('number', 0)) + 1 if now - u.get('last', 0) < 86400 else 1
    u['last'] = now
    multiplier = min(8, 2 ** (n - 1))
    durations = {}
    for k in talk:
        durations.update(GENERAL if k == 'general' else {k: DURATION_MIN[k]})
    for k, minutes in durations.items():
        u[k] = max(u.get(k, 0), now + minutes * 60 * multiplier)
    if name:
        b.memory.event(name, 'warned', now)
    b.event('admin_warned', now, subject=','.join(sorted(durations)))
    b.mood.it(morale=-0.05)
    return set(durations)


def note(b, now=None):
    """Persona note (Advanced mode): the admin's ongoing warning."""
    now = now or time.time()
    u = b.k.get('warning') or {}
    is_open = [k for k in DURATION_MIN if now < u.get(k, 0)]
    if not is_open:
        return ''
    ne = {'sohbet': 'spamming or rude chat', 'pvp': 'attacking or killing other pilots', 'box': "taking other pilots' cargo boxes"}
    return ' The game master warned him about %s %d min ago: he obeys and avoids it.' % (
        ' and '.join(ne[k] for k in is_open), max(1, int((now - u.get('last', now)) // 60)))


def system_note():
    """For the system prompt (llm.py, agent.py): while the admin is present; otherwise empty (the cache is not disturbed)."""
    name = YM.name()
    if not name:
        return ''
    return ('\n\nGAME MASTER: %s is a game administrator (GM) of this server: admin badge on the ship, admin colour in chat, may fly '
            'an admin ship (a UFO). Everyone knows it. Be polite to the GM, never insult, threaten or attack them, never argue with '
            'their decisions. When the GM warns about conduct (spam, insults, caps, killing new players, camping, taking others\' '
            'loot), the warned pilot apologizes briefly and stops; others may comment but never mock the warning. Asking the GM for '
            'free items or bans only as an obvious joke. Seeing the GM in space is a small event worth a remark.' % name)


def handle(m, g, now):
    """The chat engine's incoming message (ChatEngine.incoming_chat / incoming_whisper): the admin's warning or greeting -> was it handled (True: the replies
    happen here or in the language model, they do not go to the stock phrases)."""
    if g[0] == 'whisper':
        _, b, msg, who = g
        listener, mentioned, channel = [b], [b], None
    else:
        _, route, msg, who = g
        from .chat_engine import channel_name
        channel = channel_name(route)
        if channel is None:
            return False
        listener = m.listeners(channel, who)
        mentioned = [b for b in listener if NS.is_mentioned(b.name, msg)]
    name = who.get('userId', '')
    if not YM.mi(name_=name):
        return False
    talk = topics(msg)
    if talk:
        target = mentioned or listener
        for b in target:
            warn(b, talk, now, name)
        if m.llm is not None and m.llm.ready:
            return False                                 # the language model replies (persona note and system prompt)
        for b in (mentioned or [x for x in target if x.r.random() < 0.15])[:2]:
            m.speak(b, channel or 'whisper', SPC.template(b, 'admin_apology', name=name), recipient=name if channel is None else None, now=now,
                    priority=True)
        return True
    kind, _ = SPC.intent(msg)
    if kind == 'greeting' and channel is not None and not mentioned and (m.llm is None or not m.llm.ready):
        for b in [b for b in listener if b.r.random() < 0.5 + 0.4 * b.o('sociability')][:3]:
            m.speak(b, channel, SPC.template(b, 'admin_greeting', name=name), now=now, priority=True)
        return True
    return False


def sight_tick(y, now):
    """Admin on the map: a nearby bot says it in company chat (one per map per COMMENT_SEC)."""
    if not YM.is_open():
        return
    last = y.__dict__.setdefault('_gm_comment', {})
    for w in list(y.worlds):
        if not getattr(w, 'running', False) or not YM.mi(profile=w.p) or now - last.get(w.map_id, 0) < COMMENT_SEC:
            continue
        hx, hy = w.hero_pos(now)
        nearby = [n.bot for n in list(w.npcs.values()) if n.bot is not None and n.alive and
                 ((n.mover.pos(now)[0] - hx) ** 2 + (n.mover.pos(now)[1] - hy) ** 2) ** 0.5 < SIGHT]
        if not nearby:
            continue
        last[w.map_id] = now
        b = max(nearby, key=lambda b: b.o('talkativeness') * b.r.random())
        b.event('admin_saw', now, map=H.name(w.map_id))
        y.speak(b, 'company', SPC.template(b, 'admin_saw', map=H.name(w.map_id)), now=now)
