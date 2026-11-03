"""Player profile: the active save slot's profile.json (save/slots/<slot>/, paths.py; the panel passes it with --profile; in the old layout
save/profile.json). The core commands sent on login are produced from here,
the client's setting/window/movement requests are written here (kept when the client is closed and reopened).

On first run the profile is built from the "seed" in data/login.json (from the recording's login commands); if there is no seed, a default pilot.
Field names are the same as the protocol's, so the profile turns directly into a message.
"""
import json, os, threading, time
MODE_WINDOWS = ('voyagers', 'trinityTrials', 'expedition', 'eternal_blacklight', 'rogue_lite')     # feature bar (stage 8)
# event window -> the calendar's events (visible while one runs; live test H47). Plutus: PlutusInfoCommand; labyrinth:
# FrozenLabyrinthInfoCommand; Agatus and NPC events: the indicator of event_maps.py (the 'info' command in events.json)
EVENT_WINDOWS = {'plutus': ('plutus',), 'frozen_labyrinth': ('labyrinth',), 'agatus_event': ('agatus',), 'npc_event': None,
                 'chrominEvent': ('chromin',), 'word_puzzle': ('hitac',), 'titleFrenzy': ('title_hunt',),        # stage 3
                 'space_search': ('galaxy_trek',), 'birthday_2025': ('fiesta',), 'infiltration': ('infiltration',),
                 'miniclient_reward': None,
                 'invasion': ('invasion',), 'ship_boost_event': ('fever',), 'diminish_quests': ('urgent_quests',),
                 'strikeAndExit': ('vortex_of_greed',), 'publicWorldBoss': ('world_boss',), 'payload_escort': ('mimesis_mutiny',),  # stage 4
                 'mileageMarket': ('mileage_market',), 'vipMerchantExchange': ('vip_merchant',),                            # stage 7
                 'preBlackFridaySales': ('pre_prometheus',), 'return_of_hero': ('return_of_hero',), 'returnee_login': (),
                 'apotheosis': ('kristallon_apotheosis',), 'recallBattlePass': ('return_of_hero',),                        # 1.1.115
                 'battle_pass': ()}      # Objectives: while the save's pass runs (battle_pass.py; the session binds the hook), otherwise it opened empty
# the 1.1.115 windows are not in the interface in the recording: added to the profile as a copy of the Return of Hero item (title, size from game.xml);
# before opening a window the client looks up the menu item by name (FeatureMenuHelper.GetFeatureItemById)
NEW_WINDOWS = {'apotheosis': ('title_kristallon_apotheosis', 728, 460), 'recallBattlePass': ('return_pass_name', 800, 440)}
# those whose visibility comes from the player's state, not the calendar: itemId -> () -> bool (stage 7: the Returnee Login campaign, stores.py)
WINDOW_HOOKS = {}
# the client opens the Urgent Missions window (diminish_quests) itself when a quest arrives (DiminishingQuestHandler.OpenWindow); if the item is not
# visible in the menu it is not in the client's dictionary and cannot be opened (KeyNotFound). Because of maximized in the template it opened empty on login:
# on login it is always sent closed (live round stage 3)
CLOSED_AT_LOGIN = {'diminish_quests'}
# items whose own system reports their visibility while the game runs (not sent separately on a calendar change): Urgent Missions is visible only while there is
# a quest, the icon in the client's menu is tracked by urgent_quests.py (user 2026-10-18)
OWN_SYNC = {'diminish_quests'}
INDICATOR_WINDOWS = {'AgatusEventInfoCommand': 'agatus_event', 'NpcEventInfoCommand': 'npc_event'}
# never shown in the menu: R-Zone (PvP, with bot players; its requests go unanswered). Stellar Pathfinder cannot be hidden: on login the client
# (UIMainCenterNewSystem.ShowMenuList) looks up the "hangar", "stellar_pathfinder" and "vouchers" items by name, and if an item is missing
# the login does not complete with a KeyNotFoundException (live test stage 1); the client sets its visibility by level itself
HIDDEN_WINDOWS = ('rzone',)


def window_events(item_id):
    """The calendar events the event window is tied to (npc_event / agatus_event: those whose indicator is that command)."""
    import event_calendar as CAL
    keys = EVENT_WINDOWS.get(item_id)
    if keys is not None:
        return keys
    if item_id == 'miniclient_reward':       # Mini Client reward: those with MiniClientReward in their types (daily_rewards.py; it would open empty otherwise)
        return tuple(k for k, e in CAL.EVENTS.items() if 'MiniClientReward' in e.get('kinds', []))
    return tuple(k for k, e in CAL.EVENTS.items() for s in ([e['map']] if 'map' in e else []) + e.get('map_extra', [])
                 if INDICATOR_WINDOWS.get((s.get('info') or {}).get('command')) == item_id)


def event_window_visible(item_id, now=None, hooks=None):
    """hooks: the profile's own hooks (Profile.window_hooks; on a friend server each player's session binds its own)."""
    import event_calendar as CAL
    for hk in (hooks or {}, WINDOW_HOOKS):
        if item_id in hk:
            return bool(hk[item_id]())
    return any(CAL.is_active(k, now) for k in window_events(item_id))

import booster as BOOSTER

_STACK = None


def stack_cap(loot):
    """The client's item stack limit (client_items.json stack; close to 2^63 counts as 'unlimited') or None."""
    global _STACK
    if _STACK is None:
        K = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'client_items.json'), encoding='utf8'))
        _STACK = {k: int(v['stack']) for k, v in K['items'].items() if isinstance(v, dict) and 0 < (v.get('stack') or 0) < 10 ** 12}
    return _STACK.get(loot)
import skill_tree as SKILL
import ship_ability as SA
import lasers as LASERS
import combat_items as CIT
import extras as EX
import ranks as RT
import technology as TECH
import bank as BANK
import map_links as H
import paths as PTH
import save_migration as SM

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(HERE, 'save', 'profile.json')     # old layout; active slot: paths.profile_path()

PILOT_FIELDS = ('userId', 'userName', 'factionId', 'clanId', 'clanTag', 'level', 'ep', 'honourPoints', 'credits', 'uridium', 'premium',
                'dailyRank', 'galaxyGatesDone', 'expansionStage', 'jackpot', 'useSystemFont', 'captainEnergy', 'maxCaptainEnergy')
SHIP_FIELDS = ('typeId', 'speed', 'shield', 'shieldMax', 'hitPoints', 'hitMax', 'nanoHull', 'maxNanoHull', 'cargoSpace', 'cargoSpaceMax',
               'cloaked', 'modifier')
# the client's setting requests -> the module inside UserSettingsCommand
SETTINGS_REQUESTS = {'GameplaySettingsRequest': 'gameplaySettingsModule', 'DisplaySettingsRequest': 'displaySettingsModule',
                     'AudioSettingsRequest': 'audioSettingsModule', 'QualitySettingsRequest': 'qualitySettingsModule',
                     'QuestSettingsRequest': 'questSettingsModule', 'WindowSettingsRequest': 'windowSettingsModule'}
WINDOW_KEYS = ('posX', 'posY', 'width', 'height', 'maximized')
# GameplaySettingsModule in the recording (notSet: the player has not saved yet)
GAMEPLAY_DEFAULTS = {'autoBoost': True, 'autoRefinement': True, 'quickslotStopAttack': True, 'doubleclickAttack': True,
                     'autoChangeAmmo': True, 'autoStart': True, 'autoBuyGreenBootyKeys': False}
# premium shortcut bars: the recording is of a non-premium account, the template has only standardSlotBar. The client builds every bar from MenuInitializationCommand
# (ItemMenuMenuInitialization.ParseSlotBars, slot 1-10); without it the Pro Action Bar button shows but the bar does not open (H81). The position is
# "percent x,y|offset x,y": when the offset is 0,0 the client uses the percent position (UIBagSystem.SetInitSlotBarPosition); once dragged,
# slotmenuPremiumPosition / slotmenuProActionPosition in WindowSettingsRequest take effect.
PREMIUM_SLOT_BARS = (('premiumSlotBar', '50,79.5|0,0'), ('proActionBar', '50,73.5|0,0'))   # above the open category list
# Interface configuration (Settings > Interface): when bars are dragged the client sends their positions with WindowSettingsRequest
# (FeatureMenuHelper.SendWindowSettingsRequest: categoryBar, three shortcut bars, gameFeaturesBar, genericFeaturesBar; "x,y" percent and the
# layout order). On login the client builds the bars only from UILayoutCommand (FeatureBarVo.Init: featureBarPosition, featureBarOrder) and
# MenuInitializationCommand (ParseSlotBars: slotBarPosition "x,y|offset", slotBarOrder = WindowConstants.LayoutsMap order 0-5;
# itemBarPosition): if the saved positions are not written there, on every login they went back to their places in the template (user, 2026-10-18).
# Offset 0,0 on a shortcut bar: the client uses the percent position (UIBagSystem.SetInitSlotBarPosition). The new feature bar (type 3) is
# not in the request: in the configuration it moves with the game bar, and in the recording it comes at the same position as it (position from it, layout from the template).
FEATURE_BAR_KEYS = {1: ('gameFeatureMenuPosition', 'gameFeatureMenuOrder'), 2: ('genericFeatureMenuPosition', 'genericFeatureMenuOrder'),
                    3: ('gameFeatureMenuPosition', None)}
