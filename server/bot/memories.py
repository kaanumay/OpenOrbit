"""The bots' memory journal (Advanced mode, strong provider: llm.STRONG): important events with people as short notes, persistent in the
save.

Generative Agents (Park et al. 2023) layout: memory stream (chosen by importance x recency), a per-person impression (reflection) and
consequences born from memories (follow-up). In the save:
  k['memories']   [{t, who, summary, type, emotion (-1..1), importance (1-3), n, followup}]; summary is the English note sent to the model
  ("Kaan shot me down on 2-4")
  k['impression']  {lowercase name: {name, text, t}}: a dense opinion about a person (the model updates it with the conversation summary)
follow-up: {purpose (promise | intikam | thanks | rekabet | merak), due (moment), tool (none | follow | group_invite | duel | go_help),
map, finished}. When its time comes and both sides are online, llm.Brain raises the topic in the bot's own words and runs the tool
(due_followups).

Sources: game events (from_event -> from the event, by template; only with real players), the model's summary at the end of a conversation
(llm._memory_summary) and gossip between bots (heard). Events between bots are not memories (there are many, the player does not see them).
"""
import time

MAX_MEMORIES = 60                      # memories per bot (the least valuable one drops)
MERGE_SEC = 1800              # an event of the same type with the same person is counted if repeated within this time ("x3")
GRACE_SEC = 6 * 3600            # after a follow-up's due time passes it waits this long (if the person did not come online it is forgotten)
PURPOSES = ('promise', 'intikam', 'thanks', 'rekabet', 'merak')
FOLLOWUP_TOOLS = ('none', 'follow', 'group_invite', 'duel', 'go_help')

# game event -> (note, type, emotion, importance); {ad} is the player
TEMPLATE = {
    'killed_me': ('{name} shot me down', 'combat', -0.6, 2),
    'i_killed': ('I shot down {name}', 'combat', 0.2, 1),
    'helped_me': ('{name} came to help me', 'assist', 0.6, 2),
    'i_helped': ('I flew over to help {name}', 'assist', 0.3, 1),
    'group': ('grouped up with {name}', 'group', 0.3, 1),
    'insult': ('{name} insulted me', 'insult', -0.4, 1),
    'challenge': ('{name} challenged me to a duel', 'combat', 0.0, 2),
    'friend': ('became friends with {name}', 'friendly', 0.6, 2),
    'clan': ('{name} and I ended up in the same clan', 'friendly', 0.4, 2),
}


def memories(b):
    return b.k.setdefault('memories', [])


def impressions(b):
    return b.k.setdefault('impression', {})


def _value(a, now):
    """The weight of a memory: importance x recency (half-life one day; a repeating event is a bit heavier)."""
    return a['importance'] * (1 + 0.15 * min(5, a.get('n', 1) - 1)) * 0.5 ** (max(0, now - a['t']) / 86400)


def add(b, who, summary, kind='not', emotion=0.0, importance=1, now=None, followup=None, merge=True):
    """Add a memory; a recent event of the same type with the same person is counted. -> memory."""
    now = now if now is not None else time.time()
    mems = memories(b)
    k = str(who).lower()
    if merge:
        for a in reversed(mems):
            if a['who'].lower() == k and a['type'] == kind and a['summary'] == summary and now - a['t'] < MERGE_SEC:
                a['n'] = a.get('n', 1) + 1
                a['t'] = now
                if followup and not a.get('followup'):
                    a['followup'] = followup
                return a
    a = {'t': now, 'who': str(who), 'summary': str(summary)[:200], 'type': kind, 'emotion': round(max(-1.0, min(1.0, float(emotion))), 2),
         'importance': max(1, min(3, int(importance))), 'n': 1, 'followup': followup}
    mems.append(a)
    if len(mems) > MAX_MEMORIES:
        is_open = [x for x in mems if x.get('followup') and not x['followup'].get('finished')]
        candidate = [x for x in mems if x not in is_open] or mems
        mems.remove(min(candidate, key=lambda x: _value(x, now)))
    return a


