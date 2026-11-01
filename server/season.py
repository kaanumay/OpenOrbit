"""Season Pass (yol haritası Aşama 7; veri data/tickets.json "sezon" <- tools/tickets.py, kayıttaki pencereden).

Kayıttaki akışlar ve istemcinin mesajları:
  giriş              SeasonPassStatusCommand {pointsCost, uridiumCost (seviye başına), goldPass, extGoldPass, seasonName, marketingImage,
                     timeToEventEnd sn}, SeasonPassRewardInfoCommand (üç ödül sırası, claimed), SeasonPassMissionInfoCommand
                     {refreshInfo, missionItems [SeasonPassMissionModule {missionStatus, questDefinitionModule}]}, SeasonPointsInfoCommand
  görev ilerlemesi   QuestConditionUpdateCommand (görev motorunun biçimi); bitince "0|A|STM|sp_daily-mission-completed" (weekly, season),
                     QuestCompletedCommand {id, rating}, başarım olayı (kayıt: achievement_quest_quests_1), SeasonPointsInfoCommand
  ödül               SeasonPassRewardClaimRequest {level, goldPass, extGoldPass} -> ödül + SeasonPassRewardClaimCommand {claimed}
                     SeasonPassRewardClaimAllRequest -> alınabilen hepsi
  seviye satın alma  SeasonPassLevelPurchaseRequest {amount} -> uridyumla (uridiumCost) -> SeasonPassLevelPurchaseCommand {success}
  görev yenileme     SeasonPassRefreshRequest {questId, costType}: günlük ya da haftalık görevin yerine havuzdan başkası
Görev durumu (istemcinin MissionStatusType'ı): 0 sürüyor, 1 Gold sürüyor, 2 Gold Pass gerekir, 3 bitti, 4 Gold bitti, 5 Gold Pass
gerekir ama bitti (puanı Gold Pass alınınca gelir).
Tek oyunculu uyarlamalar: ödül sırası ve görevler kayıttaki sezonun (her sezon aynı); yalnız sezon tasarımları (dron ve P.E.T.;
2024-2025 sezonlarında Gold sırasının sonunda gemi tasarımı) sezonun sırasından: 2023-05 Mobius … 2026-08 Cerevisia (kayıttaki),
sonra baştan (etkinlik_gorunumleri.season_track; geçmiş sezonların tasarımları başka yoldan alınamıyordu).
Sezonlar gerçek oyunun ayları: şubat, mayıs, ağustos, kasım başı (season_id "2026-08"); bilinen sezonların gerçek tarihleri
data/tickets.json "sezon.takvim"de (wiki: XIV 01.08.2026 - 25.10.2026 = 86 gün, kayıttaki timeToEventEnd 25.10 23:59'a denk; XV
26.10.2026'dan, kaynak çıkana dek uyarlama), tabloda olmayanlar ay kuralıyla.
Sezon bitince alınmamış ödüller verilir (istemcinin metni: "Any unclaimed rewards from the previous season has been booked to you");
N.O.V.A. kaptanları bekler: sezon sonu penceresi SeasonPassRewardUnclaimedInfoCommand {captainPending, captainOwned, captainLimit,
captainWarning} (istemcinin ShowEndView'ı; girişte bekleyen varken yine), düğmesi SeasonPassRewardClaimAllRequest. Kadroda yer yoksa
kaptan ödülü alınmaz, SeasonPassCaptainLimitCommand ("Your N.O.V.A. roster is already full!"); bekleyenler sonraki sezon sonunda yanar.
Günlük görevler (3 + 2 Gold) her gün, haftalıklar (5 + 3 Gold) pazartesi havuzdan çekilir (wiki havuzu: 48 günlük, 51 haftalık görev;
"Complete 1 of the following tasks" satırları çok koşullu görev); sezonluklar sezon boyunca. Yenileme: günde 1 ücretsiz, sonra
satın alınanlar 1-4. 500 U, 5-7. 1.000 U, 8-10. 2.000 U, 11+. 4.000 U (wiki; günlük ve haftalık ayrı sayılır, gün ve hafta başında
sıfırlanır; kayıttaki refreshInfo sıradaki fiyatı bildirir). Seviye azami olunca satın alınan fazla puan 1 puan = 10 Onur. Gold Pass
mağazada (resource_gold-pass 400.000 U) ya da paketten; Extra Gold Pass Gold Pass'ten sonra.
Kayda özgü sezon (geliştirici notu 2026-10-28; oyuncu bildirimi: gerçek takvimin sezonu 25.10'da bitince bilet "kapanıyordu"):
sezon kaydın ilk girişinde 1. günden başlar ve panelin sezon_suresi günü sürer (takvimden bağımsız; süre değişince süren sezona da
uygulanır); aynı anda tek sezon. Biten sezonun yerine sıradaki: kayıt "ilerlemeli" oluşturulduysa (profil 'ilerlemeli', panelin yeni
kayıt penceresi) ilk sezondan (2023-05 Mobius) başlayıp her sezon bitince bir sonrakine, en yeniye dek; sonradan eklenen sezonlar
sırası gelince açılır, hepsi oynandıysa en yenisi yinelenir. Değilse hep en yeni sezon. Sezonun kimliği tasarımlarının sezonu
(etkinlik_gorunumleri.SEASONS); başarım grubu ve süreli tariflerin bitişi bu sezondan (ACTIVE). Takvim işlevleri (season_id …)
gerçek oyunun sezonlarını bilmek için kalır.
Profilde: sezon {donem, bas, oynanan, puan, gold, ext, alinan, gun, gunluk, hafta, haftalik, deger, tamam, yenileme, bekleyen [[kaptan, adet]]}.
"""
import datetime, json, os, random, threading, time

