"""Daily login calendar (in the profile "daily_login"; rewards data/daily_login.json <- the client's rewards.xml).

Save: at login DailyLoginRewardDayCommand {claimed, month, end, nextMonthSeconds, day} (new player: day 0, claimed False). Claiming the reward
(DailyLoginClaimTodayRequest -> DailyLoginClaimTodayCommand {err, claimed, day}) is not in the save: based on the client's code and texts.
`day` is the index of today's box in the client (from 0): the number of claimed days if not claimed, one less if today's was claimed (live trial
2026-10-17: when the number of claimed days was sent after the reward, the marker shifted to the next day).
Rule: one reward per real day (the next day of that month), when the month changes the calendar starts over (25 days). nextMonthSeconds: 2,678,400 in the save
(31 days, on the 15th of the month): here the time left until the start of the next month (adaptation).
"""
import datetime, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, 'data', 'daily_login.json'), encoding='utf8'))
DAYS = 25


class DailyLogin:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.today = datetime.date.today          # can be changed in tests

    def state(self):
        """The calendar in the profile: month ("YYYY-MM"), number of days claimed, last claimed date. Starts over when the month changes."""
        t = self.today()
        with self.p.lock:
            d = self.p.d.setdefault('daily_login', {'ay': '', 'day': 0, 'last': ''})
            if d['ay'] != t.strftime('%Y-%m'):
                d.update(ay=t.strftime('%Y-%m'), day=0)
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
        """Today's box (the client's `day` field, from 0): if today's was claimed, the last claimed day."""
        d = self.state()
        return d['day'] - 1 if self.claimed_today() and d['day'] > 0 else d['day']

    def fields(self):
        d = self.state()
        return dict(claimed=self.claimed_today(), month=self.today().month, end=d['day'] >= DAYS,
                    nextMonthSeconds=self.next_month_seconds(), day=self.today_index())

    def info_cmd(self):
        return ('DailyLoginRewardDayCommand', self.fields())

    def claim(self):
        """DailyLoginClaimTodayRequest: today's reward (the next day of the month; on the last day the premium reward too)."""
        d = self.state()
        if self.claimed_today() or d['day'] >= DAYS:
            self.log('   daily login: claimed today or calendar finished (day %d)' % d['day'])
            return [('DailyLoginClaimTodayCommand', dict(err='already_claimed', claimed=False, day=self.today_index()))]
        reward = DATA['months'][str(self.today().month)][d['day']]
        with self.p.lock:
            d['day'] += 1
            d['last'] = self.today().isoformat()
            self.p.dirty = True
        msgs = self.m.reward(reward['item'], reward['count'])
        if reward.get('premium'):
            msgs += self.m.reward(reward['premium']['item'], reward['premium']['count'])
        self.log('   daily login: day %d reward %s x%d%s' % (d['day'], reward['item'], reward['count'],
                                                           ' + %s' % reward['premium']['item'] if reward.get('premium') else ''))
        return [('DailyLoginClaimTodayCommand', dict(err='', claimed=True, day=self.today_index()))] + msgs + [self.info_cmd()]
