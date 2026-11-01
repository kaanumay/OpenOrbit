"""Particle weapons and Singularity Drive (roadmap Stage 9b; data data/particle.json <- tools/particle.py, source official forum
FAQs and darkorbitwiki).

Items are instances in the inventory (profile items); in the hangar in the ship's slots: cannon 'cannon' (3, one of each type), breaker
'cannonShield' (6), drive 'drive', lens 'lens' (the numbers are in the client's ship data). Instance state in the profile: particle {itemId:
{attribute [[name, value]], right (reroll), star}}; the extra attributes of cannons and breakers are rolled when obtained (count and
range by quality), the sub-attributes of drives and lenses unlock at upgrade level 5/10/15/20. Hangar tooltip: the cannon's base damage is
extAttributes ('baseDamage'), attributes modifiers ("value,name;…"), the UL cannon's ship is ships.
Reroll: cannons and breakers in the Assembly's Restabilize tab (CannonUnstableModuleModule; OptiGrad Chip, 80% of the chip and
upgrade material on recycling; UL is not recycled), drives and lenses in the Singularity Drive window (LockAttributeItem*:
Horizon Shard, lock Containment Node).
In flight (Atis, in the world's loop):
  slug (shortcut bar 'cannons'): selected and fired at the target (if a cannon of the same type is equipped; one shared 4 s cooldown for all
      cannons, range 600); with RG-SL on, the selected slug fires on its own on a laser attack. CannonAttackCommand {cannonType, hit,
      attackerId, attackedId} + AttackHitCommand (attackType CANNON 21, cannonType, strike). Helios: 40% chance to jump to 5 targets
      within 275 (PlayVisualEffectCommand 8); Nidhogg: 20 s 5% corrosion weakness, 5 stacks (VisualModifierCommand 146); Indra: chain to 7
      targets, -15% per jump (PlayVisualEffectCommand 9).
  GSP (shortcut bar 'drives'): as much ammo as the number of equipped drives, cooldown 10 s; a 600-unit field around the main target hits
      once a second for 8 s (AttackHitCommand DRIVE 22; visual DA_SHOT 17-19, field DA_OUTER_FRIENDLY 152/154/156). Apex and Prime set
      multiplier (3-10 drives), after 6 Apex/Prime the field is 900 (the client's package descriptions). With AGS-X on, it fires on its
      own on a laser attack.
The breakers' and lenses' defense is against player weapons (with bot players, Stage 11).
"""
import json, math, os, random, time

import settings as SET
import inventory as INV

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'particle.json'), encoding='utf8'))
ITEMS = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))['items']
CANNONS, SHIELDS, DRIVES, LENSES = D['cannons'], D['breakers'], D['drives'], D['lenses']
SLUGS, GSP = D['slugs'], D['gsp']
C, DR = D['cannon_common'], D['drive_common']
PREFIX = {'equipment_weapon_cannon_': 'cannon', 'equipment_cannon_shield_': 'cannonShield', 'equipment_weapon_drive_': 'drive',
          'equipment_lens_': 'lens'}
SHIP_SLOTS = {'cannon': 'cannons', 'cannonShield': 'cannon_shields', 'drive': 'drives', 'lens': 'lenses'}
SLOTS = tuple(PREFIX.values())
CANNON_ATTACK, DRIVE_ATTACK = 21, 22                 # the client's AttackType
VE_THERMAL, VE_ELECTRO, VM_CORROSIVE = 8, 9, 146     # VisualEffectType, VisualModifier
COOLDOWN_CANNON, COOLDOWN_DRIVE = 60, 61             # CooldownType (shortcut bar groups)
CPU_CANNON, CPU_DRIVE = 'equipment_extra_cpu_rg-sl', 'equipment_extra_cpu_ags-x'
DMG_KEY = {'thermal': 'cannon_damage_thermal', 'corrosive': 'cannon_corrosive_damage', 'electro': 'cannon_electro_damage'}
DRIVE_SHIP_KEYS = {'drive_experience': 'ep', 'drive_honour': 'honor', 'drive_evasion': 'evasion',     # the effect of the drive/lens and the breaker on the ship
                   'experience': 'ep', 'honour': 'honor', 'hitpoints': 'hp'}


