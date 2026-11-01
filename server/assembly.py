"""Assembly (yol haritası Aşama 5): istemcinin kendi tarifleriyle (data/recipes.json <- tools/il2cpp/client_data.py) üretim.

Akış (kayıtta giriş listesi var; üretim istekleri istemcinin kodundan):
  girişte                    AssemblyRecipeContentModule: tarifler ve durumları (Available {currentBuildCount, isNew} /
                             Build {buildAmount, remainingTimeMillis, prevBuildCount} / ReadyToCollect {prevBuildCount, buildAmount} /
                             Unavailable {type})
  AssemblyBuildRequest       {recipeLootId, targetItemId, amount}: malzemeler harcanır (inventory.py), süre başlar -> durum güncellemesi
                             (AssemblyRecipeStatusUpdateCommand); süre bitince ReadyToCollect
  AssemblyCollectRequest     sonuç x adet verilir (mağazanın ödül işlevi), durum Available ya da kullanım sınırıyla Unavailable
  AssemblyCollectAllRequest  hazır olanların hepsi
  AssemblySkipRequest        kalan süre uridyumla (dakikası 1 U, uyarlama)
  AssemblyRecipeSelectRequest  tarif görüldü (isNew kalkar)
  AssemblySetFilterRequest   pencerenin süzgeci profilde
Hangi tarifler: kayıttaki listede o gün açık olanlar (ALWAYS_VISIBLE ve takvimdeki ON_SCHEDULE; tek oyunculu: hepsi sürekli açık) ve
kayıtta olmayanlar (event_recipes): etkinlik parasını isteyenler (event_calendar.py 'para') etkinlik sürerken ya da elde o paradan varken,
Champion Token'lılar elde jeton varken, ötekiler (tasarımlar, ONLY_WHEN_OWNED taslakları; tek oyunculu uyarlama) sürekli; kaynağı
henüz olmayan malzemeyi isteyenler (NO_SOURCE) ve test tarifleri gizli. Etkin etkinliğin parasını isteyen tarif süreli
(AssemblyRecipeTemporaryTypeModule: etkinliğin kalan süresi); listeden düşen tarif AssemblyRecipeRemoveCommand ile kalkar (üretimi
sürenler kalır). Kullanım: ALWAYS_USABLE sınırsız, USABLE_ONCE bir kez, USABLE_ONCE_PER_SCHEDULE / USABLE_LIMIT_PER_SCHEDULE dönemde
bir / en_cok kez (dönem: tarif etkin bir etkinliğe bağlıysa etkinlik dönemi, değilse takvim günü). CostScalingFactor: aynı dönemde
her üretimde malzemeler bu oranla artar. Gemi isteyen tarifler (Plus gemileri): taban gemi etkin olmayanlardan harcanır; istemcinin
sayacına etkin olan da sayılır (envanter.client_count), yalnız etkin gemiyle üretimde oyunun "ship in use" uyarısı.
Profilde: assembly {uretim: {tarif: {adet, bitis, onceki}}, sayac: {tarif: toplam}, gunluk: {tarif: [gün, adet]}, gorulen: [tarif],
suzgec: {}}.
"""
import json, math, os, time

import inventory as INV
import settings as SET
import technology as TECH
import upgrades as UPG
import ranks as RT
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
T = json.load(open(os.path.join(HERE, 'data', 'recipes.json'), encoding='utf8'))['recipes']
INGREDIENTS = {loot for r in T.values() for loot in r.get('parcalar', {})}      # girişte sayaçları gönderilenler (magaza.count_msgs)
ALREADY_OWNS, ALREADY_USED, ALREADY_USED_LIMIT = 0, 1, 2          # RecipeUnavailableType (istemci)
# koşulla açılan tarifler (wiki): Spartan dron tasarımı Kronos kapısı tamamlanınca
UNLOCK = {'recipe_blueprint-spartan': lambda p: ((p.d.get('kapilar') or {}).get('kapilar', {}).get('kronos') or {}).get('tamam', 0) > 0,
          'recipe_blueprint-immunizer-cpu': lambda p: True}        # Quarantine Zone tek oyunculuda kalıcı (Aşama 8)
