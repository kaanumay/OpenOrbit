"""Renewal of the recurring daily rewards, so years without an update still feel like a live game.

What the real game gives us (the only sources: belgeler/arastirma; no public month-by-month lists exist, research 2026-11-05):
  - the daily login calendar: the client's rewards.xml, 12 monthly lists of 25 days (the client draws the list itself from the `month` of
    DailyLoginRewardDayCommand, the server cannot send other items);
  - the Monthly Deluxe list (28 days, recorded window), the Bonus Calendar (mini client) lists of Trial of Terrors (recorded),
    Thanksgiving and Prosperous (wiki); event calendars run 8-15 rewards (board-en FAQs);
  - the event currencies' drops (data/events.json, npc.json, extra_events.json).
The algorithm (all deterministic: the same month / event year always gives the same list):
  1. Daily login: the 12 real lists are permuted every year from 2027 (the lists of 2026 stay in their months): the two winter-themed
     lists (January, December: loading screen winter.jpg, Frost designs) swap every other year, the other ten move by 3 months a year
     (a step coprime with 10: a month meets all ten lists in ten years, never the same one twice in a row; within a year each list once).
  2. Value: in a real calendar every ordinary day is worth about the same, so an item's unit value is 1 / its amount there (the median
     over its occurrences); special days are worth the median ratio of the items that appear on both. Event currencies take the value of
     candy corn scaled by how much less / more of them drops.
  3. Monthly Deluxe: the recorded list keeps its shape (uridium every other day, the last day's equipment); every month the item days
     take another item of the same kind from the real reward pool with the same value (nice amounts: 2 significant digits, boosters keep
     their hours), the last day rotates among the real calendars' last-day equipment.
  4. Bonus Calendar: an event without its own real list takes the shape of the recorded Trial of Terrors list (15 days, special days 7,
     14, 15): the Halloween currency becomes the event's currency at the same value (or a same-value generic reward if it has none), the
     generic days are drawn again each year; an event with a real list keeps it in its recorded year and varies the same way later.
"""
import json, math, os, random, statistics, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
_load = lambda n: json.load(open(os.path.join(HERE, 'data', n), encoding='utf8'))
LOGIN = _load('daily_login.json')['months']
TICKETS = _load('tickets.json')
BASE_YEAR = 2026                       # the year of the client's rewards.xml lists
DELUXE_BASE = '2026-11'                # the month of the recorded Monthly Deluxe list
WINTER = (1, 12)
EVENT_CURRENCY_DROP = {'resource_collectable_candy-corn': 113.0, 'resource_collectable_golden-candy-corn': 2.0,
                       'resource_collectable_chaos-fragment': 56.0, 'resource_collectable_pulse-core': 8.0,
                       'resource_collectable_byte-remnant': 17.5}     # median drop per occurrence in the event data (2026-11-05)
HALLOWEEN = ('resource_collectable_candy-corn', 'resource_collectable_golden-candy-corn')


def login_set(year, month):
    """Which of the 12 real lists the daily login calendar shows (the client's `month`) in that month."""
    k = year - BASE_YEAR
    if k <= 0:
        return month
    if month in WINTER:
        return month if k % 2 == 0 else 13 - month
    return 2 + (month - 2 + 3 * k) % 10


def kind(loot):
    for pre, k in (('booster_', 'booster'), ('ammunition_laser_', 'laser'), ('ammunition_rocket', 'rocket'), ('ammunition_mine', 'mine'),
                   ('ammunition_', 'special'), ('resource_extra-energy', 'energy'), ('currency_', 'currency'),
                   ('equipment_', 'equipment'), ('pet_designs', 'design'), ('drone_designs', 'design'), ('ship_', 'design')):
        if loot.startswith(pre):
            return k
    return 'resource'


def _values():
    """Unit values from the real login calendars (an ordinary day = 1)."""
    normal, special = {}, {}
    for days in LOGIN.values():
        for r in days[:-1]:
            (special if r.get('special') else normal).setdefault(r['item'], []).append(r['count'])
    ratios = [statistics.median(special[i]) / statistics.median(normal[i]) for i in special if i in normal]
    sp = statistics.median(ratios) if ratios else 3.0
    val = {i: 1.0 / statistics.median(a) for i, a in normal.items()}
    for i, a in special.items():
        val.setdefault(i, sp / statistics.median(a))
    cc = 1.0 / 10000                                       # candy corn: an ordinary day of the recorded Bonus Calendar is 10,000
    for c, drop in EVENT_CURRENCY_DROP.items():
        val.setdefault(c, cc * EVENT_CURRENCY_DROP['resource_collectable_candy-corn'] / drop)
    for l, n, *f in TICKETS['mini_client']:                # the rest of the recorded Bonus Calendar
        val.setdefault(l, (sp if f and f[0] else 1.0) / n)
    for l, n in TICKETS['monthly_deluxe']:
        val.setdefault(l, 1.0 / n)
    return val, sp


