"""Parçacık silahları ve Singularity Drive (yol haritası Aşama 9b; veri data/particle.json <- tools/particle.py, kaynak resmî forum
SSS'leri ve darkorbitwiki).

Eşyalar envanterde örnek olarak (profil esyalar); hangarda geminin yuvalarına: top 'cannon' (3, her türden bir), kırıcı
'cannonShield' (6), sürücü 'drive', mercek 'lens' (sayılar istemcinin gemi verisinde). Örnek durumu profilde: parcacik {itemId:
{nitelik [[ad, değer]], hak (yenileme), yildiz}}; topların ve kırıcıların ek nitelikleri alınınca çekilir (kaliteye göre adet ve
aralık), sürücü ve merceklerin alt nitelikleri yükseltme seviyesi 5/10/15/20'de açılır. Hangar ipucu: topun temel hasarı
extAttributes ('baseDamage'), nitelikler modifiers ("değer,ad;…"), UL topun gemisi ships.
Yenileme: toplar ve kırıcılar Assembly'nin Restabilize sekmesinde (CannonUnstableModuleModule; OptiGrad Chip, geri dönüşümde çip ve
yükseltme malzemesinin %80'i; UL geri dönüştürülmez), sürücüler ve mercekler Singularity Drive penceresinde (LockAttributeItem*:
Horizon Shard, kilit Containment Node).
Uçuşta (Atis, dünyanın döngüsünde):
  slug (kısayol çubuğu 'cannons'): seçilir ve hedefe ateşlenir (aynı türden top takılıysa; bütün topların tek beklemesi 4 sn,
      menzil 600); RG-SL açıkken lazer saldırısında seçili slug kendiliğinden. CannonAttackCommand {cannonType, hit, attackerId,
      attackedId} + AttackHitCommand (attackType CANNON 21, cannonType, strike). Helios: 5 hedefe 275 içinde %40 sıçrama
      (PlayVisualEffectCommand 8); Nidhogg: 20 sn %5 aşındırma zaafı, 5 kat (VisualModifierCommand 146); Indra: 7 hedefe zincir, her
      atlamada -%15 (PlayVisualEffectCommand 9).
  GSP (kısayol çubuğu 'drives'): takılı sürücü sayısı kadar cephane, bekleme 10 sn; ana hedefin çevresinde 600 birimlik alan 8 sn
      saniyede bir vurur (AttackHitCommand DRIVE 22; görsel DA_SHOT 17-19, alan DA_OUTER_FRIENDLY 152/154/156). Apex ve Prime set
      çarpanı (3-10 sürücü), 6 Apex/Prime'dan sonra alan 900 (istemcinin paket açıklamaları). AGS-X açıkken lazer saldırısında
      kendiliğinden.
Kırıcı ve merceklerin savunması oyuncu silahlarına karşı (bot oyuncularla, Aşama 11).
"""
import json, math, os, random, time

import settings as SET
import inventory as INV

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'particle.json'), encoding='utf8'))
ITEMS = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))['esyalar']
CANNONS, SHIELDS, DRIVES, LENSES = D['cannons'], D['breakers'], D['drives'], D['lenses']
SLUGS, GSP = D['slugs'], D['gsp']
C, DR = D['cannon_common'], D['drive_common']
PREFIX = {'equipment_weapon_cannon_': 'cannon', 'equipment_cannon_shield_': 'cannonShield', 'equipment_weapon_drive_': 'drive',
          'equipment_lens_': 'lens'}