def mod(_cls, **f):
    f['_'] = _cls
    return f


def slot_of(loot):
    return next((s for p, s in PREFIX.items() if loot.startswith(p)), None)


def is_item(loot):
    return slot_of(loot) is not None


def slots(ship_loot, slot):
    return int((ITEMS.get(ship_loot, {}).get('slots') or {}).get(SHIP_SLOTS[slot], 0))


def state(p, iid):
    return p.d.get('particle', {}).get(str(iid))


def tier(loot):
    """Quality order: cannon 0-6 (C … UL), breaker 0-5 (01 … 06), drive/lens 0."""
    row = CANNONS.get(loot) or SHIELDS.get(loot)
    return row['order'] if row else 0


def pool(loot):
    if loot in CANNONS:
        return D['attributes']['top'][CANNONS[loot]['element']]
    if loot in SHIELDS:
        return D['attributes']['breaker'][SHIELDS[loot]['element']]
    return None


def roll(loot, rng=random, n=None):
    """The cannon's/breaker's extra attributes: count and range by quality; without repeats."""
    pl = pool(loot)
    if not pl:
        return []
    count = n if n is not None else (CANNONS.get(loot) or SHIELDS[loot])['extra']
    names = rng.sample(sorted(pl), min(count, len(pl)))
    t = tier(loot)
    return [[a, round(rng.uniform(*pl[a][t]), 2)] for a in names]


def rerolls(loot):
    return D['renewal']['right'][tier(loot)] if (loot in CANNONS or loot in SHIELDS) else 0


def create(p, loot, rng=random, star=0):
    """New instance -> itemId (the cannon's/breaker's extra attributes are rolled)."""
    iid = p.new_item(loot)
    st = {'attribute': roll(loot, rng), 'right': rerolls(loot), 'star': star}
    with p.lock:
        p.d.setdefault('particle', {})[str(iid)] = st
        p.dirty = True
    return iid


def level(p, iid):
    """Upgrade level (as the client shows it: 1-20)."""
    import upgrades as UPG
    return UPG.item_level(p, iid) + 1


def ensure(p, iid, rng=random):
    """The drive's/lens's sub-attributes: one each at upgrade level 5/10/15/20 (at most 4) -> state."""
    loot = p.d['items'].get(str(iid), '')
    st = state(p, iid)
    if st is None and is_item(loot):
        st = {'attribute': roll(loot, rng), 'right': rerolls(loot), 'star': 0}
        with p.lock:
            p.d.setdefault('particle', {})[str(iid)] = st
            p.dirty = True
    if st is not None and st['right'] > rerolls(loot):         # the replacement limit was dropped (URETIM-4): the remaining allowance in old saves
        st['right'] = rerolls(loot)
        p.dirty = True
    if st is not None and (loot in DRIVES or loot in LENSES):
        need = sum(1 for lv in D['lock']['levels'] if level(p, iid) >= lv)
        pl = D['attributes']['drive']
        while len(st['attribute']) < need:
            free = [a for a in sorted(pl) if not a.startswith('_') and a not in [x[0] for x in st['attribute']]]
            a = rng.choice(free)
            st['attribute'].append([a, round(rng.uniform(*pl[a]), 2)])
            p.dirty = True
    return st


def attrs(p, iid):
    st = ensure(p, iid)
    return {a: v for a, v in (st or {}).get('attribute', [])}


def modifiers_str(p, iid):
    """Attribute rows of the hangar tooltip. Client (TooltipPreparerFactory.ReturnModifiers): "NAME,value;…", name first, value the last part;
    text items_equipment_shipupgrade_modifiertype_<lowercase name>, name in uppercase; for CANNON_IGNORE_DEF_* / DRIVE_IGNORE_DEF the value is
    plain, the others "%". Before, "value,name" was sent: the tooltip showed the raw name as "+cannon_strike_corrosive%" (live test H55)."""
    st = ensure(p, iid)
    return ';'.join('%s,%d' % (a.upper(), int(round(v))) for a, v in (st or {}).get('attribute', []))


