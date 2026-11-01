"""Synthesis window: Intensify, SG Drive and Cannon Star Up (roadmap stage 9b; recipes in data/particle.json 'synthesis' <-
tools/particle.py, sources: official forum FAQs and the darkorbit wiki).

Client (UISynthesisSystem; requests from the client's code; the list never came in the recording, the window opened empty):
  SynthesisListCommand {groups: [SynthesisGroupCommand {group, button (translation key), moduleList: [SynthesisModuleListCommand
      {moduleListGroupType (Synthesis_table_1 Nidhogg, _2 Helios, _3 Indra; Synthesis_drive_1 IgniDrive, _2 Grav-Lens), modules:
      [SynthesisModuleCommand {lootId (result), star, moduleGroupType, costs [SynthesisCostLootCommand {lootId, amount, star,
      certain}], affectedShip (ship id of the UL ship cannon)}]}]}]}   on login and when the window opens
  SynthesisInventoryRequest            -> list + SynthesisInventoryCommand {equipmentInventoryItems: unfitted cannons, drives and
                                          lenses (in hangar item form)}
  SynthesisItemRequest {synthesisId "lootId|affectedShip|star", itemIds}: the selected inputs (same type, same star, not fitted)
      and the cost (uridium, Energy item) are spent, the result item arrives; 50% of an upgraded input's material is returned
      ("The selected weapon material has been reinforced ..."). Star Up: two of the same UL cannon -> one star more, attributes
      are drawn again.
"""
import json, os
import particle as PC
import inventory as INV
import resonator as RS

D = PC.D['synthesis']
RECIPES = {(r['target'], r['star']): r for r in D['recipes']}
# Ö6: recipes that cannot be shown in Assembly (the client reads a recipe from its own data) -> the "title_assembly" tab (tools/esyalar_o6.py)
EXTRA_D = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'items_o6.json'),
                         encoding='utf8'))['extra_recipes']
EXTRA = {(r['target'], r['star']): r for r in EXTRA_D['recipes']}
INSTANCE = ('equipment_', 'drone_', 'pet_')                # input is an item instance: the selected slot (certain)
EXTRA_COUNT = 'extra_recipe_counter'                             # profile: recipe -> how many times (USABLE_ONCE / en_cok)
REQUESTS = {'SynthesisInventoryRequest', 'SynthesisItemRequest'}
SOURCES = {r['input'] for r in D['recipes']} | RS.INPUTS \
    | {l for r in EXTRA_D['recipes'] for l in r['inputs'] if l.startswith(INSTANCE)}   # + Ö6: resonators, AA-1/AAP-1
