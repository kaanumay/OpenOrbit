"""Ship modules and unstable modules (roadmap stage 6; data in data/ship_modules.json <- tools/ship_modules.py).

Normal modules (DMG-CHT01, HP-VP01, SPC-XP01 ...): fitted in the hangar to the config's "upgrades" slot (HangarShipEquipmentMsg.upgrades;
the slot count comes from the client's ship data: 3 on most ships, 4 on Plus ships). The effect applies only on the ships in the description (the client's text
"This ship upgrade module can be used on the following ships: ..."); the EP of SPC-XP01/02 up to level 16.
Unstable modules (DMG-X1 ... XV03, the HP-/SHD-/SPC- series): each instance has random attributes (UnstableAttributeModule {attribute,
boostValue}; names are the client's items_equipment_shipupgrade_modifiertype_* keys) and the ships it is valid on (shipDesigns);
the client's Restabilize window (requests taken from the client's code):
  on login / on change      UnstableModulesListCommand {allModules, shardCommand {chipLeft, shardsLeft}}
  UnstableModuleRerollRequest {itemId}        an Unstable Shard is spent, only the attributes are rerolled (the ships stay the same: official
      FAQ "only the module stat modifiers will be regenerated, not the ships"); the previous ones are kept
      -> UnstableModuleRestabilizeResultCommand {itemId, oldModule, newModule, success}
  UnstableModuleRestabiliseRequest {itemId, isSalvage}  isSalvage: by paying Salvage Core etc. the previous attributes are restored ("Your
      unstable module has been salvaged to retain the same modifiers"); otherwise the new one stays
  UnstableModuleRecycleRequest {itemId}        the module is dismantled, the Unstable Shard is returned
Values follow the real recording (UnstableModulesListCommand) and the wiki, per series (data ship_modules.json unstable.restabilize and
.interval <- tools/ship_modules.py): the shard received on recycling, the reroll cost and allowance (X1/XW01 2/10/10, X2 and the in-between series
4/20/8, XSP01 20/100/4, XT10 30/150/2); the retain (Salvage) cost is 200 Salvage Core + 38 ABR + 6 Indoctrine Oil on every module. Attribute
values are whole-number percents, from the series' two-tier interval (big chance / small chance: SMALL_CHANCE); the modules in the recording have 1-3 attributes
(the main attribute from the module's family, the others from the SECONDARY pool at 1-3%) and 1-3 ships. Adaptation (not in the recording): the tier chance,
the weights of the attribute and ship counts, the X1/X2/XW01 intervals (wiki "Randomly").
In the profile: unstable {itemId: {attribute: [[name, value]], ships, right, previous}}.
"""
import json, os, random, re

import inventory as INV
import ranks as RT

HERE = os.path.dirname(os.path.abspath(__file__))
M = json.load(open(os.path.join(HERE, 'data', 'ship_modules.json'), encoding='utf8'))['modules']
ITEMS = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))['items']
SHARD, CHIP = 'resource_collectable_unstable-shard', 'resource_collectable_optigrad-chip'
ATTR_KEYS = {'damage': ('laser', 'rocket'), 'dmg_laser': ('laser',), 'dmg_rockets': ('rocket',), 'dmg_npc': ('npc',), 'dmg_pvp': ('pvp',),
             'hitpoints': ('can',), 'shield': ('kalkan',), 'speed': ('speed',), 'evasion': ('evasion',), 'hitchance_laser': ('laser_hit_chance',),
             'hitchance_rocket': ('rocket_hit_chance',), 'experience': ('ep',), 'honour': ('honor',), 'shield_penetration': ('shield_penetration',)}
POOL = {'DAMAGE': ['damage', 'dmg_laser', 'dmg_rockets', 'dmg_npc'], 'HP': ['hitpoints'], 'SHIELD': ['shield'],
        'SPECIAL': ['speed', 'evasion', 'hitchance_laser', 'hitchance_rocket', 'shield_penetration']}      # main attribute (the client's description)
