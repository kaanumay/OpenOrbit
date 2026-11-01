"""Gemi modülleri ve kararsız modüller (yol haritası Aşama 6; veri data/ship_modules.json <- tools/ship_modules.py).

Normal modüller (DMG-CHT01, HP-VP01, SPC-XP01 …): hangarda config'in "upgrades" yuvasına takılır (HangarShipEquipmentMsg.upgrades;
yuva sayısı istemcinin gemi verisinden: çoğu gemide 3, Plus gemilerde 4). Etki yalnız açıklamadaki gemilerde (istemcinin metni
"This ship upgrade module can be used on the following ships: …"); SPC-XP01/02'nin EP'si 16. seviyeye dek.
Kararsız modüller (DMG-X1 … XV03, HP-/SHD-/SPC- serileri): her örneğin rastgele nitelikleri (UnstableAttributeModule {attribute,
boostValue}; adlar istemcinin items_equipment_shipupgrade_modifiertype_* anahtarları) ve geçerli olduğu gemiler (shipDesigns) var;
istemcinin Restabilize penceresi (istekler istemcinin kodundan):
  girişte / değişince       UnstableModulesListCommand {allModules, shardCommand {chipLeft, shardsLeft}}
  UnstableModuleRerollRequest {itemId}        Unstable Shard harcanır, yalnız nitelikler yeniden çekilir (gemiler aynı kalır: resmî
      SSS "only the module stat modifiers will be regenerated, not the ships"); öncekiler saklanır
      -> UnstableModuleRestabilizeResultCommand {itemId, oldModule, newModule, success}
  UnstableModuleRestabiliseRequest {itemId, isSalvage}  isSalvage: Salvage Core vb. ödenip önceki nitelikler geri alınır ("Your
      unstable module has been salvaged to retain the same modifiers"); değilse yenisi kalır
  UnstableModuleRecycleRequest {itemId}        modül sökülür, Unstable Shard geri verilir
Değerler gerçek kayda (UnstableModulesListCommand) ve wiki'ye göre, seri başına (veri ship_modules.json kararsiz.restabilize ve
.aralik <- tools/ship_modules.py): geri dönüşümde alınan shard, yeniden çekme bedeli ve hakkı (X1/XW01 2/10/10, X2 ve ara seriler
4/20/8, XSP01 20/100/4, XT10 30/150/2); saklama (Salvage) bedeli her modülde 200 Salvage Core + 38 ABR + 6 Indoctrine Oil. Nitelik
değerleri tam sayı yüzde, serinin iki kademeli aralığından (büyük şans / küçük şans: KUCUK_SANS); kayıttaki modüllerde 1-3 nitelik
(ana nitelik modülün ailesinden, öbürleri IKINCIL havuzdan %1-3) ve 1-3 gemi var. Uyarlama (kayıtta yok): kademe şansı, nitelik ve
gemi sayısı ağırlıkları, X1/X2/XW01 aralıkları (wiki "Randomly").
Profilde: kararsiz {itemId: {nitelik: [[ad, değer]], gemiler, hak, onceki}}.
"""
import json, os, random, re

import inventory as INV
import ranks as RT

HERE = os.path.dirname(os.path.abspath(__file__))
M = json.load(open(os.path.join(HERE, 'data', 'ship_modules.json'), encoding='utf8'))['modules']
ITEMS = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))['esyalar']
SHARD, CHIP = 'resource_collectable_unstable-shard', 'resource_collectable_optigrad-chip'
ATTR_KEYS = {'damage': ('lazer', 'roket'), 'dmg_laser': ('lazer',), 'dmg_rockets': ('roket',), 'dmg_npc': ('npc',), 'dmg_pvp': ('pvp',),
             'hitpoints': ('can',), 'shield': ('kalkan',), 'speed': ('hiz',), 'evasion': ('evasion',), 'hitchance_laser': ('laser_hit_chance',),
             'hitchance_rocket': ('rocket_hit_chance',), 'experience': ('ep',), 'honour': ('onur',), 'shield_penetration': ('shield_penetration',)}
POOL = {'DAMAGE': ['damage', 'dmg_laser', 'dmg_rockets', 'dmg_npc'], 'HP': ['hitpoints'], 'SHIELD': ['shield'],
        'SPECIAL': ['speed', 'evasion', 'hitchance_laser', 'hitchance_rocket', 'shield_penetration']}      # ana nitelik (istemcinin açıklaması)
RETAIN = {'resource_collectable_salvage-core': 200, 'resource_collectable_axion-beam-regulator': 38,
          'resource_collectable_indoctrineoil': 6}          # kayıttaki retainCost, her modülde aynı (wiki "Salvage Expansion")
