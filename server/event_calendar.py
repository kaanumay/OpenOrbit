"""Etkinlik takvimi (yol haritası Aşama 7, E8; veri data/events.json).

Bir etkinlik ya yılın belli günlerinde ('donemler': [[başlangıç, bitiş]], bitiş günü dahil; yılı aşan dönem olabilir) ya da haftanın
belli günlerinde ve saatlerinde etkindir; saatler yerel saatle. Dönem ucu:
  - "AA-GG": her yıl
  - "YYYY-AA-GG": yalnız o yıl (gerçek oyunun koşuları). Bilinen son günden ('takvim_bilinen') sonra son 52 haftanın koşuları 52
    haftalık adımlarla yinelenir (haftanın günü korunur: Çarşamba başlayan etkinlik yine Çarşamba başlar); üçüncü öğesi "tek" olan
    dönem yinelenmez (yeni sunucunun Europa sıralaması)
  - "paskalya+N", "cin_yeni_yili-N", "sukran_gunu+N": o yılın bayramından N gün sonra / önce (Kasım'ın 4. perşembesi)
Dönemin üçüncü öğesi o günlerin saatleri ([[başlangıç, bitiş]]; 24'ü aşan bitiş ertesi güne taşar). Haftalık: 'gunler'
(0=pazartesi), 'saatler', 'ay_haftasi' (ayın kaçıncı o günü: [1, 3] = ayın 1. ve 3. cuması), 'hafta_dongu' [n, i] (n haftalık
döngünün i. haftası, HAFTA_BASI'ndan sayılır), 'birlikte' (yalnız bu etkinliklerden biri sürerken), 'sayilir' (başka bir etkinliğin
adı: bu etkinlik sürerken o da etkin sayılır; Şükran Günü'nde GG Double Rewards). Harita bölümlerinin de kendi 'donemler'i ve doğuş saatleri ('saatler',
'saatler_hafta_sonu') olabilir (window; panelin seans_hep_acik ayarı saatleri kaldırır, zorla açılan etkinlikte ikisi de yok).
Etkin etkinlikler:
  - istemciye EventUpdateCommand {timestamp, activeCommands [EventModule {type, id, timeLeft, lang}], utcTimeOffset}: süresiz
    özellik bayrakları ('surekli') ve etkin etkinliklerin istemci türleri (kalan süre dönemin sonuna); Command Center haberleri
    BE_<haber kimliği> türleriyle (news)
  - harita süsleri: EventActivationStateCommand (etkinliğin 'sus'u; mood_cmds)
  - başarımlar (basarim.ACTIVE_EVENTS): etkinliğin 'basarim' grupları
  - sistemler: Upgrade Hour, Dispatch Day, kapı enerjisi indirimi, Kronos günü, altın kutu, harita etkinlikleri, Battle Pass …
Oyuncunun seçimi: yönetim panelinin Etkinlikler sayfası (settings.py event_state: her etkinlik için açık / kapalı / takvime göre;
yıllık ve haftalık etkinliklerin hepsi; oyuna girişte bildirilir) önce gelir. Oyun sunucusu seçeneği: --event ad1,ad2 tarihten
bağımsız açar (haftalıkları da); --event hepsi bütün yıllık etkinlikleri, --event yok hiçbir yıllık etkinliği açmaz (haftalıklar sürer).
"""
import datetime, functools, json, os, sys, time
import game_data as DATA

import settings as SET
import event_appearances as EG

HERE = os.path.dirname(os.path.abspath(__file__))
D = DATA.load('events.json')       # Dünya Editörü: dönemler, harita bölümü, dünyadaki durum (dunya_durum)
EVENTS = D['etkinlikler']
EG.apply(EVENTS)                        # etkinlik görünümleri: GG hafta sonu kapılarının ve harita kutularının tasarımları
ALWAYS = D['surekli']['turler']
COUNTED_AS = {}                            # etkinlik -> yerine de sayılan etkinlikler ('sayilir': Şükran Günü'nde gg_cift_odul)
for _k, _e in EVENTS.items():
    if _e.get('sayilir'):
        COUNTED_AS.setdefault(_e['sayilir'], []).append(_k)
