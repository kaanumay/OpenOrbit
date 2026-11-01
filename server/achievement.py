"""Başarımlar ve unvanlar (profilde "basarimlar"; veri data/achievements.json ← istemcinin başarım XML'leri, tools/achievements.py).

Kayıt: AchievementListRequest {displayTitleId} -> AchievementListCommand {list: tamamlanan başarımlar (AchievementInfoCommand
{achievementId, level: tamamlanan seviye, score: o seviyenin hedefi, lastUpdate}), unlockAchievements1: süren başarımlar (level:
sıradaki seviye, score: sayaç; yalnız 0'dan büyükler), nextAchievements: bunlardan 7'si, unlockAchievements2 [], displayTitleId
(-1: unvan yok), titleCommandList [AchievementTitleCommand {key, id}]}. Puanları istemci kendi XML'inden toplar.
İstemcinin kodundan: kazanınca "0|A|ACG|<başarım>_<derece>|<sayı>" (derece: XML'in grade'i; gemide efekt ve açılır pencere: <anahtar>_name ve
<anahtar>_description içindeki %COUNT%); pilot sayfasındaki unvan kaydetme düğmesi AchievementListRequest {displayTitleId: seçilen}
gönderir (0: değişiklik yok sayılır). Gemi üstündeki unvan "0|n|t|<kullanıcı>|<unvan kimliği>|<unvan anahtarı>" (kayıt).
Olaylar profil.ach(tür, ...) ile gelir (dünya, görevler, kapılar, mağaza, P.E.T.): kill, gain, box, box_ammo, quest, map, jump,
distance, shot, damage, minute, formation, equip, gate, death, level, pet_level, ability, laser_types, tutorial, season_level,
dispatch, event_score, assembly_collect, package, gate_wave; E6: display (görüntü ayarının displayUse2d'si: 3B), egg (istemcinin
EggTriggerRequest'i), wb_heal / wb_damage (World Boss savaşında onarılan can ve alınan hasar), rekor_ebl / rekor_plutus (şampiyon
başarımları: tek oyunculu sıralamada kişisel rekor birinciliktir). Karşılığı olmayan koşullar (PvP, WIZ-X ile oyuncu dönüştürme, klan,
Skylab, ölü modların şampiyonlukları …) veride kalır, ilerlemez.
"""
import json, os, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'achievements.json'), encoding='utf8'))
ACH = D['achievements']
TITLES = D['unvanlar']
TITLE_KEYS = {v: k for k, v in TITLES.items()}
EVENT_TITLE_BASE = 2000          # tabloda olmayan (etkinlik) unvanlar: 2000 + crc32 % 30000 (istemcide kimlik short)
CURRENCY = {'CREDITS': 'kredi', 'URIDIUM': 'uridyum', 'EXPERIENCE': 'ep', 'HONOUR': 'onur'}
NEXT = 7                         # kayıt: nextAchievements 7 tane
# etkinlik başarımları (EVENT_* grupları, sezon bileti, etkinlik özniteliği olanlar) yalnız o etkinlik açıkken ilerler; sunucuda
# etkinlik yok, veri yerinde kalır. Bir etkinlik eklenince grubu (ya da etkinlik adı) buraya.
ACTIVE_EVENTS = set()
# koşul sınıfı -> onu ilerleten olaylar (motor yalnız bunlara bakar)
KINDS = {'Currency': 'gain', 'AvatarTypeKill': 'kill', 'NpcTypeDestroyed': 'kill', 'Collect': 'box', 'AssetCollect': 'box_ammo',
         'Quest': 'quest', 'QuestDeathless': 'quest', 'QuestSelection': 'quest', 'DiscoverMaps': 'map', 'Gatejumps': 'jump',
         'Distance': 'distance', 'AmmoShots': 'shot', 'Damage': 'damage', 'Playtime': 'minute', 'PlaytimeOnEnemyMap': 'minute',
         'MapTypeCheck': 'minute', 'DroneFormationChange': 'formation', 'DroneFormationDroneAmount': 'formation', 'EquipItem': 'equip',
         'GalaxyGateDone': 'gate', 'Destruction': 'death', 'KilledByAvatarType': 'death', 'Level': ('level', 'pet_level'),
         'AbilityType': 'ability', 'LaserTypeUsage': 'laser_types', 'TutorialFinished': 'tutorial',
         'PlayerCloaked': 'cloak_minute', 'ChainImpulse': 'chain_kill',
         # Ö1 (2026-10-18): Season Pass seviyesi (sezon.py), Dispatch (dispatch.py), seçili uzaylı türü (dunya.py, istemcinin ShipIcon
         # adıyla), etkinlik puanı (Plutus: etkinlik_kapi.py), Assembly'de toplanan üretim (assembly.py), mayın koyma (savas_esya.py: shot MINE), paket ödülü
         # (kapi.py: Prosperous), EBL dalgası (ebl.py). DesignMutationCount (WIZ-X ile oyuncu dönüştürme) bot oyuncularla.
         'LevelAbsolute': 'season_level', 'Dispatch': 'dispatch', 'NPCSelectionKill': 'kill', 'EventScore': 'event_score',
         'BuildRecipe': 'assembly_collect', 'TriggerMine': 'shot', 'CollectPackage': 'package', 'ClearGalaxyGateWave': 'gate_wave',
         # E6
         'Uses3D': 'display', 'EggTriggerCount': 'egg', 'PublicWorldBossCondition': ('wb_heal', 'wb_damage'),
         'Influence': 'influence'}       # Battle for Influence: kapı zaferinin nüfuz puanı (kapi.py; resmî forum 131012)