XP_MAX_LEVEL = 16
UPGRADE_SLOTS = 3
SMALL_CHANCE = 0.2          # iki kademeli serilerde (XV01, XU, XHD01 …) küçük şansın (yüksek kademe) olasılığı: istemci "moderate chance" (uyarlama)
PRIORITY_CHANCE = 0.5        # her gemi seçiminde öncelikli listeden çekme olasılığı (kayıttaki 12 gemiden 6'sı öncelikliydi)
SECONDARY = ('damage', 'dmg_laser', 'dmg_rockets', 'dmg_npc', 'dmg_pvp', 'hitpoints', 'shield', 'speed', 'evasion', 'hitchance_laser',
           'hitchance_rocket', 'shield_penetration')      # 2. ve 3. niteliğin havuzu (kayıt: SPC-XU03'te DMG_NPC 1, DMG-XT10'ta HITCHANCE_LASER 3 ve SHIELD 1)


def mod(name, **f):
    f['_'] = name
    return f


def is_module(loot):
    return loot in M


def unstable(loot):
    return 'unstable' in M.get(loot, {})


def slots(ship_loot):
    """Geminin modül yuvası (istemcinin gemi verisi: ship_upgrades)."""
    return int((ITEMS.get(ship_loot, {}).get('slots') or {}).get('ship_upgrades', UPGRADE_SLOTS))


def ships_for(loot):
    return M.get(loot, {}).get('ships', [])


def all_ships():
    """Kararsız modülün çekilebileceği gemiler: sunucunun gemileri (items.json gemiler)."""
    global _SHIPS
    if _SHIPS is None:
        _SHIPS = sorted(json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))['ships'])
    return _SHIPS


_SHIPS = None


# ------------------------------------------------------------ kararsız modül değerleri
def restab(loot):
    """Kararsız modülün serisinin Restabilize değerleri: geri (geri dönüşümde alınan shard), bedel (yeniden çekme), hak (en çok kaç kez)."""
    return M[loot]['unstable']['restabilize']


def pick_value(unstable, attr, rng):
    """Ana niteliğin değeri: serinin aralığı (niteliğin kendi aralığı varsa o); küçük şans (yüksek kademe) KUCUK_SANS olasılıkla;
    tam sayı yüzde (kayıttaki boostValue'lar hep tam sayı)."""
    a = unstable['interval']
    a = a.get('nitelik', {}).get(attr) or a
    lo, hi = a['lowercase'] if a.get('lowercase') and rng.random() < SMALL_CHANCE else a['buyuk']
    return rng.randint(lo, hi) / 100.0


def roll(loot, rng=random):
    """Kararsız modülün nitelikleri ve gemileri: 1-3 nitelik (biri modülün ailesinden ve serinin aralığında, öbürleri küçük) ve 1-3 gemi
    (kayıt: 7 modül 1, 1, 1, 1, 2, 2 ve 3 gemili; öncelikli gemiler sık çıkar ama zorunlu değil)."""
    info = M[loot]
    unstable = info['unstable']
    main = rng.choice(POOL.get(info['tur'], POOL['DAMAGE']))
    vals = [[main, pick_value(unstable, main, rng)]]
    vals += [[a, rng.randint(1, max(3, unstable['interval']['buyuk'][1])) / 100.0] for a in rng.sample([a for a in SECONDARY if a != main], rng.choices((0, 1, 2), (6, 3, 1))[0])]
    rng.shuffle(vals)                      # kayıtta ana nitelik ilk olmayabiliyor (DMG-XT10: DMG_NPC sonuncu)
    pref = list(unstable.get('preference', []))
    rest = [s for s in all_ships() if s not in pref and s not in unstable.get('exclude', ())]      # serinin çıkmadığı gemiler (forum 162335)
    picks = []
    for _ in range(rng.choice((1, 1, 2, 3))):
        pool = [s for s in (pref if pref and rng.random() < PRIORITY_CHANCE else rest) if s not in picks] or [s for s in rest + pref if s not in picks]
        picks.append(rng.choice(pool))
    return dict(nitelik=vals, ships=sorted(picks))


def state(p, iid):
    """Kararsız modül örneğinin kaydı (ilk bakışta çekilir)."""
    d = p.d.setdefault('unstable', {})
    rec = d.get(str(iid))
    loot = p.d['esyalar'].get(str(iid))
    if rec is None and loot and unstable(loot):
        rec = d[str(iid)] = dict(roll(loot), right=restab(loot)['right'])
        p.dirty = True
    elif rec and loot and unstable(loot) and rec['right'] > restab(loot)['right']:
        rec['right'] = restab(loot)['right']            # eski sabit 5 hak, seri azamisini (XT10 2, XSP01 4) aşamaz
        p.dirty = True
    return rec