SHIP_SLOTS = {'cannon': 'cannons', 'cannonShield': 'cannon_shields', 'drive': 'drives', 'lens': 'lenses'}
SLOTS = tuple(PREFIX.values())
CANNON_ATTACK, DRIVE_ATTACK = 21, 22                 # istemcinin AttackType'ı
VE_THERMAL, VE_ELECTRO, VM_CORROSIVE = 8, 9, 146     # VisualEffectType, VisualModifier
COOLDOWN_CANNON, COOLDOWN_DRIVE = 60, 61             # CooldownType (kısayol çubuğu grupları)
CPU_CANNON, CPU_DRIVE = 'equipment_extra_cpu_rg-sl', 'equipment_extra_cpu_ags-x'
DMG_KEY = {'thermal': 'cannon_damage_thermal', 'corrosive': 'cannon_corrosive_damage', 'electro': 'cannon_electro_damage'}
DRIVE_SHIP_KEYS = {'drive_experience': 'ep', 'drive_honour': 'onur', 'drive_evasion': 'kacinma',     # sürücü/merceğin ve kırıcının gemiye etkisi
                   'experience': 'ep', 'honour': 'onur', 'hitpoints': 'can'}


def mod(_cls, **f):
    f['_'] = _cls
    return f


def slot_of(loot):
    return next((s for p, s in PREFIX.items() if loot.startswith(p)), None)


def is_item(loot):
    return slot_of(loot) is not None


def slots(ship_loot, slot):
    return int((ITEMS.get(ship_loot, {}).get('yuvalar') or {}).get(SHIP_SLOTS[slot], 0))


def state(p, iid):
    return p.d.get('parcacik', {}).get(str(iid))


def tier(loot):
    """Kalite sırası: top 0-6 (C … UL), kırıcı 0-5 (01 … 06), sürücü/mercek 0."""
    row = CANNONS.get(loot) or SHIELDS.get(loot)
    return row['sira'] if row else 0


def pool(loot):
    if loot in CANNONS:
        return D['nitelikler']['top'][CANNONS[loot]['element']]
    if loot in SHIELDS:
        return D['nitelikler']['breaker'][SHIELDS[loot]['element']]
    return None


def roll(loot, rng=random, n=None):
    """Topun/kırıcının ek nitelikleri: kaliteye göre adet, aralık; tekrarsız."""
    pl = pool(loot)
    if not pl:
        return []
    count = n if n is not None else (CANNONS.get(loot) or SHIELDS[loot])['ek']
    names = rng.sample(sorted(pl), min(count, len(pl)))
    t = tier(loot)
    return [[a, round(rng.uniform(*pl[a][t]), 2)] for a in names]


def rerolls(loot):
    return D['yenileme']['hak'][tier(loot)] if (loot in CANNONS or loot in SHIELDS) else 0


def create(p, loot, rng=random, star=0):
    """Yeni örnek -> itemId (top/kırıcının ek nitelikleri çekilir)."""
    iid = p.new_item(loot)
    st = {'nitelik': roll(loot, rng), 'hak': rerolls(loot), 'yildiz': star}
    with p.lock:
        p.d.setdefault('parcacik', {})[str(iid)] = st
        p.dirty = True
    return iid


def level(p, iid):
    """Yükseltme seviyesi (istemcinin gösterdiği: 1-20)."""
    import upgrades as UPG
    return UPG.item_level(p, iid) + 1


def ensure(p, iid, rng=random):
    """Sürücü/merceğin alt nitelikleri: yükseltme seviyesi 5/10/15/20'de birer (en çok 4) -> durum."""
    loot = p.d['esyalar'].get(str(iid), '')
    st = state(p, iid)
    if st is None and is_item(loot):
        st = {'nitelik': roll(loot, rng), 'hak': rerolls(loot), 'yildiz': 0}
        with p.lock:
            p.d.setdefault('parcacik', {})[str(iid)] = st
            p.dirty = True
    if st is not None and st['hak'] > rerolls(loot):         # değiştirme sınırı düştü (URETIM-4): eski kayıtlardaki kalan hak
        st['hak'] = rerolls(loot)
        p.dirty = True
    if st is not None and (loot in DRIVES or loot in LENSES):
        need = sum(1 for lv in D['kilit']['seviyeler'] if level(p, iid) >= lv)
        pl = D['nitelikler']['surucu']
        while len(st['nitelik']) < need:
            free = [a for a in sorted(pl) if not a.startswith('_') and a not in [x[0] for x in st['nitelik']]]
            a = rng.choice(free)
            st['nitelik'].append([a, round(rng.uniform(*pl[a]), 2)])
            p.dirty = True
    return st


