"""Item upgrades and Disassembly (roadmap stage 6; data data/client_items.json <- tools/il2cpp/client_data.py).

The client's own data: 17 upgrade classes (upgrade_upgrade-class0 ... class10, drone, cbs) and 8 Disassembly classes; each class's
items and the time and cost of each level (ABR, credits/uridium, at some levels Diametrion, Indoctrine Oil/Accelerator). The item's
"upgradable" property gives the bonus per level (LF-3 damage 0.5%, SG3N-B02 shield 1%, Iris's shield 1% and damage 0.4% ...).
The level starts at 0 in the protocol (the client shows 1; all items in the save have upgradeLevel 0); at most the class's level count (16 or
20 are shown). Bonus = level x percent (LINEAR_CALCULATION).

Assembly window (the AssemblyRecipeContentModule in the save has 17 upgrade_ and 8 disassemble_ recipes; requests come from the client's code):
  AssemblyBuildRequest {recipeLootId upgrade_..., targetItemId (item or drone id), amount (target level, from 0)}: costs are
      spent, the timer runs -> AssemblyRecipeStatusUpdateCommand {targetItemId, Build (buildAmount is also the target level)}
  AssemblyCollectRequest / CollectAll / Skip {recipeLootId, targetItemId}: when the time is up the level rises (InventoryItemModule.upgradeLevel;
      for a drone SingleDroneEquipmentMsg damage/shieldUpgradeLevel); if equipped, damage/shield are recomputed
  DisassemblyRequest {recipeLootId disassemble_..., itemId}: an upgraded, unequipped item is taken apart; the fee in the row of its level
      is paid, negative amounts are given back (the client's text: "Do you want to disassemble this item?" / "You cannot disassemble an
      equipped item.")
In the profile: upgrade_level {itemId: level}; for a drone the record field "upgrade"; running upgrades assembly.upgrade {"recipe|target": ...}.
Upgrade Hour (items.json upgrade_hour): in that hour upgrades cost 25% less uridium; a HUD message when it starts.
Old upgrade system (panel: legacy_upgrade, user request 2026-10-31): the 2013-2019 Skylab > Tech Factory > Item Upgrading
is not in the Unity client (only its texts remain: resource_itemUpgradeSystem); the Assembly's Upgrade tab does the same upgrades with
uridium only. Price: the old system's 100% success-chance cost (board-en "Upgrading Cost Charts", topic 12614: 3,905 to level 2,
+435 per level, 104,250 U. in total up to 16; all uridium items are the same), 17-20 with the same increase. Items that used to take credits (class0: LF-1,
MP-1, SG3N-A01, Flax) a quarter (today's ABRs are ~1/4 of class2's); CBS modules with their old totals (inner modules Hull/Deflector
402,750, outer modules 268,500). Multiplier: legacy_upgrade_price. The client shows the cost from its own recipe: the panel writes legacy_table()
to the client's BepInEx/openorbit/legacy_upgrade.json, and the plugin's LegacyUpgrade patch turns the recipes into uridium.
"""
import datetime, json, os, time

import inventory as INV
import settings as SET
import event_calendar as CAL
import ranks as RT

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))
UP, DIS, ITEMS = D['upgrades'], D['disassembly'], D['items']
INGREDIENTS = {loot for groups in (UP, DIS) for recipe in groups.values() for level in recipe['levels']
               for costs in (level.get('cost', {}), level.get('jump_to', {})) for loot in costs}
