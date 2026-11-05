"""Achievements and titles (profile key "basarimlar"; data data/achievements.json <- the client's achievement XMLs, tools/achievements.py).

Record: AchievementListRequest {displayTitleId} -> AchievementListCommand {list: completed achievements (AchievementInfoCommand
{achievementId, level: completed level, score: that level's target, lastUpdate}), unlockAchievements1: achievements in progress (level:
next level, score: counter; only those above 0), nextAchievements: 7 of these, unlockAchievements2 [], displayTitleId
(-1: no title), titleCommandList [AchievementTitleCommand {key, id}]}. The client sums the points from its own XML.
From the client code: on completion "0|A|ACG|<achievement>_<grade>|<count>" (grade: the XML's grade; effect on the ship and a popup: %COUNT% in
<key>_name and <key>_description); the title save button on the pilot page sends AchievementListRequest {displayTitleId: selected}
(0: change ignored). The title on the ship is "0|n|t|<user>|<title id>|<title key>" (record).
Events arrive through player_profile.ach(type, ...) (world, quests, gates, shop, P.E.T.): kill, gain, box, box_ammo, quest, map, jump,
distance, shot, damage, minute, formation, equip, gate, death, level, pet_level, ability, laser_types, tutorial, season_level,
dispatch, event_score, assembly_collect, package, gate_wave; E6: display (the display setting's displayUse2d: 3D), egg (the client's
EggTriggerRequest), wb_heal / wb_damage (HP repaired and damage taken in the World Boss fight), rekor_ebl / rekor_plutus (champion
achievements: in the single-player ranking the personal record is first place). Conditions with no counterpart (PvP, player conversion with WIZ-X, clan,
Skylab, champions of dead mods ...) stay in the data and do not progress.
"""
import json, os, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'achievements.json'), encoding='utf8'))
ACH = D['achievements']
TITLES = D['titles']
TITLE_KEYS = {v: k for k, v in TITLES.items()}
EVENT_TITLE_BASE = 2000          # titles not in the table (event ones): 2000 + crc32 % 30000 (the id is a short in the client)
CURRENCY = {'CREDITS': 'credits', 'URIDIUM': 'uridium', 'EXPERIENCE': 'ep', 'HONOUR': 'honor'}
NEXT = 7                         # record: nextAchievements is 7 entries
# event achievements (EVENT_* groups, season pass, those with an event attribute) progress only while that event is open; the server has
# no events, the data stays in place. When an event is added, add its group (or event name) here.
ACTIVE_EVENTS = set()
# condition class -> the events that advance it (the engine looks only at these)
KINDS = {'Currency': 'gain', 'AvatarTypeKill': 'kill', 'NpcTypeDestroyed': 'kill', 'Collect': 'box', 'AssetCollect': 'box_ammo',
         'Quest': 'quest', 'QuestDeathless': 'quest', 'QuestSelection': 'quest', 'DiscoverMaps': 'map', 'Gatejumps': 'jump',
         'Distance': 'distance', 'AmmoShots': 'shot', 'Damage': 'damage', 'Playtime': 'minute', 'PlaytimeOnEnemyMap': 'minute',
         'MapTypeCheck': 'minute', 'DroneFormationChange': 'formation', 'DroneFormationDroneAmount': 'formation', 'EquipItem': 'equip',
         'GalaxyGateDone': 'gate', 'Destruction': 'death', 'KilledByAvatarType': 'death', 'Level': ('level', 'pet_level'),
         'AbilityType': 'ability', 'LaserTypeUsage': 'laser_types', 'TutorialFinished': 'tutorial',
         'PlayerCloaked': 'cloak_minute', 'ChainImpulse': 'chain_kill',
         # Ö1 (2026-10-18): Season Pass level (season.py), Dispatch (dispatch.py), selected alien type (world.py, by the client's ShipIcon
         # name), event score (Plutus: event_gate.py), production collected in Assembly (assembly.py), mine laying (combat_items.py: shot MINE), package reward
         # (galaxy_gates.py: Prosperous), EBL wave (ebl.py). DesignMutationCount (player conversion with WIZ-X) goes with the bot players.
         'LevelAbsolute': 'season_level', 'Dispatch': 'dispatch', 'NPCSelectionKill': 'kill', 'EventScore': 'event_score',
         'BuildRecipe': 'assembly_collect', 'TriggerMine': 'shot', 'CollectPackage': 'package', 'ClearGalaxyGateWave': 'gate_wave',
         # E6
         'Uses3D': 'display', 'EggTriggerCount': 'egg', 'PublicWorldBossCondition': ('wb_heal', 'wb_damage'),
         'Influence': 'influence', 'TeamDeathMatchKill': 'tdm_kill'}       # Battle for Influence: the influence points of a gate victory (galaxy_gates.py; official forum 131012)
