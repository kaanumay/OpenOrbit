"""Eşya yükseltmeleri ve Disassembly (yol haritası Aşama 6; veri data/client_items.json <- tools/il2cpp/client_data.py).

İstemcinin kendi verisi: 17 yükseltme sınıfı (upgrade_upgrade-class0 … class10, drone, cbs) ve 8 Disassembly sınıfı; her sınıfın
eşyaları ve seviye seviye süre ve maliyeti (ABR, kredi/uridyum, kimi seviyede Diametrion, Indoctrine Oil/Accelerator). Eşyanın
"upgradable" özelliği seviye başına bonusu verir (LF-3 hasarı %0,5, SG3N-B02 kalkanı %1, Iris'in kalkanı %1 ve hasarı %0,4 …).
Seviye protokolde 0'dan başlar (istemci 1 gösterir; kayıttaki bütün eşyalar upgradeLevel 0); en çok sınıfın seviye sayısı (16 ya
da 20 gösterilir). Bonus = seviye x yüzde (LINEAR_CALCULATION).

Assembly penceresi (kayıttaki AssemblyRecipeContentModule'de 17 upgrade_ ve 8 disassemble_ tarifi; istekler istemcinin kodundan):
  AssemblyBuildRequest {recipeLootId upgrade_…, targetItemId (eşya ya da dron kimliği), amount (hedef seviye, 0'dan)}: maliyetler
      harcanır, süre işler -> AssemblyRecipeStatusUpdateCommand {targetItemId, Build (buildAmount da hedef seviye)}
  AssemblyCollectRequest / CollectAll / Skip {recipeLootId, targetItemId}: süre bitince seviye artar (InventoryItemModule.upgradeLevel;
      dronda SingleDroneEquipmentMsg damage/shieldUpgradeLevel), takılıysa hasar/kalkan yeniden hesaplanır
  DisassemblyRequest {recipeLootId disassemble_…, itemId}: yükseltilmiş, takılı olmayan eşya sökülür; seviyesinin satırındaki ücret
      ödenir, eksi adetler geri verilir (istemcinin metni: "Do you want to disassemble this item?" / "You cannot disassemble an
      equipped item.")
Profilde: yukseltme_seviye {itemId: seviye}; dronda kayıt alanı "yukseltme"; süren yükseltmeler assembly.yukseltme {"tarif|hedef": …}.
Upgrade Hour (items.json yukseltme_saati): o saatte yükseltmelerin uridyum maliyeti %25 az; başlayınca HUD iletisi.
Eski yükseltme sistemi (panel: eski_yukseltme, kullanıcı isteği 2026-10-31): 2013-2019'un Skylab > Tech Factory > Item Upgrading'i
Unity istemcisinde yok (yalnız metinleri kalmış: resource_itemUpgradeSystem); Assembly'nin Upgrade sekmesi aynı yükseltmeleri yalnız
uridyumla yapar. Fiyat: eski sistemin %100 başarı şanslı bedeli (board-en "Upgrading Cost Charts", konu 12614: seviye 2'ye 3.905,
her seviye +435, 16'ya toplam 104.250 U.; bütün uridyum eşyaları aynı), 17-20 aynı artışla. Eskiden kredili eşyalar (class0: LF-1,
MP-1, SG3N-A01, Flax) dörtte bir (bugünkü ABR'leri class2'nin ~1/4'ü); CBS modülleri eski toplamlarıyla (iç modüller Hull/Deflector
402.750, dış modüller 268.500). Çarpan: eski_yukseltme_fiyat. İstemci bedeli kendi tarifinden gösterir: panel eski_tablo()'yu
istemcinin BepInEx/openorbit/eski_yukseltme.json'una yazar, eklentinin EskiYukseltme yaması tarifleri uridyuma çevirir.
"""
import datetime, json, os, time

import inventory as INV
import settings as SET
import event_calendar as CAL
import ranks as RT

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'client_items.json'), encoding='utf8'))
UP, DIS, ITEMS = D['yukseltmeler'], D['disassembly'], D['esyalar']
INGREDIENTS = {loot for groups in (UP, DIS) for recipe in groups.values() for level in recipe['seviyeler']
               for costs in (level.get('maliyet', {}), level.get('atla', {})) for loot in costs}
