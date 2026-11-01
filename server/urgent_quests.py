"""Urgent Missions (Diminishing Quests; yol haritası Ö3; veri data/extra_events.json 'acil_gorevler').

İstemci (menü öğesi diminish_quests, UIDiminishingQuestSystem): DiminishingQuestInitializationCommand {quest QuestDefinitionModule,
timeToQuestEnd (sn), acceptabilityStatus {type}} görevi gösterir; kabul DiminishingQuestAcceptQuestRequest {questId,
acceptabilityStatus} -> DiminishingQuestAcceptQuestResponse {acceptabilityStatus, timeToQuestEnd}; kaldırma
DiminishingQuestRemoveQuestCommand {acceptabilityStatus}. Durumlar (AcceptabilityType): 0 NOT_ACCEPTABLE, 1 NOT_STARTED, 2 RUNNING,
3 COMPLETED, 4 DISABLED. Metinler (flashres): diminishing_quest_available / _accepted / _completed / _expired /
_cannot_accept_outside_base. Koşulların ilerlemesi QuestConditionUpdateCommand.
Kurallar (Mart 2022 güncellemesi, oyuncu bildirimleri): uzun süre aralıksız uzaylı avlayınca ansızın çıkar; yalnız ana üste (ya da
Clan Battle Station'da) kabul edilir; süresi dolunca kaybolur; hedefler sıradan uzaylılar (ör. 2 Streuner, 2 Lordakia, 2 Mordon).
Asıl oyunda ödülü "azalan ödülleri" geri yükseltmekti; sunucuda azalan ödül olmadığından görev kendi ödülünü verir (uyarlama:
hedeflerin ödüllerinin katı).
Menü öğesi yalnız görev varken görünür (kullanıcı 2026-10-18, H140: görev yokken açılan pencere boştu, iki küçük görsel). İstemci
menünün simgelerini yalnız girişte ve harita yüklenince kuruyor (UIMainCenterNewSystem.ShowMenuList; RefreshMenuList olayı sahne
değişiminde): oyun sürerken gelen WindowItemCommand yalnız öğenin verisini değiştirir, simge eklemez/kaldırmaz. Görev gelince istemci
pencereyi simgeden uçurarak açıyor (DiminishingQuestHandler -> OpenWindow -> PlayFly: simge sözlükte yoksa KeyNotFound, H110). Menü
kurulurken görünür öğenin simgesi yaratılır, görünmez olanınki yalnız gizlenir (MenuItemDic'te kalır). Sunucu bu yüzden simgenin
oturumda yaratılıp yaratılmadığını izler (icon): yaratıldıysa görev hemen gösterilir; yoksa görev bekler, öğe görünür bildirilir ve
sonraki harita yüklenişinde (ReadyRequest; menü yeniden kurulur) gösterilir; süresi gösterilince başlar. Görev bitince öğe gizlenir;
simge sonraki kuruluşa dek kalır: görev yokken açılırsa pencere WindowItemCommand ile kapatılır ve kısa bir açıklama çıkar.
(DiminishingQuestRemoveQuestCommand değil: istemcinin işleyicisi görevi kaldırınca pencereyi kapatıp boş görevle SetQuestInfo
çağırıyor, NullReferenceException; görev bitişinde de oluyor, zararsız, istemcinin kusuru.)
Profilde: acil_gorev {gorev (tanım), durum, gosterildi, bitis (gösterilince), deger, oduller, sayac (son görevden beri öldürme), son}.
"""
import json, os, random, time

import map_links as H
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('urgent_quests', {})
EVENT = 'urgent_quests'
NOT_ACCEPTABLE, NOT_STARTED, RUNNING, COMPLETED, DISABLED = 0, 1, 2, 3, 4
QUEST_ID = 796000
ITEM = 'diminish_quests'                  # menü öğesi
REBUILD_SEC = 2.0                          # harita yüklenişinden (ReadyRequest) menünün yeniden kurulmasına pay
NO_QUEST_TEXT = 'No urgent mission right now. Urgent missions appear during long alien hunts.'


