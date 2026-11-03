"""Shop and hangar: buying ammo/equipment and fitting and removing equipment in the hangar (flows from the save and the client).

Buying (save: LCB-10 and MCB-25 purchases, belgeler/istemci/kayit_analizi.md):
  ShopItemBuyRequest {lootId, category, amount, ...} ->
    [state of the quick-buy items] + 0|A|C|credits|uridium + currency inventory + ammo counter (MenuItemStatusCommand)
    + InventoryItemUpdatedCommand + InventoryItemPack + 0|LM|ST|BAT|lootId|count + ShopItemBuyCommand(resultId 1)
    + the category's current ShopItemListCommand (maxAmount = the amount the money affords, -1 if it affords none)
  Price: price x amount, rounded up (save: 1 piece of the 0.5 U MCB-25 -> 1 U).
  When equipment is bought the item goes into the inventory (hangarId 0). If the ship has a free slot ShopItemBuyCommand carries allowAutoEquip=1 and
  hintEquipTo="hint_equip_to_ship"; the client asks "To inventory / Auto-equip" and on confirmation sends the fitting request below
  (client code: UIShopSystem.SendHangarShipMoveItemsRequest).
Single player: items sold for real money ("Payment") are sold for uridium (prices items.json payment_prices).
  The contents of packages are given from the payment_packages table (ship packages included); an item whose content is not on the server is not shown in the list.
  Parts of a package that cannot be given (an owned ship, P.E.T., formation; drones as many as there is room) are skipped, the rest is given, and the screen shows
  "Already owned, not given: ..." (package_fit); if all of it is already owned there is no purchase. The price does not change.
Quick buy: buy_<lootId> (the SELECTION item in the save; MenuActionRequest actionType 1: one click on the shortcut bar, double click on the item bar;
  a single click on the item bar is actionType 0, the real server does not answer it); the amount is the item's counter (laser 1000, rocket 100).
Hangar:
  HangarShipEquipmentRequest -> HangarShipEquipmentCommand (item ids of the two configs from the profile)
  HangarListRequest          -> HangarShipsCommand (inventory: equipment instances, ammo, ore)
  HangarShipDetailRequest    -> HangarShipDetailCommand (laser count, ammo, generators, speed)
  HangarShipMoveItemsRequest {items, source, destination, configId} (client: UINewHangarSystem.SendMoveItemRequest;
    destination/source "ship" | "inventory", the item's type determines the slot) -> HangarShipMoveItemsCommand(result 1)
    + hangarId update of the items + HangarShipEquipmentCommand; if the active config changed, speed/shield/appearance.
Drones (the account in the save had no drone; formats from the client's code):
  Shop "drone" category: Flax (credits), Iris (uridium); the price rises with every drone (items.json drones), at most 8.
  Formations are bought from the shop; they appear in the shortcut bar's drone_formations category. When selected from the bar
  (MenuActionRequest drone_formation_*) DroneFormationChangeCommand + the drone arrangement in space + bonuses (speed, shield, HP).
  In space: "0|n|d|<user>|<formation>|" + per drone "type|level|design|appearance" (client: MapEventsAssemblyHelper.
    AssembleSetDrones; type 1 Flax, 2 Iris, 3 Apis, 4 Zeus; level 1-6).
  Hangar: HangarShipsCommand.drones (HangarShipDroneView) and HangarShipEquipmentCommand.droneConfigs (drone list per config,
    fitted items SingleDroneEquipmentMsg.defaults). Only lasers and shield generators are fitted to drones (Flax 1, Iris 2 slots);
    the client sends destination/source "drone" + droneId (slot set "default"; client: UINewHangarSystem.ReturnDroneId).
Drone designs (shop "customization"; Havoc and Hercules items.json extra_shop): one "design" (with a bonus,
  DroneDesignType in the client) and one "visual" (appearance, DroneCustomizationType) slot per drone; per config (like the P.E.T. tied to the
  config number, not to the ship; in the drone record design/appearance {config: item id}). The design/appearance fields of the drone
  string in space are the client's game.xml design ids (items.json drone_designs).
P.E.T. (pet.py): in the shop pet_pet10 (one), gears (petgear) and protocols (protocol) go into the inventory; in the hangar
  P.E.T. slots (lasers, generators, gears, protocols) per config; opening slots and renaming are in pet.py.
Catalog and prices from the ShopItemListCommands in the save (data/responses.json); equipment values data/items.json.
"""
import json, math, os, time
import game_data as DATA
import booster as BOOSTER   # noqa: E402
import pet as PETM
import extras as EX
import ranks as RT
import technology as TECH
import upgrades as UPG
import ship_module as GM
import loot as LOOT
import qfc as QF
import particle as PC
import resonator as RS
import settings as SET
import map_links as H
import event_appearances as EG
import tips as IP
import season as SE
import skill_tree as SKL

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
_F = json.load(open(os.path.join(HERE, 'data', 'prices.json'), encoding='utf8'))
PRICE, EXCHANGE_RATE = _F['prices'], _F['exchange_rate']        # market balance (tools/market_balance.py); KUR: how many credits 1 U is
WORLD_SHOP = DATA.load('shop')['products']    # World Editor: lootId -> {price, currency ('C' | 'U'), on_sale}; refreshed with refresh() while the game is open


def refresh():
    """The world's shop changed (game.watch_world): the dictionary is updated in place, the next list and purchase use the new price."""
    WORLD_SHOP.clear()
    WORLD_SHOP.update(DATA.load('shop')['products'])
CONFIG_COOLDOWN_SEC = 5          # between config switches (in the save the one after 2.4 s was rejected; the duration is an adaptation)
PREMIUM_CARGO = 500             # Premium: "500 extra units of cargo space" (client breakingNewsContent_permPremiumAdvantages)

CURRENCY = {'virtual': 'credits', 'real': 'uridium'}
SLOTS = (('equipment_weapon_laser_', 'laser'), ('equipment_weapon_rocketlauncher_', 'rocket'),
         ('equipment_generator_', 'generators'), ('equipment_extra_', 'extra'), ('equipment_shipupgrade_', 'upgrades'),
         ('equipment_core_', 'QuantumFluidCore'),       # Quantum Fluid Core: the ship's special slots (qfc.py)
         ('equipment_weapon_cannon_', 'cannon'), ('equipment_cannon_shield_', 'cannonShield'),      # particle cannon, breaker
         ('equipment_weapon_drive_', 'drive'), ('equipment_lens_', 'lens'))                        # Singularity Drive, lens
# hangar panels: the client sends "ship" for the ship; slot names are also accepted
PANELS = {'ship': None, 'laser': 'laser', 'lasers': 'laser', 'generator': 'generators', 'generators': 'generators',
          'extra': 'extra', 'extras': 'extra', 'rocket': 'rocket', 'rockets': 'rocket', 'rocketlauncher': 'rocket',
          'upgrades': 'upgrades', 'upgrade': 'upgrades', 'ship_upgrades': 'upgrades', 'shipupgrade': 'upgrades'}
INVENTORY = ('inventory', '')
DEFAULT_SLOTS = {'laser': 15, 'generators': 15, 'extra': 3, 'rocket': 1, 'upgrades': 3, 'QuantumFluidCore': 2, 'cannon': 3,
                 'cannonShield': 6, 'drive': 0, 'lens': 0}
EQUIP_SLOTS = ('laser', 'generators', 'extra', 'rocket', 'upgrades', 'QuantumFluidCore', 'cannon', 'cannonShield', 'drive', 'lens')
CLIENT_SLOTS = {'laser': 'lasers', 'generators': 'generators'}       # the names in CLIENT_SHIP_SLOTS (capacity)
MODULE_TYPE_IDS = {'DAMAGE': 1, 'HP': 2, 'SHIELD': 3, 'SPECIAL': 4}       # ShipUpgradeModuleUpdateCommand.moduleTypeIds (uyarlama)
ORES = {int(t): loot for t, loot in ITEMS['ores']['kinds'].items()}     # OreType -> item (hangar inventory)
DRONES = ITEMS['drones']
FORMS = ITEMS['formations']
FORM_RULES = ITEMS['formation_rules']     # minimum drone count per formation and the sales calendar
LEVELS = ITEMS['drone_levels']
DRONE_ITEMS = ('equipment_weapon_laser_', 'equipment_generator_shield_')     # laser and shield generator for drones (+ extras: drone_ok)
REPBOT = 'equipment_extra_repbot_'                                           # repair robots: one per config
LAB = ITEMS['lab']
DESIGNS = ITEMS['drone_designs']
DESIGN_SLOTS = {'design': 'design', 'appearance': 'visual'}     # drone record key -> design slot (drone item's "slot")
DESIGN_TYPES = {'design': 'net.bigpoint.darkorbit.asset.drone.design.DroneDesignType',
                'visual': 'net.bigpoint.darkorbit.asset.drone.design.DroneCustomizationType'}
PET_LOOT = ITEMS['pet']['loot']
PET_FUEL = 'resource_pet-fuel'
PACK_MAX = 255             # list with a byte counter (InventoryItemPack.items): at most this many items
NEW_RESOURCES = ('resource_collectable_evocation-chip', 'resource_collectable_calling-chip',          # N.O.V.A. (nova.py)
                 'resource_collectable_luminaflux-alloy', 'resource_collectable_armory-token',       # Hyperforge (qfc.py), Armory
                 'resource_collectable_armory-token-mega', 'resource_collectable_optigrad-chip',       # Restabilize (particle.py)
                 'resource_collectable_horizon-shard', 'resource_collectable_containment-node',       # driver sub-attributes
                 'resource_collectable_pulse-core', 'resource_ignishard-l01', 'resource_beacon-crystal')
PASS_ITEMS = ('resource_season-pass-point', 'resource_gold-pass', 'resource_ext-gold-pass', 'resource_battle-pass',
              'resource_monthly-deluxe')
# items that have no trait (Traits) in the client's definition (only type and class in data/client_items.json): when one becomes an inventory
# item with an id, with Assembly open AssemblyInventoryIndex.UpdateItem throws NullReferenceException, and the rest of the item list (including the
# UserInventoryModule discount at login) was not processed (Gold/Extra Gold Pass, Trinity VIP Badge; live round 2). These resources are not sent
NO_TRAITS = {l for l, v in UPG.ITEMS.items() if set(v) <= {'type', 'class_name'}}
EVENT_ITEMS = ('resource_collectable_voyagers-oath-token', 'resource_voyagers-vip-badge',      # Voyagers (pve_modes.py)
               'resource_ftl-key', 'resource_collectable_galaxy-coupon', 'resource_lottery-capsule')   # Ö3 event currencies (market balance)


def mod(name, **f):
    f['_'] = name
    return f


from legacy_protocol import legacy, loot_kind  # noqa: E402,F401  (old text protocol: legacy_protocol.py)


def keyed(key, **wild):
    """Error text with the client's localization key (MessageKeyListWildcardCommand)."""
    reps = [mod('MessageWildcardReplacementModule', wildcard='%' + k + '%', replacement=v,
                replacementType=mod('ReplacementTypeModule', typeValue=5 if v.startswith('ttip_') else 0)) for k, v in wild.items()]
    return mod('MessageKeyListWildcardCommand', commandList=[
        mod('MessageKeyListWildcardModule', wildCardReplacements=reps, baseKey=key,
            baseKeyType=mod('ReplacementTypeModule', typeValue=5), textStyle=0)])


BASEKEY = json.load(open(os.path.join(HERE, 'data', 'message_keys.json'), encoding='utf8'))['keys']


# placeholders in the text (the client's ArgKey enum): if the name is "_X_" it is %X% in the text, otherwise the name itself (XXX, YYY, DATETIME)
ARG_KEYS = {'_COOLDOWN_': 0, '_BOOSTERNAME_': 1, '_module_': 2, '_level_': 3, '_date_': 4, '_userlevel_': 5, '_maxMessages_': 6,
            '_notesLimit_': 7, '_MINIMUM_BID_': 8, '_NAME_': 9, '_AMOUNT_': 10, '_CURRENCY_': 11, 'XXX': 12, 'YYY': 13,
            'DATETIME': 14, '_MAX_BID_': 15}


def res(key):
    """Localization of a placeholder value in the client (ShowCallBackText.ReturnTipByType: split by ':', if the second part is 'res' the
    last part is translated with GetTextById). "res:<key>" did not work (live test H36: the placeholder stayed raw)."""
    return ':res:' + key


def stack_extra(key, extra):
    """The text the client localizes (key) followed by a language-independent suffix (numbers): raw text "XXX<suffix>", XXX is translated in the client
    (type 1 as in RES_YERINE). The placeholder in the suffix (_AMOUNT_) is not filled on this path (live test 2026-10-30): the values go inside the suffix."""
    return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX' + extra,
               argsList=[mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS['XXX'], value=res(key))])


def stack_msg(key, **args):
    """Error/success text in response commands (ShopItemBuyCommand, HangarShipMoveItemsCommand, HangarShipActivateShipCommand).
    The client expects BaseStackCommand; another class throws InvalidCastException and drops the connection (live test).
    type 0 + enumBaseKey: the client uses the BaseKey enum name as the localization key (stringBasekey would be raw text).
    args: values of the placeholders (ArgStackCommand; client ShowCallBackText.ReturnTipString): e.g. XXX='Komutan',
    _MINIMUM_BID_='10,000'. The value res(<key>) is translated in the client. If not given, a raw placeholder like "XXX" stayed in the text
    (live trial 2026-10-17: "A new rank was created: XXX.")."""
    lst = [mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS[k], value=str(v)) for k, v in args.items()]
    if key in RES_REPLACEMENT:
        # a key in a resource the client does not load: raw text "XXX" + the localized value of XXX (type 1; ReturnTipString
        # translates the placeholders from the end to the start: first XXX, then the text's own placeholders)
        alias, extra = RES_REPLACEMENT[key]
        lst = [mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS[k], value=str(v)) for k, v in extra.items()] + lst
        lst.append(mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS['XXX'], value=res(alias)))
        return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX', argsList=lst)
    return mod('BaseStackCommand', type=0, enumBaseKey=BASEKEY[key], stringBasekey='', argsList=lst)


def raw_msg(text):
    """Raw text (type 1: stringBasekey is shown as is; like RES_YERINE)."""
    return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey=text, argsList=[])


# rejection reasons that have no counterpart in the client's texts (not in the BaseKeys or in the 40 text files; the client showed only the generic text:
# N4, HAT-7/20) -> (English, Turkish); raw text in the client's language (Shop.reason)
REASONS = {
    'name_cooldown': ('You can only rename your Pilot once every 48 hours. (Your last name change: %DATETIME%)',     # change_pilotname_error_time
                   'Pilotunun adını en fazla 48 saatte bir değiştirebilirsin. (Son ad değişikliğin: %DATETIME%)'),
    'name_banned': ('This Pilot name is not permitted.', 'Bu Pilot adına izin verilmiyor.'),                       # change_pilotname_error_blacklist
    'subscribed': ('You have subscribed to this booster. It will be bought again automatically.',            # client booster_bought_subscription
                   'Bu güçlendiriciye abone oldun; süresi bitmeden kendiliğinden yeniden alınacak.'),
    'subscription_ended': ('Your booster subscription has been cancelled.', 'Güçlendirici aboneliğin sona erdi.'),
    'pet_already': ('This item is already equipped on your P.E.T.', "Bu eşya P.E.T.'inde zaten takılı."),
    'pet_full': ('Your P.E.T. has no free slot for this item.', "P.E.T.'inde bu eşya için boş yuva yok."),
    'other_ship': ('This item is equipped on another ship. Unequip it there first.', 'Bu eşya başka bir gemide takılı; önce oradan çıkar.'),
    'same_cannon': ('Your ship already has a cannon of this type.', 'Gemide bu türden bir top zaten takılı.'),
    'qfc_ship': ('This Quantum Fluid Core is bound to another ship.', 'Bu Quantum Fluid Core başka bir gemiye bağlı.'),
    'same_qfc': ('Your ship already has a Quantum Fluid Core of this type.', 'Gemide bu türden bir Quantum Fluid Core zaten takılı.'),
    'single_slot_cpu': ('Only one Slot CPU is allowed per configuration.', "Bir config'e yalnız bir Slot CPU takılabilir."),
    'equipped_sale': ('Equipped items cannot be sold. Unequip it first (check both configurations).',
                     "Takılı eşya satılamaz; önce çıkar (iki config'e de bak)."),
    'incomplete_load': ('Some equipment were not available to be loaded into the saved configuration.',
                      "Kayıtlı config'teki bazı eşyalar yüklenemedi (satılmış ya da başka gemide)."),
    'transfer_inventory': ('Some equipment cannot be equipped on the new ship and was moved to your inventory.',
                         'Bazı eşyalar yeni gemiye takılamadığı için envantere kaldırıldı.'),
    'fuel_full': ("Your P.E.T.'s fuel tank is full.", "P.E.T.'inin yakıt deposu dolu."),
    'research_points': ('Not enough Research Points available.', 'Yeterli araştırma puanı yok.'),
    'prerequisite': ('The prerequisites for the next level of this skill are not met.', 'Bu yeteneğin sonraki seviyesinin ön koşulları karşılanmıyor.'),
    'same_module': ('Only one module of each type (Damage, HP, Shield, Special) can be equipped on a ship.',
                   'Bir gemiye her türden (hasar, can, kalkan, özel) yalnız bir modül takılabilir.'),
    'qfc_sale': ('Quantum Fluid Cores cannot be sold. You can recycle them in the Hyperforge (Assembly).',
                  "Quantum Fluid Core satılamaz; Hyperforge'da (Assembly) geri dönüştürebilirsin."),
    'rh_bond_duration': ('Returnees must bond with an active player within 24 hours of logging in.',
                      'Dönen oyuncular girişten sonraki 24 saat içinde aktif bir oyuncuya bağlanmalı.'),
}


# BaseKey names for which the client finds no text -> the equivalent in the loaded resource (and its placeholders). The client loads the "resource_items_old"
# resource but the file in the package is "resource_item_old" (LocalizationManager): the keys in that file (drone_have_max)
# are never found, the error window opened empty (live test 2026-10-18). clan_errmsg_desc_to_long is in no resource.
RES_REPLACEMENT = {'drone_have_max': ('items_drone_have_max', {}),
              'drone_slotCPUinUse': ('drone_slotCPUinUse', {}),        # in resource_system_inc; not in the BaseKeys
              'special_generic_hint': ('items_special_generic_hint', {}),
              'tf_message_not_enough_seprom': ('tf_message_not_enough_seprom', {}),   # "Not enough Seprom available" (skill tree)
              'clan_errmsg_desc_to_long': ('clan_errmsg_to_long', {'_NAME_': res('label_description')})}


# resources that are ingredients in Assembly recipes (those sold in the shop: Prismatic Socket, Nano Case ...; assembly.py)
ASSEMBLY_PARTS = {l for r in json.load(open(os.path.join(HERE, 'data', 'recipes.json'), encoding='utf8'))['recipes'].values()
                  for l in r['parts'] if l.startswith('resource_')}
STAT_TABLES = (('lasers', 'damage'), ('shield_generators', 'shield'), ('speed_generators', 'speed'))
# no effect, not sold (hidden in the shop): the Radar CPU (diplomacy colors: bot players). The Serum CPU cures IM-01 infection
NO_EFFECT = ('equipment_extra_cpu_rd-x',)
PAY_CURRENCY = {'currency_uridium': ('uridium', 'URI'), 'currency_credits': ('credits', 'CRE'), 'currency_experience': ('ep', 'EP'),
                'currency_honour': ('honourPoints', 'HON')}
PRIZE_CURRENCY = {'currency_uridium': 'uridium', 'currency_credits': 'credits', 'currency_experience': 'ep', 'currency_honour': 'honor'}
SHOP_MAX = 255                     # the counter of ShopItemListCommand.itemList is one byte (protocol.LIST_MAX)
# free item (the panel's shop price 0, "Creative"): for an item with an amount selector the client enables Buy when the affordable amount >= 1 and finds the amount
# as balance / price[0]; if the price is 0 the amount is 0 (UIShopSystem.CalculateAffordableAmount, SetRightNumberLevel), and Buy got disabled
# (user 2026-10-25). In the list price[0] is this much (converted to 1E-09 in Decimal: balance / price does not overflow; the amount is rounded to 2 digits and
# shows as 0), its text (cost) 0; the purchase's price is from buy_price (0). For ammo the amount limit is FREE_COUNT (price x amount stays 0.00).
# On click the total box writes the price without rounding ("0.000000001 U."): the client's BepInEx plugin rounds it (panel/plugin/Patches.cs ShopAmount).
FREE_PRICE = 1e-9
FREE_COUNT = 1000000


def design_base(loot):
    """Ship design -> the ship it belongs to (ship_goliath_design_amber -> ship_goliath); None if it is not a design."""
    return loot.split('_design_')[0] if loot.startswith('ship_') and '_design_' in loot else None


def slot_of(loot):
    return next((s for p, s in SLOTS if loot.startswith(p)), None)


