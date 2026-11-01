"""Oyun verisi ve dünyalar (Dünya Editörü): data/<dosya> + seçili dünyanın o dosyaya yamaları.

Dünya: panelin Dünya Editörü'nde oluşturulan değişiklik katmanı (save/dunyalar/<kimlik>.json). Sunucular onu DO_DUNYA ortam
değişkeninden alır (panel/processes.py); yoksa standart dünya (data/ olduğu gibi). Biçim:
  {"ad": …, "yamalar": {"npc.json": {"/tipler/84": {...}, "/haritalar/5/npc": [...]}, "magaza": {"/urunler/<lootId>": {...}}}}
Yama: JSON Pointer (RFC 6901) -> tam değer (varlık düzeyinde değiştirme); {"$sil": true} siler. Ebeveyni olmayan yol atlanır.
Sanal dosyalar (SANAL): data/'da karşılığı olmayan, yalnız dünyanın tanımladığı içerik (mağaza ürünlerinin fiyatı ve satışı).
Modüller içe aktarırken yukle() çağırır: dünya oyun açılırken seçilir. Oyun açıkken yalnız CANLI dosyaların değişikliği uygulanır
(tazele: dosya değişince yeniden okunur; game.dunya_izle mağazayı ve açık artırmayı yeniler); ötekiler sunucu yeniden başlayınca.
Yalnız standart kitaplık (panel de kullanır).
"""
import copy, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
DELETE = '$sil'
VIRTUAL = {'magaza': {'urunler': {}}}      # magaza.py: {lootId: {fiyat, para ('C' | 'U'), satista}}
LIVE = ('magaza', 'social.json')        # oyun açıkken uygulananlar: mağaza fiyatları ve satışı, açık artırma lotları
_WORLD = None
_MTIME = None                            # okunan dünya dosyasının değişme zamanı
_SKIPPED = []                            # uygulanamayan yamalar (dosya, yol): günlük için


def world():
    """Seçili dünya (DO_DUNYA) ya da {} (standart). Okunamazsa standart."""
    global _WORLD, _MTIME
    if _WORLD is None:
        p, _WORLD = os.environ.get('DO_DUNYA'), {}
        try:
            if p:
                _MTIME = os.path.getmtime(p)
                with open(p, encoding='utf8') as fh:
                    _WORLD = json.load(fh)
        except (OSError, ValueError):
            pass
        if not isinstance(_WORLD, dict):
            _WORLD = {}
    return _WORLD


def refresh():
    """Dünya dosyası okunduktan sonra değiştiyse yeniden okur -> CANLI dosyalardan değişenler (yoksa boş)."""
    global _WORLD
    p = os.environ.get('DO_DUNYA')
    if not p or _WORLD is None:
        return []
    try:
        t = os.path.getmtime(p)
    except OSError:
        return []
    if t == _MTIME:
        return []
    old = (_WORLD.get('yamalar') or {})
    _WORLD = None
    new_ = (world().get('yamalar') or {})
    return [d for d in LIVE if old.get(d) != new_.get(d)]


def path_parts(route):
    """'/a/b~1c' -> ['a', 'b/c'] (JSON Pointer)."""
    return [p.replace('~1', '/').replace('~0', '~') for p in route.split('/')[1:]]


def build_path(*parts):
    return ''.join('/' + str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def apply(data, patches, file=''):
    """Yamaları veri üstüne uygular (yerinde); uygulananların sayısı. Liste ebeveyninde parça sıra numarasıdır."""
    n = 0
    for route, value in (patches or {}).items():
        part = path_parts(route)
        if not part:
            continue
        parent = data
        try:
            for p in part[:-1]:
                parent = parent[int(p)] if isinstance(parent, list) else parent[p]
            last = part[-1]
            remove = isinstance(value, dict) and value.get(DELETE)
            if isinstance(parent, list):
                i = int(last)
                if remove:
                    del parent[i]
                elif i == len(parent):
                    parent.append(copy.deepcopy(value))
                else:
                    parent[i] = copy.deepcopy(value)
            elif isinstance(parent, dict):
                if remove:
                    parent.pop(last, None)
                else:
                    parent[last] = copy.deepcopy(value)
            else:
                raise TypeError(type(parent).__name__)
            n += 1
        except (KeyError, IndexError, ValueError, TypeError):
            _SKIPPED.append((file, route))
    return n


def raw(file):
    """Standart dünyadaki hâli (yamasız)."""
    if file in VIRTUAL:
        return copy.deepcopy(VIRTUAL[file])
    with open(os.path.join(DATA, file), encoding='utf8') as fh:
        return json.load(fh)


def load(file, patches=None):
    """data/<dosya> + dünyanın (verilmezse seçili dünyanın) o dosyaya yamaları."""
    d = raw(file)
    apply(d, (world().get('yamalar') or {}).get(file) if patches is None else patches, file)
    return d


def summary():
    """Günlük satırı: seçili dünyanın adı, yama sayısı ve atlananlar."""
    w = world()
    if not w:
        return 'dünya: standart'
    n = sum(len(v or {}) for v in (w.get('yamalar') or {}).values())
    return 'dünya: %s (%d değişiklik%s)' % (w.get('ad') or '?', n, ', atlanan: %s' % _SKIPPED if _SKIPPED else '')
