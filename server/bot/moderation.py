"""Chat moderators (player request 2026-10-31): enabled in the pack's settings; a few patient, helpful, loyal bots are moderators
(their chat role is "mod": the client draws them in the moderator color). Rules are toggled in the panel: ALL CAPS, flooding (the same
line or too fast), insults and harmful speech, ads/links. Someone who breaks a rule (human or bot; admins and moderators excluded) is
warned first, and if they break it again within 30 min they are muted for mute_min, and after ban_threshold mutes they are banned from
global and company chat for ban_hours. Only an online moderator makes the decision (as on the real server; if there is none the chat is
free), and writes to the channel after a few seconds. A muted person's global/company message is dropped on the chat server
(chat.Chat.block_hook), and the remaining time is reported to them with a system message.
"""
import math
import re
import time

from . import speech as SPC

RULES = ('caps', 'flood', 'insult', 'ads')
TAG = 'CM'                    # the label shown for the moderator in chat and above their ship (clans cannot take it: clan.is_reserved)
CHAT_ROLE = 'mod'              # in their own color via the client patch (panel/plugin/Yamalar.cs ModeratorRengi); the admin role would hide the label
WARNING_SEC = 1800                  # a second violation within this time after a warning mutes
_LINK = re.compile(r'(https?://|www\.|discord\.gg|\b[\w-]+\.(com|net|org|gg|io|ru|tr|de)\b)', re.I)
CHANNELS = ('global', 'company')
NOTICE = {'tr': 'Susturuldun: {0} dk kaldı.', 'en': 'You are muted: {0} min left.', 'de': 'Du bist stummgeschaltet: noch {0} Min.',
            'es': 'Estás silenciado: quedan {0} min.', 'fr': 'Tu es muet : encore {0} min.', 'pl': 'Jesteś wyciszony: zostało {0} min.',
            'pt': 'Você está silenciado: faltam {0} min.', 'ru': 'Вы заглушены: осталось {0} мин.'}


def is_open(y):
    return bool(y.setting('moderator', False)) and y.permission('chat')


def sec(y):
    """Pick the moderators (persistent: the same pack always gets the same bots): highest patience, helpfulness and loyalty, low
    aggression."""
    for b in y.bots:
        b.moderator = False
    if not is_open(y):
        return []
    n = int(y.setting('mod_count', 2) or 1)
    points = lambda b: b.o('patience') + b.o('helpfulness') + b.o('loyalty') - b.o('aggression') + 0.001 * (b.uid % 97)
    out = sorted(y.bots, key=points, reverse=True)[:n]
    for b in out:
        b.moderator = True
    return out


def _registry(y, name):
    return y.__dict__.setdefault('mod_record', {}).setdefault(str(name).lower(), {'warning': 0, 'warning_time': 0, 'mutes': 0, 'end_time': 0,
                                                                               'ban': False, 'last': []})


def violation(y, name, msg, now):
    """Which rule does the message break -> the rule or None (the first of the enabled rules). For flooding it keeps the person's recent
    messages."""
    k = _registry(y, name)
    k['last'] = [x for x in k['last'] if now - x[0] < 60] + [(now, str(msg).strip().lower())]
    letters = [c for c in str(msg) if c.isalpha()]
    if y.setting('rule_ads', True) and _LINK.search(msg):
        return 'ads'
    if y.setting('rule_insult', True):
        from . import llm as LLM
        if LLM.harmful(msg) or SPC.intent(msg)[0] == 'insult':
            return 'insult'
    if y.setting('rule_flood', True) and (sum(1 for t, m in k['last'] if m == k['last'][-1][1]) >= 3
                                       or sum(1 for t, m in k['last'] if now - t < 10) >= 5):
        return 'flood'
    if y.setting('rule_caps', True) and len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return 'caps'
    return None


def is_muted(y, name, now=None):
    """Remaining mute/ban time (s) or 0."""
    k = y.__dict__.get('mod_record', {}).get(str(name).lower())
    return max(0.0, k['end_time'] - (now or time.time())) if k else 0.0


def moderate(y, name, msg, channel, now, rol='chatter'):
    """A line in global/company chat (from a human or a bot): if a rule was broken, an online moderator applies the sanction ->
    sanction ('warning' | 'mute' | 'ban') or None."""
    if not is_open(y) or channel not in CHANNELS or rol in ('admin', 'mod', 'system'):
        return None
    b = y.name_index.get(str(name).lower())
    if b is not None and getattr(b, 'moderator', False):
        return None
    import admin_mode as YM
    if b is None and YM.mi(name_=name):
        return None
    rule = violation(y, name, msg, now)
    modes = [m for m in y.bots if getattr(m, 'moderator', False) and m.online]
    if rule is None or not modes:
        return None
    m = max(modes, key=lambda m: m.o('patience') * m.r.random())
    k = _registry(y, name)
    if k['end_time'] > now:
        return None                                       # already muted (the line was already dropped)
    if now - k['warning_time'] > WARNING_SEC:
        k['warning'] = 0
    delay = m.r.uniform(2, 8)
    if k['warning'] == 0:
        k['warning'], k['warning_time'] = 1, now
        y.speak(m, channel, SPC.template(m, 'mod_warning_' + rule, name=name), now=now + delay, priority=True)
        return 'warning'
    k['warning'] = 0
    k['mutes'] += 1
    if k['mutes'] >= int(y.setting('ban_threshold', 3) or 3):
        hour = int(y.setting('ban_hours', 24) or 24)
        k['end_time'], k['ban'], k['mutes'] = now + hour * 3600, True, 0
        y.speak(m, channel, SPC.template(m, 'mod_ban', name=name, hour=hour), now=now + delay, priority=True)
        return 'ban'
    minutes = int(y.setting('mute_min', 10) or 10)
    k['end_time'], k['ban'] = now + minutes * 60, False
    y.speak(m, channel, SPC.template(m, 'mod_mute', name=name, min=minutes), now=now + delay, priority=True)
    if b is not None:
        b.memory.event(m.name, 'insult', now)               # the muted bot is a bit resentful toward the moderator
    return 'mute'


def block(y, user, path, lang=None):
    """From the chat server (chat thread): should the human's global/company message be dropped -> notification text for the player or
    None."""
    if not is_open(y) or not (path.startswith('/room/global/') or path.startswith('/room/faction/')):
        return None
    remaining = is_muted(y, user.get('userId', ''))
    if remaining <= 0:
        return None
    return NOTICE.get(lang or 'en', NOTICE['en']).format(max(1, math.ceil(remaining / 60)))


def remind_rules(y, now):
    """Every so often (45-90 min) a moderator reminds the rules in global."""
    if not is_open(y) or now < y.__dict__.get('_mod_reminder', 0):
        return
    first = '_mod_reminder' not in y.__dict__
    y._mod_reminder = now + (600 if first else 2700 + 2700 * (hash(int(now)) % 100) / 100)
    if first:
        return
    modes = [m for m in y.bots if getattr(m, 'moderator', False) and m.online]
    if modes:
        m = modes[int(now) % len(modes)]
        y.speak(m, 'global', SPC.template(m, 'mod_rules'), now=now)
