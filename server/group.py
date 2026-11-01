"""Group (friend server; the client's GroupComponentSystem / UIGroupSystem): invite, accept and reject, revoking an invitation, leaving,
kicking, leadership, invite mode, ping, follow and the members' state in the group window.

Invite by name (InvitationCreationRequest: group window, chat's player menu) or by id (GroupInvitationRequest: contact list).
As on the real server:
  - InvitationInitializationCommand goes to the inviter, the candidate and the inviter's group members (the client writes "%inviter%
    invited %candidate%." for a third person). The invitation lapses after INVITE_SEC (InvitationRemovalCommand TIMEOUT), rejection REJECT, revoking REVOKE,
    acceptance ACKNOWLEDGE.
  - On acceptance, if there is no group it is created (the inviter is the leader): GroupInitializationCommand to the new member and the leader of the created group (members including
    themselves; the client compares the member with the hero's id), GroupMemberInitializationCommand to the old members.
  - Leaving and kicking send MemberLeaveCommand to everyone (to the one leaving too: the client closes the group's chat room); the next one takes the leader's place
    (LeaderChangeCommand); when fewer than two remain the group dissolves (GroupCloseCommand).
  - Ping (PingPositionRequest, PingMemberRequest) PingCommand to the members on the same map; follow (FollowRequest) HeroMoveCommand to the member's
    position (the client flies the hero there). If on another map, GroupErrorCommand.
The members' state (HP, position, target, in combat, hidden, online, level, ship) is compared every UPDATE_SEC and what changed goes with
GroupMemberUpdateCommand. When a guest connection drops the member stays "offline" (as long as their record remains on the server; if they return with the same key
the id is the same); when the record ends they drop out of the group. The group is in memory: it dissolves when the server closes.
Members on the same shared map (shared_maps.py; gate and mode maps are everyone's own copy, no sharing there):
  - They see each other everywhere on the map (shared_maps visibility: the view distance does not apply to a group member; dead, jumping, hidden still invisible).
  - The reward for an alien killed by a member is shared (world.World.tag_sharers, npc_reward; wiki "Uridium, Cr, XP and honor of kills
    shared"): members who live on the map with the killer and are not jumping receive the reward (distance does not matter; the real game's ~20 s firing
    requirement does not exist). Each sharer's reward is computed with their own multipliers, EP, honor, credits and uridium are divided by the number of sharers (rounded
    up). Loot is full for everyone and with their own chance: cargo boxes and boss chests drop separately for each member, the box belongs to its owner
    (other players do not see it, their P.E.T.s do not collect it), extra rewards (Palladium ...), boosters and the map event's drops too.
  - Quests: aliens killed by members count toward everyone's quest (wiki "All aliens killed by group members count towards our
    mission"): main, daily and weekly quests, Season/Battle Pass, event quests and Urgent Missions. Someone else's kill does not break
    the "kill this" restriction; achievements, rank, kill streak, drone EP and the event hooks (title, Hitac ...) belong to the killer.
"""
import json, os, threading, time
import community as TP
import map_links as H
from cbs import stm

MAX_COUNT = 8                    # most members in a group (real game)
INVITE_SEC = 120                # lifetime of an unanswered invitation
INVITE_MAX = 10             # a player's pending invitations (sent or received)
UPDATE_SEC = 1.0
COMBAT_SEC = 10.0               # how long counts as "in combat" after the last shot or damage taken
PING_SEC = 1.0                 # minimum between two pings
POSITION_THRESHOLD = 50               # the position of a member who has not moved this much is not sent again
# InvitationErrorCommand.error
GROUP_FULL, CANDIDATE_IN_GROUP, CANDIDATE_NONEXISTENT, INVITER_NONEXISTENT, NO_INVITATION, BOSS_ONLY, MAX_INVITER, \
    MAX_CANDIDATE, CANDIDATE_BLOCKING, DUPLICATE_INVITATION = range(10)
# InvitationRemovalCommand.reason
TIMEOUT, REVOKE, REJECT, ACKNOWLEDGE = 1, 2, 3, 4
# GroupErrorCommand.type
PING_FAILED, NO_GROUP, FOLLOW_FAILED = 0, 1, 2
MODE_LEADER, MODE_EVERYONE = 0, 1  # InvitationModeModule.mode: invitation only from the leader / from everyone
LEFT, KICKED = 1, 2        # MemberLeaveCommand.reason