def base_damage(p, iid, ship_loot=None):
    loot = p.d['items'].get(str(iid), '')
    row = CANNONS.get(loot)
    if not row:
        return 0
    st = state(p, iid) or {}
    dmg = row['base'] * C['star'][st.get('star', 0)]
    if row['ship'] and ship_loot == row['ship']:
        dmg *= C['ship_specific']                              # the UL cannon's own ship
    return dmg


def hangar_fields(p, iid, loot):
    """Fields to add to HangarShipEquipmentInventoryItem."""
    st = ensure(p, iid) or {}
    f = {'modifiers': modifiers_str(p, iid), 'star': st.get('star', 0)}
    if loot in CANNONS:
        f['extAttributes'] = [mod('TupleTwoModule', param0='baseDamage', param1=str(int(base_damage(p, iid))))]
        if CANNONS[loot]['ship']:
            import ship_module as GM                           # the tooltip's ship by numeric id (ReturnShips)
            f['ships'] = GM.ship_ids([CANNONS[loot]['ship']])
    return f


def equip_allowed(p, iid, slot, current):
    """-> error text or None: one cannon of each type on the ship."""
    loot = p.d['items'].get(str(iid), '')
    if slot == 'cannon':
        kind = CANNONS[loot]['type']
        if any(CANNONS.get(p.d['items'].get(str(i), ''), {}).get('type') == kind for i in current if i != iid):
            return 'the ship already has a %s cannon' % kind
    return None


def equipped(p, slot, sid=None, cid=None):
    return [i for i in p.config(cid, sid).get(slot, []) if str(i) in p.d['items']]


def cannon_for(p, element):
    """The cannon of this type equipped in the active config -> itemId or None."""
    return next((i for i in equipped(p, 'cannon') if CANNONS.get(p.d['items'][str(i)], {}).get('element') == element), None)


def shield_npc(p, e):
    """Damage bonus (points) of the equipped breakers against aliens of element e."""
    return sum(attrs(p, i).get('cannon_damage_npc_' + e, 0) for i in equipped(p, 'cannonShield'))


def mods(p, ship_loot, cfg):
    """Effects of the equipped drives and lenses on the ship (EP, honor, evasion)."""
    out = {}
    for slot in ('drive', 'lens', 'cannonShield'):
        for iid in cfg.get(slot, []):
            if str(iid) not in p.d['items']:
                continue
            for a, v in attrs(p, iid).items():
                k = DRIVE_SHIP_KEYS.get(a)
                if k:
                    out[k] = out.get(k, 0) + v / 100.0
    return out


def migrate(p):
    """Cannons, breakers, drives and lenses kept in storage before Stage 9b -> inventory instances. -> number moved."""
    moved = 0
    for loot, n in list(p.d.get('other_items', {}).items()):
        if is_item(loot) and loot in ITEMS and n > 0:
            for _ in range(int(n)):
                create(p, loot)
            p.add_resource(loot, -n)
            moved += int(n)
    return moved


# ---------------------------------------------------------------- Restabilize (cannons and breakers; ship_module.py)
def restabilizable(loot):
    return loot in CANNONS or loot in SHIELDS


def upgrade_returns(p, iid, share):
    """Share of the upgrade material (recycling and Synthesis)."""
    import upgrades as UPG
    spent = UPG.spent(p, iid) if hasattr(UPG, 'spent') else {}
    return {k: int(v * share) for k, v in spent.items() if int(v * share) > 0}


def attr_mods(st):
    """Attributes of the Restabilize and Update lists. The client (RerollStatsListItem / DriveStatsListItem) compares the name in uppercase to
    CANNON_IGNORE_DEF_* / DRIVE_IGNORE_DEF to show penetration plain, and lowercases it for the icon and text; when it went
    in lowercase, penetration showed as "51.53%" (live test H71)."""
    return [mod('UnstableAttributeModule', attribute=a.upper(), boostValue=float(v)) for a, v in (st or {}).get('attribute', [])]


