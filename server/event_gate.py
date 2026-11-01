"""Event gates (roadmap stage 7b; data in data/event_gates.json <- tools/event_gates.py).

Unlike the gates in the generator: no parts; while its event (event_calendar.py) runs, its portal stands on the entry map (X-1, X-4, X-8). On entering
through the portal the gate is set up (lives, wave order, start time); the waves, sub-groups, lives, permanent bosses and the multi-map flow are the same as
galaxy_gates.Run's (the wave format is gates.json's). Rules ('rule'):
  daily           one entry per day (gates in the same 'group' together: Gauntlet of Plutus Easy or Normal)
  cooldown_sec    cooldown after finishing or running out of lives (Trial of Terrors 12 hours)
  yearly          once a year (Birthday Gate)
  cpu             only a CPU opens the portal (Quarantine Zone: Immunizer CPU, X-7; Permafrost Fissure: Subglacial CPU, X-1; pve_modes.py);
                  cpu_hp: lives added if the CPU is used while the gate is open (Subglacial CPU +2; client text)
  quest           entered only while this quest (id) is running (Devolarium Attack: "Preemptive Strike Force" 20012; when finished, for the quest's
                  FINISH_STARTER_GATE condition the gate type STARTER_GATE); position: {company id: [x, y]} the sourced place of the portal on X-1
                  (Devolarium Attack's wiki coordinate; otherwise the portals line up in an arc in the middle of the map)
  level, once     minimum level; can be completed once (Compromising Invasion; The Breach Hard 16+)
  random          each map's waves in random order among themselves (a 'fixed' wave, Plutus, last; Gauntlet of Plutus)
  portals         this many portals on a map transition (all to a map in random order) and a return to base on the left; the maps are shuffled too,
                  the last map last (Trial of Terrors 3)
  sure            the finishing time is measured (dead time included); best times in the profile (Gauntlet of Plutus's personal record)
From the waves in an 'option' group (Vortex's "or" waves) one is chosen on entry. A wave alien's 'box' drops when it dies
(event_maps.py: Plutus Box, Demon Drone Box ...); 'extra_kinds' are non-wave kinds (Plutus's Warheads).
Rewards ('reward'): EP, honor, credits, uridium and items (through the shop's reward function).
In the profile: event_gates {gate: {ready, wave, can, order, start, done, last_day, last_year, last_end, best_sec, durations}}.
The Gauntlet of Plutus indicator uses the client's PlutusInfoCommand / PlutusStatusCommand (lives, mode, time left, best times).
Gates with no calendar (no 'event'): Quarantine Zone and Compromising Invasion (roadmap stage 8), Permafrost Fissure (opened with the Subglacial CPU,
45 waves, drops UFO and the Ufonit Proxium box: event_maps.roll) and Devolarium Attack (starter gate, with a quest).
The Breach (Cold Wave 2014, Easy 77 / Hard 78) is tied to the winter event ('kis').
Frozen Labyrinth is separate (labyrinth.py); its entry portal on X-1 is here.
"""
import datetime, json, math, os, random, time

import map_links as H
import galaxy_gates as KAPI
import rankings as RK
import event_calendar as CAL
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'event_gates.json'), encoding='utf8'))
GATES = D['kapilar']
DARK_MAPS = {int(m) for g in GATES.values() if g.get('dark') for m in g['maps']}      # flashlight (world.map_effect_msgs)
BY_MAP = {m: k for k, g in GATES.items() for m in g['maps']}
LAB = D['labyrinth']
PORTAL_BASE = 151900000                 # + id (entry), + 50 + id (return home), + 100 + id (next map)
LAB_ENTRY = PORTAL_BASE + 99            # the Frozen Labyrinth portal on X-1
# PlutusStatusCommand.mode: the window's status line (client PlutusUIData.UpdateStatus): 0/1 finished today ("Next Gauntlet opens in",
# countdown), 2 open ("Time left to defeat Plutus", countdown), 3 running ("Time spent in the Gauntlet", count up), 4 event
# over ("Rankings will be tallied in"). It was first assumed to be easy/normal: while a run was going it said "you finished today" (live test H48)
PLUTUS_DONE, PLUTUS_OPEN, PLUTUS_RUNNING = 1, 2, 3


