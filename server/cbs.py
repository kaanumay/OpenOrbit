"""Clan Battle Station (roadmap Ö5 CBS-1..4; data in data/cbs.json <- tools/cbs.py).

CBS-1 Building: 23 asteroids in X-3..X-7, 4-1..4-5 and X-BL (AssetCreateCommand type 35). When a clan player approaches (600) the window data is
sent (BattleStationBuildingUiInitializationCommand); on click the client opens the window (76) itself. Modules are dragged and dropped into
10 slots (0 Hull, 1 Deflector center; 2-9 satellites), each is installed in 50 s (one at a time); once ten modules are fitted, Build (5-60 min).
When built, the center (36) and satellites (37), deflector on and charged for 1440 min (official forum 127469).
The modules of a member who leaves/is kicked from the clan return from the station to their inventory (a built station whose Hull leaves this way stays with 1 HP: official FAQ);
when the clan is disbanded its stations are destroyed and the asteroid is emptied (forum 127469; member_left, clan_disbanded).
CBS-2 Management: while the deflector is on the station is invulnerable and uses up time; while off, time is restored (120 min per hour, 600 at
prime time 18-21; at most 48 h); when it runs out, 120 min forced off; Deactivate 30 min-8 h. Boosters (honor, EP: everywhere; damage: on the
station's map) once fitted go from 1% to the maximum (3-10%) over 20 hours. At the station: ore selling (10% more expensive), emergency repair
(500 U; 20 s x 7,500), Engineering Bay or slow self-repair; a destroyed module is repaired in the hangar with uridium. Replacing a module on a built
station takes 4 min.
CBS-3 Alien raids: at prime time while the deflector is off, two waves an hour (6-12 aliens of the map's level) hit the station; the weapon modules
fire at aliens in range. If the center is destroyed the station falls, the modules return to the inventory destroyed (0 HP).
CBS-4 Virtual rival clans: on empty asteroids a rival progresses over time (Progress of leading Clan); if the rival finishes first it becomes an
enemy station (HOSTILE); its deflector is on outside prime time. Destroying a rival's modules gives 500-2,600 U, its center 5,000 U + 50,000 credits.
Client: requests Equip/UnequipModule, BuildStation, DeflectorShieldStatusChange, EmergencyRepair, MapAssetActivation, TradeRequest (at the
station), HangarShipRepairModule; emergency repair 20 s x 7,500 (official EN/DE FAQ; forum 127469 says 20 min: mistranslation); clan window ClanBattleStationInfo / BattleStationHistoryList;
galaxy map StarmapStationCommand. In the profile: cbs {modules {iid: {loot, level, can, kalkan}}, asteroids {id: ...}, daily [...], stats}.
On a multiplayer server (several clients, friend server) the asteroids are single for everyone: in the server player's save (shared); at first
each player had their own asteroids, and the rival and stations looked different from client to client (user 2026-10-24). They belong to the
clan of whoever built the station (clan): the clan's members manage it (rights clan.RIGHTS), others see it as another clan's station (colour:
clan diplomacy; whom it fires at and who may attack it: company allegiance and war, shoots_at / attack_denied). A fitted module is moved to the slot (with its owner; unique id): everyone sees it; when removed or when the station falls it
returns to the owner (at their next login if offline). The asteroids' timed jobs (building, deflector, repair, rival) run once on the server; each
session refreshes the entities and its window when an asteroid's version changes. The log and the counts are in the clan's record.
"""
import datetime, functools, json, math, os, random, sys, threading, time, traceback, types

import settings as SET
import multiplayer as CO
import clan as KL
import community as TP
import world as world_module
import map_links as H
import galaxy_gates as GALAXY
import pve_common as PS
import paths as PTH
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'cbs.json')
D = json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}
ASTEROIDS = {a['uid']: a for a in D.get('asteroids', [])}
BY_MAP = {}
for _a in ASTEROIDS.values():
    BY_MAP.setdefault(int(_a['map']), []).append(_a['uid'])
MODS = D.get('modules', {})
ASSET_BASE = 157000000                 # + asteroid x 100 (asteroid/center), + slot (satellites)
ITEM_BASE = 157500000                  # itemId of the module instances
ASTEROID, BATTLESTATION, SATELLITE = 35, 36, 37
HULL, DEFLECTOR = 0, 1                 # center slots
SLOTS = 10
OWN, NEUTRAL, HOSTILE = 1, 2, 3        # StarmapStationInfo.StationStatus
# DestructionTypeModule.DestructionCause of a station kill on the death screen: NPC (1), "Destroyer: <module> [<clan>]". The client's own
# BATTLESTATION (5) has no death screen text (only head_killscreen_destroyer_player/npc/radiation_zone/mine/unknown) and the game closed on
# every death by a station (player report 2026-11-02)
DESTRUCTION_BATTLESTATION = 1
E = dict(UNSPECIFIED=0, NO_CLAN=1, STATION_ALREADY_BUILDING=2, ITEM_HITPOINTS_ZERO=3, ITEM_ALREADY_EQUIPPED_IN_ANOTHER_ASTEROID=4,
         CONCURRENT_EQUIP=5, REPLACE_RIGHT_MISSING=6, ITEM_NOT_OWNED=7, OUT_OF_RANGE=8, EQUIP_OF_SAME_PLAYER_RUNNING=9,
         SATELLITE_ONLY=10, HUB_ONLY=11, ITEM_NOT_IN_STATION=12, MAX_NUMBER_OF_MODULE_TYPE_EXCEEDED=13, DEFLECTOR_ALREADY_ON=14,
         DEFLECTOR_ALREADY_OFF=15, REPAIR_NO_MODULE=16, REPAIR_NO_MONEY=17, REPAIR_ALREADY_RUNNING=18, ITEM_UPGRADE_RUNNING=19)
TRADE_BATTLE_STATION = 4
SHARED_ITEM = ITEM_BASE + 1000000         # ids of the modules in the shared slot (players' order from ITEM_BASE: so they do not collide)
SHARED = {'lock': threading.Lock(), 'next': 0.0}
HULL_STANDIN = SHARED_ITEM - 100        # + asteroid: id of the 1 HP Hull left when a leaving member takes theirs (member_left)
# a station of a clan of "All" companies fires only at those who shot it (official FAQ); how long it remembers is not published (adaptation)
AGGRO_SEC = 60


def with_bots():
    """The bot package is on and bot clans are allowed to build stations (Bots: clan_cbs): the stations belong to real clans, there is no
    fake rival, asteroids open empty; the bot clans compete (bot/clan_stations.py; user request 2026-10-31)."""
    y = getattr(sys.modules.get('bot.manager'), 'ACTIVE', None)
    return y is not None and y.permission('clan') and y.permission('clan_cbs')


def shared():
    """The asteroids' shared record (the server player's profile): on a multiplayer server and while bots are present (once a bot clan has
    taken a station it is permanent: bot_clans); None in single player."""
    g = TP.GAME
    h = getattr(g, 'PROFILE', None) if g is not None else None
    if h is None:
        return None
    return h if CO.is_open() or with_bots() or (h.d.get('cbs') or {}).get('bot_clans') else None


def mod(_cls, **f):
    f['_'] = _cls
    return f


def asset_id(aid, slot=None):
    return ASSET_BASE + aid * 100 + (slot if slot is not None and slot > DEFLECTOR else 0)


@functools.lru_cache(maxsize=None)
def placement_obstacles(map_id):
    """Use the same recorded/generated structures as the session's map loader."""
    path = PTH.template('maps.json')
    with open(path, encoding='utf8') as source:
        maps = json.load(source)
    world = maps.get(str(map_id)) or H.map_world(map_id, maps.get('5'))
    obstacles = [(g['x'], g['y'], H.GATE_PEACE_RADIUS + 700) for g in H.GATES.get(map_id, [])]
    obstacles += [(m['posX'], m['posY'], H.ASSET_RANGE + 700) for m in world.get('entry', [])
                  if m['_m'] == 'AssetCreateCommand']
    obstacles += [(m['posX'], m['posY'], m['peaceRadius'] + 700) for m in world.get('ready', [])
                  if m['_m'] == 'SpaceStationCommand']
    return obstacles


@functools.lru_cache(maxsize=None)
def position(aid):
    """Keep the configured centre unless its 600-unit footprint overlaps a map object.

    Project only colliding centres beyond the obstacle, with 100 units of clearance.
    Angular boundary candidates handle overlapping exclusions deterministically.
    """
    a = ASTEROIDS[aid]
    w, h = H.map_size(a['map'])
    x, y = int(w * a['x_percent'] / 100.0), int(h * a['y_percent'] / 100.0)
    obstacles = placement_obstacles(int(a['map']))

    def clamp(point):
        return int(min(max(point[0], 700), w - 700)), int(min(max(point[1], 700), h - 700))

    def clear(point):
        return all(math.hypot(point[0] - ox, point[1] - oy) >= radius for ox, oy, radius in obstacles)

    original = clamp((x, y))
    if clear(original):
        return original
    candidates = []
    for ox, oy, radius in obstacles:
        angle = math.atan2(y - oy, x - ox)
        for direction in [angle] + [math.radians(degrees) for degrees in range(0, 360, 5)]:
            point = clamp((ox + math.cos(direction) * (radius + 2), oy + math.sin(direction) * (radius + 2)))
            if clear(point):
                candidates.append(point)
    if not candidates:
        raise ValueError('CBS %s has no clear layout position' % aid)
    return min(candidates, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)


def satellite_pos(aid, slot):
    """Recorded 22.5-degree octagon orientation, with extra vertical clearance for native module sprites."""
    x, y = position(aid)
    a = (slot - 2) * math.pi / 4 + math.pi / 8
    # Preserve the recorded octagon angle; increase height for 210px native module clearance.
    return int(x + math.cos(a) * 447), int(y + math.sin(a) * 330)


def exclusion_zones(map_id):
    """Physical station/asteroid area, available before the world spawns NPCs."""
    return [(*position(aid), D['range']) for aid in BY_MAP.get(int(map_id), [])]


def prime_time(now=None):
    t = datetime.datetime.fromtimestamp(time.time() if now is None else now)
    a, b = D.get('prime_time', ['18:00', '21:00'])
    h = t.hour + t.minute / 60.0
    return float(a.split(':')[0]) <= h < float(b.split(':')[0])


def level_value(row, lv):
    return row[max(0, min(len(row) - 1, int(lv)))]


def hp_sync(m):
    """When the panel's CBS HP multiplier changes, a module's HP and shield (and for a rival the maximum) are scaled proportionally (m['ksi']: the
    multiplier the saved values were scaled with; 1.0 if missing)."""
    k = float(SET.get('cbs_hp'))
    old = m.get('cbs', 1.0)
    if k == old:
        return
    r = k / old
    for f in ('maximum', 'hp', 'shield'):
        if f in m:
            m[f] = min(SET.I32, int(m[f] * r))
    m['cbs'] = k


def hp_max(m):
    """A module's maximum HP (for a rival, the saved maximum): with the panel's CBS HP multiplier, at most 32 bits."""
    hp_sync(m)
    return m.get('maximum') or min(SET.I32, int(level_value(MODS[m['loot']]['hp'], m['level']) * float(SET.get('cbs_hp'))))


def dmg_value(md, lv):
    """A weapon module's damage at its level: with the panel's CBS damage multiplier (all stations)."""
    return level_value(md['damage'], lv) * float(SET.get('cbs_damage'))


def stm(key, **params):
    """The client's text (flashres) with its placeholders: 0|A|STM|key|%AD%|value..."""
    return legacy('0|A|STM|%s%s' % (key, ''.join('|%%%s%%|%s' % (k, v) for k, v in params.items())))


def stamp(t=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() if t is None else t))


