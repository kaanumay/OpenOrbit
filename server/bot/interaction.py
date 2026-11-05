"""The player's requests to the bot (group, help, clan, friendship, "come / where are you"): the decision is made by the personality-based
decision engine, the action by the tools (agent_tools.py); chat only voices the decision in the bot's own words. In normal mode patterns,
in Advanced mode the language model speaks; in both, speech and action are consistent (the small model used to say "ok" and forget the
invitation, and gave a map hint to "let's group up").

decide() -> {'intent', 'accept': True | False | None, 'action': (tool, arguments) | None, 'note': English instruction to the model,
            'pattern': (pattern, fields) | None}. apply() performs the action.
Promises (in the bot's memory, 5 min / 1 h): a bot that says "inv me" accepts the player's invitation (society.decide_group), a leader
who says "klanıma başvur" accepts the player's application (society.application_decision).
"""
import re

import map_links as H
from . import agent_tools as TL
from . import catalog as K

INTENTS = ('group', 'assist', 'clan', 'friend', 'followup', 'duel', 'quest', 'special', 'gate')
GATE_LEVEL = (8, 12)                                    # lowest level that comes to a gate filler: gates like ABG; Hades, LoW, QZ
_HARD_GATE = re.compile(r'\b(hades|low|legends? of war|qz|quarantine|kronos|kuiper|lambda|kappa|zeta)\b', re.I)
DUEL_MAP = 16                                       # 4-4: PvP map anyone can enter (meeting place suggestion)
_WHERE = re.compile(r"\b(where (are|r) (you|u)|where u at|wya|nerdesin|neredesin)\b", re.I)
_MY_CLAN = re.compile(r"\b(join (my|our|us)|my clan|our clan|klan[ıi]ma|klan[ıi]m[ıi]za|bizim klan|benim klan)\b", re.I)
GROUP_PROMISE_SEC, CLAN_PROMISE_SEC = 300, 3600


def _person(name):
    import community as TP
    return TP.find(name=name) if name else None


def make_promise(b, kind, name, now, duration=None):
    b.__dict__.setdefault('promises', {})[(kind, str(name).lower())] = now + (duration or (GROUP_PROMISE_SEC if kind == 'group' else CLAN_PROMISE_SEC))


def has_promise(b, kind, name, now):
    t = b.__dict__.get('promises', {}).get((kind, str(name).lower()))
    return t is not None and now <= t


_YES = re.compile(r"^\s*(y|ya|yes|yep|yup|yeah|sure|ok|okay|k|kk|why not|lets go|let'?s go|inv|inv me|go|evet|olur|tamam|tmm|"
                   r"tabi|tabii|hadi|gel)\b", re.I)
_NO = re.compile(r"^\s*(no|nah|nope|not now|later|hay[ıi]r|yok|olmaz|sonra)\b", re.I)


def make_offer(b, kind, name, now):
    """The bot offered the player something on its own ("shall we group"): a positive reply becomes that request, and a promise is made
    too."""
    b.__dict__.setdefault('offers', {})[str(name).lower()] = (kind, now + 600)
    make_promise(b, kind, name, now, duration=600)


def offer_reply(b, name, text, now):
    """Is the player's reply positive to the bot's open offer -> the offer's intent ('group' ...) or None. If negative, the offer is
    dropped."""
    t = b.__dict__.get('offers', {}).get(str(name).lower())
    if not t or now > t[1]:
        return None
    if _NO.search(text or ''):
        del b.offers[str(name).lower()]
        return None
    if _YES.search(text or ''):
        del b.offers[str(name).lower()]
        return t[0]
    return None


def _result(intent, accept, not_, template=None, action=None):
    return {'intent': intent, 'accept': accept, 'not': not_, 'template': template, 'action': action}


def decision(y, b, intent, name, who, game_map, text, now, mailer=False):
    """mail: the request came by mail (the reply comes minutes later; for a group not an immediate invitation, a promise)."""
    if intent == 'group':
        return _group(y, b, name, who, now, mailer)
    if intent == 'quest':
        k = _group(y, b, name, who, now, mailer)          # quest help = grouping: an alien killed by the group counts for everyone's quest
        k['intent'] = 'quest'
        k['not'] = 'He asks for help with his quest; in a group every kill counts for everyone\'s quest. ' + k['not']
        return k
    if intent == 'duel':
        return _duel(y, b, name, who, game_map, now)
    if intent == 'gate':
        return _gate(y, b, name, who, now, text)
    if intent == 'special':
        return _private(y, b, name, who, now)
    if intent == 'followup':
        return _follow(y, b, name, who, game_map, text, now)
    if intent == 'friend':
        return _friend(y, b, name, who, now)
    if intent == 'clan':
        return _clan(y, b, name, who, text, now)
    return None