UP_OF = {loot: k for k, c in UP.items() for loot in c['items']}
DIS_OF = {loot: k for k, c in DIS.items() for loot in c['items']}
HOUR = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))['upgrade_hour']
LASER, SHIELD, ROCKET = 'LASER_DAMAGE_UPGRADE', 'GENERATOR_SHIELD_UPGRADE', 'ROCKETLAUNCHER_DAMAGE_UPGRADE'
DRONE_DAMAGE, DRONE_SHIELD = 'DRONE_DAMAGE_UPGRADE', 'DRONE_SHIELD_UPGRADE'
# the level badge of a hangar item (HangarShipEquipmentInventoryItem.UpgradeLevel, "key,displayed level"): the client
# (UINewHangarSystem.SetTypeIdentification) shows the badge when there is a row in the list and takes the text from TooltipPreparerFactory.ReturnItemLevelNum
# (the first of the keys in this order whose value is greater than 1); in the tooltip "Damage level" / "Shield level". When the list is empty the level field
# does not show the badge: upgraded items used to appear without a level
BADGE = {LASER: 'damageUpgradeLevel', ROCKET: 'damageUpgradeLevel', SHIELD: 'shieldUpgradeLevel',
         'CANNON_DAMAGE_UPGRADE': 'cannonDamageUpgradeLevel', 'CANNON_DEF_UPGRADE': 'cannonDefUpgradeLevel',
         'DRIVE_DAMAGE_UPGRADE': 'driveDamageUpgradeLevel', 'DRIVE_DEF_UPGRADE': 'driveDefUpgradeLevel'}


OLD_FIRST, OLD_INCREASE = 3905, 435
OLD_RATIO = {'upgrade_upgrade-class0': 0.25, 'upgrade_upgrade-class0-drone': 0.25,
             'upgrade_upgrade-class3-cbs': 268500 / 104250.0, 'upgrade_upgrade-class4-cbs': 402750 / 104250.0}


def legacy_table(is_open=None, multiplier=None):
    """The old system's uridium cost per level {class: [U. per row]} ({} if off); the panel writes it to the client too."""
    if not (SET.get('legacy_upgrade') if is_open is None else is_open):
        return {}
    m = SET.multiplier('legacy_upgrade_price') if multiplier is None else multiplier
    return {k: [int(round((OLD_FIRST + OLD_INCREASE * i) * OLD_RATIO.get(k, 1.0) * m)) for i in range(len(c['levels']))]
            for k, c in UP.items()}


def row_cost(key, i):
    """Cost of row i (from 0) of the upgrade class: if the old system is on, uridium only, otherwise the client's materials."""
    if SET.get('legacy_upgrade'):
        n = legacy_table()[key][i]
        return {'currency_uridium': n} if n > 0 else {}
    return {loot: a for loot, a in UP[key]['levels'][i]['cost'].items() if a > 0}


def mod(name, **f):
    f['_'] = name
    return f


def max_level(loot):
    k = UP_OF.get(loot)
    return len(UP[k]['levels']) if k else 0


def item_level(p, iid):
    return int(p.d.get('upgrade_level', {}).get(str(iid), 0))


def badge(loot, level):
    """Rows of the hangar badge: if upgraded, "key,level + 1" for each bonus type of the item (level 1 has no badge in the client)."""
    return ['%s,%d' % (BADGE[u['type']], level + 1) for u in ITEMS.get(loot, {}).get('upgrade', []) if u['type'] in BADGE] if level else []


def spent(p, iid):
    """Materials spent on the item's upgrades (recycling and Synthesis refund; the Upgrade Hour discount is not counted)."""
    k = UP_OF.get(p.d['items'].get(str(iid), ''))
    out = {}
    for i in range(item_level(p, iid) if k else 0):
        for loot, a in row_cost(k, i).items():
            out[loot] = out.get(loot, 0) + a
    return out


def factor(loot, level, kind):
    """Upgrade bonus multiplier: 1 + level x percent (1 if the item has no bonus of that type)."""
    if not level:
        return 1.0
    for u in ITEMS.get(loot, {}).get('upgrade', []):
        if u['type'] == kind:
            return 1 + level * u['percent'] / 100.0
    return 1.0


def drone_level(x):
    return int(x.get('upgrade', 0))


def bonus_hour(now=None):
    """The uridium discount (0.25) if Upgrade Hour is running, otherwise 0 (event_calendar.py: upgrade_hour, in local time)."""
    return HOUR['discount'] if CAL.is_active('upgrade_hour', now) else 0.0


