"""Clan Battle Station (yol haritası Ö5 CBS-1..4; veri data/cbs.json <- tools/cbs.py).

CBS-1 Kurma: X-3..X-7, 4-1..4-5 ve X-BL'deki 23 asteroit (AssetCreateCommand tür 35). Klanlı oyuncu yaklaşınca (600) pencere verisi
(BattleStationBuildingUiInitializationCommand); tıklayınca istemci pencereyi (76) kendisi açar. Modüller sürükle-bırakla 10 yuvaya
(0 Hull, 1 Deflector merkez; 2-9 uydu), her biri 50 sn'de kurulur (aynı anda tek); on modül takılınca Build (5-60 dk). Kurulunca
merkez (36) ve uydular (37), deflector açık ve 1440 dk yüklü (resmî forum 127469).
Klandan ayrılan/atılan üyenin modülleri istasyondan envanterine döner (merkezi çıkarılan istasyon düşer); klan dağılınca istasyonları
yıkılır, asteroit boşalır (forum 127469; uye_ayrildi, klan_dagildi).
CBS-2 Yönetim: Deflector açıkken istasyon dokunulmaz ve süre harcar; kapalıyken süre dolar (saatte 120 dk, prime time 18-21'de 600;
en çok 48 sa); biterse 120 dk zorunlu kapalı; Deactivate 30 dk-8 sa. Boosterlar (onur, EP: her yerde; hasar: istasyonun haritasında)
takılınca %1'den 20 saatte azamiye (%3-10). İstasyonda maden satışı (%10 pahalı), acil onarım (500 U; 20 sn x 7.500), Engineering Bay
ya da yavaş kendiliğinden onarım; yok olmuş modül hangarda uridyumla onarılır. Kurulu istasyonda modül değiştirme 4 dk.
CBS-3 Uzaylı baskınları: prime time'da deflector kapalıyken saatte iki dalga (haritanın seviyesinden 6-12 uzaylı) istasyonu vurur;
silah modülleri menzildeki uzaylılara ateş eder. Merkez yıkılırsa istasyon düşer, modüller yok olmuş (0 can) envantere döner.
CBS-4 Sanal rakip klanlar: boş asteroitlerde zamanla ilerleyen rakip (Progress of leading Clan); rakip önce bitirirse düşman istasyonu
(HOSTILE); deflector'u prime time dışında açık. Rakip modüllerini yıkmak 500-2.600 U, merkezi 5.000 U + 50.000 kredi.
İstemci: istekler Equip/UnequipModule, BuildStation, DeflectorShieldStatusChange, EmergencyRepair, MapAssetActivation, TradeRequest
(istasyonda), HangarShipRepairModule; acil onarım 20 dk x 7.500 (forum 127469); klan penceresi ClanBattleStationInfo / BattleStationHistoryList; galaksi haritası
StarmapStationCommand. Profilde: cbs {moduller {iid: {loot, seviye, can, kalkan}}, asteroitler {id: …}, gunluk [...], istatistik}.
Çok oyunculu sunucuda (çoklu istemci, arkadaş sunucusu) asteroitler herkes için tek: sunucunun oyuncusunun kaydında (ortak); önce her
oyuncunun kendi asteroitleri vardı, rakip ve istasyonlar istemciden istemciye farklı görünüyordu (kullanıcı 2026-10-24). İstasyon
kuranın klanının (klan): klanın üyeleri yönetir (haklar klan.HAKLAR), ötekiler başka klanın istasyonu olarak görür (ilişki: klan
diplomasisi). Takılan modül yuvaya taşınır (sahibiyle; benzersiz kimlik): herkes görür; çıkarılınca ya da istasyon düşünce sahibine
döner (çevrimdışıysa sonraki girişinde). Asteroitlerin zamanlı işleri (kurulum, deflector, onarım, rakip) sunucuda bir kez; her
oturum asteroidin sürümü değişince varlıkları ve penceresini yeniler. Günlük ve sayılar klanın kaydında.
"""
import datetime, functools, json, math, os, random, sys, threading, time, traceback, types

import settings as SET
import multiplayer as CO
import clan as KL
import community as TP
import world as world_module
import map_links as H
import galaxy_gates as KAPI
import pve_common as PS
import paths as PTH
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'cbs.json')
D = json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}
ASTEROIDS = {a['uid']: a for a in D.get('asteroids', [])}
BY_MAP = {}
for _a in ASTEROIDS.values():
    BY_MAP.setdefault(int(_a['map']), []).append(_a['uid'])
MODS = D.get('modules', {})
ASSET_BASE = 157000000                 # + asteroit x 100 (asteroit/merkez), + yuva (uydular)
ITEM_BASE = 157500000                  # modül örneklerinin itemId'si
ASTEROID, BATTLESTATION, SATELLITE = 35, 36, 37
HULL, DEFLECTOR = 0, 1                 # merkez yuvaları
SLOTS = 10
OWN, NEUTRAL, HOSTILE = 1, 2, 3        # StarmapStationInfo.StationStatus
DESTRUCTION_BATTLESTATION = 5           # DestructionTypeModule.DestructionCause (ölüm ekranı)
E = dict(UNSPECIFIED=0, NO_CLAN=1, STATION_ALREADY_BUILDING=2, ITEM_HITPOINTS_ZERO=3, ITEM_ALREADY_EQUIPPED_IN_ANOTHER_ASTEROID=4,
         CONCURRENT_EQUIP=5, REPLACE_RIGHT_MISSING=6, ITEM_NOT_OWNED=7, OUT_OF_RANGE=8, EQUIP_OF_SAME_PLAYER_RUNNING=9,
         SATELLITE_ONLY=10, HUB_ONLY=11, ITEM_NOT_IN_STATION=12, MAX_NUMBER_OF_MODULE_TYPE_EXCEEDED=13, DEFLECTOR_ALREADY_ON=14,
         DEFLECTOR_ALREADY_OFF=15, REPAIR_NO_MODULE=16, REPAIR_NO_MONEY=17, REPAIR_ALREADY_RUNNING=18, ITEM_UPGRADE_RUNNING=19)
TRADE_BATTLE_STATION = 4
SHARED_ITEM = ITEM_BASE + 1000000         # ortak yuvadaki modüllerin kimlikleri (oyuncuların sırası ITEM_BASE'den: çakışmasın)
SHARED = {'lock': threading.Lock(), 'next': 0.0}


def with_bots():
    """Bot paketi açık ve bot klanlarının istasyon kurması izinli (Botlar: klan_ksi): istasyonlar gerçek klanların, sahte rakip
    yok, asteroitler boş açılır; bot klanları yarışır (bot/clan_stations.py; kullanıcı isteği 2026-10-31)."""
    y = getattr(sys.modules.get('bot.manager'), 'ACTIVE', None)
    return y is not None and y.permission('clan') and y.permission('clan_cbs')


def shared():
    """Asteroitlerin ortak kaydı (sunucunun oyuncusunun profili): çok oyunculu sunucuda ve botlar varken (bir bot klanı bir kez
    istasyona el attıysa kalıcı: bot_klanlari); tek oyunculuda None."""
    g = TP.GAME
    h = getattr(g, 'PROFILE', None) if g is not None else None
    if h is None:
        return None
    return h if CO.is_open() or with_bots() or (h.d.get('cbs') or {}).get('bot_clans') else None


def mod(_cls, **f):
    f['_'] = _cls
    return f


def asset_id(aid, slot=None):
    return ASSET_BASE + aid * 100 + (slot if slot is not None and slot > DEFLECTOR else 0)


@functools.lru_cache(maxsize=None)
def placement_obstacles(map_id):
    """Use the same recorded/generated structures as the session's map loader."""
    path = PTH.template('maps.json')
    with open(path, encoding='utf8') as source:
        maps = json.load(source)
    world = maps.get(str(map_id)) or H.map_world(map_id, maps.get('5'))
    obstacles = [(g['x'], g['y'], H.GATE_PEACE_RADIUS + 700) for g in H.GATES.get(map_id, [])]
    obstacles += [(m['posX'], m['posY'], H.ASSET_RANGE + 700) for m in world.get('entry', [])
                  if m['_m'] == 'AssetCreateCommand']
    obstacles += [(m['posX'], m['posY'], m['peaceRadius'] + 700) for m in world.get('ready', [])
                  if m['_m'] == 'SpaceStationCommand']
    return obstacles


@functools.lru_cache(maxsize=None)
def position(aid):
    """Keep the configured centre unless its 600-unit footprint overlaps a map object.

    Project only colliding centres beyond the obstacle, with 100 units of clearance.
    Angular boundary candidates handle overlapping exclusions deterministically.
    """
    a = ASTEROIDS[aid]
    w, h = H.map_size(a['map'])
    x, y = int(w * a['x_percent'] / 100.0), int(h * a['y_percent'] / 100.0)
    obstacles = placement_obstacles(int(a['map']))

    def clamp(point):
        return int(min(max(point[0], 700), w - 700)), int(min(max(point[1], 700), h - 700))

    def clear(point):
        return all(math.hypot(point[0] - ox, point[1] - oy) >= radius for ox, oy, radius in obstacles)

    original = clamp((x, y))
    if clear(original):
        return original
    candidates = []
    for ox, oy, radius in obstacles:
        angle = math.atan2(y - oy, x - ox)
        for direction in [angle] + [math.radians(degrees) for degrees in range(0, 360, 5)]:
            point = clamp((ox + math.cos(direction) * (radius + 2), oy + math.sin(direction) * (radius + 2)))
            if clear(point):
                candidates.append(point)
    if not candidates:
        raise ValueError('CBS %s has no clear layout position' % aid)
    return min(candidates, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)


def satellite_pos(aid, slot):
    """Recorded 22.5-degree octagon orientation, with extra vertical clearance for native module sprites."""
    x, y = position(aid)
    a = (slot - 2) * math.pi / 4 + math.pi / 8
    # Preserve the recorded octagon angle; increase height for 210px native module clearance.
    return int(x + math.cos(a) * 447), int(y + math.sin(a) * 330)


def exclusion_zones(map_id):
    """Physical station/asteroid area, available before the world spawns NPCs."""
    return [(*position(aid), D['range']) for aid in BY_MAP.get(int(map_id), [])]


def prime_time(now=None):
    t = datetime.datetime.fromtimestamp(time.time() if now is None else now)
    a, b = D.get('prime_time', ['18:00', '21:00'])
    h = t.hour + t.minute / 60.0
    return float(a.split(':')[0]) <= h < float(b.split(':')[0])


def level_value(row, lv):
    return row[max(0, min(len(row) - 1, int(lv)))]


def hp_sync(m):
    """Panelin KSİ can çarpanı değişince modülün canı, kalkanı (ve rakipte azamisi) oranıyla ölçeklenir (m['ksi']: kayıttaki değerlerin
    hangi çarpanla ölçeklendiği; yoksa 1,0)."""
    k = float(SET.get('ksi_can'))
    old = m.get('ksi', 1.0)
    if k == old:
        return
    r = k / old
    for f in ('maximum', 'can', 'kalkan'):
        if f in m:
            m[f] = min(SET.I32, int(m[f] * r))
    m['ksi'] = k


def hp_max(m):
    """Modülün azami canı (rakipte kayıttaki azami): panelin KSİ can çarpanıyla, en çok 32 bit."""
    hp_sync(m)
    return m.get('maximum') or min(SET.I32, int(level_value(MODS[m['loot']]['can'], m['level']) * float(SET.get('ksi_can'))))


def dmg_value(md, lv):
    """Silah modülünün seviyedeki hasarı: panelin KSİ hasar çarpanıyla (bütün istasyonlar)."""
    return level_value(md['damage'], lv) * float(SET.get('cbs_damage'))


def stm(key, **params):
    """İstemcinin metni (flashres) yer tutucularıyla: 0|A|STM|anahtar|%AD%|değer…"""
    return legacy('0|A|STM|%s%s' % (key, ''.join('|%%%s%%|%s' % (k, v) for k, v in params.items())))


def stamp(t=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() if t is None else t))


