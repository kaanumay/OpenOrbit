"""Quest mode (pilot.json quests): the active quests lead the hunt. An open "kill these aliens" condition replaces the hunting list and the
maps with the quest's; "visit a map" sends the ship there; "return to the quest giver" sends it to the nearest giver. With accept, when no
active quest can be played and a slot is free, the bot flies to a quest giver and takes the highest-level quest it can play. When no quest
can be played nor taken, the mode ends (Pilot.mode_end: its 'then', stop or another mode).
A chosen quest (quests.qid; 0: automatic) is the only one played, no other is taken; when it is done (or no longer accepted, or cannot be
played) the mode ends the same way."""

REFRESH_SEC = 5.0
BLOCK_SEC = 300.0             # no quest to take at the giver: not asked again for this long
HANDED_SEC = 10.0             # after handing a quest in, before the next look at the giver


def update(pilot, now):
    """Every few seconds: the quest's aliens and maps for the hunt."""
    from . import modes as MODES
    if MODES.current(pilot) != 'quest':
        pilot.quest_goal = pilot.quest_maps = pilot.quest_aliens = None
        return
    if pilot.homing or now - pilot.quest_at < REFRESH_SEC:
        return
    pilot.quest_at = now
    qid = pilot.cfg['quests']['qid']
    if qid and not pilot.act.quest_active(qid):          # the chosen quest is done (or was cancelled)
        done = pilot.act.quest_done(qid)
        pilot.quest_goal = pilot.quest_maps = pilot.quest_aliens = None
        pilot.note('chosen quest %s' % ('done' if done else 'no longer accepted'))
        pilot.mode_end('quest_done' if done else 'quest_gone')
        return
    g = pilot.act.quest_goal(qid or None)
    old = pilot.quest_goal
    if (g and g['qid'], g and g['kind']) != (old and old['qid'], old and old['kind']):
        pilot.note('quest: %s (%s)' % (g['name'], g['kind']) if g else 'no quest to play')
    pilot.quest_goal = g
    pilot.quest_maps = g['maps'] if g and g['kind'] in ('kill', 'visit') else None
    pilot.quest_aliens = g['aliens'] if g and g['kind'] == 'kill' else None


def goal(pilot, s, now):
    """Going to a quest giver (to hand a quest in, or to take a new one) -> a label while on the way."""
    c = pilot.cfg['quests']
    if now < pilot.quest_block or not pilot.quest_at:
        return None
    g, act = pilot.quest_goal, pilot.act
    hand_in = bool(g) and g['kind'] == 'giver'
    if g is None and (not c['accept'] or c['qid'] or act.quest_slots() <= 0):      # a chosen quest: no other is taken
        pilot.mode_end('no_quest')                  # nothing to play and nothing to take
        return 'quest'
    if not hand_in and g is not None:
        return None
    st = act.go_to_giver(now)
    if st == 'no_route':
        pilot.quest_block = now + BLOCK_SEC
        if not hand_in:
            pilot.mode_end('no_quest')
        return None
    if st != 'here':
        return 'quest'
    if hand_in:
        act.hand_in()
        pilot.note('quest handed in: %s' % g['name'])
        pilot.quest_block = now + HANDED_SEC
    else:
        qid = act.accept_quest()
        if qid:
            pilot.note('quest taken: %s' % qid)
        else:
            pilot.note('no quest to take here')
            pilot.quest_block = now + BLOCK_SEC
            pilot.mode_end('no_quest')
    pilot.quest_at = 0.0                            # read the quests again at once
    return None
