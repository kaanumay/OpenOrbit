"""Yerel oyun sunucusu (TCP 8081): DarkOrbit Unity istemcisinin libcom protokolü.

Kullanım: python -I game.py <log_klasörü> [--near-npc] [--no-popups] [--invulnerable] [--control] [--profile=<yol>] [--settings=<yol>]
                                         [--stop-file=<dosya>]
  Normalde yönetim paneli başlatır (server/panel/): kayıt yuvasının profili, oyun ayarları ve durdurma dosyası onun verdiği.
  --settings=<yol>: oyun ayarları (settings.py; varsayılan save/ayarlar.json): çarpanlar, etkinlik seçimi, müzayede rakipleri,
  reklamsız/dokunulmaz/yakın NPC (seçeneklerin panel karşılıkları). Dosya değişince oyun açıkken yeniden okunur.
  --stop-file=<dosya>: dosya belirince profil kaydedilir ve sunucu kapanır (panelin "Sunucuyu durdur"u).
  --no-popups: girişte kendiliğinden açılan tanıtım pencereleri (günlük bonus, ipuçları, Season Pass) de gönderilmez.
  Gerçek parayla alışveriş pencereleri (Helix Blitz kampanyası, paket teklifi) ve Command Center'ın kendiliğinden açılması
  her zaman kapalıdır; Command Center menüden açılabilir.
  --near-npc: test kolaylığı, ilk 4 NPC türünden birer tane oyuncunun hemen yakınında doğar.
  --invulnerable: test kolaylığı, uzaylıların atışları görünür ama gemi can ve kalkan kaybetmez (ör. kapıları ölmeden denemek).
  --control: canlı test kontrol kanalı (control.py, 127.0.0.1:8099): mesaj izi, istek enjeksiyonu, komut gönderme, durum.
  --profile=<yol>: etkin kayıt yuvası (paths.py) yerine başka bir profil (panel yuvanınkini verir; canlı testler kopyayla çalışır).
Çerçeve: istemci -> sunucu ilk paket 4 bayt, sonrakiler 3 bayt BE uzunluk; sunucu -> istemci 3 bayt BE uzunluk.
Mesajlar protocol.py ile kodlanır/çözülür (tablo: istemcinin kendi read() kodu, server/data/protocol_read.json).

Giriş akışı (gerçek sunucunun kaydından, bkz. belgeler/istemci/kayit_analizi.md):
  LoginRequest  -> data/giris.json "giris" demeti
  ReadyRequest  -> "hazir" demeti (ilk ReadyRequest'te)
  Demetlerdeki "@…" işaretleri profilden (save/profil.json) ya da harita verisinden (data/haritalar.json) üretilir.
  Salt okunur istekler kayıttaki yanıtlarla karşılanır (data/yanitlar.json); ayar/pencere/hareket istekleri profile yazılır.
  Harita yüklenince dünya simülasyonu başlar (world.py): NPC'ler, savaş, ödüller, kutular.
  Mağaza ve hangar istekleri (satın alma, ekipman takıp çıkarma) shop.py'de, profil üzerinde işlenir.
  P.E.T. (pet.py): PetRequest, PetGearActivationRequest; uzaydaki davranışı dünya döngüsünde, harita değişince yeniden çıkar.
  Galaksi Kapıları (galaxy_gates.py): GalaxyGateBuilder* istekleri; X-1'deki kapı portalları ve kapı haritasındaki dalgalar dünyaya bağlanır.
Şablon dosyaları kayit/extract_templates.py ile üretilir; yoksa yalnızca profilden en küçük giriş (gemi + LoginResponse) gönderilir.
"""
import contextlib, os, re, sys, socket, threading, time, json, math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import protocol as P       # noqa: E402
import paths as PTH       # noqa: E402
import game_data as GD         # noqa: E402
from player_profile import Profile  # noqa: E402
from world import World    # noqa: E402
from shop import Shop  # noqa: E402
import shop as SHP  # noqa: E402
from quest import Quests  # noqa: E402
import world               # noqa: E402
import galaxy_gates as KAPI        # noqa: E402
import event_gate as EKP  # noqa: E402
import labyrinth as LAB      # noqa: E402
import pve_modes as PVM   # noqa: E402
import low as LOW          # noqa: E402
import assembly as ASM     # noqa: E402
import dispatch as DSP     # noqa: E402
import skylab as SKY       # noqa: E402
import bank as BANK       # noqa: E402
import loot as LOOT       # noqa: E402
import ship_module as GM    # noqa: E402
import event_calendar as CAL        # noqa: E402
import traceback           # noqa: E402
import season as SZN        # noqa: E402
import battle_pass as BPS  # noqa: E402
import daily_rewards as DRW  # noqa: E402
import achievement as ACV      # noqa: E402
from login_calendar import DailyLogin  # noqa: E402
from skill_tree import Abilities  # noqa: E402
from achievement import Achievements  # noqa: E402
import map_links as H
import combat_items as CIT    # noqa: E402
import ranks as RT         # noqa: E402
import new_systems as NS  # noqa: E402
import chat as CHT        # noqa: E402
import social as SO        # noqa: E402
import control as CTL       # noqa: E402
import settings as SET          # noqa: E402
import rankings as RK      # noqa: E402
import gm_console as GMC    # noqa: E402
import tips as IP         # noqa: E402
import payment as PAY         # noqa: E402
import panel_channel as PCH   # noqa: E402
import event_maps as EVM  # noqa: E402
import live_status as CD   # noqa: E402
import extra_events as EXE  # noqa: E402
import cbs as CBS
import stores as STO
import player_profile as PF
import inventory as INV
import multiplayer as CO
import community as TP
import clan as KL
import group as GR
import contacts as CT
import bot.manager as BOT  # noqa: E402  (bot oyuncular: belgeler/BOTLAR.md)
from legacy_protocol import legacy, parse as legacy_parse  # noqa: E402         # noqa: E402

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
LOG_DIR = ARGS[0] if ARGS else '.'
DATA = os.path.join(HERE, 'data')
lock = threading.Lock()


def log(text):
    with lock:
        with open(os.path.join(LOG_DIR, 'gs.log'), 'a', encoding='utf8') as fh:
            fh.write(time.strftime('%H:%M:%S ') + text + '\n')


def encode(msgs):
    """Mesajları çerçeveler; kodlanamayan mesaj (255'i aşan liste, bilinmeyen alan …) adıyla günlüğe yazılıp atlanır, ötekiler gider."""
    out = []
    for n, f in msgs:
        try:
            out.append(P.frame(P.encode_message(n, f)))
        except Exception as e:
            log('   kodlanamadı, gönderilmedi: %s: %r' % (n, e))
    return b''.join(out)


def save_profile(profile=None):
    """Profil kaydı (verilmezse sunucunun kendi profili); hata (dosya kilitli, disk) günlüğe yazılır, oturumu ve harita değişimini
    düşürmez; bir sonraki kayıtta yeniden denenir."""
    try:
        (profile or PROFILE).save()
    except Exception as e:
        log('   profil kaydedilemedi: %r' % e)


def _load(name, default):
    p = PTH.template(name) if name in PTH.TEMPLATES else os.path.join(DATA, name)     # şablon: kendi kaydın, yoksa paylaşılabilir kopya
    return json.load(open(p, encoding='utf8')) if p and os.path.exists(p) else default


class Templates:
    """Kayıttan çıkarılmış giriş demetleri, harita dünyası ve istek yanıtları (kendi kaydın yoksa data/defaults/'daki paylaşılabilir
    kopya; yollar.sablon)."""

    def __init__(self):
        self.entry = _load('login.json', {})
        self.maps = _load('maps.json', {})
        for w in self.maps.values():
            w['hazir'] = [m for m in w.get('hazir', []) if not (m['_m'] == 'JumpgateCreateCommand' and m['designId'] in SERVER_GATE_DESIGNS)]
        # yalnız kullanılanlar (E10): ötekilerin hepsini kod karşılıyor; kayıttaki hesabın verisi (başka oyuncuların adları, klan
        # listeleri) bir isteğin yedeğinden pencereye çıkmasın. Dosyada kalırlar: araçların kaynağı (rutbe, pve_modlari, sira_odulleri)
        self.replies = {k: v for k, v in _load('responses.json', {}).items() if k in USED_RESPONSES}
        self.produced = {}

    def map_world(self, map_id):
        """Haritanın dünya mesajları {'giris', 'hazir'}: kayıttaysa kayıttan; değilse üretilir (istasyonlu haritalarda kayıttaki
        2-1 istasyonu taşınır, harita.map_world) ve portallar istemcinin spacemap-config.xml'inden."""
        rec = self.maps.get(str(map_id))
        if rec is not None:
            return rec
        if str(map_id) not in self.produced:
            self.produced[str(map_id)] = H.map_world(map_id, self.maps.get('5'))
        return self.produced[str(map_id)]

    def station(self, map_id):
        """Haritanın istasyonu (tamir, doğma, hangar): süs istasyonları (5-2'nin korsan istasyonu) sayılmaz."""
        for m in self.map_world(map_id).get('hazir', []):
            if m['_m'] == 'SpaceStationCommand' and m.get('type') not in H.DECOR_STATION_TYPES:
                return m
        return None

    def batch(self, kind, profile):
        """'giris' ya da 'hazir' demetini [(ad, alanlar)] olarak üretir."""
        if not self.entry:
            if kind == 'giris':
                return [profile.generate('@gemi'), profile.generate('@giris_yaniti')]
            return []
        map_id = profile.d['position']['mapId']
        out, windows = [], set()
        for m in self.entry.get(kind, []):
            mk = m['_m']
            if mk in DEAD_TEMPLATE or m.get('message') in DEAD_LEGACY:
                continue
            if mk == 'WindowItemCommand':
                # kayıtta Contacts ve Ship Warp girişte üçer kez, her hazır demetinde yine üçer kez (kayıttaki yerle, maximized false:
                # açık pencere kapanır): girişte bir kez, profildeki yer ve görünürlükle (profil.patch_template)
                if kind == 'hazir' or m.get('itemId') in windows:
                    continue
                windows.add(m.get('itemId'))
            if mk in ('@harita_giris', '@harita_hazir'):
                lv = profile.d['pilot'].get('level', 1)
                out += [(n, f) for n, f in self.world_msgs(map_id, 'giris' if mk == '@harita_giris' else 'hazir')
                        if not (n == 'JumpgateCreateCommand' and f['gateId'] == H.TUTORIAL_GATE and lv >= H.TUTORIAL_MAX_LEVEL)]
            elif kind == 'hazir' and (mk == 'EquipReadyCommand' or m.get('message', '').startswith('0|n|MSG|3|2|msg_equip_')):
                continue               # kayıtta her yerde true; dünya istasyon bölgesine girip çıktıkça gönderir (dunya.check_gates)
            elif mk.startswith('@'):
                st = self.station(map_id)               # düşman üssü güvenli bölge değil (dunya.home_station)
                g = profile.generate(mk, st if st and st.get('type') == profile.d['pilot'].get('factionId') else None)
                if g:
                    out.append(g)
            else:
                out.append((mk, profile.patch_template(mk, m)))
                if mk == 'EventActivationStateCommand':      # süren etkinliklerin harita süsleri (takvim.mood_cmds)
                    out += CAL.mood_cmds(CAL.active())
        return out

    def world_msgs(self, map_id, kind):
        """Harita dünyası: kayıtta gezilen haritalar için kayıttaki mesajlar, diğerleri için istemcinin portal verisinden."""
        return [(w['_m'], {k: v for k, v in w.items() if k != '_m'}) for w in self.map_world(map_id).get(kind, [])]

    def asset_removes(self, map_id):
        """Harita değişiminde eski haritanın istasyon/taret nesnelerini kaldır (kayıttaki AssetRemoveCommand gibi)."""
        return [('AssetRemoveCommand', {'assetType': w['type'], 'uid': w['assetId']}) for w in
                self.map_world(map_id).get('giris', []) if w['_m'] == 'AssetCreateCommand']

    def response(self, name, fields):
        """Salt okunur isteğe kayıttaki yanıtı bulur: tam eşleşme, yoksa yalnız sayfalama/haber alanları farklı olan kayıt.
        Tür, modül, sıralama gibi alanlar farklıysa yanıt yok (eskiden başka türün listesi gidiyordu: Hall of Fame, Skylab modülü)."""
        entries = self.replies.get(name)
        if not entries:
            return None
        def diff(e):
            return {k for k, v in fields.items() if k != '_' and e['request'].get(k) != v}
        best = min(entries, key=lambda e: len(diff(e)))
        if diff(best) - LOOSE_FIELDS:
            return None
        return [(m['_m'], m) for m in best['response']]