def loose_item(loot):
    """An item that has no ship slot and enters the inventory as an instance: drone and P.E.T. design, P.E.T. gear and protocol (fitted in the hangar)."""
    return loot in DESIGNS or loot in PETM.DESIGNS or PETM.slot_for(loot) in ('gears', 'protocols')


def hidden(loot):
    """Is it an item in the store (diger_esyalar) that is not visible in the inventory and that no system reads. Resources (resource_) are visible; a ship design
    that arrives while the ship is missing (pending_designs) and the CBS module (cbs.absorb) deliberately wait. A reward that falls on such an item counts as lost
    (2026-10-22: Season Pass's drone designs, reserves and Assembly's P.E.T. protocols were being lost this way)."""
    return not loot.startswith(('resource_', 'module_')) and not design_base(loot)


def pet_only(loot):
    """Laser/generator specific to the P.E.T. (LF-P01, SG3N-P01 ...; items.json yalniz_pet)."""
    return bool(ITEMS['lasers'].get(loot, ITEMS['shield_generators'].get(loot, {})).get('pet_only'))


ITEM_TYPE = 'net.bigpoint.darkorbit.asset.item.ItemType'
# the client's item classes (client_items.json 'sinif' short name -> full name; from the client's text constants)
CLASS_PATHS = {c.split('.')[-1]: 'net.bigpoint.darkorbit.asset.' + c for c in (
    'cannonshield.CannonShieldType', 'weapon.CannonType', 'weapon.DriveType', 'lens.LensType', 'quantum.QuantumFluidCoreType',
    'shipupgrade.ShipUpgradeType', 'extra.ExtraType', 'extra.ModuleType', 'extra.UpgradeType', 'module.StationModuleType',
    'drone.DroneType', 'drone.formation.DroneFormationType', 'drone.design.DroneCustomizationType', 'drone.design.DroneDesignType',
    'pet.PetType', 'pet.design.PetCustomizationType', 'item.HardwareType', 'item.SynthesisResourceType', 'captain.CaptainType')}
_ist = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))['items']
CLIENT_CLASS = {k: v['class_name'] for k, v in _ist.items() if v.get('class_name') in CLASS_PATHS}
# Extras fitted to drones: those with DRONE in the client's 'equipable' trait (AGS-X, RG-SL and PA-X only to the ship). Slot CPUs
# (SLE-*) are left out for now: the extras whose slots they open are in the ship's config, removing them while on a drone would cause overflow.
# HM-7 (MERCHANT_DRONE) is also left out: in a drone slot the hangar drawing breaks (client UINewHangarSystem.SetImageSprite NullReference,
# seen live; the other drone extras are fine), the trade drone stays in the ship slot.
DRONE_EXTRAS = frozenset(k for k, v in _ist.items() if k.startswith('equipment_extra_') and 'DRONE' in (v.get('equippable') or ())
                         and v.get('type') != 'MERCHANT_DRONE' and not EX.slot_bonus_of([k]))
CLIENT_SHIP_SLOTS = {k: v['slots'] for k, v in _ist.items() if v.get('slots')}       # ship and design lootId -> the client's slots
del _ist


def drone_ok(loot):
    """Can it be fitted to a drone slot: laser, shield generator and extras (client FAQ: "lasers, shield generators and extras.
    Speed generators can't be stored on drones"); speed generators and rocket launchers cannot be fitted."""
    return loot.startswith(DRONE_ITEMS) or loot in DRONE_EXTRAS


def loot_type(loot):
    """lootType of the hangar inventory: designs, items.json loot_turleri (prefixes verified with the save), otherwise the client's own
    class. The client separates the hangar inventory by class: with the generic ItemType, outgoing cannons, drivers, lenses, breakers, QFCs
    and ship modules did not show in the inventory at all and could not be fitted in the hangar (live test H68)."""
    if loot in DESIGNS:
        return DESIGN_TYPES[DESIGNS[loot]['slot']]
    t = next((t for p, t in sorted(ITEMS['loot_types'].items(), key=lambda x: -len(x[0])) if loot.startswith(p)), ITEM_TYPE)
    if t == ITEM_TYPE and loot in CLIENT_CLASS:
        return CLASS_PATHS[CLIENT_CLASS[loot]]
    return t


def copy(x):
    return json.loads(json.dumps(x))


def catalog(replies):
    """Standard shop catalog (the panel's World Editor; no profile, no world): category -> [{lootId, price, currency ('C' | 'U'),
    fixed (priced by its own rule: drones, P.E.T. products with levels, G-HP1, fuel)}]."""
    m = Shop.__new__(Shop)
    m.lists, m.catalog, m.payment, m.extra_entry, m.credit = {}, {}, {}, {}, {}
    m.build_catalog(copy(replies))
    out = {}
    for cat, lst in m.lists.items():
        for it in lst['itemList']:
            loot = it['lootId']
            if loot in m.payment:
                currency, u = 'U', m.payment[loot]
            elif loot in m.credit:
                currency, u = 'C', m.credit[loot]
            else:
                currency, u = 'U' if it.get('currency') == 'real' else 'C', (it.get('price') or [0])[0]
            fixed = loot in DRONES or loot in (PETM.HULL, PET_FUEL) or bool(PETM.level_prices(loot))
            out.setdefault(cat, []).append({'lootId': loot, 'price': u, 'currency': currency, 'fixed': fixed})
    return out