SKIP_U_PER_MIN = 1                                                # uyarlama: kalan dakikası 1 uridyum
NO_LIMIT = 'ALWAYS_USABLE'
# kaynağı henüz olmayan malzemeler (yol haritası E8: Flower kutu avı): tarifleri gizli. Proxium (Permafrost Fissure'ın UFO ve Ufonit
# kutuları: etkinlik_kapilari.json 'permafrost') ve ondan çıkan Duothrin, Trittothrin, Quadrothrin'in kaynağı artık var; Opitite ve
# Tarnom'unki de (Plutus' Experiments: plutus_deney.py)
NO_SOURCE = {'resource_collectable_flower-token'}
CHAMPION = 'resource_collectable_champion-token'                  # aylık ödül (rutbe.py): jetonlu tarifler elde jeton varken
TEST = 'recipe_recipe-test'
BOT = set()                       # Saturn Transmitter (recipe_blueprint-ss-cpu) açık: Saturn uzaylıları PvP görevinde oyuncu sayılır
                                  # (resmî forum 127576; savas_esya uzayli_cpu ss-cpu, dunya npc_reward)
# resmî sunucu kaydı (2026-10-25): girişte tarif listesinden sonra iki boş liste ve pencerenin üç süzgeci (filterType 2, 1, 0;
# saklanmamışsa bütün kategoriler)
FILTER_TYPES = (2, 1, 0)
ALL_FILTERS = ['ships_and_designs', 'ammunition', 'weapons', 'pet', 'generators', 'drones', 'extras', 'boosters', 'hardware', 'modules',
               'techs']
LIST_CHECK_SEC = 60                                                # etkinlik başlayınca / bitince tarif listesi
# seviyeli P.E.T. dişlisi/protokolü veren tarifler 4. seviyeyi verir (istemcinin metni: "Obtain Targeting Protocol X Level 4 for your
# P.E.T."); takmak P.E.T. seviyesine bağlı (pet.level_need). Seviye 1 veriliyordu: hangarda "Level 0", her P.E.T. takabiliyordu
PET_LEVEL = 4


def event_recipes(p, now=None):
    """Kayıtta olmayan tarifler: etkinlik parasını isteyenler (event_calendar.py 'para') etkinlik sürerken ya da elde o paradan varken,
    Champion Token'lılar elde jeton varken, ötekiler sürekli; kaynağı olmayan malzemeyi isteyenler, test tarifleri, koşulla
    açılanlar (UNLOCK) ve bot oyuncu isteyenler (BOT) dışarıda."""
    import event_calendar as CAL
    currency = {l for e in CAL.EVENTS.values() for l in e.get('currency', [])} | {CHAMPION}
    cur = {l for k in CAL.active(now) for l in CAL.EVENTS[k].get('currency', [])} | {l for l in currency if p.resource(l) > 0}
    run, chromin = chromin_recipes(now), set(CAL.EVENTS.get('chromin', {}).get('currency', []))
    out = []
    for k, r in T.items():
        ps = set(r['parcalar'])
        if 'recorded' in r or k in UNLOCK or k in BOT or k.startswith(TEST) or ps & NO_SOURCE:
            continue
        if run is not None and ps & chromin and k not in run:          # Chromin koşusu: yalnız o koşunun tarifleri
            continue
        if ps & cur or not ps & currency:
            out.append(k)
    return sorted(out)


def chromin_recipes(now=None):
    """Süren Chromin Rush koşusunun tarifleri (events.json chromin.kosu_tarifleri: resmî forum, her koşuda 6-9 tarif) ya da
    None (koşu yok ya da listesi bilinmiyor). Bilinen son günden sonraki koşular 52 haftada bir: önceki yılların günü aranır."""
    import datetime
    import event_calendar as CAL
    span = CAL.period('chromin', now)
    runs = CAL.EVENTS.get('chromin', {}).get('run_recipes') or {}
    if not span or not runs:
        return None
    start = datetime.date.fromtimestamp(span[0])
    for k in range(40):
        d = (start - datetime.timedelta(days=364 * k)).isoformat()
        if d in runs:
            return set(runs[d])
    return None