class Cbs:
    REQUESTS = ('EquipModuleRequest', 'UnequipModuleRequest', 'BuildStationRequest', 'DeflectorShieldStatusChangeRequest',
                'EmergencyRepairRequest', 'HangarShipRepairModuleRequest')

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.near = None                        # menzildeki asteroit
        self.shown_assets = []                  # entities sent on this map
        self.next_raid = {}
        self.raiders = {}                       # alien -> asteroid
        self.next_shot = {}
        self.tick_err = {}                      # asteroid -> its error was written once
        self.starmap_tpl = None                 # the login's StarmapStationCommand template (resent when it changes)
        self.home = None                        # bound per session: base map
        self.prime = None                       # last known Prime Time state (announcement on transition)
        self.seen = {}                          # last seen (version, state, diplomacy) of the shared asteroids: refreshed when it changes

    # ------------------------------------------------------------ profile
    @property
    def st(self):
        d = self.p.d.setdefault('cbs', {})
        for k, v in (('modules', {}), ('asteroids', {}), ('daily', []), ('stats', {}), ('order', 0)):
            d.setdefault(k, v)
        self.migrate_rival_stats(self.p, d)
        self.absorb(d)
        return d

    @staticmethod
    def migrate_rival_stats(profile, state):
        """Upgrade synthetic saved rival capacities once, preserving damage fractions.

        Owned inventory/stations never participate. Old rivals stored a reduced
        capacity in maximum, so changing the data table alone could not update them.
        """
        version = 1  # published CBS stats configuration, 2026-10-25
        if state.get('rival_stats_version', 0) == version:
            return
        asteroids = state.get('asteroids', {})
        for a in asteroids.values() if isinstance(asteroids, dict) else []:
            if not isinstance(a, dict) or a.get('owner') != 'rival' or a.get('state') != 'built':
                continue
            slots = a.get('slots', {})
            changed = False
            for row in slots.values() if isinstance(slots, dict) else []:
                if not isinstance(row, dict) or 'iid' in row or 'module' in row:
                    continue
                loot = row.get('loot')
                md = MODS.get(loot) if isinstance(loot, str) else None
                if not md:
                    continue
                try:
                    old_max, hp, shield = (float(row[k]) for k in ('maximum', 'hp', 'shield'))
                    level = float(row['level'])
                    if not all(math.isfinite(v) for v in (old_max, hp, shield, level)) or old_max <= 0 or level != int(level):
                        continue
                    maximum = int(level_value(md['hp'], int(level)) * D['rival']['hp_multiplier'])
                    if maximum <= 0:
                        continue
                    old_shield = int(old_max * D['shield_ratio'])
                    new_shield = int(maximum * D['shield_ratio'])
                    row.update(maximum=maximum, hp=int(maximum * max(0.0, min(1.0, hp / old_max))),
                               shield=int(new_shield * max(0.0, min(1.0, shield / old_shield))) if hp > 0 and old_shield > 0 else 0)
                    row.pop('cbs', None)
                    changed = True
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
            if changed:
                a['version'] = a.get('version', 0) + 1
        state['rival_stats_version'] = version
        profile.dirty = True

    def absorb(self, d):
        """Modules that drop into the depot via the reward path (module_* counters) are turned into instances one by one (HP, shield, level). So are
        modules returned from the shared slot while offline (give_back)."""
        h = self.host
        back = ((h.d.get('cbs') or {}).get('pending') or {}).get(KL.name(self.p)) if h is not None else None
        if back:
            with h.lock:
                h.d['cbs']['pending'].pop(KL.name(self.p), None)
                h.dirty = True
            d['modules'].update(back)
            self.p.dirty = True
        store = self.p.d.get('other_items', {})
        loots = [l for l in list(store) if l in MODS]
        for loot in loots:
            n = int(store.pop(loot, 0))
            for _ in range(n):
                d['order'] += 1
                iid = ITEM_BASE + d['order']
                hp = level_value(MODS[loot]['hp'], 0)
                d['modules'][str(iid)] = dict(loot=loot, level=0, hp=hp, shield=int(hp * D['shield_ratio']))
            self.p.dirty = True

    @property
    def host(self):
        return shared()

    @property
    def asteroids(self):
        """The asteroids' record: the player's in single player, the shared one (in the server player's profile) in multiplayer."""
        h = self.host
        if h is None:
            return self.st['asteroids']
        d = h.d.setdefault('cbs', {})
        if not d.get('shared'):
            self.embed(h, d)
        if self.p is not h:
            self.bring(h, d)
        self.migrate_rival_stats(h, d)
        return d['asteroids']

    def bring(self, h, d):
        """Stations that the extra client (guest) builds in single player also become shared (like embed): the module in the slot onto an empty asteroid
        (with its owner, shared id), the station belongs to the player's clan. If the asteroid is taken in the shared record, no station is built and
        its modules stay in the inventory. At first only the server player's were shared: when the save was opened on the extra client it had no
        stations of its own (player report 2026-10-30). Waits while clanless (until their clan is bound)."""
        own = self.p.d.get('cbs') or {}
        built = [aid for aid, a in own.get('asteroids', {}).items()
                 if a.get('owner') != 'rival' and (a.get('slots') or a.get('state') in ('building', 'built'))]
        k = self.clan() if built else None
        if not k:
            return
        me, name = KL.name(self.p), self.p.d['pilot'].get('userName', '')
        with h.lock:
            shared = d.setdefault('asteroids', {})
            for aid in built:
                a = own['asteroids'].pop(aid)
                there = shared.get(aid) or {}
                if there.get('slots') or there.get('state', 'vacant') != 'vacant':
                    self.log('   CBS: %s taken in the shared record, modules of the %s station go to the inventory' % (aid, me))
                    continue
                slots = {}
                for s, y in a.get('slots', {}).items():
                    m = own.get('modules', {}).pop(str(y.get('iid')), None)
                    if m is not None:
                        d['shared_seq'] = int(d.get('shared_seq', 0)) + 1
                        slots[s] = dict(y, iid=SHARED_ITEM + d['shared_seq'], module=m, owner=me, owner_name=name)
                a.pop('rival', None)
                a.pop('rival_progress', None)
                shared[aid] = dict(a, slots=slots, clan=k['id'], version=there.get('version', 0) + 1)
                self.log('   CBS: %s station in the shared record (%s)' % (aid, me))
            h.dirty = True
        self.p.dirty = True

    def embed(self, h, d):
        """Stations that the server's player builds in single player become shared: the module in the slot to the slot (with its owner),
        the station to their clan."""
        me, cid = KL.name(h), int(h.d['pilot'].get('clanId', 0) or 0)
        with h.lock:
            d.setdefault('asteroids', {})
            mods = d.setdefault('modules', {})
            for a in d['asteroids'].values():
                if a.get('owner') == 'rival':
                    continue
                for y in a.get('slots', {}).values():
                    m = mods.pop(str(y.get('iid')), None) if 'module' not in y else None
                    if m is not None:
                        y.update(module=m, owner=me, owner_name=h.d['pilot'].get('userName', ''))
                if cid and (a.get('slots') or a.get('state') in ('building', 'built')):
                    a.setdefault('clan', cid)
            d['shared'] = True
            h.dirty = True

    @property
    def lock(self):
        h = self.host
        return (h or self.p).lock

    def mark(self):
        self.p.dirty = True
        h = self.host
        if h is not None:
            h.dirty = True

    def bump(self, a):
        """An asteroid's appearance changed (other sessions refresh in the shared record)."""
        a['version'] = a.get('version', 0) + 1

    def ast(self, aid):
        a = self.asteroids.setdefault(str(aid), {})
        a.setdefault('state', 'vacant')
        a.setdefault('slots', {})
        a.setdefault('deflector', {'on': False, 'sec': 0.0, 'closed_until': 0.0, 'last': time.time()})
        for y in a['slots'].values():
            m = y.get('module') or (y if 'loot' in y else None)
            if m is not None and m.get('loot') in MODS:
                hp_sync(m)
        return a

    def clan(self):
        return KL.clan_of(self.p) if self.host is not None else self.p.d.get('clan')

    def clan_name(self):
        k = self.clan()
        return k['name'] if k else ''

    def faction(self):
        k = self.clan()
        return int((k or {}).get('company') or self.p.d['pilot'].get('factionId', 0))

    def mine(self, a):
        """Whether the station (or the asteroid being built) belongs to the player's clan: in single player, everything except the rival."""
        if a.get('owner') == 'rival':
            return False
        if self.host is None:
            return True
        k = self.clan()
        return bool(k) and a.get('clan') in (None, k['id'])

    def st_clan(self, a):
        """The clan of the station on the asteroid (record) or None."""
        if self.host is None:
            return self.clan()
        return KL.CLANS.get(a.get('clan')) if a.get('clan') else None

    def st_name(self, a):
        return (self.st_clan(a) or {}).get('name', '')

    def st_faction(self, a):
        k = self.st_clan(a)
        return int((k or {}).get('company') or (self.p.d['pilot'].get('factionId', 0) if self.host is None else 0))

    def at_war(self, a):
        """The viewer's clan is at war with the station's clan (the virtual rival counts as a clan at war)."""
        if a.get('owner') == 'rival':
            return True
        k = self.clan()
        return bool(k) and KL.clan_relation(k['id'], a.get('clan')) == 3

    def same_company(self, a):
        """The viewer shares the station's company allegiance (the pilot's own company; a clan of "All" companies shares none)."""
        fac = self.st_faction(a)
        return bool(fac) and fac == int(self.p.d['pilot'].get('factionId', 0))

    def attack_denied(self, a):
        """Why the viewer may not attack the station (client message key) or None. Official CBS FAQ (rebalancing 2013-11-17): attackable by
        every player outside the owning clan who does not share the station's company allegiance, and by the members of a clan at war with
        the owner even of the same company. Alliances and NAPs do not change it; neither does having no clan."""
        if self.mine(a):
            return 'msg_station_not_atackable'
        if self.same_company(a) and not self.at_war(a):
            return 'msg_station_not_attackable_company_affiliation'
        return None

    def shoots_at(self, a, now=None):
        """The station sees the viewer as an enemy (its weapon modules fire at them): the players who may attack it; a station of a clan of
        "All" companies only those who shot at it (official FAQ: it "will only see players that shoot at it as enemy") and clans at war."""
        if self.attack_denied(a):
            return False
        if self.st_faction(a) or self.at_war(a):
            return True
        now = time.time() if now is None else now
        return now - (a.get('aggro') or {}).get(str(self.p.user_id), 0) < AGGRO_SEC

    def diplomacy(self, a):
        """The relation shown (ClanRelationModule.type, star map colour): rival 3, own clan 0, another clan's real diplomacy (0 none, 1 alliance,
        2 non-aggression, 3 war). relation() stays the attack rule (no diplomacy: attackable); only a war is shown hostile (player report
        2026-11-02: allied and non-enemy clans' stations were red on the star map)."""
        if a.get('owner') == 'rival':
            return 3
        if self.mine(a):
            return 0
        k = self.clan()
        return KL.clan_relation(k['id'], a.get('clan')) if k else 0

    def own_module(self, iid):
        return self.st['modules'].get(str(iid))

    def module(self, iid):
        m = self.st['modules'].get(str(iid))
        if m is None:
            y = self.slot_of(iid)
            m = y.get('module') if y else None
        if m is not None:
            hp_sync(m)
        return m

    def slot_of(self, iid):
        for a in self.asteroids.values():
            for y in a.get('slots', {}).values():
                if str(y.get('iid')) == str(iid):
                    return y
        return None

    def where(self, iid):
        """The (asteroid, slot) the module is fitted in, or None (in multiplayer the player's single-player asteroids too: so a module is not used in
        two places)."""
        stores = [self.asteroids] + ([self.st['asteroids']] if self.host is not None and self.host is not self.p else [])
        for store in stores:
            for aid, a in store.items():
                for slot, y in a.get('slots', {}).items():
                    if str(y.get('iid')) == str(iid):
                        return int(aid), int(slot)
        return None

    def give_back(self, y):
        """The module in the shared slot to its owner (at once if connected, otherwise at their next login: absorb)."""
        m = y.pop('module', None) if y else None
        if m is None or y.get('placeholder'):          # the 1 HP stand-in of a Hull taken away by a leaving member belongs to nobody
            return
        owner, iid = y.get('owner'), str(y['iid'])
        s = KL.people().get(owner) if owner != KL.name(self.p) else None
        x = self.p if owner == KL.name(self.p) else (s.profile if s is not None else None)
        if x is not None:
            with x.lock:
                x.d.setdefault('cbs', {}).setdefault('modules', {})[iid] = m
                x.dirty = True
        else:
            h = self.host or self.p
            with h.lock:
                h.d.setdefault('cbs', {}).setdefault('pending', {}).setdefault(owner, {})[iid] = m
                h.dirty = True

    def tell(self, a, msgs):
        """Announcement to the station's clan: in the shared record it goes to the clan's connected members (whichever session runs the asteroids' jobs)."""
        k = KL.CLANS.get(a.get('clan')) if self.host is not None and a.get('clan') else None
        if k is None or not msgs:
            return msgs
        for name, s in KL.people().items():
            if name in k['members'] and s.session is not None:
                s.send(msgs, 'CBS')
        return []

    def hp(self, right):
        """Clan right (in single player the player is leader)."""
        return self.host is None or KL.right(self.p, right)

    def mx(self, m):
        hp = hp_max(m)
        return hp, min(SET.I32, int(hp * D['shield_ratio']))

    # ------------------------------------------------------------ komutlar
    def module_cmd(self, iid, aid=-1, slot=-1, now=None):
        now = time.time() if now is None else now
        m = self.module(iid)
        md = MODS[m['loot']]
        mh, ms = self.mx(m)
        y = (self.ast(aid)['slots'].get(str(slot)) if aid > 0 else None) or {}
        left = max(0, int(y.get('install_end', 0) - now))
        rep = max(0, int(y.get('repair_end', 0) - now))
        owner = (y.get('owner_name') or self.p.d['pilot'].get('userName', '')) if aid > 0 else ''
        return mod('StationModuleModule', asteroidId=aid, itemId=int(iid), slotId=slot, type=md['type'], currentHitpoints=int(m['hp']),
                   maxHitpoints=mh, currentShield=int(m['shield']), maxShield=ms, upgradeLevel=int(m['level']),
                   ownerName=owner, installationSeconds=int(y.get('install_sec', 0)),
                   installationSecondsLeft=left, emergencyRepairSecondsLeft=rep,
                   emergencyRepairSecondsTotal=D['emergency_repair']['duration_sec'] if rep else 0, emergencyRepairCost=D['emergency_repair']['charge'])

    def available_cmd(self):
        free = [iid for iid in sorted(self.st['modules'], key=int) if not self.where(iid)]
        return mod('AvailableModulesCommand', modules=[self.module_cmd(i) for i in free])

    def available_msg(self):
        """Refreshes the window's inventory (the client takes the list in UiInitialization only the first time; live round Ö5)."""
        return ('AvailableModulesCommand', {'modules': self.available_cmd()['modules']})

    def equipped(self, aid, now=None):
        a = self.ast(aid)
        return mod('EquippedModulesModule', modules=[self.module_cmd(y['iid'], aid, int(s), now) for s, y in sorted(a['slots'].items(),
                                                                                                                key=lambda kv: int(kv[0]))
                                                     if self.module(y['iid'])])

    def own_progress(self, aid, now=None):
        """The progress of the clan building on the asteroid (modules whose installation is finished)."""
        now = time.time() if now is None else now
        a = self.ast(aid)
        done = sum(1 for y in a['slots'].values() if y.get('install_end', 0) <= now)
        return done / float(SLOTS)

    def progress_cmd(self, aid, now=None):
        a = self.ast(aid)
        prog = self.own_progress(aid, now)
        own = prog if self.mine(a) else 0.0                 # if another clan is building in the shared record, its progress is the best
        r, rp = a.get('rival'), a.get('rival_progress', 0) if a.get('rival') else 0
        leader = race_leader(a)                                # the race of the bot clans (clan_stations): the leader
        if leader and leader[1] > rp:
            r, rp = leader
        best = max(prog, rp)
        best_name = (self.st_name(a) or self.clan_name() if prog >= rp else r) if (prog or r) else ''
        return mod('AsteroidProgressCommand', battleStationId=aid, ownProgress=float(own), bestProgress=float(best), ownClanName=self.clan_name(),
                   bestProgressClanName=best_name or '', state=self.equipped(aid, now),
                   buildButtonActive=own >= 1.0 and a['state'] == 'vacant' and self.hp('battle_station_build'))

    def progress_msg(self, aid, now=None):
        f = dict(self.progress_cmd(aid, now))
        f.pop('_')
        return ('AsteroidProgressCommand', f)

    def status_msg(self, aid, now=None):
        f = dict(self.status_cmd(aid, now))
        f.pop('_')
        return ('BattleStationStatusCommand', f)

    def building_ui(self, aid):
        k = D['build_min']
        return ('BattleStationBuildingUiInitializationCommand', dict(
            mapAssetId=asset_id(aid), battleStationId=aid, battleStationName=ASTEROIDS[aid]['name'], progress=self.progress_cmd(aid),
            availableModules=self.available_cmd(), buildTimeInMinutesMin=k[0], buildTimeInMinutesMax=k[1], buildTimeInMinutesIncrement=k[2]))

    def booster_pct(self, aid, kind, now=None):
        """A booster module's effect (%): once fitted and installed, from 1% to the maximum over 20 hours."""
        now = time.time() if now is None else now
        a = self.ast(aid)
        if a['state'] != 'built':
            return 0.0
        for slot, y in a['slots'].items():
            m = self.module(y['iid'])
            if not m or MODS[m['loot']].get('booster') != kind or y.get('install_end', 0) > now or m['hp'] <= 0:
                continue
            top = level_value(MODS[m['loot']]['booster_percent'], m['level'])
            t = (now - max(y.get('install_end', 0), a.get('founded', 0))) / (D['booster']['growth_hours'] * 3600.0)
            return min(top, D['booster']['start'] + (top - D['booster']['start']) * max(0.0, min(1.0, t)))
        return 0.0

    def ratings(self, aid, now=None):
        a = self.ast(aid)
        att = dfn = rep = 0
        for y in a['slots'].values():
            m = self.module(y['iid'])
            if not m:
                continue
            md = MODS[m['loot']]
            dfn += int(m['hp'] + m['shield'])
            if md.get('weapon'):
                att += dmg_value(md, m['level'])
            if md.get('repair_sec'):
                rep += level_value(md['repair_sec'], m['level'])
        return att // 1000, dfn // 1000, rep

    def deflector_rate(self, now=None, aid=None):
        r = D['deflector_speed']
        base = r['prime_time'] if prime_time(now) else r['normal']
        level = 0
        if aid is not None:
            a = self.ast(aid)
            y = a['slots'].get(str(DEFLECTOR))
            m = (y if a.get('owner') == 'rival' else self.module(y.get('iid'))) if y else None
            if m and m.get('loot') == 'module_defm-1':
                level = max(0, min(15, int(m['level'])))
        # Published +1% of base per upgrade: 120 minutes/hour -> 138 at L16.
        return base * (100 + level) / 100.0

    def status_cmd(self, aid, now=None):
        now = time.time() if now is None else now
        a = self.ast(aid)
        df = a['deflector']
        att, dfn, rep = self.ratings(aid, now)
        return mod('BattleStationStatusCommand', mapAssetId=asset_id(aid), battleStationId=aid, battleStationName=ASTEROIDS[aid]['name'],
                   deflectorShieldActive=bool(df['on']), deflectorShieldSeconds=int(df['sec']), deflectorShieldSecondsMax=D['deflector_max_sec'],
                   attackRating=att, defenceRating=dfn, repairRating=rep, honorBoosterRating=int(round(self.booster_pct(aid, 'honor', now))),
                   experienceBoosterRating=int(round(self.booster_pct(aid, 'ep', now))),
                   damageBoosterRating=int(round(self.booster_pct(aid, 'damage', now))), deflectorShieldRate=int(self.deflector_rate(now, aid)),
                   repairPrice=D['emergency_repair']['charge'], equipment=self.equipped(aid, now), isOreTradeAvailable=True)

    def management_ui(self, aid, now=None):
        dm = D['deflector_min']
        a = self.ast(aid)
        return ('BattleStationManagementUiInitializationCommand', dict(
            mapAssetId=asset_id(aid), battleStationId=aid, battleStationName=ASTEROIDS[aid]['name'], clanName=self.st_name(a),
            faction=mod('FactionModule', faction=self.st_faction(a)), state=self.status_cmd(aid, now), availableModules=self.available_cmd(),
            deflectorShieldMinutesMin=dm[0], deflectorShieldMinutesMax=dm[1], deflectorShieldMinutesIncrement=dm[2],
            deflectorDeactivationPossible=bool(a['deflector']['on'])))

    def building_state(self, aid, now=None):
        now = time.time() if now is None else now
        a = self.ast(aid)
        return ('BattleStationBuildingStateCommand', dict(mapAssetId=asset_id(aid), battleStationId=aid, battleStationName=ASTEROIDS[aid]['name'],
                                                          secondsLeft=max(0, int(a.get('build_end', now) - now)),
                                                          totalSeconds=int(a.get('build_sec', 0)), ownerClan=self.st_name(a),
                                                          affiliatedFaction=mod('FactionModule', faction=self.st_faction(a))))

    def ui_msgs(self, aid):
        """The window's data on approach (the client opens it itself on click): clanless / asteroid / building / built."""
        a = self.ast(aid)
        if not self.clan():
            return [('BattleStationNoClanUiInitializationCommand', {'mapAssetId': asset_id(aid)})]
        if a.get('owner') == 'rival':
            return []
        if a['state'] == 'building':
            return [self.building_state(aid)]
        if a['state'] == 'built':
            return [self.management_ui(aid)] if self.mine(a) else []        # another clan's station
        return [self.building_ui(aid)]

    def error(self, kind):
        return [('BattleStationErrorCommand', {'type': E[kind]})]

    # ------------------------------------------------------------ entities
    def asset_cmd(self, aid_asset, kind, x, y, name, design=1, stage=0, clan=None, faction=0, relation=0):
        return ('AssetCreateCommand', dict(designId=design, clanId=int((clan or {}).get('id', 0)), showBubble=True, userName=name,
                                           assetId=aid_asset, expansionStage=stage, modifier=[], type=mod('AssetTypeModule', typeValue=kind),
                                           detectedByWarnRadar=True, invisible=False, posY=int(y),
                                           clanRelation=mod('ClanRelationModule', type=relation), clanTag=(clan or {}).get('tag', ''),
                                           factionId=faction, posX=int(x), visibleOnWarnRadar=False))

    def hub_stage(self, aid):
        """Native .115: Hull occupies bits 16+, Deflector occupies bits 0..7.

        GetLowerByte actually shifts right 16; GetUpperByte reads the low byte.
        Both AssetCreate and AssetInfo feed UpdateBattleStationVisuals.
        """
        a = self.ast(aid)
        levels = []
        for slot in (HULL, DEFLECTOR):
            y = a['slots'].get(str(slot))
            m = (y if a.get('owner') == 'rival' else self.module(y.get('iid'))) if y else None
            levels.append(max(0, min(15, int(m['level']))) if m else 0)
        return (levels[0] << 16) | levels[1]

    def map_assets(self, aid):
        """The asteroid's entities: the asteroid (35) if empty; the center (36) and satellites (37) if built."""
        a = self.ast(aid)
        x, y = position(aid)
        if a['state'] != 'built':
            cmd = self.asset_cmd(asset_id(aid), ASTEROID, x, y, ASTEROIDS[aid]['name'])
            if a['state'] == 'building':
                cmd[1]['modifier'] = [self.construction_modifier(aid)]
            return [(asset_id(aid), ASTEROID, cmd)]
        rival = a.get('owner') == 'rival'
        clan = {'id': 9000 + aid, 'tag': (a.get('rival') or '')[:3].upper()} if rival else self.st_clan(a)
        fac = a.get('rival_company', 0) if rival else self.st_faction(a)
        rel = self.diplomacy(a)
        stage = self.hub_stage(aid)
        out = [(asset_id(aid), BATTLESTATION, self.asset_cmd(asset_id(aid), BATTLESTATION, x, y, a.get('rival') if rival else self.st_name(a),
                                                             stage=stage, clan=clan, faction=fac, relation=rel))]
        for slot, slot_info in sorted(a['slots'].items(), key=lambda kv: int(kv[0])):
            s = int(slot)
            if s <= DEFLECTOR:
                continue
            m = self.module(slot_info['iid']) if not rival else slot_info
            if not m:
                continue
            sx, sy = satellite_pos(aid, s)
            loot = m['loot']
            dead = m['hp'] <= 0
            out.append((asset_id(aid, s), SATELLITE, self.asset_cmd(asset_id(aid, s), SATELLITE, sx, sy, 'wreck' if dead else MODS[loot]['code'],
                                                                   design=0 if dead else MODS[loot]['design'], stage=m['level'],
                                                                   clan=clan, faction=fac, relation=rel)))
        for uid, kind, cmd in out:
            if kind == SATELLITE and cmd[1]['designId'] == 0:
                continue
            df = a['deflector']
            if self.shielded(a):
                cmd[1]['modifier'] = [self.deflector_modifier(uid, 34, True, int(df.get('sec', 0)))]
            elif kind == BATTLESTATION:
                seconds = max(0, math.ceil(df.get('closed_until', 0) - time.time()))
                if seconds:
                    cmd[1]['modifier'] = [self.deflector_modifier(uid, 35, True, seconds)]
        return out

    @staticmethod
    def construction_modifier(aid):
        # Native .115 modifier 37 creates ConstructingEffect2D/3D; the building UI alone does not.
        return mod('VisualModifierCommand', userId=asset_id(aid), modifier=37, attribute=0,
                   additionalAttribute='', count=0, activated=True)

    @staticmethod
    def deflector_modifier(uid, modifier, active, seconds=0):
        # Native 1.1.115: 34 = shield + hub timer; 35 = hub downtime timer.
        return mod('VisualModifierCommand', userId=uid, modifier=modifier, attribute=max(0, int(seconds)),
                   additionalAttribute='', count=0, activated=active)

    def deflector_visuals(self, aid, now):
        """Update every displayed living asset, including viewers outside management range."""
        df = self.ast(aid)['deflector']
        shown = {uid for uid, _ in self.shown_assets}
        assets = [(uid, kind) for uid, kind, cmd in self.map_assets(aid)
                  if uid in shown and not (kind == SATELLITE and cmd[1]['designId'] == 0)]
        hub = asset_id(aid)
        if self.shielded(self.ast(aid)):
            # Clearing timer 35 after shield 34 would delete the active shield's own timer (both effect 49).
            msgs = [('VisualModifierCommand', self.deflector_modifier(hub, 35, False))] if hub in shown else []
            return msgs + [('VisualModifierCommand', self.deflector_modifier(uid, 34, True, df.get('sec', 0)))
                           for uid, _ in assets]
        msgs = [('VisualModifierCommand', self.deflector_modifier(uid, 34, False)) for uid, _ in assets]
        seconds = max(0, math.ceil(df.get('closed_until', 0) - now))
        if hub in shown:
            msgs.append(('VisualModifierCommand', self.deflector_modifier(hub, 35, seconds > 0, seconds)))
        return msgs

    def remove_assets(self):
        msgs = [('AssetRemoveCommand', {'assetType': mod('AssetTypeModule', typeValue=k), 'uid': i}) for i, k in self.shown_assets]
        self.shown_assets = []
        return msgs

    def show_assets(self, map_id):
        msgs = self.remove_assets()
        self.seen = {int(k): self.seen_key(a) for k, a in self.asteroids.items()}
        for aid in BY_MAP.get(int(map_id), []):
            for i, k, cmd in self.map_assets(aid):
                self.shown_assets.append((i, k))
                msgs.append(cmd)
        return msgs

    def info_cmd(self, aid, slot, m=None):
        """The entity's HP/shield bar (AssetInfoCommand)."""
        a = self.ast(aid)
        y = a['slots'].get(str(slot)) or {}
        m = m or (y if a.get('owner') == 'rival' else self.module(y.get('iid')))
        if not m:
            return None
        mh = hp_max(m)                              # for a rival, with the single-player multiplier (maximum)
        ms = min(SET.I32, int(mh * D['shield_ratio']))
        kind = BATTLESTATION if slot <= DEFLECTOR else SATELLITE
        return ('AssetInfoCommand', dict(assetId=asset_id(aid, slot), type=mod('AssetTypeModule', typeValue=kind),
                                         designId=1 if kind == BATTLESTATION else MODS[m['loot']]['design'],
                                         expansionStage=self.hub_stage(aid) if kind == BATTLESTATION else int(m['level']),
                                         hitpoints=int(m['hp']), maxHitpoints=mh, shielded=ms > 0, shieldEnergy=int(m['shield']),
                                         maxShieldEnergy=ms))

    # ------------------------------------------------------------ world
    def attach(self, world):
        self.world = world
        self.near = None
        self.shown_assets = []                 # refreshMap already removed the previous client's assets
        world.cbs_trade = self.trade_mult
        world.asset_targets = self                      # the rival station's modules are chosen and hit (world.asset_laser)
        msgs = self.show_assets(world.map_id)
        return msgs

    def can_dock(self, aid):
        """Local own/allied docking rule, independent of shield/PvP immunity."""
        k = self.clan()
        if not k or not k.get('id'):
            return False
        a = self.ast(aid)
        if a['state'] != 'built' or a.get('owner') == 'rival':
            return False
        owner = a.get('clan') or (k['id'] if self.host is None else None)
        relation = (KL.clan_relation(k['id'], owner) if self.host is not None else
                    next((d['type'] for d in k.get('diplomacy', []) if d['clan'] == owner), 0))
        return owner == k['id'] or relation == 1

    def docking_station(self, x, y):
        if self.world is None:
            return None
        for aid in BY_MAP.get(int(self.world.map_id), []):
            if not self.can_dock(aid):
                continue
            sx, sy = position(aid)
            if math.hypot(x - sx, y - sy) <= D['range']:
                return dict(posX=sx, posY=sy, peaceRadius=D['range'], pvpPeace=False)
        return None

    def starmap_msgs(self):
        """The star map's station states changed (built, rival built, destroyed): resend with the login's template."""
        return self.login_replace('StarmapStationCommand', self.starmap_tpl) if self.starmap_tpl and self.world else []

    def login_replace(self, n, f):
        if n != 'StarmapStationCommand':
            return None
        self.starmap_tpl = f
        f = json.loads(json.dumps(f))
        by_name = {a['name']: k for k, a in ASTEROIDS.items()}
        for s in f.get('stations', []):
            aid = by_name.get(s.get('asteroidName'))
            if not aid:
                continue
            a = self.ast(aid)
            s['lastChangedTimestamp'] = 0               # ownerless: not the change time the recorded account saw (E10)
            if a['state'] in ('built', 'building'):
                rival = a.get('owner') == 'rival'
                s.update(status=OWN if self.mine(a) else HOSTILE if self.diplomacy(a) == 3 else NEUTRAL, clanName=a.get('rival') if rival else self.st_name(a),
                         owningFaction=mod('FactionModule', faction=a.get('rival_company', 0) if rival else self.st_faction(a)),
                         lastChangedTimestamp=int(a.get('founded', time.time()) * 1000))
        f['currentServerTimestamp'] = int(time.time() * 1000)
        return [('StarmapStationCommand', {k: v for k, v in f.items() if k != '_m'})]

    def tick(self, now):
        msgs = []
        st = self.st
        pt = prime_time(now)
        if self.prime is not None and pt != self.prime and self.clan_name():
            # the recorded line: 0|n|MSG|1|1|msg_primetime_started| ("Activated Battle Station's Prime Time"); its end _ended
            msgs.append(legacy('0|n|MSG|1|1|msg_primetime_%s|' % ('started' if pt else 'ended')))
        self.prime = pt
        shared = self.host is not None
        run = True
        if shared:                                      # the shared asteroids' jobs run on the server once a second (whichever session)
            with SHARED['lock']:
                run = now >= SHARED['next']
                if run:
                    SHARED['next'] = now + 1.0
        for aid_s, a in list(self.asteroids.items()) if run else []:
            try:                                        # one asteroid's error must not stop the others and the proximity check
                out = self.tick_asteroid(int(aid_s), a, now)
                msgs += [] if shared else out           # in the shared record the view is refreshed by version (below), announcements go to the clan (tell)
            except Exception:
                if not self.tick_err.get(aid_s):
                    self.tick_err[aid_s] = True
                    self.log('   CBS: error in asteroid %s:\n%s' % (ASTEROIDS.get(int(aid_s), {}).get('name', aid_s), traceback.format_exc()))
        w = self.world
        if shared and w is not None:
            msgs += self.refresh_changed()
        if w and not w.hero_dead and BY_MAP.get(int(w.map_id)):
            hx, hy = w.hero_pos(now)
            near = next((aid for aid in BY_MAP[int(w.map_id)] if math.hypot(position(aid)[0] - hx, position(aid)[1] - hy)
                         <= D['range']), None)
            if near != self.near:
                if self.near:
                    msgs += [H.asset_available(asset_id(self.near), 'ttip_cbs', False),
                             ('OutOfBattleStationRangeCommand', {'battleStationId': asset_id(self.near)})]
                if near:
                    msgs += [H.asset_available(asset_id(near), 'ttip_cbs', True)] + self.ui_msgs(near)
                    msgs += self.p.hint(27) if getattr(self.p, 'hint', None) else []      # CLAN_BATTLE_STATION hint
                self.near = near
            if w:
                msgs += self.raid_tick(now)
                msgs += self.rival_fire(now)
        # AssetInfo invokes native BuildSelect. Background repairs/raids must
        # update other structures without replacing the player's target.
        if w is not None:
            msgs = [('AttackHitAssetCommand', dict(assetId=f['assetId'], hitpointsNow=f['hitpoints'],
                        hitpointsMax=f['maxHitpoints']))
                    if n == 'AssetInfoCommand' and f['assetId'] != w.target else (n, f) for n, f in msgs]
        return msgs

    def seen_key(self, a):
        """What the view of a shared asteroid depends on: its version, state and (built/building) the owner's diplomacy with the player's clan."""
        return a.get('version', 0), a.get('state'), self.diplomacy(a) if a.get('state') in ('built', 'building') else 0

    def refresh_changed(self):
        """Shared asteroids whose version changed (another session's work or the server's timed job): the entities of those on the map,
        the window of the one nearby; built/destroyed or the owner's diplomacy with the player's clan changed: the galaxy map."""
        msgs, star = [], False
        w = self.world
        for aid_s, a in list(self.asteroids.items()):
            aid = int(aid_s)
            v = self.seen_key(a)
            old = self.seen.get(aid)
            self.seen[aid] = v
            if old == v or aid not in ASTEROIDS:
                continue
            star = star or (old or (0, 'vacant', 0))[1:] != v[1:]
            if int(ASTEROIDS[aid]['map']) == int(w.map_id):
                msgs += self.refresh_assets(aid)
                if self.near == aid:
                    msgs += self.ui_msgs(aid)
        return msgs + (self.starmap_msgs() if star else [])

    def tick_asteroid(self, aid, a, now):
        msgs = []
        w = self.world
        here = w is not None and int(w.map_id) == int(ASTEROIDS[aid]['map'])
        if a.get('owner') != 'rival':
            done = [y for y in a['slots'].values()            # modules whose installation finished: refreshed once per step
                    if y.get('install_sec') and not y.get('installed') and now >= y.get('install_end', 0)]
            for y in done:
                y['installed'] = True
                self.mark()
            if done:
                self.bump(a)
            if done and here and self.near == aid:
                msgs.append(self.progress_msg(aid, now) if a['state'] == 'vacant' else self.status_msg(aid, now))
            if done and a['state'] == 'built' and here:
                msgs += self.refresh_assets(aid)
        if a['state'] == 'building' and now >= a.get('build_end', 0):
            msgs += self.finish_build(aid, now)
        if a['state'] == 'built' and a.get('owner') != 'rival':        # the rival's deflector and repair are in rival_tick
            msgs += self.deflector_tick(aid, a, now)
            msgs += self.repair_tick(aid, a, now)
        msgs += self.rival_tick(aid, a, now)
        return msgs

    def refresh_assets(self, aid):
        msgs = []
        for i, k in [x for x in self.shown_assets if ASSET_BASE + aid * 100 <= x[0] < ASSET_BASE + aid * 100 + 100]:
            msgs.append(('AssetRemoveCommand', {'assetType': mod('AssetTypeModule', typeValue=k), 'uid': i}))
            self.shown_assets.remove((i, k))
        for i, k, cmd in self.map_assets(aid):
            self.shown_assets.append((i, k))
            msgs.append(cmd)
        return msgs

    # ------------------------------------------------------------ requests
    def in_range(self, aid):
        w = self.world
        if not w or int(w.map_id) != int(ASTEROIDS.get(aid, {}).get('map', -1)):
            return False
        hx, hy = w.hero_pos()
        x, y = position(aid)
        return math.hypot(x - hx, y - hy) <= D['range'] + 100

    def handles(self, name, f):
        if name == 'MapAssetActivationRequest':
            return int(f.get('mapAssetId') or 0) // 100 * 100 - ASSET_BASE in [k * 100 for k in ASTEROIDS]
        return name in self.REQUESTS

    def handle(self, name, f):
        if name == 'MapAssetActivationRequest':
            aid = (int(f.get('mapAssetId') or 0) - ASSET_BASE) // 100
            return self.ui_msgs(aid) if aid in ASTEROIDS and self.in_range(aid) else []
        if name == 'HangarShipRepairModuleRequest':
            return self.hangar_repair(int(f.get('itemId') or 0))
        aid = int(f.get('battleStationId') or 0)
        if aid not in ASTEROIDS:
            return self.error('UNSPECIFIED')
        if not self.clan():
            return self.error('NO_CLAN')
        if not self.in_range(aid):
            return self.error('OUT_OF_RANGE')
        if name != 'EquipModuleRequest' and not self.mine(self.ast(aid)):
            return self.error('CONCURRENT_EQUIP')      # another clan's station
        out = []
        if name == 'EquipModuleRequest':
            out = self.equip(aid, int(f.get('itemId') or 0), int(f.get('slotId') or 0), bool(f.get('replace')))
        elif name == 'UnequipModuleRequest':
            out = self.unequip(aid, int(f.get('itemId') or 0))
        elif name == 'BuildStationRequest':
            out = self.build(aid, int(f.get('buildTimeInMinutes') or 0))
        elif name == 'DeflectorShieldStatusChangeRequest':
            out = self.deflector_off(aid, int(f.get('minutes') or 0))
        elif name == 'EmergencyRepairRequest':
            out = self.emergency(aid, int(f.get('slotId') or 0))
        a = self.ast(aid)
        if out and out[0][0] != 'BattleStationErrorCommand':
            self.bump(a)                               # let the other sessions refresh; this session refreshed with the reply
            self.seen[aid] = self.seen_key(a)
        return out

    def equip(self, aid, iid, slot, replace):
        a = self.ast(aid)
        now = time.time()
        m = self.own_module(iid)
        me = KL.name(self.p)
        if a.get('owner') == 'rival' or not self.mine(a):
            return self.error('CONCURRENT_EQUIP')
        if a['state'] == 'building':
            return self.error('STATION_ALREADY_BUILDING')
        if not m:
            return self.error('ITEM_NOT_OWNED')
        if self.where(iid):
            return self.error('ITEM_ALREADY_EQUIPPED_IN_ANOTHER_ASTEROID')
        if m['hp'] <= 0:
            return self.error('ITEM_HITPOINTS_ZERO')
        if any(y.get('install_end', 0) > now and y.get('owner', me) == me for b in self.asteroids.values()
               for y in b.get('slots', {}).values()):
            return self.error('EQUIP_OF_SAME_PLAYER_RUNNING')
        md = MODS[m['loot']]
        if slot < 0 or slot >= SLOTS:
            return self.error('UNSPECIFIED')
        if slot <= DEFLECTOR and (not md['center'] or (slot == HULL) != (md['type'] == 2)):
            return self.error('HUB_ONLY' if not md['center'] else 'SATELLITE_ONLY')
        if slot > DEFLECTOR and md['center']:
            return self.error('SATELLITE_ONLY')
        same = sum(1 for s, y in a['slots'].items() if int(s) != slot and self.module(y['iid'])
                   and self.module(y['iid'])['loot'] == m['loot'])
        if same >= md['max_count']:
            return self.error('MAX_NUMBER_OF_MODULE_TYPE_EXCEEDED')
        old = a['slots'].get(str(slot))
        if old and not replace:
            return self.error('CONCURRENT_EQUIP')
        if old and not self.hp('battle_station_replace_module'):
            return self.error('REPLACE_RIGHT_MISSING')
        secs = D['swap_sec'] if a['state'] == 'built' else D['install_sec']
        old_loot = (self.module(old['iid']) or {}).get('loot', '') if old else ''
        y = {'iid': iid, 'install_end': now + secs, 'install_sec': secs}
        h = self.host
        if h is not None:                               # shared: module to the slot (everyone sees it), with a unique id
            cbs_h, mods, cid = h.d['cbs'], self.st['modules'], self.clan()['id']
            with self.lock:
                cbs_h['shared_seq'] = int(cbs_h.get('shared_seq', 0)) + 1
                y.update(iid=SHARED_ITEM + cbs_h['shared_seq'], module=m, owner=me, owner_name=self.p.d['pilot'].get('userName', ''))
                mods.pop(str(iid), None)
                a['clan'] = cid
        if old:
            self.give_back(old)
        with self.lock:
            a['slots'][str(slot)] = y
            self.mark()
        if old:
            self.note(aid, 'MODULE_REPLACED', oldModuleType=old_loot,
                      oldModuleLevel=0, newModuleType=m['loot'], newModuleLevel=m['level'], slot=slot if slot > DEFLECTOR else -1)
        self.log('   CBS: %s %s slot %d (%d s)' % (ASTEROIDS[aid]['name'], m['loot'], slot, secs))
        msgs = [self.progress_msg(aid, now) if a['state'] == 'vacant' else self.status_msg(aid, now), self.available_msg()]
        if a['state'] != 'vacant':
            msgs += self.refresh_assets(aid)
        return msgs

    def unequip(self, aid, iid):
        a = self.ast(aid)
        hit = next((s for s, y in a['slots'].items() if int(y['iid']) == iid), None)
        if hit is None:
            return self.error('ITEM_NOT_IN_STATION')
        y = a['slots'][hit]
        if y.get('owner', KL.name(self.p)) != KL.name(self.p) and not self.hp('battle_station_replace_module'):
            return self.error('REPLACE_RIGHT_MISSING')
        # module removed while installing: the client's "The installation of this Module has been cancelled."
        abort = [stm('msg_station_module_install_aborted')] if y.get('install_end', 0) > time.time() else []
        m = self.module(iid)
        with self.lock:
            del a['slots'][hit]
            if not a['slots'] and a['state'] == 'vacant':
                a.pop('clan', None)                     # the emptied asteroid may belong to another clan too
            self.mark()
        self.give_back(y)
        self.note(aid, 'MODULE_REMOVED', moduleType=m['loot'] if m else '', moduleLevel=m['level'] if m else 0,
                  slot=int(hit) if int(hit) > DEFLECTOR else -1)
        if a['state'] == 'built' and int(hit) == HULL:
            self.destroy(aid, 'hull removed')
            return [self.building_ui(aid), self.available_msg()] + self.refresh_assets(aid) + abort
        msgs = [self.progress_msg(aid) if a['state'] == 'vacant' else self.status_msg(aid), self.available_msg()]
        return msgs + (self.refresh_assets(aid) if a['state'] != 'vacant' else []) + abort

    def build(self, aid, minutes):
        a = self.ast(aid)
        now = time.time()
        if a['state'] != 'vacant' or self.own_progress(aid, now) < 1.0:
            return self.error('STATION_ALREADY_BUILDING')
        if not self.hp('battle_station_build'):
            return self.error('UNSPECIFIED')
        k = D['build_min']
        minutes = max(k[0], min(k[1], minutes or k[0]))
        with self.lock:
            a.update(state='building', build_end=now + minutes * 60, build_sec=minutes * 60, owner='player')
            if self.host is not None:
                a['clan'] = self.clan()['id']
            a.pop('rival', None)
            a.pop('rival_progress', None)
            race = a.pop('race', None) or {}
            self.mark()
        for cid, r in race.items():                    # the modules of the competing bot clans to their stock (clan_stations)
            refund_race(cid, r.get('modules'))
        self.note(aid, 'BUILD_START', buildSeconds=minutes * 60)
        self.log('   CBS: %s being built (%d min)' % (ASTEROIDS[aid]['name'], minutes))
        return [self.building_state(aid, now), ('VisualModifierCommand', self.construction_modifier(aid))]

    def stats(self, a):
        """Station counts: in the profile in single player, in the station's clan record in the shared record."""
        if self.host is None:
            return self.st['stats']
        k = KL.CLANS.get(a.get('clan')) or {}
        return k.setdefault('cbs_stats', {})

    def finish_build(self, aid, now):
        a = self.ast(aid)
        ist, asteroids = self.stats(a), self.asteroids
        with self.lock:
            a.update(state='built', founded=now)
            a['deflector'] = {'on': True, 'sec': D['on_build_deflector_min'] * 60.0, 'closed_until': 0.0, 'last': now}   # forum 127469
            ist['all'] = ist.get('all', 0) + 1
            ist['max_count'] = max(ist.get('max_count', 0), sum(1 for b in asteroids.values() if b.get('state') == 'built'
                                                       and b.get('owner') != 'rival' and b.get('clan') == a.get('clan')))
            self.bump(a)
            self.mark()
        self.note(aid, 'BUILD_FINISHED')
        self.log('   CBS: %s built' % ASTEROIDS[aid]['name'])
        msgs = self.tell(a, [stm('msg_station_accomplished', STATION=ASTEROIDS[aid]['name'], CLAN=self.st_name(a),
                                 MAP=H.name(ASTEROIDS[aid]['map']))]) + self.starmap_msgs()
        w = self.world
        if w and int(w.map_id) == int(ASTEROIDS[aid]['map']):
            msgs += self.refresh_assets(aid)
            if self.near == aid:
                msgs.append(self.management_ui(aid))
        return msgs

    def deflector_charge(self, start, end, aid=None):
        """Integrate recharge over local prime-time boundaries, including offline time."""
        total = 0.0
        while start < end:
            day = datetime.datetime.fromtimestamp(start).replace(hour=0, minute=0, second=0, microsecond=0)
            boundaries = [day + datetime.timedelta(days=1)]
            for text in D.get('prime_time', ['18:00', '21:00']):
                hour, minute = map(int, text.split(':'))
                boundaries.append(day.replace(hour=hour, minute=minute))
            stop = min([end] + [t.timestamp() for t in boundaries if t.timestamp() > start])
            total += (stop - start) * self.deflector_rate(start, aid) / 60.0
            start = stop
        return total

    def deflector_tick(self, aid, a, now):
        df = a['deflector']
        cursor = min(now, df.get('last', now))
        changed, exhausted = False, False
        while True:
            if df['on']:
                elapsed = min(max(0.0, df['sec']), now - cursor)
                df['sec'] = max(0.0, df['sec'] - elapsed)
                cursor += elapsed
                if df['sec'] > 0:
                    break
                # Downtime starts at the actual exhaustion instant, even after a delayed tick.
                df.update(on=False, closed_until=cursor + D['deflector_end_off_min'] * 60)
                changed = exhausted = True
                self.bump(a)
                self.note(aid, 'DEFLECTOR_OFF')
            else:
                deadline = df.get('closed_until', 0)
                stop = min(now, max(cursor, deadline))
                if stop == cursor and df['sec'] <= 0:
                    stop = now
                df['sec'] = min(D['deflector_max_sec'], df['sec'] + self.deflector_charge(cursor, stop, aid))
                cursor = stop
                if cursor < deadline or df['sec'] <= 0:
                    break
                df['on'] = True
                changed = True
                self.bump(a)
                self.note(aid, 'DEFLECTOR_ON')
            if cursor >= now:
                break
        df['last'] = now
        self.mark()
        msgs = self.near_status(aid, now) if changed else []
        if exhausted and not df['on']:
            msgs += self.tell(a, [GALAXY.screen('The deflector shield of your Battle Station at %s is down!' % ASTEROIDS[aid]['name'])])
        return msgs

    def near_status(self, aid, now):
        """World shield/timer effects and the nearby owner's management controls."""
        msgs = self.deflector_visuals(aid, now)
        if self.near == aid and self.mine(self.ast(aid)):
            msgs += [self.status_msg(aid, now), self.management_ui(aid, now)]
        return msgs

    def deflector_off(self, aid, minutes):
        a = self.ast(aid)
        if a['state'] != 'built':
            return self.error('UNSPECIFIED')
        if not self.hp('battle_station_deflector'):
            return self.error('UNSPECIFIED')
        now = time.time()
        # Settle the active countdown before resetting its clock for the requested downtime.
        pending = self.deflector_tick(aid, a, now)
        df = a['deflector']
        if not df['on']:
            return pending + self.error('DEFLECTOR_ALREADY_OFF')
        dm = D['deflector_min']
        minutes = max(dm[0], min(dm[1], minutes or dm[0]))
        with self.lock:
            df.update(on=False, closed_until=now + minutes * 60, last=now)
            self.bump(a)
            self.mark()
        self.note(aid, 'DEFLECTOR_OFF', userName=self.p.d['pilot'].get('userName', ''))
        self.log('   CBS: %s deflector off for %d min' % (ASTEROIDS[aid]['name'], minutes))
        return pending + self.deflector_visuals(aid, now) + [self.status_msg(aid, now), self.management_ui(aid, now)]

    def emergency(self, aid, slot):
        a = self.ast(aid)
        y = a['slots'].get(str(slot))
        m = self.module(y['iid']) if y else None
        if not m or m['hp'] <= 0:
            return self.error('REPAIR_NO_MODULE')
        now = time.time()
        if y.get('repair_end', 0) > now:
            return self.error('REPAIR_ALREADY_RUNNING')
        cost = D['emergency_repair']['charge']
        if self.p.d['pilot'].get('uridium', 0) < cost:
            return self.error('REPAIR_NO_MONEY')
        self.p.gain(uridium=-cost, reason='battlestation_emergency_repair')
        with self.lock:
            y['repair_end'] = now + D['emergency_repair']['duration_sec']
            (a.get('shares') or {}).pop(str(slot), None)   # "If the Module will be repaired the damage distribution will be reset" (FAQ)
            self.mark()
        self.note(aid, 'EMERGENCY_REPAIR', moduleType=m['loot'], moduleLevel=m['level'], slot=slot if slot > DEFLECTOR else -1)
        return [self.status_msg(aid, now), stm('msg_emergency_repair_started', STATION=ASTEROIDS[aid]['name'])] + self.m.money_msgs()

    def repair_tick(self, aid, a, now):
        """Emergency repair (7,500/s), Engineering Bay (all modules), or slow repair 30 s after the last damage; the shield refills."""
        rep = 0
        for y in a['slots'].values():
            m = self.module(y['iid'])
            if m and MODS[m['loot']].get('repair_sec') and m['hp'] > 0 and y.get('install_end', 0) <= now:
                rep = level_value(MODS[m['loot']]['repair_sec'], m['level'])
        changed = []
        for slot, y in a['slots'].items():
            m = self.module(y['iid'])
            if not m or m['hp'] <= 0:
                continue
            mh, ms = self.mx(m)
            heal = 0
            if y.get('repair_end', 0) > now:
                heal += D['emergency_repair']['hp_sec']
            if rep:
                heal += rep
            elif now - a.get('last_damage', 0) > D['passive_repair']['delay_sec']:
                heal += D['passive_repair']['hp_sec']
            before = (m['hp'], m['shield'])
            m['hp'] = min(mh, m['hp'] + heal)
            if now - a.get('last_damage', 0) > 10:
                m['shield'] = min(ms, m['shield'] + ms * 0.02)
            if (m['hp'], m['shield']) != before:
                changed.append(int(slot))
        w = self.world
        if changed and w and int(w.map_id) == int(ASTEROIDS[aid]['map']) and int(now) % 5 == 0:
            return [c for c in (self.info_cmd(aid, s) for s in changed) if c]
        return []

    def hangar_repair(self, iid):
        m = self.own_module(iid)
        if not m:
            return []
        mh, ms = self.mx(m)
        from shop import stack_msg
        if self.where(iid):
            return [('HangarShipRepairModuleCommand', dict(errorMessage=stack_msg('eqt_error_playerMayNotRepair'), itemId=iid,
                                                            currentHitPoints=int(m['hp']), maxHitPoints=mh, resultId=1))]
        cost = max(D['repair_cost']['min_value'], int((mh - m['hp']) * D['repair_cost']['per_hp_U']))
        if m['hp'] >= mh or self.p.d['pilot'].get('uridium', 0) < cost:
            return [('HangarShipRepairModuleCommand', dict(errorMessage=stack_msg('empty'), itemId=iid, currentHitPoints=int(m['hp']),
                                                            maxHitPoints=mh, resultId=1))]
        self.p.gain(uridium=-cost, reason='repair_module')
        with self.p.lock:
            m['hp'], m['shield'] = mh, ms
            self.p.dirty = True
        self.log('   CBS: module repaired %s (%d U)' % (m['loot'], cost))
        return [('HangarShipRepairModuleCommand', dict(errorMessage=stack_msg('empty'), itemId=iid, currentHitPoints=mh, maxHitPoints=mh,
                                                        resultId=0))] + self.m.money_msgs()

    # ------------------------------------------------------------ boosters and trade
    def mods(self):
        """Clan-wide XP/honor stack globally up to 50%; damage applies on the station map."""
        clan = self.clan()
        if not self.p.d['pilot'].get('clanId') or not clan:
            return {}
        out = {}
        here = int(self.p.d['position'].get('mapId', 0))
        for aid_s, a in list(self.asteroids.items()):
            if a.get('state') != 'built' or not self.mine(a) or a.get('clan') not in (None, clan['id']):
                continue
            aid = int(aid_s)
            out['honor'] = min(D['booster']['cap'], out.get('honor', 0) + self.booster_pct(aid, 'honor') / 100.0)
            out['ep'] = min(D['booster']['cap'], out.get('ep', 0) + self.booster_pct(aid, 'ep') / 100.0)
            if int(ASTEROIDS[aid]['map']) == here:
                d = self.booster_pct(aid, 'damage') / 100.0
                out['laser'] = max(out.get('laser', 0), d)
                out['rocket'] = max(out.get('rocket', 0), d)
        return {k: v for k, v in out.items() if v}

    def trade_mult(self):
        """Ore selling within range of one's own station (TradeType BATTLE_STATION, price x1.1) -> multiplier or None."""
        if self.near and self.ast(self.near)['state'] == 'built' and self.mine(self.ast(self.near)):
            return D['ore_multiplier']
        return None

    # ------------------------------------------------------------ damage and destruction (raid and rival)
    def damage_module(self, aid, slot, dmg, attacker_name='', shield_only=False, hull_only=False, dealer=None):
        """Damage to a module (shield absorbs 80%) -> messages; HP 0: it is destroyed; if the center (Hull) goes the station falls. dealer: the
        player (clan.name) whose damage counts towards the destruction reward (payees)."""
        a = self.ast(aid)
        y = a['slots'].get(str(slot))
        rival = a.get('owner') == 'rival'
        m = y if rival else (self.module(y['iid']) if y else None)
        if not m or m['hp'] <= 0:
            return []
        dmg = max(0, int(dmg))
        if shield_only:
            dmg = min(dmg, m['shield'])
        to_shield = dmg if shield_only else 0 if hull_only else min(m['shield'], int(dmg * 0.8))
        hp_before = m['hp']
        m['shield'] -= to_shield
        m['hp'] = max(0, m['hp'] - (dmg - to_shield))
        a['last_damage'] = time.time()
        if dealer:
            dealt = a.setdefault('shares', {}).setdefault(str(slot), {})
            dealt[dealer] = dealt.get(dealer, 0) + to_shield + hp_before - m['hp']
        self.mark()
        msgs = [c for c in [self.info_cmd(aid, slot, m)] if c]
        if m['hp'] <= 0:
            msgs += self.module_destroyed(aid, slot, attacker_name)
        return msgs

    def module_destroyed(self, aid, slot, by=''):
        a = self.ast(aid)
        rival = a.get('owner') == 'rival'
        y = a['slots'].get(str(slot))
        m = y if rival else self.module(y['iid'])
        msgs = []
        self.note(aid, 'MODULE_DESTROYED', moduleType=m['loot'], moduleLevel=m['level'], slot=slot if slot > DEFLECTOR else -1,
                  opponentClanName=by)
        payees = self.payees(a, slot)
        if payees:                                      # an enemy station's module (rival, bot clan, another player's clan): uridium by damage share
            kind = MODS[m['loot']].get('weapon') or 'other'
            u = D['demolish_reward']['base'].get(kind, D['demolish_reward']['base']['other']) + D['demolish_reward']['per_level'] * m['level']
            u = SET.amount('uridium', u, 'mod')              # the panel's uridium multiplier
            for name, part in sorted(payees.items()):
                n = max(1, int(round(u * part)))
                msgs += self.pay(name, [stm('msg_station_satellite_destruction_reward', AMOUNT=n, MODULE=MODS[m['loot']]['code'],
                                            LEVEL=m['level'] + 1, STATION=ASTEROIDS[aid]['name'])],
                                 'battlestation_destroy_module', uridium=n)
        if not rival and self.world:                    # the clan's module was destroyed: warning (to the clan in the shared record)
            msgs += self.tell(a, [stm('msg_station_module_destroyed', STATION=ASTEROIDS[aid]['name'], MAP=H.name(ASTEROIDS[aid]['map']),
                                      MODULE=MODS[m['loot']]['code'], LEVEL=m['level'] + 1)])
        self.bump(a)
        if slot == HULL:
            msgs += self.destroy(aid, by)
            return msgs
        (a.get('shares') or {}).pop(str(slot), None)
        if self.world:
            msgs += self.refresh_assets(aid)
            self.seen[aid] = self.seen_key(a)
        return msgs

    def clan_asteroids(self, k):
        """The asteroids of the clan with a module fitted or built (in single player the player's, except the rival)."""
        for aid, a in list(self.asteroids.items()):
            if a.get('owner') == 'rival' or not (a.get('slots') or a.get('state') in ('building', 'built')):
                continue
            if self.host is not None and a.get('clan') != k['id']:
                continue
            yield int(aid), a

    def member_left(self, k, who):
        """The modules of a member who leaves or is kicked from the clan return from the stations to their inventory (forum 127469). A built station
        whose Hull is removed this way does not explode: it "will still be standing there, but with only 1 hitpoint" (official CBS FAQ) until a
        Hull is fitted again or it is destroyed."""
        me, msgs = KL.name(self.p), []
        for aid, a in self.clan_asteroids(k):
            for s, y in list(a['slots'].items()):
                if y.get('owner', me) != who:
                    continue
                with self.lock:
                    a['slots'].pop(s, None)
                    if a['state'] == 'built' and int(s) == HULL:
                        a['slots'][s] = dict(iid=HULL_STANDIN + aid, placeholder=True, owner=None, module=dict(
                            loot='module_hulm-1', level=0, hp=1, shield=0, maximum=1))
                    self.bump(a)
                    self.mark()
                self.give_back(y)
                self.note(aid, 'MODULE_REMOVED', slot=int(s) if int(s) > DEFLECTOR else -1)
            if a.get('state') == 'vacant' and not a.get('slots'):
                a.pop('clan', None)
        return msgs + (self.starmap_msgs() if msgs else [])

    def clan_disbanded(self, k):
        """The clan was deleted: its stations are destroyed, the modules (destroyed) go to their owners, the asteroid is empty (forum 127469)."""
        msgs = []
        for aid, a in list(self.clan_asteroids(k)):
            msgs += self.destroy(aid, 'clan disbanded')
        return msgs

    def bot_demolition(self, a):
        """Did this session's player destroy the bot clan's station (hit it in the last 30 s): reward as for a rival's."""
        return (a.get('owner') == 'bot' and self.m is not None and self.world is not None
                and time.time() - a.get('last_player', 0) < 30 and a.get('last_attacker') == self.p.d['pilot'].get('userName', ''))

    def payees(self, a, slot):
        """Player (clan.name) -> share of the reward for an enemy station's destroyed module or hub: "The actual amount depends on the damage
        every player deals" (official CBS FAQ); an emergency repair resets it. Empty for one's own station."""
        if self.mine(a):
            return {}
        dealt = {n: v for n, v in ((a.get('shares') or {}).get(str(slot)) or {}).items() if v > 0}
        if not dealt and (a.get('owner') == 'rival' or self.bot_demolition(a)):
            dealt = {KL.name(self.p): 1}
        total = sum(dealt.values())
        return {n: v / total for n, v in dealt.items()}

    def pay(self, name, msgs, reason, uridium=0, credits=0):
        """A destruction reward to the player name: this session's player (-> messages) or another connected one (sent to them); offline
        players miss it."""
        if name == KL.name(self.p):
            self.p.gain(uridium=uridium, credits=credits, reason=reason)
            return msgs + (self.m.money_msgs() if self.m else [])
        x = KL.people().get(name)
        if x is not None:
            x.profile.gain(uridium=uridium, credits=credits, reason=reason)
            shop = getattr(x.session, 'shop', None)
            x.send(msgs + (shop.money_msgs() if shop else []), 'CBS')
        return []

    def destroy(self, aid, by=''):
        """The station fell: modules (destroyed) to the inventory, the asteroid empty."""
        a = self.ast(aid)
        rival = a.get('owner') == 'rival'
        msgs = []
        payees = self.payees(a, HULL) if by != 'clan disbanded' else {}
        if payees:                                      # the hub of an enemy station: the reward by damage share on the hub (official FAQ)
            r = D['demolish_reward']['center']
            r = dict(r, uridium=SET.amount('uridium', r['uridium'], 'mod'), credits=SET.amount('credits', r['credits'], 'mod'))     # the panel's multipliers
            for name, part in sorted(payees.items()):
                u, c = max(1, int(round(r['uridium'] * part))), int(round(r['credits'] * part))
                msgs += self.pay(name, [stm('msg_station_hub_destruction_reward', AMOUNT=u, STATION=ASTEROIDS[aid]['name']),
                                        stm('msg_station_destroyed_by_clan', DESTROYER=self.clan_name(),
                                            LOSER=a.get('rival', '') if rival else self.st_name(a),
                                            STATION=ASTEROIDS[aid]['name'], MAP=H.name(ASTEROIDS[aid]['map']))],
                                 'battlestation_destroy_station', uridium=u, credits=c)
        if not rival:
            for y in a['slots'].values():
                m = self.module(y['iid'])
                if m:
                    m['hp'], m['shield'] = 0, 0
                self.give_back(y)                       # shared: destroyed module to its owner
            ist = self.stats(a)
            ist['demolished'] = ist.get('demolished', 0) + 1
            ist['longest_sec'] = max(ist.get('longest_sec', 0), int(time.time() - a.get('founded', time.time())))
            msgs += self.tell(a, [stm('msg_station_destroyed', LOSER=self.st_name(a), STATION=ASTEROIDS[aid]['name'],
                                      MAP=H.name(ASTEROIDS[aid]['map']))])
        self.note(aid, 'DESTROYED', opponentClanName=by)
        self.log('   CBS: station %s destroyed (%s)' % (ASTEROIDS[aid]['name'], by or 'player'))
        asteroids = self.asteroids
        with self.lock:
            asteroids[str(aid)] = {'state': 'vacant', 'slots': {}, 'rival_round': a.get('rival_round', 0) + (1 if rival else 0),
                              'version': a.get('version', 0) + 1}
            self.mark()
        self.ast(aid)
        for i in [i for i, k in self.raiders.items() if k == aid]:
            self.raiders.pop(i, None)
        msgs += self.starmap_msgs()
        if self.world:
            msgs += self.refresh_assets(aid)
        self.seen[aid] = (self.ast(aid).get('version', 0), 'vacant', 0)
        if self.near == aid and not rival:
            msgs += [self.building_ui(aid), self.available_msg()]
        return msgs

    @staticmethod
    def weapon_visual(md, attacker, target, hit):
        """Single native rocket for RAM modules; lasers keep the beam command.

        1.1.115 Hellstorm handler resolves generic map entities, including CBS
        satellites. ECO-10 appearance is a local reuse, not an official RAM skin.
        """
        if md['weapon'] == 'rocket':
            return ('HellstormAttackCommand', dict(attackerId=attacker, targetId=target, hit=hit, currentLoad=1,
                                                  rocketType=mod('AmmunitionTypeModule', typeValue=23)))
        return ('AttackLaserRunCommand', dict(attackerId=attacker, targetId=target, laserColor=0,
                                             isDiminishedBySkillShield=False, skilledLaser=False, visualType=0))

    # ------------------------------------------------------------ CBS-3: alien raids
    def raid_tick(self, now):
        w = self.world
        msgs = []
        for aid in BY_MAP.get(int(w.map_id), []):
            a = self.ast(aid)
            if a['state'] != 'built' or a.get('owner') == 'rival':
                continue
            open_ = not a['deflector']['on']
            due = a.get('next_raid', 0) if self.host is not None else self.next_raid.get(aid, 0)   # in the shared record one raid on the map
            if open_ and prime_time(now) and now >= due:
                self.next_raid[aid] = a['next_raid'] = now + D['raid']['interval_min'] * 60
                msgs += self.spawn_raid(aid)
            msgs += self.raid_fight(aid, a, now)
        return msgs

    def spawn_raid(self, aid):
        w = self.world
        cls = H.map_class(ASTEROIDS[aid]['map'])
        kinds = D['raid']['kinds'].get(cls) or ['81']
        x, y = position(aid)
        n = random.randint(*D['raid']['count'])
        hp_each, dmg_each = self.raid_power(aid, n, time.time())
        prep = lambda nn: PS.scale_npc(nn, hp=max(1.0, hp_each / max(1, nn.d['hp'] + nn.d['shield'])),     # the type's damage to the player
                                       extra={'station_damage': max(nn.d['damage'], int(dmg_each))})
        for _ in range(n):
            a, r = random.uniform(0, 2 * math.pi), random.uniform(900, 1300)
            nx = min(max(int(x + math.cos(a) * r), 300), w.map_w - 300)
            ny = min(max(int(y + math.sin(a) * r), 300), w.map_h - 300)
            npc = w.spawn_npc_at(random.choice(kinds), nx, ny, prep=prep)
            npc.gate = True
            npc.next_think = time.time() + 10 ** 6         # the raid controls movement (fights the player when hit)
            self.raiders[npc.id] = aid
            tx, ty = x + random.randint(-300, 300), y + random.randint(-200, 200)
            ms = npc.mover.go(tx, ty, max(150, npc.d.get('speed', 300)), time.time())
            w.send([('MoveCommand', dict(userId=npc.id, x=int(tx), y=int(ty), timeToTarget=ms))])
        self.log('   CBS: %s alien raid (%d)' % (ASTEROIDS[aid]['name'], n))
        return [GALAXY.screen('key:msg_object_under_attack', big=True, ASSET_NAME='Battle Station %s' % ASTEROIDS[aid]['name'])]

    def raid_power(self, aid, n, now):
        """HP+shield per raider and shot damage per the station (the map's ordinary aliens could not scratch the 1-million satellites; live test: the
        raid ended in 10 s): the weapons clear the raid unaided in ~sure_sn, and in that time the raid takes ~damage_ratio of the modules'
        HP+shield. If the player hits too it ends earlier."""
        B = D['raid']
        boost = 1 + self.booster_pct(aid, 'damage', now) / 100.0
        dps = total = 0.0
        for slot_info in self.ast(aid)['slots'].values():
            m = self.module(slot_info['iid'])
            if not m or m['hp'] <= 0:
                continue
            md = MODS[m['loot']]
            total += m['hp'] + m['shield']
            if md.get('weapon'):
                dps += dmg_value(md, m['level']) * boost * md['hit'] / md['interval_sec']
        shots = B['duration_sec'] / world_module.COMBAT['npc_attack_interval_sec']
        return dps * B['duration_sec'] / n, total * B['damage_ratio'] / shots / n

    def raid_fight(self, aid, a, now):
        w = self.world
        msgs = []
        x, y = position(aid)
        alive = [w.npcs[i] for i, k in list(self.raiders.items()) if k == aid and i in w.npcs and w.npcs[i].alive]
        for i in [i for i, k in list(self.raiders.items()) if k == aid and i not in w.npcs]:
            self.raiders.pop(i, None)
        # the aliens hit the modules (those not fighting the player)
        targets = [int(s) for s, slot_info in a['slots'].items() if self.module(slot_info['iid']) and self.module(slot_info['iid'])['hp'] > 0]
        for n in alive:
            if n.engaged or now < self.next_shot.get(n.id, 0):
                continue
            nx, ny = n.mover.pos(now)
            if math.hypot(nx - x, ny - y) > 700 and math.hypot(n.mover.x1 - x, n.mover.y1 - y) > 700:   # separated from the player: returns to the station
                w.alien_ceasefire(n)                    # if it fires at the station, the laser state closes on the client (AttackAbortLaserCommand)
                n.next_think = now + 10 ** 6
                tx, ty = x + random.randint(-300, 300), y + random.randint(-200, 200)
                ms = n.mover.go(tx, ty, max(150, n.d.get('speed', 300)), now)
                w.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])
                continue
            if math.hypot(nx - x, ny - y) > 700 or not targets:
                w.alien_ceasefire(n)                    # out of range or no target left: laser ended
                continue
            n.firing = True                             # fired a laser at the station: on release alien_ceasefire sends AttackAbortLaserCommand
            self.next_shot[n.id] = now + world_module.COMBAT['npc_attack_interval_sec']
            sats = [s for s in targets if s > DEFLECTOR]
            slot = random.choice(sats) if sats else HULL
            dmg = int(n.d.get('station_damage', n.d['damage']) * random.uniform(0.8, 1.0))
            w.send([('AttackLaserRunCommand', dict(attackerId=n.id, targetId=asset_id(aid, slot), laserColor=0,
                                                   isDiminishedBySkillShield=False, skilledLaser=False, visualType=0))])
            msgs += self.damage_module(aid, slot, dmg, n.d['name'])
            if self.ast(aid)['state'] != 'built':
                return msgs
        # the weapon modules fire at raiders in range
        dmg_boost = 1 + self.booster_pct(aid, 'damage', now) / 100.0
        for s, slot_info in a['slots'].items():
            m = self.module(slot_info['iid'])
            md = MODS[m['loot']] if m else {}
            if not m or not md.get('weapon') or m['hp'] <= 0 or slot_info.get('install_end', 0) > now:
                continue
            key = (aid, int(s))
            if now < self.next_shot.get(key, 0):
                continue
            sx, sy = satellite_pos(aid, int(s))
            near = [n for n in alive if n.alive and math.hypot(n.mover.pos(now)[0] - sx, n.mover.pos(now)[1] - sy) <= md['range']]
            if not near:
                continue
            self.next_shot[key] = now + md['interval_sec']
            n = random.choice(near)
            hit = random.random() < md['hit']
            atype = 0 if md['weapon'] == 'rocket' else 1
            w.send([self.weapon_visual(md, asset_id(aid, int(s)), n.id, hit)])
            if hit:
                w.hit_npc(n.id, int(dmg_value(md, m['level']) * dmg_boost), atype, attacker=asset_id(aid, int(s)), engage=False, source_asset=True)
            else:
                w.send([('AttackMissedCommand', dict(attackType=world_module.attack_type(atype), targetUserId=n.id, skillColorId=0))])
        return msgs

    # ------------------------------------------------------------ CBS-4: virtual rival clans
    def rival_tick(self, aid, a, now):
        """Rival clan on an empty asteroid (seeded): it progresses, and if it finishes first it builds an enemy station. No fake rival while bots are
        present: the station it built and its progress are deleted once, the asteroid opens empty (the race belongs to the bot clans: clan_stations)."""
        if with_bots():
            if a.get('owner') == 'rival' or a.get('rival') is not None:
                with self.lock:
                    if a.get('owner') == 'rival':
                        a.update(state='vacant', slots={}, deflector={'on': False, 'sec': 0.0, 'closed_until': 0.0, 'last': now})
                        a.pop('owner', None)
                    for f in ('rival', 'rival_progress', 'rival_speed', 'rival_company', 'rival_last'):
                        a.pop(f, None)
                    self.bump(a)
                    self.mark()
                self.log('   CBS: %s cleared of the fake rival (bots present)' % ASTEROIDS[aid]['name'])
                return self.starmap_msgs() + (self.refresh_assets(aid) if self.world and int(self.world.map_id) == int(ASTEROIDS[aid]['map'])
                                              else [])
            return []
        if a['state'] == 'building' or (a['state'] == 'built' and a.get('owner') != 'rival'):
            return []
        msgs = []
        if a['state'] == 'vacant':
            if 'rival' not in a:
                rnd = random.Random('%s-%s' % (aid, a.get('rival_round', 0)))
                if rnd.random() < D['rival']['probability']:
                    hours = rnd.uniform(*D['rival']['duration_hours'])
                    fac = self.faction() if self.host is None else 0          # in the shared record the rival's company is not relative to the player
                    a.update(rival=rnd.choice(D['rival']['clans']), rival_progress=0.0, rival_speed=1.0 / (hours * 3600),
                             rival_company=rnd.choice([f for f in (1, 2, 3) if f != fac] or [1]), rival_last=now)
                else:
                    a['rival'] = None
                self.mark()
            if a.get('rival'):
                slow = 0.5 if self.own_progress(aid, now) > 0 else 1.0          # the rival slows down if the player is building too
                a['rival_progress'] = min(1.0, a.get('rival_progress', 0) + (now - a.get('rival_last', now)) * a['rival_speed'] * slow)
                a['rival_last'] = now
                if a['rival_progress'] >= 1.0 and self.own_progress(aid, now) < 1.0:
                    msgs += self.rival_build(aid, a, now)
        elif a.get('owner') == 'rival':
            df = a.setdefault('deflector', {})
            active = bool(D['rival'].get('deflector_outside_prime') and not prime_time(now)
                          and now >= df.get('closed_until', 0))
            if bool(df.get('on')) != active:
                df['on'] = active
                self.bump(a)
                self.mark()
                msgs += self.deflector_visuals(aid, now)
            msgs += self.rival_repair(aid, a, now)
        return msgs

    def rival_repair(self, aid, a, now):
        """When the attack stops (passive_repair.gecikme_sn) the rival's live modules are repaired and their shields refill; if on the map, health bars
        every 5 s."""
        dt = min(5.0, max(0.0, now - a.get('last_repair', now)))
        a['last_repair'] = now
        po = D['passive_repair']
        if not dt or now - a.get('attack_at', 0) < po['delay_sec']:
            return []
        changed = []
        for s, y in a['slots'].items():
            mx = hp_max(y)
            ms = min(SET.I32, int(mx * D['shield_ratio']))
            if y['hp'] <= 0 or (y['hp'] >= mx and y['shield'] >= ms):
                continue
            y['hp'] = min(mx, y['hp'] + po['hp_sec'] * dt)
            y['shield'] = min(ms, y['shield'] + ms * 0.02 * dt)
            changed.append(int(s))
        if not changed:
            return []
        self.mark()
        w = self.world
        if not w or int(w.map_id) != int(ASTEROIDS[aid]['map']) or now < a.get('repair_notice', 0):
            return []
        a['repair_notice'] = now + 5
        return [c for c in (self.info_cmd(aid, s) for s in changed if s != DEFLECTOR) if c]

    def rival_build(self, aid, a, now):
        """The rival station: center (Hull, Deflector) and 8 satellites, level 0, independent of the player's modules."""
        free = [y['iid'] for y in a['slots'].values() if 'iid' in y]       # the player's uninstalled modules
        rnd = random.Random('%s-b' % aid)
        sats = ['module_ltm-lr', 'module_ltm-mr', 'module_ltm-hr', 'module_ram-la', 'module_ram-ma', 'module_repm-1', 'module_honm-1',
                'module_xpm-1']
        slots = {str(HULL): 'module_hulm-1', str(DEFLECTOR): 'module_defm-1'}
        for s in range(2, SLOTS):
            slots[str(s)] = sats[(s - 2) % len(sats)] if s < 4 else rnd.choice(sats[:5])
        slot_info = {}
        for s, loot in slots.items():
            hp = int(level_value(MODS[loot]['hp'], 0) * D['rival']['hp_multiplier'])      # single player: so one ship can destroy it
            slot_info[s] = dict(loot=loot, level=0, hp=hp, shield=int(hp * D['shield_ratio']), maximum=hp)
        for y in list(a['slots'].values()):            # shared: uninstalled modules to their owners
            self.give_back(y)
        with self.lock:
            a.update(state='built', owner='rival', slots=slot_info, founded=now, deflector={'on': True})
            a.pop('clan', None)
            self.bump(a)
            self.mark()
        self.log('   CBS: rival %s built the %s station (%d player modules to the inventory)' % (a['rival'], ASTEROIDS[aid]['name'], len(free)))
        msgs = [stm('msg_station_built', CLAN=a['rival'], STATION=ASTEROIDS[aid]['name'], MAP=H.name(ASTEROIDS[aid]['map']))] + self.starmap_msgs()
        if self.world and int(self.world.map_id) == int(ASTEROIDS[aid]['map']):
            msgs += self.refresh_assets(aid)
        return msgs

    def shielded(self, a):
        """The deflector is up and protects the station. Panel setting cbs_deflector off: other clans' deflectors don't (player request
        2026-11-02: destroy a station another clan has just built and build your own); one's own still does."""
        return bool((a.get('deflector') or {}).get('on')) and (SET.get('cbs_deflector') or self.mine(a))

    def rival_attackable(self, aid):
        a = self.ast(aid)
        return a.get('owner') == 'rival' and a['state'] == 'built' and not self.shielded(a)

    def hit_asset(self, asset, dmg):
        """The player's hit on the rival station (entity id) -> messages."""
        aid, slot = self.asset_slot(asset)
        if aid is None:
            return []
        return self.asset_attackable(asset) or self.asset_hit(asset, dmg)

    # ------------------------------------------------------------ the world's asset_targets interface (world.select/laser_start/asset_laser)
    @staticmethod
    def asset_slot(uid):
        try:
            uid = int(uid or 0)
        except (TypeError, ValueError, OverflowError):
            return None, None
        aid = (uid - ASSET_BASE) // 100
        slot = uid - ASSET_BASE - aid * 100
        return (aid, slot) if aid in ASTEROIDS and 0 <= slot < SLOTS and slot != DEFLECTOR else (None, None)

    def asset_module(self, uid):
        """Current-map live installed module, resolved from its owner store."""
        aid, slot = self.asset_slot(uid)
        w = self.world
        if aid is None or not w or int(w.map_id) != int(ASTEROIDS[aid]['map']):
            return None
        a = self.ast(aid)
        y = a['slots'].get(str(slot)) if a['state'] == 'built' else None
        m = (y if a.get('owner') == 'rival' else self.module(y.get('iid'))) if y else None
        return m if m and m.get('hp', 0) > 0 else None

    def asset_pos(self, uid):
        """Selection is available for friendly and shielded assets too."""
        if not self.asset_module(uid):
            return None
        aid, slot = self.asset_slot(uid)
        return position(aid) if slot == HULL else satellite_pos(aid, slot)

    def asset_select(self, uid):
        m = self.asset_module(uid)
        if not m:
            return []
        aid, slot = self.asset_slot(uid)
        # Native BuildSelect consumes AssetInfo, not the ship-only selection handler.
        return [self.info_cmd(aid, slot, m)]

    def asset_attackable(self, uid):
        """[] if hittable; otherwise the client's warning (own clan's station, same company allegiance, deflector on)."""
        aid, slot = self.asset_slot(uid)
        if self.asset_module(uid):
            a = self.ast(aid)
            denied = self.attack_denied(a)
            if denied:
                return [legacy('0|A|STM|' + denied)]
            if not self.shielded(a):
                return []
        return [legacy('0|A|STM|msg_station_not_atackable')]

    def asset_hit(self, uid, dmg):
        return self.asset_damage(uid, dmg, atype=1)

    def assets_near(self, x, y, r):
        """Ids of the hittable modules on this map closer than r units to (x, y) (P.E.T. kamikaze: pet.kamikaze)."""
        out = []
        for aid in ASTEROIDS:
            for slot in range(SLOTS):
                uid = ASSET_BASE + aid * 100 + slot
                pos = self.asset_pos(uid) if slot != DEFLECTOR else None
                if pos and math.hypot(pos[0] - x, pos[1] - y) <= r and not self.asset_attackable(uid):
                    out.append(uid)
        return out

    def asset_damage(self, uid, dmg, atype=0, shield_only=False, hull_only=False, attacker=None):
        denied = self.asset_attackable(uid)
        if denied:
            return denied
        aid, slot = self.asset_slot(uid)
        a = self.ast(aid)
        a['attack_at'] = time.time()
        a['aggro'] = {u: t for u, t in (a.get('aggro') or {}).items() if a['attack_at'] - t < AGGRO_SEC}
        a['aggro'][str(self.p.user_id)] = a['attack_at']                    # whoever shot it is its enemy ("All" stations: shoots_at)
        if a.get('owner') == 'bot':                     # a bot clan knows who hit it (defense, grudge: clan_stations); destruction reward
            a.update(last_player=a['attack_at'], last_attacker=self.p.d['pilot'].get('userName', ''), last_attacker_clan=self.clan_name())
        hit_module = self.asset_module(uid)
        hp_before, shield_before = hit_module['hp'], hit_module['shield']
        msgs = self.damage_module(aid, slot, dmg, self.clan_name(), shield_only=shield_only, hull_only=hull_only, dealer=KL.name(self.p))
        w = self.world
        if w is not None:
            w.last_shield_hit = shield_before - hit_module['shield']
        # AssetInfo invokes BuildSelect -> UnitDeselect on every hit, clearing
        # ShipInfo.IsAtk and making a moving hero face its route instead of the target.
        # AttackHit updates Entity numeric values and emits the floating damage number.
        msgs = [(name, fields) for name, fields in msgs if name != 'AssetInfoCommand']
        amount = int(hp_before - hit_module['hp'] + shield_before - hit_module['shield'])
        hit = ('AttackHitCommand', dict(attackType=world_module.attack_type(atype), attackerId=attacker if attacker is not None else w.hid if w else self.p.user_id,
            victimId=int(uid), victimHitpoints=int(hit_module['hp']), victimShield=int(hit_module['shield']),
            victimNanoHull=0, damage=amount, skilled=atype == 1, strike=False, cannonType=0))
        bar = ('AttackHitAssetCommand', dict(assetId=int(uid), hitpointsNow=int(hit_module['hp']),
            hitpointsMax=hp_max(hit_module)))
        if self.host is not None and w is not None and w.shared is not None:
            for o in list(w.shared.members):
                if o is not w and o.running and o.target == uid:
                    o.deliver([hit, bar])
        return [hit, bar] + msgs

    def rival_fire(self, now):
        """A built station's weapons (rival, bot clan or another player's clan) deal full module damage to a player in range that the station
        sees as an enemy (shoots_at: other company, clan at war; same company without war never; player report 2026-11-04: a same-company
        station fired at a clanless player) (rival.damage_multiplier default 1.0). The deflector only makes the
        station invulnerable, the weapons still fire (fandom Clan Battle Stations: after building "the module will start to attack"); a cloaked ship
        is not targeted (player report 2026-10-30: it fired only while the deflector was off and without regard to cloaking). Cause of death on the
        death screen BATTLESTATION; laser/rocket use their own attack type."""
        w = self.world
        if not w or w.hero_dead or getattr(w, 'jumping', False):
            return []
        hx, hy = w.hero_pos(now)
        cloaked = w.hidden(now)
        for aid in BY_MAP.get(int(w.map_id), []):
            a = self.ast(aid)
            rival = a.get('owner') == 'rival'
            if a['state'] != 'built' or not self.shoots_at(a, now):
                continue                                # any clan's station (bot clan or player) fires at its enemies (official FAQ)
            tag = a.get('rival', '') if rival else (self.st_clan(a) or {}).get('tag', '')
            for s, slot_info in list(a['slots'].items()):
                y = slot_info if rival else slot_info.get('module')
                if not y:
                    continue
                md = MODS[y['loot']]
                if not md.get('weapon') or y['hp'] <= 0 or w.hero_dead:
                    continue
                sx, sy = satellite_pos(aid, int(s))
                key = ('rival', aid, int(s))
                if now < self.next_shot.get(key, 0):
                    continue
                candidates = []
                distance = math.hypot(sx - hx, sy - hy)
                if distance <= md['range'] and not cloaked:
                    candidates.append((distance, 0, w.hid, None))
                pet = getattr(w, 'pet', None)
                if pet and pet.active and pet.alive and pet.w is w and not pet.hidden(now):   # cloaked with its owner (unless firing)
                    px, py = pet.pos(now)
                    distance = math.hypot(sx - px, sy - py)
                    if distance <= md['range']:
                        candidates.append((distance, 1, pet.pid, pet))
                if not candidates:
                    continue
                _, _, target_uid, target_pet = min(candidates, key=lambda row: row[:2])
                self.next_shot[key] = now + md['interval_sec']
                uid = asset_id(aid, int(s))
                defense = {} if target_pet else self.p.mods()
                evasion = max(0.0, min(1.0, target_pet.proto('evasion') if target_pet else defense.get('evasion', 0)))
                hit = random.random() < md['hit'] * (1 - evasion)
                atype = 0 if md['weapon'] == 'rocket' else 1
                laser_factor = max(0.0, 1 + defense.get('laser_taken', 0)) if atype == 1 else 1.0
                visual = self.weapon_visual(md, uid, target_uid, hit)
                if atype == 1:
                    visual[1]['isDiminishedBySkillShield'] = laser_factor < 1 or (not target_pet and w.skill_shield())
                w.send([visual])
                if hit:
                    dmg = int(round(dmg_value(md, y['level']) * D['rival']['damage_multiplier'] * laser_factor))
                    if target_pet:
                        actual = target_pet.station_hit(dmg, uid, atype=atype, now=now)
                    else:
                        who = types.SimpleNamespace(id=uid, alive=False, d={'name': '%s [%s]' % (md['code'], tag)})
                        g = self.p.d['ship']
                        before = g.get('hitPoints', 0) + g.get('shield', 0) + g.get('nanoHull', 0)
                        w.send(w.hurt_hero(dmg, killer=who, atype=atype, cause=DESTRUCTION_BATTLESTATION, now=now, source_asset=True))
                        actual = before - g.get('hitPoints', 0) - g.get('shield', 0) - g.get('nanoHull', 0)
                    if actual > 0:
                        w.last_asset_attacker = (uid, now)
                else:
                    w.send([('AttackMissedCommand', dict(attackType=world_module.attack_type(atype), targetUserId=target_uid, skillColorId=0))])
        return []

    # ------------------------------------------------------------ clan tab and log
    def log_of(self, cid=None):
        """The station log: in the profile in single player, in the clan's record in the shared record (cid; the player's clan if not given)."""
        if self.host is None:
            return self.st['daily']
        k = KL.CLANS.get(cid) if cid else self.clan()
        return k.setdefault('cbs_log', []) if k is not None else []

    def note(self, aid, kind, **values):
        a = ASTEROIDS[aid]
        e = dict(type=kind, date=stamp(), stationId=aid, stationName=a['name'], mapName=H.name(a['map']),
                 userName=values.pop('userName', ''), opponentClanName=values.pop('opponentClanName', ''),
                 buildSeconds=int(values.pop('buildSeconds', 0)), values=json.dumps(values) if values else '{}')
        b = self.ast(aid)
        g = self.log_of(b.get('clan') if b.get('owner') != 'rival' else None)
        with self.lock:
            g.insert(0, e)
            del g[200:]
            self.mark()
        if self.host is not None:
            KL.save()

    def clan_info(self):
        st = self.st
        k = self.clan()
        ist = self.stats({'clan': k['id']} if k else {}) if self.host is not None else st['stats']
        rows = []
        for aid_s, a in sorted(self.asteroids.items(), key=lambda kv: int(kv[0])):
            if a.get('state') not in ('built', 'building') or not self.mine(a):
                continue
            aid = int(aid_s)
            df = a.get('deflector') or {}
            has_def = any(int(s) == DEFLECTOR for s in a['slots'])
            rows.append(mod('BattleStationOverviewInfoCommand', stationName=ASTEROIDS[aid]['name'], xpBonus=float(self.booster_pct(aid, 'ep')),
                            timerCounter=max(0, int(a.get('build_end', 0) - time.time())) if a['state'] == 'building' else 0,
                            deflectorDownTime=max(0, int(df.get('closed_until', 0) - time.time())),
                            damageBonus=float(self.booster_pct(aid, 'damage')), defStatus=bool(df.get('on')),
                            hasDeflectorModul=has_def, deflectorIsActive=bool(df.get('on')), deflectorTime=int(df.get('sec', 0)),
                            allModuleCount=len(a['slots']), mapName=H.name(ASTEROIDS[aid]['map']), buildCompleted=a['state'] == 'built',
                            maxAmountOfModule=SLOTS, honourBonus=float(self.booster_pct(aid, 'honor')), stationId=aid))
        longest = max(ist.get('longest_sec', 0), max([int(time.time() - a.get('founded', time.time())) for a in self.asteroids.values()
                                                     if a.get('state') == 'built' and self.mine(a)] or [0]))
        return ('ClanBattleStationInfoCommand', dict(battleStationOverviewInfoCommands=rows,
                                                     stationOwnedLongestTime=str(int(longest)),     # seconds (the client formats)
                                                     maxStationAtOnce=int(ist.get('max_count', 0)), destroyedStations=int(ist.get('demolished', 0)),
                                                     stations=len(rows), allStations=int(ist.get('all', 0))))

    USER_KINDS = ('BUILD_START', 'DEFLECTOR_ON', 'EMERGENCY_REPAIR', 'MODULE_REPLACED', 'MODULE_REMOVED')

    def history_row(self, e):
        """A log line to the client: every field of values is text (the client's GetLogMessage converts to string: a number cuts the list with
        InvalidCastException - live test), level from 1; for things the player did, the name (%USERNAME% in the text)."""
        e = dict(e)
        try:
            v = json.loads(e.get('values') or '{}')
        except ValueError:
            v = {}
        e['values'] = json.dumps({k: str(int(x) + 1) if k.endswith('Level') and isinstance(x, (int, float)) else str(x)
                                  for k, x in v.items()})
        if e['type'] in self.USER_KINDS and not e.get('userName'):
            e['userName'] = self.p.d['pilot'].get('userName', '')
        return mod('BattleStationHistoryInfoCommand', **e)

    def history(self, start):
        g = self.log_of()
        rows = [self.history_row(e) for e in g[start:start + 20]]
        return ('BattleStationHistoryListCommand', {'commandList': rows, 'startIndex': start, 'total': len(g)})

    # ------------------------------------------------------------ GM console
    def gm(self, rows, d):
        """battleStation: buildTime (finish building / installations), modules (a set of modules), accept (build the asteroid next to you),
        deflector (on/off), raid (raid), rival (build the rival station)."""
        what = str(d.get('option') or d.get('name') or (rows[0] if rows else '')).strip().lower()
        msgs = []
        if 'module' in what:
            for loot in MODS:
                n = 8 if MODS[loot]['max_count'] > 1 else 1
                self.p.add_resource(loot, n)
            self.st
            msgs.append(GALAXY.screen('GM: module set added to the inventory'))
        aid = self.near
        if aid and ('build' in what or 'accept' in what):
            a = self.ast(aid)
            for y in a['slots'].values():
                y['install_end'] = 0
            if a['state'] == 'building' or 'accept' in what:
                a['build_end'] = 0
                if a['state'] == 'vacant':
                    a.update(state='building', build_sec=60)
            msgs.append(GALAXY.screen('GM: construction finished'))
        if aid and 'deflector' in what:
            df = self.ast(aid)['deflector']
            df['on'] = not df.get('on')
            df['closed_until'] = 0 if df['on'] else time.time() + 3600
            df['sec'] = max(df.get('sec', 0), 3600) if df['on'] else df.get('sec', 0)
            df['last'] = time.time()
            self.bump(self.ast(aid))
            self.mark()
            msgs += self.near_status(aid, df['last'])
        if aid and 'raid' in what:
            msgs += self.spawn_raid(aid)
        if aid and 'rival' in what:
            a = self.ast(aid)
            if a['state'] in ('built', 'building') and a.get('owner') != 'rival':
                msgs.append(GALAXY.screen('GM: your own station is here'))
            else:
                a.update(rival=D['rival']['clans'][0], rival_progress=1.0, rival_company=1 if self.faction() != 1 else 2)
                msgs += self.rival_build(aid, a, time.time())
        self.p.dirty = True
        return msgs or [GALAXY.screen('GM battleStation: modules | build | accept | deflector | raid | rival')]