def attrs(p, iid):
    st = ensure(p, iid)
    return {a: v for a, v in (st or {}).get('nitelik', [])}


def modifiers_str(p, iid):
    """Hangar ipucunun nitelik satırları. İstemci (TooltipPreparerFactory.ReturnModifiers): "AD,değer;…", ad ilk, değer son parça;
    metin items_equipment_shipupgrade_modifiertype_<ad küçük harf>, ad büyük harfle CANNON_IGNORE_DEF_* / DRIVE_IGNORE_DEF ise değer
    düz, ötekiler "%". Önce "değer,ad" gidiyordu: ipucu "+cannon_strike_corrosive%" diye ham ad gösteriyordu (canlı test H55)."""
    st = ensure(p, iid)
    return ';'.join('%s,%d' % (a.upper(), int(round(v))) for a, v in (st or {}).get('nitelik', []))


def base_damage(p, iid, ship_loot=None):
    loot = p.d['esyalar'].get(str(iid), '')
    row = CANNONS.get(loot)
    if not row:
        return 0
    st = state(p, iid) or {}
    dmg = row['taban'] * C['yildiz'][st.get('yildiz', 0)]
    if row['gemi'] and ship_loot == row['gemi']:
        dmg *= C['ship_specific']                              # UL topun kendi gemisinde
    return dmg


def hangar_fields(p, iid, loot):
    """HangarShipEquipmentInventoryItem'a eklenecek alanlar."""
    st = ensure(p, iid) or {}
    f = {'modifiers': modifiers_str(p, iid), 'star': st.get('yildiz', 0)}
    if loot in CANNONS:
        f['extAttributes'] = [mod('TupleTwoModule', param0='baseDamage', param1=str(int(base_damage(p, iid))))]
        if CANNONS[loot]['gemi']:
            import ship_module as GM                           # ipucunun gemisi sayısal kimlikle (ReturnShips)
            f['ships'] = GM.ship_ids([CANNONS[loot]['gemi']])
    return f


def equip_allowed(p, iid, slot, current):
    """-> hata metni ya da None: gemide her türden bir top."""
    loot = p.d['esyalar'].get(str(iid), '')
    if slot == 'cannon':
        kind = CANNONS[loot]['tur']
        if any(CANNONS.get(p.d['esyalar'].get(str(i), ''), {}).get('tur') == kind for i in current if i != iid):
            return 'gemide zaten bir %s topu var' % kind
    return None


def equipped(p, slot, sid=None, cid=None):
    return [i for i in p.config(cid, sid).get(slot, []) if str(i) in p.d['esyalar']]


def cannon_for(p, element):
    """Etkin config'te bu türden takılı top -> itemId ya da None."""
    return next((i for i in equipped(p, 'cannon') if CANNONS.get(p.d['esyalar'][str(i)], {}).get('element') == element), None)


def shield_npc(p, e):
    """Takılı kırıcıların uzaylıya e elementi hasar bonusu (puan)."""
    return sum(attrs(p, i).get('cannon_damage_npc_' + e, 0) for i in equipped(p, 'cannonShield'))


def mods(p, ship_loot, cfg):
    """Takılı sürücü ve merceklerin gemiye etkileri (EP, onur, kaçınma)."""
    out = {}
    for slot in ('drive', 'lens', 'cannonShield'):
        for iid in cfg.get(slot, []):
            if str(iid) not in p.d['esyalar']:
                continue
            for a, v in attrs(p, iid).items():
                k = DRIVE_SHIP_KEYS.get(a)
                if k:
                    out[k] = out.get(k, 0) + v / 100.0
    return out


def migrate(p):
    """Aşama 9b öncesi depoda saklanan top, kırıcı, sürücü ve mercekler -> envanter örnekleri. -> taşınan adet."""
    moved = 0
    for loot, n in list(p.d.get('diger_esyalar', {}).items()):
        if is_item(loot) and loot in ITEMS and n > 0:
            for _ in range(int(n)):
                create(p, loot)
            p.add_resource(loot, -n)
            moved += int(n)
    return moved


