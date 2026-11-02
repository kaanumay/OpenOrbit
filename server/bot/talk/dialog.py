"""The conversation engine of the Normal mode: who answers a message, with which move, in which language and when.

Human messages are read by nlu.py; bot lines carry their meaning (meta: act, topic, slots, question) so the bots can answer each other
through the same pipeline: a bot asks "where are the lordakia", another one answers with the right maps, the first one thanks him.
Every line is built by the grammar (grammar.py) from the language's acts, typed in the bot's own style (style.py) and sent after a
human reading + thinking + typing time.

Context: a follow-up ("why?", "where?", "u sure?") goes to the bot that answered, on the same topic; when a bot asked a human something
(a whisper "how is it going", "and you?"), his next words are taken as the answer (expectations).
"""
import difflib, math, random, re

import map_links as H
from . import facts as FA
from . import grammar as G
from . import knowledge as KN
from . import lexicon as LX
from . import nlu as NLU
from . import persona as PE
from . import style as ST
from .params import P

GAME_TOPICS = ('alien', 'boss', 'ship', 'laser', 'shield', 'drone', 'pet', 'gate', 'quest', 'uri', 'credits', 'money', 'honor', 'level',
               'clan', 'pvp', 'company', 'start', 'map', 'best', 'event', 'lag', 'game', 'ore', 'ammo')
SELF_TOPICS = {'age': 'self_age', 'origin': 'self_origin', 'playtime': 'self_playtime', 'realname': 'self_realname', 'ship': 'self_ship',
               'level': 'self_level', 'clan': 'self_clan', 'laser': 'self_laser', 'uri': 'self_money', 'credits': 'self_money',
               'money': 'self_money', 'company': 'self_company', 'map': 'self_map', 'doing': 'doing', 'job': 'self_job',
               'school': 'self_job', 'music': 'self_music', 'food': 'self_food', 'sleep': 'self_sleep', 'tired': 'self_sleep',
               'football': 'self_football', 'weather': 'self_weather', 'pvp': 'self_pvp', 'howareyou': 'howareyou'}
PERSONAL = ('age', 'origin', 'job', 'school', 'playtime', 'realname', 'music', 'food', 'sleep', 'tired', 'football', 'weather', 'doing',
            'howareyou')
BUYABLE = ('ship', 'laser', 'drone', 'shield', 'pet')
REACT = {'food': 'react_food', 'sleep': 'react_sleep', 'tired': 'react_sleep', 'school': 'react_work', 'job': 'react_work',
         'football': 'react_football', 'weather': 'react_weather', 'lag': 'react_lag', 'music': 'react_music', 'pvp': 'react_pvp',
         'company': 'react_company', 'alien': 'react_game', 'boss': 'react_game', 'map': 'react_game', 'quest': 'react_game',
         'uri': 'react_grind', 'credits': 'react_grind', 'level': 'react_grind', 'ship': 'react_ship', 'event': 'react_game',
         'quiet': 'react_quiet', 'bored': 'react_bored'}
SHIP_ORDER = ('phoenix', 'liberator', 'piranha', 'nostromo', 'bigboy', 'leonov', 'vengeance', 'goliath', 'aegis', 'citadel', 'spearhead')


class State:
    def __init__(self):
        self.recent = []                 # [(time, simplified line)]: near-repeat check across all bots
        self.meta = {}                   # (uid, text) -> meta of a queued line (read back when it is sent)
        self.turns = {}                  # conversation key -> [turn]: recent lines of the channel / whisper pair
        self.human_t = {}                # conversation key -> last time a human wrote there
        self.last_topic = {}             # human name (lower) -> (time, Msg, answering bot name or None): context of a follow-up
        self.opened = {}                 # bot uid -> last spontaneous opener time
        self.acked = {}                  # question key -> time: the asker thanked once already
        self.expect = {}                 # human name (lower) -> (time, bot name, topic, channel): the bot asked him something
        self.said = {}                   # human name (lower) -> (time, Msg): his last line naming a ship / laser / alien ("iyi mi?" after it)


def state(y):
    s = y.__dict__.get('_talk')
    if s is None:
        s = y._talk = State()
    return s


def _simple(text):
    return re.sub(r'\d+', '#', re.sub(r'[\W_]+', ' ', re.sub(r"['’`]", '', NLU.fold(text)))).strip()


def _similar(a, b):
    if a == b:
        return True
    x, y_ = set(a.split()), set(b.split())
    if len(x) >= 3 and len(y_) >= 3 and len(x & y_) / len(x | y_) >= 0.6:
        return True
    if len(a) < 12 or len(b) < 12:                            # the same line with a typo / another spacing ("2-5te kas" vs "2-5 te kas")
        return False
    sm = difflib.SequenceMatcher(None, a, b)
    return sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.8


def compose(y, b, act, lang, slots, question=False, r=None, strict=False, no_ask=False, relax=False):
    """The bot's line for the act -> [message, ...] or None (no pattern, missing fields, or only stale lines).

    Repeats are checked on what is actually sent (after the bot's style: "where are" and "where r" are the same line): no line of two
    words or more twice within repeat_sec (by anyone), never the same line by the same bot within 20 minutes, no near repeat of a 3+
    word line; one-word reactions (gg, ty, wb) may repeat, except in strict mode (spontaneous openers). no_ask: the line must not
    ask back ("and you?"): the other one already asked it. relax: a direct answer; only the bot's own repeats and the last 90
    seconds count (someone asked him: he answers even if another player said the same half an hour ago)."""
    patterns = LX.act(lang, act)
    if not patterns:
        return None
    pe = PE.of(b)
    r = r or b.r
    st = state(y)
    now = y.now
    st.recent = [x for x in st.recent[-P['similar_window']:] if now - x[0] < 3 * 3600]
    seen = [x[1] for x in st.recent]
    mine = {x[1] for x in st.recent if x[2] == b.uid and now - x[0] < 1200}
    fresh = {x[1] for x in st.recent if now - x[0] < 90}
    lately = {x[1] for x in st.recent if now - x[0] < (90 if relax else P['repeat_sec'])}
    ex = G.Expander(slots, lambda c: pe.pick(c, lang, r), lambda n: r.choice(LX.act(lang, n)) if LX.act(lang, n) else None, r,
                    opt=P['opt'] * (0.6 + 0.8 * pe.verbose))
    protect = [v for v in slots.values() if isinstance(v, str)]
    for i in range(int(P['tries'])):
        text = ex.run(r.choice(patterns))
        text = G.tidy(text) if text else None
        if not text:
            continue
        out = ST.messages(text, pe, r, question=question, lang=lang, protect=protect)
        if not out:
            continue
        sent = [_simple(m) for m in out]
        whole = _simple(' '.join(out))
        if any(x in mine or ((strict or len(x.split()) >= 2) and x in lately) for x in sent + [whole]):
            continue
        if len(whole.split()) <= 2 and whole in fresh and len(whole) > 3:
            continue
        if len(whole.split()) >= 3 and not relax and any(_similar(whole, x) for x in seen):
            continue
        if no_ask and (out[-1].rstrip().endswith('?') or NLU.read(' '.join(out)).you):
            continue
        for m in sent + ([whole] if len(sent) > 1 else []):
            st.recent.append((now, m, b.uid))
        return out
    return None


