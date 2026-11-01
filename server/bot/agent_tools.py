"""The bot's actions (tools): the decision engine, chat and the LLM (Advanced mode) make the bot do things only through these tools.

Each tool: name, description, parameters (JSON schema; given to the LLM), permission (the pack's access setting) and function (y, bot, **arg) ->
{'ok': bool, 'message': str}. Tools that change the goal set the bot's intent (brain.force): the bot carries on the job with its own judgment, and if it
is interrupted the decision engine takes over. For a new action it is enough to add a function here with @tool; the schema goes to the LLM by itself.
"""
import map_links as H
from . import brain as B
from . import catalog as K

TOOLS = {}


def tool(name, description, parameters=None, permission=None):
    def save(fn):
        TOOLS[name] = dict(name=name, description=description, parameters=parameters or {}, permission=permission, fn=fn)
        return fn
    return save


def schema(y=None, names=None):
    """The tool list for the LLM: [{name, description, parameters}] (except those whose permission is off)."""
    out = []
    for a in TOOLS.values():
        if names is not None and a['name'] not in names:
            continue
        if a['permission'] and y is not None and not y.permission(a['permission']):
            continue
        out.append({'name': a['name'], 'description': a['description'], 'parameters': a['parameters']})
    return out


def call(y, bot, name, arg=None):
    """Run the tool -> {'ok', 'message'}. An unknown tool, a disabled permission or a bad argument returns an error (the bot does nothing)."""
    a = TOOLS.get(str(name or ''))
    if a is None:
        return {'ok': False, 'message': 'unknown tool'}
    if a['permission'] and y is not None and not y.permission(a['permission']):
        return {'ok': False, 'message': 'permission off'}
    try:
        r = a['fn'](y, bot, **{k: v for k, v in (arg or {}).items() if k in a['parameters']})
    except (TypeError, ValueError, KeyError) as e:
        return {'ok': False, 'message': 'bad argument: %s' % e}
    except Exception as e:                                  # an error inside a tool (AttributeError...) must not take down the rest of the chat tick
        return {'ok': False, 'message': 'tool error: %r' % e}
    bot.event('tool', y.now if y is not None else None, name=name, result=r.get('ok'))
    return r


def _game_map(name):
    from .speech import MAP_RE
    ids = {v.lower(): k for k, v in H.NAMES.items()}
    s = str(name or '').strip().lower()
    r = MAP_RE.search(s)
    m = ids.get(s) or (ids.get('%s-%s' % (r.group(1), r.group(2))) if r else None)
    return int(m) if m is not None and int(m) in K.MAPS else None


def _ok(m=''):
    return {'ok': True, 'message': m}


def _error(m):
    return {'ok': False, 'message': m}


# ------------------------------------------------------------------------------------------------------------ targets
@tool('hunt_npcs', 'Farm aliens (on the given map if one is given).', {'map': 'string, e.g. "1-3" (optional)'})
def hunt_npcs(y, bot, map=None):
    m = _game_map(map) if map else None
    if map and (m is None or not K.can_enter(m, bot.company, bot.level)):
        return _error('cannot enter that map')
    B.force(bot, 'grinding', plan={'map': m} if m else {}, pay=0.8, now=y.now if y else None)
    return _ok()


@tool('hunt_pvp', 'Go hunting players of enemy companies.', {}, permission='pvp')
def hunt_pvp(y, bot):
    B.force(bot, 'pvp', pay=0.8, now=y.now if y else None)
    return _ok()


@tool('do_quest', 'Continue the quest chain.', {}, permission='quest')
def do_quest(y, bot):
    B.force(bot, 'quest', pay=0.8, now=y.now if y else None)
    return _ok()


@tool('go_shopping', 'Buy the best upgrade if you can afford it.', {}, permission='shop')
def go_shopping(y, bot):
    from .goals import shopping as SHOP
    c = SHOP.candidate(bot)[0]
    if c is None:
        return _error('nothing to buy or not enough money')
    if bot.pay(c[1], c[2]):
        bot.add(c[3])
        bot.event('purchase', y.now if y else None, item=c[3], price=c[2], currency=c[1])
        if c[3].startswith('ship_'):
            bot.event('new_ship', y.now if y else None, item=c[3])
        return _ok(c[3])
    return _error('not enough money')