def module_msg(p, iid):
    loot = p.d['items'][str(iid)]
    st = ensure(p, iid)
    t = tier(loot)
    back = upgrade_returns(p, iid, D['renewal']['refund'])
    return mod('CannonUnstableModuleModule', recycleReturns=D['renewal']['chip'][t],
               rerollsMax=rerolls(loot), rerollCost=D['renewal']['charge'][t], rerollsLeft=st['right'], retainCost=[],
               attributes=attr_mods(st),
               shipDesigns=[CANNONS[loot]['ship']] if CANNONS.get(loot, {}).get('ship') else [], itemId=int(iid), lootId=loot,
               upgradeReturns=[mod('LootModule', lootId=k, amount=v, modifier='') for k, v in back.items()],
               upgradeLevel=level(p, iid))          # the displayed level (same as H63: the list writes it as is, on a cannon 0 was shown too)


def modules(p):
    return [module_msg(p, int(i)) for i, l in sorted(p.d['items'].items(), key=lambda x: int(x[0])) if restabilizable(l)]


def reroll(p, iid, rng=random):
    """Attributes re-rolled with an OptiGrad Chip -> (old module, new module) or an error key."""
    loot = p.d['items'].get(str(iid), '')
    st = ensure(p, iid)
    if not restabilizable(loot) or not st:
        return 'msg_reroll_error_item'
    if st['right'] <= 0:
        return 'msg_reroll_error_item'
    cost = D['renewal']['charge'][tier(loot)]
    if INV.spend(p, {D['renewal']['chip_item']: cost}, 'buy_SPECIAL', 'cannon_reroll') is None:
        return 'msg_reroll_error_shards'
    old = module_msg(p, iid)
    with p.lock:
        st['previous'] = st['attribute']
        st['attribute'] = roll(loot, rng)
        st['right'] -= 1
        p.dirty = True
    return old, module_msg(p, iid)


def revert(p, iid):
    """The attributes before the reroll (choosing the old one in the Restabilize window) -> True: it changed."""
    st = state(p, iid)
    if not st or not st.get('previous'):
        return False
    with p.lock:
        st['attribute'] = st.pop('previous')
        p.dirty = True
    return True


def recycle(p, iid):
    """Recycling -> {lootId: count} or None (equipped)."""
    loot = p.d['items'].get(str(iid), '')
    if not restabilizable(loot) or iid in p.equipped_ids():
        return None
    got = upgrade_returns(p, iid, D['renewal']['refund'])
    chips = D['renewal']['chip'][tier(loot)]
    if chips:
        got[D['renewal']['chip_item']] = got.get(D['renewal']['chip_item'], 0) + chips
    with p.lock:
        del p.d['items'][str(iid)]
        p.d.get('particle', {}).pop(str(iid), None)
        p.dirty = True
    return got


# ---------------------------------------------------------------- sub-attributes of drives and lenses (LockAttributeItem*)
def lock_module(p, iid):
    loot = p.d['items'][str(iid)]
    st = ensure(p, iid)
    K = D['lock']
    # upgradeLevel is the displayed level (1-20): the Restabilize list writes it as is (hides it if 0), the Upgrade tab one more than the
    # inventory's; it used to start from 0, and the two tabs showed different levels (live test H63). The slots' openness from attributes
    return mod('LockAttributeItemModule', upgradeLevel=level(p, iid), lockCostLootAmounts=K['lock'], lockCostLoot=K['lock_item'],
               restabilizeCostLootAmounts=K['renewal'], restabilizeCostLoot=K['renewal_item'], lootId=loot,
               lockAttributeLevels=K['levels'],
               attributes=attr_mods(st), itemId=int(iid))


def lock_list_cmd(p):
    ids = [int(i) for i, l in sorted(p.d['items'].items(), key=lambda x: int(x[0])) if l in DRIVES or l in LENSES]
    return 'LockAttributeItemListCommand', {'remove': False, 'moduleList': [lock_module(p, i) for i in ids]}