SLOT_BAR_KEYS = {'standardSlotBar': ('slotmenuPosition', 'slotMenuOrder'),
                 'premiumSlotBar': ('slotmenuPremiumPosition', 'slotMenuPremiumOrder'),
                 'proActionBar': ('slotmenuProActionPosition', 'slotMenuProActionOrder')}
LAYOUT_COUNT = 6                    # WindowConstants.LayoutsMap (Horizontal/Vertical List/Grid, ProAction Horizontal/Vertical Grid)
# shortcut items tied to equipment (CPUs, Smart Bomb, launcher, ship abilities): refreshed after fitting/removing (menu_changes)
# "Double click to buy" in the item bar tooltip of the quick-buy item (recording: the last line of toolTipItemBar; not on the shortcut bar)
QUICK_BUY_TIP = {'_': 'MessageKeyListWildcardModule', 'wildCardReplacements': [], 'baseKey': 'ttip_quick_buy_itembar',
                 'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 5}, 'textStyle': 0}
EQUIP_MENUS = ('equipment_extra_', 'ability_', 'equipment_weapon_rocketlauncher_', 'ammunition_rocketlauncher_', 'ammunition_mine_smb-01')
DESIGN_KEYS = {'design': 'design', 'visual': 'appearance'}     # the drone's design slots -> the key in the ship's drone_design record

_LEVELS = None
_ITEMS = None


def item():
    global _ITEMS
    if _ITEMS is None:
        _ITEMS = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
    return _ITEMS


_EVENT_OPEN = {}          # calendar key -> (time queried, is it open)


def event_on(key, now=None):
    """Is the calendar event open now. Since it is called on the hot path of mods() (a calendar query ~60 µs) the result is kept for 30 s."""
    now = now or time.time()
    t = _EVENT_OPEN.get(key)
    if not t or now - t[0] > 30 or now < t[0]:
        import event_calendar as CAL
        t = _EVENT_OPEN[key] = (now, CAL.is_active(key, now))
    return t[1]


def _layout_ok(v):
    """Is the layout order the client sent valid (0-5; the client reads the order from an array, outside it is IndexOutOfRange)."""
    return isinstance(v, (str, int)) and str(v).isdigit() and int(v) < LAYOUT_COUNT


def _formations():
    return item()['formations']


def lab_data():
    return item()['lab']


def formation_id(loot_id):
    """Formation lootId -> the client's formation id (data/items.json formations; game.xml <formations>)."""
    f = _formations().get(loot_id)
    return f['id'] if f else None


def formation_drones_ok(p, loot_id):
    """Are there enough drones for the formation (Arrow and Dome 4, Heart and Pincer 6: formations.min_drones; wiki)."""
    return len(p.d['drones']) >= item()['formation_rules'].get(loot_id, {}).get('min_drones', 0)


def formation_loot(fid):
    return next((k for k, v in _formations().items() if v['id'] == fid), 'drone_formation_default')


def level_for(ep):
    global _LEVELS
    if _LEVELS is None:
        import game_data as DATA           # World Editor: level thresholds
        _LEVELS = DATA.load('levels.json')['levels'] if os.path.exists(os.path.join(HERE, 'data', 'levels.json')) else [[1, 0]]
    lv = 1
    for level, need in _LEVELS:
        if ep >= need:
            lv = level
    return lv


DEFAULT_SHIP_INIT = dict(userId=1, userName='Pilot', typeId='ship_goliath', speed=300, shield=100000, shieldMax=100000, hitPoints=356000,
                         hitMax=356000, cargoSpace=0, cargoSpaceMax=1500, x=2000, y=2000, mapId=1, factionId=1, expansionStage=3, premium=True,
                         ep=100000, honourPoints=1000, level=12, credits=1000000, uridium=50000, dailyRank=1, refreshMap=True, modifier=[])


def refine_ores(have, recipes):
    """Auto-refining's outcome on {ore type: count} with recipes [(product, {input: count})] (world.auto_refine, bot cargo boxes): one unit
    at a time in turn, so the shared Endurium is split between the two products and new Prometid/Duranium goes into Promerium.
    -> (counts after refining, {product: units made})"""
    have, made, more = dict(have), {}, True
    while more:
        more = False
        for t, r in recipes:
            if all(have.get(k, 0) >= v for k, v in r.items()):
                for k, v in r.items():
                    have[k] -= v
                have[t] = have.get(t, 0) + 1
                made[t] = made.get(t, 0) + 1
                more = True
    return have, made


def cargo_take(cargo, want, capacity, recipes=()):
    """How much of a cargo box to take: cargo {ore type: count} now, want {ore type: count} in the box, capacity the cargo area, recipes
    auto-refining's (none: the setting is off) -> {ore type: count taken} that fits once refined. Not in key order: 1,500 Prometium filled
    the cargo first and the Endurium/Terbium that would have refined it stayed on the ground (user report 2026-11-03). The largest equal
    share of every ore that fits, then each type topped up while it still fits (twice: Endurium taken late lets more Prometium in).
    Xenomit takes no space: all of it (it is also Promerium's input)."""
    space = sorted(t for t in want if t in Profile.CARGO_ORES and want[t] > 0)
    take = {t: n for t, n in want.items() if t not in Profile.CARGO_ORES}

    def fits(extra):
        have = dict(cargo)
        for t, n in list(take.items()) + list(extra.items()):
            have[t] = have.get(t, 0) + n
        have = refine_ores(have, recipes)[0] if recipes else have
        return sum(n for t, n in have.items() if t in Profile.CARGO_ORES) <= capacity

    def largest(lo, hi, extra):
        """The largest x in [lo, hi] with fits(extra(x)); lo fits. The space is not monotone (more Endurium can refine the Prometium
        down), so only what was checked is taken."""
        if fits(extra(hi)):
            return hi
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if fits(extra(mid)) else (lo, mid)
        return lo

    if not space or not fits({}):
        return take
    top = max(want[t] for t in space)
    share = largest(0, top, lambda s: {t: want[t] * s // top for t in space})
    got = {t: want[t] * share // top for t in space}
    for _ in range(2):
        for t in space:
            got[t] = largest(got[t], want[t], lambda n: {**got, t: n})
    take.update({t: n for t, n in got.items() if n > 0})
    return take


class Profile:
    # single-player rule: everyone is Premium (the account in the recording was not; H72). Its advantages from the client's texts: rocket cooldown halved and
    # repair robot x2 (world), P.E.T. repair free (pet), exit 5 s (game.LOGOUT_SEC). Ship repair at the panel's repair price.
    premium = True
    # ores counted toward cargo: the client's total (UnitAttributeOreCountUpdate.UpdateHeroCargo: Prometium ... Palladium and Osmium).
    # Xenomit (3) stays in cargo, takes no space (user report 2026-10-24: 1,500 Xenomit filled the cargo)
    CARGO_ORES = frozenset((0, 1, 2, 4, 5, 6, 7, 8, 28))

    def __init__(self, seed=None, path=None, d=None):
        """d: not from a file but from this dict (on a friend server the save a guest sent; multiplayer.GuestProfile)."""
        self.path = path = path or PTH.profile_path()
        self.lock = threading.Lock()
        self.dirty = False
        self.ach = lambda kind, **kw: []      # achievement events (achievement.py; the session binds it). Not called while holding the profile lock
        self.hint = lambda kind: []           # hint window once (tips.py; the session binds it) -> messages
        self.window_hooks = {}                # visibility of a menu item (event_window_visible; the session binds it)
        self.seed = seed or {}
        created = d is None and not os.path.exists(path)
        if d is not None:
            self.d = d
        elif not created:
            self.d = SM.migrate_obj(json.load(open(path, encoding='utf8')))   # old-format profile (imported, --profile=...)
        else:
            self.d = self._from_seed(self.seed)
            self.dirty = True
        self._migrate()
        self.menu_status_cache = {}      # menuItemId -> MenuItemStatusCommand in the template (for counter updates)
        self.menu_sent = {}              # menuItemId -> the state last reported to the client (menu_changes compares)
        self.cpu_init_sent = None        # the last CPUInitializationCommand (resent when AJP-01 is fitted/removed: menu_changes)
        self.daily_fields = None         # fields of the daily login calendar (login_calendar.py; the session binds it)
        if self.dirty and created:
            # only a new profile is written immediately (web.py reads it on login). Migrations of an existing file are written with the game's usual save (10 s):
            # loading does not change the file (when tests loaded the game module the user's save was rewritten; live test H72)
            self.save()

    # ---------------------------------------------------------------- setup
    @staticmethod
    def _from_seed(t):
        si = dict(DEFAULT_SHIP_INIT)
        si.update(t.get('ShipInitializationCommand') or {})
        d = {
            'version': 1,
            'created': time.strftime('%Y-%m-%d %H:%M:%S'),
            'pilot': {k: si.get(k) for k in PILOT_FIELDS if k in si},
            'ship': {k: si.get(k) for k in SHIP_FIELDS if k in si},
            'position': {'mapId': si['mapId'], 'x': si['x'], 'y': si['y']},
            'ores': (t.get('AttributeOreCountUpdateCommand') or {}).get('oreCountList', []),
            'formation': (t.get('DroneFormationChangeCommand') or {}).get('selectedFormationId', 0),
            'settings': t.get('UserSettingsCommand') or {},
            'key_bindings': (t.get('UserKeyBindingsUpdate') or {}).get('changedKeyBindings', []),
            'ui': t.get('UILayoutCommand') or {'featureBars': []},
        }
        # copy: when the seed's dicts were shared, the profile's changes (settings, interface, keys) also passed to the next new profiles opened in the same
        # process (the seed is from the game's template, a single object)
        return json.loads(json.dumps(d))

    def _migrate(self):
        """Adds the new sections to old profiles from the seed (equipment, ammo, selected ammo, item ids)."""
        t = self.seed
        if 'equipment' not in self.d:
            self.d['equipment'] = t.get('equipment') or {'laser': ['equipment_weapon_laser_lf-1'], 'generators': [], 'extra': [], 'rocket': []}
            self.dirty = True
        if not self.d.get('ammo_seeded'):
            got = self.d.get('ammunition', {})          # those coming from bonus boxes are added on top of the seed
            base = dict(t.get('ammunition') or {'ammunition_laser_lcb-10': 1000, 'ammunition_rocket_r-310': 20})
            for k, v in got.items():
                base[k] = base.get(k, 0) + v
            self.d['ammunition'], self.d['ammo_seeded'] = base, True
            self.dirty = True
        for k in [k for k in self.d.get('ammunition', {}) if k.startswith('resource_')]:
            # the resources in the World Editor's bonus box (ABR ...) were written to ammo (player report 2026-10-30): to storage
            n = self.d['ammunition'].pop(k)
            if n > 0:
                d = self.d.setdefault('other_items', {})
                d[k] = d.get(k, 0) + n
            self.dirty = True
        for k, default in (('selected', {'laser': 'ammunition_laser_lcb-10', 'rocket': 'ammunition_rocket_r-310'}), ('item_id', {})):
            if k not in self.d:
                self.d[k] = json.loads(json.dumps(t.get(k) or default))     # copy: the seed is not shared between profiles
                self.dirty = True
        if 'configs' not in self.d and 'ships' not in self.d:
            # hangar: owned equipment instances (itemId -> lootId) and the ids fitted in the two configs (with the ids in the recording)
            if t.get('configs') and t.get('items'):
                self.d['items'] = dict(t['items'])
                self.d['configs'] = json.loads(json.dumps(t['configs']))
                self.d['active_config'] = t.get('active_config', 1)
            else:
                self.d['items'], cfg = {}, {}
                for slot, loots in self.d['equipment'].items():
                    cfg[slot] = [self._add_item(loot) for loot in loots]
                self.d['configs'] = {'1': cfg, '2': json.loads(json.dumps(cfg))}
                self.d['active_config'] = 1
            self.dirty = True
        if 'next_id' not in self.d:
            self.d['next_id'] = max([int(i) for i in self.d['items']] + [99000000]) + 1
            self.dirty = True
        if 'ships' not in self.d:
            # multiple ships: each ship's own id, hangar id and two configs (starts with the Liberator ids in the recording)
            k = t.get('ship_ids') or {'shipId': 1, 'hangarId': 1}
            self.d['ships'] = {str(k['shipId']): {
                'lootId': self.d['ship'].get('typeId', 'ship_liberator'), 'hangarId': k['hangarId'],
                'configs': self.d.pop('configs'), 'active_config': self.d.pop('active_config', 1), 'favorite': False}}
            self.d['active_ship'] = str(k['shipId'])
            self.dirty = True
        if 'drones' not in self.d:
            # drones: order = position around the ship; formations: purchased ones (standard is always there)
            self.d['drones'], self.d['formations'], self.d['next_drone'] = [], [], 1
            self.dirty = True
        self.sync_cargo()
        if 'upgrades' not in self.d:
            self.d['upgrades'] = {}      # LabItem (0 laser, 1 rocket, 2 engine, 3 shield) -> [ore type, remaining]
            self.dirty = True
        if 'quests' not in self.d:
            # on login the account in the recording had 20000 active ("Elite Force Audition": return to the quest giver); the starting chain is from there
            self.d['quests'] = {'active': {'20000': {}}, 'done': []}
            self.dirty = True
        for s in self.d['ships'].values():
            if 'drone_config' not in s:
                s['drone_config'] = {c: {} for c in s['configs']}     # config -> drone id -> fitted item ids
                self.dirty = True
        # drone designs and P.E.T. equipment are tied to the ship (hangar): the ship's drone_design {config: {drone id: {design, appearance}}}
        # and pet_config {config: {slot: [item]}} records. They used to be tied to the config number (in the drone's record, in the P.E.T.'s config),
        # so they showed as fitted on every ship; after the Transfer System they stayed fitted on the old ship too (user report 2026-10-25).
        # The old ones go to the currently active ship (the player's own ship if in an Astral run). If the design was older it was on the drone itself, the same in both
        # configs (user report 2026-10-24: the Havocs fitted to config 1 also showed in config 2)
        run = ((self.d.get('pve') or {}).get('astral') or {}).get('run') or {}
        backup = run.get('backup') or {}
        own = [(self.d['active_ship'], self.d['drones'])]
        if run.get('inside') and backup.get('active') in self.d['ships']:
            own = [(backup['active'], backup.get('drones', [])), (self.d['active_ship'], self.d['drones'])]
        for sid, drones in own:
            for x in drones:
                for k in DESIGN_KEYS.values():
                    if k not in x:
                        continue
                    v = x.pop(k)
                    for c, iid in ((v if isinstance(v, dict) else {'1': v, '2': v}) if v else {}).items():
                        if iid:
                            self.d['ships'][sid].setdefault('drone_design', {}).setdefault(str(c), {}).setdefault(
                                str(x['uid']), {})[k] = iid
                    self.dirty = True
        pet = self.d.get('pet')
        if pet and 'config' in pet:
            self.d['ships'][own[0][0]].setdefault('pet_config', {}).update(pet.pop('config'))
            self.dirty = True
        for s in self.d['ships'].values():       # designs in the saved config: {drone: {design: {config: item}}} -> new format
            old = s.get('saved_drone_design') or {}
            if any(k in DESIGN_KEYS.values() for per in old.values() for k in per):
                new = {}
                for d, per in old.items():
                    for k, cs in per.items():
                        for c, iid in (cs or {}).items():
                            if iid:
                                new.setdefault(str(c), {}).setdefault(str(d), {})[k] = iid
                s['saved_drone_design'] = new
                self.dirty = True
        osmium = self.d.get('other_items', {}).pop('resource_ore_osmium', 0)
        if osmium:                           # Osmium (OreType 28) was not counted as ore, it had fallen into storage (2026-10-22 scan, E2)
            self.add_ores({28: osmium})
        q = self.d.get('settings', {}).get('qualitySettingsModule') or {}
        if q.get('qualityExplosion', 0) > 255:
            # the table did not know the byte swap of QualitySettingsRequest.qualityExplosion (protocol.py FIXES): the client's 3 had been saved as 768
            v = q['qualityExplosion']
            q['qualityExplosion'] = (v >> 8 & 0xFF) | (v << 8 & 0xFF00)
            self.dirty = True
        if q and not q.get('notSet') and q.get('qualityPresetting') == 3 and not any(
                q.get(k) for k in ('qualityShip', 'qualityEngine', 'qualityExplosion', 'qualityCollectables')):
            # before H229 a new profile's quality module went out as notSet: the client skipped it and stayed with its own default (preset 3, ship/engine/explosion/
            # collectable 0), pressing Save in Display sent that and it was saved: the engine trail never showed, H229 only
            # looked at notSet (user report 2026-10-26). With preset 3, all four being 0 at once cannot come from the interface (the Low preset makes all of them
            # and the preset 0): it is the signature of the client's default, repaired.
            q.update(qualityShip=3, qualityEngine=3, qualityExplosion=3, qualityCollectables=3)
            self.dirty = True
        if self.d['ship'].pop('galaxyGatesDone', None) is not None:     # old gate counter: the rings now come from the gates (galaxy_gates.rings)
            self.dirty = True
        self.add_windows()
        self.sync_equipment()

    def add_windows(self):
        """Menu items for the new windows not in the recording's interface (NEW_WINDOWS), next to the Return of Hero item."""
        for bar in self.d.get('ui', {}).get('featureBars', []):
            items = bar.get('featureBarItems', [])
            ref = next((it for it in items if it.get('itemId') == 'return_of_hero'), None)
            if not ref:
                continue
            have = {it.get('itemId') for b in self.d['ui']['featureBars'] for it in b.get('featureBarItems', [])}
            for item_id, (title, w, h) in NEW_WINDOWS.items():
                if item_id in have:
                    continue
                it = json.loads(json.dumps(ref))
                it.update(itemId=item_id, windowTitle=title, width=w, height=h, maximized=False, visible=False)
                for m in it['toolTip']['commandList']:
                    m['baseKey'] = title
                items.insert(items.index(ref) + 1, it)
                self.dirty = True

    def _text(self):
        """The JSON to be written to the file (the extra player of multi-client converts it to the real id: multiplayer.LocalProfile)."""
        return json.dumps(self.d, ensure_ascii=False, indent=1)

    def save(self, force=False):
        with self.lock:
            if not (self.dirty or force):
                return
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            # the world and the session write to the profile without a lock: if the dict's size changes while encoding ("dictionary changed size during
            # iteration") it is retried; the file is written only when the text is complete
            for k in range(5):
                try:
                    text = self._text()
                    break
                except RuntimeError:
                    if k == 4:
                        raise
                    time.sleep(0.01)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf8') as fp:
                fp.write(text)
                fp.flush()
                os.fsync(fp.fileno())           # so that no half/empty profile is left in a power cut
            # Windows: if the target file is open in another process at that moment (antivirus scanner, backup) os.replace gives "Access denied";
            # it is retried a few times (live: a 10 s save error had dropped the session)
            for k in range(6):
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if k == 5:
                        raise
                    time.sleep(0.05 * (k + 1))
            self.dirty = False

    # ---------------------------------------------------------------- generation
    @property
    def user_id(self):
        return self.d['pilot']['userId']

    def ship_init(self):
        f = dict(DEFAULT_SHIP_INIT)
        f.update(self.seed.get('ShipInitializationCommand') or {})
        f.update(self.d['pilot']); f.update(self.d['ship']); f.update(self.d['position'])
        f['premium'] = self.premium      # not written to Profile
        import galaxy_gates as GALAXY
        f['galaxyGatesDone'] = GALAXY.rings(self)     # gate rings: the bit mask of completed gates
        if getattr(self, 'captain_energy', None):
            f.update(self.captain_energy())                  # the energy of the fitted N.O.V.A. (nova.py)
        f['refreshMap'] = True   # on first login set up the ship and move to the map
        import gm_console as GMC
        if GMC.enabled(self):
            f['dailyRank'] = GMC.ADMIN_RANK  # GM console (stage 2): the client knows the admin by dailyRank 6000 (UnitFactory.InitMyUnit)
        import admin_mode as YM
        if YM.is_open(self):                    # admin mode: the badge and the admin ship's look (values are the ship's own)
            f['dailyRank'] = YM.BADGE
            f['typeId'] = YM.ship(self) or f['typeId']
        return f

    def beacon(self, station=None, near_gate=False, pos=None, repairing=False, gate_peace=False, radiation=False, void=False):
        b = dict(self.seed.get('BeaconCommand') or {})
        rep = next((e for e in EX.equipped(self) if e.startswith('equipment_extra_repbot_')), None)      # a robot fitted on a drone counts too
        b['repairRobotActive'] = repairing
        b['repairBotSkilled'] = SKILL.maxed(self, '13')       # Engineering 5/5: blue repair robot (official FAQ)
        if rep:
            b['repairRobotLootId'] = rep
        x, y = pos if pos else (self.d['position']['x'], self.d['position']['y'])
        b.update(positionX=int(x), positionY=int(y), positionAheadX=int(x), positionAheadY=int(y), inRadiationZone=radiation,
                 nearJumpGate=near_gate)
        inside = False
        if station:
            r = station.get('peaceRadius', 0)
            inside = (x - station['posX']) ** 2 + (y - station['posY']) ** 2 <= r * r
        b.update(inPeaceArea=bool((inside and station.get('pvpPeace', True)) or gate_peace) and not void, inStation=inside)     # the area around the portal is also safe (recording), not the station
        return b

    def generate(self, marker, station=None):
        """@marker in the template -> (message name, fields)."""
        if marker == '@gemi':
            return 'ShipInitializationCommand', self.ship_init()
        if marker == '@ayarlar':
            a = self.d['settings']
            q = a.get('qualitySettingsModule') or {}
            if q.get('notSet'):
                # quality was never saved (new profile): the client skips the module, its default is 0; the engine trail (ShipAsset.SetEngineVisible:
                # QualityEngine > 0) stayed off on all ships (user report 2026-10-24). A high preset goes, and when the player
                # changes it QualitySettingsRequest is saved.
                high = {k: 3 for k in q if k.startswith('quality') and k != 'qualityCustomized'}
                a = dict(a, qualitySettingsModule=dict(q, notSet=False, qualityCustomized=False, **high))
            return 'UserSettingsCommand', a
        if marker == '@tuslar':
            return 'UserKeyBindingsUpdate', {'changedKeyBindings': self.d['key_bindings']}
        if marker == '@arayuz':
            # the P.E.T. window's bar item is visible if there is a P.E.T. (the account in the recording had no P.E.T.: visible false)
            ui = json.loads(json.dumps(self.d['ui']))
            for bar in ui.get('featureBars', []):
                for it in bar.get('featureBarItems', []):
                    if it.get('itemId') == 'pet':
                        it['visible'] = bool(self.d.get('pet'))
                    if it.get('itemId') in MODE_WINDOWS:          # stage 8's modes (pve_modes.py): windows always visible
                        it['visible'] = True
                    if it.get('itemId') in EVENT_WINDOWS:         # event windows while the event runs (live test H47)
                        it['visible'] = event_window_visible(it['itemId'], hooks=self.window_hooks)
                    if it.get('itemId') in CLOSED_AT_LOGIN:
                        it['maximized'] = False
                    if it.get('itemId') in HIDDEN_WINDOWS:
                        it['visible'] = False
            # the right and left of the top row are on the same row: icons that do not fit on the left are never visible in the client (21 icons at 1280 width;
            # live test H45: Voyagers, NPC event, Rogue-Lite, R-Zone were unreachable). Mode windows to the second row (type 3).
            bars = {b.get('featureBarType'): b for b in ui.get('featureBars', [])}
            if 1 in bars and 3 in bars:
                second = set(MODE_WINDOWS) | set(EVENT_WINDOWS)
                moving = [it for it in bars[1]['featureBarItems'] if it.get('itemId') in second]
                bars[1]['featureBarItems'] = [it for it in bars[1]['featureBarItems'] if it.get('itemId') not in second]
                bars[3]['featureBarItems'] = bars[3]['featureBarItems'] + moving
            ws = self.bar_layout()
            for bar in ui.get('featureBars', []):          # feature bars the player dragged (WindowSettingsRequest)
                pos, order = FEATURE_BAR_KEYS.get(bar.get('featureBarType'), (None, None))
                if pos and ws.get(pos):
                    bar['featureBarPosition'] = ws[pos]
                if order and _layout_ok(ws.get(order)):
                    bar['featureBarOrder'] = str(ws[order])
            return 'UILayoutCommand', ui
        if marker == '@madenler':
            return 'AttributeOreCountUpdateCommand', {'oreCountList': self.d['ores']}
        if marker == '@formasyon':
            return 'DroneFormationChangeCommand', {'uid': self.user_id, 'selectedFormationId': self.d['formation']}
        if marker == '@giris_yaniti':
            return 'LoginResponse', {'status': 0}
        if marker == '@isaret':
            at_portal = bool(self.d['position'].get('at_portal'))
            return 'BeaconCommand', self.beacon(station, near_gate=at_portal, gate_peace=at_portal)
        return None

    def bar_layout(self):
        """Positions of the bars dragged in the interface configuration (WindowSettingsRequest -> settings.windowSettingsModule)."""
        return self.d.get('settings', {}).get('windowSettingsModule') or {}

    def window_item(self, item_id):
        """The menu item's current state (WindowItemCommand fields) or None."""
        _, ui = self.generate('@arayuz')
        return next(({k: v for k, v in it.items() if k != '_'} for bar in ui.get('featureBars', [])
                     for it in bar.get('featureBarItems', []) if it.get('itemId') == item_id), None)

    def event_window_items(self):
        """Menu items of the event windows, with the current visibility: when the calendar changes while the game runs as WindowItemCommand
        (the client's handler writes the item's visibility; with maximized=False it only closes the window, does not open it)."""
        _, ui = self.generate('@arayuz')
        return [('WindowItemCommand', dict({k: v for k, v in it.items() if k != '_'}, maximized=False))
                for bar in ui.get('featureBars', []) for it in bar.get('featureBarItems', [])
                if it.get('itemId') in EVENT_WINDOWS and it.get('itemId') not in OWN_SYNC]

    # ---------------------------------------------------------------- in-game changes (world simulation)
    def gain(self, ep=0, honor=0, credits=0, uridium=0, reason=None, detail='', count=0):
        """Adds the rewards -> new totals and level (EP table: data/levels.json). The clan's tax from earned credits (clan.taxed: aliens,
        players, ore, quests, gates, boxes) goes to the treasury (clan.tax; before the lock: the clan record's lock)."""
        if credits > 0 and self.d['pilot'].get('clanId'):
            import clan as KL
            if KL.taxed(reason):
                credits -= KL.tax(self, credits)
        with self.lock:
            p = self.d['pilot']
            p['ep'] = p.get('ep', 0) + ep
            p['honourPoints'] = p.get('honourPoints', 0) + honor
            p['credits'] = p.get('credits', 0) + credits
            p['uridium'] = p.get('uridium', 0) + uridium
            old = p.get('level', 1)
            p['level'] = max(old, level_for(p['ep']))
            self.dirty = True
            tot = dict(ep=p['ep'], honor=p['honourPoints'], credits=p['credits'], uridium=p['uridium'], level=p['level'],
                       leveled_up=p['level'] > old)
        if reason:                                  # account history (ranks.py): the client's description key
            RT.money(self, 'credits', credits, reason, detail, count)
            RT.money(self, 'uridium', uridium, reason, detail, count)
        if uridium > 0:
            BANK.accrue(self, uridium, reason)       # Uridium Bank: the same amount of uridium earned accumulates (bank.py)
        if reason != 'auction_bookMoneyBack':      # an auction refund is not income (the achievement counter was inflated by bids/refunds)
            self.ach('gain', ep=ep, honor=honor, credits=credits, uridium=uridium)
        if tot['leveled_up']:
            self.ach('level', value=tot['level'])
        return tot

    def add_ores(self, ores):
        """Adds {ore type: count} -> the current OreCountModule list."""
        with self.lock:
            cur = {m['oreType']['typeValue']: m['count'] for m in self.d['ores']}
            for t, n in ores.items():
                cur[int(t)] = cur.get(int(t), 0) + n
            self.d['ores'] = [{'_': 'OreCountModule', 'oreType': {'_': 'OreTypeModule', 'typeValue': t}, 'count': n}
                                  for t, n in sorted(cur.items()) if n > 0]
            self.sync_cargo()
            self.dirty = True
            return self.d['ores']

    def remove_ores(self, ores):
        """Removes {ore type: count} (sale) -> the current list; a type that runs out drops off the list (recording: the list after a sale)."""
        return self.add_ores({t: -n for t, n in ores.items()})

    def ore_count(self, t):
        return next((m['count'] for m in self.d['ores'] if m['oreType']['typeValue'] == int(t)), 0)

    def cargo_used(self):
        """Ores in the cargo (1 unit each; recording: with 73 ores free space 400 -> 327). Xenomit and event materials do not count."""
        return sum(m['count'] for m in self.d['ores'] if m['oreType']['typeValue'] in self.CARGO_ORES)

    def cargo_free(self):
        import settings as SET
        if SET.get('infinite_cargo'):
            return 10 ** 6                        # the cargo never fills (panel: Infinite cargo)
        return max(0, self.d['ship'].get('cargoSpaceMax', 0) - self.cargo_used())

    def sync_cargo(self):
        """ShipInitializationCommand.cargoSpace = free cargo space (recording)."""
        self.d['ship']['cargoSpace'] = min(self.cargo_free(), self.d['ship'].get('cargoSpaceMax', 0))      # the client shows at most the max space

    # ---------------------------------------------------------------- resource store (other_items)
    def resource(self, loot):
        """The amount of a resource in the store (Assembly materials, keys, coupons, Bifenon …; lootId)."""
        return self.d.get('other_items', {}).get(loot, 0)

    def add_resource(self, loot, n):
        """Add to storage (n < 0 removes, does not go below zero; the part over the client's stack limit is lost: official forum 150401
        "resources exceeding the maximum amount will be lost", client_items.json stack) -> new count."""
        cap = stack_cap(loot)
        with self.lock:
            d = self.d.setdefault('other_items', {})
            d[loot] = max(0, d.get(loot, 0) + n)
            if n > 0 and cap and d[loot] > cap:
                d[loot] = max(cap, d.get(loot, 0) - n)       # if already above the limit (old save) it does not reduce
            if not d[loot]:
                del d[loot]
            self.dirty = True
            return d.get(loot, 0)

    def spend_resources(self, need):
        """{lootId: count} if all are present they are spent together -> True; if one is short, none (Assembly recipes, keyed boxes)."""
        with self.lock:
            d = self.d.setdefault('other_items', {})
            if any(d.get(k, 0) < n for k, n in need.items()):
                return False
            for k, n in need.items():
                d[k] -= n
                if not d[k]:
                    del d[k]
            self.dirty = True
            return True

    def add_ammo(self, loot_id, n):
        with self.lock:
            c = self.d.setdefault('ammunition', {})
            c[loot_id] = c.get(loot_id, 0) + n
            self.dirty = True
            return c[loot_id]

    def ammo(self, loot_id):
        return self.d['ammunition'].get(loot_id, 0)

    def use_ammo(self, loot_id, n=1, event=True):
        """Spend n; None if short. event=False: the 'ammo' event is not emitted (the payment of inventory.spend emits its own 'spend' event)."""
        with self.lock:
            have = self.d['ammunition'].get(loot_id, 0)
            if have < n:
                return None
            import settings as SET
            used = 0 if SET.get('infinite_ammo') else n     # panel: infinite ammo (not consumed)
            self.d['ammunition'][loot_id] = have - used
            self.dirty = True
        if event:
            # Quests/Pass count what would have been used, even with infinite ammo
            self.ach('ammo', loot=loot_id, count=n)          # Pass quests: spend ammo (quest_tracker.py)
        return have - used

    def item_id(self, loot_id):
        """InventoryItemModule.itemId: the id in the recording, otherwise a stable number derived from lootId."""
        iid = self.d['item_id'].get(loot_id)
        if iid is None:
            import zlib
            iid = 900000000 + zlib.crc32(loot_id.encode()) % 90000000
        return iid

    # ---------------------------------------------------------------- hangar: equipment instances and configs
    def _add_item(self, loot_id):
        """A new equipment instance (each laser/generator/extra carries its own itemId) -> itemId."""
        iid = self.d.get('next_id') or max([int(i) for i in self.d['items']] + [99000000]) + 1
        self.d['next_id'] = iid + 1
        self.d['items'][str(iid)] = loot_id
        self.dirty = True
        return iid

    def new_item(self, loot_id, level=1):
        with self.lock:
            iid = self._add_item(loot_id)
            if level > 1:
                self.d.setdefault('item_level', {})[str(iid)] = level
            return iid

    def item_level(self, iid):
        """The item's level (P.E.T. gear/protocol 1-4; others 1)."""
        return self.d.get('item_level', {}).get(str(iid), 1)

    def ship(self, sid=None):
        """Ship record: lootId, hangarId, two configs, active config, stored hull. Default: the active ship."""
        return self.d['ships'][str(sid or self.d['active_ship'])]

    def ship_look(self, sid=None):
        """The ship's look: the design worn (e.g. ship_goliath_design_amber) or the ship itself. ShipInitializationCommand.typeId
        becomes this (in the recording other players appear with the design's lootId: ship_diminisher_design_diminisher-carbonite)."""
        s = self.ship(sid)
        return s.get('design') or s['lootId']

    def ship_row(self, sid=None):
        """The ship's values (items.json ships: hp, slots, base_speed, bonus ...) with the worn design's own values
        (items.json designs <- tools/design_values.py: Centurion's speed and slot designs, Holo's HP; the bonus
        is added to the ship's bonus)."""
        s = self.ship(sid)
        row = item()['ships'].get(s['lootId'], {})
        over = item().get('designs', {}).get(s.get('design') or '')
        if not over or not row:
            return row
        out = dict(row, **{k: v for k, v in over.items() if k != 'bonus'})
        bonus = dict(row.get('bonus', {}))
        for k, v in over.get('bonus', {}).items():
            bonus[k] = bonus.get(k, 0) + v
        if bonus:
            out['bonus'] = bonus
        return out

    def ship_by_hangar(self, hangar_id):
        return next((sid for sid, s in self.d['ships'].items() if s['hangarId'] == hangar_id), None)

    @property
    def active_config(self):
        return self.ship()['active_config']

    def config(self, cid=None, sid=None):
        s = self.ship(sid)
        return s['configs'].setdefault(str(cid or s['active_config']), {})

    def equipped_ids(self):
        """Item ids fitted in any config of any ship."""
        return set(self.hangar_map())

    def hangar_map(self):
        """itemId -> hangarId of the ship it is fitted on (in the inventory hangarId shows filled; 0 if not fitted). Ship slots, those fitted
        to drones, drone designs and P.E.T. equipment; all are tied to the ship (hangar) they are fitted on."""
        return {i: s['hangarId'] for sid, s in self.d['ships'].items() for i in self.ship_items(sid)}

    def item_places(self):
        """itemId -> (ship id, set of config ids) where it is equipped. The game lets one item sit in several configs of the same
        ship (shop.move only refuses another ship), so the panel shows these items for the other configs."""
        out = {}
        for sid, s in self.d['ships'].items():
            cids = set(s['configs']) | set(s.get('drone_config', {})) | set(s.get('drone_design', {})) | set(s.get('pet_config', {}))
            for cid in cids:
                for i in self.ship_items(sid, cid):
                    out.setdefault(i, (sid, set()))[1].add(str(cid))
        return out

    def ship_items(self, sid=None, cid=None):
        """A ship's (only that config's if cid is given) fitted item ids: ship slots, drones, drone designs, P.E.T."""
        s = self.ship(sid)
        cids = [str(cid)] if cid is not None else None
        pick = lambda cfgs: [v for c, v in cfgs.items() if cids is None or c in cids]
        out = [i for cfg in pick(s['configs']) for ids in cfg.values() for i in ids]
        out += [i for cfg in pick(s.get('drone_config', {})) for ids in cfg.values() for i in ids]
        out += [i for cfg in pick(s.get('drone_design', {})) for per in cfg.values() for i in per.values() if i]
        out += [i for cfg in pick(s.get('pet_config', {})) for ids in cfg.values() for i in ids]
        return out

    def pet_config(self, cid=None, sid=None):
        """The P.E.T. slot -> fitted item ids in a ship's config (default: the active ship, its active config)."""
        s = self.ship(sid)
        return s.setdefault('pet_config', {}).setdefault(str(cid or s['active_config']), {})

    def loadout(self, sid=None, cid=None):
        """The equipment in a ship's config: slot -> lootId list."""
        cfg = self.config(cid, sid)
        return {slot: [self.d['items'][str(i)] for i in cfg.get(slot, []) if str(i) in self.d['items']]
                for slot in ('laser', 'generators', 'extra', 'rocket', 'upgrades')}

    def loadout_levels(self, sid=None, cid=None):
        """The items' upgrade levels in the same order as loadout()."""
        cfg, lv = self.config(cid, sid), self.d.get('upgrade_level', {})
        return {slot: [int(lv.get(str(i), 0)) for i in cfg.get(slot, []) if str(i) in self.d['items']]
                for slot in ('laser', 'generators', 'extra', 'rocket')}

    def drone_levels(self, sid=None, cid=None):
        """In drone_loadout() order [drone lootId, the drone's upgrade level, [levels of the fitted items]]."""
        cfg, lv = self.drone_config(cid, sid), self.d.get('upgrade_level', {})
        return [[x['lootId'], int(x.get('upgrade', 0)),
                 [int(lv.get(str(i), 0)) for i in cfg.get(str(x['uid']), []) if str(i) in self.d['items']]]
                for x in self.d['drones']]

    # ---------------------------------------------------------------- drones
    def drone(self, drone_id):
        return next((x for x in self.d['drones'] if x['uid'] == int(drone_id)), None)

    def drone_config(self, cid=None, sid=None):
        """In a ship's config, drone id (text) -> fitted item ids."""
        s = self.ship(sid)
        return s.setdefault('drone_config', {}).setdefault(str(cid or s['active_config']), {})

    def drone_loadout(self, sid=None, cid=None):
        """In drone order [(drone record, [lootId ...])] (damage and shield calculation)."""
        cfg = self.drone_config(cid, sid)
        return [(x, [self.d['items'][str(i)] for i in cfg.get(str(x['uid']), []) if str(i) in self.d['items']])
                for x in self.d['drones']]

    def lab_items(self):
        """LabUpdateItemCommand.itemsUpdatedInfo: the ore loaded in each part and the remaining amount."""
        return [{'_': 'UpdateItemModule', 'itemToUpdate': {'_': 'LabItemModule', 'itemValue': int(k)},
                 'oreCountToUpdateWith': {'_': 'OreCountModule', 'oreType': {'_': 'OreTypeModule', 'typeValue': t}, 'count': n}}
                for k, (t, n) in sorted(self.d.get('upgrades', {}).items())]

    def formation(self):
        """The selected formation's bonuses (laser, rocket, shield, HP, speed, absorption, evasion, rocket cooldown, EP, honor)."""
        return _formations().get(formation_loot(self.d.get('formation', 0)), {})

    def drone_designs(self, cid=None, sid=None):
        """In a ship's config (default: the active ship, its active config), drone id (text) -> {design, appearance}."""
        s = self.ship(sid)
        return s.setdefault('drone_design', {}).setdefault(str(cid or s['active_config']), {})

    def drone_design_id(self, x, slot, cid=None, sid=None):
        """The drone's design in a ship's config (default: active) ('design', with bonus) or look ('visual') -> item
        id."""
        s = self.ship(sid)
        return s.get('drone_design', {}).get(str(cid or s['active_config']), {}).get(str(x['uid']), {}).get(DESIGN_KEYS[slot])

    def set_drone_design(self, x, slot, iid, cid=None, sid=None):
        """Item to the drone's design/appearance slot (None: empty it)."""
        per = self.drone_designs(cid, sid)
        if iid:
            per.setdefault(str(x['uid']), {})[DESIGN_KEYS[slot]] = iid
            return
        cur = per.get(str(x['uid']), {})
        cur.pop(DESIGN_KEYS[slot], None)
        if not cur:
            per.pop(str(x['uid']), None)

    def drone_design(self, x, slot, cid=None, sid=None):
        """drone_design_id'nin lootId'si."""
        iid = self.drone_design_id(x, slot, cid, sid)
        return self.d['items'].get(str(iid)) if iid else None

    def design_mods(self, cid=None, sid=None):
        """The bonuses of a config's (default: active ship, active config) drone designs: those per drone are summed; if all
        owned drones carry the same design, also the set bonus (client texts: Havoc +10% drone laser (drone_laser), Hercules
        +20% HP ...; Havoc: "If all of the drones are equipped"). Event designs in the appearance slot (Champion/Eostra: Goal Rush,
        Apocalypse Booty Box) give temporary NPC laser damage per fitted one while the event runs (per_event)."""
        designs = item()['drone_designs']
        looks = [self.drone_design(x, 'design', cid, sid) for x in self.d.get('drones', [])]
        out = {}
        for l in looks:
            for k, v in designs.get(l or '', {}).get('per_drone', {}).items():
                out[k] = out.get(k, 0) + v
        grp = lambda l: designs.get(l or '', {}).get('set_group', l)     # Demon Silver and Epic mixed also count as "all drones Demon" (forum 127526)
        if looks and looks[0] and len({grp(l) for l in looks}) == 1:
            for k, v in designs.get(looks[0], {}).get('set_bonus', {}).items():
                out[k] = out.get(k, 0) + v
        for x in self.d.get('drones', []):          # the temporary bonus of an appearance design during the event (Goal Rush, Apocalypse: NPC laser)
            e = designs.get(self.drone_design(x, 'visual', cid, sid) or '', {}).get('per_event')
            if e and event_on(e['event']):
                out['npc_laser'] = out.get('npc_laser', 0) + e['npc_laser']
        return out

    def mods(self):
        """Formation + drone design bonuses (laser, rocket, npc, shield, HP, speed, absorption, evasion, accuracy, rocket cooldown, EP, honor)."""
        out = {k: v for k, v in self.formation().items() if k != 'id'}
        for k, v in (list(self.design_mods().items()) + list(BOOSTER.mods(self).items())     # + boosters (booster.py)
                     + list(self.ship_mods().items())                                           # + ship/design bonus
                     + list(SKILL.mods(self).items())                                         # + pilot skills (skill_tree.py)
                     + list(SA.mods(self).items())                                              # + active ship abilities
                     + list((self.pet_mods() if getattr(self, 'pet_mods', None) else {}).items())         # + P.E.T. HEAT (pet.py)
                     + list((self.world_mods() if getattr(self, 'world_mods', None) else {}).items())     # + status effects
                     + list((self.mode_mods() if getattr(self, 'mode_mods', None) else {}).items())      # + mod boosters (ebl.py)
                     + list((self.nova_mods() if getattr(self, 'nova_mods', None) else {}).items())    # + N.O.V.A. (nova.py)
                     + list((self.event_mods() if getattr(self, 'event_mods', None) else {}).items())    # + Fever (fever.py)
                     + list((self.cbs_mods() if getattr(self, 'cbs_mods', None) else {}).items())):    # + CBS boosters (cbs.py)
            out[k] = min(out.get(k, v), v) if k in ('fixed_speed', 'max_speed') else out.get(k, 0) + v
        if out.get('evasion', 0) > 0.75:                 # official forum 160373: evasion at most 75%
            out['evasion'] = 0.75
        if out.get('cooldown', 0) > 0.75:                 # forum 127074: cooldown reduction at most 75% (ability)
            out['cooldown'] = 0.75
        for k in ('rocket_cooldown', 'launcher_cooldown', 'mine_cooldown', 'cannon_cooldown'):
            if out.get(k, 0) < -0.75:
                out[k] = -0.75
        return out

    def ship_mods(self):
        """The active ship's permanent bonus (passives: Cyborg +10% damage, Solaris Plus per module ...; design derivatives: G-Enforcer +5%
        damage ...; of the worn design: Tyrannos), Orcus's module multiplier and Leonov's bonus on its own X-1..X-4 (items.json)."""
        row = self.ship_row()
        out = dict(row.get('bonus', {}))
        n = min(len(self.config().get('upgrades', [])), row.get('module_max', 0))
        for k, v in row.get('per_module', {}).items():
            out[k] = out.get(k, 0) + v * n
        hp = LASERS.hp_bonus(self.d.get('equipment', {}).get('laser', [])       # LF-4 Hyperplasmoid: HP +0.5% per laser (on drones too)
                            + [l for _, loots in self.d.get('drone_equipment', []) for l in loots])
        if hp:
            out['hp'] = out.get('hp', 0) + hp
        shield_table = item()['shield_generators']                                  # Fusion Shield: shield regeneration +6.25% per fitted one
        gens = self.d.get('equipment', {}).get('generators', []) + [g for _, loots in self.d.get('drone_equipment', []) for g in loots]
        reg = sum(shield_table.get(g, {}).get('regeneration', 0) for g in gens)
        if reg:
            out['shield_regen'] = out.get('shield_regen', 0) + reg
        launchers = item()['combat_items']['launcher']['kinds']         # Plus launchers: Hydra HP/shield, Neptune damage ...
        for l in self.d.get('equipment', {}).get('rocket', []):
            for k, v in launchers.get(l, {}).get('bonus', {}).items():
                out[k] = out.get(k, 0) + v
        import ship_module as GM                                              # ship modules (normal and unstable)
        mk = row.get('module_multiplier', 1)                                     # Orcus: module attributes x1.75 (the negatives too)
        for k, v in GM.mods(self, self.ship()['lootId'], self.config().get('upgrades', []), self.d['pilot'].get('level')).items():
            out[k] = out.get(k, 0) + v * mk
        import qfc as QF                                                      # Quantum Fluid Cores (on the ship they are tied to)
        for k, v in QF.mods(self, self.ship()['lootId'], self.config().get(QF.SLOT, [])).items():
            out[k] = out.get(k, 0) + v
        import particle as PC                                                 # sub-attributes of the drive/lens (EP, honor, evasion)
        for k, v in PC.mods(self, self.ship()['lootId'], self.config()).items():
            out[k] = out.get(k, 0) + v
        hb = row.get('map_bonus')
        m = self.d['position'].get('mapId', 0)
        if hb and H.map_class(m) in hb['maps'] and H.company(m) == self.d['pilot'].get('factionId'):    # Leonov: in its own company
            for k, v in hb['bonus'].items():
                out[k] = out.get(k, 0) + v
        return out

    def lab_bonus(self, item):
        """The ore upgrade's bonus (laser/rocket damage, speed, shield); 0 if there is no upgrade."""
        u = self.d.get('upgrades', {}).get(str(item))
        return lab_data()['bonuses'][str(item)].get(str(u[0]), 0) if u and u[1] > 0 else 0

    def lab_use(self, item, n=1):
        """Spends n units from the upgrade -> True: done."""
        with self.lock:
            u = self.d.get('upgrades', {}).get(str(item))
            if not u:
                return False
            u[1] -= n
            self.dirty = True
            if u[1] <= 0:
                del self.d['upgrades'][str(item)]
                return True
            return False

    def add_drone(self, loot_id):
        """A new drone (level 1, 0 points) -> drone id."""
        with self.lock:
            did = self.d.get('next_drone', 1)
            self.d['next_drone'] = did + 1
            self.d['drones'].append({'uid': did, 'lootId': loot_id, 'level': 1, 'points': 0})
            self.dirty = True
            return did

    def sync_equipment(self):
        """The lootId lists from the active ship's active config (the world simulation reads these for damage/repair).
        drone_equipment: [[drone level, [lootId ...]] ...]."""
        self.d['equipment'] = self.loadout()
        self.d['drone_equipment'] = [[x['level'], loots] for x, loots in self.drone_loadout()]
        self.d['equipment_level'] = self.loadout_levels()          # upgrade levels (upgrades.py), in the same order
        self.d['drone_equipment_level'] = self.drone_levels()

    def add_ship(self, loot_id):
        """A new ship (two empty configs) -> shipId. Ids are given after those in the recording."""
        with self.lock:
            g = self.d['ships']
            sid = max(int(k) for k in g) + 1
            hid = max(s['hangarId'] for s in g.values()) + 1
            g[str(sid)] = {'lootId': loot_id, 'hangarId': hid, 'configs': {'1': {}, '2': {}}, 'active_config': 1, 'favorite': False,
                           'drone_config': {'1': {}, '2': {}}}
            self.dirty = True
            return sid

    def menu_status(self, menu_id):
        """The current state of a shortcut bar item (MenuItemStatusCommand): counter, selected, usable."""
        base = self.menu_status_cache.get(menu_id)
        if base is None:
            return None
        st = json.loads(json.dumps(base))
        if menu_id.startswith('drone_formation_'):
            # in the recording: standard is visible and selected; those not owned are invisible, in the tooltip ttip_item_not_owned
            owned = menu_id == 'drone_formation_default' or menu_id in self.d.get('formations', [])
            sel = formation_id(menu_id) == self.d.get('formation', 0)
            enough = formation_drones_ok(self, menu_id)
            st.update(visible=owned, available=owned and enough, activatable=owned and enough, selected=owned and sel)
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                lines = (st.get(tip) or {}).get('commandList')
                if owned and lines:
                    lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_item_not_owned']
            if owned and not enough:             # Arrow/Dome need 4 drones, Heart/Pincer 6 (wiki; client ttip_inactive_not_enough_drones)
                CIT._tips(st, [CIT._line('ttip_inactive_not_enough_drones')])
            return st
        if menu_id.startswith('ability_'):
            return SA.menu_status(self, menu_id, st)          # only the active ship's abilities (ship_ability.py)
        out = CIT.menu_status(self, menu_id, st)        # mines, Smart Bomb, Insta-Shield, CPUs, launcher (combat_items.py)
        if out is None and menu_id.startswith('tech_'):
            out = TECH.menu_status(self, menu_id, st)        # technology items (technology.py)
        if out is not None:
            return out
        if menu_id.startswith('ammunition_'):
            n = self.ammo(menu_id)
            kind = CIT.ammo_kind(menu_id)
            # ammo not in the account in the recording (R-IC3, SR-5, lasers other than RSB ...) is hidden in the template: visible if owned (live test H26)
            st.update(counterValue=n, counterStyle=4 if n > 0 else 1, available=n > 0, activatable=n > 0,
                      selected=bool(kind) and self.d['selected'].get(kind) == menu_id,
                      visible=bool(st.get('visible')) or n > 0)
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                for line in (st.get(tip) or {}).get('commandList', []):
                    for rep in line.get('wildCardReplacements', []):
                        if rep.get('wildcard') == '%COUNT%':
                            rep['replacement'] = str(n)
        return st

    def patch_template(self, name, fields):
        """Update the message from the template according to the profile: ammo counters in the shortcut menu, speed tied to equipment, and config."""
        if name == 'AttributeShipSpeedUpdateCommand':
            g = self.d['ship']
            return dict(fields, newSpeed=g.get('speed', fields['newSpeed']), displaySpeed=self.d.get('shown_speed', fields['displaySpeed']))
        if name == 'LabUpdateItemCommand':
            return dict(fields, itemsUpdatedInfo=self.lab_items())
        if name == 'DailyLoginRewardDayCommand' and self.daily_fields:
            return dict(fields, **self.daily_fields())      # the profile's calendar instead of "day 0" in the recording
        if name == 'AttributeBoosterUpdateCommand':
            return BOOSTER.update_cmd(self)[1]          # the profile's boosters instead of the empty info in the recording
        if name == 'PetInitializationCommand':
            pet = self.d.get('pet')       # the P.E.T. window's buttons (pet.py)
            return dict(fields, hasPet=bool(pet), hasFuel=bool(pet) and pet['fuel'] > 0, petIsAlive=bool(pet) and not pet['destroyed'])
        if name == 'CPUInitializationCommand':                 # the space map's jump panel (AJP-01)
            self.cpu_init_sent = dict(fields, advancedJumpCPUEquipped=CIT.has_ajp(self))
            return dict(self.cpu_init_sent)
        if name == 'LegacyModule' and fields.get('message', '').startswith('0|n|INV|'):
            parts = fields['message'].split('|')                # hidden on login if cloaked with the cloaking CPU
            return dict(fields, message='0|n|INV|%s|%d' % (parts[3], 1 if self.d.get('cpu_hidden') else 0))
        if name == 'InvitationBlockModule':                     # group invite block (the profile's choice instead of false in the recording)
            return dict(fields, active=bool(self.d.get('invite_block')))
        if name == 'LegacyModule' and fields.get('message', '').startswith('0|S|CFG|'):
            return dict(fields, message='0|S|CFG|%s' % self.active_config)
        if name == 'LegacyModule' and fields.get('message', '').startswith('0|A|JV|'):
            return dict(CIT.vouchers_msg(self)[1])                # AJP-01 coupon count (instead of 0 in the recording)
        if name == 'WindowItemCommand':
            # the menu item's place and visibility in the profile (the place in the recording; the event windows came invisible in the recording), closed
            cur = self.window_item(fields.get('itemId'))
            return dict(fields, **{k: cur[k] for k in ('posX', 'posY', 'width', 'height', 'visible') if k in cur}, maximized=False)                 if cur else fields
        if name != 'MenuInitializationCommand':
            return fields
        f = json.loads(json.dumps(fields))

        def walk(x):
            if isinstance(x, dict):
                if x.get('_') == 'MenuItemTimerCommand' and x.get('menuItemId') in SA.ABILITIES:
                    f_ = SA.timer_fields(self, x['menuItemId'])          # the ability's cooldown (on login, on map change)
                    x.update(activatable=f_['activatable'], maxTime=f_['maxTime'], time=f_['time'],
                             timerState={'_': 'TimerStateModule', 'timerStateValue': f_['timerState']})
                elif x.get('_') == 'MenuItemTimerCommand':
                    mid = x.get('menuItemId') or ''
                    f_ = (TECH.timer_fields(self, mid) if mid in TECH.ITEMS else None) or CIT.timer_fields(self, mid)   # technology, mines ...
                    if f_ and f_['timerState'] == TECH.READY:
                        f_ = None
                    if f_:
                        x.update(activatable=False, maxTime=f_['maxTime'], time=f_['time'],
                                 timerState={'_': 'TimerStateModule', 'timerStateValue': f_['timerState']})
                if x.get('_') == 'MenuItemStatusCommand' and x.get('menuItemId'):
                    lines = (x.get('toolTipItemBar') or {}).get('commandList')
                    if x['menuItemId'].startswith('buy_') and lines is not None and                             not any(l.get('baseKey') == QUICK_BUY_TIP['baseKey'] for l in lines):
                        lines.append(json.loads(json.dumps(QUICK_BUY_TIP)))
                    self.menu_status_cache.setdefault(x['menuItemId'], json.loads(json.dumps(x)))
                    cur = self.menu_status(x['menuItemId'])
                    if cur:
                        x.update(cur)
                        self.menu_mark(cur)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(f)
        bars = f.setdefault('slotBars', [])
        have = {b.get('slotBarId') for b in bars}
        bars += [{'_': 'SlotBarInitializationCommand', 'slots': [], 'slotBarId': bid, 'slotBarOrder': '0', 'slotBarPosition': pos,
                  'visible': True} for bid, pos in PREMIUM_SLOT_BARS if bid not in have]      # everyone is premium (H72, H81)
        ws = self.bar_layout()
        if ws.get('mainmenuPosition'):             # category bar (its dragged place in the configuration)
            f['itemBarPosition'] = ws['mainmenuPosition']
        for bar in bars:                           # shortcut bar: the player's layout (slot_bar_set)
            cur = self.d.get('shortcuts', {}).get(bar.get('slotBarId'))
            if cur is not None:
                bar['slots'] = [{'_': 'SlotInfoCommand', 'menuItemId': v, 'slotId': int(k)}
                                for k, v in sorted(cur.items(), key=lambda kv: int(kv[0]))]
            pos, order = SLOT_BAR_KEYS.get(bar.get('slotBarId'), (None, None))
            if pos and ws.get(pos):                # dragged place: percent position, offset 0,0
                bar['slotBarPosition'] = ws[pos].split('|')[0] + '|0,0'
            if order and _layout_ok(ws.get(order)):
                bar['slotBarOrder'] = str(ws[order])
        return f

    def gameplay(self, key):
        """Settings > Gameplay option (GameplaySettingsRequest -> settings.gameplaySettingsModule). Of this tab the client applies only attack by double
        click itself; auto upgrade, ammo switching, attack by shortcut, refining and key purchase are the server's job
        (SettingComponentSystem only saves and sends). If the setting never came, the default in the recording."""
        return bool((self.d.get('settings', {}).get('gameplaySettingsModule') or {}).get(key, GAMEPLAY_DEFAULTS.get(key, False)))

    def menu_mark(self, st):
        """This state was sent to the client (so menu_changes does not resend)."""
        self.menu_sent[st.get('menuItemId')] = json.dumps(st, sort_keys=True)

    def menu_changes(self, ids=None):
        """Shortcut items whose state changed since the last report -> MenuItemStatusCommands. Without ids, items tied to equipment
        (EQUIP_MENUS): after fitting/removing, arriving fitted from the shop, config and ship change (live test H21: when JP-01 was fitted
        it did not show on the bar)."""
        out = []
        if ids is None:
            ids = sorted(m for m in self.menu_status_cache if m.startswith(EQUIP_MENUS))
            ajp = CIT.has_ajp(self)
            if self.cpu_init_sent is not None and self.cpu_init_sent.get('advancedJumpCPUEquipped') != ajp:
                self.cpu_init_sent = dict(self.cpu_init_sent, advancedJumpCPUEquipped=ajp)      # the space map's jump panel (H23)
                out.append(('CPUInitializationCommand', dict(self.cpu_init_sent)))
        for mid in ids:
            st = self.menu_status(mid)
            if st and self.menu_sent.get(mid) != json.dumps(st, sort_keys=True):
                self.menu_mark(st)
                out.append(('MenuItemStatusCommand', st))
        return out

    def slot_bar_set(self, f, bars):
        """SlotBarConfigSetRequest: from the item bar or from a bar's slot to a slot (swaps if occupied), if dropped without a target
        it is removed from the bar. The same item can be in several slots of one bar: the client does not delete the old copy either
        (UIBagHelper.PutDownItemNew) and does not clear the emptied slot in the resent menu; when the server deleted it, it diverged from the screen
        (H83). bars: the template's bars (initial layout). In the recording the real server answers this by resending MenuInitializationCommand
        with the new slots. -> did it change"""
        item, src, dst = f.get('menuItemId') or '', f.get('slotBarIdFrom') or '', f.get('slotBarIdTo') or ''
        with self.lock:
            kb = self.d.setdefault('shortcuts', {b['slotBarId']: {str(s['slotId']): s['menuItemId'] for s in b['slots']} for b in bars})
            for bid in {src, dst} & {b for b, _ in PREMIUM_SLOT_BARS}:
                kb.setdefault(bid, {})
            if not item or (dst and dst not in kb) or (src and src not in kb):
                return False
            sfrom, stock = str(f.get('slotIdFrom')), str(f.get('slotIdTo'))
            moved = bool(src) and kb[src].get(sfrom) == item
            if moved:
                del kb[src][sfrom]
            if dst:
                old = kb[dst].get(stock)
                kb[dst][stock] = item
                if moved and old and old != item:
                    kb[src][sfrom] = old
            self.dirty = True
            return True

    def slot_bar_state(self, bars):
        """Items on the shortcut bars (quest condition PUT_ITEM_IN_SLOT_BAR; stage 1) -> {'items': {(bar, item)}, 'slots': {(bar, slot,
        item)}}. bars: the template's bars (initial layout if there are no shortcuts in the profile)."""
        kb = self.d.get('shortcuts') or {b['slotBarId']: {str(s['slotId']): s['menuItemId'] for s in b['slots']} for b in bars}
        rows = [(bar, slot, item) for bar, slots in kb.items() for slot, item in slots.items() if item]
        return {'items': {(b, i) for b, s, i in rows}, 'slots': {(b, s, i) for b, s, i in rows}}

    def set_hull(self, hp=None, shield=None):
        with self.lock:
            g = self.d['ship']
            if hp is not None:
                g['hitPoints'] = max(0, min(int(hp), g.get('hitMax', hp)))
            if shield is not None:
                g['shield'] = max(0, min(int(shield), g.get('shieldMax', shield)))
            self.dirty = True

    # ---------------------------------------------------------------- client requests
    def apply(self, name, f):
        """Writes the client's persistent-state request to the profile; True if handled."""
        with self.lock:
            if name in SETTINGS_REQUESTS:
                mod = self.d['settings'].setdefault(SETTINGS_REQUESTS[name], {})
                mod.update({k: v for k, v in f.items() if not k.startswith('_')})
                if name == 'WindowSettingsRequest' and 'minimapScale' in f:
                    mod['minmapScale'] = f['minimapScale']      # in the module the name is minmapScale (minimapScale in the request): minimap scale
                if 'notSet' in mod:
                    mod['notSet'] = False
            elif name == 'UserKeyBindingsUpdate':
                cur = {(b.get('actionType'), b.get('parameter')): b for b in self.d['key_bindings']}
                for b in f.get('changedKeyBindings', []):
                    cur[(b.get('actionType'), b.get('parameter'))] = b
                self.d['key_bindings'] = list(cur.values())
            elif name == 'ResetSettingsRequest':
                # Settings > Keyboard > Reset: keys to those in the seed (the client often cannot send the request before the connection closes: CANLI_TEST
                # N12; the panel's "key bindings" option does the same)
                self.d['key_bindings'] = self._from_seed(self.seed)['key_bindings']
            elif name == 'UIWindowUpdateRequest':
                for bar in self.d['ui'].get('featureBars', []):
                    for it in bar.get('featureBarItems', []):
                        if it.get('itemId') == f.get('itemId'):
                            it.update({k: f[k] for k in WINDOW_KEYS if k in f})
            elif name == 'MoveRequest':
                self.d['position'].update(x=f['targetX'], y=f['targetY'])
            else:
                return False
            self.dirty = True
            return True