class Upgrade:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                 # shop (inventory/currency update, speed/shield; binds the session)
        self.send = None
        self.refresh = None           # Assembly's recipe list (so the panel is redrawn when the time is up; H61)
        self.hour_on = bool(bonus_hour())
        self.old = self.old_key()       # when the old system's settings change, the recipe list again (tick)
        self.old_at = None

    @property
    def st(self):
        return self.p.d.setdefault('assembly', {}).setdefault('upgrade', {})

    # ------------------------------------------------------------ targets
    def target(self, key, tid):
        """(type, lootId, record) or None: an item ('item', loot, iid) or a drone ('drone', loot, record)."""
        loot = self.p.d['items'].get(str(tid))
        if loot:
            return 'item', loot, int(tid)
        x = next((d for d in self.p.d.get('drones', []) if d['uid'] == int(tid or 0)), None)
        if x and '-drone' in key:
            return 'drone', x['lootId'], x
        cbs = getattr(self.m, 'cbs', None)
        m = cbs.st['modules'].get(str(tid)) if cbs and '-cbs' in key and not cbs.where(tid) else None
        if m:
            return 'module', m['loot'], (int(tid), m)          # Clan Battle Station module (when not equipped; shop.module_items)
        return None

    def level_of(self, kind, ref):
        if kind == 'module':
            return int(ref[1].get('level', 0))
        return drone_level(ref) if kind == 'drone' else item_level(self.p, ref)

    def set_level(self, kind, ref, n):
        with self.p.lock:
            if kind == 'drone':
                ref['upgrade'] = n
            elif kind == 'module':                       # HP and shield to the new level's maximum (cbs.mx)
                ref[1]['level'] = n
                ref[1]['can'], ref[1]['kalkan'] = self.m.cbs.mx(ref[1])
            else:
                self.p.d.setdefault('upgrade_level', {})[str(ref)] = n
            self.p.dirty = True

    # ------------------------------------------------------------ window
    def status(self, key, tid, now=None):
        now = now or time.time()
        b = self.st.get('%s|%d' % (key, int(tid or 0)))
        if b:
            if now < b['end_time']:
                return mod('AssemblyRecipeBuildStatusModule', buildAmount=b['level'], remainingTimeMillis=int((b['end_time'] - now) * 1000),
                           prevBuildCount=0)
            return mod('AssemblyRecipeReadyToCollectStatusModule', prevBuildCount=0, buildAmount=b['level'])
        return mod('AssemblyRecipeAvailableStatusModule', currentBuildCount=0, isNew=False)

    def update(self, key, tid=0, now=None):
        return ('AssemblyRecipeStatusUpdateCommand', dict(targetItemId=int(tid or 0), status=self.status(key, tid, now), lootId=key))

    def recipes(self, now=None):
        """To the login list: each class once (no target) and running/ready upgrades with their targets."""
        out = [mod('AssemblyRecipeModule', recipeLootId=k, targetItemId=0, type=mod('AssemblyRecipeRegularTypeModule'),
                   status=self.status(k, 0, now)) for k in list(UP) + list(DIS)]
        for key_type in sorted(self.st):
            k, t = key_type.split('|')
            out.append(mod('AssemblyRecipeModule', recipeLootId=k, targetItemId=int(t), type=mod('AssemblyRecipeRegularTypeModule'),
                           status=self.status(k, t, now)))
        return out

    # ------------------------------------------------------------ upgrade
    def cost(self, key, cur, n, now=None):
        """n levels from level cur: the sum of the costs and the time (Upgrade Hour uridium 25%, Premium 5% less; in the old system
        uridium only)."""
        rows = UP[key]['levels'][cur:cur + n]
        need = {}
        for i in range(cur, cur + len(rows)):
            for loot, a in row_cost(key, i).items():
                need[loot] = need.get(loot, 0) + a
        # discounts by the client's calculation (DiscountComponentSystem.GetAmountWithDiscount; live 2026-11-01): Upgrade Hour and
        # UserInventoryModule.activePremiumDiscount (Premium 5% + Shop Discount, shop.discount) are added, uridium is rounded down,
        # credits have no discount (LF-3 316 U. -> Premium 300, + Upgrade Hour 221). Before, only Upgrade Hour was taken, rounded up:
        # the window showed 300 with Premium while 316 was charged
        pct = int(round((bonus_hour(now) + (self.m.discount() if self.m else 0.0)) * 100))
        if pct and need.get('currency_uridium'):
            need['currency_uridium'] = need['currency_uridium'] * max(0, 100 - pct) // 100
        return {} if SET.get('assembly_free') else need, SET.duration(sum(r['sure_sn'] for r in rows), 'upgrade')            # panel: cooldown

    def build(self, f, now=None):
        now = now or time.time()
        key, tid = f.get('recipeLootId', ''), int(f.get('targetItemId') or 0)
        t = self.target(key, tid)
        if key not in UP or not t or t[1] not in UP[key]['items']:
            self.log('   no upgrade: %s target %s' % (key, tid))
            return [self.update(key, tid, now)] if key in UP else []
        kind, loot, ref = t
        if '%s|%d' % (key, tid) in self.st:
            return [self.update(key, tid, now)]
        cur = self.level_of(kind, ref)
        if cur >= len(UP[key]['levels']):
            self.log('   upgrade: %s is at the top level' % loot)
            return [self.update(key, tid, now)]
        # amount is the target level (from 0): the client sends one less than the level on the counter (UpgradeViewSystem/UISingularityDriveSystem
        # .HandleBuildClicked) and also counts the running upgrade's buildAmount as the target (CollectSteps(current, buildAmount)). It used to be
        # taken as a count: the same when starting from 0, then extra levels, time and cost came out (live test H60)
        target = min(int(f.get('amount') if f.get('amount') is not None else cur + 1), len(UP[key]['levels']))
        n = target - cur
        if n < 1:
            self.log('   upgrade: target level %d is not greater than the current (%d) (%s)' % (target, cur, loot))
            return [self.update(key, tid, now)]
        need, secs = self.cost(key, cur, n, now)
        miss = INV.missing(self.p, need)
        if miss:
            self.log('   upgrade: not enough materials %s (missing %s)' % (loot, miss))
            return [self.update(key, tid, now)]
        removed = INV.spend(self.p, need, reason='buy_SPECIAL', detail=key)
        with self.p.lock:
            self.st['%s|%d' % (key, tid)] = dict(count=n, end_time=now + secs, target=tid, level=cur + n)
            self.p.dirty = True
        self.log('   upgrade started: %s %d -> %d (%d s, %s)' % (loot, cur, cur + n, secs, need))
        return INV.update_msgs(self.m, self.p, list(need), removed) + [self.update(key, tid, now)]

    def collect(self, f, now=None):
        now = now or time.time()
        key = f.get('recipeLootId') or f.get('lootId') or ''
        tid = int(f.get('targetItemId') or f.get('targetId') or 0)
        b = self.st.get('%s|%d' % (key, tid))
        if not b or now < b['end_time']:
            return [self.update(key, tid, now)] if key in UP else []
        t = self.target(key, tid)
        with self.p.lock:
            del self.st['%s|%d' % (key, tid)]
            self.p.dirty = True
        if not t:
            return [self.update(key, tid, now)]
        kind, loot, ref = t
        self.set_level(kind, ref, b['level'])
        self.p.ach('upgrade', item=loot, level=b['level'])
        RT.note(self.p, 'upgraded_item', loot, b['level'])     # logbook: log_message_upgrade_finished (%item% from info, %level%)
        self.log('   upgrade finished: %s level %d' % (loot, b['level']))
        return self.item_msgs(kind, loot, ref) + [self.update(key, tid, now)]

    def item_msgs(self, kind, loot, ref):
        """Item/drone whose level changed: inventory and hangar update, speed/shield/damage if equipped."""
        if not self.m:
            return []
        self.p.sync_equipment()
        if kind == 'drone':
            return [self.m.drone_item(ref), self.m.equipment_cmd()] + self.m.apply_stats()     # its level in Assembly too
        if kind == 'module':
            return [self.m.module_item(*ref)]
        hm = self.p.hangar_map()
        msgs = [self.m.inv_item(ref, loot, 1, hm.get(ref, 0)), self.m.pack([self.m.hangar_item(ref, loot, 1, hm.get(ref, 0))])]
        import particle as PC
        if PC.restabilizable(loot):
            import ship_module as GM
            msgs.append(GM.list_cmd(self.p))               # the cannon's level and the upgrade refund are in Restabilize (H70)
        if loot in PC.DRIVES or loot in PC.LENSES:
            # at levels 5/10/15/20 a sub-attribute unlocks: the Update window's Stats slots come from the list (live test H62: at level 5 the slot
            # stayed "LV: 5 Unlock" and the attribute only arrived at the next login)
            msgs.append(PC.lock_list_cmd(self.p))
        if ref in hm:
            msgs += [self.m.equipment_cmd()] + self.m.apply_stats()
        return msgs

    def skip_cost(self, key, b, now=None):
        """Cost of skipping the time: the sum of the levels' skip costs (the client's data, Isochronate) x the remaining-time ratio, rounded. The client
        (TargetItemRecipeModel.GetSkipIngredients, UpgradeSkipListItem.UpdatePercentage) shows it with the same calculation; before, 1 uridium per remaining
        minute was charged while the window showed Isochronate (live test H58)."""
        now = time.time() if now is None else now
        rows = UP[key]['levels'][b['level'] - b['count']:b['level']]
        total = SET.duration(sum(r['sure_sn'] for r in rows), 'upgrade') or 1
        frac = min(1.0, max(0.0, (b['end_time'] - now) / total))
        need = {}
        for r in rows:
            for loot, a in r.get('jump_to', {}).items():
                need[loot] = need.get(loot, 0) + a
        return {} if SET.get('assembly_free') else {loot: max(1, int(a * frac + 0.5)) for loot, a in need.items()}

    def skip(self, f, now=None):
        now = now or time.time()
        key, tid = f.get('recipeLootId', ''), int(f.get('targetItemId') or 0)
        b = self.st.get('%s|%d' % (key, tid))
        if not b or now >= b['end_time']:
            return [self.update(key, tid, now)] if key in UP else []
        need = self.skip_cost(key, b, now)
        miss = INV.missing(self.p, need)
        if miss:
            self.log('   upgrade could not be skipped: %s missing %s' % (key, miss))
            return [self.update(key, tid, now)]
        removed = INV.spend(self.p, need, reason='buy_SPECIAL', detail=key)
        with self.p.lock:
            b['end_time'] = now
            self.p.dirty = True
        self.log('   upgrade skipped: %s target %d (%s)' % (key, tid, need))
        return INV.update_msgs(self.m, self.p, list(need), removed) + [self.update(key, tid, now)]

    # ------------------------------------------------------------ Disassembly
    def disassemble(self, f, now=None):
        key, iid = f.get('recipeLootId', ''), int(f.get('itemId') or 0)
        loot = self.p.d['items'].get(str(iid))
        if key not in DIS or not loot or loot not in DIS[key]['items']:
            self.log('   no Disassembly: %s item %s' % (key, iid))
            return [self.update(key, iid)] if key in DIS else []
        if any(k.endswith('|%d' % iid) and (now or time.time()) < b['end_time'] for k, b in self.st.items()):
            self.log('   no Disassembly: item %s is being upgraded' % iid)               # forum 150401
            return [self.update(key, iid)]
        if iid in self.p.equipped_ids():
            from legacy_protocol import legacy
            return [legacy('0|A|STM|msg_cannot_disassemble_equipped_item'), self.update(key, iid)]
        lv = item_level(self.p, iid)
        row = next((r for r in DIS[key]['levels'] if r['level'] == lv), None)
        if not row:
            self.log('   Disassembly: %s level %d cannot be disassembled' % (loot, lv))
            return [self.update(key, iid)]
        fee = {} if SET.get('assembly_free') else {l: a for l, a in row['cost'].items() if a > 0}
        back = {l: -a for l, a in row['cost'].items() if a < 0}
        if INV.missing(self.p, fee):
            self.log('   Disassembly: not enough for the fee %s' % fee)
            return [self.update(key, iid)]
        INV.spend(self.p, fee, reason='buy_SPECIAL', detail=key)
        with self.p.lock:
            del self.p.d['items'][str(iid)]
            self.p.d.get('upgrade_level', {}).pop(str(iid), None)
            self.p.d.get('item_level', {}).pop(str(iid), None)
            self.p.dirty = True
        msgs = INV.update_msgs(self.m, self.p, list(fee), [iid])
        for l, n in back.items():
            msgs += self.m.reward(l, n) if self.m else []
            if not self.m:
                self.p.add_resource(l, n)
        self.log('   Disassembly: %s (level %d) disassembled, fee %s, back %s' % (loot, lv, fee, back))
        RT.note(self.p, 'disassembled_item', loot, lv)          # logbook: log_message_disassembly_finished (%item% from info)
        return msgs + [self.update(key, iid)]

    # ------------------------------------------------------------ requests
    def handles(self, name, f):
        key = f.get('recipeLootId') or ''
        if name == 'DisassemblyRequest':
            return True
        return name in ('AssemblyBuildRequest', 'AssemblyCollectRequest', 'AssemblySkipRequest') and key in UP

    def handle(self, name, f):
        if name == 'DisassemblyRequest':
            return self.disassemble(f)
        return {'AssemblyBuildRequest': self.build, 'AssemblyCollectRequest': self.collect, 'AssemblySkipRequest': self.skip}[name](f)

    def discount_msgs(self, now=None):
        """The discount on the client's upgrade costs (UserInventoryModule.activeHappyUpgradeDiscount, percent; the client's
        DiscountComponentSystem.UpdateFromServer): without it the window shows the full uridium while the server charged 25% less (live test H40).
        The module also carries the inventory list: the full list so the client's item counters are not erased (the shop's login counters)."""
        if not self.m:
            return []
        items = [f['item'] for n, f in self.m.count_msgs()]
        return [('UserInventoryModule', dict(activePremiumDiscount=int(round(self.m.discount() * 100)),
                                             activeRebateSubDiscount=0, inventoryItemModules=items,
                                             activeHappyUpgradeDiscount=int(round(bonus_hour(now) * 100))))]

    @staticmethod
    def old_key():
        return bool(SET.get('legacy_upgrade')), SET.multiplier('legacy_upgrade_price')

    def tick(self, now):
        # When the old system is turned on/off while the game is open, or its price changes: the client's recipe models cache the cost (on switching from on
        # to off the window kept showing uridium, live 2026-11-01); when the recipe list is sent again the models
        # are rebuilt. After 2 s: the plugin checks the cost file the panel writes at most once a second
        k = self.old_key()
        if k != self.old:
            self.old, self.old_at = k, now + 2.0
        if self.old_at and now >= self.old_at:
            self.old_at = None
            self.log('   old upgrade system: %s, price x%g' % ('on' if k[0] else 'off', k[1]))
            if self.send and self.refresh:
                self.send([self.refresh()])
        on = bool(bonus_hour(now))
        if on != self.hour_on:
            self.hour_on = on
            self.log('   Upgrade Hour %s' % ('started' if on else 'finished'))
            if self.send:
                from legacy_protocol import legacy
                msgs = [legacy('0|A|STM|bn_upgradeBounsHour_content')] if on else []     # "%25 uridyum indirimi" (the client's text)
                self.send(msgs + self.discount_msgs(now))
        done = [k for k, b in self.st.items() if not b.get('notified') and now >= b['end_time']]
        for k in done:
            with self.p.lock:
                self.st[k]['notified'] = True
                self.p.dirty = True
        if done and self.send:
            self.send([self.update(k.split('|')[0], int(k.split('|')[1]), now) for k in done] + ([self.refresh()] if self.refresh else []))
