"""Günlük ödül pencereleri: Mini Client ödülü, Monthly Deluxe, Unity istemcisi ödül görevleri (yol haritası Aşama 7; veri
data/biletler.json <- tools/biletler.py, kayıttaki pencereler).

Mini Client ödülü (kayıt: MiniClientRewardInfoCommand {rewardList 15 gün, isClaimable, timeToEndEvent sn, daysClaimed};
  MiniClientRewardClaimRequest -> ödül + MiniClientRewardDayInfoCommand {isClaimable, daysClaimed}): etkinlik süresince (takvim.py:
  'MiniClientReward' türü olan etkinlik: Trial of Terrors, E8'den Prosperous, Protegit, Gauntlet of Plutus, Mimesis, Treacherous
  Domain, Fiesta, Thanksgiving ve kış takvimi) günde bir; liste kayıttaki Halloween listesi, Thanksgiving ve Prosperous'ta wiki'nin
  8 günlük listesi (biletler.json mini_istemci_etkinlik; fandom, 2021-2022 koşuları: gerçek 2026 listesi doğrulanamıyor), ötekilerinin
  listesi kaynakta yok (Halloween'inki).
Monthly Deluxe (MonthlyDeluxeInfoCommand {rewardList 28, dayInfoCommand {today, daysClaimed, isClaimable}, timeInfoCommand
  {timeToPassEnd}}; MonthlyDeluxeClaimRequest -> MonthlyDeluxeDayInfoCommand): gerçek parayla satılan paket
  (package_event-deal-month-deluxe -> resource_monthly-deluxe) uridyumla; alındığı günden 28 gün, her gün o günün ödülü.
Unity istemcisi ödülü (EventUnityClientRewardQuestCommand {nowQuests, afterQuests, beforeQuests}; ClaimUnityClientRewardRequest
  {questId}; bitince EventQuestCompletedCommand {eventType UnityClientReward, repeatableType DAILY}): 7 günlük program, her gün 3 görev
  (giriş, bir hedef ve gerçek oyunda ödeme: tek oyunculu uyarlama Uridium Bank'tan alım). Profil başına bir kez, ilk girişten başlar;
  önceki günlerin bitmiş görevlerinin ödülü sonra da alınır.
Profilde: mini_istemci {donem, gun, n}, aylik_deluxe {baslangic, alinan}, unity_odul {baslangic, deger, tamam, alinan}.
"""
import datetime, json, os, time

import gorev_takip as GT
import takvim as TK

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'biletler.json'), encoding='utf8'))
MINI, DELUXE, UNITY = D['mini_istemci'], D['aylik_deluxe'], D['unity_odul']
MINI_EVENT = D.get('mini_istemci_etkinlik', {})       # etkinlik -> kendi gün listesi (yoksa MINI)
UNITY_Q = {q['id']: q for day in UNITY for q in day}
DELUXE_ITEM = 'resource_monthly-deluxe'


def mod(name, **f):
    f['_'] = name
    return f


def today(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now)


def mini_list(now=None):
    """Süren Mini Client etkinliğinin gün listesi [[lootId, adet, özel]]."""
    return MINI_EVENT.get(mini_event(now)[0], MINI)


def mini_event(now=None):
    for k in sorted(TK.active(now)):
        if 'MiniClientReward' in TK.EVENTS[k].get('turler', []):
            p = TK.period(k, now)
            return k, ('%s-%d' % (k, time.localtime(p[0]).tm_year) if p else k)
    return None, None


