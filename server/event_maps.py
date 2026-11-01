"""Map events (roadmap Stage 7; data data/events.json "map", aliens npc.json event_* <- tools/event_aliens.py).

If the map section of an event that is active on the calendar covers this map's class (X-2 … X-8, 4-4 …):
  - the event aliens are added to the map ('alien_spawns': type and count; "{x}" is the map class's version: event_curcubitor_x5); they respawn
    when killed, and do not spawn once the event ends
  - summoning quota ('quota'): when this many event aliens are killed the bosses ('boss': kinds, count, sure_sn; 'in_order': types in turn)
    spawn; if not killed in time they flee (the client's text: msg_curcubitor_ran_away / npc_event_boss_ran_away)
  - indicator ('info'): NpcEventInfoCommand / AgatusEventInfoCommand {textKey (the client's texts: curcubitor, agatusbreach,
    npc_valentine, npc_chaos-protegit), npcID, bossInfo {bossCount, leftToKill}, timeInfo {timeToNextSpawn, timeToEndSpawn s}}
  - drops ('drop': type -> {lootId: [min, max]}, the map version event_x_x5 if there is one, otherwise the base type; the event currency
    goes to the resource storage, in the loot log) and Curcubitor's
    "Trick or Treat": on death either Trick ('trick': probability; an uncollectable Curcubitor mine, which when planted deals 20% of your
    HP if you are near) or Treat (the chest in box_drop), not both. Until 2026-10-18 the two were independent: the mine stayed under the
    chest and exploded while collecting the chest (user report)
  - aliens without a cargo box ('no_cargo': base types; Curcubitor and Boss Curcubitor drop only their chests) -> no_cargo
  - the look of the cargo box ('cargo_kind': the client's box type, same contents; TURKEY_CARGO at Thanksgiving) -> cargo_kind
  - summoners ('call' or the boss's 'call'): while alive they summon aliens next to them at intervals (Agatus -> Spinel, Ice Meteoroid
  -> Icy)
  - hunt boxes ('boxes': the client's box type, count, contents, respawn) and boxes dropped by aliens ('box_drop': type ->
    {box type, probability, contents}; event types and the map's ordinary aliens, e.g. Luminium in Empyrian); no key needed, the P.E.T. also
    collects them; when the contents open: all 'guaranteed' rows, from 'contents' either 'one_of' one reward by weight or 'hepsi' each with its own
    probability ([lootId, count or [min, max], probability %]); also the NPC type's own 'box' (event gates)
  - roaming alien (the event's 'rover', single or a list: Hitac 2.5 and from E8 Hitac 2.0): stays sure_sn in turn on the maps of the route,
    appears if the player is on that map, moves on to the next map when its time is up; when killed, after cooldown_sec it restarts from the
    start of the route (during the session)
  - group ('group': {kinds [[type, count]], interval_sec}): a group spawning together at a random place on the map; the next group only after
    all are destroyed and interval_sec has elapsed (Space Cup's 11 Roaming Football Pirates in 4-4, official Turkish forum 127757)
  - spawned on death ('spawn_on_death': type -> [{type, count (or [min, max]), probability}]): while the event runs, when that type dies they
    spawn next to it and target the killer (2-5 I-Gygerthrall from Hatching Out's egg, Plagued Gygerthrall from Plagued Kristallin
    in Epidemi); box_drop's 'count': the number of boxes dropped per death (Demaner Freighter: 10 Special Demaner Boxes); the
    summoner's 'lifetime_sec': the summoned one disappears after this many seconds (the egg I-Hitac drops every 30 s lasts 90 s)
"""
import math, random, time

import map_links as H
import event_calendar as CAL
import settings as SET
from legacy_protocol import legacy
from galaxy_gates import screen

TRICK_MINE = 'curcubitor_mayini'        # the client's curcubitorMine model (items.json mines)
TRICK_DELAY = 1.4                         # official server record 2026-10-27: the mine appears 1.4 s after death
BOSS_TEXT = {'curcubitor': ('curcubitor_boss_spawn', 'msg_curcubitor_ran_away'), 'agatusbreach': ('agatusbreach_boss_spawn', None),
             'npc_valentine': ('npc_valentine_boss_spawn', None), 'npc_hitacAssault': ('npc_hitacAssault_boss_spawn', None)}