# takvimsiz etkinlik grupları: hep açık (Eternal Black Light'ın eski adı Eternal Gate; mod her gün açık; gizli Easter Egg'ler)
ALWAYS_GROUPS = {'EVENT_ETERNALGATE', 'EVENT_SECRET'}
# istemcinin ShipIcon adı uzaylının adından çıkmıyorsa (NPCSelectionKill)
ICON_ALIASES = {'FRIGHTFUL_CURCUBITOR': 'BOSS_FRIGHTFUL_CURCUBITOR'}


def ship_icons(name):
    """Uzaylının görünen adı -> istemcinin ShipIconModule.ShipIcon adayları ("..::{ Boss StreuneR }::.." -> BOSS_StreuneR,
    BOSS_STREUNER; enum büyük-küçük harf ayırıyor: StreuneR ve Streuner ayrı türler)."""
    import re
    words = re.findall(r'[A-Za-z0-9]+', name or '')
    if not words:
        return ()
    exact = '_'.join(w.upper() if w.lower() == 'boss' else w for w in words)
    out = (exact, exact.upper())
    return out + ((ICON_ALIASES[exact.upper()],) if exact.upper() in ICON_ALIASES else ())
# sunucu tarafı koşullar (IgnoredCondition): başarım -> olay. Aylık sıralama: tek oyunculu uyarlama, rütbe puanı kazanılan her ay;
# 1. sıra General of the Month, 2-50. sıra Acclaimed Pilot sayacı (rutbe.py daily_rank yeni ayın ilk hesabında, rütbeden sanal sıra)
SERVER_SIDE = {'achievement_monthlyranking-general': 'monthly_general', 'achievement_monthlyranking-pilot': 'monthly_pilot',
               # şampiyonlar (E6 uyarlaması): sıralamada tek oyuncu; kişisel rekor (EBL'de en ileri dalga, Plutus'ta en iyi süre)
               'achievement_event_eternalgate-champion': 'rekor_ebl', 'achievement_event_gauntletofplutus-champion': 'rekor_plutus'}


def mod(name, **f):
    f['_'] = name
    return f


from legacy_protocol import legacy  # noqa: E402,F401  (eski metin protokolü: eski_protokol.py)


def in_season(a):
    seasonal = a['grup'].startswith(('EVENT_', 'SEASONPASS')) or a.get('etkinlik')
    return not seasonal or a['grup'] in ACTIVE_EVENTS or a['grup'] in ALWAYS_GROUPS or a.get('etkinlik') in ACTIVE_EVENTS


def _index():
    out = {}
    for aid, a in ACH.items():
        if not a['etkin'] or not in_season(a):
            continue
        for c in a['seviyeler']:
            k = KINDS.get(c['sinif'])
            for kind in (k if isinstance(k, tuple) else (k,)) if k else ():
                out.setdefault(kind, [])
                if aid not in out[kind]:
                    out[kind].append(aid)
    return out


BY_KIND = _index()