import settings as SET
import event_appearances as EG
import quest_tracker as GT
import nova as NV
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, 'data', 'tickets.json'), encoding='utf8'))['season']
COST, UCOST = S['point_cost'], S['uridium_cost']
MAX_LEVEL = len(COST) - 1
MISSIONS = {int(k): v for k, v in S['quests'].items()}
DAILY, WEEKLY, SEASON = 3, 6, 9
DAILY_N, WEEKLY_N = (3, 2), (5, 3)            # (normal, Gold) (kayıt)
REFRESH_LADDER = [tuple(x) for x in S['refresh_ladder']]        # (bu sıraya dek yenileme ya da None, bedel U)
OVERFLOW_HONOR = 10                           # azami seviyenin üstündeki satın alınan puan: 1 puan = 10 Onur (wiki)
DONE_TEXT = {DAILY: 'sp_daily-mission-completed', WEEKLY: 'sp_weekly-mission-completed', SEASON: 'sp_season-mission-completed'}
TRACKS = (('free', False, False), ('gold', True, False), ('ext', False, True))
GOLD_ITEM, EXT_ITEM, POINT_ITEM = 'resource_gold-pass', 'resource_ext-gold-pass', 'resource_season-pass-point'


def _reserve_pool(*tracks):
    return [(r[1], r[2]) for t in tracks for r in S['reward'][t]
            if r[1].startswith('resource_') and r[1] not in (GOLD_ITEM, EXT_ITEM, POINT_ITEM)]


# Season Pass rezervleri (package_seasonpass-*): ödül sıralarında paket olarak gelir, istemci içeriğini vermez (yalnız "A reserve
# containing useful resources for the average pilot" / "… only the most sought after resources in the galaxy" / "… booty keys").
# Uyarlama: açılınca aynı sezonun ödül sırasındaki kaynak satırlarından biri (Gold: Gold ve Extra Gold sıraları; dev rezerv üç çekiş),
# ganimet anahtarı rezervi ücretsiz sıranın 10 anahtarı. Önceden ödül yolunda tanınmayıp görünmez depoya düşüyordu (2026-10-22).
RESERVES = {'package_seasonpass-free': (_reserve_pool('free'), 1),
            'package_seasonpass-gold': (_reserve_pool('gold', 'ext'), 1),
            'package_seasonpass-gold-giant': (_reserve_pool('gold', 'ext'), 3),
            'package_seasonpass-bootykey': ([('resource_booty-key', 10)], 1),
            'package_seasonpass-bootykey-giant': ([('resource_booty-key', 10)], 3)}


def reserve(loot, n=1):
    """Rezerv açılınca verilenler [(lootId, adet)] (aynı eşya birleşir) ya da None (rezerv değil)."""
    if loot not in RESERVES:
        return None
    pool, draws = RESERVES[loot]
    out = {}
    for _ in range(int(n) * draws):
        l, k = random.choice(pool)
        out[l] = out.get(l, 0) + k
    return sorted(out.items())