@tool('rest', 'Go back to base and rest / chat for a while.', {})
def rest(y, bot):
    B.force(bot, 'resting', pay=0.8, duration=900, now=y.now if y else None)
    return _ok()


@tool('go_help', 'Fly to the map of the player who asked for help and fight the enemies there.', {'map': 'string, e.g. "2-4"', 'name': 'string: who asked for help'},
      permission='assist')
def go_help(y, bot, map=None, name=''):
    m = _game_map(map) if map else None
    if m is None and name:
        import community as TP
        k = TP.find(name=name)
        m = int(k.profile.d['position'].get('mapId', 0)) if k is not None else None
    if m is None or m not in K.MAPS or not K.can_enter(m, bot.company, bot.level) or not K.route(bot.game_map, m, bot.company, bot.level):
        return _error('cannot go there')
    B.force(bot, 'assist', plan={'map': m, 'name': name}, pay=1.2, duration=900, now=y.now if y else None)
    if name:
        bot.memory.event(name, 'i_helped', y.now if y else None)
    return _ok(H.name(m))


@tool('duel', 'Find the player who challenged you on the meeting map and fight.', {'name': 'string', 'map': 'string, e.g. "4-4"'},
      permission='pvp')
def duel(y, bot, name='', map=None):
    m = _game_map(map) if map else None
    if not name or m is None or not K.can_enter(m, bot.company, bot.level) or not K.route(bot.game_map, m, bot.company, bot.level):
        return _error('cannot go there')
    B.force(bot, 'duel', plan={'map': m, 'name': name}, pay=1.5, duration=900, now=y.now if y else None)
    bot.memory.event(name, 'challenge', y.now if y else None)
    return _ok(H.name(m))


@tool('go_offline', 'Log out of the game (end the session).', {})
def go_offline(y, bot):
    bot.session_end = y.now if y else 0
    return _ok()


# ------------------------------------------------------------------------------------------------------------ social
@tool('write_chat', 'Write in a chat channel.', {'channel': 'global | company | clan | group', 'text': 'string'}, permission='chat')
def write_chat(y, bot, channel='company', text=''):
    if channel not in ('global', 'company', 'clan', 'group') or not str(text).strip():
        return _error('invalid channel or text')
    y.speak(bot, channel, str(text).strip()[:200])
    return _ok()


@tool('whisper', 'Send someone a private message.', {'name': 'string', 'text': 'string'}, permission='chat')
def whisper(y, bot, name='', text=''):
    if not name or not str(text).strip():
        return _error('no name or text')
    y.speak(bot, 'whisper', str(text).strip()[:200], recipient=name)
    return _ok()


@tool('group_invite', 'Invite a player to your group.', {'name': 'string'}, permission='group')
def group_invite(y, bot, name=''):
    import group as GR
    from . import society
    out = GR.handle(society.person(bot), 'InvitationCreationRequest', {'name': name})
    error = next((m[1].get('error') for m in out or () if m[0] == 'InvitationErrorCommand'), None)
    if error is not None:                               # the player is in another group, offline, invitation limit ...: stays as words
        from . import interaction as IX
        IX.make_promise(bot, 'group', name, y.now if y else 0)
        reason = {GR.GROUP_FULL: 'the group is full', GR.CANDIDATE_IN_GROUP: 'they are already in a group', GR.CANDIDATE_NONEXISTENT: 'they are not online',
                 GR.BOSS_ONLY: 'only the group leader can invite', GR.MAX_INVITER: 'you have too many pending invitations',
                 GR.MAX_CANDIDATE: 'they have too many pending invitations', GR.CANDIDATE_BLOCKING: 'they blocked you',
                 GR.DUPLICATE_INVITATION: 'your invitation was already sent, waiting for an answer'}.get(error, 'error %s' % error)
        return _error('invitation not sent: %s' % reason)
    return _ok()


@tool('leave_group', 'Leave the group.', {}, permission='group')
def leave_group(y, bot):
    import group as GR
    from . import society
    if GR.group_of(bot.uid) is None:
        return _error('not in a group')
    GR.handle(society.person(bot), 'LeaveGroupRequest', {})
    return _ok()