def set_events(names):
    """Takvimin etkin başarım grupları (event_calendar.py): değişince olay dizini yeniden kurulur -> değişti mi."""
    global BY_KIND
    names = set(names)
    if names == ACTIVE_EVENTS:
        return False
    ACTIVE_EVENTS.clear()
    ACTIVE_EVENTS.update(names)
    BY_KIND = _index()
    return True
METAS = {}                       # başvurulan başarım -> MetaAchievement'lar (skor: onun tamamlanan seviyesi)
for _aid, _a in ACH.items():
    for _c in _a['seviyeler']:
        if _a['etkin'] and _c['sinif'] == 'MetaAchievement':
            for _ref in _c.get('parametreler', {}).get('achievementId', []):
                METAS.setdefault(_ref, set()).add(_aid)


def param(c, k):
    return c.get('parametreler', {}).get(k, [])


def measure(c, kind, kw):
    """Koşul bu olayla nasıl ilerler: ('add', n) | ('set', değer) | ('item', küme öğesi) | None."""
    s = c['sinif']
    if s == 'Currency':
        n = kw.get(CURRENCY.get((param(c, 'currencyType') or [''])[0], ''), 0)
        return ('add', n) if n > 0 else None
    if s == 'AvatarTypeKill':
        if kw.get('avatar', 'NPC') not in param(c, 'avatar') or (param(c, 'id') and str(kw.get('npc')) not in param(c, 'id')):
            return None
        for i in c.get('ic', []):
            if i['sinif'] != 'InRadiation' or not kw.get('radyasyon'):
                return None
        return ('add', 1)
    if s == 'NpcTypeDestroyed':
        return ('item', str(kw.get('npc'))) if kw.get('avatar', 'NPC') == 'NPC' else None
    if s == 'Collect':
        if kw.get('tip') not in param(c, 'boxType') or ('PET' in param(c, 'avatar') and not kw.get('pet')):
            return None
        return ('add', 1)
    if s == 'AssetCollect':
        return ('add', kw.get('adet', 0)) if kw.get('silah') in param(c, 'assetType') else None
    if s in ('Quest', 'QuestDeathless'):
        return ('add', 1)
    if s in ('QuestSelection',):
        return ('item', str(kw.get('id')))
    if s == 'DiscoverMaps':
        return ('item', str(kw.get('map')))
    if s == 'Gatejumps':
        return ('add', 1)
    if s == 'Influence':
        return ('add', int(kw.get('puan', 0))) if kw.get('puan') else None
    if s in ('Distance', 'Damage'):
        return ('add', int(kw.get('adet', 0))) if kw.get('adet', 0) >= 1 else None
    if s == 'AmmoShots':
        return ('add', kw.get('adet', 1)) if kw.get('silah') in param(c, 'weaponType') else None
    if s == 'Playtime':
        return ('add', 1) if 'PET' not in param(c, 'avatar') or kw.get('pet') else None
    if s == 'PlaytimeOnEnemyMap':
        return ('add', 1) if kw.get('enemy_map') else None
    if s in ('PlayerCloaked', 'ChainImpulse'):            # gizli kalınan dakika; Chain Impulse ile öldürme (teknoloji.py)
        return ('add', 1)
    if s == 'MapTypeCheck':
        return ('add', 1) if kw.get('pvp_map') and 'PVP' in param(c, 'mapType') else None
    if s == 'DroneFormationChange':
        return ('add', 1)
    if s == 'DroneFormationDroneAmount':
        return ('set', kw.get('dron', 0))
    if s == 'EquipItem':
        return ('set', 1) if set(param(c, 'item')) & set(kw.get('esyalar', ())) else None
    if s == 'LaserTypeUsage':                               # 60 sn içinde kullanılan cephane türleri (dunya.py)
        return ('window', [str(i) for i in kw.get('items', [])])
    if s == 'TutorialFinished':                             # başlangıç görev zinciri (20000-20003) bitti
        return ('set', 1)
    if s == 'AbilityType':                                  # gemi yetenekleri (gemi_yetenek.py)
        return ('add', 1) if kw.get('tur') in param(c, 'abilityType') else None
    if s == 'GalaxyGateDone':
        return ('add', 1) if kw.get('tur') in param(c, 'galaxyGateType') else None
    if s == 'Destruction':
        return ('add', 1) if kw.get('neden') in param(c, 'reason') else None
    if s == 'KilledByAvatarType':
        if kw.get('npc') is None or 'NPC' not in param(c, 'avatar') or (param(c, 'id') and str(kw['npc']) not in param(c, 'id')):
            return None
        return ('add', 1)
    if s == 'Level' and c.get('olay') == 'LEVEL':          # sezon biletinin Level'ları başka olayla (SEASONPASS_Q…)
        who = 'PLAYER' if kind == 'level' else 'PET'
        return ('set', kw.get('deger', 0)) if who in param(c, 'avatar') else None
    if s == 'LevelAbsolute':                                # "Gold Season Pass'in 50 seviyesi": bu sezonun grubu (sezon.py)
        return ('set', kw.get('deger', 0)) if c.get('olay') == kw.get('grup') else None
    if s == 'Dispatch':                                     # DISPATCH_RETRIEVER / DISPATCH_GATE
        return ('add', 1) if c.get('olay') == kw.get('olay') else None
    if s == 'NPCSelectionKill':
        hit = kw.get('avatar', 'NPC') == 'NPC' and set(ship_icons(kw.get('ad'))) & set(param(c, 'npcType'))
        return ('add', 1) if hit else None
    if s == 'EventScore':                                   # "bir etkinlikte N puan": etkinlik dönemindeki toplam
        return ('set', kw.get('deger', 0)) if kw.get('etkinlik') in param(c, 'event') and c.get('olay') == 'EVENT_SCORE' else None
    if s == 'BuildRecipe':
        return ('add', kw.get('adet', 1)) if kw.get('tarif') in param(c, 'recipeId') else None
    if s == 'TriggerMine':                                  # "N mayını T saniyede, ölmeden": süre penceresindeki sayı
        limit = next((int(t.get('time', 0)) for t in param(c, 'timeLimit') if isinstance(t, dict)), 0)
        return ('times', limit) if kw.get('silah') in param(c, 'weaponType') else None
    if s == 'CollectPackage':
        return ('add', 1) if kw.get('paket') in param(c, 'packageId') else None
    if s == 'ClearGalaxyGateWave':                          # "Eternal Gate'te N. dalgaya ulaş": ulaşılan en yüksek dalga
        return ('max', kw.get('dalga', 0)) if kw.get('tur') in param(c, 'galaxyGateType') else None
    if s == 'Uses3D':                                       # 3B görünüm (DisplaySettingsModule.displayUse2d false)
        return ('set', 1) if kw.get('use2d') is False else None
    if s == 'EggTriggerCount':
        return ('add', 1) if kw.get('tur') in param(c, 'eggTriggerType') else None
    if s == 'PublicWorldBossCondition':                     # recoverhp / takedamage (unvanın adında); yalnız bu yılın başarımı
        want = 'wb_heal' if 'recoverhp' in c.get('unvan', '') else 'wb_damage'
        year = c.get('olay', '').endswith('_%d' % time.localtime().tm_year)
        return ('add', int(kw.get('adet', 0))) if kind == want and year and kw.get('adet', 0) > 0 else None
    return None