class GunlukOdul:
    def __init__(self, profil, log=print):
        self.p, self.log = profil, log
        self.m = None
        self.send = None
        self.map_id = None

    def reward(self, loot, n):
        return self.m.reward(loot, n) if self.m else []

    # ------------------------------------------------------------ Mini Client
    def mini_state(self, now=None):
        k, pid = mini_event(now)
        if not k:
            return None
        st = self.p.d.setdefault('mini_istemci', {})
        if st.get('donem') != pid:
            with self.p.lock:
                st.clear()
                st.update(donem=pid, gun=None, n=0)
                self.p.dirty = True
        return st

    def mini_claimable(self, st, now=None):
        return st['n'] < len(mini_list(now)) and st['gun'] != today(now).isoformat()

    def mini_info(self, now=None):
        st = self.mini_state(now)
        if st is None:
            return None
        k, _ = mini_event(now)
        rows = [mod('MiniClientItemRewardModule', amount=n, special=s, lootId=l) for l, n, s in mini_list(now)]
        return ('MiniClientRewardInfoCommand', dict(rewardList=rows, isClaimable=self.mini_claimable(st, now),
                                                    timeToEndEvent=TK.time_left(k, now), daysClaimed=st['n']))

    def mini_claim(self, f=None):
        st = self.mini_state()
        if st is None or not self.mini_claimable(st):
            return [('MiniClientRewardDayInfoCommand', dict(isClaimable=False, daysClaimed=st['n'] if st else 0))]
        l, n, s = mini_list()[st['n']]
        with self.p.lock:
            st['n'] += 1
            st['gun'] = today().isoformat()
            self.p.dirty = True
        self.log('   Mini Client ödülü: gün %d %s x%d' % (st['n'], l, n))
        return self.reward(l, n) + [('MiniClientRewardDayInfoCommand', dict(isClaimable=False, daysClaimed=st['n']))]

    # ------------------------------------------------------------ Monthly Deluxe
    def deluxe_day(self, now=None):
        st = self.p.d.get('aylik_deluxe')
        if not st:
            return -1
        d = (today(now) - datetime.date.fromisoformat(st['baslangic'])).days
        return d if 0 <= d < len(DELUXE) else -1

    def deluxe_day_cmd(self, now=None):
        st = self.p.d.get('aylik_deluxe') or {}
        d = self.deluxe_day(now)
        return mod('MonthlyDeluxeDayInfoCommand', today=d, daysClaimed=list(st.get('alinan', [])) if d >= 0 else [],
                   isClaimable=d >= 0 and d not in st.get('alinan', []))

    def deluxe_day_msg(self, now=None):
        d = dict(self.deluxe_day_cmd(now))
        d.pop('_')
        return ('MonthlyDeluxeDayInfoCommand', d)

    def deluxe_info(self, now=None):
        now = time.time() if now is None else now
        st = self.p.d.get('aylik_deluxe')
        if st and self.deluxe_day(now) >= 0:
            end = datetime.datetime.combine(datetime.date.fromisoformat(st['baslangic']) + datetime.timedelta(days=len(DELUXE)),
                                            datetime.time()).timestamp()
            left = int(end - now)
        else:
            left = -int(now)                                          # kayıt: alınmamışken eksi
        rows = [mod('MonthlyDeluxeRewardModule', lootId=l, amount=n) for l, n in DELUXE]
        return ('MonthlyDeluxeInfoCommand', dict(rewardList=rows, dayInfoCommand=self.deluxe_day_cmd(now),
                                                 timeInfoCommand=mod('MonthlyDeluxeTimeInfoCommand', timeToPassEnd=left)))

    def grant_deluxe(self, n=1):
        """Mağazadan Monthly Deluxe: bugünden 28 gün (sürerken alınırsa bittiği gün başlar)."""
        st = self.p.d.get('aylik_deluxe')
        start = today()
        if st and self.deluxe_day() >= 0:
            start = datetime.date.fromisoformat(st['baslangic']) + datetime.timedelta(days=len(DELUXE))
            self.p.add_resource(DELUXE_ITEM, n)                          # sıradaki ay depoda (bitince başlar)
            return []
        with self.p.lock:
            self.p.d['aylik_deluxe'] = {'baslangic': start.isoformat(), 'alinan': []}
            self.p.dirty = True
        if n > 1:
            self.p.add_resource(DELUXE_ITEM, n - 1)                      # kalan aylar depoda (yoksa yalnız bir ay veriliyordu)
        self.log('   Monthly Deluxe başladı: %s' % start.isoformat())
        return [self.deluxe_info()]

    def deluxe_claim(self, f=None):
        st = self.p.d.get('aylik_deluxe')
        d = self.deluxe_day()
        if not st or d < 0 or d in st['alinan']:
            return [self.deluxe_day_msg()]
        l, n = DELUXE[d]
        with self.p.lock:
            st['alinan'].append(d)
            self.p.dirty = True
        self.log('   Monthly Deluxe günü %d: %s x%d' % (d + 1, l, n))
        return self.reward(l, n) + [self.deluxe_day_msg()]

    def deluxe_roll(self):
        """Biten aboneliğin yerine depodaki bir sonraki ay."""
        st = self.p.d.get('aylik_deluxe')
        if st and self.deluxe_day() < 0 and self.p.resource(DELUXE_ITEM) > 0:
            self.p.add_resource(DELUXE_ITEM, -1)
            with self.p.lock:
                self.p.d['aylik_deluxe'] = {'baslangic': today().isoformat(), 'alinan': []}
                self.p.dirty = True

    # ------------------------------------------------------------ Unity istemcisi ödülü
    @property
    def ust(self):
        st = self.p.d.setdefault('unity_odul', {})
        if not st:
            st.update(baslangic=today().isoformat(), deger={}, tamam=[], alinan=[])
            self.p.dirty = True
        return st

    def unity_day(self, now=None):
        return (today(now) - datetime.date.fromisoformat(self.ust['baslangic'])).days

    def unity_list(self, quests):
        st = self.ust
        return mod('EventQuestListCommand', quests=[
            mod('EventQuestDefinitionModule', module=GT.with_state(q, st['deger'].get(str(q['id']), {}), q['id'] in st['tamam']),
                completed=q['id'] in st['tamam'], claimed=q['id'] in st['alinan']) for q in quests])

    def unity_cmd(self, now=None):
        d = self.unity_day(now)
        now_q = UNITY[d] if 0 <= d < len(UNITY) else []
        return ('EventUnityClientRewardQuestCommand', dict(nowQuests=self.unity_list(now_q),
                                                           afterQuests=[self.unity_list(x) for x in UNITY[max(0, d + 1):]],
                                                           beforeQuests=[self.unity_list(x) for x in UNITY[:max(0, min(d, len(UNITY)))]]))

    def unity_event(self, kind, kw):
        d = self.unity_day()
        if not 0 <= d < len(UNITY):
            return []
        st, msgs, done = self.ust, [], []
        for q in UNITY[d]:
            if q['id'] in st['tamam']:
                continue
            m, fin = GT.advance(self.p, q['rootCase'], st['deger'].setdefault(str(q['id']), {}), kind, kw, self.map_id)
            msgs += m
            if fin:
                done.append(q['id'])
        for q in done:
            with self.p.lock:
                st['tamam'].append(q)
                self.p.dirty = True
            msgs.append(('EventQuestCompletedCommand', dict(eventType='UnityClientReward', repeatableType='DAILY')))
            self.log('   Unity istemcisi ödül görevi bitti: %d' % q)
        if done:
            msgs.append(self.unity_cmd())
        return msgs

    def unity_claim(self, f):
        qid = int(f.get('questId') or 0)
        st = self.ust
        if qid not in UNITY_Q or qid not in st['tamam'] or qid in st['alinan']:
            return [self.unity_cmd()]
        with self.p.lock:
            st['alinan'].append(qid)
            self.p.dirty = True
        msgs = []
        for r in UNITY_Q[qid]['rewards']:
            msgs += self.reward(r['lootId'], r['amount'])
        self.log('   Unity istemcisi ödülü alındı: %d' % qid)
        return msgs + [self.unity_cmd()]

    # ------------------------------------------------------------ oturum
    def login_msgs(self):
        self.deluxe_roll()
        msgs = [self.deluxe_info(), self.unity_cmd()]
        mi = self.mini_info()
        return msgs + ([mi] if mi else [])

    def event(self, kind, **kw):
        msgs = self.unity_event(kind, kw)
        if msgs and self.send:
            self.send(msgs)
        return msgs

    def grant(self, loot, n):
        if loot == DELUXE_ITEM:
            return self.grant_deluxe(n)
        return None

    def handle(self, name, f):
        fn = {'MiniClientRewardClaimRequest': self.mini_claim, 'MonthlyDeluxeClaimRequest': self.deluxe_claim,
              'ClaimUnityClientRewardRequest': self.unity_claim}.get(name)
        return fn(f) if fn else None
