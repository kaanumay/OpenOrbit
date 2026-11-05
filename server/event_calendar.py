"""Event calendar (roadmap stage 7, E8; data data/events.json).

An event is active either on certain days of the year ('periods': [[start, end]], end day included; a period may span the new year) or on
certain days of the week and at certain hours; hours are in local time. A period end is:
  - "MM-DD": every year
  - "YYYY-MM-DD": that year only (runs of the real game). After the last known day ('known_calendar') the years go on from the real
    history: the event's seasons (a year ending at 'known_calendar') take turns, the last one first, then the ones before it, so each
    future year has a layout the real game really ran (Agatus' months, Empyrian's 4 or 6 runs ...). A run keeps its place in the year: the
    same date, moved to the same weekday (at most 3 days; an event that starts on a Wednesday after the sync stays on a Wednesday). Before,
    the last 52 weeks repeated in 52-week steps and slid a day earlier every year (Halloween would have started on 26 September in 2040).
    Only the event's mature seasons take part (at least 60% of the last season's runs: a launch year with two runs does not come back for a
    monthly event); an event that did not run in the last season has ended in the real game and does not come back (Mileage Market,
    Summons of Athena). Seasons before 'history_start' are not complete and are not used. A period whose third element is "single" does
    not repeat (the new server's Europa ranking)
  - "easter+N", "chinese_new_year-N", "thanksgiving_day+N": N days after / before that year's holiday (Thanksgiving is the 4th Thursday of November)
A period's third element is the hours of those days ([[start, end]]; an end beyond 24 spills into the next day). Weekly: 'days'
(0=Monday), 'hours', 'nth_of_month' (which such weekday of the month: [1, 3] = the 1st and 3rd Friday of the month), 'week_cycle' [n, i] (the i-th week of an
n-week cycle, counted from WEEK_START), 'block_cycle' [n, i] (the i-th half-week block of an n-block cycle; blocks are Monday-Wednesday and
Thursday-Sunday: the booty box rotation), 'week_pattern' {start (a Thursday), pattern, letter, span} (a real weekly sequence repeated:
the event runs the span days from each Thursday whose letter in the pattern is its own), 'together' (only while one of these events runs), 'counts_as' (the name of another event:
while this event runs that one also counts as active; GG Double Rewards on Thanksgiving). Map sections may also have their own 'periods' and spawn hours ('hours',
'hours_weekend') (window; the panel's session_always_open setting removes the hours, in a forced-open event neither applies).
Active events:
  - to the client EventUpdateCommand {timestamp, activeCommands [EventModule {type, id, timeLeft, lang}], utcTimeOffset}: permanent
    feature flags ('continuous') and the client types of the active events (the remaining time runs to the end of the period); Command Center news
    with BE_<news id> types (news)
  - map decorations: EventActivationStateCommand (the event's 'decor'; mood_cmds)
  - achievements (achievement.ACTIVE_EVENTS): the event's 'achievement' groups
  - systems: Upgrade Hour, Dispatch Day, gate energy discount, Kronos day, gold box, map events, Battle Pass ...
The player's choice: the admin panel's Events page (settings.py event_state: for each event on / off / by calendar;
all yearly and weekly events; reported at login) comes first. Game server option: --event name1,name2 opens them
regardless of date (weekly ones too); --event all opens all yearly events, --event none opens no yearly event (weekly ones continue).
"""
import datetime, functools, json, os, sys, time
import game_data as DATA

import settings as SET
import event_appearances as EG

HERE = os.path.dirname(os.path.abspath(__file__))
D = DATA.load('events.json')       # World Editor: periods, map section, state in the world (world_status)
EVENTS = D['events']
EG.apply(EVENTS)                        # event appearances: the designs of the GG weekend gates and the map boxes
ALWAYS = D['continuous']['kinds']
COUNTED_AS = {}                            # event -> events that also count in its place ('counts_as': gg_double_reward on Thanksgiving)
for _k, _e in EVENTS.items():
    if _e.get('counts_as'):
        COUNTED_AS.setdefault(_e['counts_as'], []).append(_k)