def reply_delay(pe, b, heard, text, r):
    """Reading + thinking + typing time of the first message (seconds)."""
    t = len(heard or '') / P['read_cps'] + math.exp(r.gauss(math.log(max(0.2, P['think_mu'])), P['think_sigma'])) + len(text) / pe.cps
    if KN.fighting(b):
        t += r.uniform(0.3, 1.0) * P['busy_extra']
    if r.random() < P['late_reply']:
        t += r.uniform(15, 70)
    return t


def deliver(y, b, channel, msgs, now, delay, recipient=None, meta=None, priority=False):
    """Queues the messages: the first after delay, the rest after their own typing time. -> time of the last one or None."""
    pe = PE.of(b)
    t = now + delay
    last = None
    for i, m in enumerate(msgs):
        if i:
            t += b.r.uniform(*P['split_gap']) + len(m) / pe.cps
        if meta is not None and i == len(msgs) - 1:
            state(y).meta[(b.uid, m)] = dict(meta)
        x = y.speak(b, channel, m, recipient=recipient, now=t, immediate=True, priority=priority)
        if x is None:
            return last
        last = x
    return last


def say(y, b, act, channel, now, slots=None, lang=None, recipient=None, meta=None, heard='', delay=None, question=False, priority=False,
        no_ask=False):
    """Builds and queues a line of the act. -> time it goes out or None."""
    lang = lang or PE.of(b).lang
    f = base_slots(y, b, lang)
    f.update(slots or {})
    KN.add_suffixes(f, lang, PE.of(b))
    msgs = compose(y, b, act, lang, f, question=question, strict=(meta or {}).get('kind') in ('opener', 'event'), no_ask=no_ask)
    if not msgs and (priority or (meta or {}).get('reply_to')):      # an answer to someone: rather a line said before than silence
        msgs = compose(y, b, act, lang, f, question=question, no_ask=no_ask, relax=True)
    if not msgs:
        return None
    m = dict(meta or {})
    m.setdefault('act', act)
    m.setdefault('lang', lang)
    m.setdefault('question', question)
    d = reply_delay(PE.of(b), b, heard, msgs[0], b.r) if delay is None else delay
    return deliver(y, b, channel, msgs, now, d, recipient=recipient, meta=m, priority=priority)


def map_label(m):
    """'2-3' for a normal map, None for a gate / instance map (a player says "in a gate", not "on 499")."""
    n = H.name(m)
    return n if re.match(r'^[1-5]-[1-8]$', str(n)) else None


def base_slots(y, b, lang):
    pe = PE.of(b)
    bio = pe.bio
    f = dict(level=b.level, ship=KN.nick(KN.ship_of(b), pe), company=KN.COMPANY.get(b.company, ''), age=bio['age'], city=bio['city'],
             city_from=bio['city_from'], since=bio['since'], job=bio['job'], years=max(1, 2026 - bio['since']), tag=KN.clan_tag(b) or '',
             home='%d-1' % b.company)
    ml = map_label(b.game_map)
    if ml:
        f['map'] = ml
    return f


def short_name(name, pe):
    """How a player writes someone else's name: the plain skeleton of a decorated name, often only its first part (Kasirga.1907 ->
    kasirga, efe_reis -> efe), each player his own way."""
    from .. import name_style as NS
    base = name if re.match(r'^[A-Za-z0-9_.\-]+$', str(name)) else (NS.plain(name) or str(name))
    rr = random.Random(PE.seed_of('short', pe.name.lower(), str(name).lower()))
    if rr.random() < 0.5:
        parts = [p for p in re.split(r'[._\-]+|\d+|(?<=[a-z])(?=[A-Z])', base) if p and len(p) >= 3]
        if parts:
            base = parts[0]
    return base


# ------------------------------------------------------------------------------------------------- choosing the move
def _lang_for(b, m_lang):
    """The language the bot answers in, None if it does not understand the message."""
    pe = PE.of(b)
    if m_lang is None or m_lang == pe.lang:
        return pe.lang
    if m_lang == 'en' and pe.english:
        return 'en'
    return None