REQUESTS = {'InvitationCreationRequest', 'GroupInvitationRequest', 'InvitationAcceptRequest', 'InvitationRejectRequest',
            'InvitationCancelRequest', 'LeaveGroupRequest', 'KickMemberRequest', 'ChangeLeaderRequest', 'InvitationModeRequest',
            'PingPositionRequest', 'PingMemberRequest', 'FollowRequest'}

LOCK = threading.RLock()
GROUPS = {}                  # group id -> Group
MEMBER = {}                      # player id -> group id
INVITES = {}                 # (inviter, candidate) -> last valid moment
_seq = [0]
_icon = None
_thread = None


def mod(_cls, **f):
    return dict(_=_cls, **f)


class Group:
    def __init__(self, leader):
        _seq[0] += 1
        self.id, self.leader, self.members, self.mod = _seq[0], leader, [leader], MODE_LEADER
        self.state = {}       # member -> last state sent (update)
        self.ping = {}        # member -> last ping moment


def room(gid):
    """The group's chat room (social.rooms; chat.py)."""
    return ('group', 'group', 'group_%d' % gid)


def group_of(uid):
    with LOCK:
        g = GROUPS.get(MEMBER.get(uid))
        return g


# ------------------------------------------------------------ messages
def icon(loot):
    """The ship's lootId (ship_goliath, ship_g-champion, ship_a-elite) -> ShipIcon value (unknown: DEFAULT)."""
    global _icon
    if _icon is None:
        _icon = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ship_icons.json'),
                                encoding='utf8'))['icons']
    name = str(loot or '')[5:] if str(loot or '').startswith('ship_') else str(loot or '')
    on, _, last = name.partition('-')
    base = {'a': 'AEGIS', 'c': 'CITADEL', 's': 'SPEARHEAD', 'n': 'NOSTROMO', 'g': 'GOLIATH', 'v': 'VENGEANCE', 'bb': 'BIGBOY',
             'd': 'DEFCOM', 'y': 'YAMATO'}.get(on)
    # design ships: g-champion -> GOLIATH, a-elite -> AEGIS_ELITE, n-envoy -> NOSTROMO_ENVOY, v-adept -> ADEPT
    candidates = [name.replace('-', '_').upper()] + ([base + '_' + last.replace('-', '_').upper()] if base and last else []) \
        + ([last.replace('-', '_').upper()] if on in ('g', 'v', 'bb') and last else []) + ([base] if base else [])
    return next((_icon[a] for a in candidates if a in _icon), _icon['DEFAULT'])


def npc_icon(name):
    """The alien's visible name -> ShipIcon value (achievement.ship_icons candidates; DEFAULT if not found)."""
    from achievement import ship_icons
    icon('')
    return next((_icon[a] for a in ship_icons(name) if a in _icon), _icon['DEFAULT'])


def hp(hp, hp_max, shield, shield_max, nano=0, nano_max=0):
    return mod('HealthModule', hp=int(hp), hpMax=int(hp_max), shield=int(shield), shieldMax=int(shield_max), nanoHull=int(nano),
               nanoHullMax=int(nano_max))


def ship_hp(p):
    g = p.d['ship']
    return hp(g.get('hitPoints', 0), g.get('hitMax', 0), g.get('shield', 0), g.get('shieldMax', 0), g.get('nanoHull', 0),
               g.get('maxNanoHull', 0))


def target(k, now):
    """The member's selected target (alien or player) -> TargetModule (no target: empty)."""
    w = k.world
    t = w.target if w is not None and w.running else None
    n = w.npcs.get(t) if t is not None else None
    if n is not None and n.alive:
        return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=npc_icon(n.d.get('name'))), name=str(n.d.get('name', '')),
                   health=hp(n.hp, n.d.get('hp', 0), n.shield, n.d.get('shield', 0)))
    o = TP.find(uid=t) if t is not None else None
    if o is not None and o.uid != k.uid:
        return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=icon(o.profile.ship()['lootId'])), name=o.name,
                   health=ship_hp(o.profile))
    return mod('TargetModule', shipType=mod('ShipIconModule', shipIcon=0), name='', health=hp(0, 0, 0, 0))


