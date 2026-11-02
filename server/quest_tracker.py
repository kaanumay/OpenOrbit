"""Progress of quest conditions by game events: the single measurement point for Season Pass, Battle Pass, event quests and main quests
(roadmap Stage 7, E6; main quests add position and their own types in quest.Quests.matches).

Condition types are the client's ConditionType enum (from the compiled code); the meaning of the matches is from the ParseMatches of the client's condition classes:
  1 TIMER (ms; the minute event is 60,000)     3 ENDURANCE (staying on the map, ms; minute event)   6 KILL_NPC ([npcId]; an empty list
  crashes the client)                         7 DAMAGE (any damage)                            9 TAKE_DAMAGE (damage taken: damage_taken)
  12 DISTANCE, 13 TRAVEL (distance)           20/22 AMMUNITION ([type, tier]: 1 laser, 2 rocket, 3 mine; 0 = all)
  23 SALVAGE ([company, ship, alien, ?, old ore id]; ore from the cargo box of a destroyed ship: loot event, box=True)
  27 KILL_NPCS ([npcId ...]; the total of the listed aliens)                  35 DIE (death)  42 JUMP (portal)
  56 FINISH_QUEST ([quest]; a finished quest)  29 DAMAGE_NPCS ([count, npcId ..., 0])           30 DAMAGE_PLAYERS (with bot players)
  34 VISIT_MAP                                51 CARGO (cargo box)                            52 SELL_ORE ([old ore id])
  53 LEVEL (level)                            55 COLLECT_BONUS_BOX                            67 COLLECT_LOOT ([lootId ...])
  66 IN_CLAN (clan event)                     68 FINISH_STARTER_GATE (gate event, type=STARTER_GATE; Devolarium Attack gate)
  72 USE_ORE_UPDATE ([LASER|ROCKET|SPEED|SHIELD, ORE]; upgrade in the laboratory: ore_update event; counts the ore loaded)
  80 FINISH_GALAXY_GATES ([count, name ..., map ...])   85 COLLECT_BUILT_RECIPE ([recipe]; Assembly)
  87 COMPLETED_OBJECTIVES (a finished Battle Pass quest)   89 SPEND_ITEM ([lootId])
  95 COMPLETE_SEASON_PASS_QUESTS ([2 season | 5 daily | 6 weekly])   96 LOGIN   100 RECHARGE_AMOUNT (single player: Uridium Bank)
Sub-condition 77 ON_MAP: only on the listed maps. 97 DURING_EVENT: only while the named event is open (the event type in the calendar,
e.g. NpcEvent, or the calendar key in EVENT_NAMES; the Season Pass's "15 Battle Pass quests during an event" quests).
Events (the session collects them): achievement events (kill, damage, distance, minute, gate, assembly_collect, level, ammo, spend, jump, death,
quest, clan), quest events (cargo, loot, sell, bonus, map, pos, ore_update) and internal events (login, recharge, sp_quest, objective). The intermediate value of frequent events
(damage, distance, ammo) is sent once a second.
"""
import copy, time

import event_calendar as CAL
from quest import cap, conditions, evaluate, mod

ON_MAP = 77
DURING_EVENT = 97
EVENT_NAMES = {'HitacAssault2016': 'hitac'}       # sub-condition 97's name -> calendar key (PVPSummerEvent: PvP, not in the calendar)
THROTTLE_SEC = 1.0                 # the intermediate value of the same condition at most once a second (distance, ammo, damage are frequent; save: once a second)
FREQUENT = ('damage', 'damage_taken', 'damage_player', 'distance', 'ammo')
LAST_SENT = {}                    # condition -> last send
# ore -> the client's old ore id (GameDefineSystem.Init; SELL_ORE and SALVAGE matches): 1 Prometium, 2 Endurium,
# 3 Terbium, 4 Xenomit, 11 Prometid, 12 Duranium, 13 Promerium, 14 Seprom, 15 Palladium, 42 Osmium
OLD_ORE = {'resource_ore_prometium': '1', 'resource_ore_endurium': '2', 'resource_ore_terbium': '3', 'resource_ore_xenomit': '4',
           'resource_ore_prometid': '11', 'resource_ore_duranium': '12', 'resource_ore_promerium': '13', 'resource_ore_seprom': '14',
           'resource_ore_palladium': '15', 'resource_ore_osmium': '42'}
