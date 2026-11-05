"""Monthly Astral Ascension and Eternal Black Light rankings: the period's score, the Rank tab and the payout at the month's end.

Real game: both rankings run by month (the client's title sets title_astralRankings-<mon><year>set1/2 and title_blacklightRankings-...,
data/ranking_rewards.json title_sets); the reward ranges and contents are the recorded / forum tables (ranking_rewards.json tables 9 and 7,
shown in the windows' reward tab); the top 5 get the month's ranking title. Astral's score is the total of the best three runs, Eternal
Black Light's the furthest wave.
Single-player adaptation: the other pilots of the ranking are the bot players (bot/modes.py runs the modes for them; Astral's run score
for a bot is its reached rifts x 500, the mean of the boss and time points); without bots the player is alone in it (rank 1). The payout
comes at the first moment the server sees the new month (online or at the next login): the rewards of the range, the title of the
month's set (the table's title if the client has no set for that month).
"""
import time

import rankings as RK

MODES = {'astral': dict(table=RK.ASTRAL, prefix='title_astralRankings-', name='Astral Ascension'),
         'ebl': dict(table=RK.EBL, prefix='title_blacklightRankings-', name='Eternal Black Light')}
BOT_ASTRAL_POINTS = 500                        # a bot's Astral run score per reached rift (adaptation)
MONTHS = RK.MONTHS


def month(now=None):
    return time.strftime('%Y-%m', time.localtime(now or time.time()))


def _entry(d, key):
    """The month's record in d (a profile's or a bot's): a new month keeps the old one as 'prev' (the payout reads it)."""
    e = d.get('month')
    if not e or e.get('key') != key:
        d['prev'] = e if e else d.get('prev')
        e = d['month'] = {'key': key, 'best': 0, 'runs': []}
    return e


def record(p, mode, value, now=None):
    """The player's result in the mode: Eternal Black Light a reached wave, Astral a finished run's points (the best three count)."""
    with p.lock:
        e = _entry(p.d.setdefault('monthly', {}).setdefault(mode, {}), month(now))
        if mode == 'astral':
            e['runs'] = sorted(e['runs'] + [int(value)], reverse=True)[:3]
            e['best'] = sum(e['runs'])
        else:
            e['best'] = max(e['best'], int(value))
        p.dirty = True


def record_bot(bot, mode, reached, now=None):
    from bot import modes as MD
    e = _entry(MD.state(bot, mode), month(now))
    if mode == 'astral':
        e['runs'] = sorted(e['runs'] + [int(reached) * BOT_ASTRAL_POINTS], reverse=True)[:3]
        e['best'] = sum(e['runs'])
    else:
        e['best'] = max(e['best'], int(reached))


def _value(d, key):
    for e in (d.get('month'), d.get('prev')):
        if e and e.get('key') == key:
            return int(e.get('best', 0))
    return 0


def rows(p, mode, key=None):
    """The month's ranking: [(rank, name, value, is_player)] of the player and the bot players with a result, best first."""
    import bot.manager as MGR
    key = key or month()
    out = [(p.d['pilot'].get('userName', ''), _value(p.d.get('monthly', {}).get(mode, {}), key), True)]
    y = MGR.ACTIVE
    if y is not None:
        with y.lock:
            out += [(b.name, _value((b.k.get('modes') or {}).get(mode, {}), key), False) for b in y.bots]
    out = sorted((r for r in out if r[1] > 0), key=lambda r: (-r[1], not r[2], str(r[0]).lower()))
    return [(i + 1,) + r for i, r in enumerate(out)]


def table(p, mode, key=None, count=10):
    """For a Rank tab: (the top rows, the player's row or (0, name, 0, True))."""
    r = rows(p, mode, key)
    me = next((x for x in r if x[3]), (0, p.d['pilot'].get('userName', ''), 0, True))
    return r[:count], me


def title_for(mode, key, default):
    """The month's set title (title_<x>Rankings-<mon><year>set1) when the client knows it, otherwise the table's."""
    y, m = key.split('-')
    t = '%s%s%sset1' % (MODES[mode]['prefix'], MONTHS[int(m) - 1], y)
    return t if t in RK.SET_TITLES else default


class MonthlyRankings:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.next = 0.0

    def login_msgs(self):
        return self.settle(time.time())

    def tick(self, now):
        if now < self.next:
            return []
        self.next = now + 60.0
        return self.settle(now)

    def settle(self, now):
        """A month that is over and not paid yet: the player's rank in it, the range's rewards and title."""
        msgs = []
        cur = month(now)
        for mode, info in MODES.items():
            d = self.p.d.get('monthly', {}).get(mode)
            if not d:
                continue
            e = d.get('month') if (d.get('month') or {}).get('key') != cur else d.get('prev')
            if not e or e.get('paid') or e.get('key') == cur or not e.get('best'):
                continue
            key = e['key']
            r = rows(self.p, mode, key)
            rank = next((x[0] for x in r if x[3]), 0)
            e['paid'] = True
            self.p.dirty = True
            rng = next((g for g in RK.TABLES.get(info['table'], {}).get('ranges', []) if g['from_'] <= rank <= g['e']), None)
            if rng is None:
                self.log('   monthly ranking %s %s: rank %d, no reward' % (info['name'], key, rank))
                continue
            for loot, n in rng['items']:
                if loot.startswith('currency_'):
                    kind = {'currency_uridium': 'uridium', 'currency_credits': 'credits', 'currency_honour': 'honor',
                            'currency_experience': 'ep'}.get(loot)
                    if kind:
                        self.p.gain(reason='ranking_reward', **{kind: int(n)})
                else:
                    msgs += self.m.reward(loot, int(n)) or []
            if rng.get('title'):
                import ranks as RT
                RT.grant_title(self.p, title_for(mode, key, rng['title']))
            self.log('   monthly ranking %s %s: rank %d, rewards paid' % (info['name'], key, rank))
        return msgs