def recipe_event(key, now=None):
    """Tarifi parasıyla bağlayan etkin etkinlik (event_calendar.py 'para'; yoksa None)."""
    import event_calendar as CAL
    ps = set(T[key]['parcalar'])
    return next((k for k in sorted(CAL.active(now)) if ps & set(CAL.EVENTS[k].get('currency', []))), None)


def recorded_end(key, now=None):
    """Resmî sunucuda süreli tarifin bitişi (recipes.json gecici: "sezon" Season Pass sezonunun sonu, sayı kayıttaki bitiş) ya da
    None (süresiz, bitişi geçmiş ya da etkinlik parasıyla: onun süresi yerel takvimden, recipe_event)."""
    import event_calendar as CAL
    g = T[key].get('temporary')
    if g and set(T[key]['parcalar']) & {l for e in CAL.EVENTS.values() for l in e.get('currency', [])}:
        return None
    if g == 'season':
        import season
        g = season.current_end(now)
    return g if isinstance(g, (int, float)) and g > (now or time.time()) else None


def period_of(key, now=None):
    """'Dönemde bir kez / en çok' ve CostScalingFactor'ın dönemi: etkin etkinliğe bağlı tarifte etkinliğin başladığı gün, değilse
    takvim günü (zorla açılmış etkinliğin dönemi yok: gün)."""
    import event_calendar as CAL
    ev = recipe_event(key, now)
    span = CAL.period(ev, now) if ev else None
    return '%s:%s' % (ev, today(span[0])) if span else today(now)


def mod(name, **f):
    f['_'] = name
    return f


def today(now=None):
    return time.strftime('%Y-%m-%d', time.localtime(now or time.time()))