# ------------------------------------------------------------ the bot clans' race (bot/clan_stations.py)
def race_leader(a):
    """The leading one among the bot clans racing on an empty asteroid: (clan's name, progress 0-1) or None."""
    en = None
    for cid, r in (a.get('race') or {}).items():
        k = KL.CLANS.get(int(cid))
        p = len(r.get('modules') or ()) / float(SLOTS)
        if k is not None and p > 0 and (en is None or p > en[1]):
            en = (k['name'], p)
    return en


def refund_race(cid, modules):
    """The modules of the bot clan that lost (or quit) the race on the asteroid go to the clan's stock (k['ksi']['stok'])."""
    k = KL.CLANS.get(int(cid))
    if k is None or not modules:
        return
    with KL.LOCK:
        k.setdefault('cbs', {}).setdefault('stock', []).extend(modules)


def bot_build(aid, k, modules, minutes, log=print):
    """The bot clan that finished the race starts building the station: modules into the slots (owner clan: '@klan:<id>'; when destroyed they return
    as pending, clan_stations takes them into stock), the modules of a player who fitted modules to the asteroid to their owner, those of the
    other bot clans to their stocks. -> whether it started."""
    h = shared()
    if h is None:
        return False
    c = Cbs(h, None, log)
    a = c.ast(aid)
    if a['state'] != 'vacant':
        return False
    now = time.time()
    old = list(a['slots'].values())
    with h.lock:
        d = h.d['cbs']
        slot_info, satellite = {}, iter(range(DEFLECTOR + 1, SLOTS))
        for m in modules:
            md = MODS[m['loot']]
            s = (HULL if md['type'] == 2 else DEFLECTOR) if md['center'] else next(satellite, None)
            if s is None or str(s) in slot_info:
                continue
            d['shared_seq'] = int(d.get('shared_seq', 0)) + 1
            slot_info[str(s)] = {'iid': SHARED_ITEM + d['shared_seq'], 'module': m, 'owner': '@klan:%d' % k['id'], 'owner_name': k['tag'],
                          'install_end': now, 'install_sec': 0, 'installed': True}
        others = {cid: r.get('modules') or [] for cid, r in (a.get('race') or {}).items() if int(cid) != k['id']}
        a.update(state='building', build_end=now + minutes * 60, build_sec=minutes * 60, owner='bot', clan=k['id'], slots=slot_info)
        for f in ('race', 'rival', 'rival_progress'):
            a.pop(f, None)
        d['bot_clans'] = True
        c.bump(a)
        h.dirty = True
    for y in old:
        c.give_back(y)
    for cid, mods in others.items():
        refund_race(cid, mods)
    c.note(aid, 'BUILD_START', buildSeconds=minutes * 60)
    log('   CBS: [%s] %s is building the station (%d min)' % (k['tag'], ASTEROIDS[aid]['name'], minutes))
    return True


def bot_demolish(aid, reason='clan disbanded', log=print):
    """A disbanded bot clan's station is destroyed (as clan.Clan.delete does when a player's clan is disbanded)."""
    h = shared()
    if h is not None:
        Cbs(h, None, log).destroy(aid, reason)
