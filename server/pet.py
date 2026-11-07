"""P.E.T.-10: purchase, hangar (equipment, slot unlocking, name), escort in space, gears, fuel, level, damage and repair.

The recorded account had no P.E.T. (PetInitializationCommand hasPet false). The formats come from other players' P.E.T.s (the recorded
PetActivationCommand, PetStatusCommand) and from the client's code (UIPetSystem, the PetRequest/PetGearType enums, Pet.Initialize
slot names, the P.E.T. ship types in game.xml):
  login     PetInitializationCommand {hasPet, hasFuel, petIsAlive}: the P.E.T. window's buttons
  launch    PetRequest LAUNCH (window) / TOGGLE_ACTIVATION (shortcut) -> PetHeroActivationCommand + PetStatusCommand +
            PetGearAddCommand per gear + PetGearSelectCommand (+ the target list of the locator gears: client ids of enemy NPCs
            or ore types; refreshed every 5 s as those on the map change)
  stop      PetRequest DEACTIVATE -> PetDeactivationCommand
  gear      PetGearActivationRequest {gearTypeToActivate, optParam} -> PetGearSelectCommand
  movement  MoveCommand (with the P.E.T.'s id): follows the ship; with the collector gears goes to the box/ore
  combat    in guard mode fires the selected ammo at the ship's target (NPC/CBS) or at the station attacking the ship/P.E.T.
  damage    an enemy CBS hits a P.E.T. in range; the player can also select and hit their own P.E.T. (for Kamikaze's
            HP threshold; no reward). On death ShipDestroyedCommand + PetIsDestroyedCommand + the repair button (PetUIRepairButtonCommand);
            PetRequest REPAIR_DESTROYED_PET -> PetRepairCompleteCommand, the P.E.T. returns with repair_hp of its maximum HP
  fuel      uses per minute while active (PetFuelUpdateCommand); when it runs out PetOutOfFuelCommand; HOTKEY_BUY_FUEL 1,000 units
  level     5% of the EP the player earns: PetExperiencePointsUpdateCommand, PetLevelUpdateCommand
  HEAT      heats up while active (PetHeatUpdateCommand {heatState 0 heating/1 steady/2 cooling, heatLevel, petHeatAmount(Max)}; client:
            UIPetSystem.HeatUpdate); the level bonuses go to the ship while the P.E.T. is in space (profile.mods <- pet_mods), the HP bonus to the
            P.E.T.'s own HP (recording: the maximum HP of level 20 P.E.T.s). When it stops the level's cooling
            delay starts, when it ends it cools; on dropping a level that level's delay. HEAT slots are active from level 4.
  G-HR1     Heat Release gear: spends P.E.T. HP for 4 s to lower HEAT (no delay), damages its surroundings (VisualModifier 107)
Hangar: HangarShipsCommand.petView (rootId filled = a P.E.T. exists), HangarShipEquipmentCommand.petConfigs (per config lasers,
  generators, gears, protocols, heat, visual); HangarShipUnlockSlotRequest {slotset} unlocks a slot (including "heat");
  HangarShipRenamePetRequest changes the name. The design (pet_designs_*) is in the "visual" slot: the look in space (game.xml type).
In the shop G-HP1 (pet_upgrade-g-hp1): +10,000 HP up to the P.E.T.'s level.
Values in data/items.json "pet" (wiki, recording and adaptations; the source note is there).
"""
import json, math, os, random, time
import game_data as DATA
import ranks as RT
import settings as SET
import lasers as LASERS
import map_links as H
import upgrades as UPG

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
COMBAT = DATA.load('npc.json')['combat']
PET = ITEMS['pet']
GEARS = PET['gears']
PROTOCOLS = PET['protocols']
HEAT = PET['heat']
HEAT_ROWS = HEAT['levels']
HEAT_MAX = HEAT_ROWS[-1]['threshold']
HEATING, STABLE, COOLING = 0, 1, 2       # PetHeatUpdateCommand.heatState (client: " +" white, " =" yellow, " --" blue)
PID_SHARED = 160000000                    # start of the P.E.T. ids on a friend server (aliens 150300000, CBS 157000000)
VM_HEAT_RELEASE = 107                    # VisualModifierCommand.modifier (the client's VisualModifier enum)
VM_HP_LINK = 86
HULL = PET['hp_upgrade']['loot']
DESIGNS = PET['designs']

# the client's PetGearType enum
PASSIVE, GUARD, AUTO_LOOT, AUTO_RESOURCE, ENEMY_LOCATOR, RESOURCE_LOCATOR = 1, 2, 4, 5, 6, 7
TRADE_POD, REPAIR_PET, KAMIKAZE, COMBO_REPAIR, COMBO_GUARD = 8, 9, 10, 11, 12
TRADE_BUFF = 3                          # the client's game.xml petBuffs: trade_buff.png / ttip_pet_trading
# gear cooldowns in the P.E.T. window's buff row (PetBuffCommand, seconds; the client counts down and shows "<gear> may not be selected
# until its cooldown has ended. Cooldown: m:ss"); ids read live from the client's icons and tooltips (2026-11-02): 5 Kamikaze,
# 6 Combo Ship Repair, 7 Sacrificial Flame, 8 Retargeting, 9 HP Link, 10 Mega Mine, 11 Combat Beacon, 12 HP Beacon, 13 Heat Release
# (1 Singularity, 2 Speed Leech and 4 Weaken Shield draw nothing in this client)
COOLDOWN_BUFF = {}                      # filled below, once the gear types are known
RETARGETING, HP_LINK, MEGA_MINE, COMBAT_BEACON, HP_BEACON, HEAT_RELEASE = 15, 16, 17, 18, 19, 20
FRIENDLY_SACRIFICE = 14
WORKING = {PASSIVE, GUARD, AUTO_LOOT, AUTO_RESOURCE, ENEMY_LOCATOR, RESOURCE_LOCATOR, TRADE_POD, REPAIR_PET, KAMIKAZE, COMBO_REPAIR,
           COMBO_GUARD, HEAT_RELEASE, HP_LINK, COMBAT_BEACON, HP_BEACON, MEGA_MINE, FRIENDLY_SACRIFICE}
FIGHTING = {GUARD, KAMIKAZE, COMBO_GUARD, HP_LINK}
# gears with cooldowns -> the name in the client's msg_pet_<name>-gear_cooldown_ready / _not_ready texts
TIMED = {HP_LINK: 'hp-link', COMBAT_BEACON: 'combat-beacon', HP_BEACON: 'hp-beacon', MEGA_MINE: 'mega-mine'}
BEACONS = (COMBAT_BEACON, HP_BEACON)
READY_NAMES = {**TIMED, KAMIKAZE: 'kamikaze', FRIENDLY_SACRIFICE: 'friendly_sacrifice'}     # msg_pet_<name>-gear_cooldown_ready
COOLDOWN_BUFF.update({KAMIKAZE: 5, COMBO_REPAIR: 6, FRIENDLY_SACRIFICE: 7, HP_LINK: 9, MEGA_MINE: 10, COMBAT_BEACON: 11, HP_BEACON: 12,
                      HEAT_RELEASE: 13})
MEGA_MINE_TYPE = 19                      # AddMineCommand.typeId -> lib_assets mine_19 "megaMine" (live 2026-11-05: drawn; AssetCreateCommand
                                         # PET_MEGA_MINE 70 only made an invisible building, like the recorded Curcubitor mine type 20)
SACRIFICE_EFFECT = 6                     # PlayVisualEffectCommand.VisualEffectType.PET_FRIENDLY_SACRIFICE_EXPLOSION
MINE_UID = [158600000]
BEACON_ASSET = {HP_BEACON: 71, COMBAT_BEACON: 72}   # AssetTypeModule PET_HP_BEACON / PET_COMBAT_BEACON -> "pet_beacon" (green / red tower; live 2026-11-05)                  # ids of Mega Mine objects on the map (CBS assets 157000000, P.E.T.s 160000000)
START_MAPS = ('1-1', '2-1', '3-1')       # G-KK1 is not selectable (client msg_pet_kamikaze-gear_not_on_start_maps)
FUEL_WARN = 0.1                          # when fuel drops to 10% of the maximum, msg_pet_running_out_of_fuel (the ratio is an adaptation)
FOLLOW_AHEAD = 1.0                       # while following, how many seconds behind the ship's future position to stay (follow)
# the client's PetRequest.PetRequestType enum
LAUNCH, DEACTIVATE, TOGGLE, HOTKEY_GUARD, REPAIR_DESTROYED, HOTKEY_REPAIR_SHIP, HOTKEY_BUY_FUEL = range(7)
DESTROYED_NONE, DESTROYED_KAMIKAZE = 0, 1
# hangar slots (client: Pet.Initialize, HangarAuxiliary.ReturnPetMaxSlotCount) -> fittable items
SLOTS = {'lasers': 'equipment_weapon_laser_', 'generators': 'equipment_generator_shield_', 'gears': 'equipment_petgear_',
         'protocols': 'equipment_aiprotocol_', 'visual': 'pet_designs_'}
ALL_SLOTS = tuple(SLOTS) + ('heat',)     # heat: a laser or shield generator (the slotSet of the move request is "heat")
NOVA_KEYS = {'hp': 'pet_hp', 'range': 'pet_range', 'heat': 'pet_heat', 'fuel': 'pet_fuel'}     # N.O.V.A. abilities (nova.py)
UNIQUE = ('gears',)                      # the same gear cannot be fitted twice; protocols can be fitted several times (3 Radar Protocol; user 2026-10-24)


def mod(name, **f):
    f['_'] = name
    return f


from legacy_protocol import legacy  # noqa: E402,F401  (old text protocol: legacy_protocol.py)


def blast_damage(full, d, near, reach):
    """The Kamikaze's damage at distance d from the blast: the nearest target (the one it went for) takes it in full, the others less the
    farther they are, down to none at the edge (fandom Kamikaze Gear: "the primary target will take the full damage while areas around the
    main target will take reduced damage"; player report 2026-11-04: every alien took the full damage)."""
    if d <= near or reach <= near:
        return full
    return int(full * max(0.0, 1 - (d - near) / (reach - near)))


def gear_type(t):
    return mod('PetGearTypeModule', typeValue=t)


def at_level(info, lv):
    """Gear/protocol values at a level: lists (levels 1-3, for protocols 1-4) go down to that level's value."""
    return {k: (v[min(max(lv, 1), len(v)) - 1] if isinstance(v, list) else v) for k, v in info.items()}


def has_levels(loot):
    """The item whose level is chosen in the shop (a P.E.T. gear or protocol)."""
    return loot in GEARS or loot in PROTOCOLS


def level_prices(loot):
    """The levels' uridium prices (wiki, recording; 0 at protocols' level 4 = not sold in the shop) or None."""
    info = GEARS.get(loot) or PROTOCOLS.get(loot)
    return info.get('price') if info else None


def level_need(lv):
    """The P.E.T. level needed for a gear/protocol level (wiki: level 2 4, level 3 8, level 4 20)."""
    need = PET['item_level_req']
    return need[min(max(lv, 1), len(need)) - 1]


def slot_for(loot):
    """The slot the item can be fitted in on the P.E.T. (laser, generator, gear, protocol, design) or None."""
    return next((s for s, pre in SLOTS.items() if loot.startswith(pre)), None)


def heat_slot_ok(loot):
    """Only a laser or shield generator in the HEAT slot."""
    return slot_for(loot) in ('lasers', 'generators')


def heat_level(points):
    return max(i for i, r in enumerate(HEAT_ROWS) if points >= r['threshold'])


def heat_cap(points):
    """The bar's maximum: the next HEAT threshold (the last threshold at the last level). Real recording: at level 0 petHeatAmountMax 75 (the first threshold)."""
    return HEAT_ROWS[min(heat_level(points) + 1, len(HEAT_ROWS) - 1)]['threshold']


def heat_bonus(lv):
    """Bonuses accumulated up to the HEAT level (wiki: the levels' bonuses add up)."""
    out = {}
    for r in HEAT_ROWS[1:lv + 1]:
        for k, v in r['bonus'].items():
            out[k] = out.get(k, 0) + v
    return out


def px_bonus(loot, lv):
    """LF-PX01 / SG3N-PX01: damage/shield bonus by HEAT level."""
    return HEAT['px01'][lv - 1] if lv >= 1 and loot.endswith('-px01') else 0.0


def locator_id(n):
    """The value the enemy locator uses for an NPC: the client's NPC id (npc.json npc_id) or 0 (not in the list). The client
    names the value an NPC id (UIPetSystem.SubMenuItemRender -> GameDefineSystem.GetNpcName/GetNpcIcon: NpcNames,
    game.xml ShipPatternsByNpcId); the ship model id shows a different ship (Streuner's model 84 = "Saturn Vengeance",
    Lordakia's 71 = "Hooligan"). Friendly ships (escort and guard ships, Vortex's invisible evacuation anchor) and those without a client
    id (fake Emperors, event aliens with unknown ids) do not count as enemies."""
    if not n.alive or n.d.get('friendly'):
        return 0
    return int(n.d.get('npc_id') or 0)