# ---------------------------------------------------------------- Restabilize (toplar ve kırıcılar; gemi_modul.py)
def restabilizable(loot):
    return loot in CANNONS or loot in SHIELDS


def upgrade_returns(p, iid, share):
    """Yükseltme malzemesinin payı (geri dönüşüm ve Synthesis)."""
    import upgrades as UPG
    spent = UPG.spent(p, iid) if hasattr(UPG, 'spent') else {}
    return {k: int(v * share) for k, v in spent.items() if int(v * share) > 0}


def attr_mods(st):
    """Restabilize ve Update listelerinin nitelikleri. İstemci (RerollStatsListItem / DriveStatsListItem) adı büyük harfle
    CANNON_IGNORE_DEF_* / DRIVE_IGNORE_DEF ile karşılaştırıp penetrasyonu düz gösterir, simge ve metin için küçültür; küçük harfle
    gidince penetrasyon "51.53%" görünüyordu (canlı test H71)."""
    return [mod('UnstableAttributeModule', attribute=a.upper(), boostValue=float(v)) for a, v in (st or {}).get('nitelik', [])]


def module_msg(p, iid):
    loot = p.d['esyalar'][str(iid)]
    st = ensure(p, iid)
    t = tier(loot)
    back = upgrade_returns(p, iid, D['yenileme']['refund'])
    return mod('CannonUnstableModuleModule', recycleReturns=D['yenileme']['chip'][t],
               rerollsMax=rerolls(loot), rerollCost=D['yenileme']['bedel'][t], rerollsLeft=st['hak'], retainCost=[],
               attributes=attr_mods(st),
               shipDesigns=[CANNONS[loot]['gemi']] if CANNONS.get(loot, {}).get('gemi') else [], itemId=int(iid), lootId=loot,
               upgradeReturns=[mod('LootModule', lootId=k, amount=v, modifier='') for k, v in back.items()],
               upgradeLevel=level(p, iid))          # gösterilen seviye (H63 ile aynı: liste olduğu gibi yazar, topta 0 da görünüyordu)


def modules(p):
    return [module_msg(p, int(i)) for i, l in sorted(p.d['esyalar'].items(), key=lambda x: int(x[0])) if restabilizable(l)]


def reroll(p, iid, rng=random):
    """OptiGrad Chip ile ek nitelikler yeniden -> (eski modül, yeni modül) ya da hata anahtarı."""
    loot = p.d['esyalar'].get(str(iid), '')
    st = ensure(p, iid)
    if not restabilizable(loot) or not st:
        return 'msg_reroll_error_item'
    if st['hak'] <= 0:
        return 'msg_reroll_error_item'
    cost = D['yenileme']['bedel'][tier(loot)]
    if INV.spend(p, {D['yenileme']['chip_item']: cost}, 'buy_SPECIAL', 'cannon_reroll') is None:
        return 'msg_reroll_error_shards'
    old = module_msg(p, iid)
    with p.lock:
        st['onceki'] = st['nitelik']
        st['nitelik'] = roll(loot, rng)
        st['hak'] -= 1
        p.dirty = True
    return old, module_msg(p, iid)


def revert(p, iid):
    """Yenilemeden önceki nitelikler (Restabilize penceresinde eskisini seçmek) -> True: değişti."""
    st = state(p, iid)
    if not st or not st.get('onceki'):
        return False
    with p.lock:
        st['nitelik'] = st.pop('onceki')
        p.dirty = True
    return True


def recycle(p, iid):
    """Geri dönüşüm -> {lootId: adet} ya da None (takılı)."""
    loot = p.d['esyalar'].get(str(iid), '')
    if not restabilizable(loot) or iid in p.equipped_ids():
        return None
    got = upgrade_returns(p, iid, D['yenileme']['refund'])
    chips = D['yenileme']['chip'][tier(loot)]
    if chips:
        got[D['yenileme']['chip_item']] = got.get(D['yenileme']['chip_item'], 0) + chips
    with p.lock:
        del p.d['esyalar'][str(iid)]
        p.d.get('parcacik', {}).pop(str(iid), None)
        p.dirty = True
    return got