def poi(pid, x, y, r, ptype=4, design=6):
    """MapAddPOICommand (the format of world_boss.poi; ptype 4 / design 6: green healing circle)."""
    return ('MapAddPOICommand', dict(inverted=False, poiTypeSpecification='', poiType=KAPI.mod('POITypeModule', typeValue=ptype), shape=0,
                                     active=True, design=KAPI.mod('POIDesignModule', designValue=design), poiId=pid,
                                     shapeCoordinates=[int(x), int(y), int(r)]))


def npc_type(key, wave, i):
    return 'eg_%s_%d_%d' % (key, wave, i)


def extra_type(key, name):
    return 'eg_%s_ek_%s' % (key, name)


def time_score(secs):
    """Plutus time score (forum 143902: the score depends on time, no points over 60 min; the formula is not in the source: adaptation)."""
    return max(0, int(round(1000 * (3600 - secs) / 3600.0)))


def _tip(a, key=None, aggressive=True):
    d = dict(name=a['display_name'], model=str(a['type']), hp=a['hp'], kalkan=a['kalkan'], damage=a['damage'], speed=a['speed'],
             aggressive=a.get('aggressive', aggressive), reward=dict(a['reward']), cargo=dict(a.get('cargo', {})), npc_id=a['npc_id'])
    if key:
        d['gate'] = key
    for k in ('box', 'behavior', 'anahtar', 'drop', 'renew_sec', 'points', 'extra_reward', 'cpu_increase', 'radioactive', 'range', 'hit',
              'shield_absorb', 'fugitive', 'empower'):
        if a.get(k):
            d[k] = a[k]
    return d


# the event name in the achievement for event points (achievement.py EventScore: "1,000 / 5,000 / 10,000 points in a Gauntlet of Plutus event")
SCORE_EVENTS = {'plutus': 'GauntletOfPlutus'}


def register_npcs(types):
    """Adds the gate and labyrinth aliens as NPC types (the format of gates.register_npcs)."""
    for key, g in GATES.items():
        for n, w in enumerate(g['waves']):
            for i, a in enumerate(w['alien_spawns']):
                types[npc_type(key, n, i)] = _tip(a, key)
        for name, a in g.get('extra_kinds', {}).items():
            types[extra_type(key, name)] = _tip(a, key)
        for k in [k for k in types if k.startswith(('eg_%s_' % key))]:
            types[k].setdefault('shield_absorb', KAPI.GATE_ABSORB)      # gate aliens 50% (galaxy_gates.GATE_ABSORB)
    for k, a in LAB['alien_spawns'].items():
        types[k] = _tip(a, aggressive='meteoroid' not in k and 'synk' not in k)


def center(map_id):
    w, h = H.map_size(map_id)
    return w // 2, h // 2