ORE_LOOT = {0: 'resource_ore_prometium', 1: 'resource_ore_endurium', 2: 'resource_ore_terbium', 3: 'resource_ore_xenomit',
            4: 'resource_ore_prometid', 5: 'resource_ore_duranium', 6: 'resource_ore_promerium', 7: 'resource_ore_seprom',
            8: 'resource_ore_palladium', 28: 'resource_ore_osmium'}      # the server's ore index (items.json ores)
SP_CATEGORY = {3: '5', 6: '6', 9: '2'}           # QuestType -> COMPLETE_SEASON_PASS_QUESTS match (client: DAILIES, WEEKLIES, SEASON)


def ammo_kind(loot):
    """Ammo type (the client's DamageType): 1 laser, 2 rocket, 3 mine, 4 others (special ammo, CPU)."""
    if loot.startswith('ammunition_laser_'):
        return '1'
    if loot.startswith(('ammunition_rocket_', 'ammunition_rocketlauncher_')):
        return '2'
    return '3' if loot.startswith('ammunition_mine_') else '4'


def counted(m):
    """Items from a [count, item ..., ...] match."""
    try:
        n = int(m[0]) if m else 0
    except ValueError:
        return list(m)
    return m[1:1 + n]


def measure(c, kind, kw, map_id=None):
    """How much this event advances the condition: a number (added), ('set', value) or 0."""
    on_map = [s for s in c.get('subConditions', []) if s['type'] == ON_MAP]
    if on_map and str(kw.get('map', map_id)) not in [str(x) for x in on_map[0]['matches']]:
        return 0
    t, m = c['type'], [str(x) for x in c['matches']]
    if t == 1 and kind in ('minute', 'login'):
        return 60000 if kind == 'minute' else 1                     # login: "enter the game" quests (TIMER 1 ms; save: finishes at login)
    if t == 3 and kind == 'minute':
        return 60000
    if t == 6 and kind == 'kill' and kw.get('avatar', 'NPC') == 'NPC':
        return 1 if not m or str(kw.get('npc')) in m else 0
    if t == 7 and kind == 'damage':
        return int(kw.get('count', 0))
    if t == 9 and kind == 'damage_taken':
        return int(kw.get('count', 0))
    if t in (12, 13) and kind == 'distance':
        return int(kw.get('count', 0))
    if t in (20, 22) and kind == 'ammo':
        return int(kw.get('count', 0)) if not m or m[0] in ('0', ammo_kind(kw.get('loot', ''))) else 0
    if t == 23 and kind == 'loot' and kw.get('box'):         # [company, ship, alien, ?, ore]: the filters do not know the box's source
        ore = m[4] if len(m) > 4 else '0'
        return int(kw.get('amount', 0)) if not any(x not in ('', '0') for x in m[:3]) and ore in ('', '0', OLD_ORE.get(kw.get('loot'))) else 0
    if t == 27 and kind == 'kill' and kw.get('avatar', 'NPC') == 'NPC':
        return 1 if not m or str(kw.get('npc')) in m else 0
    if t == 29 and kind == 'damage':
        ids = counted(m)
        return int(kw.get('count', 0)) if not ids or str(kw.get('npc')) in ids else 0
    if t == 30 and kind == 'damage_player':
        return int(kw.get('count', 0))
    if t == 34 and kind == 'map':
        return 1 if not m or str(kw.get('map')) in m else 0
    if t == 35 and kind == 'death':
        return 1
    if t == 42 and kind == 'jump':
        return 1
    if t == 51 and kind == 'cargo':
        return 1
    if t == 52 and kind == 'sell':
        return int(kw.get('amount', 0)) if not m or OLD_ORE.get(ORE_LOOT.get(kw.get('ore', -1))) in m else 0
    if t == 53 and kind == 'level':
        return ('set', int(kw.get('value', 0)))
    if t == 55 and kind == 'bonus':
        return 1
    if t == 56 and kind == 'quest':
        return 1 if not m or str(kw.get('id')) in m else 0
    if t == 66 and kind == 'clan':
        return 1
    if t == 67 and kind == 'loot':
        return int(kw.get('amount', 0)) if not m or kw.get('loot') in m else 0
    if t == 68 and kind == 'gate':
        return 1 if kw.get('type') == 'STARTER_GATE' else 0
    if t == 72 and kind == 'ore_update':
        # the ore loaded, not the number of upgrades ("Upgrade your Rockets with Seprom (0/80)": 80 Seprom at once is 80/80)
        if len(m) > 1 and m[0] == kw.get('type') and kw.get('ore') == 'resource_ore_' + m[1].lower():
            return int(kw.get('amount', 1))
        return 0
    if t == 80 and kind == 'gate':
        names = counted(m)
        return 1 if not names or str(kw.get('type', '')).replace('_GATE', '') in names else 0
    if t == 85 and kind == 'assembly_collect':
        return int(kw.get('count', 1)) if not m or kw.get('recipe') in m else 0
    if t == 87 and kind == 'objective':
        return 1
    if t == 89 and kind in ('spend', 'ammo'):       # spending ammo ('ammo' event; Pass quests turn it into 'spend': battle_pass.measure)
        return int(kw.get('count', 0)) if not m or kw.get('loot') in m else 0
    if t == 95 and kind == 'sp_quest':
        return 1 if not m or str(kw.get('category')) == m[0] else 0
    if t == 96 and kind == 'login':
        return 1
    if t == 100 and kind == 'recharge':
        return 1
    return 0