class Assembly:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                 # mağaza (ödül ve envanter güncellemeleri; oturum bağlar)
        self.send = None              # zamanlayıcıyla biten üretimin bildirimi (oturum bağlar)
        self.next_tick = self.next_list = 0.0
        self.free_last = SET.get('assembly_free')
        self.shown = None             # istemcideki tarif listesi (content); etkinlik bitince düşenler kaldırılır
        self.up = UPG.Upgrade(profile, log)   # Upgrade ve Disassembly sekmeleri (yukseltme.py)

    @property
    def st(self):
        d = self.p.d.setdefault('assembly', {})
        for k, v in (('uretim', {}), ('counter', {}), ('daily', {}), ('seen', []), ('filters', {})):
            d.setdefault(k, v)
        return d

    # ------------------------------------------------------------ tarifler
    def visible(self):
        """Pencerede görünen tarifler, kayıttaki sırayla; sonra depoda olan ONLY_WHEN_OWNED tarifler, koşulla açılanlar, kayıtta
        olmayanlar (event_recipes) ve üretimi süren ya da toplanmamış olanlar (etkinlik bitse de)."""
        out = sorted((k for k, r in T.items() if 'recorded' in r and k not in BOT), key=lambda k: T[k]['recorded'])
        out += sorted(k for k, r in T.items() if 'recorded' not in r and r['visibility'] == 'ONLY_WHEN_OWNED' and self.p.resource(k) > 0)
        out += [k for k, cond in UNLOCK.items() if k not in out and cond(self.p)]
        seen = set(out)
        out += [k for k in event_recipes(self.p) if k not in seen]
        seen = set(out)
        return out + sorted(k for k in self.st['uretim'] if k in T and k not in seen)

    def used_today(self, key):
        """Bu dönemdeki üretim adedi (period_of: etkinlik dönemi ya da gün)."""
        g = self.st['daily'].get(key)
        return g[1] if g and g[0] == period_of(key) else 0

    def limit_left(self, key):
        """Kalan kullanım (None: sınırsız)."""
        r = T[key]
        if r['usage'] == NO_LIMIT:
            return None
        if r['usage'] == 'USABLE_ONCE':
            return max(0, 1 - self.st['counter'].get(key, 0))
        cap = 1 if r['usage'] == 'USABLE_ONCE_PER_SCHEDULE' else (r['max_count'] or 1)
        return max(0, cap - self.used_today(key))

    def cost(self, key, amount):
        """Malzemeler x adet; CostScalingFactor: bugünkü her üretimde bir kat daha (1,1 …)."""
        if SET.get('assembly_free'):
            return {}
        r = T[key]
        f = r['scale'] ** self.used_today(key) if r['scale'] != 1 else 1
        return {loot: int(math.ceil(n * f * amount)) for loot, n in r['parcalar'].items()}

    def status(self, key, now=None):
        now = now or time.time()
        b = self.st['uretim'].get(key)
        if b:
            if now < b['bitis']:
                return mod('AssemblyRecipeBuildStatusModule', buildAmount=b['adet'], remainingTimeMillis=int((b['bitis'] - now) * 1000),
                           prevBuildCount=b['previous'])
            return mod('AssemblyRecipeReadyToCollectStatusModule', prevBuildCount=b['previous'], buildAmount=b['adet'])
        left = self.limit_left(key)
        if left == 0:
            kind = ALREADY_USED if T[key]['usage'] in ('USABLE_ONCE', 'USABLE_ONCE_PER_SCHEDULE') else ALREADY_USED_LIMIT
            return mod('AssemblyRecipeUnavailableStatusModule', type=kind)
        return mod('AssemblyRecipeAvailableStatusModule', currentBuildCount=self.build_count(key), isNew=key not in self.st['seen'])

    def build_count(self, key):
        """İstemcinin "Crafting Limit: <bu>/<MaxUses>" sayacı; MaxUses'a varınca Build'i kilitler. Sınırsız tariflerde MaxUses bir
        üretimin en çok adedi (U-LF-4, LF-P01 …): sayaç 0 (canlı test H32: bir üretimden sonra Build kilitleniyordu)."""
        r = T[key]
        if r['usage'] == NO_LIMIT:
            return 0
        if r['usage'] == 'USABLE_ONCE':
            return self.st['counter'].get(key, 0)
        return self.used_today(key)

    def recipe(self, key, now=None):
        """Etkin etkinliğin parasını isteyen tarif süreli (pencerede kalan süre); resmî sunucuda süreli olan (recipes.json gecici)
        Season Pass sezonunun sonuna ya da kayıttaki bitişine kadar süreli; öteki tarifler süresiz."""
        import event_calendar as CAL
        now = now or time.time()
        ev = recipe_event(key, now)
        end = None if ev else recorded_end(key, now)
        typ = (mod('AssemblyRecipeTemporaryTypeModule', remainingTimeMillis=CAL.time_left(ev, now) * 1000) if ev else
               mod('AssemblyRecipeTemporaryTypeModule', remainingTimeMillis=int((end - now) * 1000)) if end else
               mod('AssemblyRecipeRegularTypeModule'))
        return mod('AssemblyRecipeModule', recipeLootId=key, targetItemId=0, type=typ, status=self.status(key, now))

    def content(self):
        """Girişteki tarif listesi (kayıttaki komutun yerine)."""
        keys = self.visible()
        self.shown = set(keys)
        return ('AssemblyRecipeContentModule', {'recipes': [self.recipe(k) for k in keys] + self.up.recipes()})

    def login_msgs(self):
        """Girişte: tarif listesi, iki boş liste ve süzgeçler (resmî sunucunun sırası)."""
        return [self.content()] + [('AssemblyRecipeContentModule', {'recipes': []})] * 2 + self.filter_msgs()

    def filter_msgs(self):
        """Pencerenin süzgeçleri (AssemblySetFilterRequest'in modülü, filterType başına; saklanmamışsa bütün kategoriler): girişte
        geri (E10)."""
        return [('AssemblyWindowSettingsModule', {k: v for k, v in m.items() if k != '_'})
                for m in (self.st['filters'].get(str(t)) or {'filterType': t, 'assemblyItemFilters': list(ALL_FILTERS)}
                          for t in FILTER_TYPES)]

    def update(self, key, target=0, now=None):
        return ('AssemblyRecipeStatusUpdateCommand', dict(targetItemId=target, status=self.status(key, now), lootId=key))

    # ------------------------------------------------------------ istekler
    def build(self, f):
        key, amount = f.get('recipeLootId', ''), max(1, int(f.get('amount') or 1))
        r = T.get(key)
        if not r or key not in self.visible() or key in self.st['uretim']:
            self.log('   Assembly: üretilemez %s (%s)' % (key, 'tarif yok' if not r else 'sürüyor' if key in self.st['uretim'] else 'görünmüyor'))
            return [self.update(key)] if r else []
        left = self.limit_left(key)
        if left is not None:
            amount = min(amount, left)
        if amount <= 0 or (not r['stackable'] and amount > 1):
            amount = 1 if amount > 0 else 0
        if amount <= 0:
            return [self.update(key)]
        need = self.cost(key, amount)
        miss = INV.missing(self.p, need)
        if miss:
            self.log('   Assembly: malzeme yetmiyor %s x%d (eksik %s)' % (key, amount, miss))
            in_use = [l for l in miss if l.startswith('ship_') and INV.client_count(self.p, l) >= need[l]]
            # taban gemi var ama etkin: oyunun kuralı ve metni ("You cannot upgrade a ship that is currently in use. Please change ships
            # before upgrading."); istemcinin bu uyarıyı gösteren kodu (AssemblyViewSystem.PromptShipChange) hiç çağrılmıyor
            return ([legacy('0|A|STM|assembly_warning_ship_in_use')] if in_use else []) + [self.update(key)]
        removed = INV.spend(self.p, need, reason='buy_SPECIAL', detail=key)
        now = time.time()
        with self.p.lock:
            self.st['uretim'][key] = dict(adet=amount, bitis=now + SET.duration(r['sure_sn'] * amount, 'assembly'), previous=self.st['counter'].get(key, 0))
            if key not in self.st['seen']:
                self.st['seen'].append(key)
            if r['usage'] != NO_LIMIT or r['scale'] != 1:
                self.st['daily'][key] = [period_of(key), self.used_today(key) + amount]
            self.p.dirty = True
        self.p.ach('assembly_build', tarif=key, adet=amount)
        self.log('   Assembly: %s x%d başladı (%d sn; %s)' % (key, amount, r['sure_sn'] * amount, need))
        return INV.update_msgs(self.m, self.p, list(need), removed) + [self.update(key, f.get('targetItemId', 0))]

    def collect(self, f, now=None):
        key = f.get('recipeLootId', '')
        b = self.st['uretim'].get(key)
        now = now or time.time()
        if not b or now < b['bitis']:
            return [self.update(key)] if key in T else []
        with self.p.lock:
            del self.st['uretim'][key]
            self.st['counter'][key] = self.st['counter'].get(key, 0) + b['adet']
            self.p.dirty = True
        msgs = []
        for loot, n in T[key]['result'].items():
            msgs += self.grant(loot, n * b['adet'])
        self.p.ach('assembly_collect', tarif=key, adet=b['adet'])
        # seyir defteri (MSJ-10): istemci (ReturnLogBookInfoText) "his_assembly_…" metnini çevirir; %recipename% info'daki lootId'nin
        # adı (items_<lootId>_fullname; sonucun adı hepsinde var, tarifin adı 35 tarifte yok), %buildamount% count
        RT.note(self.p, 'his_assembly_recipe_collected_multi' if b['adet'] > 1 else 'his_assembly_recipe_collected',
                next(iter(T[key]['result'])), b['adet'])
        self.log('   Assembly: %s x%d toplandı (%s)' % (key, b['adet'], T[key]['result']))
        return msgs + [self.update(key, f.get('targetItemId', 0))]

    def grant(self, loot, n):
        """Sonuç: teknoloji eşyası sayaca, ötekiler mağazanın ödül işleviyle (cephane, ekipman, gemi, booster, kaynak …)."""
        if loot.startswith('tech_'):
            TECH.add(self.p, loot, n)
            return INV.update_msgs(self.m, self.p, [loot])
        if self.m:
            return self.m.reward(loot, n, level=PET_LEVEL)
        self.p.add_resource(loot, n)
        return []

    def collect_all(self, f):
        """AssemblyCollectAllRequest.allRequests: AssemblyRecipeKeyModule {lootId, targetId}."""
        msgs = []
        before = self.up_state()
        for c in f.get('allRequests') or []:
            g = dict(recipeLootId=c.get('lootId') or c.get('recipeLootId', ''), targetItemId=c.get('targetId') or c.get('targetItemId', 0))
            msgs += self.up.collect(g) if g['recipeLootId'] in UPG.UP else self.collect(g)
        return msgs + ([self.content()] if self.up_state() != before else [])        # H61

    def skip(self, f):
        key = f.get('recipeLootId', '')
        b = self.st['uretim'].get(key)
        now = time.time()
        if not b or now >= b['bitis']:
            return [self.update(key)] if key in T else []
        price = max(1, int(math.ceil((b['bitis'] - now) / 60.0)) * SKIP_U_PER_MIN)
        if INV.missing(self.p, {'currency_uridium': price}):
            self.log('   Assembly: atlama için uridyum yetmiyor (%d)' % price)
            return [self.update(key)]
        INV.spend(self.p, {'currency_uridium': price}, reason='buy_SPECIAL', detail=key)
        with self.p.lock:
            b['bitis'] = now
            self.p.dirty = True
        self.log('   Assembly: %s süresi atlandı (%d U)' % (key, price))
        return INV.update_msgs(self.m, self.p, ['currency_uridium']) + [self.update(key)]

    def select(self, f):
        key = f.get('recipeLootId', '')
        if key not in T or key in self.st['seen']:
            return []
        with self.p.lock:
            self.st['seen'].append(key)
            self.p.dirty = True
        return [self.update(key)]

    def set_filter(self, f):
        with self.p.lock:
            self.st['filters'][str(f.get('filterType', 0))] = f.get('assemblyWindowSettingsModule') or {}
            self.p.dirty = True
        return []

    def up_state(self):
        return {k: b['bitis'] for k, b in self.up.st.items()}

    def handle(self, name, f):
        self.up.m, self.up.send, self.up.refresh = self.m, self.send, self.content
        if self.up.handles(name, f):
            before = self.up_state()
            msgs = self.up.handle(name, f)
            if self.up_state() != before:
                # hedefli yükseltme eklendi, atlandı ya da toplandı: istemci durum güncellemesini yalnız listesindeki (tarif, hedef)
                # satırına uygular ve Update/Upgrade panelini ancak tarif listesi gelince yeniden çizer (canlı test H39: Build'den
                # sonra yükseltme görünmüyordu; H61: Skip ve Collect'ten sonra panel eski sayaçta/"Collect"te kalıyordu)
                msgs = msgs + [self.content()]
            return msgs
        fn = {'AssemblyBuildRequest': self.build, 'AssemblyCollectRequest': self.collect, 'AssemblyCollectAllRequest': self.collect_all,
              'AssemblySkipRequest': self.skip, 'AssemblyRecipeSelectRequest': self.select,
              'AssemblySetFilterRequest': self.set_filter}.get(name)
        return fn(f) if fn else None

    # ------------------------------------------------------------ zaman
    def tick(self, now):
        """Saniyede bir: süresi biten üretimler hazır (istemciye ReadyToCollect); dakikada bir tarif listesi (etkinlik bitti:
        AssemblyRecipeRemoveCommand, başladı: yeni liste)."""
        if now < self.next_tick:
            return
        self.next_tick = now + 1.0
        free = SET.get('assembly_free')
        if free != self.free_last:                # ayar değişti: istemcinin malzeme sayaçları yenilenir
            self.free_last = free
            if self.m and self.send:
                self.send(self.m.count_msgs())
        if now >= self.next_list and self.shown is not None and self.send:
            self.next_list = now + LIST_CHECK_SEC
            keys = self.visible()
            gone = sorted(self.shown - set(keys))
            if gone:
                self.send([('AssemblyRecipeRemoveCommand', {'recipes': [mod('AssemblyRecipeKeyModule', lootId=k, targetId=0)
                                                                         for k in gone]})])
                self.log('   Assembly: %d tarif listeden kalktı (%s …)' % (len(gone), gone[0]))
            if set(keys) - self.shown:
                self.send([self.content()])
            self.shown = set(keys)
        self.up.m, self.up.send, self.up.refresh = self.m, self.send, self.content
        self.up.tick(now)
        done = [k for k, b in self.st['uretim'].items() if not b.get('notified') and now >= b['bitis']]
        for k in done:
            with self.p.lock:
                self.st['uretim'][k]['notified'] = True
                self.p.dirty = True
        if done and self.send:
            self.send([self.update(k, now=now) for k in done])
