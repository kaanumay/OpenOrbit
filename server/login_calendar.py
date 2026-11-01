"""Günlük giriş takvimi (profilde "gunluk_giris"; ödüller data/daily_login.json ← istemcinin rewards.xml'i).

Kayıt: girişte DailyLoginRewardDayCommand {claimed, month, end, nextMonthSeconds, day} (yeni oyuncu: day 0, claimed False). Ödülü alma
(DailyLoginClaimTodayRequest -> DailyLoginClaimTodayCommand {err, claimed, day}) kayıtta yok: istemcinin koduna ve metinlerine göre.
`day` istemcide bugünün kutusunun sırasıdır (0'dan): alınmamışsa alınan gün sayısı, bugün alındıysa bir eksiği (canlı deneme
2026-10-17: ödülden sonra alınan gün sayısı gönderilince işaret bir sonraki güne kayıyordu).
Kural: her gerçek gün bir ödül (o ayın sıradaki günü), ay değişince takvim baştan (25 gün). nextMonthSeconds: kayıtta 2.678.400
(31 gün, ayın 15'inde): burada bir sonraki ayın başına kalan süre (uyarlama).
"""
import datetime, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, 'data', 'daily_login.json'), encoding='utf8'))
DAYS = 25


class DailyLogin:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.today = datetime.date.today          # testlerde değiştirilebilir

    def state(self):
        """Profildeki takvim: ay ("YYYY-MM"), alınan gün sayısı, son alınan tarih. Ay değişince baştan."""
        t = self.today()
        with self.p.lock:
            d = self.p.d.setdefault('daily_login', {'ay': '', 'gun': 0, 'last': ''})
            if d['ay'] != t.strftime('%Y-%m'):
                d.update(ay=t.strftime('%Y-%m'), gun=0)
                self.p.dirty = True
        return d

    def claimed_today(self):
        return self.state()['last'] == self.today().isoformat()

    def next_month_seconds(self):
        t = self.today()
        nxt = datetime.date(t.year + (t.month == 12), t.month % 12 + 1, 1)
        now = datetime.datetime.now()
        return max(0, int((datetime.datetime.combine(nxt, datetime.time()) - now).total_seconds()))

    def today_index(self):
        """Bugünün kutusu (istemcinin `day` alanı, 0'dan): bugün alındıysa son alınan gün."""
        d = self.state()
        return d['gun'] - 1 if self.claimed_today() and d['gun'] > 0 else d['gun']

    def fields(self):
        d = self.state()
        return dict(claimed=self.claimed_today(), month=self.today().month, end=d['gun'] >= DAYS,
                    nextMonthSeconds=self.next_month_seconds(), day=self.today_index())

    def info_cmd(self):
        return ('DailyLoginRewardDayCommand', self.fields())

    def claim(self):
        """DailyLoginClaimTodayRequest: bugünün ödülü (ayın sıradaki günü; son günde premium ödül de)."""
        d = self.state()
        if self.claimed_today() or d['gun'] >= DAYS:
            self.log('   günlük giriş: bugün alındı ya da takvim bitti (gün %d)' % d['gun'])
            return [('DailyLoginClaimTodayCommand', dict(err='already_claimed', claimed=False, day=self.today_index()))]
        reward = DATA['months'][str(self.today().month)][d['gun']]
        with self.p.lock:
            d['gun'] += 1
            d['last'] = self.today().isoformat()
            self.p.dirty = True
        msgs = self.m.reward(reward['esya'], reward['adet'])
        if reward.get('premium'):
            msgs += self.m.reward(reward['premium']['esya'], reward['premium']['adet'])
        self.log('   günlük giriş: %d. gün ödülü %s x%d%s' % (d['gun'], reward['esya'], reward['adet'],
                                                           ' + %s' % reward['premium']['esya'] if reward.get('premium') else ''))
        return [('DailyLoginClaimTodayCommand', dict(err='', claimed=True, day=self.today_index()))] + msgs + [self.info_cmd()]