def _mood(b, now):
    md = getattr(b, 'mood', None) or {}
    try:
        fat, ang = md['fatigue'], md['anger']
    except Exception:
        return 'good'
    if ang > 0.6:
        return 'bad'
    if fat > 0.6:
        return 'tired'
    rr = random.Random(PE.seed_of('mood', b.name.lower(), int(now) // 1800))
    return 'good' if rr.random() < 0.7 else 'meh'          # the same answer for half an hour, not a new mood every line


def _after(ship, pe):
    """The ship a pilot would buy after this one (each bot its own opinion)."""
    if ship not in SHIP_ORDER:
        return None
    i = SHIP_ORDER.index(ship)
    nxt = SHIP_ORDER[i + 1:i + 3] or SHIP_ORDER[-3:]
    return pe.opinion_of('after_' + ship, nxt)


def game_answer(y, b, m, asker, lang):
    """A move answering a game question -> (act, slots) or None."""
    pe = PE.of(b)
    topic = m.topic
    fac = KN.company_of(y, asker) or b.company
    lv = KN.level_of(y, asker) or 5
    if topic in ('level', 'map') and m.numbers and 1 <= m.numbers[0] <= 30:
        lv = m.numbers[0]                                       # "5. seviyede nerede kasılır": that level, not his
    r = b.r
    know = b.level >= 3 or r.random() < 0.6                     # a fresh pilot sometimes does not know
    best = 'best' in m.topics
    if topic in ('alien', 'boss') or (topic == 'map' and m.aliens):
        alien = (m.aliens or ['boss'])[0]
        maps = KN.alien_maps(alien, fac)
        if not maps:
            return ('dunno_alien', dict(alien=alien))
        if not know:
            return ('dunno_game', {})
        k = maps[:r.choice((1, 2, 2, 3))]
        return ('ans_where_boss' if alien == 'boss' else 'ans_where_alien', dict(alien=alien, maps=' '.join(k) if r.random() < 0.5 else ', '.join(k),
                                                                                  map1=k[0]))
    if topic == 'ship':
        if m.inherited and m.qtype == 'q_where':
            return ('ans_where_buy', {})
        if m.qtype == 'q_worth' or (m.ships and m.qtype == 'q_yn' and not m.after):
            s = (m.ships or ['goliath'])[0]
            good = pe.opinion_of('worth_' + s, (True, True, False)) if s not in ('phoenix', 'liberator') else False
            return ('ans_worth_yes' if good else 'ans_worth_no', dict(item=KN.nick(s, pe)))
        if m.after or (not m.ships and m.qtype == 'q_which' and asker.lower() in y.name_index):
            base = m.ships[0] if m.ships else KN.ship_of(y.name_index[asker.lower()])
            s = _after(base, pe)
            if s:
                return ('ans_ship', dict(item=KN.nick(s, pe)))
        if len(m.ships) >= 2:
            s = pe.opinion_of('vs_' + '_'.join(sorted(m.ships[:2])), m.ships[:2])
            return ('ans_pick', dict(item=KN.nick(s, pe)))
        if best:
            return ('ans_pick', dict(item=KN.nick(pe.opinion_of('best_ship', ('goliath', 'goliath', 'citadel', 'aegis')), pe)))
        s = KN.ladder(KN.SHIP_LADDER, lv, random.Random(PE.seed_of(pe.name, 'ship', lv)))
        return ('ans_ship', dict(item=KN.nick(s, pe)))
    if topic == 'laser':
        if m.inherited and m.qtype == 'q_where':
            return ('ans_where_buy', {})
        if len(m.lasers) >= 2:
            ranked = sorted(m.lasers[:2], key=lambda x: (x.startswith('LF'), x[-1]))
            s = pe.opinion_of('vs_' + '_'.join(sorted(m.lasers[:2])), [ranked[-1], ranked[-1], ranked[0]])
            return ('ans_pick', dict(item=s))
        if best:
            return ('ans_pick', dict(item='LF-3'))
        if m.lasers and m.qtype in ('q_worth', 'q_yn'):
            return ('ans_worth_yes', dict(item=m.lasers[0]))
        return ('ans_laser', dict(item=KN.ladder(KN.LASER_LADDER, lv, random.Random(PE.seed_of(pe.name, 'laser', lv)))))
    if topic in ('drone', 'pet', 'shield'):
        if m.inherited and m.qtype == 'q_where':
            return ('ans_where_buy', {})
        return ('ans_' + topic, {}) if know else ('dunno_game', {})
    if topic in ('uri', 'money', 'honor'):
        return ('ans_uri' if topic != 'honor' else 'ans_honor', dict(map1='%d-%d' % (fac, 5 if lv >= 10 else 3)))
    if topic == 'credits':
        return ('ans_credits', dict(map1='%d-%d' % (fac, 2 if lv < 6 else 4)))
    if topic == 'level':
        return ('ans_level', dict(map1=r.choice(FA.grind_maps(fac, lv))))
    if topic == 'start' or 'newbie' in m.acts:
        return ('ans_start', dict(map1='%d-1' % fac, alien='streuner'))
    if topic == 'quest':
        return ('ans_quest', dict(map1='%d-1' % fac))
    if topic == 'gate':
        return ('ans_gate', {}) if know else ('dunno_game', {})
    if topic == 'pvp':
        return ('ans_pvp', dict(map1=r.choice(('4-1', '4-2', '4-3', '4-4', '4-5'))))
    if topic == 'company':
        return ('ans_company', dict(company=KN.COMPANY.get(b.company)))
    if topic == 'clan':
        tag = KN.clan_tag(b)
        return ('ans_clan_have', dict(tag=tag)) if tag else ('ans_clan', {})
    if topic == 'map':
        return ('ans_map', dict(map1=r.choice(FA.grind_maps(fac, lv))))
    if topic == 'lag':
        return ('react_lag', {})
    if topic == 'event':                                      # the calendar's real events (or none)
        import event_calendar as CAL
        on = [k for k in sorted(CAL.active(y.now)) if k in CAL.EVENTS]
        if not on:
            return ('ans_event_none', {})
        short = lambda k: (((LX.DATA.get(lang) or {}).get('names') or {}).get('ev_' + k) or (LX.DATA['en'].get('names') or {}).get('ev_' + k)
                           or re.sub(r'\s*\(.*?\)', '', CAL.EVENTS[k].get('name') or k).strip().lower())
        names = [short(k) for k in on]
        k = on[r.randrange(len(on))]
        left = int(CAL.time_left(k, y.now) // 86400)
        return ('ans_event', dict(event=', '.join(names[:2]), n=left if 0 < left < 20 else None))
    if topic in ('best', 'game'):
        return ('opinion', {})
    return None


def self_answer(y, b, m, lang):
    """A move answering a question about the bot itself -> (act, slots) or None."""
    pe = PE.of(b)
    act = SELF_TOPICS.get(m.topic)
    if act is None:
        return None
    if act == 'howareyou':
        return ('howareyou_' + _mood(b, y.now), {})
    if act == 'doing':
        return ('doing_' + KN.doing(b), {})
    if act == 'self_job':
        return ('self_' + pe.bio['occ'], {})
    if act == 'self_playtime' and pe.bio['returning']:
        return ('self_playtime_back', {})
    if act == 'self_clan':
        return ('self_clan', {}) if KN.clan_tag(b) else ('self_noclan', {})
    if act == 'self_map' and m.qtype not in ('q_where', None):
        return None
    if act == 'self_laser':
        return ('self_laser', dict(item=_best_laser(b)))
    if act == 'self_food' and m.fav:
        return ('self_fav_food', {})
    return (act, {})


def _best_laser(b):
    names = [re.sub(r'^.*laser_', '', str(x)).upper() for x in (b.k['gear'].get('laser') or {})]
    return max(names, key=lambda x: (x.startswith('LF'), x[-1])) if names else 'LF-1'


def move(y, b, m, asker, addressed, lang):
    """The bot's move for a message -> (act, slots, question) or None (says nothing)."""
    main, topic = m.main, m.topic
    pe = PE.of(b)
    if main == 'botq':
        return ('deny_bot' if addressed or m.you else 'bots_all', {}, False)
    if main == 'insult':
        if addressed or (m.companies and b.company in m.companies):
            rude = int(y.setting('rude_chat', 1) or 0)
            return ('insult_back_harsh' if rude >= 2 and pe.aggr > 0.55 else 'insult_back', {}, False)
        return None
    if main == 'greet':
        return ('greet_back', {}, False)
    if main == 'howareyou':
        if 'doing' in m.topics and (addressed or m.you):             # "ne yapıyorsun": what it really does, not just "iyi"
            return ('doing_' + KN.doing(b), {}, False)
        return ('howareyou_' + _mood(b, y.now), {}, False)
    if main == 'bye':
        return ('bye_reply', {}, False)
    if main == 'back':
        return ('wb', {}, False)
    if main == 'brb':
        return ('brb_reply', {}, False) if addressed else None
    if main == 'thanks':
        return ('np', {}, False) if addressed else None
    if main == 'congrats':
        return ('congrats_thanks', {}, False) if addressed else None
    if main == 'sorry':
        return ('np', {}, False) if addressed else None
    if main == 'rollcall':
        return ('here', {}, False)
    if main == 'wish':                                        # "kolay gelsin": thanks back
        return ('wish_thanks', {}, False) if addressed or b.r.random() < 0.5 else None
    if main == 'likeq':                                       # "patates kızartması seven var mı": each bot its own taste
        likes = pe.opinion_of('like_' + _simple(m.text), (True, True, False))
        return ('like_yes' if likes else 'like_no', {}, False)
    if main == 'blame':                                       # "nobody came": the one on the way was late, the others were away
        return ('excuse_helper' if KN.helping(b, asker) else 'excuse', {}, False)
    if main == 'helpq':                                       # "anyone coming?"
        return ('on_way' if KN.helping(b, asker) else 'cant_help', {}, False)
    if main == 'question':
        if m.inherited:                                       # a follow-up of an answer this bot gave
            if m.sure:
                return ('sure_yes', {}, False)
            if m.qtype == 'q_why':
                return ('why_generic', {}, False)
            if m.qtype in ('q_yn', None) and topic not in PERSONAL:
                if (topic == 'ship' and m.ships) or (topic == 'laser' and m.lasers):    # "iyi mi?" about the ship he named
                    item = m.ships[0] if topic == 'ship' else m.lasers[0]
                    good = item not in ('phoenix', 'liberator') and pe.opinion_of('worth_' + item, (True, True, False))
                    return ('ans_good_yes' if good else 'ans_good_no', dict(item=KN.nick(item, pe) if topic == 'ship' else item), False)
                return ('opinion_yn', {}, False)
        if not m.you or m.entities or m.maps or m.fq:
            k = FA.answer(y, b, m, asker, lang)                # "lf4 nasıl alınır", "x4 kaç uri", "4-4e kaçta girilir": from the game data
            if k:
                return (k[0], k[1], False)
        personal = topic in PERSONAL
        advice = m.qtype in ('q_worth', 'q_how', 'q_why') or (m.qtype == 'q_which' and not m.you) or m.me or m.after \
            or bool(m.aliens) or 'newbie' in m.acts or 'best' in m.topics
        k = None
        if personal:
            k = self_answer(y, b, m, lang)
        elif topic in GAME_TOPICS and (advice or not (m.you or m.all or addressed)):
            k = game_answer(y, b, m, asker, lang)
        elif topic in SELF_TOPICS:
            k = self_answer(y, b, m, lang)
        if k is None and (topic in GAME_TOPICS or 'newbie' in m.acts):
            k = game_answer(y, b, m, asker, lang)
        if k:
            return (k[0], k[1], False)
        if topic in REACT and topic not in GAME_TOPICS:       # "chat ölü mü?": a remark more than a question
            return (REACT[topic], {}, False)
        if m.qtype == 'q_why':
            return ('why_generic', {}, False)
        if addressed:
            return ('opinion_yn' if m.qtype in ('q_yn', None) else 'dunno', {}, False)
        return ('opinion_yn', {}, False) if m.qtype == 'q_yn' and b.r.random() < 0.5 else None
    if main == 'complain':
        return (REACT.get(topic) or 'sympathy', {}, False)
    if main == 'brag':
        return ('congrats', {}, False)
    if main == 'newbie':
        return ('welcome_new', dict(map1='%d-1' % (KN.company_of(y, asker) or b.company)), False)
    if main == 'laugh':
        return ('laugh', {}, False)
    if main == 'sad':
        return ('sympathy', {}, False)
    if topic in REACT:
        return (REACT[topic], {}, False)
    if addressed:
        return ('react_generic', {}, False)
    return None


# ------------------------------------------------------------------------------------------------- who answers
def _key(channel, route=None, pair=()):
    return ('w',) + tuple(sorted(a.lower() for a in pair)) if channel == 'whisper' else ('r', route or channel)


def _recent_bot_speaker(y, key, now, sec=90, to=None):
    for t in reversed(state(y).turns.get(key, ())):
        if now - t['t'] > sec:
            break
        if t['bot'] and (to is None or (t.get('meta') or {}).get('reply_to') == to):
            return y.name_index.get(t['who'].lower())
    return None


def _remember(y, key, who, text, now, bot, meta=None):
    k = state(y).turns.setdefault(key, [])
    k.append(dict(t=now, who=who, text=text, bot=bot, meta=meta))
    del k[:-30]


def _interest(b, m):
    """How much the topic draws this bot in (0..1)."""
    pe = PE.of(b)
    t = m.topic
    if t in ('alien', 'boss', 'ship', 'laser', 'map', 'start', 'quest', 'level', 'uri', 'credits', 'gate', 'drone', 'shield', 'pet'):
        return 0.35 + 0.55 * pe.helpful + (0.1 if b.level >= 8 else -0.1)
    if t in ('pvp', 'company'):
        return 0.25 + 0.6 * pe.aggr
    return 0.2 + 0.6 * pe.social


def _weight(b, m):
    pe = PE.of(b)
    from .. import playstyle as PL
    return (0.2 + _interest(b, m)) * (0.5 + pe.talk) * b.r.uniform(0.5, 1.5) * (0.4 if KN.fighting(b) else 1.0) \
        * (0.12 if PL.quiet(b) else 1.0)                          # a lurker rarely joins in


def responders(y, m, listeners, addressed, now, whisper=False):
    """[(bot, addressed?)] that will answer, in order. A whisper is almost always answered (someone wrote to you alone)."""
    if addressed:
        out = []
        for b in addressed:
            p = P['p_addressed_question'] if m.question else P['p_addressed_other']
            if whisper and m.main not in ('laugh', 'statement', 'insult'):
                p = 1.0                                       # a greeting or question whispered to you alone is answered
            if m.main in ('laugh', 'statement') and not m.question:
                p *= 0.7
            if m.main == 'insult':
                p = P['p_insult_reply'] * (0.4 + 0.9 * PE.of(b).aggr)       # a calm one often just ignores it
            if b.r.random() < p:
                out.append((b, True))
        return out
    pool = [b for b in listeners if b.online]
    if not pool:
        return []
    main = m.main
    p, extra = {'question': (P['p_open_question'], P['p_second_answer']), 'greet': (P['p_greet_reply'], P['p_greet_extra']),
                'howareyou': (P['p_greet_reply'], P['p_greet_extra'] * 0.5), 'bye': (P['p_bye_reply'], 0.2),
                'back': (P['p_back_reply'], 0.1), 'botq': (P['p_bot_accusation'], 0.35), 'rollcall': (0.8, 0.45),
                'laugh': (P['p_laugh_reply'], 0.0), 'newbie': (0.7, 0.3), 'complain': (P['p_statement_reply'] * 3.0, 0.15),
                'brag': (0.55, 0.3), 'insult': (P['p_insult_reply'] * 0.6, 0.15), 'blame': (0.75, 0.3),
                'helpq': (0.55, 0.15), 'wish': (0.3, 0.1), 'likeq': (0.6, 0.35)}.get(main, (P['p_statement_reply'], 0.08))
    if main in ('question', 'greet', 'howareyou', 'statement', 'complain'):
        p = 1.0 - (1.0 - min(0.9, p * (1.4 if 'newbie' in m.acts else 1.0))) ** len(pool)     # a crowded channel answers more often
    if random.random() >= p:
        return []
    ranked = sorted(pool, key=lambda b: -_weight(b, m))
    out = [(ranked[0], False)]
    for b in ranked[1:4]:
        if random.random() < extra:
            out.append((b, False))
            extra *= 0.45
    return out


# ------------------------------------------------------------------------------------------------- entry points
def on_human(y, channel, text, who, listeners, now, route=None, whisper_bot=None):
    """A human wrote in a room (listeners: bots hearing it) or whispered to whisper_bot. -> True if handled (even silently)."""
    st = state(y)
    name = who.get('userId', '')
    if whisper_bot is not None:
        listeners = [whisper_bot]
    m = NLU.read(text, [b.name for b in y.bots])             # every bot's name: "is X on" may name one who is not here
    key = _key(channel, route, (name, whisper_bot.name) if whisper_bot is not None else ())
    out_channel = 'whisper' if whisper_bot is not None else channel
    recipient = name if whisper_bot is not None else None
    st.human_t[key] = now
    st.human_t['any'] = now
    _remember(y, key, name, text, now, False)
    by_name = {b.name.lower(): b for b in listeners}
    addressed = [whisper_bot] if whisper_bot is not None else [by_name[n.lower()] for n in m.names if n.lower() in by_name]
    if m.main in ('blame', 'helpq'):                          # about his call for help: only his company; the ones on the way first
        fac = KN.company_of(y, name)
        listeners = [b for b in listeners if fac is None or b.company == fac]
        addressed = addressed or [b for b in listeners if KN.helping(b, name)][:2]
    if _expected(y, m, name, listeners, addressed, out_channel, recipient, text, now):
        return True
    if 'presence' in m.acts and m.names and whisper_bot is None and _presence(y, m, name, listeners, out_channel, text, now):
        return True
    said = st.said.get(name.lower())
    if m.ships or m.lasers or m.aliens:
        st.said[name.lower()] = (now, m)
    prev = st.last_topic.get(name.lower())
    if m.topic is None and m.question and prev and prev[1].topic and now - prev[0] < 150 and m.main == 'question' \
            and len(m.f.split()) <= 4 and (not addressed or (prev[2] and prev[2].lower() in {b.name.lower() for b in addressed})):
        _inherit(m, prev[1], said[1] if said and said[0] > prev[0] else None)   # "neden?", "peki nerde?": same topic, same bot
        b = y.name_index.get(str(prev[2]).lower()) if prev[2] else None
        if not addressed and b is not None and b in listeners:
            addressed = [b]
        elif not addressed:
            return True                                       # a follow-up to a question nobody answered
    if not addressed and (m.you or m.main == 'wish') and not m.all:    # "kolay gelsin" right after a bot answered: to that bot
        b = _recent_bot_speaker(y, key, now, to=name, sec=240 if m.main == 'wish' else 90) or _recent_bot_speaker(y, key, now, sec=40)
        if b is not None and b in listeners:
            addressed = [b]
    if m.main == 'statement' and not addressed and not m.topic and not m.question:
        return True                                           # small talk to nobody: usually read and left alone
    answered = False
    lag = 0.0
    for b, direct in responders(y, m, listeners, addressed, now, whisper=whisper_bot is not None):
        lang = _lang_for(b, m.lang)
        if lang is None:
            if direct and whisper_bot is not None:
                say(y, b, 'no_understand', out_channel, now, lang='en', recipient=recipient, heard=text)
            continue
        mv = move(y, b, m, name, direct, lang)
        if mv is None:
            continue
        act, slots, q = mv
        pe = PE.of(b)
        slots = dict(slots, name=short_name(name, pe))
        b.memory.event(name, 'insult' if m.main == 'insult' else 'chat', now)
        ask_topic = 'howareyou' if m.main == 'howareyou' else m.topic
        ask_back = direct and act.startswith('self_') and ask_topic in PERSONAL + ('ship', 'level') \
            and b.r.random() < P['p_askback'] * (0.5 + pe.social)    # "how are you" answers carry their own "and you?" 
        meta = dict(topic=m.topic, reply_to=name, kind='answer' if m.question else 'react', depth=1)
        t = say(y, b, act, out_channel, now + lag, slots=slots, lang=lang, recipient=recipient, meta=meta, heard=text,
                priority=True)                                # an answer to a player is not held back by the channel limit
        if t is not None and ask_back:
            if say(y, b, 'askback_' + ask_topic if LX.act(lang, 'askback_' + ask_topic) else 'askback', out_channel, t, slots=slots,
                   lang=lang, recipient=recipient, delay=b.r.uniform(1.0, 3.0), question=True,
                   meta=dict(topic=ask_topic, kind='askback', depth=1, reply_to=name), priority=direct) is not None:
                st.expect[name.lower()] = (now, b.name, ask_topic, out_channel)
        if t is not None:
            if m.question and not answered:                   # "neden?" goes to the first one who answered
                st.last_topic[name.lower()] = (now, m, b.name)
            answered = True
            lag += b.r.uniform(2.0, 7.0)                      # a crowd does not answer in the same second
            if direct and act.startswith('howareyou'):
                st.expect[name.lower()] = (now, b.name, 'howareyou', out_channel)   # "iyiyim sen?" is his answer
    if m.question and not answered:
        st.last_topic[name.lower()] = (now, m, None)
    return True


def _expected(y, m, name, listeners, addressed, out_channel, recipient, text, now):
    """The bot asked this human something a moment ago and this is his answer: the bot reacts to it (and answers "and you?")."""
    st = state(y)
    e = st.expect.get(name.lower())
    if not e or now - e[0] > 240 or e[3] != out_channel:
        return False
    b = y.name_index.get(e[1].lower())
    if b is None or b not in listeners or (addressed and b not in addressed):
        return False
    if m.main in ('botq', 'insult', 'bye', 'brb', 'greet', 'blame', 'helpq'):
        return False
    if m.question and not (m.you and m.topic in (None, e[2]) and len(m.f.split()) <= 4):
        return False                                          # a new question, not his answer ("17, u?" is an answer)
    del st.expect[name.lower()]
    lang = _lang_for(b, m.lang)
    if lang is None:
        return False
    pe = PE.of(b)
    slots = dict(name=short_name(name, pe))
    if m.you:                                                 # "iyi sen?", "17, u?": he asks back
        q = NLU.Msg(text)
        q.topics.add(e[2])
        q.question, q.you = True, True
        mv = self_answer(y, b, q, lang)
        if mv:
            say(y, b, mv[0], out_channel, now, slots=dict(mv[1], **slots), lang=lang, recipient=recipient, heard=text, priority=True,
                meta=dict(kind='react', reply_to=name, depth=2, topic=e[2]), no_ask=True)
            return True
    act = 'react_answer'
    if e[2] == 'ship' and m.ships:                            # "goliath var bende": about that ship, not a bare "ok"
        act = 'react_have_ship'
        slots['item'] = KN.nick(m.ships[0], pe)
    elif e[2] == 'help':                                      # he said how many they are
        act = 'help_ok'
    if act != 'react_answer' or b.r.random() < 0.8:
        say(y, b, act, out_channel, now, slots=slots, lang=lang, recipient=recipient, heard=text, priority=True,
            meta=dict(kind='react', reply_to=name, depth=2, topic=e[2]))
    return True


def _presence(y, m, name, listeners, channel, text, now):
    """"X burda mı / is X on": X answers himself if he is here, otherwise someone who knows says yes (and where) or no."""
    tgt = y.name_index.get(m.names[0].lower())
    if tgt is None:
        return False
    lang = m.lang
    if tgt.online and tgt in listeners and _lang_for(tgt, lang):
        say(y, tgt, 'here', channel, now, lang=_lang_for(tgt, lang), heard=text, priority=True, meta=dict(kind='answer', reply_to=name))
        return True
    others = [b for b in listeners if b.online and b is not tgt and _lang_for(b, lang)]
    if not others or random.random() > 0.85:
        return True
    b = max(others, key=lambda b: (0.3 + PE.of(b).social) * b.r.random() * (2.0 if tgt.company == b.company else 1.0))
    ml = map_label(tgt.game_map) if tgt.online and tgt.company == b.company else None
    say(y, b, 'presence_yes' if tgt.online else 'presence_no', channel, now, lang=_lang_for(b, lang), heard=text,
        slots=dict(who=short_name(tgt.name, PE.of(b)), map1=ml), meta=dict(kind='answer', reply_to=name))
    return True


def _inherit(m, prev, said=None):
    """prev: the question that was answered; said: what the human named after it ("goliath var bende" ... "iyi mi?")."""
    m.topics |= prev.topics
    for src in (said, prev):
        if src is not None:
            m.entities = m.entities or src.entities
            m.aliens = m.aliens or src.aliens
            m.ships = m.ships or src.ships
            m.lasers = m.lasers or src.lasers
    m.maps = m.maps or prev.maps
    m.you = True
    m.inherited = True


def heard_bot(y, b, channel, text, now, route=None, recipient=None):
    """A bot's line went out: other bots may answer it (the line's meta says what it means)."""
    st = state(y)
    meta = st.meta.pop((b.uid, text), None)
    if recipient:
        return
    key = _key(channel, route)
    _remember(y, key, b.name, text, now, True, meta)
    if meta is None or now - st.human_t.get(key, -1e9) < 8:
        return
    depth = meta.get('depth', 1)
    if depth >= P['max_depth']:
        return
    lang = meta.get('lang')
    target = meta.get('reply_to')
    if target and target.lower() in y.name_index and meta.get('kind') in ('answer', 'react', 'askback'):
        a = y.name_index[target.lower()]                     # the bot that asked: thanks, shares, or answers the question asked back
        if not a.online or a is b:
            return
        pa = PE.of(a)
        slots = dict(name=short_name(b.name, pa))
        if meta.get('kind') == 'askback' and meta.get('topic'):
            m = NLU.Msg(text)
            m.topics.add(meta['topic'])
            m.question, m.you = True, True
            mv = self_answer(y, a, m, lang)
            if mv:
                say(y, a, mv[0], channel, now, slots=dict(mv[1], **slots), lang=lang, heard=text,
                    meta=dict(kind='react', depth=depth + 1, topic=meta['topic']), no_ask=True)
            return
        qkey = meta.get('qkey')
        if meta.get('kind') == 'answer' and qkey not in st.acked:
            st.acked[qkey] = now
            if len(st.acked) > 500:
                st.acked = {k: v for k, v in st.acked.items() if now - v < 3600}
            personal = meta.get('topic') in PERSONAL or str(meta.get('act', '')).startswith(('self_', 'doing_', 'howareyou'))
            if personal and meta.get('topic') and a.r.random() < P['p_share']:
                m = NLU.Msg(text)                               # "ben 20", "ben de 2-3'te kasıyorum": he shares his own
                m.topics.add(meta['topic'])
                m.question, m.you = True, True
                mv = self_answer(y, a, m, lang)
                if mv:
                    say(y, a, mv[0], channel, now, slots=dict(mv[1], **slots), lang=lang, heard=text,
                        meta=dict(kind='end', depth=depth + 1, topic=meta['topic']), no_ask=True)
            elif not personal and a.r.random() < P['p_ack']:
                say(y, a, 'ack', channel, now, slots=slots, lang=lang, heard=text, meta=dict(kind='end', depth=depth + 1))
        elif meta.get('kind') == 'react' and str(meta.get('act', '')).startswith('congrats') and qkey not in st.acked \
                and a.r.random() < P['p_ack']:
            st.acked[qkey] = now
            say(y, a, 'congrats_thanks', channel, now, slots=slots, lang=lang, heard=text, meta=dict(kind='end', depth=depth + 1))
        return
    if meta.get('kind') not in ('opener', 'event'):
        return
    m = meta_msg(text, meta)
    parsed = NLU.read(text)
    m.aliens, m.ships, m.lasers, m.maps = m.aliens or parsed.aliens, m.ships or parsed.ships, m.lasers or parsed.lasers, parsed.maps
    m.after = m.after or parsed.after
    m.topics |= parsed.topics & {'best'}                      # "en iyi lazer hangisi": the best one, not the next one
    lst = [c for c in y.listeners(channel, _who(b), alive=False) if c is not b and _lang_for(c, lang) == lang]
    if not lst:
        return
    p = P['p_bot_reply'] if m.question else P['p_bot_react'] if meta.get('kind') != 'event' else P['p_event_react']
    if random.random() >= p:
        return
    qkey = (b.name, round(now, 1))
    ranked = sorted(lst, key=lambda c: -_weight(c, m))
    for i, c in enumerate(ranked[:2]):
        if i and random.random() > 0.25:
            break
        mv = (meta['react'], {}, False) if meta.get('react') else move(y, c, m, b.name, False, lang)
        if mv is None:
            continue
        act, slots, q = mv
        pc = PE.of(c)
        ask_back = act.startswith('self_') and c.r.random() < P['p_askback']
        t = say(y, c, act, channel, now + i * 3, slots=dict(slots, name=short_name(b.name, pc)), lang=lang, heard=text,
                meta=dict(kind='answer' if m.question else 'react', reply_to=b.name, depth=depth + 1, topic=m.topic, qkey=qkey))
        if t is not None and ask_back:
            say(y, c, 'askback_' + m.topic if LX.act(lang, 'askback_' + m.topic) else 'askback', channel, t,
                slots=dict(name=short_name(b.name, pc)), lang=lang, delay=c.r.uniform(1.0, 3.0), question=True,
                meta=dict(kind='askback', reply_to=b.name, depth=depth + 1, topic=m.topic))


def _who(b):
    from ..chat_engine import user
    return user(b)


def meta_msg(text, meta):
    """A Msg from a bot line's meta (no parsing needed: the bot knows what it said)."""
    m = NLU.Msg(text)
    for a in meta.get('acts', ()):
        m.acts.add(a)
    if meta.get('topic'):
        m.topics.add(meta['topic'])
    m.question = bool(meta.get('question'))
    m.qtype = meta.get('qtype') or (('q_yn' if m.question else None))
    m.aliens = list(meta.get('aliens', ()))
    m.ships = list(meta.get('ships', ()))
    m.lasers = list(meta.get('lasers', ()))
    m.all = bool(meta.get('all'))
    m.after = bool(meta.get('after'))
    m.lang = meta.get('lang')
    return m


# ------------------------------------------------------------------------------------------------- spontaneous talk
OPENERS = (
    # act, weight, meta (what it means for the listeners), condition
    ('ask_where_alien', 6, dict(topic='alien', question=True, qtype='q_where'), lambda b: b.level < 10),
    ('ask_boss', 4, dict(topic='boss', question=True, qtype='q_where', aliens=['boss']), None),
    ('ask_ship_next', 5, dict(topic='ship', question=True, qtype='q_which', after=True), lambda b: b.level < 14),
    ('ask_ship_worth', 3, dict(topic='ship', question=True, qtype='q_worth'), lambda b: b.level < 14),
    ('ask_laser', 3, dict(topic='laser', question=True, qtype='q_which'), lambda b: b.level < 12),
    ('ask_uri', 3, dict(topic='uri', question=True, qtype='q_how'), None),
    ('ask_level_map', 3, dict(topic='map', question=True, qtype='q_where'), lambda b: b.level < 12),
    ('ask_howlong', 2, dict(topic='playtime', question=True, all=True), None),
    ('ask_age', 1, dict(topic='age', question=True, all=True), None),
    ('ask_doing', 3, dict(topic='doing', question=True, all=True), None),
    ('ask_music', 1, dict(topic='music', question=True, all=True), None),
    ('ask_anyone_map', 3, dict(topic='map', acts=['rollcall'], question=False, react='here_map'), None),
    ('tell_grind', 4, dict(topic='map', react='react_game'), None),
    ('tell_food', 2, dict(topic='food'), None),
    ('tell_sleep', 2, dict(topic='sleep'), None),
    ('tell_work', 2, dict(topic='job'), None),
    ('tell_bored', 2, dict(topic='game', react='react_bored'), None),
    ('tell_weather', 1, dict(topic='weather'), None),
    ('tell_football', 1, dict(topic='football'), None),
    ('complain_uri', 2, dict(topic='uri', acts=['complain']), None),
    ('complain_aliens', 2, dict(topic='alien', acts=['complain'], react='sympathy'), None),
    ('complain_lag', 1, dict(topic='lag', acts=['complain']), None),
    ('joke', 2, dict(topic=None, react='laugh'), None),
    ('rollcall', 1, dict(acts=['rollcall'], react='here'), None),
    ('group_search', 2, dict(topic='map', react='group_maybe'), lambda b: PE.of(b).social > 0.45),
)


def spontaneous(y, now):
    """Now and then a bot opens a topic (called every EVENT_SEC seconds). -> True if one did."""
    st = state(y)
    if now - st.human_t.get('any', -1e9) < P['quiet_after_human']:
        return False
    online = [b for b in y.bots if b.online]
    if not online:
        return False
    rate = P['spontaneous_per_min'] * min(1.6, len(online) / 20.0) * 5.0 / 60.0
    if random.random() >= rate:
        return False
    from .. import playstyle as PL
    free = [b for b in online if now - st.opened.get(b.uid, -1e9) >= P['bot_gap_sec'] and not PL.quiet(b)]     # lurkers do not open topics
    if not free:
        return False
    b = max(free, key=lambda b: (0.25 + PE.of(b).talk) * b.r.random())
    channel = 'company' if b.r.random() < 0.72 else 'global'
    quiet = _quiet(y, b, channel, now)
    anger = (getattr(getattr(b, 'mood', None), 'd', None) or {}).get('anger', 0.0)
    whine = now - st.__dict__.get('complained', -1e9) >= P['complaint_sec'] * (1.0 - 0.8 * min(1.0, anger))   # an angry one complains sooner
    said = st.__dict__.setdefault('opener_acts', {})
    rows = [o for o in OPENERS if (o[3] is None or o[3](b)) and (o[0] not in ('rollcall', 'ask_anyone_map') or quiet > 300)
            and (whine or not o[0].startswith('complain')) and now - said.get((b.uid, o[0]), -1e9) >= OPENER_GAP.get(o[0], 3600)]
    for _ in range(3):                                         # its lines of that topic used up lately: another topic
        act, _, meta, _ = b.r.choices(rows, weights=[o[1] * _mood_weight(b, o[0]) for o in rows])[0]
        t = _open(y, b, act, meta, channel, now)
        if t is not None:
            break
        rows = [o for o in rows if o[0] != act]
        if not rows:
            return False
    if t is None:
        return False
    st.opened[b.uid] = now
    said[(b.uid, act)] = now
    if len(said) > 3000:
        st.opener_acts = {k: v for k, v in said.items() if now - v < 3600}
    if act.startswith('complain'):
        st.complained = now
    return True


def _open(y, b, act, meta, channel, now):
    pe = PE.of(b)
    slots = {}
    meta = dict(meta, kind='opener', depth=1)
    if act == 'ask_where_alien':
        ml = map_label(b.game_map)
        al = (KN.map_aliens(ml) if ml else []) or ['streuner']
        nxt = {'streuner': 'lordakia', 'lordakia': 'saimon', 'saimon': 'mordon', 'mordon': 'devolarium', 'devolarium': 'sibelonit',
               'sibelonit': 'lordakium', 'lordakium': 'kristallin', 'kristallin': 'kristallon'}
        a = nxt.get(al[0], 'mordon')
        slots['alien'] = a
        meta['aliens'] = [a]
    elif act == 'ask_ship_worth':
        s = KN.ladder(KN.SHIP_LADDER, b.level + 4, b.r)
        slots['item'] = KN.nick(s, pe)
        meta['ships'] = [s]
    return say(y, b, act, channel, now, slots=slots, lang=pe.lang, meta=meta, question=bool(meta.get('question')), delay=0)


OPENER_GAP = {'tell_sleep': 3 * 3600, 'tell_food': 2 * 3600, 'tell_work': 3 * 3600, 'tell_weather': 3 * 3600, 'tell_football': 3 * 3600}
MOOD_OPENERS = {'fatigue': ('tell_sleep',), 'boredom': ('tell_bored', 'joke', 'group_search'), 'anger': ('complain_uri', 'complain_aliens', 'complain_lag'),
                'morale': ('joke', 'tell_grind')}


def _mood_weight(b, act):
    """How much more the bot's state makes it bring this up (x1 when calm; a tired bot talks about sleep, an angry one complains)."""
    md = getattr(getattr(b, 'mood', None), 'd', None) or {}
    w = 1.0
    for k, opener in MOOD_OPENERS.items():
        if act in opener:
            v = md.get(k, 0.0) - (0.6 if k == 'morale' else 0.0)
            w *= 1.0 + 5.0 * max(0.0, v)
    return w


def _quiet(y, b, channel, now):
    """Seconds since the last line in the channel the bot would write to."""
    from ..chat_engine import channel_path
    k = state(y).turns.get(_key(channel, channel_path(b, channel))) or []
    return now - k[-1]['t'] if k else 1e9


EVENT_ACTS = {'level': ('tell_level', dict(acts=['brag'], topic='level', react='congrats')),
              'new_ship': ('tell_ship', dict(acts=['brag'], topic='ship', react='congrats_ship')),
              'i_killed_boss': ('tell_boss', dict(acts=['brag'], topic='boss', react='congrats')),
              'death_npc': ('tell_death', dict(topic='alien', react='sympathy')),
              'quest_done': ('tell_quest', dict(topic='quest', react='congrats_small')),
              'gate_done': ('tell_gate', dict(topic='gate', react='congrats'))}


def event_line(y, b, kind, now, channel='company', **slots):
    """A bot tells what just happened to it (level, new ship, boss) -> True if a line was queued. Others may congratulate."""
    act, meta = EVENT_ACTS[kind]
    if kind == 'level' and int(slots.get('level') or b.level) < 6 and b.r.random() < 0.97:
        return False                                          # nobody announces level 2 or 3
    meta = dict(meta, kind='event', depth=1)
    return say(y, b, act, channel, now, slots=slots, meta=meta, delay=b.r.uniform(2, 9)) is not None


def witness(y, b, sub, now, **slots):
    """A bot saw something next to it (a boss kill, a pilot destroyed)."""
    return say(y, b, 'witness_boss' if sub == 'boss' else 'witness_death', 'company', now, slots=slots,
               meta=dict(kind='react', depth=2), delay=b.r.uniform(2, 8)) is not None


def help_reply(y, b, human, map_name, channel, now):
    """A bot answers a call for help it will go to: "on my way" or "how many are they?" (his answer is expected). -> True if queued."""
    pe = PE.of(b)
    ask = b.r.random() < 0.3
    recipient = human if channel == 'whisper' else None
    t = say(y, b, 'help_howmany' if ask else 'help_coming', channel, now, slots=dict(map1=str(map_name), name=short_name(human, pe)),
            recipient=recipient, question=ask, meta=dict(kind='react', reply_to=human, topic='help'))
    if t is not None and ask:
        state(y).expect[human.lower()] = (now, b.name, 'help', channel)
    return t is not None


PRIVATE = {'private_greeting': ('pm_greet', None), 'private_chat': (None, None), 'private_group': ('pm_group', None)}


def private(y, b, human, purpose, now):
    """A bot whispers to a human on its own (login greeting, small talk, a group offer) -> True if a line was queued. A question
    opens an expectation: the human's answer is understood as the answer (_expected)."""
    pe = PE.of(b)
    act = PRIVATE.get(purpose, (None,))[0]
    topic = None
    if act is None:
        act, topic = b.r.choice((('pm_howareyou', 'howareyou'), ('pm_doing', 'doing'), ('pm_howareyou', 'howareyou')))
    slots = dict(name=short_name(human, pe))
    t = say(y, b, act, 'whisper', now, slots=slots, recipient=human, question=topic is not None, delay=b.r.uniform(2, 10),
            meta=dict(kind='opener', reply_to=human, topic=topic))
    if t is not None and topic:
        state(y).expect[human.lower()] = (now, b.name, topic, 'whisper')
    return t is not None