def lock_reroll(p, iid, locks, rng=random):
    """Sub-attributes that are not locked, again (Horizon Shard; Containment Node per lock) -> True/False."""
    loot = p.d['items'].get(str(iid), '')
    st = ensure(p, iid)
    if not st or (loot not in DRIVES and loot not in LENSES) or not st['attribute']:
        return False
    locks = sorted({int(i) for i in locks or [] if 0 <= int(i) < len(st['attribute'])})
    if len(locks) >= len(st['attribute']):
        return False
    K = D['lock']
    k = min(len(locks), len(K['renewal']) - 1)
    need = {K['renewal_item']: K['renewal'][k]}
    if K['lock'][min(len(locks), len(K['lock']) - 1)]:
        need[K['lock_item']] = K['lock'][min(len(locks), len(K['lock']) - 1)]
    if INV.spend(p, need, 'buy_SPECIAL', 'drive_refine') is None:
        return False
    pl = D['attributes']['drive']
    keep = {st['attribute'][i][0] for i in locks}
    with p.lock:
        for i, (a, v) in enumerate(list(st['attribute'])):
            if i in locks:
                continue
            free = [x for x in sorted(pl) if not x.startswith('_') and x not in keep]
            b = rng.choice(free)
            keep.add(b)
            st['attribute'][i] = [b, round(rng.uniform(*pl[b]), 2)]
        p.dirty = True
    return True


# ---------------------------------------------------------------- flight
def drive_power(p, ids):
    """Total damage of the equipped drives (level, sub-attribute, set multiplier), field radius (Apex and Prime set) and the best drive's
    visual tier."""
    rows = [(i, p.d['items'][str(i)]) for i in ids]
    big = [l for i, l in rows if DRIVES[l]['shot'] >= 2]
    mult, area = 1.0, DR['area']
    for n, m, r in DR['set']:
        if len(big) >= n:
            mult, area = m, r
    total = 0.0
    for i, l in rows:
        a = attrs(p, i)
        d = DRIVES[l]['damage'] * (1 + 0.005 * (level(p, i) - 1)) * (1 + (a.get('drive_damage', 0) + a.get('drive_damage_npc', 0)) / 100.0)
        total += d * (mult if DRIVES[l]['shot'] >= 2 else 1.0)
    return total, area, max((DRIVES[l]['shot'] for i, l in rows), default=1)


