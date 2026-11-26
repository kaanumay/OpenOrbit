"""Black Light: bots raid their company's BL map as a group (user request 2026-11-26) and work toward the lasers made for it.

  raid      once a pilot reaches its company's BL entry level it gathers with others of its company at X-8, the group forms (a real
            in-game group) and goes in together; alone the BL aliens are too strong (every one is aggressive, Abide I has 600,000 HP)
  team      on a BL map the bots of a company hunt as one team: the map is judged with the team's damage and HP, each one gets its share
            of the kills and rewards (abstract_sim.farm)
  lasers    the BL aliens drop Rinusk, Blacklight traces, Eternal fragments: in Assembly they make the Prometheus laser (x3.5 against BL
            aliens, items.json lasers pr-l target_multiplier) and A-BL ammo. A raider values them (worth), so it builds them when it has the
            parts; with Prometheus lasers fitted its damage against BL aliens rises (factor)
"""
from . import catalog as K

BL_MAP = {1: 306, 2: 307, 3: 308}              # the company's own BL map (BL-1 MMO, BL-2 EIC, BL-3 VRU)
GATEWAY = {1: 20, 2: 24, 3: 28}               # X-8: the portal to its BL map
RAID_MIN = 3                                  # the group goes in from this many
TEAM_MAX = 8                                  # a group's size (group.MAX_COUNT)
PROMETHEUS = 'equipment_weapon_laser_pr-l'
A_BL = 'ammunition_laser_a-bl'
BL_MAPS = frozenset(BL_MAP.values())
PIRATE_MAPS = frozenset((91, 92, 93))         # 5-1..5-3: a group hunts as a team there (a pirate quest's group, goals/quest.py)
PIRATE_FEW = 3                                # fewer bots than this on a pirate map: it draws capable pilots (brain.map_candidates)


def entry_level(bot):
    return K.H.level_required(BL_MAP[bot.company], bot.company)


def factor(gear):
    """Damage multiplier against BL aliens from the fitted lasers (Prometheus x3.5): the fitted lasers' damage weighted by their multiplier."""
    out = K.outfit(gear)
    fitted = sorted(((K.ITEMS['lasers'][l]['damage'], l) for l, n in gear.get('laser', {}).items() for _ in range(n)
                     if l in K.ITEMS['lasers'] and not K.ITEMS['lasers'][l].get('pet_only')), reverse=True)[:out['laser_slots']]
    total = sum(d for d, _ in fitted)
    if not total:
        return 1.0
    boosted = sum(d * max([1.0] + list((K.ITEMS['lasers'][l].get('target_multiplier') or {}).values())) for d, l in fitted)
    return boosted / total


def team(bot, y):
    """The bot's team: on a BL map the online bots of its company there (with it); on a pirate map its group's bots there; at most a
    group's size."""
    m = int(bot.game_map)
    if y is None or (m not in BL_MAPS and m not in PIRATE_MAPS):
        return 1
    if m in BL_MAPS:
        n = sum(1 for o in y.on_map.get(m, ()) if o.company == bot.company and o.online)
    else:
        import group as GR
        g = GR.group_of(bot.uid)
        if g is None:
            return 1
        n = sum(1 for o in y.on_map.get(m, ()) if o.uid in g.members and o.online)
    return max(1, min(TEAM_MAX, n))


def form_group(y, leader, members, now, until):
    """A real in-game group (group.py) of bots: the leader invites, the others accept at once (they came for it); until: society.party
    does not break it up before then."""
    import group as GR
    import community as TP
    from . import society as SO
    for o in members:
        if o is not leader and GR.group_of(o.uid) is not None and GR.group_of(o.uid) is not GR.group_of(leader.uid):
            GR.handle(SO.person(o), 'LeaveGroupRequest', {})
    for o in members:
        if o is leader or GR.group_of(o.uid) is not None or TP.find(uid=o.uid) is None or TP.find(uid=leader.uid) is None:
            continue
        g = GR.group_of(leader.uid)
        if g is not None and len(g.members) >= TEAM_MAX:
            break
        GR.handle(SO.person(leader), 'GroupInvitationRequest', {'candidateId': o.uid})
        GR.handle(SO.person(o), 'InvitationAcceptRequest', {'inviterId': leader.uid})
    for o in members:
        o.party_until = until


def judged(bot, n=None, y=None):
    """The BL map as this bot sees it with a team of n (default: who is there) -> evaluate_map's result."""
    d = bot.value()
    n = n or team(bot, y)
    courage = max(0.0, min(1.0, 0.3 + 0.6 * bot.o('risk') + 0.2 * bot.mood['confidence'] - 0.3))
    return K.evaluate_map(BL_MAP[bot.company], d['dps'] * factor(bot.k['gear']) * n, d['ehp'] * n, courage)


def ready(bot):
    """Can it raid: its company's BL entry level, groups allowed, and a team of RAID_MIN like it would manage the aliens."""
    if bot.level < entry_level(bot) or not bot.permission.get('group', True):
        return False
    return bool(judged(bot, RAID_MIN)['targets'])


def worth(bot, loot):
    """Assembly: what the BL gear is worth to a raider (credits), 0 to others. Prometheus while some laser slot has no Prometheus yet; A-BL
    while it holds less than one batch."""
    if not bot.k.get('bl_raids'):
        return 0
    if loot == PROMETHEUS:
        have = bot.k['gear'].get('laser', {}).get(PROMETHEUS, 0)
        return 300000000 if have < K.outfit(bot.k['gear'])['laser_slots'] else 0
    if loot == A_BL:
        from . import weapons as WP
        return 40000000 if WP.stock(bot).get(A_BL, 0) < 25000 else 0
    return 0