RETAIN = {'resource_collectable_salvage-core': 200, 'resource_collectable_axion-beam-regulator': 38,
          'resource_collectable_indoctrineoil': 6}          # retainCost in the recording, the same on every module (wiki "Salvage Expansion")
XP_MAX_LEVEL = 16
UPGRADE_SLOTS = 3
SMALL_CHANCE = 0.2          # in two-tier series (XV01, XU, XHD01 ...) the probability of the small chance (high tier): the client says "moderate chance" (adaptation)
PRIORITY_CHANCE = 0.5        # probability of drawing from the priority list on each ship pick (6 of the 12 ships in the recording were priority)
SECONDARY = ('damage', 'dmg_laser', 'dmg_rockets', 'dmg_npc', 'dmg_pvp', 'hitpoints', 'shield', 'speed', 'evasion', 'hitchance_laser',
           'hitchance_rocket', 'shield_penetration')      # the pool of the 2nd and 3rd attribute (recording: DMG_NPC 1 on SPC-XU03, HITCHANCE_LASER 3 and SHIELD 1 on DMG-XT10)


def mod(name, **f):
    f['_'] = name
    return f


def is_module(loot):
    return loot in M


def unstable(loot):
    return 'unstable' in M.get(loot, {})


def slots(ship_loot):
    """The ship's module slots (the client's ship data: ship_upgrades)."""
    return int((ITEMS.get(ship_loot, {}).get('slots') or {}).get('ship_upgrades', UPGRADE_SLOTS))


def ships_for(loot):
    return M.get(loot, {}).get('ships', [])


def all_ships():
    """Ships an unstable module can be rolled for: the server's ships (items.json ships)."""
    global _SHIPS
    if _SHIPS is None:
        _SHIPS = sorted(json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))['ships'])
    return _SHIPS


_SHIPS = None


# ------------------------------------------------------------ unstable module values
def restab(loot):
    """A series' Restabilize values for an unstable module: refund (shard received on recycling), charge (reroll), right (how many times at most)."""
    return M[loot]['unstable']['restabilize']


def pick_value(unstable, attr, rng):
    """Value of the main attribute: the series' interval (the attribute's own interval if it has one); the small chance (high tier) with probability SMALL_CHANCE;
    whole-number percent (the boostValues in the recording are always whole numbers)."""
    a = unstable['interval']
    a = a.get('attribute', {}).get(attr) or a
    lo, hi = a['lowercase'] if a.get('lowercase') and rng.random() < SMALL_CHANCE else a['caps']
    return rng.randint(lo, hi) / 100.0


def roll(loot, rng=random):
    """An unstable module's attributes and ships: 1-3 attributes (one from the module's family and within the series' interval, the others small) and 1-3 ships
    (recording: 7 modules with 1, 1, 1, 1, 2, 2 and 3 ships; priority ships are common but not required)."""
    info = M[loot]
    unstable = info['unstable']
    main = rng.choice(POOL.get(info['type'], POOL['DAMAGE']))
    vals = [[main, pick_value(unstable, main, rng)]]
    vals += [[a, rng.randint(1, max(3, unstable['interval']['caps'][1])) / 100.0] for a in rng.sample([a for a in SECONDARY if a != main], rng.choices((0, 1, 2), (6, 3, 1))[0])]
    rng.shuffle(vals)                      # in the recording the main attribute may not be first (DMG-XT10: DMG_NPC last)
    pref = list(unstable.get('preference', []))
    rest = [s for s in all_ships() if s not in pref and s not in unstable.get('exclude', ())]      # ships the series does not drop on (forum 162335)
    picks = []
    for _ in range(rng.choice((1, 1, 2, 3))):
        pool = [s for s in (pref if pref and rng.random() < PRIORITY_CHANCE else rest) if s not in picks] or [s for s in rest + pref if s not in picks]
        picks.append(rng.choice(pool))
    return dict(attribute=vals, ships=sorted(picks))