def today(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()


def fmt_time(secs):
    m, s = divmod(int(secs), 60)
    return '%d:%02d:%02d' % (m // 60, m % 60, s) if m >= 60 else '%d:%02d' % (m, s)


class EventGates:
    """The interface of galaxy_gates' gate manager (gate, finish, exit_portal, next_portal, home, p) for event gates."""

    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                       # shop (item rewards)
        self.finish_hooks = []              # when the gate is finished (key) -> messages (Fiesta Gate's AP: fiesta.py)
        self.wave_hooks = []                # when a wave is finished (key, total waves) -> messages (the old Invasion: invasion.py)

    @property
    def d(self):
        return self.p.d.setdefault('event_gates', {})

    def gate(self, key):
        return self.d.setdefault(key, dict(ready=False, wave=0, can=GATES[key]['can'], done=0))

    def home(self):
        return KAPI.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5)

    # ------------------------------------------------------------ entry
    def allowed(self, key, now=None):
        """-> (girilebilir mi, neden)."""
        now = time.time() if now is None else now
        g, G = GATES[key], self.gate(key)
        if G.get('ready'):
            return True, 'sürüyor'
        if g.get('event') and not CAL.is_active(g['event'], now):
            return False, 'etkinlik yok'
        rule = g.get('rule', {})
        if SET.get('no_entry_limit'):                       # panel: no daily/yearly/one-time and no cooldown
            rule = {k: v for k, v in rule.items() if k not in ('once', 'daily', 'yearly', 'cooldown_sec')}
        if rule.get('cpu'):
            return False, 'CPU ile açılır'            # Quarantine Zone, Permafrost Fissure: the CPU sets up the gate (pve_modes.py)
        if rule.get('quest') and str(rule['quest']) not in (self.p.d.get('quests') or {}).get('active', {}):
            return False, 'görev gerekli'             # Devolarium Attack: only while the "Preemptive Strike Force" quest is running
        if rule.get('level') and self.p.d['pilot'].get('level', 1) < rule['level']:
            return False, 'seviye %d gerekli' % rule['level']
        if rule.get('max_level') and self.p.d['pilot'].get('level', 1) > rule['max_level']:
            return False, 'seviye en çok %d' % rule['max_level']          # the old Invasion: a gate by level range
        if rule.get('company') and rule['company'] != self.p.d['pilot'].get('factionId'):
            return False, 'başka firmanın kapısı'
        if rule.get('once') and G.get('done', 0) > 0:
            return False, 'tamamlandı'
        if rule.get('daily'):
            group = [k for k, x in GATES.items() if x.get('rule', {}).get('group', k) == rule.get('group', key)]
            if any(self.gate(k).get('last_day') == today(now) for k in group):
                return False, 'bugün girildi'
        if rule.get('yearly') and G.get('last_year') == today(now)[:4]:
            return False, 'bu yıl girildi'
        if rule.get('daily') and 0 < 86400 - (now - time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))) < 300:
            return False, 'günlük sıfırlamaya 5 dk kaldı'                # forum 143902
        if rule.get('period') and not CAL.forced(g.get('event')) and not CAL._span_at(rule['period'], datetime.datetime.fromtimestamp(now)):
            return False, 'kapı dönemi dışında'                            # The Breach: 11 December - 1 January (forum 134831)
        if rule.get('cooldown_sec') and now < G.get('last_end', 0) + rule['cooldown_sec']:
            return False, 'bekleme %d sn' % (G['last_end'] + rule['cooldown_sec'] - now)
        return True, ''

    def here(self, want, map_id):
        if want == 'X-1':
            return int(map_id) == self.home()
        return H.map_class(map_id) == want and H.company(map_id) == self.p.d['pilot'].get('factionId')

    def entry_portals(self, map_id, station, now=None):
        """The event gate portals on this map (while the event runs and can be entered) and the Frozen Labyrinth's on X-1."""
        now = time.time() if now is None else now
        out = []
        for key in sorted(GATES):
            g = GATES[key]
            if g.get('rule', {}).get('windowed'):
                continue                    # windowed entry (Fiesta Gate: one portal, the window chooses the difficulty; fiesta.py)
            if not self.here(g['entry'], map_id) or not self.allowed(key, now)[0]:
                continue
            dest = self.dest(key)
            out.append(dict(gateId=PORTAL_BASE + g['uid'], x=0, y=0, target=dest, designId=g['portal'], gate=key,
                            event_gate=True, arrival=center(dest)))
        if self.here(LAB['entry'], map_id) and CAL.is_active(LAB['event'], now):
            import labyrinth as LB
            dest = random.choice(LAB['start'])
            out.append(dict(gateId=LAB_ENTRY, x=0, y=0, target=dest, designId=LAB['portal'], gate='labyrinth',
                            arrival=LB.arrival_spot(dest)))
        # open portals side by side on an arc above the middle of the map (wiki: the Level Invasion gates are in the middle of the map;
        # official server recording: the event portals on 2-1 are in the middle column, between (10700, 3000) and (11210, 6310)). They used to
        # line up behind the base toward the corner.
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2
        for i, g in enumerate(out):
            a = -math.pi / 2 + (i - (len(out) - 1) / 2.0) * 0.55
            g['x'], g['y'] = int(cx + math.cos(a) * 2400), int(cy + math.sin(a) * 2400)
            pos = (GATES.get(g['gate'], {}).get('position') or {}).get(str(self.p.d['pilot'].get('factionId')))
            if pos:
                g['x'], g['y'] = pos                    # sourced position (Devolarium Attack: the wiki's X-1 coordinate per company)
        return out

    def enter(self, key, now=None):
        """Entered through the portal: if not set up, the gate is set up (lives, wave order, time)."""
        now = time.time() if now is None else now
        g, G = GATES[key], self.gate(key)
        if G.get('ready'):
            return
        waves = g['waves']
        groups = {}
        for i, w in enumerate(waves):
            if w.get('option'):
                groups.setdefault(w['option'], []).append(i)
        pick = {s: random.choice(v) for s, v in groups.items()}       # one of the "or" waves
        order = [i for i, w in enumerate(waves) if not w.get('option') or pick[w['option']] == i]
        if g.get('rule', {}).get('random'):        # the same map's waves shuffle among themselves
            by_map = {}
            for i in order:
                by_map.setdefault(waves[i]['map'], []).append(i)
            order = []
            maps = sorted(by_map, key=lambda m: min(by_map[m]))
            if g['rule'].get('portals'):          # Trial of Terrors: the maps are shuffled too, the last map (boss) last
                head = maps[:-1]
                random.shuffle(head)
                maps = head + maps[-1:]
            for m in maps:
                part = by_map[m]
                rest = [i for i in part if not waves[i].get('fixed')]
                random.shuffle(rest)
                order += rest + [i for i in part if waves[i].get('fixed')]
        with self.p.lock:
            G.update(ready=True, wave=0, can=SET.count('gate_lives', g['can']), order=order, start=now, last_day=today(now),
                     last_year=today(now)[:4])                   # panel: gate lives
            self.p.dirty = True
        self.log('   %s set up (%d waves, %d lives)' % (g['name'], len(order), G['can']))

    def dest(self, key):
        """The map to land on when entering the gate: the next wave's in a running gate, the first wave's if not set up."""
        G, g, order = self.gate(key), GATES[key], self.order(key)
        return g['waves'][order[min(G['wave'], len(order) - 1)]]['map'] if G.get('ready') else g['waves'][0]['map']

    def order(self, key):
        G = self.gate(key)
        return G.get('order') or list(range(len(GATES[key]['waves'])))

    # ------------------------------------------------------------ portals
    def exit_portal(self, key, map_id, side=False):
        x, y = center(map_id)
        return dict(gateId=PORTAL_BASE + 50 + GATES[key]['uid'], x=x - 1500 if side else x, y=y, target=self.home(), designId=1,
                    gate=key, exit=True, arrival='station')

    def next_portal(self, key, map_id, dest):
        x, y = center(map_id)
        return dict(gateId=PORTAL_BASE + 100 + GATES[key]['uid'], x=x, y=y, target=dest, designId=GATES[key]['portal'], gate=key,
                    arrival=center(dest))

    def next_portals(self, key, map_id, dest):
        """The next map's portals: as many as the rule's 'portals' (Trial of Terrors 3; all to a map in random order: fandom
        Vortex of Terror "waves are random with portals, which portal leads to which wave is unknown"; player report 2026-10-27:
        3 portals, a return to base on the left) or a single portal."""
        n = GATES[key].get('rule', {}).get('portals', 1)
        one = self.next_portal(key, map_id, dest)
        return [dict(one, gateId=one['gateId'] + 200 * j, y=one['y'] + (j - (n - 1) / 2.0) * 1400) for j in range(n)]

    # ------------------------------------------------------------ finish
    def end(self, key, now=None):
        now = time.time() if now is None else now
        with self.p.lock:
            G = self.gate(key)
            G.update(ready=False, wave=0, can=GATES[key]['can'], last_end=now)
            G.pop('order', None)
            G.pop('cpu_increase', None)
            self.p.dirty = True

    def finish(self, key, reward_msgs=None):
        """The last wave ended: rewards, time (best), the gate closes -> (messages, info)."""
        g, G, now = GATES[key], self.gate(key), time.time()
        o = g.get('reward', {})
        msgs = []
        cbs = self.p.cbs_mods() if getattr(self.p, 'cbs_mods', None) else {}
        currency = {k: SET.amount(k, int(o[k] * (1 + cbs.get(k, 0))) if k in ('ep', 'honor') else o[k], 'gate')
                for k in ('ep', 'honor', 'credits', 'uridium') if o.get(k)}      # the panel's multipliers
        if currency:
            tot = self.p.gain(reason='galaxy_gate_done', **currency)
            msgs += reward_msgs(tot, **currency) if reward_msgs else []
        for loot, n in o.get('items', []):
            n = random.randint(*n) if isinstance(n, list) else n          # range (Indoctrine Oil 0-20)
            if n > 0 and self.m:
                msgs += self.m.prize(loot, n, 'gate')        # panel: gate/mode reward multiplier
        if o.get('one_of') and self.m:                       # one picked by probability weight (Quarantine Box's ammo pack)
            loot, n, _ = random.choices(o['one_of'], weights=[w for _, _, w in o['one_of']])[0]
            msgs += self.m.prize(loot, random.randint(*n) if isinstance(n, list) else n, 'gate')
        for loot, n, chance in o.get('chance', []):          # lucky reward (Quarantine Box's LF-4)
            if random.random() < SET.chance('drop', chance, 'gate') and self.m:
                msgs += self.m.prize(loot, n, 'gate')
        if o.get('rolls') and self.m:                     # Quarantine: Indoctrine Oil rolls (forum 140274)
            loot, rows = o['rolls']
            n = sum(random.randint(*a) if isinstance(a, list) else a for a, c in rows if random.random() < SET.chance('drop', c, 'gate'))
            msgs += self.m.prize(loot, n, 'gate') if n else []
        bp = o.get('big_pack')
        if bp and self.m and random.random() < SET.chance('drop', bp['probability'], 'gate'):     # 0.001% Big Reward Pack
            for loot, n in bp['items']:
                if loot == 'premium_30':
                    self.p.d['pilot']['premium'] = True        # in single player Premium is always on: only the record
                    continue
                msgs += self.m.prize(loot, n, 'gate')
        c = g.get('cpu')
        if c and self.m and random.random() < SET.chance('drop', c['base'] + G.get('cpu_increase', 0.0), 'gate'):
            msgs += self.m.prize(c['item'], 1, 'gate')     # Bountiful Alien CPU: base chance, increases per Aura Dun Jig killed
        secs = int(now - G.get('start', now))
        best = G.get('best_sec')
        with self.p.lock:
            G['done'] = G.get('done', 0) + 1
            if g.get('rule', {}).get('sure') and g.get('mod') != 'easy' and secs <= 3600:   # forum 143902: Normal only, under 60 min
                if best is None or secs < best:
                    G['best_sec'] = secs
                G['durations'] = sorted(G.get('durations', []) + [secs])[:5]
            self.p.dirty = True
        self.end(key, now)
        for fn in self.finish_hooks:
            msgs += fn(key)
        self.p.ach('gate', type=g.get('gate_kind') or '%s_GATE' % key.upper())    # the client's GalaxyGateType (Birthday: BIRTHDAY)
        record = G.get('best_sec') == secs and best != secs
        if record:
            self.p.ach('record_plutus')               # champion achievement (Gauntlet of Plutus; a timed single gate): personal record
        self.log('   %s completed: %s%s' % (g['name'], fmt_time(secs), ' (new record)' if record else ''))
        return msgs, dict(new={'parts': []}, kronos=None, sure=secs)

    # ------------------------------------------------------------ event points (Gauntlet of Plutus)
    def score(self, key, now=None):
        """The point record in this event period {period, points}: Easy and Normal together; from scratch in a new period."""
        ev = GATES[key].get('event') or key
        p = CAL.period(ev, now) if ev in CAL.EVENTS else None
        period = int(p[0]) if p else 0
        rec = self.d.setdefault('points', {}).get(ev)
        if not rec or rec.get('period') != period:
            rec = self.d['points'][ev] = {'period': period, 'points': 0}
        return rec

    def add_points(self, key, n, now=None):
        """An alien's event points (source: a range per alien, forum 2019) -> PlutusPointsUpdateCommand; achievement event."""
        with self.p.lock:
            rec = self.score(key, now)
            rec['points'] += n
            self.p.dirty = True
        ev = GATES[key].get('event')
        if ev in SCORE_EVENTS:
            self.p.ach('event_score', event=SCORE_EVENTS[ev], value=rec['points'])
        G = self.gate(key)
        entries = [dict(_='PlutusScoreEntryModule', score=time_score(s), timeInSeconds=int(s)) for s in G.get('durations', [])]
        return [('PlutusPointsUpdateCommand', dict(scoreEntriesList=entries, score=rec['points']))]

    # ------------------------------------------------------------ Gauntlet of Plutus indicator
    def plutus_cmds(self, key, now=None):
        g = GATES.get(key, {})
        if not g.get('rule', {}).get('sure'):
            return []
        now = time.time() if now is None else now
        G = self.gate(key)
        group = [k for k, x in GATES.items() if x.get('rule', {}).get('group') == g.get('rule', {}).get('group')] or [key]
        done_today = any(self.gate(k).get('last_day') == today(now) and not self.gate(k).get('ready') for k in group)
        if G.get('ready') and G.get('start'):
            mode, t = PLUTUS_RUNNING, now - G['start']                     # elapsed time
        elif done_today:
            tomorrow = datetime.datetime.combine(datetime.date.fromtimestamp(now) + datetime.timedelta(days=1), datetime.time())
            mode, t = PLUTUS_DONE, tomorrow.timestamp() - now            # left until tomorrow
        else:
            mode, t = PLUTUS_OPEN, CAL.time_left(g['event'], now)      # the event's remaining time
        status = dict(_='PlutusStatusCommand', lifes=int(G.get('can', g['can'])), mode=mode, timeLeft=int(max(0, t)))
        entries = [dict(_='PlutusScoreEntryModule', score=time_score(s), timeInSeconds=int(s)) for s in G.get('durations', [])]
        return [('PlutusInfoCommand', dict(playerPoints=int(self.score(key, now)['points']), scoreEntriesList=entries, status=status,
                                           playerRanges=RK.ranges(RK.PLUTUS),          # the reward tab's ranges (stage 1)
                                           filename=''))]


