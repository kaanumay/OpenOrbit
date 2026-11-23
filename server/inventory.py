"""The player's items by lootId in a single interface (roadmap stage 5): Assembly recipes, keyed boxes, Dispatch and Skylab fees count and
spend them without caring which store they sit in.

  currency_credits / currency_uridium     the pilot's credits / uridium (spending is written to the account history)
  resource_ore_<ore>                      ore in the cargo (shop.ORES types)
  resource_logfile                        log disks (gate counter: profile kapilar.log_disk)
  ammunition_*                            ammo
  tech_*                                  technology items (technology.py counter)
  equipment_* / drone_* / pet_*           unequipped item instances in the inventory (profile items)
  ship_*                                  inactive ships (Plus recipes spend the base ship; stage 6): the ship and its configs are deleted,
                                          its equipped items return to the inventory, its designs go
  others                                  resource store (profile diger_esyalar: Assembly materials, keys, coupons ...)
"""
import os

import game_data as DATA
import technology as TECH

HERE = os.path.dirname(os.path.abspath(__file__))
ORES = {loot: int(t) for t, loot in DATA.shared('items.json')['ores']['kinds'].items()}
CURRENCY = {'currency_credits': ('credits', 'credits'), 'currency_uridium': ('uridium', 'uridium')}
ITEM_PREFIXES = ('equipment_', 'drone_', 'pet_')
_CLIENT = DATA.shared('client_items.json')['items']


def client_item_ok(loot):
    """Whether it can go to the client's inventory as an item. The client's AssemblyInventoryIndex.UpdateItem throws a NullReference for ores
    (resource_ore_*: the client counts them with AttributeOreCountUpdateCommand) and for ItemTypes without a stack limit (Gold Pass, Lottery
    Capsule, Trinity VIP Badge); since the broken item stays in the changed list, every later inventory update broke too, and the Assembly
    index was never built at login: Synthesis and Assembly resource counts were always 0 (live trial Ö6, H134; tried one by one: a currency
    update does not break it, the recorded server sends it too)."""
    if loot.startswith('resource_ore_'):
        return False
    c = _CLIENT.get(loot)
    if loot.startswith('ship_') and c:           # Assembly's base ship counter: ships with a trait list (traits) (slotable on all of them)
        return any(k in c for k in ('slots', 'selling', 'equippable', 'stack'))
    return not (c and loot.startswith('resource_') and c.get('class_name') == 'ItemType' and 'stack' not in c)


def client_filter(msgs):
    """From the outgoing messages, the InventoryItemUpdatedCommands that would break the client's inventory (client_item_ok) are dropped."""
    if not any(n == 'InventoryItemUpdatedCommand' for n, f in msgs):
        return msgs
    return [(n, f) for n, f in msgs if n != 'InventoryItemUpdatedCommand' or client_item_ok((f.get('item') or {}).get('lootId', ''))]


# every record kept per item id (forgotten with the item: sale, spending; the panel save editor's delete has the same list)
ITEM_RECORDS = ('item_level', 'upgrade_level', 'upgrade_paid', 'unstable', 'particle', 'qfc', 'resonators')


def forget(p, iid):
    """The item's own records go with it (under the profile lock)."""
    for k in ITEM_RECORDS:
        p.d.get(k, {}).pop(str(iid), None)


def on_loan(p):
    """The Astral run (astral.loan) -> (ship ids, item ids) that are not the player's to spend or sell: the rented ship and items (the run's
    end deletes them) and, while inside, the player's own parked ship (swap_out activates it again)."""
    r = ((p.d.get('pve') or {}).get('astral') or {}).get('run') or {}
    ships = {str(r['sid'])} if r.get('sid') else set()
    if r.get('inside') and (r.get('backup') or {}).get('active') is not None:
        ships.add(str(r['backup']['active']))
    return ships, {int(i) for i in list(r.get('items') or []) + list(r.get('inventory') or [])}


def free_items(p, loot):
    """Unequipped item instances (itemId list); not one with an upgrade running or waiting to be collected (its payment would be lost),
    nor a rented one (Astral)."""
    import upgrades as UPG
    eq, lv, rented = p.equipped_ids(), p.d.get('upgrade_level', {}), on_loan(p)[1]
    ids = [int(i) for i, l in p.d['items'].items() if l == loot and int(i) not in eq and int(i) not in rented and not UPG.busy(p, i)]
    return sorted(ids, key=lambda i: (int(lv.get(str(i), 0)), i))      # forum 160116: the spent one is "the lowest level in stock"