FORCED, MODE = set(), 'takvim'          # takvim | hepsi | yok (yıllıklar için)
# hafta döngüleri ('hafta_dongu') bu pazartesiden sayılır; ISO hafta paritesi 53 haftalık yılda (2026) üç haftalık ara bırakıyordu
WEEK_START = datetime.date(2024, 1, 8)
DAY, CYCLE = datetime.timedelta(days=1), datetime.timedelta(weeks=52)
KNOWN = datetime.datetime.strptime(D['takvim_bilinen'], '%Y-%m-%d') + DAY     # bilinen son günün sonu (yıla özgü dönemler)
# Çin Yeni Yılı (ay takvimi; tablo dışındaki yıllarda o dönem yok)
CNY = {2020: (1, 25), 2021: (2, 12), 2022: (2, 1), 2023: (1, 22), 2024: (2, 10), 2025: (1, 29), 2026: (2, 17), 2027: (2, 6),
       2028: (1, 26), 2029: (2, 13), 2030: (2, 3), 2031: (1, 23), 2032: (2, 11), 2033: (1, 31), 2034: (2, 19), 2035: (2, 8),
       2036: (1, 28), 2037: (2, 15), 2038: (2, 4), 2039: (1, 24), 2040: (2, 12)}
EVENT_IDS = {}                        # EventModule.id: tür adı başına sabit
# Battle Pass'in sürdürdüğü etkinlikler {etkinlik: (pass'in başı, bitişi)} (savas_bileti.ensure): kaydın pass'i 1. günden başlayıp panelin
# süresince sürer; görevleri etkinliğin içeriğine bağlı olduğundan etkinlik de o süre boyunca açık sayılır (panelde 'kapali' değilse)
PASS_RUNS = {}


def _pass_run(key, t):
    r = PASS_RUNS.get(key)
    return bool(r) and r[0] <= t < r[1]


def _tags(e):
    """Etkinliğin tek başına olabilen özellikleri: Battle Pass (kaydın tek pass'i), harita süsü (EventActivationState türü başına
    bir süs), uzaylı kargo kutusunun görünümü (CandyCargo / kargo_tur: kutu tek görünümde)."""
    out = {'pass'} if 'BattlePass' in e.get('turler', []) else set()
    if 'sus' in e:
        out.add('sus:%s' % e['sus']['tur'])
    secs = ([e['harita']] if isinstance(e.get('harita'), dict) else []) + e.get('harita_ek', [])
    if 'CandyCargo' in e.get('turler', []) or any(s.get('kargo_tur') for s in secs):
        out.add('kargo')
    return out


# Çakışan etkinlikler (geliştirici notu 2026-10-28, N1): aynı anda açık olamazlar; ikisi de açık olacaksa öncelikli olan kalır
# (resolve: panelde elle açılan, sonra kaydın Battle Pass'inin sürdürdüğü, sonra önce başlayan). Panel birini elle açınca
# çakıştığı elle açılmışlar takvime döner (panel.set_events).
CONFLICTS = {k: {j for j, f in EVENTS.items() if j != k and _tags(e) & _tags(f)} for k, e in EVENTS.items()}


def configure(argv=None):
    """--event seçeneği: 'hepsi', 'yok' ya da virgülle etkinlik adları."""
    global MODE
    argv = sys.argv if argv is None else argv
    FORCED.clear()
    MODE = 'takvim'
    for i, a in enumerate(argv):
        val = a.split('=', 1)[1] if a.startswith('--event=') else (argv[i + 1] if a == '--event' and i + 1 < len(argv) else None)
        if val is None:
            continue
        for x in val.split(','):
            x = x.strip().lower()
            if x in ('hepsi', 'yok'):
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


HOLIDAYS = {'paskalya': _easter, 'sukran_gunu': _thanksgiving,
            'cin_yeni_yili': lambda y: datetime.date(y, *CNY[y]) if y in CNY else None}