class Run(KAPI.Run):
    """Waves on the event gate map: galaxy_gates.Run, with EventGates' wave order, finish and lives."""

    def __init__(self, event_gate, world, key):
        self.k, self.w, self.key = event_gate, world, key
        self.g = GATES[key]
        self.map = int(world.map_id)
        G = event_gate.gate(key)
        self.npcs, self.keep = set(), set()
        self.guards = set()           # those guarding the permanent boss (the wave's spawned aliens; not the summoned ones: Plutus's Warheads)
        self.rad, self.rad_next = None, 0.0     # the radioactive field in progress (radio_tick) and the earliest time of the next
        self.sub, self.counted, self.left, self.exposed, self.boss = 0, None, None, False, ''
        now = time.time()
        if not G['ready'] or G['can'] <= 0:
            self.phase, self.t = 'void', now
            world.add_gate(event_gate.exit_portal(key, self.map))
        elif self.cur_map() != self.map:
            self.phase, self.t = 'void', now
            for g in event_gate.next_portals(key, self.map, self.cur_map()):
                world.add_gate(g)
            world.add_gate(event_gate.exit_portal(key, self.map, side=True))
        else:
            wait = self.g.get('rule', {}).get('entry_sec')         # Plutus: Normal 1 s, Easy 15 s (forum 143902)
            self.phase, self.t = 'intro', now + (KAPI.pace('intro_wait_sec') if wait is None else wait * SET.multiplier('wave_wait'))
            world.send(self.say('ongoing' if G['wave'] else 'entry') + self.k.plutus_cmds(key, now))
        world.log('   %s: wave %d/%d, lives %d (%s)' % (self.g['name'], G['wave'] + 1, self.wave_count(), G['can'], self.phase))

    def messages(self):
        return dict(KAPI.K['messages'], **self.g.get('messages', {}))

    def points(self, n):
        """This gate's alien died (world.kill): event points from the kind's point range (Plutus)."""
        if n.d.get('gate') != self.key or not n.d.get('points'):
            return []
        if n.d.get('cpu_increase'):                                      # Aura Dun Jig: Bountiful Alien CPU chance (EventGates.finish)
            with self.k.p.lock:
                G = self.k.gate(self.key)
                G['cpu_increase'] = G.get('cpu_increase', 0.0) + n.d['cpu_increase']
                self.k.p.dirty = True
        return self.k.add_points(self.key, random.randint(*n.d['points']))

    # ------------------------------------------------------------ Space Uncertainty (the radioactive field of a boss whose shield is gone)
    def tick(self, now):
        super().tick(now)
        self.radio_tick(now)

    def radio_tick(self, now):
        """When the permanent boss's (the npc type's 'radioactive'; Plutus) shield runs out, a radioactive field: after the warning, for sure_sn every
        second a player outside the green circles takes damage (no more than max_ratio of max HP), one inside heals; when the field
        ends, after cooldown_sec (if the shield is still 0) a new one (darkorbitwiki "Space Uncertainty", fandom)."""
        w, r = self.w, self.rad
        boss = self.boss_npc() if self.phase == 'fight' else None
        spec = boss.d.get('radioactive') if boss else None
        if r and (not spec or w.hero_dead or w.jumping):
            self.radio_end(now)
        elif not r:
            if spec and boss.shield <= 0 and now >= self.rad_next and not w.hero_dead and not w.jumping:
                self.radio_start(boss, spec, now)
        else:
            if now >= r['next']:
                r['next'] += 1.0
                self.radio_pulse(boss, spec, now)
            if now >= r['end_time']:
                self.radio_end(now)

    def radio_start(self, boss, spec, now):
        w = self.w
        hx, hy = w.hero_pos(now)
        a0, circles = random.uniform(0, 2 * math.pi), []
        for i in range(spec['circle']):          # one is near (reached during the warning time), the others far
            a = a0 + i * 2 * math.pi / spec['circle']
            d = random.uniform(*spec['distance']) if i else spec['distance'][0]
            m = spec['radius']
            circles.append((min(max(m, hx + math.cos(a) * d), w.map_w - m), min(max(m, hy + math.sin(a) * d), w.map_h - m)))
        self.rad = dict(circles=circles, end_time=now + spec['warning_sec'] + spec['sure_sn'], next=now + spec['warning_sec'])
        w.send([KAPI.screen('Plutus: Space Uncertainty! Get into a green circle!', big=True)]
               + [poi('plutusSpaceUncertainty%d' % i, x, y, spec['radius']) for i, (x, y) in enumerate(circles)])
        w.log('   %s: radioactive field (%d circles, %d s)' % (self.g['name'], len(circles), spec['sure_sn']))

    def radio_pulse(self, boss, spec, now):
        """Per-second pulse: heal if inside the circle, damage if outside."""
        w = self.w
        hx, hy = w.hero_pos(now)
        g = w.p.d['ship']
        if any(math.hypot(hx - x, hy - y) <= spec['radius'] for x, y in self.rad['circles']):
            hp0 = g.get('hitPoints', 0)
            w.p.set_hull(hp=hp0 + spec['heal_sec'])
            w.send([w.hp_msg()] + w.heal_msgs(hp0))
        else:
            w.send(w.hurt_hero(min(spec['damage_per_sec'], int(g.get('hitMax', 1) * spec['max_ratio'])), boss, atype=0, now=now,
                               source_asset=True))

    def radio_end(self, now):
        r, self.rad = self.rad, None
        spec = next((n.d.get('radioactive') for n in (self.w.npcs.get(i) for i in self.keep) if n and n.d.get('radioactive')), None)
        self.rad_next = now + (spec['cooldown_sec'] if spec else 0)
        if r:
            self.w.send([('MapRemovePOICommand', {'poiId': 'plutusSpaceUncertainty%d' % i}) for i in range(len(r['circles']))])

    def wave_count(self):
        return len(self.k.order(self.key))

    def say(self, event, **extra):
        """galaxy_gates.Run.say, with the wave count in the chosen order."""
        G = self.k.gate(self.key)
        n = min(G['wave'], self.wave_count() - 1)
        vals = dict(gate=self.g['name'], wave=n + 1, total=self.wave_count(), can=G['can'], anahtar=self.key,
                    groups=len(self.wave()['groups']), sure='')
        vals.update(extra)
        m = self.messages().get(event, {})
        return [KAPI.screen(m[kind].format(**vals), big=kind == 'caps', NAME=self.g['name'], WAVE='%d/%d' % (vals['wave'], vals['total']))
                for kind in ('caps', 'short') if kind in m]

    def cur_map(self):
        return self.wave()['map']

    def wave(self):
        G = self.k.gate(self.key)
        order = self.k.order(self.key)
        return self.g['waves'][order[min(G['wave'], len(order) - 1)]]

    def wave_msgs(self):
        return self.k.plutus_cmds(self.key)

    def sub_msgs(self):
        return []

    def spawn_one(self, i, group, x, y):
        """galaxy_gates.Run.spawn_one's version with event gate kinds (eg_*): the permanent boss's guards take no damage until spawned and dead."""
        w, G = self.w, self.k.gate(self.key)
        a = self.wave()['alien_spawns'][i]
        # with a "player"-looking alien (Compromising Invasion wave 7 Evil You) using the player's ship: the kind's "player" model is not drawn in the client,
        # the ship was invisible and could not be selected, and it was hitting with rockets (player report 2026-10-30)
        model = self.k.p.ship_look() if a['type'] == 'player' else None
        n = w.spawn_npc_at(npc_type(self.key, self.k.order(self.key)[G['wave']], i), x, y, model=model, wave=True)
        n.gate, n.hunt = True, True
        self.npcs.add(n.id)
        group.add(n.id)
        if a.get('permanent'):
            self.keep.add(n.id)
            n.invulnerable = lambda: bool(self.queue) or any(j in self.w.npcs for j in self.guards)
            self.boss = a['display_name']
            w.send(self.say('protection', name=a['display_name']))
        else:
            self.guards.add(n.id)
        return n

    def wave_done(self, now):
        G = self.k.gate(self.key)
        label = self.wave()['name']
        with self.k.p.lock:
            G['wave'] += 1
            self.k.p.dirty = True
        self.npcs.clear()
        self.keep.clear()
        self.guards.clear()
        with self.k.p.lock:
            G['total_waves'] = G.get('total_waves', 0) + 1
            self.k.p.dirty = True
        for fn in self.k.wave_hooks:
            self.w.send(fn(self.key, G['total_waves']))
        if G['wave'] >= self.wave_count() and self.g.get('rule', {}).get('infinite'):
            with self.k.p.lock:
                G['wave'] = 0                      # endless gate (the old Invasion): from the start after the last wave
                self.k.p.dirty = True
        if G['wave'] >= self.wave_count():
            self.complete()
            return
        nxt = self.cur_map()
        if nxt != self.map:
            for g in self.k.next_portals(self.key, self.map, nxt):
                self.w.add_gate(g)
            self.w.add_gate(self.k.exit_portal(self.key, self.map, side=True))
            self.w.send(self.say('next_map', wave=G['wave']) + self.k.plutus_cmds(self.key))
            self.phase = 'move'
            self.w.log('   %s: wave %s finished; next map %s' % (self.g['name'], label, nxt))
            return
        self.counted = None
        self.w.add_gate(self.k.exit_portal(self.key, self.map))
        self.w.send(self.say('wave_finished', wave=G['wave'], sn=KAPI.pace('wave_break_sec')) + self.k.plutus_cmds(self.key))
        self.phase, self.t = 'break', now + KAPI.pace('wave_break_sec')
        self.w.log('   %s: wave %s finished' % (self.g['name'], label))

    def complete(self):
        k, w = self.k, self.w
        msgs, info = k.finish(self.key, w.reward_msgs)
        w.add_gate(k.exit_portal(self.key, self.map))
        msgs += self.say('done', sure=fmt_time(info['sure'])) + k.plutus_cmds(self.key)
        w.send(msgs)
        self.phase = 'done'

    def on_death(self):
        """Lives drop by 1; if none left the gate closes (the cooldown starts)."""
        if self.phase in ('void', 'done'):
            return None
        k, G = self.k, self.k.gate(self.key)
        with k.p.lock:
            if not SET.get('infinite_lives'):                    # panel: no lives are spent in the gate
                G['can'] = max(0, G['can'] - 1)
            left = G['can']
            k.p.dirty = True
        if left <= 0:
            k.end(self.key)
        self.w.send([KAPI.screen('%s: you lost a life.' % self.g['name']), KAPI.stm('lifes_left', '%!', left)] + k.plutus_cmds(self.key))
        self.w.log('   %s: life lost, %d left%s' % (self.g['name'], left, ' (gate closed)' if left <= 0 else ''))
        self.before_death = self.phase
        self.phase = 'void' if left <= 0 else 'dead'
        return left
