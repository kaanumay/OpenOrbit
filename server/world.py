"""Map world (one world per connection): NPCs, movement, AI, laser/rocket combat, death, rewards, cargo and bonus
boxes. On the friend server the worlds of players on the same normal map share aliens, boxes and ores (shared_maps.py).

Message flows from the real server recording (belgeler/istemci/kayit_analizi.md, "In-game patterns"):
  select  ShipSelectRequest -> ShipSelectionCommand (updated after hits)
  laser   AttackLaserRequest -> every ~1.1 s AttackLaserRunCommand + AttackHitCommand(attackType 1) | AttackMissedCommand
  rocket  AttackRocketRequest -> "0|v|<attacker>|<target>|H|1|<trail>|<homing>" + 4 s cooldown, ~0.8 s later AttackHitCommand(attackType 0)
  death   AttackHitCommand(hp 0) + ShipDestroyedCommand + ShipDeselectionCommand + ShipRemoveCommand
  reward  "0|LM|ST|EP|<gain>|<total>|<level>", HON, CRE (+ InventoryItemUpdatedCommand), URI
  box     AddBoxCommand(FROM_SHIP) at the death spot (in the CandyCargo event, Halloween, CANDY_CARGO: the same box, candy look; recording; TURKEY_CARGO at Thanksgiving);
          CollectBoxRequest -> RemoveCollectableCommand(collected) + ore log. The event's 'no_cargo' aliens do not drop one
  ore     AddOreCommand (in clusters); HarvestRequest -> ~0.5 s later InventoryItemPack + MapEventOreCommand(1) +
          AttributeOreCountUpdateCommand + RemoveCollectableCommand(collected); if the cargo is full MapEventOreCommand(2)
  sale    MapAssetActionAvailableCommand when approaching the station refinery; TradeRequest -> OreTradeInfoCommand;
          TradeSellOreRequest -> AttributeOreCountUpdateCommand + "0|LM|ST|CRE|gain|total" + credits
  P.E.T.  pet.py (ticked from the world loop; NPC shots sometimes go to the P.E.T.; the P.E.T.'s hits and the boxes it collects are handled here)
  gates   galaxy_gates.py (gate portals in X-1 via add_gate; on a gate map the waves run from the world loop, gate NPCs do not respawn)
  player  ShipDestroyedCommand + KillScreenPostCommand (death screen; not in the recording, fields and option types from the client's code)
          KillScreenRepairRequest -> ShipInitializationCommand (repair at the station / portal / on the spot)
Numeric values come from data/npc.json, repair prices from data/items.json (death_screen).
"""
import json, math, os, random, re, string, threading, time, traceback, weakref
import game_data as DATA

import map_links as H
import map_layout as ML
import booster as BOOSTER
import ship_ability as SA
import status_effects as STATE
import extras as EX
import lasers as LASERS
import combat_items as CIT
import technology as TECH
import mimesis_chest as MCH
import particle as PC
import ranks as RT
import alien as ALN
import event_maps as EVT  # noqa: E402
import event_calendar as CAL          # noqa: E402
import loot as LOOT
import settings as SET
import admin_mode as YM
import upgrades as UPG
import tips as IP
import shared_maps as OH
import skill_tree as SKL
import player_combat as PVP

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = DATA.load('npc.json')
ITEMS = DATA.load('items.json')        # the world's ores (World Editor: ores.maps, respawn_sec)
COMBAT = CFG['combat']
MAP_W, MAP_H = CFG['map_size']
CREDITS_ITEM, URIDIUM_ITEM = -1908845164, -707736347      # InventoryItemModule.itemId values in the recording
# on-screen lines for the kill reward and their texts in the client (flashres: "You received %! EP." …); at most this often on screen (kill_notice)
REWARD_LINES = ('0|LM|ST|EP|', '0|LM|ST|HON|', '0|LM|ST|CRE|', '0|LM|ST|URI|')
REWARD_LINES_KEYS = {'EP': 'getexp', 'HON': 'gatherep', 'CRE': 'getcredits', 'URI': 'geturidium'}
NOTICE_GAP_SEC = 0.5
LASER_AMMO = 'ammunition_laser_lcb-10'
DEATH = ITEMS['death_screen']
# the client's KillScreenOptionTypeModule.OptionType enum (global-metadata.dat)
RAPID_AMMO, RAPID_VOLLEYS, RAPID_STEP = 'ammunition_laser_rsb-75', 4, 0.5     # RSB-75 salvo: pulse laser (laserColor 6, sound 32 laser6_0 1.23 s) 4 commands x 0.5 s (the user's official game video)
REPAIR_BASE, REPAIR_GATE, REPAIR_LOCATION, REPAIR_RAID_GATE = 1, 2, 3, 7
# option -> (detail text, hint, button): the client's translation keys (flashres)
REPAIR_TEXTS = {REPAIR_BASE: ('desc_killscreen_free_repair_cause_unknown', 'ttip_killscreen_basic_repair', 'btn_killscreen_repair_for_free'),
                REPAIR_GATE: ('desc_killscreen_repair_gate', 'ttip_killscreen_repair_jumpgate', 'btn_killscreen_repair_for_uri'),
                REPAIR_LOCATION: ('desc_killscreen_repair_location', 'ttip_killscreen_repair_location', 'btn_killscreen_repair_for_uri'),
                REPAIR_RAID_GATE: ('desc_killscreen_free_repair_cause_hadesgate', 'ttip_killscreen_repair_hadesgate',
                                   'btn_killscreen_repair_for_free')}
COLLECT_WAIT_SEC = 8            # adaptation: a clicked box is collected if the ship arrives within this many seconds (the server's ship can lag behind with accelerators)
HADES_RESPAWN_SEC = 30          # respawn time on a gate map in Hades (wiki: when someone with HP left dies, within 30 s at the gate or in X-1)
DESTRUCTION_NPC, DESTRUCTION_RADIATION, DESTRUCTION_MISC = 1, 2, 4       # DestructionTypeModule.DestructionCause
# the entrance of 5-4 (wiki: one Silver Booty Key; the key's Assembly recipe is 25 Darksilver Coin, assembly.py)
KEY_COST = [('resource_booty-key-silver', 1)]
WORMHOLE_ID = H.GATE_ID_BASE + 990100        # the hidden wormhole in 4-5 (to the Cubikon Graveyard)
DRONE_LEVELS = ITEMS['drone_levels']
ORE = ITEMS['ores']
ORE_EVENT_FINISHED, ORE_EVENT_CARGO_FULL = 1, 2       # MapEventOreCommand.EventType (client)
TRADE_INACTIVE, TRADE_STATION, TRADE_DRONE, TRADE_PET, TRADE_PIRATE = 0, 1, 2, 3, 5     # OreTradeInfoCommand.TradeType (client)
PIRATE_PRICE = 1.05
PALLADIUM, PIRATE_MARKET = 8, '92'          # Palladium is converted to gate energy only at the pirate trader in 5-2