@tool('add_friend', 'Send a friend request.', {'name': 'string'}, permission='friend')
def add_friend(y, bot, name=''):
    import contacts as CT
    from . import society
    CT.handle(society.person(bot), 'ContactRequest', {'contactRequestType': CT.CREATE, 'userName': name})
    bot.memory.event(name, 'friend', y.now if y else None)
    return _ok()


@tool('friend_accept', 'Accept an incoming friend request.', {'name': 'string'}, permission='friend')
def accept_friend(y, bot, name=''):
    import contacts as CT
    from . import society
    CT.handle(society.person(bot), 'ContactRequest', {'contactRequestType': CT.ACCEPT, 'userName': name})
    bot.memory.event(name, 'friend', y.now if y else None)
    return _ok()


@tool('send_mail', 'Send someone in-game mail.', {'name': 'string', 'subject': 'string', 'text': 'string'}, permission='chat')
def send_mail(y, bot, name='', subject='', text=''):
    import mail as PS
    from . import society
    subject, text = str(subject).strip()[:50], str(text).strip()[:1500]
    if not name or len(subject) < 3 or len(text) < 5:
        return _error('name, subject or text missing')
    out = PS.Mail(society.profile(bot), log=lambda *_: None).handle('UserMessageSendRequest', {
        'recipients': [name], 'subject': subject, 'body': text, 'recipientType': 'user'})
    return _ok() if out and out[0][1].get('success') else _error('could not be sent')


@tool('follow', 'Fly to the map the player is on and hunt next to them.', {'name': 'string'})
def follow(y, bot, name=''):
    import community as TP
    k = TP.find(name=name)
    if k is None:
        return _error('no such player')
    return hunt_npcs(y, bot, map=H.name(int(k.profile.d['position'].get('mapId', bot.game_map))))


@tool('apply_to_clan', 'Apply to a clan.', {'clan': 'string: the clan name or tag'}, permission='clan')
def apply_to_clan(y, bot, clan=''):
    import clan as KL
    from . import society
    c = next((c for c in KL.CLANS.values() if str(clan).lower() in (c['name'].lower(), c['tag'].lower())), None)
    if c is None:
        return _error('no such clan')
    out = KL.Clan(society.profile(bot)).handle('ApplyClanRequest', {'clanId': c['id'], 'message': 'lvl %d' % bot.level})
    society.update(bot)
    return _ok() if out and out[0][1].get('success') else _error('could not apply')


# ------------------------------------------------------------------------------------------------------------ clan management
# (clan_management.py; the leader or a member with the right: the game's clan requests check the rights themselves)
def _clan(bot):
    import clan as KL
    from . import society
    k = KL.clan_of(society.profile(bot))
    return k, (KL.Clan(bot.profile, log=lambda *_: None) if k else None)


def _result(out, ok='', error='not done (no right or invalid)'):
    if out and out[0][1].get('success'):
        return _ok(ok)
    e = out[0][1].get('errorMsg') if out else None
    return _error(error if not isinstance(e, dict) or not e.get('stringBasekey') else '%s: %s' % (error, e['stringBasekey']))


@tool('clan_description', 'Write the clan description (leader only).', {'text': 'string, at most 2000 characters'}, permission='clan')
def clan_description(y, bot, text=''):
    k, kl = _clan(bot)
    if k is None or not str(text).strip():
        return _error('you have no clan or the text is empty')
    return _result(kl.handle('ChangeClanDescriptionRequest', {'desc': str(text).strip()[:2000]}))


@tool('clan_announce', 'Post an announcement to the clan news.', {'text': 'string'}, permission='clan')
def clan_announce(y, bot, text=''):
    k, kl = _clan(bot)
    if k is None or not str(text).strip():
        return _error('you have no clan or the text is empty')
    return _result(kl.handle('ClanAddNewsRequest', {'newsMessage': str(text).strip()[:500]}))


