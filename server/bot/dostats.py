"""Gerçek oyuncu adları: dostats.info (oyuncu isteği 2026-10-31). Panelde ad kaynağı "DOStats" seçilince kadro adları gerçek
sunuculardaki oyuncuların adlarından alınır (dilin sunucularından: tr -> Turkey 3/4/5 ...); adların sonundaki [KLAN] etiketleri bot
klanlarının etiket havuzu olur. Sayfalar sunucu tarafında çizilen tablolar: /rank-changes, /hall-of-fame, /hall-of-gates
(?server=<kod>&gate=<kapı>); oyuncu bağlantısı <a href="/player/<kimlik>">ad</a>. Önbellek save/botlar/_dostats.json (7 gün).
"""
import html
import json
import os
import re
import time
import urllib.request

BASE_URL = 'https://dostats.info'
SERVERS = {'tr': ('tr3', 'tr4', 'tr5'), 'de': ('de2', 'de4'), 'pl': ('pl3',), 'ru': ('ru1', 'ru5'), 'es': ('es1', 'mx1'),
             'fr': ('fr1',), 'pt': ('int2', 'int6'), 'en': ('int1', 'int5', 'int7', 'int11', 'int14', 'gbl3', 'gbl4', 'gbl6', 'us2')}
PAGES = ('/rank-changes?server=%s', '/hall-of-fame?server=%s', '/hall-of-gates?server=%s&gate=Hades',
            '/hall-of-gates?server=%s&gate=Kappa')
CACHE_SEC = 7 * 86400
_PLAYER = re.compile(r'<a[^>]+href="/player/[^"]+"[^>]*>(.*?)</a>', re.S)
_TAG = re.compile(r'\[([^\[\]]{1,4})\]$')


def extract(page):
    """Sayfanın HTML'i -> oyuncu adları (sırayla, tekrarsız)."""
    out = []
    for a in _PLAYER.findall(page):
        name = html.unescape(re.sub(r'<[^>]+>', '', a)).strip()
        if name and name not in out:
            out.append(name)
    return out


def _download(route, timeout=15):
    rq = urllib.request.Request(BASE_URL + route, headers={'User-Agent': 'Mozilla/5.0 (OpenOrbit bot names)'})
    with urllib.request.urlopen(rq, timeout=timeout) as f:
        return f.read().decode('utf8', 'replace')


def _cache_path():
    import paths as PTH
    return os.path.join(PTH.SAVE, 'botlar', '_dostats.json')


def names(languages, download=None):
    """{dil: [ad]} (önbellekten ya da siteden; indir verilirse önbelleksiz, testler). Ulaşılamayan sayfa atlanır; hiç ad gelmezse
    OSError."""
    from .personality import NAME_PATTERN
    route = _cache_path() if download is None else None
    registry = {}
    if route:
        try:
            with open(route, encoding='utf8') as f:
                registry = json.load(f)
        except (OSError, ValueError):
            registry = {}
    out, changed, error = {}, False, None
    for lang in languages:
        if lang not in SERVERS:
            continue
        x = registry.get(lang)
        if not x or time.time() - x.get('t', 0) > CACHE_SEC:
            entries = []
            for s in SERVERS[lang][:1 if len(languages) > 1 else None]:      # karışık: dil başına bir sunucu (panel beklemesin)
                for page in PAGES:
                    try:
                        entries += [a for a in extract((download or _download)(page % s)) if a not in entries]
                    except (OSError, ValueError) as e:
                        error = e
            if entries:
                x = registry[lang] = {'t': time.time(), 'adlar': entries}
                changed = True
        if x:
            out[lang] = [a for a in x['adlar'] if NAME_PATTERN.match(a)]
    if changed and route:
        os.makedirs(os.path.dirname(route), exist_ok=True)
        with open(route + '.tmp', 'w', encoding='utf8') as f:
            json.dump(registry, f, ensure_ascii=False)
        os.replace(route + '.tmp', route)
    if not any(out.values()):
        raise OSError('dostats.info: %s' % (error or 'ad yok'))
    return out


def tags(pool):
    """Adların sonundaki klan etiketleri ("SILNY[DZL]" -> "DZL"), oyunun etiket kuralına uyanlar."""
    out = []
    for entries in pool.values():
        for a in entries:
            m = _TAG.search(a)
            t = m.group(1).strip() if m else ''
            if t and all(c.isalnum() or c in '-_.!?*+' for c in t) and t not in out:
                out.append(t)
    return out