# calendar-less event groups: always open (Eternal Black Light's old name is Eternal Gate; the mod is open every day; hidden Easter Eggs)
ALWAYS_GROUPS = {'EVENT_ETERNALGATE', 'EVENT_SECRET'}
# when the client's ShipIcon name cannot be derived from the alien's name (NPCSelectionKill)
ICON_ALIASES = {'FRIGHTFUL_CURCUBITOR': 'BOSS_FRIGHTFUL_CURCUBITOR'}


def ship_icons(name):
    """The alien's display name -> candidates for the client's ShipIconModule.ShipIcon ("..::{ Boss StreuneR }::.." -> BOSS_StreuneR,
    BOSS_STREUNER; the enum is case-sensitive: StreuneR and Streuner are separate types)."""
    import re
    words = re.findall(r'[A-Za-z0-9]+', name or '')
    if not words:
        return ()
    exact = '_'.join(w.upper() if w.lower() == 'boss' else w for w in words)
    out = (exact, exact.upper())
    return out + ((ICON_ALIASES[exact.upper()],) if exact.upper() in ICON_ALIASES else ())
# server-side conditions (IgnoredCondition): achievement -> event. Monthly ranking: single-player adaptation, rank points earned each month;
# rank 1 General of the Month, ranks 2-50 Acclaimed Pilot counter (ranks.py daily_rank at the first account of the new month, virtual rank from the rank)
SERVER_SIDE = {'achievement_monthlyranking-general': 'monthly_general', 'achievement_monthlyranking-pilot': 'monthly_pilot',
               # champions (E6 adaptation): a single player in the ranking; personal record (furthest wave in EBL, best time in Plutus)
               'achievement_event_eternalgate-champion': 'record_ebl', 'achievement_event_gauntletofplutus-champion': 'record_plutus'}


def mod(name, **f):
    f['_'] = name
    return f


from legacy_protocol import legacy  # noqa: E402,F401  (old text protocol: legacy_protocol.py)


def in_season(a):
    seasonal = a['group'].startswith(('EVENT_', 'SEASONPASS')) or a.get('event')
    return not seasonal or a['group'] in ACTIVE_EVENTS or a['group'] in ALWAYS_GROUPS or a.get('event') in ACTIVE_EVENTS


def _index():
    out = {}
    for aid, a in ACH.items():
        if not a['enabled'] or not in_season(a):
            continue
        for c in a['levels']:
            k = KINDS.get(c['class_name'])
            for kind in (k if isinstance(k, tuple) else (k,)) if k else ():
                out.setdefault(kind, [])
                if aid not in out[kind]:
                    out[kind].append(aid)
    return out


BY_KIND = _index()


def set_events(names):
    """The calendar's active achievement groups (event_calendar.py): when they change the event index is rebuilt -> did it change."""
    global BY_KIND
    names = set(names)
    if names == ACTIVE_EVENTS:
        return False
    ACTIVE_EVENTS.clear()
    ACTIVE_EVENTS.update(names)
    BY_KIND = _index()
    return True