LOOSE_FIELDS = {'startIndex', 'page', 'start', 'newsInfo'}       # yanıtın türünü değiştirmeyen istek alanları
# kayıtlı yanıtlardan sunucunun kullandıkları: yanıt olarak (Command Center, pilot kartı) ve veri şablonu olarak (mağaza, hangar, kapı)
USED_RESPONSES = {'CommandCenterGetDontShowRequest', 'CommandCenterNewsInfoRequest', 'InternalPilotBioRequest', 'ShopItemListRequest',
                  'HangarShipEquipmentRequest', 'HangarListRequest', 'HangarShipDetailRequest', 'GalaxyGateBuilderInfoRequest'}
# giriş şablonunun ölü yükü (E10): R-Zone durumu (171 kez; işleyicisi ölü), CTB (istemcide işleyicisi yok), 0|TR ve 0|8
# (istemcinin OnData'sında dalı yok). POIReadyCommand ölü değil: istemci bölgelerin görünümünü ancak onunla çizer
# (PoiReadyCommandHandler -> PoiZoneManager.AssemblePoiReady -> UpdateDesign/UpdateDesign2D); gelmeyince 5-X ve X-BL engelleri
# asteroit/enkaz yerine düz gri tarama görünüyordu (kullanıcı bildirimi 2026-10-25). Kayıttaki gibi haritanın hazır demetinden sonra.
DEAD_TEMPLATE = {'RzoneStatusCommand', 'CTBMatchStateCommand'}
DEAD_LEGACY = {'0|TR', '0|8'}
# kayıttaki mod portalları (2-1: Deep Space Echoes 300, Trinity Trials 304): sunucunun kendi portalları (echoes.py, arena.py) aynı yerde
# ikinci kez gidiyordu (referans karşılaştırması 2026-10-25)
SERVER_GATE_DESIGNS = {300, 304}
# gerçek sunucunun da yanıt vermediği istekler (kayıt): günlüğe "yanıtsız" diye düşmesin
SILENT = {'TrackVariableRequest',
          'CommandCenterNewsClickedRequest', 'PerformanceTrackingSendInfoRequest',
          'ProActionBarOpenStateChangeRequest', 'QuestGiverWindowClosedRequest', 'CommandCenterUpdateDontShowRequest',
          'EggTriggerRequest'}
# günlüğe hiç yazılmayan istekler. EggTriggerRequest: istemcinin "harita dışına 6100 birim çıkıldı" sürprizi
# (ChangePositionSyncGameObjectPos.Run); 2D'de geminin y'si ters eksende tutulduğu için gemi haritanın alt yarısındayken
# saniyede bir gelir (kullanıcının 2D oturumunda 10 dakikada 103 kez; H82). Yanıtı yok; gizli başarımları ilerletir (E6).
UNLOGGED = ('MoveRequest', 'KeepAlive', 'AttackRocketRequest', 'EggTriggerRequest')
EGG_TYPES = ('MINIMAP_PING', 'GOING_ROUND_THE_MAP', 'GALAXY_GATE_FIREWORK', 'RAINBOW_LASER')     # istemcinin EggTriggerType'ı
CHAT = None                # yerel sohbet sunucusu (sohbet.py; main başlatır, port 7771)
SESSIONS = set()            # oyuncusu belli olan oturumlar (arkadaş sunucusunda birden çok; cok_oyunculu.py)
CONTROL = '--control' in sys.argv        # canlı test kontrol kanalı (kontrol.py): mesaj izi ve enjeksiyon
CURRENT = None               # son bağlanan istemcinin oturumu (kontrol kanalı bunu yönetir)
TP.GAME = sys.modules[__name__]          # sunucudaki oyuncular (grup, rehber, fısıltı, posta): PROFIL, CURRENT
PROFILE_PATH = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--profile=')), None)
STOP = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--stop-file=')), None)    # panel: belirince kaydet ve çık
# kayıt (Premium'suz hesap): çıkış düğmesinden 19,2 sn sonra 0|l, bağlantı kapanır; Premium'da istemci "Log out ... in just five seconds"
LOGOUT_SEC = 5.0 if Profile.premium else 19.2

TEMPLATE = Templates()
PROFILE = Profile(TEMPLATE.entry.get('seed'), **({'path': PROFILE_PATH} if PROFILE_PATH else {}))
H.PLAYER_FACTION = PROFILE.d['pilot'].get('factionId')     # 5-X'te yalnız kendi firmasının portalları
KAPI.register_npcs(world.CFG['types'])     # kapı uzaylıları NPC türleri olarak
EKP.register_npcs(world.CFG['types'])      # etkinlik kapılarınınkiler (etkinlik_kapi.py)
world.CFG['types'].update(PVM.AR.D['kinds'])  # Aşama 8'in modlarının uzaylıları (data/pve_modlari.json)


# Season Pass, Battle Pass ve günlük ödül pencerelerinin kayıttaki giriş mesajları -> profilden üretilenler
PASS_LOGIN = dict({n: 'season' for n in ('SeasonPassStatusCommand', 'SeasonPassMissionInfoCommand', 'SeasonPointsInfoCommand',
                                        'SeasonPassRewardInfoCommand')},
                  **{n: 'ticket' for n in ('BattlePassInfoCommand', 'BattlePassKeyExchangeInfoCommand', 'BattlePassWindowSettingsModule')},
                  **{n: 'reward' for n in ('MonthlyDeluxeInfoCommand', 'MiniClientRewardInfoCommand', 'EventUnityClientRewardQuestCommand')})
DRW_REQUESTS = ('MiniClientRewardClaimRequest', 'MonthlyDeluxeClaimRequest', 'ClaimUnityClientRewardRequest')
# --reklamsiz: girişte kendiliğinden açılan kampanya/tanıtım pencerelerini gönderme
POPUP_MSGS = {'DisplayOfferCommand', 'HintWindowAddComand', 'HintWindowListInitCommand', 'DailyLoginRewardDayCommand',
              'MonthlyDeluxeInfoCommand', 'CommandCenterDontShowInfoCommand', 'SeasonPassStatusCommand',
              'SeasonPassMissionInfoCommand', 'SeasonPassRewardInfoCommand'}
# verisi pencereyi açmayan, girişte düzenden (maximized) açılan pencereler: Mini Client ödülü (MiniClientRewardInfoCommandHandler
# yalnız veriyi yazar). Veri süzülünce pencere boş açılıyordu (H155): veri hep gider, pencere kapalı gider
POPUP_WINDOWS = {'miniclient_reward'}
NO_POPUPS = '--no-popups' in sys.argv
# her zaman: gerçek parayla alışveriş pencereleri (tek oyunculuda işe yaramaz)
#   EventPaymentActorCommand: "%400 Helix Blitz" uridyum kampanyası; DisplayOfferCommand: paket teklifi penceresi
PAYMENT_POPUPS = {'EventPaymentActorCommand', 'DisplayOfferCommand'}


def no_popups(msgs):
    """Girişte kendiliğinden açılan pencereleri ayıklar. Command Center: istemci CommandCenterDontShowInfoCommand.inspected
    false gelirse pencereyi açar (CommandCenterDontShowInfoCommandHandler); hep true gönderilir, menüden açılabilir kalır."""
    popups = NO_POPUPS or SET.get('no_ads')                                                  # seçenek ya da panelin ayarı
    drop = PAYMENT_POPUPS | (POPUP_MSGS if popups else set())
    out = []
    for n, f in msgs:
        if n in drop and n != 'CommandCenterDontShowInfoCommand':
            continue
        if n == 'UILayoutCommand' and popups:
            for bar in f.get('featureBars', []):
                for it in bar.get('featureBarItems', []):
                    if it.get('itemId') in POPUP_WINDOWS:
                        it['maximized'] = False
        if n == 'CommandCenterDontShowInfoCommand':
            f = dict(f, inspected=True)
        out.append((n, f))
    return out


def login_batch(kind, first=True, profile=None):
    """first=False: harita değişimi (portal, istasyonda tamir). Girişte kendiliğinden açılan pencereler (günlük bonus, ipuçları,
    Season Pass) yalnız girişte gelir; arayüz harita değişiminde kalır, veriyi yeniden göndermek pencereleri yeniden açıyordu.
    profil: oturumun oyuncusu (arkadaş sunucusunda misafirinki; verilmezse sunucunun kendi profili)."""
    msgs = no_popups(TEMPLATE.batch(kind, profile or PROFILE))
    if not first:                    # pencere öğeleri de yalnız girişte: harita değişiminde açık pencereyi kapatıyordu (E10)
        msgs = [(n, f) for n, f in msgs if (n not in POPUP_MSGS or n == 'CommandCenterDontShowInfoCommand') and n != 'WindowItemCommand']
    return msgs


HOME_MAP = {1: 1, 2: 5, 3: 9}     # firma -> ana harita (X-1)
# arkadaş sunucusunda oyuncuların ortak dünyası olan haritalar (ortak_harita.py): firma, savaş ve Blacklight haritaları (1-1 … 5-4,
# BL-1..3); kapı, mod, etkinlik, labirent ve LoW haritaları her oyuncunun kendi kopyası
SHARED = {k for k in world.CFG['haritalar'] if k.isdigit() and re.match(r'(\d|BL)-\d$', H.name(k)) and int(k) not in KAPI.BY_MAP
              and int(k) not in EKP.BY_MAP and int(k) not in LAB.MAPS and int(k) != LOW.MAP}
NAME_MIN, NAME_MAX, STATUS_MAX = 4, 20, 200    # pilot adı 4-20 (istemci change_pilotname_error_signs_number); durum yazısı uyarlama
NAME_ILLEGAL = set(' <>@+\'"&%;/\\?|')          # istemci change_pilotname_error_signs_illegal (+ protokolün ayırıcısı |)
NAME_WAIT_SEC = 48 * 3600                         # istemci change_pilotname_error_time: "once every 48 hours"


def achievement_groups(now=None):
    """Başarımların etkin grupları: takvimin etkinlikleri ve bu sezonun Season Pass grubu (SEASONPASS_Qn; season.py)."""
    sp = SZN.achievement_group(now)
    return CAL.achievement_groups(now) | ({sp} if sp else set())

WORLD_REQUESTS = {'ShipSelectRequest': 'select', 'AttackLaserRequest': 'laser_start', 'AttackRocketRequest': 'rocket',
                  'CollectBoxRequest': 'collect', 'MenuActionRequest': 'menu_action', 'HarvestRequest': 'harvest',
                  'TradeSellOreRequest': 'sell_ore', 'InstantRepairRequest': 'instant_repair'}