def position(k, now):
    p = k.profile
    w = k.world
    n = getattr(getattr(k.session, 'bot', None), 'body', None)         # bot: its ship on the map (the position in the record stays old)
    if w is not None:
        x, y = w.hero_pos(now)
    elif n is not None and n.alive:
        x, y = n.mover.pos(now)
    else:
        x, y = p.d['position'].get('x', 0), p.d['position'].get('y', 0)
    return int(p.d['position'].get('mapId', 0)), int(x), int(y)


def state(k, now):
    """The member's state in the group window: module name -> module (the parts of GroupMemberUpdateCommand)."""
    p, w = k.profile, k.world
    pl = p.d['pilot']
    m, x, y = position(k, now)
    return {'ActivityModule': mod('ActivityModule', active=w is not None),
            'ClanModule': mod('ClanModule', clanTag=str(pl.get('clanTag', '')), clanId=int(pl.get('clanId', 0) or 0)),
            'CloakDeviceActivityModule': mod('CloakDeviceActivityModule', active=bool(w is not None and w.hidden(now))),
            'FactionModule': mod('FactionModule', faction=int(pl.get('factionId', 0) or 0)),
            'FightActivityModule': mod('FightActivityModule', active=bool(w is not None and now - w.last_combat < COMBAT_SEC)),
            'HealthModule': ship_hp(p),
            'InvitationBlockModule': mod('InvitationBlockModule', active=bool(p.d.get('invite_block'))),
            'LevelModule': mod('LevelModule', level=int(pl.get('level', 1))),
            'LocationModule': mod('LocationModule', mapId=m, x=x, y=y),
            'MemberLoggedOutModule': mod('MemberLoggedOutModule', loggedOut=k.session is None),
            'RaidGateGameStageModule': mod('RaidGateGameStageModule', gameStage=0, isInGate=False),
            'ShipIconModule': mod('ShipIconModule', shipIcon=icon(p.ship()['lootId'])),
            'TargetModule': target(k, now)}


def member_cmd(k, d):
    pl = k.profile.d['pilot']
    return mod('GroupMemberInitializationCommand', id=k.uid, name=k.name, level=int(pl.get('level', 1)),
               loggedOut=d['MemberLoggedOutModule']['loggedOut'], active=d['ActivityModule']['active'],
               cloaked=d['CloakDeviceActivityModule']['active'], inFight=d['FightActivityModule']['active'],
               blockingInvitations=d['InvitationBlockModule']['active'], raidGateGameStage=d['RaidGateGameStageModule'],
               location=d['LocationModule'], shipIcon=d['ShipIconModule'], health=d['HealthModule'], clan=d['ClanModule'],
               target=d['TargetModule'], faction=d['FactionModule'])


def group_cmd(g, people, now):
    members = []
    for u in g.members:
        k = people.get(u)
        if k is not None:
            d = state(k, now)
            g.state.setdefault(u, d)          # the state the other members see does not change: update sends the difference (the returning member's "online")
            members.append(member_cmd(k, d))
    return ('GroupInitializationCommand', {'id': g.id, 'leaderId': g.leader, 'maxSize': MAX_COUNT, 'members': members,
                                           'invitationMode': mod('InvitationModeModule', mode=g.mod)})


def invite_cmd(a, b):
    return ('InvitationInitializationCommand', {'inviterId': a.uid, 'inviterName': a.name, 'candidateId': b.uid, 'candidateName': b.name,
                                                'inviterShip': mod('ShipIconModule', shipIcon=icon(a.profile.ship()['lootId'])),
                                                'candidateShip': mod('ShipIconModule', shipIcon=icon(b.profile.ship()['lootId']))})


def error(a, b, code):
    return ('InvitationErrorCommand', {'inviterId': a, 'candidateId': b, 'error': code})


def remove(a, b, reason):
    return ('InvitationRemovalCommand', {'inviterId': a, 'candidateId': b, 'reason': reason})


def distribute(exit):
    """{uid: [message]} -> each to its client if connected (outside the lock)."""
    people = TP.all_()
    for uid, msgs in exit.items():
        k = people.get(uid)
        if k is not None and msgs:
            k.send(msgs, 'group')


def _add(exit, uid, *msgs):
    exit.setdefault(uid, []).extend(msgs)