def state(p, iid):
    """The record of an unstable module instance (rolled on first look)."""
    d = p.d.setdefault('unstable', {})
    rec = d.get(str(iid))
    loot = p.d['items'].get(str(iid))
    if rec is None and loot and unstable(loot):
        rec = d[str(iid)] = dict(roll(loot), right=restab(loot)['right'])
        p.dirty = True
    elif rec and loot and unstable(loot) and rec['right'] > restab(loot)['right']:
        rec['right'] = restab(loot)['right']            # the old fixed 5 rights cannot exceed the series maximum (XT10 2, XSP01 4)
        p.dirty = True
    return rec


def module_msg(p, iid):
    rec, loot = state(p, iid), p.d['items'].get(str(iid))
    r = restab(loot)
    return mod('UnstableModuleModule', recycleReturns=r['refund'], rerollsMax=r['right'], rerollCost=r['charge'], rerollsLeft=rec['right'],
               retainCost=[mod('LootModule', lootId=l, amount=n, modifier='') for l, n in sorted(RETAIN.items())],
               attributes=[mod('UnstableAttributeModule', attribute=a, boostValue=round(v * 100, 2)) for a, v in rec['attribute']],
               shipDesigns=list(rec['ships']), itemId=int(iid), lootId=loot)


def ship_ids(loots):
    """The hangar tooltip's ship list (HangarShipEquipmentInventoryItem.ships): the client (TooltipPreparerFactory.ReturnShips) splits on ','
    , converts each part to a number and finds the ship by id (GetItemByShipId). Ship names (ship_goliath) read as 0."""
    return ','.join(str(ITEMS[l]['uid']) for l in loots if (ITEMS.get(l) or {}).get('uid') is not None)


def modifiers_str(p, iid):
    """The hangar tooltip attributes of an unstable module: "NAME,percent;..." (TooltipPreparerFactory.ReturnModifiers: the value is a whole number, the text
    items_equipment_shipupgrade_modifiertype_<name>). When empty the tooltip's "Type:" line stayed blank (user 2026-10-19)."""
    rec = state(p, iid) or {}
    return ';'.join('%s,%d' % (a.upper(), max(1, int(round(v * 100)))) for a, v in rec.get('attribute', []) if v > 0)


def shard_cmd(p):
    return mod('UnstableModulesShardCommand', chipLeft=p.resource(CHIP), shardsLeft=p.resource(SHARD))


def list_cmd(p, reset=False):
    import particle as PC                                       # particle balls and breakers (OptiGrad Chip; stage 9b)
    ids = sorted(int(i) for i, l in p.d['items'].items() if unstable(l))
    return ('UnstableModulesListCommand', dict(allModules=[module_msg(p, i) for i in ids] + PC.modules(p), resetUI=reset,
                                                 isDiscountRunning=False, shardCommand=shard_cmd(p)))


# ------------------------------------------------------------ effects
def kind(loot):
    """The module's type (DAMAGE, HP, SHIELD, SPECIAL) or None."""
    return M.get(loot or '', {}).get('type')


def type_taken(p, iid, current):
    """Is another module of this module's type fitted on the ship: official FAQ ("New Ship Upgrade Modules FAQ"): a module once per ship,
    one module of each type (HP, Damage, Shield, Special) (user report 2026-10-25: more than one of the same type could be fitted)."""
    k = kind(p.d['items'].get(str(iid)))
    return bool(k) and any(i != iid and kind(p.d['items'].get(str(i))) == k for i in current)