class Session:
    """Bir istemci bağlantısı: giriş akışı, dünya, harita değişimi. Dünya döngüsü de buraya yazdığı için gönderme kilitli.
    Oturumun oyuncusu self.profil: sunucunun kendi kaydı (PROFIL) ya da arkadaş sunucusunda misafirin gönderdiği kayıt
    (multiplayer.py). bekle=True: oyuncu girişte (LoginRequest'in sessionID'si) belli olur, sistemler o zaman kurulur (bind)."""

    def __init__(self, c, addr, profile=None, wait=False, queue=False):
        self.c, self.addr = c, addr
        self.send_lock = threading.Lock()
        self.packet_lock = threading.Lock()      # istemcinin paketleri ve kontrol kanalının enjekte ettikleri sırayla işlenir
        self.play_start = time.time()            # oynama süresi (play_time)
        self.state_lock = threading.RLock()
        self.map_pending = False     # ShipInitializationCommand gönderildi; harita yüklenince (ReadyRequest) hazır demeti + dünya
        self.ready_n = 0             # karşılanan ReadyRequest sayısı (1: ilk giriş; sonrakiler harita yüklenişleri)
        self.world = None
        self.secrets = set()         # LoginRequest'teki oturum anahtarı: eski metin protokolü de taşır ("S|CFG|2|<kullanıcı>|<anahtar>")
        self.profile = None
        self.guest = None          # arkadaş sunucusunda misafirin kaydı (cok_oyunculu.Misafir); sunucunun kendi oyuncusunda None
        self.local = None            # çoklu istemcinin ek oyuncusu (cok_oyunculu.Yerel)
        self.client_pid = None      # bağlanan istemcinin süreci (ödeme düğmesi hangi oturumun: odeme.baglanan_pid)
        self.queue = CO.SendQueue(c) if queue else None     # arkadaş sunucusunda gönderme kuyruğu: yavaş ağ dünya kilidini tutmasın
        if not wait:
            self.bind(profile or PROFILE)

    def bind(self, profile):
        """Oturumun sistemlerini oyuncunun profiliyle kurar."""
        global CURRENT
        self.profile = profile
        if profile is PROFILE:
            CURRENT = self           # kontrol kanalı, canlı durum ve ödeme düğmesi sunucunun kendi oyuncusunun oturumunu izler
        SESSIONS.add(self)
        self.shop = Shop(self.profile, TEMPLATE.replies, log)
        self.quest = Quests(self.profile, log)
        self.quest.grant = self.quest_reward
        self.quest.send = lambda m: self.send(m, 'görev süresi')
        self.quest.state = lambda: self.world.quest_state() if self.world else {}      # MISCELLANEOUS alt koşulları (gizli, radyasyon, az can)
        self.shop.quest = self.quest.event                        # toplama görevleri: rafineride üretilen cevher
        self.daily = DailyLogin(self.profile, self.shop, log)      # günlük giriş takvimi
        self.profile.daily_fields = self.daily.fields
        self.pet = self.shop.pet
        self.pet.send_raw = lambda m: self.send(m, quiet=True)
        self.gates = KAPI.Gates(self.profile, log)
        self.gates.m = self.shop
        self.shop.gates = self.gates      # ödüllerdeki ücretsiz kapı enerjisi
        self.event_gates = EKP.EventGates(self.profile, log)                    # etkinlik kapıları (Gauntlet of Plutus, Vortex …)
        self.event_gates.m = self.shop
        self.pve = PVM.PveModes(self.profile, self.shop, self.event_gates, log)    # Aşama 8: sonsuz ve rogue-lite PvE modları
        self.pve.send = lambda m: self.send(m, 'mod')
        self.pve.change_map = self.change_map
        self.profile.mode_mods = lambda: self.pve.ebl.mods(self.profile.d['position']['mapId']) if self.pve.ebl else {}
        self.new_ = NS.NewSystems(self.profile, self.shop, log)     # Aşama 9: N.O.V.A., Armory Unlock, QFC/Hyperforge, otomatik pilot
        self.shop.new_ = self.new_
        self.shop.world = lambda: getattr(self, 'world', None)    # drone formation wait (magaza.formation_wait)
        self.profile.nova_mods = lambda: self.new_.mods(self.profile.d['position']['mapId'])
        self.profile.captain_energy = self.new_.nova.hud
        self.social = SO.Social(self.profile, self.shop, log, CHAT)   # Aşama 10: sohbet, posta, klan, müzayede, gemi ışınlama
        self.social.send = lambda m, note: self.send(m, note)
        self.social.reload = lambda: self.world and self.world.reload_ship()
        self.social_next = 0.0
        self.skill = Abilities(self.profile, self.shop, self.gates, log)    # pilot yetenek ağacı (log diskleri kapı sayacında)
        self.assembly = ASM.Assembly(self.profile, log)                            # Assembly (tarifler, üretim)
        self.assembly.m = self.shop
        self.assembly.send = lambda m: self.send(m, 'Assembly')
        self.dispatch = DSP.Dispatch(self.profile, self.gates, log)             # Dispatch (toplayıcı ve kapı gönderimi)
        self.dispatch.m = self.shop
        self.skylab = SKY.Skylab(self.profile, log)                                # Skylab (üretim, yükseltme, taşıma)
        self.skylab.m = self.shop
        self.skylab.send = lambda m: self.send(m, 'Skylab')
        self.skylab.quest = lambda **kw: self.quest.event('skylab', **kw)        # görev koşulu UPDATE_SKYLAB_TO_LEVEL (Ö1)
        self.modules = GM.Modules(self.profile, log)                             # kararsız modüller (Restabilize)
        self.modules.m = self.shop
        self.season = SZN.Season(self.profile, log)                                  # Season Pass (sezon.py)
        self.ticket = BPS.BattlePass(self.profile, log)                            # Battle Pass ve anahtar değişimi (savas_bileti.py)
        self.reward = DRW.DailyReward(self.profile, log)                              # Mini Client, Monthly Deluxe, Unity ödülü (gunluk_odul.py)
        for _o, _note in ((self.season, 'Season Pass'), (self.ticket, 'Battle Pass'), (self.reward, 'günlük ödül')):
            _o.m = self.shop
            _o.send = (lambda note: lambda m: self.send(m, note))(_note)
        self.shop.tickets = (self.season, self.ticket, self.reward)
        self.ticket.objective = lambda: self.season.event('objective')     # Season Pass 700023-700025 (etkinlikte 15 Battle Pass görevi)
        self.shop.quest = self.quest_event                        # toplama görevleri: rafineride üretilen cevher
        self.bank_sent = None         # istemcinin son gördüğü Uridium Bank birikimi
        self.cal_sent, self.cal_next = None, 0.0                            # takvim: son bildirilen etkin etkinlikler
        self.win_sent = {}                                                  # etkinlik pencerelerinin son bildirilen görünürlüğü
        ACV.set_events(achievement_groups())
        self.bank_next = 0.0
        self.achievement = Achievements(self.profile, log)                               # başarımlar ve unvanlar
        self.achievement.send = lambda m: self.send(m, 'başarım')
        self.profile.ach = self.ach_event
        self.gates.world = lambda: self.world
        self.gates.info_tpl = next((m for e in TEMPLATE.replies.get('GalaxyGateBuilderInfoRequest', []) for m in e['response']
                                      if m['_m'] == 'GalaxyGateBuilderInfoCommand'), None)
        self.logout_timer = None      # çıkış geri sayımı (UIButtonTriggerRequest logout)
        self.gm = GMC.Console(self, log)   # GM konsolu (panelde açıksa)
        self.hint = IP.Hints(self.profile, log)   # yeni başlayan ipuçları (bir kez; panelin 'ipuclari' ayarı)
        self.windows = PAY.Windows()      # son açılan pencereler: ödeme düğmesinin ürünü (odeme.py)
        self.extra = EXE.ExtraEvents(self.profile, self.shop, self.event_gates, log)   # Ö3'ün etkinlikleri (Chromin Rush …)
        if self.extra.fiesta:
            self.extra.fiesta.change_map = self.change_map
            self.extra.fiesta.titles = self.extra.title.grant_title           # Epoch Lit (Tranquil)
            self.pve.extra_windows['fiesta'] = self.extra.fiesta.portal_window
        self.cbs = CBS.Cbs(self.profile, self.shop, log)                     # Clan Battle Station (Ö5)
        self.extra.add(self.cbs)
        self.social.clan.cbs = self.cbs
        self.profile.cbs_mods = self.cbs.mods
        self.shop.cbs = self.cbs                 # Assembly: boştaki modüller envanterde, yükseltilebilir (magaza.module_items)
        self.store = STO.Stores(self.profile, self.shop, log)              # Ö7: uridyumla çalışan dükkân pencereleri
        self.extra.add(self.store)
        self.profile.window_hooks['returnee_login'] = self.store.returnee_active
        self.extra.rbp.hero = lambda: bool(self.store.rh().get('connected'))           # Recall Battle Pass: Return of Hero'daki durum
        self.profile.window_hooks['diminish_quests'] = self.extra.urgent.menu_visible   # Urgent Missions: yalnız görev varken (acil_gorevler.py)
        for kind, s in (('vortex', self.extra.vortex), ('world_boss', self.extra.boss), ('mimesis', self.extra.mimesis),   # Ö4
                        ('apotheosis', self.extra.apo)):                                                       # 1.1.115
            s.change_map = self.change_map
            self.pve.extra_windows[kind] = s.portal_window
        self.extra.send = lambda m: self.send(m, 'etkinlik')
        self.extra.title.base_title = lambda: self.achievement.title_msgs()
        self.gates.titles = self.extra.title.grant_title           # kapı tamamlama unvanı (wiki: All-Star, Boss Of Bosses, Emperor Of Hades Gate)
        self.pve.echoes.titles = self.extra.title.grant_title        # Deep Space Echoes dönem sonu sıralama unvanı (Cosmic Tyrant)
        self.extra_next = 0.0
        self.profile.hint = self.hint.show
        self.shop.rescue_depot()   # görünmez depoya düşmüş ödüller (dron tasarımı, P.E.T. protokolü, Season Pass rezervi) yerine

    # ------------------------------------------------------------ çıkış
    def logout_start(self):
        """Çıkış düğmesi: istemci kendi geri sayımını gösterir; kayıttaki gibi ~19 sn sonra 0|l ve bağlantı kapanır. Göndermezsek
        istemci süre bitince bağlantıyı koparıp yeniden giriş yapıyordu (günlük 13:11)."""
        self.logout_cancel()
        t = threading.Timer(LOGOUT_SEC, self.logout_done)
        t.daemon = True
        self.logout_timer = t
        t.start()
        log('   çıkış: %.1f sn sonra' % LOGOUT_SEC)

    def logout_cancel(self):
        if self.logout_timer:
            self.logout_timer.cancel()
            self.logout_timer = None
            log('   çıkış iptal')

    def logout_done(self):
        self.logout_timer = None
        save_profile(self.profile)
        try:
            self.send([legacy('0|l')], 'çıkış')
        except OSError:
            pass
        self.close()

    def close(self):
        """Bağlantıyı kapat (gönderilenler gittikten sonra): istemcinin okuması biter, oturum kapanır (run)."""
        try:
            if self.queue:
                self.queue.close()
            else:
                self.c.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def hand_over(self):
        """Aynı oyuncu yeniden bağlandı (arkadaş sunucusu): eski bağlantı hemen kesilir, dünyası beklemeden durur. Yalnız kapatınca
        yarı açık bağlantıda gönderim takılıp okuma bitmiyordu; eski dünya ortak haritada kalıyor, oyuncu orada iki kez oluyordu."""
        try:
            self.c.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if self.queue:
            self.queue.close()
        if self.world:
            self.world.stop()

    def ach_event(self, kind, **kw):
        """Oyun olayları: rütbe sayaçları (ranks.py), Pass görevleri, ana görevler (öldürme görev olayından gelir) ve başarımlar
        (achievement.py)."""
        RT.event(self.profile, kind, **kw)
        if kind != 'map' and not kw.get('dispatch'):     # harita ziyareti görev olayından gelir; Dispatch'in kapısı görev saymaz
            self.pass_event(kind, **kw)
            msgs = self.extra.event(kind, kw)        # Ö3'ün etkinlik görevleri (Galaxy Trek)
            if msgs:
                self.send(msgs, 'etkinlik görevi')
            msgs = self.quest.event(kind, **kw) if kind != 'kill' else []      # E6: tek ölçüm noktası (gorev_takip.measure)
            if msgs:
                self.send(msgs, 'görev')
        if kind == 'death':                       # "ölmeden" görevleri başarısız (gorev.py)
            failed = self.quest.broken('death')
            if failed:
                self.send(failed, 'görev başarısız')
        if kind == 'level':                       # seviye atlandı: yeni özelliğin davet ipucu (ipucu.py)
            hint = self.hint.level(kw.get('value', 1))
            if hint:
                self.send(hint, 'ipucu: seviye')
        return self.achievement.event(kind, **kw)

    def event_tips(self, now=None):
        """Süren harita etkinliklerinin açıklaması dönemde bir kez (tips.py; NormalTipsCommand mesaj kutusu)."""
        per = lambda k: (CAL.period(k, now) or (0,))[0]
        msgs = self.hint.event_tips(EVM.specs(now), per)
        if msgs:
            self.send(msgs, 'etkinlik bildirimi')

    def quest_event(self, kind, **kw):
        """Dünyanın görev olayları: görevler ve Pass görevleri (öldürme Pass'lere başarım olayından gider; grup üyesinin aynı
        haritada öldürdüğü uzaylı başarım değil, yalnız görev: Pass, etkinlik ve Urgent Missions görevleri de buradan)."""
        group = kind == 'kill' and kw.get('grup')
        if kind in ('cargo', 'loot', 'sell', 'bonus', 'map', 'ore_update') or group:     # ore_update: Season Pass USE_ORE_UPDATE görevleri
            self.pass_event(kind, **kw)
            msgs = self.extra.event(kind, kw) + (self.extra.urgent.kill(kw.get('npc')) if group else [])
            if msgs:
                self.send(msgs, 'etkinlik görevi')
        return self.quest.event(kind, **kw)

    def quest_state_events(self):
        """Durum koşulları (Ö1): görev kabul edilince şimdiki durum bir kez değerlendirilir (çubuktaki eşya, Skylab modüllerinin
        seviyeleri), yoksa koşul ancak bir sonraki değişiklikte ilerlerdi."""
        tpl = next((m for m in TEMPLATE.entry.get('hazir', []) if m['_m'] == 'MenuInitializationCommand'), None)
        msgs = self.quest.event('slot_bar', **self.profile.slot_bar_state(tpl['slotBars'] if tpl else []))
        for key, lv in self.skylab.levels().items():
            msgs += self.quest.event('skylab', modul=key, seviye=lv)
        if self.profile.d.get('klan'):
            msgs += self.quest.event('clan')                 # IN_CLAN: klanda olmak
        return msgs

    def pass_event(self, kind, **kw):
        """Season Pass, Battle Pass ve Unity ödülü görevleri (her biri iletisini kendisi gönderir)."""
        mid = self.profile.d['position'].get('mapId')
        for o in (self.season, self.ticket, self.reward):
            o.map_id = mid
            try:
                o.event(kind, **kw)
            except Exception:
                log('   Pass olayı hatası (%s %s):\n%s' % (kind, kw, traceback.format_exc()))

    def hint_msgs(self, n, f):
        """İpucu pencereleri: oyuncunun kapattıkları (HintWindowClosedRequest, profilde ipuclari_kapali) girişte yeniden açılmaz,
        ipucu arşivinin listesine eklenir (canlı deneme 2026-10-17: "New Employee Orientation" her girişte açılıyordu)."""
        closed = self.profile.d.get('hints_closed', [])
        if n == 'HintWindowAddComand':
            return [] if (f.get('window') or {}).get('content') in closed else [(n, f)]
        have = [w.get('content') for w in f.get('windows', [])]
        return [(n, dict(f, windows=list(f.get('windows', [])) + [{'_': 'HintWindowModule', 'content': c} for c in closed
                                                                  if c not in have]))]

    def play_time(self):
        """Bağlı kalınan süre profilde (oynama_sn): pilot kartının "Player activity: … hours" satırı (canlı test H28)."""
        now = time.time()
        start = getattr(self, 'play_start', None) or now
        self.play_start = now
        with self.profile.lock:
            self.profile.d['play_sec'] = self.profile.d.get('play_sec', 0) + max(0, now - start)

    def rename(self, name):
        """Pilot adını değiştir (ücretsiz). Yeni ad harita değişiminde gemide görünür (istemcinin NameChangeCommand işleyicisi yok).
        Geçersiz ad ya da sunucudaki başka oyuncunun adı (sohbet, posta, grup, klan oyuncuyu adıyla bulur):
        InternalPilotBioUpdateResultsCommand success=False."""
        name = str(name or '').strip()
        last = self.profile.d.get('name_change', 0)
        o = TP.find(name=name)
        if not NAME_MIN <= len(name) <= NAME_MAX:
            why = 'change_pilotname_error_signs_number'
        elif set(name) & NAME_ILLEGAL or '--' in name or not name.isprintable():
            why = 'change_pilotname_error_signs_illegal'
        elif KL.is_banned(name):                                    # Oyun Kuralları 7 (resmî forum 131990): personel adı, küfür
            why = 'name_banned'
        elif o is not None and o.profile is not self.profile or KL.is_member_name(name, self.profile.d['pilot'].get('userName', '')):
            why = 'change_pilotname_error_inUse'           # klandaki çevrimdışı üyenin ya da botun adı da (üyelik kaydı ezilmesin)
        elif SET.get('clan_cooldown') and time.time() - last < NAME_WAIT_SEC:
            why = 'name_cooldown'
        else:
            why = None
        if why is None:
            old = self.profile.d['pilot'].get('userName', '')
            with self.profile.lock:
                self.profile.d['pilot']['userName'] = name
                self.profile.d['name_change'] = time.time()
                self.profile.dirty = True
            KL.name_changed(old, name)
            import name_log as NL                          # öteki oyuncuların rehberi (arkadaş, istek, engelli) ve botların hafızası
            NL.add([{'tur': 'ad', 'eski': old, 'yeni': name}])
            from bot import manager as MGR
            if MGR.ACTIVE is not None:
                MGR.ACTIVE.apply_name_log()
            if self.social.chat:                         # sohbette yeni adla (yoksa yeniden bağlanana dek eski ad)
                self.social.chat.update_user(who=str(self.profile.user_id), userId=name)
            log('   pilot adı: %s' % name)
            return ('InternalPilotBioUpdateResultsCommand', {'success': True, 'baseStackCommand': SHP.stack_msg('change_pilotname_success')})
        log('   pilot adı değişmedi: %r (%s)' % (name, why))
        if why in SHP.REASONS:                                    # BaseKey'de yok: istemcinin metni ham (change_pilotname_error_*)
            en, tr = SHP.REASONS[why]
            msg = SHP.raw_msg((tr if self.shop.lang == 'tr' else en).replace('%DATETIME%', time.strftime('%d.%m.%Y %H:%M', time.localtime(last))))
        else:
            msg = SHP.stack_msg(why)
        return ('InternalPilotBioUpdateResultsCommand', {'success': False, 'baseStackCommand': msg})

    def pilot_bio(self, resp, uid=None):
        """InternalPilotBioRequest: kayıttaki profil kartı + oyuncunun kaydettiği bilgiler (InternalPilotBioUpdateRequest). uid:
        arkadaş sunucusunda başka oyuncunun kartı (rehber, grup, sohbet menüsü: onun kaydından)."""
        o = TP.find(uid=uid) if uid and uid != self.profile.user_id else None
        p = o.profile if o is not None else self.profile
        bio = p.d.get('pilot_bio', {})
        if p is self.profile:
            self.play_time()
        k = KL.clan_of(p) or {}                                       # ortak klan (klan.py)
        order = KL.ranking() if k else []
        rank = {'rank': p.d['pilot'].get('dailyRank', 1),            # pilot kartındaki rütbe (sayı)
                'playTime': int(p.d.get('play_sec', 0) // 3600),     # saat
                'userName': p.d['pilot'].get('userName', ''),          # kayıttaki ad değil, profilinki
                'userId': p.user_id, 'registrationDate': p.d.get('created', '') + '.0',    # kayıttaki hesabınki değil
                'ranking': RT.hof_sira(p),                                  # sunucudaki oyuncular arasında (rutbe.hof_top)
                'clanName': k.get('ad', ''), 'clanRank': next((i + 1 for i, (c, _) in enumerate(order) if c is k), 0),
                'clanMemberCount': len(k.get('members', ()))}
        return [(n, dict(f, **{k: v for k, v in dict(bio, **rank).items() if k in f})) if n == 'InternalPilotBioUserProfileCommand'
                else (n, f) for n, f in resp]

    def send(self, msgs, note=None, quiet=False):
        msgs = INV.client_filter(msgs)                # istemcinin envanter dizinini kıran eşya güncellemeleri (H134)
        w = getattr(self, 'world', None)
        if w is not None and w.defer(msgs):           # dünyanın döngü adımında: dünyanın mesajlarıyla aynı sırada adım sonunda
            if note and not quiet:
                log('-> %s (%d mesaj, adım sonunda)' % (note, len(msgs)))
            elif not quiet:
                for n, f in msgs:
                    log('-> %s %s' % (n, P.fmt(f, 160)))
            return
        data = encode(msgs)
        with self.send_lock:
            if self.queue:
                self.queue.put(data)             # arkadaş sunucusu: ağ dünya kilidini bekletmesin (cok_oyunculu.Kuyruk)
            else:
                self.c.sendall(data)
            if CONTROL:
                for n, f in msgs:
                    CTL.TRACE.add('->', n, f)
        if quiet:
            return
        if note:
            log('-> %s (%d mesaj, %d bayt)' % (note, len(msgs), len(data)))
        else:
            for n, f in msgs:
                log('-> %s %s' % (n, P.fmt(f, 160)))

    def start_world(self):
        map_id = self.profile.d['position']['mapId']
        shared = CO.is_open() and str(int(map_id)) in SHARED and int(map_id) not in self.pve.maps   # arkadaş sunucusu (ortak_harita.py)
        self.world = World(self.profile, lambda m: self.send(m, quiet=True), log, map_id, TEMPLATE.station(map_id), keep_state=True,
                           test_near='--near-npc' in sys.argv or SET.get('nearby_npc'), on_jump=self.change_map, shared=shared)
        self.world.appearance = self.appearance
        self.world.is_group_member = lambda uid: uid in GR.members(self.profile.user_id)
        self.world.death = lambda: GR.died(TP.person(self.profile))
        if CO.is_open() and not shared:                                  # oyuncunun kendi kopyası: saklanan durumu da kendisinin
            self.world.cache_key = '%s:%s' % (map_id, self.profile.user_id)
        self.world.invulnerable = '--invulnerable' in sys.argv
        self.world.dark = int(map_id) in EKP.DARK_MAPS           # Trial of Terrors: el feneri
        self.world.quick_buy = self.shop.quick_buy_msgs
        self.world.auto_buy = self.shop.auto_buy                  # otomatik alım CPU'ları (ekstra.py)
        self.world.auto_buy_fail = self.shop.auto_buy_fail
        self.world.auto_lab = self.shop.auto_lab                  # otomatik laboratuvar CPU'ları
        self.world.money_msgs = self.shop.money_msgs
        self.world.drone_msgs = self.shop.drone_msgs
        self.world.drone_item = self.shop.drone_item
        self.world.unit_msgs = lambda: (self.achievement.title_msgs() + self.shop.drone_msgs()
                                        + [self.shop.module_update(), self.profile.generate('@formasyon')])
        self.world.quest_event = self.quest_event
        self.world.lab_msgs = lambda: [self.shop.lab_cmd()]
        self.world.quest_list = self.quest.list_cmd
        self.world.stats_msgs = self.shop.apply_stats
        self.world.ore_pack = self.shop.ore_pack
        self.world.map_msgs = lambda: TEMPLATE.world_msgs(map_id, 'giris')
        self.world.on_home = self.respawn_home
        self.world.session_tick = self.tick                        # Assembly, Dispatch, Skylab zamanlayıcıları
        self.world.grant = self.shop.reward                       # uzaylının ek ödülündeki ekipman (The Stinger: Caucasus)
        self.world.pet = self.pet
        self.pet.attach(self.world)
        self.world.gg_energy = self.gates.bonus_energy
        LAB.expire_keys(self.profile)                                     # Frozen Labyrinth bittiyse anahtarlar silinir
        self.world.extra_gates = (self.gates.home_portals(map_id, TEMPLATE.station(map_id)) +     # X-1'de hazırlanan kapılar
                                  self.event_gates.entry_portals(map_id, TEMPLATE.station(map_id)) +  # etkinlik kapıları
                                  LAB.portals(map_id, self.gates.home()) +                    # labirentin bölge portalları
                                  self.pve.portals(map_id, TEMPLATE.station(map_id)) +              # modların kapıları (Aşama 8)
                                  self.extra.portals(map_id, TEMPLATE.station(map_id)))                # Ö3: Fiesta Gate
        self.world.start()
        if int(map_id) in KAPI.BY_MAP:
            with self.world.lock:
                self.world.gate = KAPI.Run(self.gates, self.world, KAPI.BY_MAP[int(map_id)])
        elif int(map_id) in EKP.BY_MAP:
            with self.world.lock:
                self.world.gate = EKP.Run(self.event_gates, self.world, EKP.BY_MAP[int(map_id)])
        elif int(map_id) in LAB.MAPS:
            with self.world.lock:
                self.world.labyrinth = LAB.Labyrinth(self.world)        # Frozen Labyrinth (labirent.py)
        with self.world.lock:
            self.pve.attach(self.world)                               # mod haritasıysa koşusu; CPU ve pencereli portallar
            self.new_.attach(self.world)                              # N.O.V.A. (istasyonda mı), otomatik pilot (lazer menzili)
            self.social.attach(self.world)                            # gemi ışınlama (istasyon, savaş, geri sayım)
            extra_msgs = self.extra.attach(self.world)                      # Ö3/Ö4'ün etkinlikleri: öldürme kancaları, harita koşuları
        if extra_msgs:
            self.world.send(extra_msgs)                                  # (önce yok sayılıyordu: Vortex'ten çıkınca HUD açık kalıyordu)
        if int(map_id) == LOW.MAP:
            with self.world.lock:
                self.world.low = LOW.Low(self.world)              # LoW (tek kişilik sürüm, low.py)
        msgs = self.quest_event('map', map=int(map_id))
        comp = H.company(map_id)
        if (comp and comp != self.profile.d['pilot'].get('factionId')) or H.name(map_id).startswith('4-'):
            msgs += self.hint.show(IP.PVP_WARNING)   # başka firmanın haritası ya da 4-X: PvP uyarısı (bir kez)
        if msgs:
            self.send(msgs, 'görev: harita')
        self.profile.ach('map', map=int(map_id))       # başarım: haritaları keşfet

    # ------------------------------------------------------------ görevler
    def quest_map(self, map_id):
        """Görevlerin işaretleri için haritanın görev vericisi ve rafinerisi."""
        g = self.quest
        g.map_id, g.giver, g.trade = int(map_id), None, None
        for n, a in TEMPLATE.world_msgs(map_id, 'giris'):
            if n == 'AssetCreateCommand' and a['type']['typeValue'] == H.QUEST_GIVER:
                g.giver = (a['assetId'], a['posX'], a['posY'])
            if n == 'AssetCreateCommand' and H.STATION_ASSETS.get(a['type']['typeValue']) == 'ttip_ore_trade':
                g.trade = (a['posX'], a['posY'])

    def with_quests(self, msgs):
        """Giriş demetindeki kayıtlı görev mesajları yerine profilin görevleri; kayıttaki Assembly tarif listesi, Dispatch yuvaları
        ve Uridium Bank birikimi yerine profilinkiler."""
        self.quest_map(self.profile.d['position']['mapId'])
        out, done, asm, passes = [], False, False, set()
        present = {n for n, f in msgs}
        for n, f in msgs:
            if n == 'DispatchSlotInfoCommand':
                out.append(self.dispatch.slot_info())
                continue
            if n == 'EventUpdateCommand':             # takvimin etkinlikleri (takvim.py)
                out.append(CAL.event_cmd())
                continue
            if n in ('NpcEventInfoCommand', 'NpcEventBossInfoCommand'):    # kayıttaki Halloween göstergesi: harita etkinliği gönderir
                continue
            if n == 'ContactListInitializationCommand':  # rehber profilden (rehber.py)
                out.append(CT.login_cmd(self.profile))
                continue
            if n == 'DailyLoginRewardDayCommand' and self.daily.claimed_today():
                continue                              # bugünün ödülü alındı: takvim girişte açılmaz (menüden: DailyLoginRewardDayRequest)
            if n in ('HintWindowAddComand', 'HintWindowListInitCommand'):
                out += self.hint_msgs(n, f)           # kapatılan ipuçları yeniden açılmaz, arşive geçer
                continue
            rep = self.social.login_replace(n, f)     # sohbet adresi yerel sunucuya, okunmamış posta (Aşama 10)
            if rep is not None:
                out += rep
                continue
            rep = self.new_.login_replace(n)          # N.O.V.A. kadrosu, Evocation Chip, QFC listesi (Aşama 9): profilden
            if rep is not None:
                out += rep
                continue
            rep = self.pve.login_replace(n)           # modların göstergeleri (Eternal Black Light, Astral Ascension): profilden
            if rep is not None:
                out += rep
                continue
            rep = self.extra.login_replace(n, f)         # Ö3'ün etkinlikleri (ek_etkinlikler.py)
            if rep is not None:
                out += rep
                continue
            group = PASS_LOGIN.get(n)                 # Season Pass, Battle Pass, günlük ödüller: profilden (kayıttaki yerine)
            if group:
                if group not in passes:               # demette kalanlar (harita değişiminde ve --reklamsiz'da pencereler çıkar)
                    passes.add(group)
                    out += [m for m in {'season': self.season, 'ticket': self.ticket, 'reward': self.reward}[group].login_msgs()
                            if m[0] in present or PASS_LOGIN.get(m[0]) != group]
                continue
            code = str(f.get('message', '')).split('|')[2:3] if n == 'LegacyModule' else []
            if code and code[0] in LOOT.CODES:          # ganimet anahtarlarının HUD sayaçları (kayıtta hepsi 0; ganimet.py)
                out.append((n, dict(f, message=LOOT.key_line(self.profile, LOOT.CODES[code[0]]))))
                continue
            if n == 'UnstableModulesListCommand':
                out.append(GM.list_cmd(self.profile))
                continue
            if n == 'ShipUpgradeModuleUpdateCommand' and f.get('uid') == self.profile.user_id:
                out.append(self.shop.module_update())
                continue
            if n == 'UridiumBankInfoCommand':
                out.append(BANK.info_cmd(self.profile))
                self.bank_sent = BANK.value(self.profile)
                continue
            if n in ('QuestInitializationCommand', 'QuestListCommand'):
                if not done:
                    out += self.quest.login_msgs()
                    done = True
                continue
            if n == 'AssemblyRecipeContentModule':
                if not asm:
                    out += self.assembly.login_msgs()
                    asm = True
                continue
            out.append((n, f))
        return out

    def tick(self, now):
        """Dünya döngüsünden (saniyede birkaç kez): zamanlı sistemler (Assembly üretimleri, Skylab yükseltme ve taşımaları, Uridium
        Bank birikimi, takvim)."""
        if now >= self.cal_next:
            self.cal_next = now + 30.0
            self.season.tick(now)                      # Season Pass: gün, hafta, sezon değişimi
            cur = CAL.active(now)
            if cur != self.cal_sent:
                items = self.profile.event_window_items()
                if self.cal_sent is not None:
                    log('   takvim: %s' % ', '.join(sorted(cur)) or '-')
                    changed = [(n, f) for n, f in items if self.win_sent.get(f['itemId']) != f['visible']]
                    self.send([CAL.event_cmd(now)] + changed + CAL.mood_cmds(cur, self.cal_sent),
                              quiet=True)      # menü öğesi (canlıda doğrulanacak: Ö1); harita süsleri
                    self.event_tips(now)
                self.win_sent = {f['itemId']: f['visible'] for n, f in items}
                self.cal_sent = cur
                ACV.set_events(achievement_groups(now))
        self.quest.tick(now)                          # süreli görevler
        if self.profile.d.get('booster_subscription') and now >= getattr(self, 'subscription_next', 0):
            self.subscription_next = now + 5.0
            msgs = self.shop.subscription_tick(now)     # booster aboneliği (forum 127558)
            if msgs:
                self.send(msgs, 'booster aboneliği')
        if now >= self.extra_next:
            self.extra_next = now + 1.0
            msgs = self.extra.tick(now)                  # Ö3'ün etkinlikleri: dönem sonları, zamanlı olaylar
            if msgs:
                self.send(msgs, 'etkinlik: zaman')
        if now >= self.social_next:
            self.social_next = now + 5.0
            msgs = self.social.tick(now)              # müzayede: biten dönemlerde kazanılan eşyalar
            if msgs:
                self.send(msgs, 'müzayede: dönem sonu')
        self.assembly.tick(now)
        self.skylab.tick(now)
        if now >= self.bank_next:
            self.bank_next = now + 5.0
            if self.bank_sent is not None and BANK.value(self.profile) != self.bank_sent:
                self.bank_sent = BANK.value(self.profile)
                self.send([BANK.info_cmd(self.profile)], quiet=True)

    def quest_reward(self, loot, n):
        cur = {'currency_credits': 'kredi', 'currency_uridium': 'uridyum', 'currency_experience': 'ep', 'currency_honour': 'onur'}
        if loot in cur:
            cbs = self.profile.cbs_mods() if getattr(self.profile, 'cbs_mods', None) else {}
            if cur[loot] in ('ep', 'onur'):
                n = int(n * (1 + cbs.get(cur[loot], 0)))
            n = SET.amount(cur[loot], n, 'gorev')           # panelin ödül çarpanları
            tot = self.profile.gain(neden='quest_won', **{cur[loot]: n})
            pet = self.pet.gain_xp(n) if cur[loot] == 'ep' else []        # forum 127074: P.E.T. görev EP'sinin %5'ini de kazanır
            return (self.world.reward_msgs(tot, **{cur[loot]: n}) if self.world else []) + (pet or [])
        return self.shop.prize(loot, n, 'gorev')         # eşya ödülü: panelin mod/görev ödülü çarpanı

    def respawn_home(self):
        """İstasyonsuz haritada istasyonda tamir: firmanın ana haritasında (X-1) istasyonda doğ (gerçek oyundaki gibi); seviye 12+ ve
        üst haritada (X-5 … X-8, 4-4, 4-5) firmanın X-8'inde (harita.x8_home)."""
        pl = self.profile.d['pilot']
        dest = H.x8_home(pl.get('factionId'), pl.get('level', 1), self.profile.d['position']['mapId']) or HOME_MAP.get(pl.get('factionId'), 5)
        st = TEMPLATE.station(dest)
        self.change_map(dest, None, pos=(st['posX'], st['posY']) if st else None)

    def revive_on_login(self):
        """Gemi yok edilmişken oyundan çıkılmışsa: istasyonda ücretsiz tamir (gerçek oyunda çıkıştan sonra portalda ve yerinde tamir
        seçenekleri kalkar, istemcinin ttip_killscreen_logout_1 metni)."""
        g = self.profile.d['gemi']
        if g.get('hitPoints', 1) > 0:
            return
        k = self.profile.d['position']
        st = TEMPLATE.station(k['mapId'])
        if not st or st.get('type') != self.profile.d['pilot'].get('factionId'):        # düşman üssünde tamir yok: kendi ana haritası
            pl = self.profile.d['pilot']
            k['mapId'] = H.x8_home(pl.get('factionId'), pl.get('level', 1), k['mapId']) or HOME_MAP.get(pl.get('factionId'), 5)
            st = TEMPLATE.station(k['mapId'])
        if st:
            k.update(x=st['posX'], y=st['posY'])
        k.pop('at_portal', None)
        self.profile.set_hull(hp=g.get('hitMax', 1), shield=g.get('shieldMax', 0))
        log('   gemi yok edilmiş hâlde çıkılmıştı: %s istasyonunda tamir edildi' % H.name(k['mapId']))

    def change_map(self, dest, gate, pos=None):
        """Portal atlaması (kayıttaki akış): eski haritayı temizle, JumpToServerCommand + yeni haritanın giriş demeti.
        pos verilirse oraya iner (yeniden doğma); verilmezse hedefteki geri dönüş portalının yanına."""
        if gate:
            self.profile.ach('jump')                   # başarım: portal atlamaları
        if gate and gate.get('event_gate'):
            self.event_gates.enter(gate['kapi'])    # etkinlik kapısının girişi: kapı kurulur (canlar, dalga sırası, süre)
            dest = self.event_gates.dest(gate['kapi'])     # karışık sırada ilk harita (Trial of Terrors)
        self.pve.on_jump(gate)                   # Astral'ın çıkışı: oyuncunun donanımı geri
        w0 = self.world                          # kilit sırası dünya iş parçacığıyla aynı (world.lock, sonra state_lock): paket
        with (w0.lock if w0 else contextlib.nullcontext()), self.state_lock:     # iş parçacığından tersi kilitleniyordu
            old = self.profile.d['position']['mapId']
            msgs = TEMPLATE.asset_removes(old)
            if self.world:
                msgs = self.world.cleanup_msgs() + msgs
                self.world.stop()
                self.world = None
            self.pet.attach(None)        # etkinse yeni haritada yeniden çıkar
            pos = pos or (gate or {}).get('arrival')      # kapı portalları: kapı haritasının ortasına / X-1'de kapının yanına
            if pos == 'istasyon':                        # atlama CPU'su ve kapıdan eve dönüş: hedefin istasyonuna (yoksa portalın yanına)
                st = TEMPLATE.station(dest)
                pos = (st['posX'], st['posY']) if st else None
            if pos == 'random':                       # 5-3'ün çıkışları 4-4'te rastgele yere (harita_duzeni.json)
                pos = H.random_arrival(dest)
            x, y = pos or H.arrival(old, dest, self.profile.d['pilot'].get('factionId'))
            self.profile.d['position'].update(mapId=dest, x=x, y=y, at_portal=pos is None)
            self.profile.dirty = True
            save_profile(self.profile)
            self.send(msgs + [('JumpToServerCommand', {})], quiet=True)
            self.map_pending = True      # giriş demetinden önce: istemcinin ReadyRequest'i hemen gelse de kaçmaz
            RT.daily_rank(self.profile)        # gün değiştiyse rütbe (istemci yalnız ShipInitializationCommand'dan okur)
            self.send(self.with_quests(login_batch('giris', first=False, profile=self.profile)),
                      'harita değişimi: %s -> %s, giriş demeti' % (H.name(old), H.name(dest)))
            self.profile.d['position'].pop('at_portal', None)

    def bind_login(self, f):
        """Arkadaş sunucusu: oturumun oyuncusu LoginRequest'in sessionID'sinden. Misafirin oturum anahtarı (web.py'si verir) ya da
        yalnız bu bilgisayardan sunucunun kendi oyuncusu (web.py'nin SESSION'ı). Aynı oyuncunun eski bağlantısı kapanır. -> bağlandı mı."""
        sid = f.get('sessionID') or ''
        m = CO.find(sid)
        if m:
            old, m.session, m.last = m.session, self, time.time()
            if old is not None and old is not self:
                old.hand_over()
            self.guest = m
            self.bind(m.profile)
            self.social.chat_host = '%s:%d' % (m.address or self.addr[0], CHAT.port if CHAT else CO.CHAT_PORT)
            log('   misafir girişi: %s (%s), sunucudaki kimlik %d' % (m.profile.d['pilot'].get('userName'), self.addr[0], m.uid))
            return True
        y = CO.find_local(sid) if self.addr[0] in ('127.0.0.1', '::1') else None
        if y:                                       # çoklu istemcinin ek oyuncusu (bu bilgisayardaki başka bir kayıt)
            old, y.session, y.last = y.session, self, time.time()
            if old is not None and old is not self:
                old.hand_over()
            self.local = y
            self.bind(y.profile)
            log('   ek istemci girişi: %s (kayıt %s), sunucudaki kimlik %d' % (y.profile.d['pilot'].get('userName'), y.save, y.uid))
            return True
        if CO.is_local(sid) and self.addr[0] in ('127.0.0.1', '::1'):
            old = CURRENT
            if old is not None and old is not self:
                old.hand_over()
            self.bind(PROFILE)
            return True
        log('   giriş reddedildi: bilinmeyen oturum (%s)' % (self.addr,))
        return False

    def appearance(self, x, y):
        """Öteki oyuncuların istemcisinde bu oyuncunun gemisi (shared_maps.py): kayıttaki başka oyuncunun mesajları
        (ShipCreateCommand, unvan, dronlar, gemi modülleri)."""
        p = self.profile
        pl, g = p.d['pilot'], p.d['gemi']
        import admin_mode as YM
        direction = YM.is_open(p)                     # yönetici: rozet ve yönetici gemisi öteki oyunculara da
        create = ('ShipCreateCommand', dict(
            userId=p.user_id, typeId=(direction and YM.ship(p)) or g.get('typeId', 'ship_liberator'), expansionStage=p.d.get('expansion_stage', 1),
            clanTag=pl.get('clanTag', ''), userName=pl.get('userName', ''), x=x, y=y, factionId=pl.get('factionId', 0),
            clanId=pl.get('clanId', 0), dailyRank=YM.BADGE if direction else pl.get('dailyRank', 0), warnBox=False, clanDiplomacy=world.mod('ClanRelationModule', type=0),
            galaxyGatesDone=KAPI.rings(p), useSystemFont=pl.get('useSystemFont', True), npc=False, cloaked=False,
            motherShipId=0, positionIndex=0, designSet='', modifier=[], minimapStrategyModule=world.mod('MinimapStrategyModule', minimapStrategy=0),
            specialNpcType=''))
        return [create] + self.achievement.title_msgs() + self.shop.drone_msgs() + [self.shop.module_update()]

    def on_packet(self, name, mid, f, err):
        if name == 'LoginRequest':
            P.secrets_of(f, self.secrets)
        if name not in UNLOGGED:
            log('<- %s(%s) %s%s' % (name, mid, P.fmt(P.redact(f, self.secrets), 300), ' [HATA %s]' % err if err else ''))
        w = self.world
        if self.profile is None and name not in ('VersionRequest', 'LoginRequest', 'KeepAlive'):
            return                               # arkadaş sunucusu: oyuncu girişte belli olur (giris_bagla)
        if name == 'VersionRequest':
            self.send([('VersionCommand', {'version': f['version'], 'equal': True})])
        elif name == 'LoginRequest':
            if self.profile is None and not self.bind_login(f):
                self.close()
                return
            self.revive_on_login()
            RT.daily_rank(self.profile)                     # günlük rütbe (ShipInitializationCommand.dailyRank)
            self.send(self.with_quests(login_batch('giris', profile=self.profile)), 'giriş demeti')
            self.map_pending = True
        elif name == 'ReadyRequest' and (self.map_pending or (w and w.reload_pending)):
            with self.state_lock:      # dünyaya kilit dışında dokun (harita değişimi dünya iş parçacığından bu kilidi alır)
                self.map_pending = False
                start = self.world is None
                self.ready_n += 1
            # Restabilize sekmesinin listesi: kayıtta girişten sonra ve envanter değişince ayrıca geliyor, giriş demetlerinde yok;
            # yalnız demetteki kaydın yerine konduğu için hiç gitmiyordu, sekme "No Items" diyordu (canlı test H69)
            unstable = [GM.list_cmd(self.profile)]
            self.send(login_batch('hazir', profile=self.profile) + self.shop.login_msgs() + self.pet.login_msgs() + self.achievement.title_msgs()
                      + self.new_.login_msgs() + unstable + self.extra.login_msgs(), 'hazır demeti')
            if start:
                self.start_world()
                self.achievement.sync()              # seviye, P.E.T. seviyesi, takılı eşyalar (önceden ulaşılanlar da sayılır)
                self.pass_event('login')         # "oyuna gir" görevleri (Unity ödülü; kayıt: girişten hemen sonra biter)
                self.pass_event('level', value=self.profile.d['pilot'].get('level', 1))
                self.event_tips()                # süren etkinliğin açıklaması (dönemde bir kez)
                group = GR.login_msgs(TP.person(self.profile))     # bağlantı kopup dönen üye: grubu ve bekleyen davetler (grup.py)
                if group:
                    self.send(group, 'grup: giriş')
            else:
                self.send(self.cbs.attach(self.world), 'CBS: harita yeniden yüklendi')
                self.world.resend()
            if self.ready_n > 1:                 # harita yüklendi (portal, ışınlama, yeniden doğma): istemci menüyü yeniden kuruyor
                self.extra.on_ready()               # (Urgent Missions'ın simgesi, acil_gorevler.py)
            self.pet.on_ready()
        elif name == 'KeepAlive':
            self.send([('StayinAlive', {})], quiet=True)
        elif name == 'MoveRequest':
            log('<- MoveRequest konum=(%d,%d) hedef=(%d,%d)' % (f['positionX'], f['positionY'], f['targetX'], f['targetY']))
            # Moves sent on the old map during a jump countdown or a map change must not overwrite the arrival position
            # (change_map sets it under state_lock, then builds ShipInitializationCommand from it).
            with self.state_lock:
                if w is not None and self.world is w and not w.jumping:
                    self.profile.apply(name, f)
            if w:
                w.on_move(f)     # outside state_lock: the world thread takes world.lock, then state_lock (change_map)
            # yanıt yok: gerçek sunucu oyuncunun kendi hareketine MoveCommand göndermiyor (kayıt: 876 isteğe 0). Gönderilen
            # MoveCommand istemcinin "hedefe varınca" işini (cevhere varınca HarvestRequest) kesiyordu.
        elif name == 'AttackAbortLaserRequest' and w:
            w.laser_stop()
        elif name == 'JumpRequest':
            if not (w and w.jump(f)):
                log('   atlama yok: yakında portal değil')
        elif name == 'QuestAcceptRequest':
            if w and not w.near_giver:
                # görev ancak görev vericinin (Mission Control) yanında alınır; istemcinin metni "Fly to Mission Control to see if
                # there are any missions for you."
                log('   görev alınamadı: görev vericiden uzakta (%s)' % f.get('questId'))
                self.send([legacy('0|A|STM|msg_maybe_quest_at_nyx'), self.quest.list_cmd()], 'görev: uzak')
            else:
                self.send(self.quest.accept(f.get('questId')) + self.quest_state_events(), 'görev: kabul')
        elif name == 'QuestCancelRequest':
            self.send(self.quest.cancel(f.get('questId')), 'görev: iptal')
        elif name == 'QuestInfoRequest':
            self.send(self.quest.info(f.get('questId')), quiet=True)
        elif name == 'QuestPrivilegeRequest':
            self.send([('QuestPrivilegeCommand', {'questId': f.get('questId', 0)})], quiet=True)
        elif name in ('QuestSettingsRequest', 'QuestListRequest'):
            if name == 'QuestSettingsRequest':
                self.profile.apply(name, f)                 # görev penceresinin süzgeci profilde kalsın
            self.send([self.quest.list_cmd()], quiet=True)
        elif name == 'QuestGiverApproachedRequest':
            msgs = self.quest.event('giver') if w and w.near_giver == f.get('questGiverId') else []
            self.send(msgs or [self.quest.list_cmd()], 'görev verici')
        elif name == 'TradeRequest' and w:
            self.send([w.trade_info()], 'rafineri: fiyatlar')
        elif name == 'KillScreenRepairRequest' and w:
            w.kill_screen_repair(f)
        elif name == 'AchievementListRequest':
            self.send(self.achievement.request(f), 'başarımlar')
        elif name == 'SkillTreeListRequest':
            self.send([self.skill.list_cmd()], 'yetenek ağacı')
        elif name == 'ConvertResearchPointsRequest':
            self.send(self.skill.convert(), 'yetenek ağacı: pilot puanı')
        elif name == 'UpLevelSkillTreeRequest':
            self.send(self.skill.up_level(f), 'yetenek ağacı: seviye')
        elif name == 'ResetSkillTreeRequest':
            self.send(self.skill.reset(), 'yetenek ağacı: sıfırlama')
        elif name == 'DailyLoginRewardDayRequest':
            self.send([self.daily.info_cmd()], 'günlük giriş: bilgi')
        elif name == 'DailyLoginClaimTodayRequest':
            self.send(self.daily.claim(), 'günlük giriş: ödül')
        elif name == 'GalaxyGateBuilderInfoRequest':
            self.send(self.gates.info_request(), 'kapı üreticisi: bilgi')
        elif name == 'GalaxyGateBuilderGetGatePartsRequest':
            self.send([self.gates.parts_cmd(f)], quiet=True)
        elif name == 'GalaxyGateBuilderMultiEnergyRequest':
            self.send(self.gates.spin(f), 'kapı üreticisi: çekiliş')
        elif name == 'GalaxyGateBuilderSetupGateRequest':
            self.send(self.gates.setup(f), 'kapı üreticisi: hazırlık')
        elif name == 'GalaxyGateBuilderBuyLifeRequest':
            self.send(self.gates.buy_life(f), 'kapı üreticisi: can')
        elif name == 'GalaxyGateBuilderSaveSpinAmountRequest':
            self.gates.save_spin(f)
        elif name == 'PetRequest':
            self.pet.request(f)
        elif name == 'PetGearActivationRequest':
            self.pet.gear_request(f)
        elif name == 'MapAssetActivationRequest':
            if self.cbs.handles(name, f):                # Clan Battle Station asteroidi/istasyonu (Ö5): pencere verisi
                self.send(self.cbs.handle(name, f), 'CBS: pencere')
            # portal için ardından JumpRequest gelir
        elif name == 'HangarShipActivateShipRequest':
            # oyundaki gibi yalnız istasyonda; gemi değişince istemci yeni gemiyle haritayı yeniden yükler (yeniden doğma gibi)
            k = self.profile.d['position']
            here = (k.get('mapId'), k.get('x'), k.get('y'))
            msgs, changed = self.shop.activate(f, in_station=w.in_station() if w else True, travel=True)
            self.send(msgs, 'hangar: gemi etkinleştirme')
            if changed and w:
                w.items.reveal()      # üste gemi değiştirmek gizlenme CPU'sunu bitirir (fandom Cloak; Ship Warp hariç: isinlama.py)
                if k['mapId'] != here[0]:                    # yeni gemi başka haritada bekliyor: oraya geçilir
                    self.change_map(k['mapId'], None, pos=(k['x'], k['y']))
                else:
                    w.reload_ship(pos=(k['x'], k['y']) if (k['x'], k['y']) != here[1:] else None)
        elif name == 'HangarShipChangeShipModelRequest':
            msgs, reload = self.shop.change_model(f)
            self.send(msgs, 'hangar: tasarım')
            if reload and w:
                w.reload_ship()      # yeni görünümle ShipInitializationCommand (istemci haritayı yeniden yükler)
        elif name == 'LegacyModule':                  # eski metin protokolü (eski_protokol.py)
            key, parts = legacy_parse(f)
            if key == 'S|CFG' and len(parts) > 2:
                msgs = self.shop.switch_config(parts[2])
                if msgs:
                    self.send(msgs, 'config geçişi')
            elif key == 'i' and len(parts) > 1 and parts[1].isdigit():
                if w:                                 # istemci bilmediği bir kimliği soruyor (kayıt: gerçek sunucu yeniden gönderir)
                    w.info_request(int(parts[1]))
            elif key == 'JCPU' and CIT.has_ajp(self.profile):  # gelişmiş atlama CPU'su (AJP-01): uzay haritasının atlama paneli
                if len(parts) > 1 and parts[1] == 'GET':
                    self.send([CIT.jcpu_list(self.profile), CIT.vouchers_msg(self.profile)], 'gelişmiş atlama listesi')
                elif w:
                    with w.lock:
                        w.items.jcpu(parts)
            elif key == 'XCP' and len(parts) > 1 and parts[1].isdigit() and w:
                with w.lock:                          # 5-2 tüccarında Palladium -> kapı enerjisi: istemci "XCP|<adet>" gönderiyor
                    w.trade_palladium(int(parts[1]))  # (canlı deneme 2026-10-17; TradeSellOreRequest gelmiyor)
            elif key == 'AEQ' and len(parts) > 1:     # Ayarlar > Gameplay "Auto-equip new items": istemci yaması OtomatikKusanma
                with self.profile.lock:                 # (istemcinin kendi kutusu hiçbir şey göndermiyor)
                    self.profile.d['auto_equip'] = parts[1] == '1'
                    self.profile.dirty = True
            elif key in ('LF', 'JCPU'):
                pass                                  # her girişte LF|c, JCPU|GET; gerçek sunucu da yanıt vermiyor (kayıt)
            else:
                log('   yanıtsız: LegacyModule %s' % key)
        elif name == 'UIButtonTriggerRequest':
            item = f.get('itemId')
            self.windows.opened(item)
            if item == 'logout':
                self.logout_start()
            else:                                     # pencere açıldı bildirimi (sosyal.py): gemi ışınlama penceresi
                resp = self.social.window(item) + self.extra.window(item)       # Ö3: Pursuit of Prestige penceresi …
                if resp:
                    self.send(resp, 'pencere: %s' % item)
        elif name == 'HangarShipAutoBuyCpuAmmoRequest':   # hangarda otomatik alım CPU'suna cephane seçimi
            self.send(self.shop.auto_buy_ammo(f), 'otomatik alım cephanesi')
        elif name == 'HallOfFameTopRequest':
            self.send(RT.hof_top(self.profile, f), 'Hall of Fame: %s' % f.get('type'))
        elif name == 'HallOfFamePagesRequest':
            self.send(RT.hof_pages(self.profile, f), 'Hall of Fame sayfası')
        elif name == 'HallOfFameDataListRequest':
            self.send(RT.hof_events(self.profile, f), 'Hall of Fame etkinlikleri')
        elif name == 'LogbookDataListRequest':
            self.send(RT.logbook(self.profile, f), 'seyir defteri')
        elif name == 'BalanceInfoListRequest':
            self.send(RT.balance(self.profile, f), 'hesap geçmişi')
        elif name == 'LogoutCancelRequest':
            self.logout_cancel()
        elif name == 'HintWindowClosedRequest':      # gerçek sunucu yanıt vermiyor (kayıt); kapatılan ipucu bir daha açılmasın
            c = (f.get('closedWindow') or {}).get('content')
            if c is not None and not f.get('wasOpenedFromArchive'):
                with self.profile.lock:
                    lst = self.profile.d.setdefault('hints_closed', [])
                    if c not in lst:
                        lst.append(c)
                        self.profile.dirty = True
        elif name == 'InternalPilotBioRequest':
            # kayıtta olmayan kimlik (arkadaş sunucusunda öteki oyuncu): kayıttaki kart şablon olur, alanlar onun profilinden
            self.send(self.pilot_bio(TEMPLATE.response(name, f) or TEMPLATE.response(name, {}) or [], int(f.get('userId') or 0)), 'pilot kartı')
        elif name == 'InternalPilotBioUpdateRequest':
            with self.profile.lock:
                old = self.profile.d.get('pilot_bio', {})
                self.profile.d['pilot_bio'] = dict({k: v for k, v in f.items() if k not in ('_', 'userId')},
                                             **({'statusMessage': old['statusMessage']} if 'statusMessage' in old else {}))
                self.profile.dirty = True
            self.send([('InternalPilotBioUpdateResultsCommand', {'success': True, 'baseStackCommand': None})], 'pilot kartı: kayıt')
        elif name == 'InternalPilotBioUpdateStatusRequest':          # pilot kartındaki durum yazısı (Ö1; UIPilotSheetSystem)
            with self.profile.lock:
                self.profile.d.setdefault('pilot_bio', {})['statusMessage'] = str(f.get('statusMessage') or '')[:STATUS_MAX]
                self.profile.dirty = True
            self.send([('InternalPilotBioUpdateResultsCommand', {'success': True, 'baseStackCommand': None})], 'pilot kartı: durum')
        elif name == 'InternalPilotBioUpdateUserNameRequest':        # profil düzenlemede ad değiştirme (Ö1; UIEditProfileSystem)
            self.send([self.rename(f.get('userName'))], 'pilot kartı: ad')
        elif name == 'GroupInvitationBlockToggleRequest':
            with self.profile.lock:                         # kayıt: her istekte açılıp kapanır
                self.profile.d['invite_block'] = not self.profile.d.get('invite_block', False)
                self.profile.dirty = True
            self.send([('InvitationBlockModule', {'active': self.profile.d['invite_block']})], 'grup daveti engeli')
        elif name in GR.REQUESTS:
            # grup (grup.py): arkadaş sunucusunda öteki oyuncular; tek oyunculuda kimse yok (davet: error 2 CANDIDATE_NONEXISTENT)
            resp = GR.handle(TP.person(self.profile), name, f)
            if resp:
                self.send(resp, 'grup: %s' % name)
        elif name in CT.REQUESTS:                                    # rehber ve posta penceresinin kişiler sekmesi (rehber.py)
            resp = CT.handle(TP.person(self.profile), name, f)
            if resp:
                self.send(resp, 'rehber: %s' % name)
        elif name == 'CommandCenterNewsClickedRequest':              # haberin tıklanması (E8; yanıtı yok): profildeki sayaç
            with self.profile.lock:
                c = self.profile.d.setdefault('news_read', {})
                c[str(f.get('newsId'))] = c.get(str(f.get('newsId')), 0) + 1
                self.profile.dirty = True
        elif name == 'CommandCenterNewsInfoRequest':                 # istemcinin haberlerinin tıklanma sayıları (takvim.news)
            c = self.profile.d.get('news_read', {})
            ids = [dict(_='CommandCenterNewsModule', eventId=x.get('eventId', 0), newsId=x['newsId'], clickCount=c[x['newsId']])
                   for x in f.get('newsInfo') or [] if c.get(x.get('newsId'))]
            self.send([('CommandCenterInfoCommand', {'ids': ids})], 'Command Center: %d haber' % len(f.get('newsInfo') or []))
        elif name in SILENT:
            if name == 'EggTriggerRequest' and 0 <= f.get('eggTriggerType', -1) < len(EGG_TYPES):
                self.profile.ach('egg', tur=EGG_TYPES[f['eggTriggerType']])     # gizli başarımlar (EVENT_SECRET); yanıtı yok
        elif name.startswith(('Assembly', 'Disassembly', 'Dispatch', 'Skylab')):
            sysm = self.assembly if name.startswith(('Assembly', 'Disassembly')) else self.dispatch if name.startswith('Dispatch') \
                else self.skylab
            resp = sysm.handle(name, f)
            if resp is None:
                log('   yanıtsız: %s' % name)
            elif resp:
                self.send(resp, '%s: %s' % (name.split('Request')[0], name))
        elif name.startswith(('SeasonPass', 'BattlePass')) or name in DRW_REQUESTS:
            sysm = self.season if name.startswith('SeasonPass') else self.ticket if name.startswith('BattlePass') else self.reward
            resp = sysm.handle(name, f)
            if resp is None:
                log('   yanıtsız: %s' % name)
            elif resp:
                self.send(resp, name.split('Request')[0])
        elif name.startswith('UnstableModule') or name == 'RerollWindowSettingsRequest':
            resp = self.modules.handle(name, f)
            if resp:
                self.send(resp, 'Restabilize: %s' % name)
        elif name == 'RankRewardRequest' and RK.reward(f) is not None:     # sıralama ödül tabloları (Ö1; siralama.py)
            self.send(RK.reward(f), 'sıralama ödülleri')
        elif name in GMC.REQUESTS:                                          # GM konsolu (Ö2; gm_konsol.py)
            self.send(self.gm.handle(name, f), 'GM konsolu: %s' % (f.get('name') or name))
        elif name == 'EvoucherHistoryListRequest':                          # kupon penceresinin geçmişi: yerelde kod çözümü yok (Ö1)
            self.send([('EvoucherHistoryListCommand', {'list': []})], 'kupon geçmişi')
        elif name == 'UridiumBankClaimRequest':
            before = self.profile.d['pilot'].get('uridium', 0)
            self.send(BANK.claim(self.profile, self.shop.money_msgs, log), 'Uridium Bank')
            self.bank_sent = BANK.value(self.profile)
            if self.profile.d['pilot'].get('uridium', 0) > before:
                self.pass_event('recharge')                # tek oyunculu: Unity ödülünün "yükleme" görevi (gerçek oyunda ödeme)
        elif self.shop.handles(name, f):
            resp = self.shop.handle(name, f)
            if resp is None:
                resp = TEMPLATE.response(name, f)
            if resp:
                self.send(resp, 'mağaza/hangar: %s' % name)
            if w and name == 'HangarShipMoveItemsRequest' and w.repairing and not w.repair_rate():
                w.stop_repair()          # onarım robotu çıkarıldı
            if name == 'HangarShipMoveItemsRequest':
                self.profile.ach('sync')       # başarım: takılı eşyalar (Champion/Beacon tasarımı)
        elif name == 'SlotBarConfigSetRequest':
            tpl = next((m for m in TEMPLATE.entry.get('hazir', []) if m['_m'] == 'MenuInitializationCommand'), None)
            if tpl and self.profile.slot_bar_set(f, tpl['slotBars']):
                self.send([('MenuInitializationCommand', self.profile.patch_template('MenuInitializationCommand', tpl))]
                          + self.quest.event('slot_bar', **self.profile.slot_bar_state(tpl['slotBars'])), 'kısayol çubuğu')
        elif name in PVM.REQUESTS:
            self.send(self.pve.handle(name, f), 'mod: %s' % name)      # Aşama 8'in modları (pve_modlari.py)
        elif name == 'ChangeClanFirmaRequest':                         # şirket değiştirme (klan.switch_company): yeni firmanın X-1'i
            msgs, home = self.social.clan.switch_company(f)
            self.send(msgs, 'şirket değişimi')
            if home:
                if self.profile is PROFILE:
                    H.PLAYER_FACTION = self.profile.d['pilot'].get('factionId')
                st = TEMPLATE.station(home)
                self.change_map(home, None, pos=(st['posX'], st['posY']) if st else None)
        elif name in SO.REQUESTS:
            resp = self.social.handle(name, f, time.time())             # Aşama 10: sosyal bölüm (sosyal.py)
            if resp:
                self.send(resp, 'sosyal: %s' % name)
        elif name in NS.REQUESTS:
            resp = self.new_.handle(name, f)                           # Aşama 9'un sistemleri (yeni_sistemler.py)
            if resp:
                self.send(resp, 'yeni sistem: %s' % name)
        elif self.extra.handles(name):
            resp = self.extra.handle(name, f)                             # Ö3'ün etkinlikleri (ek_etkinlikler.py)
            if resp:
                self.send(resp, 'etkinlik: %s' % name)
        elif name in WORLD_REQUESTS and w:
            getattr(w, WORLD_REQUESTS[name])(f)
        elif self.profile.apply(name, f):
            log('   profile yazıldı: %s' % name)
            if name == 'DisplaySettingsRequest':
                self.profile.ach('display', use2d=f.get('displayUse2d'))      # başarım: 3B görünüm (Uses3D)
                # SaveInterfaceSettingsTab changes flags, but the client only applies toolbar visibility on UIBag refresh.
                tpl = next((m for m in TEMPLATE.entry.get('hazir', []) if m['_m'] == 'MenuInitializationCommand'), None)
                if tpl:
                    self.send([('MenuInitializationCommand', self.profile.patch_template('MenuInitializationCommand', tpl))],
                              'arayüz: kısayol çubukları')
            if name == 'UIWindowUpdateRequest':
                if f.get('maximized'):
                    self.windows.opened(f.get('itemId'))
                if 'trade' in str(f.get('itemId')) and not f.get('maximized') and w:       # ticaret penceresi kapandı (P.E.T. kargo tüccarı)
                    with w.lock:
                        self.pet.trade_close(time.time())
                resp = self.extra.window_update(f)        # pencere açıldı/kapandı (UIButtonTriggerRequest göndermeyenler)
                if resp:
                    self.send(resp, 'pencere: %s' % f.get('itemId'))
        else:
            resp = no_popups(TEMPLATE.response(name, f) or [])
            if resp:
                self.send(resp, 'kayıtlı yanıt: %s' % name)
            elif name != 'ReadyRequest':
                log('   yanıtsız: %s' % name)

    def run(self):
        log('connect %s' % (self.addr,))
        fr = P.Framer(client_side=True)
        last_save = time.time()
        try:
            while True:
                d = self.c.recv(65536)
                if not d:
                    break
                for pkt in fr.feed(d):
                    mid, name, f, left, err = P.decode_message(pkt)
                    if CONTROL:
                        CTL.TRACE.add('<-', name, f)
                    with self.packet_lock:
                        try:                      # bir isteğin hatası oturumu düşürmesin: yığın izi günlüğe, istemci bağlı kalır
                            self.on_packet(name, mid, f, err)
                        except ConnectionError:
                            raise
                        except Exception:
                            log('   istek hatası (%s):\n%s' % (name, traceback.format_exc()))
                    if time.time() - last_save > 10:
                        last_save = time.time()
                        self.play_time()
                        save_profile(self.profile)
        except ConnectionError as e:
            log('   bağlantı kapandı: %r' % e)
        except Exception:
            log('error\n%s' % traceback.format_exc())
        if self.world:
            self.world.stop()
        if self.profile is not None:
            self.play_time()
            save_profile(self.profile)
            if not any(s is not self and s.profile is self.profile for s in list(SESSIONS)):
                CT.forget(self.profile.user_id)              # sonraki girişte rehber baştan gider
        log('disconnect %s' % (self.addr,))
        global CURRENT
        if CURRENT is self:
            CURRENT = None
        SESSIONS.discard(self)
        if self.queue:                              # kuyruktakiler gitsin, sonra soket kapanır (kapanmayınca iş parçacığı + soket sızıyordu)
            self.queue.close()
            self.queue.thread.join(5)
        try:
            self.c.close()
        except OSError:
            pass
        m = self.guest
        if m is not None and m.session is self:      # misafirin son hâli yayımlanır (paneli alır); yeniden bağlanabilir
            self.profile.save(force=True)
            m.session, m.last = None, time.time()
        y = self.local
        if y is not None and y.session is self:      # ek oyuncu: istemcisi yeniden açılınca sürer; panel bırakınca kayıttan çıkar
            with CO.COND:
                y.session, y.last = None, time.time()
                if y.finished:
                    CO.LOCAL_PLAYERS.pop(y.session, None)

    def payment_click(self):
        """İstemcinin ödeme düğmesi (odeme.Dinleyici: 127.0.0.1:443'e bağlandı): mağaza Extras'ta açılır, ürün ekranda yazılır."""
        msg = self.windows.offline()
        if msg:                                       # kupon kodu ya da resim yükleme: mağaza açılmaz
            log('   443: ödeme dışı istek -> %s' % msg)
            with self.packet_lock:
                self.send([KAPI.screen(msg)], '443: ekran metni')
            return
        item = self.windows.guess()
        log('   ödeme düğmesi -> mağaza (son pencere: %s)' % (item or '-'))
        with self.packet_lock:
            self.send(PAY.redirect(self.shop, item), 'ödeme düğmesi: mağaza')

    def inject(self, name, f):
        """Kontrol kanalı: istemci göndermiş gibi bir istek (izde '<=')."""
        CTL.TRACE.add('<=', name, f)
        log('<= (kontrol) %s' % name)
        with self.packet_lock:
            self.on_packet(name, -1, f, None)


def handle(c, addr):
    """Yeni bağlantı. Arkadaş sunucusunda (--multiplayer) önce ilk baytlara bakılır: HTTP ise misafirin hesap gönderimi
    (cok_oyunculu.http), değilse oyun istemcisi (oyuncusu girişte belli olur; gönderme kuyruğuyla)."""
    if not CO.is_open():
        Session(c, addr).run()
        return
    try:
        c.settimeout(20)
        first, end = b'', time.time() + 20
        while len(first) < 4 and time.time() < end:
            first = c.recv(4, socket.MSG_PEEK)
            if not first:
                c.close()
                return
            if len(first) < 4:
                time.sleep(0.05)
        c.settimeout(None)
    except OSError:
        c.close()
        return
    if CO.is_http(first):
        CO.http(c, addr, sys.modules[__name__])
    else:
        Session(c, addr, wait=True, queue=True).run()


def close_session(s):
    s.close()


def payment_session(addr):
    """Ödeme düğmesine basan istemcinin oturumu: tek oturumda (ya da süreç bulunamazsa) sunucunun kendi oyuncusununki; çoklu
    istemcide bağlanan süreç oturumların istemcileriyle eşlenir (odeme.baglanan_pid; oyun bağlantısı 8081'de)."""
    sessions = [s for s in list(SESSIONS) if s.profile is not None]
    if len(sessions) > 1:
        pid = PAY.connecting_pid(addr, PAY.PORT)
        for s in sessions if pid else []:
            if s.client_pid is None:
                s.client_pid = PAY.connecting_pid(s.addr, 8081)
            if s.client_pid == pid:
                return s
    return CURRENT


def payment_clicked(addr):
    s = payment_session(addr)
    if s is not None:
        s.payment_click()


def server_info():
    """GET /misafir/bilgi: misafirin paneli bağlanmadan önce gösterir (sunucunun pilotu, oyuncular, şifre, yer, sürümler)."""
    ms = CO.entries()
    names = sorted({s.profile.d['pilot'].get('userName', '?') for s in list(SESSIONS) if s.profile is not None})
    try:
        client = open(os.path.join(DATA, 'protocols', 'version.txt'), encoding='utf8').read().strip() or '1.1.116'
    except OSError:
        client = '1.1.116'
    client = max(client, '1.1.116', key=lambda v: tuple(int(x) for x in v.split('.')))     # surum.txt güncellemede eskide kalabilir
    return {'sunucu': 'darkorbit', 'protokol': CO.PROTOCOL, 'code': CO.SETTINGS['code'], 'client': client,
            'pilot': PROFILE.d['pilot'].get('userName', ''), 'players': names, 'guest': len(ms), 'max_count': CO.SETTINGS['max_count'],
            'password': bool(CO.SETTINGS['password']), 'yer': len(ms) < CO.SETTINGS['max_count']}


def watch_world():
    """Dünya Editörü: oyun açıkken dünya dosyası değişince mağazanın fiyatları ve açık artırmanın lotları yenilenir (veri.CANLI);
    öteki değişiklikler sunucu yeniden başlayınca (panel bildirir)."""
    import auction as MZ
    while True:
        time.sleep(2)
        try:
            changed = GD.refresh()
            if 'shop' in changed:
                SHP.refresh()
            if 'social.json' in changed:
                MZ.refresh()
            if changed:
                log('dünya canlı güncellendi: %s' % ', '.join({'shop': 'mağaza', 'social.json': 'açık artırma'}[d] for d in changed))
        except Exception:
            log('dünya izlenemedi: %s' % traceback.format_exc())


def autosave():
    """Profil 10 sn'de bir diske (değiştiyse). Oturum yalnız istemciden paket gelince kaydediyordu: boşta yapılan son değişiklik
    (pencere kapatma, kontrol kanalı, NPC ödülü) sunucu penceresi kapatılırsa kayboluyordu (canlı test H57).
    --stop-file=<dosya> (panel): dosya belirince oynama süresi ve profil kaydedilir, sunucu kapanır (zorla kapatmada son 10 sn gitmesin)."""
    last = time.time()
    while True:
        time.sleep(0.5 if STOP else 10)
        if STOP and os.path.exists(STOP):
            stop_gracefully()
        if time.time() - last < 10:
            continue
        last = time.time()
        save_profile()                    # dosya kilitliyse bir sonraki turda
        for s in list(SESSIONS):         # arkadaş sunucusu: misafirlerin kayıtları (yeni sürüm panellerine gider)
            if s.profile is not None and s.profile is not PROFILE:
                save_profile(s.profile)
        if CO.is_open():
            CO.tick(close_session)


def stop_gracefully():
    """Panelin durdurma isteği: oturumun oynama süresi ve profil kaydedilir, süreç çıkar."""
    try:
        if CURRENT is not None:
            CURRENT.play_time()
        PROFILE.save(force=True)
        BOT.close()                       # bot paketinin durumu
        if CO.is_open():                     # misafirlerin son hâli panellerine (bekleyen yoklamalara) verilir, ek oyuncularınki yuvalarına
            for s in list(SESSIONS):
                if s.guest is not None or s.local is not None:
                    s.play_time()
            for y in CO.local_players():
                save_profile(y.profile)
            CO.shutdown()
        log('panel: durdurma isteği, profil kaydedildi, sunucu kapanıyor')
    except Exception as e:
        log('panel: durdururken kayıt hatası %r' % e)
    try:
        os.remove(STOP)
    except OSError:
        pass
    os._exit(0)


def main():
    global CHAT
    if PTH.MIGRATION_ERROR:                                # kayıtlar yeni biçime taşınamadı: eski biçimle yarım açılmaz
        sys.exit('save migration failed: %s' % PTH.MIGRATION_ERROR)
    P.warning = log
    SET.configure()              # oyun ayarları (panel): --ayarlar=<yol> ya da save/ayarlar.json; değişince kendiliğinden okunur
    log('ayarlar: %s | %s' % (SET._state['route'], ', '.join('%s %s' % x for x in SET.summary()) or 'varsayılan'))
    log(GD.summary())             # Dünya Editörü'nün dünyası (OO_WORLD; veri.py)
    address = '127.0.0.1'
    if '--multiplayer' in sys.argv:  # arkadaş sunucusu: oyun ve sohbet bütün ağlardan (cok_oyunculu.py); ayarlar ortam değişkeninde
        CO.configure(os.environ.get('OO_MULTIPLAYER'), log)
        address = CO.SETTINGS['address']
        KL.configure(os.path.join(PTH.SAVE, 'clans.json'))     # ortak klanlar: çevrimdışı üyeye olanlar sonraki girişte
    CHAT = CHT.Chat(log, address=address)
    CHAT.start()                # yerel sohbet (7771); istemci girişteki ChatParamCommand ile buraya bağlanır
    if os.environ.get('OO_BOT'):
        BOT.server(os.environ['OO_BOT'], log)     # Botlar sayfasının paketi (dünyaya atanmış)
    threading.Thread(target=autosave, daemon=True).start()
    if os.environ.get('OO_WORLD'):
        threading.Thread(target=watch_world, daemon=True).start()
    CD.start(sys.modules[__name__], LOG_DIR, log)     # panelin canlı durum sayfası (<günlükler>/canli_durum.json)
    PCH.start(sys.modules[__name__], LOG_DIR, log)     # panelin oyun menüleri (Mağaza, Hangar, Skylab, Açık Artırma): yerel kanal
    if CONTROL:
        CTL.Control(sys.modules[__name__]).start()
        CHAT.trace = CTL.chat_trace          # sohbet çerçeveleri de izde ("Sohbet:<tür>")
    PAY.Listener(payment_clicked, log).start()     # ödeme düğmeleri -> mağaza (127.0.0.1:443)
    s = socket.socket()
    if CO.is_open() and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)    # Windows: başka süreç aynı portu ele geçiremesin
    else:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((address, 8081)); s.listen(16)
    log('gs listening %s:8081 | profil: %s %s harita %s | şablon: %s%s%s' % (
        address, PROFILE.d['pilot'].get('userName'), PROFILE.d['gemi'].get('typeId'), PROFILE.d['position']['mapId'],
        TEMPLATE.entry.get('kaynak', 'none'), ' | profil dosyası: %s' % PROFILE.path if PROFILE_PATH else '',
        (' | arkadaş sunucusu: en çok %d misafir%s' % (CO.SETTINGS['max_count'], ', şifreli' if CO.SETTINGS['password'] else '')
         if CO.SETTINGS['guest'] else ' | çoklu istemci (yalnız bu bilgisayar)') if CO.is_open() else ''))
    while True:
        c, addr = s.accept()
        threading.Thread(target=handle, args=(c, addr), daemon=True).start()


if __name__ == '__main__':
    main()
