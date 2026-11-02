"""Local game server (TCP 8081): the libcom protocol of the DarkOrbit Unity client.

Usage: python -I game.py <log_folder> [--near-npc] [--no-popups] [--invulnerable] [--control] [--profile=<path>] [--settings=<path>]
                                         [--stop-file=<file>]
  Normally the admin panel starts it (server/panel/): the save slot's profile, the game settings and the stop file come from it.
  --settings=<path>: game settings (settings.py; default save/settings.json): multipliers, event choice, auction rivals,
  ad-free/invulnerable/near NPC (the panel counterparts of the options). Re-read while the game is open when the file changes.
  --stop-file=<file>: when the file appears the profile is saved and the server closes (the panel's "Stop server").
  --no-popups: promotional windows that open on their own at login (daily bonus, hints, Season Pass) are not sent either.
  Real-money shopping windows (Helix Blitz campaign, package offer) and the Command Center opening on its own
  are always off; the Command Center can be opened from the menu.
  --near-npc: a test convenience, one of each of the first 4 NPC types spawns right next to the player.
  --invulnerable: a test convenience, aliens' shots are visible but the ship loses no HP or shield (e.g. to try gates without dying).
  --control: live test control channel (control.py, 127.0.0.1:8099): message trace, request injection, sending commands, state.
  --profile=<path>: another profile instead of the active save slot (paths.py) (the panel passes the slot's; live tests work on a copy).
Framing: client -> server the first packet has a 4-byte, later ones a 3-byte BE length; server -> client a 3-byte BE length.
Messages are encoded/decoded with protocol.py (table: the client's own read() code, server/data/protocol_read.json).

Login flow (from the real server's record, see belgeler/istemci/kayit_analizi.md):
  LoginRequest  -> data/login.json "entry" bundle
  ReadyRequest  -> "ready" bundle (on the first ReadyRequest)
  The "@..." markers in the bundles are produced from the profile (profile.json) or the map data (data/maps.json).
  Read-only requests are answered with the replies in the record (data/responses.json); settings/window/movement requests are written to the profile.
  When the map loads the world simulation starts (world.py): NPCs, combat, rewards, boxes.
  Shop and hangar requests (purchases, equipping and unequipping) are handled in shop.py, on the profile.
  P.E.T. (pet.py): PetRequest, PetGearActivationRequest; its behavior in space is in the world loop, it comes out again on a map change.
  Galaxy Gates (galaxy_gates.py): GalaxyGateBuilder* requests; the gate portals in X-1 and the waves on the gate map are tied to the world.
Template files are produced with recording/extract_templates.py; if missing, only the smallest login (ship + LoginResponse) is sent from the profile.
"""
import contextlib, os, re, sys, socket, threading, time, json, math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import protocol as P       # noqa: E402
import paths as PTH       # noqa: E402
import game_data as GD         # noqa: E402
from player_profile import Profile  # noqa: E402
from world import World    # noqa: E402
from shop import Shop  # noqa: E402
import shop as SHP  # noqa: E402
from quest import Quests  # noqa: E402
import world               # noqa: E402
import galaxy_gates as GALAXY        # noqa: E402
import event_gate as EKP  # noqa: E402
import labyrinth as LAB      # noqa: E402
import pve_modes as PVM   # noqa: E402
import low as LOW          # noqa: E402
import assembly as ASM     # noqa: E402
import dispatch as DSP     # noqa: E402
import skylab as SKY       # noqa: E402
import bank as BANK       # noqa: E402
import loot as LOOT       # noqa: E402
import ship_module as GM    # noqa: E402
import event_calendar as CAL        # noqa: E402
import traceback           # noqa: E402
import season as SZN        # noqa: E402
import battle_pass as BPS  # noqa: E402
import daily_rewards as DRW  # noqa: E402
import achievement as ACV      # noqa: E402
from login_calendar import DailyLogin  # noqa: E402
from skill_tree import Abilities  # noqa: E402
from achievement import Achievements  # noqa: E402
import map_links as H
import combat_items as CIT    # noqa: E402
import ranks as RT         # noqa: E402
import new_systems as NS  # noqa: E402
import chat as CHT        # noqa: E402
import social as SO        # noqa: E402
import control as CTL       # noqa: E402
import settings as SET          # noqa: E402
import rankings as RK      # noqa: E402
import gm_console as GMC    # noqa: E402
import tips as IP         # noqa: E402
import payment as PAY         # noqa: E402
import panel_channel as PCH   # noqa: E402
import event_maps as EVM  # noqa: E402
import live_status as CD   # noqa: E402
import extra_events as EXE  # noqa: E402
import pilot as PILOT  # noqa: E402  (Auto Mode)
import cbs as CBS
import stores as STO
import player_profile as PF
import inventory as INV
import multiplayer as CO
import community as TP
import clan as KL
import group as GR
import contacts as CT
import bot.manager as BOT  # noqa: E402  (bot players: belgeler/BOTLAR.md)
from legacy_protocol import legacy, parse as legacy_parse  # noqa: E402         # noqa: E402

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
LOG_DIR = ARGS[0] if ARGS else '.'
DATA = os.path.join(HERE, 'data')
lock = threading.Lock()


def log(text):
    with lock:
        with open(os.path.join(LOG_DIR, 'gs.log'), 'a', encoding='utf8') as fh:
            fh.write(time.strftime('%H:%M:%S ') + text + '\n')


def encode(msgs):
    """Frames the messages; a message that cannot be encoded (a list over 255, an unknown field ...) is written to the log by name and skipped, the others go."""
    out = []
    for n, f in msgs:
        try:
            out.append(P.frame(P.encode_message(n, f)))
        except Exception as e:
            log('   could not encode, not sent: %s: %r' % (n, e))
    return b''.join(out)


def save_profile(profile=None):
    """Profile save (the server's own profile if not given); an error (file locked, disk) is written to the log and does not bring down the session or the map change;
    it is retried at the next save."""
    try:
        (profile or PROFILE).save()
    except Exception as e:
        log('   profile could not be saved: %r' % e)


def _load(name, default):
    p = PTH.template(name) if name in PTH.TEMPLATES else os.path.join(DATA, name)     # template: your own record, otherwise the shareable copy
    return json.load(open(p, encoding='utf8')) if p and os.path.exists(p) else default


class Templates:
    """Login bundles extracted from the record, the map world and the request replies (if you have no record of your own, the shareable copy in data/defaults/;
    paths.template)."""

    def __init__(self):
        self.entry = _load('login.json', {})
        self.maps = _load('maps.json', {})
        for map_id, w in self.maps.items():
            w['ready'] = [m for m in w.get('ready', []) if not (m['_m'] == 'JumpgateCreateCommand' and m['designId'] in SERVER_GATE_DESIGNS)]
            seen = set()
            for m in list(w['ready']):
                if m['_m'] != 'JumpgateCreateCommand':
                    continue
                if m['gateId'] in seen:                 # the 2-2 record lists each portal twice
                    w['ready'].remove(m)
                    continue
                seen.add(m['gateId'])
                p = H.ML.gate_pos(int(map_id), m['gateId'] - H.GATE_ID_BASE)
                if p:       # World Editor: a recorded map's (2-1, 2-2) portal is drawn where it was moved (the jump already used the new spot)
                    m['x'], m['y'] = p
        # only the ones used (E10): the code covers all the others; the record account's data (other players' names, clan
        # lists) must not leak into the window from a request's backup. They stay in the file: the source of the tools (rank, pve_modes, ranking_rewards)
        self.replies = {k: v for k, v in _load('responses.json', {}).items() if k in USED_RESPONSES}
        self.produced = {}

    def map_world(self, map_id):
        """The map's world messages {'giris', 'hazir'}: from the record if it is there; otherwise produced (on maps with a station the 2-1 station in the record
        is moved, map.map_world) and the portals from the client's spacemap-config.xml."""
        rec = self.maps.get(str(map_id))
        if rec is not None:
            return rec
        if str(map_id) not in self.produced:
            self.produced[str(map_id)] = H.map_world(map_id, self.maps.get('5'))
        return self.produced[str(map_id)]

    def station(self, map_id):
        """The map's station (repair, spawn, hangar): decorative stations (5-2's pirate station) do not count."""
        for m in self.map_world(map_id).get('ready', []):
            if m['_m'] == 'SpaceStationCommand' and m.get('type') not in H.DECOR_STATION_TYPES:
                return m
        return None

    def batch(self, kind, profile):
        """Produces the 'giris' or 'hazir' bundle as [(name, fields)]."""
        if not self.entry:
            if kind == 'entry':
                return [profile.generate('@gemi'), profile.generate('@giris_yaniti')]
            return []
        map_id = profile.d['position']['mapId']
        out, windows = [], set()
        for m in self.entry.get(kind, []):
            mk = m['_m']
            if mk in DEAD_TEMPLATE or m.get('message') in DEAD_LEGACY:
                continue
            if mk == 'WindowItemCommand':
                # in the record Contacts and Ship Warp come three times at login and again three times in every ready bundle (with the position in the record, maximized false:
                # an open window closes): once at login, with the position and visibility in the profile (profile.patch_template)
                if kind == 'ready' or m.get('itemId') in windows:
                    continue
                windows.add(m.get('itemId'))
            if mk in ('@harita_giris', '@harita_hazir'):
                lv = profile.d['pilot'].get('level', 1)
                out += [(n, f) for n, f in self.world_msgs(map_id, 'entry' if mk == '@harita_giris' else 'ready')
                        if not (n == 'JumpgateCreateCommand' and f['gateId'] == H.TUTORIAL_GATE and lv >= H.TUTORIAL_MAX_LEVEL)]
            elif kind == 'ready' and (mk == 'EquipReadyCommand' or m.get('message', '').startswith('0|n|MSG|3|2|msg_equip_')):
                continue               # true everywhere in the record; the world sends it as it enters and leaves the station zone (world.check_gates)
            elif mk.startswith('@'):
                st = self.station(map_id)               # the enemy base is not a safe zone (world.home_station)
                g = profile.generate(mk, st if st and st.get('type') == profile.d['pilot'].get('factionId') else None)
                if g:
                    out.append(g)
            else:
                out.append((mk, profile.patch_template(mk, m)))
                if mk == 'EventActivationStateCommand':      # map decorations of the running events (calendar.mood_cmds)
                    out += CAL.mood_cmds(CAL.active())
        return out

    def world_msgs(self, map_id, kind):
        """Map world: for maps visited in the record the messages in the record, for the others from the client's portal data."""
        return [(w['_m'], {k: v for k, v in w.items() if k != '_m'}) for w in self.map_world(map_id).get(kind, [])]

    def asset_removes(self, map_id):
        """On a map change remove the old map's station/turret objects (like the AssetRemoveCommand in the record)."""
        return [('AssetRemoveCommand', {'assetType': w['type'], 'uid': w['assetId']}) for w in
                self.map_world(map_id).get('entry', []) if w['_m'] == 'AssetCreateCommand']

    def response(self, name, fields):
        """Finds the recorded reply for a read-only request: an exact match, otherwise a record that differs only in the paging/news fields.
        If fields like type, module or sort differ there is no reply (before, another type's list went: Hall of Fame, Skylab module)."""
        entries = self.replies.get(name)
        if not entries:
            return None
        def diff(e):
            return {k for k, v in fields.items() if k != '_' and e['request'].get(k) != v}
        best = min(entries, key=lambda e: len(diff(e)))
        if diff(best) - LOOSE_FIELDS:
            return None
        return [(m['_m'], m) for m in best['response']]


