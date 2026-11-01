"""The panel's event calendar (panel.py /api/takvim): events' open intervals and sessions within [start, bit).

- event: event_calendar.intervals (same rule as period; the panel's manual choice is separate: the panel passes it as 'statuses')
- map sections ('map', 'map_extra'): those with their own periods or spawn times (event_calendar.section_intervals)
- sessions of major content: data/major_content.json and extra_events.json. The rule is the same as in the game (vortex.session,
  world_boss.window, apotheosis.window, mimesis.run_state, title_hunt.in_window) but since those modules load the world it is
  computed from the data; test_event_calendar.py compares the two.
With the panel's session_always_open setting sessions and spawn times are always open (always_open).
Times in local time; the output is a timestamp (seconds).
"""
import datetime, json, os

import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
DAY = datetime.timedelta(days=1)


def _data(name):
    try:
        return json.load(open(os.path.join(HERE, 'data', name), encoding='utf8'))
    except (OSError, ValueError):
        return {}


BIG_CONTENT, EX = _data('major_content.json'), _data('extra_events.json')


def _hm(s):
    h, m = s.split(':')
    return datetime.timedelta(hours=int(h), minutes=int(m))


def _starts(a, b, times, days=range(7), duration=0):
    """Daily starts [(start, day)] — sessions touching [a, b) (including the previous day's long session)."""
    out = []
    for d in CAL._days(a, b):
        if d.weekday() in days:
            out += [(d + t, d) for t in times if d + t < b and d + t + datetime.timedelta(seconds=duration) > a]
    return out


def sessions(a, b):
    """Sessions of major content: [{'uid', 'event', 'ranges': [[start, end, flag]]}] (datetime; flag: in vortex the
    double-reward session 1, in mimesis the closing of entry)."""
    out = []
    v = BIG_CONTENT.get('vortex')
    if v:
        duration, double = v.get('session_sec', 900), v.get('double_hour')
        out.append({'uid': 'vortex', 'event': v.get('event'), 'ranges': [
            [s, s + datetime.timedelta(seconds=duration), int(d.isoweekday() in v.get('double_days', []) and s - d == _hm(double or '99:00'))]
            for s, d in _starts(a, b, [_hm(x) for x in v.get('sessions', [])], duration=duration)]})
    for uid, key, day_list in (('world_boss', 'world_boss', range(7)), ('kristallon', 'kristallon_apotheosis', None)):
        p = BIG_CONTENT.get(key)
        if p:
            days = p.get('days', range(7)) if day_list is None else day_list
            out.append({'uid': uid, 'event': p.get('event'), 'ranges': [
                [d + _hm(x), d + _hm(y), 0] for d in CAL._days(a, b) if d.weekday() in days for x, y in p.get('windows', [])
                if d + _hm(x) < b and d + _hm(y) > a]})
    m = BIG_CONTENT.get('mimesis')
    if m:
        duration, entry = m.get('sure_sn', 2700), m.get('entry_sec', 300)
        out.append({'uid': 'mimesis', 'event': m.get('event'), 'ranges': [
            [s, s + datetime.timedelta(seconds=duration), s + datetime.timedelta(seconds=entry)]
            for s, _ in _starts(a, b, [datetime.timedelta(hours=h) for h in m.get('hours', [])], duration=duration)]})
    u = EX.get('title_hunt')
    if u:
        out.append({'uid': 'title_hunt', 'event': u.get('event', 'title_hunt'),
                    'ranges': [[s, e, 0] for s, e in CAL._daily(a, b, lambda d: u.get('hours', []))]})
    for x in out:
        x['ranges'] = [r for r in x['ranges'] if r[1] > a and r[0] < b]
    return out


def _sections(e):
    for k in ('map', 'map_extra'):
        v = e.get(k)
        for s in (v if isinstance(v, list) else [v] if v else []):
            if 'hours' in s or 'periods' in s:
                yield s


def _ts(r):
    return [x.timestamp() if isinstance(x, datetime.datetime) else x for x in r]


def _cut(iv, active):
    """Cuts session intervals [start, end, flag] with the event's open intervals (the flag is kept)."""
    return [[max(s, p), min(e, q)] + r for s, e, *r in iv for p, q in active if max(s, p) < min(e, q)]


def schedule(start, bit, always_open=False, statuses=None):
    """[start, bit) (timestamp) -> {key: {'ranges' (calendar), 'etkin' (with manual choice: 'on' the whole interval, 'off' empty),
    'sessions': [{'uid', 'type', 'maps', 'ranges' [[s, e, flag]]}]}}. Sessions only while the event is open (as in the game).
    statuses: key -> the panel's manual choice ('on' / 'off'; if absent the calendar)."""
    a, b = datetime.datetime.fromtimestamp(start), datetime.datetime.fromtimestamp(bit)
    statuses = statuses or {}
    out = {}
    for k in CAL.EVENTS:
        iv = [_ts(r) for r in CAL.intervals(k, a, b)]
        st = statuses.get(k)
        out[k] = {'ranges': iv, 'etkin': [[start, bit]] if st == 'on' else [] if st == 'off' else iv, 'sessions': []}
    for k, e in CAL.EVENTS.items():
        for i, s in enumerate(_sections(e)):
            iv = [_ts(r) + [0] for r in CAL.section_intervals(s, a, b, always_open)]
            out[k]['sessions'].append({'uid': 'map_%d' % i, 'type': 'alien' if 'alien_spawns' in s else 'box' if 'boxes' in s else 'map',
                                       'maps': s.get('maps', []), 'ranges': _cut(iv, out[k]['etkin'])})
    for x in sessions(a, b):
        if x['event'] in out:
            iv = [[start, bit, 0]] if always_open else [_ts(r) for r in x['ranges']]
            out[x['event']]['sessions'].append({'uid': x['uid'], 'type': 'session', 'maps': [],
                                                   'ranges': _cut(iv, out[x['event']]['etkin'])})
    return out


def next_(key, now, day=400):
    """The event's current or next interval [start, end] (timestamp; None if none within `day` days)."""
    a = datetime.datetime.fromtimestamp(now)
    iv = CAL.intervals(key, a, a + DAY * day)
    return _ts(iv[0]) if iv else None
