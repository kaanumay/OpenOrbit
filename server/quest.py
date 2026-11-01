"""Görevler: görev listesi, bilgi, kabul/iptal, ilerleme ve ödüller (kayıttaki akışlar). Veri: data/quests.json (tools/quests.py).

Kayıttaki akışlar:
  görev vericiye yaklaşınca  QuestGiversAvailableCommand(görev verici) + QuestListCommand; uzaklaşınca boş liste
  QuestInfoRequest           -> QuestInfoCommand(tanım, puanlar)
  QuestAcceptRequest         -> QuestInitializationCommand(tanım, koşul durumları) + QuestListCommand
  ilerleme                   -> QuestConditionUpdateCommand(koşul, değer/etkin/tamam); hedefe ulaşınca önce değer, sonra tamam
                                ve sıradaki koşul etkin. "Görev vericiye dön" etkinleşince mini haritada işaret (CreateMinimapMark)
  QuestGiverApproachedRequest -> dönüş koşulu + QuestCompletedCommand + RemoveMinimapMark + ödüller + QuestListCommand
  QuestCancelRequest         -> RemoveMinimapMark + QuestCancelledCommand + QuestListCommand
Süre sınırlı görev ("sure_sn"; tanımda HASTE koşulu, değeri geçen ms): süre dolarsa ya da kısıtı bozulursa ("basarisiz": ölüm, bir
firmanın oyuncusunu vurmak) QuestFailedCommand {id} (istemci "q2_failed_quest" iletisiyle görevi kaldırır) + QuestListCommand; görev
yeniden alınabilir. Süre gerçek zamanla (oyundan çıkınca da) işler.
Liste durumları (istemcinin AcceptabilityType'ı): 0 kabul edilemez (eksik seviye/önceki görev), 1 alınabilir, 2 sürüyor, 3 tamamlandı.
Görev sınırı: listenin maxQuests'i toplam değil boş slot sayısıdır (kayıt: görev yokken 5, biri sürerken 4). İstemci onu
QuestComponent.MaxAcceptedQuests'te tutar, penceresinde "n görev slotu boş" (label_questslots_free_s) olarak gösterir ve 0 olunca
kabulü kapatır (QuestComponentSystem.IsQuestSlotLimitReached). Sınır panelin 'en_cok_gorev' ayarı (oyunun değeri MAX_QUESTS).
Pencerenin sekmeleri (QuestType; E6, data/quest_extras.json): 3 günlük ve 6 haftalık görevler zorluk başına biri (günlük her gün, haftalık
pazartesi değişir; dönemi geçen sürüyorsa başarısız), 5 etkinlik görevleri ayrı yuvada (maxEventQuests, boş yuva), 4 meydan okumalar
sıralamasız: tekrar alınır, puan bitirme süresi (sn), kişisel en iyisi görev bilgisinde. Koşulların ölçümü Pass görevleriyle ortak
(gorev_takip.measure); burada yalnız ana görevlere özgü türler ve oyuncunun firmasına göre çözülen konumlar. Kısıtlar ("basarisiz"):
ölüm, bir firmanın oyuncusunu vurmak, hasar sınırı (AVOID_DAMAGE gösterimi), yasak uzaylıyı öldürmek, yasak cephane (cins: 1 lazer,
2 roket, 3 mayın, 0 hepsi; SAVE_AMMUNITION gösterimi). Puan görevi ("puan": hedefsiz öldürme koşullarının kimlikleri; "mümkün olduğunca
çok"): bitirme puanı öldürme sayısıdır, en iyisi en çoğu. Firmaya özgü meydan okuma ("firma"): yalnız o firmanın pilotuna görünür.
Seviye havuzlu günlükler ("havuz": {"seviye": 3 | 10 | 15 | 17}; darkorbitwiki Daily Missions): her havuzdan günün rastgele biri
(tarih ve seviyeden türeyen sabit seçim), kabulden 24 saat sonra sona erer (REAL_TIME_HASTE: istemci kalan süreyi kendisi sayar; süre dolunca
başarısız). Zorluk havuzlarında (Tetrathrin günlük, Kyhalon haftalık) aynı anda yalnız biri sürebilir (istemcinin
EXCLUSIVE_POOL_QUEST_RUNNING koşulu: öbürleri kabul edilemez). Elit görevler ("gizli": önkoşulu bitmeden listede görünmez; kayıtta da yok).
Özel görevler (etkinlik görevleri, "etkinlik": takvim anahtarları): yalnız etkinlik açıkken listelenir, etkinlik bitince sürüyorsa başarısız
olur; "tekrar": günde bir (gunluk) ya da etkinlik başına bir (etkinlik) kez; "unvan": bitince başarım unvanı.
Profilde: gorevler.aktif {görev: {koşul: değer}}, gorevler.tamam [görev], gorevler.donem {günlük/haftalık/tekrarlanan görev: bittiği dönem},
gorevler.skor {meydan okuma: en iyi süre (puan görevinde puan)}.
"""
import copy, datetime, json, math, os, random, time
import game_data as GD
import ranks as RT
import booster as BOOSTER
import settings as SET
import event_calendar as CAL