TABLE_KEY = 'Synthesis_%s'                                  # table_1 -> Synthesis_table_1 (Nidhogg), drive_1 -> Synthesis_drive_1 …
ACTION_KEY = {'star': 'synthesis_cannon_star_promote'}     # action button; the others "Synthesis"


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Synthesis:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                 # shop (hangar item, rewards, money); binds the session

    def module(self, r):
        # client (UISynthesisSystem.SelectNeedItem / OnTypeSelectionChanged): certain=true every record is an item slot to select
        # ("Select n / NeedNum", NeedNum = the number of these records), certain=false records are "held/needed" material rows (red if
        # short). At first the input was a single record (amount 5) and uridium went certain too: the window showed "0 / 2" and two slots (H53)
        costs = [mod('SynthesisCostLootCommand', lootId=r['input'], amount=1, star=r['input_star'], certain=True)] * r['count']
        costs += [mod('SynthesisCostLootCommand', lootId=k, amount=v, star=0, certain=False) for k, v in r['charge'].items()]
        ship = D['ship_ids'].get(r['ship'], 0) if r['ship'] else 0
        return mod('SynthesisModuleCommand', star=r['star'], moduleGroupType=TABLE_KEY % r['table'], lootId=r['target'], costs=costs,
                   affectedShip=ship)

    def extra_module(self, r):
        costs = []
        for loot, n in r['inputs'].items():
            if loot.startswith(INSTANCE):
                costs += [mod('SynthesisCostLootCommand', lootId=loot, amount=1, star=0, certain=True)] * n
            else:
                costs.append(mod('SynthesisCostLootCommand', lootId=loot, amount=n, star=0, certain=False))
        return mod('SynthesisModuleCommand', star=r['star'], moduleGroupType=EXTRA_D['table'], lootId=r['target'], costs=costs,
                   affectedShip=0)

    def list_cmd(self):
        groups = {}
        for r in D['recipes']:
            groups.setdefault(r['group'], {}).setdefault(r['table'], []).append(r)
        # the client translates the top tab's name from 'group', the left buttons' names from moduleListGroupType, and the action button below from 'button'
        # (all translation keys); at first the tabs and buttons looked empty (live test H52, tried through the control channel)
        out = [mod('SynthesisGroupCommand', button=ACTION_KEY.get(g, 'Synthesis_button'), group=D['buttons'][g], moduleList=[
            mod('SynthesisModuleListCommand', moduleListGroupType=TABLE_KEY % t, modules=[self.module(r) for r in rs])
            for t, rs in sorted(tables.items())]) for g, tables in groups.items()]
        out.append(RS.group_cmd(self.p))                    # Ö6: Resonator tab (rezonator.py; C's cost from the player's resources)
        out.append(mod('SynthesisGroupCommand', button='Synthesis_button', group=EXTRA_D['group'], moduleList=[
            mod('SynthesisModuleListCommand', moduleListGroupType=EXTRA_D['table'],
                modules=[self.extra_module(r) for r in EXTRA_D['recipes']])]))
        return 'SynthesisListCommand', {'groups': out}

    def cost_loots(self):
        """Resources that have a cost row in the window (certain=false; except money)."""
        out = {k for r in D['recipes'] for k in r['charge']} | set(RS.SOURCES)
        out |= {l for r in EXTRA_D['recipes'] for l in r['inputs'] if not l.startswith(INSTANCE)}
        return {l for l in out if not l.startswith('currency_')}

    def free_items(self):
        eq = self.p.equipped_ids()
        return [int(i) for i, l in sorted(self.p.d['items'].items(), key=lambda x: int(x[0])) if l in SOURCES and int(i) not in eq]

    def inventory_cmds(self):
        items = []
        if self.m:
            items = [self.m.hangar_item(i, self.p.d['items'][str(i)], 1) for i in self.free_items()]
            # the cost row's "held" count: the client (UISynthesisSystem.OnTypeSelectionChanged) looks up the lootId in this list and takes its
            # itemCount (uridium from Hero); when resources were not in the list, Energy, Mucosum ... were always "0/n" and the button disabled (Ö6)
            for loot in sorted(self.cost_loots()):
                n = INV.count(self.p, loot)
                if n > 0:
                    items.append(self.m.hangar_item(self.m.item_id(loot), loot, n))
        # client (InventoryItemData.UpdateDetailedItems): if remove=false it clears the list and puts the new one, but if a full item
        # arrived it adds without clearing. After Synthesis, when only the new item was left alone, the spent inputs stayed in the window
        # (live test H54): for a single item an empty list (which clears) goes first
        cmd = lambda lst: ('SynthesisInventoryCommand', {'equipmentInventoryItems': lst, 'remove': False})
        return ([cmd([])] if len(items) == 1 else []) + [cmd(items)]

    def handle(self, name, f):
        if name == 'SynthesisInventoryRequest':
            return [self.list_cmd()] + self.inventory_cmds()
        if name == 'SynthesisItemRequest':
            return self.synth(f)
        return []

    def fail(self, why):
        from legacy_protocol import stm
        self.log('   Synthesis failed: %s' % why)
        return [stm('Synthesis_error')] + self.inventory_cmds()

    def extra(self, r, ids):
        """The Assembly tab's recipe: the selected items (AA-1 ...) and resources are spent, the output goes via the reward path (design, EP, ammo ...)."""
        p = self.p
        done = p.d.get(EXTRA_COUNT, {}).get(r['recipe'], 0)
        if r.get('max_count') and done >= r['max_count']:
            return self.fail('%s at most %d times' % (r['recipe'], r['max_count']))
        free = set(self.free_items())
        chosen = []
        for loot, n in r['inputs'].items():
            if not loot.startswith(INSTANCE):
                continue
            ok = [i for i in dict.fromkeys(ids) if i in free and p.d['items'].get(str(i)) == loot]
            ok += [i for i in sorted(free) if p.d['items'].get(str(i)) == loot and i not in ok]
            if len(ok) < n:
                return self.fail('not enough %s (%d/%d)' % (loot, len(ok), n))
            chosen += ok[:n]
        rest = {l: n for l, n in r['inputs'].items() if not l.startswith(INSTANCE)}
        if rest and INV.spend(p, rest, 'buy_SPECIAL', 'assembly') is None:
            return self.fail('cost not covered (%s)' % rest)
        with p.lock:
            for i in chosen:
                p.d['items'].pop(str(i), None)
            p.d.setdefault(EXTRA_COUNT, {})[r['recipe']] = done + 1
            p.dirty = True
        msgs = [('InventoryItemRemovedCommand', {'itemId': i}) for i in chosen] + INV.update_msgs(self.m, p, list(rest))
        if self.m:
            msgs += self.m.reward(r['target'], r['count'])
        else:
            p.add_resource(r['target'], r['count'])
        self.log('   Synthesis (Assembly): %s -> %s x%d' % (r['inputs'], r['target'], r['count']))
        return msgs + [self.list_cmd()] + self.inventory_cmds()        # the reward path sends the "you received" text itself

    def synth(self, f):
        parts = str(f.get('synthesisId') or '').split('|')
        try:
            star = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            star = 0
        if RS.is_item(parts[0]):
            return RS.synth(self, parts[0], f.get('itemIds') or [])
        if (parts[0], star) in EXTRA:
            return self.extra(EXTRA[(parts[0], star)], [int(x) for x in (f.get('itemIds') or [])])
        r = RECIPES.get((parts[0], star))
        if not r:
            return self.fail('no recipe (%s)' % f.get('synthesisId'))
        free = set(self.free_items())
        ids = [int(x) for x in (f.get('itemIds') or [])]
        ok = lambda i: (i in free and self.p.d['items'].get(str(i)) == r['input']
                        and (PC.state(self.p, i) or {}).get('star', 0) == r['input_star'])
        ids = [i for i in dict.fromkeys(ids) if ok(i)]
        if len(ids) < r['count']:                    # if the client selected too few, it is completed from the suitable ones (non-upgraded first)
            rest = sorted((i for i in free if ok(i) and i not in ids), key=lambda i: PC.level(self.p, i))
            ids += rest[:r['count'] - len(ids)]
        if len(ids) < r['count']:
            return self.fail('not enough %s (%d/%d)' % (r['input'], len(ids), r['count']))
        ids = ids[:r['count']]
        if INV.spend(self.p, dict(r['charge']), 'buy_SPECIAL', 'synthesis') is None:
            return self.fail('cost not covered (%s)' % r['charge'])
        refund = {}
        for i in ids:
            for k, v in PC.upgrade_returns(self.p, i, D['refund']).items():
                refund[k] = refund.get(k, 0) + v
        with self.p.lock:
            for i in ids:
                del self.p.d['items'][str(i)]
                self.p.d.get('particle', {}).pop(str(i), None)
                self.p.d.get('upgrade_level', {}).pop(str(i), None)
            self.p.dirty = True
        new = PC.create(self.p, r['target'], star=r['star'])
        msgs = [('InventoryItemRemovedCommand', {'itemId': i}) for i in ids] + INV.update_msgs(self.m, self.p, list(r['charge']))
        if self.m:
            msgs += [self.m.inv_item(new, r['target'], 1), self.m.pack([self.m.hangar_item(new, r['target'], 1)])]
            for k, v in refund.items():
                msgs += self.m.reward(k, v)
        else:
            for k, v in refund.items():
                self.p.add_resource(k, v)
        self.log('   Synthesis: %d x %s -> %s%s (cost %s%s)' % (len(ids), r['input'], r['target'], ' %d star' % r['star'] if r['star'] else '',
                                                              r['charge'], ', refund %s' % refund if refund else ''))
        from legacy_protocol import legacy
        import ship_module as GM                     # the new cannon to the Restabilize list (H70)
        return msgs + [legacy('0|LM|ST|LOT|%s|1' % r['target'])] + self.inventory_cmds() + [GM.list_cmd(self.p)]