class Shop:
    def __init__(self, profile, replies, log=print):
        self.p, self.log = profile, log
        self.lang = None          # the client's language (ChatAuthenticateUserRequest.language; social): raw rejection texts (reason)
        self.gates = None      # Galaxy Gates (free energy in the reward; the session binds it)
        self.quest = None        # quest events (session: quest.event; refined ore counts towards ore collection quests)
        self.tickets = None     # (Season Pass, Battle Pass, daily rewards): the session binds it; pass items go to them
        self.new_ = None         # the systems of stage 9 (new_systems.py): N.O.V.A. and QFC rewards go to them
        self.chromin = None      # Chromin Rush (chromin.py; the session binds it): limit Chromin entry
        self.hitac = None        # Hitac Word Puzzle (hitac_lottery.py; the session binds it): the letter in the box
        self.world = lambda: None  # current World (the session sets it): drone formation wait (formation_wait)
        self.lists, self.catalog = {}, {}
        self.payment = {}        # single player: an item sold for real money ("Payment") -> uridium price
        self.extra_entry = {}    # extra_shop row (calendar / once: the packages of the Ö7 shops)
        self.credit = {}         # market balance: "Payment" product with credits -> credit price (data/fiyatlar.json)
        self.shop_gate = None    # (row, lootId) -> is it sold now (stores.py: event, campaign, one time, level)
        self.on_bought = []      # after the purchase (lootId, count) -> messages (stores.py: VIP, Pre-BF, Mileage counters)
        self.build_catalog(replies)
        first = lambda req, name: next((m for e in replies.get(req, []) for m in e['response'] if m['_m'] == name), None)
        self.equip_tpl = first('HangarShipEquipmentRequest', 'HangarShipEquipmentCommand')
        self.ships_tpl = first('HangarListRequest', 'HangarShipsCommand')
        self.detail_tpl = first('HangarShipDetailRequest', 'HangarShipDetailCommand')
        self.item_tpl, self.tpl_ids = None, {}
        for pack in (self.ships_tpl or {}).get('items', []):
            for it in pack.get('items', []):
                self.item_tpl = self.item_tpl or it
                self.tpl_ids.setdefault(it['lootId'], it['itemid'])
        self.sent_lists = set()          # shop categories sent to the client in this session
        self.featured = None             # (category, lootId, end): the payment button's product is at the top of the list (payment.py)
        self.pet = PETM.Pet(profile, log)  # the session binds its own P.E.T. (behavior in space comes with the world)
        self.pet.on_stats = self.apply_stats       # ship values when the HEAT bonus changes
        for loot, n in list(profile.d.get('other_items', {}).items()):
            if loot.startswith('pet_designs_'):       # P.E.T. designs kept in the store before stage 6 -> inventory
                for _ in range(n):
                    profile.new_item(loot)
                profile.add_resource(loot, -n)

    def build_catalog(self, replies):
        """Catalog: the ShopItemListCommands in the save + extra shop + P.E.T. fuel; prices (market balance, then the world's shop)."""
        price = ITEMS['payment_prices']
        for e in replies.get('ShopItemListRequest', []):
            for m in e['response']:
                if m['_m'] == 'ShopItemListCommand':
                    self.lists.setdefault(m['category'], m)
                    for it in m['itemList']:
                        self.catalog.setdefault(it['lootId'], it)
                        if it.get('cost') == 'Payment' or it.get('isPaymentItem'):
                            self.payment.setdefault(it['lootId'], price['special'].get(it['lootId'], price.get(m['category'], price['default'])))
        for cat, extra in ITEMS['extra_shop'].items():     # items not in the save that cannot be obtained any other way in single player
            lst = self.lists.get(cat) if not cat.startswith('_') else None
            for x in (extra if lst else []):
                self.extra_entry[x['lootId']] = x
                tpl = self.catalog.get(x['template'])
                if tpl and x['lootId'] not in self.catalog:
                    is_credit = 'credits' in x                    # credit row (Liberator 40,000 C: player request 2026-10-30)
                    amount = x['credits'] if is_credit else x['uridium']
                    it = dict(copy(tpl), lootId=x['lootId'], price=[float(amount)], currency='virtual' if is_credit else 'real', isPaymentItem=0,
                              cost='{:,} {}'.format(amount, 'C.' if is_credit else 'U.'))
                    lst['itemList'].append(it)
                    self.catalog[x['lootId']] = it
        # P.E.T. fuel on the PET/GEAR tab, at the shortcut's unit price (uridium: real save 1,000 units = 250 U, so the unit is 0.25 U),
        # with a selected amount (not in the shop in the save; user report 2026-10-25: it was bought only via the shortcut and automatically). Template:
        # the ammo row with uridium and a selected amount
        lst, tpl = self.lists.get('petgear'), self.catalog.get('ammunition_rocketlauncher_ubr-100')
        if lst and tpl and PET_FUEL not in self.catalog:
            f = PETM.PET['fuel_buy']
            it = dict(copy(tpl), lootId=PET_FUEL, category='petgear', price=[f['uridium'] / f['count']], currency='real',
                      cost='{:g} U.'.format(f['uridium'] / f['count']))
            lst['itemList'].append(it)
            self.catalog[PET_FUEL] = it
        self.apply_prices()

    def apply_prices(self):
        """Market balance prices (data/prices.json <- tools/market_balance.py): the price of Payment products and of the extra shop
        on a single scale; those whose contents are of the credit class are priced in credits."""
        for loot, r in PRICE.items():
            it = self.catalog.get(loot)
            if r['currency'] == 'C':
                self.payment.pop(loot, None)
                if it is not None and (it.get('cost') == 'Payment' or it.get('isPaymentItem')):
                    self.credit[loot] = r['price']
                elif it is not None:
                    it.update(price=[float(r['price'])], currency='virtual', cost='{:,} C.'.format(r['price']))
            elif loot in self.payment:
                self.payment[loot] = r['price']
            elif it is not None and loot in self.extra_entry:
                it.update(price=[float(r['price'])], currency='real', cost='{:,} U.'.format(r['price']))

    @property
    def hangar_id(self):
        return self.p.ship()['hangarId']

    @property
    def ship_id(self):
        return int(self.p.d['active_ship'])

    # ------------------------------------------------------------ helpers
    def handles(self, name, f):
        if name == 'MenuActionRequest':
            mid = f.get('menuItemId', '')
            # Quick-buy activation is actionType=1 (slot-bar click, item-bar double click); the recorded server ignores 0.
            return (mid.startswith('buy_') and f.get('actionType') == 1) or mid in FORMS
        return name in ('ShopItemListRequest', 'ShopItemBuyRequest', 'HangarShipEquipmentRequest', 'HangarListRequest',
                        'HangarShipDetailRequest', 'HangarShipMoveItemsRequest', 'LabRefinementRequest', 'LabUpdateItemRequest',
                        'LabUpdateRequest', 'HangarShipUnlockSlotRequest', 'HangarShipRenamePetRequest', 'HangarShipSellItemRequest',
                        'HangarShipSellDroneRequest', 'HangarShipFavouriteRequest', 'HangarShipClearConfigRequest',
                        'HangarShipSaveConfigRequest', 'HangarShipLoadConfigRequest', 'HangarShipImportConfigRequest')

    def ship_sid(self, ship_id):
        """The active ship if the shipId in the request is not in the profile."""
        return str(ship_id) if str(ship_id) in self.p.d['ships'] else self.p.d['active_ship']

    def handle(self, name, f):
        """Response messages for the request; if None it is left to the recorded response."""
        if name == 'ShopItemListRequest':
            m = self.shop_list(f.get('category', ''))
            if m:
                self.sent_lists.add(f.get('category', ''))
            return [m] if m else None
        if name == 'HangarShipSellItemRequest':
            return self.sell(f)
        if name == 'HangarShipSellDroneRequest':
            return self.sell_drone(f)
        if name == 'ShopItemBuyRequest' and f.get('action') == 'toggleSubscription':
            return self.toggle_subscription(f.get('lootId', ''), f.get('category', ''), f.get('buyCategory', ''))
        if name == 'ShopItemBuyRequest':
            return self.buy(f.get('lootId', ''), f.get('amount', 1), f.get('category', ''), f.get('buyCategory', ''),
                            pet_name=f.get('petName') or '', level=f.get('level') or 1)
        if name == 'MenuActionRequest':
            if f['menuItemId'] in FORMS:
                return self.change_formation(f['menuItemId'])
            return self.quick_buy(f['menuItemId'][4:])
        if name == 'HangarShipEquipmentRequest':
            return [self.equipment_cmd(self.ship_sid(f.get('shipId')))] if self.equip_tpl else None
        if name == 'HangarListRequest':
            if not self.ships_tpl:
                return None
            # the client's hangar ship grid uses the shop's ship list; if the hangar is opened before the list arrives
            # HangerListCallBack throws NullReferenceException (live test). In the save the shop was always opened first.
            with self.p.lock:          # those left in slots the client cannot see (fitted earlier) go to the inventory: otherwise the hangar does not open
                trimmed = [i for sid in self.p.d['ships'] for i in self.trim_slots(sid)]
                if trimmed:
                    self.p.sync_equipment()
                    self.p.dirty = True
                    self.log('   hangar: %d items without a slot moved to the inventory' % len(trimmed))
            pre = []
            if 'ship' not in self.sent_lists and self.shop_list('ship'):
                pre.append(self.shop_list('ship'))
                self.sent_lists.add('ship')
            return pre + [self.ships_cmd()]
        if name == 'HangarShipDetailRequest':
            return [self.detail_cmd(self.ship_sid(f.get('shipId')))] if self.detail_tpl else None
        if name == 'HangarShipMoveItemsRequest':
            return self.move(f)
        if name == 'HangarShipFavouriteRequest':
            return self.favourite(f)
        if name == 'HangarShipClearConfigRequest':
            return self.clear_config(f)
        if name == 'HangarShipSaveConfigRequest':
            return self.save_config(f)
        if name == 'HangarShipLoadConfigRequest':
            return self.load_config(f)
        if name == 'HangarShipImportConfigRequest':
            return self.import_config(f)
        if name == 'LabRefinementRequest':
            return self.refine(f)
        if name == 'LabUpdateItemRequest':
            return self.upgrade(f)
        if name == 'LabUpdateRequest':
            return [self.lab_cmd()]
        if name == 'HangarShipUnlockSlotRequest':
            return self.pet.unlock(f) + self.money_msgs()
        if name == 'HangarShipRenamePetRequest':
            return self.pet.rename(f)
        return None

    # ------------------------------------------------------------ refining and upgrades
    def lab_cmd(self):
        return ('LabUpdateItemCommand', {'itemsUpdatedInfo': self.p.lab_items()})

    def refine(self, f):
        """LabRefinementRequest {toProduce: {oreType, count}}: the raw materials of the recipe are deducted, the product is added (recipes from the client's game.xml)."""
        m = f.get('toProduce') or {}
        t, n = (m.get('oreType') or {}).get('typeValue'), int(m.get('count') or 0)
        recipe = LAB['recipes'].get(str(t))
        if not recipe or n <= 0:
            return []
        need = {int(k): v * n for k, v in recipe.items()}
        short = [k for k, v in need.items() if self.p.ore_count(k) < v]
        if short:
            self.log('   refining failed: %s x%d (missing %s)' % (ORES.get(t), n, ', '.join(ORES.get(k, str(k)) for k in short)))
            return [('AttributeOreCountUpdateCommand', {'oreCountList': self.p.d['ores']})]
        self.p.remove_ores(need)
        totals = self.p.add_ores({t: n})
        self.log('   rafine: %s x%d (%s)' % (ORES.get(t), n, ', '.join('%s %d' % (ORES.get(k), v) for k, v in need.items())))
        msgs = [('AttributeOreCountUpdateCommand', {'oreCountList': totals}), self.ore_pack(sorted(need) + [t])]
        return msgs + (self.quest('loot', loot=ORES.get(t), amount=n) if self.quest else [])

    def upgrade(self, f):
        """LabUpdateItemRequest {itemToUpdate, updateWith {oreType, count}}: the ore is loaded into the part, each ore is LAB['unit']: laser/
        rocket 10 rounds/pieces, engine/shield 10 minutes (at most LAB['maximum']; leftover ore stays in the cargo). The same ore is added, a different ore
        erases the previous one (client: lab_alert).
        Speed and shield change immediately."""
        item = (f.get('itemToUpdate') or {}).get('itemValue')
        m = f.get('updateWith') or {}
        t, n = (m.get('oreType') or {}).get('typeValue'), int(m.get('count') or 0)
        if str(item) not in LAB['bonuses'] or str(t) not in LAB['bonuses'][str(item)] or n <= 0 or self.p.ore_count(t) < n:
            self.log('   upgrade failed: part %s, ore %s x%d (have %d)' % (item, t, n, self.p.ore_count(t) if t is not None else 0))
            return [self.lab_cmd()]
        old = self.p.d.get('upgrades', {}).get(str(item))
        have = old[1] if old and old[0] == t else 0
        n = min(n, max(0, LAB['maximum'] - have) // LAB['unit'][str(item)])
        if n <= 0:
            self.log('   upgrade failed: part %s is full (%d)' % (item, have))
            return [self.lab_cmd()]
        totals = self.p.remove_ores({t: n})
        with self.p.lock:
            ups = self.p.d.setdefault('upgrades', {})
            ups[str(item)] = [t, have + n * LAB['unit'][str(item)]]
            self.p.dirty = True
        key = ('lab_upgrade_laser', 'lab_upgrade_rocket', 'lab_upgrade_speed', 'lab_upgrade_shield')[item]
        self.log('   upgrade: part %d <- %s x%d (total %d)' % (item, ORES.get(t), n, ups[str(item)][1]))
        return ([('AttributeOreCountUpdateCommand', {'oreCountList': totals}), self.ore_pack([t]), self.lab_cmd()] + self.apply_stats()
                + [legacy('0|A|STM|%s' % key)]
                + (self.quest('ore_update', type=('LASER', 'ROCKET', 'SPEED', 'SHIELD')[item], ore=ORES.get(t), amount=n)
                   if self.quest else []))

    def item_id(self, loot):
        return self.p.d['item_id'].get(loot) or self.tpl_ids.get(loot) or self.p.item_id(loot)

    def capacity(self, slot, sid=None, cid=None, extras=None):
        """The number of slots of a slot type of the ship. Extra slots depend on the config: with the slot CPU (SL-01..04) in that config (cid; the active one if
        absent) or in the given extras (extras: lootId list). The active config's CPU was always counted first: a Slot CPU fitted to the other
        config did not open slots (user report 2026-10-24)."""
        if slot == 'upgrades':                                       # ship module slot: the client's ship data (ship_module.py)
            return GM.slots(self.p.ship(sid)['lootId'])
        if slot == 'QuantumFluidCore':                               # QFC slot: the client's ship data (qfc.py)
            return QF.slots(self.p.ship(sid)['lootId'])
        if slot in PC.SLOTS:                                         # cannon, breaker, driver, lens: the client's ship data
            return PC.slots(self.p.ship(sid)['lootId'], slot)
        ship = self.p.ship_row(sid)                                  # with the slots of the design being worn (Tyrannos 15 lasers ...)
        bonus = 0
        if slot == 'extra':
            bonus = EX.slot_bonus_of(extras) if extras is not None else EX.slot_bonus(self.p, sid, cid)
        if slot == 'extra' and self.equip_tpl and 'extra' not in ship:
            return self.equip_tpl.get('extrasSlotsSize1', DEFAULT_SLOTS['extra']) + bonus
        n = ship.get(slot, DEFAULT_SLOTS[slot]) + bonus
        if slot in CLIENT_SLOTS:          # the client draws these slots from its own ship data (the count is not in HangarShipEquipmentCommand):
            # items fitted to hand-increased items.json slots did not show, and on the second edit the hangar did not open (player report 2026-10-31)
            y = CLIENT_SHIP_SLOTS.get(self.p.ship_look(sid)) or CLIENT_SHIP_SLOTS.get(self.p.ship(sid)['lootId']) or {}
            n = min(n, y.get(CLIENT_SLOTS[slot], n))
        return n

    def trim_slots(self, sid):
        """Lasers, generators and launchers fitted beyond their slots go to the inventory (under the lock) -> the ids of those that came off."""
        trimmed = []
        for cfg in self.p.ship(sid)['configs'].values():
            for slot in ('laser', 'generators', 'rocket'):
                lst = cfg.get(slot, [])
                trimmed += lst[self.capacity(slot, sid):]
                del lst[self.capacity(slot, sid):]
        return trimmed

    def inv_item(self, iid, loot, amount, hangar=0, level=None):
        lv = UPG.item_level(self.p, iid) if str(iid) in self.p.d['items'] else 0     # upgrade level (upgrades.py)
        lv = lv if level is None else level
        return ('InventoryItemUpdatedCommand', {'item': mod('InventoryItemModule', upgradeLevel=lv, lootId=loot, amount=amount, itemId=iid,
                                                            star=(PC.state(self.p, iid) or {}).get('star', 0), isNew=False,
                                                            hangarId=hangar, extAttributes=[], inventoryItemAttributes=[])})

    def drone_item(self, x):
        """The drone as an item in the client's inventory (its id is the drone's id, its level the upgrade level): Assembly's Upgrade
        tab picks what to upgrade only from the items in the inventory; since drones were never sent, Iris, Apis, Zeus (and Flax) were
        not in the list (user report 2026-10-24). The Build request's targetItemId is the drone's id (upgrades.target).
        The drone's level (1-6) is in the InventoryItemAttributeKey.LEVEL (1) attribute: the Upgrade tab builds the bonus row from it
        (ItemBuff.ParseDrone: the "upgradable" of the level data named lootId + (level - 1)). With the list empty "drone_iris-1" could not be found,
        the row showed a white icon and "-1%" (user report 2026-10-24)."""
        msg = self.inv_item(x['uid'], x['lootId'], 1, self.hangar_id, level=UPG.drone_level(x))
        msg[1]['item']['inventoryItemAttributes'] = [mod('InventoryItemAttributeModule', key=1, value=str(x['level']))]
        return msg

    def hangar_item(self, iid, loot, count, hangar=0, level=None):
        it = copy(self.item_tpl) if self.item_tpl else mod(
            'HangarShipEquipmentInventoryItem', moduleRepairCosts=0, modifiers='', star=0, UpgradeLevel=[], charges=-1, setBonusAmt=0,
            setBonusInfo=[], attachedAmmo='', extAttributes=[], setBonusActiveConfig1=False, setBonusActiveConfig2=False,
            currentHitPoints=1, maxHitPoints=0, asteroidId=-1, level=0, setBonus=False, modifier='', isUnstableShipUpgrade=False, ships='')
        it.update(itemid=iid, lootId=loot, itemCount=count, hangarId=hangar, lootType=loot_type(loot))
        if GM.unstable(loot) and str(iid) in self.p.d['items']:
            it['isUnstableShipUpgrade'] = True                          # unstable module (ship_module.py)
            it['ships'] = GM.ship_ids(GM.state(self.p, iid)['ships'])   # hint: "Goliath for +%5 damage, ..."
            it['modifiers'] = GM.modifiers_str(self.p, iid)
        if PC.is_item(loot) and str(iid) in self.p.d['items']:
            it.update(PC.hangar_fields(self.p, iid, loot))              # cannon: base damage, attributes, star, UL's ship
        elif RS.is_item(loot) and str(iid) in self.p.d['items']:
            it['modifiers'] = RS.modifiers_str(self.p, iid)             # attributes of the Xeno Resonator (Ö6)
        elif loot.startswith(QF.PREFIX) and QF.state(self.p, iid):
            it['ships'] = GM.ship_ids([QF.state(self.p, iid)['ship']])  # QFC: linked ship and attributes (qfc.modifiers_str)
            it['modifiers'] = QF.modifiers_str(self.p, iid)
        if EX.attached(self.p, loot):
            it['attachedAmmo'] = EX.attached(self.p, loot)      # selected ammo of the auto-buy CPU
        if PETM.has_levels(loot):
            # P.E.T. gear/protocol: the client shows the level as is, "Level: %level%" (TooltipPreparerFactory.ReturnItemLevel),
            # and looks up the description at level - 1 (ReturnItemTips.ReturnItemTip). Before, level - 1 was sent: level 1 showed "Level 0", level 4
            # had the description of level 3 (user report 2026-10-24)
            it['level'] = level if level is not None else self.p.item_level(iid)
        elif UPG.max_level(loot) and str(iid) in self.p.d['items']:
            it['level'] = UPG.item_level(self.p, iid)               # upgrade level (0 = 1 in the client)
            it['UpgradeLevel'] = UPG.badge(loot, it['level'])       # level badge in the inventory and slots
        return it

    def pack(self, items):
        return ('InventoryItemPack', {'items': items})

    def item_updates(self, ids):
        """Items whose hangar changed because they are fitted: the client's inventory and hangar grid (as in move). They were not sent on config loading and
        transfer: loaded lasers showed both in the slot and in the inventory, and those freed did not show in the inventory (live 2026-10-24)."""
        es, hm = self.p.d['items'], self.p.hangar_map()
        ids = sorted(i for i in set(ids) if str(i) in es)
        items = [self.hangar_item(i, es[str(i)], 1, hm.get(i, 0)) for i in ids]
        return [self.inv_item(i, es[str(i)], 1, hm.get(i, 0)) for i in ids] + \
            [self.pack(items[k:k + PACK_MAX]) for k in range(0, len(items), PACK_MAX)]

    def ore_pack(self, types):
        """Ore items in the hangar inventory when the ore count changes (save: InventoryItemPack on collecting, itemCount is the new count)."""
        return self.pack([self.hangar_item(self.item_id(ORES[t]), ORES[t], self.p.ore_count(t)) for t in types if t in ORES])

    # ------------------------------------------------------------ shop
    def drone_slots(self, loot):
        """How many more drones of this type can be bought: Flax/Iris together at most dron_azami (8); Apis and Zeus one each, outside the limit
        (wiki: at most 10)."""
        ds = self.p.d['drones']
        if DRONES[loot].get('single'):
            return 0 if any(x['lootId'] == loot for x in ds) else 1
        return max(0, ITEMS['max_drones'] - sum(1 for x in ds if not DRONES[x['lootId']].get('single')))

    def drone_room(self, loot):
        return self.drone_slots(loot) > 0

    def owned_unique(self, loot):
        """Unique item the player already has: ship, ship design, drone formation, unique drone, P.E.T. The official shop
        stops listing these once bought."""
        if loot == PET_LOOT:
            return self.pet.owned
        if loot.startswith('ship_'):
            if design_base(loot):
                return any(loot in s.get('designs', []) for s in self.p.d['ships'].values())
            return any(s['lootId'] == loot for s in self.p.d['ships'].values())
        if loot in FORMS:
            return loot == 'drone_formation_default' or loot in self.p.d['formations']
        if loot in DRONES and DRONES[loot].get('single'):
            return self.drone_slots(loot) == 0
        if loot.startswith(('package_', 'deal_')):
            return self.package_done(loot)
        return False

    @staticmethod
    def unique_loot(g):
        """An item owned once: ship, ship design, drone formation, P.E.T., unique drone."""
        return g.startswith('ship_') or g in FORMS or g == PET_LOOT or bool(g in DRONES and DRONES[g].get('single'))

    def package_done(self, loot):
        """A unique package (containing a ship, design, formation, P.E.T. or unique drone; Defcom-Raven, Stellar, Dusklight ...) is bought once;
        if it was bought or all of its unique contents are already owned it does not appear in the shop and cannot be bought (player report 2026-10-27:
        the Defcom package stayed in the list after it was bought). The panel's 'paket_siniri' setting turns this off (then owned content is skipped,
        the rest is given: package_fit)."""
        if not SET.get('pack_limit'):
            return False
        unique = [g for g, n in (self.contents(loot, 1) or []) if self.unique_loot(g)]
        if not unique:
            return False
        return loot in self.p.d.get('unique_packages', []) or all(self.owned_unique(g) for g in unique)

    def package_fit(self, grants, owned):
        """What can be given now from a package's contents: an owned ship, P.E.T. and formation are skipped, drones are given as many as there is room
        -> (to be given, [(lootId, skipped count, error key)])."""
        fit, skipped, taken = [], [], 0             # taken: Flax/Iris counted in this package (shared limit)
        for g, n in grants:
            if g.startswith('ship_') and not design_base(g) and g in owned:
                skipped.append((g, 1, 'items_shop_error_ship_contains_ship'))
            elif g == PET_LOOT and self.pet.owned:
                skipped.append((g, 1, 'eqt_error_generic'))
            elif g in FORMS and (g == 'drone_formation_default' or g in self.p.d['formations']):
                skipped.append((g, 1, 'items_drone_formation_already_in_use'))
            elif g in DRONES:
                single = DRONES[g].get('single')
                k = max(0, min(n, self.drone_slots(g) - (0 if single else taken)))
                taken += 0 if single else k
                if k:
                    fit.append((g, k))
                if k < n:
                    skipped.append((g, n - k, 'drone_have_max'))
            else:
                fit.append((g, n))
        return fit, skipped

    @staticmethod
    def skipped_msg(skipped):
        """On-screen message for what could not be given from a package (e.g. "Already owned, not given: P.E.T., 8x Iris")."""
        import galaxy_gates as GALAXY
        name = lambda g: 'P.E.T.' if g == PET_LOOT else g.rsplit('_', 1)[-1].title()
        return GALAXY.screen('Already owned, not given: ' + ', '.join(('%dx %s' % (n, name(g))) if n > 1 else name(g)
                                                                  for g, n, key in skipped))

    def drone_price(self, loot):
        """Flax/Iris: by which drone of the same type it is (wiki: Flax doubles from 100,000 C, Iris rises from 15,000 U)."""
        info = DRONES[loot]
        n = sum(1 for x in self.p.d['drones'] if x['lootId'] == loot)
        return info['currency'], info['prices'][min(n, len(info['prices']) - 1)]

    def world_price(self, loot):
        """The World Editor's price -> (currency field, price) or None; excluding those priced by their own rule (drones, G-HP1, fuel,
        P.E.T. products with levels)."""
        w = WORLD_SHOP.get(loot)
        if not w or w.get('price') is None or loot not in self.catalog or loot in DRONES or loot in (PETM.HULL, PET_FUEL) or PETM.level_prices(loot):
            return None
        return ('credits' if w.get('currency') == 'C' else 'uridium'), w['price']

    def price(self, loot, level=1):
        """-> (currency field, unit price) or None (an item not in the save). "Payment" items in uridium.
        P.E.T. gears/protocols by level (wiki prices, uridium). The world's price comes first."""
        wp = self.world_price(loot)
        if wp:
            return wp
        if loot in DRONES:
            return self.drone_price(loot)
        if loot == PETM.HULL:                        # G-HP1: by which upgrade it is (as many as the P.E.T. level)
            u = self.pet.hull_price()
            return ('uridium', u) if u else None
        prices = PETM.level_prices(loot)
        if prices and loot in self.catalog:
            return 'uridium', prices[min(max(int(level), 1), len(prices)) - 1]
        if loot in self.payment:
            return 'uridium', self.payment[loot]
        if loot in self.credit:
            return 'credits', self.credit[loot]
        it = self.catalog.get(loot)
        if not it or it.get('cost') == 'Payment' or it.get('currency') not in CURRENCY or not it.get('price') or it['price'][0] < 0:
            return None          # a price of 0 is valid: Phoenix is 0 C in the shop
        return CURRENCY[it['currency']], it['price'][0]

    def buy_price(self, loot, level=1):
        """Purchase price: price() x the panel's shop price multiplier (sale and recycling values come from price(), without the multiplier); for purchases
        with uridium, Shop Discount."""
        pr = self.price(loot, level)
        uri = bool(pr) and pr[0] == 'uridium'
        k = SET.multiplier('shop_price', 'uridium' if uri else 'credits') * (1 - self.discount() if uri else 1)
        return pr if not pr or k == 1.0 else (pr[0], pr[1] * k)

    def discount(self):
        """Discount rate for purchases with uridium (items.json shop_discount): Premium 5% (everyone) + the rate if Shop Discount is running."""
        m = ITEMS['shop_discount']
        return round((m['premium_rate'] if self.p.premium else 0.0) + (m['ratio'] if self.p.d.get('shop_discount', 0) > time.time() else 0.0), 4)

    def gate_ok(self, loot):
        if WORLD_SHOP.get(loot, {}).get('on_sale') is False:      # World Editor: a product removed from sale
            return False
        if not EG.in_shop(loot):          # when the panel's setting is off, event appearances only from their events
            return False
        entry = self.extra_entry.get(loot) or FORM_RULES.get(loot)      # Bat is sold only at Halloween (formation_rules.calendar; wiki)
        return self.shop_gate(entry, loot) if self.shop_gate else True

    def shop_list(self, category):
        t = self.lists.get(category)
        if not t:
            return None
        t = copy(t)
        t['currentShipLootId'] = self.p.ship()['lootId']
        if not self.pet.owned:          # fuel with the P.E.T.
            t['itemList'] = [it for it in t['itemList'] if it['lootId'] != PET_FUEL]
        # unique items already owned are not listed (official shop): the list sent after a purchase drops the item at once
        t['itemList'] = [it for it in t['itemList'] if not self.owned_unique(it['lootId'])]
        # those with no counterpart on the server (Assembly parts, keys, packages with undefined contents ...) are not shown
        t['itemList'] = [it for it in t['itemList'] if self.contents(it['lootId'], 1) is not None and self.gate_ok(it['lootId'])]
        if category == 'shipdesign':
            # the extra shop's ship designs (the sourceless designs of E4 and E11, ~270) do not fit in the tab (SHOP_MAX): only those of the ships
            # in the hangar, the current ship's designs first (the excess is cut from the end; those in the save always stay)
            owned = {s['lootId'] for s in self.p.d['ships'].values()}
            extra = lambda it: it['lootId'] in self.extra_entry
            t['itemList'] = [it for it in t['itemList'] if not extra(it) or design_base(it['lootId']) in owned]
            t['itemList'].sort(key=lambda it: extra(it) and design_base(it['lootId']) != t['currentShipLootId'])
        for it in t['itemList']:
            if (self.extra_entry.get(it['lootId']) or {}).get('once'):
                it['maxAmount'] = 1                          # Ö7 packages: once per event
            elif (self.extra_entry.get(it['lootId']) or {}).get('max_count'):
                it['maxAmount'] = self.extra_entry[it['lootId']]['max_count']      # forum 109162: Super Support Package 15
        t['itemList'] = [it for it in t['itemList'] if it['lootId'] != PETM.HULL or self.pet.hull_price()]
        for it in t['itemList']:
            if it['lootId'] == PETM.HULL:
                u = self.pet.hull_price()
                it.update(price=[float(u)], cost='{:,} U.'.format(u))
        for it in t['itemList']:
            if it['lootId'] in self.payment:
                u = self.payment[it['lootId']]
                it.update(price=[float(u)], currency='real', cost='{:,} U.'.format(u), isPaymentItem=0, elite=1)
            elif it['lootId'] in self.credit:
                c = self.credit[it['lootId']]
                it.update(price=[float(c)], currency='virtual', cost='{:,} C.'.format(c), isPaymentItem=0, elite=1)
        for it in t['itemList']:            # the World Editor's price (can change while the game is open: in every list)
            wp = self.world_price(it['lootId'])
            if wp:
                is_credit = wp[0] == 'credits'
                it.update(price=[float(wp[1])], currency='virtual' if is_credit else 'real', cost='{:,} {}'.format(int(wp[1]), 'C.' if is_credit else 'U.'),
                          isPaymentItem=0)
        for it in t['itemList']:
            if it['lootId'] in DRONES:
                cur, u = self.drone_price(it['lootId'])
                it.update(price=[float(u)], cost='{:,} {}'.format(u, 'U.' if cur == 'uridium' else 'C.'))
            prices = PETM.level_prices(it['lootId'])
            if prices:                    # level selector: price per level
                it.update(price=[float(u) for u in prices])
        credit_mult, uridium_mult, disc = SET.multiplier('shop_price', 'credits'), SET.multiplier('shop_price', 'uridium'), self.discount()
        if credit_mult != 1.0 or uridium_mult != 1.0 or disc:              # the panel's shop price multiplier and Shop Discount (uridium): the price and text the client shows
            for it in t['itemList']:      # (the client does not apply UserInventoryModule.activePremiumDiscount to the price, live round 2)
                if it.get('price') and it['price'][0] > 0 and it.get('cost') != 'Payment':
                    price_mult = uridium_mult * (1 - disc) if it.get('currency') == 'real' else credit_mult
                    if it['lootId'] == PET_FUEL:         # unit 0.25 U: not rounded up to the ceiling (it would show 1 U and look 4 times more expensive)
                        it['price'] = [round(u * price_mult, 4) for u in it['price']]
                        it['cost'] = '{:g} U.'.format(round(it['price'][0], 2))
                        continue
                    it['price'] = [float(math.ceil(u * price_mult - 1e-9)) for u in it['price']]
                    it['cost'] = '{:,} {}'.format(int(it['price'][0]), 'U.' if it.get('currency') == 'real' else 'C.')
        for it in t['itemList']:
            prices = PETM.level_prices(it['lootId'])
            if prices:
                # level buttons: the client (UIShopSystem.SetRightNumberLevel) enables button i if i <= MaxNum, MaxNum = the smaller of the affordable
                # amount and maxAmount (if 3, all). The maxAmount in the save was 1 (the account had no P.E.T.), the server did not change it:
                # only level 1 could be selected whatever the P.E.T. level (user 2026-10-18). maxAmount = the highest level the P.E.T. allows
                # (wiki: level 2 P.E.T. 4, level 3 8, 3X 20). Gears sold with a 4th tier go with the "3X" button
                # (save: G-EL1/G-RL1 levelGrades [1,2,3,3X]); the 4th tier of protocols is not sold in the shop, [1,2,3] as in the save
                lv = self.pet.d['level'] if self.pet.owned else 0
                grades = [str(n) for n in range(1, min(len(prices), 3) + 1)]
                if len(prices) > 3 and prices[3] and it['lootId'] in PETM.GEARS:
                    grades.append('3X')
                top = min(len(grades), max(n for n in range(1, len(prices) + 1) if lv >= PETM.level_need(n)))
                it.update(maxAmount=top, maxlevel=top, levelGrades='[%s]' % ','.join(grades))
            if prices and it.get('LevelDataList'):
                # the level button's price and text (ClickToggle: LevelDataList[level]) are the same as what is bought: the ones in the save stayed, on G-HR1
                # 15,000 / 32,000 showed while 32,000 / 55,000 was charged; the panel's multiplier is here too
                rows = it['LevelDataList'] = [dict(r) for r in it['LevelDataList']]
                for r, u0, u in zip(rows, prices, it['price']):
                    if u0:                                 # 0: not sold in the shop (the row in the save stays); u can be 0 with the multiplier (free)
                        r.update(price=int(u), cost='{:,} U.'.format(int(u)))
            if it['lootId'] == PETM.HULL and it.get('LevelDataList'):
                # G-HP1 is a copy of G-REP1 (ek_magaza template): the detail panel and confirmation window read from LevelDataList, in the copy G-REP1's
                # prices stayed (2,500 U. was shown and 25,000 U. charged, live 2026-10-24): in each row the upgrade's price
                it['LevelDataList'] = [dict(r, price=int(it['price'][0]), cost=it['cost']) for r in it['LevelDataList']]
        for it in t['itemList']:
            if it['lootId'] == PET_FUEL:          # at most the free space of the store and as many as the money affords
                pr = self.buy_price(PET_FUEL)
                n = min(self.fuel_room(), int(self.p.d['pilot'].get(pr[0], 0) // pr[1]) if pr[1] > 0 else FREE_COUNT)
                it['maxAmount'] = n if n >= 1 else -1
        if category == 'ammunition':
            for it in t['itemList']:
                pr = self.buy_price(it['lootId'])
                if pr and pr[1] > 0:
                    n = int(self.p.d['pilot'].get(pr[0], 0) // pr[1])
                    it['maxAmount'] = min(n, 2 ** 31 - 1) if n >= 1 else -1
                elif pr:
                    it['maxAmount'] = FREE_COUNT              # free: not the save's amount (what the saved account's money afforded)
        for it in t['itemList']:
            if it.get('amountsSelectable') and it.get('price') and it['price'][0] == 0:
                it['price'] = [FREE_PRICE] + it['price'][1:]
        if self.featured and self.featured[0] == category and time.time() < self.featured[2]:
            # the shop opened from the payment button (payment.py): the client opens the shop with 'extras,resource_key_access-dse' and selects that product, or the first
            # product if it is not in the list (ExpeditionBuyTicketCommandHandler, CreateItem): the ticket is not in this list (live round 2)
            t['itemList'] = [it for it in t['itemList'] if it['lootId'] != 'resource_key_access-dse']
            t['itemList'].sort(key=lambda it: it['lootId'] != self.featured[1])
        if len(t['itemList']) > SHOP_MAX:
            # the list counter is one byte (the client's reading): the excess cannot be encoded, the tab would never open; those at the end (extra products) are not shown.
            # Event rows (extra_shop calendar) are not cut: so that the event's keys and packages are not lost when the tab is full
            self.log('   shop: %s tab has %d products, showing the first %d' % (category, len(t['itemList']), SHOP_MAX))
            evt = lambda it: bool((self.extra_entry.get(it['lootId']) or {}).get('calendar'))
            rest = {id(it) for it in [it for it in t['itemList'] if not evt(it)][:max(0, SHOP_MAX - sum(map(evt, t['itemList'])))]}
            t['itemList'] = [it for it in t['itemList'] if evt(it) or id(it) in rest][:SHOP_MAX]
        return ('ShopItemListCommand', t)

    def feature(self, category, loot, sec=15.0):
        """This product comes first in the next lists (sec seconds) of this category."""
        self.featured = (category, loot, time.time() + sec) if loot else None

    def fuel_room(self):
        """Free space in the P.E.T.'s fuel tank (0 if there is no P.E.T.)."""
        return max(0, PETM.PET['max_fuel'] - int(self.pet.d['fuel'])) if self.pet.owned else 0

    def reason(self, key):
        """Raw text from NEDENLER in the client's language (Turkish for a Turkish client, English for the others)."""
        en, tr = REASONS[key]
        return raw_msg(tr if self.lang == 'tr' else en)

    def money_msgs(self):
        pl = self.p.d['pilot']
        return [legacy('0|A|C|%d|%d' % (pl.get('credits', 0), pl.get('uridium', 0))),
                self.inv_item(self.item_id('currency_uridium'), 'currency_uridium', pl.get('uridium', 0)),
                self.inv_item(self.item_id('currency_credits'), 'currency_credits', pl.get('credits', 0))]

    def quick_buy_status(self, menu_id):
        """Quick-buy item on the shortcut bar: active/inactive depending on whether the money suffices (save: the ttip_currency_missing row)."""
        base = self.p.menu_status_cache.get(menu_id)
        pr = self.buy_price(menu_id[4:])
        if base is None or not pr:
            return None
        st = copy(base)
        ok = self.p.d['pilot'].get(pr[0], 0) >= math.ceil(pr[1] * max(st.get('counterValue', 1), 1) - 1e-9)
        st['activatable'] = ok
        for tip in ('toolTipSlotBar', 'toolTipItemBar'):
            lines = (st.get(tip) or {}).get('commandList')
            if lines is None:
                continue
            lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_currency_missing']
            if not ok:
                lines.append(copy(keyed('ttip_currency_missing', CURRENCY='ttip_' + pr[0])['commandList'][0]))
        return st

    def quick_buy_msgs(self, currency=None):
        """Current state of the quick-buy items when money changes (sent after every purchase and reward in the save)."""
        out = []
        for mid in sorted(self.p.menu_status_cache):
            if mid.startswith('buy_'):
                pr = self.price(mid[4:])
                if pr and (currency is None or pr[0] == currency):
                    st = self.quick_buy_status(mid)
                    if st:
                        out.append(('MenuItemStatusCommand', st))
        return out

    def buy_cmd(self, loot, category, buy_category, result, amount=0, error=None, equip_ids=(), free=0, success=None):
        sub = self.p.d.get('booster_subscription', {}).get(loot)
        return ('ShopItemBuyCommand', dict(
            canEquipItemId=[float(i) for i in equip_ids], slotSet='', hintEquipTo='hint_equip_to_ship' if equip_ids else '',
            canBeSubscribedTo=BOOSTER.is_booster(loot), userHasBoosterPackage=False, buyCategory=buy_category, resultId=result,
            configId=self.p.active_config if equip_ids else 0, errorMessage=error, lootId=loot, category=category,
            hangarId=self.hangar_id if equip_ids else 0, realBuyAmount=amount, isSubscriptionRunning=bool(sub),
            allowAutoEquip=1 if equip_ids else 0, sucessMessage=success, emptySlotCount=free, droneId=0,
            isSubscriptionPaused=bool(sub and sub.get('state') == 'paused'),
            secondsLeft=int(BOOSTER.left(self.p, loot)) if sub else 0, action='toggleSubscription' if sub else ''))

    def toggle_subscription(self, loot, category='', buy_category=''):
        """Booster subscription (official forum 127558 Hangar-Booster: "ABONE OL" / "ABONELİĞİ BİTİR"; the client's button
        ShopItemBuyRequest action 'toggleSubscription'): when subscribed it is bought once; before the time runs out it is bought again if the uridium suffices,
        if not the subscription pauses until there is money (subscription_tick)."""
        if not BOOSTER.is_booster(loot):
            return [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('shop_item_not_found'))]
        subs = self.p.d.setdefault('booster_subscription', {})
        if loot in subs:
            with self.p.lock:
                del subs[loot]
                self.p.dirty = True
            self.log('   booster subscription ended: %s' % loot)
            return [self.buy_cmd(loot, category, buy_category, 1, success=self.reason('subscription_ended'))]
        msgs = self.buy(loot, 1, category, buy_category)
        if not BOOSTER.left(self.p, loot):
            return msgs                                  # could not be bought (no money): the subscription does not start
        with self.p.lock:
            subs[loot] = {'state': 'active'}
            self.p.dirty = True
        self.log('   booster subscription: %s' % loot)
        return msgs + [self.buy_cmd(loot, category, buy_category, 1, success=self.reason('subscribed'))]

    def subscription_tick(self, now):
        """Boosters with a running subscription: when under 60 s remain they are bought again if the uridium suffices, otherwise they pause."""
        msgs = []
        for loot, sub in list(self.p.d.get('booster_subscription', {}).items()):
            if BOOSTER.left(self.p, loot, now) > 60:
                continue
            pr = self.buy_price(loot)
            ok = pr and (self.p.d['pilot'].get('uridium', 0) if pr[0] == 'uridium' else self.p.d['pilot'].get('credits', 0)) >= pr[1]
            state = 'active' if ok else 'paused'
            if ok:
                msgs += [m for m in self.buy(loot, 1) if m[0] != 'ShopItemBuyCommand']
            if sub.get('state') != state:
                with self.p.lock:
                    sub['state'] = state
                    self.p.dirty = True
                if not ok:
                    self.log('   booster subscription paused (no money): %s' % loot)
        return msgs

    def free_slots(self, slot, cid=None):
        return max(0, self.capacity(slot) - len(self.p.config(cid).get(slot, [])))

    def fits(self, slot, iid, loot, pending=()):
        """Can a newly arrived item be fitted to the active config by itself (or suggested): move()'s rules (the module's ship and
        type, slot CPU, repair robot); the player fits QFC and particle items. pending: other items suggested for fitting in the same purchase.
        User report 2026-10-25: a reward module was fitted even if it was not the active ship's."""
        cur = list(self.p.config().get(slot, [])) + [i for i in pending if slot_of(self.p.d['items'].get(str(i), '')) == slot]
        loots = [self.p.d['items'].get(str(i), '') for i in cur]
        if slot == 'upgrades':
            return GM.equip_allowed(self.p, iid, self.p.ship()['lootId']) and not GM.type_taken(self.p, iid, cur)
        if slot == 'QuantumFluidCore' or slot in PC.SLOTS:
            return False
        if slot == 'extra':
            on_drones = [self.p.d['items'].get(str(i), '') for ids in self.p.drone_config().values() for i in ids]   # those in the drones' config too
            return not (EX.slot_bonus_of([loot]) and EX.slot_bonus_of(loots)) and loot not in on_drones and \
                not (loot.startswith(REPBOT) and any(l.startswith(REPBOT) for l in loots + on_drones))
        return True

    @staticmethod
    def contents(loot, amount):
        """What is given on purchase [(lootId, count)]: ammo, equipment and the ship itself, packages from items.json odeme_paketleri.
        None: the server cannot give this item yet (design, key ...). A ship is always 1 piece."""
        if loot in NO_EFFECT:
            return None
        pk = ITEMS['payment_packages'].get(loot)
        if pk:
            if any(l.startswith('ship_') and not design_base(l) and l not in ITEMS['ships'] for l, n in pk):
                return None          # a ship that is not on the server (Paladin, Basilisk ...; stage 6): the package is not shown
            return [(l, 1 if l.startswith('ship_') else n * amount) for l, n in pk]
        if loot.startswith('ship_') and (loot in ITEMS['ships'] or design_base(loot)):
            return [(loot, 1)]
        if loot in DRONES or loot in FORMS or loot == PET_LOOT or loot == PETM.HULL:
            return [(loot, 1)]
        if loot in PETM.DESIGNS:                     # P.E.T. design: into the inventory, fitted to the P.E.T.'s appearance slot
            return [(loot, amount)]
        if BOOSTER.is_booster(loot):
            return [(loot, amount)]
        if loot == 'resource_logfile' or loot in LOOT.KEYS or loot in ASSEMBLY_PARTS:   # log disc; loot keys; Assembly ingredient
            return [(loot, amount)]
        if loot == 'resource_key_access-dse':        # DSE Travel Permit: Deep Space Echoes'un bileti (echoes.py)
            return [(loot, amount)]
        if loot == PET_FUEL:                         # P.E.T.'in deposuna (_reward)
            return [(loot, amount)]
        if loot in PASS_ITEMS or loot in EVENT_ITEMS:                                # Gold Pass, Battle Pass, points, Monthly Deluxe; event currencies
            return [(loot, amount)]
        if loot.startswith(('captain_', 'resource_collectable_energy-')) or loot in NEW_RESOURCES or loot in RS.SOURCES:  # + Ö6 resonator resources
            return [(loot, amount)]
        if loot.startswith('ammunition_') or slot_of(loot) or loot in DESIGNS or PETM.slot_for(loot) in ('gears', 'protocols'):
            return [(loot, amount)]
        if loot in TECH.ITEMS:                         # technology item (Explosive Charging Blob: extra shop)
            return [(loot, amount)]
        return None

    def buy(self, loot, amount, category='', buy_category='', quick=False, pet_name='', level=1):
        amount = max(1, int(amount or 1))
        try:                                        # the 3X button sends the level as "3X" (levelGrades): 4th tier
            level = 4 if str(level).upper() == '3X' else max(1, int(level))
        except (TypeError, ValueError):
            level = 1
        if not PETM.has_levels(loot):
            level = 1
        elif level > len(PETM.level_prices(loot)) or not PETM.level_prices(loot)[level - 1]:
            # a tier not in the shop: the 3X of gears, the 4th level of protocols other than AI-ECO (save; client text "You can't
            # purchase this P.E.T. Gear level from the shop")
            self.log('   no purchase: %s level %d (not sold in the shop)' % (loot, level))
            return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('pet_gear_shop_level_limit'))]
        elif level > 1 and (not self.pet.owned or self.pet.d['level'] < PETM.level_need(level)):
            # wiki: P.E.T. level 4 for a level 2 gear/protocol, 8 for level 3, 20 for level 4 (client: pet_gear_shop_level_limit)
            self.log('   no purchase: %s level %d (P.E.T. level %d required)' % (loot, level, PETM.level_need(level)))
            return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('pet_gear_shop_level_limit'))]
        if self.package_done(loot) and loot in self.p.d.get('unique_packages', []):     # a unique package once (panel: paket_siniri;
            # if its contents already exist the rules below give the game's own error: items_shop_error_ship_contains_ship ...)
            self.log('   no purchase: %s (unique package already bought)' % loot)
            return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('shop_item_not_found'))]
        if not self.gate_ok(loot):                  # Ö7: a package outside its event, already bought (once) or outside the level
            self.log('   no purchase: %s (not sold now)' % loot)
            return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('shop_item_not_found'))]
        if (self.extra_entry.get(loot) or {}).get('once'):
            amount = 1
        elif (self.extra_entry.get(loot) or {}).get('max_count'):
            amount = min(amount, self.extra_entry[loot]['max_count'])
        if loot == PET_FUEL:                        # as much as the store's free space (the excess is not charged)
            if self.fuel_room() <= 0:
                self.log('   no purchase: P.E.T. fuel tank is full or there is no P.E.T.')
                return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=self.reason('fuel_full'))]
            amount = min(amount, self.fuel_room())
        pr = self.buy_price(loot, level)
        grants = self.contents(loot, amount)
        is_ammo = loot.startswith('ammunition_')
        fail = lambda key: [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg(key))]
        if not pr or not grants:
            self.log('   no purchase: %s (%s)' % (loot, 'not in the shop' if not pr else 'contents not on the server yet'))
            return fail('shop_item_not_found')
        owned = {s['lootId'] for s in self.p.d['ships'].values()}
        pkg = loot.startswith(('package_', 'deal_'))
        skipped = []
        if pkg:      # package (S-OS-01 = Yamato + Defcom, Stellar): an owned ship, P.E.T., formation and drone room are skipped, the rest is given
            grants, skipped = self.package_fit(grants, owned)
            if not grants:
                self.log('   no purchase: %s (all of its contents already exist)' % loot)
                return fail(skipped[0][2])
        if any(g in owned for g, n in grants if g.startswith('ship_') and not design_base(g)):
            self.log('   no purchase: %s (this ship already exists)' % loot)
            return fail('items_shop_error_ship_contains_ship')        # the game's rule: one of each ship type
        for g, n in ([] if pkg else grants):
            base = design_base(g)
            if base and base not in owned:
                self.log('   no purchase: %s (%s missing)' % (g, base))
                return fail('dse_ship_not_exist')                      # a design can only be bought while owning that ship
            if base and any(g in s.get('designs', []) for s in self.p.d['ships'].values()):
                self.log('   no purchase: %s (design already exists)' % g)
                return fail('items_design_already_in_use')
        for g, n in grants:
            if g in DRONES and not self.drone_room(g):
                self.log('   no purchase: %s (at most %d drones)' % (g, ITEMS['max_drones']))
                return fail('drone_have_max')
            if g in FORMS and (g == 'drone_formation_default' or g in self.p.d['formations']):
                self.log('   no purchase: %s (formation already exists)' % g)
                return fail('items_drone_formation_already_in_use')
            if g == PET_LOOT and self.pet.owned:
                self.log('   no purchase: P.E.T. already exists')
                return fail('eqt_error_generic')
        if amount != 1 and any(g.startswith('ship_') or g in DRONES or g in FORMS or g in (PET_LOOT, PETM.HULL) for g, n in grants):
            amount = 1          # the contents also by 1 piece (otherwise amount times the resource was given for the price of 1)
            grants = self.contents(loot, 1)
            if pkg:
                grants, skipped = self.package_fit(grants, owned)
        cur, unit = pr
        cost = math.ceil(unit * amount - 1e-9)
        with self.p.lock:
            pl = self.p.d['pilot']
            if pl.get(cur, 0) < cost:
                self.log('   not enough money: %s x%d = %d %s (have %d)' % (loot, amount, cost, cur, pl.get(cur, 0)))
                return fail('not_enough_' + cur)
            pl[cur] -= cost
            self.p.dirty = True
        RT.money(self.p, cur, -cost, RT.buy_desc(loot), loot, amount)           # account history
        msgs = self.quick_buy_msgs(cur) + self.money_msgs()
        equip_ids, free = [], 0
        for g, n in grants:
            if design_base(g):
                sid = self.own_ship(design_base(g))
                if sid is None:                           # design in the package, no ship: waits in the store (pending_designs)
                    if not self.p.resource(g):
                        self.p.add_resource(g, 1)
                    self.log('   design stored: %s (%s missing)' % (g, design_base(g)))
                    continue
                if g in self.p.ship(sid).get('designs', []):
                    continue
                with self.p.lock:
                    self.p.ship(sid).setdefault('designs', []).append(g)
                    self.p.dirty = True
                msgs += [('ShipDesignAddedCommand', {'lootId': g}), legacy('0|LM|ST|LOT|%s|1' % g)]
                self.log('   new design: %s (%s)' % (g, design_base(g)))
            elif g.startswith(('resource_', 'currency_', 'tech_', 'pet_designs_', 'captain_')) or (pkg and BOOSTER.is_booster(g)):
                msgs += self.reward(g, n)                  # package contents: resource store, money, technology, hourly booster
            elif g.startswith('ship_'):
                sid = self.p.add_ship(g)
                msgs.append(legacy('0|LM|ST|LOT|%s|1' % g))
                msgs += self.pending_designs(g)            # designs that arrive while the ship is missing (Assembly, box, package)
                msgs += self.ship_count_msgs([g])          # base ship of the Plus recipe (Assembly counter)
                self.log('   new ship: %s (shipId %d, hangarId %d)' % (g, sid, self.p.ship(sid)['hangarId']))
            elif g in DRONES:                              # all the drones in the package (Stellar: 8 Iris), as many as there is room (package_fit)
                for _ in range(n):
                    did = self.p.add_drone(g)
                    msgs.append(self.drone_item(self.p.drone(did)))      # can be upgraded in Assembly
                msgs += [legacy('0|LM|ST|LOT|%s|%d' % (g, n))] + self.drone_msgs() + self.formation_status_msgs()
                self.p.ach('formation', drone=len(self.p.d['drones']))
                self.log('   new drone: %s x%d (id %d, total %d)' % (g, n, did, len(self.p.d['drones'])))
            elif g in FORMS:
                with self.p.lock:
                    self.p.d['formations'].append(g)
                    self.p.dirty = True
                st = self.p.menu_status(g)
                msgs += ([('MenuItemStatusCommand', st)] if st else []) + [legacy('0|LM|ST|LOT|%s|1' % g)]
                self.log('   new formation: %s' % g)
            elif g.startswith('ammunition_'):
                before = self.p.ammo(g)
                total = self.p.add_ammo(g, n)
                iid = self.item_id(g)
                st = self.p.menu_status(g)
                if st:
                    msgs.append(('MenuItemStatusCommand', st))
                if before == 0:
                    msgs.append(('RefreshSelectedUICategoryCommand', {}))
                kind = loot_kind(g)
                msgs += [self.inv_item(iid, g, total), self.pack([self.hangar_item(iid, g, total)]),
                         legacy('0|LM|ST|%s|%s|%d' % (kind, g, n))]
            elif g == PETM.HULL:
                msgs += self.pet.upgrade_hull()            # +10,000 max HP (wiki), gauge if in space
            elif g == PET_LOOT:
                msgs += self.grant_pet(pet_name)
            elif g == 'resource_logfile':
                msgs += self.reward(g, n)                  # the pilot skill tree's log disc (the gate generator's counter)
            elif BOOSTER.is_booster(g):
                BOOSTER.add(self.p, g, n)                  # 10 hours each; added to the same booster's duration
                msgs += [BOOSTER.update_cmd(self.p), legacy('0|LM|ST|LOT|%s|%d' % (g, n))] + self.apply_stats()
                self.log('   booster: %s x%d (%d s left)' % (g, n, BOOSTER.left(self.p, g)))
            elif not slot_of(g):
                for _ in range(n):            # drone design, P.E.T. gear/protocol: into the inventory (fitted in the hangar)
                    iid = self.p.new_item(g, level)
                    msgs += [self.inv_item(iid, g, 1), self.pack([self.hangar_item(iid, g, 1)])]
                msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (g, n)))
                if level > 1:
                    self.log('   level %d: %s' % (level, g))
            else:
                room = self.free_slots(slot_of(g))
                free += room
                got = 0
                for _ in range(n):
                    iid = self.p.new_item(g)
                    msgs += [self.inv_item(iid, g, 1), self.pack([self.hangar_item(iid, g, 1)])]
                    if got < room and self.fits(slot_of(g), iid, g, equip_ids):
                        equip_ids.append(iid)
                        got += 1
                if g == 'equipment_extra_hmd-07':
                    msgs += self.p.menu_changes([g])      # HM-7: appears on the shortcut bar immediately even if not fitted
                msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (g, n)))
        self.log('   purchased: %s x%d = %d %s (remaining %d)' % (loot, amount, cost, cur, self.p.d['pilot'][cur]))
        if skipped:
            self.log('   not given from the package (already owned): %s' % ', '.join('%s x%d' % (g, n) for g, n, key in skipped))
            msgs.append(self.skipped_msg(skipped))
        if pkg and any(self.unique_loot(g) for g, n in self.contents(loot, 1) or []):
            with self.p.lock:
                self.p.d.setdefault('unique_packages', []).append(loot)      # bought once (package_done)
                self.p.dirty = True
        for cb in self.on_bought:                      # Ö7 shops (stores.py)
            msgs += cb(loot, amount) or []
        for g, n in grants:                            # hint (once): second ship -> ship warp, first equipment -> fit in the hangar
            msgs += self.p.hint(IP.for_purchase(self.p, g, bool(slot_of(g)) and not g.startswith('ammunition_')))
        if not quick:
            buy = self.buy_cmd(loot, category, buy_category, 1, amount, equip_ids=equip_ids, free=free)
            lst = self.shop_list(category)
            # when the list arrives the client (ShopItemListCommandHandler -> CreateItem -> OnClickItem) hides the purchase window:
            # the question "You have free slots on your ship, equip it?" vanished as soon as it appeared (live test 2026-10-18). If there is a
            # question the list goes first, the question after; otherwise the order in the save (ShopItemBuyCommand, then the list).
            msgs += ([lst, buy] if equip_ids else [buy, lst]) if lst else [buy]
        return msgs

    def grant_pet(self, name=''):
        """P.E.T. (shop, package, Assembly, box): given if missing; icon on the bar, the window's buttons."""
        if self.pet.owned:
            return []
        with self.p.lock:
            self.p.d['pet'] = PETM.new_pet(self.p)
            if len((name or '').strip()) >= 3:              # the "P.E.T. name" field in the shop
                self.p.d['pet']['name'] = name.strip()[:20]
            self.p.dirty = True
        stored = self.p.resource(PET_FUEL)              # fuel won before owning a P.E.T. (pass, quest) waited in storage: into the tank
        if stored:
            add = max(0, min(stored, PETM.PET['max_fuel'] - self.p.d['pet']['fuel']))
            with self.p.lock:
                self.p.d['pet']['fuel'] += add
            self.p.add_resource(PET_FUEL, -add)
        self.log('   new P.E.T.: %s' % PET_LOOT)
        return [('PetPurchasedCommand', {}), self.pet.init_msg(), self.p.generate('@arayuz'),    # P.E.T. icon on the bar
                legacy('0|LM|ST|LOT|%s|1' % PET_LOOT)]

    def prize(self, loot, n, source='mod'):
        """Quest, gate, mode, event and Dispatch reward: reward()'s panel-aware path. Credits, uridium, EP and honor with their own multipliers;
        stackable items (ammo, resources, keys, technology items) with the 'mod_odul' multiplier; single items (ship, laser, design,
        booster, P.E.T., ticket) as they are. source: the panel's sub-setting (gorev, kapi, mod). The shop, package, exchange and GM paths use reward()
        (not scaled)."""
        key = PRIZE_CURRENCY.get(loot)
        if key:
            n = SET.amount(key, n, source)
        elif loot.startswith(('ammunition_', 'resource_', 'tech_')) and loot not in PASS_ITEMS:
            n = SET.amount('mode_reward', n, source)
        return self.reward(loot, n) if n > 0 else []

    def reward(self, loot, n, level=1):
        msgs = self._reward(loot, n, level)
        if loot in (GM.SHARD, GM.CHIP) or PC.restabilizable(loot):
            # the Restabilize tab takes its cost counters and the list from this command (in the save it comes again when the inventory changes);
            # when an OptiGrad Chip / Unstable Shard arrived the tab showed 0 and kept the button disabled (live test H70)
            msgs = list(msgs or []) + [GM.list_cmd(self.p)]
        return msgs

    def _reward(self, loot, n, level=1):
        """Quest reward (other than credits/uridium/EP/honor): ammo, equipment (fitted to the active ship if there is a free slot; as in the save;
        not fitted if "Auto-equip new items" is off), ship, ship design, ore, booster, gate energy, log disc. A reward with no counterpart on the server (Assembly
        resource, voucher ...) is kept in the profile (diger_esyalar). level: the level of a P.E.T. gear/protocol with levels (Assembly recipes)."""
        msgs = []
        RT.note(self.p, 'received_item', loot, n)                              # logbook
        if loot == PET_LOOT:                       # on the reward path the P.E.T. fell into the store and vanished (live test H43)
            return self.grant_pet()
        got = SE.reserve(loot, n)
        if got is not None:                        # Season Pass reserve: its contents (season.py; before, it fell into the invisible store)
            for l, k in got:
                msgs += self.reward(l, k)
            self.log('   reserve opened: %s x%d -> %s' % (loot, n, ', '.join('%s x%d' % x for x in got)))
            return msgs
        if loot in PASS_ITEMS and self.tickets:                               # Season Pass points, Gold/Extra Gold, Battle Pass, Deluxe
            season, bp, go = self.tickets
            if loot == 'resource_battle-pass':
                return bp.grant_pass(n)
            if loot == 'resource_monthly-deluxe':
                return go.grant_deluxe(n)
            return season.grant(loot, n)
        if self.new_ and (loot.startswith(('captain_', QF.PREFIX)) or PC.is_item(loot)):     # N.O.V.A., QFC, cannon/driver (new_systems.py)
            got = self.new_.reward(loot, n)
            if got is not None:
                return got
        if loot in PAY_CURRENCY:                    # money / EP in the package (not counted in the account history or the Uridium Bank)
            field, kind = PAY_CURRENCY[loot]
            with self.p.lock:
                pl = self.p.d['pilot']
                pl[field] = pl.get(field, 0) + n
                self.p.dirty = True
            if loot == 'currency_experience':
                tot = self.p.gain()                         # the level is recomputed from EP
                msgs.append(legacy('0|LM|ST|EP|%d|%d|%d' % (n, tot['ep'], tot['level'])))
            else:
                msgs += self.money_msgs() + [legacy('0|LM|ST|%s|%d|%d' % (kind, n, self.p.d['pilot'][field]))]
            return msgs
        if loot in ITEMS['shop_discount']['day']:  # Shop Discount (daily login): the discount's duration is added (the gauge at the next login)
            with self.p.lock:
                d = self.p.d
                d['shop_discount'] = max(d.get('shop_discount', 0), time.time()) + ITEMS['shop_discount']['day'][loot] * 86400 * n
                self.p.dirty = True
            return msgs + [legacy('0|LM|ST|LOT|%s|%d' % (loot, n))]
        if loot.startswith('tech_'):                # technology item (Assembly and packages): to the counter
            TECH.add(self.p, loot, n)
            st = self.p.menu_status(loot)
            return msgs + ([('MenuItemStatusCommand', st)] if st else []) + [legacy('0|LM|ST|LOT|%s|%d' % (loot, n))]
        if loot.startswith('ammunition_'):
            total = self.p.add_ammo(loot, n)
            iid = self.item_id(loot)
            st = self.p.menu_status(loot)
            if st:
                msgs.append(('MenuItemStatusCommand', st))
            kind = loot_kind(loot)
            msgs += [self.inv_item(iid, loot, total), self.pack([self.hangar_item(iid, loot, total)]), legacy('0|LM|ST|%s|%s|%d' % (kind, loot, n))]
        elif slot_of(loot):
            slot, equipped = slot_of(loot), False
            auto = self.p.d.get('auto_equip', True)     # Settings > Gameplay "Auto-equip new items" (if off it stays in the inventory)
            for _ in range(n):
                iid = self.p.new_item(loot)
                msgs += [self.inv_item(iid, loot, 1), self.pack([self.hangar_item(iid, loot, 1)])]
                if auto and self.free_slots(slot) > 0 and not pet_only(loot) and self.fits(slot, iid, loot):
                    with self.p.lock:
                        self.p.config().setdefault(slot, []).append(iid)
                        self.p.sync_equipment()
                        self.p.dirty = True
                    msgs.append(self.inv_item(iid, loot, 1, self.hangar_id))
                    equipped = True
            if equipped:
                msgs += [self.equipment_cmd()] + self.apply_stats()
            msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
            if GM.unstable(loot):                       # Restabilize list (live test H41: it came only at login)
                msgs.append(GM.list_cmd(self.p))
        elif loot.startswith('ship_') and loot in ITEMS['ships']:
            if loot not in {s['lootId'] for s in self.p.d['ships'].values()}:
                self.p.add_ship(loot)
                msgs.append(legacy('0|LM|ST|LOT|%s|1' % loot))
                msgs += self.pending_designs(loot) + self.ship_count_msgs([loot])
                if self.ships_tpl:
                    msgs.append(self.ships_cmd())              # new ship in the hangar list (Assembly, gate, box)
        elif design_base(loot) and self.grant_design(loot):
            msgs += [('ShipDesignAddedCommand', {'lootId': loot}), legacy('0|LM|ST|LOT|%s|1' % loot)]
        elif loot in ORES.values():
            # reward ore all comes even if the cargo is full, the cargo exceeds the maximum (official Skylab FAQ: "transferred to your ship regardless",
            # "temporarily greater cargo capacity"; a 10,000 Seprom reward in a 9,000 cargo). Ore/boxes are not collected until room is freed.
            # It used to give only as much as there was room: Assembly's 5,000 Seprom vanished in a full cargo (user report 2026-10-24)
            t = next(k for k, v in ORES.items() if v == loot)
            if n > 0:
                msgs += [('AttributeOreCountUpdateCommand', {'oreCountList': self.p.add_ores({t: n})}), self.ore_pack([t]),
                         ('LMCollectResourcesCommand', dict(priorityMode=mod('LogMessengerPriorityModule', priorityModeValue=0),     # the log line
                                                            contentList=[mod('OreCountModule', oreType=mod('OreTypeModule', typeValue=t), count=n)]))]
        elif loose_item(loot):     # drone / P.E.T. design, P.E.T. gear and protocol (gate, box, Assembly, Pass): into the inventory, fitted in the hangar
            for _ in range(n):
                iid = self.p.new_item(loot, level if PETM.level_prices(loot) else 1)
                msgs += [self.inv_item(iid, loot, 1), self.pack([self.hangar_item(iid, loot, 1)])]
            msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
        elif BOOSTER.is_booster(loot):   # reward booster: count in hours, runs while in the game (daily login, quest)
            BOOSTER.add(self.p, loot, seconds=n * 3600)
            msgs += [BOOSTER.update_cmd(self.p), legacy('0|LM|ST|LOT|%s|%d' % (loot, n))] + self.apply_stats()
        elif loot == 'resource_extra-energy' and self.gates:
            msgs += self.gates.bonus_energy(n)       # the Galaxy Gate generator's free energy
        elif loot in DRONES:                           # Assembly/Dispatch: drone (Flax/Iris at most dron_azami, Apis/Zeus one each)
            for _ in range(n):
                if not self.drone_room(loot):
                    break
                msgs.append(self.drone_item(self.p.drone(self.p.add_drone(loot))))     # can be upgraded in Assembly
            msgs += [legacy('0|LM|ST|LOT|%s|%d' % (loot, n))] + self.drone_msgs() + self.formation_status_msgs()
        elif loot in FORMS:
            if loot not in self.p.d['formations']:
                with self.p.lock:
                    self.p.d['formations'].append(loot)
                    self.p.dirty = True
            st = self.p.menu_status(loot)
            msgs += ([('MenuItemStatusCommand', st)] if st else []) + [legacy('0|LM|ST|LOT|%s|1' % loot)]
        elif loot == 'resource_repairvoucher' and self.gates:
            with self.p.lock:                          # repair voucher: on the death screen (world.vouchers)
                self.gates.d['voucher'] += n
                self.p.dirty = True
            msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
        elif loot == 'resource_pet-fuel' and self.pet and self.pet.owned:
            before = self.p.d['pet'].get('fuel', 0)
            add = max(0, min(n, PETM.PET['max_fuel'] - before))
            with self.p.lock:
                self.p.d['pet']['fuel'] = before + add
                self.p.dirty = True
            if add:
                msgs += [legacy('0|LM|ST|LOT|%s|%d' % (loot, add)), self.pet.fuel_msg()]     # the P.E.T. window's fuel bar
                if before <= 0:                        # the window still said "no fuel" (hasFuel false since it ran dry): launch possible again
                    msgs.append(self.pet.init_msg())
            if add < n:                                # storage full: client log_msg_not_gather_pet_fuel ("cargo is full")
                msgs.append(('PetFuelCargoFullMessage', {}))
        elif loot == 'resource_logfile' and self.gates:
            with self.p.lock:                          # log disc: converted to pilot points (skill_tree.py)
                self.gates.d['log_disk'] += n
                self.p.dirty = True
            msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
        elif loot == 'resource_wordpuzzle-letter' and self.hitac:
            msgs += self.hitac.grant_letter(n)         # the letter in the Hitac box: Word Puzzle (hitac_lottery.py)
        elif loot == 'resource_collectable_chromin' and self.chromin:
            msgs += self.chromin.gain(n)               # Chromin Rush: 160,000 limit, the excess to credits (chromin.py)
        else:                            # no system spends it yet (Assembly resources, vouchers ...): in the store (player_profile.add_resource)
            total = self.p.add_resource(loot, n)
            if loot.startswith('resource_'):
                msgs += self.resource_msgs(loot, total, n)
            elif design_base(loot):     # design of a ship not owned yet (pending_designs): the box gave nothing visible (player report 2026-11-03)
                msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
            if loot in LOOT.KEYS and LOOT.key_line(self.p, LOOT.KEYS[loot]):         # loot key: HUD counter
                msgs.append(legacy(LOOT.key_line(self.p, LOOT.KEYS[loot])))
            if hidden(loot):        # invisible in the inventory, no system reads it: this reward is lost (test_odul_yollari catches it)
                self.log('   WARNING: reward not recognized, will not show in the inventory: %s x%d (kept in the store, total %d)' % (loot, n, total))
            else:
                self.log('   reward in the store: %s x%d (total %d)' % (loot, n, total))
        return msgs

    def rescue_depot(self):
        """Moves items that had fallen into the invisible store because they were not recognized earlier on the reward path to where they belong (2026-10-22: Season Pass's Hyperion drone
        design and reserves, Assembly's P.E.T. protocols): designs, gears and protocols to the inventory; reserves are opened (the same
        contents are merged so the logbook does not fill up). Those still not recognized stay in the store, with a warning in the log. The session calls this once per connection,
        before the login messages -> the moved [(lootId, count)]."""
        moved, opened = [], {}
        # designs whose ship is bought later: a ship bought from the shop did not hand out the waiting ones (user report 2026-10-24: Assembly's
        # Spectrum Legend was also missing after Spectrum was bought)
        for base in sorted({s['lootId'] for s in self.p.d['ships'].values()}):
            moved += [(f['lootId'], 1) for n_, f in self.pending_designs(base)]
        for loot, n in sorted(self.p.d.get('other_items', {}).items()):
            n = int(n)
            if n <= 0 or not hidden(loot):
                continue
            if loose_item(loot):
                for _ in range(n):
                    self.p.new_item(loot)
            elif loot in SE.RESERVES:
                for l, k in SE.reserve(loot, n):
                    opened[l] = opened.get(l, 0) + k
            else:
                self.log('   WARNING: item in the store not visible in the inventory: %s x%d' % (loot, n))
                continue
            self.p.add_resource(loot, -n)
            moved.append((loot, n))
        for l, k in sorted(opened.items()):
            self.reward(l, k)
        if moved:
            self.log('   rescued from the store: %s%s' % (', '.join('%s x%d' % x for x in moved),
                                                    ' -> %s' % ', '.join('%s x%d' % x for x in sorted(opened.items())) if opened else ''))
        return moved

    def resource_msgs(self, loot, total, n):
        """Counter of a resource in the store (InventoryItemUpdatedCommand: Assembly ingredient counters come from here; live test H31) and the log line
        (if n > 0 "... obtained")."""
        iid = self.item_id(loot)
        items = [] if loot in NO_TRAITS else [self.inv_item(iid, loot, total), self.pack([self.hangar_item(iid, loot, total)])]
        return items + ([legacy('0|LM|ST|LOT|%s|%d' % (loot, n))] if n > 0 else [])

    # ------------------------------------------------------------ selling
    def sale_value(self, loot, n=1):
        """Sale -> (currency field, amount) or None. The client's own value (the item's "sellable" trait, shown as credits in the hangar's item info;
        data/client_items.json); otherwise the price's satis_orani (adaptation), ref_value for an item with no shop price. It is not sold for more than (or
        the same as) the purchase price: then the price's satis_orani (SL-01 was bought for 3,000 U and sold for the client's value of 1,250,000 C)."""
        v = UPG.ITEMS.get(loot, {}).get('selling')
        if v:
            pr = self.price(loot)
            cost = pr[1] * (EXCHANGE_RATE if pr[0] == 'uridium' else 1) if pr else 0
            if cost and v >= cost:
                v = cost * ITEMS['sale_ratio']
            return 'credits', int(v * n)
        fixed = ITEMS.get('ship_sale', {}).get(loot)
        if fixed:
            return fixed[0], int(fixed[1] * n)
        pr = self.price(loot) or self.ref_value(loot)
        if not pr:
            return None
        return pr[0], int(pr[1] * n * ITEMS['sale_ratio'])

    def ref_value(self, loot):
        """Value of an item not in the shop (items.json _satis_degerleri): laser/shield/speed are scaled by power against the strongest uridium shop item
        in the same table; the others from the prefix table."""
        for table, key in STAT_TABLES:
            row = ITEMS[table].get(loot)
            if row and row.get(key):
                priced = [(l, self.price(l)) for l, r in ITEMS[table].items() if l != loot and r.get(key)]
                priced = [(l, pr) for l, pr in priced if pr and pr[0] == 'uridium']
                if priced:
                    ref, (cur, val) = max(priced, key=lambda x: ITEMS[table][x[0]][key])
                    return cur, val * row[key] / ITEMS[table][ref][key]
        return next((tuple(v) for k, v in ITEMS['sale_values'].items() if loot.startswith(k)), None)

    def sell(self, f):
        """HangarShipSellItemRequest {itemList: [{itemId, quantity}]}: an unfitted item or ammo in the inventory. If all of them
        can be sold they are sold (InventoryItemRemovedCommand / counter update + money), otherwise none."""
        fail = lambda reason=None: [('HangarShipSellItemCommand', dict(
            errorMessage=self.reason(reason) if reason else stack_msg('eqt_error_generic'), resultId=0))]
        equipped = self.p.equipped_ids()
        ammo_ids = {self.item_id(l): l for l in self.p.d['ammunition']}
        plan = []
        for pk in f.get('itemList') or []:
            iid, q = int(pk.get('itemId') or 0), max(1, int(pk.get('quantity') or 1))
            if any(iid == x[0] for x in plan):          # the same item twice: it was paid twice
                return fail()
            loot = self.p.d['items'].get(str(iid))
            if loot:
                if iid in equipped:
                    self.log('   no sale: %s is fitted' % loot)
                    return fail('equipped_sale')
                if loot.startswith(QF.PREFIX):                  # QFC is not sold, it is recycled at the Hyperforge (official FAQ)
                    self.log('   no sale: %s (QFC)' % loot)
                    return fail('qfc_sale')
                q = 1
            elif iid in ammo_ids:
                loot = ammo_ids[iid]
                q = min(q, self.p.ammo(loot))
            val = self.sale_value(loot, q) if loot and q > 0 else None
            if not val:
                self.log('   no sale: item %s (%s)' % (iid, loot))
                return fail()
            plan.append((iid, loot, q, val))
        if not plan:
            return fail()
        msgs, got = [], {}
        for iid, loot, q, (cur, amount) in plan:
            if str(iid) in self.p.d['items']:
                with self.p.lock:
                    del self.p.d['items'][str(iid)]
                    self.p.d.get('item_level', {}).pop(str(iid), None)
                    self.p.dirty = True
                msgs.append(('InventoryItemRemovedCommand', {'itemId': iid}))
            else:
                total = self.p.add_ammo(loot, -q)
                st = self.p.menu_status(loot)
                msgs += ([('MenuItemStatusCommand', st)] if st else []) + [self.inv_item(iid, loot, total),
                                                                          self.pack([self.hangar_item(iid, loot, total)])]
            got[cur] = got.get(cur, 0) + amount
            RT.money(self.p, cur, amount, RT.sell_desc(loot), loot, q)              # account history
            self.log('   sold: %s x%d = %d %s' % (loot, q, amount, cur))
        with self.p.lock:
            for cur, amount in got.items():
                self.p.d['pilot'][cur] = self.p.d['pilot'].get(cur, 0) + amount
            self.p.dirty = True
        return msgs + self.money_msgs() + [('HangarShipSellItemCommand', dict(errorMessage=None, resultId=1))]

    def sell_drone(self, f):
        """HangarShipSellDroneRequest {droneId}: the drone is sold; the items on it and its design return to the inventory. Value: the client's
        "sellable" value (credits; Flax 100,000, Iris 500,000), otherwise the satis_orani of the price of the last drone of that type."""
        x = self.p.drone(f.get('droneId') or 0)
        if not x or DRONES[x['lootId']].get('single'):        # Apis/Zeus are not sold (no "sellable" in the client)
            return [('HangarShipSellDroneCommand', dict(resultId=0, errorMessage=stack_msg('eqt_error_generic'), drones=self.drone_views()))]
        info = DRONES[x['lootId']]
        n = sum(1 for y in self.p.d['drones'] if y['lootId'] == x['lootId'])
        amount = int(info['prices'][min(n, len(info['prices'])) - 1] * ITEMS['sale_ratio'])
        cur = info['currency']
        if UPG.ITEMS.get(x['lootId'], {}).get('selling'):
            cur, amount = 'credits', int(UPG.ITEMS[x['lootId']]['selling'])
        freed = []                    # in every ship the drone's items and designs go to the inventory
        with self.p.lock:
            for s in self.p.d['ships'].values():
                for c in s.get('drone_config', {}).values():
                    freed += c.pop(str(x['uid']), None) or []
                for c in s.get('drone_design', {}).values():
                    freed += [i for i in (c.pop(str(x['uid']), None) or {}).values() if i]
            self.p.d['drones'].remove(x)
            self.p.d['pilot'][cur] = self.p.d['pilot'].get(cur, 0) + amount
            self.p.sync_equipment()
            self.p.dirty = True
        RT.money(self.p, cur, amount, 'sell_drone', x['lootId'], 1)
        self.log('   drone sold: %s (id %d) = %d %s' % (x['lootId'], x['uid'], amount, cur))
        # the freed items are not fitted in the client's inventory either (hangarId 0): before, they counted as fitted until the hangar list was asked for again
        # and did not show in the inventory
        form = self.formation_status_msgs()          # if the sold drone brought the count below the active formation's minimum it returns to standard
        return (self.money_msgs() + [('InventoryItemRemovedCommand', {'itemId': x['uid']}),          # From the Assembly list
                                     ('HangarShipSellDroneCommand', dict(resultId=1, errorMessage=None, drones=self.drone_views()))]
                + form + self.drone_msgs() + [self.equipment_cmd()] + self.item_updates(freed) + self.apply_stats())

    @staticmethod
    def stack(key):
        return stack_msg(key)

    def grant_design(self, loot):
        """Ship design reward: if the ship is in the profile it is added to its designs -> True; otherwise False (the reward is kept)."""
        sid = self.own_ship(design_base(loot))
        if not sid:
            return False
        with self.p.lock:
            ds = self.p.ship(sid).setdefault('designs', [])
            if loot not in ds:
                ds.append(loot)
            self.p.dirty = True
        self.log('   design reward: %s' % loot)
        return True

    def own_ship(self, base):
        """The owned ship of this type (shipId) or None. Astral's rented ship does not count: it is taken back when the run ends, the design would go
        with it."""
        loan = (((self.p.d.get('pve') or {}).get('astral') or {}).get('run') or {}).get('sid')
        return next((k for k, s in self.p.d['ships'].items() if s['lootId'] == base and k != loan), None)

    def pending_designs(self, ship_loot):
        """Ship obtained: the stored design rewards (those that arrived while the ship was missing) are now given."""
        msgs = []
        for loot in [l for l in self.p.d.get('other_items', {}) if design_base(l) == ship_loot]:
            if self.grant_design(loot):
                self.p.add_resource(loot, -self.p.resource(loot))
                msgs += [('ShipDesignAddedCommand', {'lootId': loot})]
        return msgs

    def auto_buy(self, loot, n):
        """Auto-buy CPU (ALB-X, RB-X): silent purchase at the shop price -> messages (empty if the money does not suffice)."""
        return self.buy(loot, n, quick=True) if self.price(loot) else []

    def auto_buy_fail(self, loot, n):
        """The client's text (Ö1) if the auto-buy did not happen because the money did not suffice: 0|ammobuy_fail_uri / _cre ("Ammo purchase failed! Not
        enough Uridium." ...; NetConnectionHelper.OnData) -> messages or empty."""
        pr = self.buy_price(loot, 1) if self.price(loot) else None
        if not pr or self.p.d['pilot'].get(pr[0], 0) >= math.ceil(pr[1] * n - 1e-9):
            return []
        return [legacy('0|ammobuy_fail_%s' % ('uri' if pr[0] == 'uridium' else 'cre'))]

    def auto_buy_ammo(self, f):
        """HangarShipAutoBuyCpuAmmoRequest: the ammo the auto-buy CPU (ALB-X laser, RB-X rocket and launcher rocket) will buy
        (in the profile) -> HangarShipAutoBuyCpuAmmoCommand (the client updates the item's attachedAmmo in the inventory). RB-X's list
        also has the launcher rockets; selecting ECO-10 gave an error (user report 2026-10-25)."""
        iid, ammo = f.get('itemId'), f.get('ammoLootId') or ''
        loot = self.p.d['items'].get(str(iid))
        cfg = EX.X.get(loot, {}).get('auto_pickup')
        ok = bool(cfg) and cfg['type'] in ('laser', 'rocket') and ammo.startswith(
            ('ammunition_laser_',) if cfg['type'] == 'laser' else ('ammunition_rocket_', 'ammunition_rocketlauncher_')) \
            and bool(self.price(ammo))
        if ok:
            with self.p.lock:
                self.p.d.setdefault('auto_buy_ammo', {})[loot] = ammo
                self.p.dirty = True
            self.log('   auto-buy: %s -> %s' % (loot, ammo))
        return [('HangarShipAutoBuyCpuAmmoCommand', dict(result=1 if ok else 0, cpuItemId=iid or 0, ammoLootId=ammo,
                                                          errorMessage=None if ok else stack_msg('eqt_error_generic')))]

    def auto_lab(self, item, ore, best=False):
        """Auto-laboratory CPU (NC-AWL/AWR/AWB/AGB): when an upgrade finishes it starts again with the same ore in the cargo (best: the best one)."""
        opts = LAB['bonuses'].get(str(item), {})
        if best:
            ore = max((int(t) for t in opts if self.p.ore_count(int(t)) > 0), key=lambda t: opts[str(t)], default=None)
        if ore is None or str(ore) not in opts or self.p.ore_count(ore) <= 0:
            return []
        n = min(self.p.ore_count(ore), 10000)
        self.log('   auto-upgrade: part %d <- %s x%d' % (item, ORES.get(ore), n))
        return self.upgrade({'itemToUpdate': {'itemValue': item}, 'updateWith': {'oreType': {'typeValue': ore}, 'count': n}})

    def quick_buy(self, loot):
        st = self.p.menu_status_cache.get('buy_' + loot, {})
        return self.buy(loot, st.get('counterValue') or (100 if 'rocket' in loot else 1000), quick=True)

    # ------------------------------------------------------------ hangar
    def equipment_cmd(self, sid=None):
        ship = self.p.ship(sid)
        t = copy(self.equip_tpl)
        t.pop('_m', None)
        cur = ship['active_config']
        for c in t['shipConfigs']:
            pc = ship['configs'].get(str(c['setId']), {})
            for slot in EQUIP_SLOTS:
                c[slot] = list(pc.get(slot, []))
            c['active'] = c['setId'] == cur
        # lootId with appearance (design attached): the client keeps the slot layout under the name in the ship list and looks it up with this (ships_cmd)
        t.update(currentConfigId=cur, lootId=self.p.ship_look(sid), hangarId=ship['hangarId'], shipId=int(sid or self.p.d['active_ship']),
                 extrasSlotsSize1=self.capacity('extra', sid, 1), extrasSlotsSize2=self.capacity('extra', sid, 2),
                 droneConfigs=[self.drone_config_msg(c['setId'], c['setId'] == cur, sid) for c in t['shipConfigs']],
                 petConfigs=self.pet.config_msgs(cur, sid))
        return ('HangarShipEquipmentCommand', t)

    def drone_config_msg(self, cid, active, sid=None):
        """The drones and fitted items in one config of a ship (HangarDroneEquipmentMsg; item ids
        SingleDroneEquipmentMsg.defaults, design and appearance design/visual; the designs are in the ship's config, dron_tasarim)."""
        dc = self.p.drone_config(cid, sid)
        drones = []
        team = self.p.design_mods(cid, sid).get('drone_laser', 0)   # Havoc, Cerberus: to the drone lasers when all drones have that design
        for i, x in enumerate(self.p.d['drones']):
            lv = LEVELS[x['level'] - 1]
            shd = DESIGNS.get(self.p.drone_design(x, 'design', cid, sid) or '', {}).get('drone_shield', 0)     # Hercules: to that drone's shield
            look, design = self.p.drone_design_id(x, 'visual', cid, sid), self.p.drone_design_id(x, 'design', cid, sid)
            # client (UINewHangarSystem.CreateItemInfo): "Effect: weaponEffect%/shieldEffect%"; a value with ...Bouns > 0 is blue.
            # The effect of level, design and Assembly upgrade is the same as in combat (world: drone laser, shop: drone shield); 0/0
            # was being sent (live round 2), the upgrade was not counted (user report 2026-10-24: "the upgraded drone gives no bonus").
            # "Upgrade lvl. Damage/Shield" is written as in the client: level + 1 as in Assembly
            up = UPG.drone_level(x)
            weapon = ((1 + lv['laser'] + team) * UPG.factor(x['lootId'], up, UPG.DRONE_DAMAGE) - 1) * 100
            shield = ((1 + lv['shield'] + shd) * UPG.factor(x['lootId'], up, UPG.DRONE_SHIELD) - 1) * 100
            drones.append(mod('SingleDroneEquipmentMsg', level=x['level'], visual=[look] if look else [],
                              shieldBouns=round(shield - lv['shield'] * 100, 2), repairValue='', defaults=list(dc.get(str(x['uid']), [])),
                              weaponBouns=round(weapon - lv['laser'] * 100, 2), damageUpgradeLevel=up + 1, shieldUpgradeLevel=up + 1,
                              design=[design] if design else [], shieldEffect=round(shield, 2),
                              position=i, droneId=x['uid'], damage=0.0, repairType='', weaponEffect=round(weapon, 2)))
        return mod('HangarDroneEquipmentMsg', setId=int(cid), active=active, position=0, setDroneEquipment=drones)

    def drone_views(self):
        """Drones in the hangar list: order, level, points and the points of the next level."""
        out = []
        for i, x in enumerate(self.p.d['drones']):
            nxt = LEVELS[min(x['level'], len(LEVELS) - 1)]['points']
            out.append(mod('HangarShipDroneView', position=i, damage=0.0, droneId=x['uid'], points=x['points'], level=x['level'],
                           lootId=x['lootId'], nextLevel=nxt, droneTypeId=DRONES[x['lootId']]['type']))
        return out

    def formation_status_msgs(self):
        """When the drone count changes: the buttons of owned formations that need a minimum number of drones (Arrow, Dome, Heart, Pincer; wiki). If the drones no longer
        suffice for the active formation (a drone was sold) it returns to the standard formation."""
        out = []
        cur = next((k for k, v in FORMS.items() if v['id'] == self.p.d.get('formation', 0)), None)
        if FORM_RULES.get(cur, {}).get('min_drones', 0) > len(self.p.d['drones']):
            with self.p.lock:
                self.p.d['formation'] = 0
                self.p.dirty = True
            out += [('DroneFormationChangeCommand', {'uid': self.p.user_id, 'selectedFormationId': 0})]
            out += [('MenuItemStatusCommand', st) for st in [self.p.menu_status('drone_formation_default')] if st]
        for k in self.p.d['formations']:
            st = FORM_RULES.get(k, {}).get('min_drones') and self.p.menu_status(k)
            if st:
                out.append(('MenuItemStatusCommand', st))
        return out

    def drone_msgs(self):
        """Drones in space: "0|n|d|<user>|<formation>|type|level|design|appearance..." (save: other players' drones;
        design/appearance are the client's game.xml design ids, 0 standard)."""
        ds = self.p.d['drones']
        if not ds:
            return []
        look = lambda x, slot: DESIGNS.get(self.p.drone_design(x, slot) or '', {}).get('id', 0)
        body = '|'.join('%d|%d|%d|%d' % (DRONES[x['lootId']]['type'], x['level'], look(x, 'design'), look(x, 'visual')) for x in ds)
        return [legacy('0|n|d|%d|%d|%s' % (self.p.user_id, self.p.d.get('formation', 0), body))]

    def inventory_items(self):
        hm = self.p.hangar_map()
        items = [self.hangar_item(int(i), loot, 1, hm.get(int(i), 0)) for i, loot in self.p.d['items'].items()]
        items += [self.hangar_item(self.item_id(loot), loot, n) for loot, n in self.p.d['ammunition'].items() if n > 0]
        for m in self.p.d['ores']:
            loot = ORES.get(m['oreType']['typeValue'])
            if loot and m['count'] > 0:
                items.append(self.hangar_item(self.item_id(loot), loot, m['count']))
        for loot, n in sorted(self.p.d.get('other_items', {}).items()):   # stored resources (ABR, Schism, key, voucher …)
            if loot.startswith('resource_') and n > 0 and loot not in NO_TRAITS:
                items.append(self.hangar_item(self.item_id(loot), loot, n))
        return items

    def ships_cmd(self):
        """Hangar list: owned ships (the active one marked), a design list for each, the shared inventory. Ship name with appearance
        (e.g. ship_sentinel_design_sentinel-phantasm): the client (HangarShipsCommandHandlerEvent) finds the slot layout by the name
        before "_design" and writes this name, the equipment window looks the layout up with HangarShipEquipmentCommand.lootId (CreateTabSlot); when the
        base name was gone, the first MANAGE after a design change threw NullReferenceException (live round 2)."""
        t = copy(self.ships_tpl)
        t.pop('_m', None)
        sids = sorted(self.p.d['ships'], key=int)
        t['ships'] = [mod('HangarShipBriefCommand', isActive=sid == self.p.d['active_ship'], lootId=self.p.ship_look(sid),
                          shipId=int(sid), isFavorite=bool(self.p.ship(sid).get('favorite'))) for sid in sids]
        t['allDesignPack'] = [mod('ShipDesignPack', designList=self.designs(sid)) for sid in sids]
        # the InventoryItemPack.items count is a byte (at most 255): the inventory is split into packs of 255. The client reads all of them
        # (InventoryItemData.RefreshItems: foreach over the packs); with a 268-item inventory the list could not be encoded (live 2026-10-19)
        items = self.inventory_items()
        t['items'] = [mod('InventoryItemPack', items=items[i:i + PACK_MAX]) for i in range(0, len(items), PACK_MAX)] or \
            [mod('InventoryItemPack', items=[])]
        t['drones'] = self.drone_views()
        t['petView'] = self.pet.view()
        return ('HangarShipsCommand', t)

    def stats(self, sid=None):
        """Displayed speed, in-game speed, shield and shield absorption ratio according to a ship's active config."""
        active = sid is None or str(sid) == self.p.d['active_ship']
        eq = self.p.d['equipment'] if active else self.p.loadout(sid)
        gens = eq.get('generators', [])
        ship = self.p.ship_row(sid) or None                        # with the base speed of the design being worn (Centurion 290-315)
        display = speed = None
        if ship:
            display = ship['base_speed'] + sum(ITEMS['speed_generators'].get(g, {}).get('speed', 0) for g in gens)
            speed = display - ITEMS['speed_diff']
        form = self.p.mods()                                # formation + drone designs
        lab = active and self.p.lab_bonus(2)              # engine upgrade (Duranium, Promerium)
        if ship:
            display = int((display + form.get('speed_absolute', 0))                                       # Leonov +20
                          * (1 + form.get('speed', 0)) * (1 + (lab or 0)) * SET.multiplier('ship_speed'))     # panel: the ship's speed
            if 'floor_speed' in form:                           # Speed Burst (technology.py): at least this speed
                display = max(display, int(form['floor_speed']))
            if 'fixed_speed' in form:                         # ship abilities: Travel 450, Fortify 0 (does not move)
                display = int(form['fixed_speed'])
            if 'max_speed' in form:                         # slowing sphere (Barb, The Stinger, Saboteur): at most this speed
                display = min(display, int(form['max_speed']))
            speed = max(0, display - ITEMS['speed_diff'])
        # (shield, absorption): the generators on the ship + those on the drones (with the drone level bonus, wiki: +4% per level)
        shield_table = ITEMS['shield_generators']
        glv = (self.p.d.get('equipment_level') if active else self.p.loadout_levels(sid) or {}) or {}
        glv = glv.get('generators', [])
        shields = [(shield_table[g]['shield'] * UPG.factor(g, glv[i] if i < len(glv) else 0, UPG.SHIELD), shield_table[g]['absorb'])
                   for i, g in enumerate(gens) if g in shield_table]
        ship_gens = len(shields)
        cid = self.p.ship(sid)['active_config']
        for (x, loots), (dloot, dup, ilv) in zip(self.p.drone_loadout(sid), self.p.drone_levels(sid)):
            # drone level and the drone's design (Hercules: +15% to that drone's shield generators); the drone's and generator's upgrade
            bonus = 1 + LEVELS[x['level'] - 1]['shield'] + DESIGNS.get(self.p.drone_design(x, 'design', cid, sid) or '', {}).get('drone_shield', 0)
            bonus *= UPG.factor(dloot, dup, UPG.DRONE_SHIELD)
            shields += [(shield_table[g]['shield'] * bonus * UPG.factor(g, ilv[j] if j < len(ilv) else 0, UPG.SHIELD), shield_table[g]['absorb'])
                        for j, g in enumerate(loots) if g in shield_table]
        total = sum(k for k, e in shields)
        absorb = sum(k * e for k, e in shields) / total if total else 0.8
        absorb = max(0.0, min(1.0, absorb + form.get('absorb', 0)))
        hp = self.p.ship_row(sid).get('hp')
        total *= 1 + ((active and self.p.lab_bonus(3)) or 0)     # shield upgrade (Duranium, Promerium, Seprom, Osmium)
        # the panel's ship HP and shield multipliers; the shield goes to the client as 32 bits (AttributeShieldUpdateCommand)
        shield_max = min(SET.I32, int(total * (1 + form.get('shield', 0)) * SET.multiplier('ship_shield')))
        hp_max = max(1, int(hp * (1 + form.get('hp', 0)) * SET.multiplier('ship_hp') + form.get('hp_flat', 0))) if hp else None
        if hp_max and active:
            hp_max = max(1, int(hp_max * form.get('hp_multiplier', 1.0)))   # infection: 15% of the total hull, Pilot Bio included
        return dict(display=display, speed=speed, shield_max=shield_max, absorb=absorb,
                    lasers=len(eq.get('laser', [])), speed_gens=sum(1 for g in gens if g in ITEMS['speed_generators']),
                    shield_gens=ship_gens, hp_max=hp_max)

    def detail_cmd(self, sid=None):
        t = copy(self.detail_tpl)
        t.pop('_m', None)
        sid = str(sid or self.p.d['active_ship'])
        ship, s, c = self.p.ship(sid), self.stats(sid), self.p.d['ammunition']
        if sid == self.p.d['active_ship']:
            g = self.p.d['ship']
            hull = dict(hp=int(g.get('hitPoints', 0)), maxHp=g.get('hitMax', 0), shield=int(g.get('shield', 0)),
                        nano=int(g.get('nanoHull', 0)), maxNano=g.get('maxNanoHull', 0))
        else:
            hp = self.p.ship_row(sid).get('hp', 0)
            hull_def = ship.get('hull') or {}
            hull = dict(hp=int(hull_def.get('hitPoints', hp)), maxHp=hp, shield=0, nano=int(hull_def.get('nanoHull', 0)), maxNano=hp)
        t.update(hull, hull=round(100 * hull['hp'] / max(hull['maxHp'], 1)),          # hull integrity % (save: 115,659/116,000 -> 100)
                 upgradeModuleCount=len(self.p.loadout(sid)['upgrades']),              # fitted ship upgrade modules
                 laserAmmo=sum(n for k, n in c.items() if k.startswith('ammunition_laser_')),
                 rockets=sum(n for k, n in c.items() if k.startswith('ammunition_rocket_')),
                 laserCount=s['lasers'], speedGenerators=s['speed_gens'], shieldGenerators=s['shield_gens'], shipId=int(sid),
                 isActive=sid == self.p.d['active_ship'], isFavorite=bool(ship.get('favorite')), lootId='',
                 curDesignLootId=self.p.ship_look(sid), designList=self.designs(sid),
                 repairVouchers=int((self.p.d.get('gates') or {}).get('voucher', 0)))      # repair vouchers of the gates
        t['maxSpeed'] = s['display'] or 0                       # not the 355 in the save if it is absent from the ship data
        return ('HangarShipDetailCommand', t)

    def apply_stats(self):
        """Active ship/config changed: speed/shield/appearance update (save: AttributeShipSpeedUpdateCommand, ShipExtensionsCommand)."""
        msgs = []
        s = self.stats()
        g = self.p.d['ship']
        with self.p.lock:
            if s['speed'] is not None and s['speed'] != g.get('speed'):      # 0: Fortify (does not move)
                g['speed'] = s['speed']
                self.p.d['shown_speed'] = s['display']      # the speed template at login uses this too (player_profile.patch_template)
                msgs.append(('AttributeShipSpeedUpdateCommand', {'newSpeed': s['speed'], 'displaySpeed': s['display']}))
            if s['hp_max'] and s['hp_max'] != g.get('hitMax'):
                g['hitMax'] = s['hp_max']                      # the formation's HP bonus/penalty (Heart, Moth, Diamond ...)
                g['hitPoints'] = min(g.get('hitPoints', 0), s['hp_max'])
                msgs.append(('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g['hitMax'],
                                                         nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0))))
            if s['shield_max'] != g.get('shieldMax', 0):
                old_max = g.get('shieldMax', 0)
                if getattr(self, 'keep_shield_ratio', False) and old_max > 0:      # formation: the shield percentage is kept
                    g['shield'] = min(s['shield_max'], g.get('shield', 0) * s['shield_max'] / old_max)
                else:
                    g['shield'] = min(g.get('shield', 0), s['shield_max'])
                g['shieldMax'] = s['shield_max']
                msgs.append(('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g['shieldMax']}))
            self.p.d['shield_absorb'] = s['absorb']
            # cargo space: the ship's cargo + the Logistics skill (skill_tree.py); shown in ShipInitializationCommand
            base = self.p.ship_row().get('cargo', 0) + self.p.mods().get('cargo_absolute', 0)      # Leonov +500
            if base and self.p.premium:
                base += PREMIUM_CARGO          # wiki: (base + Premium 500) x2 cargo compressor; the multipliers apply to this sum
            if base:
                cargo = int(base * (1 + self.p.mods().get('cargo_space', 0)) * EX.cargo_factor(self.p)    # + cargo CPU
                            * (1 + (self.pet.proto('cargo') if self.pet.owned else 0))      # + AI-CR (even if the P.E.T. is not in space)
                            * SET.multiplier('cargo'))                                       # panel: cargo capacity
                if cargo != g.get('cargoSpaceMax'):
                    g['cargoSpaceMax'] = cargo
                    self.p.sync_cargo()
                    # the client (UpdateCargoSpaceCommandHandler: Hero.MaxCargo) did not see the new maximum until a map change otherwise (Ö1)
                    msgs.append(('UpdateCargoSpaceCommand', {'cargoSpaceMax': cargo}))
            # appearance: 1-3 by laser count (save: 1 laser -> 1, 2 lasers -> 2). ShipInitializationCommand.expansionStage
            # stayed at 1 in the save, only ShipExtensionsCommand changed; that is why it is kept separate (login_msgs resends it at login)
            mm = self.module_update()                          # icons of the ship modules
            if mm[1] != self.p.d.get('module_icons'):
                self.p.d['module_icons'] = mm[1]
                msgs.append(mm)
            stage = self.extension_stage()
            if stage != self.p.d.get('expansion_stage', 1):
                self.p.d['expansion_stage'] = stage
                msgs.append(('ShipExtensionsCommand', {'userId': self.p.user_id, 'extensionStage': stage}))
            self.p.dirty = True
        return msgs + self.p.menu_changes()                    # CPUs, Smart Bomb, launcher, abilities (live test H21)

    def module_update(self):
        """The active ship's module slots and the types of fitted modules (ShipUpgradeModuleUpdateCommand; in the save at login max 3, empty)."""
        ids = self.p.config().get('upgrades', [])
        types = [MODULE_TYPE_IDS.get(GM.M.get(self.p.d['items'].get(str(i), ''), {}).get('type'), 1) for i in ids
                 if str(i) in self.p.d['items']]
        return ('ShipUpgradeModuleUpdateCommand', dict(max=self.capacity('upgrades'), moduleTypeIds=types, uid=self.p.user_id))

    def extension_stage(self):
        n = len(self.p.d['equipment'].get('laser', []))
        return max(1, min(3, math.ceil(3 * n / max(self.capacity('laser'), 1))))

    def login_msgs(self):
        """After the map loads: the appearance tied to equipment (comes with login 1 in the save), drones and item counters."""
        stage = self.p.d.get('expansion_stage', 1)
        msgs = [('ShipExtensionsCommand', {'userId': self.p.user_id, 'extensionStage': stage})] if stage != 1 else []
        shield = SKL.shield_cmd(self.p)
        if shield[1]['shieldSkillId']:
            msgs.append(shield)                     # appearance of the shield skill (skill_tree.shield_cmd)
        import upgrades as UPG
        counts = self.count_msgs()
        hour, shop = UPG.bonus_hour(), self.discount()
        disc = [('UserInventoryModule', dict(activePremiumDiscount=int(round(shop * 100)), activeRebateSubDiscount=0,
                                             inventoryItemModules=[f['item'] for n, f in counts],
                                             activeHappyUpgradeDiscount=int(round(hour * 100))))] if hour or shop else []
        # quick-buy items: the template's hint had the saved account's "ttip_currency_missing" row, by money (live K7)
        return msgs + self.drone_msgs() + counts + disc + self.quick_buy_msgs()   # discount if Upgrade Hour (H40) or Shop Discount is running

    def count_msgs(self):
        """The client's item counters at login (InventoryItemUpdatedCommand): Assembly ingredients are counted from here; in the save's login
        there were only four resources, money and the other ingredients showed 0 (live test H33). Money, the items at hand that appear in recipes, all the
        resources in the store (upgrade/jump/Update/Synthesis costs: ABR, Diametrion, Isochronate, Horizon Shard ...; when only Assembly
        recipes were counted these showed 0, live test H59) and equipment instances."""
        import assembly as ASM
        import inventory as INV
        held = {k for k, v in self.p.d.get('other_items', {}).items()
                if v > 0 and k.startswith('resource_') and k not in NO_TRAITS}
        free = SET.get('assembly_free')
        loots = ['currency_credits', 'currency_uridium'] + sorted((ASM.INGREDIENTS | UPG.INGREDIENTS | held) - {'currency_credits', 'currency_uridium'})
        out = []
        for loot in loots:
            if loot.startswith(('equipment_', 'drone_', 'recipe_')):
                continue                        # items with instances from the hangar inventory (HangarShipsCommand)
            n = INV.client_count(self.p, loot)  # including ships (the base ship of Plus recipes)
            if free and not loot.startswith('ship_'):
                n = max(n, 10 ** 6)             # Free Assembly: the client sees all ingredients as sufficient
            if n > 0 or loot.startswith('currency_'):
                out.append(self.inv_item(self.item_id(loot), loot, n))
        # item instances (level, the hangar it is fitted in): Assembly's Upgrade/Disassembly tabs recognize only these (H38)
        hm = self.p.hangar_map()
        for iid, loot in sorted(self.p.d['items'].items(), key=lambda kv: int(kv[0])):
            if loot.startswith(('equipment_', 'drone_designs_', 'pet_designs_')):
                out.append(self.inv_item(int(iid), loot, 1, hm.get(int(iid), 0)))
        return out + [self.drone_item(x) for x in self.p.d['drones']] + self.module_items()

    def module_items(self):
        """Unfitted Clan Battle Station modules in the inventory (as in the save: InventoryItemModule, attribute 0 = HP, upgradeLevel):
        Assembly's Upgrade tab picks what to upgrade from the inventory, and since the modules were never sent they were not in the list (player
        report 2026-10-27). The Build request's targetItemId is the module's id (upgrades.target)."""
        cbs = getattr(self, 'cbs', None)
        if not cbs:
            return []
        return [self.module_item(iid, m) for iid, m in sorted(cbs.st['modules'].items(), key=lambda kv: int(kv[0]))
                if not cbs.where(iid)]

    def module_item(self, iid, m):
        msg = self.inv_item(int(iid), m['loot'], 1, level=int(m.get('level', 0)))
        msg[1]['item']['inventoryItemAttributes'] = [mod('InventoryItemAttributeModule', key=0, value=str(int(m.get('hp', 0))))]
        return msg

    def ship_count_msgs(self, loots):
        """Assembly counter when a ship is gained/spent (only for those that are the base ship in recipes; inventory.client_count)."""
        import assembly as ASM
        import inventory as INV
        return [self.inv_item(self.item_id(l), l, INV.client_count(self.p, l)) for l in sorted(set(loots)) if l in ASM.INGREDIENTS]

    def formation_wait(self, loot, now=None):
        """Wait between two formation changes (items.json combat_items.formation; client CooldownType DRONE_FORMATION).
        Returns None while the wait runs, else the messages that start it: the shortcut-bar countdown of group 47. The world's
        Items keeps the end in the profile and sends the reset when it ends. Without a world nothing is started."""
        import combat_items as CIT
        now = now or time.time()
        group = CIT.item_cooldown(loot)[0]
        if now < CIT.ready_at(self.p, group):
            return None
        w = self.world()
        items = getattr(w, 'items', None)
        if items is None:
            return []
        with w.lock:
            return [items.cooldown(loot, now)]

    def change_formation(self, loot):
        """Formation from the shortcut bar (MenuActionRequest drone_formation_*): DroneFormationChangeCommand, the selected item on the bar,
        the arrangement in space and speed/shield/HP with the formation's bonuses."""
        if loot != 'drone_formation_default' and loot not in self.p.d['formations']:
            self.log('   no formation: %s' % loot)
            return []
        old = self.p.d.get('formation', 0)
        new = FORMS[loot]['id']
        if old == new:
            return []
        need = FORM_RULES.get(loot, {}).get('min_drones', 0)             # Arrow and Dome 4, Heart and Pincer 6 drones (wiki)
        if len(self.p.d['drones']) < need:
            self.log('   no formation: %s (at least %d drones needed)' % (loot, need))
            return []
        wait = self.formation_wait(loot)
        if wait is None:
            self.log('   formation change refused: still cooling down (%s)' % loot)
            return []
        with self.p.lock:
            self.p.d['formation'] = new
            self.p.dirty = True
        msgs = [('DroneFormationChangeCommand', {'uid': self.p.user_id, 'selectedFormationId': new})] + wait
        for k, v in FORMS.items():
            if v['id'] in (old, new):
                st = self.p.menu_status(k)
                if st:
                    msgs.append(('MenuItemStatusCommand', st))
        # the shield percentage is kept: a formation that raises the maximum shield does not refill the shield (player report: switching from Heart to another
        # formation with low shield filled the shield completely; entering and leaving a formation that lowers the shield does not gain shield either)
        self.keep_shield_ratio = True
        try:
            msgs += self.drone_msgs() + self.apply_stats()
        finally:
            self.keep_shield_ratio = False
        self.log('   formation: %s (%d)' % (loot, new))
        self.p.ach('formation', drone=len(self.p.d['drones']))
        return msgs

    def favourite(self, f):
        """HangarShipFavouriteRequest {favourite, shipId}: a star in the hangar. In ship warp the client lists only favorites ("You can
        only Warp ships that are marked as your favorites!"). resultId 1 is success (HangarShipFavouriteCommandHandler; live trial
        2026-10-17: the request was not processed at all)."""
        sid = str(f.get('shipId'))
        if sid not in self.p.d['ships']:
            return [('HangarShipFavouriteCommand', {'resultId': 0, 'errorMessage': stack_msg('eqt_error_generic')})]
        favs = sum(1 for k, s in self.p.d['ships'].items() if s.get('favorite') and k != sid)
        if f.get('favourite') and favs >= ITEMS.get('favorite_ship_limit', 10):      # forum 127436: at most 10 favorite ships
            return [('HangarShipFavouriteCommand', {'resultId': 0, 'errorMessage': stack_msg('items_hangarSlot_max_favs')})]
        with self.p.lock:
            self.p.d['ships'][sid]['favorite'] = bool(f.get('favourite'))
            self.p.dirty = True
        self.log('   hangar: %s favorite %s' % (self.p.ship(sid)['lootId'], 'evet' if f.get('favourite') else 'no'))
        return [('HangarShipFavouriteCommand', {'resultId': 1, 'errorMessage': None}), self.ships_cmd()]

    def clear_config(self, f):
        """HangarShipClearConfigRequest {wipe, configId, shipId}: all the items in the config go to the inventory (ship slots, drones
        and P.E.T.). On success (resultId 1) the client asks for the equipment again (HangarShipClearConfigCommandHandler)."""
        # The client's clear button always sends wipe=0 (gs.log), so drones and P.E.T. are cleared regardless of that flag.
        # Only this config is touched: the other config keeps its ship, drone and P.E.T. items.
        sid = self.ship_sid(f.get('shipId'))
        ship = self.p.ship(sid)
        cid = str(f.get('configId')) if str(f.get('configId')) in ship['configs'] else str(ship['active_config'])
        ids = self.p.ship_items(sid, cid)
        msgs = self.move({'items': ids, 'source': 'ship', 'destination': 'inventory', 'hangarId': ship['hangarId'],
                          'configId': int(cid)}) if ids else []
        self.log('   hangar: %s config %s cleared (%d items)' % (ship['lootId'], cid, len(ids)))
        return [('HangarShipClearConfigCommand', {'resultId': 1, 'errorMessage': None})] +             [m for m in msgs if m[0] != 'HangarShipMoveItemsCommand']

    # The client's texts: "Saves the equipment equipped on both configuration 1 and 2 for this ship." / "Load the equipment saved ..." /
    # "Transfer this ship's configuration and equipment to another ship with the same number of slots!" (live trial 2026-10-17:
    # none of the three were processed). The record is in the ship's profile: saved_config {config: {slot: [item]}}.
    def save_config(self, f):
        sid = self.ship_sid(f.get('shipId'))
        with self.p.lock:
            ship = self.p.d['ships'][sid]
            ship['saved_config'] = {c: {s: list(v) for s, v in cfg.items()} for c, cfg in ship['configs'].items()}
            # Drones and P.E.T. are part of the saved setup too (before, only the ship slots were saved).
            ship['saved_drone_config'] = {c: {d: list(v) for d, v in cfg.items()} for c, cfg in ship.get('drone_config', {}).items()}
            ship['saved_drone_design'] = {c: {d: dict(per) for d, per in cfg.items()} for c, cfg in ship.get('drone_design', {}).items()}
            ship['saved_pet_config'] = {c: {s: list(v) for s, v in cfg.items()} for c, cfg in ship.get('pet_config', {}).items()} \
                if self.pet.owned else {}
            self.p.dirty = True
        self.log('   hangar: %s config saved' % self.p.ship(sid)['lootId'])
        return [('HangarShipSaveConfigCommand', {'title': stack_msg('popup_save_success_title'),
                                                 'description': stack_msg('popup_save_success_description'), 'resultId': 1})]

    def load_config(self, f):
        """Re-fits the record: first the ship slots of both configs are emptied; an item in the record that no longer exists (sold) or that is
        fitted on another ship is skipped ("Some equipment were not available ...")."""
        sid = self.ship_sid(f.get('shipId'))
        ship = self.p.ship(sid)
        saved = ship.get('saved_config')
        if not saved:
            return [('HangarShipLoadConfigCommand', {'title': stack_msg('eqt_error_generic'), 'description': stack_msg('empty'),
                                                     'resultId': 0})]
        # Drone items, drone designs and P.E.T. items. Saves made before they were stored have no such key: those parts stay as is.
        s_drones = ship.get('saved_drone_config')
        s_designs = ship.get('saved_drone_design')
        s_pet = ship.get('saved_pet_config') if self.pet.owned else None
        es, hid = self.p.d['items'], ship['hangarId']
        missing = 0
        touched = [i for cfg in ship['configs'].values() for ids in cfg.values() for i in ids]
        touched += [i for cfg in saved.values() for ids in cfg.values() for i in ids]
        with self.p.lock:
            for c, cfg in ship['configs'].items():
                for s in cfg:
                    cfg[s] = []
            if s_drones is not None:
                for c, cfg in list(ship.get('drone_config', {}).items()) + list(s_drones.items()):
                    touched += [i for ids in cfg.values() for i in ids]
                for cfg in ship.get('drone_config', {}).values():
                    for d in cfg:
                        cfg[d] = []
            if s_designs is not None:
                for cfg in list(ship.get('drone_design', {}).values()) + list(s_designs.values()):
                    touched += [i for per in cfg.values() for i in per.values() if i]
                ship['drone_design'] = {}
            if s_pet is not None:
                for cfg in list(ship.get('pet_config', {}).values()) + list(s_pet.values()):
                    touched += [i for ids in cfg.values() for i in ids]
                for cfg in ship.get('pet_config', {}).values():
                    for s in cfg:
                        cfg[s] = []
            busy = self.p.hangar_map()
            used = {}                                   # config -> items already put back (an item is used once per config)

            def free(i, c):
                """The saved item still exists, is not on another ship and is not already used in this config."""
                ok = str(i) in es and busy.get(i, hid) == hid and i not in used.setdefault(str(c), set())
                if ok:
                    used[str(c)].add(i)
                return ok

            for c, slots in saved.items():
                cfg = ship['configs'].setdefault(c, {})
                extras = [self.p.d['items'].get(str(i), '') for i in slots.get('extra', [])]     # with the Slot CPU in the record
                for s, ids in slots.items():
                    for i in ids:
                        if s == 'upgrades' and GM.type_taken(self.p, i, cfg.get(s, [])):
                            missing += 1                    # one module of each type (a config saved before the rule)
                        elif len(cfg.get(s, [])) < self.capacity(s, sid, extras=extras) and free(i, c):
                            cfg.setdefault(s, []).append(i)
                        else:
                            missing += 1
            for c, per in (s_drones or {}).items():
                dcfg = self.p.drone_config(c, sid)
                for d, ids in per.items():
                    x = self.p.drone(d)                 # the drone may have been sold since
                    lst = dcfg.setdefault(str(d), [])
                    for i in ids:
                        if x and drone_ok(es.get(str(i), '')) and len(lst) < DRONES[x['lootId']]['slot'] and free(i, c):
                            lst.append(i)
                        else:
                            missing += 1
            for c, cfg in (s_designs or {}).items():
                for d, per in cfg.items():
                    x = self.p.drone(d)
                    for k, i in per.items():
                        d_row = DESIGNS.get(es.get(str(i), ''))
                        if x and d_row and DESIGN_SLOTS.get(k) == d_row['slot'] and free(i, c):
                            self.p.set_drone_design(x, DESIGN_SLOTS[k], i, c, sid)
                        else:
                            missing += 1
            for c, slots in (s_pet or {}).items():
                pcfg = self.pet.config(c, sid)
                for s, ids in slots.items():
                    for i in ids:
                        if s in pcfg and len(pcfg[s]) < self.pet.open_slots(s) and free(i, c):
                            pcfg[s].append(i)
                        else:
                            missing += 1
            self.p.dirty = True
            self.p.sync_equipment()
        self.log('   hangar: %s config loaded (%d items not found)' % (ship['lootId'], missing))
        desc = self.reason('incomplete_load') if missing             else stack_msg('popup_load_success_description')
        msgs = [('HangarShipLoadConfigCommand', {'title': stack_msg('popup_load_success_title'), 'description': desc, 'resultId': 1}),
                self.equipment_cmd(sid)] + self.item_updates(touched)
        if sid != self.p.d['active_ship']:
            return msgs
        msgs += self.apply_stats() + (self.drone_msgs() if s_designs is not None else [])
        return msgs + (self.pet.refresh() if s_pet is not None else [])

    def import_config(self, f):
        """Transfer System: everything fitted on the source ship is moved to the target ship (the target's old items go to the inventory): the ship slots of both
        configs, lasers/generators fitted to drones (dron_konfig), drone designs (dron_tasarim) and P.E.T. equipment (pet_konfig);
        all tied to the ship (hangar). Nothing stays fitted on the source: a ship module that cannot be fitted to the target and a QFC tied to another ship
        go to the inventory, with a warning on screen (user report 2026-10-25: designs, the P.E.T. and these modules stayed on the old ship and did not show in the
        normal inventory when the old ship was not selected). Every slot of the target must take the number of items moved."""
        import galaxy_gates as GALAXY
        src, dst = str(f.get('originShipId')), str(f.get('targetShipId'))
        fail = lambda: [('HangarShipImportConfigCommand', {'shipId': int(dst) if dst.isdigit() else 0,
                                                           'errorMessage': stack_msg('error_can_not_equip_to_slot'), 'resultId': 0})]
        if src == dst or src not in self.p.d['ships'] or dst not in self.p.d['ships']:
            return fail()
        a, b = self.p.ship(src), self.p.ship(dst)
        drop = lambda s, i: ((s == 'upgrades' and not GM.equip_allowed(self.p, i, b['lootId']))
                             or (s == 'QuantumFluidCore' and QF.equip_allowed(self.p, i, b['lootId'], []) is not None))
        go = {c: {s: [i for i in ids if not drop(s, i)] for s, ids in cfg.items()} for c, cfg in a['configs'].items()}
        for c, cfg in go.items():
            extras = [self.p.d['items'].get(str(i), '') for i in cfg.get('extra', [])]       # the Slot CPU is moved too
            for s, ids in cfg.items():
                if len(ids) > self.capacity(s, dst, extras=extras):
                    self.log('   hangar: no transfer: %s %s slots %d > %d' % (b['lootId'], s, len(ids), self.capacity(s, dst, extras=extras)))
                    return fail()
        touched = self.p.ship_items(src) + self.p.ship_items(dst)
        dropped = sum(len(ids) - len(go[c][s]) for c, cfg in a['configs'].items() for s, ids in cfg.items())
        with self.p.lock:
            for c, cfg in go.items():
                b['configs'][c] = cfg
                a['configs'][c] = {}
            b['drone_config'], a['drone_config'] = a.get('drone_config', {}), {c: {} for c in a['configs']}
            for k in ('drone_design', 'pet_config'):
                b[k], a[k] = a.get(k, {}), {}
            self.p.dirty = True
            self.p.sync_equipment()
        self.log('   hangar: config %s -> %s transferred%s' % (a['lootId'], b['lootId'], ' (%d items could not be fitted, to the inventory)' % dropped if dropped else ''))
        msgs = [('HangarShipImportConfigCommand', {'shipId': int(dst), 'errorMessage': None, 'resultId': 1}), self.equipment_cmd(dst)]
        msgs += self.item_updates(touched)                 # the transferred ones are on the target ship, the target's old ones and those that could not be fitted in the inventory
        if dropped:
            msgs.append(GALAXY.screen(REASONS['transfer_inventory'][1 if self.lang == 'tr' else 0]))
        if self.p.d['active_ship'] in (src, dst):
            msgs += self.apply_stats() + self.drone_msgs() + self.pet.refresh()
        return msgs

    def move(self, f):
        """Fitting/removing: the hangarId in the request says which ship, the configId which config. Destination/source "ship",
        "inventory", "drone" (+ droneId; laser/generator "default", design "design", appearance "visual") or "pet" (slot set
        lasers/generators/gears/protocols; the item's type determines the slot)."""
        ids = [int(x) for x in f.get('items', [])]
        src, dst = (f.get('source') or '').lower(), (f.get('destination') or '').lower()
        sid = self.p.ship_by_hangar(f.get('hangarId')) or self.p.d['active_ship']
        ship = self.p.ship(sid)
        cid = f.get('configId') if str(f.get('configId')) in ship['configs'] else ship['active_config']
        active = sid == self.p.d['active_ship'] and str(cid) == str(ship['active_config'])
        to_inv = dst in INVENTORY
        drone = self.p.drone(f.get('droneId') or 0) if dst == 'drone' else None
        moved, err, cause, err_args = [], None, None, {}
        with self.p.lock:
            cfg = self.p.config(cid, sid)
            dcfg = self.p.drone_config(cid, sid)
            pcfg = self.pet.config(cid, sid) if self.pet.owned else {}
            dd = self.p.drone_designs(cid, sid)
            pet_before = {k: list(v) for k, v in pcfg.items()}
            busy = self.p.hangar_map()
            loots = lambda lst: [self.p.d['items'].get(str(i), '') for i in lst]

            def extras_of(lists, skip):
                """The lootIds of the extras in the given item lists, excluding the `skip` item (one-per-type rule per config)."""
                return [l for l in loots([i for lst in lists for i in lst if i != skip]) if l.startswith('equipment_extra_')]

            def detach(iid):
                """Removes the item from where it is in this config (ship slot, drone, P.E.T.) or from the drone's design slot."""
                for lst in list(cfg.values()) + list(dcfg.values()) + list(pcfg.values()):
                    if iid in lst:
                        lst.remove(iid)
                        return True
                for d, per in list(dd.items()):
                    for k, v in list(per.items()):
                        if v == iid:
                            del per[k]
                            if not per:
                                del dd[d]
                            return True
                return False

            def fail(why, reason=None):
                nonlocal err, cause
                err = err or 'error_can_not_equip_to_slot'
                cause = cause or reason
                self.log('   hangar: %s' % why)

            for iid in ids:
                loot = self.p.d['items'].get(str(iid)) or ''
                slot = slot_of(loot)
                if not loot:
                    fail('bilinmeyen eşya %s' % iid)
                elif to_inv:
                    rest = [i for i in cfg.get('extra', []) if i not in ids]      # those removed in the same request do not count (clear_config)
                    if iid in cfg.get('extra', []) and len(rest) > self.capacity('extra', sid, extras=loots(rest)):
                        # the slot CPU cannot be removed while the slots it opened are full (the client's text: "Error: Slot CPU is currently in use.")
                        fail('%s çıkmaz: ekstra yuvaları dolu' % loot)
                        err = 'drone_slotCPUinUse'
                    elif detach(iid):
                        moved.append((iid, loot))
                elif pet_only(loot) and dst != 'pet':
                    fail('%s yalnız P.E.T.\'e takılır' % loot)
                elif loot in DESIGNS:
                    # drone design: the drone's "design" or "visual" slot (by the item's type); the old one returns to the inventory
                    if dst != 'drone' or not drone:
                        fail('%s yalnız drona takılır (%r)' % (loot, dst))
                        continue
                    old = self.p.drone_design_id(drone, DESIGNS[loot]['slot'], cid, sid)
                    if old == iid:
                        continue
                    if busy.get(iid, ship['hangarId']) != ship['hangarId']:
                        fail('%s başka gemide takılı' % loot, 'other_ship')
                        continue
                    detach(iid)
                    # only in this config of this ship (the design of the other config and the other ships stays the same)
                    self.p.set_drone_design(drone, DESIGNS[loot]['slot'], iid, cid, sid)
                    moved.append((iid, loot))
                    if old:
                        moved.append((old, self.p.d['items'].get(str(old), '')))
                elif dst == 'pet':
                    pslot = PETM.slot_for(loot)
                    if (f.get('slotSet') or '').lower() == 'heat' and PETM.heat_slot_ok(loot):
                        pslot = 'heat'                    # HEAT slot: laser or shield generator (HEAT active from level 4)
                    if not self.pet.owned or not pslot:
                        fail("%s P.E.T.'e takılamaz" % loot)
                        continue
                    lst = pcfg[pslot]
                    if iid in lst:
                        continue
                    if pslot == 'visual' and lst:         # single appearance slot: the old one returns to the inventory
                        old = lst.pop()
                        moved.append((old, self.p.d['items'].get(str(old), '')))
                    if busy.get(iid, ship['hangarId']) != ship['hangarId']:
                        fail('%s başka gemide takılı' % loot, 'other_ship')
                    elif len(lst) >= self.pet.open_slots(pslot):
                        fail('P.E.T. %s yuvaları dolu (%d)' % (pslot, self.pet.open_slots(pslot)), 'pet_full')
                    elif pslot in PETM.UNIQUE and loot in [self.p.d['items'].get(str(i)) for i in lst]:
                        fail('%s zaten takılı' % loot, 'pet_already')
                    elif self.pet.d['level'] < PETM.level_need(self.p.item_level(iid)):
                        fail('%s seviye %d: P.E.T. seviyesi %d gerekir' % (loot, self.p.item_level(iid),
                                                                           PETM.level_need(self.p.item_level(iid))))
                        err = 'pet_gear_requirement'
                        # the client's text "Required: P.E.T. Level %level%" (live test: the placeholder stayed empty)
                        err_args = {'_level_': PETM.level_need(self.p.item_level(iid))}
                    else:
                        detach(iid)
                        lst.append(iid)
                        moved.append((iid, loot))
                elif not slot:
                    fail('%s buraya takılamaz (%r)' % (loot, dst))
                elif dst == 'drone':
                    lst = dcfg.setdefault(str(drone['uid']), []) if drone else None
                    if lst is not None and iid in lst:
                        continue
                    held = extras_of([cfg.get('extra', [])] + list(dcfg.values()), iid) if loot in DRONE_EXTRAS else []
                    if not drone or not drone_ok(loot):
                        fail('%s drona takılamaz (dron %s)' % (loot, f.get('droneId')))   # laser, shield generator and extras
                    elif busy.get(iid, ship['hangarId']) != ship['hangarId'] or len(lst) >= DRONES[drone['lootId']]['slot']:
                        fail('dron %s dolu ya da eşya başka gemide' % f.get('droneId'))
                    elif loot in held or (loot.startswith(REPBOT) and any(l.startswith(REPBOT) for l in held)):
                        # one of each extra per config, ship and drones together (client FAQ drones_specials_p)
                        fail('%s: already in the config (ship or drone)' % loot)
                        err = 'special_generic_hint'
                    else:
                        detach(iid)
                        lst.append(iid)
                        moved.append((iid, loot))
                elif dst in PANELS and PANELS[dst] in (None, slot):
                    lst = cfg.setdefault(slot, [])
                    if iid in lst:
                        continue
                    if busy.get(iid, ship['hangarId']) != ship['hangarId']:
                        fail('%s başka gemide takılı' % loot, 'other_ship')
                    elif slot == 'upgrades' and not GM.equip_allowed(self.p, iid, ship['lootId']):
                        fail('%s bu gemiye takılmaz (%s)' % (loot, ship['lootId']))      # the module's ships
                    elif slot == 'upgrades' and GM.type_taken(self.p, iid, lst):
                        fail('%s: gemide %s türünden modül var' % (loot, GM.kind(loot)), 'same_module')    # one module of each type
                    elif slot == 'QuantumFluidCore' and QF.equip_allowed(self.p, iid, ship['lootId'], lst):
                        fail('%s: %s' % (loot, QF.equip_allowed(self.p, iid, ship['lootId'], lst)),     # linked ship, one each of AX/DF
                             'qfc_ship' if (QF.state(self.p, iid) or {}).get('ship') != ship['lootId'] else 'same_qfc')
                    elif slot in PC.SLOTS and PC.equip_allowed(self.p, iid, slot, lst):
                        fail('%s: %s' % (loot, PC.equip_allowed(self.p, iid, slot, lst)), 'same_cannon')   # one cannon of each type
                    elif slot == 'extra' and EX.slot_bonus_of([loot]) and EX.slot_bonus_of(loots(lst)):
                        fail('%s: the config already has a slot CPU' % loot, 'single_slot_cpu')       # one slot CPU per config (wiki)
                    elif slot == 'extra' and (loot in extras_of(dcfg.values(), iid) or loot in loots(lst) or loot.startswith(REPBOT)
                                              and any(l.startswith(REPBOT) for l in extras_of([lst] + list(dcfg.values()), iid))):
                        # one repair robot per config (user report 2026-10-24: two could be fitted); the client's text
                        # "Only one of these items is allowed per configuration."
                        fail('%s: config\'te onarım robotu ya da dronda aynı ekstra var' % loot)
                        err = 'special_generic_hint'
                    elif len(lst) >= self.capacity(slot, sid, extras=loots(cfg.get('extra', []))):
                        fail('%s yuvaları dolu' % slot)
                    else:
                        detach(iid)                                       # if fitted on a drone or P.E.T. it is taken from there
                        lst.append(iid)
                        moved.append((iid, loot))
                else:
                    fail('unknown panel %r -> %r' % (src, dst))
            if moved:
                self.p.dirty = True
                self.p.sync_equipment()
            pet_changed = {k: list(v) for k, v in pcfg.items()} != pet_before
        where = ' (dron %s%s)' % (f.get('droneId'), ' ' + f['slotSet'] if f.get('slotSet') else '') if 'drone' in (src, dst) else ''
        self.log('   hangar %s config %s: %s %s -> %s%s%s' % (ship['lootId'], cid, ', '.join(l.rsplit('_', 1)[-1] for i, l in moved) or '-',
                                                            src, dst, where, ' (error: %s)' % err if err else ''))
        ok = bool(moved) or not err
        msg = self.reason(cause) if cause and err == 'error_can_not_equip_to_slot' else stack_msg(err, **err_args) if err else None
        msgs = [('HangarShipMoveItemsCommand', {'result': 1 if ok else 0, 'errorMessage': None if ok else msg})]
        if moved:
            hm = self.p.hangar_map()
            msgs += [self.inv_item(i, l, 1, hm.get(i, 0)) for i, l in moved]
            msgs.append(self.equipment_cmd(sid))
            # the client's inventory grid is refreshed with this pack (save: after fitting, the items of that slot with hangarId)
            slots = {slot_of(l) for i, l in moved}
            group = [i for c in ship['configs'].values() for s in slots for i in c.get(s, [])]
            group += [i for k in ('drone_config', 'pet_config') for c in ship.get(k, {}).values() for ids_ in c.values() for i in ids_]
            group += [i for c in ship.get('drone_design', {}).values() for per in c.values() for i in per.values() if i]
            items = list(dict.fromkeys([i for i, l in moved] + group))
            msgs.append(self.pack([self.hangar_item(i, self.p.d['items'][str(i)], 1, hm.get(i, 0)) for i in items]))
            if active:
                msgs += self.apply_stats()
            if active and any(l in DESIGNS for i, l in moved):
                msgs += self.drone_msgs()                  # appearance of the drones in space
            if pet_changed and sid == self.p.d['active_ship']:
                # the P.E.T.'s gears and values in space: only when the P.E.T.'s equipment changes (fitting a laser/generator to the ship was also
                # counted as a P.E.T. slot type, and the level-up effect appeared every time)
                msgs += self.pet.refresh()
        return msgs

    # ------------------------------------------------------------ ship change and config switch
    def activate(self, f, in_station=True, travel=False):
        """HangarShipActivateShipRequest {shipId} -> HangarShipActivateShipCommand (client: result 1 success, message window).
        Only at the station as in the game. If successful (messages, True): the session makes the ship reload (ShipInitializationCommand).
        Each ship stays where it was left (forum 127436: changing in the hangar "your actual ship stays where you are on the active map");
        travel (hangar) takes the pilot to the new ship's saved position, in warping (ship_warp.py) the ship comes to the pilot."""
        sid = str(f.get('shipId'))
        reply = lambda res, err=None, ok=None: ('HangarShipActivateShipCommand', {
            'errorMessage': err, 'successMessage': ok, 'currentShipLootId': self.p.ship()['lootId'], 'result': res})
        if sid not in self.p.d['ships']:
            return [reply(0, stack_msg('eqt_error_generic'))], False
        if sid == self.p.d['active_ship']:
            return [reply(1, ok=stack_msg('info_text_switch_active_hangar_success'))], False
        if not in_station:
            self.log('   ship not changed: not at the station')
            return [reply(0, stack_msg('info_text_switch_hangar_station_only'))], False
        with self.p.lock:
            g = self.p.d['ship']
            self.p.ship()['hull'] = {'hitPoints': int(g.get('hitPoints', 0)), 'nanoHull': int(g.get('nanoHull', 0))}
            k = self.p.d['position']
            if H.parked(k.get('mapId')):
                self.p.ship()['position'] = {'mapId': k['mapId'], 'x': int(k['x']), 'y': int(k['y'])}
            old = self.p.ship()['lootId']
            self.p.d['active_ship'] = sid
            new = self.p.ship()
            dest = new.get('position')
            if travel and dest and H.parked(dest.get('mapId')):
                k.update(dest)
            row = self.p.ship_row(sid)
            hp = row.get('hp', g.get('hitMax', 0))
            hull_def = new.get('hull') or {'hitPoints': hp, 'nanoHull': 0}
            cargo = row.get('cargo', g.get('cargoSpaceMax', 0))
            g.update(typeId=self.p.ship_look(sid), hitMax=hp, maxNanoHull=hp, hitPoints=min(hull_def['hitPoints'], hp), nanoHull=hull_def['nanoHull'],
                     cargoSpaceMax=cargo)
            self.p.sync_cargo()                                    # free space = the new ship's cargo - ores
            self.p.sync_equipment()
            self.p.dirty = True
        # apply_stats marks the states as "sent": if its messages were dropped the new ship's AJP-01 (CPUInitializationCommand)
        # never went out, the space map showed the old ship's jump panel (user report 2026-10-25)
        stats = self.apply_stats()
        self.log('   ship changed: %s -> %s (shipId %s)' % (old, new['lootId'], sid))
        return [reply(1, ok=stack_msg('info_text_switch_active_hangar_success'))] + stats, True

    def designs(self, sid=None):
        """Design list in the hangar (drop-down): the ship's own appearance + purchased designs."""
        s = self.p.ship(sid)
        return [s['lootId']] + list(s.get('designs', []))

    def change_model(self, f):
        """HangarShipChangeShipModelRequest {shipId, lootId} (the design menu in the hangar, UINewHangarSystem.DropdownValueChanged)
        -> HangarShipChangeShipModelCommand {resultId 1}. When the appearance of the active ship changes (messages, True): the session makes the ship
        reload (ShipInitializationCommand.typeId = design)."""
        sid = str(f.get('shipId'))
        loot = f.get('lootId', '')
        reply = lambda res, err=None: ('HangarShipChangeShipModelCommand', {'resultId': res, 'errorMessage': err})
        if sid not in self.p.d['ships']:
            return [reply(0, stack_msg('dse_ship_not_exist'))], False
        if loot not in self.designs(sid):
            self.log('   no design: %s (%s)' % (loot, self.p.ship(sid)['lootId']))
            return [reply(0, stack_msg('eqt_error_generic'))], False
        with self.p.lock:
            ship = self.p.ship(sid)
            old = self.p.ship_look(sid)
            ship['design'] = None if loot == ship['lootId'] else loot
            trimmed = self.trim_slots(sid)               # if the design has fewer slots (Tyrannos 15 lasers, *-6 no rockets) the excess goes to the inventory
            active = sid == self.p.d['active_ship']
            if active:
                self.p.d['ship']['typeId'] = self.p.ship_look(sid)
                self.p.sync_equipment()
            self.p.dirty = True
        self.log('   appearance: %s -> %s' % (old, self.p.ship_look(sid)))
        # those that went to the inventory are not fitted in the client either (before, they looked fitted until the hangar list was asked for again)
        freed = [self.equipment_cmd(sid)] + self.item_updates(trimmed) if trimmed else []
        # the design's own values (player_profile.ship_row): speed, HP, slots, bonuses
        return [reply(1)] + freed + (self.apply_stats() if active else []), active and old != self.p.ship_look(sid)

    def switch_config(self, n):
        """The client's "S|CFG|n|..." request (save: t~591 and 598). The response in the order of the save: interface refresh, appearance, HP;
        shield, 0|n|e, appearance, 0|n|INV, 0|S|CFG|n; speed."""
        ship = self.p.ship()
        n = int(n)
        if str(n) not in ship['configs']:
            return []
        if n != 1 and ((self.p.d.get('pve') or {}).get('astral') or {}).get('run'):     # forum 162090: in Astral only Config 1
            self.log('   Astral: Config %d is closed' % n)
            return [legacy('0|S|CFG|1')]
        now = time.time()
        if now - getattr(self, 'last_config', 0) < CONFIG_COOLDOWN_SEC:       # save: the second switch after 2.4 s was rejected
            self.log('   config switch waiting')
            return [legacy('0|A|STM|config_change_failed_time')]
        self.last_config = now
        g = self.p.d['ship']
        with self.p.lock:
            # each config keeps its own shield: save the current one before leaving it
            shields = ship.setdefault('shield_generators', {})
            shields[str(ship['active_config'])] = int(g.get('shield', 0))
            ship['active_config'] = n
            self.p.sync_equipment()
            self.p.dirty = True
        # HP, shield, speed and appearance are below in the save's order; the others (the config's CPUs and launcher on the shortcut bar, module
        # icons, cargo) were being dropped: the bar showed the old config's CPUs
        later = [m for m in self.apply_stats() if m[0] not in ('AttributeShipSpeedUpdateCommand', 'HitpointInfoCommand',
                                                                 'AttributeShieldUpdateCommand', 'ShipExtensionsCommand')]
        with self.p.lock:
            # restore the new config's own shield (never used yet: starts empty), capped by its shieldMax
            g['shield'] = max(0, min(int(shields.get(str(n), 0)), g.get('shieldMax', 0)))
        uid = self.p.user_id
        stage = ('ShipExtensionsCommand', {'userId': uid, 'extensionStage': self.p.d.get('expansion_stage', 1)})
        s = self.stats()
        msgs = [('RefreshSelectedUICategoryCommand', {}), stage,
                ('HitpointInfoCommand', dict(hitpoints=int(g.get('hitPoints', 0)), hitpointsMax=g.get('hitMax', 0),
                                             nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0))),
                ('AttributeShieldUpdateCommand', {'shieldNow': int(g.get('shield', 0)), 'shieldMax': g.get('shieldMax', 0)}),
                # appearance of the shield skill (in the save's account without the skill shieldSkillId 0: if the client has it, it removes ShieldEffect; K3)
                SKL.shield_cmd(self.p),
                legacy('0|n|e|%d|0|0' % uid), stage, legacy('0|n|INV|%d|0' % uid), legacy('0|S|CFG|%d' % n)]
        if s['speed'] is not None:
            msgs.append(('AttributeShipSpeedUpdateCommand', {'newSpeed': s['speed'], 'displaySpeed': s['display']}))
        self.log('   config %d: %s' % (n, ', '.join('%s %d' % (k, len(v)) for k, v in self.p.d['equipment'].items() if v)))
        # + the drones' designs in this config (appearance in space) and the P.E.T.'s equipment in this config (if in space)
        return msgs + later + self.drone_msgs() + self.pet.refresh()