import map_links as H
import galaxy_gates as KAPI

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = GD.load('quests.json')
QUESTS = {int(k): v for k, v in DATA['quests'].items()}
MAX_QUESTS = DATA.get('max_quests', 5)      # oyunun sınırı (kayıttaki en büyük maxQuests); oyunda panel ayarı geçerli
EX = GD.load('quest_extras.json')       # E6 (tools/gorev_ekleri.py)
QUESTS.update({int(k): v for k, v in EX['quests'].items()})
MAX_EVENT_QUESTS = EX['max_event_quests']
POOLS = {}                                    # ('gunluk' | 'haftalik', zorluk) -> görevler
LEVEL_POOLS = {}                              # seviye (3 | 10 | 15 | 17) -> günlük görevler (her gün birini sunar)
for _q, _v in sorted(QUESTS.items()):
    if _v.get('pool'):
        if 'seviye' in _v['pool']:
            LEVEL_POOLS.setdefault(_v['pool']['seviye'], []).append(_q)
        else:
            POOLS.setdefault((_v['pool']['tur'], _v['pool']['difficulty']), []).append(_q)
EVENT_QUEST = 5                               # QuestType: 3 günlük, 4 meydan okuma, 5 etkinlik, 6 haftalık

KILL_NPC, CARGO, COLLECT_BONUS_BOX, COLLECT_LOOT, SELL_ORE, VISIT_MAP, VISIT_QUEST_GIVER, ON_MAP = 6, 51, 55, 67, 52, 34, 62, 77
KILL_PLAYERS = 28            # PvP görevleri: olay "kill_player" (ileride bot oyuncular gönderecek)
# Ö1: eşyayı çubuğa koy (olay slot_bar: {(çubuk, öğe)}; eşleşme [çubuk, öğe] ya da [çubuk, yuva, öğe]), istasyon nesnesine git
# (olay asset: nesne türü; eşleşme [tür], 48 hangar …), Skylab modülünü seviyeye yükselt (olay skylab: modül, seviye; eşleşme
# [modül], hedef seviye). İstemcinin koşul sınıfları: PutItemInSlotBarCondition, VisitMapAssetCondition, UpdateSkylabToLevelCondition
PUT_ITEM_IN_SLOT_BAR, VISIT_MAP_ASSET, UPDATE_SKYLAB_TO_LEVEL = 70, 75, 76
HASTE = 2                    # süre sınırı gösterimi (istemci: HasteCondition, zaman biçiminde)
REAL_TIME_HASTE = 63         # gerçek zamanlı süre (istemci: RealTimeHasteCondition; değer kalan ms, istemci saniyede bir düşürür)
AVOID_DAMAGE = 8             # hasar sınırı gösterimi (değeri alınan hasar; sınıra varınca görev başarısız)
# Haritada kalma (ENDURANCE, hedef ms) saniyede bir konum olayıyla ('pos', dunya.ach_tick; kayıtlı süre: ms) ilerler. DAMAGE
# ("tüm hasar kaydedilir", hedefsiz gösterim) alınan hasarı sayar. VISIT_MAP'in COORDINATES alt koşulu (eşleşme [x*100, y*100,
# yarıçap], istemci: CoordinatesCondition) haritada o noktanın yarıçapına girince biter. MISCELLANEOUS alt koşulunun kimliği
# (istemci: GameDefineSystem.InitMiscellaneousConditionTypes) -> (oturum durumu, beklenen değer): 3 görünür, 4 gizli, 5 radyasyon
# bölgesinde, 7 canı onda birin altında (durumu oturum verir: Gorevler.state).
ENDURANCE, DAMAGE, COORDINATES, MISCELLANEOUS = 3, 7, 11, 19
MISC_STATE = {3: ('hidden', False), 4: ('hidden', True), 5: ('radiation', True), 7: ('az_can', True)}
START = '_bas'               # etkin görevin değerlerinde başlangıç zamanı (süreli görevler ve meydan okumalar)
PERIOD = '_donem'            # günlük/haftalık görevin alındığı dönem
ACCEPT = '_accept'             # havuzlu görevin kabul anı (haftalık GG cevher görevinin 14 günü)
NOT_ACCEPTABLE, NOT_STARTED, RUNNING, COMPLETED = 0, 1, 2, 3
REQ_LEVEL, REQ_PRE_QUEST, REQ_EXCLUSIVE_POOL = 0, 3, 6      # QuestRequirementType (6: EXCLUSIVE_POOL_QUEST_RUNNING)
MARK_GIVER, MARK_TRADE = 1, 2            # işaret kimliği quest_<görev>_<n> (kayıt: dönüşte 1)
CAMPAIGN_SEC = 30 * 86400                 # başlangıç kampanyası ("Level N" 502001-502006; yeni sunucu açılışında ~1 ay): profilin
                                          # 'kampanya'sından (yeni kayıtta seçilince açılış anı) bu süre görünür


def mod(name, **f):
    f['_'] = name
    return f