def _day(s, y):
    """Yıllık dönem ucu ("AA-GG" ya da "bayram±N") y yılında -> datetime (yoksa None)."""
    name, sign, n = s.partition('+') if '+' in s else s.partition('-') if s[0].isalpha() else (s, '', '')
    if name in HOLIDAYS:
        d = HOLIDAYS[name](y)
        return d and datetime.datetime.combine(d, datetime.time()) + (DAY * int(n or 0) * (-1 if sign == '-' else 1))
    m, d = s.split('-')
    return datetime.datetime(y, int(m), int(d))


@functools.lru_cache(maxsize=4096)
def _date(s, fmt):
    """Sabit tarih metninin ayrıştırılması (strptime pahalı; etkinlik sorguları saniyede binlerce kez: botlar)."""
    return datetime.datetime.strptime(s, fmt)


_SPANS = {}                                     # id(dönem listesi) -> (liste, (yıl, döngü), dönemler): etkinlik sorguları sık (botlar)


def _spans(entries, t):
    """t'yi içerebilecek dönemler [(başlangıç, bitiş, saatler)] (datetime; bitiş hariç). Sonuç yalnız t'nin yılına ve 52 haftalık
    döngüsüne bağlı: liste başına önbellekte (çağıranlar yalnız okur)."""
    k = (t.year, (t - KNOWN) // CYCLE if t >= KNOWN else None)
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
        if a[:4].isdigit() and len(a) in (10, 16):          # 'YYYY-AA-GG' ya da 'YYYY-AA-GG SS:DD' (ilk gün saatle: Chromin 10:00)
            s = _date(a, '%Y-%m-%d %H:%M' if len(a) == 16 else '%Y-%m-%d')
            e = _date(b, '%Y-%m-%d %H:%M') if len(b) == 16 else _date(b, '%Y-%m-%d') + DAY
            (once if h[:1] == ['tek'] else dated).append((s, e, h[1:] if h[:1] == ['tek'] else h))
            continue
        for y in (t.year - 1, t.year):
            s, e = _day(a, y), _day(b, y)
            if s and e:
                out.append((s, (e if e >= s else _day(b, y + 1)) + DAY, h))
    if dated and t >= KNOWN:                    # bilinen son günden sonra: son 52 haftanın koşuları 52 haftada bir
        n = (t - KNOWN) // CYCLE + 1
        out += [(s + k * CYCLE, e + k * CYCLE, h) for s, e, h in dated if KNOWN - CYCLE <= s < KNOWN for k in (n - 1, n) if k]
    return out + dated + once


def _hours(t, hours, first=None, last=None):
    """t'yi kapsayan saat penceresi (başlangıç, bitiş) ya da None; hours: [[a, b]] ya da gün -> [[a, b]]. Önceki günün 24'ü aşan
    penceresi de sayılır; first/last: pencerenin başladığı gün bu aralıkta olmalı."""
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
    """Haftalık etkinlik bu gün var mı ('gunler', 'ay_haftasi', 'hafta_dongu')."""
    if d.weekday() not in e.get('gunler', range(7)) or (e.get('ay_haftasi') and (d.day - 1) // 7 + 1 not in e['ay_haftasi']):
        return False
    n, i = e.get('hafta_dongu', (1, 0))
    return (d.date() - WEEK_START).days // 7 % n == i


def period(key, now=None):
    """Etkinliğin şu anki (ya da yoksa None) dönemi: (başlangıç, bitiş) zaman damgası; bitiş hariç."""
    e, t = EVENTS[key], _dt(now)
    if e.get('birlikte') and not any(_on(k, now) for k in e['birlikte']):       # yalnız bu etkinliklerden biri sürerken (Fever)
        return None
    if 'donemler' in e:
        p = _span_at(e['donemler'], t)
    else:
        p = _hours(t, lambda d: e.get('saatler', [[0, 24]]) if _week_day(e, d) else [])
    if p:
        return p[0].timestamp(), p[1].timestamp()
    return next(filter(None, (period(k, now) for k in COUNTED_AS.get(key, ()))), None)      # 'sayilir': yerine sayılan etkinliğin dönemi


def window(s, now=None):
    """Harita bölümü şu an açık mı: kendi 'donemler'i ve doğuş saatleri ('saatler', hafta sonu 'saatler_hafta_sonu'). Panelin
    seans_hep_acik ayarı açıksa yalnız dönemler."""
    t = _dt(now)
    if 'donemler' in s and not _span_at(s['donemler'], t):
        return False
    if 'saatler' not in s or SET.get('seans_hep_acik'):
        return True
    return _hours(t, lambda d: s.get('saatler_hafta_sonu', s['saatler']) if d.weekday() >= 5 else s['saatler']) is not None


def upcoming(key, now=None, days=366):
    """Etkinliğin şimdiden sonraki 'days' gün içindeki dönemleri [(başlangıç, bitiş)] (datetime; günlük saatler hariç; panel)."""
    e, t = EVENTS[key], _dt(now)
    if 'donemler' not in e:
        return []
    end = t + DAY * days
    found = {(s, f) for x in (t, t + DAY * (days // 2), end) for s, f, h in _spans(e['donemler'], x) if f > t and s < end}
    return sorted(found)


# ------------------------------------------------------------------ aralıklar (panelin etkinlik takvimi: takvim_cizelge.py)
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
    """İki birleşik aralık listesinin kesişimi."""
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
    """[a, b)'ye dokunan günlerin başları (önceki gün dahil: 24'ü aşan saatler ertesi güne taşar)."""
    d = a.replace(hour=0, minute=0, second=0, microsecond=0) - DAY
    while d < b:
        yield d
        d += DAY


def _daily(a, b, hours):
    """Günlük saat pencereleri [a, b) içinde; hours: gün -> [[başlangıç, bitiş]] (saat)."""
    return _merge(_clip([[d + datetime.timedelta(hours=x), d + datetime.timedelta(hours=y)] for d in _days(a, b) for x, y in hours(d)],
                        a, b))


def _span_windows(entries, a, b):
    """Dönem listesinin [a, b) içindeki açık aralıkları (_span_at ile aynı kural; saatli dönemde günlük saatler)."""
    found, t = {}, a - DAY * 7
    while True:                                   # _spans t'nin yılına ve 52 haftalık döngüsüne bakar: aralık boyunca örneklenir
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
    """Etkinliğin takvime göre [a, b) içindeki açık aralıkları [[başlangıç, bitiş]] (datetime; birleşik ve kırpılmış). period ile aynı
    kural; panelin elle seçimi ve --event sayılmaz ('birlikte': o etkinliklerin takvimdeki aralıklarıyla kesişim)."""
    e = EVENTS[key]
    if 'donemler' in e:
        iv = _span_windows(e['donemler'], a, b)
    else:
        iv = _daily(a, b, lambda d: e.get('saatler', [[0, 24]]) if _week_day(e, d) else [])
    iv = _merge(iv + [x for k in COUNTED_AS.get(key, ()) for x in intervals(k, a, b)])      # 'sayilir': yerine sayılan etkinlikler
    if e.get('birlikte'):
        iv = _intersect(iv, _merge([x for k in e['birlikte'] for x in intervals(k, a, b)]))
    return iv


def section_intervals(s, a, b, always_open=False):
    """Harita bölümünün [a, b) içindeki açık aralıkları (window ile aynı kural; hep_acik: panelin seans_hep_acik ayarı)."""
    iv = _span_windows(s['donemler'], a, b) if 'donemler' in s else [[a, b]]
    if 'saatler' in s and not always_open:
        iv = _intersect(iv, _daily(a, b, lambda d: s.get('saatler_hafta_sonu', s['saatler']) if d.weekday() >= 5 else s['saatler']))
    return iv


def _rank(key, now):
    """Çakışmada öncelik (küçük kazanır): elle açılan, Battle Pass'in sürdürdüğü, sonra dönemi önce başlayan."""
    t = time.time() if now is None else now
    if SET.event_state(key) == 'acik' or key in FORCED:
        top = 0
    elif _pass_run(key, t):
        top = 1
    else:
        top = 2
    p = period(key, now)
    return top, p[0] if p else 0, key


def resolve(on, rank):
    """Açık etkinliklerden çakışmayanlar: öncelik sırasıyla, kalanın çakıştıkları düşer."""
    keep = set(on)
    for k in sorted(on, key=rank):
        if k in keep:
            keep -= CONFLICTS.get(k, set())
    return keep


def is_active(key, now=None):
    """Etkinlik açık mı: kendi kuralı (_on) ve çakışma (aynı anda açık çakışanlarından öncelikli olan; bağlı bileşen içinde).
    --event ile adı verilenler (geliştirici seçeneği) çakışmaya bakmaz."""
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
        return st == 'acik'
    if e.get('world_status') in ('acik', 'kapali'):     # dünyanın ayarı (kaydın Etkinlikler ayarından sonra)
        return e['world_status'] == 'acik'
    yearly = 'donemler' in e
    if key in FORCED or (yearly and MODE == 'hepsi'):
        return True
    if yearly and MODE == 'yok':
        return False
    if _pass_run(key, time.time() if now is None else now):
        return True
    return period(key, now) is not None


def forced(key):
    """Etkinlik tarihten bağımsız açık mı (panelde 'acik', --event ad ya da hepsi): harita bölümlerinin pencereleri sayılmaz."""
    st = SET.event_state(key)
    return st == 'acik' or key in FORCED or (MODE == 'hepsi' and 'donemler' in EVENTS[key]) or (
        not st and EVENTS[key].get('world_status') == 'acik')


_ACTIVE = [None, None]                  # (anahtar, sonuç): aynı an için (saniyede bir 14 etkinlik modülü ayrı ayrı sorar: ek_etkinlikler)


def active(now=None):
    key = None
    if now is not None:
        key = (now, MODE, frozenset(FORCED), tuple(sorted(PASS_RUNS.items())),
               tuple(sorted((SET._current().get('etkinlikler') or {}).items())))
        if _ACTIVE[0] == key:
            return set(_ACTIVE[1])
    on = {k for k in EVENTS if _on(k, now)}
    r = resolve(on, lambda k: _rank(k, now)) | (on & FORCED)
    if key is not None:
        _ACTIVE[:] = key, frozenset(r)
    return r


def has_type(t, now=None):
    """Etkinlik türü (EventModule.type, ör. CandyCargo) şu an etkin mi."""
    return t in ALWAYS or any(t in EVENTS[k].get('turler', []) for k in active(now))


def time_left(key, now=None):
    """Kalan saniye (zorla açılmış etkinlikte 30 gün)."""
    p = period(key, now)
    now = time.time() if now is None else now
    if _pass_run(key, now):                             # Battle Pass'in sürdürdüğü etkinlik: pass bitene dek
        return max(int(PASS_RUNS[key][1] - now), int(p[1] - now) if p else 0)
    return max(0, int(p[1] - now)) if p else 30 * 86400


def gate_rewards(key, now=None):
    """Etkin etkinliklerin Galaksi Kapısı ödülleri ('kapi_odulu'): [(lootId, adet, olasılık)] (Empyrian / Prosperous Fragment …);
    paketin kalemleri hariç (gate_bundles)."""
    return [tuple(r) for k in sorted(active(now)) for s in EVENTS[k].get('kapi_odulu', []) if key in s['kapilar'] and not s.get('paket')
            for r in s.get('esyalar', [])]


def gate_choices(key, now=None):
    """Etkin etkinliklerin bu kapıdaki seçimli ödülleri ('kapi_odulu' satırının 'secim'i: 'olasilik'la [[lootId, adet(, ağırlık)]]'ten biri, ağırlık yoksa eşit;
    'yinelenmez': sahip olunan tasarım çıkmaz): GG Special Rewards Weekend paketleri, LF-4 günü."""
    return [s for k in sorted(active(now)) for s in EVENTS[k].get('kapi_odulu', []) if key in s['kapilar'] and s.get('secim')]


def gate_bundles(key, now=None):
    """Etkin etkinliklerin bu kapıdaki ödül paketleri ('kapi_odulu' satırı 'paket' adıyla: 'olasilik'la düşer, 'esyalar' kalemleri
    [lootId, adet, olasılık] kendi olasılıklarıyla; Prosperous Package): düşünce başarımın CollectPackage koşulu da (kapi.finish)."""
    return [s for k in sorted(active(now)) for s in EVENTS[k].get('kapi_odulu', []) if key in s['kapilar'] and s.get('paket')]


def achievement_groups(now=None):
    return {g for k in active(now) for g in EVENTS[k].get('basarim', [])}


MON = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
MONTH = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')


def news(key, now=None):
    """Etkinliğin bu koşusunun Command Center haberleri (istemcinin resource_news'undaki bn_<kimlik>; tools/calendar_e8.py): 'haber'
    kalıbı dönemin başlangıcıyla ({Y}, {m}, {Mon}, {mon}, {Month}); istemcide yoksa 'haber_varsayilan'; artı 'haber_ek'."""
    e = EVENTS[key]
    if 'haberler' not in e:
        return []
    p = period(key, now)
    d = datetime.date.fromtimestamp(p[0] if p else time.time() if now is None else now)
    ids = [x.format(Y=d.year, m='%02d' % d.month, Mon=MON[d.month - 1], mon=MON[d.month - 1].lower(), Month=MONTH[d.month - 1])
           for x in e['haber']]
    main = next((x for x in ids if x in e['haberler']), e.get('haber_varsayilan'))
    return ([main] if main else []) + e.get('haber_ek', [])


def _id(t):
    if t not in EVENT_IDS:
        EVENT_IDS[t] = 13000 + len(EVENT_IDS)
    return EVENT_IDS[t]


def event_cmd(now=None):
    """EventUpdateCommand (girişte; kayıttaki komutun yerine)."""
    now = time.time() if now is None else now
    mods, seen = [], set()
    for t in ALWAYS:
        mods.append(dict(_='EventModule', type=t, timeLeft=210030 * 3600, id=_id(t), lang='all'))
        seen.add(t)
    for k in sorted(active(now)):
        left = time_left(k, now)
        for t in EVENTS[k].get('turler', []) + ['BE_' + n for n in news(k, now)]:      # BE_<kimlik>: Command Center haberi
            if t not in seen:
                seen.add(t)
                mods.append(dict(_='EventModule', type=t, timeLeft=left, id=_id(t), lang='all'))
    offset = -time.timezone if not time.localtime(now).tm_isdst else -time.altzone        # saniye (kayıt: 7200)
    return ('EventUpdateCommand', dict(timestamp=int(now * 1000), activeCommands=mods, utcTimeOffset=int(offset)))


def moods(keys):
    """Etkinliklerin harita süsleri {istemcinin EventType'ı: 'sus'} (Prometheus hologramı, buzdağları, Paskalya, Carnival, Breach)."""
    return {EVENTS[k]['sus']['tur']: EVENTS[k]['sus'] for k in sorted(keys) if 'sus' in EVENTS[k]}


def mood_cmds(keys, before=None):
    """Süslerin EventActivationStateCommand'ları (hazır demetinde açık olanlar; 'before' verilirse yalnız açılan ve kapananlar).
    'deger': EventActivationIntegerAttributeModule (buzdağı boyutu)."""
    on, old = moods(keys), moods(before or ())
    cmd = lambda s, a: ('EventActivationStateCommand', dict(type=s['tur'], active=a, attributes=[
        dict(_='EventActivationIntegerAttributeModule', value=s['deger'])] if 'deger' in s else []))
    return ([cmd(s, True) for t, s in sorted(on.items()) if before is None or t not in old]
            + [cmd(s, False) for t, s in sorted(old.items()) if t not in on])


configure()