def state(p):
    return p.d.setdefault('achievements', {'score': {}, 'kume': {}, 'seviye': {}, 'tarih': {}, 'unvanlar': [], 'unvan': -1})


def target(c):
    return len(c['kume']) if 'kume' in c else c.get('deger', 1)


def title_id(key):
    """Unvanın kimliği. Başarım tablosunda olmayan etkinlik unvanları (World Boss, Mimesis, Strike and Exit, Galaxy Trek, BL/Astral
    sıralaması) anahtardan sabit kimlik alır: her açılışta aynı, kayıttaki seçili unvan yeniden açılışta da çözülür."""
    if key not in TITLES:
        TITLES[key] = EVENT_TITLE_BASE + zlib.crc32(key.encode()) % 30000
        TITLE_KEYS[TITLES[key]] = key
    return TITLES[key]


class Achievements:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        for k in state(profile)['unvanlar']:
            title_id(k)
        self.send = None             # oturum: kendiliğinden giden mesajlar (kazanma bildirimi, güncel liste)

    # ------------------------------------------------------------ durum
    def level(self, aid):
        return state(self.p)['seviye'].get(aid, 0)

    def current(self, aid):
        lv, levels = self.level(aid), ACH[aid]['seviyeler']
        return levels[lv] if lv < len(levels) else None

    def score(self, aid, c=None):
        st = state(self.p)
        c = c or self.current(aid)
        if c and 'kume' in c:
            return len(set(st['kume'].get(aid, [])) & set(c['kume']))
        return st['score'].get(aid, 0)

    def met(self, aid, c):
        if not c or not c['sinif'] or (c['sinif'] == 'IgnoredCondition' and aid not in SERVER_SIDE):
            return False
        s = self.score(aid, c)
        return s > target(c) if c.get('operator') == '>' else s >= target(c)

    # ------------------------------------------------------------ olaylar
    def event(self, kind, **kw):
        """Oyun olayı -> sayaçlar; tamamlanan seviyeler bildirilir. -> [(başarım, seviye)]."""
        if kind == 'sync':
            return self.sync()
        st = state(self.p)
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        changed = []
        with self.p.lock:
            if kind == 'death':                       # resetOnDeath: ölmeden yapılması gerekenler baştan
                for aid in ACH:
                    c = self.current(aid)
                    if c and c.get('reset_on_death') and (st['score'].get(aid) or st.get('time', {}).get(aid)):
                        st['score'][aid] = 0
                        st.get('time', {}).pop(aid, None)
                        st['tarih'][aid] = now
                        self.p.dirty = True
            for aid in list(BY_KIND.get(kind, ())) + [a for a, k in SERVER_SIDE.items() if k == kind and ACH.get(a, {}).get('etkin')]:
                c = self.current(aid)
                k = (SERVER_SIDE.get(aid) or KINDS.get(c['sinif'])) if c else None
                if not k or kind not in (k if isinstance(k, tuple) else (k,)):
                    continue
                m = ('add', 1) if c['sinif'] == 'IgnoredCondition' else measure(c, kind, kw)
                if not m:
                    continue
                ev = ACH[aid].get('period_reset')             # "ilerleme bir sonraki etkinliğe taşınmaz" (Ölümsüz Tutku; resmî forum)
                if ev:
                    import event_calendar as CAL
                    span = CAL.period(ev)
                    key = int(span[0]) if span else 0
                    if st.setdefault('donem', {}).get(aid) != key:
                        st['donem'][aid] = key
                        st['score'][aid] = 0
                        st['kume'].pop(aid, None)
                op, v = m
                if op == 'add':
                    st['score'][aid] = st['score'].get(aid, 0) + v
                elif op == 'set':
                    if st['score'].get(aid) == v:
                        continue
                    st['score'][aid] = v
                elif op == 'max':
                    if v <= st['score'].get(aid, 0):
                        continue
                    st['score'][aid] = v
                elif op == 'times':                  # son v saniyedeki olay sayısı (TriggerMine); ölünce sıfırlanır (olumde_sifir)
                    t = time.time()
                    times = [x for x in st.setdefault('time', {}).get(aid, []) if t - x < v] + [t]
                    st['time'][aid] = times
                    st['score'][aid] = len(times)
                elif op == 'window':                 # kümenin anlık hâli (süre penceresi): birikmez
                    cur = sorted(set(v) & set(c['kume']), key=str)
                    if st['kume'].get(aid) == cur:
                        continue
                    st['kume'][aid] = cur
                else:
                    if v not in c['kume'] or v in st['kume'].get(aid, []):
                        continue
                    st['kume'].setdefault(aid, []).append(v)
                st['tarih'][aid] = now
                changed.append(aid)
            if changed:
                self.p.dirty = True
        return self.advance(changed)

    def advance(self, aids):
        """Koşulu tutan seviyeleri tamamla (birden çok seviye birden geçilebilir); MetaAchievement'ları güncelle; bildir."""
        st = state(self.p)
        done, msgs, todo = [], [], list(aids)
        while todo:
            aid = todo.pop(0)
            while self.met(aid, self.current(aid)):
                c = self.current(aid)
                with self.p.lock:
                    st['seviye'][aid] = self.level(aid) + 1
                    st['tarih'][aid] = time.strftime('%Y-%m-%d %H:%M:%S')
                    if c.get('unvan') and c['unvan'] not in st['unvanlar']:
                        st['unvanlar'].append(c['unvan'])
                    self.p.dirty = True
                lv = self.level(aid)
                done.append((aid, lv))
                # istemci metni ve simgeyi XML'in grade'iyle arar (<başarım>_<grade>_name); bazı başarımlarda sıradan farklı
                # (achievement_destroy_centuryfalcon tek seviye, grade 2): canlı test H29, boş bildirim kutusu çıkıyordu
                msgs.append(legacy('0|A|ACG|%s_%d|%d' % (aid, c.get('grade', lv), target(c))))
                self.log('   başarım: %s seviye %d (+%d puan%s)' % (aid, lv, c.get('puan', 0),
                                                                   ', unvan %s' % c['unvan'] if c.get('unvan') else ''))
                for meta in METAS.get(aid, ()):
                    with self.p.lock:
                        st['score'][meta] = lv
                    todo.append(meta)
        if msgs and self.send:
            # yalnız kazanma satırı (kayıt: liste ancak AchievementListRequest'e). Liste kendiliğinden gönderilince pilot sayfası hiç
            # açılmamışsa istemci çöküyordu (canlı deneme 2026-10-17: UIPilotSheetSystem.UpdateTotalPoints, NullReference)
            self.send(msgs)
        return done

    def sync(self):
        """Profilden hesaplananlar (store=false): oyuncu ve P.E.T. seviyesi, takılı eşyalar (dron tasarımları dahil)."""
        d = self.p.d
        done = self.event('level', deger=d['pilot'].get('level', 1))
        if d.get('pet'):
            done += self.event('pet_level', deger=d['pet'].get('seviye', 0))
        items = [x for v in d.get('ekipman', {}).values() for x in v]
        items += [self.p.drone_design(x, s) for x in d.get('dronlar', []) for s in ('design', 'visual')]
        done += self.event('display', use2d=d.get('ayarlar', {}).get('displaySettingsModule', {}).get('displayUse2d'))
        return done + self.event('equip', esyalar=[x for x in items if x])

    # ------------------------------------------------------------ istemci
    def info(self, aid, level, score):
        return mod('AchievementInfoCommand', lastUpdate=state(self.p)['tarih'].get(aid, ''), achievementId=aid, level=level,
                   score=int(score))

    def list_cmd(self):
        st = state(self.p)
        done, running = [], []
        for aid, a in ACH.items():
            if not a['etkin']:
                continue
            lv = self.level(aid)
            if lv:
                done.append(self.info(aid, lv, target(a['seviyeler'][lv - 1])))
            c = self.current(aid)
            if c and c['sinif'] and self.score(aid, c) > 0:
                running.append((self.score(aid, c) / max(target(c), 1), self.info(aid, lv + 1, self.score(aid, c))))
        nxt = [x for _, x in sorted(running, key=lambda r: -r[0])[:NEXT]]
        titles = [mod('AchievementTitleCommand', key=k, id=TITLES[k]) for k in st['unvanlar'] if k in TITLES]
        return ('AchievementListCommand', dict(unlockAchievements2=[], nextAchievements=nxt, displayTitleId=st['unvan'],
                                               titleCommandList=titles, list=done, unlockAchievements1=[x for _, x in running]))

    def title_msgs(self):
        """Gemi üstündeki unvan (kayıt: 0|n|t|<kullanıcı>|<kimlik>|<anahtar>); yoksa boş."""
        t = state(self.p)['unvan']
        return [legacy('0|n|t|%d|%d|%s' % (self.p.user_id, t, TITLE_KEYS[t]))] if t in TITLE_KEYS else []

    def request(self, f):
        """AchievementListRequest {displayTitleId}: 0 liste; -1 unvanı kaldır; sahip olunan unvanın kimliği onu seçer."""
        st = state(self.p)
        t = int(f.get('displayTitleId') or 0)
        msgs = []
        if t and t != st['unvan']:
            if t == -1 or TITLE_KEYS.get(t) in st['unvanlar']:
                with self.p.lock:
                    st['unvan'] = t
                    self.p.dirty = True
                msgs = self.title_msgs()
                self.log('   unvan: %s' % (TITLE_KEYS.get(t) or 'yok'))
            else:
                self.log('   unvan seçilemedi: %d sahip olunmuyor' % t)
        self.sync()
        return [self.list_cmd()] + msgs