def mod(name, **f):
    f['_'] = name
    return f


def _day(text, plus=0):
    return (datetime.datetime.strptime(text, '%Y-%m-%d') + datetime.timedelta(days=plus)).timestamp()


# gerçek tarihleri bilinen sezonlar: ((yıl, ay), başlangıç, bitiş ya da None = ay kuralının sonu); bitiş günü dahil
WINDOWS = [(tuple(int(x) for x in w['id'].split('-')), _day(w['start']), _day(w['end_time'], 1) if w.get('end_time') else None)
           for w in S.get('calendar', [])]


def formula_end(y, m):
    """Ay kuralına göre (y, m) sezonunun bitişi: üç ay sonra ayın ilk günü."""
    return datetime.datetime(y + (m == 11), (m + 2) % 12 + 1, 1).timestamp()


def season_span(now=None):
    """Zamandaki sezon: ((yıl, ay), bitiş zamanı). Gerçek oyunun sezonları şubat, mayıs, ağustos ve kasım başında
    (achievement_seasonpass_202608); tablodaki sezonun tarihleri (sezon.takvim) kuralı geçersiz kılar."""
    now = time.time() if now is None else now
    t = datetime.datetime.fromtimestamp(now)
    rule = t.year - (t.month < 2), (t.month - 2) % 12 // 3 * 3 + 2
    for ym, a, b in WINDOWS:
        if a <= now and (now < b if b else rule <= ym):          # bitişsiz sezon, ay kuralı bir sonrakine geçene dek sürer
            return ym, b or formula_end(*ym)
    return rule, formula_end(*rule)


def season_start(now=None):
    """Sezonun başladığı (yıl, ay)."""
    return season_span(now)[0]


def season_id(now=None):
    return '%d-%02d' % season_start(now)


def season_end(now=None):
    return season_span(now)[1]


ACTIVE = {}                 # oynanan sezon {sid, bitis} (Sezon.ensure yazar): başarım grubu ve süreli tarifler (assembly) buna bakar


def current_end(now=None):
    """Oynanan sezonun bitişi (kayda özgü); bilinmiyorsa takvimin sezonununki."""
    return ACTIVE.get('end_time') or season_end(now)


def achievement_group(now=None):
    """Bu sezonun Season Pass başarım grubu (SEASONPASS_Qn; istemcinin LevelAbsolute başarımları: "Gold Season Pass'in 50 / 80
    seviyesi"). Gerçek oyunun sezonları başlangıç ayıyla adlı (achievement_seasonpass_202608 = Q14); istemcide bu sezonunki yoksa
    ondan önce başlamış en yeni sezonunki (uyarlama). Oynanan sezon (ACTIVE) varsa onunki."""
    import re
    import achievement as BS
    start = tuple(int(x) for x in ACTIVE['sid'].split('-')) if ACTIVE.get('sid') else season_start(now)
    best = None
    for aid, a in BS.ACH.items():
        m = re.match(r'achievement_seasonpass_(\d{4})(\d{2})$', aid)
        if m and (int(m.group(1)), int(m.group(2))) <= start and (best is None or m.groups() > best[0]):
            best = (m.groups(), a['group'])
    return best[1] if best else None