def active(now=None):
    return EVENT in CAL.active(now)


def mod(name, **f):
    f['_'] = name
    return f


def status(t):
    return mod('QuestAcceptabilityStatusModule', type=t)


def quest_def(qid, targets, rewards):
    """Öldürme görevi (KILL_NPC koşulları; hepsi gerekli)."""
    conds = []
    for i, (npc_id, n) in enumerate(targets):
        conds.append(mod('QuestElementModule', questCase=mod('QuestCaseModule', id=0, active=False, mandatory=False, ordered=False,
                                                             mandatoryCount=0, modifier=[]),
                         condition=mod('QuestConditionModule', id=qid * 10 + i + 1, matches=[str(npc_id)], type=6, displayType=6,
                                       targetValue=n, mandatory=True, subConditions=[],
                                       state=mod('QuestConditionStateModule', currentValue=0, active=True, completed=False))))
    return mod('QuestDefinitionModule', id=qid, types=[mod('QuestTypeModule', type=8)],
               rootCase=mod('QuestCaseModule', id=qid * 10, active=True, mandatory=True, ordered=False, mandatoryCount=len(conds),
                            modifier=conds),
               rewards=[mod('LootModule', lootId=l, amount=a, modifier='') for l, a in rewards],
               icons=[mod('QuestIconModule', icon=1)], textKeyFoundation='', portraitId='', star=0)