class Shot:
    """The world's particle cannon and drive shots (called under the world lock)."""

    def __init__(self, world):
        self.w, self.p = world, world.p
        self.zones = []                # [{x, y, end, next, damage, target, vm}]
        self.corrosive = {}              # npc id -> [stacks, end]
        with self.p.lock:
            sel = self.p.d.setdefault('selected', {})
            sel.setdefault('slug', 'ammunition_slug_ths-d01')
            sel.setdefault('gsp', 'ammunition_spool_gsp-30')

    def ready(self, group, now):
        import combat_items as CIT
        return now >= CIT.ready_at(self.p, group)

    def cool(self, group, sec, now):
        import combat_items as CIT
        sec *= SET.multiplier('skill_cooldown', 'particle')     # panel: ability and item cooldowns (cannon and drive too)
        with self.p.lock:
            self.p.d.setdefault(CIT.TIMERS, {})[str(group)] = [now + sec, int(sec * 1000)]
            self.p.dirty = True
        ms = int(sec * 1000)
        self.w.send([CIT.timer_msg(group, ms)])
        self.w.later(sec, lambda: self.w.send([CIT.timer_msg(group, ms, cooling=False)]))

    def menu(self, item, act, now=None):
        """Shortcut bar: a slug or GSP is selected and fired if there is a target."""
        now = now or time.time()
        kind = 'slug' if item in SLUGS else 'gsp'
        if act not in (0, 1):
            return
        old = self.p.d['selected'].get(kind)
        if item != old and self.p.ammo(item) > 0:
            self.p.d['selected'][kind] = item
            self.p.dirty = True
            self.w.send([('MenuItemStatusCommand', st) for st in (self.p.menu_status(old) if old else None, self.p.menu_status(item)) if st])
            self.w.log('   %s selected: %s' % ('slug' if kind == 'slug' else 'GSP', item))
        if act == 0:
            return  # Category SELECT chooses ammo without firing a cannon/drive.
        n = self.w.npcs.get(self.w.target)
        if n and n.alive:
            (self.fire_cannon if kind == 'slug' else self.fire_drive)(n, now, item)

    def auto(self, n, now):
        """On a laser attack: RG-SL fires the selected slug, AGS-X fires the selected GSP on its own."""
        import combat_items as CIT
        if CIT.toggled(self.p, CPU_CANNON) and self.ready(COOLDOWN_CANNON, now):
            self.fire_cannon(n, now, self.p.d['selected'].get('slug'), auto=True)
        if CIT.toggled(self.p, CPU_DRIVE) and self.ready(COOLDOWN_DRIVE, now):
            self.fire_drive(n, now, self.p.d['selected'].get('gsp'), auto=True)

    def in_range(self, n, now, rng):
        hx, hy = self.w.hero_pos(now)
        nx, ny = n.mover.pos(now)
        return math.hypot(nx - hx, ny - hy) <= rng

    def others(self, x, y, radius, skip, now):
        out = []
        for m in self.w.npcs.values():
            if m.alive and m.id not in skip and not m.d.get('friendly'):
                mx, my = m.mover.pos(now)
                d = math.hypot(mx - x, my - y)
                if d <= radius:
                    out.append((d, m))
        return [m for d, m in sorted(out, key=lambda x: x[0])]

    # ------------------------------------------------------------ cannon
    def fire_cannon(self, n, now, slug, auto=False):
        w, p = self.w, self.p
        if not slug or slug not in SLUGS or w.hero_dead or w.jumping:
            return False
        element = SLUGS[slug]['element']
        iid = cannon_for(p, element)
        why = None
        if iid is None:
            why = 'no %s cannon equipped' % element
        elif not self.ready(COOLDOWN_CANNON, now):
            why = 'cooldown'
        elif p.ammo(slug) <= 0:
            why = 'no ammo'
        elif w.in_peace(*w.hero_pos(now)):
            why = 'safe zone'
        elif not self.in_range(n, now, C['range']):
            why = 'out of range'
        if why:
            if not auto:
                w.log('   cannon not fired (%s): %s' % (slug, why))
            return False
        p.use_ammo(slug, 1)
        loot = p.d['items'][str(iid)]
        row = CANNONS[loot]
        a = attrs(p, iid)
        e = row['element']
        self.cool(COOLDOWN_CANNON, C['interval_sec'] * max(0.1, 1 + p.mods().get('cannon_cooldown', 0)), now)    # Supercharge Plus -%50
        w.last_combat = now
        hit = random.random() < C['hit'] * (1 + a.get('cannon_hit_chance_' + e, 0) / 100.0 + p.mods().get('cannon_hit', 0))   # Lepus
        msgs = w.ammo_msgs(slug) + [('CannonAttackCommand', dict(cannonType=row['cannonType'], hit=hit, attackerId=w.hid, attackedId=n.id))]
        w.send(msgs)
        p.ach('shot', weapon='CANNON')
        if not hit:
            from world import attack_type
            w.send([('AttackMissedCommand', dict(attackType=attack_type(CANNON_ATTACK), targetUserId=n.id, skillColorId=0))])
            return True
        dmg = base_damage(p, iid, p.ship()['lootId']) * (1 + 0.005 * (level(p, iid) - 1)) * SLUGS[slug]['multiplier']
        dmg *= random.uniform(*C['damage_range']) * (1 + (a.get(DMG_KEY[e], 0) + a.get('cannon_damage_npc_' + e, 0) + shield_npc(p, e)) / 100.0)
        dmg *= 1 + p.mods().get('top', 0)
        crit = random.random() < C['crit'] + a.get('cannon_strike_' + e, 0) / 100.0
        if crit:
            dmg *= 1 + C['crit_damage'] + a.get('cannon_strike_damage_' + e, 0) / 100.0
        dmg = int(dmg)
        nx, ny = n.mover.pos(now)
        w.hit_npc(n.id, dmg, CANNON_ATTACK, strike=crit, cannon=row['cannonType'])
        if e == 'thermal':                                       # Helios: jump
            S = C['splash']
            near = self.others(nx, ny, S['radius'], {n.id}, now)[:S['target']]
            if near:
                w.send([('PlayVisualEffectCommand', dict(activatorId=n.id, targetIds=[m.id for m in near], visualEffect=VE_THERMAL))])
                for m in near:
                    w.hit_npc(m.id, int(dmg * S['ratio']), CANNON_ATTACK, cannon=row['cannonType'])
        elif e == 'corrosive':                                   # Nidhogg: corrosion weakness
            A = C['abrasion']
            k = self.corrosive.get(n.id, [0, 0])
            k = [min(A['multiplier'], (k[0] if k[1] > now else 0) + 1), now + A['sec']]
            self.corrosive[n.id] = k
            if n.alive:
                w.send([('VisualModifierCommand', dict(userId=n.id, modifier=VM_CORROSIVE, attribute=k[0], additionalAttribute='',
                                                       count=k[0], activated=True))])
        elif e == 'electro':                                     # Indra: chain
            Z = C['chain']
            chain, seen, x, y, d = [], {n.id}, nx, ny, dmg
            while len(chain) < Z['target'] - 1:
                nxt = self.others(x, y, Z['radius'], seen, now)
                if not nxt:
                    break
                m = nxt[0]
                seen.add(m.id)
                chain.append(m)
                x, y = m.mover.pos(now)
            if chain:
                w.send([('PlayVisualEffectCommand', dict(activatorId=n.id, targetIds=[m.id for m in chain], visualEffect=VE_ELECTRO))])
                for m in chain:
                    d = int(d * (1 - Z['reduction']))
                    w.hit_npc(m.id, d, CANNON_ATTACK, cannon=row['cannonType'])
        return True

    def vulnerability(self, uid, now):
        k = self.corrosive.get(uid)
        return k[0] * C['abrasion']['ratio'] if k and k[1] > now else 0.0

    # ------------------------------------------------------------ drive
    def fire_drive(self, n, now, gsp, auto=False):
        w, p = self.w, self.p
        if not gsp or gsp not in GSP or w.hero_dead or w.jumping:
            return False
        ids = equipped(p, 'drive')
        power, area, best = drive_power(p, ids) if ids else (0, DR['area'], 1)
        why = None
        if not ids:
            why = 'no drive equipped'
        elif not self.ready(COOLDOWN_DRIVE, now):
            why = 'cooldown'
        elif p.ammo(gsp) < len(ids):
            why = 'not enough GSP'
        elif w.in_peace(*w.hero_pos(now)):
            why = 'safe zone'
        elif not self.in_range(n, now, DR['range']):
            why = 'out of range'
        if why:
            if not auto:
                w.log('   drive not fired (%s): %s' % (gsp, why))
            return False
        p.use_ammo(gsp, len(ids))
        self.cool(COOLDOWN_DRIVE, DR['cooldown_sec'], now)
        w.last_combat = now
        shot, vm = DR['effect'][str(best)]
        x, y = n.mover.pos(now)
        import ship_ability as SA
        bonus = SA.take(p, 'next_gsp')                 # Hyperion Quantum Amplifier: +10% on this shot
        zone = self.resonate({'x': x, 'y': y, 'end_time': now + DR['duration_sec'], 'next': now, 'damage': power * GSP[gsp] * (1 + bonus), 'target': n.id,
                              'vm': vm, 'area': area}, now)
        self.zones.append(zone)
        w.send(w.ammo_msgs(gsp) + [('PlayVisualEffectCommand', dict(activatorId=w.hid, targetIds=[n.id], visualEffect=shot)),
                                   ('VisualModifierCommand', dict(userId=n.id, modifier=vm, attribute=0, additionalAttribute='', count=0,
                                                                  activated=True))])
        p.ach('shot', weapon='DRIVE')
        self.zone_tick(zone, now)
        return True

    def resonate(self, z, now):
        """Attributes of the best Strike Resonator (resonator.py, Ö6): radius, duration, total damage, aftershock, slowdown,
        following the main target. Damage is per second: the total damage (duration x per-second) is kept with the multiplier."""
        import resonator as RS
        a = RS.strike_mods(self.p)
        if not a:
            return z
        duration, total = float(DR['duration_sec']), 1.0
        if 'collapse' in a:
            duration, total = duration * 0.75, total * (1 + a['collapse'] / 100.0)
        elif 'evernight' in a:
            duration, total = duration * 1.25, total * (1 + a['evernight'] / 100.0)
        per = z['damage'] * total * DR['duration_sec'] / duration
        z.update(end_time=now + duration, damage=per, area=z['area'] * (1 + a.get('expansion', 0) / 100.0), resonator=a)
        if 'aftershock' in a:                       # 75% over the field's duration, 25% at the end (radius +x)
            z['aftershock_dmg'] = per * 0.25 * duration
            z['damage'] = per * 0.75
            z['aftershock_area'] = z['area'] * (1 + a['aftershock'] / 100.0)
        if 'stagnation' in a:
            z['slow'] = a['stagnation'] / 100.0
        if 'adhesion' in a:
            z['follow'] = now + min(a['adhesion'], duration)
        return z

    def zone_tick(self, z, now):
        if now < z['next'] or self.w.hero_dead:
            return
        zones = self.zones
        z['next'] = now + 1.0
        t = self.w.npcs.get(z['target'])
        if z.get('follow', 0) > now and t is not None and t.alive:       # Adhesion: the field moves with the main target
            z['x'], z['y'] = t.mover.pos(now)
        for m in self.others(z['x'], z['y'], z.get('area', DR['area']), set(), now):
            if self.w.hero_dead or self.zones is not zones:
                break                                   # a hit can kill the hero or stop the world and clear all zones
            if z.get('slow'):                                          # Stagnation: slow while in the field (ends 1.2 s after leaving)
                self.w.npc_effect(m, 'slow', 1.2, z['slow'], source='resonator')
            if random.random() < DR['hit']:
                self.w.hit_npc(m.id, int(z['damage']), DRIVE_ATTACK)

    @staticmethod
    def zone_end(z):
        return ('VisualModifierCommand', dict(userId=z['target'], modifier=z['vm'], attribute=0,
                                               additionalAttribute='', count=0, activated=False))

    def clear(self):
        """Cancel pending drive visuals and damage when leaving this world or dying."""
        # Replacing the list also invalidates a damage iteration running inside a hit callback.
        zones, self.zones = self.zones, []
        if zones:
            self.w.send([self.zone_end(z) for z in zones])

    def tick(self, now):
        if self.zones:
            zones = self.zones
            for z in list(zones):
                if self.zones is not zones:
                    break
                if z not in self.zones:
                    continue
                if now >= z['end_time']:
                    self.zones.remove(z)
                    if z.get('aftershock_dmg'):                                  # Aftershock: the remaining 25% explodes at the end
                        for m in self.others(z['x'], z['y'], z['aftershock_area'], set(), now):
                            if self.w.hero_dead or self.zones is not zones:
                                break
                            self.w.hit_npc(m.id, int(z['aftershock_dmg']), DRIVE_ATTACK)
                    # The client can cancel an effect by unit ID after that unit was removed.
                    self.w.send([self.zone_end(z)])
                else:
                    self.zone_tick(z, now)
        for uid, k in list(self.corrosive.items()):
            if k[1] <= now:
                del self.corrosive[uid]
                if uid in self.w.npcs:
                    self.w.send([('VisualModifierCommand', dict(userId=uid, modifier=VM_CORROSIVE, attribute=0, additionalAttribute='',
                                                                count=0, activated=False))])
