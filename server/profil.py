"""Oyuncu profili: etkin kayıt yuvasının profil.json'u (save/kayitlar/<yuva>/, yollar.py; panel --profil ile verir; eski düzende
save/profil.json). Girişte gönderilen çekirdek komutlar buradan üretilir,
istemcinin ayar/pencere/hareket istekleri buraya yazılır (istemci kapanıp açılınca korunur).

İlk çalıştırmada profil, data/giris.json'daki "tohum"dan (kaydın giriş komutlarından) kurulur; tohum yoksa varsayılan pilot.
Alan adları protokoldeki adlarla aynıdır, böylece profil doğrudan mesaja dönüşür.
"""
import json, os, threading, time
MODE_WINDOWS = ('voyagers', 'trinityTrials', 'expedition', 'eternal_blacklight', 'rogue_lite')     # özellik çubuğu (Aşama 8)
# etkinlik penceresi -> takvimdeki etkinlikler (biri sürerken görünür; canlı test H47). Plutus: PlutusInfoCommand; labirent:
# FrozenLabyrinthInfoCommand; Agatus ve NPC etkinlikleri: etkinlik_harita.py'nin göstergesi (etkinlikler.json 'bilgi' komutu)
EVENT_WINDOWS = {'plutus': ('plutus',), 'frozen_labyrinth': ('labirent',), 'agatus_event': ('agatus',), 'npc_event': None,
                 'chrominEvent': ('chromin',), 'word_puzzle': ('hitac',), 'titleFrenzy': ('unvan_avi',),        # Ö3
                 'space_search': ('galaxy_trek',), 'birthday_2025': ('fiesta',), 'infiltration': ('infiltration',),
                 'miniclient_reward': None,
                 'invasion': ('invasion',), 'ship_boost_event': ('fever',), 'diminish_quests': ('acil_gorevler',),
                 'strikeAndExit': ('vortex_of_greed',), 'publicWorldBoss': ('world_boss',), 'payload_escort': ('mimesis_mutiny',),  # Ö4
                 'mileageMarket': ('mileage_market',), 'vipMerchantExchange': ('vip_merchant',),                            # Ö7
                 'preBlackFridaySales': ('pre_prometheus',), 'return_of_hero': ('return_of_hero',), 'returnee_login': (),
                 'apotheosis': ('kristallon_apotheosis',), 'recallBattlePass': ('return_of_hero',)}                       # 1.1.115
# 1.1.115'in pencereleri kayıttaki arayüzde yok: profile Return of Hero öğesinin kopyası olarak eklenir (başlık, boyut game.xml'den);
# istemci pencereyi açmadan önce menü öğesini adıyla arıyor (FeatureMenuHelper.GetFeatureItemById)
NEW_WINDOWS = {'apotheosis': ('title_kristallon_apotheosis', 728, 460), 'recallBattlePass': ('return_pass_name', 800, 440)}
# görünürlüğü takvimden değil oyuncunun durumundan olanlar: itemId -> () -> bool (Ö7: Returnee Login kampanyası, dukkanlar.py)
WINDOW_HOOKS = {}
# Urgent Missions'ın penceresini (diminish_quests) istemci görev gelince kendisi açıyor (DiminishingQuestHandler.OpenWindow); öğe
# menüde görünmezse istemcinin sözlüğünde yok, açılamıyor (KeyNotFound). Şablondaki maximized yüzünden girişte boş açılıyordu:
# girişte hep kapalı gider (canlı tur Ö3)
CLOSED_AT_LOGIN = {'diminish_quests'}
# görünürlüğünü kendi sistemi oyun sürerken bildiren öğeler (takvim değişiminde ayrıca gönderilmez): Urgent Missions yalnız görev
# varken görünür, istemcinin menüsündeki simgeyi acil_gorevler.py izliyor (kullanıcı 2026-10-18)
OWN_SYNC = {'diminish_quests'}
INDICATOR_WINDOWS = {'AgatusEventInfoCommand': 'agatus_event', 'NpcEventInfoCommand': 'npc_event'}
# menüde hiç gösterilmeyenler: R-Zone (PvP, bot oyuncularla; istekleri karşılıksız). Stellar Pathfinder gizlenemez: istemci girişte
# (UIMainCenterNewSystem.ShowMenuList) "hangar", "stellar_pathfinder" ve "vouchers" öğelerini adıyla arıyor, öğe yoksa
# KeyNotFoundException ile giriş tamamlanmıyor (canlı test Ö1); görünürlüğünü istemci seviyeye göre kendisi ayarlıyor
HIDDEN_WINDOWS = ('rzone',)


def window_events(item_id):
    """Etkinlik penceresinin bağlı olduğu takvim etkinlikleri (npc_event / agatus_event: göstergesi o komut olanlar)."""
    import takvim as TKV
    keys = EVENT_WINDOWS.get(item_id)
    if keys is not None:
        return keys
    if item_id == 'miniclient_reward':       # Mini Client ödülü: türlerinde MiniClientReward olanlar (gunluk_odul.py; dışında boş açılırdı)
        return tuple(k for k, e in TKV.EVENTS.items() if 'MiniClientReward' in e.get('turler', []))
    return tuple(k for k, e in TKV.EVENTS.items() for s in ([e['harita']] if 'harita' in e else []) + e.get('harita_ek', [])
                 if INDICATOR_WINDOWS.get((s.get('bilgi') or {}).get('komut')) == item_id)


def event_window_visible(item_id, now=None, hooks=None):
    """hooks: profilin kendi kancaları (Profil.window_hooks; arkadaş sunucusunda her oyuncunun oturumu kendininkini bağlar)."""
    import takvim as TKV
    for hk in (hooks or {}, WINDOW_HOOKS):
        if item_id in hk:
            return bool(hk[item_id]())
    return any(TKV.is_active(k, now) for k in window_events(item_id))

import booster as BOOSTER

_YIGIN = None


def stack_cap(loot):
    """İstemcinin eşya yığın sınırı (istemci_esyalari.json yigin; 2^63'e yakın 'sınırsız' sayılır) ya da None."""
    global _YIGIN
    if _YIGIN is None:
        K = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'istemci_esyalari.json'), encoding='utf8'))
        _YIGIN = {k: int(v['yigin']) for k, v in K['esyalar'].items() if isinstance(v, dict) and 0 < (v.get('yigin') or 0) < 10 ** 12}
    return _YIGIN.get(loot)
import yetenek as YETENEK
import gemi_yetenek as GY
import lazer as LAZER
import savas_esya as SE
import ekstra as EK
import rutbe as RT
import teknoloji as TK
import banka as BANK
import harita as H
import yollar as YOL

HERE = os.path.dirname(os.path.abspath(__file__))
PROFIL_PATH = os.path.join(HERE, 'save', 'profil.json')     # eski düzen; etkin yuva: yollar.profile_path()

PILOT_FIELDS = ('userId', 'userName', 'factionId', 'clanId', 'clanTag', 'level', 'ep', 'honourPoints', 'credits', 'uridium', 'premium',
                'dailyRank', 'galaxyGatesDone', 'expansionStage', 'jackpot', 'useSystemFont', 'captainEnergy', 'maxCaptainEnergy')
SHIP_FIELDS = ('typeId', 'speed', 'shield', 'shieldMax', 'hitPoints', 'hitMax', 'nanoHull', 'maxNanoHull', 'cargoSpace', 'cargoSpaceMax',
               'cloaked', 'modifier')
# istemcinin ayar istekleri -> UserSettingsCommand içindeki modül
SETTINGS_REQUESTS = {'GameplaySettingsRequest': 'gameplaySettingsModule', 'DisplaySettingsRequest': 'displaySettingsModule',
                     'AudioSettingsRequest': 'audioSettingsModule', 'QualitySettingsRequest': 'qualitySettingsModule',
                     'QuestSettingsRequest': 'questSettingsModule', 'WindowSettingsRequest': 'windowSettingsModule'}
WINDOW_KEYS = ('posX', 'posY', 'width', 'height', 'maximized')
# kayıttaki GameplaySettingsModule (notSet: oyuncu henüz kaydetmedi)
GAMEPLAY_DEFAULTS = {'autoBoost': True, 'autoRefinement': True, 'quickslotStopAttack': True, 'doubleclickAttack': True,
                     'autoChangeAmmo': True, 'autoStart': True, 'autoBuyGreenBootyKeys': False}
# premium kısayol çubukları: kayıt premiumsuz hesaptan, şablonda yalnız standardSlotBar var. İstemci her çubuğu MenuInitializationCommand'dan
# kurar (ItemMenuMenuInitialization.ParseSlotBars, yuva 1-10); yoksa Pro Action Bar düğmesi görünür ama çubuk açılmaz (H81). Konum
# "yüzde x,y|kayma x,y": kayma 0,0 olunca istemci yüzde konumunu kullanır (UIBagSystem.SetInitSlotBarPosition); sürüklenince
# WindowSettingsRequest'teki slotmenuPremiumPosition / slotmenuProActionPosition geçerli olur.
PREMIUM_SLOT_BARS = (('premiumSlotBar', '50,79.5|0,0'), ('proActionBar', '50,73.5|0,0'))   # açılan kategori listesinin üstünde
# Arayüz yapılandırması (Ayarlar > Interface): çubuklar sürüklenince istemci konumlarını WindowSettingsRequest'le gönderir
# (FeatureMenuHelper.SendWindowSettingsRequest: categoryBar, üç kısayol çubuğu, gameFeaturesBar, genericFeaturesBar; "x,y" yüzde ve
# düzen sırası). Girişte istemci çubukları yalnız UILayoutCommand'dan (FeatureBarVo.Init: featureBarPosition, featureBarOrder) ve
# MenuInitializationCommand'dan (ParseSlotBars: slotBarPosition "x,y|kayma", slotBarOrder = WindowConstants.LayoutsMap sırası 0-5;
# itemBarPosition) kurar: kaydedilen konumlar oraya yazılmazsa her girişte şablondaki yerlerine dönüyordu (kullanıcı, 2026-10-18).
# Kısayol çubuğunda kayma 0,0: istemci yüzde konumunu kullanır (UIBagSystem.SetInitSlotBarPosition). Yeni özellik çubuğu (tür 3)
# istekte yok: yapılandırmada oyun çubuğuyla birlikte taşınıyor, kayıtta da onunla aynı konumda geliyor (konum ondan, düzeni şablondan).
FEATURE_BAR_KEYS = {1: ('gameFeatureMenuPosition', 'gameFeatureMenuOrder'), 2: ('genericFeatureMenuPosition', 'genericFeatureMenuOrder'),
                    3: ('gameFeatureMenuPosition', None)}