class Cbs:
    REQUESTS = ('EquipModuleRequest', 'UnequipModuleRequest', 'BuildStationRequest', 'DeflectorShieldStatusChangeRequest',
                'EmergencyRepairRequest', 'HangarShipRepairModuleRequest')

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.near = None                        # menzildeki asteroit
        self.shown_assets = []                  # bu haritada gönderilen varlıklar
        self.next_raid = {}
        self.raiders = {}                       # uzaylı -> asteroit
        self.next_shot = {}
        self.tick_err = {}                      # asteroit -> hatası bir kez yazıldı
        self.starmap_tpl = None                 # girişin StarmapStationCommand şablonu (değişince yeniden gönderilir)
        self.home = None                        # oturum bağlar: üs haritası
        self.prime = None                       # son bilinen Prime Time durumu (geçişte duyuru)
        self.seen = {}                          # ortak asteroitlerin son görülen (sürüm, durum): değişince yenilenir

    # ------------------------------------------------------------ profil
    @property
    def st(self):
        d = self.p.d.setdefault('cbs', {})
        for k, v in (('modules', {}), ('asteroids', {}), ('daily', []), ('stats', {}), ('order', 0)):
            d.setdefault(k, v)
        self.migrate_rival_stats(self.p, d)
        self.absorb(d)
        return d

    @staticmethod
    def migrate_rival_stats(profile, state):
        """Upgrade synthetic saved rival capacities once, preserving damage fractions.

        Owned inventory/stations never participate. Old rivals stored a reduced
        capacity in azami, so changing the data table alone could not update them.
        """
        version = 1  # published CBS stats configuration, 2026-10-25
        if state.get('rival_stats_version', 0) == version:
            return
        asteroids = state.get('asteroids', {})
        for a in asteroids.values() if isinstance(asteroids, dict) else []:
            if not isinstance(a, dict) or a.get('owner') != 'rival' or a.get('state') != 'built':
                continue
            slots = a.get('slots', {})
            changed = False
            for row in slots.values() if isinstance(slots, dict) else []:
                if not isinstance(row, dict) or 'iid' in row or 'module' in row:
                    continue
                loot = row.get('loot')
                md = MODS.get(loot) if isinstance(loot, str) else None
                if not md:
                    continue
                try:
                    old_max, hp, shield = (float(row[k]) for k in ('maximum', 'can', 'kalkan'))
                    level = float(row['level'])
                    if not all(math.isfinite(v) for v in (old_max, hp, shield, level)) or old_max <= 0 or level != int(level):
                        continue
                    maximum = int(level_value(md['can'], int(level)) * D['rival']['hp_multiplier'])
                    if maximum <= 0:
                        continue
                    old_shield = int(old_max * D['shield_ratio'])
                    new_shield = int(maximum * D['shield_ratio'])
                    row.update(maximum=maximum, can=int(maximum * max(0.0, min(1.0, hp / old_max))),
                               kalkan=int(new_shield * max(0.0, min(1.0, shield / old_shield))) if hp > 0 and old_shield > 0 else 0)
                    row.pop('ksi', None)
                    changed = True
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
            if changed:
                a['version'] = a.get('version', 0) + 1
        state['rival_stats_version'] = version
        profile.dirty = True

    def absorb(self, d):
        """Ödül yolundan depoya düşen modüller (module_* sayaçları) tek tek örneğe çevrilir (can, kalkan, seviye). Ortak yuvadan
        çevrimdışıyken dönen modüller (give_back) de."""
        h = self.host
        back = ((h.d.get('cbs') or {}).get('pending') or {}).get(KL.name(self.p)) if h is not None else None
        if back:
            with h.lock:
                h.d['cbs']['pending'].pop(KL.name(self.p), None)
                h.dirty = True
            d['modules'].update(back)
            self.p.dirty = True
        store = self.p.d.get('other_items', {})
        loots = [l for l in list(store) if l in MODS]
        for loot in loots:
            n = int(store.pop(loot, 0))
            for _ in range(n):
                d['order'] += 1
                iid = ITEM_BASE + d['order']
                hp = level_value(MODS[loot]['can'], 0)
                d['modules'][str(iid)] = dict(loot=loot, level=0, can=hp, kalkan=int(hp * D['shield_ratio']))
            self.p.dirty = True

    @property
    def host(self):
        return shared()

    @property
    def asteroids(self):
        """Asteroitlerin kaydı: tek oyunculuda oyuncunun, çok oyunculuda ortak (sunucunun oyuncusunun profilinde)."""
        h = self.host
        if h is None:
            return self.st['asteroids']
        d = h.d.setdefault('cbs', {})
        if not d.get('shared'):
            self.embed(h, d)
        if self.p is not h:
            self.bring(h, d)
        self.migrate_rival_stats(h, d)
        return d['asteroids']

    def bring(self, h, d):
        """Ek istemcinin (misafirin) tek oyunculuda kurduğu istasyonlar da ortak olur (embed gibi): boş asteroide yuvadaki modül
        (sahibiyle, ortak kimlikle), istasyon oyuncunun klanının. Asteroit ortakta doluysa istasyon kurulmaz, modülleri envanterinde
        kalır. Önce yalnız sunucunun oyuncusununkiler ortaktı: kayıt ek istemcide açılınca kendi istasyonları yoktu (oyuncu bildirimi
        2026-10-30). Klansızken bekler (klanı bağlanınca)."""
        own = self.p.d.get('cbs') or {}
        built = [aid for aid, a in own.get('asteroids', {}).items()
                 if a.get('owner') != 'rival' and (a.get('slots') or a.get('state') in ('building', 'built'))]
        k = self.clan() if built else None
        if not k:
            return
        me, name = KL.name(self.p), self.p.d['pilot'].get('userName', '')
        with h.lock:
            shared = d.setdefault('asteroids', {})
            for aid in built:
                a = own['asteroids'].pop(aid)
                there = shared.get(aid) or {}
                if there.get('slots') or there.get('state', 'vacant') != 'vacant':
                    self.log('   CBS: %s ortakta dolu, %s istasyonunun modülleri envantere' % (aid, me))
                    continue
                slots = {}
                for s, y in a.get('slots', {}).items():
                    m = own.get('modules', {}).pop(str(y.get('iid')), None)
                    if m is not None:
                        d['shared_seq'] = int(d.get('shared_seq', 0)) + 1
                        slots[s] = dict(y, iid=SHARED_ITEM + d['shared_seq'], module=m, owner=me, owner_name=name)
                a.pop('rival', None)
                a.pop('rival_progress', None)
                shared[aid] = dict(a, slots=slots, clan=k['id'], version=there.get('version', 0) + 1)
                self.log('   CBS: %s istasyonu ortakta (%s)' % (aid, me))
            h.dirty = True
        self.p.dirty = True

    def embed(self, h, d):
        """Sunucunun oyuncusunun tek oyunculuda kurduğu istasyonlar ortak olur: yuvadaki modül yuvaya (sahibiyle), istasyon klanının."""
        me, cid = KL.name(h), int(h.d['pilot'].get('clanId', 0) or 0)
        with h.lock:
            d.setdefault('asteroids', {})
            mods = d.setdefault('modules', {})
            for a in d['asteroids'].values():
                if a.get('owner') == 'rival':
                    continue
                for y in a.get('slots', {}).values():
                    m = mods.pop(str(y.get('iid')), None) if 'module' not in y else None
                    if m is not None:
                        y.update(module=m, owner=me, owner_name=h.d['pilot'].get('userName', ''))
                if cid and (a.get('slots') or a.get('state') in ('building', 'built')):
                    a.setdefault('clan', cid)
            d['shared'] = True
            h.dirty = True

    @property
    def lock(self):
        h = self.host
        return (h or self.p).lock

    def mark(self):
        self.p.dirty = True
        h = self.host
        if h is not None:
            h.dirty = True

    def bump(self, a):
        """Asteroidin görünümü değişti (ortakta öteki oturumlar yeniler)."""
        a['version'] = a.get('version', 0) + 1

    def ast(self, aid):
        a = self.asteroids.setdefault(str(aid), {})
        a.setdefault('state', 'vacant')
        a.setdefault('slots', {})
        a.setdefault('deflector', {'on': False, 'sn': 0.0, 'closed_until': 0.0, 'last': time.time()})
        for y in a['slots'].values():
            m = y.get('module') or (y if 'loot' in y else None)
            if m is not None and m.get('loot') in MODS:
                hp_sync(m)
        return a

    def clan(self):
        return KL.clan_of(self.p) if self.host is not None else self.p.d.get('clan')

    def clan_name(self):
        k = self.clan()
        return k['name'] if k else ''

    def faction(self):
        k = self.clan()
        return int((k or {}).get('company') or self.p.d['pilot'].get('factionId', 0))

    def mine(self, a):
        """İstasyon (ya da kurulan asteroit) oyuncunun klanının mı: tek oyunculuda rakip dışındakiler."""
        if a.get('owner') == 'rival':
            return False
        if self.host is None:
            return True
        k = self.clan()
        return bool(k) and a.get('clan') in (None, k['id'])

    def st_clan(self, a):
        """Asteroitteki istasyonun klanı (kayıt) ya da None."""
        if self.host is None:
            return self.clan()
        return KL.CLANS.get(a.get('clan')) if a.get('clan') else None

    def st_name(self, a):
        return (self.st_clan(a) or {}).get('name', '')

    def st_faction(self, a):
        k = self.st_clan(a)
        return int((k or {}).get('company') or (self.p.d['pilot'].get('factionId', 0) if self.host is None else 0))

    def relation(self, a):
        """Varlığın klan ilişkisi (bakana göre): rakip savaş, kendi klanınki 0, başkasınınki diplomasiye göre (yoksa düşman)."""
        if a.get('owner') == 'rival':
            return 3
        if self.mine(a):
            return 0
        k = self.clan()
        return (KL.clan_relation(k['id'], a.get('clan')) if k else 0) or 3

    def own_module(self, iid):
        return self.st['modules'].get(str(iid))

    def module(self, iid):
        m = self.st['modules'].get(str(iid))
        if m is None:
            y = self.slot_of(iid)
            m = y.get('module') if y else None
        if m is not None:
            hp_sync(m)
        return m

    def slot_of(self, iid):
        for a in self.asteroids.values():
            for y in a.get('slots', {}).values():
                if str(y.get('iid')) == str(iid):
                    return y
        return None

    def where(self, iid):
        """Modülün takılı olduğu (asteroit, yuva) ya da None (çok oyunculuda oyuncunun tek oyunculu asteroitleri de: modül iki yerde
        kullanılmasın)."""
        stores = [self.asteroids] + ([self.st['asteroids']] if self.host is not None and self.host is not self.p else [])
        for store in stores:
            for aid, a in store.items():
                for slot, y in a.get('slots', {}).items():
                    if str(y.get('iid')) == str(iid):
                        return int(aid), int(slot)
        return None

    def give_back(self, y):
        """Ortak yuvadaki modül sahibine (bağlıysa hemen, değilse sonraki girişinde: absorb)."""
        m = y.pop('module', None) if y else None
        if m is None:
            return
        owner, iid = y.get('owner'), str(y['iid'])
        s = KL.people().get(owner) if owner != KL.name(self.p) else None
        x = self.p if owner == KL.name(self.p) else (s.profile if s is not None else None)
        if x is not None:
            with x.lock:
                x.d.setdefault('cbs', {}).setdefault('modules', {})[iid] = m
                x.dirty = True
        else:
            h = self.host or self.p
            with h.lock:
                h.d.setdefault('cbs', {}).setdefault('pending', {}).setdefault(owner, {})[iid] = m
                h.dirty = True

    def tell(self, a, msgs):
        """İstasyonun klanına duyuru: ortakta klanın bağlı üyelerine gider (asteroitlerin işlerini hangi oturum yürütürse yürütsün)."""
        k = KL.CLANS.get(a.get('clan')) if self.host is not None and a.get('clan') else None
        if k is None or not msgs:
            return msgs
        for name, s in KL.people().items():
            if name in k['members'] and s.session is not None:
                s.send(msgs, 'CBS')
        return []

    def hp(self, right):
        """Klan hakkı (tek oyunculuda oyuncu lider)."""
        return self.host is None or KL.right(self.p, right)

    def mx(self, m):
        hp = hp_max(m)
        return hp, min(SET.I32, int(hp * D['shield_ratio']))

    # ------------------------------------------------------------ komutlar
    def module_cmd(self, iid, aid=-1, slot=-1, now=None):
        now = time.time() if now is None else now
        m = self.module(iid)
        md = MODS[m['loot']]
        mh, ms = self.mx(m)
        y = (self.ast(aid)['slots'].get(str(slot)) if aid > 0 else None) or {}
        left = max(0, int(y.get('install_end', 0) - now))
        rep = max(0, int(y.get('repair_end', 0) - now))
        owner = (y.get('owner_name') or self.p.d['pilot'].get('userName', '')) if aid > 0 else ''
        return mod('StationModuleModule', asteroidId=aid, itemId=int(iid), slotId=slot, type=md['type'], currentHitpoints=int(m['can']),
                   maxHitpoints=mh, currentShield=int(m['kalkan']), maxShield=ms, upgradeLevel=int(m['level']),
                   ownerName=owner, installationSeconds=int(y.get('install_sec', 0)),
                   installationSecondsLeft=left, emergencyRepairSecondsLeft=rep,
                   emergencyRepairSecondsTotal=D['emergency_repair']['sure_sn'] if rep else 0, emergencyRepairCost=D['emergency_repair']['charge'])

    def available_cmd(self):
        free = [iid for iid in sorted(self.st['modules'], key=int) if not self.where(iid)]
        return mod('AvailableModulesCommand', modules=[self.module_cmd(i) for i in free])

    def available_msg(self):
        """Pencerenin envanterini yeniler (istemci UiInitialization'daki listeyi yalnız ilk kez alıyor; canlı tur Ö5)."""
        return ('AvailableModulesCommand', {'modules': self.available_cmd()['modules']})

    def equipped(self, aid, now=None):
        a = self.ast(aid)
        return mod('EquippedModulesModule', modules=[self.module_cmd(y['iid'], aid, int(s), now) for s, y in sorted(a['slots'].items(),
                                                                                                                key=lambda kv: int(kv[0]))
                                                     if self.module(y['iid'])])

    def own_progress(self, aid, now=None):
        """Asteroitte kuran klanın ilerlemesi (kurulumu biten modüller)."""
        now = time.time() if now is None else now
        a = self.ast(aid)
        done = sum(1 for y in a['slots'].values() if y.get('install_end', 0) <= now)
        return done / float(SLOTS)

    def progress_cmd(self, aid, now=None):
        a = self.ast(aid)
        prog = self.own_progress(aid, now)
        own = prog if self.mine(a) else 0.0                 # ortakta başka klan kuruyorsa onun ilerlemesi en iyi
        r, rp = a.get('rival'), a.get('rival_progress', 0) if a.get('rival') else 0
        leader = race_leader(a)                                # bot klanlarının yarışı (klan_us): önde gideni
        if leader and leader[1] > rp:
            r, rp = leader
        best = max(prog, rp)
        best_name = (self.st_name(a) or self.clan_name() if prog >= rp else r) if (prog or r) else ''
        return mod('AsteroidProgressCommand', battleStationId=aid, ownProgress=float(own), bestProgress=float(best), ownClanName=self.clan_name(),
                   bestProgressClanName=best_name or '', state=self.equipped(aid, now),
                   buildButtonActive=own >= 1.0 and a['state'] == 'vacant' and self.hp('battle_station_build'))

    def progress_msg(self, aid, now=None):
        f = dict(self.progress_cmd(aid, now))
        f.pop('_')
        return ('AsteroidProgressCommand', f)

    def status_msg(self, aid, now=None):
        f = dict(self.status_cmd(aid, now))
        f.pop('_')
        return ('BattleStationStatusCommand', f)

    def building_ui(self, aid):
        k = D['build_min']
        return ('BattleStationBuildingUiInitializationCommand', dict(
            mapAssetId=asset_id(aid), battleStationId=aid, battleStationName=ASTEROIDS[aid]['name'], progress=self.progress_cmd(aid),
            availableModules=self.available_cmd(), buildTimeInMinutesMin=k[0], buildTimeInMinutesMax=k[1], buildTimeInMinutesIncrement=k[2]))

    def booster_pct(self, aid, kind, now=None):
        """Booster modülünün etkisi (%): takılıp kurulduktan sonra %1'den 20 saatte azamiye."""
        now = time.time() if now is None else now
        a = self.ast(aid)
        if a['state'] != 'built':
            return 0.0
        for slot, y in a['slots'].items():
            m = self.module(y['iid'])
            if not m or MODS[m['loot']].get('booster') != kind or y.get('install_end', 0) > now or m['can'] <= 0:
                continue
            top = level_value(MODS[m['loot']]['booster_percent'], m['level'])
            t = (now - max(y.get('install_end', 0), a.get('founded', 0))) / (D['booster']['growth_hours'] * 3600.0)
            return min(top, D['booster']['start'] + (top - D['booster']['start']) * max(0.0, min(1.0, t)))
        return 0.0

    def ratings(self, aid, now=None):
        a = self.ast(aid)
        att = dfn = rep = 0
        for y in a['slots'].values():
            m = self.module(y['iid'])
            if not m:
                continue
            md = MODS[m['loot']]
            dfn += int(m['can'] + m['kalkan'])
            if md.get('weapon'):
                att += dmg_value(md, m['level'])
            if md.get('repair_sec'):
                rep += level_value(md['repair_sec'], m['level'])
        return att // 1000, dfn // 1000, rep

    def deflector_rate(self, now=None, aid=None):
        r = D['deflector_speed']
        base = r['prime_time'] if prime_time(now) else r['normal']
        level = 0
        if aid is not None:
            a = self.ast(aid)
            y = a['slots'].get(str(DEFLECTOR))
            m = (y if a.get('owner') == 'rival' else self.module(y.get('iid'))) if y else None
            if m and m.get('loot') == 'module_defm-1':
                level = max(0, min(15, int(m['level'])))
        # Published +1% of base per upgrade: 120 minutes/hour -> 138 at L16.
        return base * (100 + level) / 100.0

    def status_cmd(self, aid, now=None):
        now = time.time() if now is None else now
        a = self.ast(aid)
        df = a['deflector']
        att, dfn, rep = self.ratings(aid, now)
        return mod('BattleStationStatusCommand', mapAssetId=asset_id(aid), battleStationId=aid, battleStationName=ASTEROIDS[aid]['name'],
                   deflectorShieldActive=bool(df['on']), deflectorShieldSeconds=int(df['sn']), deflectorShieldSecondsMax=D['deflector_max_sec'],
                   attackRating=att, defenceRating=dfn, repairRating=rep, honorBoosterRating=int(round(self.booster_pct(aid, 'honor', now))),
                   experienceBoosterRating=int(round(self.booster_pct(aid, 'ep', now))),
                   damageBoosterRating=int(round(self.booster_pct(aid, 'damage', now))), deflectorShieldRate=int(self.deflector_rate(now, aid)),
                   repairPrice=D['emergency_repair']['charge'], equipment=self.equipped(aid, now), isOreTradeAvailable=True)

    def management_ui(self, aid, now=None):
        dm = D['deflector_min']
        a = self.ast(aid)
        return ('BattleStationManagementUiInitializationCommand', dict(
            mapAssetId=asset_id(aid), battleStationId=aid, battleStationName=ASTEROIDS[aid]['name'], clanName=self.st_name(a),
            faction=mod('FactionModule', faction=self.st_faction(a)), state=self.status_cmd(aid, now), availableModules=self.available_cmd(),
            deflectorShieldMinutesMin=dm[0], deflectorShieldMinutesMax=dm[1], deflectorShieldMinutesIncrement=dm[2],
            deflectorDeactivationPossible=bool(a['deflector']['on'])))

    def building_state(self, aid, now=None):
        now = time.time() if now is None else now
        a = self.ast(aid)
        return ('BattleStationBuildingStateCommand', dict(mapAssetId=asset_id(aid), battleStationId=aid, battleStationName=ASTEROIDS[aid]['name'],
                                                          secondsLeft=max(0, int(a.get('build_end', now) - now)),
                                                          totalSeconds=int(a.get('build_sec', 0)), ownerClan=self.st_name(a),
                                                          affiliatedFaction=mod('FactionModule', faction=self.st_faction(a))))

    def ui_msgs(self, aid):
        """Yaklaşınca pencerenin verisi (istemci tıklamada kendisi açar): klansız / asteroit / kuruluyor / kurulu."""
        a = self.ast(aid)
        if not self.clan():
            return [('BattleStationNoClanUiInitializationCommand', {'mapAssetId': asset_id(aid)})]
        if a.get('owner') == 'rival':
            return []
        if a['state'] == 'building':
            return [self.building_state(aid)]
        if a['state'] == 'built':
            return [self.management_ui(aid)] if self.mine(a) else []        # başka klanın istasyonu
        return [self.building_ui(aid)]

    def error(self, kind):
        return [('BattleStationErrorCommand', {'type': E[kind]})]

    # ------------------------------------------------------------ varlıklar
    def asset_cmd(self, aid_asset, kind, x, y, name, design=1, stage=0, clan=None, faction=0, relation=0):
        return ('AssetCreateCommand', dict(designId=design, clanId=int((clan or {}).get('id', 0)), showBubble=True, userName=name,
                                           assetId=aid_asset, expansionStage=stage, modifier=[], type=mod('AssetTypeModule', typeValue=kind),
                                           detectedByWarnRadar=True, invisible=False, posY=int(y),
                                           clanRelation=mod('ClanRelationModule', type=relation), clanTag=(clan or {}).get('tag', ''),
                                           factionId=faction, posX=int(x), visibleOnWarnRadar=False))

    def hub_stage(self, aid):
        """Native .115: Hull occupies bits 16+, Deflector occupies bits 0..7.

        GetLowerByte actually shifts right 16; GetUpperByte reads the low byte.
        Both AssetCreate and AssetInfo feed UpdateBattleStationVisuals.
        """
        a = self.ast(aid)
        levels = []
        for slot in (HULL, DEFLECTOR):
            y = a['slots'].get(str(slot))
            m = (y if a.get('owner') == 'rival' else self.module(y.get('iid'))) if y else None
            levels.append(max(0, min(15, int(m['level']))) if m else 0)
        return (levels[0] << 16) | levels[1]

    def map_assets(self, aid):
        """Asteroidin varlıkları: boşsa asteroit (35); kuruluysa merkez (36) ve uydular (37)."""
        a = self.ast(aid)
        x, y = position(aid)
        if a['state'] != 'built':
            cmd = self.asset_cmd(asset_id(aid), ASTEROID, x, y, ASTEROIDS[aid]['name'])
            if a['state'] == 'building':
                cmd[1]['modifier'] = [self.construction_modifier(aid)]
            return [(asset_id(aid), ASTEROID, cmd)]
        rival = a.get('owner') == 'rival'
        clan = {'id': 9000 + aid, 'tag': (a.get('rival') or '')[:3].upper()} if rival else self.st_clan(a)
        fac = a.get('rival_company', 0) if rival else self.st_faction(a)
        rel = self.relation(a)
        stage = self.hub_stage(aid)
        out = [(asset_id(aid), BATTLESTATION, self.asset_cmd(asset_id(aid), BATTLESTATION, x, y, a.get('rival') if rival else self.st_name(a),
                                                             stage=stage, clan=clan, faction=fac, relation=rel))]
        for slot, slot_info in sorted(a['slots'].items(), key=lambda kv: int(kv[0])):
            s = int(slot)
            if s <= DEFLECTOR:
                continue
            m = self.module(slot_info['iid']) if not rival else slot_info
            if not m:
                continue
            sx, sy = satellite_pos(aid, s)
            loot = m['loot']
            dead = m['can'] <= 0
            out.append((asset_id(aid, s), SATELLITE, self.asset_cmd(asset_id(aid, s), SATELLITE, sx, sy, 'wreck' if dead else MODS[loot]['code'],
                                                                   design=0 if dead else MODS[loot]['design'], stage=m['level'],
                                                                   clan=clan, faction=fac, relation=rel)))
        for uid, kind, cmd in out:
            if kind == SATELLITE and cmd[1]['designId'] == 0:
                continue
            df = a['deflector']
            if df.get('on'):
                cmd[1]['modifier'] = [self.deflector_modifier(uid, 34, True, int(df.get('sn', 0)))]
            elif kind == BATTLESTATION:
                seconds = max(0, math.ceil(df.get('closed_until', 0) - time.time()))
                if seconds:
                    cmd[1]['modifier'] = [self.deflector_modifier(uid, 35, True, seconds)]
        return out

    @staticmethod
    def construction_modifier(aid):
        # Native .115 modifier 37 creates ConstructingEffect2D/3D; the building UI alone does not.
        return mod('VisualModifierCommand', userId=asset_id(aid), modifier=37, attribute=0,
                   additionalAttribute='', count=0, activated=True)

    @staticmethod
    def deflector_modifier(uid, modifier, active, seconds=0):
        # Native 1.1.115: 34 = shield + hub timer; 35 = hub downtime timer.
        return mod('VisualModifierCommand', userId=uid, modifier=modifier, attribute=max(0, int(seconds)),
                   additionalAttribute='', count=0, activated=active)

    def deflector_visuals(self, aid, now):
        """Update every displayed living asset, including viewers outside management range."""
        df = self.ast(aid)['deflector']
        shown = {uid for uid, _ in self.shown_assets}
        assets = [(uid, kind) for uid, kind, cmd in self.map_assets(aid)
                  if uid in shown and not (kind == SATELLITE and cmd[1]['designId'] == 0)]
        hub = asset_id(aid)
        if df['on']:
            # Clearing timer 35 after shield 34 would delete the active shield's own timer (both effect 49).
            msgs = [('VisualModifierCommand', self.deflector_modifier(hub, 35, False))] if hub in shown else []
            return msgs + [('VisualModifierCommand', self.deflector_modifier(uid, 34, True, df.get('sn', 0)))
                           for uid, _ in assets]
        msgs = [('VisualModifierCommand', self.deflector_modifier(uid, 34, False)) for uid, _ in assets]
        seconds = max(0, math.ceil(df.get('closed_until', 0) - now))
        if hub in shown:
            msgs.append(('VisualModifierCommand', self.deflector_modifier(hub, 35, seconds > 0, seconds)))
        return msgs

    def remove_assets(self):
        msgs = [('AssetRemoveCommand', {'assetType': mod('AssetTypeModule', typeValue=k), 'uid': i}) for i, k in self.shown_assets]
        self.shown_assets = []
        return msgs

    def show_assets(self, map_id):
        msgs = self.remove_assets()
        self.seen = {int(k): (a.get('version', 0), a.get('state')) for k, a in self.asteroids.items()}
        for aid in BY_MAP.get(int(map_id), []):
            for i, k, cmd in self.map_assets(aid):
                self.shown_assets.append((i, k))
                msgs.append(cmd)
        return msgs

    def info_cmd(self, aid, slot, m=None):
        """Varlığın can/kalkan çubuğu (AssetInfoCommand)."""
        a = self.ast(aid)
        y = a['slots'].get(str(slot)) or {}
        m = m or (y if a.get('owner') == 'rival' else self.module(y.get('iid')))
        if not m:
            return None
        mh = hp_max(m)                              # rakipte tek oyunculu çarpanla (azami)
        ms = min(SET.I32, int(mh * D['shield_ratio']))
        kind = BATTLESTATION if slot <= DEFLECTOR else SATELLITE
        return ('AssetInfoCommand', dict(assetId=asset_id(aid, slot), type=mod('AssetTypeModule', typeValue=kind),
                                         designId=1 if kind == BATTLESTATION else MODS[m['loot']]['design'],
                                         expansionStage=self.hub_stage(aid) if kind == BATTLESTATION else int(m['level']),
                                         hitpoints=int(m['can']), maxHitpoints=mh, shielded=ms > 0, shieldEnergy=int(m['kalkan']),
                                         maxShieldEnergy=ms))

    # ------------------------------------------------------------ dünya
    def attach(self, world):
        self.world = world
        self.near = None
        self.shown_assets = []                 # refreshMap already removed the previous client's assets
        world.cbs_trade = self.trade_mult
        world.asset_targets = self                      # rakip istasyonun modülleri seçilir ve vurulur (dunya.asset_laser)
        msgs = self.show_assets(world.map_id)
        return msgs

    def can_dock(self, aid):
        """Local own/allied docking rule, independent of shield/PvP immunity."""
        k = self.clan()
        if not k or not k.get('id'):
            return False
        a = self.ast(aid)
        if a['state'] != 'built' or a.get('owner') == 'rival':
            return False
        owner = a.get('clan') or (k['id'] if self.host is None else None)
        relation = (KL.clan_relation(k['id'], owner) if self.host is not None else
                    next((d['type'] for d in k.get('diplomacy', []) if d['clan'] == owner), 0))
        return owner == k['id'] or relation == 1

    def docking_station(self, x, y):
        if self.world is None:
            return None
        for aid in BY_MAP.get(int(self.world.map_id), []):
            if not self.can_dock(aid):
                continue
            sx, sy = position(aid)
            if math.hypot(x - sx, y - sy) <= D['range']:
                return dict(posX=sx, posY=sy, peaceRadius=D['range'], pvpPeace=False)
        return None

    def starmap_msgs(self):
        """Yıldız haritasının istasyon durumları değişti (kuruldu, rakip kurdu, yıkıldı): girişteki şablonla yeniden."""
        return self.login_replace('StarmapStationCommand', self.starmap_tpl) if self.starmap_tpl and self.world else []

    def login_replace(self, n, f):
        if n != 'StarmapStationCommand':
            return None
        self.starmap_tpl = f
        f = json.loads(json.dumps(f))
        by_name = {a['name']: k for k, a in ASTEROIDS.items()}
        for s in f.get('stations', []):
            aid = by_name.get(s.get('asteroidName'))
            if not aid:
                continue
            a = self.ast(aid)
            s['lastChangedTimestamp'] = 0               # sahipsiz: kayıttaki hesabın gördüğü değişim zamanı değil (E10)
            if a['state'] in ('built', 'building'):
                rival = a.get('owner') == 'rival'
                s.update(status=OWN if self.mine(a) else HOSTILE, clanName=a.get('rival') if rival else self.st_name(a),
                         owningFaction=mod('FactionModule', faction=a.get('rival_company', 0) if rival else self.st_faction(a)),
                         lastChangedTimestamp=int(a.get('founded', time.time()) * 1000))
        f['currentServerTimestamp'] = int(time.time() * 1000)
        return [('StarmapStationCommand', {k: v for k, v in f.items() if k != '_m'})]

    def tick(self, now):
        msgs = []
        st = self.st
        pt = prime_time(now)
        if self.prime is not None and pt != self.prime and self.clan_name():
            # kayıttaki satır: 0|n|MSG|1|1|msg_primetime_started| ("Activated Battle Station's Prime Time"); bitişi _ended
            msgs.append(legacy('0|n|MSG|1|1|msg_primetime_%s|' % ('started' if pt else 'ended')))
        self.prime = pt
        shared = self.host is not None
        run = True
        if shared:                                      # ortak asteroitlerin işleri sunucuda saniyede bir (hangi oturum olursa)
            with SHARED['lock']:
                run = now >= SHARED['next']
                if run:
                    SHARED['next'] = now + 1.0
        for aid_s, a in list(self.asteroids.items()) if run else []:
            try:                                        # bir asteroidin hatası ötekileri ve yakınlığı durdurmasın
                out = self.tick_asteroid(int(aid_s), a, now)
                msgs += [] if shared else out           # ortakta görünüm sürümle yenilenir (aşağıda), duyurular klana (tell)
            except Exception:
                if not self.tick_err.get(aid_s):
                    self.tick_err[aid_s] = True
                    self.log('   CBS: %s asteroidinde hata:\n%s' % (ASTEROIDS.get(int(aid_s), {}).get('name', aid_s), traceback.format_exc()))
        w = self.world
        if shared and w is not None:
            msgs += self.refresh_changed()
        if w and not w.hero_dead and BY_MAP.get(int(w.map_id)):
            hx, hy = w.hero_pos(now)
            near = next((aid for aid in BY_MAP[int(w.map_id)] if math.hypot(position(aid)[0] - hx, position(aid)[1] - hy)
                         <= D['range']), None)
            if near != self.near:
                if self.near:
                    msgs += [H.asset_available(asset_id(self.near), 'ttip_cbs', False),
                             ('OutOfBattleStationRangeCommand', {'battleStationId': asset_id(self.near)})]
                if near:
                    msgs += [H.asset_available(asset_id(near), 'ttip_cbs', True)] + self.ui_msgs(near)
                    msgs += self.p.hint(27) if getattr(self.p, 'hint', None) else []      # CLAN_BATTLE_STATION ipucu
                self.near = near
            if w:
                msgs += self.raid_tick(now)
                msgs += self.rival_fire(now)
        # AssetInfo invokes native BuildSelect. Background repairs/raids must
        # update other structures without replacing the player's target.
        if w is not None:
            msgs = [('AttackHitAssetCommand', dict(assetId=f['assetId'], hitpointsNow=f['hitpoints'],
                        hitpointsMax=f['maxHitpoints']))
                    if n == 'AssetInfoCommand' and f['assetId'] != w.target else (n, f) for n, f in msgs]
        return msgs

    def refresh_changed(self):
        """Ortak asteroitlerden sürümü değişenler (başka oturumun işi ya da sunucunun zamanlı işi): haritadakilerin varlıkları,
        yakınındakinin penceresi; kuruldu/yıkıldı: galaksi haritası."""
        msgs, star = [], False
        w = self.world
        for aid_s, a in list(self.asteroids.items()):
            aid = int(aid_s)
            v = (a.get('version', 0), a.get('state'))
            old = self.seen.get(aid)
            self.seen[aid] = v
            if old == v or aid not in ASTEROIDS:
                continue
            star = star or (old or (0, 'vacant'))[1] != v[1]
            if int(ASTEROIDS[aid]['map']) == int(w.map_id):
                msgs += self.refresh_assets(aid)
                if self.near == aid:
                    msgs += self.ui_msgs(aid)
        return msgs + (self.starmap_msgs() if star else [])

    def tick_asteroid(self, aid, a, now):
        msgs = []
        w = self.world
        here = w is not None and int(w.map_id) == int(ASTEROIDS[aid]['map'])
        if a.get('owner') != 'rival':
            done = [y for y in a['slots'].values()            # kurulumu biten modüller: adımda bir kez yenilenir
                    if y.get('install_sec') and not y.get('installed') and now >= y.get('install_end', 0)]
            for y in done:
                y['installed'] = True
                self.mark()
            if done:
                self.bump(a)
            if done and here and self.near == aid:
                msgs.append(self.progress_msg(aid, now) if a['state'] == 'vacant' else self.status_msg(aid, now))
            if done and a['state'] == 'built' and here:
                msgs += self.refresh_assets(aid)
        if a['state'] == 'building' and now >= a.get('build_end', 0):
            msgs += self.finish_build(aid, now)
        if a['state'] == 'built' and a.get('owner') != 'rival':        # rakibin deflector'ü ve onarımı rival_tick'te
            msgs += self.deflector_tick(aid, a, now)
            msgs += self.repair_tick(aid, a, now)
        msgs += self.rival_tick(aid, a, now)
        return msgs

    def refresh_assets(self, aid):
        msgs = []
        for i, k in [x for x in self.shown_assets if ASSET_BASE + aid * 100 <= x[0] < ASSET_BASE + aid * 100 + 100]:
            msgs.append(('AssetRemoveCommand', {'assetType': mod('AssetTypeModule', typeValue=k), 'uid': i}))
            self.shown_assets.remove((i, k))
        for i, k, cmd in self.map_assets(aid):
            self.shown_assets.append((i, k))
            msgs.append(cmd)
        return msgs

    # ------------------------------------------------------------ istekler
    def in_range(self, aid):
        w = self.world
        if not w or int(w.map_id) != int(ASTEROIDS.get(aid, {}).get('map', -1)):
            return False
        hx, hy = w.hero_pos()
        x, y = position(aid)
        return math.hypot(x - hx, y - hy) <= D['range'] + 100

    def handles(self, name, f):
        if name == 'MapAssetActivationRequest':
            return int(f.get('mapAssetId') or 0) // 100 * 100 - ASSET_BASE in [k * 100 for k in ASTEROIDS]
        return name in self.REQUESTS

    def handle(self, name, f):
        if name == 'MapAssetActivationRequest':
            aid = (int(f.get('mapAssetId') or 0) - ASSET_BASE) // 100
            return self.ui_msgs(aid) if aid in ASTEROIDS and self.in_range(aid) else []
        if name == 'HangarShipRepairModuleRequest':
            return self.hangar_repair(int(f.get('itemId') or 0))
        aid = int(f.get('battleStationId') or 0)
        if aid not in ASTEROIDS:
            return self.error('UNSPECIFIED')
        if not self.clan():
            return self.error('NO_CLAN')
        if not self.in_range(aid):
            return self.error('OUT_OF_RANGE')
        if name != 'EquipModuleRequest' and not self.mine(self.ast(aid)):
            return self.error('CONCURRENT_EQUIP')      # başka klanın istasyonu
        out = []
        if name == 'EquipModuleRequest':
            out = self.equip(aid, int(f.get('itemId') or 0), int(f.get('slotId') or 0), bool(f.get('replace')))
        elif name == 'UnequipModuleRequest':
            out = self.unequip(aid, int(f.get('itemId') or 0))
        elif name == 'BuildStationRequest':
            out = self.build(aid, int(f.get('buildTimeInMinutes') or 0))
        elif name == 'DeflectorShieldStatusChangeRequest':
            out = self.deflector_off(aid, int(f.get('minutes') or 0))
        elif name == 'EmergencyRepairRequest':
            out = self.emergency(aid, int(f.get('slotId') or 0))
        a = self.ast(aid)
        if out and out[0][0] != 'BattleStationErrorCommand':
            self.bump(a)                               # öteki oturumlar yenilesin; bu oturum yanıtla yeniledi
            self.seen[aid] = (a.get('version', 0), a.get('state'))
        return out

    def equip(self, aid, iid, slot, replace):
        a = self.ast(aid)
        now = time.time()
        m = self.own_module(iid)
        me = KL.name(self.p)
        if a.get('owner') == 'rival' or not self.mine(a):
            return self.error('CONCURRENT_EQUIP')
        if a['state'] == 'building':
            return self.error('STATION_ALREADY_BUILDING')
        if not m:
            return self.error('ITEM_NOT_OWNED')
        if self.where(iid):
            return self.error('ITEM_ALREADY_EQUIPPED_IN_ANOTHER_ASTEROID')
        if m['can'] <= 0:
            return self.error('ITEM_HITPOINTS_ZERO')
        if any(y.get('install_end', 0) > now and y.get('owner', me) == me for b in self.asteroids.values()
               for y in b.get('slots', {}).values()):
            return self.error('EQUIP_OF_SAME_PLAYER_RUNNING')
        md = MODS[m['loot']]
        if slot < 0 or slot >= SLOTS:
            return self.error('UNSPECIFIED')
        if slot <= DEFLECTOR and (not md['center'] or (slot == HULL) != (md['type'] == 2)):
            return self.error('HUB_ONLY' if not md['center'] else 'SATELLITE_ONLY')
        if slot > DEFLECTOR and md['center']:
            return self.error('SATELLITE_ONLY')
        same = sum(1 for s, y in a['slots'].items() if int(s) != slot and self.module(y['iid'])
                   and self.module(y['iid'])['loot'] == m['loot'])
        if same >= md['max_count']:
            return self.error('MAX_NUMBER_OF_MODULE_TYPE_EXCEEDED')
        old = a['slots'].get(str(slot))
        if old and not replace:
            return self.error('CONCURRENT_EQUIP')
        if old and not self.hp('battle_station_replace_module'):
            return self.error('REPLACE_RIGHT_MISSING')
        secs = D['swap_sec'] if a['state'] == 'built' else D['install_sec']
        old_loot = (self.module(old['iid']) or {}).get('loot', '') if old else ''
        y = {'iid': iid, 'install_end': now + secs, 'install_sec': secs}
        h = self.host
        if h is not None:                               # ortak: modül yuvaya (herkes görsün), benzersiz kimlikle
            cbs_h, mods, cid = h.d['cbs'], self.st['modules'], self.clan()['id']
            with self.lock:
                cbs_h['shared_seq'] = int(cbs_h.get('shared_seq', 0)) + 1
                y.update(iid=SHARED_ITEM + cbs_h['shared_seq'], module=m, owner=me, owner_name=self.p.d['pilot'].get('userName', ''))
                mods.pop(str(iid), None)
                a['clan'] = cid
        if old:
            self.give_back(old)
        with self.lock:
            a['slots'][str(slot)] = y
            self.mark()
        if old:
            self.note(aid, 'MODULE_REPLACED', oldModuleType=old_loot,
                      oldModuleLevel=0, newModuleType=m['loot'], newModuleLevel=m['level'], slot=slot if slot > DEFLECTOR else -1)
        self.log('   CBS: %s %s yuva %d (%d sn)' % (ASTEROIDS[aid]['name'], m['loot'], slot, secs))
        msgs = [self.progress_msg(aid, now) if a['state'] == 'vacant' else self.status_msg(aid, now), self.available_msg()]
        if a['state'] != 'vacant':
            msgs += self.refresh_assets(aid)
        return msgs

    def unequip(self, aid, iid):
        a = self.ast(aid)
        hit = next((s for s, y in a['slots'].items() if int(y['iid']) == iid), None)
        if hit is None:
            return self.error('ITEM_NOT_IN_STATION')
        y = a['slots'][hit]
        if y.get('owner', KL.name(self.p)) != KL.name(self.p) and not self.hp('battle_station_replace_module'):
            return self.error('REPLACE_RIGHT_MISSING')
        # kurulumu sürerken çıkarılan modül: istemcinin "The installation of this Module has been cancelled."
        abort = [stm('msg_station_module_install_aborted')] if y.get('install_end', 0) > time.time() else []
        m = self.module(iid)
        with self.lock:
            del a['slots'][hit]
            if not a['slots'] and a['state'] == 'vacant':
                a.pop('clan', None)                     # boşalan asteroit başka klanın da olabilir
            self.mark()
        self.give_back(y)
        self.note(aid, 'MODULE_REMOVED', moduleType=m['loot'] if m else '', moduleLevel=m['level'] if m else 0,
                  slot=int(hit) if int(hit) > DEFLECTOR else -1)
        if a['state'] == 'built' and int(hit) == HULL:
            self.destroy(aid, 'hull removed')
            return [self.building_ui(aid), self.available_msg()] + self.refresh_assets(aid) + abort
        msgs = [self.progress_msg(aid) if a['state'] == 'vacant' else self.status_msg(aid), self.available_msg()]
        return msgs + (self.refresh_assets(aid) if a['state'] != 'vacant' else []) + abort

    def build(self, aid, minutes):
        a = self.ast(aid)
        now = time.time()
        if a['state'] != 'vacant' or self.own_progress(aid, now) < 1.0:
            return self.error('STATION_ALREADY_BUILDING')
        if not self.hp('battle_station_build'):
            return self.error('UNSPECIFIED')
        k = D['build_min']
        minutes = max(k[0], min(k[1], minutes or k[0]))
        with self.lock:
            a.update(state='building', build_end=now + minutes * 60, build_sec=minutes * 60, owner='player')
            if self.host is not None:
                a['clan'] = self.clan()['id']
            a.pop('rival', None)
            a.pop('rival_progress', None)
            race = a.pop('race', None) or {}
            self.mark()
        for cid, r in race.items():                    # yarışan bot klanlarının modülleri stoklarına (klan_us)
            refund_race(cid, r.get('modules'))
        self.note(aid, 'BUILD_START', buildSeconds=minutes * 60)
        self.log('   CBS: %s kuruluyor (%d dk)' % (ASTEROIDS[aid]['name'], minutes))
        return [self.building_state(aid, now), ('VisualModifierCommand', self.construction_modifier(aid))]

    def stats(self, a):
        """İstasyon sayıları: tek oyunculuda profilde, ortakta istasyonun klanının kaydında."""
        if self.host is None:
            return self.st['stats']
        k = KL.CLANS.get(a.get('clan')) or {}
        return k.setdefault('cbs_stats', {})

    def finish_build(self, aid, now):
        a = self.ast(aid)
        ist, asteroids = self.stats(a), self.asteroids
        with self.lock:
            a.update(state='built', founded=now)
            a['deflector'] = {'on': True, 'sn': D['on_build_deflector_min'] * 60.0, 'closed_until': 0.0, 'last': now}   # forum 127469
            ist['all'] = ist.get('all', 0) + 1
            ist['max_count'] = max(ist.get('max_count', 0), sum(1 for b in asteroids.values() if b.get('state') == 'built'
                                                       and b.get('owner') != 'rival' and b.get('clan') == a.get('clan')))
            self.bump(a)
            self.mark()
        self.note(aid, 'BUILD_FINISHED')
        self.log('   CBS: %s kuruldu' % ASTEROIDS[aid]['name'])
        msgs = self.tell(a, [stm('msg_station_accomplished', STATION=ASTEROIDS[aid]['name'], CLAN=self.st_name(a),
                                 MAP=H.name(ASTEROIDS[aid]['map']))]) + self.starmap_msgs()
        w = self.world
        if w and int(w.map_id) == int(ASTEROIDS[aid]['map']):
            msgs += self.refresh_assets(aid)
            if self.near == aid:
                msgs.append(self.management_ui(aid))
        return msgs

    def deflector_charge(self, start, end, aid=None):
        """Integrate recharge over local prime-time boundaries, including offline time."""
        total = 0.0
        while start < end:
            day = datetime.datetime.fromtimestamp(start).replace(hour=0, minute=0, second=0, microsecond=0)
            boundaries = [day + datetime.timedelta(days=1)]
            for text in D.get('prime_time', ['18:00', '21:00']):
                hour, minute = map(int, text.split(':'))
                boundaries.append(day.replace(hour=hour, minute=minute))
            stop = min([end] + [t.timestamp() for t in boundaries if t.timestamp() > start])
            total += (stop - start) * self.deflector_rate(start, aid) / 60.0
            start = stop
        return total

    def deflector_tick(self, aid, a, now):
        df = a['deflector']
        cursor = min(now, df.get('last', now))
        changed, exhausted = False, False
        while True:
            if df['on']:
                elapsed = min(max(0.0, df['sn']), now - cursor)
                df['sn'] = max(0.0, df['sn'] - elapsed)
                cursor += elapsed
                if df['sn'] > 0:
                    break
                # Downtime starts at the actual exhaustion instant, even after a delayed tick.
                df.update(on=False, closed_until=cursor + D['deflector_end_off_min'] * 60)
                changed = exhausted = True
                self.bump(a)
                self.note(aid, 'DEFLECTOR_OFF')
            else:
                deadline = df.get('closed_until', 0)
                stop = min(now, max(cursor, deadline))
                if stop == cursor and df['sn'] <= 0:
                    stop = now
                df['sn'] = min(D['deflector_max_sec'], df['sn'] + self.deflector_charge(cursor, stop, aid))
                cursor = stop
                if cursor < deadline or df['sn'] <= 0:
                    break
                df['on'] = True
                changed = True
                self.bump(a)
                self.note(aid, 'DEFLECTOR_ON')
            if cursor >= now:
                break
        df['last'] = now
        self.mark()
        msgs = self.near_status(aid, now) if changed else []
        if exhausted and not df['on']:
            msgs += self.tell(a, [KAPI.screen('The deflector shield of your Battle Station at %s is down!' % ASTEROIDS[aid]['name'])])
        return msgs

    def near_status(self, aid, now):
        """World shield/timer effects and the nearby owner's management controls."""
        msgs = self.deflector_visuals(aid, now)
        if self.near == aid and self.mine(self.ast(aid)):
            msgs += [self.status_msg(aid, now), self.management_ui(aid, now)]
        return msgs

    def deflector_off(self, aid, minutes):
        a = self.ast(aid)
        if a['state'] != 'built':
            return self.error('UNSPECIFIED')
        if not self.hp('battle_station_deflector'):
            return self.error('UNSPECIFIED')
        now = time.time()
        # Settle the active countdown before resetting its clock for the requested downtime.
        pending = self.deflector_tick(aid, a, now)
        df = a['deflector']
        if not df['on']:
            return pending + self.error('DEFLECTOR_ALREADY_OFF')
        dm = D['deflector_min']
        minutes = max(dm[0], min(dm[1], minutes or dm[0]))
        with self.lock:
            df.update(on=False, closed_until=now + minutes * 60, last=now)
            self.bump(a)
            self.mark()
        self.note(aid, 'DEFLECTOR_OFF', userName=self.p.d['pilot'].get('userName', ''))
        self.log('   CBS: %s deflector %d dk kapalı' % (ASTEROIDS[aid]['name'], minutes))
        return pending + self.deflector_visuals(aid, now) + [self.status_msg(aid, now), self.management_ui(aid, now)]

    def emergency(self, aid, slot):
        a = self.ast(aid)
        y = a['slots'].get(str(slot))
        m = self.module(y['iid']) if y else None
        if not m or m['can'] <= 0:
            return self.error('REPAIR_NO_MODULE')
        now = time.time()
        if y.get('repair_end', 0) > now:
            return self.error('REPAIR_ALREADY_RUNNING')
        cost = D['emergency_repair']['charge']
        if self.p.d['pilot'].get('uridium', 0) < cost:
            return self.error('REPAIR_NO_MONEY')
        self.p.gain(uridium=-cost, reason='battlestation_emergency_repair')
        with self.lock:
            y['repair_end'] = now + D['emergency_repair']['sure_sn']
            self.mark()
        self.note(aid, 'EMERGENCY_REPAIR', moduleType=m['loot'], moduleLevel=m['level'], slot=slot if slot > DEFLECTOR else -1)
        return [self.status_msg(aid, now), stm('msg_emergency_repair_started', STATION=ASTEROIDS[aid]['name'])] + self.m.money_msgs()

    def repair_tick(self, aid, a, now):
        """Acil onarım (7.500/sn), Engineering Bay (bütün modüller) ya da son hasardan 30 sn sonra yavaş onarım; kalkan dolar."""
        rep = 0
        for y in a['slots'].values():
            m = self.module(y['iid'])
            if m and MODS[m['loot']].get('repair_sec') and m['can'] > 0 and y.get('install_end', 0) <= now:
                rep = level_value(MODS[m['loot']]['repair_sec'], m['level'])
        changed = []
        for slot, y in a['slots'].items():
            m = self.module(y['iid'])
            if not m or m['can'] <= 0:
                continue
            mh, ms = self.mx(m)
            heal = 0
            if y.get('repair_end', 0) > now:
                heal += D['emergency_repair']['hp_sec']
            if rep:
                heal += rep
            elif now - a.get('last_damage', 0) > D['passive_repair']['delay_sec']:
                heal += D['passive_repair']['hp_sec']
            before = (m['can'], m['kalkan'])
            m['can'] = min(mh, m['can'] + heal)
            if now - a.get('last_damage', 0) > 10:
                m['kalkan'] = min(ms, m['kalkan'] + ms * 0.02)
            if (m['can'], m['kalkan']) != before:
                changed.append(int(slot))
        w = self.world
        if changed and w and int(w.map_id) == int(ASTEROIDS[aid]['map']) and int(now) % 5 == 0:
            return [c for c in (self.info_cmd(aid, s) for s in changed) if c]
        return []

    def hangar_repair(self, iid):
        m = self.own_module(iid)
        if not m:
            return []
        mh, ms = self.mx(m)
        from shop import stack_msg
        if self.where(iid):
            return [('HangarShipRepairModuleCommand', dict(errorMessage=stack_msg('eqt_error_playerMayNotRepair'), itemId=iid,
                                                            currentHitPoints=int(m['can']), maxHitPoints=mh, resultId=1))]
        cost = max(D['repair_cost']['en_az'], int((mh - m['can']) * D['repair_cost']['per_hp_U']))
        if m['can'] >= mh or self.p.d['pilot'].get('uridium', 0) < cost:
            return [('HangarShipRepairModuleCommand', dict(errorMessage=stack_msg('empty'), itemId=iid, currentHitPoints=int(m['can']),
                                                            maxHitPoints=mh, resultId=1))]
        self.p.gain(uridium=-cost, reason='repair_module')
        with self.p.lock:
            m['can'], m['kalkan'] = mh, ms
            self.p.dirty = True
        self.log('   CBS: modül onarıldı %s (%d U)' % (m['loot'], cost))
        return [('HangarShipRepairModuleCommand', dict(errorMessage=stack_msg('empty'), itemId=iid, currentHitPoints=mh, maxHitPoints=mh,
                                                        resultId=0))] + self.m.money_msgs()

    # ------------------------------------------------------------ boosterlar ve ticaret
    def mods(self):
        """Clan-wide XP/honor stack globally up to 50%; damage applies on the station map."""
        clan = self.clan()
        if not self.p.d['pilot'].get('clanId') or not clan:
            return {}
        out = {}
        here = int(self.p.d['position'].get('mapId', 0))
        for aid_s, a in list(self.asteroids.items()):
            if a.get('state') != 'built' or not self.mine(a) or a.get('clan') not in (None, clan['id']):
                continue
            aid = int(aid_s)
            out['honor'] = min(D['booster']['cap'], out.get('honor', 0) + self.booster_pct(aid, 'honor') / 100.0)
            out['ep'] = min(D['booster']['cap'], out.get('ep', 0) + self.booster_pct(aid, 'ep') / 100.0)
            if int(ASTEROIDS[aid]['map']) == here:
                d = self.booster_pct(aid, 'damage') / 100.0
                out['laser'] = max(out.get('laser', 0), d)
                out['rocket'] = max(out.get('rocket', 0), d)
        return {k: v for k, v in out.items() if v}

    def trade_mult(self):
        """Kendi istasyonunun menzilinde maden satışı (TradeType BATTLE_STATION, fiyat x1,1) -> çarpan ya da None."""
        if self.near and self.ast(self.near)['state'] == 'built' and self.mine(self.ast(self.near)):
            return D['ore_multiplier']
        return None

    # ------------------------------------------------------------ hasar ve yıkım (baskın ve rakip)
    def damage_module(self, aid, slot, dmg, attacker_name='', shield_only=False, hull_only=False):
        """Modüle hasar (kalkan %80 emer) -> mesajlar; can 0: yok olur; merkez (Hull) giderse istasyon düşer."""
        a = self.ast(aid)
        y = a['slots'].get(str(slot))
        rival = a.get('owner') == 'rival'
        m = y if rival else (self.module(y['iid']) if y else None)
        if not m or m['can'] <= 0:
            return []
        dmg = max(0, int(dmg))
        if shield_only:
            dmg = min(dmg, m['kalkan'])
        to_shield = dmg if shield_only else 0 if hull_only else min(m['kalkan'], int(dmg * 0.8))
        m['kalkan'] -= to_shield
        m['can'] = max(0, m['can'] - (dmg - to_shield))
        a['last_damage'] = time.time()
        self.mark()
        msgs = [c for c in [self.info_cmd(aid, slot, m)] if c]
        if m['can'] <= 0:
            msgs += self.module_destroyed(aid, slot, attacker_name)
        return msgs

    def module_destroyed(self, aid, slot, by=''):
        a = self.ast(aid)
        rival = a.get('owner') == 'rival'
        y = a['slots'].get(str(slot))
        m = y if rival else self.module(y['iid'])
        msgs = []
        self.note(aid, 'MODULE_DESTROYED', moduleType=m['loot'], moduleLevel=m['level'], slot=slot if slot > DEFLECTOR else -1,
                  opponentClanName=by)
        if rival or self.bot_demolition(a):                 # oyuncu rakibin (ya da bot klanının) modülünü yıktı: uridyum
            kind = MODS[m['loot']].get('weapon') or 'other'
            u = D['demolish_reward']['base'].get(kind, D['demolish_reward']['base']['other']) + D['demolish_reward']['per_level'] * m['level']
            u = SET.amount('uridium', u, 'mod')              # panelin uridyum çarpanı
            self.p.gain(uridium=u, reason='battlestation_destroy_module')
            msgs += [stm('msg_station_satellite_destruction_reward', AMOUNT=u, MODULE=MODS[m['loot']]['code'], LEVEL=m['level'] + 1,
                         STATION=ASTEROIDS[aid]['name'])] + self.m.money_msgs()
        elif self.world:                                # oyuncunun modülü yıkıldı: uyarı (ortakta klana)
            msgs += self.tell(a, [stm('msg_station_module_destroyed', STATION=ASTEROIDS[aid]['name'], MAP=H.name(ASTEROIDS[aid]['map']),
                                      MODULE=MODS[m['loot']]['code'], LEVEL=m['level'] + 1)])
        self.bump(a)
        if slot == HULL:
            msgs += self.destroy(aid, by)
        elif self.world:
            msgs += self.refresh_assets(aid)
            self.seen[aid] = (a.get('version', 0), a.get('state'))
        return msgs

    def clan_asteroids(self, k):
        """Klanın modül takılı ya da kurulu asteroitleri (tek oyunculuda oyuncunun rakip dışındakileri)."""
        for aid, a in list(self.asteroids.items()):
            if a.get('owner') == 'rival' or not (a.get('slots') or a.get('state') in ('building', 'built')):
                continue
            if self.host is not None and a.get('clan') != k['id']:
                continue
            yield int(aid), a

    def member_left(self, k, who):
        """Klandan ayrılan ya da atılan üyenin modülleri istasyonlardan envanterine döner (forum 127469). Merkezi (Hull) çıkan kurulu
        istasyon düşer (unequip'teki kural; forumda 1 canla kalır: uyarlama)."""
        me, msgs = KL.name(self.p), []
        for aid, a in self.clan_asteroids(k):
            for s, y in list(a['slots'].items()):
                if y.get('owner', me) != who:
                    continue
                with self.lock:
                    a['slots'].pop(s, None)
                    self.bump(a)
                    self.mark()
                self.give_back(y)
                self.note(aid, 'MODULE_REMOVED', slot=int(s) if int(s) > DEFLECTOR else -1)
                if a['state'] == 'built' and int(s) == HULL:
                    msgs += self.destroy(aid, 'hull removed')
                    break
            if a.get('state') == 'vacant' and not a.get('slots'):
                a.pop('clan', None)
        return msgs + (self.starmap_msgs() if msgs else [])

    def clan_disbanded(self, k):
        """Klan silindi: istasyonları yıkılır, modülleri (yok olmuş) sahiplerine, asteroit boş (forum 127469)."""
        msgs = []
        for aid, a in list(self.clan_asteroids(k)):
            msgs += self.destroy(aid, 'clan disbanded')
        return msgs

    def bot_demolition(self, a):
        """Bot klanının istasyonunu bu oturumun oyuncusu mu yıktı (son 30 sn'de vurdu): rakibinki gibi ödül."""
        return (a.get('owner') == 'bot' and self.m is not None and self.world is not None
                and time.time() - a.get('last_player', 0) < 30 and a.get('last_attacker') == self.p.d['pilot'].get('userName', ''))

    def destroy(self, aid, by=''):
        """İstasyon düştü: modüller (yok olmuş) envantere, asteroit boş."""
        a = self.ast(aid)
        rival = a.get('owner') == 'rival'
        msgs = []
        if rival or self.bot_demolition(a):
            r = D['demolish_reward']['center']
            r = dict(r, uridium=SET.amount('uridium', r['uridium'], 'mod'), credits=SET.amount('credits', r['credits'], 'mod'))     # panelin çarpanları
            self.p.gain(uridium=r['uridium'], credits=r['credits'], reason='battlestation_destroy_station')
            msgs += [stm('msg_station_hub_destruction_reward', AMOUNT=r['uridium'], STATION=ASTEROIDS[aid]['name']),
                     stm('msg_station_destroyed_by_clan', DESTROYER=self.clan_name(), LOSER=a.get('rival', '') if rival else self.st_name(a),
                         STATION=ASTEROIDS[aid]['name'], MAP=H.name(ASTEROIDS[aid]['map']))] + self.m.money_msgs()
        if not rival:
            for y in a['slots'].values():
                m = self.module(y['iid'])
                if m:
                    m['can'], m['kalkan'] = 0, 0
                self.give_back(y)                       # ortak: yok olmuş modül sahibine
            ist = self.stats(a)
            ist['demolished'] = ist.get('demolished', 0) + 1
            ist['longest_sec'] = max(ist.get('longest_sec', 0), int(time.time() - a.get('founded', time.time())))
            msgs += self.tell(a, [stm('msg_station_destroyed', LOSER=self.st_name(a), STATION=ASTEROIDS[aid]['name'],
                                      MAP=H.name(ASTEROIDS[aid]['map']))])
        self.note(aid, 'DESTROYED', opponentClanName=by)
        self.log('   CBS: %s istasyonu yıkıldı (%s)' % (ASTEROIDS[aid]['name'], by or 'player'))
        asteroids = self.asteroids
        with self.lock:
            asteroids[str(aid)] = {'state': 'vacant', 'slots': {}, 'rival_round': a.get('rival_round', 0) + (1 if rival else 0),
                              'version': a.get('version', 0) + 1}
            self.mark()
        self.ast(aid)
        for i in [i for i, k in self.raiders.items() if k == aid]:
            self.raiders.pop(i, None)
        msgs += self.starmap_msgs()
        if self.world:
            msgs += self.refresh_assets(aid)
        self.seen[aid] = (self.ast(aid).get('version', 0), 'vacant')
        if self.near == aid and not rival:
            msgs += [self.building_ui(aid), self.available_msg()]
        return msgs

    @staticmethod
    def weapon_visual(md, attacker, target, hit):
        """Single native rocket for RAM modules; lasers keep the beam command.

        1.1.115 Hellstorm handler resolves generic map entities, including CBS
        satellites. ECO-10 appearance is a local reuse, not an official RAM skin.
        """
        if md['weapon'] == 'rocket':
            return ('HellstormAttackCommand', dict(attackerId=attacker, targetId=target, hit=hit, currentLoad=1,
                                                  rocketType=mod('AmmunitionTypeModule', typeValue=23)))
        return ('AttackLaserRunCommand', dict(attackerId=attacker, targetId=target, laserColor=0,
                                             isDiminishedBySkillShield=False, skilledLaser=False, visualType=0))

    # ------------------------------------------------------------ CBS-3: uzaylı baskınları
    def raid_tick(self, now):
        w = self.world
        msgs = []
        for aid in BY_MAP.get(int(w.map_id), []):
            a = self.ast(aid)
            if a['state'] != 'built' or a.get('owner') == 'rival':
                continue
            open_ = not a['deflector']['on']
            due = a.get('next_raid', 0) if self.host is not None else self.next_raid.get(aid, 0)   # ortakta haritada tek baskın
            if open_ and prime_time(now) and now >= due:
                self.next_raid[aid] = a['next_raid'] = now + D['raid']['interval_min'] * 60
                msgs += self.spawn_raid(aid)
            msgs += self.raid_fight(aid, a, now)
        return msgs

    def spawn_raid(self, aid):
        w = self.world
        cls = H.map_class(ASTEROIDS[aid]['map'])
        kinds = D['raid']['kinds'].get(cls) or ['81']
        x, y = position(aid)
        n = random.randint(*D['raid']['count'])
        hp_each, dmg_each = self.raid_power(aid, n, time.time())
        prep = lambda nn: PS.scale_npc(nn, hp=max(1.0, hp_each / max(1, nn.d['hp'] + nn.d['kalkan'])),     # oyuncuya türün hasarı
                                       extra={'station_damage': max(nn.d['damage'], int(dmg_each))})
        for _ in range(n):
            a, r = random.uniform(0, 2 * math.pi), random.uniform(900, 1300)
            nx = min(max(int(x + math.cos(a) * r), 300), w.map_w - 300)
            ny = min(max(int(y + math.sin(a) * r), 300), w.map_h - 300)
            npc = w.spawn_npc_at(random.choice(kinds), nx, ny, prep=prep)
            npc.gate = True
            npc.next_think = time.time() + 10 ** 6         # hareketi baskın yönetir (vurulunca oyuncuyla savaşır)
            self.raiders[npc.id] = aid
            tx, ty = x + random.randint(-300, 300), y + random.randint(-200, 200)
            ms = npc.mover.go(tx, ty, max(150, npc.d.get('speed', 300)), time.time())
            w.send([('MoveCommand', dict(userId=npc.id, x=int(tx), y=int(ty), timeToTarget=ms))])
        self.log('   CBS: %s uzaylı baskını (%d)' % (ASTEROIDS[aid]['name'], n))
        return [KAPI.screen('key:msg_object_under_attack', big=True, ASSET_NAME='Battle Station %s' % ASTEROIDS[aid]['name'])]

    def raid_power(self, aid, n, now):
        """Baskıncı başına can+kalkan ve atış hasarı istasyona göre (haritanın sıradan uzaylıları 1 milyonluk uyduları çizemiyordu;
        canlı test: baskın 10 sn'de bitti): silahlar baskını yardımsız ~sure_sn'de temizler, o sürede baskın modüllerin can+kalkanının
        ~hasar_orani'nı götürür. Oyuncu da vurursa daha erken biter."""
        B = D['raid']
        boost = 1 + self.booster_pct(aid, 'damage', now) / 100.0
        dps = total = 0.0
        for slot_info in self.ast(aid)['slots'].values():
            m = self.module(slot_info['iid'])
            if not m or m['can'] <= 0:
                continue
            md = MODS[m['loot']]
            total += m['can'] + m['kalkan']
            if md.get('weapon'):
                dps += dmg_value(md, m['level']) * boost * md['hit'] / md['interval_sec']
        shots = B['sure_sn'] / world_module.COMBAT['npc_attack_interval_sec']
        return dps * B['sure_sn'] / n, total * B['damage_ratio'] / shots / n

    def raid_fight(self, aid, a, now):
        w = self.world
        msgs = []
        x, y = position(aid)
        alive = [w.npcs[i] for i, k in list(self.raiders.items()) if k == aid and i in w.npcs and w.npcs[i].alive]
        for i in [i for i, k in list(self.raiders.items()) if k == aid and i not in w.npcs]:
            self.raiders.pop(i, None)
        # uzaylılar modülleri vurur (oyuncuyla savaşmayanlar)
        targets = [int(s) for s, slot_info in a['slots'].items() if self.module(slot_info['iid']) and self.module(slot_info['iid'])['can'] > 0]
        for n in alive:
            if n.engaged or now < self.next_shot.get(n.id, 0):
                continue
            nx, ny = n.mover.pos(now)
            if math.hypot(nx - x, ny - y) > 700 and math.hypot(n.mover.x1 - x, n.mover.y1 - y) > 700:   # oyuncudan kopan: istasyona döner
                w.alien_ceasefire(n)                    # istasyona ateş ediyorsa istemcide lazer durumu kapanır (AttackAbortLaserCommand)
                n.next_think = now + 10 ** 6
                tx, ty = x + random.randint(-300, 300), y + random.randint(-200, 200)
                ms = n.mover.go(tx, ty, max(150, n.d.get('speed', 300)), now)
                w.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])
                continue
            if math.hypot(nx - x, ny - y) > 700 or not targets:
                w.alien_ceasefire(n)                    # menzil dışı ya da hedef kalmadı: lazer bitti
                continue
            n.firing = True                             # istasyona lazer açtı: bırakınca alien_ceasefire AttackAbortLaserCommand yollar
            self.next_shot[n.id] = now + world_module.COMBAT['npc_attack_interval_sec']
            sats = [s for s in targets if s > DEFLECTOR]
            slot = random.choice(sats) if sats else HULL
            dmg = int(n.d.get('station_damage', n.d['damage']) * random.uniform(0.8, 1.0))
            w.send([('AttackLaserRunCommand', dict(attackerId=n.id, targetId=asset_id(aid, slot), laserColor=0,
                                                   isDiminishedBySkillShield=False, skilledLaser=False, visualType=0))])
            msgs += self.damage_module(aid, slot, dmg, n.d['name'])
            if self.ast(aid)['state'] != 'built':
                return msgs
        # silah modülleri menzildeki baskıncılara ateş eder
        dmg_boost = 1 + self.booster_pct(aid, 'damage', now) / 100.0
        for s, slot_info in a['slots'].items():
            m = self.module(slot_info['iid'])
            md = MODS[m['loot']] if m else {}
            if not m or not md.get('weapon') or m['can'] <= 0 or slot_info.get('install_end', 0) > now:
                continue
            key = (aid, int(s))
            if now < self.next_shot.get(key, 0):
                continue
            sx, sy = satellite_pos(aid, int(s))
            near = [n for n in alive if n.alive and math.hypot(n.mover.pos(now)[0] - sx, n.mover.pos(now)[1] - sy) <= md['range']]
            if not near:
                continue
            self.next_shot[key] = now + md['interval_sec']
            n = random.choice(near)
            hit = random.random() < md['hit']
            atype = 0 if md['weapon'] == 'rocket' else 1
            w.send([self.weapon_visual(md, asset_id(aid, int(s)), n.id, hit)])
            if hit:
                w.hit_npc(n.id, int(dmg_value(md, m['level']) * dmg_boost), atype, attacker=asset_id(aid, int(s)), engage=False, source_asset=True)
            else:
                w.send([('AttackMissedCommand', dict(attackType=world_module.attack_type(atype), targetUserId=n.id, skillColorId=0))])
        return msgs

    # ------------------------------------------------------------ CBS-4: sanal rakip klanlar
    def rival_tick(self, aid, a, now):
        """Boş asteroitte rakip klan (tohumlu): ilerler, önce bitirirse düşman istasyonu kurar. Botlar varken sahte rakip yok:
        kurduğu istasyon ve ilerlemesi bir kez silinir, asteroit boş açılır (yarış bot klanlarının: klan_us)."""
        if with_bots():
            if a.get('owner') == 'rival' or a.get('rival') is not None:
                with self.lock:
                    if a.get('owner') == 'rival':
                        a.update(state='vacant', slots={}, deflector={'on': False, 'sn': 0.0, 'closed_until': 0.0, 'last': now})
                        a.pop('owner', None)
                    for f in ('rival', 'rival_progress', 'rival_speed', 'rival_company', 'rival_last'):
                        a.pop(f, None)
                    self.bump(a)
                    self.mark()
                self.log('   CBS: %s sahte rakipten temizlendi (botlar var)' % ASTEROIDS[aid]['name'])
                return self.starmap_msgs() + (self.refresh_assets(aid) if self.world and int(self.world.map_id) == int(ASTEROIDS[aid]['map'])
                                              else [])
            return []
        if a['state'] == 'building' or (a['state'] == 'built' and a.get('owner') != 'rival'):
            return []
        msgs = []
        if a['state'] == 'vacant':
            if 'rival' not in a:
                rnd = random.Random('%s-%s' % (aid, a.get('rival_round', 0)))
                if rnd.random() < D['rival']['probability']:
                    hours = rnd.uniform(*D['rival']['duration_hours'])
                    fac = self.faction() if self.host is None else 0          # ortakta rakibin firması oyuncuya göre değil
                    a.update(rival=rnd.choice(D['rival']['clans']), rival_progress=0.0, rival_speed=1.0 / (hours * 3600),
                             rival_company=rnd.choice([f for f in (1, 2, 3) if f != fac] or [1]), rival_last=now)
                else:
                    a['rival'] = None
                self.mark()
            if a.get('rival'):
                slow = 0.5 if self.own_progress(aid, now) > 0 else 1.0          # oyuncu da kuruyorsa rakip yavaşlar
                a['rival_progress'] = min(1.0, a.get('rival_progress', 0) + (now - a.get('rival_last', now)) * a['rival_speed'] * slow)
                a['rival_last'] = now
                if a['rival_progress'] >= 1.0 and self.own_progress(aid, now) < 1.0:
                    msgs += self.rival_build(aid, a, now)
        elif a.get('owner') == 'rival':
            df = a.setdefault('deflector', {})
            active = bool(D['rival'].get('deflector_outside_prime') and not prime_time(now)
                          and now >= df.get('closed_until', 0))
            if bool(df.get('on')) != active:
                df['on'] = active
                self.bump(a)
                self.mark()
                msgs += self.deflector_visuals(aid, now)
            msgs += self.rival_repair(aid, a, now)
        return msgs

    def rival_repair(self, aid, a, now):
        """Saldırı kesilince (pasif_onarim.gecikme_sn) rakibin canlı modülleri onarılır, kalkanları dolar; haritadaysa 5 sn'de bir
        can çubukları."""
        dt = min(5.0, max(0.0, now - a.get('last_repair', now)))
        a['last_repair'] = now
        po = D['passive_repair']
        if not dt or now - a.get('attack_at', 0) < po['delay_sec']:
            return []
        changed = []
        for s, y in a['slots'].items():
            mx = hp_max(y)
            ms = min(SET.I32, int(mx * D['shield_ratio']))
            if y['can'] <= 0 or (y['can'] >= mx and y['kalkan'] >= ms):
                continue
            y['can'] = min(mx, y['can'] + po['hp_sec'] * dt)
            y['kalkan'] = min(ms, y['kalkan'] + ms * 0.02 * dt)
            changed.append(int(s))
        if not changed:
            return []
        self.mark()
        w = self.world
        if not w or int(w.map_id) != int(ASTEROIDS[aid]['map']) or now < a.get('repair_notice', 0):
            return []
        a['repair_notice'] = now + 5
        return [c for c in (self.info_cmd(aid, s) for s in changed if s != DEFLECTOR) if c]

    def rival_build(self, aid, a, now):
        """Rakip istasyonu: merkez (Hull, Deflector) ve 8 uydu, seviye 0, oyuncunun modüllerinden bağımsız."""
        free = [y['iid'] for y in a['slots'].values() if 'iid' in y]       # oyuncunun kurulmamış modülleri
        rnd = random.Random('%s-b' % aid)
        sats = ['module_ltm-lr', 'module_ltm-mr', 'module_ltm-hr', 'module_ram-la', 'module_ram-ma', 'module_repm-1', 'module_honm-1',
                'module_xpm-1']
        slots = {str(HULL): 'module_hulm-1', str(DEFLECTOR): 'module_defm-1'}
        for s in range(2, SLOTS):
            slots[str(s)] = sats[(s - 2) % len(sats)] if s < 4 else rnd.choice(sats[:5])
        slot_info = {}
        for s, loot in slots.items():
            hp = int(level_value(MODS[loot]['can'], 0) * D['rival']['hp_multiplier'])      # tek oyunculu: tek gemi yıkabilsin
            slot_info[s] = dict(loot=loot, level=0, can=hp, kalkan=int(hp * D['shield_ratio']), maximum=hp)
        for y in list(a['slots'].values()):            # ortak: kurulmamış modüller sahiplerine
            self.give_back(y)
        with self.lock:
            a.update(state='built', owner='rival', slots=slot_info, founded=now, deflector={'on': True})
            a.pop('clan', None)
            self.bump(a)
            self.mark()
        self.log('   CBS: rakip %s, %s istasyonunu kurdu (oyuncunun %d modülü envantere)' % (a['rival'], ASTEROIDS[aid]['name'], len(free)))
        msgs = [stm('msg_station_built', CLAN=a['rival'], STATION=ASTEROIDS[aid]['name'], MAP=H.name(ASTEROIDS[aid]['map']))] + self.starmap_msgs()
        if self.world and int(self.world.map_id) == int(ASTEROIDS[aid]['map']):
            msgs += self.refresh_assets(aid)
        return msgs

    def rival_attackable(self, aid):
        a = self.ast(aid)
        return a.get('owner') == 'rival' and a['state'] == 'built' and not (a.get('deflector') or {}).get('on')

    def hit_asset(self, asset, dmg):
        """Oyuncunun rakip istasyonuna vuruşu (varlık kimliği) -> mesajlar."""
        aid, slot = self.asset_slot(asset)
        if aid is None:
            return []
        return self.asset_attackable(asset) or self.asset_hit(asset, dmg)

    # ------------------------------------------------------------ dünyanın asset_targets arayüzü (dunya.select/laser_start/asset_laser)
    @staticmethod
    def asset_slot(uid):
        try:
            uid = int(uid or 0)
        except (TypeError, ValueError, OverflowError):
            return None, None
        aid = (uid - ASSET_BASE) // 100
        slot = uid - ASSET_BASE - aid * 100
        return (aid, slot) if aid in ASTEROIDS and 0 <= slot < SLOTS and slot != DEFLECTOR else (None, None)

    def asset_module(self, uid):
        """Current-map live installed module, resolved from its owner store."""
        aid, slot = self.asset_slot(uid)
        w = self.world
        if aid is None or not w or int(w.map_id) != int(ASTEROIDS[aid]['map']):
            return None
        a = self.ast(aid)
        y = a['slots'].get(str(slot)) if a['state'] == 'built' else None
        m = (y if a.get('owner') == 'rival' else self.module(y.get('iid'))) if y else None
        return m if m and m.get('can', 0) > 0 else None

    def asset_pos(self, uid):
        """Selection is available for friendly and shielded assets too."""
        if not self.asset_module(uid):
            return None
        aid, slot = self.asset_slot(uid)
        return position(aid) if slot == HULL else satellite_pos(aid, slot)

    def asset_select(self, uid):
        m = self.asset_module(uid)
        if not m:
            return []
        aid, slot = self.asset_slot(uid)
        # Native BuildSelect consumes AssetInfo, not the ship-only selection handler.
        return [self.info_cmd(aid, slot, m)]

    def asset_attackable(self, uid):
        """[] vurulabilir; deflector açıksa istemcinin uyarısı."""
        aid, slot = self.asset_slot(uid)
        if self.asset_module(uid):
            a = self.ast(aid)
            hostile = self.rival_attackable(aid) or (self.host is not None and not self.mine(a)
                and self.relation(a) == 3 and not a['deflector'].get('on'))
            if hostile:
                return []
        return [legacy('0|A|STM|msg_station_not_atackable')]

    def asset_hit(self, uid, dmg):
        return self.asset_damage(uid, dmg, atype=1)

    def assets_near(self, x, y, r):
        """Bu haritada (x, y)'ye r birimden yakın, vurulabilir modüllerin kimlikleri (P.E.T. kamikazesi: pet.kamikaze)."""
        out = []
        for aid in ASTEROIDS:
            for slot in range(SLOTS):
                uid = ASSET_BASE + aid * 100 + slot
                pos = self.asset_pos(uid) if slot != DEFLECTOR else None
                if pos and math.hypot(pos[0] - x, pos[1] - y) <= r and not self.asset_attackable(uid):
                    out.append(uid)
        return out

    def asset_damage(self, uid, dmg, atype=0, shield_only=False, hull_only=False, attacker=None):
        denied = self.asset_attackable(uid)
        if denied:
            return denied
        aid, slot = self.asset_slot(uid)
        a = self.ast(aid)
        a['attack_at'] = time.time()
        if a.get('owner') == 'bot':                     # bot klanı kimin vurduğunu bilir (savunma, kin: klan_us); yıkım ödülü
            a.update(last_player=a['attack_at'], last_attacker=self.p.d['pilot'].get('userName', ''), last_attacker_clan=self.clan_name())
        hit_module = self.asset_module(uid)
        hp_before, shield_before = hit_module['can'], hit_module['kalkan']
        msgs = self.damage_module(aid, slot, dmg, self.clan_name(), shield_only=shield_only, hull_only=hull_only)
        w = self.world
        if w is not None:
            w.last_shield_hit = shield_before - hit_module['kalkan']
        # AssetInfo invokes BuildSelect -> UnitDeselect on every hit, clearing
        # ShipInfo.IsAtk and making a moving hero face its route instead of the target.
        # AttackHit updates Entity numeric values and emits the floating damage number.
        msgs = [(name, fields) for name, fields in msgs if name != 'AssetInfoCommand']
        amount = int(hp_before - hit_module['can'] + shield_before - hit_module['kalkan'])
        hit = ('AttackHitCommand', dict(attackType=world_module.attack_type(atype), attackerId=attacker if attacker is not None else w.hid if w else self.p.user_id,
            victimId=int(uid), victimHitpoints=int(hit_module['can']), victimShield=int(hit_module['kalkan']),
            victimNanoHull=0, damage=amount, skilled=atype == 1, strike=False, cannonType=0))
        bar = ('AttackHitAssetCommand', dict(assetId=int(uid), hitpointsNow=int(hit_module['can']),
            hitpointsMax=hp_max(hit_module)))
        if self.host is not None and w is not None and w.shared is not None:
            for o in list(w.shared.members):
                if o is not w and o.running and o.target == uid:
                    o.deliver([hit, bar])
        return [hit, bar] + msgs

    def rival_fire(self, now):
        """Kurulu rakip istasyonun silahları menzildeki oyuncuya tam modül hasarı (rakip.hasar_carpani varsayılan 1,0). Deflector
        yalnız istasyonu dokunulmaz yapar, silahlar yine ateş eder (fandom Clan Battle Stations: kurulumdan sonra "the module will
        start to attack"); gizlenmiş gemi hedeflenmez (oyuncu bildirimi 2026-10-30: yalnız deflector kapalıyken ve gizlenmeye bakmadan
        ateş ediyordu). Ölüm ekranında neden BATTLESTATION; lazer/roket kendi saldırı türünü kullanır."""
        w = self.world
        if not w or w.hero_dead or getattr(w, 'jumping', False):
            return []
        hx, hy = w.hero_pos(now)
        cloaked = w.hidden(now)
        for aid in BY_MAP.get(int(w.map_id), []):
            a = self.ast(aid)
            bot_st = a.get('owner') == 'bot' and self.host is not None and not self.mine(a) and self.relation(a) == 3
            if (a.get('owner') != 'rival' and not bot_st) or a['state'] != 'built':
                continue                                # bot klanının istasyonu da düşmanına ateş eder (klan_us)
            tag = a.get('rival', '') if not bot_st else (self.st_clan(a) or {}).get('tag', '')
            for s, slot_info in list(a['slots'].items()):
                y = slot_info if not bot_st else slot_info.get('module')
                if not y:
                    continue
                md = MODS[y['loot']]
                if not md.get('weapon') or y['can'] <= 0 or w.hero_dead:
                    continue
                sx, sy = satellite_pos(aid, int(s))
                key = ('rival', aid, int(s))
                if now < self.next_shot.get(key, 0):
                    continue
                candidates = []
                distance = math.hypot(sx - hx, sy - hy)
                if distance <= md['range'] and not cloaked:
                    candidates.append((distance, 0, w.hid, None))
                pet = getattr(w, 'pet', None)
                if pet and pet.active and pet.alive and pet.w is w:
                    px, py = pet.pos(now)
                    distance = math.hypot(sx - px, sy - py)
                    if distance <= md['range']:
                        candidates.append((distance, 1, pet.pid, pet))
                if not candidates:
                    continue
                _, _, target_uid, target_pet = min(candidates, key=lambda row: row[:2])
                self.next_shot[key] = now + md['interval_sec']
                uid = asset_id(aid, int(s))
                defense = {} if target_pet else self.p.mods()
                evasion = max(0.0, min(1.0, target_pet.proto('evasion') if target_pet else defense.get('evasion', 0)))
                hit = random.random() < md['hit'] * (1 - evasion)
                atype = 0 if md['weapon'] == 'rocket' else 1
                laser_factor = max(0.0, 1 + defense.get('laser_taken', 0)) if atype == 1 else 1.0
                visual = self.weapon_visual(md, uid, target_uid, hit)
                if atype == 1:
                    visual[1]['isDiminishedBySkillShield'] = laser_factor < 1 or (not target_pet and w.skill_shield())
                w.send([visual])
                if hit:
                    dmg = int(round(dmg_value(md, y['level']) * D['rival']['damage_multiplier'] * laser_factor))
                    if target_pet:
                        actual = target_pet.station_hit(dmg, uid, atype=atype, now=now)
                    else:
                        who = types.SimpleNamespace(id=uid, alive=False, d={'name': '%s [%s]' % (md['code'], tag)})
                        g = self.p.d['ship']
                        before = g.get('hitPoints', 0) + g.get('shield', 0) + g.get('nanoHull', 0)
                        w.send(w.hurt_hero(dmg, killer=who, atype=atype, cause=DESTRUCTION_BATTLESTATION, now=now, source_asset=True))
                        actual = before - g.get('hitPoints', 0) - g.get('shield', 0) - g.get('nanoHull', 0)
                    if actual > 0:
                        w.last_asset_attacker = (uid, now)
                else:
                    w.send([('AttackMissedCommand', dict(attackType=world_module.attack_type(atype), targetUserId=target_uid, skillColorId=0))])
        return []

    # ------------------------------------------------------------ klan sekmesi ve günlük
    def log_of(self, cid=None):
        """İstasyon günlüğü: tek oyunculuda profilde, ortakta klanın kaydında (cid; verilmezse oyuncunun klanı)."""
        if self.host is None:
            return self.st['daily']
        k = KL.CLANS.get(cid) if cid else self.clan()
        return k.setdefault('cbs_log', []) if k is not None else []

    def note(self, aid, kind, **values):
        a = ASTEROIDS[aid]
        e = dict(type=kind, date=stamp(), stationId=aid, stationName=a['name'], mapName=H.name(a['map']),
                 userName=values.pop('userName', ''), opponentClanName=values.pop('opponentClanName', ''),
                 buildSeconds=int(values.pop('buildSeconds', 0)), values=json.dumps(values) if values else '{}')
        b = self.ast(aid)
        g = self.log_of(b.get('clan') if b.get('owner') != 'rival' else None)
        with self.lock:
            g.insert(0, e)
            del g[200:]
            self.mark()
        if self.host is not None:
            KL.save()

    def clan_info(self):
        st = self.st
        k = self.clan()
        ist = self.stats({'clan': k['id']} if k else {}) if self.host is not None else st['stats']
        rows = []
        for aid_s, a in sorted(self.asteroids.items(), key=lambda kv: int(kv[0])):
            if a.get('state') not in ('built', 'building') or not self.mine(a):
                continue
            aid = int(aid_s)
            df = a.get('deflector') or {}
            has_def = any(int(s) == DEFLECTOR for s in a['slots'])
            rows.append(mod('BattleStationOverviewInfoCommand', stationName=ASTEROIDS[aid]['name'], xpBonus=float(self.booster_pct(aid, 'ep')),
                            timerCounter=max(0, int(a.get('build_end', 0) - time.time())) if a['state'] == 'building' else 0,
                            deflectorDownTime=max(0, int(df.get('closed_until', 0) - time.time())),
                            damageBonus=float(self.booster_pct(aid, 'damage')), defStatus=bool(df.get('on')),
                            hasDeflectorModul=has_def, deflectorIsActive=bool(df.get('on')), deflectorTime=int(df.get('sn', 0)),
                            allModuleCount=len(a['slots']), mapName=H.name(ASTEROIDS[aid]['map']), buildCompleted=a['state'] == 'built',
                            maxAmountOfModule=SLOTS, honourBonus=float(self.booster_pct(aid, 'honor')), stationId=aid))
        longest = max(ist.get('longest_sec', 0), max([int(time.time() - a.get('founded', time.time())) for a in self.asteroids.values()
                                                     if a.get('state') == 'built' and self.mine(a)] or [0]))
        return ('ClanBattleStationInfoCommand', dict(battleStationOverviewInfoCommands=rows,
                                                     stationOwnedLongestTime=str(int(longest)),     # saniye (istemci biçimler)
                                                     maxStationAtOnce=int(ist.get('max_count', 0)), destroyedStations=int(ist.get('demolished', 0)),
                                                     stations=len(rows), allStations=int(ist.get('all', 0))))

    USER_KINDS = ('BUILD_START', 'DEFLECTOR_ON', 'EMERGENCY_REPAIR', 'MODULE_REPLACED', 'MODULE_REMOVED')

    def history_row(self, e):
        """Günlük satırı istemciye: values'ın her alanı metin (istemci GetLogMessage string'e çevirir: sayı InvalidCastException ile
        listeyi keser - canlı test), seviye 1'den; oyuncunun yaptığı işlerde ad (metinde %USERNAME%)."""
        e = dict(e)
        try:
            v = json.loads(e.get('values') or '{}')
        except ValueError:
            v = {}
        e['values'] = json.dumps({k: str(int(x) + 1) if k.endswith('Level') and isinstance(x, (int, float)) else str(x)
                                  for k, x in v.items()})
        if e['type'] in self.USER_KINDS and not e.get('userName'):
            e['userName'] = self.p.d['pilot'].get('userName', '')
        return mod('BattleStationHistoryInfoCommand', **e)

    def history(self, start):
        g = self.log_of()
        rows = [self.history_row(e) for e in g[start:start + 20]]
        return ('BattleStationHistoryListCommand', {'commandList': rows, 'startIndex': start, 'total': len(g)})

    # ------------------------------------------------------------ GM konsolu
    def gm(self, rows, d):
        """battleStation: buildTime (kurmayı / kurulumları bitir), modules (bir modül seti), accept (yanındaki asteroidi kur),
        deflector (aç/kapa), raid (baskın), rival (rakip istasyonu kur)."""
        what = str(d.get('option') or d.get('name') or (rows[0] if rows else '')).strip().lower()
        msgs = []
        if 'module' in what:
            for loot in MODS:
                n = 8 if MODS[loot]['max_count'] > 1 else 1
                self.p.add_resource(loot, n)
            self.st
            msgs.append(KAPI.screen('GM: modül seti envantere'))
        aid = self.near
        if aid and ('build' in what or 'accept' in what):
            a = self.ast(aid)
            for y in a['slots'].values():
                y['install_end'] = 0
            if a['state'] == 'building' or 'accept' in what:
                a['build_end'] = 0
                if a['state'] == 'vacant':
                    a.update(state='building', build_sec=60)
            msgs.append(KAPI.screen('GM: kurulum bitti'))
        if aid and 'deflector' in what:
            df = self.ast(aid)['deflector']
            df['on'] = not df.get('on')
            df['closed_until'] = 0 if df['on'] else time.time() + 3600
            df['sn'] = max(df.get('sn', 0), 3600) if df['on'] else df.get('sn', 0)
            df['last'] = time.time()
            self.bump(self.ast(aid))
            self.mark()
            msgs += self.near_status(aid, df['last'])
        if aid and 'raid' in what:
            msgs += self.spawn_raid(aid)
        if aid and 'rival' in what:
            a = self.ast(aid)
            if a['state'] in ('built', 'building') and a.get('owner') != 'rival':
                msgs.append(KAPI.screen('GM: burada kendi istasyonun var'))
            else:
                a.update(rival=D['rival']['clans'][0], rival_progress=1.0, rival_company=1 if self.faction() != 1 else 2)
                msgs += self.rival_build(aid, a, time.time())
        self.p.dirty = True
        return msgs or [KAPI.screen('GM battleStation: modules | build | accept | deflector | raid | rival')]