# ------------------------------------------------------------------------------------------------------------ group
def _group(y, b, name, who, now, mailer=False):
    import group as GR
    from . import society
    if not y.permission('group'):
        return _result('group', False, 'You decided to DECLINE (you play solo). Say no in your own words.', ('reply_no', {}))
    o = _person(name)
    other_uid = o.uid if o is not None else int(who.get('id') or 0)
    bg, other_group = GR.group_of(b.uid), (GR.group_of(other_uid) if other_uid else None)
    if bg is not None and other_uid in bg.members:
        return _result('group', None, 'You are ALREADY in a group with him: no invite needed, just answer as his teammate.')
    i_am_leader = bg is not None and bg.leader == b.uid and len(bg.members) < GR.MAX_COUNT
    if bg is not None and not (i_am_leader and other_group is None):
        return _result('group', False, 'You are already in another group, so you DECLINE. Say so in your own words.',
                      ('already_in_group', {}))
    if not society.decide_group(y, b, name, other_uid, now):
        return _result('group', False, 'You decided to DECLINE (busy or not in the mood). Say no in your own words, maybe a short '
                                     'reason.', ('reply_no', {}))
    if mailer:
        make_promise(b, 'group', name, now, duration=6 * 3600)       # by mail: the invitation is theirs, they accept when met in the game
        return _result('group', True, 'You decided to ACCEPT: tell him to invite you (or whisper you) when you are both online, you '
                                    'will join his group.', ('inv_me', {}))
    if other_group is not None or o is None or o.session is None:
        make_promise(b, 'group', name, now)                      # if they are in the group (or offline) the invitation is theirs: they accept on arrival
        return _result('group', True, 'You decided to ACCEPT, but HE has to invite you (he is already in a group or offline): tell '
                                    'him to send you an invite (inv me) and you will join.', ('inv_me', {}))
    return _result('group', True, 'You decided to ACCEPT: you are sending him a group invite right now. Say yes in your own words '
                                '(he should accept your invite).', ('invite_sent', {}), ('group_invite', {'name': name}))


# ------------------------------------------------------------------------------------------------------------ gate filler
def _gate(y, b, name, who, now, text=''):
    """"Need fillers for Hades": a bot with enough level that is willing says "inv me" and promises (the invitation is theirs: once in the
    group it enters the gate with you, ship.gate_tick). When not at the gate a group is formed; when the player enters the gate the bots
    in the group come too."""
    if not (y.permission('gate_filler') and y.permission('group')):
        return _result('gate', False, 'You decided NOT to join (busy). Say no in your own words.', ('reply_no', {}))
    if b.level < GATE_LEVEL[bool(_HARD_GATE.search(text or ''))]:
        return _result('gate', False, 'Your ship is too weak for that gate: say so in your own words.', ('cant_come', {}))
    if b.target is not None and b.target.name in ('gate', 'mod', 'duel', 'pvp_match'):
        return _result('gate', False, 'You are busy in your own gate/event now: say so.', ('reply_no', {}))
    fac = int(who.get('factionId') or 0)
    p = 0.3 + 0.35 * b.o('sociability') + 0.35 * b.o('ambition') + 0.6 * b.memory.relation(name, now) - 0.3 * b.mood['fatigue']
    if fac and fac != b.company:
        p -= 0.6
    if b.r.random() >= p:
        return _result('gate', False, 'You decided NOT to join his gate. Say it in your own words.', ('reply_no', {}))
    make_promise(b, 'group', name, now, duration=1200)                # accepts when invited
    return _result('gate', True, 'You ACCEPT to fill his gate: tell him to invite you (inv me), you will jump in with him.',
                  ('inv_me', {}))


# ------------------------------------------------------------------------------------------------------------ private message
def _private(y, b, name, who, now):
    """"PM me": a willing bot writes its reply as a whisper instead of to the channel ('fisilti': the chat and LLM paths look at it)."""
    if not y.permission('chat'):
        return None
    fac = int(who.get('factionId') or 0)
    p = 0.3 + 0.5 * b.o('sociability') + 0.3 * b.o('helpfulness') + 0.6 * b.memory.relation(name, now) - (0.3 if fac and fac != b.company
                                                                                                        else 0)
    if b.r.random() >= p:
        return None
    k = _result('special', True, 'He asked someone to send him a private message: you WHISPER him now (this line goes to him '
                              'privately): a short opener like asking what he needs.', ('pm_reply', {}))
    k['whisper'] = True
    return k