def during_event(c, now=None):
    """If sub-condition 97 (DURING_EVENT) is present, whether the named event is open now; otherwise True."""
    during = [s for s in c.get('subConditions', []) if s['type'] == DURING_EVENT]
    return not during or any(EVENT_NAMES.get(n) in CAL.active(now) or CAL.has_type(n, now) for n in during[0]['matches'])


def cond_update(cid, value, active, completed):
    return ('QuestConditionUpdateCommand', {'questConditionId': cid, 'state': mod(
        'QuestConditionStateModule', currentValue=value, active=active, completed=completed)})


def advance(p, root, vals, kind, kw, map_id=None, notify=True, fn=measure):
    """Advances a quest's conditions with the event (values in vals, under the lock; fn: measurement, for main quests Quests.matches)
    -> (messages, whether completed)."""
    before = evaluate(root, vals)[0]
    changed = []
    for c in conditions(root):
        if not before[c['id']][0]:
            continue
        inc = fn(c, kind, kw, map_id)
        if not inc or not during_event(c):
            continue
        key = str(c['id'])
        with p.lock:
            old = vals.get(key, 0)
            new = cap(c, inc[1] if isinstance(inc, tuple) else old + inc)
            if new == old:
                continue
            vals[key] = new
            p.dirty = True
        changed.append(c)
    if not changed:
        return [], False
    after, done = evaluate(root, vals)
    msgs = []
    if notify:
        ids = {c['id'] for c in changed}
        now = time.time()
        for c in conditions(root):
            v = cap(c, vals.get(str(c['id']), 0))
            moved = after[c['id']] != before[c['id']]
            if c['id'] in ids and (moved or kind not in FREQUENT or now - LAST_SENT.get(c['id'], 0) >= THROTTLE_SEC):
                LAST_SENT[c['id']] = now
                msgs.append(cond_update(c['id'], v, True, False))
            if moved:
                msgs.append(cond_update(c['id'], v, *after[c['id']]))
    return msgs, done


def with_state(definition, vals, completed=False):
    """A copy of the quest definition, condition states with values (all done if completed)."""
    d = copy.deepcopy(definition)
    root = d['rootCase']
    flags = evaluate(root, vals)[0]
    for c in conditions(root):
        active, comp = flags[c['id']]
        v = cap(c, vals.get(str(c['id']), 0))
        if completed:
            active, comp, v = False, True, c['targetValue']
        c['state'].update(currentValue=v, active=active, completed=comp)
    return d