# ------------------------------------------------------------ requests
def handle(k, name, f, now=None):
    """The requesting player (community.Person) -> the reply that goes to them; those that go to others are sent directly."""
    now = now or time.time()
    exit = {}
    with LOCK:
        if name == 'InvitationCreationRequest':
            b = TP.find(name=f.get('name'))
            _invite(k, b, exit, now)
        elif name == 'GroupInvitationRequest':
            _invite(k, TP.find(uid=f.get('candidateId')), exit, now)
        elif name == 'InvitationAcceptRequest':
            _accepted(k, int(f.get('inviterId') or 0), exit, now)
        elif name == 'InvitationRejectRequest':
            a = int(f.get('inviterId') or 0)
            if INVITES.pop((a, k.uid), None) is None:
                _add(exit, k.uid, error(a, k.uid, NO_INVITATION))
            else:
                _invite_ended(a, k.uid, REJECT, exit)
        elif name == 'InvitationCancelRequest':
            b = int(f.get('candidateId') or 0)
            if INVITES.pop((k.uid, b), None) is None:
                _add(exit, k.uid, error(k.uid, b, NO_INVITATION))
            else:
                _invite_ended(k.uid, b, REVOKE, exit)
        elif name == 'LeaveGroupRequest':
            if group_of(k.uid) is None:
                _add(exit, k.uid, ('GroupErrorCommand', {'type': NO_GROUP}))
            else:
                _leave(k.uid, LEFT, exit)
        elif name == 'KickMemberRequest':
            g, u = group_of(k.uid), int(f.get('memberId') or 0)
            if g is not None and g.leader == k.uid and u in g.members and u != k.uid:
                _leave(u, KICKED, exit)
        elif name == 'ChangeLeaderRequest':
            g, u = group_of(k.uid), int(f.get('memberId') or 0)
            if g is not None and g.leader == k.uid and u in g.members and u != k.uid:
                g.leader = u
                for x in g.members:
                    _add(exit, x, ('LeaderChangeCommand', {'leaderId': u}))
        elif name == 'InvitationModeRequest':
            g = group_of(k.uid)
            mode = int((f.get('mode') or {}).get('mode', MODE_LEADER))
            if g is not None and g.leader == k.uid and mode in (MODE_LEADER, MODE_EVERYONE):
                g.mod = mode
                for x in g.members:
                    _add(exit, x, ('InvitationModeModule', {'mode': mode}))
        elif name in ('PingPositionRequest', 'PingMemberRequest'):
            _ping(k, name, f, exit, now)
        elif name == 'FollowRequest':
            g, u = group_of(k.uid), int(f.get('memberId') or 0)
            o = TP.find(uid=u) if g is not None and u in g.members else None
            # a bot member has no world (its session is fake): if online, the position from its ship (player report 2026-10-31: "Go to!" on a bot
            # said "location unknown: wrong map")
            if o is not None and o.session is not None and k.world is not None and position(o, now)[0] == position(k, now)[0]:
                _, x, y = position(o, now)
                _add(exit, k.uid, ('HeroMoveCommand', {'x': x, 'y': y}))
            else:
                _add(exit, k.uid, ('GroupErrorCommand', {'type': FOLLOW_FAILED if g is not None else NO_GROUP}))
    own = exit.pop(k.uid, [])
    distribute(exit)
    return own


def _invite(a, b, exit, now):
    g = group_of(a.uid)
    bid = b.uid if b is not None else 0
    if b is None or b.uid == a.uid or b.session is None:
        err = CANDIDATE_NONEXISTENT
    elif g is not None and g.leader != a.uid and g.mod == MODE_LEADER:
        err = BOSS_ONLY
    elif g is not None and len(g.members) + sum(1 for x, _ in INVITES if x in g.members) >= MAX_COUNT:
        err = GROUP_FULL
    elif group_of(b.uid) is not None:
        err = CANDIDATE_IN_GROUP
    elif b.profile.d.get('invite_block'):
        err = CANDIDATE_BLOCKING
    elif (a.uid, b.uid) in INVITES:
        err = DUPLICATE_INVITATION
    elif sum(1 for x, _ in INVITES if x == a.uid) >= INVITE_MAX:
        err = MAX_INVITER
    elif sum(1 for _, y in INVITES if y == b.uid) >= INVITE_MAX:
        err = MAX_CANDIDATE
    else:
        err = None
    if err is not None:
        _add(exit, a.uid, error(a.uid, bid, err))
        return
    INVITES[(a.uid, b.uid)] = now + INVITE_SEC
    launch()                                                  # lapsed invitations and the members' state
    cmd = invite_cmd(a, b)
    _add(exit, a.uid, cmd, stm('msg_grp_inv_sent', name=b.name))
    _add(exit, b.uid, cmd, stm('msg_grp_inv_received', name=a.name))
    for x in (g.members if g is not None else ()):
        if x != a.uid:
            _add(exit, x, cmd)