class UrgentQuests:
    REQUESTS = ('DiminishingQuestAcceptQuestRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.since = time.time()                   # aralıksız oynama (oturumun başı)
        self.icon = None                           # simge oturumda yaratıldı mı (girişte belli olur; sonra hep kalır)
        self.vis_sent = None                       # istemciye bildirilen görünürlük (öğenin verisi)
        self.rebuild_at = None                     # menünün yeniden kurulacağı an (harita yüklenişi)
        self.win_open = False                      # pencere açık (UIWindowUpdateRequest maximized)

    @property
    def st(self):
        return self.p.d.setdefault('urgent_quest', {})

    def attach(self, world):
        self.world = world
        return []

    # ------------------------------------------------------------ menü öğesi
    def has_quest(self, now=None):
        """Bekleyen ya da gösterilmiş, süresi dolmamış görev."""
        q = self.st
        if not q.get('quest') or q.get('state') not in (NOT_STARTED, RUNNING):
            return False
        return not q.get('shown', True) or (time.time() if now is None else now) < q.get('end_time', 0)

    def menu_visible(self, now=None):
        """Öğenin görünürlüğü (profil.WINDOW_HOOKS): etkinlik sürerken ve görev varken."""
        return active(now) and self.has_quest(now)

    def sync(self, now=None):
        """Görünürlük değiştiyse WindowItemCommand (maximized False: açık pencereyi kapatır, açmaz; simge haritada kurulur)."""
        v = self.menu_visible(now)
        if self.vis_sent is None or self.vis_sent == v:
            return []
        self.vis_sent = v
        it = self.p.window_item(ITEM) if hasattr(self.p, 'window_item') else None
        return [('WindowItemCommand', dict(it, visible=v, maximized=False))] if it else []

    def on_ready(self):
        """Harita yüklendi (ReadyRequest; ilk giriş dışında): istemci menüyü bildirilen görünürlükle yeniden kuracak."""
        self.rebuild_at = time.time() + REBUILD_SEC
        return []

    def show(self, now):
        """Görevi istemciye gönder (pencere açılır); bekleyen görevin süresi şimdi başlar."""
        q = self.st
        fresh = not q.get('shown', True)
        if fresh:
            with self.p.lock:
                q['shown'] = True
                q['end_time'] = now + D.get('sure_sn', 1200)
                self.p.dirty = True
            self.log('   Urgent Mission: %s' % q.get('targets'))
        return self.sync(now) + [self.init_cmd(now)] + ([legacy('0|A|STM|diminishing_quest_available')] if fresh else [])

    def can_show(self):
        return self.icon is not False and self.rebuild_at is None     # icon None: giriş olmadı (testler)

    # ------------------------------------------------------------ görev
    def make(self, now):
        """Haritanın sıradan uzaylılarından 3 hedef (2-4'er)."""
        import world as world_module
        w = self.world
        rows = (world_module.CFG['maps'].get(str(w.map_id)) or {}).get('npc', []) if w else []
        T = world_module.CFG['types']
        kinds = [r['tip'] for r in rows if r['tip'] in T and T[r['tip']].get('npc_id') and not T[r['tip']].get('boss')]
        if not kinds:
            return None
        pick = random.sample(kinds, min(3, len(kinds)))
        targets = [(T[k]['npc_id'], random.randint(*D.get('count', [2, 4]))) for k in pick]
        mult = D.get('reward_multiplier', 3)
        tot = {'ep': 0, 'honor': 0, 'credits': 0, 'uridium': 0}
        for k, (npc_id, n) in zip(pick, targets):
            for a in tot:
                tot[a] += T[k].get('reward', {}).get(a, 0) * n * mult
        cur = {'ep': 'currency_experience', 'honor': 'currency_honour', 'credits': 'currency_credits', 'uridium': 'currency_uridium'}
        rewards = [(cur[a], int(v)) for a, v in tot.items() if v]
        qid = QUEST_ID + random.randint(1, 999)
        return dict(quest=quest_def(qid, targets, rewards), state=NOT_STARTED, shown=False, end_time=0, value={},
                    rewards=rewards, targets=[[k, n] for k, (_, n) in zip(pick, targets)])

    def init_cmd(self, now=None):
        # timeToQuestEnd saniye (canlı: milisaniye 18 dk'yı "12 Days 17 Hrs." gösteriyordu)
        q = self.st
        now = time.time() if now is None else now
        return ('DiminishingQuestInitializationCommand', dict(quest=q['quest'], timeToQuestEnd=max(0, int(q['end_time'] - now)),
                                                              acceptabilityStatus=status(q['state'])))

    def login_msgs(self):
        """Hazır demeti. İlk girişte menü öğenin o anki görünürlüğüyle kuruldu (UILayoutCommand, profil.WINDOW_HOOKS). Demet her
        harita yüklenişinde yeniden gidiyor: orada bir şey yapılmaz (görev istemcide duruyor; yeniden gönderilse pencere her
        haritada yeniden açılırdı); menünün yeniden kuruluşu on_ready'de."""
        if self.vis_sent is not None:
            return []
        now = time.time()
        self.icon = self.vis_sent = self.menu_visible(now)
        return self.show(now) if self.icon else []

    def on_kill(self, w, npc, x, y):
        return self.kill(npc.d.get('npc_id'))

    def kill(self, npc_id):
        """Uzaylı öldü (kendisi ya da grup üyesi aynı haritada; game.Session.quest_event) -> mesajlar."""
        q = self.st
        with self.p.lock:
            q['counter'] = q.get('counter', 0) + 1
            self.p.dirty = True
        if q.get('state') != RUNNING:
            return []
        import quest_tracker as GT
        msgs, done = GT.advance(self.p, q['quest']['rootCase'], q['value'], 'kill', {'npc': npc_id, 'avatar': 'NPC'})
        if done:
            with self.p.lock:
                q['state'] = COMPLETED
                self.p.dirty = True
            for loot, n in q['rewards']:
                msgs += self.m.prize(loot, n, 'quest')
            msgs += [legacy('0|A|STM|diminishing_quest_completed'),
                     ('DiminishingQuestRemoveQuestCommand', {'acceptabilityStatus': status(COMPLETED)})] + self.m.money_msgs()
            self.log('   Urgent Mission tamamlandı: %s' % q['targets'])
            self.reset()
            msgs += self.sync()
        return msgs

    def reset(self):
        with self.p.lock:
            for k in ('quest', 'state', 'shown', 'end_time', 'value', 'rewards', 'targets'):
                self.st.pop(k, None)
            self.st['counter'] = 0
            self.st['last'] = time.time()
            self.p.dirty = True
        self.since = time.time()

    def tick(self, now):
        out = []
        if self.rebuild_at is not None and now >= self.rebuild_at:
            self.rebuild_at = None
            self.icon = bool(self.icon) or bool(self.vis_sent)    # görünürse simge yaratıldı; yaratılan simge gizlense de kalır
        q = self.st
        if active(now) and q.get('quest'):
            if not q.get('shown', True):
                return out + (self.show(now) if self.can_show() else self.sync(now))
            if now >= q['end_time']:
                self.log('   Urgent Mission süresi doldu')
                self.reset()
                return out + [legacy('0|A|STM|diminishing_quest_expired'),
                              ('DiminishingQuestRemoveQuestCommand', {'acceptabilityStatus': status(NOT_ACCEPTABLE)})] + self.sync(now)
            return out
        out += self.sync(now)                          # etkinlik başladı / bitti
        if not active(now):
            return out
        w = self.world
        if not w or w.hero_dead or getattr(w, 'gate', None):
            return out
        if now - self.since < D.get('play_sec', 2700) or q.get('counter', 0) < D.get('kills', 150):
            return out
        if now - q.get('last', 0) < D.get('interval_sec', 3600):
            return out
        new = self.make(now)
        if not new:
            return out
        with self.p.lock:
            q.update(new)
            self.p.dirty = True
        if self.can_show():
            return out + self.show(now)
        self.log('   Urgent Mission bekliyor (menüde simgesi yok; harita yüklenince): %s' % new['targets'])
        return out + self.sync(now)

    def window_update(self, f):
        """Pencere açıldı (istemci bu pencere için UIButtonTriggerRequest göndermiyor, yalnız UIWindowUpdateRequest maximized True;
        taşıma/boyutta da gelir: yalnız kapalıdan açığa geçiş)."""
        if f.get('itemId') != ITEM:
            return None
        opened = bool(f.get('maximized')) and not self.win_open
        self.win_open = bool(f.get('maximized'))
        return self.window(ITEM) if opened else None

    def window(self, item):
        """Pencere açıldı: bekleyen görev hemen gösterilir; görev yoksa (bitmiş görevin simgesi) pencere kapanır."""
        if item != ITEM:
            return None
        now = time.time()
        if self.has_quest(now) and not self.st.get('shown', True):
            return self.show(now)
        if not self.has_quest(now):
            import galaxy_gates as KAPI                    # ekran metni (MessageCommand; istemci İngilizce)
            it = self.p.window_item(ITEM) if hasattr(self.p, 'window_item') else None
            close = [('WindowItemCommand', dict(it, visible=False, maximized=False))] if it else []
            return close + [KAPI.screen(NO_QUEST_TEXT)]
        return None

    def handle(self, name, f):
        q = self.st
        if name != 'DiminishingQuestAcceptQuestRequest' or not q.get('quest') or q.get('state') != NOT_STARTED or \
                not q.get('shown', True):
            return []
        w = self.world
        home = w and w.in_station() and w.station and H.company(w.map_id) == self.p.d['pilot'].get('factionId')
        if not home:
            return [legacy('0|A|STM|diminishing_quest_cannot_accept_outside_base')]
        with self.p.lock:
            q['state'] = RUNNING
            self.p.dirty = True
        self.log('   Urgent Mission kabul edildi')
        return [('DiminishingQuestAcceptQuestResponse', dict(acceptabilityStatus=status(RUNNING),
                                                              timeToQuestEnd=max(0, int(q['end_time'] - time.time())))),
                legacy('0|A|STM|diminishing_quest_accepted')]