UP_OF = {loot: k for k, c in UP.items() for loot in c['esyalar']}
DIS_OF = {loot: k for k, c in DIS.items() for loot in c['esyalar']}
HOUR = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))['yukseltme_saati']
LASER, SHIELD, ROCKET = 'LASER_DAMAGE_UPGRADE', 'GENERATOR_SHIELD_UPGRADE', 'ROCKETLAUNCHER_DAMAGE_UPGRADE'
DRONE_DAMAGE, DRONE_SHIELD = 'DRONE_DAMAGE_UPGRADE', 'DRONE_SHIELD_UPGRADE'
# hangar eşyasının seviye rozeti (HangarShipEquipmentInventoryItem.UpgradeLevel, "anahtar,gösterilen seviye"): istemci
# (UINewHangarSystem.SetTypeIdentification) rozeti listede satır varken açar, yazıyı TooltipPreparerFactory.ReturnItemLevelNum'dan
# alır (bu sıradaki anahtarlardan değeri 1'den büyük ilki); ipucunda "Damage level" / "Shield level". Liste boşken level alanı
# rozeti açmıyor: yükseltilmiş eşyalar seviyesiz görünüyordu
BADGE = {LASER: 'damageUpgradeLevel', ROCKET: 'damageUpgradeLevel', SHIELD: 'shieldUpgradeLevel',
         'CANNON_DAMAGE_UPGRADE': 'cannonDamageUpgradeLevel', 'CANNON_DEF_UPGRADE': 'cannonDefUpgradeLevel',
         'DRIVE_DAMAGE_UPGRADE': 'driveDamageUpgradeLevel', 'DRIVE_DEF_UPGRADE': 'driveDefUpgradeLevel'}


OLD_FIRST, OLD_INCREASE = 3905, 435
OLD_RATIO = {'upgrade_upgrade-class0': 0.25, 'upgrade_upgrade-class0-drone': 0.25,
             'upgrade_upgrade-class3-cbs': 268500 / 104250.0, 'upgrade_upgrade-class4-cbs': 402750 / 104250.0}


def legacy_table(is_open=None, multiplier=None):
    """Eski sistemin seviye seviye uridyum bedeli {sınıf: [satır başına U.]} (kapalıysa {}); panel istemciye de yazar."""
    if not (SET.get('eski_yukseltme') if is_open is None else is_open):
        return {}
    m = SET.multiplier('eski_yukseltme_fiyat') if multiplier is None else multiplier
    return {k: [int(round((OLD_FIRST + OLD_INCREASE * i) * OLD_RATIO.get(k, 1.0) * m)) for i in range(len(c['seviyeler']))]
            for k, c in UP.items()}


def row_cost(key, i):
    """Yükseltme sınıfının i. satırının (0'dan) bedeli: eski sistem açıksa yalnız uridyum, değilse istemcinin malzemeleri."""
    if SET.get('eski_yukseltme'):
        n = legacy_table()[key][i]
        return {'currency_uridium': n} if n > 0 else {}
    return {loot: a for loot, a in UP[key]['seviyeler'][i]['maliyet'].items() if a > 0}


def mod(name, **f):
    f['_'] = name
    return f


def max_level(loot):
    k = UP_OF.get(loot)
    return len(UP[k]['seviyeler']) if k else 0


def item_level(p, iid):
    return int(p.d.get('yukseltme_seviye', {}).get(str(iid), 0))


def badge(loot, level):
    """Hangar rozetinin satırları: yükseltilmişse eşyanın her bonus türü için "anahtar,seviye + 1" (istemcide 1. seviye rozetsiz)."""
    return ['%s,%d' % (BADGE[u['tur']], level + 1) for u in ITEMS.get(loot, {}).get('yukseltme', []) if u['tur'] in BADGE] if level else []


def spent(p, iid):
    """Eşyanın yükseltmelerine harcanan malzeme (geri dönüşüm ve Synthesis iadesi; Upgrade Hour indirimi sayılmaz)."""
    k = UP_OF.get(p.d['esyalar'].get(str(iid), ''))
    out = {}
    for i in range(item_level(p, iid) if k else 0):
        for loot, a in row_cost(k, i).items():
            out[loot] = out.get(loot, 0) + a
    return out


def factor(loot, level, kind):
    """Yükseltme bonusu çarpanı: 1 + seviye x yüzde (eşyanın o türden bonusu yoksa 1)."""
    if not level:
        return 1.0
    for u in ITEMS.get(loot, {}).get('yukseltme', []):
        if u['tur'] == kind:
            return 1 + level * u['yuzde'] / 100.0
    return 1.0