@tool('clan_mail', 'Send mail to the whole clan.', {'subject': 'string', 'text': 'string'}, permission='clan')
def clan_mail(y, bot, subject='', text=''):
    k, kl = _clan(bot)
    if k is None or not str(subject).strip() or not str(text).strip():
        return _error('you have no clan or the subject/text is empty')
    return _result(kl.handle('ClanSendAllMessageRequest', {'subject': str(subject).strip()[:50], 'msgText': str(text).strip()[:1500]}))


@tool('clan_rank', 'Add or delete a rank, or change its rights.', {
    'operation': 'add | delete | rights', 'rank': 'string: the rank name',
    'rights': 'string: comma-separated rights (hiremember, firemember, editranks, news, roundmail, tax, payout, diplo_start, diplo_end, '
              'diplo_war, battle_station_build, battle_station_replace_module, battle_station_deflector)'}, permission='clan')
def clan_rank(y, bot, operation='add', rank='', rights=''):
    import clan as KL
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None or not str(rank).strip():
        return _error('you have no clan or the rank name is empty')
    right = [h.strip() for h in str(rights or '').split(',') if h.strip() in KL.RIGHTS]
    if operation == 'add':
        out = kl.handle('ClanNewRankRequest', {'newRank': str(rank).strip()[:30]})
        r = CMG.find_rank(k, rank)
        if out and out[0][1].get('success') and r is not None and right:
            kl.handle('EditClanRanksRequest', {'ranks': [{'rankId': r['id'], 'rankName': r['name'], 'rights': right}]})
        return _result(out, 'rank added')
    r = CMG.find_rank(k, rank)
    if r is None:
        return _error('no such rank')
    if operation == 'delete':
        return _result(kl.handle('ClanDeleteRankRequest', {'deleteRankId': r['id']}), 'rank deleted')
    if operation == 'rights':
        return _result(kl.handle('EditClanRanksRequest', {'ranks': [{'rankId': r['id'], 'rankName': r['name'], 'rights': right}]}),
                      'rights: %s' % (', '.join(right) or 'none'))
    return _error('operation must be add, delete or rights')