# ---------------------------------------------------------------- sürücü ve merceklerin alt nitelikleri (LockAttributeItem*)
def lock_module(p, iid):
    loot = p.d['esyalar'][str(iid)]
    st = ensure(p, iid)
    K = D['kilit']
    # upgradeLevel gösterilen seviye (1-20): Restabilize listesi onu olduğu gibi yazar (0'sa gizler), Upgrade sekmesi envanterdekinin
    # bir fazlasını; önce 0'dan gidiyordu, iki sekme farklı seviye gösteriyordu (canlı test H63). Yuvaların açıklığı attributes'tan
    return mod('LockAttributeItemModule', upgradeLevel=level(p, iid), lockCostLootAmounts=K['kilit'], lockCostLoot=K['lock_item'],
               restabilizeCostLootAmounts=K['yenileme'], restabilizeCostLoot=K['renewal_item'], lootId=loot,
               lockAttributeLevels=K['seviyeler'],
               attributes=attr_mods(st), itemId=int(iid))


def lock_list_cmd(p):
    ids = [int(i) for i, l in sorted(p.d['esyalar'].items(), key=lambda x: int(x[0])) if l in DRIVES or l in LENSES]
    return 'LockAttributeItemListCommand', {'remove': False, 'moduleList': [lock_module(p, i) for i in ids]}


def lock_reroll(p, iid, locks, rng=random):
    """Kilitlenmeyen alt nitelikler yeniden (Horizon Shard; kilit başına Containment Node) -> True/False."""
    loot = p.d['esyalar'].get(str(iid), '')
    st = ensure(p, iid)
    if not st or (loot not in DRIVES and loot not in LENSES) or not st['nitelik']:
        return False
    locks = sorted({int(i) for i in locks or [] if 0 <= int(i) < len(st['nitelik'])})
    if len(locks) >= len(st['nitelik']):
        return False
    K = D['kilit']
    k = min(len(locks), len(K['yenileme']) - 1)
    need = {K['renewal_item']: K['yenileme'][k]}
    if K['kilit'][min(len(locks), len(K['kilit']) - 1)]:
        need[K['lock_item']] = K['kilit'][min(len(locks), len(K['kilit']) - 1)]
    if INV.spend(p, need, 'buy_SPECIAL', 'drive_refine') is None:
        return False
    pl = D['nitelikler']['surucu']
    keep = {st['nitelik'][i][0] for i in locks}
    with p.lock:
        for i, (a, v) in enumerate(list(st['nitelik'])):
            if i in locks:
                continue
            free = [x for x in sorted(pl) if not x.startswith('_') and x not in keep]
            b = rng.choice(free)
            keep.add(b)
            st['nitelik'][i] = [b, round(rng.uniform(*pl[b]), 2)]
        p.dirty = True
    return True


# ---------------------------------------------------------------- uçuş
def drive_power(p, ids):
    """Takılı sürücülerin toplam hasarı (seviye, alt nitelik, set çarpanı), alan yarıçapı (Apex ve Prime seti) ve en iyi sürücünün
    görsel kademesi."""
    rows = [(i, p.d['esyalar'][str(i)]) for i in ids]
    big = [l for i, l in rows if DRIVES[l]['atis'] >= 2]
    mult, area = 1.0, DR['alan']
    for n, m, r in DR['set']:
        if len(big) >= n:
            mult, area = m, r
    total = 0.0
    for i, l in rows:
        a = attrs(p, i)
        d = DRIVES[l]['hasar'] * (1 + 0.005 * (level(p, i) - 1)) * (1 + (a.get('drive_damage', 0) + a.get('drive_damage_npc', 0)) / 100.0)
        total += d * (mult if DRIVES[l]['atis'] >= 2 else 1.0)
    return total, area, max((DRIVES[l]['atis'] for i, l in rows), default=1)