def _invite_ended(a, b, reason, exit):
    """The invitation lapsed: InvitationRemovalCommand to the inviter, the candidate and the inviter's group members (the client writes the text)."""
    g = group_of(a)
    for x in {a, b} | set(g.members if g is not None else ()):
        _add(exit, x, remove(a, b, reason))


def _accepted(b, a, exit, now):
    if INVITES.pop((a, b.uid), None) is None:
        _add(exit, b.uid, error(a, b.uid, NO_INVITATION))
        return
    person_a = TP.find(uid=a)
    if person_a is None:
        _invite_ended(a, b.uid, REJECT, exit)
        _add(exit, b.uid, error(a, b.uid, INVITER_NONEXISTENT))
        return
    if group_of(b.uid) is not None:
        _invite_ended(a, b.uid, ACKNOWLEDGE, exit)
        _add(exit, b.uid, error(a, b.uid, CANDIDATE_IN_GROUP))
        return
    g = group_of(a)
    if g is not None and len(g.members) >= MAX_COUNT:
        _invite_ended(a, b.uid, ACKNOWLEDGE, exit)
        _add(exit, b.uid, error(a, b.uid, GROUP_FULL))
        return
    _invite_ended(a, b.uid, ACKNOWLEDGE, exit)
    for (x, y) in [d for d in INVITES if d[1] == b.uid]:     # the candidate's other invitations lapse (now in a group)
        del INVITES[(x, y)]
        _invite_ended(x, y, REJECT, exit)
    people = TP.all_()
    new_ = g is None
    if new_:
        g = Group(a)
        GROUPS[g.id] = g
        MEMBER[a] = g.id
    old = list(g.members)
    g.members.append(b.uid)
    MEMBER[b.uid] = g.id
    if _bot(g.leader) and not _bot(b.uid):        # a player under a bot's leadership: the player becomes the leader (bots do not use invite mode or kicking;
        g.leader = b.uid                          # player report 2026-10-31: "Change invite settings" did not work)
        for x in old:
            _add(exit, x, ('LeaderChangeCommand', {'leaderId': g.leader}))
    init = group_cmd(g, people, now)
    _add(exit, b.uid, init)
    if new_:
        _add(exit, a, init, stm('msg_grp_new_member', name=b.name))
    else:
        member = next(m for m in init[1]['members'] if m['id'] == b.uid)
        for x in old:
            _add(exit, x, ('GroupMemberInitializationCommand', {k: v for k, v in member.items() if k != '_'}),
                  stm('msg_grp_new_member', name=b.name))


def _bot(uid):
    return TP.BOTS is not None and uid in TP.BOTS()


def _leave(u, reason, exit):
    g = group_of(u)
    if g is None:
        return
    for x in g.members:
        _add(exit, x, ('MemberLeaveCommand', {'playerId': u, 'reason': reason}))
    g.members.remove(u)
    g.state.pop(u, None)
    MEMBER.pop(u, None)
    for (x, y) in [d for d in INVITES if d[0] == u]:          # the leaver's invitations lapse on behalf of their group
        del INVITES[(x, y)]
        _invite_ended(x, y, REVOKE, exit)
    leaving = [u]
    if len(g.members) < 2:
        for x in g.members:
            _add(exit, x, ('GroupCloseCommand', {}), stm('msg_grp_broken_up'))
            MEMBER.pop(x, None)
        leaving += g.members
        del GROUPS[g.id]
    elif g.leader == u:
        g.leader = g.members[0]
        for x in g.members:
            _add(exit, x, ('LeaderChangeCommand', {'leaderId': g.leader}))
    _leave_chat(g.id, leaving)