# ------------------------------------------------------------ bot klanlarının yarışı (bot/klan_us.py)
def race_leader(a):
    """Boş asteroitte yarışan bot klanlarından önde gideni: (klanın adı, ilerleme 0-1) ya da None."""
    en = None
    for cid, r in (a.get('race') or {}).items():
        k = KL.CLANS.get(int(cid))
        p = len(r.get('modules') or ()) / float(SLOTS)
        if k is not None and p > 0 and (en is None or p > en[1]):
            en = (k['name'], p)
    return en


def refund_race(cid, modules):
    """Yarışı kaybeden (ya da bırakan) bot klanının asteroitteki modülleri klanın stoğuna (k['ksi']['stok'])."""
    k = KL.CLANS.get(int(cid))
    if k is None or not modules:
        return
    with KL.LOCK:
        k.setdefault('ksi', {}).setdefault('stock', []).extend(modules)


def bot_build(aid, k, modules, minutes, log=print):
    """Yarışı bitiren bot klanı istasyonu kurmaya başlar: modüller yuvalara (sahibi klan: '@klan:<kimlik>'; yıkılınca bekleyen
    olarak döner, klan_us stoğa alır), asteroide modül takmış oyuncunun modülleri sahibine, öteki bot klanlarınınkiler stoklarına.
    -> başladı mı."""
    h = shared()
    if h is None:
        return False
    c = Cbs(h, None, log)
    a = c.ast(aid)
    if a['state'] != 'vacant':
        return False
    now = time.time()
    old = list(a['slots'].values())
    with h.lock:
        d = h.d['cbs']
        slot_info, satellite = {}, iter(range(DEFLECTOR + 1, SLOTS))
        for m in modules:
            md = MODS[m['loot']]
            s = (HULL if md['type'] == 2 else DEFLECTOR) if md['center'] else next(satellite, None)
            if s is None or str(s) in slot_info:
                continue
            d['shared_seq'] = int(d.get('shared_seq', 0)) + 1
            slot_info[str(s)] = {'iid': SHARED_ITEM + d['shared_seq'], 'module': m, 'owner': '@klan:%d' % k['id'], 'owner_name': k['tag'],
                          'install_end': now, 'install_sec': 0, 'installed': True}
        others = {cid: r.get('modules') or [] for cid, r in (a.get('race') or {}).items() if int(cid) != k['id']}
        a.update(state='building', build_end=now + minutes * 60, build_sec=minutes * 60, owner='bot', clan=k['id'], slots=slot_info)
        for f in ('race', 'rival', 'rival_progress'):
            a.pop(f, None)
        d['bot_clans'] = True
        c.bump(a)
        h.dirty = True
    for y in old:
        c.give_back(y)
    for cid, mods in others.items():
        refund_race(cid, mods)
    c.note(aid, 'BUILD_START', buildSeconds=minutes * 60)
    log('   CBS: [%s] %s istasyonunu kuruyor (%d dk)' % (k['tag'], ASTEROIDS[aid]['name'], minutes))
    return True


def bot_demolish(aid, reason='clan disbanded', log=print):
    """Dağılan bot klanının istasyonu yıkılır (oyuncunun klanı dağılınca klan.Klan.delete'in yaptığı gibi)."""
    h = shared()
    if h is not None:
        Cbs(h, None, log).destroy(aid, reason)