class Shot:
    """Dünyanın parçacık topu ve sürücü atışları (dünya kilidi altında çağrılır)."""

    def __init__(self, world):
        self.w, self.p = world, world.p
        self.zones = []                # [{x, y, bitis, sonraki, hasar, hedef, vm}]
        self.corrosive = {}              # npc id -> [kat, bitiş]
        with self.p.lock:
            sel = self.p.d.setdefault('secili', {})
            sel.setdefault('slug', 'ammunition_slug_ths-d01')
            sel.setdefault('gsp', 'ammunition_spool_gsp-30')

    def ready(self, group, now):
        import combat_items as CIT
        return now >= CIT.ready_at(self.p, group)

    def cool(self, group, sec, now):
        import combat_items as CIT
        sec *= SET.multiplier('yetenek_bekleme', 'parcacik')     # panel: yetenek ve eşya beklemeleri (top ve sürücü de)
        with self.p.lock:
            self.p.d.setdefault(CIT.TIMERS, {})[str(group)] = [now + sec, int(sec * 1000)]
            self.p.dirty = True
        ms = int(sec * 1000)
        self.w.send([CIT.timer_msg(group, ms)])
        self.w.later(sec, lambda: self.w.send([CIT.timer_msg(group, ms, cooling=False)]))

    def menu(self, item, act, now=None):
        """Kısayol çubuğu: slug ya da GSP seçilir ve hedef varsa ateşlenir."""
        now = now or time.time()
        kind = 'slug' if item in SLUGS else 'gsp'
        if act not in (0, 1):
            return
        old = self.p.d['secili'].get(kind)
        if item != old and self.p.ammo(item) > 0:
            self.p.d['secili'][kind] = item
            self.p.dirty = True
            self.w.send([('MenuItemStatusCommand', st) for st in (self.p.menu_status(old) if old else None, self.p.menu_status(item)) if st])
            self.w.log('   %s seçildi: %s' % ('slug' if kind == 'slug' else 'GSP', item))
        if act == 0:
            return  # Category SELECT chooses ammo without firing a cannon/drive.
        n = self.w.npcs.get(self.w.target)
        if n and n.alive:
            (self.fire_cannon if kind == 'slug' else self.fire_drive)(n, now, item)

    def auto(self, n, now):
        """Lazer saldırısında: RG-SL seçili slug'ı, AGS-X seçili GSP'yi kendiliğinden ateşler."""
        import combat_items as CIT
        if CIT.toggled(self.p, CPU_CANNON) and self.ready(COOLDOWN_CANNON, now):
            self.fire_cannon(n, now, self.p.d['secili'].get('slug'), auto=True)
        if CIT.toggled(self.p, CPU_DRIVE) and self.ready(COOLDOWN_DRIVE, now):
            self.fire_drive(n, now, self.p.d['secili'].get('gsp'), auto=True)

    def in_range(self, n, now, rng):
        hx, hy = self.w.hero_pos(now)
        nx, ny = n.mover.pos(now)
        return math.hypot(nx - hx, ny - hy) <= rng

    def others(self, x, y, radius, skip, now):
        out = []
        for m in self.w.npcs.values():
            if m.alive and m.id not in skip and not m.d.get('dost'):
                mx, my = m.mover.pos(now)
                d = math.hypot(mx - x, my - y)
                if d <= radius:
                    out.append((d, m))
        return [m for d, m in sorted(out, key=lambda x: x[0])]

    # ------------------------------------------------------------ top
    def fire_cannon(self, n, now, slug, auto=False):
        w, p = self.w, self.p
        if not slug or slug not in SLUGS or w.hero_dead or w.jumping:
            return False
        element = SLUGS[slug]['element']
        iid = cannon_for(p, element)
        why = None
        if iid is None:
            why = 'takılı %s topu yok' % element
        elif not self.ready(COOLDOWN_CANNON, now):
            why = 'bekleme'
        elif p.ammo(slug) <= 0:
            why = 'slug yok'
        elif w.in_peace(*w.hero_pos(now)):
            why = 'güvenli bölge'
        elif not self.in_range(n, now, C['menzil']):
            why = 'menzil dışı'
        if why:
            if not auto:
                w.log('   top ateşlenmedi (%s): %s' % (slug, why))
            return False
        p.use_ammo(slug, 1)
        loot = p.d['esyalar'][str(iid)]
        row = CANNONS[loot]
        a = attrs(p, iid)
        e = row['element']
        self.cool(COOLDOWN_CANNON, C['aralik_sn'] * max(0.1, 1 + p.mods().get('top_bekleme', 0)), now)    # Supercharge Plus -%50
        w.last_combat = now
        hit = random.random() < C['isabet'] * (1 + a.get('cannon_hit_chance_' + e, 0) / 100.0 + p.mods().get('cannon_hit', 0))   # Lepus
        msgs = w.ammo_msgs(slug) + [('CannonAttackCommand', dict(cannonType=row['cannonType'], hit=hit, attackerId=w.hid, attackedId=n.id))]
        w.send(msgs)
        p.ach('shot', silah='CANNON')
        if not hit:
            from world import attack_type
            w.send([('AttackMissedCommand', dict(attackType=attack_type(CANNON_ATTACK), targetUserId=n.id, skillColorId=0))])
            return True
        dmg = base_damage(p, iid, p.ship()['lootId']) * (1 + 0.005 * (level(p, iid) - 1)) * SLUGS[slug]['carpan']
        dmg *= random.uniform(*C['hasar_araligi']) * (1 + (a.get(DMG_KEY[e], 0) + a.get('cannon_damage_npc_' + e, 0) + shield_npc(p, e)) / 100.0)
        dmg *= 1 + p.mods().get('top', 0)
        crit = random.random() < C['kritik'] + a.get('cannon_strike_' + e, 0) / 100.0
        if crit:
            dmg *= 1 + C['crit_damage'] + a.get('cannon_strike_damage_' + e, 0) / 100.0
        dmg = int(dmg)
        nx, ny = n.mover.pos(now)
        w.hit_npc(n.id, dmg, CANNON_ATTACK, strike=crit, cannon=row['cannonType'])
        if e == 'thermal':                                       # Helios: sıçrama
            S = C['splash']
            near = self.others(nx, ny, S['yaricap'], {n.id}, now)[:S['hedef']]
            if near:
                w.send([('PlayVisualEffectCommand', dict(activatorId=n.id, targetIds=[m.id for m in near], visualEffect=VE_THERMAL))])
                for m in near:
                    w.hit_npc(m.id, int(dmg * S['oran']), CANNON_ATTACK, cannon=row['cannonType'])
        elif e == 'corrosive':                                   # Nidhogg: aşındırma zaafı
            A = C['abrasion']
            k = self.corrosive.get(n.id, [0, 0])
            k = [min(A['multiplier'], (k[0] if k[1] > now else 0) + 1), now + A['sn']]
            self.corrosive[n.id] = k
            if n.alive:
                w.send([('VisualModifierCommand', dict(userId=n.id, modifier=VM_CORROSIVE, attribute=k[0], additionalAttribute='',
                                                       count=k[0], activated=True))])
        elif e == 'electro':                                     # Indra: zincir
            Z = C['zincir']
            chain, seen, x, y, d = [], {n.id}, nx, ny, dmg
            while len(chain) < Z['hedef'] - 1:
                nxt = self.others(x, y, Z['yaricap'], seen, now)
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
        return k[0] * C['abrasion']['oran'] if k and k[1] > now else 0.0

    # ------------------------------------------------------------ sürücü
    def fire_drive(self, n, now, gsp, auto=False):
        w, p = self.w, self.p
        if not gsp or gsp not in GSP or w.hero_dead or w.jumping:
            return False
        ids = equipped(p, 'drive')
        power, area, best = drive_power(p, ids) if ids else (0, DR['alan'], 1)
        why = None
        if not ids:
            why = 'takılı sürücü yok'
        elif not self.ready(COOLDOWN_DRIVE, now):
            why = 'bekleme'
        elif p.ammo(gsp) < len(ids):
            why = 'GSP yetmiyor'
        elif w.in_peace(*w.hero_pos(now)):
            why = 'güvenli bölge'
        elif not self.in_range(n, now, DR['menzil']):
            why = 'menzil dışı'
        if why:
            if not auto:
                w.log('   sürücü ateşlenmedi (%s): %s' % (gsp, why))
            return False
        p.use_ammo(gsp, len(ids))
        self.cool(COOLDOWN_DRIVE, DR['bekleme_sn'], now)
        w.last_combat = now
        shot, vm = DR['effect'][str(best)]
        x, y = n.mover.pos(now)
        import ship_ability as SA
        bonus = SA.take(p, 'sonraki_gsp')                 # Hyperion Quantum Amplifier: bu atışa +%10
        zone = self.resonate({'x': x, 'y': y, 'bitis': now + DR['sure_sn'], 'next': now, 'hasar': power * GSP[gsp] * (1 + bonus), 'hedef': n.id,
                              'vm': vm, 'alan': area}, now)
        self.zones.append(zone)
        w.send(w.ammo_msgs(gsp) + [('PlayVisualEffectCommand', dict(activatorId=w.hid, targetIds=[n.id], visualEffect=shot)),
                                   ('VisualModifierCommand', dict(userId=n.id, modifier=vm, attribute=0, additionalAttribute='', count=0,
                                                                  activated=True))])
        p.ach('shot', silah='DRIVE')
        self.zone_tick(zone, now)
        return True

    def resonate(self, z, now):
        """En iyi Strike Resonator'ın nitelikleri (resonator.py, Ö6): yarıçap, süre, toplam hasar, artçı patlama, yavaşlatma,
        ana hedefi izleme. Hasar saniyelik: toplam hasar (süre x saniyelik) çarpanla korunur."""
        import resonator as RS
        a = RS.strike_mods(self.p)
        if not a:
            return z
        duration, total = float(DR['sure_sn']), 1.0
        if 'collapse' in a:
            duration, total = duration * 0.75, total * (1 + a['collapse'] / 100.0)
        elif 'evernight' in a:
            duration, total = duration * 1.25, total * (1 + a['evernight'] / 100.0)
        per = z['hasar'] * total * DR['sure_sn'] / duration
        z.update(bitis=now + duration, hasar=per, alan=z['alan'] * (1 + a.get('expansion', 0) / 100.0), rezonator=a)
        if 'aftershock' in a:                       # %75 alan süresince, %25 bitişte (yarıçap +x)
            z['aftershock_dmg'] = per * 0.25 * duration
            z['hasar'] = per * 0.75
            z['aftershock_area'] = z['alan'] * (1 + a['aftershock'] / 100.0)
        if 'stagnation' in a:
            z['yavas'] = a['stagnation'] / 100.0
        if 'adhesion' in a:
            z['follow'] = now + min(a['adhesion'], duration)
        return z

    def zone_tick(self, z, now):
        if now < z['next'] or self.w.hero_dead:
            return
        zones = self.zones
        z['next'] = now + 1.0
        t = self.w.npcs.get(z['hedef'])
        if z.get('follow', 0) > now and t is not None and t.alive:       # Adhesion: alan ana hedefle gider
            z['x'], z['y'] = t.mover.pos(now)
        for m in self.others(z['x'], z['y'], z.get('alan', DR['alan']), set(), now):
            if self.w.hero_dead or self.zones is not zones:
                break                                   # a hit can kill the hero or stop the world and clear all zones
            if z.get('yavas'):                                          # Stagnation: alandayken yavaş (çıkınca 1,2 sn'de biter)
                self.w.npc_effect(m, 'yavas', 1.2, z['yavas'], source='rezonator')
            if random.random() < DR['isabet']:
                self.w.hit_npc(m.id, int(z['hasar']), DRIVE_ATTACK)

    @staticmethod
    def zone_end(z):
        return ('VisualModifierCommand', dict(userId=z['hedef'], modifier=z['vm'], attribute=0,
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
                if now >= z['bitis']:
                    self.zones.remove(z)
                    if z.get('aftershock_dmg'):                                  # Aftershock: kalan %25 bitişte patlar
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