METAS = {}                       # referenced achievement -> MetaAchievements (score: its completed level)
for _aid, _a in ACH.items():
    for _c in _a['levels']:
        if _a['enabled'] and _c['class_name'] == 'MetaAchievement':
            for _ref in _c.get('parameters', {}).get('achievementId', []):
                METAS.setdefault(_ref, set()).add(_aid)


def param(c, k):
    return c.get('parameters', {}).get(k, [])


def measure(c, kind, kw):
    """How the condition advances with this event: ('add', n) | ('set', value) | ('item', set element) | None."""
    s = c['class_name']
    if s == 'Currency':
        n = kw.get(CURRENCY.get((param(c, 'currencyType') or [''])[0], ''), 0)
        return ('add', n) if n > 0 else None
    if s == 'AvatarTypeKill':
        if kw.get('avatar', 'NPC') not in param(c, 'avatar') or (param(c, 'id') and str(kw.get('npc')) not in param(c, 'id')):
            return None
        for i in c.get('ic', []):
            if i['class_name'] != 'InRadiation' or not kw.get('radiation'):
                return None
        return ('add', 1)
    if s == 'NpcTypeDestroyed':
        return ('item', str(kw.get('npc'))) if kw.get('avatar', 'NPC') == 'NPC' else None
    if s == 'Collect':
        if kw.get('tip') not in param(c, 'boxType') or ('PET' in param(c, 'avatar') and not kw.get('pet')):
            return None
        return ('add', 1)
    if s == 'AssetCollect':
        return ('add', kw.get('count', 0)) if kw.get('weapon') in param(c, 'assetType') else None
    if s in ('Quest', 'QuestDeathless'):
        return ('add', 1)
    if s in ('QuestSelection',):
        return ('item', str(kw.get('id')))
    if s == 'DiscoverMaps':
        return ('item', str(kw.get('map')))
    if s == 'Gatejumps':
        return ('add', 1)
    if s == 'Influence':
        return ('add', int(kw.get('points', 0))) if kw.get('points') else None
    if s in ('Distance', 'Damage'):
        return ('add', int(kw.get('count', 0))) if kw.get('count', 0) >= 1 else None
    if s == 'AmmoShots':
        return ('add', kw.get('count', 1)) if kw.get('weapon') in param(c, 'weaponType') else None
    if s == 'Playtime':
        return ('add', 1) if 'PET' not in param(c, 'avatar') or kw.get('pet') else None
    if s == 'PlaytimeOnEnemyMap':
        return ('add', 1) if kw.get('enemy_map') else None
    if s in ('PlayerCloaked', 'ChainImpulse'):            # minutes stayed hidden; kills with Chain Impulse (technology.py)
        return ('add', 1)
    if s == 'MapTypeCheck':
        return ('add', 1) if kw.get('pvp_map') and 'PVP' in param(c, 'mapType') else None
    if s == 'DroneFormationChange':
        return ('add', 1)
    if s == 'DroneFormationDroneAmount':
        return ('set', kw.get('drone', 0))
    if s == 'EquipItem':
        return ('set', 1) if set(param(c, 'item')) & set(kw.get('items', ())) else None
    if s == 'LaserTypeUsage':                               # ammo types used within 60 s (world.py)
        return ('window', [str(i) for i in kw.get('items', [])])
    if s == 'TutorialFinished':                             # starter quest chain (20000-20003) finished
        return ('set', 1)
    if s == 'AbilityType':                                  # ship abilities (ship_ability.py)
        return ('add', 1) if kw.get('type') in param(c, 'abilityType') else None
    if s == 'GalaxyGateDone':
        return ('add', 1) if kw.get('type') in param(c, 'galaxyGateType') else None
    if s == 'Destruction':
        return ('add', 1) if kw.get('reason') in param(c, 'reason') else None
    if s == 'KilledByAvatarType':
        if kw.get('npc') is None or 'NPC' not in param(c, 'avatar') or (param(c, 'id') and str(kw['npc']) not in param(c, 'id')):
            return None
        return ('add', 1)
    if s == 'Level' and c.get('incident') == 'LEVEL':          # the season pass's Levels through another event (SEASONPASS_Q...)
        who = 'PLAYER' if kind == 'level' else 'PET'
        return ('set', kw.get('value', 0)) if who in param(c, 'avatar') else None
    if s == 'LevelAbsolute':                                # "50 levels of the Gold Season Pass": this season's group (season.py)
        return ('set', kw.get('value', 0)) if c.get('incident') == kw.get('group') else None
    if s == 'Dispatch':                                     # DISPATCH_RETRIEVER / DISPATCH_GATE
        return ('add', 1) if c.get('incident') == kw.get('incident') else None
    if s == 'NPCSelectionKill':
        hit = kw.get('avatar', 'NPC') == 'NPC' and set(ship_icons(kw.get('name'))) & set(param(c, 'npcType'))
        return ('add', 1) if hit else None
    if s == 'EventScore':                                   # "N points in one event": the total over the event period
        return ('set', kw.get('value', 0)) if kw.get('event') in param(c, 'event') and c.get('incident') == 'EVENT_SCORE' else None
    if s == 'BuildRecipe':
        return ('add', kw.get('count', 1)) if kw.get('recipe') in param(c, 'recipeId') else None
    if s == 'TriggerMine':                                  # "N mines in T seconds, without dying": the count within the time window
        limit = next((int(t.get('time', 0)) for t in param(c, 'timeLimit') if isinstance(t, dict)), 0)
        return ('times', limit) if kw.get('weapon') in param(c, 'weaponType') else None
    if s == 'TeamDeathMatchKill':                          # a kill in Team Deathmatch (team_deathmatch.py)
        return ('add', 1)
    if s == 'CollectPackage':
        return ('add', 1) if kw.get('package') in param(c, 'packageId') else None
    if s == 'ClearGalaxyGateWave':                          # "Reach wave N in the Eternal Gate": the highest wave reached
        return ('max', kw.get('wave', 0)) if kw.get('type') in param(c, 'galaxyGateType') else None
    if s == 'Uses3D':                                       # 3D view (DisplaySettingsModule.displayUse2d false)
        return ('set', 1) if kw.get('use2d') is False else None
    if s == 'EggTriggerCount':
        return ('add', 1) if kw.get('type') in param(c, 'eggTriggerType') else None
    if s == 'PublicWorldBossCondition':                     # recoverhp / takedamage (in the title's name); only this year's achievement
        want = 'wb_heal' if 'recoverhp' in c.get('title', '') else 'wb_damage'
        year = c.get('incident', '').endswith('_%d' % time.localtime().tm_year)
        return ('add', int(kw.get('count', 0))) if kind == want and year and kw.get('count', 0) > 0 else None
    return None


