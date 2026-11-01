"""Synthesis penceresi: Intensify, SG Drive ve Cannon Star Up (yol haritası Aşama 9b; tarifler data/particle.json 'synthesis' <-
tools/particle.py, kaynak resmî forum SSS'leri ve darkorbitwiki).

İstemci (UISynthesisSystem; istekler istemcinin kodundan; kayıtta liste hiç gelmemiş, pencere boş açılıyordu):
  SynthesisListCommand {groups: [SynthesisGroupCommand {group, button (çeviri anahtarı), moduleList: [SynthesisModuleListCommand
      {moduleListGroupType (Synthesis_table_1 Nidhogg, _2 Helios, _3 Indra; Synthesis_drive_1 IgniDrive, _2 Grav-Lens), modules:
      [SynthesisModuleCommand {lootId (sonuç), star, moduleGroupType, costs [SynthesisCostLootCommand {lootId, amount, star,
      certain}], affectedShip (UL gemi topunun gemi kimliği)}]}]}]}   girişte ve pencere açılınca
  SynthesisInventoryRequest            -> liste + SynthesisInventoryCommand {equipmentInventoryItems: takılı olmayan top, sürücü ve
                                          mercekler (hangar eşyası biçiminde)}
  SynthesisItemRequest {synthesisId "lootId|affectedShip|star", itemIds}: seçilen girdiler (aynı tür, aynı yıldız, takılı değil)
      ve bedel (uridyum, Energy eşyası) harcanır, sonuç eşyası gelir; yükseltilmiş girdinin malzemesinin %50'si geri verilir
      ("The selected weapon material has been reinforced …"). Star Up: aynı UL topundan iki tane -> bir yıldız fazlası, nitelikler
      yeniden çekilir.
"""
import json, os
import particle as PC
import inventory as INV
import resonator as RS

D = PC.D['synthesis']
RECIPES = {(r['hedef'], r['yildiz']): r for r in D['recipes']}
# Ö6: Assembly'de gösterilemeyen tarifler (istemci tarifi kendi verisinden okur) -> "title_assembly" sekmesi (tools/esyalar_o6.py)
EXTRA_D = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'items_o6.json'),
                         encoding='utf8'))['extra_recipes']
EXTRA = {(r['hedef'], r['yildiz']): r for r in EXTRA_D['recipes']}
INSTANCE = ('equipment_', 'drone_', 'pet_')                # girdisi eşya örneği: seçilen yuva (certain)
EXTRA_COUNT = 'ek_tarif_sayac'                             # profil: tarif -> kaç kez (USABLE_ONCE / en_cok)
REQUESTS = {'SynthesisInventoryRequest', 'SynthesisItemRequest'}
SOURCES = {r['girdi'] for r in D['recipes']} | RS.INPUTS \
    | {l for r in EXTRA_D['recipes'] for l in r['girdiler'] if l.startswith(INSTANCE)}   # + Ö6: rezonatörler, AA-1/AAP-1