def mods(p, ship_loot, iids, level=None):
    """Bonuses of the fitted modules (only on a valid ship; the first of each type: second ones fitted before the rule do not count)."""
    out, seen = {}, set()
    for iid in iids:
        loot = p.d['items'].get(str(iid))
        info = M.get(loot or '')
        if not info or info['type'] in seen:
            continue
        seen.add(info['type'])
        if 'unstable' in info:
            rec = state(p, iid)
            if ship_loot not in rec['ships']:
                continue
            eff = {}
            for a, v in rec['attribute']:
                for k in ATTR_KEYS.get(a, ()):
                    eff[k] = eff.get(k, 0) + v
        else:
            if ship_loot not in info['ships']:
                continue
            eff = dict(info['effects'])
            if 'ep' in eff and loot.startswith('equipment_shipupgrade_spc-xp') and (level or 0) >= XP_MAX_LEVEL:
                eff.pop('ep')                                   # SPC-XP01/02: up to level 16
        for k, v in eff.items():
            out[k] = out.get(k, 0) + v
    return out


def equip_allowed(p, iid, ship_loot):
    """A module fits only its own ships: the ones in the description normally, the rolled ships for unstable (official FAQ: the tooltip says "the ships it
    can be equipped on"; in live round 2 DMG-XSP01 was fitting a Solaris Plus that was not in its list)."""
    loot = p.d['items'].get(str(iid))
    info = M.get(loot or '')
    return bool(info) and ship_loot in (state(p, iid)['ships'] if 'unstable' in info else info['ships'])