def _ping(k, name, f, exit, now):
    g = group_of(k.uid)
    if g is None:
        _add(exit, k.uid, ('GroupErrorCommand', {'type': NO_GROUP}))
        return
    if now - g.ping.get(k.uid, 0) < PING_SEC:
        _add(exit, k.uid, ('GroupErrorCommand', {'type': PING_FAILED}), stm('msg_grp_ping_error'))
        return
    people = TP.all_()
    game_map = position(k, now)[0]
    if name == 'PingMemberRequest':
        o = people.get(int(f.get('memberId') or 0))
        if o is None or o.uid not in g.members or o.world is None or position(o, now)[0] != game_map:
            _add(exit, k.uid, ('GroupErrorCommand', {'type': PING_FAILED}))
            return
        _, x, y = position(o, now)
    else:
        x, y = int(f.get('x', 0)), int(f.get('y', 0))
    g.ping[k.uid] = now
    for u in g.members:
        o = people.get(u)
        if o is not None and o.world is not None and position(o, now)[0] == game_map:
            _add(exit, u, ('PingCommand', {'x': x, 'y': y}))


def _leave_chat(gid, uids):
    """The chat connection of those who leave the group should no longer listen to the group's room (the client closes the room itself). Not needed for joiners:
    the client reconnects to chat at GroupInitializationCommand, takes the rooms from social.rooms (the group's is there)."""
    people = TP.all_()
    for u in uids:
        k = people.get(u)
        sh = getattr(getattr(k.session if k is not None else None, 'social', None), 'chat', None)
        if sh is not None:
            sh.room_drop(str(u), *room(gid)[1:])


# ------------------------------------------------------------ login and state updates
def login_msgs(k, now=None):
    """The player entered the game (first ReadyRequest): the group and pending invitations (the client starts with an empty group window at login)."""
    now = now or time.time()
    out = []
    with LOCK:
        people = TP.all_()
        g = group_of(k.uid)
        if g is not None:
            out.append(group_cmd(g, people, now))
        for (a, b) in list(INVITES):
            if k.uid in (a, b) and a in people and b in people:
                out.append(invite_cmd(people[a], people[b]))
        if k.profile.d.get('invite_block'):
            out.append(('InvitationBlockModule', {'active': True}))
    return out


def update(now=None):
    """One step: lapsed invitations, members whose record ended, the members' changed state."""
    now = now or time.time()
    exit = {}
    with LOCK:
        people = TP.all_()
        for (a, b), last in list(INVITES.items()):
            if last <= now or a not in people or b not in people:
                del INVITES[(a, b)]
                _invite_ended(a, b, TIMEOUT, exit)
        for g in list(GROUPS.values()):
            for u in [u for u in g.members if u not in people]:
                _leave(u, LEFT, exit)
            if g.id not in GROUPS:
                continue
            for u in g.members:
                k = people[u]
                new_ = state(k, now)
                old = g.state.get(u) or {}
                diff = [v for n, v in new_.items() if old.get(n) != v and not (n == 'LocationModule' and _nearby(old.get(n), v))]
                if not diff:
                    continue
                g.state[u] = dict(old, **{v['_']: v for v in diff})
                msgs = [('GroupMemberUpdateCommand', {'playerId': u, 'updates': diff})]
                for v in diff:
                    if v['_'] == 'MemberLoggedOutModule' and old:
                        msgs.append(stm('msg_grp_member_logs_out' if v['loggedOut'] else 'msg_grp_member_back', name=k.name))
                    elif v['_'] == 'LocationModule' and old.get('LocationModule') and old['LocationModule']['mapId'] != v['mapId']:
                        msgs.append(stm('msg_grp_jump', name=k.name, map=H.name(v['mapId'])))
                for x in g.members:
                    _add(exit, x, *[m for m in msgs if x != u or m[0] == 'GroupMemberUpdateCommand'])
    distribute(exit)


def _nearby(a, b):
    return a is not None and a['mapId'] == b['mapId'] and abs(a['x'] - b['x']) < POSITION_THRESHOLD and abs(a['y'] - b['y']) < POSITION_THRESHOLD


def died(k):
    """A member was shot (world.hero_death): "%name% was shot down." to the other members (the client writes only its own death)."""
    g = group_of(k.uid)
    if g is not None:
        distribute({u: [stm('msg_grp_member_killed', name=k.name)] for u in list(g.members) if u != k.uid})


def members(uid):
    """The ids of the other members in the player's group (attack ban, chat room)."""
    g = group_of(uid)
    return [u for u in g.members if u != uid] if g is not None else []


def _loop():
    while True:
        time.sleep(UPDATE_SEC)
        try:
            update()
        except Exception:
            import traceback
            traceback.print_exc()


def launch():
    """The thread of the state updates (once, when the first group is created)."""
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, name='group', daemon=True)
        _thread.start()