FORCED, MODE = set(), 'calendar'          # calendar | all | none (for yearly ones)
# week cycles ('week_cycle') are counted from this Monday; ISO week parity left a three-week gap in a 53-week year (2026)
WEEK_START = datetime.date(2024, 1, 8)
DAY = datetime.timedelta(days=1)
KNOWN = datetime.datetime.strptime(D['known_calendar'], '%Y-%m-%d') + DAY     # end of the last known day (year-specific periods)
HISTORY_START = datetime.datetime.strptime(D.get('history_start', '2023-01-01'), '%Y-%m-%d')   # the dated runs are complete from here
MATURE = 0.6                          # a past season takes part in the rotation with at least this share of the last season's runs
# Chinese New Year (lunar calendar; in years outside the table that period does not exist)
CNY = {2020: (1, 25), 2021: (2, 12), 2022: (2, 1), 2023: (1, 22), 2024: (2, 10), 2025: (1, 29), 2026: (2, 17), 2027: (2, 6),
       2028: (1, 26), 2029: (2, 13), 2030: (2, 3), 2031: (1, 23), 2032: (2, 11), 2033: (1, 31), 2034: (2, 19), 2035: (2, 8),
       2036: (1, 28), 2037: (2, 15), 2038: (2, 4), 2039: (1, 24), 2040: (2, 12)}
EVENT_IDS = {}                        # EventModule.id: fixed per type name
# Events kept alive by the Battle Pass {event: (pass start, end)} (battle_pass.ensure): the save's pass starts from day 1 and lasts as long as the panel's
# duration; since its quests depend on the event's content, the event also counts as open for that time (if it is not 'off' in the panel)
PASS_RUNS = {}


def _pass_run(key, t):
    r = PASS_RUNS.get(key)
    return bool(r) and r[0] <= t < r[1]


def _tags(e):
    """Features an event can have on its own: Battle Pass (the save's single pass), map decoration (one decoration per EventActivationState type),
    the look of the alien cargo box (CandyCargo / cargo_kind: the box has a single look)."""
    out = {'pass'} if 'BattlePass' in e.get('kinds', []) else set()
    if 'decor' in e:
        out.add('sus:%s' % e['decor']['type'])
    secs = ([e['map']] if isinstance(e.get('map'), dict) else []) + e.get('map_extra', [])
    if 'CandyCargo' in e.get('kinds', []) or any(s.get('cargo_kind') for s in secs):
        out.add('cargo')
    return out


# Conflicting events (developer note 2026-10-28, N1): they cannot be open at the same time; if both would be open, the higher-priority one stays
# (resolve: the one opened by hand in the panel, then the one kept alive by the save's Battle Pass, then the one that started first). When the panel opens one by hand
# those opened by hand that conflict with it return to the calendar (panel.set_events).
CONFLICTS = {k: {j for j, f in EVENTS.items() if j != k and _tags(e) & _tags(f)} for k, e in EVENTS.items()}


def configure(argv=None):
    """The --event option: 'all', 'none' or comma-separated event names."""
    global MODE
    argv = sys.argv if argv is None else argv
    FORCED.clear()
    MODE = 'calendar'
    for i, a in enumerate(argv):
        val = a.split('=', 1)[1] if a.startswith('--event=') else (argv[i + 1] if a == '--event' and i + 1 < len(argv) else None)
        if val is None:
            continue
        for x in val.split(','):
            x = x.strip().lower()
            if x in ('all', 'none'):
                MODE = x
            elif x in EVENTS:
                FORCED.add(x)


def _dt(now):
    return datetime.datetime.fromtimestamp(time.time() if now is None else now)