def state(p):
    return p.d.setdefault('achievements', {'score': {}, 'set': {}, 'level': {}, 'date': {}, 'titles': [], 'title': -1})


def target(c):
    return len(c['set']) if 'set' in c else c.get('value', 1)


def title_id(key):
    """The title's id. Event titles that are not in the achievement table (World Boss, Mimesis, Strike and Exit, Galaxy Trek, BL/Astral
    ranking) get a fixed id from the key: the same on every start, so the selected title in the save resolves again after a restart."""
    if key not in TITLES:
        TITLES[key] = EVENT_TITLE_BASE + zlib.crc32(key.encode()) % 30000
        TITLE_KEYS[TITLES[key]] = key
    return TITLES[key]


class Achievements:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        for k in state(profile)['titles']:
            title_id(k)
        self.send = None             # session: messages sent on their own (completion notice, current list)

    # ------------------------------------------------------------ state
    def level(self, aid):
        return state(self.p)['level'].get(aid, 0)

    def current(self, aid):
        lv, levels = self.level(aid), ACH[aid]['levels']
        return levels[lv] if lv < len(levels) else None

    def score(self, aid, c=None):
        st = state(self.p)
        c = c or self.current(aid)
        if c and 'set' in c:
            return len(set(st['set'].get(aid, [])) & set(c['set']))
        return st['score'].get(aid, 0)

    def met(self, aid, c):
        if not c or not c['class_name'] or (c['class_name'] == 'IgnoredCondition' and aid not in SERVER_SIDE):
            return False
        s = self.score(aid, c)
        return s > target(c) if c.get('operator') == '>' else s >= target(c)

    # ------------------------------------------------------------ events
    def event(self, kind, **kw):
        """Game event -> counters; completed levels are reported. -> [(achievement, level)]."""
        if kind == 'sync':
            return self.sync()
        st = state(self.p)
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        changed = []
        with self.p.lock:
            if kind == 'death':                       # resetOnDeath: those that must be done without dying start over
                for aid in ACH:
                    c = self.current(aid)
                    if c and c.get('reset_on_death') and (st['score'].get(aid) or st.get('time', {}).get(aid)):
                        st['score'][aid] = 0
                        st.get('time', {}).pop(aid, None)
                        st['date'][aid] = now
                        self.p.dirty = True
            for aid in list(BY_KIND.get(kind, ())) + [a for a, k in SERVER_SIDE.items() if k == kind and ACH.get(a, {}).get('enabled')]:
                c = self.current(aid)
                k = (SERVER_SIDE.get(aid) or KINDS.get(c['class_name'])) if c else None
                if not k or kind not in (k if isinstance(k, tuple) else (k,)):
                    continue
                m = ('add', 1) if c['class_name'] == 'IgnoredCondition' else measure(c, kind, kw)
                if not m:
                    continue
                ev = ACH[aid].get('period_reset')             # "progress is not carried over to the next event" (Immortal Passion; official forum)
                if ev:
                    import event_calendar as CAL
                    span = CAL.period(ev)
                    key = int(span[0]) if span else 0
                    if st.setdefault('period', {}).get(aid) != key:
                        st['period'][aid] = key
                        st['score'][aid] = 0
                        st['set'].pop(aid, None)
                op, v = m
                if op == 'add':
                    st['score'][aid] = st['score'].get(aid, 0) + v
                elif op == 'set':
                    if st['score'].get(aid) == v:
                        continue
                    st['score'][aid] = v
                elif op == 'max':
                    if v <= st['score'].get(aid, 0):
                        continue
                    st['score'][aid] = v
                elif op == 'times':                  # number of events in the last v seconds (TriggerMine); reset on death (olumde_sifir)
                    t = time.time()
                    times = [x for x in st.setdefault('time', {}).get(aid, []) if t - x < v] + [t]
                    st['time'][aid] = times
                    st['score'][aid] = len(times)
                elif op == 'window':                 # the set's current state (time window): does not accumulate
                    cur = sorted(set(v) & set(c['set']), key=str)
                    if st['set'].get(aid) == cur:
                        continue
                    st['set'][aid] = cur
                else:
                    if v not in c['set'] or v in st['set'].get(aid, []):
                        continue
                    st['set'].setdefault(aid, []).append(v)
                st['date'][aid] = now
                changed.append(aid)
            if changed:
                self.p.dirty = True
        return self.advance(changed)

    def advance(self, aids):
        """Complete the levels the condition holds for (several levels can be passed at once); update the MetaAchievements; notify."""
        st = state(self.p)
        done, msgs, todo = [], [], list(aids)
        while todo:
            aid = todo.pop(0)
            while self.met(aid, self.current(aid)):
                c = self.current(aid)
                with self.p.lock:
                    st['level'][aid] = self.level(aid) + 1
                    st['date'][aid] = time.strftime('%Y-%m-%d %H:%M:%S')
                    if c.get('title') and c['title'] not in st['titles']:
                        st['titles'].append(c['title'])
                    self.p.dirty = True
                lv = self.level(aid)
                done.append((aid, lv))
                # the client looks up the text and icon by the XML's grade (<achievement>_<grade>_name); for some achievements it differs from the order
                # (achievement_destroy_centuryfalcon has one level, grade 2): live test H29, an empty notification box appeared
                msgs.append(legacy('0|A|ACG|%s_%d|%d' % (aid, c.get('grade', lv), target(c))))
                self.log('   achievement: %s level %d (+%d points%s)' % (aid, lv, c.get('points', 0),
                                                                   ', unvan %s' % c['title'] if c.get('title') else ''))
                for meta in METAS.get(aid, ()):
                    with self.p.lock:
                        st['score'][meta] = lv
                    todo.append(meta)
        if msgs and self.send:
            # only the completion row (record: the list only on AchievementListRequest). When the list was sent on its own and the pilot page had never been
            # opened the client crashed (live test 2026-10-17: UIPilotSheetSystem.UpdateTotalPoints, NullReference)
            self.send(msgs)
        return done

    def sync(self):
        """Computed from the profile (store=false): player and P.E.T. level, equipped items (including drone designs)."""
        d = self.p.d
        done = self.event('level', value=d['pilot'].get('level', 1))
        if d.get('pet'):
            done += self.event('pet_level', value=d['pet'].get('level', 0))
        items = [x for v in d.get('equipment', {}).values() for x in v]
        items += [self.p.drone_design(x, s) for x in d.get('drones', []) for s in ('design', 'visual')]
        done += self.event('display', use2d=d.get('settings', {}).get('displaySettingsModule', {}).get('displayUse2d'))
        return done + self.event('equip', items=[x for x in items if x])

    # ------------------------------------------------------------ client
    def info(self, aid, level, score):
        return mod('AchievementInfoCommand', lastUpdate=state(self.p)['date'].get(aid, ''), achievementId=aid, level=level,
                   score=int(score))

    def list_cmd(self):
        st = state(self.p)
        done, running = [], []
        for aid, a in ACH.items():
            if not a['enabled']:
                continue
            lv = self.level(aid)
            if lv:
                done.append(self.info(aid, lv, target(a['levels'][lv - 1])))
            c = self.current(aid)
            if c and c['class_name'] and self.score(aid, c) > 0:
                running.append((self.score(aid, c) / max(target(c), 1), self.info(aid, lv + 1, self.score(aid, c))))
        nxt = [x for _, x in sorted(running, key=lambda r: -r[0])[:NEXT]]
        titles = [mod('AchievementTitleCommand', key=k, id=TITLES[k]) for k in st['titles'] if k in TITLES]
        return ('AchievementListCommand', dict(unlockAchievements2=[], nextAchievements=nxt, displayTitleId=st['title'],
                                               titleCommandList=titles, list=done, unlockAchievements1=[x for _, x in running]))

    def title_msgs(self):
        """The title on the ship (record: 0|n|t|<user>|<id>|<key>); empty if none."""
        t = state(self.p)['title']
        return [legacy('0|n|t|%d|%d|%s' % (self.p.user_id, t, TITLE_KEYS[t]))] if t in TITLE_KEYS else []

    def request(self, f):
        """AchievementListRequest {displayTitleId}: 0 list; -1 remove the title; the id of an owned title selects it."""
        st = state(self.p)
        t = int(f.get('displayTitleId') or 0)
        msgs = []
        if t and t != st['title']:
            if t == -1 or TITLE_KEYS.get(t) in st['titles']:
                with self.p.lock:
                    st['title'] = t
                    self.p.dirty = True
                msgs = self.title_msgs() or [legacy('0|n|trm|%d' % self.p.user_id)]     # removed: the client clears it (AssembleRemoveTitle)
                self.log('   unvan: %s' % (TITLE_KEYS.get(t) or 'none'))
            else:
                self.log('   title not selected: %d is not owned' % t)
        self.sync()
        return [self.list_cmd()] + msgs