def mod(name, **f):
    f['_'] = name
    return f


def specs(now=None):
    """The currently open map sections of the active events: [(event, section)] (the section's periods and spawn times: event_calendar.window;
    for a forcibly opened event, all of them)."""
    out = []
    for k in sorted(CAL.active(now)):
        e = CAL.EVENTS[k]
        for s in ([e['map']] if 'map' in e else []) + e.get('map_extra', []):
            if CAL.forced(k) or CAL.window(s, now):
                out.append((k, s))
    return out


PROXIUM = 'resource_collectable_proxium'


def roll(spec, mods=None):
    """Box contents -> [(lootId, count)]: all 'guaranteed' rows, from 'contents' according to 'mod'. mods: the player's bonuses (player_profile.mods());
    if the box is 'proxium' (Permafrost Fissure's UFO and Ufonit boxes) the Proxium row's probability rises by the Proxium Drop Booster's
    points (proxium_chance: 10% -> 35%) and its count by the Proxium Doubler's ratio (proxium: x2)."""
    rows = spec.get('contents', [])
    bonus = mods if spec.get('proxium') and mods else {}
    amount = lambda a, l=None: int((random.randint(*a) if isinstance(a, list) else a) * (1 + bonus.get('proxium', 0) if l == PROXIUM else 1))
    pct = lambda l, c: c + bonus.get('proxium_chance', 0) * 100 if l == PROXIUM else c
    out = [(l, amount(a, l)) for l, a, *c in spec.get('guaranteed', [])]
    out += [(l, amount(a, l)) for l, a, c in spec.get('additional', []) if random.random() * 100 < pct(l, c)]   # with a separate probability (Permafrost Proxium)
    if spec.get('mod', 'one_of') == 'all':
        return out + [(l, amount(a, l)) for l, a, *c in rows if random.random() * 100 < pct(l, c[0] if c and c[0] is not None else 100)]
    weights = [pct(l, c[0] if c and c[0] is not None else 1) for l, a, *c in rows]
    if not rows or sum(weights) <= 0:
        return out
    l, a, *c = random.choices(rows, weights)[0]
    return out + [(l, amount(a, l))]


ROVER = {}                         # roamer (rovers) -> the start of its route (after the wait once killed)
NO_CARGO = {b for e in CAL.EVENTS.values() for s in ([e['map']] if 'map' in e else []) + e.get('map_extra', [])
            for b in s.get('no_cargo', [])}          # even after the event ends: that type's alien never drops a cargo box


def no_cargo(n):
    """Does this alien not drop a cargo box (the event data's 'no_cargo'; Curcubitor drops only its chest)."""
    return base(n.tip) in NO_CARGO


def rovers(k):
    """The event's roamers [(ROVER key, roamer)]: the first under the event's name, the others 'name#index'."""
    g = CAL.EVENTS[k].get('rover') or []
    return [(k if i == 0 else '%s#%d' % (k, i), x) for i, x in enumerate(g if isinstance(g, list) else [g])]