@tool('member_rank', 'Give a member a rank (empty rank: take their rank away).', {'name': 'string: the member', 'rank': 'string: the rank name'}, permission='clan')
def member_rank(y, bot, name='', rank=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('you have no clan')
    a, u = CMG.find_member(k, name)
    r = CMG.find_rank(k, rank) if str(rank or '').strip() else {'id': 0}
    if u is None or r is None:
        return _error('no such member or rank')
    return _result(kl.handle('EditClanMemberRequest', {'rankId': r['id'], 'memberId': int(u.get('uid', 0))}))


@tool('kick_member', 'Kick a member out of the clan.', {'name': 'string'}, permission='clan')
def kick_member(y, bot, name=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('you have no clan')
    result = CMG.kick(y, bot, k, kl, y.now if y else 0, name=name)
    return _ok('%s kicked' % result) if result else _error('could not kick (no right or not a member)')


@tool('transfer_leadership', 'Hand the clan leadership over to a member.', {'name': 'string'}, permission='clan')
def transfer_leadership(y, bot, name=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('you have no clan')
    result = CMG.hand_over(y, bot, k, kl, y.now if y else 0, name=name)
    return _ok('the leader is now %s' % result) if result else _error('could not hand over (you are not the leader or they are not a member)')


@tool('clan_tax', 'Set the clan tax (percent, 0-5).', {'ratio': 'integer'}, permission='clan')
def clan_tax(y, bot, ratio=0):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('you have no clan')
    return _ok('tax %d%%' % int(ratio)) if CMG.set_tax(bot, k, kl, y.now if y else 0, ratio=int(ratio)) else _error('you have no tax right')


@tool('clan_budget', 'Split the treasury (percent; at most 90 in total, the rest is a reserve): battle station, payments to members, war.',
      {'cbs': 'integer', 'payment': 'integer', 'combat': 'integer'}, permission='clan')
def clan_budget(y, bot, cbs=None, payment=None, combat=None):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None or k['leader'] != bot.name.lower():
        return _error('leader only')
    b = CMG.set_budget(bot, k, y.now if y else 0, *[None if v is None else max(0, int(v)) / 100.0 for v in (cbs, payment, combat)])
    return _ok('station %d%%, payments %d%%, war %d%%' % (100 * b['cbs'], 100 * b['payment'], 100 * b['combat']))


@tool('clan_payout', 'Pay a member credits from the treasury.', {'name': 'string', 'amount': 'integer'}, permission='clan')
def clan_payout(y, bot, name='', amount=0):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('you have no clan')
    a, u = CMG.find_member(k, name)
    if u is None:
        return _error('no such member')
    return _result(kl.handle('PayoutClanRequest', {'amount': int(amount), 'payoutUserId': int(u.get('uid', 0)), 'reason': 'payout'}),
                  'paid', 'not paid (no right, not enough in the treasury or the member reached the weekly limit)')


@tool('clan_station', 'Choose the free asteroid where the clan builds its battle station (by name; modules are paid from the treasury, from the station share of the budget).',
      {'station': 'string: the asteroid name'}, permission='clan_cbs')
def clan_station(y, bot, station=''):
    from . import clan_stations as CBA
    k, kl = _clan(bot)
    if k is None or not CBA.is_open() or not kl.right('battle_station_build', k):
        return _error('you have no right to build a station')
    return _ok('target: %s' % station) if CBA.set_target(k, station, bot) else _error('no such free asteroid')


_DIPLO = {'peace': 0, 'alliance': 1, 'non_aggression': 2, 'nap': 2, 'war': 3}


@tool('clan_diplomacy', 'Offer another clan an alliance, a non-aggression pact, war or peace.',
      {'clan': 'string: the clan name or tag', 'type': 'alliance | non_aggression | war | peace', 'text': 'string'}, permission='clan_diplomacy')
def clan_diplomacy(y, bot, clan='', type='', text=''):
    import clan as KL
    k, kl = _clan(bot)
    c = next((c for c in KL.CLANS.values() if str(clan).lower() in (c['name'].lower(), c['tag'].lower())), None)
    if k is None or c is None or str(type).lower() not in _DIPLO:
        return _error('you have no clan, no such clan or an invalid type')
    return _result(kl.handle('ClanNewDiplomacyRequest', {'diploClanID': c['id'], 'diploForm': _DIPLO[str(type).lower()],
                                                        'desc': str(text or '').strip()[:200]}), 'offer sent')


@tool('diplomacy_reply', 'Accept or decline a diplomacy offer made to your clan.', {'clan': 'string', 'accept': 'boolean'},
      permission='clan_diplomacy')
def diplomacy_reply(y, bot, clan='', accept=False):
    import clan as KL
    k, kl = _clan(bot)
    if k is None:
        return _error('you have no clan')
    s = str(clan).lower()
    r = None
    for x in k.get('diplomacy_requests', []):
        o = KL.CLANS.get(x['from_clan']) or {}
        if x['to'] == k['id'] and s in (str(o.get('name', '')).lower(), str(o.get('tag', '')).lower()):
            r = x
            break
    if r is None:
        return _error('no pending offer from that clan')
    return _result(kl.handle('ClanEditDiploOfferRequest', {'diploId': r['id'], 'status': 'allow' if accept in (True, 'true', 1) else 'deny'}))


@tool('none', 'Do nothing.', {})
def none_(y, bot):
    return _ok()


# ------------------------------------------------------------------------------------------------------------ the agent's tools
# (Advanced mode, strong provider: bot/agent.py offers them to the model; the decision engine can call them too)
def _item(bot, item):
    """Shop candidate (gain, currency, price, loot): matches the full loot or its ending ("lf-2", "goliath")."""
    from .goals import shopping as SHOP
    s = str(item or '').strip().lower()
    if not s:
        return None
    m = bot.game_settings.multiplier('shop_price')
    for a, p, f, l in SHOP.candidates(bot):
        if l.lower() == s or l.lower().rsplit('_', 1)[-1] == s:
            return a, p, f * m, l
    return None


@tool('buy_item', 'Buy a specific upgrade from the shop (the name in the shop list).', {'item': 'string: the item name'}, permission='shop')
def buy_item(y, bot, item=''):
    c = _item(bot, item)
    if c is None:
        return _error('not in the shop list (or no slot for it / something better is equipped)')
    currency = {'C': bot.k['credits'], 'U': bot.k['uridium']}[c[1]]
    if currency < c[2]:
        return _error('not enough money: %d %s needed, you have %d' % (c[2], c[1], currency))
    if not bot.pay(c[1], c[2]):
        return _error('not enough money')
    bot.add(c[3])
    bot.ist('purchase')
    bot.event('purchase', y.now if y else None, item=c[3], price=c[2], currency=c[1])
    if c[3].startswith('ship_'):
        bot.event('new_ship', y.now if y else None, item=c[3])
    if bot.k.get('savings') == c[3]:
        bot.k['savings'] = None                         # bought what it had been saving for
    return _ok('bought %s (%d %s)' % (c[3], c[2], c[1]))


@tool('save_up', 'Save up for an upgrade (shopping spends on nothing else); an empty name clears the goal.', {'item': 'string'},
      permission='shop')
def save_up(y, bot, item=''):
    if not str(item or '').strip():
        bot.k['savings'] = None
        return _ok('saving goal cleared')
    c = _item(bot, item)
    if c is None:
        return _error('not in the shop list')
    bot.k['savings'] = c[3]
    bot._candidates = None
    bot._savings_woke = False                         # when the money is complete the agent wakes up once (agent.wakers)
    return _ok('saving up for %s (%d %s)' % (c[3], c[2], c[1]))


@tool('pick_quest', 'Take a specific quest from the available ones (when you have no quest).', {'quest': 'string: the quest name or number'},
      permission='quest')
def pick_quest(y, bot, quest=''):
    from .goals import quest as QU
    if bot.k.get('quest'):
        return _error('a quest is already running: %s' % QU.quests().get(bot.k['quest']['id'], {}).get('name', '?'))
    s = str(quest or '').strip().lower().lstrip('#')
    for qid, q in QU.eligible(bot):
        if s in (str(qid), str(q.get('name', '')).lower()):
            bot.k['quest'] = dict(id=qid, conditions={})
            if not (QU.next_up(bot) or (None, None))[1]:
                bot.k['quest'] = None
                return _error('this quest\'s place cannot be reached right now')
            bot.event('quest_taken', y.now if y else None, name=q.get('name'))
            B.force(bot, 'quest', pay=0.9, now=y.now if y else None)
            return _ok('quest taken: %s' % q.get('name'))
    return _error('not among the available quests')


@tool('sell_cargo', 'Sell the ore in your cargo at the nearest station.', {}, permission='cargo')
def sell_cargo(y, bot):
    if bot.cargo_fill() <= 0:
        return _error('cargo is empty')
    B.force(bot, 'selling', pay=1.0, duration=900, now=y.now if y else None)
    return _ok()


@tool('enter_mode', 'Enter an open mode (event / PvE): pays the entry and goes to the mode map.', {'mod': 'string: the mode name'},
      permission='modes')
def enter_mode(y, bot, mod=''):
    from . import modes as MD
    now = y.now if y else None
    s = str(mod or '').strip().lower()
    m = next((m for m in MD.candidates(bot, now) if s in (m.uid.lower(), str(m.name).lower())), None)
    if m is None:
        return _error('this mode cannot be entered right now')
    bot._mode_candidate, bot._mode_next_check = m, (now or 0) + 300
    B.force(bot, 'mod', pay=1.2, duration=900, now=now)
    return _ok(m.name)


@tool('run_gate', 'Enter a built Galaxy Gate.', {}, permission='gate')
def run_gate(y, bot):
    from . import galaxy_gates as GT
    k = GT.can_run(bot)
    if bot.level < 10 or k is None:
        return _error('no built gate you can run')
    B.force(bot, 'gate', pay=1.2, duration=900, now=y.now if y else None)
    return _ok(GT.GATES[k]['name'])


@tool('session', 'Stay in the game this many more minutes (5-180).', {'minutes': 'integer'})
def session(y, bot, minutes=30):
    d = max(5, min(180, int(minutes)))
    bot.session_end = (y.now if y else 0) + d * 60
    return _ok('%d more min' % d)