LOOSE_FIELDS = {'startIndex', 'page', 'start', 'newsInfo'}       # request fields that do not change the reply's type
# the recorded replies the server uses: as replies (Command Center, pilot card) and as a data template (shop, hangar, gate)
USED_RESPONSES = {'CommandCenterGetDontShowRequest', 'CommandCenterNewsInfoRequest', 'InternalPilotBioRequest', 'ShopItemListRequest',
                  'HangarShipEquipmentRequest', 'HangarListRequest', 'HangarShipDetailRequest', 'GalaxyGateBuilderInfoRequest'}
# dead payload of the login template (E10): R-Zone state (171 times; its handler is dead), CTB (no handler in the client), 0|TR and 0|8
# (no branch in the client's OnData). POIReadyCommand is not dead: the client draws the zones' appearance only with it
# (PoiReadyCommandHandler -> PoiZoneManager.AssemblePoiReady -> UpdateDesign/UpdateDesign2D); when it did not arrive the 5-X and X-BL obstacles
# looked like a plain grey scan instead of asteroids/debris (user report 2026-10-25). After the map's ready bundle as in the record.
DEAD_TEMPLATE = {'RzoneStatusCommand', 'CTBMatchStateCommand'}
DEAD_LEGACY = {'0|TR', '0|8'}
# the mode portals in the record (2-1: Deep Space Echoes 300, Trinity Trials 304): the server's own portals (echoes.py, arena.py) went a second
# time at the same place (reference comparison 2026-10-25)
SERVER_GATE_DESIGNS = {300, 304}
# requests the real server does not answer either (record): so they do not show up as "unanswered" in the log
SILENT = {'TrackVariableRequest',
          'CommandCenterNewsClickedRequest', 'PerformanceTrackingSendInfoRequest',
          'ProActionBarOpenStateChangeRequest', 'QuestGiverWindowClosedRequest', 'CommandCenterUpdateDontShowRequest',
          'EggTriggerRequest'}
# requests that are never written to the log. EggTriggerRequest: the client's "went 6100 units outside the map" surprise
# (ChangePositionSyncGameObjectPos.Run); in 2D the ship's y is kept on the reversed axis, so while the ship is in the lower half of the map it comes
# every second (103 times in 10 minutes in the user's 2D session; H82). It has no reply; it advances hidden achievements (E6).
UNLOGGED = ('MoveRequest', 'KeepAlive', 'AttackRocketRequest', 'EggTriggerRequest')
EGG_TYPES = ('MINIMAP_PING', 'GOING_ROUND_THE_MAP', 'GALAXY_GATE_FIREWORK', 'RAINBOW_LASER')     # the client's EggTriggerType
CHAT = None                # local chat server (chat.py; main starts it, port 7771)
SESSIONS = set()            # sessions whose player is known (several on the friend server; multiplayer.py)
CONTROL = '--control' in sys.argv        # live test control channel (control.py): message trace and injection
CURRENT = None               # the session of the most recently connected client (the control channel drives it)
TP.GAME = sys.modules[__name__]          # the players on the server (group, contacts, whisper, mail): PROFILE, CURRENT
PROFILE_PATH = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--profile=')), None)
STOP = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--stop-file=')), None)    # panel: when it appears save and exit
# record (account without Premium): 0|l 19.2 s after the exit button, the connection closes; with Premium the client says "Log out ... in just five seconds"
LOGOUT_SEC = 5.0 if Profile.premium else 19.2

TEMPLATE = Templates()
PROFILE = Profile(TEMPLATE.entry.get('seed'), **({'path': PROFILE_PATH} if PROFILE_PATH else {}))
H.PLAYER_FACTION = PROFILE.d['pilot'].get('factionId')     # in 5-X only the portals of its own company
GALAXY.register_npcs(world.CFG['types'])     # gate aliens as NPC types
EKP.register_npcs(world.CFG['types'])      # those of the event gates (event_gate.py)
world.CFG['types'].update(PVM.AR.D['kinds'])  # aliens of the stage 8 modes (data/pve_modes.json)


# the login messages in the record for the Season Pass, Battle Pass and daily reward windows -> the ones produced from the profile
PASS_LOGIN = dict({n: 'season' for n in ('SeasonPassStatusCommand', 'SeasonPassMissionInfoCommand', 'SeasonPointsInfoCommand',
                                        'SeasonPassRewardInfoCommand')},
                  **{n: 'ticket' for n in ('BattlePassInfoCommand', 'BattlePassKeyExchangeInfoCommand', 'BattlePassWindowSettingsModule')},
                  **{n: 'reward' for n in ('MonthlyDeluxeInfoCommand', 'MiniClientRewardInfoCommand', 'EventUnityClientRewardQuestCommand')})
DRW_REQUESTS = ('MiniClientRewardClaimRequest', 'MonthlyDeluxeClaimRequest', 'ClaimUnityClientRewardRequest')
# --reklamsiz: do not send campaign/promo windows that open on their own at login
POPUP_MSGS = {'DisplayOfferCommand', 'HintWindowAddComand', 'HintWindowListInitCommand', 'DailyLoginRewardDayCommand',
              'MonthlyDeluxeInfoCommand', 'CommandCenterDontShowInfoCommand', 'SeasonPassStatusCommand',
              'SeasonPassMissionInfoCommand', 'SeasonPassRewardInfoCommand'}
# windows whose data does not open the window, that open from the layout (maximized) at login: Mini Client reward (MiniClientRewardInfoCommandHandler
# only writes the data). When the data was filtered the window opened empty (H155): the data always goes, the window goes closed
POPUP_WINDOWS = {'miniclient_reward'}
NO_POPUPS = '--no-popups' in sys.argv
# always: real-money shopping windows (useless in single player)
#   EventPaymentActorCommand: "%400 Helix Blitz" uridium campaign; DisplayOfferCommand: package offer window
PAYMENT_POPUPS = {'EventPaymentActorCommand', 'DisplayOfferCommand'}


def no_popups(msgs):
    """Filters out the windows that open on their own at login. Command Center: if the client's CommandCenterDontShowInfoCommand.inspected
    comes false it opens the window (CommandCenterDontShowInfoCommandHandler); true is always sent, it can still be opened from the menu."""
    popups = NO_POPUPS or SET.get('no_ads')                                                  # option or the panel's setting
    drop = PAYMENT_POPUPS | (POPUP_MSGS if popups else set())
    out = []
    for n, f in msgs:
        if n in drop and n != 'CommandCenterDontShowInfoCommand':
            continue
        if n == 'UILayoutCommand' and popups:
            for bar in f.get('featureBars', []):
                for it in bar.get('featureBarItems', []):
                    if it.get('itemId') in POPUP_WINDOWS:
                        it['maximized'] = False
        if n == 'CommandCenterDontShowInfoCommand':
            f = dict(f, inspected=True)
        out.append((n, f))
    return out


def login_batch(kind, first=True, profile=None):
    """first=False: map change (portal, repair at the station). Windows that open on their own at login (daily bonus, hints,
    Season Pass) come only at login; the UI stays across a map change, resending the data used to reopen the windows.
    profile: the session's player (a guest's on the friend server; the server's own profile if not given)."""
    msgs = no_popups(TEMPLATE.batch(kind, profile or PROFILE))
    if not first:                    # window elements also only at login: on a map change they used to close an open window (E10)
        msgs = [(n, f) for n, f in msgs if (n not in POPUP_MSGS or n == 'CommandCenterDontShowInfoCommand') and n != 'WindowItemCommand']
    return msgs


HOME_MAP = {1: 1, 2: 5, 3: 9}     # company -> home map (X-1)
# maps that are the players' shared world on the friend server (shared_maps.py): company, battle and Blacklight maps (1-1 ... 5-4,
# BL-1..3); gate, mode, event, labyrinth and LoW maps are each player's own copy
SHARED = {k for k in world.CFG['maps'] if k.isdigit() and re.match(r'(\d|BL)-\d$', H.name(k)) and int(k) not in GALAXY.BY_MAP
              and int(k) not in EKP.BY_MAP and int(k) not in LAB.MAPS and int(k) != LOW.MAP}
NAME_MIN, NAME_MAX, STATUS_MAX = 4, 20, 200    # pilot name 4-20 (the client's change_pilotname_error_signs_number); the status text is an adaptation
NAME_ILLEGAL = set(' <>@+\'"&%;/\\?|')          # the client's change_pilotname_error_signs_illegal (+ the protocol's separator |)
NAME_WAIT_SEC = 48 * 3600                         # client change_pilotname_error_time: "once every 48 hours"


def achievement_groups(now=None):
    """Active groups of the achievements: the calendar's events and this season's Season Pass group (SEASONPASS_Qn; season.py)."""
    sp = SZN.achievement_group(now)
    return CAL.achievement_groups(now) | ({sp} if sp else set())

WORLD_REQUESTS = {'ShipSelectRequest': 'select', 'AttackLaserRequest': 'laser_start', 'AttackRocketRequest': 'rocket',
                  'CollectBoxRequest': 'collect', 'MenuActionRequest': 'menu_action', 'HarvestRequest': 'harvest',
                  'TradeSellOreRequest': 'sell_ore', 'InstantRepairRequest': 'instant_repair'}