def route_at(k, g, now):
    """The map where the roamer currently is (None while waiting)."""
    start = ROVER.setdefault(k, now)
    if now < start:
        return None
    return g['route'][int((now - start) // g['duration_sec']) % len(g['route'])]


def route_leg(k, g, now):
    """The roamer's leg on this map: (previous map, next map, moment it leaves this map)."""
    start = ROVER.setdefault(k, now)
    i = int((now - start) // g['duration_sec'])
    r = g['route']
    return r[(i - 1) % len(r)], r[(i + 1) % len(r)], start + (i + 1) * g['duration_sec']


def gate_to(w, name):
    """The location of the portal on this map to the given map, or None."""
    g = next((g for g in w.gates if g.get('target') is not None and H.name(g['target']) == name), None)
    return (g['x'], g['y']) if g else None


def fmt(t, mc):
    return t.replace('{x}', mc.lower().replace('-', ''))


def base(tip):
    """event_curcubitor_x5 -> event_curcubitor."""
    head, _, tail = tip.rpartition('_')
    return head if tail[:1] == 'x' and tail[1:].isdigit() else tip


class MapEvents:
    def __init__(self, w):
        self.w = w
        self.mc = H.map_class(w.map_id)
        self.st = {}                   # event -> {counter, boss [id], end, order}
        self.calls = {}                # summoner alien id -> next summoning
        self.next_tick = 0.0

    def here(self, now=None):
        return [(k, s) for k, s in specs(now) if self.mc in s['maps']]

    def state(self, k):
        return self.st.setdefault(k, dict(counter=0, boss=[], end_time=None, order=0))

    def minion_types(self, s):
        return [fmt(u['type'], self.mc) for u in s.get('alien_spawns', [])]

    def cargo_kind(self, now=None):
        """The event look of the alien's cargo box (the section's 'cargo_kind': TURKEY_CARGO at Thanksgiving; same contents) or None."""
        return next((s['cargo_kind'] for k, s in self.here(now) if s.get('cargo_kind')), None)

    def active_type(self, tip, now=None):
        """Can this event type spawn now (the event is running and on this map)."""
        return any(tip in self.minion_types(s) for k, s in self.here(now))

    # ------------------------------------------------------------ setup and indicator
    def box_spec(self, tip, now=None):
        return next((b for k, s in self.here(now) for b in s.get('boxes', []) if b['type'] == tip), None)

    def spawn_box(self, tip):
        """Hunt box: at a random place, unlimited time; once collected a new one after renew_sec (if the event is running)."""
        spec = self.box_spec(tip)
        if not spec:
            return None
        x, y = self.w.random_spot()
        h = self.w.drop_box(tip, x, y, None, None)
        self.w.boxes[h]['event'] = spec
        return h

    def setup(self):
        """When the map opens (or the event starts): missing event aliens and hunt boxes."""
        w = self.w
        for k, s in self.here():
            for b in s.get('boxes', []):
                have = sum(1 for x in w.boxes.values() if x['tip'] == b['type'] and x.get('event'))
                for _ in range(max(0, SET.count('box_abundance', b.get('count', 1), 'event') - have)):
                    self.spawn_box(b['type'])
            for u in s.get('alien_spawns', []):
                tip = fmt(u['type'], self.mc)
                if tip not in w.CFG_TYPES:
                    continue
                have = sum(1 for n in w.npcs.values() if n.alive and n.tip == tip)
                for _ in range(max(0, SET.count('npc_count', u['count'], 'event') - have)):
                    w.spawn_npc(tip, announce=True)

    def info_msgs(self, now=None):
        now = time.time() if now is None else now
        msgs = []
        for k, s in self.here(now):
            b = s.get('info')
            if not b:
                continue
            st = self.state(k)
            quota = s.get('quota', {}).get(self.mc, 0)
            alive = [i for i in st['boss'] if i in self.w.npcs and self.w.npcs[i].alive]
            agatus = b['command'] == 'AgatusEventInfoCommand'
            pre = 'AgatusEvent' if agatus else 'NpcEvent'
            msgs.append((b['command'], dict(
                textKey=b['text'], type=0, npcID=b['npc'],
                bossInfoCommand=mod(pre + 'BossInfoCommand', bossCount=len(alive), leftToKill=max(0, quota - st['counter']) if quota else 0),
                timeInfoCommand=mod(pre + 'TimeInfoCommand', timeToNextSpawn=0, timeToEndSpawn=CAL.time_left(k, now)))))
        # the indicator also on a map with no event (Ö1, live test): boss and remaining kills 0 -> the client writes "There are no %NPC%
        # on this map" (NpcEventUIData.UpdateDescriptions); when it was not sent the window opened empty
        sent = {(c, f['textKey']) for c, f in msgs}
        for k, s in specs(now):
            b = s.get('info')
            if not b or (b['command'], b['text']) in sent:
                continue
            sent.add((b['command'], b['text']))
            pre = 'AgatusEvent' if b['command'] == 'AgatusEventInfoCommand' else 'NpcEvent'
            msgs.append((b['command'], dict(textKey=b['text'], type=0, npcID=b['npc'],
                                          bossInfoCommand=mod(pre + 'BossInfoCommand', bossCount=0, leftToKill=0),
                                          timeInfoCommand=mod(pre + 'TimeInfoCommand', timeToNextSpawn=0,
                                                              timeToEndSpawn=CAL.time_left(k, now)))))
        return msgs

    # ------------------------------------------------------------ events
    def on_kill(self, n, x, y, now=None, w=None, pay=None):
        """w: the world that killed (on a shared map self.w is the leader; drops and extra rewards are the killer's). pay: the worlds of
        those sharing the reward (including the killer; group: world.stakeholders): dropped boxes and extra rewards go to each with their own
        chance, in a group the box owner's."""
        w = w or self.w
        pay = pay or [w]
        owner = lambda v: v.hid if len(pay) > 1 else None
        box = n.d.get('box')                   # the type's box (event gates: wave box, Plutus's package, Synk's box)
        for v in pay:
            if box and random.random() < SET.chance('drop', box.get('probability', 1.0), 'event'):
                h = v.drop_box(box['type'], x, y, None, box.get('lifetime_sec', 300), owner(v))
                v.boxes[h]['event'] = box
        now = time.time() if now is None else now
        b, msgs = base(n.tip), []
        by_tip = lambda tab: tab.get(n.tip, tab.get(b))       # the map-specific version (event_chaos_protegit_x5) first, otherwise the base type
        trick = (n.tip.startswith('event_') and w.items is not None
                 and random.random() < max([s.get('trick', {}).get(b, 0) for k, s in self.here(now)] or [0]))
        if trick:                                                       # Trick: an uncollectable mine instead of the chest
            w.later(TRICK_DELAY, lambda: w.items.alien_mine(TRICK_MINE, x, y, n.id, time.time()))
        for k, s in self.here(now):
            roster_row = by_tip(s.get('box_drop', {}))
            for v in pay if roster_row and not trick else ():
                if random.random() < SET.chance('drop', roster_row.get('probability', 1.0), 'event'):    # the alien's box (Treat …)
                    for j in range(roster_row.get('count', 1)):                   # Demaner Freighter: 10 boxes, side by side
                        h = v.drop_box(roster_row['type'], x + 60 * (j % 5), y + 60 * (j // 5), None, roster_row.get('lifetime_sec', 300), owner(v))
                        v.boxes[h]['event'] = roster_row
            for sp in by_tip(s.get('spawn_on_death', {})) or []:            # spawned on death during the event: they target the killer
                if random.random() >= sp.get('probability', 1.0) or sp['type'] not in w.CFG_TYPES:
                    continue
                cnt = random.randint(*sp['count']) if isinstance(sp.get('count'), list) else sp.get('count', 1)
                for j in range(cnt):
                    a = 2 * math.pi * j / max(1, cnt)
                    c = w.spawn_npc_at(sp['type'], x + math.cos(a) * 150, y + math.sin(a) * 150)
                    c.summoned = True
                    c.engaged = True
                    c.next_think = now
                w.log('   %s died: %d x %s spawned (%s)' % (n.d['name'], cnt, sp['type'], k))
        for rocket, g in [r for k in sorted(CAL.active(now)) for r in rovers(k)]:
            if n.tip == g['type']:
                ROVER[rocket] = now + g.get('cooldown_sec', 1800)
                msgs.append(screen('key:msg_summoning_boss_killed', big=True, NPC_NAME=n.d['name']))      # "… Another will arrive soon!"
                w.log('   roamer %s destroyed (%s)' % (n.d['name'], rocket))
        if not n.tip.startswith('event_'):
            return msgs
        for k, s in self.here(now):
            st = self.state(k)
            drops = by_tip(s.get('drop', {}))
            if drops:
                msgs += w.extra_loot(n, drops)
                for v in pay:
                    if v is not w:
                        v.send(v.extra_loot(n, drops))
            if n.id in st['boss']:
                st['boss'].remove(n.id)
                if not st['boss']:
                    st['end_time'] = None
                    w.log('   event bosses destroyed (%s)' % k)
                msgs += self.info_msgs(now)
            elif n.tip in self.minion_types(s) and s.get('quota', {}).get(self.mc) and not st['boss']:
                st['counter'] += 1
                if st['counter'] >= s['quota'][self.mc]:
                    msgs += self.summon(k, s, now)
                msgs += self.info_msgs(now)
        self.calls.pop(n.id, None)
        return msgs

    def rover(self, now):
        """Is the roaming alien on this map: it spawns on arrival, leaves as it moves along the route."""
        w, out = self.w, []
        name = H.name(w.map_id)
        for k, rocket, g in [(k, rocket, g) for k in sorted(CAL.EVENTS) for rocket, g in rovers(k)]:
            st = self.state(k).setdefault('rover', {})
            # on re-entering the map the roamer coming from the map state is counted too (otherwise a second one spawned: live test
            # 2026-10-30)
            alive = [i for i, n in w.npcs.items() if n.alive and (i in st.get(rocket, []) or n.tip == g['type'])]
            at = route_at(rocket, g, now) if CAL.is_active(k, now) else None
            if at == name and not alive and g['type'] in w.CFG_TYPES:
                # darkorbitwiki (Hitac Mothership): "flies in a straight line between the ports and jumps to another map": it enters from
                # the previous map's portal and flies straight to the next one's portal (player report 2026-10-30: it spawned at a random
                # place and vanished when its time was up). Arrival: the end of its time on this map (sure_sn, adaptation)
                prev, nxt, until = route_leg(rocket, g, now)
                x, y = gate_to(w, prev) or w.random_spot()
                n = w.spawn_npc_at(g['type'], x, y)
                n.summoned = True                        # the world does not respawn it, it is not removed when the event ends (the route manages it)
                tx, ty = gate_to(w, nxt) or w.random_spot()
                n.route = (tx, ty, until)
                w.npc_summon(n, now, hit=False)          # fandom (Hitac-Mothership): comes with its six helpers
                for c in n.children:
                    w.npcs[c].engaged = False            # they attack when the player approaches or hits them (so they do not chase a distant one)
                alive = [n.id]
                out.append(screen('key:msg_npc_spawned_map', big=True, NPC_NAME=n.d['name'], MAP=name))
                w.log('   roamer %s arrived (%s)' % (n.d['name'], name))
            elif alive and at != name:
                for i in alive:
                    n = w.npcs[i]
                    for c in [c for c in n.children if c in w.npcs]:
                        w.alien.expire(w.npcs[c])
                    w.alien.expire(n)
                    out.append(screen('%s jumped to %s.' % (n.d['name'], at or '?')))
                    w.log('   roamer %s left -> %s' % (n.d['name'], at))
                alive = []
            st[rocket] = alive
        return out

    def summon(self, k, s, now):
        w, st, p = self.w, self.state(k), s['boss']
        st['counter'] = 0
        kinds = [fmt(t, self.mc) for t in p['kinds']]
        if p.get('in_order'):
            kinds = [kinds[st['order'] % len(kinds)]]
            st['order'] += 1
        hx, hy = w.hero_pos(now)
        for i in range(p.get('count', 1)):
            tip = kinds[i % len(kinds)]
            if tip not in w.CFG_TYPES:
                continue
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(900, 1400)
            x = min(max(600, hx + math.cos(a) * r), w.map_w - 600)
            y = min(max(600, hy + math.sin(a) * r), w.map_h - 600)
            c = w.spawn_npc_at(tip, x, y)
            c.summoned = True
            st['boss'].append(c.id)
        st['end_time'] = now + p.get('duration_sec', 1800)
        w.log('   event boss summoned (%s): %s x%d' % (k, ', '.join(kinds), len(st['boss'])))
        first = w.npcs.get(st['boss'][0]) if st['boss'] else None
        if first:
            w.cinematic(*first.mover.pos(now))                       # cinematic entry (Ö2; can be turned off from the panel)
        text = BOSS_TEXT.get((s.get('info') or {}).get('text'), (None, None))[0]
        return [legacy('0|A|STM|%s' % text)] if text else []

    def group(self, k, g, now):
        """Spawns the group at a random place on the map; the next group only when this group is destroyed and interval_sec has elapsed."""
        w, st = self.w, self.state(k).setdefault('group', {'members': [], 'next': 0})
        st['members'] = [i for i in st['members'] if i in w.npcs and w.npcs[i].alive]
        if st['members'] or now < st['next']:
            return []
        x, y = w.random_spot()
        kinds = [fmt(t, self.mc) for t, c in g['kinds'] for _ in range(c)]
        for i, tip in enumerate(kinds):
            if tip not in w.CFG_TYPES:
                continue
            a = 2 * math.pi * i / len(kinds)
            c = w.spawn_npc_at(tip, x + math.cos(a) * 250, y + math.sin(a) * 250)
            c.summoned = True                            # the world does not respawn it; a new one when the group is destroyed
            st['members'].append(c.id)
        st['next'] = now + g.get('interval_sec', 600)
        w.log('   event group spawned (%s): %d aliens (%d,%d)' % (k, len(st['members']), x, y))
        return []

    def tick(self, now):
        if now < self.next_tick:
            return
        self.next_tick = now + 1.0
        w, msgs = self.w, []
        here = self.here(now)
        for k, s in here:
            st = self.state(k)
            if s.get('group'):
                msgs += self.group(k, s['group'], now)
            if st['boss'] and st['end_time'] and now >= st['end_time']:          # time is up: the bosses flee
                for i in st['boss']:
                    n = w.npcs.get(i)
                    if n and n.alive:
                        w.alien.expire(n)
                st['boss'], st['end_time'] = [], None
                ran = BOSS_TEXT.get((s.get('info') or {}).get('text'), (None, None))[1] or 'npc_event_boss_ran_away'
                msgs += [legacy('0|A|STM|%s' % ran)] + self.info_msgs(now)
                w.log('   event bosses fled (%s)' % k)
            callers = {b: (c, False) for b, c in s.get('call', {}).items()}           # always (Ice Meteoroid)
            if s.get('boss', {}).get('call'):
                for t in s['boss']['kinds']:                                       # boss: while under attack (Agatus)
                    callers[base(fmt(t, self.mc))] = (s['boss']['call'], True)
            for n in list(w.npcs.values()):
                c, need_fight = callers.get(base(n.tip), (None, False)) if n.alive and n.tip.startswith('event_') else (None, False)
                if not c or (need_fight and not n.engaged):
                    continue
                if now < self.calls.setdefault(n.id, now + c['interval_sec']):
                    continue
                self.calls[n.id] = now + c['interval_sec']
                kids = [i for i in n.children if i in w.npcs and w.npcs[i].alive]
                tip = fmt(c['type'], self.mc)
                if tip not in w.CFG_TYPES:
                    continue
                nx, ny = n.mover.pos(now)
                for j in range(min(c['count'], c['max_count'] - len(kids))):
                    a = random.uniform(0, 2 * math.pi)
                    ch = w.spawn_npc_at(tip, nx + math.cos(a) * 150, ny + math.sin(a) * 150)
                    ch.summoned = True
                    ch.engaged = n.engaged
                    if c.get('lifetime_sec'):                     # I-Hitac's egg disappears after 90 s (alien.tick 'lifetime')
                        ch.ab['lifetime'] = now + c['lifetime_sec']
                    n.children.add(ch.id)
        msgs += self.rover(now)
        if here != getattr(self, 'last_here', None):        # event started/ended: aliens and indicator
            self.last_here = here
            keep = {fmt(u['type'], self.mc) for k, s in here for u in s.get('alien_spawns', [])}
            for n in list(w.npcs.values()):                  # the ended event's aliens (from the saved map state) are removed
                if n.alive and n.tip.startswith('event_') and not n.summoned and n.tip not in keep and not n.engaged:
                    w.alien.expire(n)
            boxes = {b['type'] for k, s in here for b in s.get('boxes', [])}
            for h, b in list(w.boxes.items()):                 # the ended event's hunt boxes
                if b.get('event') and b['event'].get('renew_sec') and b['tip'] not in boxes:
                    del w.boxes[h]
                    msgs.append(('RemoveCollectableCommand', {'collected': False, 'hash': h}))
            self.setup()
            msgs += self.info_msgs(now)
        if msgs:
            w.send(msgs)