VALUE, SPECIAL = _values()
FINALS = sorted({d[-1]['item'] for d in LOGIN.values() if kind(d[-1]['item']) == 'equipment'} |
                {d[-1]['premium']['item'] for d in LOGIN.values() if d[-1].get('premium') and kind(d[-1]['premium']['item']) == 'equipment'} |
                {TICKETS['monthly_deluxe'][-1][0]})
def _scale(rows):
    """A list's day in login days: the median of (its amount / the login day amount) over its items that are in the login calendars
    (the recorded Monthly Deluxe is about 4 login days a day, the Bonus Calendar about 1)."""
    r = [n * VALUE[l] for l, n, *_ in rows if l in VALUE and kind(l) not in ('currency', 'equipment', 'booster') and l not in HALLOWEEN]
    return statistics.median(r) if r else 1.0


DELUXE_DAY = _scale(TICKETS['monthly_deluxe'])
MINI_DAY = _scale(TICKETS['mini_client'])
POOL = sorted({r['item'] for d in LOGIN.values() for r in d[:-1] if kind(r['item']) in ('booster', 'laser', 'rocket', 'mine', 'energy',
                                                                                        'resource')} - set(HALLOWEEN))


def nice(n):
    """2 significant digits, at least 1 (5, 15, 250, 7,500 ...)."""
    if n < 1:
        return 1
    p = 10 ** max(0, int(math.log10(n)) - 1)
    return int(round(n / p) * p)


def _rng(*key):
    return random.Random(zlib.crc32(repr(key).encode()))


def swap(rng, loot, n, day, used=(), any_kind=False):
    """Another real reward of the same kind (any generic kind if any_kind) worth `day` login days (boosters keep their hours)."""
    k = kind(loot)
    cands = [i for i in POOL if (any_kind and kind(i) != 'booster' or kind(i) == k) and i != loot and i not in used] or [loot]
    new = rng.choice(cands)
    if k == 'booster' and not any_kind:
        return new, n
    return new, nice(day / VALUE.get(new, 1.0))


def deluxe_list(month_key):
    """The Monthly Deluxe list of a month ("YYYY-MM": the month the subscription started) [[lootId, count]]."""
    real = [list(x) for x in TICKETS['monthly_deluxe']]
    if month_key == DELUXE_BASE:
        return real
    rng = _rng('deluxe', month_key)
    out, used = [], set()
    for i, (loot, n) in enumerate(real):
        if i == len(real) - 1:
            out.append([rng.choice(FINALS), 1])
        elif kind(loot) == 'currency':
            out.append([loot, n])
        else:
            new, m = swap(rng, loot, n, DELUXE_DAY, used)
            used.add(new)
            out.append([new, m])
    return out


def mini_list(event, year, own=None, currency=()):
    """The Bonus Calendar of an event's run in a year [[lootId, count, special]]. own: the event's real list (and its year), currency:
    the event's currencies (events.json)."""
    real, real_year = own if own else (TICKETS['mini_client'], None)
    if own and year == real_year:
        return [list(x) for x in real]
    if not own and event == 'halloween' and year == BASE_YEAR:
        return [list(x) for x in TICKETS['mini_client']]
    rng = _rng('mini', event, year)
    cur = [c for c in currency if c in VALUE]
    out, used = [], set()
    for loot, n, sp in real:
        day = MINI_DAY * (SPECIAL if sp else 1.0)
        if loot in HALLOWEEN and event != 'halloween':
            if cur:                                        # the event's currency, as much as the Halloween currency was worth
                c = cur[min(len(cur) - 1, HALLOWEEN.index(loot))]
                out.append([c, nice(n * VALUE[loot] / VALUE[c]), sp])
                continue
            new, m = swap(rng, loot, n, day, used, any_kind=True)       # no currency: a generic reward of the same value
            used.add(new)
            out.append([new, m, sp])
            continue
        if loot in HALLOWEEN:                              # Trial of Terrors keeps its own currency days
            out.append([loot, n, sp])
            continue
        new, m = swap(rng, loot, n, day, used)
        used.add(new)
        out.append([new, m, sp])
    return out