def time_ago(dt):
    dt = max(0, dt)
    if dt < 120:
        return 'just now'
    if dt < 3600:
        return '%d min ago' % (dt // 60)
    if dt < 86400:
        return '%d h ago' % (dt // 3600)
    return '%d days ago' % (dt // 86400)


def _line(a, now):
    return '%s (%s%s)' % (a['summary'], time_ago(now - a['t']), ', x%d' % a['n'] if a.get('n', 1) > 1 else '')


def recall(b, who, now, n=6):
    """The n most valuable memories with a person, oldest to newest."""
    k = str(who).lower()
    mems = [a for a in memories(b) if a['who'].lower() == k]
    return sorted(sorted(mems, key=lambda a: -_value(a, now))[:n], key=lambda a: a['t'])


def text(b, who, now):
    """Prompt: the impression and memories about a person ('' if none)."""
    out = ''
    trace = impressions(b).get(str(who).lower())
    if trace and trace.get('text'):
        out += ' Your impression of %s: %s.' % (trace['name'], trace['text'].rstrip('.'))
    mems = recall(b, who, now)
    if mems:
        out += ' Your memories with %s: %s.' % (mems[-1]['who'], '; '.join(_line(a, now) for a in mems))
    is_open = [a['followup'] for a in mems if a.get('followup') and not a['followup'].get('finished')]
    if is_open:
        out += ' Still pending with him: %s.' % ', '.join(PURPOSE_NAME[t['purpose']] for t in is_open)
    return out


PURPOSE_NAME = {'promise': 'a plan you agreed on', 'intikam': 'you want revenge', 'thanks': 'you owe him thanks', 'rekabet': 'a rivalry',
           'merak': 'something you wanted to ask him'}


def important(b, now, n=3, humans=None):
    """The bot's most valuable memories (regardless of person; if humans are given, only with them)."""
    mems = [a for a in memories(b) if humans is None or a['who'].lower() in humans]
    return sorted(mems, key=lambda a: -_value(a, now))[:n]


def write_impression(b, who, text_, now):
    if text_ and str(text_).strip():
        impressions(b)[str(who).lower()] = {'name': str(who), 'text': str(text_).strip()[:240], 't': now}


def set_followup(purpose, now, minutes=10, tool='none', game_map=''):
    if purpose not in PURPOSES:
        return None
    return {'purpose': purpose, 'due': now + max(1, min(240, int(minutes or 10))) * 60, 'tool': tool if tool in FOLLOWUP_TOOLS else 'none',
            'map': str(game_map or '')[:8], 'finished': False}


# ------------------------------------------------------------------------------------------------------------ game events
def is_human(y, name):
    """Is it a real player (not a bot or an alien)."""
    if not name or str(name).lower() in getattr(y, 'name_index', {}):
        return False
    try:
        import community as TP
        return TP.find(name=name) is not None
    except Exception:
        return False


def from_event(y, b, name, kind, now=None):
    """Hook of from_event: an important event with a player becomes a memory; some have consequences (revenge, thanks)."""
    from . import llm
    if not llm.STRONG or kind not in TEMPLATE or not is_human(y, name):
        return None
    now = now if now is not None else y.now
    summary, t, emotion, importance = TEMPLATE[kind]
    a = add(b, name, summary.format(name=name), t, emotion, importance, now)
    if a.get('followup'):
        return a
    if kind == 'killed_me' and a['n'] >= 2 and b.o('aggression') > 0.45 and _firma(name) not in (0, b.firma) and b.permission.get('pvp', True):
        a['followup'] = set_followup('intikam', now, b.r.uniform(3, 15), 'duel')             # if hit twice: revenge
    elif kind == 'helped_me' and b.r.random() < 0.4 + 0.5 * b.o('sociability'):
        a['followup'] = set_followup('thanks', now, b.r.uniform(2, 8))
    elif kind == 'insult' and a['n'] >= 2 and b.o('rekabet') > 0.5:
        a['followup'] = set_followup('rekabet', now, b.r.uniform(5, 30))
    return a


def _firma(name):
    try:
        import community as TP
        k = TP.find(name=name)
        return int(k.profile.d['pilot'].get('factionId', 0)) if k is not None else 0
    except Exception:
        return 0


def due_followups(y, now, online):
    """[(bot, memory)]: follow-ups whose time has come and are not finished (bot and person online). Ones long overdue count as finished."""
    out = []
    for b in y.bots:
        for a in memories(b):
            t = a.get('followup')
            if not t or t.get('finished') or now < t['due']:
                continue
            if now - t['due'] > GRACE_SEC:
                t['finished'] = True                         # the opportunity passed
                continue
            if b.online and b.dead_until <= now and a['who'].lower() in online:
                out.append((b, a))
    return out


# ------------------------------------------------------------------------------------------------------------ gossip
def pick_gossip(b, now, r):
    """A player memory to tell in the bots' own chat (important, fresher than a day) or None."""
    mems = [a for a in memories(b) if a['importance'] >= 2 and now - a['t'] < 86400 and a['type'] != 'heard']
    return r.choice(mems) if mems else None


def hear_gossip(listener, narrator, a, now):
    """The bot that heard the gossip: its relationship with the person changes slightly, a low-importance "heard" memory."""
    listener.memory.event(a['who'], 'gossip_good' if a['emotion'] > 0.1 else 'gossip_bad' if a['emotion'] < -0.1 else 'sohbet', now)
    add(listener, a['who'], 'heard from %s: %s' % (narrator.name, a['summary']), 'heard', a['emotion'] * 0.5, 1, now)