def ore_prices(honor):
    """Refinery sale prices: base + honor/divisor, capped (wiki; the recording gives the base prices)."""
    out = {}
    k = SET.multiplier('ore_price')                    # panel: ore sale price (the window shows this too)
    for t, (base, div, cap) in ORE['prices'].items():
        v = min(cap, base + (int(honor // div) if div else 0))
        out[int(t)] = v if k == 1.0 else min(SET.I32, max(0, int(round(v * k))))
    return out
DRONE_POINTS = ITEMS['drone_points']
INVINCIBILITY = 33                             # VisualModifierCommand.modifier (the client's VisualModifier enum)
# the miss given by Evasive Maneuvers (AttackMissedCommand.skillColorId -> the color of DamageReceivedEffect; game.xml hitpointColors:
# 3 0066CC blue). Official FAQ: with the evasion skill misses are blue instead of purple
EVADE_COLOR = 3
STREAK_GAP_SEC = 10.0                           # kill streak: the most between two kills (kill_streak)
STREAKS = [(3, 'epic_msg_killstreak_triplekill'), (6, 'epic_msg_killstreak_unstoppable'), (10, 'epic_msg_killstreak_godlike'),
           (15, 'epic_msg_killstreak_likeaboss')]
FLASHLIGHT = 62                                # flashlight: the screen goes dark, the direction the ship faces is lit (FlashLightEffect, effect 90)


def mod(name, **f):
    f['_'] = name
    return f


REPAIR_VOUCHERS = 10             # coupon cost of an instant repair at the repair station (official forum 127572/127585: 10 coupons)
# CombatStateCommand.combatState (the client's CombatStateType; Ö1)
COMBAT_OUT_OF_RANGE, COMBAT_CONTINUES, COMBAT_ESCAPED = 0, 1, 2


def range_exceeded(uid, max_range, kind):
    """Out of range: the client shows a range effect on the target (AttackRangeExceededCommand; type 0 rocket, 1 laser)."""
    return ('AttackRangeExceededCommand', {'uid': uid, 'maxRange': int(max_range), 'type': kind})


# auto-switch order when ammo runs out (ordinary ammo in order; it does not switch to special ammo on its own)
AUTO_AMMO = ['ammunition_laser_ucb-100', 'ammunition_laser_mcb-50', 'ammunition_laser_mcb-25', 'ammunition_laser_lcb-10']
BLOCKED_BOX = 'FROM_SHIP_BLOCKED'   # client: another player's cargo box (shows blue if Settings > other players' cargo boxes is on)
TAG_SEC = 15.0                    # the tag drops if the tag owner does not hit for this long


def tag_alien(n, who, now):
    """An alien was fired at: if it has no tag (or it dropped), the shooter tags it; every hit by the owner refreshes the tag.
    who: ('h', hero id) or ('b', bot id)."""
    t = getattr(n, 'tag', None)
    if t is None or t[0] == who or now - t[1] > TAG_SEC:
        n.tag = (who, now)
    elif who[0] == 'h' and t[0][0] == 'b' and SET.get('player_tag') and not group_npc(n):
        n.tag = (who, now)                                  # the player takes the bot's tag (panel: player_tag)


def group_npc(n):
    """An alien fought together (world bosses that drop a chest, like Mindfire Behemoth, Invoke XVI; npc.json shared: Cubikon, Ice
    Meteoroids, Hitac): while the panel's group_split is on, the tag does not pass and the reward is split by damage dealt; when off it
    is an ordinary alien (the tagger gets everything: levelling up a friend). Before, the split needed player_tag (off by default) and
    did not cover the meteoroids and Hitac (player report 2026-11-02)."""
    return bool(SET.get('group_split') and (n.d.get('shared') or n.d.get('chest') or n.d.get('boss')
                                            or str(getattr(n, 'tip', '')).startswith('wb_')))


def record_damage(n, who, dmg):
    """The damage dealt to a group alien by who ('h', hero) or ('b', bot): reward sharing (tag_sharers)."""
    if dmg > 0 and group_npc(n):
        d = n.__dict__.setdefault('damage_split', {})
        d[who] = d.get(who, 0) + dmg


def tag_owner(n, now):
    """The alien's valid tag (the reward, quest and cargo box are theirs) or None (no tag, dropped, or turned off in the panel)."""
    t = getattr(n, 'tag', None)
    return t[0] if t is not None and now - t[1] <= TAG_SEC and SET.get('tag') else None


CARGO_BOXES = ('FROM_SHIP', 'CANDY_CARGO', 'TURKEY_CARGO')     # the alien's cargo box (CANDY_CARGO: in Halloween's CandyCargo, recording; TURKEY_CARGO: at Thanksgiving)
AUTO_REFINE = (4, 5, 6)       # products of automatic refining (laboratory recipes, in this order): Prometid, Duranium, Promerium


def attack_type(v):
    return mod('AttackTypeModule', attackTypeValue=v)   # 0 rocket, 1 laser, 3 radiation (the client's AttackType enum)


from legacy_protocol import legacy, stm  # noqa: E402,F401  (old text protocol: legacy_protocol.py)


def halloween_boss(d):
    """The boss that appears as a ghost at Halloween (Boss in its name; including Boss Curcubitor)."""
    return 'Boss' in d.get('name', '')


# achievement "laser show" (LaserTypeUsage 1-6): the client's order of basic laser ammo (adaptation: LCB-10 … RSB-75)
AMMO_TYPE_IDS = {'ammunition_laser_lcb-10': 1, 'ammunition_laser_mcb-25': 2, 'ammunition_laser_mcb-50': 3, 'ammunition_laser_ucb-100': 4,
                 'ammunition_laser_sab-50': 5, 'ammunition_laser_rsb-75': 6}


def loc(key, **wild):
    """Text shown from the client's own translation file: MessageLocalizedWildcardCommand (format in the recording: key type 5,
    %AD% placeholders plain text 0)."""
    return mod('MessageLocalizedWildcardCommand', baseKey=key, baseKeyType=mod('ReplacementTypeModule', typeValue=5),
               wildCardReplacements=[mod('MessageWildcardReplacementModule', wildcard='%%%s%%' % k, replacement=str(v),
                                         replacementType=mod('ReplacementTypeModule', typeValue=0)) for k, v in wild.items()])


CLIENT_TWEEN = 1.05      # the client plays every movement in 1.05 times the sent duration (Mover)


class Mover:
    """Linear movement: the current position from start-end and duration. The client plays both MoveCommand and its own ship's travel in 1.05
    times the duration (MoveComponentSystem.MoveToAsync → linear DOMove(duration * 1.05)); the movement on the server takes that long too,
    and the timeToTarget sent to the client is the duration derived from speed (go, ms_left). Before, the server's ship and aliens moved 5% ahead of
    what was drawn (live measurement 2026-10-24: 562 fast ship 535 units/s; the P.E.T. overtook the ship on a long trip, H216)."""

    def __init__(self, x, y):
        self.x0 = self.x1 = x
        self.y0 = self.y1 = y
        self.t0 = self.t1 = 0.0

    def pos(self, now):
        if now >= self.t1 or self.t1 <= self.t0:
            return self.x1, self.y1
        f = (now - self.t0) / (self.t1 - self.t0)
        return self.x0 + (self.x1 - self.x0) * f, self.y0 + (self.y1 - self.y0) * f

    def go(self, x, y, speed, now, start=None):
        sx, sy = start if start else self.pos(now)
        d = math.hypot(x - sx, y - sy)
        stop = d / max(speed, 1)
        self.x0, self.y0, self.x1, self.y1, self.t0, self.t1 = sx, sy, x, y, now, now + stop * CLIENT_TWEEN
        return int(stop * 1000)

    def ms_left(self, now):
        """The remaining time of an ongoing movement to send to the client (timeToTarget, ms)."""
        return int((self.t1 - now) / CLIENT_TWEEN * 1000)


class NPC:
    bot = None                              # bot ship (bot/ship.BotShip): looks like a player, its mind is ship.think
    bot_target = None                        # the id of the bot ship this alien answers with (ship.npc_to_bot)
    bot_scan = 0.0                           # next look for a bot ship nearby (aggressive alien: ship.notice_bot)

    def __init__(self, uid, tip, x, y, wave=False):
        self.id, self.tip, self.d = uid, tip, CFG['types'][tip]
        k = SET.multiplier('npc_hp', 'wave' if wave else 'map')     # wave: alien of a gate and mode wave
        if k != 1.0 and not self.d.get('friendly'):        # the panel's HP multiplier: a copy of the type, not the shared dict (n.d maximum value)
            self.d = dict(self.d, hp=max(1, int(self.d['hp'] * k)), shield=min(SET.I32, int(self.d['shield'] * k)))
        self.model = self.d.get('model', tip)      # the client's ship model (differs from the type key for types sharing the same model)
        self.mover = Mover(x, y)
        self.hp, self.shield = self.d['hp'], self.d['shield']
        self.engaged = False
        self.gate = False                   # Galaxy Gate alien: does not respawn
        self.hunt = False                   # wave alien (gates, modes): does not let go of the player, does not flee to wander
        self.flee = False                   # the player fled to a safe zone: move away
        self.park = None                    # (x, y) zone center: it waited at the zone's edge; after waiting it wanders briefly away from the zone
        self.pend_dmg = 0                   # total damage of the shots that hit: a single AttackHitCommand in the per-second tick (npc_hit_tick)
        self.firing = False                 # opened a laser on the player, its end (AttackAbortLaserCommand) has not yet gone to the client (alien_ceasefire)
        self.blocked = 0.0                  # the chase path was blocked by a structure/zone: no attacking again until this moment (to avoid a stop/search loop)
        self.invulnerable = None            # function: takes no damage while it returns True (Zeta Devourer: while other aliens live; galaxy_gates.py)
        self.vm = {}                        # ongoing visual effects (VisualModifier -> fields): sent with ShipCreateCommand on re-entering view
        self.next_think = time.time() + random.uniform(1, 6)
        self.next_shot = 0.0
        self.alive = True
        # its own place around the player while chasing (angle offset, distance): so that those coming from the same direction do not stack on one point
        self.spread = random.uniform(-0.8, 0.8)
        # its distance to the player while chasing: in the official server recording 10%-90% of the firing aliens are at 90-310 units (median 167; 195 shots).
        # Before it was 250-440: aliens stood scattered and did not get in range of the P.E.T. kamikaze (player report 2026-10-27)
        self.keep = random.uniform(90, 310)
        self.effect = STATE.Effects()         # status effects: slow, freeze, poison, weak shield … (state.py)
        self.behavior = ALN.of(self.d)       # behavior hooks and abilities (npc.json, alien_abilities.json; alien.py)
        self.summoned = False               # summoned or spawned on death: does not respawn
        self.children = set()               # the ones they summoned (ids)
        self.guard = None                   # (summoner's id, guard): wanders around the summoner (Cubikon's Protegits)
        self.route = None                     # (x, y, arrival time): the rover (Hitac) flies straight from portal to portal (event_maps.rover)
        self.last_hit = 0.0                 # the moment it was last hit (out-of-combat regeneration)
        self.next_summon = 0.0
        self.next_regen = 0.0
        self.next_shield_regen = 0.0        # the alien's own shield refill (World.npc_shield_regen)
        self.ab = {}                        # state of the abilities (alien.py: cooldowns, thresholds, vanishing, speed)
        self.attackers = {}                 # attacker -> last hit time (Battleray's rage)
        self.foe = None                     # the world that runs its AI on a shared map (shared_maps.Map.owners)

    def speed(self):
        """Its speed: the one changed by the ability (Emperor Sibelon 380) or the type's; with the panel's alien speed multiplier (immobile ones stay 0)."""
        v = self.ab.get('speed') or self.d['speed']
        k = SET.multiplier('npc_speed')
        return max(1, int(v * k)) if v > 0 and k != 1.0 else v


def extra_count(spec, chance=1.0):
    """The amount of the extra reward: a number, [min, max] or {count, probability} (npc.json extra_reward; tools/npc_maps.py). chance:
    probability multiplier (PRC-B00/B01 booster)."""
    if isinstance(spec, dict):
        if random.random() >= spec.get('probability', 1) * chance:
            return 0
        spec = spec.get('count', 1)
    if isinstance(spec, list):
        return random.randint(int(spec[0]), int(spec[1]))
    return int(spec)


def rand_hash():
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(random.randint(4, 6)))


# saving the map state: the session's world (keep_state) holds the aliens, boxes, ores and pending respawns here after leaving the map;
# if the same map is returned to within this time it continues where it left off (so that boxes and gate energy cannot be
# gathered by going back and forth through a portal). Galaxy Gate maps are not saved (galaxy_gates.py keeps its own state).
ROCKET_ALLOWANCE = 0.25               # the allowance given to the client in the rocket cooldown (s)
WORLD_CACHE = {}
WORLD_CACHE_SEC = 600             # adaptation: 10 minutes
WORLD_CACHE_MAX = 8


RUNNING = weakref.WeakSet()            # worlds whose loop is running (for sync)


def sync():
    """Takes and releases the lock of every running world once: the ongoing loop step finishes and the messages gathered in the step have been sent
    (send collection). Tests call it after waiting for a state, before looking at the messages."""
    for w in list(RUNNING):
        with w.lock:
            pass


class Metrics:
    """Duration of a loop step: the mean and the maximum of the last 10 s (ms), the total steps and the number of slow steps (> 50 ms)."""
    SLOW_MS = 50.0

    def __init__(self, window_sec=10.0):
        self.window = window_sec
        self.step = 0
        self.slow = 0
        self.last = []                       # (moment, ms)

    def add(self, ms, now=None):
        now = time.time() if now is None else now
        self.step += 1
        if ms > self.SLOW_MS:
            self.slow += 1
        self.last.append((now, ms))
        while self.last and self.last[0][0] < now - self.window:
            self.last.pop(0)

    def summary(self):
        v = [ms for _, ms in self.last]
        return {'step': self.step, 'slow': self.slow, 'avg_ms': round(sum(v) / len(v), 2) if v else 0.0,
                'max_ms': round(max(v), 2) if v else 0.0}


class World:
    @property
    def invulnerable(self):
        """Test invulnerability: the --invulnerable option or the panel's setting (it changes while the game is running too)."""
        return self._invulnerable or SET.get('immune_until')

    @invulnerable.setter
    def invulnerable(self, v):
        self._invulnerable = bool(v)

    def __init__(self, profile, send, log, map_id, station=None, test_near=False, on_jump=None, keep_state=False, shared=False):
        """paylas: on the friend server a normal map is shared with the worlds of the other players on the same map (shared_maps.py)."""
        self.perf = Metrics()                 # duration of the loop step (ms): live status and panel
        self.step_errors = {}               # last line of the loop error -> the moment it was last written to the log (step_error)
        self.step_peace = None              # in the step's alien loop: hero position -> in a safe zone (hero_in_peace)
        self._batch = None                 # what is to be sent while the loop step runs (in a single frame at the end of the step)
        self._loop_ident = None             # the loop's thread (defer: also queues the session's messages inside the step)
        self.cbs_trade = None               # ore sale at the Clan Battle Station: () -> price multiplier or None (cbs.py)
        self.last_asset_attacker = None     # (CBS module uid, hit time): PET guard retaliation.
        self.asset_targets = None           # hittable map objects (the modules of a rival Battle Station: cbs.py): asset_pos(id)
        #                                     -> (x, y) | None, asset_select(id), asset_attackable(id) -> [] | error, asset_hit(id, damage)
        self.p, self.send_raw, self.log = profile, send, log
        self.map_id = str(map_id)
        # 4-4, 4-5, 5-x double size (npc.json "boyut"), GG Hades half size (the client's scaleFactor)
        self.map_w, self.map_h = (CFG['maps'].get(self.map_id) or {}).get('size') or H.map_size(self.map_id)
        self.station = station
        self.lock = threading.RLock()
        self.npcs = {}
        self.boxes = {}            # hash -> dict(tip, x, y, icerik, bitis)
        self.ores = {}             # hash -> dict(tip, x, y): ores on the map
        self.ore_fields = []       # centers of the ore clusters
        self.pending = []          # pending respawns [moment, type ('npc', 'bonus', 'ore'), value]; saved with the map state
        self.keep_state = keep_state
        self.assets = []           # (id, x, y, hint): the station's clickable objects (HQ, hangar, refinery)
        self.asset_types = {}      # object id -> the client's AssetType (quest condition VISIT_MAP_ASSET)
        self.near_assets = None    # nearby objects (None: at the next step the state of all of them is sent)
        self.foreign_assets = []   # objects and the quest giver of another company's base: not clickable (check_assets)
        self.timers = []           # (time, function)
        self.notice = None         # the last kill reward lines waiting to be shown on screen (kill_notice)
        self.notice_at = 0.0       # the moment the last reward lines went to the screen
        self.notice_timer = False
        self.collect_wish = None   # (box, last moment): the box to be collected when the ship reaches it (collect)
        self.opening = None        # the loot box being opened {h, bitis} (open_booty)
        self._next_uid = OH.UID_BASE
        k = self.p.d['position']
        self.hero = Mover(k['x'], k['y'])
        self._effect_destination = None        # pending flight target while a zero-speed effect lasts
        self.target = None
        self.attacking = False
        self.next_laser = 0.0
        self.ammo_ready = {}           # ammo with its own cooldown (RSB-75, RCB-140: 3 s) -> the moment it can fire again
        self.ammo_timer_end = {}       # cooldown group -> end of the countdown shown on the shortcut bar (ammo_timer)
        self.rocket_ready = 0.0
        self.running = False
        self.hero_dead = False
        self.reload_pending = False   # when the player respawns the client reloads the map
        self.test_near = test_near     # test convenience: one each of the first 4 NPC types spawns near the player (--yakin-npc)
        self.invulnerable = False      # test convenience: hits are visible, hull and shield do not decrease (--invulnerable; also in the panel)
        self.dark = False          # dark map (Trial of Terrors): flashlight effect (session settings; event_gate.DARK_MAPS)
        self.gates = list(H.gates(map_id, self.p.d['pilot'].get('factionId')))   # portals to other maps (spacemap-config.xml)
        self.extra_gates = []          # portals added by the session (the Galaxy Gates in X-1; galaxy_gates.py), reported on login
        self.gate = None               # waves on a gate map (galaxy_gates.Run)
        self.low = None                # the single-player version of LoW (low.Low)
        self.labyrinth = None           # Frozen Labyrinth map (labyrinth.Labyrinth)
        self.gate_fee = None           # paid portal (labyrinth: Labyrinth Key) -> (does it pass, messages)
        self.sold = False              # ore sold at the station: the refinery window closes on the first move (on_move)
        self.session_tick = None       # the session's timed systems (Assembly, Dispatch, Skylab; game.Session.tick)
        self.visible = set()           # NPCs the client knows (view distance; recording: shown at ~2,000 units)
        self.seen_items = set()        # boxes and ores the client knows (recording: at ~1,000 units)
        self.next_booster = 0.0        # booster durations once a second
        self.radiation_since = None    # since when it has been outside the map (radiation)
        self.ach_next, self.ach_pos, self.ach_dist, self.ach_secs = 0.0, None, 0.0, 0     # achievement counters (ach_tick)
        self.abilities = SA.Engine(self, COMBAT['laser_range'])     # ship abilities (ship_ability.py)
        self.items = CIT.Items(self)                                # mines, CPUs, launcher, special rockets (combat_items.py)
        self.tech = TECH.Technology(self)                               # technology items (technology.py)
        self.particle = PC.Shot(self)                                # particle cannons and Singularity Drive (particle.py)
        self.alien = ALN.Abilities(self)                             # alien abilities (alien.py)
        self.CFG_TYPES = CFG['types']
        self.event = EVT.MapEvents(self)                     # the calendar's map events (event_maps.py)
        self.grant = None                                             # session: shop.reward (the equipment in an alien's extra reward)
        self.range_warned = None                                      # the target an out-of-range warning was sent for (once)
        self.combat_sent = (None, 0.0)                                # last combat state line (combat_state)
        self.combat_music = False                                     # is combat music playing (music_tick)
        self.streak = [0, 0.0, 0]                                     # kill streak: count, last kill, last announced threshold
        self.kill_hooks = []                                          # on an alien reward (w, npc, x, y) -> messages (Ö3: extra_events.py)
        self.free_gate_repair = lambda: False                         # free repair at the portal (Fever: fever.py)
        self.cinema = False                                           # is the cinematic camera locked (cinematic)
        self.next_auto, self.auto_wait = 0.0, {}                       # automatic CPUs (auto_tick)
        self.auto_buy = None                                          # session: shop.auto_buy (ALB-X, RB-X)
        self.auto_buy_fail = None                                     # session: shop.auto_buy_fail (the not-enough-money text)
        self.auto_warned = set()                                      # ammo for which the not-enough-money text was shown
        self.auto_lab = None                                          # session: shop.auto_lab (NC-AWL/AWR/AWB/AGB)
        self.hero_effects = STATE.Effects()                              # the player's status effects (speed, hit; into player_profile.mods)
        infection = getattr(self.p, '_infection_effect', None)          # time left on a map change; not written to the save file
        if infection and infection['end_time'] > time.time():
            self.hero_effects.d['infection'] = [infection]
        else:
            self.p._infection_effect = None
        self.p.world_mods = self.all_mods
        self.ammo_seen = {}                                           # ammo -> last shot (achievement: types within 60 s)
        self.next_radiation = 0.0
        self.gg_energy = None          # gate energy from a bonus box (galaxy_gates.py)
        self.gate_lives = None         # HP left when dying at a gate (the death screen's text)
        self.near_gate = None
        self.gate_peace = False        # in the safe zone around a portal (BeaconCommand.inPeaceArea)
        self.peace_void = False        # an alien the player attacked in a safe zone is fighting them: the zone is void for them
        self.entered = time.time()     # entering the map (in 4-5 the portal DMZ for a while)
        self.station_inside = None     # in the station zone (BeaconCommand.inStation); None: sent on the first step
        self.jumping = False
        self.on_jump = on_jump         # (target map, portal) -> the session performs the map change
        self.repairing = False
        self.next_repair = 0.0
        self.last_combat = 0.0         # last shot or damage taken (the repair robot works out of combat)
        self.last_pvp = 0.0            # last PvP shot fired at or taken from a player (player_combat.py; portal lock in 4-X)
        self.next_shield = 0.0
        self.next_form_shield = 0.0    # the formation's shield refill/drain (form_shield_tick)
        self.next_overdrive = 0.0      # SL-01, Prometheus: extra damage every 5 s (lasers.py)
        self.anger = LASERS.Fervor()       # Asmodeus Fervor
        self.ramp = [1.0, 0.0]        # IDB-125: multiplier, last hit
        self.crit = False              # the last laser_damage was an Odysseus crit (strike in the hit message)
        self.quick_buy = None          # when money changes, the state of the quick-buy items in the shortcut bar (shop.py)
        self.map_msgs = None           # the map's objects on entry (station, turrets): sent again on reload
        self.on_home = None            # repair at the station on a map without one: the session takes the player to the company's home map
        self.money_msgs = None         # UI update when money changes (shop.py)
        self.death_pos = None          # place of death (the nearest portal for repair on the spot, repair at the portal)
        self.death_time = 0.0          # moment of death (respawn time at the gate in Hades)
        self.invuln_until = 0.0        # attack protection after repair on the spot (lifted when the player attacks)
        self.drone_msgs = None         # when drones change (level up), the drone formation in space (shop.py)
        self.drone_item = None         # inventory item of the drone that levels up (Assembly's Upgrade tab reads the level from it)
        self.unit_msgs = None          # look tied to the ship (title, drones, modules): when the ship is rebuilt in place (badge_refresh)
        self.stats_msgs = None         # when the drone level changes, shield etc. are recalculated (shop.apply_stats)
        self.settings_version, self.next_setting = None, 0.0     # when the panel's settings file changes, the ship's values are recalculated (settings_tick)
        self.ore_pack = None           # when ore counts change, the hangar inventory (shop.py)
        self.quest_event = None        # quest progress: (event, ...) -> messages (quest.py)
        self.lab_msgs = None           # upgrade state (LabUpdateItemCommand, shop.py)
        self.lab_clock = {2: 0.0, 3: 0.0}   # unspent seconds of the engine (movement) and shield (combat) upgrades
        self.lab_tick = time.time()
        self.quest_list = None         # quest list on approaching a quest giver (quest.py)
        self.givers = []               # quest givers (id, x, y)
        self.near_giver = None         # the nearby quest giver
        self.pet = None                # the session's P.E.T. (pet.py)
        self.ally = None               # a friendly that can take aliens' shots (echoes.py: the protected/escorted ship)
        self.portal_cpu = None         # mode gate CPU (Eternal, Astral, Immunizer; pve_modes.py)
        self.gate_window = None        # windowed portal (Voyagers, Trinity, Astral, Echoes): a window instead of jumping
        self.last_hurt = 0.0           # when the ship last took damage (the C-SR gear repairs while no damage is being taken)
        self.rules = (CFG['maps'].get(self.map_id) or {})          # the map's rules (npc.json; graveyard, wormhole …)
        self.next_rules = 0.0
        self.next_drifter = 0.0
        self.wormhole = None           # the hidden wormhole in 4-5: the portal and the moment it will relocate
        self.boxes_taken = 0           # bonus boxes taken on this visit (value decreases in the graveyard)
        self.players = {}            # other players the client sees: id -> look signature (shared map)
        self.pets = {}               # their P.E.T.s in space: owner's id -> (P.E.T. id, …) (shared_maps.pet_signature)
        self.appearance = None            # session: (x, y) -> this hero's ship in the other players' clients (game.Session.appearance)
        self.choice = None              # the last ShipSelectionCommand sent for the selected other player (again when HP changes)
        self.fire = False              # was it attacking in the previous step (the laser's end to the other players: step)
        self.is_group_member = lambda uid: False      # session: is the player in this hero's group (group.py; attack warning)
        self.death = None               # session: the hero was hit (notification to group members)
        self.shared = OH.take(self.map_id) if shared else None     # shared map: lock, aliens, boxes, ores, spawns
        self.shared_released = False
        self.stopped = False             # stop once (when the session reconnects it is also stopped on login, game.Session.devret)
        self.cache_key = self.map_id   # WORLD_CACHE key (on the friend server the player's own copy is per player; game.start_world)
        if self.shared:
            o = self.shared
            self.lock = o.lock
            self.npcs, self.boxes, self.ores, self.pending, self.ore_fields = o.npcs, o.boxes, o.ores, o.pending, o.ore_fields
            if o.event is None:
                o.event = self.event
            self.event = o.event             # the map event's counters and bosses are everyone's

    @property
    def next_uid(self):
        return self.shared.next_uid if self.shared else self._next_uid

    @next_uid.setter
    def next_uid(self, v):
        if self.shared:
            self.shared.next_uid = v
        else:
            self._next_uid = v

    # ------------------------------------------------------------ helpers
    @property
    def hid(self):
        return self.p.user_id

    def send(self, msgs):
        if self.shared is not None and len(self.shared.members) > 1:
            self.shared.mirror(self, msgs)     # what everyone sees (an alien's movement, hits, explosions) also goes to the other players
        self.deliver(msgs)

    def deliver(self, msgs):
        """To this world's client (through the view filters; if in a loop step, at the end of the step)."""
        if self.npcs:       # the movement of an NPC out of view does not go to the client (it does not know it)
            msgs = [m for m in msgs if not (m[0] == 'MoveCommand' and m[1]['userId'] in self.npcs and m[1]['userId'] not in self.visible)]
        msgs = [m for m in msgs if self.item_filter(m)]
        if not msgs:
            return
        if any(m[0] == 'AttributeShieldUpdateCommand' for m in msgs):
            # the official server repeats the shield's look after every shield update (reference recording 2026-10-25:
            # AttributeSkillShieldUpdateCommand right after it). When it went only on login, the client drew Shield Engineering's shield
            # as a flat ring drifted off the ship (user report 2026-10-25; when repeated live it wrapped around the ship)
            msgs = [x for m in msgs for x in ([m, SKL.shield_cmd(self.p)] if m[0] == 'AttributeShieldUpdateCommand' else [m])]
        if self._batch is not None:         # in a loop step: all together at the end of the step (send collection)
            self._batch.extend(msgs)
            return
        try:
            self.send_raw(msgs)
        except OSError:
            self.running = False

    # ------------------------------------------------------------ shared map (friend server; shared_maps.py)
    def leader(self):
        """Whether this world runs the map's jobs (respawns, expired boxes, map event)."""
        return self.shared is None or self.shared.leader is self

    def owner(self, n, now):
        """Whether this world runs the alien's AI and abilities (always in single player)."""
        return self.shared is None or self.shared.is_owner(self, n, now)

    def ours(self, n):
        """Whether the alien concerns this hero (so it lets go when the hero dies or jumps): all of them in single player."""
        return self.shared is None or n.foe in (None, self)

    def hidden(self, now):
        return self.abilities.cloaked(now) or self.items.cloaked()

    def reachable(self, now):
        """Whether aliens can attack this hero (not dead, jumping, cloaked, or in a safe zone)."""
        return not (self.hero_dead or self.jumping or self.hidden(now) or self.in_peace(*self.hero_pos(now)) or YM.spectator(self.p))

    def knows(self, uid):
        """Whether the client knows this ship (itself and its P.E.T., the aliens it sees, players and their P.E.T.s; 0: environment)."""
        return (uid == 0 or uid == self.hid or uid in self.visible or uid in self.players
                or (self.pet is not None and self.pet.active and uid == self.pet.pid) or any(p[0] == uid for p in self.pets.values()))

    def signature(self):
        """The look of its ship in the other players' clients (game.Session.appearance: ship, design, clan, title, the drones' type, level
        and designs, modules): when it changes the other players rebuild the ship."""
        return repr(self.appearance(0, 0)) if self.appearance else None

    def gorunum_msgs(self, now):
        """This hero's ship and its ongoing movement in the other player's client."""
        x, y = self.hero_pos(now)
        msgs = list(self.appearance(int(x), int(y))) if self.appearance else []
        msgs += self.items.mine_effect_msgs(now, replay=True, remember=False)
        m = self.hero
        if m.t1 > now:
            msgs.append(('MoveCommand', dict(userId=self.hid, x=int(m.x1), y=int(m.y1), timeToTarget=m.ms_left(now))))
        return msgs

    def defer(self, msgs):
        """A session message coming from the loop's thread while a loop step runs (session_tick, hooks) goes at the end of the step in the same order as
        the world's own -> True; otherwise False (the session sends it right away)."""
        if self._batch is None or threading.get_ident() != self._loop_ident:
            return False
        self._batch.extend(msgs)
        return True

    def all_mods(self, now=None):
        """Status effects + Amor/Psyche pairing (player_profile.mods' world_mods hook)."""
        out = dict(self.hero_effects.mods(now))
        for k, v in self.pair_mods().items():
            out[k] = out.get(k, 0) + v
        return out

    def pair_mods(self):
        """An Amor design gets +10% shield +5% HP with a Psyche in its group on the same map, a Psyche +10% damage with an Amor (official forum
        160373 Orcus/Solaris; the client's design texts)."""
        look = self.p.ship_look()
        amor = '-amor' in look
        if not (amor or '-psyche' in look) or not self.shared:
            return {}
        want = '-psyche' if amor else '-amor'
        if not any(o is not self and o.running and self.is_group_member(o.hid) and want in o.p.ship_look() for o in self.shared.members):
            return {}
        return {'shield': 0.10, 'hp': 0.05} if amor else {'laser': 0.10, 'rocket': 0.10}

    def later(self, delay, fn):
        self.timers.append((time.time() + delay, fn))

    def auto_jump(self, g, delay=5):
        """Gate or LoW finished: the player jumps home by itself from portal g after delay s (official forum 127543/126411: sent to X-1
        after the last wave); the portal stays open as a backup."""
        def go():
            if self.running and not self.hero_dead and not self.jumping and self.on_jump:
                self.jumping, self.attacking, self.target = True, False, None
                self.send([('JumpInitiatedCommand', {'mapId': g['target'], 'gateId': g['gateId']})])
                self.later(H.JUMP_DELAY_SEC, lambda: self.on_jump(g['target'], g))
        self.later(delay, go)

    def schedule(self, delay, kind, value=None):
        """Respawn (alien, bonus box, ore): saved together with the map state (WORLD_CACHE)."""
        self.pending.append([time.time() + delay, kind, value])

    def respawn_tick(self, now):
        due = [p for p in self.pending if p[0] <= now]
        if not due:
            return
        self.pending[:] = [p for p in self.pending if p[0] > now]       # in place: the list is shared on a shared map
        for _, kind, value in due:
            if kind == 'npc':
                if not str(value).startswith('event_') or self.event.active_type(value):     # it does not spawn if the event is over
                    self.spawn_npc(value)
                    if value == 'npc121' and self.p.gameplay('showBattlerayNotifications'):   # forum 127431: Deadly Battleray notice
                        self.send([legacy('0|A|STM|strikeandexit_message_boss_spawn')])
            elif kind == 'bonus':
                self.spawn_bonus_box()
            elif kind == 'booty':
                self.spawn_booty(value)
            elif kind == 'event_box':
                self.event.spawn_box(value)
            elif kind == 'ore' and self.ore_fields:
                self.add_ore(value)

    def save_state(self):
        """Leaving the map: the state goes to WORLD_CACHE (only the session's world; not a gate map)."""
        if not self.keep_state or self.gate:
            return
        with self.lock:
            npcs = [n for n in self.npcs.values() if n.alive and not n.gate]
            for n in npcs:
                n.engaged, n.flee, n.children, n.foe, n.park, n.firing = False, False, set(), None, None, False
                n.pend_dmg = 0                   # their timers went with the world: if they stayed, the alien never dealt damage again (npc_hit_tick)
                n.ab.pop('summon_queued', None)
            WORLD_CACHE[self.cache_key] = dict(an=time.time(), npcs=npcs, boxes=dict(self.boxes), ores=dict(self.ores),
                                            pending=list(self.pending), ore_fields=list(self.ore_fields), next_uid=self.next_uid)
        while len(WORLD_CACHE) > WORLD_CACHE_MAX:
            del WORLD_CACHE[min(WORLD_CACHE, key=lambda k: WORLD_CACHE[k]['an'])]

    def restore_state(self):
        """Saved state (if it has not expired) -> True: aliens in place, boxes and ores the same, pending spawns continue."""
        c = WORLD_CACHE.pop(self.cache_key, None) if self.keep_state else None
        now = time.time()
        if not c or now - c['an'] > WORLD_CACHE_SEC:
            return False
        for n in c['npcs']:
            x, y = n.mover.pos(now)
            n.mover = Mover(int(x), int(y))
            n.next_think, n.next_shot = now + random.uniform(1, 6), 0.0
            self.npcs[n.id] = n
        # the containers are filled in place: on a shared map the other worlds hold the same ones (shared_maps.py)
        self.boxes.update({h: b for h, b in c['boxes'].items() if not b.get('end_time') or b['end_time'] > now})
        self.ores.update({h: o for h, o in c['ores'].items() if not o.get('busy')})
        self.pending[:], self.ore_fields[:] = c['pending'], c['ore_fields']
        self.next_uid = max(self.next_uid, c['next_uid'])
        self.log('   map state restored (%d s ago): %d NPCs, %d boxes, %d ores, %d pending spawns' % (
            now - c['an'], len(self.npcs), len(self.boxes), len(self.ores), len(self.pending)))
        return True

    def in_peace(self, x, y):
        """Safe zone: around its own company's station or around the map portals (NPCs do not attack, spawn or wander there)."""
        return bool(self.station_at(x, y)) or self.near_gate_peace(x, y) or self.near_giver_peace(x, y) or ML.in_safe(self.map_id, x, y)

    def in_pvp_peace(self, x, y, faction=None):
        """Home station, portal and map-layout DMZs; CBS docking grants no PvP protection. faction: whose protection (default the pilot's;
        a bot ship's own company: the zones protect only on that company's maps, player report 2026-11-02: a VRU bot was safe at a 1-3
        portal of an MMO pilot and an EIC bot could be shot at its own 2-3 portal). The quest-giver zones are the pilot's alone."""
        own = faction is None or faction == self.p.d['pilot'].get('factionId')
        s = self.home_station(faction)
        return (bool(s and math.hypot(x - s['posX'], y - s['posY']) <= s['peaceRadius'])
                or self.near_gate_peace(x, y, faction) or (own and self.near_giver_peace(x, y)) or ML.in_safe(self.map_id, x, y))

    def peace_gates(self, faction=None):
        """Portals that have a safe zone: map portals (not Galaxy Gate and gate map portals; map_links.py). None on an enemy
        company's map (faction: default the pilot's) and on war maps (4-1..4-4); in 4-5, 15 s after entering (the client's DMZ help)."""
        n, fac = H.name(self.map_id), H.company(self.map_id)
        if n in H.NO_DMZ_MAPS or (fac and fac != (self.p.d['pilot'].get('factionId') if faction is None else faction)) \
                or time.time() > self.entered + H.DMZ_AFTER_JUMP_SEC.get(n, float('inf')):
            return []
        return [g for g in self.gates if not g.get('gate') and not g.get('hidden')]

    def near_gate_peace(self, x, y, faction=None):
        r = ML.gate_peace_radius(self.map_id, H.GATE_PEACE_RADIUS)        # "very small" in X-BL (map_layout.json)
        return any(math.hypot(g['x'] - x, g['y'] - y) <= r for g in self.peace_gates(faction))

    def giver_zones(self):
        """Demilitarized zones (x, y, radius) around the pilot's own usable quest givers (map_links.GIVER_PEACE_RADIUS). A giver inside
        the home station's zone (X-1, X-8) adds none: the station already protects it and keeps its own rules (retaliating aliens)."""
        if not H.giver_dmz(self.map_id):
            return []
        s = self.home_station()
        return [(x, y, H.GIVER_PEACE_RADIUS) for gid, x, y in self.givers
                if not (s and math.hypot(x - s['posX'], y - s['posY']) <= s['peaceRadius'])]

    def near_giver_peace(self, x, y):
        return any(math.hypot(gx - x, gy - y) <= r for gx, gy, r in self.giver_zones())

    def home_station(self, faction=None):
        """The player's (or faction's) company station: at another company's base (X-1, X-8) there is no safe zone, refinery, hangar,
        equipment change or repair at the station; on death the player respawns on their own home map."""
        s = self.station
        return s if s and s.get('type') == (self.p.d['pilot'].get('factionId') if faction is None else faction) else None

    def station_at(self, x, y):
        """Friendly home station or completed own/allied CBS at this position."""
        s = self.home_station()
        if s and math.hypot(x - s['posX'], y - s['posY']) <= s['peaceRadius']:
            return s
        provider = self.asset_targets
        return provider.docking_station(x, y) if provider and hasattr(provider, 'docking_station') else None

    def in_station(self, now=None):
        now = time.time() if now is None else now
        x, y = self.hero_pos(now)
        here = self.in_peace(x, y) if SET.get('portal_hangar') else bool(self.station_at(x, y)) or ML.in_safe(self.map_id, x, y)
        return (not self.hero_dead and not self.jumping and now - self.last_combat >= ITEMS['out_of_combat_sec']
                and (here or bool(self.low and self.low.docking_station(x, y))))

    def reload_ship(self, pos=None):
        """Ship changed in the hangar: ShipInitializationCommand with the new ship; the client reloads the map,
        when ReadyRequest arrives the NPCs and boxes are announced again (the flow on respawn). pos: the new ship's place on this map."""
        with self.lock:
            self.stop_repair()
            x, y = pos or self.hero_pos()
            self.p.d['position'].update(x=int(x), y=int(y))
            self.hero = Mover(int(x), int(y))
            self.target, self.attacking = None, False
            self.reload_pending = True
            if self.pet:
                self.pet.reload()
            self.send(self.reload_msgs())

    def reload_msgs(self):
        """ShipInitializationCommand (refreshMap) clears the map on the client: the ship + the map's objects on entry.
        NPCs, boxes and the ready bundle come with the ReadyRequest the client sends afterwards."""
        return [self.p.generate('@gemi')] + (self.map_msgs() if self.map_msgs else [])

    def random_spot(self):
        for _ in range(50):
            x, y = random.uniform(600, self.map_w - 600), random.uniform(600, self.map_h - 600)
            if not self.near_zone(x, y, 700) and not ML.blocked(self.map_id, x, y, 300):
                return int(x), int(y)
        # A random retry limit must not put an NPC back into a station at map centre.
        for row in range(9):
            for col in range(9):
                x, y = 600 + (self.map_w - 1200) * col / 8, 600 + (self.map_h - 1200) * row / 8
                if not self.near_zone(x, y, 700) and not ML.blocked(self.map_id, x, y, 300):
                    return int(x), int(y)
        return self.map_w // 2, self.map_h // 2

    def hero_pos(self, now=None):
        return self.hero.pos(now or time.time())

    # ------------------------------------------------------------ spawning
    def ship_create(self, n):
        if n.bot is not None:
            return BG.appearance(self, n)
        x, y = n.mover.pos(time.time())
        return ('ShipCreateCommand', dict(
            # expansionStage: number of visible lasers; 1-3 depending on type (npc.json genisleme, official server recording 2026-10-27)
            userId=n.id, typeId=n.model, expansionStage=n.d.get('spread', 1), clanTag='', userName=n.d['name'], x=int(x), y=int(y), factionId=0, clanId=0,
            dailyRank=0, warnBox=False, clanDiplomacy=mod('ClanRelationModule', type=0), galaxyGatesDone=0, useSystemFont=False, npc=True,
            cloaked=bool(getattr(n, 'hidden', False)), motherShipId=0, positionIndex=0, designSet='',      # Infiltration
            modifier=[mod('VisualModifierCommand', **v) for v in n.vm.values()] + ([mod(
                'VisualModifierCommand', userId=n.id, modifier=CIT.S['ghost']['visual'], attribute=0, additionalAttribute='', count=1,
                activated=True)] if self.ghostly(n) else []),
            minimapStrategyModule=mod('MinimapStrategyModule', minimapStrategy=0), specialNpcType=''))

    def ghostly(self, n):
        """Halloween boss or Trial of Terrors alien: shown as a ghost (Ghostifier's GHOST_EFFECT; fandom Pumpkin Fest
        "Ghost Boss Aliens", player report 2026-10-27: in the real game the bosses and all of Trial of Terrors' aliens)."""
        if not hasattr(n, 'ghost'):
            n.ghost = n.d.get('gate') == 'vortex' or (halloween_boss(n.d) and 'halloween' in CAL.active())
        return n.ghost

    def npc_visual(self, n, modifier, on):
        """The alien's ongoing visual effect (VisualModifierCommand; Zeta Devourer's protective shield): while on it stays in n.vm, and when the alien
        re-enters view it arrives with ShipCreateCommand."""
        v = dict(userId=n.id, modifier=modifier, attribute=0, additionalAttribute='', count=1 if on else 0, activated=on)
        if on:
            n.vm[modifier] = v
        else:
            n.vm.pop(modifier, None)
        return ('VisualModifierCommand', v)

    def item_pos(self, h):
        it = self.boxes.get(h) or self.ores.get(h)
        return (it['x'], it['y']) if it else None

    def item_in_view(self, h, hx, hy):
        if h in self.boxes and (not self.own(self.boxes[h]) or self.cargo_hidden(self.boxes[h])):     # someone else's loot (group)
            return False
        p = self.item_pos(h)
        lim = COMBAT['box_drop' if h in self.seen_items else 'box_sight']
        return bool(p) and math.hypot(p[0] - hx, p[1] - hy) <= lim

    def item_filter(self, m):
        """Box and ore view: adding a far one is not sent (it is sent on entering view), removing one the client does not know is not
        sent. What is sent is recorded in the client's known list."""
        name, f = m[0], m[1]
        if name in ('AddBoxCommand', 'AddOreCommand'):
            hx, hy = self.hero_pos()
            if not self.item_in_view(f['hash'], hx, hy):
                return False
            self.seen_items.add(f['hash'])
        elif name == 'RemoveCollectableCommand':
            if f['hash'] not in self.seen_items:
                return False
            self.seen_items.discard(f['hash'])
        return True

    def item_msg(self, h):
        if h in self.ores:
            return self.ore_msg(h)
        return self.box_cmd(h, self.boxes[h])

    def box_cmd(self, h, b):
        """The box's AddBoxCommand to this hero: someone else's cargo box is FROM_SHIP_BLOCKED (the client shows it blue only if the "other
        players' cargo boxes" setting is on)."""
        tip = b['tip']
        if tip in CARGO_BOXES and not self.own_tag(b.get('owner_tag')) and SET.get('cargo_ownership'):
            tip = BLOCKED_BOX
        return ('AddBoxCommand', dict(hash=h, boxType=tip, x=b['x'], y=b['y']))

    def in_view(self, n, now, hx=None, hy=None):
        """Whether the NPC is within view distance (once shown, it stays visible up to the drop distance). The selected target stays visible even if it moves away:
        in the real game the lock drops only with another selection, the target's EMP, a map change or the target's death; the ship faces the target, the target is on
        the minimap (player report 2026-10-28: the selection was being dropped when it moved away)."""
        if n.id == self.target and n.id in self.visible:
            return True
        if hx is None:
            hx, hy = self.hero_pos(now)
        nx, ny = n.mover.pos(now)
        lim = COMBAT['view_drop' if n.id in self.visible else 'sight_range'] * self.abilities.view_factor(now)   # Recon
        return math.hypot(nx - hx, ny - hy) <= lim

    def show(self, n, now):
        """Announce the NPC to the client: ShipCreateCommand, and if it is moving, the remaining movement (MoveCommand)."""
        self.visible.add(n.id)
        msgs = [self.ship_create(n)]
        if n.bot is not None:
            msgs += BG.extra_look(n)                 # the bot's title and drones (like the player's ship)
        msgs += list((getattr(n, 'images', None) or {}).values())     # permanent visuals (Ö4: evacuation zone, Guardian area)
        m = n.mover
        if m.t1 > now:
            msgs.append(('MoveCommand', dict(userId=n.id, x=int(m.x1), y=int(m.y1), timeToTarget=m.ms_left(now))))
        return msgs

    def info_request(self, uid):
        """Old text protocol "i|<id>": the client asks about an entity it does not know; resent as in the recording."""
        with self.lock:
            n = self.npcs.get(uid)
            if n and n.alive and n.id not in self.visible and self.in_view(n, time.time()):
                self.send(self.show(n, time.time()))
            elif n and n.alive and n.id in self.visible:
                self.send([self.ship_create(n)])

    def visible_msgs(self, now):
        """All NPCs within view distance (on login and when the map is reloaded)."""
        self.visible.clear()
        hx, hy = self.hero_pos(now)
        return [m for n in self.npcs.values() if self.in_view(n, now, hx, hy) for m in self.show(n, now)]

    def omega_maps(self):
        """For Omega AutoTactic's selection lists (autopilot.py): the current map and map -> the names of the aliens that appear there
        (npc.json's map tables; also those alive on this map now: event, gate wave, summoned)."""
        T = CFG['types']
        with self.lock:
            maps = {k: {T[r['tip']]['name'] for r in v.get('npc', []) if T.get(r.get('tip'), {}).get('name')}
                    for k, v in CFG['maps'].items() if k.isdigit()}
            maps.setdefault(self.map_id, set()).update(n.d['name'] for n in self.npcs.values()
                                                       if n.alive and n.d.get('name') and not getattr(n, 'hidden', False))
        return self.map_id, maps

    def view_tick(self, now):
        """An NPC entering view is shown, one leaving is removed (ShipRemoveCommand as in the recording; if it is the target, the selection is dropped)."""
        hx, hy = self.hero_pos(now)
        msgs = []
        for n in list(self.npcs.values()):
            seen = n.id in self.visible
            if self.in_view(n, now, hx, hy):
                if not seen:
                    msgs += self.show(n, now)
            elif seen:
                self.visible.discard(n.id)
                if self.target == n.id:
                    self.target, self.attacking = None, False
                    msgs.append(('ShipDeselectionCommand', {}))
                msgs.append(('ShipRemoveCommand', {'userId': n.id}))
        for h in list(self.boxes) + list(self.ores):          # boxes and ores (~1,000 units)
            seen = h in self.seen_items
            if self.item_in_view(h, hx, hy):
                if not seen:
                    msgs.append(self.item_msg(h))
            elif seen:
                msgs.append(('RemoveCollectableCommand', {'collected': False, 'hash': h}))
        if self.shared:
            msgs += self.shared_view(now, hx, hy)
        if msgs:
            self.send(msgs)

    def shared_view(self, now, hx, hy):
        """Shared map: an alien another player killed or pulled, and a box and ore they collected, also disappear from this client; the other
        players' ships are shown according to view (shared_maps.Map.visibility)."""
        msgs = []
        for uid in [u for u in self.visible if u not in self.npcs]:
            self.visible.discard(uid)
            if self.target == uid:
                self.target, self.attacking = None, False
                msgs.append(('ShipDeselectionCommand', {}))
            msgs.append(('ShipRemoveCommand', {'userId': uid}))
        msgs += [('RemoveCollectableCommand', {'collected': False, 'hash': h}) for h in list(self.seen_items)
                 if h not in self.boxes and h not in self.ores]
        lim = self.abilities.view_factor(now)
        msgs += self.shared.visibility(self, now, hx, hy, COMBAT['sight_range'] * lim, COMBAT['view_drop'] * lim)
        if self.choice is not None and self.target == self.choice[1]['userId']:     # the selected other player
            w = self.player(self.target)
            if w is None:                                    # left view (ShipRemoveCommand above)
                self.target, self.attacking, self.choice = None, False, None
                msgs.append(('ShipDeselectionCommand', {}))
            elif self.player_selection(w) != self.choice:        # HP or shield changed (the real server resends too)
                self.choice = self.player_selection(w)
                msgs.append(self.choice)
        return msgs

    def player(self, uid):
        """The world of the other player the client sees (shared map) or None."""
        if self.shared is None or uid not in self.players:
            return None
        return next((w for w in self.shared.members if w.hid == uid and w.running), None)

    def player_selection(self, w):
        """Selection of the other player: the client selects the player by id (shipType does not matter), the bars from its record."""
        g = w.p.d['ship']
        return ('ShipSelectionCommand', dict(userId=w.hid, shipType=0, shield=int(g.get('shield', 0)), shieldMax=int(g.get('shieldMax', 0)),
                                             hitpoints=int(g.get('hitPoints', 0)), hitpointsMax=int(g.get('hitMax', 0)),
                                             nanoHull=int(g.get('nanoHull', 0)), maxNanoHull=int(g.get('maxNanoHull', 0)),
                                             shieldSkill=False))

    def lairs(self, tip):
        """Fixed spawn points of the type on this map (npc.json maps.fixed_spots, else map_layout.json lairs) or None."""
        return self.rules.get('fixed_spots', {}).get(tip) or ML.lairs(self.map_id).get(tip)

    def fixed_spot(self, tip):
        """A free one among the type's fixed spawn points (npc.json maps.fixed_spots; Cubikon's four points) or None."""
        pts = self.lairs(tip)
        if not pts:
            return None
        free = [p for p in pts if not any(n.tip == tip and math.hypot(n.mover.x1 - p[0], n.mover.y1 - p[1]) < 800
                                          for n in self.npcs.values())]
        return tuple(random.choice(free or pts))

    def zone_spot(self, tip):
        """An unobstructed point in the type's spawn zone (npc.json maps.npc[].region [x, y, radius]; World Editor) or None."""
        z = next((g['region'] for g in (CFG['maps'].get(self.map_id) or {}).get('npc', []) if g['tip'] == tip and g.get('region')), None)
        if not z:
            return None
        for _ in range(30):
            a, r = random.uniform(0, 2 * math.pi), z[2] * math.sqrt(random.random())
            x = min(max(z[0] + math.cos(a) * r, 300), self.map_w - 300)
            y = min(max(z[1] + math.sin(a) * r, 300), self.map_h - 300)
            if not ML.blocked(self.map_id, x, y, 200):
                return int(x), int(y)
        return int(z[0]), int(z[1])

    def spawn_npc(self, tip, announce=True):
        pts = self.lairs(tip)
        if pts and sum(1 for o in self.npcs.values() if o.alive and o.tip == tip) >= len(pts):
            # one per lair at most: the count multiplier (npc_count) used to stack extras on taken lairs (Invoke XVI on BL maps)
            return None
        self.next_uid += 1
        x, y = self.fixed_spot(tip) or self.zone_spot(tip) or self.random_spot()
        n = NPC(self.next_uid, tip, x, y)
        self.npcs[n.id] = n
        now = time.time()
        if announce and self.in_view(n, now):
            self.send(self.show(n, now))
        return n

    def spawn_npc_at(self, tip, x, y, model=None, prep=None, wave=False):
        """NPC at a given point (gate waves). model: a look different from the type's (Kronos Evil You: the player's ship); prep:
        applied to the instance before it is announced (buff in modes, pve_common.scale_npc); wave: gate and mode wave (the panel's HP
        sub-setting)."""
        self.next_uid += 1
        n = NPC(self.next_uid, tip, int(x), int(y), wave)
        if model:
            n.model = model
        if prep:
            prep(n)
        self.npcs[n.id] = n
        now = time.time()
        if self.in_view(n, now):
            self.send(self.show(n, now))
        return n

    PORTAL_MARGIN, PORTAL_GAP = 800, 700

    def fit_gate(self, g):
        """The portal is within the map bounds and not on top of another portal. Portals lined up on an arc next to the base (event
        gates, labyrinth, Voyagers/Trinity/arena) fell off the map (into the radiation zone) when the base is in a corner (live test H46:
        in 2-1 Plutus x=21,681, Voyagers y=-1,806). On a map with a recording, the gate and mode portal is at its place on the official server according to its design
        (map_layout.json design_spot: 2-1, 2-8). in_place: those deliberately lined up side by side are not shifted (Echoes Command Hall)."""
        m = self.PORTAL_MARGIN
        x, y = ML.design_pos(self.map_id, g.get('designId')) or (g['x'], g['y'])
        x = min(max(int(x), m), self.map_w - m)
        y = min(max(int(y), m), self.map_h - m)
        for _ in range(0 if g.get('in_place') else 12):
            hit = next((o for o in self.gates if o['gateId'] != g['gateId'] and math.hypot(o['x'] - x, o['y'] - y) < self.PORTAL_GAP), None)
            if not hit:
                break
            # if pressed against the edge, shift along the edge, otherwise toward the middle of the map
            if x in (m, self.map_w - m):
                y = min(max(y + (self.PORTAL_GAP if y < self.map_h // 2 else -self.PORTAL_GAP), m), self.map_h - m)
            elif y in (m, self.map_h - m):
                x = min(max(x + (self.PORTAL_GAP if x < self.map_w // 2 else -self.PORTAL_GAP), m), self.map_w - m)
            else:
                x += self.PORTAL_GAP if x < self.map_w // 2 else -self.PORTAL_GAP
        if (x, y) != (g['x'], g['y']):
            g = dict(g, x=x, y=y)
        return g

    def add_gate(self, g):
        """A portal added later (Galaxy Gate, exit from a gate)."""
        if any(x['gateId'] == g['gateId'] for x in self.gates):
            return
        g = self.fit_gate(g)
        self.gates.append(g)
        if 'designId' in g:                      # no design: there is no portal on the client, works with J (Echoes hangar)
            self.send([H.jumpgate_create(g)])

    def remove_gate(self, gid):
        if not any(x['gateId'] == gid for x in self.gates):
            return
        self.gates = [x for x in self.gates if x['gateId'] != gid]
        if self.near_gate == gid:
            self.near_gate = None
        self.send([('JumpGateRemoveCommand', {'gateId': gid})])

    def drop_box(self, kind, x, y, content, life, owner=None, owner_tag=None):
        """owner: the box belongs only to this hero (loot that drops for everyone in a group; other players do not see it and cannot collect it). owner_tag: the cargo box's
        owner ('h', hero) or ('b', bot): others see it blue, and if they collect it they lose honor if from the same company (cargo_penalty)."""
        h = rand_hash()
        while h in self.boxes:
            h = rand_hash()
        self.boxes[h] = dict(tip=kind, x=int(x), y=int(y), contents=content, end_time=time.time() + life if life else None)
        if owner is not None:
            self.boxes[h]['owner'] = owner
        if owner_tag is not None:
            self.boxes[h]['owner_tag'] = owner_tag
        self.send([self.box_cmd(h, self.boxes[h])])
        return h

    def own(self, b):
        """Whether this hero can see and collect the box (ownerless or their own)."""
        return b.get('owner') in (None, self.hid)

    def cargo_hidden(self, b):
        """Someone else's cargo box and the player's "other players' cargo boxes" setting (displayPenaltyCargoboxes) is off: none is
        sent, the ones seen are removed (view loop). The client applies the setting only at the moment it is changed and still drew a
        FROM_SHIP_BLOCKED that came later (user report 2026-10-30)."""
        if b.get('tip') not in CARGO_BOXES or not SET.get('cargo_ownership') or self.own_tag(b.get('owner_tag')):
            return False
        setting = (self.p.d.get('settings') or {}).get('displaySettingsModule') or {}
        return not setting.get('displayPenaltyCargoboxes', True)

    def own_tag(self, who):
        """Whether the tag or cargo owner is this hero (or someone in their group: player or bot); None: nobody's."""
        return who is None or tuple(who) == ('h', self.hid) or self.is_group_member(who[1])

    def cargo_penalty(self, owner_tag):
        """Collected someone else's cargo box: if the owner is from the same company, an honor loss, 10 the first that day, doubling each time
        (darkorbitwiki Ranks: "Stealing cargo boxes from other players from the same company: -10, twice as much for each next
        one") -> messages."""
        fac = None
        if owner_tag[0] == 'h' and self.shared is not None:
            o = next((w for w in self.shared.members if w.hid == owner_tag[1]), None)
            fac = o.p.d['pilot'].get('factionId') if o is not None else None
        elif owner_tag[0] == 'b':
            fac = BG.bot_company(owner_tag[1])
        if fac != self.p.d['pilot'].get('factionId'):
            return []
        d = self.p.d.setdefault('cargo_theft', {})
        day = time.strftime('%Y-%m-%d')
        if d.get('day') != day:
            d.update(day=day, n=0)
        penalty = 10 * 2 ** min(d['n'], 16)
        d['n'] += 1
        tot = self.p.gain(honor=-penalty)
        self.log('   someone else\'s cargo box collected: -%d honor' % penalty)
        return self.reward_msgs(tot, honor=-penalty)

    def drop_chests(self, spec, x, y, owner=None):
        """Boss chests: in single player all damage is the player's, the most items from the best tier; arranged around the alien, the contents
        like an event box when opened ('kesin' rows; event_maps.roll)."""
        for k in range(spec['count']):
            a = 2 * math.pi * k / spec['count']
            h = self.drop_box(spec['type'], x + math.cos(a) * 200, y + math.sin(a) * 200, None, spec.get('lifetime_sec', 600), owner)
            self.boxes[h]['event'] = spec

    def spawn_bonus_box(self):
        x, y = self.random_spot()
        table = CFG['bonus_box_4x'] if H.name(self.map_id).startswith('4-') else CFG['bonus_boxes']   # boxes.md: rich box in 4-X
        self.drop_box('BONUS_BOX', x, y, random.choice(table), None)

    def spawn_booty(self, kind):
        """Keyed loot box (loot.py): at a random place, permanent; when collected a new one after renew_sec."""
        if not LOOT.active(kind):
            return
        x, y = self.random_spot()
        h = self.drop_box(kind, x, y, None, None)
        self.boxes[h]['keyed'] = True

    def load_assets(self):
        """Usable station assets and quest givers of the map's entry messages (foreign ones only listed as unusable)."""
        own = self.p.d['pilot'].get('factionId')
        for name, a in (self.map_msgs() if self.map_msgs else []):
            if name != 'AssetCreateCommand':
                continue
            if a['type']['typeValue'] in H.STATION_ASSETS:
                if a.get('factionId') in (0, None, own):
                    self.assets.append((a['assetId'], a['posX'], a['posY'], H.STATION_ASSETS[a['type']['typeValue']]))
                    self.asset_types[a['assetId']] = a['type']['typeValue']
                else:
                    self.foreign_assets.append(a['assetId'])        # the enemy base's are not used
            if a['type']['typeValue'] == H.QUEST_GIVER:
                # the quest giver is only that of its own company ("Browse your company's missions"; user report 2026-10-25: an EIC
                # pilot could use the Mission Control of the VRU/MMO base and of its X-5s)
                if H.company(self.map_id) in (None, own):
                    self.givers.append((a['assetId'], a['posX'], a['posY']))
                else:
                    self.foreign_assets.append(a['assetId'])

    def start(self):
        m = CFG['maps'].get(self.map_id)
        if not m:
            self.log('   world: no NPC list for map %s' % self.map_id)
            m = {'npc': [], 'bonus_boxes': 0}     # let the loop run anyway: portals, repair, shield
        with self.lock:
            self.load_assets()            # before spawning: quest giver DMZs keep aliens from spawning there (zone_circles)
            joined = bool(self.shared and self.shared.members)      # another player on the shared map: the aliens, boxes, ores are theirs too
            restored = joined or self.restore_state()
            for g in ([] if restored else m['npc']):
                for _ in range(SET.count('npc_count', g['count'], 'map')):
                    self.spawn_npc(g['tip'], announce=False)
            if self.test_near and not joined:
                hx, hy = self.hero_pos()
                picks, seen = [], set()
                for n in self.npcs.values():
                    if n.tip not in seen and len(picks) < 4:
                        picks.append(n); seen.add(n.tip)
                for k, n in enumerate(picks):
                    a = 0.6 + k * 1.6
                    n.mover = Mover(int(hx + math.cos(a) * 550), int(hy + math.sin(a) * 450))
                    n.next_think = time.time() + 600     # let it stand still until attacked
                    self.log('   test NPC %d %s position=(%d,%d), player=(%d,%d)' % (n.id, n.d['name'], n.mover.x1, n.mover.y1, hx, hy))
            self.send(self.visible_msgs(time.time()) + self.map_effect_msgs())
            self.deliver(self.items.mine_snapshot(time.time()) + self.items.mine_effect_msgs(replay=True))    # only to the new client; do not mirror again to neighbors
            if not restored:
                for _ in range(SET.count('box_abundance', m.get('bonus_boxes', 0), 'bonus')):
                    self.spawn_bonus_box()
                for kind, n in ([] if self.gate else LOOT.spawns(H.name(self.map_id))):
                    for _ in range(SET.count('box_abundance', n, 'booty')):
                        self.spawn_booty(kind)
                self.spawn_ores()
            self.send([self.ore_msg(h) for h in self.ores])
            mines = ML.mine_spots(self.map_id, self.gates)        # 5-1, 5-3 minefields (map_layout.json; on every load)
            if mines:
                self.send([self.items.field_mine(x, y, time.time()) for x, y in mines])
            if restored:                  # stored boxes are announced again (through the view filter)
                self.send([self.box_cmd(h, b) for h, b in self.boxes.items()])
            for g in self.extra_gates:
                self.add_gate(g)
            self.start_rules()
            if joined:                    # the map event's indicator (it had gone only to the leader when it entered the map)
                self.send(self.event.info_msgs())
        self.running = True
        with self.lock:
            if self.shared:
                self.shared.killer(self)
            self.check_gates(time.time())     # if it spawned at a portal, jumping should be possible right away
        RUNNING.add(self)
        threading.Thread(target=self.loop, daemon=True).start()
        self.log('   world: map %s, %d NPCs, %d bonus boxes, %d ores' % (self.map_id, len(self.npcs), len(self.boxes), len(self.ores)))

    def stop(self):
        self.running = False
        if self.stopped:
            return
        self.stopped = True
        BG.detach(self)                        # bot ships are not stored with the map state
        with self.lock:
            self.particle.clear()
        if self.shared is None:
            self.save_state()
        elif not self.shared_released:            # shared map: the last one to leave stores the state (WORLD_CACHE), the containers are emptied
            self.shared_released = True
            if self.shared.detach(self):
                self.save_state()
                with self.lock:
                    for c in (self.npcs, self.boxes, self.ores, self.pending, self.ore_fields):
                        c.clear()
            self.shared.release()
        if self.hero_effects.d.keys() & {'slow', 'frozen', 'speed_up', 'speed_limit', 'weakness', 'skill'}:
            for kind in ('slow', 'frozen', 'speed_up', 'speed_limit', 'weakness', 'skill'):
                self.hero_effects.remove(kind)      # map-specific effects are lifted; the infection is carried over with its remaining time
            if self.stats_msgs:
                self.send(self.stats_msgs())
        if getattr(self.p, 'world_mods', None) == self.all_mods:
            self.p.world_mods = None

    def cinematic(self, x, y, hold=3.0):
        """Cinematic camera (Ö2; the panel's 'cinematic' setting): the camera goes to a point (CameraLockToCoordinatesCommand; the client locks
        the controls for that time), after hold seconds it returns to the ship (CameraLockToHeroCommand). It is also released on map change and death."""
        if not SET.get('cinematic') or self.hero_dead or self.jumping:
            return
        self.cinema = True
        self.send([('CameraLockToCoordinatesCommand', dict(x=int(x), y=int(y), duration=1.0))])
        self.later(hold, self.cinematic_end)

    def cinematic_end(self):
        if self.cinema:
            self.cinema = False
            self.send([('CameraLockToHeroCommand', {})])

    def cleanup_msgs(self):
        """Messages that remove this map's NPCs and boxes from the client on a map change."""
        with self.lock:
            cam = [('CameraLockToHeroCommand', {})] if self.cinema else []
            self.cinema = False
            players = list(self.players) + [p[0] for p in self.pets.values()]     # the other players' ships and P.E.T.s (shared map)
            self.players, self.pets = {}, {}
            return cam + ([('ShipRemoveCommand', {'userId': uid}) for uid in players] +
                    [('ShipRemoveCommand', {'userId': uid}) for uid in self.npcs if uid in self.visible] +
                    [('RemoveCollectableCommand', {'collected': False, 'hash': h}) for h in list(self.boxes) + list(self.ores)
                     if h in self.seen_items] +
                    [ALN.asset_remove(aid, ALN.BUFF_CAPSULE) for aid in self.alien.capsules] +
                    (self.low.cleanup_msgs() if self.low else []))

    # ------------------------------------------------------------ map rules (Stage 4)
    def start_rules(self):
        """On login: hiding in the graveyard is lifted and the slowing weather; the hidden wormhole in 4-5."""
        r = self.rules
        if r.get('no_stealth'):
            self.abilities.reveal()
            self.items.reveal()
        if r.get('slow'):
            self.hero_effect('slow', 24 * 3600, r['slow'], source='map')
        if r.get('wormhole'):
            self.move_wormhole(time.time())

    def move_wormhole(self, now):
        """The hidden portal in 4-5: invisible on the minimap, has no safe zone. If a position is given it stays there (the center of the white hole),
        otherwise it relocates every relocate_sec."""
        s = self.rules['wormhole']
        if self.wormhole:
            self.remove_gate(WORMHOLE_ID)
        x, y = s.get('position') or self.random_spot()
        g = dict(gateId=WORMHOLE_ID, x=x, y=y, target=s['target'], designId=1, hidden=True, wormhole=True, arrival='random')
        self.wormhole = (g, now + s['relocate_sec'] if s.get('relocate_sec') else float('inf'))
        self.add_gate(g)
        self.log('   wormhole (%d,%d)' % (x, y))

    def wormhole_dest(self):
        """Passing through the wormhole: by chance the Cubikon Graveyard, otherwise a random map (fandom Wormhole; forum 127347)."""
        s = self.rules['wormhole']
        maps = CIT.random_maps(self.p, int(self.map_id))
        if not maps or random.random() < s.get('graveyard_chance', 1.0):
            return s['target']
        return random.choice(maps)

    def rules_tick(self, now):
        """Once a second: hiding cannot be used in the graveyard; the wormhole relocates; stragglers on a timetable."""
        if now < self.next_rules:
            return
        self.next_rules = now + 1.0
        fog = ML.of(self.map_id).get('palladium')            # 5-1, 5-3: the area where the Palladium fog turns hiding off (fandom 5-1, 5-3)
        if fog and not self.rules.get('no_stealth'):
            hx, hy = self.hero_pos(now)
            fog = fog['area'][0] <= hx <= fog['area'][2] and fog['area'][1] <= hy <= fog['area'][3]
        if (self.rules.get('no_stealth') or fog) and (self.abilities.cloaked(now) or self.items.cloaked()):
            self.abilities.reveal()
            self.items.reveal()
        if self.wormhole and now >= self.wormhole[1] and not self.jumping:
            self.move_wormhole(now)
        self.drifter_tick(now)

    @staticmethod
    def slot_time(hm, now):
        """"HH:MM" -> the latest moment this time of day passed (today or yesterday; local time)."""
        h, m = (int(v) for v in hm.split(':'))
        lt = time.localtime(now)
        t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
        # yesterday: calendar day (on a daylight saving change day 86,400 s would shift an hour); mktime carries day 0 of the month into the previous month
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - 1, h, m, 0, 0, 0, -1)) if t > now else t

    def drifter_tick(self, now):
        """Timetabled Black Light stragglers (npc.json maps.scheduled; wiki times): spawns if, within scheduled_duration_sec after its time,
        it is not on the map and was not killed at that time; does not respawn."""
        if now < self.next_drifter or self.gate or not self.leader():
            return
        self.next_drifter = now + 5.0
        done = self.p.d.get('scheduled', {})
        for e in self.rules.get('scheduled', []):
            for hm in e['hours']:
                slot = self.slot_time(hm, now)
                if now >= slot + COMBAT.get('scheduled_duration_sec', 3600):
                    continue
                key = '%s|%s|%d' % (self.map_id, e['tip'], int(slot))
                if key in done or any(n.alive and n.ab.get('scheduled') for n in self.npcs.values() if n.tip == e['tip']):
                    continue
                n = self.spawn_npc(e['tip'])
                if not n:
                    continue                    # every lair of the type is taken
                n.summoned = True
                n.ab['scheduled'] = key
                self.log('   timetabled alien: %s (%s)' % (n.d['name'], hm))

    def drifter_killed(self, n):
        key = n.ab.get('scheduled')
        if not key:
            return
        now = int(time.time())
        for w in [self] + [w for w in (self.shared.members if self.shared else []) if w is not self]:   # shared map: the leader should know too
            with w.p.lock:
                done = w.p.d.setdefault('scheduled', {})
                done[key] = now
                for k in [k for k, t in done.items() if now - t > 2 * 86400]:
                    del done[k]
                w.p.dirty = True

    def pay_key(self):
        """The entrance of 5-4: one Silver Booty Key (KEY_COST) -> was it paid."""
        for loot, n in KEY_COST:
            if self.p.resource(loot) >= n:
                self.p.add_resource(loot, -n)
                self.log('   5-4 entrance: %d %s' % (n, loot))
                return True
        return False

    # ------------------------------------------------------------ ores
    def spawn_ores(self):
        """The map's ores (items.json ores.maps: by the map's name (World Editor), else by the map class) in clusters;
        outside the safe zones."""
        counts = ORE['maps'].get(H.name(self.map_id)) or ORE['maps'].get(H.map_class(self.map_id))
        if not counts:
            return
        total = sum(counts.values())
        self.ore_fields[:] = [self.random_spot() for _ in range(max(3, total // ORE['per_cluster']))]
        for t, n in counts.items():
            for _ in range(SET.count('ore_abundance', n)):              # panel: ore abundance
                self.add_ore(int(t), announce=False)
        self.log('   ore clusters: %s' % ' '.join('(%d,%d)' % c for c in self.ore_fields))

    def ore_spot(self):
        field = ML.of(self.map_id).get('palladium')      # 5-1, 5-3: in the Palladium fog area, between the obstacles (map_layout.json)
        if field:
            return ML.free_spot(self.map_id, field['area']) or self.random_spot()
        for _ in range(30):
            cx, cy = random.choice(self.ore_fields)
            a, r = random.uniform(0, 2 * math.pi), random.uniform(0, ORE['cluster_radius'])
            x, y = cx + math.cos(a) * r, cy + math.sin(a) * r
            if 300 < x < self.map_w - 300 and 300 < y < self.map_h - 300 and not self.near_zone(x, y, 200):
                return int(x), int(y)
        return self.random_spot()

    def add_ore(self, t, announce=True):
        h = rand_hash()
        while h in self.ores or h in self.boxes:
            h = rand_hash()
        x, y = self.ore_spot()
        self.ores[h] = dict(tip=t, x=x, y=y)
        if announce:
            self.send([self.ore_msg(h)])
        return h

    def ore_msg(self, h):
        o = self.ores[h]
        return ('AddOreCommand', dict(hash=h, oreType=mod('OreTypeModule', typeValue=o['tip']), x=o['x'], y=o['y']))

    def harvest(self, f):
        """HarvestRequest {itemHash}: the client takes the ship to the ore and sends it; collected ~0.5 s later (recording)."""
        with self.lock:
            h = f.get('itemHash')
            o = self.ores.get(h)
            if not o or o.get('busy') or self.hero_dead or self.jumping:
                return
            hx, hy = self.hero_pos()
            if math.hypot(o['x'] - hx, o['y'] - hy) > ORE['harvest_distance']:
                self.log('   ore far away: %d units' % math.hypot(o['x'] - hx, o['y'] - hy))
                return
            pre = self.auto_refine()
            if self.p.cargo_free() < 1:
                self.send(pre + [('MapEventOreCommand', dict(eventType=ORE_EVENT_CARGO_FULL, oreType=mod('OreTypeModule', typeValue=o['tip']),
                                                             hash=h)), legacy('0|A|STM|loadfull')] + self.p.hint(IP.FULL_CARGO))
                self.log('   cargo full')
                return
            o['busy'] = True
            self.send(pre + [self.beam_msg()])           # collection beam (recording: SLA right after HarvestRequest)
            self.later(ORE['harvest_sec'], lambda: self.finish_harvest(h))

    def finish_harvest(self, h):
        o = self.ores.get(h)
        if not o:
            return
        pre = self.auto_refine()
        if self.p.cargo_free() < 1:
            o['busy'] = False
            self.send(pre + [('MapEventOreCommand', dict(eventType=ORE_EVENT_CARGO_FULL, oreType=mod('OreTypeModule', typeValue=o['tip']),
                                                         hash=h)), legacy('0|A|STM|loadfull')] + self.p.hint(IP.FULL_CARGO))
            return
        del self.ores[h]
        got = max(1, min(SET.amount('collecting', 1, 'ore'), self.p.cargo_free()))      # the panel's collection multiplier
        totals = self.p.add_ores({o['tip']: got})
        msgs = pre + ([self.ore_pack([o['tip']])] if self.ore_pack else [])
        msgs += [('MapEventOreCommand', dict(eventType=ORE_EVENT_FINISHED, oreType=mod('OreTypeModule', typeValue=o['tip']), hash='')),
                 ('AttributeOreCountUpdateCommand', {'oreCountList': totals}),
                 ('RemoveCollectableCommand', {'collected': True, 'hash': h})]
        msgs += self.quest('loot', loot=ORE['kinds'].get(str(o['tip']), ''), amount=got)
        self.send(msgs + self.auto_refine() + self.p.hint(IP.SELL_RESOURCE))
        self.schedule(random.uniform(*ORE['respawn_sec']) * SET.multiplier('ore_respawn'), 'ore', o['tip'])     # panel

    def auto_refine(self):
        """Settings > Gameplay "Auto-refine raw materials" (autoRefinement; the client's hint "Only works with a premium pack", in single
        player everyone is premium): after every collection (ore, cargo box, what the P.E.T. collected), before a collection and when the cargo is
        full, everything is refined as far as the laboratory recipes allow: Prometium + Endurium -> Prometid, Endurium + Terbium -> Duranium,
        Prometid + Duranium + Xenomit -> Promerium ("Raw materials were automatically refined.", auto_ore_update). The setting was never
        applied (H84); until 2026-10-18 it worked only when the cargo was full and without Promerium (user report). -> messages"""
        if not self.p.gameplay('autoRefinement'):
            return []
        recipes = [(t, {int(k): v for k, v in ITEMS['lab']['recipes'][str(t)].items()}) for t in AUTO_REFINE]
        have = {k: self.p.ore_count(k) for t, r in recipes for k in [t, *r]}
        start, made, more = dict(have), {}, True
        while more:                 # one unit at a time in turn: the shared Endurium is split between the two products, new Prometid/Duranium goes into Promerium
            more = False
            for t, r in recipes:
                if all(have[k] >= v for k, v in r.items()):
                    for k, v in r.items():
                        have[k] -= v
                    have[t] += 1
                    made[t] = made.get(t, 0) + 1
                    more = True
        if not made:
            return []
        used = {k: start[k] - have[k] for k in have if have[k] < start[k]}
        gained = {k: have[k] - start[k] for k in have if have[k] > start[k]}
        self.p.remove_ores(used)
        totals = self.p.add_ores(gained)
        self.log('   auto-refine: %s (%s); free in cargo %d' % (', '.join('%s %d' % (ORE['kinds'].get(str(t)), n) for t, n in made.items()),
                                                                 ', '.join('%s %d' % (ORE['kinds'].get(str(k)), n) for k, n in used.items()),
                                                                 self.p.cargo_free()))
        msgs = [('AttributeOreCountUpdateCommand', {'oreCountList': totals}), stm('auto_ore_update')]
        if self.ore_pack:
            msgs.append(self.ore_pack(sorted(set(used) | set(gained))))
        for t, n in made.items():
            msgs += self.quest('loot', loot=ORE['kinds'].get(str(t), ''), amount=n)
        return msgs

    # ------------------------------------------------------------ station: objects and refinery
    def at_station(self):
        s = self.home_station()
        hx, hy = self.hero_pos()
        if self.low and self.low.docking_station(hx, hy):        # LoW: the HQ station after the last relay (forum 126411)
            return True
        return bool(s) and math.hypot(hx - s['posX'], hy - s['posY']) <= s['peaceRadius']

    def at_trade(self):
        """Whether trading is possible: at the station or next to the standalone Trader (5-2)."""
        if self.at_station():
            return True
        hx, hy = self.hero_pos()
        return any(tip == 'ttip_ore_trade' and math.hypot(x - hx, y - hy) <= H.ASSET_RANGE for a, x, y, tip in self.assets)

    def check_assets(self, now):
        """Approaching/leaving station objects: they become clickable (refinery -> trade window). On approaching the quest giver
        QuestGiversAvailableCommand + quest list, on leaving an empty list (recording: ~500 units)."""
        hx, hy = self.hero_pos(now)
        giver = next((g for g in self.givers if math.hypot(g[1] - hx, g[2] - hy) <= H.ASSET_RANGE), None)
        gid = giver[0] if giver else None
        if gid != self.near_giver:
            self.near_giver = gid
            tip = mod('MessageKeyListWildcardCommand', commandList=[mod('MessageKeyListWildcardModule', wildCardReplacements=[],
                      baseKey='ttip_quest_giver_company', baseKeyType=mod('ReplacementTypeModule', typeValue=5), textStyle=0)])
            msgs = [('QuestGiversAvailableCommand', {'questGivers': [mod('QuestGiverModule', questGiverId=1, mapObjectId=gid, toolTip=tip)]
                                                     if gid else []})]
            if gid and self.quest_list:
                msgs.append(self.quest_list())
            self.send(msgs)
        if self.near_assets is None and self.foreign_assets:
            # another company's base: the HQ of the template on entry came clickable (the state of the recording's 2-1 HQ)
            self.send([H.asset_available(a, '', False) for a in self.foreign_assets])
        if not self.assets:
            self.near_assets = set()
            return
        near = {a for a, x, y, tip in self.assets if math.hypot(x - hx, y - hy) <= H.ASSET_RANGE}
        arrived = near - (self.near_assets or set())
        changed = {a for a, x, y, tip in self.assets} if self.near_assets is None else near ^ self.near_assets
        self.near_assets = near
        if changed:
            msgs = [self.asset_msg(a, tip, a in near) for a, x, y, tip in self.assets if a in changed]
            for a in sorted(arrived):                        # quest: "Fly to the following location: Hangar" (Ö1)
                msgs += self.quest('asset', type=self.asset_types.get(a))
            self.send(msgs)

    def asset_msg(self, a, tip, near):
        """The station object's hint; at the repair station the coupon counts (the client's ttip_instant_repair / _not_available)."""
        if tip != 'ttip_instant_repair':
            return H.asset_available(a, tip, near)
        v = self.vouchers()
        if v >= REPAIR_VOUCHERS:
            return H.asset_available(a, tip, near, [('%VOUCHERS_PRESENT%', v), ('%REPAIRS_POSSIBLE%', v // REPAIR_VOUCHERS)])
        return H.asset_available(a, 'ttip_instant_repair_not_available', near, [('%VOUCHERS_PRESENT%', v),
                                                                                   ('%VOUCHERS_NEEDED%', REPAIR_VOUCHERS)])

    def instant_repair(self, f):
        """InstantRepairRequest {repairAssetId} (Ö1): the repair station at the station (AssetType 53/54; client AssetClickOpenWindow) refills the hull
        at once with a repair coupon (the coupon's description: "a sojourn at a repair station for your ship"). Not possible if the coupons are not enough or
        the hull is full; the hint is refreshed."""
        with self.lock:
            now = time.time()
            hx, hy = self.hero_pos(now)
            st = next(((a, x, y, tip) for a, x, y, tip in self.assets if a == f.get('repairAssetId') and tip == 'ttip_instant_repair'), None)
            g = self.p.d['ship']
            if not st or self.hero_dead or math.hypot(st[1] - hx, st[2] - hy) > H.ASSET_RANGE:
                self.log('   no instant repair: repair station not nearby')
                return
            if g.get('hitPoints', 0) >= g.get('hitMax', 0) or self.vouchers() < REPAIR_VOUCHERS:
                self.log('   instant repair did not happen: %s' % ('hull full' if g.get('hitPoints', 0) >= g.get('hitMax', 0) else 'no coupon'))
                self.send([self.asset_msg(st[0], st[3], True)])
                return
            with self.p.lock:
                self.p.d['gates']['voucher'] -= REPAIR_VOUCHERS
                self.p.dirty = True
            hp0 = g.get('hitPoints', 0)
            self.p.set_hull(hp=g.get('hitMax', 0))
            self.send([self.hp_msg()] + self.heal_msgs(hp0) + [legacy('0|A|STM|repair_voucher_used'), self.asset_msg(st[0], st[3], True)])
            self.log('   instant repair: +%d HP (coupons left %d)' % (int(g['hitPoints'] - hp0), self.vouchers()))

    def trade_info(self):
        """TradeRequest (click on the refinery) -> OreTradeInfoCommand: the prices if at the station; in space, if the P.E.T.'s cargo trader
        is selected, P.E.T. trading; if there is an HM-7 trade drone (its icon in the shortcut bar, menu_action) drone trading; otherwise
        trading is not active."""
        pr = ore_prices(self.p.d['pilot'].get('honourPoints', 0))
        pirate = self.at_trade() and self.map_id == PIRATE_MARKET          # the pirate trader in 5-2: Palladium -> gate energy
        kind = (TRADE_PIRATE if pirate else TRADE_STATION if self.at_trade() else TRADE_PET if self.pet_trade()
                else TRADE_DRONE if self.hm7_ready() else TRADE_INACTIVE)          # HM-7 trade drone: anywhere (same order as sell_ore)
        cbs = self.cbs_trade() if self.cbs_trade and not self.at_trade() else None
        if cbs:                                                             # in its own Battle Station (Ö5): 10% more expensive
            kind = 4
            pr = {k: int(v * cbs) for k, v in pr.items()}
        if pirate:                                                          # forum 127532: the 5-2 pirate trader x1.05 (21/31/52/420/420/1,050)
            pr = {k: int(v * PIRATE_PRICE) for k, v in pr.items()}
        return ('OreTradeInfoCommand', dict(
            prometiumPrice=pr[0], enduriumPrice=pr[1], terbiumPrice=pr[2], prometidPrice=pr[4], duraniumPrice=pr[5],
            promeriumPrice=pr[6], sepromPrice=pr[7], osmiumPrice=pr[28],
            palladiumExchangeRate=ORE['palladium_energy'] if pirate else -1, type=kind,
            remainingCharges=EX.uses(self.p, 'equipment_extra_hmd-07') if kind == TRADE_DRONE else 0))

    def trade_palladium(self, n):
        """At the pirate trader in 5-2, Palladium -> gate energy (15 to 1; leftover Palladium stays in cargo)."""
        rate = ORE['palladium_energy']
        units = min(n, self.p.ore_count(PALLADIUM)) // rate
        if not (self.at_trade() and self.map_id == PIRATE_MARKET) or units <= 0 or not self.gg_energy:
            self.log('   Palladium exchange did not happen: %d (at the 5-2 trader: %s)' % (n, self.at_trade() and self.map_id == PIRATE_MARKET))
            return
        totals = self.p.remove_ores({PALLADIUM: units * rate})
        msgs = [('AttributeOreCountUpdateCommand', {'oreCountList': totals})] + self.gg_energy(units)
        if self.ore_pack:
            msgs.append(self.ore_pack([PALLADIUM]))
        msgs += self.quest('sell', ore=PALLADIUM, amount=units * rate)
        self.send(msgs)
        self.log('   Palladium x%d -> %d gate energy' % (units * rate, units))

    def hm7_ready(self):
        return EX.owned(self.p, CIT.HM7) and EX.uses(self.p, CIT.HM7) > 0

    def pet_trade(self):
        return bool(self.pet and self.pet.active and self.pet.trading and time.time() >= self.pet.trade_ready)

    def sell_ore(self, f):
        """TradeSellOreRequest {toSell: {oreType, count}} -> cargo and credits (order as in the recording)."""
        m = f.get('toSell') or {}
        t, n = (m.get('oreType') or {}).get('typeValue'), int(m.get('count') or 0)
        if t == PALLADIUM:
            with self.lock:
                self.trade_palladium(n)
            return
        with self.lock:
            price = ore_prices(self.p.d['pilot'].get('honourPoints', 0)).get(t)
            have = self.p.ore_count(t) if t is not None else 0
            cbs = self.cbs_trade() if self.cbs_trade and not self.at_trade() else None
            if cbs and price is not None:                                   # in its own Battle Station (Ö5)
                price = int(price * cbs)
            if price is not None and self.at_trade() and self.map_id == PIRATE_MARKET:
                price = int(price * PIRATE_PRICE)                           # 5-2 pirate trader (forum 127532)
            by_pet = not self.at_trade() and not cbs and self.pet_trade()
            by_hm7 = not self.at_trade() and not by_pet and not cbs and self.hm7_ready()     # HM-7: anywhere, 100 sales
            if not (self.at_trade() or cbs or by_pet or by_hm7) or price is None or n <= 0 or n > have:
                self.log('   no sale: type %s x%d (held %d, at the station %s)' % (t, n, have, self.at_trade()))
                return
            if by_pet and not self.pet.trade_paid and self.pet.d['fuel'] < self.pet.trade_fuel():      # fuel cost of the sale (client: "You have to use P.E.T. fuel to trade")
                self.log('   P.E.T. sale did not happen: not enough fuel (%d < %d)' % (self.pet.d['fuel'], self.pet.trade_fuel()))
                self.send([legacy('0|A|STM|msg_pet_no_fuel_to_activate')])
                return
            if by_pet:
                price = int(price * (1 + self.pet.trade_bonus()))     # G-TRA1: +%5/15/30
                self.pet.trade_charge()               # the session's fuel at the first sale; the cooldown starts when the window closes (pet.trade_close)
            elif by_hm7:
                self.log('   sale with HM-7 (left %d)' % EX.use(self.p, 'equipment_extra_hmd-07'))
            totals = self.p.remove_ores({t: n})
            credits = n * price
            msgs = [('AttributeOreCountUpdateCommand', {'oreCountList': totals})]
            msgs += self.reward_msgs(self.p.gain(credits=credits, reason=RT.ore_desc(t), count=n), credits=credits)
            if self.ore_pack:
                msgs.append(self.ore_pack([t]))
            msgs += self.quest('sell', ore=t, amount=n)
            if by_hm7:
                msgs += self.p.menu_changes([CIT.HM7])         # if the last use was spent, the shortcut icon goes inactive at once
            self.send(msgs)
            self.sold = self.sold or self.at_trade()
            self.log('   sold: %s x%d = %d credits' % (ORE['kinds'].get(str(t), t), n, credits))

    # ------------------------------------------------------------ portals
    def check_gates(self, now):
        """Approaching/leaving a portal: BeaconCommand(nearJumpGate) + MapAssetActionAvailableCommand (as in the recording)."""
        hx, hy = self.hero_pos(now)
        g = min((g for g in self.gates if math.hypot(g['x'] - hx, g['y'] - hy) <= H.JUMP_RADIUS),
                key=lambda g: math.hypot(g['x'] - hx, g['y'] - hy), default=None)      # nearby portals (Echoes hall): the nearest
        gid = g['gateId'] if g else None
        peace = self.near_gate_peace(hx, hy) or self.near_giver_peace(hx, hy) or ML.in_safe(self.map_id, hx, hy)
        s = self.station_at(hx, hy)
        inside = bool(s)
        ready = self.in_station(now)
        # if the alien the player attacked is also hitting them in the safe zone, the zone does not apply to them: the "Demilitarized zone" text
        # is not shown (player report 2026-10-28, real game)
        void = any(n.alive and self.npc_retaliating(n) for n in self.npcs.values())
        if (gid == self.near_gate and peace == self.gate_peace and inside == self.station_inside and void == self.peace_void
                and ready == getattr(self, 'equip_ready', None)):
            return
        was = getattr(self, 'equip_ready', None)
        self.equip_ready = ready
        self.gate_peace, self.station_inside, self.peace_void = peace, inside, void    # also on entering/leaving the station (inStation, inPeaceArea; recording)
        msgs = [('BeaconCommand', self.p.beacon(s, near_gate=bool(g), pos=(hx, hy), gate_peace=peace,
                                                radiation=self.radiation_since is not None, void=void))]
        if ready != was:          # whether equipment can be changed (in_station; recording: on arrival and on leaving, in pairs)
            msgs += [('EquipReadyCommand', {'ready': ready}),
                     legacy('0|n|MSG|3|2|%s|' % ('msg_equip_ready' if ready else 'msg_equip_not_ready'))]
        if gid == self.near_gate:
            self.send(msgs)
            return
        old = next((x for x in self.gates if x['gateId'] == self.near_gate), None)
        if old:
            msgs.append(H.gate_available(old, False))
        if g:
            msgs.append(H.gate_available(g, True))
            msgs += self.p.hint(IP.JUMP_GATES)
        self.near_gate = gid
        self.send(msgs)

    def jump(self, f=None):
        """JumpRequest: if a portal is nearby, JumpInitiatedCommand, ~3 s later the map change (the session does it)."""
        with self.lock:
            g = next((x for x in self.gates if x['gateId'] == self.near_gate), None)
            if not g or self.jumping or self.hero_dead:
                if not (g or self.jumping or self.hero_dead):
                    self.send([stm('jumpgate_failed_no_gate')])     # "Jump not possible! You're not located close enough to a jump gate."
                return False
            if g.get('wormhole'):
                g = dict(g, target=self.wormhole_dest())         # again on every pass: graveyard or a random map
            if H.map_class(self.map_id).startswith('4-') and time.time() - self.last_pvp < ITEMS['combat_items']['jump_cpu']['combat_sec']:
                self.send([stm('jumpgate_failed_pvp_map')])         # on a war map (4-X) the portal cannot be used while PvP goes on (fandom Portal)
                self.log('   portal %d: PvP in progress (4-X)' % g['gateId'])
                return True
            need = 0 if g.get('gate') else H.level_required(g['target'], self.p.d['pilot'].get('factionId'))
            if self.p.d['pilot'].get('level', 1) < need:
                # the client's text: "You need level %! for the jump. Not possible to jump from your level."
                self.send([legacy('0|A|STM|jumplevelfalse|%%!|%d' % need)])
                self.log('   portal %d: %s requires level %d' % (g['gateId'], H.name(g['target']), need))
                return True
            if g.get('fee') == 'silver_key' and not self.pay_key():
                self.send([legacy('0|A|STM|msg_hidden_pirate_map_no_silverkey')])     # "You need a Silver Booty Key to enter 5-4."
                self.log('   portal %d: no Silver Booty Key for 5-4' % g['gateId'])
                return True
            if g.get('windowed') and self.gate_window:  # windowed portal: the mode's window instead of jumping (pve_modes.py)
                self.gate_window(g)
                return True
            if g.get('paid') and self.gate_fee:     # paid portal (Frozen Labyrinth's corner portals: Labyrinth Key)
                ok, fee = self.gate_fee(g)
                if fee:
                    self.send(fee)
                if not ok:
                    return True
            self.abilities.reveal()
            self.jumping, self.attacking, self.target = True, False, None
            for n in self.npcs.values():
                if self.ours(n):
                    n.engaged = False
            self.send([('JumpInitiatedCommand', {'mapId': g['target'], 'gateId': g['gateId']})])
            self.log('   portal %d: %s -> %s jump started' % (g['gateId'], H.name(self.map_id), H.name(g['target'])))
            if self.on_jump:
                self.later(H.JUMP_DELAY_SEC, lambda: self.on_jump(g['target'], g))
            return True

    def resend(self):
        """Map reloaded (e.g. respawn): announce all NPCs and boxes again; the portal/safe zone state and the
        attack protection are resent (the client cleared the map)."""
        with self.lock:
            self.reload_pending = False
            self.equip_ready = None
            self.near_gate, self.gate_peace, self.station_inside = None, None, None   # the next check_gates resends the marker
            self.seen_items.clear()                                                    # the client cleared the map
            self.players.clear()                                                     # the other players (shared map) at the next step
            self.pets.clear()
            msgs = self.visible_msgs(time.time()) + \
                   [self.box_cmd(h, b) for h, b in self.boxes.items()] + \
                   [self.ore_msg(h) for h in self.ores] + [H.jumpgate_create(g) for g in self.gates if 'designId' in g] + \
                   self.alien.capsule_msgs() + (self.low.asset_msgs() if self.low else []) + self.items.mine_msgs()
            self.near_assets, self.near_giver = None, None
            left = self.invuln_until - time.time()
            if left > 0:
                msgs.append(self.invuln_msg(True))
                self.later(left, self.end_invuln)
            self.send(msgs + self.map_effect_msgs())
            self.deliver(self.items.mine_snapshot(time.time()) + self.items.mine_effect_msgs(replay=True))    # the client cleared the mines along with the map
            self.check_gates(time.time())

    def map_effect_msgs(self):
        """The map's visual effect: the flashlight on Trial of Terrors maps (VisualModifierCommand FLASHLIGHT; client
        VisualModifierAssemblyHelper -> FlashLightEffect2D: a dark veil, a cone of light in the ship's direction). The client deletes the effect on a map
        change, reload and repair (ParticleEffectComponentSystem.RemoveAllEffects): it is resent when the world is built and on
        every reload. The panel's "karanlik" setting turns it off."""
        if not (self.dark and SET.get('dark')):
            return []
        return [('VisualModifierCommand', dict(userId=self.hid, modifier=FLASHLIGHT, attribute=0, additionalAttribute='', count=0,
                                               activated=True))]

    # ------------------------------------------------------------ client requests
    def on_move(self, f):
        with self.lock:
            now = time.time()
            if self.pet and self.pet.trading:
                self.pet.trade_close(now)      # the client sends nothing when it closes the trade window; moving or selecting another module ends the trade (original game)
            self._effect_destination = None
            speed = self.p.d['ship'].get('speed', 300)
            x, y = f['targetX'], f['targetY']
            if speed <= 0:
                self._effect_destination = (x, y)          # while standing, a new request replaces the old pending target
                x, y = self.hero_pos(now)
                self.hero = Mover(x, y)
                ms = 0
            else:
                ms = self.hero.go(x, y, speed, now, start=(f['positionX'], f['positionY']))
            if self.shared:                 # the players who see it (shared map)
                self.shared.movement(self, x, y, ms)
            if self.sold:                  # recording: on the first MoveRequest after a sale, 0|UI|W|MIW|ore_trade (the window shrinks)
                self.sold = False
                self.send([legacy('0|UI|W|MIW|ore_trade')])

    def selection(self, n):
        # for bosses with a string model (DREADFYRE_FORTRESS, EMPEROR_KRISTALLON_BOSS_2) shipType is the client's npcId
        stype = int(n.model) if str(n.model).isdigit() else int(n.d.get('npc_id', 0))
        # official server recording (2026-10-25): the maximum shield of an alien with a shield is the definition's plus 1 (StreuneR 30,000 / 30,001, Curcubitor
        # 270,000 / 270,001, Boss Curcubitor 5,400,001); a full shield is the definition itself
        return ('ShipSelectionCommand', dict(userId=n.id, shipType=stype, shield=int(n.shield),
                                             shieldMax=n.d['shield'] + 1 if n.d['shield'] else 0,
                                             hitpoints=int(n.hp), hitpointsMax=n.d['hp'], nanoHull=0, maxNanoHull=0, shieldSkill=False))

    def asset_at(self, uid):
        """The position of a hittable map entity (rival station module) or None."""
        return self.asset_targets.asset_pos(uid) if self.asset_targets and uid not in self.npcs else None

    def select(self, f):
        with self.lock:
            n = self.npcs.get(f.get('targetId'))
            if n and n.alive and n.bot is not None and time.time() < n.__dict__.get('emp_lock', 0):
                self.send([('ShipDeselectionCommand', {})])      # the bot's EMP: the targeting device does not work for a short time (bot/active_items.emp)
            elif n and n.alive:
                if self.target not in (None, n.id) and self.p.ship()['lootId'] == 'ship_cyborg' and                         SA.is_active(self.p, 'ability_venom'):           # forum 160373: Cyborg Singularity II ends when another target is clicked
                    self.abilities.end_now('ability_venom', time.time())
                if self.attacking and self.target != n.id:
                    self.laser_stop()            # the attack ends when another target is selected (real game; in the client ShipInfo.set_Target drops IsAtk)
                self.target = n.id
                self.send([self.selection(n)] + ([] if n.d.get('friendly') else self.p.hint(IP.ATTACK)))
            elif self.own_pet(f.get('targetId')):           # its own P.E.T.: hittable (for Kamikaze's HP threshold; pet_laser)
                self.target = self.pet.pid
                self.send([self.pet.selection_msg()])
            elif self.asset_at(f.get('targetId')):          # the client selects the entity with ShipSelectionCommand + AssetInfoCommand
                self.target = f.get('targetId')
                self.send(self.asset_targets.asset_select(self.target))
            elif self.player(f.get('targetId')):            # other player (friend server): selected, HP watched (shared_view)
                w = self.player(f.get('targetId'))
                self.target, self.attacking, self.choice = w.hid, False, self.player_selection(w)
                self.send([self.choice])

    def laser_start(self, f):
        with self.lock:
            n = self.npcs.get(f.get('targetId'))
            pet = self.own_pet(f.get('targetId'))          # its own P.E.T. (pet_laser)
            asset = None if n or pet else self.asset_at(f.get('targetId'))
            player = self.player(f.get('targetId')) if not n and not asset and not pet else None
            if n is not None and n.bot is not None:
                denied = BG.attack_error(self, n) or ([('ShipDeselectionCommand', {})]       # cloaked bot: only the one who selected it hits it
                                                        if (n.__dict__.get('hidden') and self.target != n.id)
                                                        or time.time() < n.__dict__.get('emp_lock', 0) else [])
                if denied:
                    self.send(denied)
                    return
            if player:
                denied = PVP.attack_error(self, player, time.time())
                if denied:
                    self.send(denied)
                    return
            if (not asset and not pet and not player and (not n or not n.alive)) or self.hero_dead:
                return
            if asset:                                       # entity (double click: AttackLaserRequest) - cannot be hit while the deflector is on
                err = self.asset_targets.asset_attackable(f.get('targetId'))
                if err:
                    self.send(err)
                    return
            uid = n.id if n else f.get('targetId')
            self.end_invuln(force=True)          # on attacking, the protection from repair on the spot is lifted
            self.abilities.reveal()              # on attacking, cloaking ends
            self.items.reveal()                  # the cloak CPU too
            self.target, self.attacking = uid, True
            self.next_laser = max(self.next_laser, time.time())
            self.send([('UIItemAddHighlightCommand', dict(
                soundModule=mod('SoundTriggerModule', playSound=False, soundId=0), itemSource=mod('UiItemSourceModule', itemSource=0),
                highlightType=mod('HighlightTypeModule', type=6), itemId=LASER_AMMO)),
                legacy('0|n|LSH|%d|%d' % (uid, self.hid))])

    def laser_stop(self, notify=True):
        with self.lock:
            was = self.attacking
            self.attacking = False
            if notify:
                self.fire = False            # the end goes to everyone below (so step does not resend it)
                msgs = [('AttackAbortLaserCommand', {'uid': self.hid})]
                if was:
                    msgs.append(('UIItemRemoveHighlightCommand', dict(itemId=LASER_AMMO, itemSource=mod('UiItemSourceModule', itemSource=0),
                                                                     highlightType=mod('HighlightTypeModule', type=6))))
                self.send(msgs)

    def rocket(self, f):
        with self.lock:
            now = time.time()
            uid = f.get('targetId')
            n = self.npcs.get(uid)
            asset = self.asset_at(uid) if not n else None
            rocket = self.p.d['selected']['rocket']
            player = self.player(uid) if not n and not asset else None
            if player:
                PVP.rocket(self, player, now)
                return
            special = CIT.special(rocket)          # the special rocket has its own cooldown (combat_items.py)
            # cooldown allowance: since the client starts its counter when the message arrives, a request can arrive just before the cooldown ends (live trial:
            # a rocket arriving at 3.89 s in a 4 s cooldown was silently ignored)
            if (not special and now < self.rocket_ready - ROCKET_ALLOWANCE) or (not asset and (not n or not n.alive)) or self.hero_dead or self.jumping:
                return
            if asset:
                denied = self.asset_targets.asset_attackable(uid)
                if denied:
                    self.send(denied)
                    return
                if special and not (CIT.ROCKETS[rocket].get('damage') or CIT.ROCKETS[rocket].get('shield_damage')):
                    return
            hx, hy = self.hero_pos(now)
            nx, ny = asset if asset else n.mover.pos(now)
            if math.hypot(nx - hx, ny - hy) > COMBAT['rocket_range']:
                self.send([range_exceeded(uid, COMBAT['rocket_range'], 0)])
                return
            if special:
                self.items.fire_special(rocket, n if n else uid, now)
                return
            if self.p.use_ammo(rocket, 1) is None:
                sub, msgs = self.ammo_out('rocket', rocket, 1)    # if auto switch is on, the same shot with the new type
                self.send(msgs)
                if not sub or self.p.use_ammo(sub, 1) is None:
                    return
                rocket = sub
            if rocket != IP.PLT_2021 and self.p.ammo(IP.PLT_2021) > 0:
                h = self.p.hint(IP.EQUIP_YOUR_ROCKETS)            # "Why did you not equip the PLT-2021?" (hint once)
                if h:
                    self.send(h)
            self.end_invuln(force=True)
            self.abilities.reveal()
            self.items.reveal()
            self.last_combat = now
            self.stop_repair()
            self.p.ach('shot', weapon='ROCKET_LAUNCHER')
            ms = int(COMBAT['rocket_cooldown_ms'] * (0.5 if self.p.premium else 1)                  # Premium: "50% shorter rocket reload"
                     * (1 + self.p.mods().get('rocket_cooldown', 0))                               # 3D Ring +%25, 3D Dome -%25, Demon -%5
                     * EX.rocket_factor(self.p) * SET.multiplier('rocket_cooldown'))                          # R0K-T01: halved; panel
            ms = self.abilities.rocket_ms(ms, now)                  # Rapid Fire (Tartarus)
            self.rocket_ready = now + ms / 1000
            hit = random.random() < self.rocket_hit(rocket)
            self.send(self.ammo_msgs(rocket) + [self.rocket_msg(uid, hit, ITEMS['rockets'].get(rocket, {}).get('uid', 1)),
                       ('MenuItemCooldownGroupTimerCommand', dict(timerState=mod('TimerStateModule', timerStateValue=2),
                                                                  cooldownType=mod('CooldownTypeModule', typeValue=4), maxTime=ms, time=ms))])
            dmg = int(ITEMS['rockets'].get(rocket, {'damage': 1000})['damage'] * random.uniform(0.85, 1.0)   # recording: R-310 853/991
                      * (1 + self.p.mods().get('rocket', 0) + self.p.mods().get('enemy_rocket', 0) + (self.p.mods().get('npc', 0) if n else 0))
                      * (1 + self.p.lab_bonus(1)))
            if self.p.lab_bonus(1):
                self.lab_spend(1)                   # rocket upgrade: 1 per rocket
            if hit:
                self.later(COMBAT['rocket_flight_sec'], lambda: self.hit_asset(uid, dmg, 0) if asset else self.hit_npc(uid, dmg, 0, ammo=rocket))
            else:
                self.later(COMBAT['rocket_flight_sec'], lambda: self.send([('AttackMissedCommand', dict(
                    attackType=attack_type(0), targetUserId=uid, skillColorId=0))]))
            self.later(ms / 1000, lambda: self.send([('MenuItemCooldownGroupTimerCommand', dict(
                timerState=mod('TimerStateModule', timerStateValue=0), cooldownType=mod('CooldownTypeModule', typeValue=4),
                maxTime=ms, time=0))]))

    def rocket_hit(self, rocket):
        """The rocket's hit chance: base (npc.json roket_isabet; BDR-1211 100%) x (1 + Heat-Seeking Missiles + DMG-H01 + status)."""
        if self.tech.full_rocket_hit():
            return 1.0                                      # Precision Targeter
        m = self.p.mods()
        base = ITEMS['rockets'].get(rocket, {}).get('hit', COMBAT['rocket_hit_chance'])
        bonus = m.get('rocket_hit_chance', 0) + m.get('hit', 0)
        return SET.chance('player_hit_chance', min(1.0, base * max(0.0, 1 + bonus)))     # panel

    def collect(self, f):
        """CollectBoxRequest {itemHash, boxX/Y, posX/Y}: the client takes the ship to the box and sends it. The distance is measured with the ship position
        the server knows (as with ore): the client's posX/posY is not the ship but the clicked object's position in the scene; in 3D the box
        itself, in 2D its Y is always 0 (in 2D boxes were not being collected, H80). If the ship is still on its way the box is taken on arrival."""
        with self.lock:
            h = f.get('itemHash')
            if h not in self.boxes or not self.own(self.boxes[h]) or self.hero_dead or self.jumping:
                return
            if not self.box_near(h):
                self.collect_wish = (h, time.time() + COLLECT_WAIT_SEC)
                return
            self.collect_wish = None
            self.take_box(h)

    def beam_msg(self, by_pet=False):
        """Collection beam: 0|A|SLA|mode|unit (client: SetAttributeAssemblyHelper.AssembleCollectionBeamActive). The beam comes out of
        the unit; mode 0 plays the sound of the object the player clicked (Hero.LastCollectedSoundId; always 0|player in the recording), 1 plays the collection
        beam sound (beam0, sound 3). When the P.E.T. collected it also sent 0|ship: the beam came out of the ship and the last sound (often 0 = laser) played."""
        if by_pet and self.pet:
            return legacy('0|A|SLA|1|%d' % self.pet.pid)
        return legacy('0|A|SLA|0|%d' % self.hid)

    def box_near(self, h, now=None):
        b = self.boxes.get(h)
        hx, hy = self.hero_pos(now)
        return bool(b) and math.hypot(b['x'] - hx, b['y'] - hy) <= COMBAT['harvest_distance']

    def collect_tick(self, now):
        """The requested box: taken when the ship arrives; the request is dropped if the time runs out, the box is gone or the ship dies."""
        h, until = self.collect_wish
        if now > until or h not in self.boxes or self.hero_dead:
            self.collect_wish = None
        elif not self.jumping and self.box_near(h, now):
            self.collect_wish = None
            self.take_box(h)

    def take_box(self, h, by_pet=False):
        """Take the box (the player or the P.E.T.'s automatic collector): a cargo box's ores as much as fits in the cargo (the part that does not fit stays in the box on the ground), a bonus box's
        credits/uridium/ammo. The P.E.T.'s rescue protocol (AI-S) increases the contents of a box the P.E.T. collected (the client "boxes,
        collected by your P.E.T.")."""
        with self.lock:
            b = self.boxes.get(h)
            if not b or not self.own(b) or (by_pet and b.get('no_pet')):      # the P.E.T. cannot collect Vortex of Greed boxes (Ö4)
                return False
            foreign = b['tip'] in CARGO_BOXES and not self.own_tag(b.get('owner_tag')) and SET.get('cargo_ownership')
            if foreign and by_pet:
                return False                                # the P.E.T. does not collect someone else's cargo
            boost = 1 + (self.pet.proto('box') if by_pet and self.pet else 0)
            m = self.p.mods()          # pilot skills: Tractor Beam I/II (cargo/bonus box), Luck (bonus box uridium)
            pre = []
            cargo_box = b['tip'] in CARGO_BOXES
            if cargo_box:                                       # auto-refining first (if the setting is on): room is made
                pre = self.auto_refine()
            if cargo_box and self.p.cargo_free() < 1 and any(int(k) in self.p.CARGO_ORES for k in b['contents']):
                self.send(pre + [legacy('0|A|STM|loadfull')] + self.p.hint(IP.FULL_CARGO))     # cargo full: the box stays in place
                return False
            if b['tip'] in LOOT.BOXES and not b.get('event'):
                return False if by_pet else self.open_booty(h, b)
            ores, left, free = {}, {}, self.p.cargo_free()
            if cargo_box:                                   # ores are taken as much as fits in the cargo; the part that does not fit stays in the box (the box is not deleted)
                mult = boost * (1 + m.get('cargo_box', 0))
                for k, v in sorted(b['contents'].items()):
                    take = want = int(v * mult)
                    if int(k) in self.p.CARGO_ORES:            # Xenomit takes no space: all of it is taken
                        take = min(want, free)
                        free -= take
                        if take < want and v - math.ceil(take / mult - 1e-9) > 0:     # what was taken (base unit) is deducted from the box
                            left[k] = v - math.ceil(take / mult - 1e-9)
                    if take > 0:
                        ores[int(k)] = take
            if left:
                b['contents'] = left
            else:
                del self.boxes[h]
            extra = b.pop('extra', None) if cargo_box else None           # the extra resources in the box (extra_loot box) on the first take
            msgs = pre + [self.beam_msg(by_pet)] + ([] if left else [('RemoveCollectableCommand', {'collected': True, 'hash': h})])
            if foreign and not b.get('stolen'):             # someone else's box: penalty once (on a partial take the box stays on the ground)
                b['stolen'] = True
                msgs += self.cargo_penalty(b['owner_tag'])
                BG.on_box_taken(b['owner_tag'], self.p.d['pilot'].get('userName', ''))
            if cargo_box:
                totals = self.p.add_ores(ores)
                content = [mod('OreCountModule', oreType=mod('OreTypeModule', typeValue=t), count=c) for t, c in sorted(ores.items())]
                msgs += [('LMCollectResourcesCommand', dict(priorityMode=mod('LogMessengerPriorityModule', priorityModeValue=0),
                                                            contentList=content))] if content else []
                msgs += [('AttributeOreCountUpdateCommand', {'oreCountList': totals})]
                if not left:
                    msgs += self.quest('cargo')          # box counter: when the box is emptied (on a partial take the box stays on the ground)
                for t, c in sorted(ores.items()):
                    msgs += self.quest('loot', loot=ORE['kinds'].get(str(t), ''), amount=c, box=True)    # box: SALVAGE quest
                    RT.note(self.p, 'received_item', ORE['kinds'].get(str(t), ''), c)       # logbook
                for loot, c in sorted((extra or {}).items()):
                    c = int(c * boost)
                    if loot == 'resource_pet-fuel' and self.grant:
                        msgs += self.grant(loot, c)              # into the P.E.T.'s tank (storage fuel is never burnt)
                    else:
                        self.p.add_resource(loot, c)
                        msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, c)))
                    msgs += self.quest('loot', loot=loot, amount=c, box=True)
                msgs += self.auto_refine()               # after every collection (if the setting is on)
                if left and self.p.cargo_free() < 1:     # partial take: the rest is taken once room is made (sale/refining)
                    msgs += [legacy('0|A|STM|loadfull')] + self.p.hint(IP.FULL_CARGO)
            elif b.get('al'):                        # a box with its own collect function (Ö4: Vortex's Stellar Coin boxes)
                msgs += b['al'](b) or []
            elif b.get('event'):                       # event box (event_maps.py): the contents are drawn when opened
                got = EVT.roll(b['event'], m)
                for loot, n in got:
                    msgs += self.grant_loot(loot, n)
                    if loot.startswith('resource_collectable_'):          # collection quest (Collect 200 Proxium: Permafrost's UFO / Ufonit boxes)
                        msgs += self.quest('loot', loot=loot, amount=n)
                if b['tip'].startswith('MIMESIS_AI_'):    # Mimesis Chest: a buff with 30% chance on top of the reward (mimesis_chest.py)
                    msgs += MCH.roll(self)
                if b['event'].get('renew_sec'):
                    self.schedule(random.uniform(*b['event']['renew_sec']) * SET.multiplier('box_respawn'), 'event_box', b['tip'])
                self.log('   event box %s: %s' % (b['tip'], ', '.join('%s x%d' % x for x in got) or '-'))
            elif b['tip'] == 'BONUS_BOX':
                what, amount = b['contents']
                seq = self.rules.get('bonus_sequence')
                if seq:                                  # Cubikon Graveyard: the first 1,000 UCB-100, then LCB-10 increasingly (wiki)
                    what, amount = seq[min(self.boxes_taken, len(seq) - 1)]
                    self.boxes_taken += 1
                cap = self.rules.get('bonus_ucb_cap')
                if cap:                                  # ??? map: 1,000 each up to 100,000 UCB-100, then LCB-10 (forum 127347)
                    (what, amount), lim, rest = cap[0], cap[1], cap[2]
                    if self.boxes_taken * amount >= lim:
                        what, amount = rest
                    self.boxes_taken += 1
                x1 = self.x1_reward()            # at a high level in its own X-1 the bonus box also decreases (fandom 1-1, 2-1, Lowers)
                amount = int(amount * boost * (1 + m.get('bonus_box', 0)) * (1 + (m.get('bonus_uridium', 0) if what == 'uridium' else 0))
                             * ((x1 > 0) if what == 'energy' else x1))     # a single unit of energy cannot decrease in steps: only 15+ empty (HARITALAR-7)
                amount = SET.amount({'credits': 'credits', 'uridium': 'uridium', 'energy': 'gate_energy'}.get(what, 'collecting'), amount, 'box')  # panel
                if amount <= 0:
                    pass                                 # level 15+ in its own X-1: the bonus box is empty (x1_reward)
                elif what == 'credits':
                    msgs += self.reward_msgs(self.p.gain(credits=amount, reason='collect_bonusbox'), credits=amount)
                elif what == 'uridium':
                    msgs += self.reward_msgs(self.p.gain(uridium=amount, reason='collect_bonusbox'), uridium=amount)
                elif what == 'energy':
                    msgs += self.gg_energy(amount) if self.gg_energy else []      # the Galaxy Gate generator's free energy
                    RT.note(self.p, 'gg_extra_energy_got', count=amount)
                elif not what.startswith('ammunition_'):
                    # the World Editor's non-ammo reward (ABR, resource, equipment): the shop's reward path (it was written to ammo and did not
                    # show in Assembly: player report 2026-10-30)
                    RT.note(self.p, 'received_item', what, amount)
                    if self.grant:
                        msgs += self.grant(what, amount)
                    else:
                        self.p.add_resource(what, amount)
                    if what.startswith('resource_collectable_'):
                        msgs += self.quest('loot', loot=what, amount=amount)
                else:
                    RT.note(self.p, 'received_item', what, amount)
                    self.p.add_ammo(what, amount)
                    msgs.append(legacy('0|LM|ST|BAT|%s|%d' % (what, amount)))
                    self.p.ach('box_ammo', weapon='LASER' if what.startswith('ammunition_laser_') else 'ROCKET_LAUNCHER', count=amount)
                self.schedule(random.uniform(30, 60) * SET.multiplier('box_respawn'), 'bonus')
                msgs += self.quest('bonus')
            self.send(msgs)
            if not by_pet:
                self.abilities.reveal()          # collecting a box ends cloaking
            if not left:                         # achievement counter: when the box is emptied
                self.p.ach('box', tip=b['tip'], pet=by_pet)
            if by_pet:
                self.log('   P.E.T. collected a box: %s' % b['tip'])
            return True

    def open_booty(self, h, b):
        """Keyed box (loot.py): without a key the box stays and the client's text; a green key can be bought automatically in the settings.
        If there is one, opening starts: the collection beam for loot.OPEN_SEC and a countdown above the ship (0|A|SLA|0|ship|s: the client's
        SetAttributeAssemblyHelper.AssembleCollectionBeamActive reads the 6th field as seconds, TimerCountdownEffect) and in the log
        "Collecting pirate booty." (0|LM|ST|SLA); when the time is up finish_booty. It used to open instantly (user report 2026-10-24;
        ~5 s in the official game, the user's decision 3 s). A second click while opening: "Collecting box already" (0|LM|ST|BAH). Called
        while the lock is held -> did opening start."""
        kind = b['tip']
        box = LOOT.BOXES[kind]
        key, msgs = box['key'], []
        if self.opening:
            self.send([legacy('0|LM|ST|BAH')])
            return False
        if self.p.resource(key) < 1 and key == LOOT.GREEN_KEY:
            if not self.p.gameplay('autoBuyGreenBootyKeys'):           # Settings > Gameplay
                self.send([legacy('0|A|STM|msg_booty-key-green_auto_buy_not_active')])
                return False
            msgs = self.auto_buy(key, 1) if self.auto_buy else []
            if self.p.resource(key) < 1:
                self.send([legacy('0|A|STM|msg_booty-key-green_no_uridium_for_auto_buy')])
                return False
        if self.p.resource(key) < 1:
            self.send([legacy('0|A|STM|%s' % box['missing_message'])])
            return False
        self.opening = {'h': h, 'end_time': time.time() + LOOT.OPEN_SEC}
        self.send(msgs + [legacy('0|LM|ST|SLA'), legacy('0|A|SLA|0|%d|%d' % (self.hid, LOOT.OPEN_SEC))])
        self.log('   %s opening (%d s)' % (box['name'], LOOT.OPEN_SEC))
        return True

    def booty_tick(self, now):
        """The loot box being opened: it opens when the time is up. If the ship moves away from the box, dies, jumps or the box is gone (on a shared map
        someone else took it) it is canceled: 0|A|SLC (the client writes "Collection canceled." and in 3D removes the beam and the counter). The client has no
        cancel of its own, the server decides."""
        h = self.opening['h']
        if h not in self.boxes or self.hero_dead or self.jumping or not self.box_near(h, now):
            self.opening = None
            self.send([legacy('0|A|SLC')])
            self.log('   loot box opening canceled')
        elif now >= self.opening['end_time']:
            self.opening = None
            self.finish_booty(h, self.boxes[h])

    def finish_booty(self, h, b):
        """Opening finished: a key is spent, a reward from the contents is given with the shop's reward function (the beam and counter end by themselves)."""
        kind = b['tip']
        box = LOOT.BOXES[kind]
        key, msgs = box['key'], []
        if self.p.resource(key) < 1:                                    # the key was lost while opening (sale, other spending)
            self.send([legacy('0|A|STM|%s' % box['missing_message'])])
            return False
        del self.boxes[h]
        self.p.add_resource(key, -1)
        if box.get('ledger'):
            RT.note(self.p, box['ledger'])                              # logbook: "… booty key used"
        got = LOOT.pick_all(self.p, kind)                                 # if an Epic pack comes out, all the parts
        msgs += [('RemoveCollectableCommand', {'collected': True, 'hash': h})]
        if LOOT.key_line(self.p, kind):
            msgs.append(legacy(LOOT.key_line(self.p, kind)))
        for loot, n in got:
            msgs += self.grant_loot(loot, n)      # money (Prime Astral's EP/honor …) to the account, the rest with the shop's reward function; the panel's multipliers
        if box.get('renew_sec'):                                       # Echo chest: dropped by the boss, does not respawn
            self.schedule(LOOT.respawn_delay(kind) * SET.multiplier('box_respawn'), 'booty', kind)
        self.send(msgs)
        self.abilities.reveal()
        self.p.ach('box', tip=kind, pet=False)
        self.log('   %s opened (%s): %s' % (box['name'], key, ', '.join('%s x%d' % x for x in got)))
        return True

    # ------------------------------------------------------------ combat
    def reward_msgs(self, tot, ep=0, honor=0, credits=0, uridium=0):
        msgs = []
        if ep:
            msgs.append(legacy('0|LM|ST|EP|%d|%d|%d' % (ep, tot['ep'], tot['level'])))
        if tot.get('leveled_up'):
            msgs.append(('LevelUpCommand', {'uid': self.hid, 'newLevel': tot['level']}))     # level-up effect
        if honor:
            msgs.append(legacy('0|LM|ST|HON|%d|%d' % (honor, tot['honor'])))
        if credits:
            msgs += [legacy('0|LM|ST|CRE|%d|%d' % (credits, tot['credits'])), self.currency_item('currency_credits', CREDITS_ITEM, tot['credits'])]
        if uridium:
            msgs += [legacy('0|LM|ST|URI|%d|%d' % (uridium, tot['uridium'])), self.currency_item('currency_uridium', URIDIUM_ITEM, tot['uridium'])]
        if (credits or uridium) and self.quick_buy:
            msgs += self.quick_buy()
        rank = RT.live_rank(self.p) if ep or honor else None          # rank points changed: if a threshold was crossed, the rank at once
        if rank:
            msgs += self.rank_msgs(*rank)
        return msgs

    def kill_notice(self, msgs):
        """The kill reward's on-screen lines (0|LM|ST|EP/HON/CRE/URI): in the middle of the screen only the latest kill's, at most once per
        NOTICE_ARA_SN; the lines of those in between go only to the log. The client's instant log (InstantLog, 4 lines) shows all the lines
        arriving in the same frame: when many aliens were killed the rewards overlapped on screen (user report 2026-10-25).
        -> messages to send right away (those outside the lines; old lines that fall to the log)."""
        line = lambda m: m[0] == 'LegacyModule' and m[1]['message'].startswith(REWARD_LINES)
        lines, out = [m for m in msgs if line(m)], [m for m in msgs if not line(m)]
        if not lines:
            return out
        if self.notice:
            out = self.log_only(self.notice) + out         # a new one came in its place: the earlier ones only in the log
        self.notice = lines
        now = time.time()
        if now >= self.notice_at + NOTICE_GAP_SEC:
            return out + self.flush_notice(now)
        if not self.notice_timer:
            self.notice_timer = True
            self.later(self.notice_at + NOTICE_GAP_SEC - now, lambda: self.send(self.flush_notice(time.time())))
        return out

    def flush_notice(self, now):
        self.notice_timer = False
        lines, self.notice = self.notice or [], None
        if lines:
            self.notice_at = now
        return lines

    @staticmethod
    def log_only(lines):
        """0|LM|ST reward lines -> the same texts written only to the log (MessageCommand displayTarget 0; the client's keys)."""
        out = []
        for _, f in lines:
            p = f['message'].split('|')
            out.append(('MessageCommand', dict(displayTarget=0, displayStyle=1, messageModule=mod('WildcardMessageModule', message=mod(
                'MessageKeyListWildcardModule', baseKey=REWARD_LINES_KEYS[p[3]], textStyle=0,
                baseKeyType=mod('ReplacementTypeModule', typeValue=5),
                wildCardReplacements=[mod('MessageWildcardReplacementModule', wildcard='%!', replacement='{:,}'.format(int(p[4])),
                                          replacementType=mod('ReplacementTypeModule', typeValue=0))])))))
        return out

    def rank_msgs(self, old, new):
        """Rank changed: the client's text ("Congratulations, you've reached a new rank. This rank is:" / rank_down and the rank's name,
        rang_N) and the icon on the ship (badge_refresh)."""
        self.log('   rank %s -> %s' % (old, new))
        msgs = []
        if 1 <= new <= len(RT.R['thresholds']):
            msgs += [legacy('0|A|STM|%s' % ('rank_up' if new > old else 'rank_down')), legacy('0|A|STM|rang_%d' % new)]
        return msgs + self.badge_refresh()

    def badge_refresh(self):
        """The rank icon on the ship at once: the client reads dailyRank only from ShipInitializationCommand. With refreshMap=False, if the ship
        type (typeId) changed it rebuilds the ship in place (ShipInitializationCommandHandler: ReleaseShip, Remove, InitMyUnit;
        the map is not reloaded), if it is the same it does nothing: first with another type, then with the real ship."""
        name, f = self.p.generate('@gemi')
        x, y = self.hero_pos()
        f.update(refreshMap=False, x=int(x), y=int(y))
        other = 'ship_yamato' if f['typeId'] == 'ship_phoenix' else 'ship_phoenix'
        # the new ship object has no title, drones and modules (live test: the drones vanished): the ones in the entry bundle again
        return [(name, dict(f, typeId=other)), (name, f)] + (self.unit_msgs() if self.unit_msgs else [])

    @staticmethod
    def currency_item(loot, item_id, amount):
        return ('InventoryItemUpdatedCommand', {'item': mod('InventoryItemModule', upgradeLevel=0, lootId=loot, amount=amount, itemId=item_id,
                                                            star=0, isNew=False, hangarId=0, extAttributes=[], inventoryItemAttributes=[])})

    def hit_npc(self, uid, dmg, atype, shield_only=False, attacker=None, hull_only=False, split=None, strike=False, cannon=0,
                engage=True, source_asset=False, ammo=None):
        """A hit by the hero (or the P.E.T.): the shield absorbs 70% of the damage (from the recording), the rest goes to HP. Ammo like SAB-50
        hits only the shield. split=(to the shield, to the hull): damage with a fixed ratio like a mine (no absorption). engage=False: the hitter is not
        the player (the Clan Battle Station's satellites): the alien does not turn on the player. ammo: the laser's or rocket's ammo; if the type has
        'ammo_only' only that ammo does damage (Referee-Bot: CBO-100 and CBR; the P.E.T., mines and abilities cannot hit it either)."""
        with self.lock:
            n = self.npcs.get(uid)
            if not n or not n.alive or n.d.get('friendly'):         # a friendly ship (Deep Space Echoes: protected/escorted) cannot be hit
                return
            if n.bot is not None and not BG.was_hit(self, n, attacker):    # bot: PvP rules (DMZ, starting map)
                return
            now = time.time()
            immune = (n.invulnerable and n.invulnerable()) or n.effect.invulnerable(now) or self.guarded(n)
            only = n.d.get('ammo_only')            # official Turkish forum 135026: "CBO-100 & CBR HSTM Rockets hariç tüm cephanelere karşı dayanıklı" (resistant to all ammo except CBO-100 & CBR HSTM Rockets)
            if only and ammo not in only:
                immune = True
            if immune:
                dmg = 0
            k = 1.0 if source_asset else SET.multiplier('player_damage', 'pve' if n.bot is None else 'bot')                     # the panel's damage multiplier (laser, rocket, mine, cannon, P.E.T. …)
            if k != 1.0:
                dmg = int(dmg * k)
                if split:
                    split = (split[0] * k, split[1] * k)
            n.last_hit = now
            if getattr(n, 'hidden', False):                          # a cloaked commando becomes visible when hit (Infiltration: infiltration.py)
                n.hidden = False
                self.send([legacy('0|n|INV|%d|0' % n.id)])
            self.alien.attacked(n, attacker, now)
            self.npc_summon(n, now)
            if not attacker and not hull_only:                     # Target Marker; Nidhogg's erosion weakness (particle.py)
                dmg = int(dmg * (1 + n.effect.damage_bonus(now) + self.particle.vulnerability(n.id, now)))
            red = getattr(n, 'damage_reduction', None)                # Ö4: Dreadfyre Fortress's Guardian shields (25% each)
            if red:
                dmg = int(dmg * max(0.0, 1 - red()))
            if shield_only:
                dmg = min(dmg, int(n.shield))
            absorb = n.d.get('shield_absorb', COMBAT['npc_shield_absorb'])           # the type's absorption
            kh = 1.0 if attacker else n.effect.shield_damage(now)                # Diminisher Weaken Shields: damage to the shield increases
            if not attacker:                                                     # shield piercing (Moth +20%, Double Arrow +10%, Pincer -10%):
                absorb = min(1.0, max(0.0, absorb - self.p.mods().get('shield_penetration', 0)))     # falls as points like in PvP
            if split:                                                            # mine (combat_items.py)
                b = 0 if immune else 1 + n.effect.damage_bonus(now)
                to_shield = min(int(n.shield), int(split[0] * b * kh))
                dmg = to_shield + int(split[1] * b)
            else:
                to_shield = dmg if shield_only else 0 if hull_only else min(n.shield, int(round(dmg * absorb)))
                if kh > 1.0 and to_shield and not shield_only:                   # the shield melts kh times the share it absorbed; the share passing to the hull is the same, if the shield runs out its share by kh
                    want = int(round(to_shield * kh))
                    loss = min(int(n.shield), want)
                    taken = to_shield if loss >= want else int(round(loss / kh))
                    dmg, to_shield = dmg - taken + loss, loss
            n.shield -= to_shield
            n.hp = max(0, n.hp - (dmg - to_shield))
            floor = getattr(n, 'hp_floor', 0)                    # Ö4: Guardian "falls" at 1 HP (phase 1-3)
            if floor and n.hp < floor:
                n.hp = floor
                if getattr(n, 'at_floor', None):
                    n.at_floor(n)
            if dmg > 0 and getattr(n, 'damage_hook', None):      # Ö4: the fight's damage counter (progress rewards)
                n.damage_hook(dmg)
            if dmg > 0 and not attacker:
                self.p.ach('damage', count=dmg, npc=n.d.get('npc_id'))
            # summoning and vanishing at an HP threshold (alien.py); reversed controls and EMPs answer only the pilot's own hit, not the P.E.T.'s or a
            # battle station's (a Boss Saimon hit by the base reversed the controls of a pilot who wasn't attacking it: player report 2026-11-02)
            self.alien.on_hit(n, dmg, attacker, now, to_player=engage and not attacker)
            if engage and not attacker:                  # the pilot's own hit lets this NPC fight on inside a protected zone; the P.E.T.'s does not
                if getattr(n, 'station_retaliation', None) is None:
                    n.station_retaliation = {}
                n.station_retaliation[self.hid] = now    # keep each player's permission on a shared NPC
            if engage:
                tag_alien(n, ('h', self.hid), now)                # the first to fire tags (a miss too; the P.E.T.'s hit is also its owner's)
                record_damage(n, ('h', self.hid), dmg)
            if attacker and self.hidden(now):
                engage = False                   # a cloaked player's P.E.T. (kamikaze, laser) does not lock the alien onto the player (report 2026-10-28)
            if engage and not n.engaged:
                n.engaged = True
                n.next_think = min(n.next_think, time.time())   # an attacked NPC reacts at once
                if self.shared:
                    n.foe = self                                  # shared map: turns on whoever hit it
            self.last_shield_hit = to_shield
            msgs = [('AttackHitCommand', dict(attackType=attack_type(atype), attackerId=attacker or self.hid, victimId=n.id,
                                              victimHitpoints=int(n.hp),
                                              victimShield=int(n.shield), victimNanoHull=0, damage=dmg, skilled=atype == 1, strike=strike,
                                              cannonType=cannon))]
            if n.hp <= 0:
                msgs += self.kill(n)
            elif self.target == n.id:
                msgs.append(self.selection(n))
            self.send(msgs)

    @staticmethod
    def respawn_range(n):
        """Respawn time: an ordinary alien 12-25 s; Boss, Uber, Cubikon, Behemoth longer (npc.json respawn_special);
        with the panel's respawn multiplier."""
        o = COMBAT.get('respawn_special', {})
        ev = next((CAL.EVENTS[k]['respawn'][n.tip] for k in sorted(CAL.active())
                   if n.tip in CAL.EVENTS[k].get('respawn', {})), None)     # in an event (Pirate Raid: Uber pirates 150/300 s)
        if ev:
            r = ev
        elif n.tip in o:
            r = o[n.tip]
        elif 'Uber' in n.d['name'] and 'uber' in o:
            r = o['uber']
        elif n.d['name'].startswith('..::{') and 'boss' in o:
            r = o['boss']
        else:
            r = COMBAT['respawn_sec']
        k = SET.multiplier('npc_respawn')
        return r if k == 1.0 else [x * k for x in r]

    @staticmethod
    def npc_range(n):
        """The NPC's firing range: the type's own value; immobile ones longer than the player's range (otherwise they cannot answer back)."""
        r = n.d.get('range') or (COMBAT['npc_fixed_range'] if n.d['speed'] <= 0 else COMBAT['npc_range'])
        return r * SET.multiplier('npc_range')          # panel: alien firing range (laser, rockets, sticky bomb, guards)

    def grant_loot(self, loot, n, source='box'):
        """Reward from a box: money EP/honor/credits/uridium to the account (counts toward the Uridium Bank), the rest with the shop's reward function. source:
        the panel's sub-setting (the modes' money 'mod')."""
        if loot == 'resource_key_access-flb':                              # Labyrinth Key (Ice Box): a counter in the profile, not in the resource storage
            import labyrinth as LB
            return LB.add_keys(self.p, n)
        if loot.startswith('olay_puani:'):                                 # event points (Hatching Out's Viral Boxes: VPP)
            import event_points as OP
            return OP.add(self.p, loot.split(':', 1)[1], n, self.grant)
        cur = {'currency_credits': 'credits', 'currency_uridium': 'uridium', 'currency_experience': 'ep', 'currency_honour': 'honor'}
        n = SET.amount(cur.get(loot, 'collecting'), n, source)                 # the panel's multipliers
        if loot in cur:
            kw = {cur[loot]: n}
            return self.reward_msgs(self.p.gain(reason='collect_bonusbox', **kw), **kw)
        if n <= 0:
            return []
        if self.grant:
            return self.grant(loot, n)
        self.p.add_resource(loot, n)
        return [legacy('0|LM|ST|LOT|%s|%d' % (loot, n))]

    def extra_loot(self, n, specs=None, box=None):
        """Extra rewards (npc.json extra_reward <- aliens.md "Extra destroy rewards"; specs: event drops, event_maps.py): Palladium
        to the cargo (as much as fits), the others (Bifenon, Darksilver Coin, Candy Corn …) to the resource storage; shown in the loot log.
        box: collectible resources (scrap, mucosum, prismatium …) go to this dict, not the storage; they drop with the alien's cargo box and are given
        when the box is collected (take_box; player report 2026-10-27: in the real game they do not come straight to the inventory)."""
        msgs = []
        bm = BOOSTER.mods(self.p)
        boost = 1 + bm.get('special_chance', 0)                              # PRC-B00/B01: chance of Hybrid Alloy and Indoctrine Oil
        for loot, spec in (n.d.get('extra_reward', {}) if specs is None else specs).items():
            special = loot in BOOSTER.B.get('special_chance_sources', ())
            cnt = extra_count(spec, (boost if special else 1.0) * SET.multiplier('drop', 'extra'))
            if special and cnt > 0:
                cnt = int(cnt * (1 + bm.get('special_amount', 0)))          # PRM-B01 (PCOMB-B01): amount x2 (Ö6)
            if loot == 'resource_collectable_agate-splinter' and cnt > 0:
                cnt = int(cnt * (1 + bm.get('agate_amount', 0)))          # AS-B01: Agate Splinter x2
            if cnt <= 0:
                continue
            if loot.startswith(('equipment_', 'ammunition_', 'tech_')) or loot == 'resource_extra-energy' or                     (loot in ('resource_logfile', 'resource_pet-fuel') and self.grant):   # P.E.T. fuel: into the tank, not storage     # the log file goes to the gate generator's counter (skill tree)
                msgs += self.grant(loot, cnt) if self.grant else []      # The Stinger's Caucasus laser (0.5%), A-BL, chaos packs (ammo, NPC Nuke, EE)
                continue
            cnt = SET.amount('collecting', cnt, 'extra')                        # the panel's collection multiplier
            if loot == 'resource_ore_palladium':
                cnt = min(cnt, self.p.cargo_free())
                if cnt > 0:
                    msgs.append(('AttributeOreCountUpdateCommand', {'oreCountList': self.p.add_ores({8: cnt})}))
                    if self.ore_pack:
                        msgs.append(self.ore_pack([8]))
            elif cnt > 0 and box is not None:
                box[loot] = box.get(loot, 0) + cnt
                continue
            elif cnt > 0:
                self.p.add_resource(loot, cnt)
            if cnt > 0:
                msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, cnt)))
                msgs += self.quest('loot', loot=loot, amount=cnt)           # collection quests (Palladium …)
        return msgs

    def cargo_of(self, n):
        """The NPC's cargo box; it decreases at a high level on X-1 maps (npc.json x1_cargo: L7 50% … none at L10+)."""
        boost = 1 + self.p.mods().get('cargo', 0)                       # RES-B01 (booster): alien resources
        cargo = {t: SET.amount('collecting', int(v * boost), 'cargo') for t, v in n.d['cargo'].items()}      # the panel's collection multiplier
        cargo = {t: v for t, v in cargo.items() if v > 0}
        if H.map_class(self.map_id) == 'X-1' and SET.get('x1_cargo'):          # panel: can be turned off
            lv = self.p.d['pilot'].get('level', 1)
            f = next((k for l, k in reversed(COMBAT['x1_cargo']) if lv >= l), 1)
            cargo = {t: int(v * f) for t, v in cargo.items() if int(v * f) > 0}
        return cargo

    def x1_reward(self):
        """On your own X-1 map the kill reward (EP, honor, credits, uridium) decreases at a high level: from level 7, none at 15
        (npc.json x1_reward; the panel's x1_cargo setting turns it off)."""
        if H.map_class(self.map_id) != 'X-1' or H.company(self.map_id) != self.p.d['pilot'].get('factionId') or not SET.get('x1_cargo'):
            return 1
        lv = self.p.d['pilot'].get('level', 1)
        return next((k for l, k in reversed(COMBAT['x1_reward']) if lv >= l), 1)

    @staticmethod
    def aggressive(n):
        """Whether the alien chases the player on its own: the panel's aggression setting (0 the type's setting, 1 all, 2 none). A non-aggressive
        one also answers back when hit."""
        lv = SET.get('npc_aggression')
        return bool(n.d.get('aggressive')) if not lv else lv == 1

    def remove_npc(self, n):
        """The alien withdraws without a reward and without exploding (the fleeing Infiltration commando) -> messages (under the lock)."""
        n.alive = False
        self.npcs.pop(n.id, None)
        msgs = self.pet.npc_gone(n.id) if self.pet else []
        if self.target == n.id:
            self.target, self.attacking = None, False
            msgs.append(('ShipDeselectionCommand', {}))
        if n.id in self.visible:
            self.visible.discard(n.id)
            msgs.append(('ShipRemoveCommand', {'userId': n.id}))
        return msgs

    def kill(self, n):
        if n.bot is not None:
            return BG.was_killed(self, n)
        n.alive = False
        del self.npcs[n.id]
        x, y = n.mover.pos(time.time())
        if BG.is_boss(n):
            BG.witness(self, 'boss', x, y, name=n.d.get('name', ''), who=self.p.d['pilot'].get('userName', ''))
        msgs = []
        pet_stop = self.pet.npc_gone(n.id) if self.pet else []     # if the P.E.T. is firing at it, its laser stops
        if n.d.get('uncounted'):                 # fake Emperor Lordakium: no reward, no box, does not respawn; explodes
            if n.id in self.visible:
                self.visible.discard(n.id)
                msgs += [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': n.id})]
            if self.target == n.id:
                self.target, self.attacking = None, False
                msgs.append(('ShipDeselectionCommand', {}))
            return pet_stop + msgs + self.alien.on_kill(n, x, y)
        if n.id in self.visible:
            self.visible.discard(n.id)
            msgs.append(('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0)))
        if self.target == n.id:
            self.target, self.attacking = None, False
            msgs.append(('ShipDeselectionCommand', {}))
        if msgs and msgs[0][0] == 'ShipDestroyedCommand':
            msgs.append(('ShipRemoveCommand', {'userId': n.id}))
        msgs = pet_stop + msgs
        self.anger.kill(self.lasers(), time.time())          # Asmodeus Fervor
        pay = self.tag_sharers(n, x, y)
        for sp in n.behavior.get('spawn_on_death', []):       # those that spawn on death (Lordakium spores …): they do not respawn
            for k in range(sp.get('count', 1)):
                a = 2 * math.pi * k / max(1, sp.get('count', 1))
                c = self.spawn_npc_at(sp['type'], x + math.cos(a) * 120, y + math.sin(a) * 120)
                self.alien.adopt(n, c)          # counted as the wave's alien at a gate
                c.engaged = n.engaged
                c.next_think = time.time()      # thinks as soon as it spawns (spores attack without waiting)
        if not n.gate and not n.summoned:
            self.schedule(random.uniform(*self.respawn_range(n)), 'npc', n.tip)
        self.drifter_killed(n)
        return msgs + self.alien.on_kill(n, x, y) + self.event.on_kill(n, x, y, w=self, pay=pay) + \
            (self.labyrinth.on_kill(n, x, y) if self.labyrinth else [])

    def tag_sharers(self, n, x, y):
        """Gives the alien's reward to the owner of its tag -> the sharing worlds. The tag is this hero's or their group's: as usual
        (paydaslar); another player's (friend server): theirs and their group's; a bot's: the bot's (the reward, quest and cargo box go to
        it, ship.tag_reward). Whoever finishes off someone else's tagged alien gets neither the reward nor the quest count."""
        who = tag_owner(n, time.time())
        if getattr(n, 'damage_split', None) and self.by_damage(n, x, y):
            return [self]
        if who is not None and who[0] == 'b' and not (who[1] in self.npcs and self.npcs[who[1]].alive):
            who = None                                     # the tagging bot fled or died: the killer gets it
        if who is not None and who[0] == 'h' and who[1] != self.hid and (self.shared is None or not any(
                w.hid == who[1] and w.running and not w.hero_dead for w in self.shared.members)):
            who = None                                     # the tagging player is not on the map
        owner = self
        if not self.own_tag(who):
            owner = None
            if who[0] == 'h' and self.shared is not None:
                owner = next((w for w in self.shared.members if w.hid == who[1] and w.running and not w.hero_dead), None)
            elif who[0] == 'b':
                BG.tag_reward(self, n, who[1], x, y)
            self.log('   %s was tagged by someone else: the reward and quest are theirs' % n.d.get('name'))
            if owner is None:
                return []
        pay = owner.stakeholders()
        bots = BG.group_bots(owner)                    # the bots in the hero's group are sharers too (player report 2026-10-31)
        for w in pay:
            w.npc_reward(n, x, y, len(pay) + len(bots), own=w is owner)
        for b in bots:
            BG.npc_reward(b, n, len(pay) + len(bots))
        return pay

    def by_damage(self, n, x, y):
        """A group alien's reward (EP, honor, credits, uridium) is split between players and bots by the damage they dealt (npc_reward
        ratio, ship.npc_reward share); the cargo box goes to whoever dealt the most. The share of one not on the map is not lost: it is distributed among the rest.
        -> was it split (there is nothing to split with a single damage dealer)."""
        recipients = []
        for who, dmg in n.damage_split.items():
            if who[0] == 'h':
                w = self if who[1] == self.hid else next((o for o in (self.shared.members if self.shared else [])
                                                          if o.hid == who[1] and o.running and not o.hero_dead), None)
                if w is not None:
                    recipients.append((dmg, who, w))
            elif who[1] in self.npcs and self.npcs[who[1]].alive and BG.bot_online(who[1]):
                recipients.append((dmg, who, None))
        if len(recipients) < 2:
            return False
        total = float(sum(a[0] for a in recipients))
        first = max(recipients, key=lambda a: a[0])[1]
        self.log('   %s: reward split by damage (%s)' % (n.d.get('name'), ', '.join('%s%s %d%%' % (a[1][0], a[1][1], 100 * a[0] / total)
                                                                              for a in recipients)))
        for dmg, who, w in recipients:
            if w is not None:
                w.npc_reward(n, x, y, own=w is self, ratio=dmg / total, box=who == first)
            else:
                BG.split_reward(self, n, who[1], dmg / total, x, y, box=who == first)
        return True

    def stakeholders(self):
        """Those who share the alien's reward: the killer and, on a shared map, the members of their group alive on the same map (distance does not matter;
        group.py). In single player, at a gate and without a group only the killer."""
        if self.shared is None:
            return [self]
        return [self] + [w for w in self.shared.members if w is not self and w.running and not w.hero_dead and not w.jumping
                         and self.is_group_member(w.hid)]

    def kill_reward(self, n):
        """The alien's reward to this hero {ep, honor, credits, uridium}: the type's, formation and pilot skills, the X-1 reduction, the panel's
        multipliers."""
        o = dict(n.d['reward'])
        k = getattr(n, 'reward_multiplier', 1)                          # a single alien's multiplier (Infiltration commando: infiltration.py)
        if k != 1:
            o = {a: int(v * k) for a, v in o.items()}
        form = self.p.mods()
        o['ep'] = int(o['ep'] * (1 + form.get('ep', 0)))          # Barrage, Bat, 3D X
        o['honor'] = int(o['honor'] * (1 + form.get('honor', 0)))    # Pincer, 3D Veteran; 3D X removes honor
        o['credits'] = int(o['credits'] * (1 + form.get('credits', 0)))  # Greed (pilot skill)
        if halloween_boss(n.d) and self.ghostly(n):
            o['uridium'] *= 2                                      # Halloween: the bosses' uridium doubled (player report 2026-10-27)
        if o.get('uridium') and random.random() < form.get('double_uridium', 0):
            o['uridium'] *= 2                                      # N.O.V.A. Autonomous Extraction (in Galaxy Gates; nova.py)
        f = self.x1_reward()
        if f != 1:
            o = {a: int(v * f) for a, v in o.items()}
        for k in ('ep', 'honor', 'credits', 'uridium'):
            o[k] = SET.amount(k, o.get(k, 0), 'npc')                # the panel's reward multipliers
        return o

    def npc_reward(self, n, x, y, share=1, own=True, ratio=1.0, box=True):
        """The alien's reward and loot to this hero (kill; in a group each sharer's world gives their own). EP, honor, credits and
        uridium are split between the sharers (rounded up; the P.E.T.'s EP too); the cargo box, chests, extra rewards and
        booster go whole to everyone, in a group the boxes are the owner's (only they see and collect them). own: the killer; the achievement, streak, drone EP, ship
        skill charge, logbook, gate score and event hooks are theirs; for the other sharers it counts as a quest (group).
        ratio < 1: share by damage (group alien, by_damage): the reward is at this ratio; box: whether the cargo box is for this hero."""
        o = self.kill_reward(n)
        if share > 1:
            o = dict(o, **{k: -(-o[k] // share) for k in ('ep', 'honor', 'credits', 'uridium')})
        if ratio < 1:
            o = dict(o, **{k: int(math.ceil(o[k] * ratio)) for k in ('ep', 'honor', 'credits', 'uridium')})
        in_rad = self.radiation_since is not None
        owner = self.hid if share > 1 or ratio < 1 else None
        owner_tag = ('h', self.hid) if SET.get('cargo_ownership') else None     # the cargo box's owner (others see it blue)
        extra = {}                                            # extra resources going into the box (extra_loot box)

        def reward():
            if own:
                self.p.ach('kill', avatar='NPC', npc=n.d.get('npc_id'), radiation=in_rad, name=n.d.get('name'))
                SA.charge(self.p, 'kills')                 # Momentum, Stockpile: one charge per kill
            tot = self.p.gain(ep=o['ep'], honor=o['honor'], credits=o['credits'], uridium=o['uridium'], reason='bonus_abschussAlien')
            if own:
                RT.note_kill(self.p, n.d.get('npc_id', 0), o['ep'], o['honor'])     # logbook
            points = self.gate.points(n) if own and n.d.get('points') and hasattr(self.gate, 'points') else []    # Plutus' score
            quest = self.quest('kill', npc=n.d.get('npc_id')) if own else \
                self.quest('kill', npc=n.d.get('npc_id'), avatar='NPC', radiation=in_rad, name=n.d.get('name'), group=True)
            g_ = n.d.get('empower')
            if g_ and own:                                   # Plutus runaway: temporary damage and speed power, the time is renewed on killing again
                self.hero_effects.remove('skill', source='fugitive')
                self.hero_effects.add('skill', g_['duration_sec'], {'mods': {'laser': g_['damage'], 'rocket': g_['damage'], 'speed': g_['speed']}}, 'fugitive',
                                   time.time())
                quest += self.stats_msgs() if self.stats_msgs else []
            if getattr(n, 'saturn', False) and own:          # the Saturn Sender CPU's alien: an enemy player in the PvP quest (forum 127576)
                fac = self.p.d['pilot'].get('factionId', 1)
                quest += self.quest('kill_player', ship=n.model, faction=random.choice([f for f in (1, 2, 3) if f != fac]))
            self.send(self.kill_notice(self.reward_msgs(tot, ep=o['ep'], honor=o['honor'], credits=o['credits'], uridium=o['uridium']))
                      + (self.drone_points(n) if own else []) + quest + (self.pet.gain_xp(o['ep']) if self.pet else [])
                      + self.booster_drop(n) + self.extra_loot(n, box=extra) + points
                      + (self.kill_streak() + self.p.hint(IP.WEALTHY_FAMOUS) + [m for hk in self.kill_hooks for m in hk(self, n, x, y)]
                         if own else []))
            self.log('   %s destroyed%s: +%d EP, +%d honor, +%d credits, +%d uridium (level %d)' % (
                n.d['name'], ' (group share 1/%d%s)' % (share, '' if own else ', hit by a group member') if share > 1 else '',
                o['ep'], o['honor'], o['credits'], o['uridium'], tot['level']))
        self.later(0.3, reward)
        cargo = {} if EVT.no_cargo(n) or not box else self.cargo_of(n)        # Curcubitor: only its chest (event_maps)
        kind = self.event.cargo_kind() or ('CANDY_CARGO' if CAL.has_type('CandyCargo') else 'FROM_SHIP')

        def cargo_drop():                                  # after the reward (0.3 s): the extra resources are in the box too
            if cargo or extra:
                h = self.drop_box(kind, x, y, cargo, COMBAT['box_life_sec'], owner, owner_tag)
                if extra:
                    self.boxes[h]['extra'] = extra
        self.later(COMBAT['box_delay_sec'], cargo_drop)
        if n.d.get('chest'):                              # chests by damage (Invoke XVI, Mindfire Behemoth; npc.json)
            self.later(COMBAT['box_delay_sec'], lambda: self.drop_chests(n.d['chest'], x, y, owner))

    def lab_spend(self, item, n=1):
        """Spend from the upgrade: laser round, rocket, engine/shield minute. When it ends speed/shield return to their old state; if an automatic laboratory
        CPU (NC-AWL/AWR/AWB/AGB) is equipped and Settings > Gameplay "Automatic weapons upgrade by activating lab CPU" (autoBoost;
        AutoWeaponsUpgrade in the client) is on, it reloads with the ore in cargo (the setting was not being checked, H86)."""
        ore = (self.p.d.get('upgrades', {}).get(str(item)) or [None])[0]
        done = self.p.lab_use(item, n)
        msgs = self.lab_msgs() if self.lab_msgs else []
        if done:
            self.log('   upgrade finished: part %d' % item)
            if item in (2, 3) and self.stats_msgs:
                msgs = self.stats_msgs() + msgs
            auto = [(l, EX.X[l]) for l, parts in EX.props(self.p, 'auto_lab') if item in parts]
            if auto and self.auto_lab and self.p.gameplay('autoBoost'):
                msgs += self.auto_lab(item, ore, bool(auto[0][1].get('best')))
        self.send([m for m in msgs if m])

    def lab_time(self, now):
        """The engine upgrade is spent while moving, the shield upgrade in combat, minute by minute."""
        dt, self.lab_tick = now - self.lab_tick, now
        if self.p.lab_bonus(2) and self.hero.t1 > now:
            self.lab_clock[2] += dt
        if self.p.lab_bonus(3) and now - self.last_combat < ITEMS['out_of_combat_sec']:
            self.lab_clock[3] += dt
        for item in (2, 3):
            if self.lab_clock[item] >= ITEMS['lab']['minute_sec']:
                self.lab_clock[item] -= ITEMS['lab']['minute_sec']
                self.lab_spend(item)

    def quest(self, kind, **kw):
        """Quest progress (the session's quest.py) -> messages to send."""
        return self.quest_event(kind, map=int(self.map_id), **kw) if self.quest_event else []

    def quest_state(self):
        """Instant state for quest sub-conditions (MISCELLANEOUS): cloaked, in the radiation zone, HP below a tenth."""
        g = self.p.d['ship']
        return {'hidden': bool(self.abilities.cloaked() or self.items.cloaked()), 'radiation': self.radiation_since is not None,
                'low_hp': g.get('hitPoints', 0) < 0.1 * g.get('hitMax', 0)}

    def pvp_drone_points(self, victim_ship):
        """Drone points on killing a player (official forum 127526 table: row the one killed, column the killer ship; unknown is the Goliath class)."""
        t = DRONE_POINTS.get('player') or {}
        order = t.get('_ship_order', [])
        mine = self.p.ship()['lootId']
        row = t.get(victim_ship) or t.get('ship_goliath') or []
        col = order.index(mine) if mine in order else len(order) - 1
        return self.add_drone_points(SET.amount('drone_xp', row[col] if row else 0))

    def drone_points(self, n):
        """Drones get points from the alien killed; the points depend on the ship (wiki table, fewer on a strong ship). A drone that passes the level
        threshold levels up: laser/shield bonus grows, its look in space changes."""
        if not self.p.d.get('drones'):
            return []
        name = re.sub(r'^[^A-Za-z]+|[^A-Za-z]+$', '', n.d['name'])      # "-=[ Lordakia ]=-", "..::{ Boss Lordakia }::.."
        for pre in ('Boss ', 'Uber ', 'Über ', 'Uber'):                   # "( UberStreuner )": also without spaces
            name = name[len(pre):] if name.startswith(pre) else name
        order = DRONE_POINTS['_ship_order']
        ship = self.p.ship()['lootId']
        col = order.index(ship) if ship in order else len(order) - 1
        pts = SET.amount('drone_xp', (DRONE_POINTS.get(name) or [0] * len(order))[col])     # panel: drone experience
        return self.add_drone_points(pts)

    def add_drone_points(self, pts):
        if not pts or not self.p.d.get('drones'):
            return []
        up = []
        with self.p.lock:
            for x in self.p.d['drones']:
                x['points'] += pts
                while x['level'] < len(DRONE_LEVELS) and x['points'] >= DRONE_LEVELS[x['level']]['points']:
                    x['level'] += 1
                    up.append(x)
            self.p.dirty = True
            if up:
                self.p.sync_equipment()
        if not up:
            return []
        self.log('   drone leveled up: %s' % ', '.join('%s %d' % (x['lootId'][6:], x['level']) for x in up))
        return ((self.drone_msgs() if self.drone_msgs else []) + (self.stats_msgs() if self.stats_msgs else [])
                + ([self.drone_item(x) for x in {id(x): x for x in up}.values()] if self.drone_item else []))

    # ------------------------------------------------------------ equipment and ammo
    def lasers(self):
        return [l for l in self.p.d['equipment'].get('laser', []) if l in ITEMS['lasers']]

    def laser_levels(self):
        """The lasers on the ship with their upgrade levels [(lootId, level)] (upgrades.py)."""
        lv = self.p.d.get('equipment_level', {}).get('laser', [])
        out = [(l, lv[i] if i < len(lv) else 0) for i, l in enumerate(self.p.d['equipment'].get('laser', [])) if l in ITEMS['lasers']]
        ship = self.lasers()
        return out if [l for l, v in out] == ship else [(l, 0) for l in ship]      # lasers() from another source (test, effects)

    def drone_lasers(self):
        return [l for level, loots in self.p.d.get('drone_equipment', []) for l in loots if l in ITEMS['lasers']]

    def ammo_msgs(self, loot):
        """Ammo count changed: shortcut bar counter + inventory (on every shot as in the recording)."""
        msgs = [('InventoryItemUpdatedCommand', {'item': mod('InventoryItemModule', upgradeLevel=0, lootId=loot, amount=self.p.ammo(loot),
                                                             itemId=self.p.item_id(loot), star=0, isNew=False, hangarId=0,
                                                             extAttributes=[], inventoryItemAttributes=[])})]
        st = self.p.menu_status(loot)
        if st:
            msgs.insert(0, ('MenuItemStatusCommand', st))
        return msgs

    def laser_damage(self, ammo, target=None, now=None, pvp=False, ev=True):
        """Total laser damage = total laser damage x ammo multiplier x random (recording: 65 x 0.76-1.0).
        The lasers' special properties are in lasers.py (Unstable LF-4 random, Prometheus x3.5, set bonuses, Odysseus crit, SL-01 extra damage).
        -> (HP+shield damage, shield-only damage)"""
        now = now or time.time()
        lasers = ITEMS['lasers']
        ship = self.lasers()
        drones = self.drone_lasers()
        vlo = self.tech.laser_bonus(now)                          # Versus Laser Overdrive: +500 to base damage per laser (VoG)
        # Per-laser abilities also work on drone lasers (overdrive, x3.5 ...); set bonuses, count-based effects (Mortifier/
        # Asmodeus/Anchorlock sets, Odysseus crit, Anchorlock slow) and Asmodeus Fervor count ship lasers only (wiki "only ship").
        base = sum((LASERS.hit(l, target, pvp=pvp) + vlo) * UPG.factor(l, lv, UPG.LASER) for l, lv in self.laser_levels()) \
            * (1 + LASERS.set_bonus(ship, pvp=pvp) + self.anger.bonus(ship, now))
        self.crit = bool(ship) and random.random() < LASERS.crit_chance(ship)
        if self.crit:
            base += LASERS.crit_damage(ship)                       # Odysseus crit
        extra = LASERS.overdrive(ship + drones, target, pvp)
        if extra and now >= self.next_overdrive:                  # SL-01 +38, Caucasus +100, Prometheus +200 (x3.5 Black Light): every 5 s
            base += extra
            self.next_overdrive = now + LASERS.OVERDRIVE_SEC
        mods = self.p.mods()
        dlv = self.p.d.get('drone_equipment_level', [])
        for k, (level, loots) in enumerate(self.p.d.get('drone_equipment', [])):
            dloot, dup, ilv = dlv[k] if k < len(dlv) else (None, 0, [])
            hits = sum((LASERS.hit(l, target, pvp=pvp) + vlo) * UPG.factor(l, ilv[j] if j < len(ilv) else 0, UPG.LASER)
                       for j, l in enumerate(loots) if l in lasers)
            base += (hits * (1 + DRONE_LEVELS[level - 1]['laser'] + mods.get('drone_laser', 0))      # Havoc, Cerberus: to the drone laser
                     * UPG.factor(dloot, dup, UPG.DRONE_DAMAGE))
        base *= ((1 + mods.get('laser', 0) + (mods.get('home_laser', 0) if ev else 0)                 # Leonov home advantage (not against a friend)
                  + ((mods.get('pvp_laser', 0) + mods.get('pvp_damage', 0)) if pvp else (mods.get('npc', 0) + mods.get('npc_laser', 0))))       # formation, drone design
                 * (1 + self.p.lab_bonus(0)))                                                   # laser upgrade
        a = ITEMS['laser_ammo'].get(ammo, {'multiplier': 1})
        r = random.uniform(*ITEMS['damage_random'])
        multiplier = a.get('pvp_multiplier', a.get('multiplier', 1)) if pvp else (LASERS.name_match(a.get('target_multiplier', {}), target) or a.get('multiplier', 1))   # SBL-100 x8 to Sibelon …
        if not pvp and LASERS.name_match(a.get('target_multiplier', {}), target) and time.strftime('%m-%d') in a.get('day_multiplier', {}):
            multiplier = a['day_multiplier'][time.strftime('%m-%d')]          # VB-142: 14 February x8 (forum 161430)
        ramp = a.get('ramp')
        if ramp:                                                  # IDB-125: from x1, +1.25 per hit, at most x6; resets after 3 s
            multiplier = 1.0 if now - self.ramp[1] > ramp['reset_sec'] else self.ramp[0]
            self.ramp = [min(ramp['maximum'], multiplier + ramp['step']), now]
        if target is not None and not pvp:                        # while an event runs UCB-100 / CC-C / RSB-75 for the aliens in the list (items.json event_ammo)
            multiplier = LASERS.event_ammo(ammo, target, CAL.is_active) or multiplier
        if target is not None and ammo in (target.d.get('ammo_multiplier') or {}):          # Ö4: ammo bonus of the event alien
            multiplier = target.d['ammo_multiplier'][ammo]
        flat = LASERS.flat_extra(ship + drones, pvp) if multiplier and (pvp or target is not None) else 0       # Paritydrill / Magmadrill +5, LF-3 +15: after the multipliers
        return int(base * multiplier * r) + flat, int(base * a.get('shield_multiplier', 0) * r)

    def laser_range(self):
        """Laser range: -25% if SL-01 is equipped (on the ship or a drone) (lasers.py); the accumulated charge of Momentum/Stockpile (+5 per charge)."""
        return int(COMBAT['laser_range'] * LASERS.range_factor(self.lasers() + self.drone_lasers())) + SA.range_bonus(self.p)

    def other_ammo(self, kind, empty, need):
        """The strongest ordinary ammo in hand in place of the ammo that ran out -> lootId (laser: AUTO_AMMO order; rocket: by damage, excluding special
        rockets) or None."""
        if kind == 'laser':
            order = AUTO_AMMO + sorted(a for a in self.p.d['ammunition'] if a.startswith('ammunition_laser_') and a not in AUTO_AMMO)
        else:
            order = sorted((r for r in ITEMS['rockets'] if not CIT.special(r)), key=lambda r: -ITEMS['rockets'][r].get('damage', 0))
        return next((a for a in order if a != empty and self.p.ammo(a) >= need), None)

    def ammo_out(self, kind, empty, need):
        """The selected ammo ran out -> (new ammo or None, messages). If Settings > Gameplay "Change ammo/rocket type automatically"
        (autoChangeAmmo) is on, it switches to the ammo in hand ("chgbat"/"chgrok" text); if not, or there is no other ammo, the client's
        ammo warning: 0|W|<L|R>|0|1 "attack canceled, change the type", 0|W|<L|R> "out of ammo, buy"
        (NetConnectionHelper.OnData -> SetAttributeAssemblyHelper.NoAmmunition; the server never sent it, H85)."""
        sub = self.other_ammo(kind, empty, need)
        code = 'L' if kind == 'laser' else 'R'
        if sub and self.p.gameplay('autoChangeAmmo'):
            self.p.d['selected'][kind] = sub
            self.p.dirty = True
            name = sub.rsplit('_', 1)[-1].upper()
            msgs = [('MenuItemStatusCommand', st) for st in (self.p.menu_status(empty), self.p.menu_status(sub)) if st]
            self.log('   ammo ran out (%s): switched to %s ammo' % (empty, sub))
            return sub, msgs + [stm('chgbat' if code == 'L' else 'chgrok', '%!', name)]
        self.log('   ammo ran out (%s): %s' % (empty, 'other ammo in hand' if sub else 'none at all'))
        return None, [legacy('0|W|%s|0|1' % code) if sub else legacy('0|W|%s' % code)] + ([] if sub else self.p.hint(IP.GET_MORE_AMMO))

    def laser_color(self, ammo):
        """AttackLaserRunCommand.laserColor: the client's laser type (beam, light and sound; items.json laser_colors). If all the ship's
        laser slots are filled with the same laser, that set's color (all LF-3: x1/x2 blue, x3 green), otherwise the ammo's (x4 white …)."""
        laser_colors = ITEMS['laser_colors']
        lasers = self.lasers()
        cap = self.p.ship_row().get('laser', 0)
        if lasers and len(lasers) >= cap and len(set(lasers)) == 1 and ammo in laser_colors['full_set'].get(lasers[0], {}):
            return laser_colors['full_set'][lasers[0]][ammo]
        return laser_colors['ammunition'].get(ammo, 0)

    def skilled_laser(self):
        """AttackLaserRunCommand.skilledLaser: at the final level (3/3) of Bounty Hunter II (22b) the client draws the laser thick (game.xml
        <laserDefinitions>: each salvo's skillResKey, e.g. laser1 -> skillLaser1; the official Turkish forum's "21 arge ile kalın sıkma" (thick shot with 21 research points) route is
        the prerequisites of Bounty Hunter II 3/3; fandom Battery). The color stays the same (laser_color)."""
        return SKL.maxed(self.p, '22b')

    def skill_shield(self):
        """AttackLaserRunCommand.isDiminishedBySkillShield (laser hitting the ship): the client (LaserSalvo2DNew/3DNew) meets the projectile on the ship's
        hit face with a "shieldDamage" effect (a white, semi-transparent shield facing the direction of the shot; if the ship quality in the settings is not
        0). At the final level of Shield Mechanics (8) and with the shield full (official FAQ: white shield at 5/5); visual only."""
        return SKL.maxed(self.p, '8') and self.p.d['ship'].get('shield', 0) > 0

    def rocket_look(self):
        """The rocket's look -> (trail, homing): the 0|v|…|trail|homing fields of the old text (client NetConnectionHelper.OnData 'v': the 7th field is the
        rocketSmoke id, if the 8th field is 1 AttackRocketRun/BezierRocketEffect isHeatSeeking: curved flight and red glow). Trail
        (seen live): 0 orange-red flame (the trail of an account without skills in the official server recording), 1 purple-blue: at the final level of
        Rocket Fusion (6) (official FAQ: "purple trail"), 2 thin gray: with Precision Targeter on; homing: Heat-Seeking Missiles (20) from level 1
        on, every rocket, the missing ones too (fandom Heat-Seeking Missiles, Skill tree and Rocket Trail Colours: 1 point is enough for the visual, the final
        level is not needed; in the official server recording the homing players' rockets 64/64 and 52/52, including 6 misses, were homing: the flag depends on
        the skill, not the shot; darkorbitwiki's "at the final level" line contradicts this). Earlier versions: only on a rocket the skill saved
        (2026-10-24), then only at 5/5 (2026-10-25); user report 2026-10-26: the visual starts from the first point."""
        smoke = 2 if self.tech.full_rocket_hit() else 1 if SKL.maxed(self.p, '6') else 0
        return smoke, int(SKL.level(self.p, '20') > 0)

    def rocket_msg(self, target, hit, kind):
        """The player's rocket visual (old text 0|v|attacker|target|H/M|type|trail|homing)."""
        return legacy('0|v|%d|%d|%s|%d|%d|%d' % ((self.hid, target, 'H' if hit else 'M', kind) + self.rocket_look()))

    def hit_asset(self, uid, dmg, atype=0, shield_only=False, hull_only=False, attacker=None):
        """Resolve an impact against the current map, including shield-only ammunition."""
        with self.lock:
            self.last_shield_hit = 0
            if self.hero_dead or self.jumping or not self.asset_at(uid):
                return []
            if attacker is not None and attacker != self.hid:
                pet = self.pet
                if not (pet and pet.active and pet.alive and pet.w is self and pet.pid == attacker):
                    return []
            denied = self.asset_targets.asset_attackable(uid)
            if denied:
                self.send(denied)
                return denied
            if hasattr(self.asset_targets, 'asset_damage'):
                msgs = self.asset_targets.asset_damage(uid, dmg, atype=atype,
                    shield_only=shield_only, hull_only=hull_only, attacker=attacker)
            elif not shield_only:
                msgs = self.asset_targets.asset_hit(uid, dmg)  # LoW relay keeps its charge behavior.
            else:
                return []
            self.send(msgs)
            return msgs

    def asset_laser(self, now):
        """Laser at a map entity (rival Battle Station module): range, ammo, hit; the entity's owner applies the damage
        (asset_targets.asset_hit: shield, HP, destruction and reward)."""
        uid = self.target
        pos = self.asset_at(uid)
        if not pos or self.asset_targets.asset_attackable(uid):
            self.laser_stop()
            return
        def hit(dmg, shield):
            if shield:
                self.hit_asset(uid, shield, 1, shield_only=True)
                drained = self.last_shield_hit
                if drained:
                    g = self.p.d['ship']
                    self.p.set_hull(shield=g.get('shield', 0) + drained)
                    self.send([('AttributeShieldUpdateCommand', dict(shieldNow=int(g['shield']), shieldMax=int(g.get('shieldMax', 0))))])
            if dmg:
                self.hit_asset(uid, dmg, 1)
        self.side_laser(now, uid, pos, hit, asset=True)
        if not self.asset_at(uid):
            self.laser_stop()

    def own_pet(self, uid):
        """Is the id the player's own P.E.T. in space?"""
        return self.pet is not None and self.pet.active and uid == self.pet.pid

    def pet_laser(self, now):
        """Laser at one's own P.E.T. (it can be selected and hit; for Kamikaze's HP threshold, user report 2026-10-24): the P.E.T. takes the damage
        (pet.owner_hit), no reward. When the P.E.T. stops or is destroyed the laser stops."""
        pet = self.pet
        if pet.active:
            self.side_laser(now, pet.pid, pet.pos(now), pet.owner_hit)
        if not pet.active:
            self.laser_stop()

    def ammo_timer(self, ammo, now):
        """Shortcut-bar countdown for laser ammo with its own cooldown (RSB-75, RCB-140: client CooldownType
        RAPID_SALVO_BLAST = 10, the cooldownGroup of their MenuItemInitializationCommand). Returns the start message
        and schedules the reset; a reset is skipped if a newer shot of the same group restarted the timer."""
        cfg = ITEMS['laser_ammo'].get(ammo, {})
        group, sec = cfg.get('cooldown_group'), cfg.get('interval_sec')
        if not group or not sec:
            return []
        ms = int(sec * 1000)
        end = now + sec
        self.ammo_timer_end[group] = end

        def reset():
            if self.ammo_timer_end.get(group) == end:
                self.send([CIT.timer_msg(group, ms, cooling=False)])
        self.later(sec, reset)
        return [CIT.timer_msg(group, ms)]

    @staticmethod
    def slow_ammo(ammo):
        """Laser ammo with its own cooldown (RSB-75, RCB-140)."""
        return bool(ammo and ITEMS['laser_ammo'].get(ammo, {}).get('interval_sec'))

    def rapid_volleys(self, ammo, uid):
        """RSB-75 is a rapid salvo: the client plays one volley (and its clip) per AttackLaserRunCommand, so the single command of a 3 s
        cooldown looked and sounded like one short shot. Official recording (user's RSB-75 video): the sound is laser6_0 (the pulse
        laser, game.xml sound 32; the user picked it by ear; laser5_x was the wrong clip) and the envelope fits 4 starts 0.5 s apart
        (correlation 0.85), the fire lasting ~1.7 s, then silence until the next salvo 3 s after the first; damage stays one hit."""
        n = RAPID_VOLLEYS if ammo == RAPID_AMMO else 1
        for i in range(1, n):
            self.later(RAPID_STEP * i, lambda: self.send([('AttackLaserRunCommand', dict(
                attackerId=self.hid, targetId=uid, laserColor=self.laser_color(ammo), isDiminishedBySkillShield=False,
                skilledLaser=self.skilled_laser(), visualType=0))]) if self.attacking and self.target == uid and not self.hero_dead
                and not self.jumping else None)

    def slow_ammo_shot(self, ammo, now=None):
        """RSB-75 / RCB-140 fire as soon as they are selected during an attack, like on the official server, instead of
        waiting for the next laser tick (next_laser). Nothing happens while the ammo cools down: the tick fires it later.
        The shot sets next_laser again, so the next normal salvo waits a full interval; the only extra salvo is bounded
        by the ammo's own cooldown (at most one more every interval_sec)."""
        now = now or time.time()
        if (not self.slow_ammo(ammo) or not self.attacking or self.hero_dead or self.jumping
                or self.p.d['selected'].get('laser') != ammo or now < self.ammo_ready.get(ammo, 0)):
            return
        self.log('   instant shot: %s' % ammo)
        self.hero_laser(now)

    def side_laser(self, now, uid, pos, hit, pvp=False, asset=False):
        """Laser at a non-alien target (asset_laser, pet_laser): range, ammo, hit; if it hits, hit(damage)."""
        hx, hy = self.hero_pos(now)
        rng = self.laser_range()
        if math.hypot(pos[0] - hx, pos[1] - hy) > rng:
            if self.range_warned != uid:
                self.range_warned = uid
                self.send([range_exceeded(uid, rng, 1)] + self.combat_state(COMBAT_OUT_OF_RANGE, now))
            return
        if self.range_warned == uid:
            self.send(self.combat_state(COMBAT_CONTINUES, now))
        self.range_warned = None
        lasers = self.lasers() + self.drone_lasers()
        ammo = self.p.d['selected']['laser']
        cooldown = ITEMS['laser_ammo'].get(ammo, {}).get('interval_sec')
        if cooldown and now < self.ammo_ready.get(ammo, 0):
            return
        if not lasers or self.p.use_ammo(ammo, len(lasers)) is None:
            if not lasers:
                self.send([stm('no_lasers_on_board')])      # "Your ship doesn't have any laser cannons. That's why you can't attack."
                self.laser_stop()
                return
            sub, msgs = self.ammo_out('laser', ammo, len(lasers))
            self.send(msgs)
            if not sub:
                self.laser_stop()
            return
        self.last_combat = now
        self.stop_repair()
        self.next_laser = now + COMBAT['laser_interval_sec']
        if cooldown:
            self.ammo_ready[ammo] = now + cooldown
        self.send(self.ammo_msgs(ammo) + self.ammo_timer(ammo, now) + [('AttackLaserRunCommand', dict(attackerId=self.hid, targetId=uid,laserColor=self.laser_color(ammo),
                                                                         isDiminishedBySkillShield=False, skilledLaser=self.skilled_laser(),
                                                                         visualType=0))])
        self.rapid_volleys(ammo, uid)
        self.p.ach('shot', weapon='LASER')
        m_ = self.p.mods()
        aim = self.items.aim(SET.chance('player_hit_chance', COMBAT['laser_hit_chance'] * (1 + m_.get('hit', 0) + m_.get('laser_hit_chance', 0))))
        if pvp:
            defender = self.player(uid)
            if defender:
                aim *= 1 - max(0.0, min(1.0, defender.p.mods().get('evasion', 0)))
        if random.random() < aim:
            same = pvp and defender and defender.p.d['pilot'].get('factionId') == self.p.d['pilot'].get('factionId')
            dmg, shield = self.laser_damage(ammo, pvp=pvp, ev=not same)
            if pvp or asset:
                hit(dmg, shield)
            else:
                hit(dmg)
        else:
            self.send([('AttackMissedCommand', dict(attackType=attack_type(1), targetUserId=uid, skillColorId=0))])
        if asset and self.asset_at(uid):
            self.items.auto_weapons(uid, now)
        if self.p.lab_bonus(0):
            self.lab_spend(0, len(lasers))  # every fired salvo (player, P.E.T., base module) uses one charge per laser, misses too

    def hero_laser(self, now):
        player = self.player(self.target)
        if player:
            return PVP.laser(self, player, now)
        if self.pet is not None and self.pet.owned and self.target == self.pet.pid:
            return self.pet_laser(now)
        if self.target not in self.npcs and self.asset_at(self.target):
            return self.asset_laser(now)
        n = self.npcs.get(self.target)
        if not n or not n.alive:
            self.attacking = False
            return
        hx, hy = self.hero_pos(now)
        nx, ny = n.mover.pos(now)
        rng = self.laser_range()
        if math.hypot(nx - hx, ny - hy) > rng:
            if self.range_warned != n.id:               # the client draws a range effect (AttackRangeExceededCommandHandler)
                self.range_warned = n.id
                self.send([range_exceeded(n.id, rng, 1)] + self.combat_state(COMBAT_OUT_OF_RANGE, now))
            return
        if self.range_warned == n.id:                   # back in range: "The battle continues."
            self.send(self.combat_state(COMBAT_CONTINUES, now))
        self.range_warned = None
        lasers = self.lasers() + self.drone_lasers()      # the drone lasers also fire and use ammo
        ammo = self.p.d['selected']['laser']
        cooldown = ITEMS['laser_ammo'].get(ammo, {}).get('interval_sec')
        if cooldown and now < self.ammo_ready.get(ammo, 0):
            return            # the cooldown belongs to this ammo (wiki: RSB-75 3 s); when another ammo is switched to, it fires at once
        if not lasers or self.p.use_ammo(ammo, len(lasers)) is None:
            if not lasers:
                self.log('   no laser shot: no laser equipped')
                self.send([stm('no_lasers_on_board')])      # "Your ship doesn't have any laser cannons. That's why you can't attack."
                self.laser_stop()
                return
            sub, msgs = self.ammo_out('laser', ammo, len(lasers))
            self.send(msgs)
            if not sub:
                self.laser_stop()
            return                                      # if it was switched, the next shot is with the new ammo
        self.last_combat = now
        self.stop_repair()
        self.next_laser = now + COMBAT['laser_interval_sec']
        if cooldown:
            self.ammo_ready[ammo] = now + cooldown
        self.send(self.ammo_msgs(ammo) + self.ammo_timer(ammo, now) + [('AttackLaserRunCommand', dict(attackerId=self.hid, targetId=n.id,
                                                                         laserColor=self.laser_color(ammo),
                                                                         isDiminishedBySkillShield=False, skilledLaser=self.skilled_laser(),
                                                                         visualType=0))])
        self.rapid_volleys(ammo, n.id)
        self.p.ach('shot', weapon='LASER')
        self.ammo_seen[ammo] = now                      # achievement "laser show": 6 basic ammo within 60 s
        recent = [AMMO_TYPE_IDS[a] for a, t in self.ammo_seen.items() if a in AMMO_TYPE_IDS and now - t <= 60]
        self.p.ach('laser_types', items=recent)
        m_ = self.p.mods()
        if random.random() < self.items.aim(SET.chance('player_hit_chance', COMBAT['laser_hit_chance'] * (1 + m_.get('hit', 0) + m_.get('laser_hit_chance', 0)))):   # + AIM CPU, P.E.T. HEAT; panel
            dmg, shield_dmg = self.laser_damage(ammo, n)
            if shield_dmg:
                self.last_shield_hit = 0
                self.hit_npc(n.id, shield_dmg, 1, shield_only=True, ammo=ammo)
                if self.last_shield_hit:                 # Shield Leech (SAB-50 x2, CBO-100 x1): the drained shield goes to the player
                    g = self.p.d['ship']
                    self.p.set_hull(shield=g.get('shield', 0) + self.last_shield_hit)
                    self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])
            if dmg:
                self.hit_npc(n.id, dmg, 1, strike=self.crit, ammo=ammo)
                self.tech.leech(ammo, dmg)               # Energy Leech
            proc = LASERS.slow_proc(self.lasers())        # LF-5 Anchorlock: slowing by chance depending on count
            if proc and n.alive and random.random() < proc[0]:
                self.npc_effect(n, 'slow', proc[2], proc[1], source='lf-5-al')
        else:
            self.send([('AttackMissedCommand', dict(attackType=attack_type(1), targetUserId=n.id, skillColorId=0))])
        if self.p.lab_bonus(0):
            self.lab_spend(0, len(lasers))      # laser upgrade: one per laser (and drone laser) in the salvo, like the ammo
        self.items.auto_weapons(n, now)         # AROL-X, RL-LB1
        if n.alive:
            self.particle.auto(n, now)          # RG-SL (slug), AGS-X (GSP)

    def menu_action(self, f):
        """Shortcut bar. The actionType the client sends depends on the item type (the client's code, ItemMenuActionRequest): single-use
        and selection items 1, toggle and timer items (ship abilities, technology, cloak/aim CPUs) 0; a single click on a selection item in the item
        bar is 0: the ammo is selected, the attack is not triggered."""
        item = f.get('menuItemId', '')
        act = f.get('actionType')
        with self.lock:
            kind = CIT.ammo_kind(item)
            if kind in ('slug', 'gsp'):                 # particle cannon / Singularity Drive: selected and fired at the target
                self.particle.menu(item, act)
                return
            if kind:                                    # selection: laser, rocket (including special rockets), launcher ammo
                if act not in (0, 1):
                    return
                old = self.p.d['selected'].get(kind)
                if act == 1 and kind == 'laser' and self.quickslot_attack(item, old):
                    return
                if item == old or self.p.ammo(item) <= 0:
                    return
                self.p.d['selected'][kind] = item
                self.p.dirty = True
                self.send([('MenuItemStatusCommand', st) for st in (self.p.menu_status(old), self.p.menu_status(item)) if st])
                self.log('   %s ammo: %s' % (kind, item))
                if act == 1 and kind == 'laser' and self.quickslot_on() and not self.attacking:
                    self.quickslot_start()
                if kind == 'laser':
                    self.slow_ammo_shot(item)
            elif item.startswith(CIT.EMOTE_PREFIX):
                if act == 1:
                    self.emote(item)                # emote (Ö6)
            elif item.startswith('ability_'):
                self.abilities.activate(item)       # ship ability (ship_ability.py)
            elif item.startswith('tech_'):
                self.tech.activate(item)            # technology item (technology.py)
            elif self.items.menu(item):
                pass                                # mine, Smart Bomb, Insta-Shield, EMP, CPUs, launcher (combat_items.py)
            elif item.startswith('ammunition_ggportal_') and self.portal_cpu:
                self.portal_cpu(item)               # mode gate CPU (pve_modes.py)
            elif item == CIT.HM7:                    # HM-7 trade drone: its icon opens the trade window (TradeType.DRONE)
                if self.hm7_ready():
                    self.send([self.trade_info()])
            elif act == 0:
                pass                                # SELECT: a single click in the item bar (in the recording the real server does not answer)
            elif item == 'equipment_extra_repbot_rep':
                # clicking again does not stop the repair (player report 2026-10-31); it stops by itself in combat or when HP is full (repair_tick)
                self.start_repair()
            else:
                self.log('   menu action not available yet: %s' % item)

    def emote(self, item, now=None):
        """Emote (the shortcut bar's special_items): 1 piece is consumed, 5 s above the ship (EmoteActivationCommand; client
        EmoteEffect, sprite <name>_100x100); all emotes are in a common cooldown group (58, 10 s: adaptation)."""
        now = now or time.time()
        group = CIT.O6['phrases']['cooldown_group']
        if self.hero_dead or self.p.ammo(item) <= 0 or not self.items.ready(group, now):
            return False
        if self.p.use_ammo(item, 1) is None:
            return False
        st = self.p.menu_status(item)
        self.send([('EmoteActivationCommand', {'userId': self.hid, 'lootId': item})] + ([('MenuItemStatusCommand', st)] if st else [])
                  + [self.items.cooldown(item, now)])
        self.log('   emote: %s' % item)
        return True

    def quickslot_on(self):
        """Settings > Gameplay "Start and stop attacks using the shortcut bar" (quickslotStopAttack). The client does not read the setting, it only
        sends MenuActionRequest (H87). Not applied while Omega AutoTactic runs: it also selects ammo with a shortcut request."""
        return self.p.gameplay('quickslotStopAttack') and (self.p.d.get('autopilot') or {}).get('state') != 0

    def quickslot_start(self):
        # Map clicks and the laser shortcut must validate the same target kinds.
        # laser_start owns NPC, pet, player and asset hostility/shield checks.
        uid = self.target
        if uid is not None:
            self.laser_start({'targetId': uid})
            if self.attacking:
                self.log('   attack with shortcut: %s' % uid)

    def quickslot_attack(self, item, old):
        """The selected laser ammo was pressed: if attacking, it stops; if a target is selected, the attack starts -> was it handled."""
        if item != old or not self.quickslot_on():
            return False
        if self.attacking:
            self.log('   attack with shortcut stopped')
            self.laser_stop()
        elif self.p.ammo(item) > 0:
            self.quickslot_start()
        return True

    # ------------------------------------------------------------ repair robot
    def repair_rate(self):
        rep = next((e for e in EX.equipped(self.p) if e in ITEMS['repair_robots']), None)      # a robot equipped on a drone also works
        if not rep:
            return 0
        r = ITEMS['repair_robots'][rep]
        boost = (1 + self.p.mods().get('repair', 0)) * SET.multiplier('repair_speed')     # REP-B01 (booster); panel
        if self.p.premium:
            boost *= 2                                                              # Premium: "twice as effective repair robots"
        if 'full_repair_sec' in r:
            return self.p.d['ship'].get('hitMax', 0) / r['full_repair_sec'] * boost
        return r.get('hp_per_minute', 0) / 60.0 * boost

    def repbot_highlight(self):
        return dict(itemId='equipment_extra_repbot_rep', itemSource=mod('UiItemSourceModule', itemSource=0),
                    highlightType=mod('HighlightTypeModule', type=3))

    def start_repair(self):
        g = self.p.d['ship']
        now = time.time()
        if (not self.repair_rate() or self.hero_dead or g.get('hitPoints', 0) >= g.get('hitMax', 0)
                or now - self.last_combat < ITEMS['regen_cooldown_sec']):
            self.send([('UIItemRemoveHighlightCommand', self.repbot_highlight())])     # the failed-attempt reply in the recording
            return
        if not self.repairing:
            self.next_repair = now + 1.0
        self.repairing = True
        self.send([('BeaconCommand', self.p.beacon(self.station_at(*self.hero_pos(now)), near_gate=bool(self.near_gate), pos=self.hero_pos(now), repairing=True,
                                                    gate_peace=self.gate_peace, radiation=self.radiation_since is not None,
                                                    void=self.peace_void)),
                   ('UIItemAddHighlightCommand', dict(self.repbot_highlight(), soundModule=mod('SoundTriggerModule', playSound=False, soundId=0)))])
        self.log('   repair robot worked (%.0f HP/s)' % self.repair_rate())

    def stop_repair(self):
        if not self.repairing:
            return
        self.repairing = False
        self.send([('BeaconCommand', self.p.beacon(self.station_at(*self.hero_pos()), near_gate=bool(self.near_gate), pos=self.hero_pos(), repairing=False,
                                                    gate_peace=self.gate_peace, radiation=self.radiation_since is not None,
                                                    void=self.peace_void)),
                   ('UIItemRemoveHighlightCommand', self.repbot_highlight())])

    # ------------------------------------------------------------ status effects (state.py)
    def npc_effect(self, n, kind, sec, value=1.0, source=None, **extra):
        """Status effect on an alien. Frozen and slow: cuts the ongoing movement at that moment (so the client recomputes with the new speed)."""
        now = time.time()
        e = n.effect.add(kind, sec, value, source, now, **extra)
        if kind in ('frozen', 'slow') and n.mover.t1 > now:
            x, y = n.mover.pos(now)
            n.mover = Mover(x, y)
            n.next_think = now if kind == 'slow' else now + sec
            if n.id in self.visible:
                self.send([('MoveCommand', dict(userId=n.id, x=int(x), y=int(y), timeToTarget=0))])
        return e

    # ------------------------------------------------------------ alien behavior hooks (npc.json "davranis")
    def guarded(self, n):
        """invulnerable_while_summons_live: takes no damage while one of those it summoned lives (Battleray's Interceptors …)."""
        if not n.behavior.get('invulnerable_while_summons_live'):
            return False
        n.children = {c for c in n.children if c in self.npcs and self.npcs[c].alive}
        return bool(n.children)

    def npc_summon(self, n, now, hit=True, hitter=None):
        """summon_on_hit {type, count, max_count, cooldown_sec, first_cooldown_sec, calm_sec}: when hit, summons helpers around itself (Cubikon ->
        Protegit …). first_cooldown_sec: on the first hit after calm_sec (15) of not being hit, the summon comes that much later (user report 2026-10-25:
        the Protegits came out right at the first shot). hit: not a hit, the pending first summon. hitter: the hitting bot ship (the helpers spawn around the
        bot and attack it: alien.summoner_bot); None for the player's hit."""
        if hit:                         # so that the HP threshold and periodic summons know too (alien.summoner_bot)
            n.ab['summoner'] = hitter.id if hitter is not None else None
        v = n.behavior.get('summon_on_hit')
        if not v:
            return
        if hit and v.get('first_cooldown_sec'):
            quiet = now - n.ab.get('summon_hit', -1e9) > v.get('calm_sec', 15)
            n.ab['summon_hit'] = now
            if quiet:
                n.next_summon = now + v['first_cooldown_sec']
                self.later(v['first_cooldown_sec'], lambda: n.alive and n.id in self.npcs and self.npc_summon(n, time.time(), hit=False))
                return
        if now < n.next_summon:
            return
        n.children = {c for c in n.children if c in self.npcs and self.npcs[c].alive}
        if v.get('when_all_dead') and n.ab.get('summoned'):
            # replacements only once all the helpers are destroyed, cooldown_sec later (Hitac; player report 2026-10-30: the cooldown was counted from every
            # summon, and a new helper came within 1-2 minutes in place of each one that died)
            if n.children or n.ab.get('summon_queued', 0):
                n.ab.pop('vacant', None)
                return
            n.ab.setdefault('vacant', now)
            if now < n.ab['vacant'] + v.get('cooldown_sec', 10):
                return
            n.ab.pop('vacant')
        n.ab['summoned'] = True
        room = (v.get('max_count', v.get('count', 1)) + (self.alien.extra_summons(n, now) if 'anger' in n.behavior else 0) - len(n.children)
                - n.ab.get('summon_queued', 0))
        if room <= 0:
            return
        count, gap = min(room, v.get('count', 1)), v.get('interval_sec', 0)
        # interval_sec: the swarm comes out one after another (when Cubikon's 25 Protegits came out at once the client froze for a moment; user report
        # 2026-10-25); group [min, max]: one group every interval_sec (Cubikon: 2-3 per second; user report 2026-10-27).
        # Those waiting in the queue count toward en_cok. The next summon after the whole swarm is out
        delays, k = [], 0
        while len(delays) < count:
            size = random.randint(*v['group']) if v.get('group') else 1
            delays += [k * gap] * size
            k += 1
        delays = delays[:count]
        n.next_summon = now + max(v.get('cooldown_sec', 10), delays[-1] + gap)
        if v.get('swarm_visual') and 'swarm' not in (getattr(n, 'images', None) or {}):
            # "0|n|s|<id>": the client's MapEventsAssemblyHelper.AssembleSpawnEnemies -> SpawnChildrenEffect: Cubikon opens up,
            # the yellow core shows, stays open until it dies (live 2026-10-27). Permanent visual: also goes to whoever enters view later
            n.images = dict(getattr(n, 'images', None) or {}, swarm=legacy('0|n|s|%d' % n.id))
            if n.id in self.visible:
                self.send([n.images['swarm']])

        def queued():
            n.ab['summon_queued'] -= 1
            if n.alive and n.id in self.npcs:
                self.summon_one(n, v, time.time())
        for d in delays:
            if d:
                n.ab['summon_queued'] = n.ab.get('summon_queued', 0) + 1
                self.later(d, queued)
            else:
                self.summon_one(n, v, now)
        self.log('   %s summoned help: %d %s' % (n.d['name'], count, CFG['types'][v['type']]['name']))

    def summon_one(self, n, v, now):
        x, y, r = *n.mover.pos(now), 200
        bot = self.alien.summoner_bot(n)
        if bot is not None:             # summoned by the bot: spawns around the bot, attacks the bot
            (x, y), r = bot.mover.pos(now), random.uniform(*v['spawn_range']) if v.get('spawn_range') else 250
        elif v.get('spawn_range'):            # from a bit away from the player to just outside the screen (Cubikon; user report 2026-10-27)
            (x, y), r = self.hero_pos(now), random.uniform(*v['spawn_range'])
        a = random.uniform(0, 2 * math.pi)
        c = self.spawn_npc_at(v['type'], min(max(x + math.cos(a) * r, 300), self.map_w - 300),
                              min(max(y + math.sin(a) * r, 300), self.map_h - 300))
        self.alien.adopt(n, c)
        self.alien.trigger_attack(c, bot, now)          # the swarm attacks at once (fandom: the Protegits come at you all at once)
        if v.get('guard'):
            c.guard = (n.id, v['guard'])
        n.children.add(c.id)

    def npc_regen(self, n, now):
        """regeneration {hp_sec, shield_per_sec, cooldown_sec}: if not hit for cooldown_sec, HP/shield refill per second (Cubikon …)."""
        r = n.behavior['regeneration']
        if now < n.next_regen or now - n.last_hit < r.get('cooldown_sec', 5):
            return
        n.next_regen = now + 1.0
        hp, sh = n.hp, n.shield
        n.hp = min(n.d['hp'], n.hp + r.get('hp_sec', 0))
        n.shield = min(n.d['shield'], n.shield + r.get('shield_per_sec', 0))
        if (n.hp, n.shield) != (hp, sh) and self.target == n.id:
            self.send([self.selection(n)])

    def npc_shield_regen(self, n, now):
        """Every alien refills its shield by itself, also in combat (COMBAT npc_shield_regen of the maximum per second); HP does not (player
        report 2026-11-02: only Cubikon regenerated, and only its HP)."""
        if now < n.next_shield_regen:
            return
        n.next_shield_regen = now + 1.0
        n.shield = min(n.d['shield'], n.shield + max(1, int(n.d['shield'] * COMBAT.get('npc_shield_regen', 0.0025))))
        if self.target == n.id:
            self.send([self.selection(n)])

    def effect_stats_msgs(self, now=None):
        """Update the effect speed; re-time the ongoing flight toward the same target with the new speed, from where it is."""
        now = time.time() if now is None else now
        before = self.p.d['ship'].get('speed')
        mover = self.hero
        msgs = self.stats_msgs() if self.stats_msgs else []
        return msgs + self.respeed_flight(before, now, mover)

    def respeed_flight(self, before, now=None, mover=None):
        """Ship speed changed from `before` (effect, config switch): reschedule the ongoing flight from where the ship is now,
        to the same destination, at the new speed (the client only re-tweens on a new MoveCommand)."""
        now = time.time() if now is None else now
        mover = self.hero if mover is None else mover
        msgs = []
        speed = self.p.d['ship'].get('speed')
        if speed == before or speed is None or self.hero_dead or self.jumping or self.hero is not mover:
            return msgs
        target = (mover.x1, mover.y1) if mover.t1 > now else self._effect_destination
        if target is None:
            return msgs                         # do not start a new flight for a stationary/arrived ship
        x, y = mover.pos(now)
        if speed <= 0:
            self._effect_destination = target
            self.hero = Mover(x, y)              # so it does not drag at Mover.go's minimum speed of 1
            ms, target = 0, (x, y)
        else:
            self._effect_destination = None
            ms = mover.go(*target, speed, now)
        msgs.append(('MoveCommand', dict(userId=self.hid, x=int(target[0]), y=int(target[1]), timeToTarget=ms)))
        return msgs

    def hero_effect(self, kind, sec, value=1.0, source=None):
        """Status effect on the player: speed/hit from the profile bonuses (player_profile.mods -> world_mods); the speed gauge is updated at once."""
        if kind == 'infection':
            if self.items.serum_cure():
                return None                      # Serum CPU: cures an infection on its own
            self.hero_effects.remove(kind)          # re-infection does not stack; only the duration is renewed
        e = self.hero_effects.add(kind, sec, value, source)
        if kind == 'infection':
            self.p._infection_effect = e
        self.send(self.items.mine_effect_msgs())
        if kind in ('slow', 'frozen', 'speed_up', 'speed_limit', 'infection', 'skill') and self.stats_msgs:
            self.send(self.effect_stats_msgs())
        return e

    def effects_tick(self, now):
        for n in list(self.npcs.values()):
            if not self.owner(n, now):
                continue                                  # shared map: the alien's effects are run by its owner
            if n.alive and n.effect.d:
                for dmg in n.effect.poison_due(now):        # poison (Venom …): to the hull
                    self.hit_npc(n.id, dmg, 1, hull_only=True)
                n.effect.expired(now)
            if n.alive and 'regeneration' in n.behavior:
                self.npc_regen(n, now)
            if n.alive and n.bot is None and n.shield < n.d['shield']:
                self.npc_shield_regen(n, now)
        expired = self.hero_effects.expired(now) if self.hero_effects.d else set()
        expired.update(kind for kind in self.items.mine_visuals if not self.hero_effects.get(kind, now))
        infection = getattr(self.p, '_infection_effect', None)
        if infection and infection['end_time'] <= now:    # mods() may have filtered out the effects beforehand
            expired.add('infection')
        if 'infection' in expired:
            self.p._infection_effect = None
        self.send(self.items.mine_effect_msgs(now))
        if expired & {'slow', 'frozen', 'speed_up', 'speed_limit', 'weakness', 'infection', 'skill'} and self.stats_msgs:
            self.send(self.effect_stats_msgs(now))         # if the speed changed, the ongoing flight is re-timed too

    # ------------------------------------------------------------ automatic CPUs (extras.py)
    def auto_tick(self, now):
        """NC-RRB-X: the repair robot on its own if HP is missing and out of combat; ALB-X/RB-X/FB-X: automatic purchase below the threshold."""
        if now < self.next_auto:
            return
        self.next_auto = now + 1.0
        g = self.p.d['ship']
        if not self.hero_dead and self.p.cargo_free() < 1:
            # cargo full: auto-refining (if the setting is on) on its own. It used to work only while the player collected; the cargo stays full when filled by the P.E.T.'s
            # collecting, Palladium, a gate reward or Skylab, and the P.E.T. also stopped collecting
            msgs = self.auto_refine()
            if msgs:
                self.send(msgs)
        if (EX.has(self.p, 'auto_repair') and not self.repairing and not self.hero_dead and g.get('hitPoints', 0) < g.get('hitMax', 0)
                and now - self.last_combat >= ITEMS['regen_cooldown_sec'] and self.repair_rate()):
            self.start_repair()
        for loot, cfg in EX.props(self.p, 'auto_pickup'):
            kind = cfg['type']
            if now < self.auto_wait.get(kind, 0):
                continue
            if kind == 'fuel':
                if self.pet and self.pet.owned and self.pet.d['fuel'] < cfg['threshold']:
                    self.auto_wait[kind] = now + 10
                    self.pet.buy_fuel(cfg['count'])
                continue
            ammo = EX.attached(self.p, loot) or self.p.d['selected'].get('laser' if kind == 'laser' else 'rocket')   # selected in the hangar
            if ammo and self.p.ammo(ammo) < cfg['threshold'] and self.auto_buy:
                self.auto_wait[kind] = now + 10                  # if money is not enough, it tries again after 10 s
                msgs = self.auto_buy(ammo, cfg['count'])
                if msgs:
                    self.send(msgs)
                    self.auto_warned.discard(ammo)
                    self.log('   auto purchase (%s): %s x%d' % (loot, ammo, cfg['count']))
                elif self.auto_buy_fail and ammo not in self.auto_warned:
                    warn = self.auto_buy_fail(ammo, cfg['count'])     # not enough money: the client's text, once until a purchase happens
                    if warn:
                        self.auto_warned.add(ammo)
                        self.send(warn)

    def hp_msg(self):
        g = self.p.d['ship']
        return ('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g.get('hitMax', 0),
                                            nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0)))

    def heal_msgs(self, hp0=None, sh0=None):
        """The "+amount" number of healing (Ö1): 0|A|HL|<healer>|<target>|HPT or SHD|<new value>|<amount>. The client
        (SetAttributeAssemblyHelper.AssembleHealInfo) writes the target's HP/shield and shows the number (HP green, shield blue).
        hp0 / sh0: values before the healing; no message if it did not increase. Not used for the shield's own refill."""
        g, out = self.p.d['ship'], []
        for kind, before, now in (('HPT', hp0, g.get('hitPoints', 0)), ('SHD', sh0, g.get('shield', 0))):
            if before is not None and int(now) > int(before):
                out.append(legacy('0|A|HL|%d|%d|%s|%d|%d' % (self.hid, self.hid, kind, int(now), int(now) - int(before))))
        return out

    def repair_tick(self, now):
        g = self.p.d['ship']
        if self.hero_dead or now - self.last_combat < ITEMS['regen_cooldown_sec']:
            self.stop_repair()
            return
        if now < self.next_repair:
            return
        self.next_repair = now + 1.0
        hp0 = g.get('hitPoints', 0)
        self.p.set_hull(hp=hp0 + self.repair_rate())
        self.send([('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g.get('hitMax', 0),
                                                nanoHull=g.get('nanoHull', 0), nanoHullMax=g.get('maxNanoHull', 0)))]
                  + self.heal_msgs(hp0))
        if getattr(self.gate, 'key', None) == 'world_boss':
            self.p.ach('wb_heal', count=g['hitPoints'] - hp0)          # World Boss achievement (recoverhp)
        if g['hitPoints'] >= g.get('hitMax', 0):
            self.stop_repair()
            self.log('   repair done')

    def music_tick(self, now):
        """Combat music (Ö1): CombatMusicCommand 0 (START) when combat starts, 1 (END) when it leaves combat. The client plays it if the combat
        music in the Sound settings is on and it is not turned off on the map (MapViewComponentSystem.UpdateMusic)."""
        fight = not self.hero_dead and now - self.last_combat < ITEMS['out_of_combat_sec']
        if fight != self.combat_music:
            self.combat_music = fight
            g = self.p.d['ship']
            hurt = not fight and not self.hero_dead and g.get('hitPoints', 0) < g.get('hitMax', 0)
            self.send([('CombatMusicCommand', {'combatEvent': 0 if fight else 1})] + (self.p.hint(IP.SHIP_REPAIR) if hurt else []))

    def shield_tick(self, now):
        """The shield fills: regen_cooldown_sec (15) after the last damage taken, at a rate of shield_regen_sec (4%) per second; firing
        does not stop the refill (real recording 20261027_235305: while the player fired, 4%/s refill 17 s after the last damage; player report
        2026-10-30). The panel's shield_regen multiplier and SREG-B01 stack on top (recording and fandom Shield: items.json notes)."""
        g = self.p.d['ship']
        k = SET.multiplier('shield_regen')                   # panel: 0 never fills
        if (now < self.next_shield or self.hero_dead or g.get('shield', 0) >= g.get('shieldMax', 0) or k <= 0
                or now - self.last_hurt < ITEMS['regen_cooldown_sec']
                or self.p.mods().get('shield_decay_sec', 0) > 0):       # Moth / 3D Wheel drain: the passive refill must not erase the drain
            return
        self.next_shield = now + 1.0
        rate = ITEMS['shield_regen_sec'] * (1 + self.p.mods().get('shield_regen', 0)) * k   # SREG-B01 (booster)
        self.p.set_hull(shield=g.get('shield', 0) + max(1, g['shieldMax'] * rate))
        self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g['shieldMax']})])

    def settings_tick(self, now):
        """The panel's settings file changed (checked once a second): the ship's HP, shield, speed and cargo values are recalculated while the game runs
        (shop.apply_stats; only the changed value is sent). Once on entering the map too: settings changed while the game was off."""
        if now < self.next_setting or not self.stats_msgs or self.hero_dead:
            return
        self.next_setting = now + 1.0
        v = SET.version()
        if v != self.settings_version:
            self.settings_version = v
            msgs = self.stats_msgs()
            if msgs:
                self.send(msgs)

    def form_shield_tick(self, now):
        """The formation's shield effect, once a second: Diamond 1%/s (at most 5,000) and 3D Dome 0.5%/s refill even in combat; Moth and
        3D Wheel drain 5%/s (client: "drains shields by 5% per second", no combat condition)."""
        if now < self.next_form_shield:
            return
        self.next_form_shield = now + 1.0
        m = self.p.mods()
        up, down = m.get('shield_refill_sec', 0), m.get('shield_decay_sec', 0)
        if self.hero_dead or not (up or down):
            return
        g = self.p.d['ship']
        mx, sh = g.get('shieldMax', 0), g.get('shield', 0)
        delta = min(mx * up, m.get('shield_refill_max') or mx * up)
        delta -= mx * down
        new = max(0, min(mx, sh + delta))
        if int(new) != int(sh):
            self.p.set_hull(shield=new)
            self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': mx})])

    def npc_shoot(self, n, now):
        """The alien's shot: at a friendly ship (echoes.py) or the ship. It does not fire at the P.E.T., and Mindfire Behemoth's extra target at critical HP
        (alien.extra_target) is absent too: in the real game only enemy players attack the P.E.T. (user report 2026-10-24)."""
        n.firing = True                         # laser state on (a shot at a friendly ship too): on release alien_ceasefire sends AttackAbortLaserCommand
        if self.ally and self.ally.take_shot(n, now):
            return                              # the shot went to a friendly ship (echoes.py, mimesis.py)
        ddol = n.effect.get('shot_disrupted', now)          # Disruptor DDoL: laser cooldown 3-5 s
        n.next_shot = now + (random.uniform(*ddol[0]['interval']) if ddol else n.d.get('shot_interval_sec', COMBAT['npc_attack_interval_sec']))
        m = self.p.mods()
        msgs = [('AttackLaserRunCommand', dict(attackerId=n.id, targetId=self.hid, laserColor=self.alien.laser_color(n, now),
                                               isDiminishedBySkillShield=m.get('laser_taken', 0) < 0 or self.skill_shield(),  # Spectrum
                                               skilledLaser=False, visualType=0))]
        aim = SET.chance('npc_hit_chance', n.d.get('hit', COMBAT['npc_hit_chance'])) * (1 - n.effect.accuracy_loss(now))
        roll = random.random()
        if roll < aim * (1 - m.get('evasion', 0)):
            raw = n.d['damage'] * random.uniform(0.8, 1.0) * self.alien.laser_factor(n, now)      # recording: x0.8-1.0; rage, DMG capsule
            dmg = int(raw * max(0.0, 1 + m.get('laser_taken', 0)))                              # Spectrum
            self.npc_hit_tick(n, dmg, now)
            if raw - dmg >= 1 and n.alive and SA.effect(self.p, 'reflect_laser', now):
                self.hit_npc(n.id, int(raw - dmg), 1)  # Spectrum Plus Prismatic Reflecting: the reduced damage goes to the attacker
            self.alien.after_shot(n, now, True)        # slowing shot (alien.py)
        else:
            self.last_combat = now
            self.stop_repair()
            evaded = roll < aim * (1 - (m.get('evasion', 0) - SKL.mods(self.p).get('evasion', 0)))     # it used to hit without the skill
            msgs.append(('AttackMissedCommand', dict(attackType=attack_type(1), targetUserId=self.hid,      # official FAQ: a miss is purple, blue with the evasion skill
                                                     skillColorId=EVADE_COLOR if evaded else 0)))
        self.send(msgs)

    def npc_hit_tick(self, n, dmg, now):
        """The damage of the shots that hit accumulates; in the per-second tick (official recording: AttackHitCommands are always in the same second phase, at most one per
        alien per second, its damage the sum of 1-5 shots: Recruit Streuner 31-38, 65-76, 99-115, 129-153, 169-184) it goes as a single hit."""
        n.pend_dmg += dmg
        if n.pend_dmg == dmg:
            self.later(1.0 - now % 1.0, lambda: self.npc_hit_flush(n))

    def npc_hit_flush(self, n):
        dmg, n.pend_dmg = n.pend_dmg, 0
        if dmg > 0 and not self.hero_dead:
            self.send(self.hurt_hero(dmg, n, now=time.time()))

    def hurt_hero(self, dmg, killer=None, atype=1, msgs=None, now=None, cause=None, source_player=None, shield_only=False, source_asset=False):
        """Damage to the player (the alien's laser, rocket, bomb, singularity, explosion): Fortify, Insta-Shield; the shield absorbs at the generators'
        ratio, the nano hull melts after the shield and before the hull; Anti-AI base; test invulnerability. -> messages
        (AttackHitCommand; if HP runs out, the death screen)."""
        now = now or time.time()
        msgs = [] if msgs is None else msgs
        g, m = self.p.d['ship'], self.p.mods()
        place = 'wave' if getattr(killer, 'hunt', False) else 'map'      # the panel's damage sub-setting: is it a gate and mode wave
        k = 1.0 if (source_player or source_asset) else SET.multiplier('npc_damage', place)      # the panel's damage multiplier
        raw = dmg * k                                                     # damage before the damage_taken reduction: Revenge reflects this
        dmg = int(dmg * max(0.0, 1 + m.get('damage_taken', 0)) * k)       # Fortify, Revenge (damage taken 5%)
        if self.hero_effects.invulnerable(now) or ((source_player or source_asset) and (self.invulnerable or now < self.invuln_until)):
            dmg = 0                                 # Insta-Shield (combat_items.py)
        if YM.spectator(self.p):
            dmg = 0                                 # admin spectator: takes no damage (admin_mode.py)
        if dmg and killer is not None and getattr(killer, 'alive', False):
            back = SA.effect(self.p, 'mirror', now) or self.hero_effects.ability('mirror', now)       # Berserker Revenge (Mimesis Chest's too): the damage returns to the attacker
            if back:
                self.hit_npc(killer.id, int(raw * back), 1)
            heal = SA.effect(self.p, 'absorb_hp', now) or self.hero_effects.ability('absorb_hp', now)  # Orcus Assimilate (Mimesis Chest's too): the alien damage turns into HP
            if heal:
                self.p.set_hull(hp=g.get('hitPoints', 0) + dmg * heal)
                dmg = int(dmg * (1 - heal))
        self.last_hurt = self.last_combat = now
        self.stop_repair()
        if dmg > 0:
            self.p.ach('damage_taken', count=dmg)       # damage taken (quest condition TAKE_DAMAGE; Galaxy Trek's Endurance quest)
            if getattr(self.gate, 'key', None) == 'world_boss':
                self.p.ach('wb_damage', count=dmg)      # World Boss achievement (takedamage)
        sh = g.get('shield', 0)
        absorption = self.p.d.get('shield_absorb', 0.8)
        if source_player:
            absorption = max(0.0, absorption - source_player.p.mods().get('shield_penetration', 0))
        to_shield = min(sh, dmg if shield_only else int(dmg * absorption))   # the shield generators' absorption ratio (esyalar.json)
        if shield_only:
            dmg = to_shield
        hull = dmg - to_shield
        stim, sb = 0, self.p.ship_row().get('stim_barrier')
        if sb and hull > 0 and random.random() < sb['chance']:      # Pusat Plus Stim Barrier: 10% of the hull damage is not taken, it turns into HP
            stim = int(hull * sb['ratio'])
            hull -= stim
            msgs.append(stm('msg_stim_barrier_activated'))
        nano = g.get('nanoHull', 0)
        from_nano = min(nano, hull)                # nano hull (gate draw): melts after the shield, before the hull
        linked = self.pet.link_take(hull - from_nano) if self.pet and not self.invulnerable else 0   # G-HPL1: hull damage to the P.E.T.
        hp = g.get('hitPoints', 0) - (hull - from_nano - linked) + stim
        floor = 0 if (source_player or source_asset) else self.tech.hp_floor(now)  # Anti-AI protects against NPCs only
        if floor:
            hp = max(hp, floor)
        if hp <= 0 and self.abilities.hold_on(now):                      # Tempest Volt Back-up: HP 1, invulnerable for 3 s
            hp = 1
        if hp <= 0 and self.abilities.last_stand(now):                   # Paladin Last Stand: HP refills
            hp = g.get('hitMax', hp)
        to_shield = int(to_shield * (1.0 if shield_only else max(0.0, 1 + m.get('shield_damage_taken', 0))))      # Sentinel: the shield melts less
        if not self.invulnerable:
            self.p.set_hull(hp=hp, shield=sh - to_shield)
            with self.p.lock:
                g['nanoHull'] = nano - from_nano
        msgs.append(('AttackHitCommand', dict(attackType=attack_type(atype), attackerId=source_player.hid if source_player else killer.id if killer else 0, victimId=self.hid,
                                              victimHitpoints=int(g['hitPoints']), victimShield=int(g.get('shield', 0)),
                                              victimNanoHull=int(g.get('nanoHull', 0)), damage=dmg, skilled=False, strike=False,
                                              cannonType=0)))
        if g['hitPoints'] > 0 and self.pet:
            self.pet.ship_hurt(now, None if source_player or source_asset else killer)    # G-KK1: low ship HP or an alien attacking
        if g['hitPoints'] <= 0 and not self.hero_dead:
            self.hero_death(msgs, killer, cause=cause, source_player=source_player)
        return msgs

    # ------------------------------------------------------------ boosters
    def booster_tick(self, now):
        """Once a second: the duration of a booster dropped by an alien decreases; a booster that expires is dropped (gauge + HP/shield cap)."""
        if now < self.next_booster:
            return
        dt = 1.0 if self.next_booster == 0 else now - self.next_booster + 1.0
        self.next_booster = now + 1.0
        gone = BOOSTER.tick(self.p, now, min(dt, 5.0))
        if gone:
            self.send([BOOSTER.update_cmd(self.p, removed=gone)] + (self.stats_msgs() if self.stats_msgs else []))
            self.log('   booster finished: %s' % ', '.join(gone))

    def booster_drop(self, n):
        """Booster from a Boss/Uber alien (wiki: 1-10 hours; pauses offline)."""
        got = BOOSTER.drop_for(n.d['name'])
        if not got:
            return []
        loot, hours = got
        BOOSTER.add(self.p, loot, seconds=hours * 3600)
        self.log('   booster found: %s (%d hours)' % (loot, hours))
        shown = max(1, int(round(hours * SET.multiplier('booster_duration'))))      # BOOSTER.add extends the duration by the panel's multiplier
        return ([('BoosterFoundOnMapCommand', {'lootId': loot, 'hours': shown}), BOOSTER.update_cmd(self.p)]
                + (self.stats_msgs() if self.stats_msgs else []))

    # ------------------------------------------------------------ radiation
    def radiation_tick(self, now):
        """Outside the map boundary is radiation: BeaconCommand.inRadiationZone, a warning (the client's msg_radiation_warning text) and every
        second 1% of max HP to the hull, rising up to 5% (wiki). If it dies, the cause is radiation."""
        if self.hero_dead:
            self.radiation_since = None
            return
        hx, hy = self.hero_pos(now)
        inside = 0 <= hx <= self.map_w and 0 <= hy <= self.map_h
        if inside and self.gate and hasattr(self.gate, 'safe_at'):
            inside = self.gate.safe_at(hx, hy, now)          # Ö4: in Mimesis Mutiny the outside of the protected area is radiation
        if inside:
            if self.radiation_since is not None:
                self.radiation_since = None
                self.send([self.beacon_msg(now)])
                self.log('   left the radiation zone')
            return
        if self.radiation_since is None:
            self.radiation_since, self.next_radiation = now, now + 1.0
            self.send([self.beacon_msg(now), ('MessageCommand', dict(
                displayTarget=2, displayStyle=0, messageModule=mod('WildcardMessageModule', message=mod(
                    'MessageKeyListWildcardModule', wildCardReplacements=[], baseKey='msg_radiation_warning',
                    baseKeyType=mod('ReplacementTypeModule', typeValue=5), textStyle=0))))])
            self.log('   radiation zone (%d,%d)' % (hx, hy))
            return
        if now < self.next_radiation:
            return
        self.next_radiation += 1.0
        lo, hi = COMBAT['radiation_percent']
        pct = min(hi, lo * (1 + int((now - self.radiation_since) / COMBAT['radiation_increase_sec']))) * SET.multiplier('radiation')   # panel
        g = self.p.d['ship']
        self.stop_repair()
        dmg = int(g.get('hitMax', 0) * pct)
        if not self.invulnerable:
            self.p.set_hull(hp=g.get('hitPoints', 0) - dmg)
        msgs = [('AttackHitCommand', dict(attackType=attack_type(3), attackerId=0, victimId=self.hid,     # official recording: 3 = RADIATION, attacker 0
                                          victimHitpoints=int(g['hitPoints']), victimShield=int(g.get('shield', 0)),
                                          victimNanoHull=int(g.get('nanoHull', 0)), damage=dmg, skilled=False, strike=False,
                                          cannonType=0))]
        if g['hitPoints'] <= 0:
            self.hero_death(msgs, cause=DESTRUCTION_RADIATION)
            self.radiation_since = None
        self.send(msgs)

    def beacon_msg(self, now):
        return ('BeaconCommand', self.p.beacon(self.station_at(*self.hero_pos(now)), near_gate=bool(self.near_gate), pos=self.hero_pos(now),
                                               repairing=self.repairing, gate_peace=self.gate_peace,
                                               radiation=self.radiation_since is not None, void=self.peace_void))

    # ------------------------------------------------------------ death and the death screen
    def ach_tick(self, now):
        """Achievement counters: distance covered (once a second; teleporting does not count) and play time (once a minute; whether the P.E.T. is active,
        another company's map, a PvP map (4-X)). A position event once a second for quests (reach a coordinate, stay on a map)."""
        if now < self.ach_next:
            return
        self.ach_next = now + 1.0
        pos = self.hero_pos(now)
        if self.ach_pos and not self.hero_dead and not self.jumping:
            d = math.hypot(pos[0] - self.ach_pos[0], pos[1] - self.ach_pos[1])
            if d < 2000:
                self.ach_dist += d
                if self.ach_dist >= 1:
                    self.p.ach('distance', count=int(self.ach_dist))
                    self.ach_dist -= int(self.ach_dist)
        self.ach_pos = pos
        if not self.hero_dead and not self.jumping:
            msgs = self.quest('pos', x=int(pos[0]), y=int(pos[1]))
            if msgs:
                self.send(msgs)
        self.ach_secs += 1
        if self.ach_secs >= 60 and not self.hero_dead:
            self.ach_secs = 0
            comp = H.company(self.map_id)
            self.p.ach('minute', pet=bool(self.pet and self.pet.active), pvp_map=H.name(self.map_id).startswith('4-'),
                       enemy_map=bool(comp and comp != self.p.d['pilot'].get('factionId')))
            if self.abilities.cloaked(now) or self.items.cloaked():
                self.p.ach('cloak_minute')          # achievement PlayerCloaked (minute)

    def kill_streak(self, now=None):
        """Kill streak (Ö2; the panel's 'kill_streak' setting). The client plays the announcement's sound with "0|n|KSMSG|<key>"
        (MapEventsAssemblyHelper.AssembleKillstreakMessage: triplekill, unstoppable, godlike, likeaboss -> sound 0x53-0x56); the text is a screen message
        with the same key (STM). Thresholds are an adaptation (the real server's PvP thresholds are unknown): 3, 6, 10, 15 kills in a row
        within STREAK_GAP_SEC; after 15, "Like a boss!" every 5. The streak resets on death."""
        now = time.time() if now is None else now
        st = self.streak
        st[0] = st[0] + 1 if now - st[1] <= STREAK_GAP_SEC else 1
        st[1] = now
        if st[0] == 1:
            st[2] = 0
        key = next((k for c, k in STREAKS if st[0] == c), None)
        if key is None and st[0] > STREAKS[-1][0] and (st[0] - STREAKS[-1][0]) % 5 == 0:
            key = STREAKS[-1][1]
        if not key or not SET.get('kill_streak'):
            return []
        st[2] = st[0]
        self.log('   kill streak: %d (%s)' % (st[0], key))
        return [legacy('0|n|KSMSG|%s' % key), stm(key)]

    def hero_death(self, msgs, killer=None, cause=None, note=None, source_player=None):
        """The player died: explosion + death screen (KillScreenPostCommand). The player respawns when they pick a repair on the screen (kill_screen_repair)."""
        self.hero_dead = True
        try:
            hx, hy = self.hero_pos()
            BG.witness(self, 'player_died', hx, hy, name=self.p.d['pilot'].get('userName', ''),
                     killer=getattr(getattr(killer, 'bot', None), 'name', None) or getattr(killer, 'd', {}).get('name', ''))
        except Exception:
            pass                                         # the witness chat must never block the death
        self._effect_destination = None
        infected = bool(self.hero_effects.d.get('infection') or getattr(self.p, '_infection_effect', None))
        self.hero_effects.remove('infection')
        self.p._infection_effect = None
        self.send(self.items.mine_effect_msgs())
        if infected and self.stats_msgs:
            self.send(self.stats_msgs())          # death ends the infection; it does not heal the hull
        self.particle.clear()
        self.streak = [0, 0.0, 0]                                     # streak broken
        self.cinematic_end()                                          # so the camera lock does not remain
        self.attacking = False
        self.stop_repair()
        if self.pet:
            self.pet.hero_died()
        self.abilities.on_death()
        self.items.on_death()
        self.tech.on_death()
        self.gate_lives = self.gate.on_death() if self.gate else None
        if self.low:
            self.low.on_death()
        x, y = (int(v) for v in self.hero_pos())
        self.hero = Mover(x, y)
        self.death_pos = (x, y)
        self.death_time = time.time()
        if self.raid_gate():
            self.later(HADES_RESPAWN_SEC + 0.5, self.raid_expired)
        self.p.d['position'].update(x=x, y=y)
        for n in self.npcs.values():
            if self.ours(n):
                n.engaged = False
        msgs.append(('ShipDestroyedCommand', dict(destroyedUserId=self.hid, explosionTypeId=0)))
        bot_killer = killer is not None and getattr(killer, 'bot', None) is not None     # bot player (bot/ship.py)
        killer_name = source_player.p.d['pilot'].get('userName', '') if source_player else killer.d['name'] if killer else ''
        death_cause = 0 if source_player else (cause if cause is not None else DESTRUCTION_NPC if killer else DESTRUCTION_MISC)
        msgs.append(('KillScreenPostCommand', dict(
            killerName=killer_name, killerEpppLink='', playerShipAlias=self.p.ship_look(),
            cause=mod('DestructionTypeModule', cause=death_cause),
            options=self.repair_options())))
        self.log('   player destroyed (%s): death screen' % (killer_name or '?'))
        self.p.ach('death', npc=killer.d.get('npc_id') if killer else None,
                   reason='PLAYER' if source_player or bot_killer else {DESTRUCTION_RADIATION: 'RADIATION'}.get(cause, 'NPC' if killer else 'MISC'))
        key = note or ('killed_by_radiation' if cause == DESTRUCTION_RADIATION
                       else 'killed_by_npc_%s' % killer.d.get('npc_id', 0) if killer and not bot_killer else None)
        if bot_killer:
            BG.player_died(self, killer)
        if key:
            RT.note(self.p, key)                        # logbook
        if self.death:
            self.death()                                 # "hit" to group members
        if source_player is not None:                   # PvP reward / friendly fire penalty (player_combat.on_kill)
            import player_combat as OS
            source_player.send(OS.on_kill(source_player, self))

    def raid_gate(self):
        """A player with HP left in Hades can respawn on the gate map (within HADES_RESPAWN_SN after death)."""
        k = self.gate
        return bool(k and k.key == 'hades' and self.gate_lives and time.time() - self.death_time < HADES_RESPAWN_SEC)

    def raid_expired(self):
        if self.hero_dead and self.gate:
            self.send([('KillScreenUpdateCommand', {'options': self.repair_options()})])     # the respawn-at-gate option is lifted

    def vouchers(self):
        """Repair coupons (the "repair credit" produced by gates; client: ttip_repair-vouchers_count)."""
        return int((self.p.d.get('gates') or {}).get('voucher', 0))

    def repair_offers(self):
        """Options on the death screen: type -> uridium price. Repair at the station is free; repair at the portal if there is a portal on the map.
        If there is a repair coupon, repair at the portal and on the spot uses the coupon (free; client: "Use repair credit")."""
        offers = {REPAIR_BASE: 0}
        if self.gate and hasattr(self.gate, 'repair_offers'):
            return self.gate.repair_offers()      # Ö4: Vortex of Greed's free respawn on the spot (STRIKE_AND_EXIT)
        if self.low:
            return offers                       # LoW: only at the station (X-1); the portal in X-3 is returned to within the return time
        if self.gate:
            if self.raid_gate():
                offers[REPAIR_RAID_GATE] = 0    # Hades: free on the gate map (client: ttip_killscreen_repair_hadesgate)
            return offers                       # at a gate: free repair at the top (client: galaxygates_pvemap_leave_on_kill_p)
        voucher = self.vouchers() > 0 or bool(self.rules.get('free_repair'))      # Cubikon Graveyard: repairs are free (npc.json)
        k = SET.multiplier('repair_cost')                                   # the panel's repair price multiplier
        if self.gates:
            offers[REPAIR_GATE] = 0 if voucher or self.free_gate_repair() else int(round(DEATH['portal_uridium'] * k))
        offers[REPAIR_LOCATION] = 0 if voucher else int(round(DEATH['in_place_uridium'] * k))
        return offers

    def repair_options(self):
        """KillScreenOptionModule list. The client picks the icon and hint from the option type itself; the price, whether it can be afforded,
        the detail text and the button label are from here (the client's translation keys)."""
        u = self.p.d['pilot'].get('uridium', 0)
        out = []
        vouchers = 0 if self.rules.get('free_repair') else self.vouchers()          # on a free map the coupon is not written or spent
        for kind, price in self.repair_offers().items():
            if kind not in REPAIR_TEXTS:          # the run's option (Ö4): the texts from it
                desc, tooltip, btn, (akey, aparams) = self.gate.repair_texts(kind)
                out.append(mod('KillScreenOptionModule', repairType=mod('KillScreenOptionTypeModule', repairTypeValue=kind),
                               price=mod('PriceModule', type=1, amount=price), affordableForPlayer=True, cooldownTime=0,
                               descriptionKey=loc(desc), descriptionKeyAddon=loc(akey, **aparams), toolTipKey=loc(tooltip),
                               buttonKey=loc(btn)))
                continue
            desc, tooltip, btn = REPAIR_TEXTS[kind]
            count, addon = price, loc('')
            if self.gate and kind == REPAIR_BASE:
                desc, price = ('desc_killscreen_free_repair_cause_galaxygate_lives' if self.gate_lives
                               else 'desc_killscreen_free_repair_cause_galaxygate'), self.gate_lives or 0
                count = price
            elif kind == REPAIR_RAID_GATE:
                count = self.gate_lives or 0
                addon = loc('desc_killscreen_option_available_countdown_hadesgate',
                            COUNTDOWN=max(0, int(HADES_RESPAWN_SEC - (time.time() - self.death_time))))
            elif kind in (REPAIR_GATE, REPAIR_LOCATION) and vouchers:
                desc, btn, count = ('desc_killscreen_repair_voucher_s' if vouchers == 1 else 'desc_killscreen_repair_voucher_p',
                                    'btn_killscreen_repair_voucher', vouchers)
            out.append(mod('KillScreenOptionModule', repairType=mod('KillScreenOptionTypeModule', repairTypeValue=kind),
                           price=mod('PriceModule', type=1, amount=price), affordableForPlayer=u >= price, cooldownTime=0,
                           descriptionKey=loc(desc, COUNT=count), descriptionKeyAddon=addon, toolTipKey=loc(tooltip),
                           buttonKey=loc(btn, COUNT=count)))
            if self.gate and kind == REPAIR_BASE:
                out[-1]['price'] = mod('PriceModule', type=1, amount=0)
                out[-1]['affordableForPlayer'] = True
        return out

    def kill_screen_repair(self, f):
        """KillScreenRepairRequest: the chosen repair. At the station: full HP (on a map without a station, on the company's home map);
        at the portal: full HP at the portal nearest the place of death; on the spot: 10% of HP and attack protection."""
        kind = (f.get('selection') or {}).get('repairTypeValue')
        with self.lock:
            if not self.hero_dead:
                return
            price = self.repair_offers().get(kind)
            if price is None or self.p.d['pilot'].get('uridium', 0) < price:
                self.log('   no repair: option %s, price %s' % (kind, price))
                self.send([('KillScreenUpdateCommand', {'options': self.repair_options()})])
                return
            msgs = []
            if price:
                self.p.gain(uridium=-price, reason='repair_ship')
                msgs += self.money_msgs() if self.money_msgs else []
            elif kind in (REPAIR_GATE, REPAIR_LOCATION) and self.vouchers() > 0 and not self.gate and not self.rules.get('free_repair'):
                with self.p.lock:
                    self.p.d['gates']['voucher'] -= 1          # repair coupon used (client: repair_voucher_used)
                    self.p.dirty = True
                self.log('   repair coupon used (left %d)' % self.vouchers())
            g = self.p.d['ship']
            hp, shield = g.get('hitMax', 1), g.get('shieldMax', 0)
            x, y = self.death_pos or self.hero_pos()
            if kind == REPAIR_BASE and not self.home_station() and self.on_home:
                self.p.set_hull(hp=hp, shield=shield)
                self.hero_dead = False
                self.send(msgs)
                self.log('   repair at the station: respawning on the company home map')
                self.on_home()                   # the map changes; this world stops
                return
            if kind not in REPAIR_TEXTS:              # the run's option (Ö4): the position from it, or not yet
                spot = self.gate.repair(kind) if self.gate and hasattr(self.gate, 'repair') else None
                if not spot:
                    self.send([('KillScreenUpdateCommand', {'options': self.repair_options()})])
                    return
                x, y = spot
            elif kind == REPAIR_BASE and self.home_station():
                x, y = self.station['posX'], self.station['posY']
            elif kind == REPAIR_RAID_GATE:
                x, y = self.map_w // 2, self.map_h // 2         # Hades: in the middle of the gate map, with full HP; the wave continues
                self.gate.revive()
            elif kind == REPAIR_GATE:
                gate = min(self.peace_gates() or self.gates, key=lambda gt: math.hypot(gt['x'] - x, gt['y'] - y))
                x, y = gate['x'], gate['y']
            elif kind == REPAIR_LOCATION:
                hp, shield = max(1, int(hp * SET.get('on_spot_hp') / 100.0)), 0             # panel (the game's value is 10%, 10 s)
                self.invuln_until = time.time() + SET.get('on_spot_protection')
            self.p.set_hull(hp=hp, shield=shield)
            self.p.d['position'].update(x=int(x), y=int(y))
            self.hero = Mover(int(x), int(y))
            self.hero_dead = False
            self.death_pos = None
            self.target, self.attacking = None, False
            self.reload_pending = True
            if self.pet:
                self.pet.reload()
            self.send(msgs + self.reload_msgs())
            self.log('   repair (%s, %d U): respawned at (%d,%d) with %d HP' % (
                {REPAIR_BASE: 'in_station', REPAIR_GATE: 'at_portal', REPAIR_LOCATION: 'in_place'}.get(kind, 'run option %s' % kind),
                price, x, y, hp))

    def invuln_msg(self, on):
        return ('VisualModifierCommand', dict(userId=self.hid, modifier=INVINCIBILITY, attribute=0, additionalAttribute='',
                                              count=1 if on else 0, activated=on))

    def end_invuln(self, force=False):
        """The attack protection from repair on the spot ends (the time ran out or the player attacked)."""
        if self.invuln_until and (force or time.time() >= self.invuln_until - 0.05):
            self.invuln_until = 0.0
            self.send([self.invuln_msg(False)])
            self.log('   attack protection ended')

    def zone_circles(self):
        """NPC physical exclusion includes every asteroid, even before CBS.attach. Portals only where they have a DMZ (peace_gates):
        on 4-5 after the entry window, 4-1..4-4 and foreign maps aliens fly up to the portal (player report 2026-10-31: near the 4-5
        pirate portal aliens never came close, so they could be shot without circling)."""
        import cbs
        zones = cbs.exclusion_zones(self.map_id)
        if self.station:
            zones.append((self.station['posX'], self.station['posY'], self.station['peaceRadius']))
        return (zones + list(ML.safe_zones(self.map_id)) + self.giver_zones()
                + [(g['x'], g['y'], ML.gate_peace_radius(self.map_id, H.GATE_PEACE_RADIUS)) for g in self.peace_gates()])

    def near_zone(self, x, y, margin):
        return any(math.hypot(x - sx, y - sy) <= radius + margin for sx, sy, radius in self.zone_circles())

    def path_near_zone(self, x, y, tx, ty, allow_station=False):
        """Reject a route through a structure; allow an NPC already inside to exit outward."""
        dx, dy = tx - x, ty - y
        length2 = dx * dx + dy * dy
        zones = (list(ML.safe_zones(self.map_id)) + self.giver_zones()
                 + [(g['x'], g['y'], ML.gate_peace_radius(self.map_id, H.GATE_PEACE_RADIUS)) for g in self.peace_gates()]
                 if allow_station else self.zone_circles())
        for sx, sy, radius in zones:
            fraction = max(0.0, min(1.0, ((sx - x) * dx + (sy - y) * dy) / length2)) if length2 else 0.0
            distance = math.hypot(x + fraction * dx - sx, y + fraction * dy - sy)
            start = math.hypot(x - sx, y - sy)
            if distance < radius and not (start < radius and fraction == 0 and math.hypot(tx - sx, ty - sy) > start):
                return True
        return False

    def stop_npc_motion(self, n, now):
        x, y = n.mover.pos(now)
        n.mover.go(x, y, 1, now)
        self.send([('MoveCommand', dict(userId=n.id, x=int(x), y=int(y), timeToTarget=0))])
        n.next_think = now + 2

    def spot_away(self, hx, hy):
        """A wander point away from the safe zones and the player."""
        best = None
        for _ in range(20):
            x, y = self.random_spot()
            if math.hypot(x - hx, y - hy) > 3000:
                return x, y
            best = best or (x, y)
        return best

    def alien_ceasefire(self, n):
        """The alien stops attacking the pilot (gave up at a zone, out of range, frozen, he died / jumped / cloaked): the client keeps a
        ship that opened laser fire turned to its old target until AttackAbortLaserCommand arrives, so it flew away backwards (user
        report 2026-10-26; same as H166). The real server sends it whenever an alien stops firing (real recording 5-2 and elsewhere)."""
        if n.firing:
            n.firing = False
            self.send([('AttackAbortLaserCommand', dict(uid=n.id))])

    def disengage(self, n, now, flee=True):
        """Let go of the chase. flee: at the next think it moves away from the safe zone and the player (a wave alien does not flee, it waits in place)."""
        self.alien_ceasefire(n)
        if n.engaged and not self.hero_dead:
            self.send(self.combat_state(COMBAT_ESCAPED, now))        # "You escaped the attack."
        n.engaged = False
        n.station_retaliation = {}
        n.flee = flee
        n.park = None
        n.next_think = now

    def peace_circle(self, x, y):
        """(x, y, radius) of the protected zone around a point (home station or docked CBS, portal, layout safe zone) or None."""
        s = self.station_at(x, y)
        zones = ([(s['posX'], s['posY'], s['peaceRadius'])] if s else []) + list(ML.safe_zones(self.map_id)) + self.giver_zones()
        zones += [(g['x'], g['y'], ML.gate_peace_radius(self.map_id, H.GATE_PEACE_RADIUS)) for g in self.peace_gates()]
        return next((z for z in zones if math.hypot(x - z[0], y - z[1]) <= z[2]), None)

    def park_at_zone(self, n, hx, hy, nx, ny, now):
        """The pilot entered a protected zone and this alien gave up: it stops just outside the zone edge (real recording: 91-150
        units beyond it) and waits 6-13 s, then roams away from the zone (think). False: no usable edge point, it flees as before."""
        zone = self.peace_circle(hx, hy)
        if not zone or n.speed() <= 0 or n.effect.frozen(now) or self.ward_of(n) or ML.navigates(self.map_id):
            return False
        cx, cy, r = zone
        a, edge = math.atan2(ny - cy, nx - cx), r + random.uniform(90, 150)
        tx, ty = cx + math.cos(a) * edge, cy + math.sin(a) * edge
        if (not (300 <= tx <= self.map_w - 300 and 300 <= ty <= self.map_h - 300) or self.near_zone(tx, ty, 0)
                or self.path_near_zone(nx, ny, tx, ty)):
            return False
        n.flee, n.park = False, (cx, cy)
        ms = n.mover.go(tx, ty, n.speed() * n.effect.speed_factor(now), now)
        self.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])
        n.next_think = now + max(ms / 1000, random.uniform(6, 13))
        return True

    def combat_state(self, state, now):
        """Combat state line (Ö1): CombatStateCommand {combatState}; the client (AttackUpdateCombatState) writes to the log: 0 "Out of
        range", 1 "The battle continues.", 2 "You escaped the attack.". The same state is not repeated within 5 s (multiple aliens)."""
        last, t = self.combat_sent
        if state == last and now - t < 5.0:
            return []
        self.combat_sent = (state, now)
        return [('CombatStateCommand', {'combatState': state})]

    def ward_of(self, n):
        """The living summoner of a guard (NPC.guard) or None: when the summoner dies it wanders like an ordinary alien."""
        p = self.npcs.get(n.guard[0]) if n.guard else None
        return p if p and p.alive else None

    def guard_spot(self, n, post, hx, hy, now):
        """The point an attacking guard will go to: around the summoner (guard.radius), on the side facing the player and keeping the player in
        its range; otherwise the point on the perimeter nearest the player (a guard does not move away from its summoner). guard.hit_and_run {nearby, far, near_sec,
        far_sec}: hit-and-run around the player (Cubikon's Protegits; user report 2026-10-27): it comes next to them, one or two shots,
        moves away (if in range it keeps firing), soon approaches again; each at its own angle, scattered."""
        hit_run = n.guard[1].get('hit_and_run')
        if hit_run:
            near = not n.ab.get('nearby')
            n.ab['nearby'] = near
            nx, ny = n.mover.pos(now)
            r = random.uniform(*hit_run['nearby' if near else 'far'])
            a = math.atan2(ny - hy, nx - hx) + random.uniform(-1.2, 1.2)        # stays by itself: the swarm does not gather on the ship
            n.ab['wait'] = random.uniform(*hit_run['near_sec' if near else 'far_sec'])
            return hx + math.cos(a) * r, hy + math.sin(a) * r
        px, py = post.mover.pos(now)
        lo, hi = n.guard[1]['radius']
        b = math.atan2(hy - py, hx - px)
        for _ in range(8):
            a, r = b + random.uniform(-1.2, 1.2), random.uniform(lo, hi)
            tx, ty = px + math.cos(a) * r, py + math.sin(a) * r
            if math.hypot(tx - hx, ty - hy) <= self.npc_range(n) * 0.9:
                return tx, ty
        a = b + random.uniform(-0.3, 0.3)
        return px + math.cos(a) * hi, py + math.sin(a) * hi

    def leashed(self, n, post, hx, hy, now):
        """A guard's leash (guard.leash; otherwise outside the perimeter + firing range): if the player is this far from the summoner it lets go,
        wanders around the summoner (user report 2026-10-25: the Protegits chased the player very far from Cubikon).
        When the attack is dropped it does not return: it fights until Cubikon dies (player report 2026-10-28)."""
        px, py = post.mover.pos(now)
        return math.hypot(hx - px, hy - py) > n.guard[1].get('leash', n.guard[1]['radius'][1] + self.npc_range(n))

    def npc_retaliating(self, n):
        """In a protected zone (station, portal, layout safe zone) only the NPC the pilot attacked in this encounter keeps fighting him."""
        permissions = getattr(n, 'station_retaliation', None) or {}
        when = permissions.get(self.hid)
        if when is not None and when < max(self.entered, self.death_time):
            permissions.pop(self.hid, None)     # a previous map visit or life grants no permission
            return False
        return bool(n.engaged and when is not None)

    def hero_in_peace(self, hx, hy):
        """in_peace(hero): in the step's alien loop every alien asks about the same position, computed once per position."""
        memo = self.step_peace
        if memo is None:
            return self.in_peace(hx, hy)
        r = memo.get((hx, hy))
        if r is None:
            r = memo[(hx, hy)] = self.in_peace(hx, hy)
        return r

    def think(self, n, now):
        """NPC AI: wander; if attacked or of an aggressive type, chase the player and fire."""
        if n.bot is not None:
            try:
                return BG.think(self, n, now)    # bot ship (bot/ship.py)
            except Exception:
                self.step_error('bot %s' % n.bot.name)    # one bot's error must not stop the other aliens and the step
                return None
        if n.bot_target is not None and BG.npc_to_bot(self, n, now):
            return                              # answering back to a bot
        if n.d.get('friendly'):
            return                              # the mode manages the friendly ship (echoes.py)
        if n.d.get('fugitive'):                    # the Plutus turret's runaway alien: moves away from the player, does not fire (forum 143902)
            n.engaged, n.next_think = False, now + 3
            tx, ty = self.alien.flee_spot(n, now)
            self.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=n.mover.go(tx, ty, n.speed(), now)))])
            return
        if getattr(n, 'passive', False):
            n.engaged = False                   # alien that does not fire (Infiltration commando: infiltration.py)
        hx, hy = self.hero_pos(now)
        nx, ny = n.mover.pos(now)
        dist = math.hypot(hx - nx, hy - ny)
        retaliating = self.npc_retaliating(n)
        # protected zone (station, portal, layout safe zone): nobody attacks the pilot, except the alien he attacked (permission set in hit_npc)
        zoned = self.hero_in_peace(hx, hy) and not retaliating
        cloaked = self.abilities.cloaked(now) or self.items.cloaked()
        hidden = self.hero_dead or self.jumping or YM.spectator(self.p)       # admin spectator: nobody chases (admin_mode.py)
        hero_safe = zoned or hidden                 # reasons to let go of the chase; no cloaking: an attacking alien does not give up until EMP-01 (player report)
        spared = hero_safe or cloaked               # reasons to start a new attack
        if n.route:                                   # rover: does not chase, continues on its route; fires at a player in range
            if now >= n.next_think and not n.effect.frozen(now):
                tx, ty, until = n.route
                left = math.hypot(tx - nx, ty - ny)
                if left > 50:
                    v = min(n.speed(), max(30.0, left / max(1.0, until - now))) * n.effect.speed_factor(now)
                    ms = n.mover.go(tx, ty, v, now)
                    self.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])
                n.next_think = now + 10
            if n.engaged or (self.aggressive(n) and not spared and dist < n.d.get('notice_distance', COMBAT['npc_notice_distance'])):
                n.engaged = not hero_safe
            if (n.engaged and not spared and dist <= self.npc_range(n) and now >= n.next_shot and n.d['damage'] > 0
                    and now >= self.invuln_until and not n.effect.frozen(now)):
                self.npc_shoot(n, now)
            elif n.firing and (dist > self.npc_range(n) or hero_safe):
                self.alien_ceasefire(n)
            return
        if getattr(n, 'ambush', None):                # ambush wave group (echoes.lair): in place until the player approaches or hits one
            if not (n.engaged or n.ambush['on'] or (not spared and dist <= n.ambush['r'])):
                return
            n.ambush['on'] = True
            n.ambush, n.engaged, n.hunt = None, True, True
            n.next_think = now
        phase = self.alien.low_health(n, now)
        if phase:                               # low HP (alien.low_health): flees; on arrival parks (does not fire). If in range while fleeing it fires
            if (phase == 'flee' and n.engaged and not hero_safe and not n.effect.frozen(now) and dist <= self.alien.flee_range(n)
                    and now >= n.next_shot and n.d['damage'] > 0 and now >= self.invuln_until):
                self.npc_shoot(n, now)
            elif phase != 'flee' or not n.engaged or hero_safe or dist > self.alien.flee_range(n):
                self.alien_ceasefire(n)         # park, safe zone or out of range: the laser ended
            return
        # wave alien (gate, mode): always after the player regardless of distance and the aggression setting. Before, when it stayed farther than 2,500 units
        # or when the player died and respawned/cloaked, it let go and went wandering 3,000+ units from the player, and the aliens left at the gate
        # could not be found (user report, 2026-10-22: Delta Gate wave III)
        hunt = n.hunt and not getattr(n, 'passive', False)
        post = self.ward_of(n)
        tied = bool(post) and self.leashed(n, post, hx, hy, now)       # guard: the player is far from its summoner
        if hunt and not n.engaged and not spared and now >= n.next_think:
            n.engaged = True                    # the player is reachable again (respawned, cloaking ended, EMP passed …)
        if (not hunt and not n.engaged and not tied and self.aggressive(n) and not getattr(n, 'passive', False) and now >= n.blocked
                and not self.in_peace(nx, ny) and BG.notice_bot(self, n, now, float('inf') if spared else dist)):
            return                              # a bot ship nearer than the player: attacks it (from the next think: npc_to_bot)
        if (self.aggressive(n) and not getattr(n, 'passive', False) and not spared
                and dist < n.d.get('notice_distance', COMBAT['npc_notice_distance']) * SET.multiplier('npc_notice')
                and not self.in_peace(nx, ny)
                and not n.engaged and not tied and now >= n.blocked):
            n.engaged = True
            n.next_think = min(n.next_think, now)      # start chasing at once (even if frozen with --yakin-npc)
            self.log('   %s attacking (distance %d)' % (n.d['name'], dist))
        if n.engaged and (hero_safe or tied or (dist > 2500 and not hunt)):
            self.disengage(n, now, flee=not hunt)   # the player fled to a safe zone: let go of the chase
            if zoned and not hidden and not hunt:
                self.park_at_zone(n, hx, hy, nx, ny, now)       # waits at the zone's edge (does not flee far); if not possible it moves away
        if n.effect.frozen(now):
            self.alien_ceasefire(n)
            return                              # frozen: does not move, does not fire (state.py)
        if n.engaged:
            # the guard (Cubikon's Protegits) does not stand still: it wanders between points around the summoner that keep the player in its range;
            # when the player goes outside the leash it lets go of the chase (above). Before, it did not move within 450 units, and the swarm
            # that spawned at Cubikon's foot stayed on one point (user report 2026-10-24)
            spot = self.guard_spot(n, post, hx, hy, now) if post and now >= n.next_think else None
            near = min(450, n.keep + 150) * min(1.0, SET.multiplier('npc_range'))   # shorter firing range: close in so the alien can still shoot
            circle = bool(post) and dist <= near
            if (dist > near or post) and now >= n.next_think and n.speed() > 0:
                a = math.atan2(ny - hy, nx - hx) + (random.choice((-1, 1)) * random.uniform(0.6, 1.3) if circle else n.spread)
                keep = n.keep * min(1.0, SET.multiplier('npc_range'))
                tx, ty = spot or (hx + math.cos(a) * keep, hy + math.sin(a) * keep)
                # within the map: so an alien does not leave the map while the player is at the edge or outside the boundary (radiation)
                tx = min(max(tx, 300), self.map_w - 300)
                ty = min(max(ty, 300), self.map_h - 300)
                follows = retaliating and self.hero_in_peace(hx, hy)      # the alien the pilot attacked follows him into the zone
                if not hunt and not follows and (self.path_near_zone(nx, ny, tx, ty, allow_station=retaliating)
                                                 or (self.near_zone(tx, ty, 0) and not (retaliating and self.station_at(tx, ty)
                                                                                       and not self.near_gate_peace(tx, ty)))):
                    self.disengage(n, now)          # does not enter the safe zone
                    self.stop_npc_motion(n, now)
                    n.blocked = now + 6             # so aggression does not restart every step and put it in a stop/search/let-go loop (live: 10 MoveCommand/s)
                    return
                if ML.navigates(self.map_id):      # X-BL: around the wall (the first waypoint of the path; again on every think)
                    if not ML.clear(self.map_id, hx, hy, tx, ty):
                        tx, ty = hx, hy             # the chase point is on the alien's side of the wall: the path to the player itself
                    tx, ty = ML.waypoint(self.map_id, self.map_w, self.map_h, nx, ny, tx, ty)
                ms = 0
                if not (hunt and self.in_peace(tx, ty) and not follows):     # a wave alien waits at the edge of the safe zone (the one the player hit enters)
                    ms = n.mover.go(tx, ty, n.speed() * n.effect.speed_factor(now), now)
                    self.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])
                n.next_think = now + (max(0.5, ms / 1000) + n.ab.pop('wait', 0) if post else 1.0)
            if dist <= self.npc_range(n) and now >= n.next_shot and n.d['damage'] > 0 and now >= self.invuln_until:
                if n.next_shot == 0.0:
                    self.send([legacy('0|n|LSH|%d|%d' % (self.hid, n.id))])
                self.npc_shoot(n, now)
            elif dist > self.npc_range(n):
                self.alien_ceasefire(n)         # went out of range: the laser state closes on the client
            return
        if hunt:
            return                              # a wave alien does not wander: it goes after the player again once reachable
        if now >= n.next_think and n.speed() <= 0:
            n.next_think = now + 3600          # immobile (Cubikon, Mindfire Behemoth)
        elif now >= n.next_think and post:
            # the guard wanders around the summoner (guard.radius), does not flee; each step it turns a bit more around it
            px, py = post.mover.pos(now)
            r = random.uniform(*n.guard[1]['radius'])
            a = math.atan2(ny - py, nx - px) + random.choice((-1, 1)) * random.uniform(0.5, 1.5)
            tx = min(max(px + math.cos(a) * r, 300), self.map_w - 300)
            ty = min(max(py + math.sin(a) * r, 300), self.map_h - 300)
            if self.path_near_zone(nx, ny, tx, ty):
                self.stop_npc_motion(n, now)
                return
            n.flee = False
            ms = n.mover.go(tx, ty, n.speed() * 0.6 * n.effect.speed_factor(now), now)
            self.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])
            n.next_think = now + ms / 1000 + random.uniform(0.2, 1.0)
        elif now >= n.next_think:
            park, n.park = n.park, None             # waited at a zone edge: a normal short wander, away from the zone
            # official server recording (2026-10-27, Lordakia/Saimon/Curcubitor… thousands of steps): wander speed ~90% of nominal, a step is a ~1.5 s
            # movement (0-3 s uniform; Lordakia avg 323 units), ~0.5 s wait between steps
            r = max(30, n.speed() * 0.9 * random.uniform(0.1, 2.9))
            a = math.atan2(ny - park[1], nx - park[0]) + random.uniform(-1.2, 1.2) if park else random.uniform(0, 2 * math.pi)
            tk = COMBAT.get('passive_follow')
            if (tk and not park and not spared and tk['nearby'] < dist <= tk['distance'] and not self.aggressive(n)
                    and not any(n.tip == h or n.tip.startswith(h) for h in tk.get('exclude', ()))):
                a = math.atan2(hy - ny, hx - nx) + random.uniform(-tk['spread'], tk['spread'])    # a passive alien watches the player
                r = min(r, dist - tk['nearby'])
            tx = min(max(nx + math.cos(a) * r, 300), self.map_w - 300)
            ty = min(max(ny + math.sin(a) * r, 300), self.map_h - 300)
            leaving = n.flee or (self.near_zone(nx, ny, 500) and not park)
            if leaving or self.near_zone(tx, ty, 0 if park else 500):
                tx, ty = self.spot_away(hx, hy)     # move away from inside/the edge of the safe zone, away from the player
            if ML.navigates(self.map_id):
                tx, ty = ML.waypoint(self.map_id, self.map_w, self.map_h, nx, ny, tx, ty)
            tries = 0
            while self.path_near_zone(nx, ny, tx, ty):
                tries += 1
                if tries > 5:
                    self.stop_npc_motion(n, now)    # stuck at the edge of a structure: no point with an open path found
                    return
                tx, ty = self.spot_away(hx, hy)     # try another point (so stop commands do not rain every 2 s)
                if ML.navigates(self.map_id):
                    tx, ty = ML.waypoint(self.map_id, self.map_w, self.map_h, nx, ny, tx, ty)
            n.flee = False
            ms = n.mover.go(tx, ty, n.speed() * (1.0 if leaving else 0.9) * n.effect.speed_factor(now), now)
            self.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])
            n.next_think = now + ms / 1000 + random.uniform(0, 1.0)

    def loop(self):
        self._loop_ident = threading.get_ident()
        while self.running:
            time.sleep(0.1)
            with self.lock:
                if not self.running:
                    break                      # stopped (map change) but the loop was waiting for the lock: do not process one more step
                t0 = time.perf_counter()
                self._batch = []
                try:
                    self.step(time.time())
                except Exception:               # so the thread does not die (aliens and timers would stop); the next step tries again
                    self.step_error('step')
                finally:
                    batch, self._batch = self._batch, None
                if batch:                       # under the lock: before the session's later messages, in the same order
                    try:
                        self.send_raw(batch)
                    except OSError:
                        self.running = False
                    except Exception:
                        self.step_error('send')
                self.perf.add((time.perf_counter() - t0) * 1000.0)

    def step_error(self, what):
        """The loop error's stack trace to the log; the same error (its last line) is written at most once per 60 s."""
        tb = traceback.format_exc()
        key, now = tb.strip().splitlines()[-1], time.time()
        if now - self.step_errors.get(key, 0) >= 60:
            self.step_errors[key] = now
            self.log('   world %s error (%s):\n%s' % (what, H.name(self.map_id), tb))

    def step(self, now):
        """One step of the loop (0.1 s; under the world lock): timers, view, aliens, boxes … The measuring tool
        (tools/performance.py) calls it without a thread."""
        due = [t for t in self.timers if t[0] <= now]
        self.timers = [t for t in self.timers if t[0] > now]
        for _, fn in due:
            try:                               # if one fails, the other timers in the same step must not be lost
                fn()
            except Exception:
                self.step_error('timer')
        if self.collect_wish:
            self.collect_tick(now)
        if self.opening:
            self.booty_tick(now)
        if not self.jumping:
            self.check_gates(now)
            self.check_assets(now)
            self.view_tick(now)
            self.radiation_tick(now)
        leader = self.leader()                   # on a shared map the map's jobs are with the leader (shared_maps.py)
        self.booster_tick(now)
        if leader:
            self.respawn_tick(now)
            BG.tick(self, now)                 # bots (bot/ship.py): those on the map as ships
        self.auto_tick(now)
        self.effects_tick(now)
        self.abilities.tick(now)
        self.items.tick(now)
        self.tech.tick(now)
        self.particle.tick(now)
        self.alien.tick(now)
        if leader:
            self.event.tick(now)
        self.rules_tick(now)
        self.ach_tick(now)
        if self.repairing:
            self.repair_tick(now)
        self.shield_tick(now)
        self.settings_tick(now)
        self.music_tick(now)
        self.form_shield_tick(now)
        self.lab_time(now)
        if self.attacking and not self.hero_dead and not self.jumping and now >= self.next_laser:
            self.hero_laser(now)
        if self.fire and not self.attacking and self.shared:
            # laser ended (target died or someone else killed it, left view, player jumped …): the client sets up the attacker's target in AttackLaserRunCommand
            # and turns the ship toward it; if AttackAbortLaserCommand does not arrive, on the other players' screens the ship
            # stays facing the target, its nose does not turn and no engine effect appears (shared_maps.REFLECTED)
            self.shared.mirror(self, [('AttackAbortLaserCommand', {'uid': self.hid})])
        self.fire = self.attacking
        if self.pet:
            self.pet.tick(now)
        if self.gate:
            self.gate.tick(now)
        if self.low:
            self.low.tick(now)
        if self.labyrinth:
            self.labyrinth.tick(now)
        if self.session_tick:
            self.session_tick(now)
        self.step_peace = {}
        try:
            for n in list(self.npcs.values()):
                if self.owner(n, now):        # the world that owns the alien on a shared map (the one it fights or the nearest player)
                    self.think(n, now)
        finally:
            self.step_peace = None
        for h, b in list(self.boxes.items()) if leader else ():
            if b['end_time'] and now > b['end_time']:
                del self.boxes[h]
                self.send([('RemoveCollectableCommand', {'collected': False, 'hash': h})])

import bot.ship as BG  # noqa: E402  (bot players; ship imports world: after the classes)