# ------------------------------------------------------------------------------------------------------------ duel
def _duel(y, b, name, who, game_map, now):
    """In response to a challenge: a bot from another company, aggressive and competitive, with enough power accepts; the meeting place is
    its map (if the bot can enter it) or the map named, otherwise 4-4. A bot from the same company does not duel (cannot attack its own
    company)."""
    fac = int(who.get('factionId') or 0)
    if fac == b.company:
        return _result('duel', False, 'He is in YOUR company: you cannot fight your own company, say so (or joke about it).',
                      ('duel_same', {}))
    if not (y.permission('pvp') and y.permission('attack_player')):
        return _result('duel', False, 'You decided NOT to fight him now. Say it in your own words.', ('duel_refuse', {}))
    o = _person(name)
    if o is None or o.session is None:
        return None
    player_level = int(o.profile.d['pilot'].get('level', 1))
    p = 0.05 + 0.5 * b.o('aggression') + 0.25 * b.o('rivalry') + 0.3 * b.mood['anger'] - 0.5 * b.memory.relation(name, now) \
        - 0.07 * max(0, player_level - b.level) + 0.03 * max(0, b.level - player_level)
    if b.target is not None and b.target.name in ('quest', 'mod', 'gate', 'group', 'pvp_match'):
        p -= 0.25
    if b.r.random() >= p:
        return _result('duel', False, 'You decided NOT to fight him (busy or not worth it). Answer in character: a short taunt '
                                       'or a lazy no.', ('duel_refuse', {}))
    candidates = [TL._game_map(game_map) if game_map else None, int(o.profile.d['position'].get('mapId', 0)), DUEL_MAP]
    m = next((m for m in candidates if m and m in K.MAPS and K.can_enter(m, b.company, b.level)
              and K.route(b.game_map, m, b.company, b.level)), None)
    if m is None:
        return _result('duel', False, 'You would fight him but you cannot reach him (level too low): say so.', ('cant_come', {}))
    return _result('duel', True, 'You ACCEPT the fight: you are flying to %s to find and attack him. Say it in your own words '
                                  '(a short confident line naming %s).' % (H.name(m), H.name(m)),
                  ('duel_accept', {'map': H.name(m)}), ('duel', {'name': name, 'map': H.name(m)}))


# ------------------------------------------------------------------------------------------------------------ follow
def _follow(y, b, name, who, game_map, text, now):
    here = H.name(b.game_map)
    if _WHERE.search(text or ''):
        if not re.match(r'^[1-5]-[1-8]$', str(here)):         # a gate / instance map has no name people use ("on 499")
            return _result('followup', None, 'He asks where you are: you are inside a galaxy gate. Tell him.', ('used_in_gate', {}))
        return _result('followup', None, 'He asks where you are: you are on %s. Tell him (just the map, no status report).' % here,
                      ('used_in', {'map': here}))
    o = _person(name)
    m = TL._game_map(game_map) if game_map else (int(o.profile.d['position'].get('mapId', 0)) if o is not None else None)
    if not m or m not in K.MAPS:
        return _result('followup', None, 'He wants you to come but you do not know where he is: ask him which map.')
    if m == b.game_map:
        return _result('followup', True, 'You are already on %s too: say so (he can find you there).' % here,
                      ('used_in', {'map': here}))
    if not K.can_enter(m, b.company, b.level) or not K.route(b.game_map, m, b.company, b.level):
        return _result('followup', False, 'You CANNOT go to %s (your level is too low or it is enemy land): say so.' % H.name(m),
                      ('cant_come', {}))
    from . import society
    fac = int(who.get('factionId') or 0)
    p = 0.2 + 0.5 * b.o('helpfulness') + 0.6 * b.memory.relation(name, now) - 0.3 * b.mood['fatigue']
    if fac and fac != b.company:
        p -= 0.6
    if b.target is not None and b.target.name in ('quest', 'mod', 'gate'):
        p -= 0.2
    if _in_group(b, name):
        p += 0.4                                         # a group mate is calling
    if b.r.random() >= p:
        return _result('followup', False, 'You decided NOT to come (busy with your own thing). Say it in your own words.',
                      ('reply_no', {}))
    return _result('followup', True, 'You decided to COME: you are flying to %s now. Say it in your own words.' % H.name(m),
                  ('coming', {'map': H.name(m)}), ('hunt_npcs', {'map': H.name(m)}))