def _easter(y):
    """Paskalya (Gregoryen; anonim algoritma)."""
    a, b, c = y % 19, y // 100, y % 100
    h = (19 * a + b - b // 4 - (b - (b + 8) // 25 + 1) // 3 + 15) % 30
    l = (32 + 2 * (b % 4) + 2 * (c // 4) - h - c % 4) % 7
    m = (a + 11 * h + 22 * l) // 451
    return datetime.date(y, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)


def _thanksgiving(y):
    first = datetime.date(y, 11, 1)
    return first + datetime.timedelta(days=(3 - first.weekday()) % 7 + 21)


def _new_moon(k):
    """The k-th new moon after January 2000 (Meeus, Astronomical Algorithms ch. 49, the main terms): UTC datetime (within minutes)."""
    import math
    T = k / 1236.85
    jde = 2451550.09766 + 29.530588861 * k + 0.00015437 * T * T
    E = 1 - 0.002516 * T
    rad = math.radians
    M = rad(2.5534 + 29.10535670 * k)
    Mp = rad(201.5643 + 385.81693528 * k + 0.0107582 * T * T)
    F = rad(160.7108 + 390.67050284 * k - 0.0016118 * T * T)
    Om = rad(124.7746 - 1.56375588 * k)
    jde += (-0.40720 * math.sin(Mp) + 0.17241 * E * math.sin(M) + 0.01608 * math.sin(2 * Mp) + 0.01039 * math.sin(2 * F)
            + 0.00739 * E * math.sin(Mp - M) - 0.00514 * E * math.sin(Mp + M) + 0.00208 * E * E * math.sin(2 * M)
            - 0.00111 * math.sin(Mp - 2 * F) - 0.00057 * math.sin(Mp + 2 * F) + 0.00056 * E * math.sin(2 * Mp + M)
            - 0.00042 * math.sin(3 * Mp) + 0.00042 * E * math.sin(M + 2 * F) + 0.00038 * E * math.sin(M - 2 * F)
            - 0.00024 * E * math.sin(2 * Mp - M) - 0.00017 * math.sin(Om))
    return datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=jde - 2451545.0 - 69 / 86400.0)


def _cny(y):
    """Chinese New Year: the table, otherwise the first new moon (China time, UTC+8) on or after 21 January (the second new moon after
    the winter solstice; agrees with the table for 2020-2040). Years after the table no longer lose Prosperous."""
    if y in CNY:
        return datetime.date(y, *CNY[y])
    k = int(round((y - 2000) * 12.3685)) - 1
    while True:
        d = (_new_moon(k) + datetime.timedelta(hours=8)).date()
        if d >= datetime.date(y, 1, 21):
            return d
        k += 1


HOLIDAYS = {'easter': _easter, 'thanksgiving_day': _thanksgiving, 'chinese_new_year': _cny}


def _day(s, y):
    """A yearly period end ("MM-DD" or "holiday±N") in year y -> datetime (None if there is none)."""
    name, sign, n = s.partition('+') if '+' in s else s.partition('-') if s[0].isalpha() else (s, '', '')
    if name in HOLIDAYS:
        d = HOLIDAYS[name](y)
        return d and datetime.datetime.combine(d, datetime.time()) + (DAY * int(n or 0) * (-1 if sign == '-' else 1))
    m, d = s.split('-')
    return datetime.datetime(y, int(m), int(d))


@functools.lru_cache(maxsize=4096)
def _date(s, fmt):
    """Parsing fixed date text (strptime is expensive; event queries run thousands of times per second: bots)."""
    return datetime.datetime.strptime(s, fmt)


_SPANS = {}                                     # id(period list) -> (list, (year, cycle), periods): event queries are frequent (bots)


def _add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:                          # 29 February
        return d.replace(year=d.year + n, day=28)


def season(x):
    """The season of a moment: 1 = the first year after 'known_calendar', 0 = the last known year, -1 the one before ..."""
    n = x.year - KNOWN.year
    if x < _add_years(KNOWN, n):
        n -= 1
    return n + 1


def _project(run, years):
    """A past run moved by whole years: the same date, then to the same weekday (at most 3 days)."""
    s, e, h = run
    base = _add_years(s, years)
    delta = (s.weekday() - base.weekday()) % 7
    if delta > 3:
        delta -= 7
    start = base + datetime.timedelta(days=delta)
    return start, start + (e - s), h


def _sources(dated):
    """The event's real seasons -> runs, and the rotation order (the last season first; only mature, complete seasons; empty if the
    event did not run in the last season)."""
    by = {}
    for r in dated:
        h = season(r[0])
        if h <= 0 and _add_years(KNOWN, h - 1) >= HISTORY_START:
            by.setdefault(h, []).append(r)
    if 0 not in by:
        return by, []
    need = MATURE * len(by[0])
    return by, [h for h in sorted(by, reverse=True) if len(by[h]) >= need]


def _spans(entries, t):
    """Periods that may contain t [(start, end, hours)] (datetime; end excluded). The result depends only on t's year and season:
    cached per list (callers only read)."""
    k = (t.year, season(t) if t >= KNOWN else None)
    c = _SPANS.get(id(entries))
    if c and c[0] is entries and c[1] == k:
        return c[2]
    if len(_SPANS) > 512:
        _SPANS.clear()
    out = _compute_spans(entries, t)
    _SPANS[id(entries)] = (entries, k, out)
    return out


def _compute_spans(entries, t):
    out, dated, once = [], [], []
    for a, b, *h in entries:
        if a[:4].isdigit() and len(a) in (10, 16):          # 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (first day with an hour: Chromin 10:00)
            s = _date(a, '%Y-%m-%d %H:%M' if len(a) == 16 else '%Y-%m-%d')
            e = _date(b, '%Y-%m-%d %H:%M') if len(b) == 16 else _date(b, '%Y-%m-%d') + DAY
            (once if h[:1] == ['single'] else dated).append((s, e, h[1:] if h[:1] == ['single'] else h))
            continue
        for y in (t.year - 1, t.year):
            s, e = _day(a, y), _day(b, y)
            if s and e:
                out.append((s, (e if e >= s else _day(b, y + 1)) + DAY, h))
    if dated and t >= KNOWN:                    # after the last known day: the real seasons take turns (see the module's text)
        by, order = _sources(dated)
        proj = []
        for s in (season(t) - 1, season(t)):
            if s >= 1 and order:
                src = order[(s - 1) % len(order)]
                proj += [p for p in (_project(r, s - src) for r in by[src]) if p[1] > KNOWN]
        # a run already announced for those days replaces the projected one (Chromin 2026-11-02..08 against 2025-11-04 a year later); a
        # long projected run goes on after the announced one when at least half of it is left (Kristallon Apotheosis: permanent content)
        for p in proj:
            hit = [e for s, e, _ in dated if p[0] < e and s < p[1]]
            if not hit:
                out.append(p)
            elif (p[1] - max(hit)) * 2 >= p[1] - p[0]:
                out.append((max(hit), p[1], p[2]))
    return out + dated + once


def _hours(t, hours, first=None, last=None):
    """The hour window that covers t (start, end) or None; hours: [[a, b]] or day -> [[a, b]]. The previous day's window that runs past 24
    also counts; first/last: the day the window started on must be in this range."""
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in (day - DAY, day):
        if first and not first <= d < last:
            continue
        for a, b in hours(d) if callable(hours) else hours:
            s, e = d + datetime.timedelta(hours=a), d + datetime.timedelta(hours=b)
            if s <= t < e:
                return s, e
    return None


def _span_at(entries, t):
    for s, e, h in _spans(entries, t):
        if s <= t < e:
            return _hours(t, h[0], s, e) if h else (s, e)
    return None


def _week_day(e, d):
    """Whether the weekly event is on this day ('days', 'nth_of_month', 'week_cycle')."""
    if d.weekday() not in e.get('days', range(7)) or (e.get('nth_of_month') and (d.day - 1) // 7 + 1 not in e['nth_of_month']):
        return False
    if e.get('week_pattern'):                    # a real weekly sequence repeated (bp-calendar's shop sales: Thursday-Monday blocks)
        w = e['week_pattern']
        th = d.date() - datetime.timedelta(days=(d.weekday() - 3) % 7)          # the block's Thursday
        if (d.date() - th).days >= w.get('span', 5):
            return False
        k = (th - datetime.date.fromisoformat(w['start'])).days // 7 % len(w['pattern'])
        return w['pattern'][k] == w['letter']
    if e.get('block_cycle'):                     # half-week blocks Monday-Wednesday / Thursday-Sunday (the booty box rotation)
        n, i = e['block_cycle']
        if (2 * ((d.date() - WEEK_START).days // 7) + (d.weekday() >= 3)) % n != i:
            return False
    n, i = e.get('week_cycle', (1, 0))
    return (d.date() - WEEK_START).days // 7 % n == i


def period(key, now=None):
    """The event's current period (None if there is none): (start, end) timestamps; end excluded."""
    e, t = EVENTS[key], _dt(now)
    if e.get('together') and not any(_on(k, now) for k in e['together']):       # only while one of these events runs (Fever)
        return None
    if 'periods' in e:
        p = _span_at(e['periods'], t)
    else:
        p = _hours(t, lambda d: e.get('hours', [[0, 24]]) if _week_day(e, d) else [])
    if p:
        return p[0].timestamp(), p[1].timestamp()
    return next(filter(None, (period(k, now) for k in COUNTED_AS.get(key, ()))), None)      # 'counts_as': the period of the event that counts in its place


def window(s, now=None):
    """Whether the map section is open now: its own 'periods' and spawn hours ('hours', weekend 'hours_weekend'). If the panel's
    session_always_open setting is on, only the periods."""
    t = _dt(now)
    if 'periods' in s and not _span_at(s['periods'], t):
        return False
    if 'hours' not in s or SET.get('session_always_open'):
        return True
    return _hours(t, lambda d: s.get('hours_weekend', s['hours']) if d.weekday() >= 5 else s['hours']) is not None


def upcoming(key, now=None, days=366):
    """The event's periods within the next 'days' days from now [(start, end)] (datetime; excluding daily hours; panel)."""
    e, t = EVENTS[key], _dt(now)
    if 'periods' not in e:
        return []
    end = t + DAY * days
    found = {(s, f) for x in (t, t + DAY * (days // 2), end) for s, f, h in _spans(e['periods'], x) if f > t and s < end}
    return sorted(found)


# ------------------------------------------------------------------ intervals (the panel's event calendar)
def _merge(iv):
    out = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _clip(iv, a, b):
    return [[max(s, a), min(e, b)] for s, e in iv if e > a and s < b]


def _intersect(x, y):
    """Intersection of two merged interval lists."""
    out, i, j = [], 0, 0
    while i < len(x) and j < len(y):
        s, e = max(x[i][0], y[j][0]), min(x[i][1], y[j][1])
        if s < e:
            out.append([s, e])
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return out


def _days(a, b):
    """Starts of the days touching [a, b) (including the previous day: hours beyond 24 spill into the next day)."""
    d = a.replace(hour=0, minute=0, second=0, microsecond=0) - DAY
    while d < b:
        yield d
        d += DAY


def _daily(a, b, hours):
    """Daily hour windows within [a, b); hours: day -> [[start, end]] (hours)."""
    return _merge(_clip([[d + datetime.timedelta(hours=x), d + datetime.timedelta(hours=y)] for d in _days(a, b) for x, y in hours(d)],
                        a, b))


def _span_windows(entries, a, b):
    """The open intervals of the period list within [a, b) (same rule as _span_at; for a period with hours, the daily hours)."""
    found, t = {}, a - DAY * 7
    while True:                                   # _spans looks at t's year and 52-week cycle: sampled across the interval
        for s, e, h in _spans(entries, t):
            found[(s, e, json.dumps(h))] = h
        if t >= b:
            break
        t = min(t + DAY * 7, b)
    out = []
    for (s, e, _), h in found.items():
        if e <= a or s >= b:
            continue
        out += _daily(max(s, a - DAY), min(e, b), lambda d: h[0] if s <= d < e else []) if h else [[s, e]]
    return _merge(_clip(out, a, b))


def intervals(key, a, b):
    """The event's open intervals within [a, b) by the calendar [[start, end]] (datetime; merged and clipped). Same rule as period;
    the panel's manual choice and --event do not count ('together': intersection with the calendar intervals of those events)."""
    e = EVENTS[key]
    if 'periods' in e:
        iv = _span_windows(e['periods'], a, b)
    else:
        iv = _daily(a, b, lambda d: e.get('hours', [[0, 24]]) if _week_day(e, d) else [])
    iv = _merge(iv + [x for k in COUNTED_AS.get(key, ()) for x in intervals(k, a, b)])      # 'counts_as': the events that count in its place
    if e.get('together'):
        iv = _intersect(iv, _merge([x for k in e['together'] for x in intervals(k, a, b)]))
    return iv


def section_intervals(s, a, b, always_open=False):
    """The map section's open intervals within [a, b) (same rule as window; always_open: the panel's session_always_open setting)."""
    iv = _span_windows(s['periods'], a, b) if 'periods' in s else [[a, b]]
    if 'hours' in s and not always_open:
        iv = _intersect(iv, _daily(a, b, lambda d: s.get('hours_weekend', s['hours']) if d.weekday() >= 5 else s['hours']))
    return iv


def _rank(key, now):
    """Priority on conflict (smaller wins): the one opened by hand, the one kept alive by the Battle Pass, then the one whose period started first."""
    t = time.time() if now is None else now
    if SET.event_state(key) == 'on' or key in FORCED:
        top = 0
    elif _pass_run(key, t):
        top = 1
    else:
        top = 2
    p = period(key, now)
    return top, p[0] if p else 0, key


def resolve(on, rank):
    """Non-conflicting ones among the open events: in priority order, those that conflict with the remainder drop out."""
    keep = set(on)
    for k in sorted(on, key=rank):
        if k in keep:
            keep -= CONFLICTS.get(k, set())
    return keep


def is_active(key, now=None):
    """Whether the event is open: its own rule (_on) and the conflict (the higher-priority one among those open at the same time that conflict with it; within a connected component).
    Those named with --event (a developer option) ignore the conflict."""
    if not _on(key, now):
        return False
    if key in FORCED:
        return True
    comp, todo = {key}, [key]
    while todo:
        for j in CONFLICTS.get(todo.pop(), ()):
            if j not in comp and _on(j, now):
                comp.add(j)
                todo.append(j)
    return len(comp) == 1 or key in resolve(comp, lambda k: _rank(k, now))


def _on(key, now=None):
    e = EVENTS.get(key)
    if not e:
        return False
    st = SET.event_state(key)
    if st:
        return st == 'on'
    if e.get('world_status') in ('on', 'off'):     # the world's setting (after the save's Events setting)
        return e['world_status'] == 'on'
    yearly = 'periods' in e
    if key in FORCED or (yearly and MODE == 'all'):
        return True
    if yearly and MODE == 'none':
        return False
    if _pass_run(key, time.time() if now is None else now):
        return True
    return period(key, now) is not None


def forced(key):
    """Whether the event is open regardless of date ('on' in the panel, --event name or all): map sections' windows do not count."""
    st = SET.event_state(key)
    return st == 'on' or key in FORCED or (MODE == 'all' and 'periods' in EVENTS[key]) or (
        not st and EVENTS[key].get('world_status') == 'on')


_ACTIVE = [None, None]                  # (key, result): for the same moment (every second 14 event modules ask separately: extra_events)


def active(now=None):
    key = None
    if now is not None:
        key = (now, MODE, frozenset(FORCED), tuple(sorted(PASS_RUNS.items())),
               tuple(sorted((SET._current().get('events') or {}).items())))
        if _ACTIVE[0] == key:
            return set(_ACTIVE[1])
    on = {k for k in EVENTS if _on(k, now)}
    r = resolve(on, lambda k: _rank(k, now)) | (on & FORCED)
    if key is not None:
        _ACTIVE[:] = key, frozenset(r)
    return r


def has_type(t, now=None):
    """Whether the event type (EventModule.type, e.g. CandyCargo) is active now."""
    return t in ALWAYS or any(t in EVENTS[k].get('kinds', []) for k in active(now))


def time_left(key, now=None):
    """Remaining seconds (30 days for a forced-open event)."""
    p = period(key, now)
    now = time.time() if now is None else now
    if _pass_run(key, now):                             # event kept alive by the Battle Pass: until the pass ends
        return max(int(PASS_RUNS[key][1] - now), int(p[1] - now) if p else 0)
    return max(0, int(p[1] - now)) if p else 30 * 86400


def gate_rewards(key, now=None):
    """Galaxy Gate rewards of the active events ('gate_reward'): [(lootId, count, probability)] (Empyrian / Prosperous Fragment ...);
    excluding the bundle's items (gate_bundles)."""
    return [tuple(r) for k in sorted(active(now)) for s in EVENTS[k].get('gate_reward', []) if key in s['gates'] and not s.get('package')
            for r in s.get('items', [])]


def gate_choices(key, now=None):
    """The active events' choice rewards at this gate (the 'choice' of a 'gate_reward' row: one of [[lootId, count(, weight)]] with 'probability', equal if there is no weight;
    'non_repeating': a design the player owns does not drop): GG Special Rewards Weekend bundles, LF-4 day."""
    return [s for k in sorted(active(now)) for s in EVENTS[k].get('gate_reward', []) if key in s['gates'] and s.get('choice')]


def gate_bundles(key, now=None):
    """The active events' reward bundles at this gate ('gate_reward' row with a 'package' name: drops with 'probability', the 'items' entries
    [lootId, count, probability] with their own probabilities; Prosperous Package): when it drops the achievement's CollectPackage condition counts too (gate.finish)."""
    return [s for k in sorted(active(now)) for s in EVENTS[k].get('gate_reward', []) if key in s['gates'] and s.get('package')]


def achievement_groups(now=None):
    return {g for k in active(now) for g in EVENTS[k].get('achievement', [])}


MON = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
MONTH = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')


def news(key, now=None):
    """The Command Center news of this run of the event (bn_<id> in the client's resource_news; tools/calendar_e8.py): the 'news'
    pattern with the period's start ({Y}, {m}, {Mon}, {mon}, {Month}); if absent in the client 'news_default'; plus 'news_extra'."""
    e = EVENTS[key]
    if 'clan_news' not in e:
        return []
    p = period(key, now)
    d = datetime.date.fromtimestamp(p[0] if p else time.time() if now is None else now)
    ids = [x.format(Y=d.year, m='%02d' % d.month, Mon=MON[d.month - 1], mon=MON[d.month - 1].lower(), Month=MONTH[d.month - 1])
           for x in e['news']]
    main = next((x for x in ids if x in e['clan_news']), e.get('news_default'))
    return ([main] if main else []) + e.get('news_extra', [])


def _id(t):
    if t not in EVENT_IDS:
        EVENT_IDS[t] = 13000 + len(EVENT_IDS)
    return EVENT_IDS[t]


def event_cmd(now=None):
    """EventUpdateCommand (at login; in place of the command in the save)."""
    now = time.time() if now is None else now
    mods, seen = [], set()
    for t in ALWAYS:
        mods.append(dict(_='EventModule', type=t, timeLeft=210030 * 3600, id=_id(t), lang='all'))
        seen.add(t)
    for k in sorted(active(now)):
        left = time_left(k, now)
        for t in EVENTS[k].get('kinds', []) + ['BE_' + n for n in news(k, now)]:      # BE_<news id>: Command Center news
            if t not in seen:
                seen.add(t)
                mods.append(dict(_='EventModule', type=t, timeLeft=left, id=_id(t), lang='all'))
    offset = -time.timezone if not time.localtime(now).tm_isdst else -time.altzone        # seconds (save: 7200)
    return ('EventUpdateCommand', dict(timestamp=int(now * 1000), activeCommands=mods, utcTimeOffset=int(offset)))


def moods(keys):
    """The events' map decorations {the client's EventType: 'decor'} (Prometheus hologram, icebergs, Easter, Carnival, Breach)."""
    return {EVENTS[k]['decor']['type']: EVENTS[k]['decor'] for k in sorted(keys) if 'decor' in EVENTS[k]}


def mood_cmds(keys, before=None):
    """The decorations' EventActivationStateCommands (those open in the ready bundle; if 'before' is given, only those that open and close).
    'value': EventActivationIntegerAttributeModule (iceberg size)."""
    on, old = moods(keys), moods(before or ())
    cmd = lambda s, a: ('EventActivationStateCommand', dict(type=s['type'], active=a, attributes=[
        dict(_='EventActivationIntegerAttributeModule', value=s['value'])] if 'value' in s else []))
    return ([cmd(s, True) for t, s in sorted(on.items()) if before is None or t not in old]
            + [cmd(s, False) for t, s in sorted(old.items()) if t not in on])


configure()