SLOT_BAR_KEYS = {'standardSlotBar': ('slotmenuPosition', 'slotMenuOrder'),
                 'premiumSlotBar': ('slotmenuPremiumPosition', 'slotMenuPremiumOrder'),
                 'proActionBar': ('slotmenuProActionPosition', 'slotMenuProActionOrder')}
LAYOUT_COUNT = 6                    # WindowConstants.LayoutsMap (Horizontal/Vertical List/Grid, ProAction Horizontal/Vertical Grid)
# ekipmana bağlı kısayol öğeleri (CPU'lar, Smart Bomb, fırlatıcı, gemi yetenekleri): takma/çıkarmadan sonra yenilenir (menu_changes)
# hızlı alım öğesinin eşya çubuğu ipucundaki "Double click to buy" (kayıt: toolTipItemBar'ın son satırı; kısayol çubuğunda yok)
QUICK_BUY_TIP = {'_': 'MessageKeyListWildcardModule', 'wildCardReplacements': [], 'baseKey': 'ttip_quick_buy_itembar',
                 'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 5}, 'textStyle': 0}
EQUIP_MENUS = ('equipment_extra_', 'ability_', 'equipment_weapon_rocketlauncher_', 'ammunition_rocketlauncher_', 'ammunition_mine_smb-01')
DESIGN_KEYS = {'design': 'tasarim', 'visual': 'gorunum'}     # dronun tasarım yuvaları -> geminin dron_tasarim kaydındaki anahtar

_LEVELS = None
_ESYA = None


def esya():
    global _ESYA
    if _ESYA is None:
        _ESYA = json.load(open(os.path.join(HERE, 'data', 'esyalar.json'), encoding='utf8'))
    return _ESYA


_ETKINLIK_ACIK = {}          # takvim anahtarı -> (sorgu zamanı, açık mı)


def event_on(key, now=None):
    """Takvim etkinliği şimdi açık mı. mods()'un sıcak yolunda çağrıldığından (takvim sorgusu ~60 µs) sonuç 30 sn saklanır."""
    now = now or time.time()
    t = _ETKINLIK_ACIK.get(key)
    if not t or now - t[0] > 30 or now < t[0]:
        import takvim as TKV
        t = _ETKINLIK_ACIK[key] = (now, TKV.is_active(key, now))
    return t[1]


def _layout_ok(v):
    """İstemcinin gönderdiği düzen sırası geçerli mi (0-5; istemci sırayı diziden okur, dışı IndexOutOfRange)."""
    return isinstance(v, (str, int)) and str(v).isdigit() and int(v) < LAYOUT_COUNT


def _formations():
    return esya()['formasyonlar']


def lab_data():
    return esya()['laboratuvar']


def formation_id(loot_id):
    """Formasyon lootId'si -> istemcinin formasyon kimliği (data/esyalar.json formasyonlar; game.xml <formations>)."""
    f = _formations().get(loot_id)
    return f['id'] if f else None


def formation_drones_ok(p, loot_id):
    """Formasyon için yeterli dron var mı (Arrow ve Dome 4, Heart ve Pincer 6: formasyonlar.asgari_dron; wiki)."""
    return len(p.d['dronlar']) >= esya()['formasyon_kurallari'].get(loot_id, {}).get('asgari_dron', 0)


def formation_loot(fid):
    return next((k for k, v in _formations().items() if v['id'] == fid), 'drone_formation_default')


def level_for(ep):
    global _LEVELS
    if _LEVELS is None:
        import veri as VERI           # Dünya Editörü: seviye eşikleri
        _LEVELS = VERI.yukle('seviyeler.json')['seviyeler'] if os.path.exists(os.path.join(HERE, 'data', 'seviyeler.json')) else [[1, 0]]
    lv = 1
    for level, need in _LEVELS:
        if ep >= need:
            lv = level
    return lv


DEFAULT_SHIP_INIT = dict(userId=1, userName='Pilot', typeId='ship_goliath', speed=300, shield=100000, shieldMax=100000, hitPoints=356000,
                         hitMax=356000, cargoSpace=0, cargoSpaceMax=1500, x=2000, y=2000, mapId=1, factionId=1, expansionStage=3, premium=True,
                         ep=100000, honourPoints=1000, level=12, credits=1000000, uridium=50000, dailyRank=1, refreshMap=True, modifier=[])


class Profil:
    # tek oyunculu kural: herkes Premium (kayıttaki hesap değildi; H72). Avantajları istemcinin metinlerinden: roket beklemesi yarı ve
    # onarım robotu x2 (dunya), P.E.T. tamiri ücretsiz (pet), çıkış 5 sn (game.LOGOUT_SN). Gemi tamiri panelin tamir ücretiyle.
    premium = True
    # kargoya sayılan cevherler: istemcinin toplamı (UnitAttributeOreCountUpdate.UpdateHeroCargo: Prometium … Palladium ve Osmium).
    # Xenomit (3) kargoda durur, yer kaplamaz (kullanıcı bildirimi 2026-10-24: 1.500 Xenomit kargoyu dolduruyordu)
    CARGO_ORES = frozenset((0, 1, 2, 4, 5, 6, 7, 8, 28))

    def __init__(self, tohum=None, path=None, d=None):
        """d: dosyadan değil bu sözlükten (arkadaş sunucusunda misafirin gönderdiği kayıt; cok_oyunculu.MisafirProfil)."""
        self.path = path = path or YOL.profile_path()
        self.lock = threading.Lock()
        self.dirty = False
        self.ach = lambda kind, **kw: []      # başarım olayları (basarim.py; oturum bağlar). Profil kilidi tutulurken çağrılmaz
        self.hint = lambda kind: []           # ipucu penceresi bir kez (ipucu.py; oturum bağlar) -> mesajlar
        self.window_hooks = {}                # menü öğesinin görünürlüğü (event_window_visible; oturum bağlar)
        self.tohum = tohum or {}
        created = d is None and not os.path.exists(path)
        if d is not None:
            self.d = d
        elif not created:
            self.d = json.load(open(path, encoding='utf8'))
        else:
            self.d = self._from_seed(self.tohum)
            self.dirty = True
        self._migrate()
        self.menu_status_cache = {}      # menuItemId -> şablondaki MenuItemStatusCommand (sayaç güncellemeleri için)
        self.menu_sent = {}              # menuItemId -> istemciye son bildirilen durum (menu_changes karşılaştırır)
        self.cpu_init_sent = None        # son CPUInitializationCommand (AJP-01 takılınca/çıkarılınca yeniden: menu_changes)
        self.daily_fields = None         # günlük giriş takviminin alanları (gunluk.py; oturum bağlar)
        if self.dirty and created:
            # yalnız yeni profil hemen yazılır (web.py girişte okur). Var olan dosyanın göçleri oyunun olağan kaydıyla (10 sn) yazılır:
            # yüklemek dosyayı değiştirmez (testler game modülünü yükleyince kullanıcının kaydı yeniden yazılmıştı; canlı test H72)
            self.save()

    # ---------------------------------------------------------------- kurulum
    @staticmethod
    def _from_seed(t):
        si = dict(DEFAULT_SHIP_INIT)
        si.update(t.get('ShipInitializationCommand') or {})
        d = {
            'surum': 1,
            'olusturma': time.strftime('%Y-%m-%d %H:%M:%S'),
            'pilot': {k: si.get(k) for k in PILOT_FIELDS if k in si},
            'gemi': {k: si.get(k) for k in SHIP_FIELDS if k in si},
            'konum': {'mapId': si['mapId'], 'x': si['x'], 'y': si['y']},
            'madenler': (t.get('AttributeOreCountUpdateCommand') or {}).get('oreCountList', []),
            'formasyon': (t.get('DroneFormationChangeCommand') or {}).get('selectedFormationId', 0),
            'ayarlar': t.get('UserSettingsCommand') or {},
            'tus_atamalari': (t.get('UserKeyBindingsUpdate') or {}).get('changedKeyBindings', []),
            'arayuz': t.get('UILayoutCommand') or {'featureBars': []},
        }
        # kopya: tohumun sözlükleri paylaşılınca profilin değişiklikleri (ayarlar, arayüz, tuşlar) aynı süreçte açılan sonraki yeni
        # profillere de geçiyordu (tohum oyunun şablonundan, tek nesne)
        return json.loads(json.dumps(d))

    def _migrate(self):
        """Eski profillere yeni bölümleri tohumdan ekler (ekipman, cephane, seçili cephane, eşya kimlikleri)."""
        t = self.tohum
        if 'ekipman' not in self.d:
            self.d['ekipman'] = t.get('ekipman') or {'laser': ['equipment_weapon_laser_lf-1'], 'generators': [], 'extra': [], 'rocket': []}
            self.dirty = True
        if not self.d.get('cephane_tohum'):
            got = self.d.get('cephane', {})          # bonus kutularından gelenler tohumun üstüne eklenir
            base = dict(t.get('cephane') or {'ammunition_laser_lcb-10': 1000, 'ammunition_rocket_r-310': 20})
            for k, v in got.items():
                base[k] = base.get(k, 0) + v
            self.d['cephane'], self.d['cephane_tohum'] = base, True
            self.dirty = True
        for k in [k for k in self.d.get('cephane', {}) if k.startswith('resource_')]:
            # Dünya Editörü'nün bonus kutusundaki kaynaklar (ABR …) cephaneye yazılıyordu (oyuncu bildirimi 2026-10-30): depoya
            n = self.d['cephane'].pop(k)
            if n > 0:
                d = self.d.setdefault('diger_esyalar', {})
                d[k] = d.get(k, 0) + n
            self.dirty = True
        for k, default in (('secili', {'lazer': 'ammunition_laser_lcb-10', 'roket': 'ammunition_rocket_r-310'}), ('esya_kimlik', {})):
            if k not in self.d:
                self.d[k] = json.loads(json.dumps(t.get(k) or default))     # kopya: tohum profiller arasında paylaşılmasın
                self.dirty = True
        if 'konfigler' not in self.d and 'gemiler' not in self.d:
            # hangar: sahip olunan ekipman örnekleri (itemId -> lootId) ve iki config'te takılı kimlikler (kayıttaki kimliklerle)
            if t.get('konfigler') and t.get('esyalar'):
                self.d['esyalar'] = dict(t['esyalar'])
                self.d['konfigler'] = json.loads(json.dumps(t['konfigler']))
                self.d['aktif_konfig'] = t.get('aktif_konfig', 1)
            else:
                self.d['esyalar'], cfg = {}, {}
                for slot, loots in self.d['ekipman'].items():
                    cfg[slot] = [self._add_item(loot) for loot in loots]
                self.d['konfigler'] = {'1': cfg, '2': json.loads(json.dumps(cfg))}
                self.d['aktif_konfig'] = 1
            self.dirty = True
        if 'sonraki_kimlik' not in self.d:
            self.d['sonraki_kimlik'] = max([int(i) for i in self.d['esyalar']] + [99000000]) + 1
            self.dirty = True
        if 'gemiler' not in self.d:
            # birden çok gemi: her geminin kendi kimliği, hangar kimliği ve iki config'i (kayıttaki Liberator kimlikleriyle başlar)
            k = t.get('gemi_kimlik') or {'shipId': 1, 'hangarId': 1}
            self.d['gemiler'] = {str(k['shipId']): {
                'lootId': self.d['gemi'].get('typeId', 'ship_liberator'), 'hangarId': k['hangarId'],
                'konfigler': self.d.pop('konfigler'), 'aktif_konfig': self.d.pop('aktif_konfig', 1), 'favori': False}}
            self.d['aktif_gemi'] = str(k['shipId'])
            self.dirty = True
        if 'dronlar' not in self.d:
            # dronlar: sıra = gemi çevresindeki konum; formasyonlar: satın alınanlar (standart her zaman var)
            self.d['dronlar'], self.d['formasyonlar'], self.d['sonraki_dron'] = [], [], 1
            self.dirty = True
        self.sync_cargo()
        if 'yukseltmeler' not in self.d:
            self.d['yukseltmeler'] = {}      # LabItem (0 lazer, 1 roket, 2 motor, 3 kalkan) -> [cevher türü, kalan]
            self.dirty = True
        if 'gorevler' not in self.d:
            # kayıttaki hesapta girişte 20000 ("Elite Force Audition": görev vericiye dön) etkindi; başlangıç zinciri oradan
            self.d['gorevler'] = {'aktif': {'20000': {}}, 'tamam': []}
            self.dirty = True
        for s in self.d['gemiler'].values():
            if 'dron_konfig' not in s:
                s['dron_konfig'] = {c: {} for c in s['konfigler']}     # config -> dron kimliği -> takılı eşya kimlikleri
                self.dirty = True
        # dron tasarımları ve P.E.T. donanımı gemiye (hangara) bağlı: geminin dron_tasarim {config: {dron kimliği: {tasarim, gorunum}}}
        # ve pet_konfig {config: {yuva: [eşya]}} kayıtları. Önceden config numarasına bağlıydı (dronun kaydında, P.E.T.'in konfig'inde),
        # her gemide takılı görünüyordu; Transfer System'den sonra eski gemide de takılı kalıyordu (kullanıcı bildirimi 2026-10-25).
        # Eskiler o anki etkin gemiye (Astral koşusundaysa oyuncunun kendi gemisine). Tasarım daha eskiyse dronun kendisindeydi, iki
        # config'te aynı (kullanıcı bildirimi 2026-10-24: config 1'e takılan Havoc'lar config 2'de de görünüyordu)
        kosu = ((self.d.get('pve') or {}).get('astral') or {}).get('kosu') or {}
        yedek = kosu.get('yedek') or {}
        own = [(self.d['aktif_gemi'], self.d['dronlar'])]
        if kosu.get('icerde') and yedek.get('aktif') in self.d['gemiler']:
            own = [(yedek['aktif'], yedek.get('dronlar', [])), (self.d['aktif_gemi'], self.d['dronlar'])]
        for sid, drones in own:
            for x in drones:
                for k in DESIGN_KEYS.values():
                    if k not in x:
                        continue
                    v = x.pop(k)
                    for c, iid in ((v if isinstance(v, dict) else {'1': v, '2': v}) if v else {}).items():
                        if iid:
                            self.d['gemiler'][sid].setdefault('dron_tasarim', {}).setdefault(str(c), {}).setdefault(
                                str(x['kimlik']), {})[k] = iid
                    self.dirty = True
        pet = self.d.get('pet')
        if pet and 'konfig' in pet:
            self.d['gemiler'][own[0][0]].setdefault('pet_konfig', {}).update(pet.pop('konfig'))
            self.dirty = True
        for s in self.d['gemiler'].values():       # kayıtlı config'teki tasarımlar: {dron: {tasarim: {config: eşya}}} -> yeni biçim
            old = s.get('kayitli_dron_tasarim') or {}
            if any(k in DESIGN_KEYS.values() for per in old.values() for k in per):
                new = {}
                for d, per in old.items():
                    for k, cs in per.items():
                        for c, iid in (cs or {}).items():
                            if iid:
                                new.setdefault(str(c), {}).setdefault(str(d), {})[k] = iid
                s['kayitli_dron_tasarim'] = new
                self.dirty = True
        osmium = self.d.get('diger_esyalar', {}).pop('resource_ore_osmium', 0)
        if osmium:                           # Osmium (OreType 28) cevher sayılmıyordu, depoya düşmüştü (2026-10-22 taraması, E2)
            self.add_ores({28: osmium})
        q = self.d.get('ayarlar', {}).get('qualitySettingsModule') or {}
        if q.get('qualityExplosion', 0) > 255:
            # tablo QualitySettingsRequest.qualityExplosion'ın bayt takasını bilmiyordu (protocol.py FIXES): istemcinin 3'ü 768 kaydedilmişti
            v = q['qualityExplosion']
            q['qualityExplosion'] = (v >> 8 & 0xFF) | (v << 8 & 0xFF00)
            self.dirty = True
        if q and not q.get('notSet') and q.get('qualityPresetting') == 3 and not any(
                q.get(k) for k in ('qualityShip', 'qualityEngine', 'qualityExplosion', 'qualityCollectables')):
            # H229'dan önce yeni profilin kalite modülü notSet gidiyordu: istemci atlayıp kendi öntanımlısıyla (ön ayar 3, gemi/motor/patlama/
            # toplanabilir 0) kaldı, Display'de Save'e basınca onu yolladı ve kaydedildi: motor izi hiç görünmüyordu, H229 yalnız notSet'e
            # bakıyordu (kullanıcı bildirimi 2026-10-26). Ön ayar 3 iken dördünün birden 0 olması arayüzden oluşmaz (Düşük ön ayar hepsini
            # ve ön ayarı 0 yapar): istemcinin öntanımlısının imzası, onarılır.
            q.update(qualityShip=3, qualityEngine=3, qualityExplosion=3, qualityCollectables=3)
            self.dirty = True
        if self.d['gemi'].pop('galaxyGatesDone', None) is not None:     # eski kapı sayacı: halkalar artık kapılardan (kapi.rings)
            self.dirty = True
        self.add_windows()
        self.sync_ekipman()

    def add_windows(self):
        """Kayıttaki arayüzde olmayan yeni pencerelerin menü öğeleri (NEW_WINDOWS), Return of Hero öğesinin yanına."""
        for bar in self.d.get('arayuz', {}).get('featureBars', []):
            items = bar.get('featureBarItems', [])
            ref = next((it for it in items if it.get('itemId') == 'return_of_hero'), None)
            if not ref:
                continue
            have = {it.get('itemId') for b in self.d['arayuz']['featureBars'] for it in b.get('featureBarItems', [])}
            for item_id, (title, w, h) in NEW_WINDOWS.items():
                if item_id in have:
                    continue
                it = json.loads(json.dumps(ref))
                it.update(itemId=item_id, windowTitle=title, width=w, height=h, maximized=False, visible=False)
                for m in it['toolTip']['commandList']:
                    m['baseKey'] = title
                items.insert(items.index(ref) + 1, it)
                self.dirty = True

    def _metin(self):
        """Dosyaya yazılacak JSON (çoklu istemcinin ek oyuncusu asıl kimliğe çevirir: cok_oyunculu.YerelProfil)."""
        return json.dumps(self.d, ensure_ascii=False, indent=1)

    def save(self, force=False):
        with self.lock:
            if not (self.dirty or force):
                return
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            # dünya ve oturum profile kilitsiz yazıyor: kodlama sürerken sözlüğün boyu değişirse ("dictionary changed size during
            # iteration") yeniden denenir; dosyaya ancak metin tamamlanınca yazılır
            for k in range(5):
                try:
                    text = self._metin()
                    break
                except RuntimeError:
                    if k == 4:
                        raise
                    time.sleep(0.01)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf8') as fp:
                fp.write(text)
                fp.flush()
                os.fsync(fp.fileno())           # elektrik kesintisinde yarım/boş profil kalmasın
            # Windows: hedef dosya o an başka süreçte açıksa (virüs tarayıcısı, yedekleme) os.replace "Erişim engellendi" verir;
            # birkaç kez yeniden denenir (canlı: 10 sn'lik kayıt hatası oturumu düşürmüştü)
            for k in range(6):
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if k == 5:
                        raise
                    time.sleep(0.05 * (k + 1))
            self.dirty = False

    # ---------------------------------------------------------------- üretim
    @property
    def user_id(self):
        return self.d['pilot']['userId']

    def ship_init(self):
        f = dict(DEFAULT_SHIP_INIT)
        f.update(self.tohum.get('ShipInitializationCommand') or {})
        f.update(self.d['pilot']); f.update(self.d['gemi']); f.update(self.d['konum'])
        f['premium'] = self.premium      # Profile yazılmaz
        import kapi as KAPI
        f['galaxyGatesDone'] = KAPI.rings(self)     # kapı halkaları: tamamlanan kapıların bit maskesi
        if getattr(self, 'captain_energy', None):
            f.update(self.captain_energy())                  # takılı N.O.V.A.'nın enerjisi (nova.py)
        f['refreshMap'] = True   # ilk girişte gemiyi kur ve haritaya geç
        import gm_konsol as GMK
        if GMK.enabled(self):
            f['dailyRank'] = GMK.ADMIN_RANK  # GM konsolu (Ö2): istemci yöneticiyi dailyRank 6000 ile tanıyor (UnitFactory.InitMyUnit)
        import yonetici_modu as YM
        if YM.acik(self):                    # yönetici modu: rozet ve yönetici gemisinin görünümü (değerler kendi geminin)
            f['dailyRank'] = YM.ROZET
            f['typeId'] = YM.gemi(self) or f['typeId']
        return f

    def beacon(self, station=None, near_gate=False, pos=None, repairing=False, gate_peace=False, radiation=False, void=False):
        b = dict(self.tohum.get('BeaconCommand') or {})
        rep = next((e for e in EK.equipped(self) if e.startswith('equipment_extra_repbot_')), None)      # dronda takılı robot da sayılır
        b['repairRobotActive'] = repairing
        b['repairBotSkilled'] = YETENEK.maxed(self, '13')       # Engineering 5/5: mavi tamir robotu (resmî SSS)
        if rep:
            b['repairRobotLootId'] = rep
        x, y = pos if pos else (self.d['konum']['x'], self.d['konum']['y'])
        b.update(positionX=int(x), positionY=int(y), positionAheadX=int(x), positionAheadY=int(y), inRadiationZone=radiation,
                 nearJumpGate=near_gate)
        inside = False
        if station:
            r = station.get('peaceRadius', 0)
            inside = (x - station['posX']) ** 2 + (y - station['posY']) ** 2 <= r * r
        b.update(inPeaceArea=bool((inside and station.get('pvpPeace', True)) or gate_peace) and not void, inStation=inside)     # portal çevresi de güvenli (kayıt), istasyon değil
        return b

    def generate(self, marker, station=None):
        """Şablondaki @işaret -> (mesaj adı, alanlar)."""
        if marker == '@gemi':
            return 'ShipInitializationCommand', self.ship_init()
        if marker == '@ayarlar':
            a = self.d['ayarlar']
            q = a.get('qualitySettingsModule') or {}
            if q.get('notSet'):
                # kalite hiç kaydedilmemiş (yeni profil): istemci modülü atlıyor, öntanımlısı 0; motor izi (ShipAsset.SetEngineVisible:
                # QualityEngine > 0) bütün gemilerde kapalı kalıyordu (kullanıcı bildirimi 2026-10-24). Yüksek ön ayar gider, oyuncu
                # değiştirince QualitySettingsRequest kaydedilir.
                high = {k: 3 for k in q if k.startswith('quality') and k != 'qualityCustomized'}
                a = dict(a, qualitySettingsModule=dict(q, notSet=False, qualityCustomized=False, **high))
            return 'UserSettingsCommand', a
        if marker == '@tuslar':
            return 'UserKeyBindingsUpdate', {'changedKeyBindings': self.d['tus_atamalari']}
        if marker == '@arayuz':
            # P.E.T. penceresinin çubuk öğesi P.E.T. varsa görünür (kayıttaki hesapta P.E.T. yoktu: visible false)
            ui = json.loads(json.dumps(self.d['arayuz']))
            for bar in ui.get('featureBars', []):
                for it in bar.get('featureBarItems', []):
                    if it.get('itemId') == 'pet':
                        it['visible'] = bool(self.d.get('pet'))
                    if it.get('itemId') in MODE_WINDOWS:          # Aşama 8'in modları (pve_modlari.py): pencereleri hep görünür
                        it['visible'] = True
                    if it.get('itemId') in EVENT_WINDOWS:         # etkinlik pencereleri etkinlik sürerken (canlı test H47)
                        it['visible'] = event_window_visible(it['itemId'], hooks=self.window_hooks)
                    if it.get('itemId') in CLOSED_AT_LOGIN:
                        it['maximized'] = False
                    if it.get('itemId') in HIDDEN_WINDOWS:
                        it['visible'] = False
            # üst satırın sağı ve solu aynı satırda: sola sığmayan simgeler istemcide hiç görünmüyor (1280 genişlikte 21 simge;
            # canlı test H45: Voyagers, NPC etkinliği, Rogue-Lite, R-Zone erişilemiyordu). Mod pencereleri ikinci satıra (tür 3).
            bars = {b.get('featureBarType'): b for b in ui.get('featureBars', [])}
            if 1 in bars and 3 in bars:
                second = set(MODE_WINDOWS) | set(EVENT_WINDOWS)
                moving = [it for it in bars[1]['featureBarItems'] if it.get('itemId') in second]
                bars[1]['featureBarItems'] = [it for it in bars[1]['featureBarItems'] if it.get('itemId') not in second]
                bars[3]['featureBarItems'] = bars[3]['featureBarItems'] + moving
            ws = self.bar_layout()
            for bar in ui.get('featureBars', []):          # oyuncunun sürüklediği özellik çubukları (WindowSettingsRequest)
                pos, order = FEATURE_BAR_KEYS.get(bar.get('featureBarType'), (None, None))
                if pos and ws.get(pos):
                    bar['featureBarPosition'] = ws[pos]
                if order and _layout_ok(ws.get(order)):
                    bar['featureBarOrder'] = str(ws[order])
            return 'UILayoutCommand', ui
        if marker == '@madenler':
            return 'AttributeOreCountUpdateCommand', {'oreCountList': self.d['madenler']}
        if marker == '@formasyon':
            return 'DroneFormationChangeCommand', {'uid': self.user_id, 'selectedFormationId': self.d['formasyon']}
        if marker == '@giris_yaniti':
            return 'LoginResponse', {'status': 0}
        if marker == '@isaret':
            portalda = bool(self.d['konum'].get('portalda'))
            return 'BeaconCommand', self.beacon(station, near_gate=portalda, gate_peace=portalda)
        return None

    def bar_layout(self):
        """Arayüz yapılandırmasında sürüklenen çubukların konumları (WindowSettingsRequest -> ayarlar.windowSettingsModule)."""
        return self.d.get('ayarlar', {}).get('windowSettingsModule') or {}

    def window_item(self, item_id):
        """Menü öğesinin şimdiki hâli (WindowItemCommand alanları) ya da None."""
        _, ui = self.generate('@arayuz')
        return next(({k: v for k, v in it.items() if k != '_'} for bar in ui.get('featureBars', [])
                     for it in bar.get('featureBarItems', []) if it.get('itemId') == item_id), None)

    def event_window_items(self):
        """Etkinlik pencerelerinin menü öğeleri, şimdiki görünürlükle: oyun sürerken takvim değişince WindowItemCommand olarak
        (istemcinin işleyicisi öğenin görünürlüğünü yazar; maximized=False ile pencereyi yalnız kapatır, açmaz)."""
        _, ui = self.generate('@arayuz')
        return [('WindowItemCommand', dict({k: v for k, v in it.items() if k != '_'}, maximized=False))
                for bar in ui.get('featureBars', []) for it in bar.get('featureBarItems', [])
                if it.get('itemId') in EVENT_WINDOWS and it.get('itemId') not in OWN_SYNC]

    # ---------------------------------------------------------------- oyun içi değişiklikler (dünya simülasyonu)
    def gain(self, ep=0, onur=0, kredi=0, uridyum=0, neden=None, detay='', adet=0):
        """Ödülleri ekler -> yeni toplamlar ve seviye (EP tablosu: data/seviyeler.json). Uzaylı ödülünün kredisinden klanın vergisi
        kasaya (klan.vergi; kilitten önce: klan kaydının kilidi)."""
        if kredi > 0 and neden == 'bonus_abschussAlien' and self.d['pilot'].get('clanId'):
            import klan as KL
            kredi -= KL.vergi(self, kredi)
        with self.lock:
            p = self.d['pilot']
            p['ep'] = p.get('ep', 0) + ep
            p['honourPoints'] = p.get('honourPoints', 0) + onur
            p['credits'] = p.get('credits', 0) + kredi
            p['uridium'] = p.get('uridium', 0) + uridyum
            old = p.get('level', 1)
            p['level'] = max(old, level_for(p['ep']))
            self.dirty = True
            tot = dict(ep=p['ep'], onur=p['honourPoints'], kredi=p['credits'], uridyum=p['uridium'], seviye=p['level'],
                       seviye_atladi=p['level'] > old)
        if neden:                                  # hesap geçmişi (rutbe.py): istemcinin açıklama anahtarı
            RT.money(self, 'kredi', kredi, neden, detay, adet)
            RT.money(self, 'uridyum', uridyum, neden, detay, adet)
        if uridyum > 0:
            BANK.accrue(self, uridyum, neden)       # Uridium Bank: kazanılan uridyumun aynısı birikir (banka.py)
        self.ach('gain', ep=ep, onur=onur, kredi=kredi, uridyum=uridyum)
        if tot['seviye_atladi']:
            self.ach('level', deger=tot['seviye'])
        return tot

    def add_ores(self, ores):
        """{cevher türü: adet} ekler -> güncel OreCountModule listesi."""
        with self.lock:
            cur = {m['oreType']['typeValue']: m['count'] for m in self.d['madenler']}
            for t, n in ores.items():
                cur[int(t)] = cur.get(int(t), 0) + n
            self.d['madenler'] = [{'_': 'OreCountModule', 'oreType': {'_': 'OreTypeModule', 'typeValue': t}, 'count': n}
                                  for t, n in sorted(cur.items()) if n > 0]
            self.sync_cargo()
            self.dirty = True
            return self.d['madenler']

    def remove_ores(self, ores):
        """{cevher türü: adet} çıkarır (satış) -> güncel liste; biten tür listeden düşer (kayıt: satıştan sonraki liste)."""
        return self.add_ores({t: -n for t, n in ores.items()})

    def ore_count(self, t):
        return next((m['count'] for m in self.d['madenler'] if m['oreType']['typeValue'] == int(t)), 0)

    def cargo_used(self):
        """Kargodaki cevherler (her biri 1 birim; kayıt: 73 cevherle boş alan 400 -> 327). Xenomit ve etkinlik malzemeleri sayılmaz."""
        return sum(m['count'] for m in self.d['madenler'] if m['oreType']['typeValue'] in self.CARGO_ORES)

    def cargo_free(self):
        import ayar as AY
        if AY.get('sonsuz_kargo'):
            return 10 ** 6                        # kargo hiç dolmaz (panel: Sonsuz kargo)
        return max(0, self.d['gemi'].get('cargoSpaceMax', 0) - self.cargo_used())

    def sync_cargo(self):
        """ShipInitializationCommand.cargoSpace = boş kargo alanı (kayıt)."""
        self.d['gemi']['cargoSpace'] = min(self.cargo_free(), self.d['gemi'].get('cargoSpaceMax', 0))      # istemci en çok azami alanı gösterir

    # ---------------------------------------------------------------- kaynak deposu (diger_esyalar)
    def resource(self, loot):
        """Depodaki kaynak (Assembly malzemeleri, anahtarlar, kuponlar, Bifenon …; lootId) adedi."""
        return self.d.get('diger_esyalar', {}).get(loot, 0)

    def add_resource(self, loot, n):
        """Depoya ekle (n < 0 çıkarır, sıfırın altına inmez; istemcinin yığın sınırını aşan kısım kaybolur: resmî forum 150401
        "maksimum tutarı aşan kaynaklar kaybolacaktır", istemci_esyalari.json yigin) -> yeni adet."""
        cap = stack_cap(loot)
        with self.lock:
            d = self.d.setdefault('diger_esyalar', {})
            d[loot] = max(0, d.get(loot, 0) + n)
            if n > 0 and cap and d[loot] > cap:
                d[loot] = max(cap, d.get(loot, 0) - n)       # zaten sınırın üstündeyse (eski kayıt) azaltmaz
            if not d[loot]:
                del d[loot]
            self.dirty = True
            return d.get(loot, 0)

    def spend_resources(self, need):
        """{lootId: adet} hepsi varsa birlikte harcanır -> True; biri yetmezse hiçbiri (Assembly tarifleri, anahtarlı kutular)."""
        with self.lock:
            d = self.d.setdefault('diger_esyalar', {})
            if any(d.get(k, 0) < n for k, n in need.items()):
                return False
            for k, n in need.items():
                d[k] -= n
                if not d[k]:
                    del d[k]
            self.dirty = True
            return True

    def add_ammo(self, loot_id, n):
        with self.lock:
            c = self.d.setdefault('cephane', {})
            c[loot_id] = c.get(loot_id, 0) + n
            self.dirty = True
            return c[loot_id]

    def ammo(self, loot_id):
        return self.d['cephane'].get(loot_id, 0)

    def use_ammo(self, loot_id, n=1, event=True):
        """n adet harca; yetmezse None. event=False: 'ammo' olayı yayılmaz (envanter.spend ödemesi kendi 'spend' olayını yayar)."""
        with self.lock:
            have = self.d['cephane'].get(loot_id, 0)
            if have < n:
                return None
            import ayar as AY
            used = 0 if AY.get('sonsuz_cephane') else n     # panel: sonsuz cephane (harcanmaz)
            self.d['cephane'][loot_id] = have - used
            self.dirty = True
        if event:
            # Quests/Pass count what would have been used, even with infinite ammo
            self.ach('ammo', loot=loot_id, adet=n)          # Pass görevleri: cephane harca (gorev_takip.py)
        return have - used

    def item_id(self, loot_id):
        """InventoryItemModule.itemId: kayıttaki kimlik, yoksa lootId'den türetilen kararlı sayı."""
        iid = self.d['esya_kimlik'].get(loot_id)
        if iid is None:
            import zlib
            iid = 900000000 + zlib.crc32(loot_id.encode()) % 90000000
        return iid

    # ---------------------------------------------------------------- hangar: ekipman örnekleri ve config'ler
    def _add_item(self, loot_id):
        """Yeni ekipman örneği (her lazer/jeneratör/ekstra ayrı itemId taşır) -> itemId."""
        iid = self.d.get('sonraki_kimlik') or max([int(i) for i in self.d['esyalar']] + [99000000]) + 1
        self.d['sonraki_kimlik'] = iid + 1
        self.d['esyalar'][str(iid)] = loot_id
        self.dirty = True
        return iid

    def new_item(self, loot_id, level=1):
        with self.lock:
            iid = self._add_item(loot_id)
            if level > 1:
                self.d.setdefault('esya_seviye', {})[str(iid)] = level
            return iid

    def item_level(self, iid):
        """Eşyanın seviyesi (P.E.T. dişlisi/protokolü 1-4; diğerleri 1)."""
        return self.d.get('esya_seviye', {}).get(str(iid), 1)

    def ship(self, sid=None):
        """Gemi kaydı: lootId, hangarId, iki config, etkin config, saklanan gövde. Varsayılan: etkin gemi."""
        return self.d['gemiler'][str(sid or self.d['aktif_gemi'])]

    def ship_look(self, sid=None):
        """Geminin görünümü: giyilen tasarım (ör. ship_goliath_design_amber) ya da geminin kendisi. ShipInitializationCommand.typeId
        bu olur (kayıtta başka oyuncular tasarım lootId'siyle görünüyor: ship_diminisher_design_diminisher-carbonite)."""
        s = self.ship(sid)
        return s.get('tasarim') or s['lootId']

    def ship_row(self, sid=None):
        """Geminin değerleri (esyalar.json gemiler: hp, yuvalar, temel_hiz, bonus …) giyilen tasarımın kendi değerleriyle
        (esyalar.json tasarimlar <- tools/tasarim_degerleri.py: Centurion'un hız ve yuva tasarımları, Holo'nun canı; bonusu
        geminin bonusuna eklenir)."""
        s = self.ship(sid)
        row = esya()['gemiler'].get(s['lootId'], {})
        over = esya().get('tasarimlar', {}).get(s.get('tasarim') or '')
        if not over or not row:
            return row
        out = dict(row, **{k: v for k, v in over.items() if k != 'bonus'})
        bonus = dict(row.get('bonus', {}))
        for k, v in over.get('bonus', {}).items():
            bonus[k] = bonus.get(k, 0) + v
        if bonus:
            out['bonus'] = bonus
        return out

    def ship_by_hangar(self, hangar_id):
        return next((sid for sid, s in self.d['gemiler'].items() if s['hangarId'] == hangar_id), None)

    @property
    def aktif_konfig(self):
        return self.ship()['aktif_konfig']

    def config(self, cid=None, sid=None):
        s = self.ship(sid)
        return s['konfigler'].setdefault(str(cid or s['aktif_konfig']), {})

    def equipped_ids(self):
        """Herhangi bir geminin herhangi bir config'inde takılı eşya kimlikleri."""
        return set(self.hangar_map())

    def hangar_map(self):
        """itemId -> takılı olduğu geminin hangarId'si (envanterde hangarId dolu görünür; takılı değilse 0). Gemi yuvaları, dronlara
        takılılar, dron tasarımları ve P.E.T. donanımı; hepsi takıldığı gemiye (hangara) bağlı."""
        return {i: s['hangarId'] for sid, s in self.d['gemiler'].items() for i in self.ship_items(sid)}

    def item_places(self):
        """itemId -> (ship id, set of config ids) where it is equipped. The game lets one item sit in several configs of the same
        ship (magaza.move only refuses another ship), so the panel shows these items for the other configs."""
        out = {}
        for sid, s in self.d['gemiler'].items():
            cids = set(s['konfigler']) | set(s.get('dron_konfig', {})) | set(s.get('dron_tasarim', {})) | set(s.get('pet_konfig', {}))
            for cid in cids:
                for i in self.ship_items(sid, cid):
                    out.setdefault(i, (sid, set()))[1].add(str(cid))
        return out

    def ship_items(self, sid=None, cid=None):
        """Bir geminin (cid verilirse yalnız o config'inin) takılı eşya kimlikleri: gemi yuvaları, dronlar, dron tasarımları, P.E.T."""
        s = self.ship(sid)
        cids = [str(cid)] if cid is not None else None
        pick = lambda cfgs: [v for c, v in cfgs.items() if cids is None or c in cids]
        out = [i for cfg in pick(s['konfigler']) for ids in cfg.values() for i in ids]
        out += [i for cfg in pick(s.get('dron_konfig', {})) for ids in cfg.values() for i in ids]
        out += [i for cfg in pick(s.get('dron_tasarim', {})) for per in cfg.values() for i in per.values() if i]
        out += [i for cfg in pick(s.get('pet_konfig', {})) for ids in cfg.values() for i in ids]
        return out

    def pet_config(self, cid=None, sid=None):
        """Bir geminin bir config'inde (varsayılan: etkin gemi, onun etkin config'i) P.E.T. yuvası -> takılı eşya kimlikleri."""
        s = self.ship(sid)
        return s.setdefault('pet_konfig', {}).setdefault(str(cid or s['aktif_konfig']), {})

    def loadout(self, sid=None, cid=None):
        """Bir geminin bir config'indeki ekipman: yuva -> lootId listesi."""
        cfg = self.config(cid, sid)
        return {slot: [self.d['esyalar'][str(i)] for i in cfg.get(slot, []) if str(i) in self.d['esyalar']]
                for slot in ('laser', 'generators', 'extra', 'rocket', 'upgrades')}

    def loadout_levels(self, sid=None, cid=None):
        """loadout() ile aynı sırada eşyaların yükseltme seviyeleri."""
        cfg, lv = self.config(cid, sid), self.d.get('yukseltme_seviye', {})
        return {slot: [int(lv.get(str(i), 0)) for i in cfg.get(slot, []) if str(i) in self.d['esyalar']]
                for slot in ('laser', 'generators', 'extra', 'rocket')}

    def drone_levels(self, sid=None, cid=None):
        """drone_loadout() sırasıyla [dron lootId, dronun yükseltme seviyesi, [takılı eşyaların seviyeleri]]."""
        cfg, lv = self.drone_config(cid, sid), self.d.get('yukseltme_seviye', {})
        return [[x['lootId'], int(x.get('yukseltme', 0)),
                 [int(lv.get(str(i), 0)) for i in cfg.get(str(x['kimlik']), []) if str(i) in self.d['esyalar']]]
                for x in self.d['dronlar']]

    # ---------------------------------------------------------------- dronlar
    def drone(self, drone_id):
        return next((x for x in self.d['dronlar'] if x['kimlik'] == int(drone_id)), None)

    def drone_config(self, cid=None, sid=None):
        """Bir geminin bir config'inde dron kimliği (metin) -> takılı eşya kimlikleri."""
        s = self.ship(sid)
        return s.setdefault('dron_konfig', {}).setdefault(str(cid or s['aktif_konfig']), {})

    def drone_loadout(self, sid=None, cid=None):
        """Dron sırasıyla [(dron kaydı, [lootId …])] (hasar ve kalkan hesabı)."""
        cfg = self.drone_config(cid, sid)
        return [(x, [self.d['esyalar'][str(i)] for i in cfg.get(str(x['kimlik']), []) if str(i) in self.d['esyalar']])
                for x in self.d['dronlar']]

    def lab_items(self):
        """LabUpdateItemCommand.itemsUpdatedInfo: her parçada yüklü cevher ve kalan miktar."""
        return [{'_': 'UpdateItemModule', 'itemToUpdate': {'_': 'LabItemModule', 'itemValue': int(k)},
                 'oreCountToUpdateWith': {'_': 'OreCountModule', 'oreType': {'_': 'OreTypeModule', 'typeValue': t}, 'count': n}}
                for k, (t, n) in sorted(self.d.get('yukseltmeler', {}).items())]

    def formation(self):
        """Seçili formasyonun bonusları (lazer, roket, kalkan, can, hiz, emme, kacinma, roket_bekleme, ep, onur)."""
        return _formations().get(formation_loot(self.d.get('formasyon', 0)), {})

    def drone_designs(self, cid=None, sid=None):
        """Bir geminin bir config'inde (varsayılan: etkin gemi, onun etkin config'i) dron kimliği (metin) -> {tasarim, gorunum}."""
        s = self.ship(sid)
        return s.setdefault('dron_tasarim', {}).setdefault(str(cid or s['aktif_konfig']), {})

    def drone_design_id(self, x, slot, cid=None, sid=None):
        """Dronun bir geminin bir config'indeki (varsayılan: etkin) tasarımı ('design', bonuslu) ya da görünümü ('visual') -> eşya
        kimliği."""
        s = self.ship(sid)
        return s.get('dron_tasarim', {}).get(str(cid or s['aktif_konfig']), {}).get(str(x['kimlik']), {}).get(DESIGN_KEYS[slot])

    def set_drone_design(self, x, slot, iid, cid=None, sid=None):
        """Dronun tasarım/görünüm yuvasına eşya (None: boşalt)."""
        per = self.drone_designs(cid, sid)
        if iid:
            per.setdefault(str(x['kimlik']), {})[DESIGN_KEYS[slot]] = iid
            return
        cur = per.get(str(x['kimlik']), {})
        cur.pop(DESIGN_KEYS[slot], None)
        if not cur:
            per.pop(str(x['kimlik']), None)

    def drone_design(self, x, slot, cid=None, sid=None):
        """drone_design_id'nin lootId'si."""
        iid = self.drone_design_id(x, slot, cid, sid)
        return self.d['esyalar'].get(str(iid)) if iid else None

    def design_mods(self, cid=None, sid=None):
        """Bir config'in (varsayılan: etkin gemi, etkin config) dron tasarımlarının bonusları: dron başına olanlar toplanır; sahip
        olunan bütün dronlar aynı tasarımı taşıyorsa takım bonusu da (istemci metinleri: Havoc +%10 dron lazeri (dron_lazer), Hercules
        +%20 can …; Havoc: "If all of the drones are equipped"). Görünüm yuvasındaki etkinlik tasarımları (Champion/Eostra: Goal Rush,
        Apocalypse Booty Box) etkinlik sürerken takılı başına geçici NPC lazer hasarı verir (etkinlik_basina)."""
        designs = esya()['dron_tasarimlari']
        looks = [self.drone_design(x, 'design', cid, sid) for x in self.d.get('dronlar', [])]
        out = {}
        for l in looks:
            for k, v in designs.get(l or '', {}).get('dron_basina', {}).items():
                out[k] = out.get(k, 0) + v
        grp = lambda l: designs.get(l or '', {}).get('takim_grubu', l)     # Demon Gümüş ve Epic karışık da "tüm dronlar Demon" (forum 127526)
        if looks and looks[0] and len({grp(l) for l in looks}) == 1:
            for k, v in designs.get(looks[0], {}).get('takim', {}).items():
                out[k] = out.get(k, 0) + v
        for x in self.d.get('dronlar', []):          # görünüm tasarımının etkinlikteki geçici bonusu (Goal Rush, Apocalypse: NPC lazer)
            e = designs.get(self.drone_design(x, 'visual', cid, sid) or '', {}).get('etkinlik_basina')
            if e and event_on(e['etkinlik']):
                out['npc_lazer'] = out.get('npc_lazer', 0) + e['npc_lazer']
        return out

    def mods(self):
        """Formasyon + dron tasarımı bonusları (lazer, roket, npc, kalkan, can, hiz, emme, kacinma, isabet, roket_bekleme, ep, onur)."""
        out = {k: v for k, v in self.formation().items() if k != 'id'}
        for k, v in (list(self.design_mods().items()) + list(BOOSTER.mods(self).items())     # + boosterlar (booster.py)
                     + list(self.ship_mods().items())                                           # + gemi/tasarım bonusu
                     + list(YETENEK.mods(self).items())                                         # + pilot yetenekleri (yetenek.py)
                     + list(GY.mods(self).items())                                              # + etkin gemi yetenekleri
                     + list((self.pet_mods() if getattr(self, 'pet_mods', None) else {}).items())         # + P.E.T. HEAT (pet.py)
                     + list((self.world_mods() if getattr(self, 'world_mods', None) else {}).items())     # + durum etkileri
                     + list((self.mode_mods() if getattr(self, 'mode_mods', None) else {}).items())      # + mod boosterları (ebl.py)
                     + list((self.nova_mods() if getattr(self, 'nova_mods', None) else {}).items())    # + N.O.V.A. (nova.py)
                     + list((self.event_mods() if getattr(self, 'event_mods', None) else {}).items())    # + Fever (fever.py)
                     + list((self.cbs_mods() if getattr(self, 'cbs_mods', None) else {}).items())):    # + CBS boosterları (cbs.py)
            out[k] = min(out.get(k, v), v) if k in ('sabit_hiz', 'azami_hiz') else out.get(k, 0) + v
        if out.get('kacinma', 0) > 0.75:                 # resmî forum 160373: kaçınma en çok %75
            out['kacinma'] = 0.75
        if out.get('bekleme', 0) > 0.75:                 # forum 127074: bekleme kısaltması en çok %75 (yetenek)
            out['bekleme'] = 0.75
        for k in ('roket_bekleme', 'fircatici_bekleme', 'mayin_bekleme', 'top_bekleme'):
            if out.get(k, 0) < -0.75:
                out[k] = -0.75
        return out

    def ship_mods(self):
        """Etkin geminin kalıcı bonusu (pasifler: Cyborg +%10 hasar, Solaris Plus modül başına …; tasarım türevleri: G-Enforcer +%5
        hasar …; giyilen tasarımınki: Tyrannos), Orcus'un modül çarpanı ve Leonov'un kendi X-1..X-4'ündeki bonusu (esyalar.json)."""
        row = self.ship_row()
        out = dict(row.get('bonus', {}))
        n = min(len(self.config().get('upgrades', [])), row.get('modul_azami', 0))
        for k, v in row.get('modul_basina', {}).items():
            out[k] = out.get(k, 0) + v * n
        hp = LAZER.hp_bonus(self.d.get('ekipman', {}).get('laser', [])       # LF-4 Hyperplasmoid: lazer başına can +%0,5 (dronlarda da)
                            + [l for _, loots in self.d.get('dron_ekipman', []) for l in loots])
        if hp:
            out['can'] = out.get('can', 0) + hp
        kj = esya()['kalkan_jeneratorleri']                                  # Fusion Shield: takılı başına kalkan yenilenmesi +%6,25
        gens = self.d.get('ekipman', {}).get('generators', []) + [g for _, loots in self.d.get('dron_ekipman', []) for g in loots]
        reg = sum(kj.get(g, {}).get('yenilenme', 0) for g in gens)
        if reg:
            out['kalkan_yenilenme'] = out.get('kalkan_yenilenme', 0) + reg
        launchers = esya()['savas_esyalari']['fircatici']['turler']         # Plus fırlatıcılar: Hydra can/kalkan, Neptune hasar …
        for l in self.d.get('ekipman', {}).get('rocket', []):
            for k, v in launchers.get(l, {}).get('bonus', {}).items():
                out[k] = out.get(k, 0) + v
        import gemi_modul as GM                                              # gemi modülleri (normal ve kararsız)
        mk = row.get('modul_carpani', 1)                                     # Orcus: modül nitelikleri x1,75 (eksiler de)
        for k, v in GM.mods(self, self.ship()['lootId'], self.config().get('upgrades', []), self.d['pilot'].get('level')).items():
            out[k] = out.get(k, 0) + v * mk
        import qfc as QF                                                      # Quantum Fluid Core'lar (bağlı oldukları gemide)
        for k, v in QF.mods(self, self.ship()['lootId'], self.config().get(QF.SLOT, [])).items():
            out[k] = out.get(k, 0) + v
        import parcacik as PC                                                 # sürücü/merceğin alt nitelikleri (EP, onur, kaçınma)
        for k, v in PC.mods(self, self.ship()['lootId'], self.config()).items():
            out[k] = out.get(k, 0) + v
        hb = row.get('harita_bonusu')
        m = self.d['konum'].get('mapId', 0)
        if hb and H.map_class(m) in hb['haritalar'] and H.company(m) == self.d['pilot'].get('factionId'):    # Leonov: kendi firmasında
            for k, v in hb['bonus'].items():
                out[k] = out.get(k, 0) + v
        return out

    def lab_bonus(self, item):
        """Cevher yükseltmesinin bonusu (lazer/roket hasarı, hız, kalkan); yükseltme yoksa 0."""
        u = self.d.get('yukseltmeler', {}).get(str(item))
        return lab_data()['bonuslar'][str(item)].get(str(u[0]), 0) if u and u[1] > 0 else 0

    def lab_use(self, item, n=1):
        """Yükseltmeden n birim harcar -> True: bitti."""
        with self.lock:
            u = self.d.get('yukseltmeler', {}).get(str(item))
            if not u:
                return False
            u[1] -= n
            self.dirty = True
            if u[1] <= 0:
                del self.d['yukseltmeler'][str(item)]
                return True
            return False

    def add_drone(self, loot_id):
        """Yeni dron (seviye 1, 0 puan) -> dron kimliği."""
        with self.lock:
            did = self.d.get('sonraki_dron', 1)
            self.d['sonraki_dron'] = did + 1
            self.d['dronlar'].append({'kimlik': did, 'lootId': loot_id, 'seviye': 1, 'puan': 0})
            self.dirty = True
            return did

    def sync_ekipman(self):
        """Etkin geminin etkin config'inden lootId listeleri (dünya simülasyonu hasar/onarım için bunları okur).
        dron_ekipman: [[dron seviyesi, [lootId …]] …]."""
        self.d['ekipman'] = self.loadout()
        self.d['dron_ekipman'] = [[x['seviye'], loots] for x, loots in self.drone_loadout()]
        self.d['ekipman_seviye'] = self.loadout_levels()          # yükseltme seviyeleri (yukseltme.py), aynı sırada
        self.d['dron_ekipman_seviye'] = self.drone_levels()

    def add_ship(self, loot_id):
        """Yeni gemi (boş iki config) -> shipId. Kimlikler kayıttakilerin ardından verilir."""
        with self.lock:
            g = self.d['gemiler']
            sid = max(int(k) for k in g) + 1
            hid = max(s['hangarId'] for s in g.values()) + 1
            g[str(sid)] = {'lootId': loot_id, 'hangarId': hid, 'konfigler': {'1': {}, '2': {}}, 'aktif_konfig': 1, 'favori': False,
                           'dron_konfig': {'1': {}, '2': {}}}
            self.dirty = True
            return sid

    def menu_status(self, menu_id):
        """Kısayol çubuğu öğesinin güncel durumu (MenuItemStatusCommand): sayaç, seçili, kullanılabilir."""
        base = self.menu_status_cache.get(menu_id)
        if base is None:
            return None
        st = json.loads(json.dumps(base))
        if menu_id.startswith('drone_formation_'):
            # kayıtta: standart görünür ve seçili; sahip olunmayanlar görünmez, ipucunda ttip_item_not_owned
            owned = menu_id == 'drone_formation_default' or menu_id in self.d.get('formasyonlar', [])
            sel = formation_id(menu_id) == self.d.get('formasyon', 0)
            enough = formation_drones_ok(self, menu_id)
            st.update(visible=owned, available=owned and enough, activatable=owned and enough, selected=owned and sel)
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                lines = (st.get(tip) or {}).get('commandList')
                if owned and lines:
                    lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_item_not_owned']
            if owned and not enough:             # Arrow/Dome 4, Heart/Pincer 6 dron ister (wiki; istemci ttip_inactive_not_enough_drones)
                SE._tips(st, [SE._line('ttip_inactive_not_enough_drones')])
            return st
        if menu_id.startswith('ability_'):
            return GY.menu_status(self, menu_id, st)          # yalnız etkin geminin yetenekleri (gemi_yetenek.py)
        out = SE.menu_status(self, menu_id, st)        # mayınlar, Smart Bomb, Insta-Shield, CPU'lar, fırlatıcı (savas_esya.py)
        if out is None and menu_id.startswith('tech_'):
            out = TK.menu_status(self, menu_id, st)        # teknoloji eşyaları (teknoloji.py)
        if out is not None:
            return out
        if menu_id.startswith('ammunition_'):
            n = self.ammo(menu_id)
            kind = SE.ammo_kind(menu_id)
            # kayıttaki hesapta olmayan cephaneler (R-IC3, SR-5, RSB dışı lazerler …) şablonda gizli: eldeyse görünür (canlı test H26)
            st.update(counterValue=n, counterStyle=4 if n > 0 else 1, available=n > 0, activatable=n > 0,
                      selected=bool(kind) and self.d['secili'].get(kind) == menu_id,
                      visible=bool(st.get('visible')) or n > 0)
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                for line in (st.get(tip) or {}).get('commandList', []):
                    for rep in line.get('wildCardReplacements', []):
                        if rep.get('wildcard') == '%COUNT%':
                            rep['replacement'] = str(n)
        return st

    def patch_template(self, name, fields):
        """Şablondan gelen mesajı profile göre güncelle: kısayol menüsündeki cephane sayaçları, ekipmana bağlı hız ve config."""
        if name == 'AttributeShipSpeedUpdateCommand':
            g = self.d['gemi']
            return dict(fields, newSpeed=g.get('speed', fields['newSpeed']), displaySpeed=self.d.get('gosterilen_hiz', fields['displaySpeed']))
        if name == 'LabUpdateItemCommand':
            return dict(fields, itemsUpdatedInfo=self.lab_items())
        if name == 'DailyLoginRewardDayCommand' and self.daily_fields:
            return dict(fields, **self.daily_fields())      # kayıttaki "gün 0" yerine profilin takvimi
        if name == 'AttributeBoosterUpdateCommand':
            return BOOSTER.update_cmd(self)[1]          # kayıttaki boş bilgi yerine profilin boosterları
        if name == 'PetInitializationCommand':
            pet = self.d.get('pet')       # P.E.T. penceresinin düğmeleri (pet.py)
            return dict(fields, hasPet=bool(pet), hasFuel=bool(pet) and pet['yakit'] > 0, petIsAlive=bool(pet) and not pet['yikik'])
        if name == 'CPUInitializationCommand':                 # uzay haritasının atlama paneli (AJP-01)
            self.cpu_init_sent = dict(fields, advancedJumpCPUEquipped=SE.has_ajp(self))
            return dict(self.cpu_init_sent)
        if name == 'LegacyModule' and fields.get('message', '').startswith('0|n|INV|'):
            parts = fields['message'].split('|')                # gizlenme CPU'suyla gizliyken girişte gizli
            return dict(fields, message='0|n|INV|%s|%d' % (parts[3], 1 if self.d.get('cpu_gizli') else 0))
        if name == 'InvitationBlockModule':                     # grup daveti engeli (kayıttaki false yerine profilin seçimi)
            return dict(fields, active=bool(self.d.get('davet_engeli')))
        if name == 'LegacyModule' and fields.get('message', '').startswith('0|S|CFG|'):
            return dict(fields, message='0|S|CFG|%s' % self.aktif_konfig)
        if name == 'LegacyModule' and fields.get('message', '').startswith('0|A|JV|'):
            return dict(SE.vouchers_msg(self)[1])                # AJP-01 kupon sayısı (kayıttaki 0 yerine)
        if name == 'WindowItemCommand':
            # menü öğesinin profildeki yeri ve görünürlüğü (kayıttaki yer; etkinlik pencereleri kayıtta görünmez geliyordu), kapalı
            cur = self.window_item(fields.get('itemId'))
            return dict(fields, **{k: cur[k] for k in ('posX', 'posY', 'width', 'height', 'visible') if k in cur}, maximized=False)                 if cur else fields
        if name != 'MenuInitializationCommand':
            return fields
        f = json.loads(json.dumps(fields))

        def walk(x):
            if isinstance(x, dict):
                if x.get('_') == 'MenuItemTimerCommand' and x.get('menuItemId') in GY.ABILITIES:
                    f_ = GY.timer_fields(self, x['menuItemId'])          # yeteneğin bekleme süresi (girişte, harita değişiminde)
                    x.update(activatable=f_['activatable'], maxTime=f_['maxTime'], time=f_['time'],
                             timerState={'_': 'TimerStateModule', 'timerStateValue': f_['timerState']})
                elif x.get('_') == 'MenuItemTimerCommand':
                    mid = x.get('menuItemId') or ''
                    f_ = (TK.timer_fields(self, mid) if mid in TK.ITEMS else None) or SE.timer_fields(self, mid)   # teknoloji, mayın …
                    if f_ and f_['timerState'] == TK.READY:
                        f_ = None
                    if f_:
                        x.update(activatable=False, maxTime=f_['maxTime'], time=f_['time'],
                                 timerState={'_': 'TimerStateModule', 'timerStateValue': f_['timerState']})
                if x.get('_') == 'MenuItemStatusCommand' and x.get('menuItemId'):
                    lines = (x.get('toolTipItemBar') or {}).get('commandList')
                    if x['menuItemId'].startswith('buy_') and lines is not None and                             not any(l.get('baseKey') == QUICK_BUY_TIP['baseKey'] for l in lines):
                        lines.append(json.loads(json.dumps(QUICK_BUY_TIP)))
                    self.menu_status_cache.setdefault(x['menuItemId'], json.loads(json.dumps(x)))
                    cur = self.menu_status(x['menuItemId'])
                    if cur:
                        x.update(cur)
                        self.menu_mark(cur)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(f)
        bars = f.setdefault('slotBars', [])
        have = {b.get('slotBarId') for b in bars}
        bars += [{'_': 'SlotBarInitializationCommand', 'slots': [], 'slotBarId': bid, 'slotBarOrder': '0', 'slotBarPosition': pos,
                  'visible': True} for bid, pos in PREMIUM_SLOT_BARS if bid not in have]      # herkes premium (H72, H81)
        ws = self.bar_layout()
        if ws.get('mainmenuPosition'):             # kategori çubuğu (yapılandırmada sürüklenen yeri)
            f['itemBarPosition'] = ws['mainmenuPosition']
        for bar in bars:                           # kısayol çubuğu: oyuncunun düzeni (slot_bar_set)
            cur = self.d.get('kisayol', {}).get(bar.get('slotBarId'))
            if cur is not None:
                bar['slots'] = [{'_': 'SlotInfoCommand', 'menuItemId': v, 'slotId': int(k)}
                                for k, v in sorted(cur.items(), key=lambda kv: int(kv[0]))]
            pos, order = SLOT_BAR_KEYS.get(bar.get('slotBarId'), (None, None))
            if pos and ws.get(pos):                # sürüklenen yer: yüzde konumu, kayma 0,0
                bar['slotBarPosition'] = ws[pos].split('|')[0] + '|0,0'
            if order and _layout_ok(ws.get(order)):
                bar['slotBarOrder'] = str(ws[order])
        return f

    def gameplay(self, key):
        """Ayarlar > Gameplay seçeneği (GameplaySettingsRequest -> ayarlar.gameplaySettingsModule). İstemci bu sekmeden yalnız çift
        tıklamayla saldırıyı kendisi uyguluyor; otomatik yükseltme, cephane değişimi, kısayolla saldırı, arıtma ve anahtar alımı
        sunucunun işi (SettingComponentSystem yalnız kaydedip gönderiyor). Ayar hiç gelmediyse kayıttaki varsayılan."""
        return bool((self.d.get('ayarlar', {}).get('gameplaySettingsModule') or {}).get(key, GAMEPLAY_DEFAULTS.get(key, False)))

    def menu_mark(self, st):
        """Bu durum istemciye gönderildi (menu_changes yeniden göndermesin)."""
        self.menu_sent[st.get('menuItemId')] = json.dumps(st, sort_keys=True)

    def menu_changes(self, ids=None):
        """Son bildirimden beri durumu değişen kısayol öğeleri -> MenuItemStatusCommand'lar. ids yoksa ekipmana bağlı öğeler
        (EQUIP_MENUS): takma/çıkarma, mağazadan takılı gelme, config ve gemi değişiminden sonra (canlı test H21: JP-01 takılınca
        çubukta görünmüyordu)."""
        out = []
        if ids is None:
            ids = sorted(m for m in self.menu_status_cache if m.startswith(EQUIP_MENUS))
            ajp = SE.has_ajp(self)
            if self.cpu_init_sent is not None and self.cpu_init_sent.get('advancedJumpCPUEquipped') != ajp:
                self.cpu_init_sent = dict(self.cpu_init_sent, advancedJumpCPUEquipped=ajp)      # uzay haritasının atlama paneli (H23)
                out.append(('CPUInitializationCommand', dict(self.cpu_init_sent)))
        for mid in ids:
            st = self.menu_status(mid)
            if st and self.menu_sent.get(mid) != json.dumps(st, sort_keys=True):
                self.menu_mark(st)
                out.append(('MenuItemStatusCommand', st))
        return out

    def slot_bar_set(self, f, bars):
        """SlotBarConfigSetRequest: öğe çubuğundan ya da bir çubuğun yuvasından bir yuvaya (doluysa yer değiştirir), hedefsiz
        bırakılırsa çubuktan çıkar. Aynı öğe bir çubukta birden çok yuvada olabilir: istemci de eski kopyayı silmiyor
        (UIBagHelper.PutDownItemNew) ve yeniden gönderilen menüde boşalan yuvayı temizlemiyor; sunucu silince ekranla ayrışıyordu
        (H83). bars: şablonun çubukları (ilk düzen). Kayıtta gerçek sunucu bunu MenuInitializationCommand'ı yeni yuvalarla yeniden
        göndererek yanıtlıyor. -> değişti mi"""
        item, src, dst = f.get('menuItemId') or '', f.get('slotBarIdFrom') or '', f.get('slotBarIdTo') or ''
        with self.lock:
            kb = self.d.setdefault('kisayol', {b['slotBarId']: {str(s['slotId']): s['menuItemId'] for s in b['slots']} for b in bars})
            for bid in {src, dst} & {b for b, _ in PREMIUM_SLOT_BARS}:
                kb.setdefault(bid, {})
            if not item or (dst and dst not in kb) or (src and src not in kb):
                return False
            sfrom, sto = str(f.get('slotIdFrom')), str(f.get('slotIdTo'))
            moved = bool(src) and kb[src].get(sfrom) == item
            if moved:
                del kb[src][sfrom]
            if dst:
                old = kb[dst].get(sto)
                kb[dst][sto] = item
                if moved and old and old != item:
                    kb[src][sfrom] = old
            self.dirty = True
            return True

    def slot_bar_state(self, bars):
        """Kısayol çubuklarındaki öğeler (görev koşulu PUT_ITEM_IN_SLOT_BAR; Ö1) -> {'items': {(çubuk, öğe)}, 'slots': {(çubuk, yuva,
        öğe)}}. bars: şablonun çubukları (profilde kısayol yoksa ilk düzen)."""
        kb = self.d.get('kisayol') or {b['slotBarId']: {str(s['slotId']): s['menuItemId'] for s in b['slots']} for b in bars}
        rows = [(bar, slot, item) for bar, slots in kb.items() for slot, item in slots.items() if item]
        return {'items': {(b, i) for b, s, i in rows}, 'slots': {(b, s, i) for b, s, i in rows}}

    def set_hull(self, hp=None, shield=None):
        with self.lock:
            g = self.d['gemi']
            if hp is not None:
                g['hitPoints'] = max(0, min(int(hp), g.get('hitMax', hp)))
            if shield is not None:
                g['shield'] = max(0, min(int(shield), g.get('shieldMax', shield)))
            self.dirty = True

    # ---------------------------------------------------------------- istemci istekleri
    def apply(self, name, f):
        """İstemcinin kalıcı durum isteğini profile yazar; işlendiyse True."""
        with self.lock:
            if name in SETTINGS_REQUESTS:
                mod = self.d['ayarlar'].setdefault(SETTINGS_REQUESTS[name], {})
                mod.update({k: v for k, v in f.items() if not k.startswith('_')})
                if name == 'WindowSettingsRequest' and 'minimapScale' in f:
                    mod['minmapScale'] = f['minimapScale']      # modülde adı minmapScale (istekte minimapScale): mini harita ölçeği
                if 'notSet' in mod:
                    mod['notSet'] = False
            elif name == 'UserKeyBindingsUpdate':
                cur = {(b.get('actionType'), b.get('parameter')): b for b in self.d['tus_atamalari']}
                for b in f.get('changedKeyBindings', []):
                    cur[(b.get('actionType'), b.get('parameter'))] = b
                self.d['tus_atamalari'] = list(cur.values())
            elif name == 'ResetSettingsRequest':
                # Ayarlar > Klavye > Reset: tuşlar tohumdakine (istemci isteği çoğu kez bağlantı kapanmadan gönderemiyor: CANLI_TEST
                # N12; panelin "tuş atamaları" seçeneği aynısı)
                self.d['tus_atamalari'] = self._from_seed(self.tohum)['tus_atamalari']
            elif name == 'UIWindowUpdateRequest':
                for bar in self.d['arayuz'].get('featureBars', []):
                    for it in bar.get('featureBarItems', []):
                        if it.get('itemId') == f.get('itemId'):
                            it.update({k: f[k] for k in WINDOW_KEYS if k in f})
            elif name == 'MoveRequest':
                self.d['konum'].update(x=f['targetX'], y=f['targetY'])
            else:
                return False
            self.dirty = True
            return True
