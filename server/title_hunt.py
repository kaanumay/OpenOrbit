"""Pursuit of Prestige / Title Frenzy (yol haritası Ö3; veri data/extra_events.json 'unvan_avi').

İstemci (menü öğesi titleFrenzy, pencere 116, UITitleFrenzySystem): TitleFrenzyInfoCommand {schedule TitleFrenzyScheduleUpdateCommand
{timeToNextWindow, timeToWindowEnd}, timeToEventEnd, titleKey, rankRewards [RankRewardRangeModule], npcIds}, TitleFrenzyOwnerUpdateCommand
{username, titleId, mapId} (unvanın kimde olduğu; pencerenin "Titles are currently on the following NPCs/Players" listesi),
TitleFrenzyRankingInfoCommand {isActive, myRank, prevRank, nextRank, rankingInfoList [{username, score, rank}]}; sıralamanın ödül
sekmesi RankRewardRequest rankType 12 (rankings.py), Rankings'in sayfası RankingsEventsInfoRequest rankType 3. Metinler:
log_msg_titlefrenzy_takeover (%NAME% %MAP%: uzaylıda), log_msg_titlefrenzy_playertakeover (oyuncuda), titlefrenzy_window-*.
Kurallar (wiki hitac-assault): 4 Prestige unvanı rastgele Hitac Underling'lerde (X-2..X-8); saatler 07-09, 12-14, 18-20, 22-24;
unvanı taşıyan uzaylıyı öldüren unvanı alır; ölüm, çıkış, üsse ya da kapıya girme, 30 dk kesintisiz tutma unvanı kaybettirir (unvan
başka bir uzaylıya geçer); toplam tutma süresi sıralamayı belirler. Unvan tutulurken gemi üstünde görünür (0|n|t).
Tek oyunculu uyarlama: rakipler sanal (müzayede rakiplerinin adları); uzaylıdaki unvanı arada bir sanal rakip kapar, bir süre tutup
bırakır; puanları da böyle birikir. Unvan haritada değil başka haritada uzaylıdaysa yalnız listede görünür; oyuncu o haritaya
gelince bir Underling unvanı taşır (gemi üstünde unvanıyla). Puan: tutulan dakika.
Profilde: unvan_avi {donem, puan (dk), unvanlar {id: {owner: 'npc'|'oyuncu'|'rakip', harita, ad, bas}}, rakipler {name: puan},
odul_alindi}.
Çok oyunculu sunucuda her oyuncunun unvanları kendisinin; ortak haritanın uzaylısındaki unvan oyuncunun adıyla (unvanlar {name: kimlik}):
iki oyuncu aynı Underling'i kendi unvanının taşıyıcısı sanmasın (önce n.unvan ortaktı). Sıralamada sunucunun öteki oyuncuları da.
"""
import json, os, random, time

import map_links as H
import rankings as RK
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('title_hunt', {})
EVENT = D.get('event', 'title_hunt')
RANK_TYPE = 12                                     # RankRewardRequest.RankType.TITLE_FRENZY
WINDOWS = [tuple(w) for w in D.get('hours', [[7, 9], [12, 14], [18, 20], [22, 24]])]
MAPS = D.get('maps', ['X-2', 'X-3', 'X-4', 'X-5', 'X-6', 'X-7', 'X-8'])
TITLE_KEY = D.get('title', 'title_titlefrenzy_event2026')
REWARD_TITLE = D.get('reward_title', 'title_titlefrenzy-aug2026-reward')
COUNT = D.get('count', 4)
HOLD_MAX = D.get('max_hold_sec', 1800)
CARRIER = D.get('carrier', 'event_hitac_underling_')
TITLE_ID_BASE = 1500                               # gemi üstündeki unvanın kimliği (istemci anahtarı gösterir)
if D.get('table'):
    RK.TABLES[RANK_TYPE] = D['table']


def register_titles():
    """Unvanları başarım tablosuna (gemi üstü unvan, başarım penceresinde seçilebilir ödül unvanı)."""
    import achievement as ACV
    for i, key in enumerate((TITLE_KEY, REWARD_TITLE)):
        if key not in ACV.TITLES:
            ACV.TITLES[key] = TITLE_ID_BASE + i
            ACV.TITLE_KEYS[TITLE_ID_BASE + i] = key


def map_id(cls, faction):
    """X-n haritasının firmaya göre kimliği (harita sınıfı -> kimlik)."""
    return next((m for m, n in H.NAMES.items() if H.map_class(m) == cls and (H.company(m) in (None, faction))), 0)


def in_window(now=None):
    """(pencere sürüyor mu, pencerenin bitişine/başlangıcına kalan saniye)."""
    t = time.localtime(time.time() if now is None else now)
    h = t.tm_hour + t.tm_min / 60.0 + t.tm_sec / 3600.0
    for a, b in WINDOWS:
        if a <= h < b:
            return True, int((b - h) * 3600)
    nxt = min([a for a, b in WINDOWS if a > h] or [WINDOWS[0][0] + 24])
    return False, int((nxt - h) * 3600)