def module_msg(p, iid):
    rec, loot = state(p, iid), p.d['esyalar'].get(str(iid))
    r = restab(loot)
    return mod('UnstableModuleModule', recycleReturns=r['refund'], rerollsMax=r['right'], rerollCost=r['charge'], rerollsLeft=rec['right'],
               retainCost=[mod('LootModule', lootId=l, amount=n, modifier='') for l, n in sorted(RETAIN.items())],
               attributes=[mod('UnstableAttributeModule', attribute=a, boostValue=round(v * 100, 2)) for a, v in rec['nitelik']],
               shipDesigns=list(rec['ships']), itemId=int(iid), lootId=loot)


def ship_ids(loots):
    """Hangar ipucunun gemi listesi (HangarShipEquipmentInventoryItem.ships): istemci (TooltipPreparerFactory.ReturnShips) ','
    ile böler, her parçayı sayıya çevirip gemiyi kimliğiyle bulur (GetItemByShipId). Gemi adları (ship_goliath) 0 okunuyordu."""
    return ','.join(str(ITEMS[l]['kimlik']) for l in loots if (ITEMS.get(l) or {}).get('kimlik') is not None)


def modifiers_str(p, iid):
    """Kararsız modülün hangar ipucu nitelikleri: "AD,yüzde;…" (TooltipPreparerFactory.ReturnModifiers: değer tam sayı, metin
    items_equipment_shipupgrade_modifiertype_<ad>). Boşken ipucunun "Tür:" satırı boş kalıyordu (kullanıcı 2026-10-19)."""
    rec = state(p, iid) or {}
    return ';'.join('%s,%d' % (a.upper(), max(1, int(round(v * 100)))) for a, v in rec.get('nitelik', []) if v > 0)


def shard_cmd(p):
    return mod('UnstableModulesShardCommand', chipLeft=p.resource(CHIP), shardsLeft=p.resource(SHARD))


def list_cmd(p, reset=False):
    import particle as PC                                       # parçacık topları ve kırıcılar (OptiGrad Chip; Aşama 9b)
    ids = sorted(int(i) for i, l in p.d['esyalar'].items() if unstable(l))
    return ('UnstableModulesListCommand', dict(allModules=[module_msg(p, i) for i in ids] + PC.modules(p), resetUI=reset,
                                                 isDiscountRunning=False, shardCommand=shard_cmd(p)))


# ------------------------------------------------------------ etkiler
def kind(loot):
    """Modülün türü (DAMAGE, HP, SHIELD, SPECIAL) ya da None."""
    return M.get(loot or '', {}).get('tur')


def type_taken(p, iid, current):
    """Gemide bu modülün türünden başka bir modül takılı mı: resmî SSS ("New Ship Upgrade Modules FAQ"): bir modül gemide bir kez,
    her türden (HP, Damage, Shield, Special) bir modül (kullanıcı bildirimi 2026-10-25: aynı türden birden çok takılabiliyordu)."""
    k = kind(p.d['esyalar'].get(str(iid)))
    return bool(k) and any(i != iid and kind(p.d['esyalar'].get(str(i))) == k for i in current)


def mods(p, ship_loot, iids, level=None):
    """Takılı modüllerin bonusları (yalnız geçerli gemide; her türden ilki: kural öncesi takılmış ikinciler sayılmaz)."""
    out, seen = {}, set()
    for iid in iids:
        loot = p.d['esyalar'].get(str(iid))
        info = M.get(loot or '')
        if not info or info['tur'] in seen:
            continue
        seen.add(info['tur'])
        if 'unstable' in info:
            rec = state(p, iid)
            if ship_loot not in rec['ships']:
                continue
            eff = {}
            for a, v in rec['nitelik']:
                for k in ATTR_KEYS.get(a, ()):
                    eff[k] = eff.get(k, 0) + v
        else:
            if ship_loot not in info['ships']:
                continue
            eff = dict(info['effects'])
            if 'ep' in eff and loot.startswith('equipment_shipupgrade_spc-xp') and (level or 0) >= XP_MAX_LEVEL:
                eff.pop('ep')                                   # SPC-XP01/02: 16. seviyeye dek
        for k, v in eff.items():
            out[k] = out.get(k, 0) + v
    return out


def equip_allowed(p, iid, ship_loot):
    """Modül yalnız kendi gemilerine takılır: normalde açıklamadaki, kararsızda çekilen gemiler (resmî SSS: ipucunda "the ships it
    can be equipped on"; canlı tur 2'de DMG-XSP01 listesinde olmayan Solaris Plus'a takılıyordu)."""
    loot = p.d['esyalar'].get(str(iid))
    info = M.get(loot or '')
    return bool(info) and ship_loot in (state(p, iid)['ships'] if 'unstable' in info else info['ships'])