def count(p, loot):
    if loot in CURRENCY:
        return int(p.d['pilot'].get(CURRENCY[loot][0], 0))
    if loot in ORES:
        return p.ore_count(ORES[loot])
    if loot == 'resource_logfile':
        return int((p.d.get('gates') or {}).get('log_disk', 0))
    if loot.startswith('ammunition_'):
        return p.ammo(loot)
    if loot.startswith('tech_'):
        return TECH.count(p, loot)
    if loot.startswith(ITEM_PREFIXES):
        return len(free_items(p, loot))
    if loot.startswith('ship_'):
        return len(spare_ships(p, loot))
    return p.resource(loot)


def spare_ships(p, loot):
    """Ships that can be spent: of this type, inactive, not rented or parked by an Astral run (shipId list)."""
    loan = on_loan(p)[0]
    return [sid for sid, s in p.d['ships'].items() if s['lootId'] == loot and sid != str(p.d['active_ship']) and sid not in loan]


def client_count(p, loot):
    """The amount that goes to the client's Assembly counter. Ships including the active one: the client knows a recipe's base ship only from this
    counter (it does not add ships to the item list itself); it was never sent, so in Plus recipes an owned ship appeared "missing"
    (user 2026-10-19: Solaris Plus). The active ship is not spent: the game's warning on building (assembly.build)."""
    if loot.startswith('ship_'):
        return sum(1 for s in p.d['ships'].values() if s['lootId'] == loot)
    return count(p, loot)


def spendable(loot):
    return True


def missing(p, need):
    """Missing ones {lootId: shortfall} (including the unspendable)."""
    return {k: n - count(p, k) for k, n in need.items() if count(p, k) < n or not spendable(k)}


def spend(p, need, reason='buy_SPECIAL', detail=''):
    """Spends all together if all are present -> list of what was spent; if one is short, none (None)."""
    if missing(p, need):
        return None
    removed = []
    for loot, n in need.items():
        if n <= 0:
            continue
        p.ach('spend', loot=loot, count=n)               # Pass quests: spend an item (quest_tracker.py)
        if loot in CURRENCY:
            p.gain(**{CURRENCY[loot][1]: -n, 'reason': reason, 'detail': detail})
        elif loot in ORES:
            p.remove_ores({ORES[loot]: n})
        elif loot == 'resource_logfile':
            with p.lock:
                p.d['gates']['log_disk'] -= n
                p.dirty = True
        elif loot.startswith('ammunition_'):
            p.use_ammo(loot, n, event=False, paid=True)   # already counted above as 'spend' (no double count)
        elif loot.startswith('tech_'):
            TECH.add(p, loot, -n)
        elif loot.startswith('ship_'):
            for sid in spare_ships(p, loot)[:n]:
                with p.lock:
                    del p.d['ships'][sid]                 # its configs go: equipped items return to the inventory
                    p.dirty = True
        elif loot.startswith(ITEM_PREFIXES):
            for iid in free_items(p, loot)[:n]:
                with p.lock:
                    del p.d['items'][str(iid)]
                    forget(p, iid)
                    p.dirty = True
                removed.append(iid)
        else:
            p.add_resource(loot, -n)
    return removed


def update_msgs(m, p, loots, removed=()):
    """UI update for the changed items (with the shop helpers): money, cargo, ammo, resource store, deleted instances."""
    msgs = [('InventoryItemRemovedCommand', {'itemId': iid}) for iid in removed]
    if not m:
        return msgs
    if any(l in CURRENCY for l in loots):
        msgs += m.money_msgs()
    if any(l.startswith('ship_') for l in loots):
        msgs.append(m.ships_cmd())                        # the spent ship is removed from the hangar list
        msgs += m.ship_count_msgs([l for l in loots if l.startswith('ship_')])     # Assembly counter
    ores = sorted(ORES[l] for l in loots if l in ORES)
    if ores:
        msgs += [('AttributeOreCountUpdateCommand', {'oreCountList': p.d['ores']}), m.ore_pack(ores)]
    for loot in loots:
        if loot in CURRENCY or loot in ORES or loot.startswith(ITEM_PREFIXES + ('ship_',)):
            continue
        n = count(p, loot)
        if loot.startswith('ammunition_'):
            st = p.menu_status(loot)
            msgs += [('MenuItemStatusCommand', st)] if st else []
        elif loot.startswith('tech_'):
            st = p.menu_status(loot)                    # the counter of the technology item on the shortcut bar
            msgs += [('MenuItemStatusCommand', st)] if st else []
            continue
        iid = m.item_id(loot)
        msgs += [m.inv_item(iid, loot, n), m.pack([m.hangar_item(iid, loot, n)])]
    return msgs