TABLE_KEY = 'Synthesis_%s'                                  # table_1 -> Synthesis_table_1 (Nidhogg), drive_1 -> Synthesis_drive_1 …
ACTION_KEY = {'star': 'synthesis_cannon_star_promote'}     # işlem düğmesi; ötekiler "Synthesis"


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Synthesis:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                 # mağaza (hangar eşyası, ödüller, para); oturum bağlar

    def module(self, r):
        # istemci (UISynthesisSystem.SelectNeedItem / OnTypeSelectionChanged): certain=true her kayıt seçilecek bir eşya yuvası
        # ("Select n / NeedNum", NeedNum = bu kayıtların sayısı), certain=false kayıtlar "eldeki/gereken" malzeme satırı (yetmezse
        # kırmızı). Önce girdi tek kayıt (adet 5) ve uridyum da certain gidiyordu: pencere "0 / 2" ve iki yuva gösteriyordu (H53)
        costs = [mod('SynthesisCostLootCommand', lootId=r['girdi'], amount=1, star=r['input_star'], certain=True)] * r['adet']
        costs += [mod('SynthesisCostLootCommand', lootId=k, amount=v, star=0, certain=False) for k, v in r['bedel'].items()]
        ship = D['ship_ids'].get(r['gemi'], 0) if r['gemi'] else 0
        return mod('SynthesisModuleCommand', star=r['yildiz'], moduleGroupType=TABLE_KEY % r['tablo'], lootId=r['hedef'], costs=costs,
                   affectedShip=ship)

    def extra_module(self, r):
        costs = []
        for loot, n in r['girdiler'].items():
            if loot.startswith(INSTANCE):
                costs += [mod('SynthesisCostLootCommand', lootId=loot, amount=1, star=0, certain=True)] * n
            else:
                costs.append(mod('SynthesisCostLootCommand', lootId=loot, amount=n, star=0, certain=False))
        return mod('SynthesisModuleCommand', star=r['yildiz'], moduleGroupType=EXTRA_D['tablo'], lootId=r['hedef'], costs=costs,
                   affectedShip=0)

    def list_cmd(self):
        groups = {}
        for r in D['recipes']:
            groups.setdefault(r['grup'], {}).setdefault(r['tablo'], []).append(r)
        # istemci üst sekmenin adını 'group'tan, sol düğmelerin adını moduleListGroupType'tan, alttaki işlem düğmesini 'button'dan
        # çeviriyor (hepsi çeviri anahtarı); önce sekmeler ve düğmeler boş görünüyordu (canlı test H52, kontrol kanalıyla denendi)
        out = [mod('SynthesisGroupCommand', button=ACTION_KEY.get(g, 'Synthesis_button'), group=D['buttons'][g], moduleList=[
            mod('SynthesisModuleListCommand', moduleListGroupType=TABLE_KEY % t, modules=[self.module(r) for r in rs])
            for t, rs in sorted(tables.items())]) for g, tables in groups.items()]
        out.append(RS.group_cmd(self.p))                    # Ö6: Resonator sekmesi (rezonator.py; C'nin bedeli oyuncunun kaynağından)
        out.append(mod('SynthesisGroupCommand', button='Synthesis_button', group=EXTRA_D['grup'], moduleList=[
            mod('SynthesisModuleListCommand', moduleListGroupType=EXTRA_D['tablo'],
                modules=[self.extra_module(r) for r in EXTRA_D['recipes']])]))
        return 'SynthesisListCommand', {'groups': out}

    def cost_loots(self):
        """Pencerede bedel satırı olan kaynaklar (certain=false; para hariç)."""
        out = {k for r in D['recipes'] for k in r['bedel']} | set(RS.SOURCES)
        out |= {l for r in EXTRA_D['recipes'] for l in r['girdiler'] if not l.startswith(INSTANCE)}
        return {l for l in out if not l.startswith('currency_')}

    def free_items(self):
        eq = self.p.equipped_ids()
        return [int(i) for i, l in sorted(self.p.d['esyalar'].items(), key=lambda x: int(x[0])) if l in SOURCES and int(i) not in eq]

    def inventory_cmds(self):
        items = []
        if self.m:
            items = [self.m.hangar_item(i, self.p.d['esyalar'][str(i)], 1) for i in self.free_items()]
            # bedel satırının "eldeki" sayısı: istemci (UISynthesisSystem.OnTypeSelectionChanged) bu listede lootId'yi arar ve
            # itemCount'unu alır (uridyum Hero'dan); kaynaklar listede yokken Energy, Mucosum … hep "0/n" ve düğme kapalıydı (Ö6)
            for loot in sorted(self.cost_loots()):
                n = INV.count(self.p, loot)
                if n > 0:
                    items.append(self.m.hangar_item(self.m.item_id(loot), loot, n))
        # istemci (InventoryItemData.UpdateDetailedItems): remove=false ise listeyi temizleyip yenisini koyar, ama tam bir öğe
        # geldiyse temizlemeden ekler. Synthesis'ten sonra yalnız yeni eşya boşta kalınca harcanan girdiler pencerede kalıyordu
        # (canlı test H54): tek öğede önce boş liste (temizler) gider
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
        self.log('   Synthesis olmadı: %s' % why)
        return [stm('Synthesis_error')] + self.inventory_cmds()

    def extra(self, r, ids):
        """Assembly sekmesinin tarifi: seçilen eşyalar (AA-1 …) ve kaynaklar harcanır, çıktı ödül yoluyla (tasarım, EP, cephane …)."""
        p = self.p
        done = p.d.get(EXTRA_COUNT, {}).get(r['tarif'], 0)
        if r.get('en_cok') and done >= r['en_cok']:
            return self.fail('%s en çok %d kez' % (r['tarif'], r['en_cok']))
        free = set(self.free_items())
        chosen = []
        for loot, n in r['girdiler'].items():
            if not loot.startswith(INSTANCE):
                continue
            ok = [i for i in dict.fromkeys(ids) if i in free and p.d['esyalar'].get(str(i)) == loot]
            ok += [i for i in sorted(free) if p.d['esyalar'].get(str(i)) == loot and i not in ok]
            if len(ok) < n:
                return self.fail('%s yetmiyor (%d/%d)' % (loot, len(ok), n))
            chosen += ok[:n]
        rest = {l: n for l, n in r['girdiler'].items() if not l.startswith(INSTANCE)}
        if rest and INV.spend(p, rest, 'buy_SPECIAL', 'assembly') is None:
            return self.fail('bedel yetmiyor (%s)' % rest)
        with p.lock:
            for i in chosen:
                p.d['esyalar'].pop(str(i), None)
            p.d.setdefault(EXTRA_COUNT, {})[r['tarif']] = done + 1
            p.dirty = True
        msgs = [('InventoryItemRemovedCommand', {'itemId': i}) for i in chosen] + INV.update_msgs(self.m, p, list(rest))
        if self.m:
            msgs += self.m.reward(r['hedef'], r['adet'])
        else:
            p.add_resource(r['hedef'], r['adet'])
        self.log('   Synthesis (Assembly): %s -> %s x%d' % (r['girdiler'], r['hedef'], r['adet']))
        return msgs + [self.list_cmd()] + self.inventory_cmds()        # ödül yolu "aldınız" metnini kendisi gönderir

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
            return self.fail('tarif yok (%s)' % f.get('synthesisId'))
        free = set(self.free_items())
        ids = [int(x) for x in (f.get('itemIds') or [])]
        ok = lambda i: (i in free and self.p.d['esyalar'].get(str(i)) == r['girdi']
                        and (PC.state(self.p, i) or {}).get('yildiz', 0) == r['input_star'])
        ids = [i for i in dict.fromkeys(ids) if ok(i)]
        if len(ids) < r['adet']:                    # istemci eksik seçtiyse uygun olanlardan tamamlanır (yükseltilmemişler önce)
            rest = sorted((i for i in free if ok(i) and i not in ids), key=lambda i: PC.level(self.p, i))
            ids += rest[:r['adet'] - len(ids)]
        if len(ids) < r['adet']:
            return self.fail('%s yetmiyor (%d/%d)' % (r['girdi'], len(ids), r['adet']))
        ids = ids[:r['adet']]
        if INV.spend(self.p, dict(r['bedel']), 'buy_SPECIAL', 'synthesis') is None:
            return self.fail('bedel yetmiyor (%s)' % r['bedel'])
        refund = {}
        for i in ids:
            for k, v in PC.upgrade_returns(self.p, i, D['refund']).items():
                refund[k] = refund.get(k, 0) + v
        with self.p.lock:
            for i in ids:
                del self.p.d['esyalar'][str(i)]
                self.p.d.get('parcacik', {}).pop(str(i), None)
                self.p.d.get('yukseltme_seviye', {}).pop(str(i), None)
            self.p.dirty = True
        new = PC.create(self.p, r['hedef'], star=r['yildiz'])
        msgs = [('InventoryItemRemovedCommand', {'itemId': i}) for i in ids] + INV.update_msgs(self.m, self.p, list(r['bedel']))
        if self.m:
            msgs += [self.m.inv_item(new, r['hedef'], 1), self.m.pack([self.m.hangar_item(new, r['hedef'], 1)])]
            for k, v in refund.items():
                msgs += self.m.reward(k, v)
        else:
            for k, v in refund.items():
                self.p.add_resource(k, v)
        self.log('   Synthesis: %d x %s -> %s%s (bedel %s%s)' % (len(ids), r['girdi'], r['hedef'], ' %d yıldız' % r['yildiz'] if r['yildiz'] else '',
                                                              r['bedel'], ', iade %s' % refund if refund else ''))
        from legacy_protocol import legacy
        import ship_module as GM                     # yeni top Restabilize listesine (H70)
        return msgs + [legacy('0|LM|ST|LOT|%s|1' % r['hedef'])] + self.inventory_cmds() + [GM.list_cmd(self.p)]