def drone_level(x):
    return int(x.get('yukseltme', 0))


def bonus_hour(now=None):
    """Upgrade Hour sürüyorsa uridyum indirimi (0,25), yoksa 0 (event_calendar.py: yukseltme_saati, yerel saatle)."""
    return HOUR['indirim'] if CAL.is_active('yukseltme_saati', now) else 0.0


class Upgrade:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                 # mağaza (envanter/para güncellemesi, hız/kalkan; oturum bağlar)
        self.send = None
        self.refresh = None           # Assembly'nin tarif listesi (süre bitince panel yeniden çizilsin; H61)
        self.hour_on = bool(bonus_hour())
        self.old = self.old_key()       # eski sistemin ayarları değişince tarif listesi yeniden (tick)
        self.old_at = None

    @property
    def st(self):
        return self.p.d.setdefault('assembly', {}).setdefault('yukseltme', {})

    # ------------------------------------------------------------ hedefler
    def target(self, key, tid):
        """(tür, lootId, kayıt) ya da None: eşya ('esya', loot, iid) ya da dron ('dron', loot, kayıt)."""
        loot = self.p.d['esyalar'].get(str(tid))
        if loot:
            return 'esya', loot, int(tid)
        x = next((d for d in self.p.d.get('dronlar', []) if d['kimlik'] == int(tid or 0)), None)
        if x and '-drone' in key:
            return 'dron', x['lootId'], x
        cbs = getattr(self.m, 'cbs', None)
        m = cbs.st['moduller'].get(str(tid)) if cbs and '-cbs' in key and not cbs.where(tid) else None
        if m:
            return 'modul', m['loot'], (int(tid), m)          # Clan Battle Station modülü (takılı değilken; magaza.module_items)
        return None

    def level_of(self, kind, ref):
        if kind == 'modul':
            return int(ref[1].get('seviye', 0))
        return drone_level(ref) if kind == 'dron' else item_level(self.p, ref)

    def set_level(self, kind, ref, n):
        with self.p.lock:
            if kind == 'dron':
                ref['yukseltme'] = n
            elif kind == 'modul':                       # can ve kalkan yeni seviyenin azamisine (cbs.mx)
                ref[1]['seviye'] = n
                ref[1]['can'], ref[1]['kalkan'] = self.m.cbs.mx(ref[1])
            else:
                self.p.d.setdefault('yukseltme_seviye', {})[str(ref)] = n
            self.p.dirty = True

    # ------------------------------------------------------------ pencere
    def status(self, key, tid, now=None):
        now = now or time.time()
        b = self.st.get('%s|%d' % (key, int(tid or 0)))
        if b:
            if now < b['bitis']:
                return mod('AssemblyRecipeBuildStatusModule', buildAmount=b['seviye'], remainingTimeMillis=int((b['bitis'] - now) * 1000),
                           prevBuildCount=0)
            return mod('AssemblyRecipeReadyToCollectStatusModule', prevBuildCount=0, buildAmount=b['seviye'])
        return mod('AssemblyRecipeAvailableStatusModule', currentBuildCount=0, isNew=False)

    def update(self, key, tid=0, now=None):
        return ('AssemblyRecipeStatusUpdateCommand', dict(targetItemId=int(tid or 0), status=self.status(key, tid, now), lootId=key))

    def recipes(self, now=None):
        """Girişteki listeye: her sınıf bir kez (hedefsiz) ve süren/hazır yükseltmeler hedefleriyle."""
        out = [mod('AssemblyRecipeModule', recipeLootId=k, targetItemId=0, type=mod('AssemblyRecipeRegularTypeModule'),
                   status=self.status(k, 0, now)) for k in list(UP) + list(DIS)]
        for key_type in sorted(self.st):
            k, t = key_type.split('|')
            out.append(mod('AssemblyRecipeModule', recipeLootId=k, targetItemId=int(t), type=mod('AssemblyRecipeRegularTypeModule'),
                           status=self.status(k, t, now)))
        return out

    # ------------------------------------------------------------ yükseltme
    def cost(self, key, cur, n, now=None):
        """cur seviyesinden n seviye: maliyetlerin toplamı ve süre (Upgrade Hour'da uridyum %25, Premium'da %5 az; eski sistemde
        yalnız uridyum)."""
        rows = UP[key]['seviyeler'][cur:cur + n]
        need = {}
        for i in range(cur, cur + len(rows)):
            for loot, a in row_cost(key, i).items():
                need[loot] = need.get(loot, 0) + a
        # indirimler istemcinin hesabıyla (DiscountComponentSystem.GetAmountWithDiscount; canlı 2026-11-01): Upgrade Hour ve
        # UserInventoryModule.activePremiumDiscount (Premium %5 + Shop Discount, magaza.discount) toplanır, uridyum aşağı yuvarlanır,
        # kredi indirimsiz (LF-3 316 U. -> Premium 300, + Upgrade Hour 221). Önce yalnız Upgrade Hour, yukarı yuvarlanarak alınıyordu:
        # pencere Premium'la 300 gösterirken 316 alınıyordu
        pct = int(round((bonus_hour(now) + (self.m.discount() if self.m else 0.0)) * 100))
        if pct and need.get('currency_uridium'):
            need['currency_uridium'] = need['currency_uridium'] * max(0, 100 - pct) // 100
        return {} if SET.get('assembly_ucretsiz') else need, SET.duration(sum(r['sure_sn'] for r in rows), 'yukseltme')            # panel: bekleme

    def build(self, f, now=None):
        now = now or time.time()
        key, tid = f.get('recipeLootId', ''), int(f.get('targetItemId') or 0)
        t = self.target(key, tid)
        if key not in UP or not t or t[1] not in UP[key]['esyalar']:
            self.log('   yükseltme yok: %s hedef %s' % (key, tid))
            return [self.update(key, tid, now)] if key in UP else []
        kind, loot, ref = t
        if '%s|%d' % (key, tid) in self.st:
            return [self.update(key, tid, now)]
        cur = self.level_of(kind, ref)
        if cur >= len(UP[key]['seviyeler']):
            self.log('   yükseltme: %s en üst seviyede' % loot)
            return [self.update(key, tid, now)]
        # amount hedef seviye (0'dan): istemci sayaçtaki seviyenin bir eksiğini gönderir (UpgradeViewSystem/UISingularityDriveSystem
        # .HandleBuildClicked) ve süren yükseltmenin buildAmount'unu da hedef sayar (CollectSteps(şimdiki, buildAmount)). Önce adet
        # sanılıyordu: 0'dan başlayınca aynı, sonra fazla seviye, süre ve bedel çıkıyordu (canlı test H60)
        target = min(int(f.get('amount') if f.get('amount') is not None else cur + 1), len(UP[key]['seviyeler']))
        n = target - cur
        if n < 1:
            self.log('   yükseltme: hedef seviye %d şimdikinden (%d) büyük değil (%s)' % (target, cur, loot))
            return [self.update(key, tid, now)]
        need, secs = self.cost(key, cur, n, now)
        miss = INV.missing(self.p, need)
        if miss:
            self.log('   yükseltme: malzeme yetmiyor %s (eksik %s)' % (loot, miss))
            return [self.update(key, tid, now)]
        removed = INV.spend(self.p, need, reason='buy_SPECIAL', detail=key)
        with self.p.lock:
            self.st['%s|%d' % (key, tid)] = dict(adet=n, bitis=now + secs, hedef=tid, seviye=cur + n)
            self.p.dirty = True
        self.log('   yükseltme başladı: %s %d -> %d (%d sn, %s)' % (loot, cur, cur + n, secs, need))
        return INV.update_msgs(self.m, self.p, list(need), removed) + [self.update(key, tid, now)]

    def collect(self, f, now=None):
        now = now or time.time()
        key = f.get('recipeLootId') or f.get('lootId') or ''
        tid = int(f.get('targetItemId') or f.get('targetId') or 0)
        b = self.st.get('%s|%d' % (key, tid))
        if not b or now < b['bitis']:
            return [self.update(key, tid, now)] if key in UP else []
        t = self.target(key, tid)
        with self.p.lock:
            del self.st['%s|%d' % (key, tid)]
            self.p.dirty = True
        if not t:
            return [self.update(key, tid, now)]
        kind, loot, ref = t
        self.set_level(kind, ref, b['seviye'])
        self.p.ach('upgrade', esya=loot, seviye=b['seviye'])
        RT.note(self.p, 'upgraded_item', loot, b['seviye'])     # seyir defteri: log_message_upgrade_finished (%item% info'dan, %level%)
        self.log('   yükseltme bitti: %s seviye %d' % (loot, b['seviye']))
        return self.item_msgs(kind, loot, ref) + [self.update(key, tid, now)]

    def item_msgs(self, kind, loot, ref):
        """Seviyesi değişen eşya/dron: envanter ve hangar güncellemesi, takılıysa hız/kalkan/hasar."""
        if not self.m:
            return []
        self.p.sync_equipment()
        if kind == 'dron':
            return [self.m.drone_item(ref), self.m.equipment_cmd()] + self.m.apply_stats()     # Assembly'deki seviyesi de
        if kind == 'modul':
            return [self.m.module_item(*ref)]
        hm = self.p.hangar_map()
        msgs = [self.m.inv_item(ref, loot, 1, hm.get(ref, 0)), self.m.pack([self.m.hangar_item(ref, loot, 1, hm.get(ref, 0))])]
        import particle as PC
        if PC.restabilizable(loot):
            import ship_module as GM
            msgs.append(GM.list_cmd(self.p))               # topun seviyesi ve yükseltme iadesi Restabilize'da (H70)
        if loot in PC.DRIVES or loot in PC.LENSES:
            # 5/10/15/20. seviyede alt nitelik açılır: Update penceresinin Stats yuvaları listeden (canlı test H62: seviye 5'te yuva
            # "LV: 5 Unlock" kalıyordu, nitelik ancak sonraki girişte geliyordu)
            msgs.append(PC.lock_list_cmd(self.p))
        if ref in hm:
            msgs += [self.m.equipment_cmd()] + self.m.apply_stats()
        return msgs

    def skip_cost(self, key, b, now=None):
        """Süreyi atlama bedeli: seviyelerin atla toplamı (istemcinin verisi, Isochronate) x kalan süre oranı, yuvarlanmış. İstemci
        (TargetItemRecipeModel.GetSkipIngredients, UpgradeSkipListItem.UpdatePercentage) aynı hesapla gösterir; önce kalan dakika
        başına 1 uridyum alınıyordu, pencere ise Isochronate gösteriyordu (canlı test H58)."""
        now = time.time() if now is None else now
        rows = UP[key]['seviyeler'][b['seviye'] - b['adet']:b['seviye']]
        total = SET.duration(sum(r['sure_sn'] for r in rows), 'yukseltme') or 1
        frac = min(1.0, max(0.0, (b['bitis'] - now) / total))
        need = {}
        for r in rows:
            for loot, a in r.get('atla', {}).items():
                need[loot] = need.get(loot, 0) + a
        return {} if SET.get('assembly_ucretsiz') else {loot: max(1, int(a * frac + 0.5)) for loot, a in need.items()}

    def skip(self, f, now=None):
        now = now or time.time()
        key, tid = f.get('recipeLootId', ''), int(f.get('targetItemId') or 0)
        b = self.st.get('%s|%d' % (key, tid))
        if not b or now >= b['bitis']:
            return [self.update(key, tid, now)] if key in UP else []
        need = self.skip_cost(key, b, now)
        miss = INV.missing(self.p, need)
        if miss:
            self.log('   yükseltme atlanamadı: %s eksik %s' % (key, miss))
            return [self.update(key, tid, now)]
        removed = INV.spend(self.p, need, reason='buy_SPECIAL', detail=key)
        with self.p.lock:
            b['bitis'] = now
            self.p.dirty = True
        self.log('   yükseltme atlandı: %s hedef %d (%s)' % (key, tid, need))
        return INV.update_msgs(self.m, self.p, list(need), removed) + [self.update(key, tid, now)]

    # ------------------------------------------------------------ Disassembly
    def disassemble(self, f, now=None):
        key, iid = f.get('recipeLootId', ''), int(f.get('itemId') or 0)
        loot = self.p.d['esyalar'].get(str(iid))
        if key not in DIS or not loot or loot not in DIS[key]['esyalar']:
            self.log('   Disassembly yok: %s eşya %s' % (key, iid))
            return [self.update(key, iid)] if key in DIS else []
        if any(k.endswith('|%d' % iid) and (now or time.time()) < b['bitis'] for k, b in self.st.items()):
            self.log('   Disassembly yok: eşya %s yükseltiliyor' % iid)               # forum 150401
            return [self.update(key, iid)]
        if iid in self.p.equipped_ids():
            from legacy_protocol import legacy
            return [legacy('0|A|STM|msg_cannot_disassemble_equipped_item'), self.update(key, iid)]
        lv = item_level(self.p, iid)
        row = next((r for r in DIS[key]['seviyeler'] if r['seviye'] == lv), None)
        if not row:
            self.log('   Disassembly: %s seviye %d sökülmez' % (loot, lv))
            return [self.update(key, iid)]
        fee = {} if SET.get('assembly_ucretsiz') else {l: a for l, a in row['maliyet'].items() if a > 0}
        back = {l: -a for l, a in row['maliyet'].items() if a < 0}
        if INV.missing(self.p, fee):
            self.log('   Disassembly: ücret yetmiyor %s' % fee)
            return [self.update(key, iid)]
        INV.spend(self.p, fee, reason='buy_SPECIAL', detail=key)
        with self.p.lock:
            del self.p.d['esyalar'][str(iid)]
            self.p.d.get('yukseltme_seviye', {}).pop(str(iid), None)
            self.p.d.get('esya_seviye', {}).pop(str(iid), None)
            self.p.dirty = True
        msgs = INV.update_msgs(self.m, self.p, list(fee), [iid])
        for l, n in back.items():
            msgs += self.m.reward(l, n) if self.m else []
            if not self.m:
                self.p.add_resource(l, n)
        self.log('   Disassembly: %s (seviye %d) söküldü, ücret %s, geri %s' % (loot, lv, fee, back))
        RT.note(self.p, 'disassembled_item', loot, lv)          # seyir defteri: log_message_disassembly_finished (%item% info'dan)
        return msgs + [self.update(key, iid)]

    # ------------------------------------------------------------ istekler
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
        """İstemcinin yükseltme bedellerindeki indirim (UserInventoryModule.activeHappyUpgradeDiscount, yüzde; istemci
        DiscountComponentSystem.UpdateFromServer): yoksa pencere tam uridyumu gösteriyor, sunucu %25 az alıyordu (canlı test H40).
        Modül envanter listesini de taşıyor: istemcinin eşya sayaçları silinmesin diye tam liste (mağazanın giriş sayaçları)."""
        if not self.m:
            return []
        items = [f['item'] for n, f in self.m.count_msgs()]
        return [('UserInventoryModule', dict(activePremiumDiscount=int(round(self.m.discount() * 100)),
                                             activeRebateSubDiscount=0, inventoryItemModules=items,
                                             activeHappyUpgradeDiscount=int(round(bonus_hour(now) * 100))))]

    @staticmethod
    def old_key():
        return bool(SET.get('eski_yukseltme')), SET.multiplier('eski_yukseltme_fiyat')

    def tick(self, now):
        # Eski sistem oyun açıkken açılıp kapanınca ya da fiyatı değişince: istemcinin tarif modelleri bedeli önbellekler (açıktan
        # kapalıya geçişte pencere uridyumu göstermeyi sürdürüyordu, canlı 2026-11-01); tarif listesi yeniden gönderilince modeller
        # yeniden kurulur. 2 sn sonra: eklenti panelin yazdığı bedel dosyasına en çok saniyede bir bakar
        k = self.old_key()
        if k != self.old:
            self.old, self.old_at = k, now + 2.0
        if self.old_at and now >= self.old_at:
            self.old_at = None
            self.log('   eski yükseltme sistemi: %s, fiyat x%g' % ('açık' if k[0] else 'kapalı', k[1]))
            if self.send and self.refresh:
                self.send([self.refresh()])
        on = bool(bonus_hour(now))
        if on != self.hour_on:
            self.hour_on = on
            self.log('   Upgrade Hour %s' % ('başladı' if on else 'bitti'))
            if self.send:
                from legacy_protocol import legacy
                msgs = [legacy('0|A|STM|bn_upgradeBounsHour_content')] if on else []     # "%25 uridyum indirimi" (istemcinin metni)
                self.send(msgs + self.discount_msgs(now))
        done = [k for k, b in self.st.items() if not b.get('notified') and now >= b['bitis']]
        for k in done:
            with self.p.lock:
                self.st[k]['notified'] = True
                self.p.dirty = True
        if done and self.send:
            self.send([self.update(k.split('|')[0], int(k.split('|')[1]), now) for k in done] + ([self.refresh()] if self.refresh else []))