class Session:
    """A client connection: login flow, world, map change. Sending is locked since the world loop writes here too.
    The session's player is self.profile: the server's own record (PROFILE) or, on the friend server, the record the guest sent
    (multiplayer.py). wait=True: the player becomes known at login (the sessionID of LoginRequest), the systems are set up then (bind)."""

    def __init__(self, c, addr, profile=None, wait=False, queue=False):
        self.c, self.addr = c, addr
        self.send_lock = threading.Lock()
        self.packet_lock = threading.Lock()      # the client's packets and the ones the control channel injects are processed in order
        self.play_start = time.time()            # play time (play_time)
        self.state_lock = threading.RLock()
        self.map_pending = False     # ShipInitializationCommand was sent; when the map loads (ReadyRequest) the ready bundle + world
        self.ready_n = 0             # number of ReadyRequests answered (1: first login; the later ones are map loads)
        self.world = None
        self.secrets = set()         # the session key in LoginRequest: the old text protocol carries it too ("S|CFG|2|<user>|<key>")
        self.profile = None
        self.guest = None          # the guest's record on the friend server (multiplayer.Guest); None for the server's own player
        self.local = None            # the extra player of the multi-client (multiplayer.LocalPlayer)
        self.client_pid = None      # the connecting client's process (which session the payment button belongs to: payment.connecting_pid)
        self.queue = CO.SendQueue(c) if queue else None     # send queue on the friend server: so a slow network does not hold the world lock
        if not wait:
            self.bind(profile or PROFILE)

    def bind(self, profile):
        """Sets up the session's systems with the player's profile."""
        global CURRENT
        self.profile = profile
        if profile is PROFILE:
            CURRENT = self           # the control channel, live state and payment button watch the session of the server's own player
        SESSIONS.add(self)
        self.shop = Shop(self.profile, TEMPLATE.replies, log)
        self.quest = Quests(self.profile, log)
        self.quest.grant = self.quest_reward
        self.quest.send = lambda m: self.send(m, 'quest timer')
        self.quest.state = lambda: self.world.quest_state() if self.world else {}      # MISCELLANEOUS sub-conditions (hidden, radiation, low HP)
        self.shop.quest = self.quest.event                        # collection quests: ore produced in the refinery
        self.daily = DailyLogin(self.profile, self.shop, log)      # daily login calendar
        self.profile.daily_fields = self.daily.fields
        self.pet = self.shop.pet
        self.pet.send_raw = lambda m: self.send(m, quiet=True)
        self.gates = GALAXY.Gates(self.profile, log)
        self.gates.m = self.shop
        self.shop.gates = self.gates      # free gate energy in rewards
        self.event_gates = EKP.EventGates(self.profile, log)                    # event gates (Gauntlet of Plutus, Vortex ...)
        self.event_gates.m = self.shop
        self.pve = PVM.PveModes(self.profile, self.shop, self.event_gates, log)    # stage 8: endless and rogue-lite PvE modes
        self.pve.send = lambda m: self.send(m, 'mod')
        self.pve.change_map = self.change_map
        self.profile.mode_mods = lambda: self.pve.ebl.mods(self.profile.d['position']['mapId']) if self.pve.ebl else {}
        self.new_ = NS.NewSystems(self.profile, self.shop, log)     # stage 9: N.O.V.A., Armory Unlock, QFC/Hyperforge, auto pilot
        self.shop.new_ = self.new_
        self.shop.world = lambda: getattr(self, 'world', None)    # drone formation wait (shop.formation_wait)
        self.profile.nova_mods = lambda: self.new_.mods(self.profile.d['position']['mapId'])
        self.profile.captain_energy = self.new_.nova.hud
        self.social = SO.Social(self.profile, self.shop, log, CHAT)   # stage 10: chat, mail, clan, auction, ship warp
        self.social.send = lambda m, note: self.send(m, note)
        self.social.reload = lambda: self.world and self.world.reload_ship()
        self.social_next = 0.0
        self.skill = Abilities(self.profile, self.shop, self.gates, log)    # pilot skill tree (log disks in the gate counter)
        self.assembly = ASM.Assembly(self.profile, log)                            # Assembly (recipes, production)
        self.assembly.m = self.shop
        self.assembly.send = lambda m: self.send(m, 'Assembly')
        self.dispatch = DSP.Dispatch(self.profile, self.gates, log)             # Dispatch (collector and gate dispatch)
        self.dispatch.m = self.shop
        self.skylab = SKY.Skylab(self.profile, log)                                # Skylab (production, upgrade, transport)
        self.skylab.m = self.shop
        self.skylab.send = lambda m: self.send(m, 'Skylab')
        self.skylab.quest = lambda **kw: self.quest.event('skylab', **kw)        # quest condition UPDATE_SKYLAB_TO_LEVEL (Ö1)
        self.modules = GM.Modules(self.profile, log)                             # unstable modules (Restabilize)
        self.modules.m = self.shop
        self.season = SZN.Season(self.profile, log)                                  # Season Pass (season.py)
        self.ticket = BPS.BattlePass(self.profile, log)                            # Battle Pass and key exchange (battle_pass.py)
        self.reward = DRW.DailyReward(self.profile, log)                              # Mini Client, Monthly Deluxe, Unity reward (daily_rewards.py)
        for _o, _note in ((self.season, 'Season Pass'), (self.ticket, 'Battle Pass'), (self.reward, 'daily reward')):
            _o.m = self.shop
            _o.send = (lambda note: lambda m: self.send(m, note))(_note)
        self.shop.tickets = (self.season, self.ticket, self.reward)
        self.ticket.objective = lambda: self.season.event('objective')     # Season Pass 700023-700025 (15 Battle Pass quests in the event)
        self.shop.quest = self.quest_event                        # collection quests: ore produced in the refinery
        self.bank_sent = None         # the Uridium Bank accumulation the client last saw
        self.cal_sent, self.cal_next = None, 0.0                            # calendar: the active events last reported
        self.win_sent = {}                                                  # the last reported visibility of the event windows
        ACV.set_events(achievement_groups())
        self.bank_next = 0.0
        self.achievement = Achievements(self.profile, log)                               # achievements and titles
        self.achievement.send = lambda m: self.send(m, 'achievement')
        self.profile.ach = self.ach_event
        self.gates.world = lambda: self.world
        self.gates.info_tpl = next((m for e in TEMPLATE.replies.get('GalaxyGateBuilderInfoRequest', []) for m in e['response']
                                      if m['_m'] == 'GalaxyGateBuilderInfoCommand'), None)
        self.logout_timer = None      # exit countdown (UIButtonTriggerRequest logout)
        self.gm = GMC.Console(self, log)   # GM console (if enabled in the panel)
        self.hint = IP.Hints(self.profile, log)   # hints for new players (once; the panel's 'hints' setting)
        self.windows = PAY.Windows()      # the windows opened last: the payment button's product (payment.py)
        self.extra = EXE.ExtraEvents(self.profile, self.shop, self.event_gates, log)   # events of Ö3 (Chromin Rush ...)
        if self.extra.fiesta:
            self.extra.fiesta.change_map = self.change_map
            self.extra.fiesta.titles = self.extra.title.grant_title           # Epoch Lit (Tranquil)
            self.pve.extra_windows['fiesta'] = self.extra.fiesta.portal_window
        self.cbs = CBS.Cbs(self.profile, self.shop, log)                     # Clan Battle Station (Ö5)
        self.extra.add(self.cbs)
        self.social.clan.cbs = self.cbs
        self.profile.cbs_mods = self.cbs.mods
        self.shop.cbs = self.cbs                 # Assembly: idle modules are in the inventory, upgradeable (shop.module_items)
        self.store = STO.Stores(self.profile, self.shop, log)              # Ö7: shop windows that run on uridium
        self.extra.add(self.store)
        self.extra.add(PILOT.Pilot(self, log))                # Auto Mode (pilot/): the server flies the ship; local feature
        self.profile.window_hooks['returnee_login'] = self.store.returnee_active
        self.extra.rbp.hero = lambda: bool(self.store.rh().get('connected'))           # Recall Battle Pass: the state in Return of Hero
        # Season Pass quest finished -> event systems (Recall Battle Pass, Return of Hero: COMPLETE_SEASON_PASS_QUESTS quests)
        self.season.quest_done = lambda cat: self.extra.event('sp_quest', dict(category=cat))
        self.profile.window_hooks['diminish_quests'] = self.extra.urgent.menu_visible   # Urgent Missions: only while there is a quest (urgent_quests.py)
        for kind, s in (('vortex', self.extra.vortex), ('world_boss', self.extra.boss), ('mimesis', self.extra.mimesis),   # Ö4
                        ('apotheosis', self.extra.apo)):                                                       # 1.1.115
            s.change_map = self.change_map
            self.pve.extra_windows[kind] = s.portal_window
        self.extra.send = lambda m: self.send(m, 'event')
        self.extra.title.base_title = lambda: self.achievement.title_msgs()
        self.gates.titles = self.extra.title.grant_title           # gate completion title (wiki: All-Star, Boss Of Bosses, Emperor Of Hades Gate)
        self.pve.echoes.titles = self.extra.title.grant_title        # Deep Space Echoes end-of-period ranking title (Cosmic Tyrant)
        self.extra_next = 0.0
        self.profile.hint = self.hint.show
        self.shop.rescue_depot()   # in place of rewards that landed in the invisible storage (drone design, P.E.T. protocol, Season Pass reserve)

    # ------------------------------------------------------------ exit
    def logout_start(self):
        """Exit button: the client shows its own countdown; as in the record, 0|l after ~19 s and the connection closes. If we do not send it
        the client used to cut the connection when the time ran out and log in again (log 13:11)."""
        self.logout_cancel()
        t = threading.Timer(LOGOUT_SEC, self.logout_done)
        t.daemon = True
        self.logout_timer = t
        t.start()
        log('   exit: in %.1f s' % LOGOUT_SEC)

    def logout_cancel(self):
        if self.logout_timer:
            self.logout_timer.cancel()
            self.logout_timer = None
            log('   exit cancelled')

    def logout_done(self):
        self.logout_timer = None
        save_profile(self.profile)
        try:
            self.send([legacy('0|l')], 'logout')
        except OSError:
            pass
        self.close()

    def close(self):
        """Close the connection (after what was sent has gone): the client's reading ends, the session closes (run)."""
        try:
            if self.queue:
                self.queue.close()
            else:
                self.c.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def hand_over(self):
        """The same player reconnected (friend server): the old connection is cut at once, its world stops without waiting. Only closing
        left sending stuck on a half-open connection and reading never finished; the old world stayed on the shared map, the player was there twice."""
        try:
            self.c.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if self.queue:
            self.queue.close()
        if self.world:
            self.world.stop()

    def ach_event(self, kind, **kw):
        """Game events: rank counters (ranks.py), Pass quests, main quests (kills come from the quest event) and achievements
        (achievement.py)."""
        RT.event(self.profile, kind, **kw)
        if kind != 'map' and not kw.get('dispatch'):     # map visits come from the quest event; Dispatch's gate does not count as a quest
            self.pass_event(kind, **kw)
            msgs = self.extra.event(kind, kw)        # Ö3's event quests (Galaxy Trek)
            if msgs:
                self.send(msgs, 'event quest')
            msgs = self.quest.event(kind, **kw) if kind != 'kill' else []      # E6: the single measuring point (quest_tracker.measure)
            if msgs:
                self.send(msgs, 'quest')
        if kind == 'death':                       # "without dying" quests fail (quest.py)
            failed = self.quest.broken('death')
            if failed:
                self.send(failed, 'quest failed')
        if kind == 'level':                       # level up: the invitation hint for the new feature (hints.py)
            hint = self.hint.level(kw.get('value', 1))
            if hint:
                self.send(hint, 'ipucu: seviye')
        return self.achievement.event(kind, **kw)

    def event_tips(self, now=None):
        """Description of the running map events once per period (tips.py; NormalTipsCommand message box)."""
        per = lambda k: (CAL.period(k, now) or (0,))[0]
        msgs = self.hint.event_tips(EVM.specs(now), per)
        if msgs:
            self.send(msgs, 'event notice')

    def quest_event(self, kind, **kw):
        """The world's quest events: quests and Pass quests (kills go to the Passes from the achievement event; an alien a group member kills on the same
        map is not an achievement, only a quest: Pass, event and Urgent Missions quests come from here too)."""
        group = kind == 'kill' and kw.get('group')
        if kind in ('cargo', 'loot', 'sell', 'bonus', 'map', 'ore_update') or group:     # ore_update: Season Pass USE_ORE_UPDATE quests
            self.pass_event(kind, **kw)
            msgs = self.extra.event(kind, kw) + (self.extra.urgent.kill(kw.get('npc')) if group else [])
            if msgs:
                self.send(msgs, 'event quest')
        return self.quest.event(kind, **kw)

    def quest_state_events(self):
        """State conditions (Ö1): when a quest is accepted the current state is evaluated once (the item in the bar, the levels of the Skylab modules),
        otherwise the condition would only advance at the next change."""
        tpl = next((m for m in TEMPLATE.entry.get('ready', []) if m['_m'] == 'MenuInitializationCommand'), None)
        msgs = self.quest.event('slot_bar', **self.profile.slot_bar_state(tpl['slotBars'] if tpl else []))
        for key, lv in self.skylab.levels().items():
            msgs += self.quest.event('skylab', module=key, level=lv)
        if self.profile.d.get('clan'):
            msgs += self.quest.event('clan')                 # IN_CLAN: klanda olmak
        return msgs

    def pass_event(self, kind, **kw):
        """Season Pass, Battle Pass and Unity reward quests (each sends its own message)."""
        mid = self.profile.d['position'].get('mapId')
        for o in (self.season, self.ticket, self.reward):
            o.map_id = mid
            try:
                o.event(kind, **kw)
            except Exception:
                log('   Pass event error (%s %s):\n%s' % (kind, kw, traceback.format_exc()))

    def hint_msgs(self, n, f):
        """Hint windows: those the player closed (HintWindowClosedRequest, hints_closed in the profile) do not reopen at login,
        they are added to the hint archive list (live trial 2026-10-17: "New Employee Orientation" opened at every login)."""
        closed = self.profile.d.get('hints_closed', [])
        if n == 'HintWindowAddComand':
            return [] if (f.get('window') or {}).get('content') in closed else [(n, f)]
        have = [w.get('content') for w in f.get('windows', [])]
        return [(n, dict(f, windows=list(f.get('windows', [])) + [{'_': 'HintWindowModule', 'content': c} for c in closed
                                                                  if c not in have]))]

    def play_time(self):
        """The time stayed connected is in the profile (play_seconds): the pilot card's "Player activity: ... hours" line (live test H28)."""
        now = time.time()
        start = getattr(self, 'play_start', None) or now
        self.play_start = now
        with self.profile.lock:
            self.profile.d['play_sec'] = self.profile.d.get('play_sec', 0) + max(0, now - start)

    def rename(self, name):
        """Change the pilot name (free). The new name shows on the ship at the map change (the client has no NameChangeCommand handler).
        An invalid name or another player's name on the server (chat, mail, group, clan find the player by name):
        InternalPilotBioUpdateResultsCommand success=False."""
        name = str(name or '').strip()
        last = self.profile.d.get('name_change', 0)
        o = TP.find(name=name)
        if not NAME_MIN <= len(name) <= NAME_MAX:
            why = 'change_pilotname_error_signs_number'
        elif set(name) & NAME_ILLEGAL or '--' in name or not name.isprintable():
            why = 'change_pilotname_error_signs_illegal'
        elif KL.is_banned(name):                                    # Game Rules 7 (official forum 131990): staff names, swearing
            why = 'name_banned'
        elif o is not None and o.profile is not self.profile or KL.is_member_name(name, self.profile.d['pilot'].get('userName', '')):
            why = 'change_pilotname_error_inUse'           # also the name of an offline clan member or a bot (so the membership record is not overwritten)
        elif SET.get('clan_cooldown') and time.time() - last < NAME_WAIT_SEC:
            why = 'name_cooldown'
        else:
            why = None
        if why is None:
            old = self.profile.d['pilot'].get('userName', '')
            with self.profile.lock:
                self.profile.d['pilot']['userName'] = name
                self.profile.d['name_change'] = time.time()
                self.profile.dirty = True
            KL.name_changed(old, name)
            import name_log as NL                          # other players' contact lists (friends, requests, blocked) and the bots' memory
            NL.add([{'type': 'name', 'old': old, 'new': name}])
            from bot import manager as MGR
            if MGR.ACTIVE is not None:
                MGR.ACTIVE.apply_name_log()
            if self.social.chat:                         # in chat with the new name (otherwise the old name until it reconnects)
                self.social.chat.update_user(who=str(self.profile.user_id), userId=name)
            log('   pilot name: %s' % name)
            return ('InternalPilotBioUpdateResultsCommand', {'success': True, 'baseStackCommand': SHP.stack_msg('change_pilotname_success')})
        log('   pilot name not changed: %r (%s)' % (name, why))
        if why in SHP.REASONS:                                    # not in BaseKey: the client's text is raw (change_pilotname_error_*)
            en, tr = SHP.REASONS[why]
            msg = SHP.raw_msg((tr if self.shop.lang == 'tr' else en).replace('%DATETIME%', time.strftime('%d.%m.%Y %H:%M', time.localtime(last))))
        else:
            msg = SHP.stack_msg(why)
        return ('InternalPilotBioUpdateResultsCommand', {'success': False, 'baseStackCommand': msg})

    def pilot_bio(self, resp, uid=None):
        """InternalPilotBioRequest: the profile card in the record + the information the player saved (InternalPilotBioUpdateRequest). uid:
        another player's card on the friend server (contacts, group, chat menu: from their record)."""
        o = TP.find(uid=uid) if uid and uid != self.profile.user_id else None
        p = o.profile if o is not None else self.profile
        bio = p.d.get('pilot_bio', {})
        if p is self.profile:
            self.play_time()
        k = KL.clan_of(p) or {}                                       # shared clan (clan.py)
        order = KL.ranking() if k else []
        rank = {'rank': p.d['pilot'].get('dailyRank', 1),            # the rank on the pilot card (number)
                'playTime': int(p.d.get('play_sec', 0) // 3600),     # clock
                'userName': p.d['pilot'].get('userName', ''),          # its profile's, not the name in the record
                'userId': p.user_id, 'registrationDate': p.d.get('created', '') + '.0',    # not the record account's
                'ranking': RT.hof_sira(p),                                  # among the players on the server (ranks.hof_top)
                'clanName': k.get('name', ''), 'clanRank': next((i + 1 for i, (c, _) in enumerate(order) if c is k), 0),
                'clanMemberCount': len(k.get('members', ()))}
        return [(n, dict(f, **{k: v for k, v in dict(bio, **rank).items() if k in f})) if n == 'InternalPilotBioUserProfileCommand'
                else (n, f) for n, f in resp]

    def send(self, msgs, note=None, quiet=False):
        msgs = INV.client_filter(msgs)                # item updates that break the client's inventory index (H134)
        w = getattr(self, 'world', None)
        if w is not None and w.defer(msgs):           # in the world's loop step: at the end of the step, in the same order as the world's messages
            if note and not quiet:
                log('-> %s (%d messages, at end of step)' % (note, len(msgs)))
            elif not quiet:
                for n, f in msgs:
                    log('-> %s %s' % (n, P.fmt(f, 160)))
            return
        data = encode(msgs)
        with self.send_lock:
            if self.queue:
                self.queue.put(data)             # friend server: so the network does not hold the world lock (multiplayer.SendQueue)
            else:
                self.c.sendall(data)
            if CONTROL:
                for n, f in msgs:
                    CTL.TRACE.add('->', n, f)
        if quiet:
            return
        if note:
            log('-> %s (%d messages, %d bytes)' % (note, len(msgs), len(data)))
        else:
            for n, f in msgs:
                log('-> %s %s' % (n, P.fmt(f, 160)))

    def start_world(self):
        map_id = self.profile.d['position']['mapId']
        shared = CO.is_open() and str(int(map_id)) in SHARED and int(map_id) not in self.pve.maps   # friend server (shared_maps.py)
        self.world = World(self.profile, lambda m: self.send(m, quiet=True), log, map_id, TEMPLATE.station(map_id), keep_state=True,
                           test_near='--near-npc' in sys.argv or SET.get('nearby_npc'), on_jump=self.change_map, shared=shared)
        self.world.appearance = self.appearance
        self.world.is_group_member = lambda uid: uid in GR.members(self.profile.user_id)
        self.world.death = lambda: GR.died(TP.person(self.profile))
        if CO.is_open() and not shared:                                  # the player's own copy: the stored state is its own too
            self.world.cache_key = '%s:%s' % (map_id, self.profile.user_id)
        self.world.invulnerable = '--invulnerable' in sys.argv
        self.world.dark = int(map_id) in EKP.DARK_MAPS           # Trial of Terrors: flashlight
        self.world.quick_buy = self.shop.quick_buy_msgs
        self.world.auto_buy = self.shop.auto_buy                  # auto-buy CPUs (extras.py)
        self.world.auto_buy_fail = self.shop.auto_buy_fail
        self.world.auto_lab = self.shop.auto_lab                  # auto lab CPUs
        self.world.money_msgs = self.shop.money_msgs
        self.world.drone_msgs = self.shop.drone_msgs
        self.world.drone_item = self.shop.drone_item
        self.world.unit_msgs = lambda: (self.achievement.title_msgs() + self.shop.drone_msgs()
                                        + [self.shop.module_update(), self.profile.generate('@formasyon')])
        self.world.quest_event = self.quest_event
        self.world.lab_msgs = lambda: [self.shop.lab_cmd()]
        self.world.quest_list = self.quest.list_cmd
        self.world.stats_msgs = self.shop.apply_stats
        self.world.ore_pack = self.shop.ore_pack
        self.world.map_msgs = lambda: TEMPLATE.world_msgs(map_id, 'entry')
        self.world.on_home = self.respawn_home
        self.world.session_tick = self.tick                        # Assembly, Dispatch, Skylab timers
        self.world.grant = self.shop.reward                       # the equipment in an alien's extra reward (The Stinger: Caucasus)
        self.world.pet = self.pet
        self.pet.attach(self.world)
        self.world.gg_energy = self.gates.bonus_energy
        LAB.expire_keys(self.profile)                                     # if Frozen Labyrinth is over, the keys are deleted
        self.world.extra_gates = (self.gates.home_portals(map_id, TEMPLATE.station(map_id)) +     # gates prepared in X-1
                                  self.event_gates.entry_portals(map_id, TEMPLATE.station(map_id)) +  # event gates
                                  LAB.portals(map_id, self.gates.home()) +                    # the labyrinth's zone portals
                                  self.pve.portals(map_id, TEMPLATE.station(map_id)) +              # the modes' gates (stage 8)
                                  self.extra.portals(map_id, TEMPLATE.station(map_id)))                # Ö3: Fiesta Gate
        self.world.start()
        if int(map_id) in GALAXY.BY_MAP:
            with self.world.lock:
                self.world.gate = GALAXY.Run(self.gates, self.world, GALAXY.BY_MAP[int(map_id)])
        elif int(map_id) in EKP.BY_MAP:
            with self.world.lock:
                self.world.gate = EKP.Run(self.event_gates, self.world, EKP.BY_MAP[int(map_id)])
        elif int(map_id) in LAB.MAPS:
            with self.world.lock:
                self.world.labyrinth = LAB.Labyrinth(self.world)        # Frozen Labyrinth (labyrinth.py)
        with self.world.lock:
            self.pve.attach(self.world)                               # if it is a mode map, its run; CPU and windowed portals
            self.new_.attach(self.world)                              # N.O.V.A. (whether at the station), auto pilot (laser range)
            self.social.attach(self.world)                            # ship warp (station, combat, countdown)
            extra_msgs = self.extra.attach(self.world)                      # events of Ö3/Ö4: kill hooks, map runs
        if extra_msgs:
            self.world.send(extra_msgs)                                  # (it used to be ignored: the HUD stayed open after leaving Vortex)
        if int(map_id) == LOW.MAP:
            with self.world.lock:
                self.world.low = LOW.Low(self.world)              # LoW (single-player version, low.py)
        msgs = self.quest_event('map', map=int(map_id))
        comp = H.company(map_id)
        if (comp and comp != self.profile.d['pilot'].get('factionId')) or H.name(map_id).startswith('4-'):
            msgs += self.hint.show(IP.PVP_WARNING)   # another company's map or 4-X: PvP warning (once)
        if msgs:
            self.send(msgs, 'quest: map')
        self.profile.ach('map', map=int(map_id))       # achievement: discover the maps

    # ------------------------------------------------------------ quests
    def quest_map(self, map_id):
        """The map's quest giver and refinery for the quests' markers."""
        g = self.quest
        g.map_id, g.giver, g.trade = int(map_id), None, None
        for n, a in TEMPLATE.world_msgs(map_id, 'entry'):
            if n == 'AssetCreateCommand' and a['type']['typeValue'] == H.QUEST_GIVER:
                g.giver = (a['assetId'], a['posX'], a['posY'])
            if n == 'AssetCreateCommand' and H.STATION_ASSETS.get(a['type']['typeValue']) == 'ttip_ore_trade':
                g.trade = (a['posX'], a['posY'])

    def with_quests(self, msgs):
        """The profile's quests in place of the recorded quest messages in the login bundle; the profile's Assembly recipe list, Dispatch slots
        and Uridium Bank accumulation in place of the recorded ones."""
        self.quest_map(self.profile.d['position']['mapId'])
        out, done, asm, passes = [], False, False, set()
        present = {n for n, f in msgs}
        for n, f in msgs:
            if n == 'DispatchSlotInfoCommand':
                out.append(self.dispatch.slot_info())
                continue
            if n == 'EventUpdateCommand':             # the calendar's events (event_calendar.py)
                out.append(CAL.event_cmd())
                continue
            if n in ('NpcEventInfoCommand', 'NpcEventBossInfoCommand'):    # the Halloween indicator in the record: the map event sends it
                continue
            if n == 'ContactListInitializationCommand':  # directory from the profile (contacts.py)
                out.append(CT.login_cmd(self.profile))
                continue
            if n == 'DailyLoginRewardDayCommand' and self.daily.claimed_today():
                continue                              # today's reward was claimed: the calendar does not open at login (from the menu: DailyLoginRewardDayRequest)
            if n in ('HintWindowAddComand', 'HintWindowListInitCommand'):
                out += self.hint_msgs(n, f)           # closed hints do not reopen, they go to the archive
                continue
            rep = self.social.login_replace(n, f)     # chat address to the local server, unread mail (stage 10)
            if rep is not None:
                out += rep
                continue
            rep = self.new_.login_replace(n)          # N.O.V.A. roster, Evocation Chip, QFC list (stage 9): from the profile
            if rep is not None:
                out += rep
                continue
            rep = self.pve.login_replace(n)           # the modes' indicators (Eternal Black Light, Astral Ascension): from the profile
            if rep is not None:
                out += rep
                continue
            rep = self.extra.login_replace(n, f)         # events of Ö3 (extra_events.py)
            if rep is not None:
                out += rep
                continue
            group = PASS_LOGIN.get(n)                 # Season Pass, Battle Pass, daily rewards: from the profile (in place of the recorded ones)
            if group:
                if group not in passes:               # what stays in the bundle (windows come out on a map change and with --reklamsiz)
                    passes.add(group)
                    out += [m for m in {'season': self.season, 'ticket': self.ticket, 'reward': self.reward}[group].login_msgs()
                            if m[0] in present or PASS_LOGIN.get(m[0]) != group]
                continue
            code = str(f.get('message', '')).split('|')[2:3] if n == 'LegacyModule' else []
            if code and code[0] in LOOT.CODES:          # HUD counters of the loot keys (all 0 in the record; loot.py)
                out.append((n, dict(f, message=LOOT.key_line(self.profile, LOOT.CODES[code[0]]))))
                continue
            if n == 'UnstableModulesListCommand':
                out.append(GM.list_cmd(self.profile))
                continue
            if n == 'ShipUpgradeModuleUpdateCommand' and f.get('uid') == self.profile.user_id:
                out.append(self.shop.module_update())
                continue
            if n == 'UridiumBankInfoCommand':
                out.append(BANK.info_cmd(self.profile))
                self.bank_sent = BANK.value(self.profile)
                continue
            if n in ('QuestInitializationCommand', 'QuestListCommand'):
                if not done:
                    out += self.quest.login_msgs()
                    done = True
                continue
            if n == 'AssemblyRecipeContentModule':
                if not asm:
                    out += self.assembly.login_msgs()
                    asm = True
                continue
            out.append((n, f))
        return out

    def tick(self, now):
        """From the world loop (several times a second): timed systems (Assembly productions, Skylab upgrades and transports, Uridium
        Bank accumulation, calendar)."""
        if now >= self.cal_next:
            self.cal_next = now + 30.0
            self.season.tick(now)                      # Season Pass: day, week, season change
            cur = CAL.active(now)
            if cur != self.cal_sent:
                items = self.profile.event_window_items()
                if self.cal_sent is not None:
                    log('   calendar: %s' % ', '.join(sorted(cur)) or '-')
                    changed = [(n, f) for n, f in items if self.win_sent.get(f['itemId']) != f['visible']]
                    self.send([CAL.event_cmd(now)] + changed + CAL.mood_cmds(cur, self.cal_sent),
                              quiet=True)      # menu item (to be verified live: Ö1); map decorations
                    self.event_tips(now)
                self.win_sent = {f['itemId']: f['visible'] for n, f in items}
                self.cal_sent = cur
                ACV.set_events(achievement_groups(now))
        self.quest.tick(now)                          # timed quests
        if self.profile.d.get('booster_subscription') and now >= getattr(self, 'subscription_next', 0):
            self.subscription_next = now + 5.0
            msgs = self.shop.subscription_tick(now)     # booster subscription (forum 127558)
            if msgs:
                self.send(msgs, 'booster subscription')
        if now >= self.extra_next:
            self.extra_next = now + 1.0
            msgs = self.extra.tick(now)                  # events of Ö3: period ends, timed occurrences
            if msgs:
                self.send(msgs, 'event: time')
        if now >= self.social_next:
            self.social_next = now + 5.0
            msgs = self.social.tick(now)              # auction: items won in periods that have ended
            if msgs:
                self.send(msgs, 'auction: period end')
        self.assembly.tick(now)
        self.skylab.tick(now)
        if now >= self.bank_next:
            self.bank_next = now + 5.0
            if self.bank_sent is not None and BANK.value(self.profile) != self.bank_sent:
                self.bank_sent = BANK.value(self.profile)
                self.send([BANK.info_cmd(self.profile)], quiet=True)

    def quest_reward(self, loot, n):
        cur = {'currency_credits': 'credits', 'currency_uridium': 'uridium', 'currency_experience': 'ep', 'currency_honour': 'honor'}
        if loot in cur:
            cbs = self.profile.cbs_mods() if getattr(self.profile, 'cbs_mods', None) else {}
            if cur[loot] in ('ep', 'honor'):
                n = int(n * (1 + cbs.get(cur[loot], 0)))
            n = SET.amount(cur[loot], n, 'quest')           # the panel's reward multipliers
            tot = self.profile.gain(reason='quest_won', **{cur[loot]: n})
            pet = self.pet.gain_xp(n) if cur[loot] == 'ep' else []        # forum 127074: the P.E.T. also earns 5% of the quest EP
            return (self.world.reward_msgs(tot, **{cur[loot]: n}) if self.world else []) + (pet or [])
        return self.shop.prize(loot, n, 'quest')         # item reward: the panel's mode/quest reward multiplier

    def respawn_home(self):
        """Repair at the station on a map with no station: spawn at the station on the company's home map (X-1) (like the real game); at level 12+ and
        on higher maps (X-5 ... X-8, 4-4, 4-5) at the company's X-8 (map.x8_home)."""
        pl = self.profile.d['pilot']
        dest = H.x8_home(pl.get('factionId'), pl.get('level', 1), self.profile.d['position']['mapId']) or HOME_MAP.get(pl.get('factionId'), 5)
        st = TEMPLATE.station(dest)
        self.change_map(dest, None, pos=(st['posX'], st['posY']) if st else None)

    def revive_on_login(self):
        """If the player left the game while the ship was destroyed: free repair at the station (in the real game after leaving the repair at the portal
        and on the spot options are gone, the client's ttip_killscreen_logout_1 text)."""
        g = self.profile.d['ship']
        if g.get('hitPoints', 1) > 0:
            return
        k = self.profile.d['position']
        st = TEMPLATE.station(k['mapId'])
        if not st or st.get('type') != self.profile.d['pilot'].get('factionId'):        # no repair at the enemy base: its own home map
            pl = self.profile.d['pilot']
            k['mapId'] = H.x8_home(pl.get('factionId'), pl.get('level', 1), k['mapId']) or HOME_MAP.get(pl.get('factionId'), 5)
            st = TEMPLATE.station(k['mapId'])
        if st:
            k.update(x=st['posX'], y=st['posY'])
        k.pop('at_portal', None)
        self.profile.set_hull(hp=g.get('hitMax', 1), shield=g.get('shieldMax', 0))
        log('   left with the ship destroyed: repaired at the %s station' % H.name(k['mapId']))

    def change_map(self, dest, gate, pos=None):
        """Portal jump (the flow in the record): clear the old map, JumpToServerCommand + the new map's login bundle.
        If pos is given it lands there (respawn); otherwise next to the return portal at the destination."""
        if gate:
            self.profile.ach('jump')                   # achievement: portal jumps
        if gate and gate.get('event_gate'):
            self.event_gates.enter(gate['gate'])    # entering an event gate: the gate is set up (lives, wave order, time)
            dest = self.event_gates.dest(gate['gate'])     # the first map in the random order (Trial of Terrors)
        self.pve.on_jump(gate)                   # Astral's exit: the player's equipment back
        w0 = self.world                          # lock order the same as the world thread's (world.lock, then state_lock): from the packet
        with (w0.lock if w0 else contextlib.nullcontext()), self.state_lock:     # thread the reverse used to deadlock
            old = self.profile.d['position']['mapId']
            msgs = TEMPLATE.asset_removes(old)
            if self.world:
                msgs = self.world.cleanup_msgs() + msgs
                self.world.stop()
                self.world = None
            self.pet.attach(None)        # if active it comes out again on the new map
            pos = pos or (gate or {}).get('arrival')      # gate portals: to the middle of the gate map / next to the gate in X-1
            if pos == 'station':                        # jump CPU and the return home from a gate: to the destination's station (otherwise next to the portal)
                st = TEMPLATE.station(dest)
                pos = (st['posX'], st['posY']) if st else None
            if pos == 'random':                       # 5-3's exits go to a random place on 4-4 (map_layout.json)
                pos = H.random_arrival(dest)
            x, y = pos or H.arrival(old, dest, self.profile.d['pilot'].get('factionId'))
            self.profile.d['position'].update(mapId=dest, x=x, y=y, at_portal=pos is None)
            self.profile.dirty = True
            save_profile(self.profile)
            self.send(msgs + [('JumpToServerCommand', {})], quiet=True)
            self.map_pending = True      # before the login bundle: even if the client's ReadyRequest comes right away it does not slip through
            RT.daily_rank(self.profile)        # rank if the day changed (the client reads it only from ShipInitializationCommand)
            self.send(self.with_quests(login_batch('entry', first=False, profile=self.profile)),
                      'map change: %s -> %s, login bundle' % (H.name(old), H.name(dest)))
            self.profile.d['position'].pop('at_portal', None)

    def bind_login(self, f):
        """Friend server: the session's player from the sessionID of LoginRequest. The guest's session key (web.py gives it) or
        only from this computer the server's own player (web.py's SESSION). The same player's old connection is closed. -> whether connected."""
        sid = f.get('sessionID') or ''
        m = CO.find(sid)
        if m:
            old, m.session, m.last = m.session, self, time.time()
            if old is not None and old is not self:
                old.hand_over()
            self.guest = m
            self.bind(m.profile)
            self.social.chat_host = '%s:%d' % (m.address or self.addr[0], CHAT.port if CHAT else CO.CHAT_PORT)
            log('   guest login: %s (%s), id on the server %d' % (m.profile.d['pilot'].get('userName'), self.addr[0], m.uid))
            return True
        y = CO.find_local(sid) if self.addr[0] in ('127.0.0.1', '::1') else None
        if y:                                       # the multi-client's extra player (another record on this computer)
            old, y.session, y.last = y.session, self, time.time()
            if old is not None and old is not self:
                old.hand_over()
            self.local = y
            self.bind(y.profile)
            log('   extra client login: %s (record %s), id on the server %d' % (y.profile.d['pilot'].get('userName'), y.save, y.uid))
            return True
        if CO.is_local(sid) and self.addr[0] in ('127.0.0.1', '::1'):
            old = CURRENT
            if old is not None and old is not self:
                old.hand_over()
            self.bind(PROFILE)
            return True
        log('   login rejected: unknown session (%s)' % (self.addr,))
        return False

    def appearance(self, x, y):
        """This player's ship in the other players' clients (shared_maps.py): the other player's messages in the record
        (ShipCreateCommand, title, drones, ship modules)."""
        p = self.profile
        pl, g = p.d['pilot'], p.d['ship']
        import admin_mode as YM
        direction = YM.is_open(p)                     # admin: the badge and admin ship to the other players too
        create = ('ShipCreateCommand', dict(
            userId=p.user_id, typeId=(direction and YM.ship(p)) or g.get('typeId', 'ship_liberator'), expansionStage=p.d.get('expansion_stage', 1),
            clanTag=pl.get('clanTag', ''), userName=pl.get('userName', ''), x=x, y=y, factionId=pl.get('factionId', 0),
            clanId=pl.get('clanId', 0), dailyRank=YM.BADGE if direction else pl.get('dailyRank', 0), warnBox=False, clanDiplomacy=world.mod('ClanRelationModule', type=0),
            galaxyGatesDone=GALAXY.rings(p), useSystemFont=pl.get('useSystemFont', True), npc=False, cloaked=False,
            motherShipId=0, positionIndex=0, designSet='', modifier=[], minimapStrategyModule=world.mod('MinimapStrategyModule', minimapStrategy=0),
            specialNpcType=''))
        return [create] + self.achievement.title_msgs() + self.shop.drone_msgs() + [self.shop.module_update()]

    def on_packet(self, name, mid, f, err):
        if name == 'LoginRequest':
            P.secrets_of(f, self.secrets)
        if name not in UNLOGGED:
            log('<- %s(%s) %s%s' % (name, mid, P.fmt(P.redact(f, self.secrets), 300), ' [ERROR %s]' % err if err else ''))
        w = self.world
        if self.profile is None and name not in ('VersionRequest', 'LoginRequest', 'KeepAlive'):
            return                               # friend server: the player becomes known at login (bind_login)
        if name == 'VersionRequest':
            self.send([('VersionCommand', {'version': f['version'], 'equal': True})])
        elif name == 'LoginRequest':
            if self.profile is None and not self.bind_login(f):
                self.close()
                return
            self.revive_on_login()
            RT.daily_rank(self.profile)                     # daily rank (ShipInitializationCommand.dailyRank)
            self.send(self.with_quests(login_batch('entry', profile=self.profile)), 'login bundle')
            self.map_pending = True
        elif name == 'ReadyRequest' and (self.map_pending or (w and w.reload_pending)):
            with self.state_lock:      # touch the world outside the lock (a map change takes this lock from the world thread)
                self.map_pending = False
                start = self.world is None
                self.ready_n += 1
            # the Restabilize tab's list: in the record it comes separately after login and when the inventory changes, it is not in the login bundles;
            # since it was only put in place of the record in the bundle it never went, the tab said "No Items" (live test H69)
            unstable = [GM.list_cmd(self.profile)]
            self.send(login_batch('ready', profile=self.profile) + self.shop.login_msgs() + self.pet.login_msgs() + self.achievement.title_msgs()
                      + self.new_.login_msgs() + unstable + self.extra.login_msgs(), 'ready bundle')
            if start:
                self.start_world()
                self.achievement.sync()              # level, P.E.T. level, equipped items (those reached earlier also count)
                self.pass_event('login')         # "enter the game" quests (Unity reward; record: it finishes right after login)
                self.pass_event('level', value=self.profile.d['pilot'].get('level', 1))
                self.event_tips()                # description of the running event (once per period)
                group = GR.login_msgs(TP.person(self.profile))     # a member who returns after the connection dropped: the group and pending invitations (group.py)
                if group:
                    self.send(group, 'group: login')
            else:
                self.send(self.cbs.attach(self.world), 'CBS: map reloaded')
                self.world.resend()
            if self.ready_n > 1:                 # map loaded (portal, warp, respawn): the client rebuilds the menu
                self.extra.on_ready()               # (the Urgent Missions icon, urgent_quests.py)
            self.pet.on_ready()
        elif name == 'KeepAlive':
            self.send([('StayinAlive', {})], quiet=True)
        elif name == 'MoveRequest':
            log('<- MoveRequest position=(%d,%d) target=(%d,%d)' % (f['positionX'], f['positionY'], f['targetX'], f['targetY']))
            # Moves sent on the old map during a jump countdown or a map change must not overwrite the arrival position
            # (change_map sets it under state_lock, then builds ShipInitializationCommand from it).
            with self.state_lock:
                if w is not None and self.world is w and not w.jumping:
                    self.profile.apply(name, f)
            if w:
                w.on_move(f)     # outside state_lock: the world thread takes world.lock, then state_lock (change_map)
            # no reply: the real server does not send MoveCommand for the player's own movement (record: 0 for 876 requests). A MoveCommand that was sent
            # cut the client's "on arrival" job (HarvestRequest on reaching the ore).
        elif name == 'AttackAbortLaserRequest' and w:
            w.laser_stop()
        elif name == 'JumpRequest':
            if not (w and w.jump(f)):
                log('   no jump: not near a portal')
        elif name == 'QuestAcceptRequest':
            if w and not w.near_giver:
                # a quest can only be taken next to the quest giver (Mission Control); the client's text "Fly to Mission Control to see if
                # there are any missions for you."
                log('   quest not taken: far from the quest giver (%s)' % f.get('questId'))
                self.send([legacy('0|A|STM|msg_maybe_quest_at_nyx'), self.quest.list_cmd()], 'quest: far away')
            else:
                self.send(self.quest.accept(f.get('questId')) + self.quest_state_events(), 'quest: accept')
        elif name == 'QuestCancelRequest':
            self.send(self.quest.cancel(f.get('questId')), 'quest: cancel')
        elif name == 'QuestInfoRequest':
            self.send(self.quest.info(f.get('questId')), quiet=True)
        elif name == 'QuestPrivilegeRequest':
            self.send([('QuestPrivilegeCommand', {'questId': f.get('questId', 0)})], quiet=True)
        elif name in ('QuestSettingsRequest', 'QuestListRequest'):
            if name == 'QuestSettingsRequest':
                self.profile.apply(name, f)                 # the quest window's filter stays in the profile
            self.send([self.quest.list_cmd()], quiet=True)
        elif name == 'QuestGiverApproachedRequest':
            msgs = self.quest.event('giver') if w and w.near_giver == f.get('questGiverId') else []
            self.send(msgs or [self.quest.list_cmd()], 'quest giver')
        elif name == 'TradeRequest' and w:
            self.send([w.trade_info()], 'rafineri: fiyatlar')
        elif name == 'KillScreenRepairRequest' and w:
            w.kill_screen_repair(f)
        elif name == 'AchievementListRequest':
            self.send(self.achievement.request(f), 'achievements')
        elif name == 'SkillTreeListRequest':
            self.send([self.skill.list_cmd()], 'skill tree')
        elif name == 'ConvertResearchPointsRequest':
            self.send(self.skill.convert(), 'skill tree: pilot points')
        elif name == 'UpLevelSkillTreeRequest':
            self.send(self.skill.up_level(f), 'skill tree: level')
        elif name == 'ResetSkillTreeRequest':
            self.send(self.skill.reset(), 'skill tree: reset')
        elif name == 'DailyLoginRewardDayRequest':
            self.send([self.daily.info_cmd()], 'daily login: info')
        elif name == 'DailyLoginClaimTodayRequest':
            self.send(self.daily.claim(), 'daily login: reward')
        elif name == 'GalaxyGateBuilderInfoRequest':
            self.send(self.gates.info_request(), 'gate builder: info')
        elif name == 'GalaxyGateBuilderGetGatePartsRequest':
            self.send([self.gates.parts_cmd(f)], quiet=True)
        elif name == 'GalaxyGateBuilderMultiEnergyRequest':
            self.send(self.gates.spin(f), 'gate builder: spin')
        elif name == 'GalaxyGateBuilderSetupGateRequest':
            self.send(self.gates.setup(f), 'gate builder: prepare')
        elif name == 'GalaxyGateBuilderBuyLifeRequest':
            self.send(self.gates.buy_life(f), 'gate builder: lives')
        elif name == 'GalaxyGateBuilderSaveSpinAmountRequest':
            self.gates.save_spin(f)
        elif name == 'PetRequest':
            self.pet.request(f)
        elif name == 'PetGearActivationRequest':
            self.pet.gear_request(f)
        elif name == 'MapAssetActivationRequest':
            if self.cbs.handles(name, f):                # Clan Battle Station asteroid/station (Ö5): window data
                self.send(self.cbs.handle(name, f), 'CBS: pencere')
            # for a portal JumpRequest follows
        elif name == 'HangarShipActivateShipRequest':
            # only at the station as in the game; when the ship changes the client reloads the map with the new ship (like a respawn)
            k = self.profile.d['position']
            here = (k.get('mapId'), k.get('x'), k.get('y'))
            msgs, changed = self.shop.activate(f, in_station=w.in_station() if w else True, travel=True)
            self.send(msgs, 'hangar: activate ship')
            if changed and w:
                w.items.reveal()      # changing ship at the base ends the cloak CPU (fandom Cloak; except Ship Warp: ship_warp.py)
                if k['mapId'] != here[0]:                    # the new ship is waiting on another map: switch to it
                    self.change_map(k['mapId'], None, pos=(k['x'], k['y']))
                else:
                    w.reload_ship(pos=(k['x'], k['y']) if (k['x'], k['y']) != here[1:] else None)
        elif name == 'HangarShipChangeShipModelRequest':
            msgs, reload = self.shop.change_model(f)
            self.send(msgs, 'hangar: design')
            if reload and w:
                w.reload_ship()      # ShipInitializationCommand with the new appearance (the client reloads the map)
        elif name == 'LegacyModule':                  # old text protocol (legacy_protocol.py)
            key, parts = legacy_parse(f)
            if key == 'S|CFG' and len(parts) > 2:
                before = self.profile.d['ship'].get('speed')
                msgs = self.shop.switch_config(parts[2])
                if msgs and w:
                    with w.lock:           # a flight already under way takes the new config's speed at once
                        moves = w.respeed_flight(before)
                        if moves and w.shared:     # the session's send is not mirrored (World.send is): the others see the new pace too
                            w.shared.mirror(w, moves)
                    msgs += moves
                if msgs:
                    self.send(msgs, 'config switch')
            elif key == 'i' and len(parts) > 1 and parts[1].isdigit():
                if w:                                 # the client asks about an id it does not know (record: the real server sends it again)
                    w.info_request(int(parts[1]))
            elif key == 'JCPU' and CIT.has_ajp(self.profile):  # advanced jump CPU (AJP-01): the space map's jump panel
                if len(parts) > 1 and parts[1] == 'GET':
                    self.send([CIT.jcpu_list(self.profile), CIT.vouchers_msg(self.profile)], 'advanced jump list')
                elif w:
                    with w.lock:
                        w.items.jcpu(parts)
            elif key == 'XCP' and len(parts) > 1 and parts[1].isdigit() and w:
                with w.lock:                          # Palladium at the 5-2 trader -> gate energy: the client sends "XCP|<count>"
                    w.trade_palladium(int(parts[1]))  # (live trial 2026-10-17; TradeSellOreRequest does not come)
            elif key == 'AEQ' and len(parts) > 1:     # Settings > Gameplay "Auto-equip new items": client patch AutoEquip
                with self.profile.lock:                 # (the client's own box sends nothing)
                    self.profile.d['auto_equip'] = parts[1] == '1'
                    self.profile.dirty = True
            elif key in ('LF', 'JCPU'):
                pass                                  # LF|c, JCPU|GET at every login; the real server does not reply either (record)
            else:
                log('   unanswered: LegacyModule %s' % key)
        elif name == 'UIButtonTriggerRequest':
            item = f.get('itemId')
            self.windows.opened(item)
            if item == 'logout':
                self.logout_start()
            else:                                     # window opened notification (social.py): the ship warp window
                resp = self.social.window(item) + self.extra.window(item)       # Ö3: Pursuit of Prestige window ...
                if resp:
                    self.send(resp, 'pencere: %s' % item)
        elif name == 'HangarShipAutoBuyCpuAmmoRequest':   # ammo choice for the auto-buy CPU in the hangar
            self.send(self.shop.auto_buy_ammo(f), 'auto-buy ammo')
        elif name == 'HallOfFameTopRequest':
            self.send(RT.hof_top(self.profile, f), 'Hall of Fame: %s' % f.get('type'))
        elif name == 'HallOfFamePagesRequest':
            self.send(RT.hof_pages(self.profile, f), 'Hall of Fame page')
        elif name == 'HallOfFameDataListRequest':
            self.send(RT.hof_events(self.profile, f), 'Hall of Fame etkinlikleri')
        elif name == 'LogbookDataListRequest':
            self.send(RT.logbook(self.profile, f), 'seyir defteri')
        elif name == 'BalanceInfoListRequest':
            self.send(RT.balance(self.profile, f), 'account history')
        elif name == 'LogoutCancelRequest':
            self.logout_cancel()
        elif name == 'HintWindowClosedRequest':      # the real server does not reply (record); a closed hint must not open again
            c = (f.get('closedWindow') or {}).get('content')
            if c is not None and not f.get('wasOpenedFromArchive'):
                with self.profile.lock:
                    lst = self.profile.d.setdefault('hints_closed', [])
                    if c not in lst:
                        lst.append(c)
                        self.profile.dirty = True
        elif name == 'InternalPilotBioRequest':
            # an id not in the record (another player on the friend server): the card in the record becomes the template, the fields from their profile
            self.send(self.pilot_bio(TEMPLATE.response(name, f) or TEMPLATE.response(name, {}) or [], int(f.get('userId') or 0)), 'pilot card')
        elif name == 'InternalPilotBioUpdateRequest':
            with self.profile.lock:
                old = self.profile.d.get('pilot_bio', {})
                self.profile.d['pilot_bio'] = dict({k: v for k, v in f.items() if k not in ('_', 'userId')},
                                             **({'statusMessage': old['statusMessage']} if 'statusMessage' in old else {}))
                self.profile.dirty = True
            self.send([('InternalPilotBioUpdateResultsCommand', {'success': True, 'baseStackCommand': None})], 'pilot card: record')
        elif name == 'InternalPilotBioUpdateStatusRequest':          # status text on the pilot card (Ö1; UIPilotSheetSystem)
            with self.profile.lock:
                self.profile.d.setdefault('pilot_bio', {})['statusMessage'] = str(f.get('statusMessage') or '')[:STATUS_MAX]
                self.profile.dirty = True
            self.send([('InternalPilotBioUpdateResultsCommand', {'success': True, 'baseStackCommand': None})], 'pilot card: status')
        elif name == 'InternalPilotBioUpdateUserNameRequest':        # renaming in profile editing (Ö1; UIEditProfileSystem)
            self.send([self.rename(f.get('userName'))], 'pilot card: name')
        elif name == 'GroupInvitationBlockToggleRequest':
            with self.profile.lock:                         # record: opened and closed on every request
                self.profile.d['invite_block'] = not self.profile.d.get('invite_block', False)
                self.profile.dirty = True
            self.send([('InvitationBlockModule', {'active': self.profile.d['invite_block']})], 'group invitation block')
        elif name in GR.REQUESTS:
            # group (group.py): other players on the friend server; in single player there is nobody (invite: error 2 CANDIDATE_NONEXISTENT)
            resp = GR.handle(TP.person(self.profile), name, f)
            if resp:
                self.send(resp, 'group: %s' % name)
        elif name in CT.REQUESTS:                                    # the contacts tab of the contacts and mail window (contacts.py)
            resp = CT.handle(TP.person(self.profile), name, f)
            if resp:
                self.send(resp, 'rehber: %s' % name)
        elif name == 'CommandCenterNewsClickedRequest':              # a click on news (E8; it has no reply): the counter in the profile
            with self.profile.lock:
                c = self.profile.d.setdefault('news_read', {})
                c[str(f.get('newsId'))] = c.get(str(f.get('newsId')), 0) + 1
                self.profile.dirty = True
        elif name == 'CommandCenterNewsInfoRequest':                 # click counts of the client's news (calendar.news)
            c = self.profile.d.get('news_read', {})
            ids = [dict(_='CommandCenterNewsModule', eventId=x.get('eventId', 0), newsId=x['newsId'], clickCount=c[x['newsId']])
                   for x in f.get('newsInfo') or [] if c.get(x.get('newsId'))]
            self.send([('CommandCenterInfoCommand', {'ids': ids})], 'Command Center: %d haber' % len(f.get('newsInfo') or []))
        elif name in SILENT:
            if name == 'EggTriggerRequest' and 0 <= f.get('eggTriggerType', -1) < len(EGG_TYPES):
                self.profile.ach('egg', type=EGG_TYPES[f['eggTriggerType']])     # hidden achievements (EVENT_SECRET); it has no reply
        elif name.startswith(('Assembly', 'Disassembly', 'Dispatch', 'Skylab')):
            sysm = self.assembly if name.startswith(('Assembly', 'Disassembly')) else self.dispatch if name.startswith('Dispatch') \
                else self.skylab
            resp = sysm.handle(name, f)
            if resp is None:
                log('   unanswered: %s' % name)
            elif resp:
                self.send(resp, '%s: %s' % (name.split('Request')[0], name))
        elif name.startswith(('SeasonPass', 'BattlePass')) or name in DRW_REQUESTS:
            sysm = self.season if name.startswith('SeasonPass') else self.ticket if name.startswith('BattlePass') else self.reward
            resp = sysm.handle(name, f)
            if resp is None:
                log('   unanswered: %s' % name)
            elif resp:
                self.send(resp, name.split('Request')[0])
        elif name.startswith('UnstableModule') or name == 'RerollWindowSettingsRequest':
            resp = self.modules.handle(name, f)
            if resp:
                self.send(resp, 'Restabilize: %s' % name)
        elif name == 'RankRewardRequest' and RK.reward(f) is not None:     # ranking reward tables (Ö1; ranking_rewards.py)
            self.send(RK.reward(f), 'ranking rewards')
        elif name in GMC.REQUESTS:                                          # GM console (Ö2; gm_console.py)
            self.send(self.gm.handle(name, f), 'GM console: %s' % (f.get('name') or name))
        elif name == 'EvoucherHistoryListRequest':                          # the coupon window's history: there is no code decoding locally (Ö1)
            self.send([('EvoucherHistoryListCommand', {'list': []})], 'voucher history')
        elif name == 'UridiumBankClaimRequest':
            before = self.profile.d['pilot'].get('uridium', 0)
            self.send(BANK.claim(self.profile, self.shop.money_msgs, log), 'Uridium Bank')
            self.bank_sent = BANK.value(self.profile)
            if self.profile.d['pilot'].get('uridium', 0) > before:
                self.pass_event('recharge')                # single player: the Unity reward's "top up" quest (a payment in the real game)
        elif self.shop.handles(name, f):
            resp = self.shop.handle(name, f)
            if resp is None:
                resp = TEMPLATE.response(name, f)
            if resp:
                self.send(resp, 'shop/hangar: %s' % name)
            if w and name == 'HangarShipMoveItemsRequest' and w.repairing and not w.repair_rate():
                w.stop_repair()          # repair robot removed
            if name == 'HangarShipMoveItemsRequest':
                self.profile.ach('sync')       # achievement: equipped items (Champion/Beacon design)
        elif name == 'SlotBarConfigSetRequest':
            tpl = next((m for m in TEMPLATE.entry.get('ready', []) if m['_m'] == 'MenuInitializationCommand'), None)
            if tpl and self.profile.slot_bar_set(f, tpl['slotBars']):
                self.send([('MenuInitializationCommand', self.profile.patch_template('MenuInitializationCommand', tpl))]
                          + self.quest.event('slot_bar', **self.profile.slot_bar_state(tpl['slotBars'])), 'shortcut bar')
        elif name in PVM.REQUESTS:
            self.send(self.pve.handle(name, f), 'mod: %s' % name)      # stage 8's modes (pve_modes.py)
        elif name == 'ChangeClanFirmaRequest':                         # switching company (clan.switch_company): the new company's X-1
            msgs, home = self.social.clan.switch_company(f)
            self.send(msgs, 'company change')
            if home:
                if self.profile is PROFILE:
                    H.PLAYER_FACTION = self.profile.d['pilot'].get('factionId')
                st = TEMPLATE.station(home)
                self.change_map(home, None, pos=(st['posX'], st['posY']) if st else None)
        elif name in SO.REQUESTS:
            resp = self.social.handle(name, f, time.time())             # stage 10: the social part (social.py)
            if resp:
                self.send(resp, 'sosyal: %s' % name)
        elif name in NS.REQUESTS:
            resp = self.new_.handle(name, f)                           # stage 9's systems (new_systems.py)
            if resp:
                self.send(resp, 'yeni sistem: %s' % name)
        elif self.extra.handles(name):
            resp = self.extra.handle(name, f)                             # events of Ö3 (extra_events.py)
            if resp:
                self.send(resp, 'event: %s' % name)
        elif name in WORLD_REQUESTS and w:
            getattr(w, WORLD_REQUESTS[name])(f)
        elif self.profile.apply(name, f):
            log('   profile written: %s' % name)
            if name == 'DisplaySettingsRequest':
                self.profile.ach('display', use2d=f.get('displayUse2d'))      # achievement: 3D view (Uses3D)
                # SaveInterfaceSettingsTab changes flags, but the client only applies toolbar visibility on UIBag refresh.
                tpl = next((m for m in TEMPLATE.entry.get('ready', []) if m['_m'] == 'MenuInitializationCommand'), None)
                if tpl:
                    self.send([('MenuInitializationCommand', self.profile.patch_template('MenuInitializationCommand', tpl))],
                              'UI: shortcut bars')
            if name == 'UIWindowUpdateRequest':
                if f.get('maximized'):
                    self.windows.opened(f.get('itemId'))
                if 'trade' in str(f.get('itemId')) and not f.get('maximized') and w:       # trade window closed (P.E.T. cargo trader)
                    with w.lock:
                        self.pet.trade_close(time.time())
                resp = self.extra.window_update(f)        # window opened/closed (those that do not send UIButtonTriggerRequest)
                if resp:
                    self.send(resp, 'pencere: %s' % f.get('itemId'))
        else:
            resp = no_popups(TEMPLATE.response(name, f) or [])
            if resp:
                self.send(resp, 'recorded reply: %s' % name)
            elif name != 'ReadyRequest':
                log('   unanswered: %s' % name)

    def run(self):
        log('connect %s' % (self.addr,))
        fr = P.Framer(client_side=True)
        last_save = time.time()
        try:
            while True:
                d = self.c.recv(65536)
                if not d:
                    break
                for pkt in fr.feed(d):
                    mid, name, f, left, err = P.decode_message(pkt)
                    if CONTROL:
                        CTL.TRACE.add('<-', name, f)
                    with self.packet_lock:
                        try:                      # one request's error must not bring down the session: the stack trace to the log, the client stays connected
                            self.on_packet(name, mid, f, err)
                        except ConnectionError:
                            raise
                        except Exception:
                            log('   request error (%s):\n%s' % (name, traceback.format_exc()))
                    if time.time() - last_save > 10:
                        last_save = time.time()
                        self.play_time()
                        save_profile(self.profile)
        except ConnectionError as e:
            log('   connection closed: %r' % e)
        except Exception:
            log('error\n%s' % traceback.format_exc())
        if self.world:
            self.world.stop()
        if self.profile is not None:
            self.play_time()
            save_profile(self.profile)
            if not any(s is not self and s.profile is self.profile for s in list(SESSIONS)):
                CT.forget(self.profile.user_id)              # at the next login the contact list is sent from scratch
        log('disconnect %s' % (self.addr,))
        global CURRENT
        if CURRENT is self:
            CURRENT = None
        SESSIONS.discard(self)
        if self.queue:                              # let what is in the queue go, then the socket closes (when it did not close the thread + socket leaked)
            self.queue.close()
            self.queue.thread.join(5)
        try:
            self.c.close()
        except OSError:
            pass
        m = self.guest
        if m is not None and m.session is self:      # the guest's final state is published (the panel takes it); can reconnect
            self.profile.save(force=True)
            m.session, m.last = None, time.time()
        y = self.local
        if y is not None and y.session is self:      # extra player: continues when its client is reopened; leaves the record when the panel lets go
            with CO.COND:
                y.session, y.last = None, time.time()
                if y.finished:
                    CO.LOCAL_PLAYERS.pop(y.session, None)

    def payment_click(self):
        """The client's payment button (payment.Listener: connected to 127.0.0.1:443): the shop opens at Extras, the product is written on screen."""
        msg = self.windows.offline()
        if msg:                                       # coupon code or image upload: the shop does not open
            log('   443: non-payment request -> %s' % msg)
            with self.packet_lock:
                self.send([GALAXY.screen(msg)], '443: ekran metni')
            return
        item = self.windows.guess()
        log('   payment button -> shop (last window: %s)' % (item or '-'))
        with self.packet_lock:
            self.send(PAY.redirect(self.shop, item), 'payment button: shop')

    def inject(self, name, f):
        """Control channel: a request as if the client sent it ('<=' in the trace)."""
        CTL.TRACE.add('<=', name, f)
        log('<= (control) %s' % name)
        with self.packet_lock:
            self.on_packet(name, -1, f, None)


def handle(c, addr):
    """New connection. On the friend server (--multiplayer) the first bytes are looked at first: if HTTP, the guest's account submission
    (multiplayer.http), otherwise the game client (its player becomes known at login; with a send queue)."""
    if not CO.is_open():
        Session(c, addr).run()
        return
    try:
        c.settimeout(20)
        first, end = b'', time.time() + 20
        while len(first) < 4 and time.time() < end:
            first = c.recv(4, socket.MSG_PEEK)
            if not first:
                c.close()
                return
            if len(first) < 4:
                time.sleep(0.05)
        c.settimeout(None)
    except OSError:
        c.close()
        return
    if CO.is_http(first):
        CO.http(c, addr, sys.modules[__name__])
    else:
        Session(c, addr, wait=True, queue=True).run()


def close_session(s):
    s.close()


def payment_session(addr):
    """The session of the client that pressed the payment button: with a single session (or if the process is not found) the server's own player's; with multiple
    clients the connecting process is matched with the sessions' clients (payment.connecting_pid; the game connection is on 8081)."""
    sessions = [s for s in list(SESSIONS) if s.profile is not None]
    if len(sessions) > 1:
        pid = PAY.connecting_pid(addr, PAY.PORT)
        for s in sessions if pid else []:
            if s.client_pid is None:
                s.client_pid = PAY.connecting_pid(s.addr, 8081)
            if s.client_pid == pid:
                return s
    return CURRENT


def payment_clicked(addr):
    s = payment_session(addr)
    if s is not None:
        s.payment_click()


def server_info():
    """GET /misafir/bilgi: shown to the guest's panel before connecting (the server's pilot, players, password, place, versions)."""
    ms = CO.entries()
    names = sorted({s.profile.d['pilot'].get('userName', '?') for s in list(SESSIONS) if s.profile is not None})
    try:
        client = open(os.path.join(DATA, 'protocols', 'version.txt'), encoding='utf8').read().strip() or '1.1.116'
    except OSError:
        client = '1.1.116'
    client = max(client, '1.1.116', key=lambda v: tuple(int(x) for x in v.split('.')))     # version.txt may be stale after an update
    # 'sunucu', 'protokol' and X-DarkOrbit: this is the friend version negotiation, old panels read it too: does not change
    return {'sunucu': 'darkorbit', 'protokol': CO.PROTOCOL, 'code': CO.SETTINGS['code'], 'client': client,
            'pilot': PROFILE.d['pilot'].get('userName', ''), 'players': names, 'guest': len(ms), 'max_count': CO.SETTINGS['max_count'],
            'password': bool(CO.SETTINGS['password']), 'place': len(ms) < CO.SETTINGS['max_count']}


def watch_world():
    """World Editor: when the world file changes while the game is open the shop's prices and the auction's lots are refreshed (data.LIVE);
    other changes when the server restarts (the panel notifies)."""
    import auction as MZ
    while True:
        time.sleep(2)
        try:
            changed = GD.refresh()
            if 'shop' in changed:
                SHP.refresh()
            if 'social.json' in changed:
                MZ.refresh()
            if changed:
                log('world updated live: %s' % ', '.join({'shop': 'shop', 'social.json': 'auction'}[d] for d in changed))
        except Exception:
            log('could not watch the world: %s' % traceback.format_exc())


def autosave():
    """The profile to disk every 10 s (if changed). The session used to save only when a packet came from the client: the last change made while idle
    (closing a window, control channel, NPC reward) was lost if the server window was closed (live test H57).
    --stop-file=<file> (panel): when the file appears play time and the profile are saved, the server closes (so the last 10 s are not lost on a forced close)."""
    last = time.time()
    while True:
        time.sleep(0.5 if STOP else 10)
        if STOP and os.path.exists(STOP):
            stop_gracefully()
        if time.time() - last < 10:
            continue
        last = time.time()
        save_profile()                    # if the file is locked, the next round
        for s in list(SESSIONS):         # friend server: the guests' records (go to the new version panels)
            if s.profile is not None and s.profile is not PROFILE:
                save_profile(s.profile)
        if CO.is_open():
            CO.tick(close_session)


def stop_gracefully():
    """The panel's stop request: the session's play time and the profile are saved, the process exits."""
    try:
        if CURRENT is not None:
            CURRENT.play_time()
        PROFILE.save(force=True)
        BOT.close()                       # bot paketinin durumu
        if CO.is_open():                     # the guests' final state is given to their panels (to pending polls), the extra players' to their slots
            for s in list(SESSIONS):
                if s.guest is not None or s.local is not None:
                    s.play_time()
            for y in CO.local_players():
                save_profile(y.profile)
            CO.shutdown()
        log('panel: stop request, profile saved, server shutting down')
    except Exception as e:
        log('panel: save error while stopping %r' % e)
    try:
        os.remove(STOP)
    except OSError:
        pass
    os._exit(0)


def main():
    global CHAT
    if PTH.MIGRATION_ERROR:                                # the records could not be moved to the new format: it does not half-open with the old format
        sys.exit('save migration failed: %s' % PTH.MIGRATION_ERROR)
    P.warning = log
    SET.configure()              # game settings (panel): --settings=<path> or save/settings.json; re-read by itself when changed
    log('settings: %s | %s' % (SET._state['route'], ', '.join('%s %s' % x for x in SET.summary()) or 'default'))
    log(GD.summary())             # the World Editor's world (OO_WORLD; data.py)
    address = '127.0.0.1'
    if '--multiplayer' in sys.argv:  # friend server: game and chat from all networks (multiplayer.py); settings in the environment variable
        CO.configure(os.environ.get('OO_MULTIPLAYER'), log)
        address = CO.SETTINGS['address']
        KL.configure(os.path.join(PTH.SAVE, 'clans.json'))     # shared clans: what happened to an offline member applies at the next login
    CHAT = CHT.Chat(log, address=address)
    CHAT.start()                # local chat (7771); the client connects here with ChatParamCommand at login
    if os.environ.get('OO_BOT'):
        BOT.server(os.environ['OO_BOT'], log)     # the Bots page's pack (assigned to the world)
    threading.Thread(target=autosave, daemon=True).start()
    if os.environ.get('OO_WORLD'):
        threading.Thread(target=watch_world, daemon=True).start()
    CD.start(sys.modules[__name__], LOG_DIR, log)     # the panel's live state page (<logs>/live_status.json)
    PCH.start(sys.modules[__name__], LOG_DIR, log)     # the panel's in-game menus (Shop, Hangar, Skylab, Auction): local channel
    if CONTROL:
        CTL.Control(sys.modules[__name__]).start()
        CHAT.trace = CTL.chat_trace          # chat frames are in the trace too ("Chat:<type>")
    PAY.Listener(payment_clicked, log).start()     # payment buttons -> shop (127.0.0.1:443)
    s = socket.socket()
    if CO.is_open() and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)    # Windows: so another process cannot take over the same port
    else:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((address, 8081)); s.listen(16)
    log('gs listening %s:8081 | profile: %s %s map %s | template: %s%s%s' % (
        address, PROFILE.d['pilot'].get('userName'), PROFILE.d['ship'].get('typeId'), PROFILE.d['position']['mapId'],
        TEMPLATE.entry.get('source', 'none'), ' | profile file: %s' % PROFILE.path if PROFILE_PATH else '',
        (' | friend server: at most %d guests%s' % (CO.SETTINGS['max_count'], ', encrypted' if CO.SETTINGS['password'] else '')
         if CO.SETTINGS['guest'] else ' | multi-client (this computer only)') if CO.is_open() else ''))
    while True:
        c, addr = s.accept()
        threading.Thread(target=handle, args=(c, addr), daemon=True).start()


if __name__ == '__main__':
    main()