def day_id(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()


def week_id(now=None):
    y, w, _ = datetime.date.fromtimestamp(time.time() if now is None else now).isocalendar()
    return '%d-W%02d' % (y, w)


def level_of(points):
    total, lv = 0, 0
    for i, c in enumerate(COST):
        total += c
        if points >= total:
            lv = i
        else:
            break
    return lv


def threshold(lv):
    return sum(COST[:lv + 1])


def pool(qtype, gold):
    return sorted(q for q, m in MISSIONS.items() if m['type'] == qtype and m['gold'] == gold)


def pick(qtype, seed, counts, exclude=()):
    rng = random.Random(seed)
    out = []
    for gold, n in zip((False, True), counts):
        cands = [q for q in pool(qtype, gold) if q not in exclude]
        out += rng.sample(cands, min(n, len(cands)))
    return out


def refresh_price(n):
    """Görev yenilemenin bedeli (U): n yenileme satın alınmışken sıradaki (wiki: 1-4. 500, 5-7. 1.000, 8-10. 2.000, sonrası 4.000)."""
    for last, cost in REFRESH_LADDER:
        if last is None or n < last:
            return cost


def seasons(now=None):
    """Sezonların kimlikleri, eskiden yeniye (etkinlik_gorunumleri.SEASONS: tasarımları bilinenler); gerçek takvimde başlamış
    daha yeni sezon da (tasarımları tablodan örneklenir: EG.season_track)."""
    ids = [s['season'] for s in EG.SEASONS]
    cur = season_id(now)
    return ids + [cur] if cur > ids[-1] else ids


def next_season(played, progressive, now=None):
    """Sıradaki sezon: ilerlemelide oynanmamış ilk sezon (yoksa en yeni), değilse en yeni."""
    ids = seasons(now)
    return next((i for i in ids if i not in played), ids[-1]) if progressive else ids[-1]


def duration():
    return max(1, int(SET.get('season_duration'))) * 86400


def points_of(qid):
    return sum(r['amount'] for r in MISSIONS[qid]['definition']['rewards'] if r['lootId'] == POINT_ITEM)


class Season:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None              # mağaza (ödüller, para mesajları; oturum bağlar)
        self.send = None           # oturuma gönderme (görev ilerlemesi olaylardan gelir)
        self.map_id = None
        # yalnız aynı iş parçacığında iç içe olayı önler: dünyanın (öldürme, toplama) ve oturumun (alım, satış) aynı anda gelen
        # olayları ortak bir bayrakla birbirini düşürüyordu
        self.local = threading.local()

    # ------------------------------------------------------------ durum
    @property
    def st(self):
        return self.p.d.setdefault('season', {})

    def track(self, key):
        """Sezonun ödül sırası: kayıttakinin sezon tasarımları sezonun sırasındakilerle (etkinlik_gorunumleri.season_track)."""
        return EG.season_track(key, S['reward'][key], self.st.get('period') or seasons()[-1])

    def end(self):
        """Oynanan sezonun bitişi: başlangıcı + panelin süresi."""
        return self.st.get('start', time.time()) + duration()

    def ended(self, now):
        return bool(self.st.get('period')) and (not self.st.get('start') or now >= self.end())

    def ensure(self, now=None):
        """Sezon, gün ve hafta değiştiyse yenile -> bildirilecek mesajlar."""
        now = time.time() if now is None else now
        st, msgs = self.st, []
        if '-Q' in st.get('period', ''):             # eski biçim (takvim çeyreği): çeyreğin ilk gününün sezonu (ilerleme silinmesin)
            y, q = st['period'].split('-Q')
            with self.p.lock:
                st['period'] = season_id(datetime.datetime(int(y), int(q) * 3 - 2, 1).timestamp())
        if st.get('period') and not st.get('start'):    # takvime bağlı eski kayıt: ilerlemesi kalır, sezonu bugünden sürer
            with self.p.lock:
                st['start'] = now
                st.setdefault('played', [st['period']])
                self.p.dirty = True
        if not st.get('period') or self.ended(now):
            wait, played = [], list(st.get('played', []))
            if st.get('period'):
                ended, wait = self.close_season()
                msgs += ended
            sid = next_season(played, bool(self.p.d.get('progressive')), now)
            with self.p.lock:
                st.clear()
                st.update(period=sid, start=now, played=played + [sid], points=0, gold=False, ext=False,
                          claimed={k: [] for k, g, e in TRACKS}, value={}, done=[], seasonal=pool(SEASON, False) + pool(SEASON, True),
                          renewal={'day': 0, 'week': 0}, pending=wait)
                self.p.dirty = True
            self.log('   Season Pass sezonu başladı: %s (%s, %d gün)' % (sid, EG.season(sid)['name'], duration() // 86400))
            msgs += self.activate_items()
        ACTIVE.update(sid=st['period'], end_time=self.end())
        # havuzdan kalkmış görev kimlikleri (havuz wiki'ye göre yenilendi): liste yeniden çekilir, eski ilerleme silinir
        if any(q not in MISSIONS for q in st.get('daily', [])):
            st['day'] = None
        if any(q not in MISSIONS for q in st.get('weekly', [])):
            st['week'] = None
        if st.get('day') != day_id(now):
            self.reset_list('daily', DAILY, DAILY_N, 'day', day_id(now))
        if st.get('week') != week_id(now):
            self.reset_list('weekly', WEEKLY, WEEKLY_N, 'week', week_id(now))
        return msgs

    def reset_list(self, key, qtype, counts, stamp_key, stamp):
        st = self.st
        with self.p.lock:
            for q in st.get(key, []):
                st['value'].pop(str(q), None)
                if q in st['done']:
                    st['done'].remove(q)
            st[key] = pick(qtype, '%s|%s' % (st['period'], stamp), counts)
            st[stamp_key] = stamp
            st['renewal'][stamp_key] = 0
            self.p.dirty = True

    def missions(self):
        st = self.st
        return st.get('daily', []) + st.get('weekly', []) + st.get('seasonal', [])

    def level(self):
        return level_of(self.st.get('points', 0))

    def image(self):
        """Pencerenin görseli: oynanan sezonunki (resmî CDN'de olmayanlarda kayıttaki)."""
        return S['images'].get(self.st.get('period'), S['visual'])

    def status_code(self, qid):
        gold, done = MISSIONS[qid]['gold'], qid in self.st['done']
        if not gold:
            return 3 if done else 0
        if self.st.get('gold'):
            return 4 if done else 1
        return 5 if done else 2

    # ------------------------------------------------------------ mesajlar
    def status_cmd(self, now=None, tips=False):
        st = self.st
        return ('SeasonPassStatusCommand', dict(pointsCost=list(COST), uridiumCost=list(UCOST), goldPass=bool(st.get('gold')),
                                                showTips=tips, marketingImage=self.image(), seasonName=S['name'],
                                                extGoldPass=bool(st.get('ext')),
                                                timeToEventEnd=max(0, int(self.end() - (time.time() if now is None else now)))))

    def reward_cmd(self):
        claimed = self.st['claimed']
        rows = {}
        for key, gold, ext in TRACKS:
            rows[key] = [mod('SeasonPassRewardModule', amount=n, goldPass=gold, claimed=lv in claimed[key], level=lv, extGoldPass=ext, lootId=l)
                         for lv, l, n in self.track(key)]
        return ('SeasonPassRewardInfoCommand', dict(goldPassRewardItems=rows['gold'], freeRewardItems=rows['free'],
                                                    extGoldPassRewardItems=rows['ext']))

    def refresh_info(self):
        y = self.st['renewal']
        free_left = max(0, 1 - y.get('day', 0))
        return mod('RefreshQuestInfo', nextDailyUridium=-1 if free_left else refresh_price(self.paid_refreshes('daily')), weeklyCount=0,
                   dailyLeft=free_left, dailyCount=1, nextWeeklyUridium=refresh_price(self.paid_refreshes('weekly')), weeklyLeft=0)

    def paid_refreshes(self, key):
        """Bu gün (günlük) ya da hafta (haftalık) satın alınmış yenileme sayısı (günlüğün ilki ücretsiz)."""
        y = self.st['renewal']
        return max(0, y.get('day', 0) - 1) if key == 'daily' else y.get('week', 0)

    def mission_cmd(self):
        st = self.st
        items = [mod('SeasonPassMissionModule', missionStatus=mod('SeasonPassMissionStatusModule', type=self.status_code(q)),
                     questDefinitionModule=GT.with_state(MISSIONS[q]['definition'], st['value'].get(str(q), {}), q in st['done']))
                 for q in self.missions()]
        return ('SeasonPassMissionInfoCommand', dict(refreshInfo=self.refresh_info(), missionInfoType=0, missionItems=items))

    def points_cmd(self):
        return ('SeasonPointsInfoCommand', {'points': int(self.st.get('points', 0))})

    def login_msgs(self):
        msgs = self.ensure()
        # showTips: istemci (UIMainCenterNewSystem.InitWindows) girişte pencereyi açar, bayrağı yalnız kendinde siler. Hiç
        # kaydedilmediği için pencere her girişte açılıyordu (canlı test H56): sezonda bir kez, ipucu yeni sezonda sıfırlanır
        tips = not self.st.get('tooltip')
        if tips:
            with self.p.lock:
                self.st['tooltip'] = True
                self.p.dirty = True
        self.level_event()                                          # başarım (eski profiller: seviye zaten 50'yi geçmiş olabilir)
        return msgs + [self.status_cmd(tips=tips), self.mission_cmd(), self.points_cmd(), self.reward_cmd()] + self.unclaimed_msgs()

    def roster(self):
        return len((self.p.d.get('nova') or {}).get('roster', []))

    def roster_full(self, loot, n):
        """N.O.V.A. ödülü için kadroda yer yok mu (nova.py'nin hire'ı kadro doluyken kaptanı uridyuma çevirirdi)."""
        return loot.startswith('captain_') and self.roster() + n > NV.D['max_roster']

    def unclaimed_msgs(self):
        """Önceki sezondan bekleyen N.O.V.A.'lar varsa sezon sonu penceresi."""
        wait = sum(n for l, n in self.st.get('pending', []))
        if not wait:
            return []
        return [('SeasonPassRewardUnclaimedInfoCommand', dict(captainLimit=NV.D['max_roster'], captainPending=wait,
                                                              captainOwned=self.roster(), captainWarning=self.roster_full('captain_', wait),
                                                              spcId=0, marketingImage=self.image(), seasonName=S['name']))]

    # ------------------------------------------------------------ puan ve Gold Pass
    def add_points(self, n, bought=False):
        """Puan ekler. bought: puan paketinden; azami seviyenin üstüne taşan kısmı 1 puan = 10 Onur olur (wiki)."""
        old = self.level()
        with self.p.lock:
            total = self.st.get('points', 0) + n
            excess = min(n, max(0, total - threshold(MAX_LEVEL))) if bought else 0
            self.st['points'] = total - excess
            self.p.dirty = True
        msgs = []
        if excess:
            honor = excess * OVERFLOW_HONOR
            if self.m:
                msgs += self.m.reward('currency_honour', honor)
            else:
                self.p.gain(honor=honor)
            self.log('   Season Pass puanı azami seviyeyi aştı: %d puan -> %d Onur' % (excess, honor))
        if self.level() > old:
            self.log('   Season Pass seviyesi %d (%d puan)' % (self.level(), self.st['points']))
            self.level_event()
            return msgs + [self.points_cmd(), self.reward_cmd()]       # ızgara yalnız ödül listesiyle açılır (canlı test H44)
        return msgs + [self.points_cmd()]

    def level_event(self):
        """Başarım: Gold Season Pass'in seviyesi (LevelAbsolute; Gold Pass yoksa 0)."""
        self.p.ach('season_level', value=self.level() if self.st.get('gold') else 0, group=achievement_group())

    def activate_items(self):
        """Depodaki Gold / Extra Gold Pass bu sezona (Extra yalnız Gold'dan sonra) -> mesajlar."""
        msgs = []
        st = self.st
        if not st.get('gold') and self.p.resource(GOLD_ITEM) > 0:
            self.p.add_resource(GOLD_ITEM, -1)
            with self.p.lock:
                st['gold'] = True
                self.p.dirty = True
            pend = [q for q in self.missions() if MISSIONS[q]['gold'] and q in st['done']]
            for q in pend:                                          # Gold Pass'ten önce biten Gold görevlerinin puanı
                msgs += self.add_points(points_of(q))
            self.log('   Gold Pass etkin (%s)%s' % (st['period'], ', %d görevin puanı' % len(pend) if pend else ''))
            self.level_event()                                      # Gold Pass'ten önce ulaşılan seviye de sayılır
        if st.get('gold') and not st.get('ext') and self.p.resource(EXT_ITEM) > 0:
            self.p.add_resource(EXT_ITEM, -1)
            with self.p.lock:
                st['ext'] = True
                self.p.dirty = True
            self.log('   Extra Gold Pass etkin (%s)' % st['period'])
        return msgs

    def grant(self, loot, n):
        """Mağaza ödülü: Season Pass puanı ya da Gold/Extra Gold Pass -> mesajlar."""
        self.ensure()
        if loot == POINT_ITEM:
            return self.add_points(n, bought=True)
        self.p.add_resource(loot, n)
        msgs = self.activate_items()
        return msgs + [self.status_cmd(), self.mission_cmd(), self.reward_cmd(), self.points_cmd()]

    # ------------------------------------------------------------ görevler
    def event(self, kind, **kw):
        """Oyun olayı -> görev ilerlemesi (oturuma gönderilir)."""
        if getattr(self.local, 'busy', False) or not self.p.d.get('season'):
            return []
        self.local.busy = True
        try:
            msgs = self._event(kind, kw)
        finally:
            self.local.busy = False
        if msgs and self.send:
            self.send(msgs)
        return msgs

    def _event(self, kind, kw):
        msgs, done = [], []
        st = self.st
        for q in self.missions():
            if q in st['done']:
                continue
            vals = st['value'].setdefault(str(q), {})
            m, fin = GT.advance(self.p, MISSIONS[q]['definition']['rootCase'], vals, kind, kw, self.map_id)
            msgs += m
            if fin:
                done.append(q)
        for q in done:
            msgs += self.complete(q)
        for q in done:                                              # sezon görevleri: N günlük/haftalık bitir
            msgs += self._event('sp_quest', dict(category=GT.SP_CATEGORY[MISSIONS[q]['type']]))
        return msgs

    def complete(self, qid):
        st = self.st
        with self.p.lock:
            if qid not in st['done']:
                st['done'].append(qid)
            self.p.dirty = True
        qt = MISSIONS[qid]['type']
        msgs = [legacy('0|A|STM|%s' % DONE_TEXT[qt]), ('QuestCompletedCommand', {'id': qid, 'rating': 0})]
        locked = MISSIONS[qid]['gold'] and not st.get('gold')
        if not locked:
            bonus = self.p.mods().get('season_points', 0)                     # N.O.V.A. Bonus Hunter / Bonus Slayer (nova.py)
            msgs += self.add_points(int(round(points_of(qid) * (1 + bonus) * SET.multiplier('season_points'))))      # panel
        if qt == DAILY and self.m:                                          # günlük görev: Armory Token (Aşama 9; armory.py)
            import armory as AU
            msgs += self.m.reward(AU.TOKEN, AU.D['daily_quest_token'])
        self.p.ach('quest', id=qid)                                  # kayıt: Season Pass görevi başarımlarda sayılır
        self.log('   Season Pass görevi bitti: %d (%s, %d puan%s)' % (qid, {DAILY: 'günlük', WEEKLY: 'haftalık', SEASON: 'season'}[qt],
                                                                     points_of(qid), ', Gold Pass bekliyor' if locked else ''))
        return msgs

    # ------------------------------------------------------------ istekler
    def claimable(self, key, lv):
        st = self.st
        if lv > self.level() or lv in st['claimed'][key]:
            return None
        if key == 'gold' and not st.get('gold') or key == 'ext' and not st.get('ext'):
            return None
        return next(((l, n) for rlv, l, n in self.track(key) if rlv == lv), None)

    def give(self, key, lv):
        got = self.claimable(key, lv)
        if not got:
            return None
        with self.p.lock:
            self.st['claimed'][key].append(lv)
            self.p.dirty = True
        l, n = got
        self.log('   Season Pass ödülü: seviye %d %s: %s x%d' % (lv, key, l, n))
        return self.m.reward(l, n) if self.m else []

    def claim(self, f):
        self.ensure()
        lv = int(f.get('level') or 0)
        key = 'ext' if f.get('extGoldPass') else 'gold' if f.get('goldPass') else 'free'
        got = self.claimable(key, lv)
        if got and self.roster_full(*got):
            return [('SeasonPassCaptainLimitCommand', {})]
        msgs = self.give(key, lv)
        if msgs is None:
            return [legacy('0|A|STM|sp_error_no-claimable-rewards')]
        return msgs + [('SeasonPassRewardClaimCommand', dict(extGoldPass=key == 'ext', goldPass=key == 'gold', claimed=True, level=lv))]

    def claim_all(self, f=None):
        """Claim All ya da sezon sonu penceresinin düğmesi (spcId): önce önceki sezondan bekleyen N.O.V.A.'lar."""
        self.ensure()
        msgs, n, full = [], 0, False
        for row in list(self.st.get('pending', [])):
            if self.roster_full(*row):
                full = True
                continue
            with self.p.lock:
                self.st['pending'].remove(row)
                self.p.dirty = True
            msgs += self.m.reward(*row) if self.m else []
            n += 1
        for key, gold, ext in TRACKS:
            for lv, l, a in self.track(key):
                got = self.claimable(key, lv)
                if got and self.roster_full(*got):
                    full = True
                    continue
                got = self.give(key, lv)
                if got is not None:
                    n += 1
                    msgs += got + [('SeasonPassRewardClaimCommand', dict(extGoldPass=ext, goldPass=gold, claimed=True, level=lv))]
        if full:
            msgs.append(('SeasonPassCaptainLimitCommand', {}))
        if not n:
            return msgs or [legacy('0|A|STM|sp_error_no-claimable-rewards')]
        return msgs + [self.reward_cmd()]

    def buy_levels(self, f):
        self.ensure()
        cur = self.level()
        n = max(0, min(int(f.get('amount') or 0), MAX_LEVEL - cur))
        cost = sum(UCOST[cur + 1:cur + 1 + n])
        pl = self.p.d['pilot']
        if not n or pl.get('uridium', 0) < cost:
            self.log('   Season Pass seviyesi alınamadı: %d seviye, %d U' % (n, cost))
            return [('SeasonPassLevelPurchaseCommand', {'success': False})]
        tot = self.p.gain(uridium=-cost, reason='buy_SPECIAL', detail='season_pass_level')
        with self.p.lock:
            self.st['points'] = max(self.st.get('points', 0), threshold(cur + n))
            self.p.dirty = True
        self.log('   Season Pass: %d seviye alındı (%d U) -> %d' % (n, cost, self.level()))
        self.level_event()
        return ([('SeasonPassLevelPurchaseCommand', {'success': True}), self.points_cmd(), self.reward_cmd()]     # ızgara (H44)
                + (self.m.money_msgs() if self.m else []))

    def refresh(self, f):
        """SeasonPassRefreshRequest: günlük/haftalık görevin yerine havuzdan başkası (bitmiş görev yenilenmez)."""
        self.ensure()
        st, qid = self.st, int(f.get('questId') or 0)
        key = 'daily' if qid in st.get('daily', []) else 'weekly' if qid in st.get('weekly', []) else None
        if not key or qid in st['done']:
            return [self.mission_cmd()]
        stamp = 'day' if key == 'daily' else 'week'
        free = key == 'daily' and st['renewal'].get('day', 0) < 1
        cost = 0 if free else refresh_price(self.paid_refreshes(key))
        qt, gold = MISSIONS[qid]['type'], MISSIONS[qid]['gold']
        cands = [q for q in pool(qt, gold) if q not in st[key]]
        if not cands:                                              # değişecek görev yok: bedel alınmaz
            return [self.mission_cmd()]
        if cost:
            if self.p.d['pilot'].get('uridium', 0) < cost:
                return [legacy('0|A|STM|not_enough_uridium'), self.mission_cmd()]
            self.p.gain(uridium=-cost, reason='buy_SPECIAL', detail='season_pass_refresh')
        new = random.choice(cands)
        with self.p.lock:
            st[key][st[key].index(qid)] = new
            st['value'].pop(str(qid), None)
            st['renewal'][stamp] = st['renewal'].get(stamp, 0) + 1
            self.p.dirty = True
        self.log('   Season Pass görevi yenilendi: %d -> %d%s' % (qid, new, '' if free else ' (%d U)' % cost))
        return [self.mission_cmd()] + ([] if free or not self.m else self.m.money_msgs())

    def close_season(self):
        """Sezon bitti: ulaşılan seviyelerin alınmamış ödülleri verilir; N.O.V.A.'lar bekler -> (mesajlar, bekleyenler)."""
        msgs, n, wait = [], 0, []
        for key, gold, ext in TRACKS:
            for lv, l, a in self.track(key):
                got = self.claimable(key, lv)
                if got and got[0].startswith('captain_'):
                    wait.append(list(got))
                    continue
                got = self.give(key, lv)
                if got is not None:
                    msgs += got
                    n += 1
        self.log('   Season Pass sezonu bitti (%s): %d ödül verildi, %d N.O.V.A. bekliyor' % (self.st.get('period'), n, len(wait)))
        return msgs + [legacy('0|A|STM|sp_season-has-ended_description')], wait

    def handle(self, name, f):
        fn = {'SeasonPassRewardClaimRequest': self.claim, 'SeasonPassRewardClaimAllRequest': self.claim_all,
              'SeasonPassLevelPurchaseRequest': self.buy_levels, 'SeasonPassRefreshRequest': self.refresh}.get(name)
        return fn(f) if fn else None

    def tick(self, now):
        if self.p.d.get('season') and (self.st.get('day') != day_id(now) or self.ended(now)):
            ended = self.ended(now)
            msgs = self.ensure(now) + [self.status_cmd(now), self.mission_cmd(), self.points_cmd(), self.reward_cmd()]
            msgs += self.unclaimed_msgs() if ended else []
            if self.send:
                self.send(msgs)