def new_pet(profile):
    """The purchased P.E.T. (level 0, 10,000 fuel). Its equipment is in each ship's own two configs (profile.pet_config)."""
    return {'uid': 7001, 'name': PET['name'], 'level': 0, 'ep': 0, 'hp': PET['hp'], 'shield': 0, 'fuel': PET['start_fuel'],
            'destroyed': False, 'gear': PASSIVE, 'slot': dict(PET['start_slots']), 'heat': 0.0, 'hp_upgrade': 0}


class Pet:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.w = None                # the world in space (world.World); a new one is bound when the map changes
        self.send_raw = None         # do not send to the session when there is no world (hangar, shop)
        self.active = False
        self.relaunch = False        # map changed/reloaded: launches again when ready
        self.mover = None
        self.task = None             # ('box' | 'ore', hash): the collector gear's target
        self.shooting = None         # the NPC/CBS id being fired at
        self.last_fight = 0.0        # the P.E.T.'s own combat (shot, hit, being hit): does not affect the hero's combat (w.last_combat: repair, shield)
        self.next_shot = self.next_follow = self.next_second = self.next_locate = 0.0
        self.fuel_clock = 0.0        # unspent fuel (units)
        self.tick_t = time.time()
        self.locate = {}             # locator gear -> selected target (client NPC id / ore type)
        self.targets_sent = {}       # locator gear -> the target list sent to the client
        self.trading = False         # cargo trader selected: the refinery window is open in space
        self.trade_ready = 0.0
        self.trade_wait = False      # cargo trader cooling down: the P.E.T. window is locked, "Trade buff" icon (trade_close)
        self.trade_paid = False      # this trade session's fuel was paid (sell as much as wanted while the window is open)
        self.fuel_sent, self.next_fuel_msg = 0, 0.0
        self.release_end = 0.0       # G-HR1 (Heat Release) end, if running
        self.release_ready = 0.0     # G-HR1 cooldown end
        self.link_end = 0.0          # G-HPL1 (HP Link) end, if linked
        self.csr_end = self.csr_ready = 0.0     # end of the C-SR2 repair window (5 s) and of the cooldown (15 s)
        self.beacon = None           # G-BC1/G-BH1 marker: (type, x, y, end)
        self.beacon_uid = None       # its tower on the map (AssetCreateCommand)
        self.in_beacon = False       # the ship is within the marker's range: the bonus is on the ship
        self.mine = None             # G-MM1 mine on the map: {uid, x, y, next, left}
        self.ready = {}              # gears on cooldown (TIMED): type -> cooldown end
        self.charge_end = 0.0        # G-KK1 flying at its target: explodes on arrival
        self.charge_at = None        # what it flies at: an NPC/bot id or ('p', world) of a player on the shared map; re-aimed on arrival
        self.charge_hops = 0
        self.rep_state = None        # G-REP state last sent (PetGearActivationChangeCommand: on while the P.E.T. is hurt)
        self.buffs_sent = {}         # cooldown buffs in the window: buff id -> cooldown end (buff_msgs)
        self.look = None             # the look (ship type) the client knows: PetLevelUpdateCommand only when it changes
        self.release_wait = False    # a "ready" message will go when the cooldown ends
        self.heat_sent, self.next_heat_msg = None, 0.0
        self.on_stats = None         # ship values again (shop.apply_stats): when the HEAT bonus changes
        profile.pet_mods = self.heat_mods
        self.load_cooldowns()

    # ------------------------------------------------------------ profile
    @property
    def d(self):
        return self.p.d.get('pet')

    @property
    def owned(self):
        return bool(self.d)

    @property
    def pid(self):
        """7001 in the recording; on a friend server per player (so it does not get mixed up on the same map with other players' P.E.T.s)."""
        import multiplayer as CO
        return PID_SHARED + self.p.user_id % 10 ** 7 if CO.is_open() else self.d['uid']

    @property
    def alive(self):
        return self.owned and not self.d['destroyed']

    def row(self, lv=None):
        return PET['levels'][self.d['level'] if lv is None else lv]

    def config(self, cid=None, sid=None):
        """The P.E.T.'s slots in one config of a ship (default: the active one): the P.E.T. is single, its equipment is in the ship's (hangar's) record."""
        c = self.p.pet_config(cid, sid)
        for s in ALL_SLOTS:
            c.setdefault(s, [])
        return c

    def loadout(self, cid=None):
        """Equipped items in a config: slot -> lootId list."""
        es = self.p.d['items']
        return {s: [es[str(i)] for i in ids if str(i) in es] for s, ids in self.config(cid).items()}

    def leveled(self, slot):
        """Equipped gears/protocols: [(lootId, level 1-3)]."""
        es = self.p.d['items']
        return [(es[str(i)], self.p.item_level(i)) for i in self.config()[slot] if str(i) in es]

    def proto(self, key):
        """The value of equipped protocols + N.O.V.A.'s P.E.T. abilities (nova.py: HP, range, HEAT gain; fuel decreases)."""
        v = sum(at_level(PROTOCOLS.get(l, {}), lv).get(key, 0) for l, lv in self.leveled('protocols'))
        nk = NOVA_KEYS.get(key)
        if nk and getattr(self.p, 'nova_mods', None):
            n = self.p.nova_mods().get(nk, 0)
            v += -n if key == 'fuel' else n
        return v

    def installed_gears(self):
        """Equipped gears: type -> (lootId, values at the level, level)."""
        out = {}
        for l, lv in self.leveled('gears'):
            g = GEARS.get(l)
            if g:
                out.setdefault(g['type'], (l, at_level(g, lv), lv))
        return out

    def gear(self, t):
        return (self.installed_gears().get(t) or (None, {}, 0))[1]

    def hp_max(self):
        """Base HP + G-HP1 upgrades (+10,000 each), with the AI-HP protocol and HEAT's HP bonus (recording: the maximum HP of level 20
        P.E.T.s (50,000 + G-HP1) x1.10 / x1.20, with AI-HP x1.14)."""
        base = PET['hp'] + PET['hp_upgrade']['step'] * self.d.get('hp_upgrade', 0)
        return int(base * (1 + self.proto('hp') + self.heat_bonuses().get('hp', 0)))

    def heat_items(self, slot):
        """Lasers/generators in the HEAT slot: counted only if the HEAT level has reached slot_level (4)."""
        if self.heat_lv() < HEAT['slot_level']:
            return []
        return [l for l in self.loadout()['heat'] if slot_for(l) == slot]

    def upgraded(self, slot):
        """Lasers or generators in the slot (those in the HEAT slot as in heat_items) with their upgrade levels [(lootId, level)]."""
        es, lv, c = self.p.d['items'], self.p.d.get('upgrade_level', {}), self.config()
        ids = c[slot] + (c['heat'] if self.heat_lv() >= HEAT['slot_level'] else [])
        return [(es[str(i)], int(lv.get(str(i), 0))) for i in ids if str(i) in es and slot_for(es[str(i)]) == slot]

    def shields(self):
        """Generators: (shield, absorption); SG3N-PX01 HEAT bonus and upgrade level (client GENERATOR_SHIELD_UPGRADE 1%)."""
        shield_table, hl = ITEMS['shield_generators'], self.heat_lv()
        return [(shield_table[g]['shield'] * (1 + px_bonus(g, hl)) * UPG.factor(g, lv, UPG.SHIELD), shield_table[g]['absorb']) for g, lv in self.upgraded('generators')
                if g in shield_table]

    def shield_max(self):
        return int(sum(k for k, e in self.shields()) * (1 + self.row()['shield'] + self.proto('shield')))

    def absorb(self):
        sh = self.shields()
        total = sum(k for k, e in sh)
        return sum(k * e for k, e in sh) / total if total else 0.8

    def lasers(self):
        return [l for l in self.loadout()['lasers'] + self.heat_items('lasers') if l in ITEMS['lasers']]

    def laser_damage(self, target=None, pvp=False):
        """The lasers' total damage: lasers.py's hit as on the ship (AAP-1's target_multiplier, alien bonus), the LF-PX01 HEAT
        bonus and upgrade level (client LASER_DAMAGE_UPGRADE 0.5%)."""
        hl = self.heat_lv()
        return sum(LASERS.hit(l, target, pvp=pvp) * (1 + px_bonus(l, hl)) * UPG.factor(l, lv, UPG.LASER)
                   for l, lv in self.upgraded('lasers') if l in ITEMS['lasers'])

    def speed(self):
        """The P.E.T. follows the ship: the same speed as the ship (recording: another player's P.E.T. 395)."""
        return self.p.d['ship'].get('speed', 300)

    def design(self):
        """The equipped P.E.T. design (lootId) or None."""
        v = self.loadout()['visual']
        return v[0] if v else None

    def ship_type(self):
        """Look: the equipped design's game.xml type (tools/pet_designs.py), otherwise by level (12 level 1-3 ... 22 level 13-15)."""
        t = DESIGNS.get(self.design() or '')
        if t:
            return t
        lv = self.d['level']
        return [t for need, t in PET['ship_type'] if lv >= need][-1]

    def fuel_per_min(self, now=None):
        """Level table (real recording: level 7 33, 13 44; the forum's 1 + 2 x level + 2 x protocol + 4 x gear formula gives a single number,
        it cannot produce level 13's 44: the recording governs) x fuel protocol, Combo Guard, HP Link / beacon x1.3, +5% per heat level."""
        rate = self.row()['fuel_per_min'] * (1 + self.proto('fuel'))
        g = self.d.get('gear')
        if g == COMBO_GUARD:
            rate *= 1 + self.gear(COMBO_GUARD).get('extra_fuel', 0)
        now = time.time() if now is None else now
        if self.link_end > now:
            rate *= self.gear(HP_LINK).get('fuel_multiplier', 1)
        if self.beacon and self.beacon[3] > now:
            rate *= self.gear(self.beacon[0]).get('fuel_multiplier', 1)
        rate *= 1 + 0.05 * self.heat_lv()
        return rate * SET.multiplier('pet_fuel')                 # panel: P.E.T. fuel (C-SR2's extra fuel per repair: each_second)

    def open_slots(self, slot):
        if slot == 'visual':
            return 1                         # client: HangarAuxiliary.ReturnPetMaxSlotCount "visual" is fixed
        if slot == 'generators':             # the generator slot does not come with the level: starting 2 + purchased (real recording: 2 at level 7)
            worn = (len(c.get(slot, [])) for s in self.p.d['ships'].values() for c in s.get('pet_config', {}).values())
            return max(self.d['slot'].get(slot, 0), max(worn, default=0))       # what was fitted in an old profile is always open
        return max(self.d['slot'].get(slot, 0), self.row()['slot'].get(slot, 0))

    def slot_price(self, slot):
        """The next slot's uridium price; 0 if the maximum slots are reached. The first of the HEAT slots is paid too (wiki 20,000)."""
        n = self.open_slots(slot)
        prices = PET['slot_prices'].get(slot, [])
        # panel: service fees (at least 1: 0 means "maximum slots")
        return max(1, SET.price('service_price', prices[n], 'pet')) if n < min(PET['max_slots'].get(slot, 0), len(prices)) else 0

    def gear_list(self):
        """The window's gear list: (type, level, usable). Passive and guard always; the others if fitted."""
        out = [(PASSIVE, 1, True), (GUARD, 1, True)]
        for t, (l, g, lv) in sorted(self.installed_gears().items()):
            out.append((t, lv, t in WORKING and 'none' not in g))
        return out

    # ------------------------------------------------------------ HEAT
    def cool(self, now=None):
        """Cooling while inactive: once the level's delay ends at cooling_sec rate; on dropping a level it stops and that level's
        delay starts (wiki). Time spent out of the game counts too (heat_time)."""
        d = self.d
        now = time.time() if now is None else now
        t = d.get('heat_time') or now
        if self.active:
            d['heat_time'] = now
            return
        rate, before = HEAT['cooling_sec'], d.get('heat', 0)
        while d.get('heat', 0) > 0 and t < now:
            start = d.get('heat_cooldown') or 0
            if start >= now:
                break
            t = max(t, start)
            lv = heat_level(d['heat'])
            target = max(0.0, HEAT_ROWS[lv]['threshold'] - 1e-6) if lv else 0.0
            need = (d['heat'] - target) / rate
            if t + need <= now:
                t += need
                d['heat'] = target
                d['heat_cooldown'] = t + HEAT_ROWS[heat_level(target)]['cooldown_sec']
            else:
                d['heat'] -= (now - t) * rate
                t = now
        d['heat_time'] = now                 # lock-free: P.E.T. values are read even under the lock (player_profile.lock is not re-entered)
        if d.get('heat', 0) != before:
            self.p.dirty = True

    def heat(self):
        if not self.owned:
            return 0.0
        self.cool()
        return self.d.get('heat', 0.0)

    def heat_lv(self):
        return heat_level(self.heat()) if self.owned else 0

    def heat_state(self, now=None):
        now = time.time() if now is None else now
        if self.active:
            return HEATING if self.d.get('heat', 0) < HEAT_MAX else STABLE
        return COOLING if self.d.get('heat', 0) > 0 and now >= (self.d.get('heat_cooldown') or 0) else STABLE

    def heat_bonuses(self):
        """The HEAT level's bonuses; on Goliath Plus each of them and the ship's six base stats (NPC and PvP damage, HP, shield penetration,
        laser accuracy, evasion) +1% per HEAT level (items.json per_heat; official forum 160989)."""
        lv = self.heat_lv()
        per = self.p.ship_row().get('per_heat', 0) * lv
        out = {k: v + per for k, v in heat_bonus(lv).items()}
        if per:
            for k in ('npc', 'pvp_damage', 'hp', 'shield_penetration', 'hit', 'evasion'):
                out.setdefault(k, per)
        return out

    def in_fight(self, now=None):
        """P.E.T. in combat: it or the ship fired / was hit within out_of_combat_sec."""
        now = time.time() if now is None else now
        return bool(self.w) and now - max(self.w.last_combat, self.last_fight) < ITEMS['out_of_combat_sec']

    def heat_mods(self):
        """HEAT bonuses to the ship (player_profile.mods): only while the P.E.T. is in space; the HP bonus to the P.E.T. itself (hp_max). That of the
        G-BC1/G-BH1 marker while within the ship's range."""
        if not (self.owned and self.active):
            return {}
        out = {k: v for k, v in self.heat_bonuses().items() if k != 'hp'}
        beacon = self.beacon
        if self.in_beacon and beacon:
            for k, v in self.gear(beacon[0]).get('bonus', {}).items():
                out[k] = out.get(k, 0) + v
        return out

    def heat_msg(self, now=None):
        h = self.heat()
        return ('PetHeatUpdateCommand', dict(heatState=self.heat_state(now), petHeatAmountMax=float(heat_cap(h)), heatLevel=heat_level(h),
                                             petHeatAmount=float(round(h, 2))))

    def add_heat(self, amount):
        """Changes HEAT (within limits) -> whether the level changed."""
        d = self.d
        old = heat_level(d.get('heat', 0))
        with self.p.lock:
            d['heat'] = min(float(HEAT_MAX), max(0.0, d.get('heat', 0) + amount))
            d['heat_time'] = time.time()
            self.p.dirty = True
        return heat_level(d['heat']) != old

    def stop_heat(self, now):
        """The P.E.T. was withdrawn from space: the cooling delay of its current level starts."""
        with self.p.lock:
            self.d['heat_cooldown'] = now + HEAT_ROWS[heat_level(self.d.get('heat', 0))]['cooldown_sec']
            self.d['heat_time'] = now
            self.p.dirty = True

    def stats_msgs(self):
        """The HEAT bonus changed: ship values (HP, damage ...) again."""
        return self.on_stats() if self.on_stats else []

    # ------------------------------------------------------------ G-HP1 (HP upgrade)
    def hull_price(self):
        """The uridium price of the next HP upgrade or None (no P.E.T., upgraded up to its level, at most 20)."""
        if not self.owned:
            return None
        n, prices = self.d.get('hp_upgrade', 0), PET['hp_upgrade']['prices']
        return prices[n] if n < min(self.d['level'], len(prices)) else None

    def upgrade_hull(self):
        step = PET['hp_upgrade']['step']
        with self.p.lock:
            self.d['hp_upgrade'] = self.d.get('hp_upgrade', 0) + 1
            self.d['hp'] = min(self.hp_max(), self.d['hp'] + step)
            self.p.dirty = True
        self.log('   P.E.T. HP upgrade %d: maximum HP %d' % (self.d['hp_upgrade'], self.hp_max()))
        return [self.hp_msg(), self.status_msg()] if self.active else []

    # ------------------------------------------------------------ mesajlar
    def send(self, msgs):
        msgs = [m for m in msgs if m]
        if not msgs:
            return
        if self.w:
            self.w.send(msgs)
        elif self.send_raw:
            self.send_raw(msgs)

    def init_msg(self):
        return ('PetInitializationCommand', {'hasPet': self.owned, 'hasFuel': self.owned and self.d['fuel'] > 0,
                                             'petIsAlive': self.alive})

    def status_msg(self):
        d = self.d
        return ('PetStatusCommand', dict(
            petId=self.pid, petLevel=d['level'], petExperiencePoints=d['ep'], petExperiencePointsUntilNextLevel=self.next_xp(),
            petHitPoints=int(d['hp']), petHitPointsMax=self.hp_max(), petShieldEnergyNow=int(d['shield']),
            petShieldEnergyMax=self.shield_max(), petCurrentFuel=int(d['fuel']), petMaxFuel=PET['max_fuel'], petSpeed=self.speed(),
            petName=d['name'], petLootId=''))

    def next_xp(self):
        """The next level's total EP; at the highest level the current EP (recording: the two are equal for level 20 P.E.T.s)."""
        lv = self.d['level']
        rows = PET['levels']
        return rows[lv + 1]['ep'] if lv + 1 < len(rows) else self.d['ep']

    def activation_msg(self, x, y):
        pl = self.p.d['pilot']
        self.look = self.ship_type()
        return ('PetHeroActivationCommand', dict(
            ownerId=self.p.user_id, petId=self.pid, shipType=self.ship_type(), expansionStage=1, petName=self.d['name'],
            factionId=pl.get('factionId', 1), clanId=0, petLevel=self.d['level'], clanTag='', x=int(x), y=int(y), petSpeed=self.speed(),
            minimapStrategyModule=mod('MinimapStrategyModule', minimapStrategy=0)))

    def gear_msgs(self):
        msgs = [('PetGearAddCommand', dict(gearType=gear_type(t), level=lv, amount=0, enabled=ok)) for t, lv, ok in self.gear_list()]
        self.targets_sent = {}
        self.rep_state = None                    # the G-REP state goes again with the next second
        return msgs + self.locator_msgs() + self.cooldown_msgs(time.time()) + [self.select_msg()]

    def cooldown_msgs(self, now):
        """Gears still cooling down are grey again (PetGearAddCommand comes enabled): after a kamikaze and repair, a relaunch or a map change
        Kamikaze, HP Link, the beacons and Heat Release looked ready while on cooldown (player report 2026-11-02: "no Kami timer")."""
        off = [t for t, r in self.ready.items() if r > now] + ([HEAT_RELEASE] if self.release_ready > now else [])
        installed = self.installed_gears()
        return [('PetGearActivationChangeCommand', dict(gearType=gear_type(t), active=False)) for t in off if t in installed]

    def cooldown_ends(self, now):
        """Gears cooling down -> {gear type: end}."""
        out = {t: r for t, r in self.ready.items() if r > now}
        if self.release_ready > now:
            out[HEAT_RELEASE] = self.release_ready
        if self.csr_end <= now < self.csr_ready:
            out[COMBO_REPAIR] = self.csr_ready
        return out

    def buff_msgs(self, now):
        """The cooldown buffs of the P.E.T. window (bottom left, where the trade buff is): added with the seconds left when a cooldown
        starts (also while the P.E.T. is destroyed, as after a kamikaze), removed when it ends (player report 2026-11-02: no Kamikaze timer)."""
        want = {COOLDOWN_BUFF[t]: e for t, e in self.cooldown_ends(now).items() if t in COOLDOWN_BUFF}
        msgs = [('PetBuffCommand', dict(effectAction=0, effectId=b, addingParameters=[max(1, int(math.ceil(e - now)))]))
                for b, e in sorted(want.items()) if self.buffs_sent.get(b) != e]
        msgs += [('PetBuffCommand', dict(effectAction=1, effectId=b, addingParameters=[])) for b in sorted(self.buffs_sent) if b not in want]
        self.buffs_sent = want
        return msgs

    def load_cooldowns(self):
        """Cooldown end times are kept in the pet save (d['cd']): relogging does not skip them."""
        now = time.time()
        cd = (self.d or {}).get('cd') or {}
        self.ready = {int(t): r for t, r in cd.get('ready', {}).items() if r > now}
        self.release_ready = cd.get('release_ready', 0.0)
        self.release_wait = self.release_ready > now
        self.csr_ready = cd.get('csr_ready', 0.0)
        self.trade_ready = cd.get('trade_ready', 0.0)
        self.trade_wait = self.trade_ready > now

    def save_cooldowns(self, now):
        d = self.d
        cd = {'ready': {str(t): r for t, r in self.ready.items() if r > now}}
        for k, v in (('release_ready', self.release_ready), ('csr_ready', self.csr_ready),
                     ('trade_ready', self.trade_ready if self.trade_wait else 0.0)):
            if v > now:
                cd[k] = v
        if d is not None and d.get('cd', {'ready': {}}) != cd:
            with self.p.lock:
                d['cd'] = cd
                self.p.dirty = True

    def cooldown_step(self, now):
        """Cooldowns end also while the P.E.T. is in the hangar or destroyed (after a kamikaze it is always destroyed: the ready message and the
        gear's state never came until it was repaired and launched)."""
        msgs = []
        self.save_cooldowns(now)
        if self.release_wait and now >= self.release_ready:
            self.release_wait = False
            msgs += [legacy('0|A|STM|msg_pet_heat-release-gear_cooldown_ready'),
                     ('PetGearActivationChangeCommand', dict(gearType=gear_type(HEAT_RELEASE), active=True))]
        for t in [t for t, r in self.ready.items() if now >= r]:          # cooldown over: the gear can be selected again
            del self.ready[t]
            msgs += [legacy('0|A|STM|msg_pet_%s-gear_cooldown_ready' % READY_NAMES[t]),
                     ('PetGearActivationChangeCommand', dict(gearType=gear_type(t), active=True))]
        msgs += self.buff_msgs(now)
        if msgs:
            self.send(msgs)

    def locator_msgs(self, changed=False):
        """Target lists of the equipped locator gears (PetLocatorGearInitializationCommand; the client replaces the list:
        PetUIInfo.AssembleGearTargetsList). changed: only those that differ from the last sent (gate waves, spawning/ending types)."""
        msgs = []
        for t in (ENEMY_LOCATOR, RESOURCE_LOCATOR):
            if t not in self.installed_gears():
                continue
            values = self.targets(t)
            if changed and values == self.targets_sent.get(t):
                continue
            self.targets_sent[t] = values
            msgs.append(('PetLocatorGearInitializationCommand', dict(locatorType=gear_type(t), possibleTargetValues=values)))
        return msgs

    def select_msg(self):
        t = self.d.get('gear', GUARD)
        opt = [self.locate[t]] if t in self.locate else []
        return ('PetGearSelectCommand', dict(gearType=gear_type(t), optionalParams=opt))

    def hp_msg(self):
        return ('PetHitpointsUpdateCommand', dict(hitpointsNow=int(self.d['hp']), hitpointsMax=self.hp_max(),
                                                  useRepairGear=self.d.get('gear') == REPAIR_PET))

    def shield_msg(self):
        return ('PetShieldUpdateCommand', dict(petShieldNow=int(self.d['shield']), petShieldMax=self.shield_max()))

    def fuel_msg(self):
        return ('PetFuelUpdateCommand', dict(petFuelNow=int(self.d['fuel']), petFuelMax=PET['max_fuel']))

    def repair_button(self):
        return ('PetUIRepairButtonCommand', dict(enabled=self.owned and self.d['destroyed'], repairCosts=self.repair_cost()))

    def rename_price(self):
        return SET.price('service_price', PET['rename_uridium'], 'pet')            # panel: service fees

    def repair_cost(self):
        if not self.owned or self.p.premium:                       # Premium: "Free P.E.T. repairs" (the client's notice)
            return 0
        return SET.price('service_price', self.row()['repair_uridium'], 'pet')                           # panel: service fees

    def login_msgs(self):
        """After the map has loaded: the repair button if destroyed; if the map changed the active P.E.T. launches again."""
        if not self.owned:
            return []
        msgs = [self.repair_button()] if self.d['destroyed'] else []
        return msgs + [self.heat_msg()]                  # the P.E.T. window's HEAT gauge (even when inactive)

    # ------------------------------------------------------------ hangar
    def view(self):
        """HangarShipsCommand.petView (the client fills the P.E.T. panel if rootId is non-empty)."""
        base = dict(petHeatSlotPrice=0, maxGearSlots=0, petGearsSlotPrice=0, rootId='', petProtocolsSlotPrice=0, maxFuel=0, maxLaserSlots=0,
                    petRenamePrice=0, maxHeatSlots=0, expNextLevel=0, shieldGenerators=0, fuel=0, hitPoints=0, petGeneratorsSlotPrice=0,
                    petLasersSlotPrice=0, exp=0, maxHitPoints=0, damageDistribution=0, level=0, maxDamageDistribution=0, maxProtocolSlots=0,
                    lasers=0, maxGeneratorSlots=0, name='', maxLasers=0)
        if not self.owned:
            return dict(base, _='HangarShipPetView')       # the field name 'name': collides with mod()
        d, lo = self.d, self.loadout()
        base.update(rootId=PET['loot'], name=d['name'], level=d['level'], exp=d['ep'], expNextLevel=self.next_xp(), hitPoints=int(d['hp']),
                    maxHitPoints=self.hp_max(), fuel=int(d['fuel']), maxFuel=PET['max_fuel'], lasers=len(lo['lasers']),
                    maxLasers=self.open_slots('lasers'), shieldGenerators=len(lo['generators']),
                    maxLaserSlots=self.open_slots('lasers'), maxGeneratorSlots=self.open_slots('generators'),
                    maxGearSlots=self.open_slots('gears'), maxProtocolSlots=self.open_slots('protocols'),
                    petLasersSlotPrice=self.slot_price('lasers'), petGeneratorsSlotPrice=self.slot_price('generators'),
                    petGearsSlotPrice=self.slot_price('gears'), petProtocolsSlotPrice=self.slot_price('protocols'),
                    maxHeatSlots=self.open_slots('heat'), petHeatSlotPrice=self.slot_price('heat'), petRenamePrice=self.rename_price())
        return dict(base, _='HangarShipPetView')       # the field name 'name': collides with mod()

    def config_msgs(self, cur, sid=None):
        """HangarShipEquipmentCommand.petConfigs: a ship's equipped item ids per config."""
        if not self.owned:
            return []
        out = []
        for cid in ('1', '2'):
            c = self.config(cid, sid)
            out.append(mod('HangarPetEquipmentMsg', setId=int(cid), active=int(cid) == int(cur), laser=list(c['lasers']),
                           generator=list(c['generators']), gear=list(c['gears']), protocol=list(c['protocols']), heat=list(c['heat']),
                           visual=list(c['visual'])))
        return out

    def unlock(self, f):
        """HangarShipUnlockSlotRequest {slotset}: one more slot with uridium (wiki price, by slot number)."""
        slot = (f.get('slotset') or '').lower()
        reply = lambda res, err=None: ('HangarShipUnlockSlotCommand', dict(
            nextGearsSlotUridium=self.slot_price('gears') if self.owned else 0, nextLasersSlotUridium=self.slot_price('lasers') if self.owned else 0,
            errorMessage=err, nextGeneratorSlotUridium=self.slot_price('generators') if self.owned else 0,
            nextProtocolsSlotUridium=self.slot_price('protocols') if self.owned else 0,
            nextHeatSlotUridium=self.slot_price('heat') if self.owned else 0, resultId=res))
        if not self.owned or slot not in PET['slot_prices']:
            self.log('   P.E.T. slot not unlocked: %r' % slot)
            return [reply(0)]
        price = self.slot_price(slot)
        u = self.p.d['pilot'].get('uridium', 0)
        if not price or u < price:
            self.log('   P.E.T. slot not unlocked: %s (price %d, uridium %d)' % (slot, price, u))
            return [reply(0)]
        with self.p.lock:
            self.p.d['pilot']['uridium'] = u - price
            self.d['slot'][slot] = self.open_slots(slot) + 1
            self.p.dirty = True
        RT.money(self.p, 'uridium', -price, 'buy_SPECIAL')
        self.log('   P.E.T. slot unlocked: %s %d (%d U)' % (slot, self.open_slots(slot), price))
        return [reply(1)]

    def rename(self, f):
        """HangarShipRenamePetRequest: 1-24 letters or digits (the client's error_pet_name_length / error_pet_name_char texts); each
        rename costs rename_price() uridium (real recording: petView.petRenamePrice 3,000)."""
        from shop import stack_msg
        name = (f.get('name') or '').strip()
        price = self.rename_price()
        err = (None if not self.owned else 'error_pet_name_length' if not 1 <= len(name) <= 24 else
               'error_pet_name_char' if not name.isalnum() else
               'not_enough_uridium' if self.p.d['pilot'].get('uridium', 0) < price else None)
        ok = self.owned and not err
        if ok:
            with self.p.lock:
                self.p.d['pilot']['uridium'] -= price
                self.d['name'] = name
                self.p.dirty = True
            RT.money(self.p, 'uridium', -price, 'buy_SPECIAL')
            self.log('   P.E.T. name: %s (%d U)' % (name, price))
        elif err:
            self.log('   P.E.T. rename failed: %r (%s)' % (name, err))
        msgs = [('HangarShipRenamePetCommand', dict(errorMessage=stack_msg(err) if err else None, resultId=1 if ok else 0,
                                                    newName=name if ok else ''))]
        if ok and self.active:
            msgs.append(self.status_msg())
        return msgs

    # ------------------------------------------------------------ requests
    def request(self, f):
        """PetRequest: launch/stop/shortcuts/repair/fuel."""
        kind = f.get('petRequestType')
        if not self.owned:
            return
        lock = self.w.lock if self.w else _NoLock()
        with lock:
            if kind == LAUNCH or (kind == TOGGLE and not self.active):
                # in the real game a P.E.T. the player launches always comes out in passive mode: E (report 2026-10-27) and the window's Launch
                # button (report 2026-10-28: it came out in guard mode). Relaunching on a map change (launch) keeps the gear
                if not self.active:
                    self.d['gear'] = PASSIVE
                self.launch()
                if self.active:
                    self.send([legacy('0|A|STM|msg_pet_activated')])     # at the player's request (not on a map change)
            elif (kind == DEACTIVATE or kind == TOGGLE) and self.in_fight():
                self.send([legacy('0|A|STM|msg_pet_in_combat')])     # forum 127074: cannot be turned off in combat (possible when passive and undamaged)
            elif kind == DEACTIVATE or kind == TOGGLE:
                self.deactivate(msg='msg_pet_deactivated')
            elif kind == HOTKEY_GUARD:
                self.launch_into(COMBO_GUARD if COMBO_GUARD in self.installed_gears() else GUARD)
            elif kind == HOTKEY_REPAIR_SHIP:
                self.launch_into(COMBO_REPAIR if COMBO_REPAIR in self.installed_gears() else REPAIR_PET)
            elif kind == REPAIR_DESTROYED:
                self.repair()
            elif kind == HOTKEY_BUY_FUEL:
                self.buy_fuel()
            else:
                self.log('   P.E.T. request unknown: %s' % kind)

    def gear_request(self, f):
        t = (f.get('gearTypeToActivate') or {}).get('typeValue')
        lock = self.w.lock if self.w else _NoLock()
        with lock:
            self.launch_into(t, f.get('optParam') or 0)

    def launch_into(self, t, opt=0):
        """Gear shortcut (R, D, gear keys): if the P.E.T. is off it launches with that gear (player report 2026-10-27: in the real game R
        starts an off P.E.T. in guard mode; here nothing happened)."""
        if not self.active and t in {g for g, lv, usable in self.gear_list() if usable}:
            self.launch()
            if not self.active:
                return
        self.select(t, opt)

    def hidden(self, now):
        """While the owner is cloaked the P.E.T. is hidden too; visible while firing (last 3 s) (official forum 127074)."""
        w = self.w
        if not w:
            return False
        cloaked = (w.items.cloaked() if getattr(w, 'items', None) else False) or \
            (w.abilities.cloaked(now) if getattr(w, 'abilities', None) else False)
        return bool(cloaked) and now - self.last_fight >= 3

    def view_msgs(self, now):
        """This P.E.T. on the other player's client (shared map; recording: another player's P.E.T. PetActivationCommand, petDesignId
        game.xml type) and its ongoing movement."""
        pl, (x, y), m = self.p.d['pilot'], self.pos(now), self.mover
        msgs = [('PetActivationCommand', dict(
            ownerId=self.p.user_id, petId=self.pid, petDesignId=self.look, expansionStage=1, petName=self.d['name'],
            petFactionId=pl.get('factionId', 1), petClanID=pl.get('clanId', 0), petLevel=self.d['level'], clanTag=pl.get('clanTag', ''),
            clanRelationship=mod('ClanRelationModule', type=0), x=int(x), y=int(y), petSpeed=self.speed(), isInIdleMode=False,
            isVisible=not self.hidden(now), minimapStrategyModule=mod('MinimapStrategyModule', minimapStrategy=0)))]
        if m.t1 > now:
            msgs.append(('MoveCommand', dict(userId=self.pid, x=int(m.x1), y=int(m.y1), timeToTarget=m.ms_left(now))))
        return msgs

    def launch(self):
        w = self.w
        if self.active or not w or w.hero_dead or (self.trade_wait and time.time() < self.trade_ready):
            return
        if self.d['destroyed']:
            self.send([self.repair_button(), legacy('0|A|STM|msg_pet_is_dead')])
            return
        if self.d['fuel'] <= 0:
            self.send([legacy('0|A|STM|msg_pet_no_fuel_to_launch'), self.init_msg()])
            return
        now = time.time()
        hx, hy = w.hero_pos(now)
        a = random.uniform(0, 2 * math.pi)
        x, y = hx + math.cos(a) * PET['follow_distance'], hy + math.sin(a) * PET['follow_distance']
        from world import Mover
        self.mover = Mover(int(x), int(y))
        self.cool(now)                           # cooling for the time spent away; it does not cool in space
        self.release_end = self.link_end = 0.0
        self.beacon, self.in_beacon = None, False
        self.active, self.task, self.shooting = True, None, None
        self.cloak_sent = False                  # the new unit is visible on the owner's client (tick sends the cloak)
        self.tick_t = self.next_second = now
        with self.p.lock:
            self.d['hp'] = min(self.d['hp'], self.hp_max())
            self.d['shield'] = min(self.d['shield'], self.shield_max())
            self.p.dirty = True
        if self.d.get('gear') not in {t for t, lv, ok in self.gear_list() if ok} or self.d.get('gear') in (TRADE_POD, HEAT_RELEASE, HP_LINK):
            self.d['gear'] = PASSIVE
        self.trading = False
        self.fuel_sent = int(self.d['fuel'])
        self.heat_sent = int(self.d.get('heat', 0))
        self.send([self.activation_msg(x, y), self.status_msg()] + self.gear_msgs() + [self.heat_msg(now)] + self.stats_msgs())
        self.log('   P.E.T. launched: level %d, HP %d/%d, shield %d, fuel %d, %d lasers, gear %d' % (
            self.d['level'], self.d['hp'], self.hp_max(), self.d['shield'], self.d['fuel'], len(self.lasers()), self.d['gear']))

    def disrupt(self, now, sec=5):
        """EMP: the P.E.T. is out of action for sn seconds (log_msg_pet_disruption_on/off), then launches again by itself (the duration is an adaptation)."""
        self.deactivate(msg='log_msg_pet_disruption_on')
        w = self.w

        def back():
            if self.w is w and not self.active and self.owned and self.d['fuel'] > 0:
                self.launch()
                self.send([legacy('0|A|STM|log_msg_pet_disruption_off')])
        if w:
            w.later(sec, back)

    def deactivate(self, notify=True, msg=None):
        if not self.active:
            return
        now = time.time()
        if self.release_end:
            self.end_release(now, notify=False)
        if self.link_end:
            self.end_link(now, notify=False)
        self.beacon_gone()
        self.beacon, self.in_beacon = None, False
        self.active, self.task, self.trading = False, None, False
        self.charge_end = 0.0
        self.stop_heat(now)                      # the cooling delay starts
        msgs = self.abort_msgs() if self.shooting else []
        self.shooting = None
        if notify:
            # client: PetDeactivationCommand only hides the unit; the window looks "active" while the P.E.T. unit exists (UIPetSystem.RefPet).
            # The unit is removed with ShipRemoveCommand; then PetInitializationCommand refreshes the window (launch button; live test).
            msgs += [('PetDeactivationCommand', {'petId': self.pid}), ('ShipRemoveCommand', {'userId': self.pid}), self.init_msg()]
            if msg:
                msgs.append(legacy('0|A|STM|%s' % msg))
        self.send(msgs + [self.heat_msg(now)] + self.stats_msgs())       # the HEAT bonus leaves the ship
        self.log('   P.E.T. stopped%s' % (' (%s)' % msg if msg else ''))

    def select(self, t, opt=0):
        if not self.owned:
            return
        ok = {g for g, lv, usable in self.gear_list() if usable}
        if t not in ok:
            self.log('   P.E.T. gear missing/unusable: %s' % t)
            self.send([self.select_msg()])
            return
        now = time.time()
        if self.trading and t != TRADE_POD:
            self.trade_close(now)                # choosing another module ends the trade too (player verification, original game)
            return
        if self.trade_wait and now < self.trade_ready:
            self.log('   P.E.T. locked: trade cooldown (%d s)' % (self.trade_ready - now))
            self.send([self.select_msg()])
            return
        if t == TRADE_POD and self.d['fuel'] < self.trade_fuel():      # the sale's fuel cost is not covered: the window does not open
            self.log('   cargo trader could not be selected: not enough fuel (%d < %d)' % (self.d['fuel'], self.trade_fuel()))
            self.send([self.select_msg(), legacy('0|A|STM|msg_pet_no_fuel_to_activate')])
            return
        if t == KAMIKAZE and (now < self.ready.get(KAMIKAZE, 0) or self.start_map()):
            self.log('   Kamikaze could not be selected (%s)' % ('starting map' if self.start_map() else 'beklemede'))
            self.send([self.select_msg()] + ([legacy('0|A|STM|msg_pet_kamikaze-gear_not_on_start_maps')] if self.start_map() else []))
            return
        if t in TIMED:
            if not (self.active and self.w) or (t == HP_LINK and self.link_end):
                self.send([self.select_msg()])   # the P.E.T. is not in space or already linked
                return
            if now < self.ready.get(t, 0):
                self.log('   %s on cooldown (%d s)' % (TIMED[t], self.ready[t] - now))
                self.send([self.select_msg()] + ([legacy('0|A|STM|msg_pet_%s-gear_cooldown_not_ready' % TIMED[t])]
                                                 if t in BEACONS or t == MEGA_MINE else []))
                return
            if t in BEACONS:
                return self.drop_beacon(t, now)   # single use: the selected gear does not change
            if t == MEGA_MINE:
                return self.drop_mine(now)
        if t == FRIENDLY_SACRIFICE and now < self.ready.get(FRIENDLY_SACRIFICE, 0):
            self.send([self.select_msg(), legacy('0|A|STM|msg_pet_friendly_sacrifice-gear_cooldown_not_ready')])
            return
        if t == HEAT_RELEASE:
            if self.release_end or not (self.active and self.w):
                self.send([self.select_msg()])   # already running or the P.E.T. is not in space
                return
            why = ('msg_pet_heat-release-gear_cooldown_not_ready' if now < self.release_ready else
                   'msg_pet_heat-release-gear_no_heat' if self.heat() <= 0 else None)
            if why:
                self.log('   Heat Release could not be selected: %s' % why)
                self.send([self.select_msg(), legacy('0|A|STM|%s' % why)])
                return
        elif self.release_end:
            self.end_release(now)                # another gear selected: Heat Release ends early
        if self.link_end:
            self.end_link(now)                   # another gear selected: HP Link ends early
        old = self.d.get('gear')
        with self.p.lock:
            self.d['gear'] = t
            self.p.dirty = True
        if t in (ENEMY_LOCATOR, RESOURCE_LOCATOR) and opt:
            self.locate[t] = int(opt)
        self.task = None if t not in (AUTO_LOOT, AUTO_RESOURCE) else self.task
        msgs = [self.select_msg()]
        if self.shooting and t not in FIGHTING:
            msgs += self.abort_msgs()
            self.shooting = None
        self.trading = t == TRADE_POD
        if self.trading:
            self.trade_paid = False
            msgs.append(('PetTradeWindowShowCommand', {}))
            if self.active and self.w:                   # the 1.1.115 client does not listen to the PetTradeWindowShow event: the window is opened only by
                msgs.append(self.w.trade_info())         # OreTradeInfoCommand (TradeType.PET) (report 2026-10-26)
        if t == REPAIR_PET or old == REPAIR_PET:
            msgs.append(self.hp_msg())
        if t == HEAT_RELEASE:
            self.release_end = now + self.gear(HEAT_RELEASE).get('duration_sec', 4)
            msgs.append(self.release_visual(True))
        if t == HP_LINK:
            self.link_end = now + self.gear(HP_LINK).get('duration_sec', 20)
            msgs.append(self.link_visual(True))
        # the client's texts: "Guard mode activated", "P.E.T. repairs the ship now.", the combat gear without lasers
        msgs += [legacy('0|A|STM|%s' % k) for k in (
            'msg_pet_guard_mode_activated' if t == GUARD else 'msg_pet_ship_repair_gear_activated' if t == COMBO_REPAIR else None,
            'msg_pet_no_laser_equipped' if t in FIGHTING and not self.lasers() else None) if k]
        self.send(msgs)
        self.log('   P.E.T. gear: %s%s' % (t, ' target %s' % opt if opt else ''))

    def release_visual(self, on):
        return ('VisualModifierCommand', dict(userId=self.pid, modifier=VM_HEAT_RELEASE, attribute=0, additionalAttribute='', count=0,
                                              activated=on))

    def release_step(self, now):
        """Heat Release second: HEAT drops (no cooling delay), P.E.T. HP is spent, aliens in range take damage."""
        g, w, d = self.gear(HEAT_RELEASE), self.w, self.d
        if now >= self.release_end:
            return self.end_release(now, notify=False)                  # time is up (4 s: 4 hits)
        changed = self.add_heat(-g.get('heat_sec', 0))
        with self.p.lock:
            d['hp'] = min(self.hp_max(), max(1, d['hp'] - g.get('hp_sec', 0)))      # the gear does not destroy the P.E.T. (adaptation); HEAT
            self.p.dirty = True                                                    # drops so the maximum HP does too
        px, py = self.pos(now)
        hit = [n for n in list(w.npcs.values()) if n.alive and math.hypot(n.mover.pos(now)[0] - px, n.mover.pos(now)[1] - py) <= g.get('range', 0)]
        for n in hit:
            w.hit_npc(n.id, int(g.get('damage_per_sec', 0)), 1, attacker=self.pid)
        if hit:
            self.last_fight = now
        msgs = [self.hp_msg(), self.heat_msg(now)] + (self.stats_msgs() if changed else [])
        if d.get('heat', 0) <= 0 or d['hp'] <= g.get('hp_sec', 0):
            msgs += self.end_release(now, notify=False)                 # HEAT ended or HP is not enough
        return msgs

    def end_release(self, now, notify=True):
        """Heat Release ended: the visual closes, the cooldown starts, the P.E.T. returns to guard."""
        self.release_end = 0.0
        self.release_ready = now + self.gear(HEAT_RELEASE).get('cooldown_sec', 60)
        self.release_wait = True
        with self.p.lock:
            self.d['gear'] = GUARD
            self.p.dirty = True
        # in the P.E.T. window the gear is gray during the cooldown (Ö1; the client processes it only while the window is open: PetGearActivationChangeCommand)
        msgs = [self.release_visual(False), self.select_msg(),
                ('PetGearActivationChangeCommand', dict(gearType=gear_type(HEAT_RELEASE), active=False))]
        if notify:
            self.send(msgs)
        return msgs

    # ------------------------------------------------------------ G-HPL1, G-BC1, G-BH1
    def link_visual(self, on):
        """HP Link visual: the client's VisualModifier HP_LINK, above the P.E.T., attribute linked ship (unverified)."""
        return ('VisualModifierCommand', dict(userId=self.pid, modifier=VM_HP_LINK, attribute=self.w.hid if self.w else 0,
                                              additionalAttribute='', count=0, activated=on))

    def link_take(self, dmg):
        """G-HPL1: while linked, hull damage coming to the ship is deducted from the P.E.T.'s HP -> the transferred damage. If its HP runs out
        the P.E.T. is destroyed."""
        if not (self.link_end and self.active) or dmg <= 0:
            return 0
        d = self.d
        taken = min(dmg, d['hp'])
        with self.p.lock:
            d['hp'] -= taken
            self.p.dirty = True
        if d['hp'] <= 0:
            self.destroyed(DESTROYED_NONE)
        else:
            self.send([self.hp_msg()])
        return taken

    def end_link(self, now, notify=True):
        """HP Link ended: the visual closes, the cooldown starts, the P.E.T. returns to guard."""
        self.link_end = 0.0
        self.ready[HP_LINK] = now + self.gear(HP_LINK).get('cooldown_sec', 240)
        with self.p.lock:
            self.d['gear'] = GUARD
            self.p.dirty = True
        msgs = [self.link_visual(False), self.select_msg(),
                ('PetGearActivationChangeCommand', dict(gearType=gear_type(HP_LINK), active=False))]
        if notify:
            self.send(msgs)
        return msgs

    def drop_beacon(self, t, now):
        """G-BC1/G-BH1: the P.E.T. leaves a marker where it is (a bonus to the ship in range); the selected gear does not change, the cooldown starts."""
        g = self.gear(t)
        x, y = self.pos(now)
        self.beacon_gone()
        self.beacon, self.in_beacon = (t, x, y, now + g.get('duration_sec', 30)), False
        self.ready[t] = now + g.get('cooldown_sec', 240)
        MINE_UID[0] += 1
        self.beacon_uid = (MINE_UID[0], BEACON_ASSET[t])
        tower = ('AssetCreateCommand', dict(designId=0, clanId=0, showBubble=False, userName='', assetId=MINE_UID[0], expansionStage=0,
                                            modifier=[], type=mod('AssetTypeModule', typeValue=BEACON_ASSET[t]), detectedByWarnRadar=False,
                                            invisible=False, posX=int(x), posY=int(y), clanRelation=mod('ClanRelationModule', type=0),
                                            clanTag='', factionId=self.p.d['pilot'].get('factionId', 0), visibleOnWarnRadar=False))
        self.send([self.select_msg(), ('PetGearActivationChangeCommand', dict(gearType=gear_type(t), active=False)), tower]
                  + self.beacon_step(now))
        self.log('   P.E.T. marker: %s (%d, %d)' % (TIMED[t], x, y))

    # ------------------------------------------------------------ G-MM1, G-FS1
    def drop_mine(self, now):
        """G-MM1 (wiki p-e-t): the P.E.T. leaves a mine where it is; it goes off after arm_sec and hits every player not in the group
        (bot ships, enemy players on a shared map; not aliens) with 'pulses' blasts of 'damage' within 'duration_sec'. Single use: the selected
        gear does not change, the cooldown starts (PetBuffCommand 10)."""
        g = self.gear(MEGA_MINE)
        x, y = self.pos(now)
        MINE_UID[0] += 1
        n = max(1, int(g.get('pulses', 5)))
        gap = max(0.0, (g.get('duration_sec', 6) - g.get('arm_sec', 2)) / max(1, n - 1))
        self.mine = dict(uid=MINE_UID[0], x=x, y=y, next=now + g.get('arm_sec', 2), left=n, gap=gap)
        self.ready[MEGA_MINE] = now + g.get('cooldown_sec', 240)
        self.send([self.select_msg(), ('PetGearActivationChangeCommand', dict(gearType=gear_type(MEGA_MINE), active=False)),
                   ('AddMineCommand', dict(hash='pmm%d' % self.mine['uid'], x=int(x), y=int(y), typeId=MEGA_MINE_TYPE,
                                           maxSkill1=False, maxSkill5b=False))])
        self.log('   P.E.T. Mega Mine (%d, %d)' % (x, y))

    def mine_targets(self, now, x, y, reach):
        """Players the mine may hit: bot ships and players on the shared map, within reach, by the attack rules (group, clan, safe zone)."""
        w = self.w
        import player_combat as PVP
        import bot.ship as BG
        bots = [n for n in list(w.npcs.values()) if n.alive and n.bot is not None and not w.is_group_member(n.bot.uid)
                and math.hypot(n.mover.pos(now)[0] - x, n.mover.pos(now)[1] - y) <= reach and not BG.attack_error(w, n, now)]
        players = [o for o in (list(w.shared.members) if w.shared is not None else [])
                   if o is not w and o.running and not o.hero_dead and o.map_id == w.map_id
                   and math.hypot(o.hero_pos(now)[0] - x, o.hero_pos(now)[1] - y) <= reach and not PVP.attack_error(w, o, now)]
        return bots, players

    def mine_step(self, now):
        m, g, w = self.mine, self.gear(MEGA_MINE) or self.gear_data(MEGA_MINE), self.w
        bots, players = self.mine_targets(now, m['x'], m['y'], g.get('range', 0))
        dmg = int(g.get('damage', 0))
        msgs = []
        for n in bots:
            w.hit_npc(n.id, dmg, 0, attacker=self.pid)
            msgs.append(legacy('0|n|PMME|%d' % n.id))            # the ring on the unit hit (MapEventsAssemblyHelper.AssemblePetMegaMineExploded)
        if players:
            import player_combat as PVP
            for o in players:
                PVP._hit(w, o, now, dmg, atype=0)
                msgs.append(legacy('0|n|PMME|%d' % o.hid))
        m['left'] -= 1
        m['next'] = now + m['gap']
        if m['left'] <= 0:
            msgs.append(('RemoveMineCommand', {'hash': 'pmm%d' % m['uid']}))
            self.mine = None
        return msgs

    def gear_data(self, t):
        """The gear's data at level 1 (the mine keeps going after the gear was unequipped)."""
        loot = next((l for l, g in GEARS.items() if g.get('type') == t), None)
        return at_level(GEARS.get(loot, {}), 1) if loot else {}

    def sacrifice(self, now):
        """G-FS1 (wiki p-e-t): passive; when a friendly ship (same clan and/or group: player or bot) in range has its shield below the
        threshold, the P.E.T. flies to it and explodes: the ship gets 'transfer' of the P.E.T.'s maximum shield (fandom Sacrificial Flame:
        "based on your P.E.T.'s maximum"), the P.E.T. is destroyed and the cooldown starts (PetBuffCommand 7). -> True if it went off."""
        g, w = self.gear(FRIENDLY_SACRIFICE), self.w
        px, py = self.pos(now)
        reach, low = g.get('range', 0), g.get('threshold', 0.5)
        clan = int(self.p.d['pilot'].get('clanId') or 0)
        mates = [(o, o.p.d['ship']) for o in (list(w.shared.members) if w.shared is not None else [])
                 if o is not w and o.running and not o.hero_dead and o.map_id == w.map_id
                 and (w.is_group_member(o.hid) or (clan and clan == int(o.p.d['pilot'].get('clanId') or 0)))
                 and math.hypot(o.hero_pos(now)[0] - px, o.hero_pos(now)[1] - py) <= reach]
        target = next(((o, s) for o, s in mates if s.get('shieldMax', 0) and s.get('shield', 0) < s['shieldMax'] * low), None)

        def friend_bot(n):
            if w.is_group_member(n.bot.uid):
                return True
            import bot.society as T
            return bool(clan) and clan == int(T.profile(n.bot).d['pilot'].get('clanId') or 0)
        bot = None if target else next((n for n in list(w.npcs.values()) if n.alive and n.bot is not None and friend_bot(n)
                                        and n.d.get('shield', 0) and n.shield < n.d['shield'] * low
                                        and math.hypot(n.mover.pos(now)[0] - px, n.mover.pos(now)[1] - py) <= reach), None)
        if not target and not bot:
            return False
        give = int(self.shield_max() * g.get('transfer', 0.3))
        tid = target[0].hid if target else bot.id
        self.send([('PlayVisualEffectCommand', dict(targetIds=[tid], activatorId=self.pid, visualEffect=SACRIFICE_EFFECT))])
        if target:
            o, s = target
            o.p.set_hull(shield=s.get('shield', 0) + give)
            o.send([('AttributeShieldUpdateCommand', {'shieldNow': int(s['shield']), 'shieldMax': s.get('shieldMax', 0)})])
        else:
            bot.shield = min(bot.d['shield'], bot.shield + give)
        self.ready[FRIENDLY_SACRIFICE] = now + g.get('cooldown_sec', 90)
        with self.p.lock:
            self.d['gear'] = GUARD
            self.p.dirty = True
        self.destroyed(DESTROYED_NONE)
        self.send([('PetGearActivationChangeCommand', dict(gearType=gear_type(FRIENDLY_SACRIFICE), active=False))])
        self.log('   P.E.T. Sacrificial Flame: +%d shield to %s' % (give, tid))
        return True

    def beacon_gone(self):
        """The marker's tower leaves the map (its time is up, the P.E.T. was called back or a new marker was laid)."""
        if self.beacon_uid:
            uid, kind = self.beacon_uid
            self.beacon_uid = None
            self.send([('AssetRemoveCommand', {'assetType': mod('AssetTypeModule', typeValue=kind), 'uid': uid})])

    def beacon_step(self, now):
        """The marker's duration and whether the ship is in range: ship values again when it changes."""
        inside = False
        if self.beacon:
            t, x, y, end = self.beacon
            if now >= end:
                self.beacon = None
                self.beacon_gone()
            else:
                hx, hy = self.w.hero_pos(now)
                inside = math.hypot(hx - x, hy - y) <= self.gear(t).get('range', 0)
        if inside == self.in_beacon:
            return []
        self.in_beacon = inside
        return self.stats_msgs()

    def repair(self):
        """Repair a destroyed P.E.T.: uridium by level (wiki: levels 0-2 free). It returns with repair_hp of its maximum HP: when it returned with full
        HP, Kamikaze (explodes when HP is below the threshold) could not be used after every repair (user report 2026-10-24)."""
        if not self.d['destroyed']:
            return
        cost = self.repair_cost()
        pl = self.p.d['pilot']
        if pl.get('uridium', 0) < cost:
            self.send([legacy('0|A|STM|not_enough_uridium'), self.repair_button()])
            return
        with self.p.lock:
            pl['uridium'] = pl.get('uridium', 0) - cost
            self.d.update(destroyed=False, hp=max(1, int(self.hp_max() * PET['repair_hp'])), shield=self.shield_max())
            self.p.dirty = True
        RT.money(self.p, 'uridium', -cost, 'repair_pet')
        msgs = [('PetRepairCompleteCommand', {}), self.init_msg(), self.repair_button()]
        if cost and self.w and self.w.money_msgs:
            msgs += self.w.money_msgs()
        self.send(msgs)
        self.log('   P.E.T. repaired (%d U)' % cost)

    def buy_fuel(self, amount=None):
        """Shortcut: 1,000 units of fuel, with uridium (real recording: 250 U, does not touch credits; client texts log_msg_bought_fuel_hotkey*).
        The P.E.T. must be active. amount: the auto-buy CPU's (FB-X: 10,000; the price in the same proportion)."""
        f = dict(PET['fuel_buy'])
        if amount:
            f.update(uridium=f['uridium'] * amount // f['count'], count=amount)
        f['uridium'] = SET.price('service_price', f['uridium'], 'pet')     # panel: service fees
        pl = self.p.d['pilot']
        if not self.active:
            self.send([legacy('0|A|STM|log_msg_bought_fuel_hotkey_inactive')])
        elif self.d['fuel'] + f['count'] > PET['max_fuel']:
            self.send([legacy('0|A|STM|log_msg_bought_fuel_hotkey_full')])
        elif pl.get('uridium', 0) < f['uridium']:
            self.send([legacy('0|A|STM|not_enough_uridium')])
        else:
            with self.p.lock:
                pl['uridium'] -= f['uridium']
                self.d['fuel'] += f['count']
                self.p.dirty = True
            RT.money(self.p, 'uridium', -f['uridium'], 'buy_PETFUEL', qty=f['count'])
            msgs = [self.fuel_msg(), legacy('0|A|STM|log_msg_bought_fuel_hotkey')]
            if self.w and self.w.money_msgs:
                msgs += self.w.money_msgs()
            self.send(msgs)
            self.log('   P.E.T. fuel bought: +%d (%d U)' % (f['count'], f['uridium']))

    # ------------------------------------------------------------ space
    def attach(self, world):
        """New map world: the active P.E.T. launches again after the ready bundle (in the real game it passes through the portal together)."""
        was = self.active
        if was:
            self.stop_heat(time.time())          # it does not cool during the transition (the delay lasts until it relaunches)
            self.release_end = 0.0
        self.w, self.active, self.task, self.shooting = world, False, None, None
        self.charge_end = 0.0
        self.relaunch = self.relaunch or was

    def on_ready(self):
        """Map loaded (ReadyRequest): if it was active on the previous map it launches again."""
        if self.trade_wait and self.w:
            self.send(self.trade_block_msgs(time.time()))          # map changed: the client asks again for the lock and the icon
        self.buffs_sent = {}                                        # the cooldown buffs again with the next tick (new map, login)
        if self.relaunch and self.w:
            self.relaunch = False
            with self.w.lock:
                self.launch()

    def reload(self):
        """Ship reloaded (repair, ship change): the client clears the map; launches again when ready."""
        if self.active:
            self.stop_heat(time.time())
            self.release_end = 0.0
            self.active, self.task, self.shooting = False, None, None     # the client clears the map
            self.relaunch = True

    def pos(self, now):
        return self.mover.pos(now)

    def move(self, x, y, speed, now):
        ms = self.mover.go(x, y, speed, now)
        self.w.send([('MoveCommand', dict(userId=self.pid, x=int(x), y=int(y), timeToTarget=ms))])

    def tick(self, now):
        """From the world loop (under the lock): follow, collect, fire, fuel, repair, locator."""
        if self.trade_wait and self.w and now >= self.trade_ready:
            self.trade_unblock()
        if self.w:
            self.cooldown_step(now)
            if self.mine and now >= self.mine['next']:
                self.send(self.mine_step(now))
        if not self.active or not self.alive or not self.w:
            return
        w = self.w
        hidden = self.hidden(now)
        if hidden != getattr(self, 'cloak_sent', False):
            # the owner's own client too: before only the other players' view hid it, the owner saw it while cloaked (user report 2026-11-07;
            # fandom Extra: the cloak hides "your ship (including any drones or P.E.T.)"); the client takes 0|n|INV for the P.E.T. unit too
            self.cloak_sent = hidden
            self.send([legacy('0|n|INV|%d|%d' % (self.pid, 1 if hidden else 0))])
        if self.d['fuel'] <= 0:
            self.deactivate(msg='msg_pet_out_of_fuel')
            return
        dt, self.tick_t = now - self.tick_t, now
        if w.hero_dead or w.jumping:
            return
        self.fuel_clock += self.fuel_per_min() * dt / 60.0
        if self.fuel_clock >= 1:
            used = int(self.fuel_clock)
            self.fuel_clock -= used
            before = self.d['fuel']
            with self.p.lock:
                self.d['fuel'] = max(0, before - used)
                self.p.dirty = True
            if 0 < self.d['fuel'] <= PET['max_fuel'] * FUEL_WARN < before:
                self.send([legacy('0|A|STM|msg_pet_running_out_of_fuel')])
            if self.d['fuel'] <= 0:
                self.send([self.fuel_msg(), ('PetOutOfFuelCommand', {}), self.init_msg()])
                self.deactivate(msg='msg_pet_out_of_fuel')
                return
        if self.charge_end:                      # G-KK1 on its way: no following, no fighting
            if now >= self.charge_end and not self.recharge(now):
                self.kamikaze(now)
            return
        if now >= self.next_second:
            self.next_second = now + 1.0
            self.each_second(now)
        if not self.active:
            return
        g = self.d.get('gear')
        if g in (AUTO_LOOT, AUTO_RESOURCE) and self.collect_step(now, g):
            return
        if g in FIGHTING:
            if self.fight(now):
                return                   # fighting next to the target
        elif self.shooting:
            self.stop_shooting()
        self.follow(now)

    def each_second(self, now):
        self.cooldown_step(now)                  # (tick runs it too, also while inactive; repeating it is harmless)
        w, d, msgs = self.w, self.d, []
        if self.release_end:
            msgs += self.release_step(now)
        else:                                    # HEAT: heats up while active, faster in combat; the AI-AH protocol increases it
            fighting = self.shooting or now - max(w.last_combat, self.last_fight) < HEAT['combat_sec']
            lo = self.loadout()                        # forum 156747: heats faster with more equipment (the ratio is an adaptation: 10% per part)
            gain = (HEAT['gain_per_min'] / 60.0 + (HEAT['combat_gain_sec'] if fighting else 0)) * (1 + self.proto('heat')) * \
                (1 + 0.1 * (len(lo.get('gears', [])) + len(lo.get('protocols', []))))
            if self.add_heat(gain):
                self.log('   P.E.T. HEAT level %d (%d points)' % (heat_level(d['heat']), d['heat']))
                msgs += [self.heat_msg(now), self.hp_msg()] + self.stats_msgs()          # HEAT's HP bonus: max HP
                self.heat_sent, self.next_heat_msg = int(d['heat']), now + 5
            elif int(d['heat']) != self.heat_sent and now >= self.next_heat_msg:
                self.heat_sent, self.next_heat_msg = int(d['heat']), now + 5      # the gauge at most every 5 s
                msgs.append(self.heat_msg(now))
        if self.link_end and now >= self.link_end:
            msgs += self.end_link(now, notify=False)
        msgs += self.beacon_step(now)
        if d.get('gear') == FRIENDLY_SACRIFICE and now >= self.ready.get(FRIENDLY_SACRIFICE, 0) and self.sacrifice(now):
            if msgs:
                self.send(msgs)
            return
        if REPAIR_PET in self.installed_gears():       # real recording: G-REP is on while the P.E.T. is hurt, off once it is full
            hurt = d['hp'] < self.hp_max()
            if hurt != self.rep_state:
                self.rep_state = hurt
                msgs.append(('PetGearActivationChangeCommand', dict(gearType=gear_type(REPAIR_PET), active=hurt)))
        if int(d['fuel']) != self.fuel_sent and now >= self.next_fuel_msg:
            self.fuel_sent, self.next_fuel_msg = int(d['fuel']), now + 10      # the fuel gauge at most every 10 s
            msgs.append(self.fuel_msg())
        g = d.get('gear')
        if g == REPAIR_PET and d['hp'] < self.hp_max() and not self.in_fight(now):     # forum 127074: does not work in combat
            with self.p.lock:
                d['hp'] = min(self.hp_max(), d['hp'] + self.gear(REPAIR_PET).get('hp_sec', 0))
                self.p.dirty = True
            msgs.append(self.hp_msg())
        if d['shield'] < self.shield_max() and now - max(w.last_combat, self.last_fight) >= ITEMS['out_of_combat_sec']:
            with self.p.lock:
                d['shield'] = min(self.shield_max(), d['shield'] + max(1, self.shield_max() * ITEMS['shield_regen_sec']))
                self.p.dirty = True
            msgs.append(self.shield_msg())
        if g == COMBO_REPAIR:
            ship = self.p.d['ship']
            cg = self.gear(COMBO_REPAIR)
            cost = cg.get('extra_fuel', 0) * SET.multiplier('pet_fuel')     # forum 127074: 5 s repair, 15 s cooldown, fuel on activation
            hurt = ship.get('hitPoints', 0) < ship.get('hitMax', 0) and now - w.last_hurt >= ITEMS['out_of_combat_sec']
            if hurt and now >= self.csr_end and now >= self.csr_ready and d['fuel'] >= cost:
                self.csr_end = now + cg.get('duration_sec', 5)
                self.csr_ready = self.csr_end + cg.get('cooldown_sec', 15)
                with self.p.lock:
                    d['fuel'] -= cost
                    self.p.dirty = True
            if hurt and now < self.csr_end:
                hp0 = ship['hitPoints']
                self.p.set_hull(hp=hp0 + cg.get('hp_sec', 0))
                msgs.append(('HitpointInfoCommand', dict(hitpoints=int(ship['hitPoints']), hitpointsMax=ship.get('hitMax', 0),
                                                         nanoHull=ship.get('nanoHull', 0), nanoHullMax=ship.get('maxNanoHull', 0))))
                msgs += w.heal_msgs(hp0)                                  # the "+HP" number (Ö1)
                px, py = self.pos(now)                                    # repair beam (client Heal_Beam: source P.E.T., target ship)
                msgs.append(('HealBeamCommand', dict(sourceId=str(self.pid), sourcePositionX=int(px), sourcePositionY=int(py), targetId=w.hid)))
        if g in (ENEMY_LOCATOR, RESOURCE_LOCATOR):
            # No target (none chosen, none on the map or none in range): the client expects (-1, -1) and dims the arrow
            # (LocatorGearEffect3D.UpdateGearInfo: alpha 0.2, no rotation). Sending nothing left the arrow at its default
            # rotation, pointing north, or frozen on the last target.
            spot = self.locate_target(g, self.locate[g]) if g in self.locate else None
            x, y = (int(spot[0]), int(spot[1])) if spot else (-1, -1)
            msgs.append(('PetGearLocatorUpdate', dict(x=x, y=y)))
        if now >= self.next_locate:
            self.next_locate = now + 5
            msgs += self.locator_msgs(changed=True)
        self.send(msgs)
        if self.kamikaze_due(now):
            self.kamikaze(now)

    def follow(self, now):
        """Follow the ship. While the ship is moving, behind it: to follow_distance behind its position FOLLOW_AHEAD s later, at the speed that
        arrives in that time (at most 1.5 times the ship's speed). It used to go to where the ship would arrive: at the same speed, because
        its path was shorter, it flew ahead of the ship (user report 2026-10-24). While the ship is still, to follow_distance away from where it will arrive (faster if left behind). The ship's position is
        what the client draws (world.Mover): when the server's ship ran 5% ahead, the P.E.T. still looked ahead on a long path (live test H216)."""
        w = self.w
        if now < self.next_follow:
            return
        h = w.hero
        px, py = self.pos(now)
        if h.t1 > now:
            hx, hy = h.pos(now + FOLLOW_AHEAD)
            dx, dy = h.x1 - h.x0, h.y1 - h.y0
            n = math.hypot(dx, dy) or 1
            tx, ty = hx - dx / n * PET['follow_distance'], hy - dy / n * PET['follow_distance']
            self.move(tx, ty, min(math.hypot(tx - px, ty - py) / FOLLOW_AHEAD, self.speed() * 1.5), now)
            self.next_follow = now + 0.5
            return
        hx, hy = h.x1, h.y1
        a = math.atan2(py - hy, px - hx)
        tx, ty = hx + math.cos(a) * PET['follow_distance'], hy + math.sin(a) * PET['follow_distance']
        if math.hypot(tx - self.mover.x1, ty - self.mover.y1) < 80 and math.hypot(tx - px, ty - py) < 400:
            return
        hpx, hpy = w.hero_pos(now)
        far = math.hypot(px - hpx, py - hpy) > 700
        self.move(tx, ty, self.speed() * (1.5 if far else 1.0), now)
        self.next_follow = now + 0.5

    def range_bonus(self):
        return 1 + self.proto('range')

    def gear_range(self, t):
        """The gear's range (including AI-R); 3X gears (level 4) gain range per HEAT level (heat_range: G-EL/G-RL +180, G-AL/G-AR +108)."""
        g = self.gear(t)
        return (g.get('range', 0) + g.get('heat_range', 0) * self.heat_lv()) * self.range_bonus()

    def collect_step(self, now, g):
        """Automatic collector: among the boxes/ores within the gear's range (AI-R) of the ship, go to the one nearest the P.E.T., collect on
        arrival; only boxes it may take (someone else's cargo, booty boxes are skipped: it used to hover over them for good). True if it did something."""
        w = self.w
        if self.task:
            kind, h = self.task
            target = (w.boxes if kind == 'box' else w.ores).get(h)
            if not target or (kind == 'ore' and target.get('busy')):
                self.task = None
                return False
            if now >= self.mover.t1:
                self.task = None
                if kind == 'box':
                    w.take_box(h, by_pet=True)
                else:
                    target['busy'] = True
                    w.send([w.beam_msg(by_pet=True)])     # the collection beam from the P.E.T.
                    w.later(ORE_DELAY, lambda: w.finish_harvest(h))
            return True
        rng = self.gear_range(g)
        sx, sy = w.hero_pos(now)
        px, py = self.pos(now)
        if g == AUTO_LOOT:
            full = self.p.cargo_free() < 1
            cands = [(h, b) for h, b in w.boxes.items() if not (full and b['tip'] in ('FROM_SHIP', 'CANDY_CARGO', 'TURKEY_CARGO') and not b.get('event')) and not b.get('keyed')
                     and w.pet_can_take(b)]
        else:
            if self.p.cargo_free() < 1:
                return False
            cands = [(h, o) for h, o in w.ores.items() if not o.get('busy')]
        # Reach is measured from the ship (otherwise it hops box to box away from the pilot), the pick is the nearest one to the P.E.T.
        cands = [(math.hypot(o['x'] - px, o['y'] - py), h, o) for h, o in cands if math.hypot(o['x'] - sx, o['y'] - sy) <= rng]
        if not cands:
            return False
        dist, h, o = min(cands, key=lambda c: c[0])
        self.task = ('box' if g == AUTO_LOOT else 'ore', h)
        self.move(o['x'], o['y'], self.speed() * 1.5, now)
        return True

    def fight(self, now):
        """Guard: fire at the ship's live target, otherwise at a nearby attacker. CBS targets also pass the current map, hostility and deflector
        check on every shot; NPC behavior stays the same."""
        w = self.w
        n = w.npcs.get(w.target) if w.attacking else None
        uid = w.target if w.attacking else None
        asset = w.asset_at(uid) if not n and uid is not None else None
        if asset and w.asset_targets.asset_attackable(uid):
            asset = None
        px, py = self.pos(now)
        hx, hy = w.hero_pos(now)
        if not (n and n.alive) and not asset:
            n = None
            recent = getattr(w, 'last_asset_attacker', None)
            if recent and 0 <= now - recent[1] <= ITEMS['out_of_combat_sec']:
                uid = recent[0]
                asset = w.asset_at(uid)
                if asset and w.asset_targets.asset_attackable(uid):
                    asset = None
            if not asset:
                near = [(math.hypot(x.mover.pos(now)[0] - hx, x.mover.pos(now)[1] - hy), x) for x in w.npcs.values() if x.alive and x.engaged]
                near = [c for c in near if c[0] <= PET['combat_distance']]
                n = min(near, key=lambda c: c[0])[1] if near else None
        if n:
            uid = n.id
        pos = asset or (n.mover.pos(now) if n else None)
        if not pos or math.hypot(pos[0] - hx, pos[1] - hy) > PET['combat_distance']:
            if self.shooting:
                self.stop_shooting()
            return False
        nx, ny = pos
        lasers = self.lasers()
        if not lasers:
            if self.shooting:
                self.stop_shooting()
            return False
        dist = math.hypot(nx - px, ny - py)
        if dist > PET['near_distance'] and now >= self.next_follow:
            a = math.atan2(py - ny, px - nx)          # to a point on the P.E.T.'s side of the target
            self.move(nx + math.cos(a) * PET['near_distance'] * 0.8, ny + math.sin(a) * PET['near_distance'] * 0.8, self.speed() * 1.2, now)
            self.next_follow = now + 0.5
        if dist > COMBAT['laser_range']:
            if self.shooting:
                self.stop_shooting()
            return True
        if now < self.next_shot:
            return True
        ammo = self.p.d['selected']['laser']
        if self.p.use_ammo(ammo, len(lasers)) is None:
            if self.shooting:
                self.stop_shooting()
            return False
        if self.shooting != uid:
            self.log('   P.E.T. firing: %s (%d lasers, %s)' % (n.d['name'] if n else 'CBS %s' % uid, len(lasers), ammo))
        self.shooting = uid
        self.next_shot = now + ITEMS['laser_ammo'].get(ammo, {}).get('interval_sec', COMBAT['laser_interval_sec'])
        self.last_fight = now                  # not w.last_combat: the pilot is not in combat, repair and shield regeneration keep running
        w.send(w.ammo_msgs(ammo) + [('AttackLaserRunCommand', dict(attackerId=self.pid, targetId=uid,
                                                                   laserColor=ITEMS['laser_colors']['ammunition'].get(ammo, 0),
                                                                   isDiminishedBySkillShield=False, skilledLaser=False, visualType=0))])
        if random.random() < SET.chance('player_hit_chance', COMBAT['laser_hit_chance'] * (1 + self.proto('hit'))):
            base = self.laser_damage(n, pvp=bool(asset))
            base *= 1 + self.row()['damage'] + self.proto('laser') + (self.proto('alien') if n else 0)
            if self.d.get('gear') == HP_LINK:
                base *= self.gear(HP_LINK).get('pet_damage', 1)
            a = ITEMS['laser_ammo'].get(ammo, {'multiplier': 1})
            r = random.uniform(*ITEMS['damage_random'])
            shield = int(base * a.get('shield_multiplier', 0) * r)
            dmg = shield or int(base * a.get('multiplier', 1) * r) + LASERS.flat_extra(self.lasers(), bool(asset))     # Paritydrill +5: after the multipliers
            if asset:
                w.hit_asset(uid, dmg, 1, shield_only=bool(shield), attacker=self.pid)
                if not w.asset_at(uid):
                    self.stop_shooting()
            else:
                w.hit_npc(uid, dmg, 1, shield_only=bool(shield), attacker=self.pid)
        else:
            w.send([('AttackMissedCommand', dict(attackType=mod('AttackTypeModule', attackTypeValue=1), targetUserId=uid, skillColorId=0))])
        return True

    def stop_shooting(self):
        self.shooting = None
        self.w.send(self.abort_msgs())

    def abort_msgs(self):
        """The P.E.T.'s laser stops. The client keeps AttackLaserRunCommand's salvo going until stopped; PetLaserAttackStopCommand has no handler
        on the client, the salvo ends with AttackAbortLaserCommand {uid}. Only that was sent: when the target died the P.E.T. fired at a dead (or
        reused) unit, outside the map (user 2026-10-19)."""
        return [('PetLaserAttackStopCommand', {'petId': self.pid}), ('AttackAbortLaserCommand', {'uid': self.pid})]

    def npc_gone(self, nid):
        """An alien died or withdrew (world, under the lock) -> messages: if the P.E.T. is firing at it, the laser stops."""
        if self.shooting == nid:
            self.shooting = None
            return self.abort_msgs()
        return []

    def trade_bonus(self):
        """The price bonus of a sale with G-TRA1 (wiki +5%/15%/30%; client "Trade bonus")."""
        return self.gear(TRADE_POD).get('trade_bonus', 0)

    def trade_fuel(self):
        """A sale's fuel cost (one-time; client "You have to use P.E.T. fuel to trade"). The amount is an adaptation: items.json
        G-TRA1 trade_fuel; AI-ECO and the panel's fuel multiplier apply like other fuel costs."""
        return self.gear(TRADE_POD).get('trade_fuel', 0) * (1 + self.proto('fuel')) * SET.multiplier('pet_fuel')

    def trade_charge(self):
        """First sale in a trade session: fuel is deducted once; as much as wanted can be sold while the window is open (real game, player report
        2026-10-27)."""
        if self.trade_paid:
            return
        self.trade_paid = True
        with self.p.lock:
            self.d['fuel'] = max(0, self.d['fuel'] - self.trade_fuel())
            self.p.dirty = True
        self.send([self.fuel_msg()])

    def trade_block_msgs(self, now):
        """P.E.T. window while cooling down: buttons locked and a "Trade buff" icon with a countdown (the client's game.xml petBuffs 3 =
        ttip_pet_trading; PetBuffCommand action 0 adds, duration in seconds: sending ms live showed 8:19:58)."""
        return [('PetBlockUICommand', dict(blocked=True, blockAll=True)),
                ('PetBuffCommand', dict(effectAction=0, effectId=TRADE_BUFF, addingParameters=[int(self.trade_ready - now)]))]

    def trade_close(self, now):
        """Trade window closed (real game): the P.E.T. is hidden, switches to Passive mode, the window is locked and cooling starts (300/120/30 s
        by gear level); when it ends the window opens, the P.E.T. can be launched again."""
        if not self.trading:
            return
        self.trading = self.trade_paid = False
        cool = self.gear(TRADE_POD).get('cooldown_sec', 0)
        self.trade_ready = now + cool
        self.trade_wait = cool > 0
        self.relaunch = False
        with self.p.lock:
            self.d['gear'] = PASSIVE
            self.p.dirty = True
        self.deactivate(notify=False)            # the window must keep recognizing the P.E.T. (PetInfo): only the unit is removed, the buff attaches to it
        self.send([self.select_msg()] + (self.trade_block_msgs(now) if self.trade_wait else []) + [('ShipRemoveCommand', {'userId': self.pid})])
        self.log('   trade ended: P.E.T. locked for %d s' % cool)

    def trade_unblock(self):
        self.trade_wait = False
        self.send([('PetBlockUICommand', dict(blocked=False, blockAll=False)),
                   ('PetBuffCommand', dict(effectAction=1, effectId=TRADE_BUFF, addingParameters=[]))])
        self.log('   P.E.T. trade cooldown ended')

    def targets(self, g):
        """The locator gear's selectable targets: the client ids of enemy NPCs on the map (locator_id) or ore types."""
        w = self.w
        if not w:
            return []
        if g == ENEMY_LOCATOR:
            return sorted({k for k in map(locator_id, w.npcs.values()) if k})
        return sorted({o['tip'] for o in w.ores.values()})

    def locate_target(self, g, value):
        w = self.w
        now = time.time()
        hx, hy = w.hero_pos(now)
        rng = 1e9 if SET.get('infinite_pet_range') else self.gear_range(g)
        if g == ENEMY_LOCATOR:
            spots = [n.mover.pos(now) for n in w.npcs.values() if locator_id(n) == value]
        else:
            spots = [(o['x'], o['y']) for o in w.ores.values() if o['tip'] == value]
        spots = [s for s in spots if math.hypot(s[0] - hx, s[1] - hy) <= rng]
        return min(spots, key=lambda s: math.hypot(s[0] - hx, s[1] - hy)) if spots else None

    def selection_msg(self):
        """The player selected their own P.E.T. (world.select): HP and shield in the target bar."""
        return ('ShipSelectionCommand', dict(userId=self.pid, shipType=self.look or self.ship_type(), shield=int(self.d['shield']),
                                             shieldMax=self.shield_max(), hitpoints=int(self.d['hp']), hitpointsMax=self.hp_max(),
                                             nanoHull=0, maxNanoHull=0, shieldSkill=False))

    def station_hit(self, dmg, attacker, atype=0, now=None):
        """CBS hit: the P.E.T.'s own shield absorption; damage report with the real loss and the station id."""
        w = self.w
        if not self.active or not self.alive or not w or w.hero_dead or w.jumping:
            return 0
        dmg = max(0, int(dmg))
        if not dmg:
            return 0
        now = time.time() if now is None else now
        d = self.d
        with self.p.lock:
            shield = min(d['shield'], int(dmg * self.absorb()))
            hull = min(d['hp'], dmg - shield)
            d['shield'] -= shield
            d['hp'] -= hull
            self.p.dirty = True
        amount = int(shield + hull)
        if amount:
            self.last_fight = now
            w.send([('AttackHitCommand', dict(attackType=mod('AttackTypeModule', attackTypeValue=atype), attackerId=int(attacker),
                victimId=self.pid, victimHitpoints=int(d['hp']), victimShield=int(d['shield']), victimNanoHull=0,
                damage=amount, skilled=False, strike=False, cannonType=0)), self.hp_msg(), self.shield_msg()])
            if d['hp'] <= 0:
                self.destroyed(DESTROYED_NONE)
        return amount

    def owner_hit(self, dmg):
        """The player's laser at their own P.E.T. (world.pet_laser): the shield absorbs, the rest from HP; if HP runs out it is destroyed, no reward. Aliens
        do not fire at the P.E.T. (in the real game only enemy players; the server is PvE): for Kamikaze's HP threshold the player can hit it
        themselves (user report 2026-10-24). Kamikaze does not explode below the threshold, it explodes when an enemy approaches (each_second)."""
        if not self.active or not self.w:
            return
        d = self.d
        with self.p.lock:
            to_shield = min(d['shield'], int(dmg * self.absorb()))
            d['shield'] -= to_shield
            d['hp'] = max(0, d['hp'] - (dmg - to_shield))
            self.p.dirty = True
        self.w.send([('AttackHitCommand', dict(attackType=mod('AttackTypeModule', attackTypeValue=1), attackerId=self.w.hid,
                                               victimId=self.pid, victimHitpoints=int(d['hp']), victimShield=int(d['shield']),
                                               victimNanoHull=0, damage=dmg, skilled=False, strike=False, cannonType=0)),
                     self.hp_msg(), self.shield_msg()])
        if d['hp'] <= 0:
            self.destroyed(DESTROYED_NONE)

    def kamikaze_due(self, now):
        """G-KK1 is ready, HP below the threshold and an enemy in range (attacking the ship or the ship's target): it explodes."""
        kamikaze_cfg = self.gear(KAMIKAZE)
        if not self.kamikaze_armed(now) or self.d['hp'] > self.hp_max() * kamikaze_cfg.get('threshold', 0):
            return False
        w = self.w
        px, py = self.pos(now)
        return any(n.alive and not n.d.get('friendly') and (n.engaged or n.id == w.target or (n.bot is not None and n.target == w.hid))
                   and math.hypot(n.mover.pos(now)[0] - px, n.mover.pos(now)[1] - py) <= kamikaze_cfg['range'] for n in list(w.npcs.values()))             or bool(self.assets_in_blast(px, py, kamikaze_cfg['range']))

    def assets_in_blast(self, px, py, r):
        """Hittable clan base modules within the explosion range (cbs.assets_near; player report 2026-10-30: kamikaze did not affect bases)."""
        near = getattr(self.w.asset_targets, 'assets_near', None)
        return near(px, py, r) if near else []

    def start_map(self):
        """Maps where kamikaze cannot be used: starting maps and LoW (official forum 126411 "A kamikaze module will not be usable in a gate")."""
        return bool(self.w) and (H.name(self.w.map_id) in START_MAPS or bool(getattr(self.w, 'low', None)))

    def kamikaze_armed(self, now):
        """G-KK1 selected, not on cooldown, not on a starting map."""
        return self.d.get('gear') == KAMIKAZE and now >= self.ready.get(KAMIKAZE, 0) and not self.start_map()

    def ship_hurt(self, now, attacker=None):
        """The ship took damage (world.hurt_hero): G-KK1 goes off when the ship's HP drops below the threshold (client "your P.E.T. or ship") and
        when an alien attacks the ship (fandom Kamikaze Gear: "activates when the player or P.E.T. is attacked by any damage source"). Aliens never
        fire at the P.E.T. here, so its own HP threshold was hardly ever reached and the gear looked dead (player report 2026-11-02)."""
        if not (self.active and self.alive and self.w) or self.charge_end or not self.kamikaze_armed(now):
            return
        ship = self.p.d['ship']
        if ship.get('hitPoints', 0) <= ship.get('hitMax', 0) * self.gear(KAMIKAZE).get('threshold', 0) or getattr(attacker, 'mover', None):
            self.charge(now, attacker)

    def charge(self, now, attacker=None):
        """G-KK1 flies straight at the locked target, else at the alien that hit the ship, and explodes there (fandom Kamikaze Gear); with
        neither it explodes where it is. It used to explode at once next to the ship, where the aliens it was meant for often weren't."""
        w = self.w
        n = w.npcs.get(w.target)
        if not (n and n.alive and not n.d.get('friendly')):
            n = attacker if getattr(attacker, 'alive', False) and getattr(attacker, 'mover', None) else None
        other = w.player(w.target) if n is None and w.shared is not None and w.target else None      # a player on the shared map
        if n is None and other is None:
            return self.kamikaze(now)
        self.charge_at, self.charge_hops = (n.id if n is not None else ('p', other)), 0
        if not self.recharge(now, first=True):
            self.kamikaze(now)

    def charge_target_pos(self, now):
        """Where the charge target is now, or None (gone, dead, left the map)."""
        t = self.charge_at
        if isinstance(t, tuple):
            o = t[1]
            return None if o.hero_dead or not o.running or o.map_id != self.w.map_id else o.hero_pos(now)
        n = self.w.npcs.get(t)
        return n.mover.pos(now) if n is not None and n.alive else None

    def recharge(self, now, first=False):
        """Flies (again) at the charge target if it is farther than half the blast range -> still flying. A moving target (a bot, a player)
        used to be gone from the spot when the P.E.T. arrived and the blast hit nothing (player report 2026-11-02); at most 4 legs."""
        pos = self.charge_target_pos(now) if self.charge_at is not None else None
        self.charge_end = 0.0
        if pos is None or self.charge_hops >= 4:
            return False
        px, py = self.pos(now)
        dist = math.hypot(pos[0] - px, pos[1] - py)
        if dist <= self.gear(KAMIKAZE)['range'] * 0.5:
            return False
        speed = max(1, self.speed())
        if self.shooting:
            self.stop_shooting()
        self.move(pos[0], pos[1], speed, now)
        self.charge_end = now + dist / speed
        self.charge_hops += 1
        if first:
            self.log('   P.E.T. kamikaze: flying at %s (%d away)' % (self.charge_at, dist))
        return True

    def kamikaze(self, now):
        """Kamikaze gear: explodes when HP drops below the threshold, damages nearby NPCs (the P.E.T. is destroyed), the cooldown starts (wiki
        120/60/30 s; when it ends msg_pet_kamikaze-gear_cooldown_ready). The client shows the "Kamikaze used" message itself."""
        w, kamikaze_cfg = self.w, self.gear(KAMIKAZE)
        px, py = self.pos(now)
        reach, full = kamikaze_cfg['range'], kamikaze_cfg['damage']
        hit = [(n, math.hypot(n.mover.pos(now)[0] - px, n.mover.pos(now)[1] - py)) for n in list(w.npcs.values()) if n.alive]
        hit = [(n, d) for n, d in hit if d <= reach]
        assets = self.assets_in_blast(px, py, reach)
        self.charge_end = 0.0
        self.ready[KAMIKAZE] = now + kamikaze_cfg.get('cooldown_sec', 0)
        with self.p.lock:
            self.d['gear'] = GUARD
            self.p.dirty = True
        self.destroyed(DESTROYED_KAMIKAZE)
        self.send([('PetGearActivationChangeCommand', dict(gearType=gear_type(KAMIKAZE), active=False))])   # grey while cooling down
        self.charge_at = None
        players = []
        if w.shared is not None:                    # enemy players on the shared map (player report 2026-11-02: only NPCs and bots were hit)
            import player_combat as PVP
            for o in list(w.shared.members):
                if o is w or not o.running or o.hero_dead or o.map_id != w.map_id:
                    continue
                d = math.hypot(o.hero_pos(now)[0] - px, o.hero_pos(now)[1] - py)
                if d <= reach and not PVP.attack_error(w, o, now):
                    players.append((o, d))
        near = min([d for _, d in hit + players], default=0.0)
        for n, d in hit:
            w.hit_npc(n.id, blast_damage(full, d, near, reach), 1, attacker=self.pid)
        for uid in assets:
            self.send(w.asset_targets.asset_damage(uid, full, attacker=self.pid))
        for o, d in players:
            PVP._hit(w, o, now, blast_damage(full, d, near, reach), atype=0)      # the PvP rules and the panel's damage multiplier as for a rocket
        self.log('   P.E.T. kamikaze: %d NPCs, %d players, %d base modules hit' % (len(hit), len(players), len(assets)))

    def destroyed(self, kind, killer=None):
        with self.p.lock:
            self.d.update(destroyed=True, hp=0, shield=0)
            self.p.dirty = True
        self.deactivate(notify=False)
        self.send([('ShipDestroyedCommand', dict(destroyedUserId=self.pid, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': self.pid}),
                   ('PetIsDestroyedCommand', dict(destroyedType=kind)), self.init_msg(), self.repair_button()])
        self.log('   P.E.T. destroyed%s' % (' (%s)' % killer.d['name'] if killer else ''))

    def hero_died(self):
        """Ship destroyed: the P.E.T. stops too (launched by hand after respawn)."""
        self.relaunch = False
        self.deactivate()

    def gain_xp(self, ep):
        """5% of the EP the player earns (wiki). It does not earn while inactive. On a level-up the look and slots change."""
        if not self.active or ep <= 0:
            return []
        add = int(ep * PET['ep_share'] * (1 + self.p.mods().get('pet_ep', 0)) * SET.multiplier('pet_ep'))     # P-EP booster; panel
        if not add:
            return []
        d = self.d
        with self.p.lock:
            d['ep'] += add
            old = d['level']
            while d['level'] + 1 < len(PET['levels']) and d['ep'] >= PET['levels'][d['level'] + 1]['ep']:
                d['level'] += 1
            self.p.dirty = True
        msgs = [('PetExperiencePointsUpdateCommand', dict(currentExperiencePoints=d['ep'], maxExperiencePoints=self.next_xp()))]
        if d['level'] > old:
            self.look = self.ship_type()
            msgs += [('PetLevelUpdateCommand', dict(petLevel=d['level'], petExperiencePointsUntilNextLevel=self.next_xp(),
                                                    designId=self.ship_type(), expansionStage=1)), self.status_msg()]
            self.log('   P.E.T. leveled up: %d' % d['level'])
            self.p.ach('pet_level', value=d['level'])
        return msgs

    def refresh(self):
        """P.E.T. equipment changed in the hangar: if it is in space, resend gears, status and look (design). The look is applied
        by recreating the unit (respawn_msgs), only when it changes: no level-up effect on each hangar move (2026-10-19)."""
        if not self.active:
            return []
        hp, sh = self.hp_max(), self.shield_max()
        with self.p.lock:
            self.d['hp'] = min(self.d['hp'], hp)
            self.d['shield'] = min(self.d['shield'], sh)
        if self.d.get('gear') not in {t for t, lv, ok in self.gear_list() if ok}:
            self.d['gear'] = GUARD
        look = []
        if self.ship_type() != self.look:
            look = self.respawn_msgs(time.time())
        return look + [('PetGearResetCommand', {}), self.status_msg()] + self.gear_msgs()

    def respawn_msgs(self, now):
        """Recreate the P.E.T. unit in place so a new design shows at once. The client's PetLevelUpdateCommand handler
        (PetPetLevelUpdate.Run) reloads the model before it stores the new ship pattern, so the old model stays until the P.E.T.
        is launched again; only PetHeroActivationCommand.shipType applies the design (user report 2026-10-25)."""
        (x, y), m = self.pos(now), self.mover
        msgs = self.abort_msgs() if self.shooting else []
        msgs += [('ShipRemoveCommand', {'userId': self.pid}), self.activation_msg(x, y)]     # activation_msg updates self.look
        if m.t1 > now:
            msgs.append(('MoveCommand', dict(userId=self.pid, x=int(m.x1), y=int(m.y1), timeToTarget=m.ms_left(now))))
        return msgs


ORE_DELAY = ITEMS['ores']['harvest_sec']


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