def conditions(case):
    """Ağaçtaki koşullar (kimliği olanlar)."""
    for el in case['modifier']:
        c = el['condition']
        if c['id']:
            yield c
        if el['questCase']['id'] or el['questCase']['modifier']:
            yield from conditions(el['questCase'])


def cap(c, v):
    """Koşul değeri hedefle sınırlı; hedefsiz (0) puan koşulunda ("mümkün olduğunca çok öldür") sınırsız."""
    return min(v, c['targetValue']) if c['targetValue'] else v


def evaluate(case, values, enabled=True, out=None):
    """Koşul durumları {koşul: (etkin, tamam)} ve durumun tamamlanıp tamamlanmadığı. Sıralı durumda tamamlanmamış ilk öğeden
    sonrakiler etkin değil ve hepsi gerekir; sırasızda hepsi etkin, mandatoryCount kadarı yeter. Zorunlu olmayan koşullar (süre,
    ölmeden, hasar sınırı, cephane kısıtı, puan gösterimi) hiç tamamlanmaz ve sayılmaz."""
    out = {} if out is None else out
    done, gate = 0, enabled
    for el in case['modifier']:
        c = el['condition']
        if c['id']:
            comp = c['mandatory'] and values.get(str(c['id']), 0) >= c['targetValue']
            out[c['id']] = (gate and not comp, comp)
        else:
            comp = evaluate(el['questCase'], values, gate, out)[1]
        done += comp
        if not comp and case['ordered']:
            gate = False
    need = len(case['modifier']) if case['ordered'] else (case['mandatoryCount'] or len(case['modifier']))
    return out, done >= need


def maps_for(spec, faction):
    """"own X-3" / "enemy X-5" / "any enemy map" / "4-5" / "Epsilon Gate" / "LoW" -> harita kimlikleri (oyuncunun firmasına göre;
    kapı: kapının haritaları, gates.json)."""
    ids = {v: k for k, v in H.NAMES.items()}
    if spec.endswith(' Gate') and spec.split()[0].lower() in KAPI.KAPI:
        return list(KAPI.KAPI[spec.split()[0].lower()]['haritalar'])
    import event_gate as EKP
    g = next((g for g in EKP.GATES.values() if g.get('ad') == spec), None)       # etkinlik kapısı adıyla (Quarantine Zone: Epidemi 512263)
    if g:
        return list(g['haritalar'])
    if spec.endswith(' X-BL'):                           # Blacklight: BL-n n. firmanın (harita.company)
        facs = {'own': [faction], 'enemy': [f for f in (1, 2, 3) if f != faction], 'any': [1, 2, 3]}[spec.split()[0]]
        names = ['BL-%d' % f for f in facs]
    elif len(spec) == 3 and spec[0] in '1235' and spec[1:] == '-X':     # "1-X": firmanın bütün haritaları, "5-X": 5-1..5-4
        names = ['%s-%d' % (spec[0], n) for n in range(1, 9)]
    elif spec == 'own 4-2':                              # firmanın PvP haritası (4-1 MMO, 4-2 EIC, 4-3 VRU; wiki "your 4-2 map")
        names = ['4-%d' % faction]
    elif spec.startswith('own X-'):
        names = ['%d-%s' % (faction, spec[6:])]
    elif spec.startswith('enemy X-'):
        names = ['%d-%s' % (f, spec[8:]) for f in (1, 2, 3) if f != faction]
    elif spec.startswith('any X-'):                     # herhangi firmanın X-n'i (resmî forum 149871: 111006)
        names = ['%d-%s' % (f, spec[6:]) for f in (1, 2, 3)]
    elif spec == 'any enemy map':
        names = ['%d-%d' % (f, n) for f in (1, 2, 3) if f != faction for n in range(1, 9)]
    else:
        names = [spec]
    return [ids[n] for n in names if n in ids]


def period_key(qid, now=None):
    """Günlük görevin günü ya da haftalık görevin haftası (yerel saat; hafta pazartesi başlar). Zorluk havuzlu GG cevher görevleri
    06:30'da (haftalık pazartesi 06:30) yenilenir (resmî forum 129125)."""
    t = time.time() if now is None else now
    if 'difficulty' in QUESTS[qid]['pool']:
        t -= 6.5 * 3600
    d = datetime.date.fromtimestamp(t)
    return d.isoformat() if QUESTS[qid]['pool']['tur'] == 'daily' else '%d-W%02d' % d.isocalendar()[:2]


def offered(now=None):
    """Bugünün günlük ve bu haftanın haftalık görevleri: zorluk başına biri, kayıttaki günün seçiminden sırayla ilerler; seviye
    havuzlarından (3, 10, 15, 17) her gün rastgele biri (tarih ve seviyeden türeyen sabit seçim: gün içinde ve yeniden açılışta aynı)."""
    t = time.time() if now is None else now
    d = datetime.date.fromtimestamp(t)
    dz = datetime.date.fromtimestamp(t - 6.5 * 3600)    # zorluk havuzları 06:30'da döner (period_key ile aynı; yoksa 00:00-06:30 arası tekrar alınıyordu)
    out = set()
    for kind in ('daily', 'weekly'):
        d0 = datetime.date.fromisoformat(EX[kind]['tarih'])
        steps = (dz - d0).days if kind == 'daily' else ((dz - d0).days + d0.weekday() - dz.weekday()) // 7
        for first in EX[kind]['selected']:
            pool = POOLS[(kind, QUESTS[first]['pool']['difficulty'])]
            out.add(pool[(pool.index(first) + steps) % len(pool)])
    for level, pool in LEVEL_POOLS.items():
        out.add(random.Random('%s:%d' % (d.isoformat(), level)).choice(pool))
    return out