def _in_group(b, name):
    import group as GR
    o = _person(name)
    g = GR.group_of(b.uid)
    return g is not None and o is not None and o.uid in g.members


# ------------------------------------------------------------------------------------------------------------ friendship
def _friend(y, b, name, who, now):
    import contacts as CT
    from . import society
    if not y.permission('friend'):
        return _result('friend', False, 'You decided to DECLINE. Say no in your own words.', ('reply_no', {}))
    r = CT.save(society.profile(b))
    if CT._var(r.get('friend', []), name):
        return _result('friend', None, 'You are already friends with him: say so.')
    p = 0.25 + 0.5 * b.o('sociability') + 0.7 * b.memory.relation(name, now)
    fac = int(who.get('factionId') or 0)
    if fac and fac != b.company:
        p -= 0.3
    if b.r.random() >= p:
        return _result('friend', False, 'You decided NOT to add him (you barely know him). Say it in your own words, not rude.',
                      ('reply_no', {}))
    tool = 'friend_accept' if CT._var(r.get('incoming', []), name) else 'add_friend'
    return _result('friend', True, 'You decided YES: you %s now. Say it in your own words.' % (
        'accept his friend request' if tool == 'friend_accept' else 'send him a friend request'),
        ('friend_done', {}), (tool, {'name': name}))


# ------------------------------------------------------------------------------------------------------------ clan
def _clan(y, b, name, who, text, now):
    import clan as KL
    from . import society
    bot_clan = KL.clan_of(society.profile(b))
    o = _person(name)
    ok = KL.clan_of(o.profile) if o is not None else None
    if ok is not None and _MY_CLAN.search(text or ''):   # "klanıma gel": does it apply
        if bot_clan is not None:
            return _result('clan', False, 'You are already in the clan [%s] %s and stay loyal: decline in your own words.' % (
                bot_clan['tag'], bot_clan['name']), ('clan_member', {'tag': bot_clan['tag'], 'leader': bot_clan['leader']}))
        if not y.permission('clan') or society.clan_company(ok) not in (0, b.company):
            return _result('clan', False, 'You decided NOT to join his clan. Say it in your own words.', ('reply_no', {}))
        p = 0.15 + 0.4 * b.o('sociability') + 0.7 * b.memory.relation(name, now) - 0.03 * max(0, b.level - int(
            o.profile.d['pilot'].get('level', 1)) - 4)
        if b.r.random() >= p:
            return _result('clan', False, 'You decided NOT to join his clan (not now). Say it in your own words.', ('reply_no', {}))
        return _result('clan', True, 'You decided to JOIN his clan [%s]: you are sending an application now. Say it in your own words.'
                      % ok['tag'], ('applied_to_clan', {}), ('apply_to_clan', {'clan': ok['tag']}))
    if bot_clan is None:
        return _result('clan', None, 'You are not in any clan yourself: say so (maybe you are looking too).', ('no_clan', {}))
    if bot_clan['leader'] == b.name.lower():
        make_promise(b, 'clan', name, now)                       # if it applies, accepts
        return _result('clan', True, 'You LEAD the clan [%s] %s and you are recruiting: tell him to apply, you will accept him.' % (
            bot_clan['tag'], bot_clan['name']), ('clan_apply', {'tag': bot_clan['tag']}))
    leader = bot_clan['members'].get(bot_clan['leader'], {}).get('name') or bot_clan['leader']
    return _result('clan', None, 'You are a member of [%s] %s (leader: %s): tell him he can apply there.' % (
        bot_clan['tag'], bot_clan['name'], leader), ('clan_member', {'tag': bot_clan['tag'], 'leader': leader}))


# ------------------------------------------------------------------------------------------------------------ apply
def apply(y, b, k, delay=0.0):
    """The decision's action (if any) -> tool result. delay: performs it after writing its reply (writes "sure" and then sends the
    invitation; the invitation must not come before the reply); enters the chat engine's action queue."""
    if not k or not k.get('action'):
        return None
    if delay > 0 and hasattr(y, 'actions'):
        y.actions.append((y.now + delay, b, k['action']))
        return None
    return TL.call(y, b, *k['action'])