# ------------------------------------------------------------ requests
class Modules:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None

    def result(self, iid, old, new, ok=True):
        return ('UnstableModuleRestabilizeResultCommand', dict(itemId=int(iid), oldModule=old, newModule=new, success=ok))

    def reroll(self, f):
        iid = int(f.get('itemId') or 0)
        loot = self.p.d['items'].get(str(iid))
        import particle as PC
        if loot and PC.restabilizable(loot):                    # ball/breaker: extra attributes with OptiGrad Chip
            from legacy_protocol import legacy
            res = PC.reroll(self.p, iid)
            if isinstance(res, str):
                return [legacy('0|A|STM|%s' % res), list_cmd(self.p)]
            self.log('   Restabilize: %s -> %s' % (loot, PC.state(self.p, iid)['attribute']))
            return INV.update_msgs(self.m, self.p, [CHIP]) + self.after(iid, [self.result(iid, *res)])
        if not loot or not unstable(loot):
            from legacy_protocol import legacy
            return [legacy('0|A|STM|msg_reroll_error_item')]
        rec = state(self.p, iid)
        if rec['right'] <= 0:
            from legacy_protocol import legacy
            return [legacy('0|A|STM|msg_reroll_error_item')]
        cost = restab(loot)['charge']
        if INV.missing(self.p, {SHARD: cost}):
            from legacy_protocol import legacy
            return [legacy('0|A|STM|msg_reroll_error_shards'), list_cmd(self.p)]
        old = module_msg(self.p, iid)
        self.p.add_resource(SHARD, -cost)
        with self.p.lock:
            rec['previous'] = dict(attribute=rec['attribute'])
            rec['attribute'] = roll(loot)['attribute']             # ships do not change (official FAQ)
            rec['right'] -= 1
            self.p.dirty = True
        self.log('   Restabilize: %s -> %s %s' % (loot, rec['attribute'], rec['ships']))
        RT.note(self.p, 'his_rerolled_unstable_module', loot, cost)    # logbook (%NAME% from info, %COUNT%)
        return self.after(iid, [self.result(iid, old, module_msg(self.p, iid))])

    def restabilise(self, f):
        iid = int(f.get('itemId') or 0)
        import particle as PC
        if PC.restabilizable(self.p.d['items'].get(str(iid), '')):      # ball/breaker: go back to the old one or keep the new one
            if f.get('isSalvage'):
                PC.revert(self.p, iid)
            else:
                (PC.state(self.p, iid) or {}).pop('previous', None)
            return self.after(iid, [])
        rec = state(self.p, iid) if str(iid) in self.p.d['items'] else None
        if not rec:
            return []
        if not f.get('isSalvage'):
            with self.p.lock:
                rec.pop('previous', None)
                self.p.dirty = True
            return [list_cmd(self.p)]
        if not rec.get('previous'):
            return [list_cmd(self.p)]
        if INV.missing(self.p, RETAIN):
            from legacy_protocol import legacy
            return [legacy('0|A|STM|msg_reroll_error_salvage'), list_cmd(self.p)]
        removed = INV.spend(self.p, RETAIN, reason='buy_SPECIAL', detail='salvage')
        old = module_msg(self.p, iid)
        with self.p.lock:
            rec.update(rec.pop('previous'))
            self.p.dirty = True
        self.log('   Salvage: %s returned to its previous attributes' % self.p.d['items'][str(iid)])
        return INV.update_msgs(self.m, self.p, list(RETAIN), removed) + self.after(iid, [self.result(iid, old, module_msg(self.p, iid))])

    def recycle(self, f):
        iid = int(f.get('itemId') or 0)
        loot = self.p.d['items'].get(str(iid))
        import particle as PC
        if loot and PC.restabilizable(loot):                    # ball/breaker: OptiGrad Chip and 80% of the upgrade material
            from legacy_protocol import legacy
            got = PC.recycle(self.p, iid)
            if got is None:
                return [legacy('0|A|STM|msg_reroll_error_item'), list_cmd(self.p)]
            msgs = [('InventoryItemRemovedCommand', {'itemId': iid})]
            for l, n in got.items():
                msgs += self.m.reward(l, n) if self.m else []
                if not self.m:
                    self.p.add_resource(l, n)
            self.log('   recycle: %s -> %s' % (loot, got))
            return msgs + [('UnstableModuleRecycleResultCommand', dict(itemId=iid, shardCommand=shard_cmd(self.p))), list_cmd(self.p)]
        if not loot or not unstable(loot):
            from legacy_protocol import legacy
            return [legacy('0|A|STM|msg_reroll_error_item')]
        worn = iid in self.p.equipped_ids()                  # forum 162335: it can be recycled while fitted too; first removed from its slot
        with self.p.lock:
            for s in self.p.d['ships'].values():
                for cfg in s.get('configs', {}).values():
                    for lst in cfg.values():
                        if isinstance(lst, list) and iid in lst:
                            lst.remove(iid)
            del self.p.d['items'][str(iid)]
            self.p.d.get('unstable', {}).pop(str(iid), None)
            self.p.dirty = True
        back = restab(loot)['refund']
        msgs = [('InventoryItemRemovedCommand', {'itemId': iid})] + (self.m.reward(SHARD, back) if self.m else [])
        if not self.m:
            self.p.add_resource(SHARD, back)
        self.log('   recycle: %s -> %d shard' % (loot, back))
        RT.note(self.p, 'his_recycled_unstable_module', loot, back)
        if worn and self.m:
            msgs += [self.m.equipment_cmd()] + self.m.apply_stats()
        return msgs + [('UnstableModuleRecycleResultCommand', dict(itemId=iid, shardCommand=shard_cmd(self.p))), list_cmd(self.p)]

    def after(self, iid, msgs):
        """If the fitted module changed, speed/shield/HP again."""
        out = msgs + [list_cmd(self.p)]
        if self.m and iid in self.p.equipped_ids():
            out += [self.m.equipment_cmd()] + self.m.apply_stats()
        return out

    def handle(self, name, f):
        fn = {'UnstableModuleRerollRequest': self.reroll, 'UnstableModuleRestabiliseRequest': self.restabilise,
              'UnstableModuleRecycleRequest': self.recycle}.get(name)
        if name == 'RerollWindowSettingsRequest':
            with self.p.lock:
                self.p.d['reroll_settings'] = f.get('rerollWindowSettingsModule') or {}
                self.p.dirty = True
            return []
        return fn(f) if fn else None