class TitleHunt:
    REQUESTS = ('RankingsEventsInfoRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.attached = 0.0                        # harita açıldığı an (taşıyıcılar biraz sonra atanır)
        self.shown = None                          # unvanları istemciye gönderilen açılış (attached)
        self.was = None
        self.next_rival = 0.0
        self.base_title = None                     # başarımın gemi üstü unvanı (oturum bağlar: basarim.title_msgs)
        register_titles()

    @property
    def st(self):
        d = self.p.d.setdefault('title_hunt', {})
        for k, v in (('points', 0.0), ('titles', {}), ('rivals', {})):
            d.setdefault(k, v)
        return d

    def enabled(self, now=None):
        """Pursuit of Prestige sürüyor ve Hitac'ın Underling'leri haritalarda (Hitac Assault)."""
        cur = CAL.active(now)
        return EVENT in cur and 'hitac' in cur

    def faction(self):
        return self.p.d['pilot'].get('factionId', 2)

    # ------------------------------------------------------------ komutlar
    def owner_cmds(self):
        out = []
        for tid in range(1, COUNT + 1):
            t = self.st['titles'].get(str(tid))
            if not t:
                out.append(('TitleFrenzyOwnerUpdateCommand', {'username': '', 'titleId': tid, 'mapId': 0}))
                continue
            name = self.p.d['pilot'].get('userName', '') if t['owner'] == 'player' else t['name']
            out.append(('TitleFrenzyOwnerUpdateCommand', {'username': name, 'titleId': tid, 'mapId': t.get('map', 0)}))
        return out

    def schedule_cmd(self, now=None):
        on, left = in_window(now)
        # süreler saniye (canlı: milisaniye gönderilince 1 sa 41 dk "70 Days 14 Hrs." görünüyordu)
        return {'_': 'TitleFrenzyScheduleUpdateCommand', 'timeToNextWindow': 0 if on else left,
                'timeToWindowEnd': left if on else 0}

    def info_cmd(self, now=None):
        return ('TitleFrenzyInfoCommand', dict(schedule=self.schedule_cmd(now), timeToEventEnd=CAL.time_left(EVENT, now),
                                               titleKey=TITLE_KEY, rankRewards=RK.ranges(RANK_TYPE), npcIds=D.get('npc_ids', [299])))

    def ranking(self):
        """Oyuncu, sunucunun öteki oyuncuları ve sanal rakipler, puana göre."""
        import community as TP
        rows = [(self.p.d['pilot'].get('userName', ''), self.st['points'] + self.held_minutes(), True)]
        for k in TP.all_().values():
            if k.profile is not self.p and (k.profile.d.get('title_hunt') or {}).get('period') == self.st.get('period'):
                o = TitleHunt.__new__(TitleHunt)
                o.p = k.profile
                rows.append((k.name, (k.profile.d['title_hunt'].get('points') or 0.0) + o.held_minutes(), False))
        rows += [(n, s, False) for n, s in self.st['rivals'].items()]
        rows.sort(key=lambda r: -r[1])
        return rows

    def ranking_cmd(self):
        rows = self.ranking()
        mod = lambda i: None if i < 0 or i >= len(rows) else {'_': 'TitleFrenzyRankingInfoModule', 'username': rows[i][0],
                                                              'score': round(float(rows[i][1]), 1), 'rank': i + 1}
        me = next(i for i, r in enumerate(rows) if r[2])
        return ('TitleFrenzyRankingInfoCommand', dict(isActive=self.enabled(), myRank=mod(me), prevRank=mod(me - 1),
                                                      nextRank=mod(me + 1),
                                                      rankingInfoList=[mod(i) for i in range(min(len(rows), D.get('entries', 10)))]))

    def login_msgs(self):
        if not self.enabled():
            return []
        msgs = [self.info_cmd()] + self.owner_cmds()          # sıralama yalnız Rankings açılınca (Hall of Fame'in arayüzüne gider;
        return msgs + self.ship_title_msgs()                   # pencere kapalıyken InitRankingUI hata veriyordu: canlı tur Ö3)

    def window(self, item):
        """Pencere açıldı (UIButtonTriggerRequest titleFrenzy)."""
        if item != 'titleFrenzy' or not self.enabled():
            return []
        return [self.info_cmd()] + self.owner_cmds()

    def handle(self, name, f):
        if name == 'RankingsEventsInfoRequest' and int(f.get('rankType') or 0) == 3:
            return [self.ranking_cmd()]
        return []

    # ------------------------------------------------------------ unvanlar
    def held(self):
        return [tid for tid, t in self.st['titles'].items() if t['owner'] == 'player']

    def held_minutes(self, now=None):
        now = time.time() if now is None else now
        return sum(max(0, now - t['start']) for t in self.st['titles'].values() if t['owner'] == 'player') / 60.0

    def ship_title_msgs(self):
        """Gemi üstündeki unvan: unvan tutulurken Prestige unvanı, değilse başarımın seçili unvanı (basarim.title_msgs)."""
        if self.held():
            return [legacy('0|n|t|%d|%d|%s' % (self.p.user_id, TITLE_ID_BASE, TITLE_KEY))]
        return []

    def to_npc(self, tid, avoid=None, now=None):
        """Unvan rastgele bir haritadaki Underling'e geçer."""
        cls = random.choice([m for m in MAPS if m != avoid] or MAPS)
        name = D.get('carrier_name', 'Hitac-Underling')
        with self.p.lock:
            self.st['titles'][str(tid)] = {'owner': 'npc', 'map': map_id(cls, self.faction()), 'class_name': cls, 'name': name,
                                             'start': time.time() if now is None else now}
            self.p.dirty = True
        return [self.owner_one(tid), legacy('0|A|STM|log_msg_titlefrenzy_takeover|%%NAME%%|%s|%%MAP%%|%s' % (name, cls))]

    def owner_one(self, tid):
        return next(m for m in self.owner_cmds() if m[1]['titleId'] == int(tid))

    def drop(self, why, now=None):
        """Oyuncu unvanlarını kaybeder (ölüm, çıkış, üs, kapı, 30 dk): süre puana, unvan başka uzaylıya."""
        now = time.time() if now is None else now
        msgs = []
        for tid in self.held():
            t = self.st['titles'][tid]
            gained = max(0, now - t['start']) / 60.0
            with self.p.lock:
                self.st['points'] += gained
                self.p.dirty = True
            self.log('   Prestige unvanı %s bırakıldı (%s): +%.1f dk' % (tid, why, gained))
            msgs += self.to_npc(tid, avoid=t.get('class_name'), now=now)
        if msgs:
            msgs += self.title_reset_msgs()
        return msgs

    def title_reset_msgs(self):
        """Prestige unvanı gitti: başarımın seçili unvanı (yoksa unvansız)."""
        base = self.base_title() if self.base_title else []
        return base or [legacy('0|n|t|%d|0|' % self.p.user_id)]

    def attach(self, world):
        """Harita açıldı: buradaki unvanların taşıyıcıları tick'te atanır (canlı: attach'te haritanın uzaylıları henüz
        geri yüklenmemişti, unvan hiçbir Underling'e geçmiyordu)."""
        self.world = world
        self.attached = time.time()
        return []

    def mark(self, n):
        """Uzaylının taşıdığı bu oyuncunun unvanı ya da None."""
        return (getattr(n, 'titles', None) or {}).get(self.key)

    @property
    def key(self):
        return str(self.p.d['pilot'].get('userName', '')).strip().lower()

    def carriers(self, now):
        """Bu haritadaki, taşıyıcısı olmayan unvanlar bir Underling'e (gemi üstünde unvanıyla) -> mesajlar."""
        w = self.world
        if not w or now - self.attached < 2.0:            # uzaylılar istemcide oluşturulduktan sonra
            return []
        cls = H.map_class(w.map_id)
        mine = [tid for tid, t in self.st['titles'].items() if t['owner'] == 'npc' and t.get('class_name') == cls]
        if not mine:
            return []
        msgs = []
        with w.lock:
            if self.shown != self.attached:         # haritaya yeniden girildi: geri gelen taşıyıcıların unvanı istemcide yok
                self.shown = self.attached
                msgs += [legacy('0|n|t|%d|%d|%s' % (n.id, TITLE_ID_BASE, TITLE_KEY))
                         for n in w.npcs.values() if n.alive and self.mark(n) in mine]
            have = {self.mark(n) for n in w.npcs.values() if n.alive}
            free = [n for n in w.npcs.values() if n.alive and n.tip.startswith(CARRIER) and not getattr(n, 'titles', None)]
            for tid, n in zip([tid for tid in mine if tid not in have], free):
                n.titles = dict(getattr(n, 'titles', None) or {}, **{self.key: tid})
                msgs.append(legacy('0|n|t|%d|%d|%s' % (n.id, TITLE_ID_BASE, TITLE_KEY)))
        return msgs

    def on_kill(self, w, npc, x, y):
        tid = self.mark(npc)
        if not tid or not self.enabled():
            return []
        t = self.st['titles'].get(tid)
        if not t or t['owner'] != 'npc':
            return []
        with self.p.lock:
            self.st['titles'][tid] = {'owner': 'player', 'map': int(w.map_id), 'class_name': H.map_class(w.map_id), 'name': '',
                                         'start': time.time()}
            self.p.dirty = True
        name = self.p.d['pilot'].get('userName', '')
        self.log('   Prestige unvanı %s alındı (%s)' % (tid, H.name(w.map_id)))
        return [self.owner_one(tid), legacy('0|A|STM|log_msg_titlefrenzy_playertakeover|%%NAME%%|%s|%%MAP%%|%s' % (name, H.name(w.map_id)))] \
            + self.ship_title_msgs()

    # ------------------------------------------------------------ zaman
    def start_window(self, now):
        msgs = []
        with self.p.lock:
            self.st['titles'] = {}
            self.p.dirty = True
        for tid in range(1, COUNT + 1):
            msgs += self.to_npc(tid, now=now)
        if self.world:
            self.attach(self.world)
        return msgs + [self.info_cmd(now)]

    def end_window(self, now):
        msgs = self.drop('pencere bitti', now)
        with self.p.lock:
            self.st['titles'] = {}
            self.p.dirty = True
        return msgs + [self.info_cmd(now)] + self.owner_cmds()

    def rivals_tick(self, now):
        """Sanal rakipler: uzaylıdaki unvanı arada bir kapar, bir süre tutup bırakır; puanları birikir."""
        if now < self.next_rival:
            return []
        self.next_rival = now + 60
        import auction as MZ
        msgs = []
        for tid, t in list(self.st['titles'].items()):
            if t['owner'] == 'rival' and now - t['start'] >= t.get('sure', 600):
                with self.p.lock:
                    self.st['rivals'][t['name']] = self.st['rivals'].get(t['name'], 0.0) + (now - t['start']) / 60.0
                    self.p.dirty = True
                msgs += self.to_npc(tid, avoid=t.get('class_name'), now=now)
            elif t['owner'] == 'npc' and random.random() < D.get('rival_capture', 0.08):
                name = '%s%s' % (random.choice(MZ.R['names']), random.choice(MZ.R['attachments']))
                with self.p.lock:
                    self.st['titles'][tid] = dict(t, owner='rival', name=name, start=now, sure=random.randint(*D.get('rival_duration', [300, 1500])))
                    self.p.dirty = True
                msgs.append(self.owner_one(tid))
        return msgs

    def tick(self, now):
        if not self.enabled(now):
            return self.event_end(now)
        if self.st.get('period') is None:
            with self.p.lock:
                self.st['period'] = (CAL.period(EVENT, now) or (now,))[0]
                self.p.dirty = True
        on = in_window(now)[0]
        msgs = []
        if self.was is not None and on != self.was:
            msgs += self.start_window(now) if on else self.end_window(now)
        elif self.was is None and on and not self.st['titles']:
            msgs += self.start_window(now)
        self.was = on
        if on:
            msgs += self.carriers(now)
            msgs += self.rivals_tick(now)
            for tid in self.held():                        # 30 dk kesintisiz tutma
                if now - self.st['titles'][tid]['start'] >= HOLD_MAX:
                    msgs += self.drop('30 dk', now)
                    break
            w = self.world
            if self.held() and w and (w.in_station() or getattr(w, 'gate', None)):
                msgs += self.drop('üs/kapı', now)
        return msgs

    def event_end(self, now):
        """Etkinlik bitti: sıralamaya göre ödül (bir kez) ve durum sıfır."""
        if self.st.get('period') is None:
            return []
        msgs = self.drop('etkinlik bitti', now)
        rank = next(i + 1 for i, r in enumerate(self.ranking()) if r[2])
        t = RK.TABLES.get(RANK_TYPE) or {}
        r = next((r for r in t.get('ranges', []) if r['from_'] <= rank <= r['e']), None)
        if r and self.st['points'] > 0:
            for loot, n in r['items']:
                msgs += self.m.prize(loot, n)
            if r.get('title'):
                msgs += self.grant_title(r['title'])
            msgs.append(RK.confirmation(rank, RK.DEFAULT_REWARD, r))           # RewardType'ta Title Frenzy yok
            self.log('   Pursuit of Prestige bitti: %d. sıra (%.1f dk), ödül %s' % (rank, self.st['points'], r['items']))
        with self.p.lock:
            self.p.d['title_hunt'] = {}
            self.p.dirty = True
        return msgs + self.m.money_msgs()

    def grant_title(self, key):
        import achievement as ACV
        st = ACV.state(self.p)
        ACV.title_id(key)                                  # başarım penceresinde seçilebilsin (tabloda olmayan etkinlik unvanı)
        if key not in st['titles']:
            with self.p.lock:
                st['titles'].append(key)
                self.p.dirty = True
        # istemcide "unvan alındı" metni yok; LOT satırı adı eşya kaynağında aradığından seyir defterine "You received ." yazıyordu
        # (canlı tur 2): satır gönderilmez, unvan başarım penceresinde seçilir
        return []
