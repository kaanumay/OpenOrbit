"""Panelin etkinlik takvimi (panel.py /api/takvim): etkinliklerin [bas, bit) içindeki açık aralıkları ve seansları.

- etkinlik: takvim.intervals (period ile aynı kural; panelin elle seçimi ayrı: panel 'durum' olarak verir)
- harita bölümleri ('harita', 'harita_ek'): kendi dönemleri ya da doğuş saatleri olanlar (takvim.section_intervals)
- büyük içeriklerin seansları: data/major_content.json ve extra_events.json. Kural oyundakiyle aynı (vortex.session,
  dunya_patronu.window, apotheosis.window, mimesis.run_state, unvan_avi.in_window) ama o modüller dünyayı yüklediği için veriden
  hesaplanır; test_event_calendar.py ikisini karşılaştırır.
Panelin seans_hep_acik ayarında seanslar ve doğuş saatleri hep açık (hep_acik).
Zamanlar yerel saatle; çıktı zaman damgası (saniye).
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
    """Günlük başlangıçlar [(başlangıç, gün)] — [a, b)'ye dokunan seanslar (önceki günün uzun seansı dahil)."""
    out = []
    for d in CAL._days(a, b):
        if d.weekday() in days:
            out += [(d + t, d) for t in times if d + t < b and d + t + datetime.timedelta(seconds=duration) > a]
    return out


def sessions(a, b):
    """Büyük içeriklerin seansları: [{'kimlik', 'etkinlik', 'araliklar': [[başlangıç, bitiş, işaret]]}] (datetime; işaret: vortex'te
    çift ödüllü seans 1, mimesis'te girişin kapanışı)."""
    out = []
    v = BIG_CONTENT.get('vortex')
    if v:
        duration, double = v.get('session_sec', 900), v.get('double_hour')
        out.append({'kimlik': 'vortex', 'etkinlik': v.get('etkinlik'), 'ranges': [
            [s, s + datetime.timedelta(seconds=duration), int(d.isoweekday() in v.get('double_days', []) and s - d == _hm(double or '99:00'))]
            for s, d in _starts(a, b, [_hm(x) for x in v.get('sessions', [])], duration=duration)]})
    for uid, key, day_list in (('world_boss', 'world_boss', range(7)), ('kristallon', 'kristallon_apotheosis', None)):
        p = BIG_CONTENT.get(key)
        if p:
            days = p.get('days', range(7)) if day_list is None else day_list
            out.append({'kimlik': uid, 'etkinlik': p.get('etkinlik'), 'ranges': [
                [d + _hm(x), d + _hm(y), 0] for d in CAL._days(a, b) if d.weekday() in days for x, y in p.get('windows', [])
                if d + _hm(x) < b and d + _hm(y) > a]})
    m = BIG_CONTENT.get('mimesis')
    if m:
        duration, entry = m.get('sure_sn', 2700), m.get('entry_sec', 300)
        out.append({'kimlik': 'mimesis', 'etkinlik': m.get('etkinlik'), 'ranges': [
            [s, s + datetime.timedelta(seconds=duration), s + datetime.timedelta(seconds=entry)]
            for s, _ in _starts(a, b, [datetime.timedelta(hours=h) for h in m.get('hours', [])], duration=duration)]})
    u = EX.get('title_hunt')
    if u:
        out.append({'kimlik': 'title_hunt', 'etkinlik': u.get('etkinlik', 'title_hunt'),
                    'ranges': [[s, e, 0] for s, e in CAL._daily(a, b, lambda d: u.get('hours', []))]})
    for x in out:
        x['ranges'] = [r for r in x['ranges'] if r[1] > a and r[0] < b]
    return out


def _sections(e):
    for k in ('harita', 'map_extra'):
        v = e.get(k)
        for s in (v if isinstance(v, list) else [v] if v else []):
            if 'hours' in s or 'donemler' in s:
                yield s


def _ts(r):
    return [x.timestamp() if isinstance(x, datetime.datetime) else x for x in r]


def _cut(iv, active):
    """Seans aralıklarını [başlangıç, bitiş, işaret] etkinliğin açık aralıklarıyla keser (işaret korunur)."""
    return [[max(s, p), min(e, q)] + r for s, e, *r in iv for p, q in active if max(s, p) < min(e, q)]


def schedule(start, bit, always_open=False, statuses=None):
    """[bas, bit) (zaman damgası) -> {anahtar: {'araliklar' (takvim), 'etkin' (elle seçimle: 'acik' bütün aralık, 'kapali' boş),
    'seanslar': [{'kimlik', 'tur', 'haritalar', 'araliklar' [[s, e, işaret]]}]}}. Seanslar yalnız etkinlik açıkken (oyundaki gibi).
    durumlar: anahtar -> panelin elle seçimi ('acik' / 'kapali'; yoksa takvim)."""
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
            out[k]['sessions'].append({'kimlik': 'map_%d' % i, 'tur': 'alien' if 'alien_spawns' in s else 'kutu' if 'boxes' in s else 'harita',
                                       'haritalar': s.get('haritalar', []), 'ranges': _cut(iv, out[k]['etkin'])})
    for x in sessions(a, b):
        if x['etkinlik'] in out:
            iv = [[start, bit, 0]] if always_open else [_ts(r) for r in x['ranges']]
            out[x['etkinlik']]['sessions'].append({'kimlik': x['kimlik'], 'tur': 'session', 'haritalar': [],
                                                   'ranges': _cut(iv, out[x['etkinlik']]['etkin'])})
    return out


def next_(key, now, day=400):
    """Etkinliğin şimdiki ya da sonraki aralığı [başlangıç, bitiş] (zaman damgası; 'gun' gün içinde yoksa None)."""
    a = datetime.datetime.fromtimestamp(now)
    iv = CAL.intervals(key, a, a + DAY * day)
    return _ts(iv[0]) if iv else None