# ------------------------------------------------------------ istekler
class Modules:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None

    def result(self, iid, old, new, ok=True):
        return ('UnstableModuleRestabilizeResultCommand', dict(itemId=int(iid), oldModule=old, newModule=new, success=ok))

    def reroll(self, f):
        iid = int(f.get('itemId') or 0)
        loot = self.p.d['esyalar'].get(str(iid))
        import particle as PC
        if loot and PC.restabilizable(loot):                    # top/kırıcı: OptiGrad Chip ile ek nitelikler
            from legacy_protocol import legacy
            res = PC.reroll(self.p, iid)
            if isinstance(res, str):
                return [legacy('0|A|STM|%s' % res), list_cmd(self.p)]
            self.log('   Restabilize: %s -> %s' % (loot, PC.state(self.p, iid)['nitelik']))
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
            rec['previous'] = dict(nitelik=rec['nitelik'])
            rec['nitelik'] = roll(loot)['nitelik']             # gemiler değişmez (resmî SSS)
            rec['right'] -= 1
            self.p.dirty = True
        self.log('   Restabilize: %s -> %s %s' % (loot, rec['nitelik'], rec['ships']))
        RT.note(self.p, 'his_rerolled_unstable_module', loot, cost)    # seyir defteri (%NAME% info'dan, %COUNT%)
        return self.after(iid, [self.result(iid, old, module_msg(self.p, iid))])

    def restabilise(self, f):
        iid = int(f.get('itemId') or 0)
        import particle as PC
        if PC.restabilizable(self.p.d['esyalar'].get(str(iid), '')):      # top/kırıcı: eskisine dön ya da yenisi kalsın
            if f.get('isSalvage'):
                PC.revert(self.p, iid)
            else:
                (PC.state(self.p, iid) or {}).pop('previous', None)
            return self.after(iid, [])
        rec = state(self.p, iid) if str(iid) in self.p.d['esyalar'] else None
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
        self.log('   Salvage: %s önceki niteliklere döndü' % self.p.d['esyalar'][str(iid)])
        return INV.update_msgs(self.m, self.p, list(RETAIN), removed) + self.after(iid, [self.result(iid, old, module_msg(self.p, iid))])

    def recycle(self, f):
        iid = int(f.get('itemId') or 0)
        loot = self.p.d['esyalar'].get(str(iid))
        import particle as PC
        if loot and PC.restabilizable(loot):                    # top/kırıcı: OptiGrad Chip ve yükseltme malzemesinin %80'i
            from legacy_protocol import legacy
            got = PC.recycle(self.p, iid)
            if got is None:
                return [legacy('0|A|STM|msg_reroll_error_item'), list_cmd(self.p)]
            msgs = [('InventoryItemRemovedCommand', {'itemId': iid})]
            for l, n in got.items():
                msgs += self.m.reward(l, n) if self.m else []
                if not self.m:
                    self.p.add_resource(l, n)
            self.log('   geri dönüşüm: %s -> %s' % (loot, got))
            return msgs + [('UnstableModuleRecycleResultCommand', dict(itemId=iid, shardCommand=shard_cmd(self.p))), list_cmd(self.p)]
        if not loot or not unstable(loot):
            from legacy_protocol import legacy
            return [legacy('0|A|STM|msg_reroll_error_item')]
        worn = iid in self.p.equipped_ids()                  # forum 162335: takılıyken de geri dönüşür; önce yuvasından çıkar
        with self.p.lock:
            for s in self.p.d['ships'].values():
                for cfg in s.get('configs', {}).values():
                    for lst in cfg.values():
                        if isinstance(lst, list) and iid in lst:
                            lst.remove(iid)
            del self.p.d['esyalar'][str(iid)]
            self.p.d.get('unstable', {}).pop(str(iid), None)
            self.p.dirty = True
        back = restab(loot)['refund']
        msgs = [('InventoryItemRemovedCommand', {'itemId': iid})] + (self.m.reward(SHARD, back) if self.m else [])
        if not self.m:
            self.p.add_resource(SHARD, back)
        self.log('   geri dönüşüm: %s -> %d shard' % (loot, back))
        RT.note(self.p, 'his_recycled_unstable_module', loot, back)
        if worn and self.m:
            msgs += [self.m.equipment_cmd()] + self.m.apply_stats()
        return msgs + [('UnstableModuleRecycleResultCommand', dict(itemId=iid, shardCommand=shard_cmd(self.p))), list_cmd(self.p)]

    def after(self, iid, msgs):
        """Takılı modül değiştiyse hız/kalkan/can yeniden."""
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