def event_open(q, now=None):
    """Özel görevin etkinliği açık mı ("etkinlik": takvim anahtarlarından biri etkin); etkinlik alanı olmayan görev hep açık."""
    return not q.get('etkinlik') or any(CAL.is_active(k, now) for k in q['etkinlik'])


def repeat_key(qid, now=None):
    """Tekrarlanan özel görevin dönemi: "gunluk" günün tarihi; "etkinlik" etkinliğin o anki döneminin başı (panelden zorla
    açılmış ya da dönemi olmayan etkinlikte "zorla")."""
    q = QUESTS[qid]
    if q.get('tekrar') == 'daily':
        return datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()
    for k in q.get('etkinlik', []):
        if k in CAL.EVENTS and CAL.is_active(k, now):
            p = CAL.period(k, now)
            return str(int(p[0])) if p else 'force'
    return 'force'


import quest_tracker as GT         # noqa: E402  (gorev_takip bu modülün conditions/evaluate/mod'unu kullanır: onlardan sonra)


class Quests:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.map_id = None
        self.giver = None          # bu haritadaki görev verici (kimlik, x, y)
        self.trade = None          # bu haritadaki rafineri (x, y)
        self.grant = None          # (lootId, adet) -> ödül mesajları (oturum: mağaza ve dünya)
        self.marks = {}            # görev -> gösterilen işaretler
        self.send = None           # zamanlayıcının iletileri (oturum bağlar)
        self.state = dict          # MISCELLANEOUS alt koşulları için anlık durum {gizli, radyasyon, az_can} (oturum bağlar)
        self.next_tick = 0.0
        self.offer = None          # son listedeki günlük/haftalık görevler (değişince liste yenilenir)

    @property
    def st(self):
        return self.p.d['quests']

    def faction(self):
        return self.p.d['pilot'].get('factionId', 2)

    def resolve(self, matches):
        return [str(m) for x in matches for m in (maps_for(x[1:], self.faction()) if str(x).startswith('@') else [x])]

    # ------------------------------------------------------------ durum ve liste
    def values(self, qid):
        return self.st['active'].get(str(qid), {})

    def visible(self, qid, offer):
        """Listede mi: günlük/haftalık yalnız dönemin görevi (ya da sürüyorsa), kendi firmasının "Steal … resources"ı yok, firmaya
        özgü meydan okuma ("firma": 17 / 186 / 187 …) yalnız o firmanın pilotuna."""
        q = QUESTS[qid]
        if q.get('off') and str(qid) not in self.st['active']:
            return False                                    # Dünya Editörü'nde kapatılan görev (sürüyorsa bitirilebilir)
        if q.get('kampanya') and str(qid) not in self.st['active'] and not SET.get('kampanya') and time.time() >=self.p.d.get('kampanya', -CAMPAIGN_SEC) + CAMPAIGN_SEC:
            return False                                    # başlangıç kampanyası: yeni kayıtta seçildiyse ilk ay (sürüyorsa bitirilebilir)
        if q.get('pool') and qid not in offer and str(qid) not in self.st['active']:
            return False
        if str(qid) not in self.st['active'] and ((q.get('etkinlik') and not event_open(q))
                                                  or (q.get('hidden') and not all(self.done(x) for x in q['previous']))):
            return False                                    # etkinlik kapalı ya da elit görevin kilidi (Silent Sabotage) açılmadı
        return q.get('company_excluded') != self.faction() and q.get('firma', self.faction()) == self.faction()

    def done(self, qid):
        """Görev bitti mi: bir kez alınanlar tamamlananlarda, günlük/haftalık/tekrarlanan özel görevler bu dönem için dönemde."""
        q = QUESTS.get(qid)
        if qid in self.st['tamam']:
            return True
        key = period_key(qid) if q and q.get('pool') else repeat_key(qid) if q and q.get('tekrar') else None
        return key is not None and self.st.get('donem', {}).get(str(qid)) == key

    def exclusive_running(self, qid):
        """Zorluk havuzunda (Tetrathrin günlük, Kyhalon haftalık) başka bir görev sürüyor mu: havuzda aynı anda yalnız biri sürer."""
        h = QUESTS[qid].get('pool') or {}
        return 'difficulty' in h and any(
            int(a) != qid and int(a) in QUESTS and 'difficulty' in (QUESTS[int(a)].get('pool') or {})
            and QUESTS[int(a)]['pool']['tur'] == h['tur'] for a in self.st['active'])

    def portrait(self, q):
        """Görev vericinin portresi; seviye 3 günlükler oyuncunun firma lideri ("portre_firma")."""
        return q.get('portrait_company', {}).get(str(self.faction()), q.get('portrait', ''))

    def status(self, qid):
        """-> (durum, eksik koşullar)."""
        q = QUESTS[qid]
        if self.done(qid):
            return COMPLETED, []
        if str(qid) in self.st['active']:
            return RUNNING, []
        miss = []
        if self.p.d['pilot'].get('level', 1) < q['seviye']:
            miss.append(mod('QuestRequirementModule', requirementType=REQ_LEVEL, minValue=q['seviye'], maxValue=0, matches=[], missingMatches=[]))
        if self.exclusive_running(qid):
            miss.append(mod('QuestRequirementModule', requirementType=REQ_EXCLUSIVE_POOL, minValue=0, maxValue=0, matches=[], missingMatches=[]))
        pre = [x for x in q['previous'] if x in QUESTS and not self.done(x)]       # oynanamayan önceki görev engel olmaz
        if pre:
            miss.append(mod('QuestRequirementModule', requirementType=REQ_PRE_QUEST, minValue=0, maxValue=len(pre), matches=[],
                            missingMatches=[mod('QuestLocalizationModule', questId=x, textKeyFoundation='') for x in pre]))
        return (NOT_ACCEPTABLE if miss else NOT_STARTED), miss

    def slim(self, qid):
        q = QUESTS[qid]
        s, miss = self.status(qid)
        return mod('QuestSlimInfoModule', questId=qid, rootCaseId=q['root']['id'], minLevel=q['seviye'], priority=q['priority'],
                   types=[mod('QuestTypeModule', type=t) for t in q['kinds']], icon=mod('QuestIconModule', icon=q['icon']),
                   acceptabilityStatus=mod('QuestAcceptabilityStatusModule', type=s), missingAcceptRequirements=miss,
                   textKeyFoundation='', portraitId=self.portrait(q), star=0)

    def running(self, event=False):
        """Slot tutan görevler (oynanabilen etkin görevler); event: etkinlik görevlerinin ayrı yuvası."""
        return sum(1 for q in self.st['active'] if int(q) in QUESTS and (EVENT_QUEST in QUESTS[int(q)]['kinds']) == event)

    def free_slots(self, event=False):
        return max(0, (MAX_EVENT_QUESTS if event else SET.get('max_quests')) - self.running(event))

    def list_cmd(self):
        self.offer = offered()
        return ('QuestListCommand', {'list': [self.slim(q) for q in sorted(QUESTS) if self.visible(q, self.offer)], 'onlyStarter': False,
                                     'maxQuests': self.free_slots(), 'maxEventQuests': self.free_slots(True)})

    def definition(self, qid):
        q = QUESTS[qid]
        root = copy.deepcopy(q['root'])
        vals = self.values(qid)
        flags = evaluate(root, vals)[0]
        for c in conditions(root):
            active, comp = flags[c['id']]
            c['state'].update(currentValue=cap(c, vals.get(str(c['id']), 0)), active=active, completed=comp)
            if c['type'] == HASTE:
                c['state']['currentValue'] = self.elapsed_ms(qid, c['targetValue'])
            elif c['type'] == REAL_TIME_HASTE:                  # kalan süre (ms); istemci saniyede bir düşürür
                c['state']['currentValue'] = c['targetValue'] - self.elapsed_ms(qid, c['targetValue'])
            c['matches'] = self.resolve(c['matches'])
            for s in c['subConditions']:
                s['matches'] = self.resolve(s['matches'])
        return mod('QuestDefinitionModule', id=qid, types=[mod('QuestTypeModule', type=t) for t in q['kinds']], rootCase=root,
                   rewards=[mod('LootModule', lootId=l, amount=n, modifier='') for l, n in q['rewards']],
                   icons=[mod('QuestIconModule', icon=q['icon'])], textKeyFoundation='', portraitId=self.portrait(q), star=0)

    def info(self, qid):
        """Görev bilgisi; meydan okumada oyuncunun en iyi süresi (sıralamasız: tek satır, birinci)."""
        if qid not in QUESTS:
            return []
        best = self.st.get('score', {}).get(str(qid))
        me = {'_': 'QuestChallengeRatingModule', 'name': self.p.d['pilot'].get('userName', '') if best is not None else '',
              'epppLink': '', 'rank': 1 if best is not None else 0, 'rating': best or 0, 'diffToFirst': 0}
        return [('QuestInfoCommand', {'definition': self.definition(qid), 'ratings': [me] if best is not None else [],
                                      'playersRating': me})]

    def login_msgs(self):
        """Girişte ve harita değişiminde: etkin görevler, liste ve bu haritadaki işaretler."""
        self.marks = {}
        msgs = [('QuestInitializationCommand', {'quest': self.definition(int(q))}) for q in self.st['active'] if int(q) in QUESTS]
        msgs.append(self.list_cmd())
        for q in self.st['active']:
            if int(q) in QUESTS:
                msgs += self.mark_msgs(int(q))
        return msgs

    # ------------------------------------------------------------ işaretler
    def mark_msgs(self, qid):
        """Etkin "görev vericiye dön" / "maden sat" koşulu için mini harita işareti (kayıt: görev vericinin konumu, yanıp söner)."""
        flags = evaluate(QUESTS[qid]['root'], self.values(qid))[0]
        want = set()
        for c in conditions(QUESTS[qid]['root']):
            if flags[c['id']][0]:
                if c['type'] == VISIT_QUEST_GIVER and self.giver:
                    want.add(MARK_GIVER)
                elif c['type'] == SELL_ORE and self.trade:
                    want.add(MARK_TRADE)
        have = self.marks.setdefault(qid, set())
        msgs = []
        for n in sorted(want - have):
            x, y = self.giver[1:] if n == MARK_GIVER else self.trade
            msgs.append(('CreateMinimapMark', dict(count=-1, scale=1.0, uid='quest_%d_%d' % (qid, n), positionX=x, positionY=y, interval=0.5,
                                                   inverse=False, soundModule=mod('SoundTriggerModule', playSound=True, soundId=132), type=0)))
        for n in sorted(have - want):
            msgs.append(('RemoveMinimapMark', {'uid': 'quest_%d_%d' % (qid, n)}))
        self.marks[qid] = want
        return msgs

    # ------------------------------------------------------------ istekler
    def accept(self, qid):
        q = QUESTS.get(qid)
        s = self.status(qid)[0] if q else None
        event = bool(q) and EVENT_QUEST in q['kinds']
        if s != NOT_STARTED or not self.free_slots(event) or not self.visible(qid, offered()):
            self.log('   görev alınamadı: %s (durum %s, etkin %d/%d)' % (qid, s, self.running(event), SET.get('max_quests')))
            return [self.list_cmd()]
        if q.get('pool') and 'difficulty' in q['pool'] and any(
                'difficulty' in (QUESTS.get(int(a), {}).get('pool') or {}) and QUESTS[int(a)]['pool']['tur'] == q['pool']['tur']
                for a in self.st['active']):
            self.log('   görev alınamadı: %s (aynı anda tek %s cevher görevi)' % (qid, q['pool']['tur']))    # forum 129125
            return [self.list_cmd()]
        vals = {START: time.time()} if q.get('sure_sn') or q.get('challenge') else {}
        if q.get('pool'):
            vals[PERIOD] = period_key(qid)
            vals[ACCEPT] = time.time()
        elif q.get('tekrar'):
            vals[PERIOD] = repeat_key(qid)
        with self.p.lock:
            self.st['active'][str(qid)] = vals
            self.p.dirty = True
        self.log('   görev alındı: %d %s%s' % (qid, q['ad'], ' (%d sn)' % q['sure_sn'] if q.get('sure_sn') else ''))
        msgs = [('QuestInitializationCommand', {'quest': self.definition(qid)}), self.list_cmd()] + self.mark_msgs(qid)
        msgs += self.event('level', value=self.p.d['pilot'].get('level', 1))        # "Level N": şimdiki seviye
        return msgs + self.event('map', map=self.map_id) if self.map_id is not None else msgs

    def cancel(self, qid):
        if str(qid) not in self.st['active']:
            return []
        with self.p.lock:
            del self.st['active'][str(qid)]
            self.p.dirty = True
        msgs = [('RemoveMinimapMark', {'uid': 'quest_%d_%d' % (qid, n)}) for n in sorted(self.marks.pop(qid, set()))]
        self.log('   görev iptal: %d' % qid)
        return msgs + [('QuestCancelledCommand', {'id': qid}), self.list_cmd()]

    # ------------------------------------------------------------ ilerleme
    def matches(self, c, kind, kw, map_id=None):
        """Olay bu koşulu ilerletiyor mu -> eklenecek miktar ya da ('set', değer). Ortak türler gorev_takip.measure'da (Pass görevleriyle
        tek ölçüm noktası); burada konum ("@own X-3") oyuncunun firmasına göre çözülür ve ana görevlere özgü türler ölçülür."""
        subs = c['subConditions']
        on_map = [s for s in subs if s['type'] == ON_MAP]
        if on_map and str(kw.get('map', self.map_id)) not in self.resolve(on_map[0]['matches']):
            return 0
        misc = [MISC_STATE.get(int(s['matches'][0]) if s['matches'] else -1) for s in subs if s['type'] == MISCELLANEOUS]
        if misc:
            now = self.state()
            if any(x is None or now.get(x[0], False) != x[1] for x in misc):
                return 0
        m = c['matches']
        if c['type'] == VISIT_MAP:
            coord = next((s['matches'] for s in subs if s['type'] == COORDINATES), None)
            if coord:                                       # haritada koordinata varmak: yarıçap içinde saniyelik konum
                return 1 if (kind == 'pos' and str(kw.get('map')) in self.resolve(m)
                             and math.hypot(kw.get('x', 0) - int(coord[0]), kw.get('y', 0) - int(coord[1])) <= int(coord[2])) else 0
            return 1 if kind == 'map' and str(kw.get('map')) in self.resolve(m) else 0
        if c['type'] == ENDURANCE:
            return int(kw.get('ms', 1000)) if kind == 'pos' else 0      # kalma süresi saniyelik olayla (dakika olayı değil)
        if c['type'] == DAMAGE:
            return int(kw.get('adet', 0)) if kind == 'damage_taken' else 0       # "tüm hasar kaydedilir": alınan hasar
        if c['type'] == AVOID_DAMAGE:
            return 0                                        # kısıt (broken)
        if c['type'] == VISIT_QUEST_GIVER and kind == 'giver':
            return 1
        if c['type'] == PUT_ITEM_IN_SLOT_BAR and kind == 'slot_bar' and len(m) >= 2:
            items = set(kw.get('items', ()))
            return 1 if (m[0], m[-1]) in items and (len(m) < 3 or (m[0], m[1], m[-1]) in set(kw.get('slots', ()))) else 0
        if c['type'] == VISIT_MAP_ASSET and kind == 'asset':
            return 1 if str(kw.get('tur')) in m else 0
        if c['type'] == UPDATE_SKYLAB_TO_LEVEL and kind == 'skylab':
            return c['targetValue'] if m and kw.get('modul') == m[0] and kw.get('seviye', 0) >= c['targetValue'] else 0
        if c['type'] == KILL_PLAYERS and kind == 'kill_player':
            # eşleşme [gemi sayısı, gemiler…, firma sayısı, firmalar…] (istemci: KillPlayersCondition.ParseMatches)
            n = int(m[0]) if m else 0
            ships, rest = m[1:1 + n], m[1 + n:]
            facs = rest[1:1 + int(rest[0])] if rest else []
            if kw.get('faction') == self.faction():
                return 0
            return 1 if (not ships or str(kw.get('ship')) in ships) and (not facs or str(kw.get('faction')) in facs) else 0
        return GT.measure(dict(c, subConditions=[]), kind, kw, self.map_id)

    def event(self, kind, **kw):
        """Oyun olayı (görev olayları: kill, cargo, bonus, loot, sell, map, giver …; başarım olayları: damage, distance, gate, level …)
        -> koşul güncellemeleri, işaretler, tamamlanan görevler. Grup üyesinin öldürdüğü (grup) sayılır, kısıtı bozmaz."""
        msgs = self.broken(kind, **kw) if kind in ('kill_player', 'kill', 'damage_taken', 'damage_player', 'ammo') and not kw.get('grup') else []
        for qs in list(self.st['active']):
            qid = int(qs)
            if qid not in QUESTS or qs not in self.st['active']:
                continue
            upd, done = GT.advance(self.p, QUESTS[qid]['root'], self.st['active'][qs], kind, kw, self.map_id, fn=self.matches)
            if not upd and not done:
                continue
            msgs += upd + self.mark_msgs(qid)
            if done:
                msgs += self.complete(qid)
        return msgs

    # ------------------------------------------------------------ süre ve kısıtlar
    def elapsed_ms(self, qid, target):
        vals = self.values(qid)
        if START not in vals:
            return 0
        return int(min(target - 1, max(0, (time.time() - vals[START]) * 1000)))

    def fail(self, qid, why):
        if str(qid) not in self.st['active']:
            return []
        with self.p.lock:
            del self.st['active'][str(qid)]
            self.p.dirty = True
        msgs = [('RemoveMinimapMark', {'uid': 'quest_%d_%d' % (qid, n)}) for n in sorted(self.marks.pop(qid, set()))]
        self.log('   görev başarısız: %d %s (%s)' % (qid, QUESTS[qid]['ad'], why))
        return msgs + [('QuestFailedCommand', {'id': qid}), self.list_cmd()]

    def broken(self, kind, **kw):
        """Kısıt bozuldu mu: ölüm, yasak firmanın oyuncusunu vurmak, yasak uzaylıyı öldürmek ya da hasar sınırı (alınan hasar
        AVOID_DAMAGE koşulunda birikir, gösterimi saniyede bir) -> başarısız görevlerin ve hasar gösteriminin mesajları."""
        msgs = []
        for qs in list(self.st['active']):
            q = QUESTS.get(int(qs))
            for f in (q or {}).get('failed', []):
                if f['tur'] == 'hasar' and kind == 'damage_taken':
                    c = next(c for c in conditions(q['root']) if c['type'] == AVOID_DAMAGE)
                    with self.p.lock:
                        v = self.st['active'][qs][str(c['id'])] = self.st['active'][qs].get(str(c['id']), 0) + int(kw.get('adet', 0))
                        self.p.dirty = True
                    hit = v >= f['cap']
                    if not hit and time.time() - GT.LAST_SENT.get(c['id'], 0) >= GT.THROTTLE_SEC:
                        GT.LAST_SENT[c['id']] = time.time()
                        msgs.append(self.cond_update(c['id'], v, True, False))
                else:
                    hit = ((f['tur'] == 'olum' and kind == 'death')
                           or (f['tur'] == 'player_damage' and kind == 'damage_player' and kw.get('adet', 0) > 0)       # "Don't damage other players"
                           or (f['tur'] == 'player' and kind == 'kill_player' and kw.get('faction') == f['firma'])
                           or (f['tur'] == 'kills' and kind == 'kill' and kw.get('npc') in f['npc'])
                           or (f['tur'] == 'ammunition' and kind == 'ammo' and kw.get('adet', 0) > 0
                               and GT.ammo_kind(kw.get('loot', '')) in (('1', '2', '3') if f['ammo_class'] == '0' else (f['ammo_class'],))))
                if hit:
                    msgs += self.fail(int(qs), 'kısıt: %s' % f['tur'])
                    break
        return msgs

    def tick(self, now):
        """Süreli görevler: süre dolunca başarısız; değilse 5 sn'de bir süre koşulunun değeri. Günlük/haftalık görevin dönemi
        geçtiyse başarısız; dönem değişince liste yenilenir."""
        if now < self.next_tick:
            return
        self.next_tick = now + 5.0
        msgs = []
        if self.offer is not None and offered(now) != self.offer:
            msgs.append(self.list_cmd())
        for qs in list(self.st['active']):
            q = QUESTS.get(int(qs))
            if q and q.get('etkinlik') and not event_open(q, now):
                msgs += self.fail(int(qs), 'etkinlik bitti')
                continue
            if (q and q.get('pool') and 'difficulty' in q['pool'] and q['pool']['tur'] != 'daily'
                    and now - self.st['active'][qs].get(ACCEPT, now) > 14 * 86400):
                msgs += self.fail(int(qs), '14 gün geçti')        # forum 129125: kabul edilen görev dönem bitince düşmez; haftalık 14 gün
                continue
            if not q or not q.get('sure_sn'):
                continue
            start = self.st['active'][qs].get(START, now)
            if now - start >= q['sure_sn']:
                msgs += self.fail(int(qs), 'süre doldu')
                continue
            for c in conditions(q['root']):
                if c['type'] == HASTE:
                    msgs.append(self.cond_update(c['id'], self.elapsed_ms(int(qs), c['targetValue']), True, False))
        if msgs and self.send:
            self.send(msgs)

    @staticmethod
    def cond_update(cid, value, active, completed):
        return ('QuestConditionUpdateCommand', {'questConditionId': cid, 'state': mod(
            'QuestConditionStateModule', currentValue=value, active=active, completed=completed)})

    def complete(self, qid):
        """Görev bitti: günlük/haftalık dönemine, meydan okuma en iyi süresine (puan görevinde en iyi puanına; tekrar alınır),
        ötekiler tamamlananlara yazılır."""
        q = QUESTS[qid]
        rating = 0
        with self.p.lock:
            vals = self.st['active'].pop(str(qid), {})
            if q.get('pool'):
                self.st.setdefault('donem', {})[str(qid)] = vals.get(PERIOD) or period_key(qid)
            elif q.get('tekrar'):                    # özel görev: bu gün / bu etkinlik için bitti
                self.st.setdefault('donem', {})[str(qid)] = vals.get(PERIOD) or repeat_key(qid)
            elif q.get('challenge'):
                best = self.st.setdefault('score', {})
                if q.get('puan'):                    # puan görevi ("mümkün olduğunca çok"): puan öldürülenlerin sayısı, en iyisi en çoğu
                    rating = sum(vals.get(str(i), 0) for i in q['puan'])
                    best[str(qid)] = max(best.get(str(qid), rating), rating)
                else:
                    rating = max(1, int(time.time() - vals.get(START, time.time())))
                    best[str(qid)] = min(best.get(str(qid), rating), rating)
            elif qid not in self.st['tamam']:
                self.st['tamam'].append(qid)
            self.p.dirty = True
        self.p.ach('quest', id=qid)
        if q.get('title'):
            RT.grant_title(self.p, q['title'])       # ödül unvanı (Plus Ultra: Transcendent Radiance); başarım penceresinde seçilir
        RT.note(self.p, 'quest_success_%d' % qid, quest=qid, done=1)          # seyir defteri
        if qid == 20003:
            self.p.ach('tutorial')                   # başarım: başlangıç görevleri (20000-20003) bitti
        msgs = [('QuestCompletedCommand', {'id': qid, 'rating': rating})]
        msgs += [('RemoveMinimapMark', {'uid': 'quest_%d_%d' % (qid, n)}) for n in sorted(self.marks.pop(qid, set()))]
        mult = 1 + BOOSTER.mods(self.p).get('quest_reward', 0)        # QR-01 / NQR-B01: görev ödülleri x2 (uridyum hariç; Ö6)
        for loot, n in QUESTS[qid]['rewards']:
            n = n if loot == 'currency_uridium' or loot.startswith('resource_premium-days') else int(n * mult)   # Titan SSS: Premium günü katlanmaz
            msgs += self.grant(loot, n) if self.grant else []
        self.log('   görev tamamlandı: %d %s (%s)' % (qid, QUESTS[qid]['ad'], ', '.join('%s x%d' % (l, n) for l, n in QUESTS[qid]['rewards'])))
        return msgs + [self.list_cmd()]
