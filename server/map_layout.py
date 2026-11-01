"""Harita düzeni (data/map_layout.json): korsan haritaları (5-1, 5-2, 5-3) ve Black Light haritaları (1-BL, 2-BL, 3-BL).

Engeller istemciye MapAddPOICommand NO_ACCESS dikdörtgenleri olarak gider: istemci gemiyi kenarda durdurur (PoiZoneManager.CheckCollisions,
'NOA' bölgeleri), haritada tasarımıyla (asteroit/hurda) ve mini haritada taralı çizer. Daire dışındaki şekillerin shapeCoordinates'i
düz (x, y) çiftleri (MapAddPoiCommandHandler.Handle); dikdörtgen resmî sunucunun sırasıyla dört köşe (x0,y0),(x1,y0),(x1,y1),(x0,y1).
Sunucu tarafında: doğma, cevher ve mayın yerleri engellerin dışında; dolasma açık haritada (X-BL) uzaylılar engellerin çevresinden
ızgara üzerinde A* ile dolaşır (korsan haritalarında uzaylılar eskisi gibi düz gider: fandom "aliens ... go through them"); portalların
yeri ve hedef haritadaki varış yeri; Palladium alanı (ShieldDamage POI'si); mayın alanları (Mines POI'leri); güvenli bölgeler (5-2 korsan
üssü).
"""
import heapq, json, math, os, random
import game_data as DATA

HERE = os.path.dirname(os.path.abspath(__file__))
_D = DATA.load('map_layout.json')
MAPS = {int(k): v for k, v in _D['haritalar'].items()}
_WALLS = {m: [tuple(e[1:5]) for e in d.get('obstacles', [])] for m, d in MAPS.items()}
MINE = _D['mayin']
NO_ACCESS, SHIELD_DAMAGE, MINES = 5, 3, 10     # POIType (resmî sunucu kaydı: Palladium alanı "ShieldDamage", mayın alanı "Mines1")
POLYGON, RECTANGLE = 1, 2                       # istemcinin ShapeType'ı (CIRCLE 0, POLYGON 1, RECTANGLE 2)
NEBULA = 5                                      # POIDesign: Palladium alanının sisi
CELL = 200                                      # dolaşma ızgarasının hücresi
SHIP_PAD = 150                                  # uzaylının doğarken engelden uzak durduğu pay
NAV_PAD = 60                                    # dolaşmada pay: 2-BL'nin sol kenardaki 300 birimlik geçidi açık kalsın (oyuncu
                                                # gemisi engele nokta olarak çarpar, dar geçitten geçer)


def of(map_id):
    return MAPS.get(int(map_id), {})


def walls(map_id):
    """Engel dikdörtgenleri [(x0, y0, x1, y1)]."""
    return _WALLS.get(int(map_id), [])


def _poi(pid, ptype, design, rect, shape=RECTANGLE, coords=None):
    x0, y0, x1, y1 = rect
    return {'_m': 'MapAddPOICommand', 'inverted': False, 'poiTypeSpecification': '',
            'poiType': {'_': 'POITypeModule', 'typeValue': ptype}, 'shape': shape, 'active': True,
            'design': {'_': 'POIDesignModule', 'designValue': design}, 'poiId': pid,
            'shapeCoordinates': coords or [int(x0), int(y0), int(x1), int(y0), int(x1), int(y1), int(x0), int(y1)]}


def poi_msgs(map_id):
    """Haritanın hazır demetindeki bölgeler: engeller (çokgenler olduğu gibi), Palladium alanı, mayın alanları ve öteki bölgeler
    (5-2 istasyonunun Equippable Zone'u) (harita.map_world)."""
    d = of(map_id)
    out = [_poi(e[0], NO_ACCESS, e[5], e[1:5], *((POLYGON, e[6]) if len(e) > 6 else ())) for e in d.get('obstacles', [])]
    if 'palladium' in d:
        out.append(_poi(d['palladium']['id'], SHIELD_DAMAGE, NEBULA, d['palladium']['alan']))
    out += [_poi('Mines%d' % (i + 1), MINES, 0, r) for i, r in enumerate(d.get('mine_fields', []))]
    out += [_poi(pid, t, design, (0, 0, 0, 0), shape, coords) for pid, t, shape, design, coords in d.get('zones', [])]
    return out


def gate_pos(map_id, key):
    """Portalın düzendeki yeri ya da None (harita.GATES yüklenirken)."""
    p = of(map_id).get('portals', {}).get(str(key))
    return tuple(p) if p else None


def arrival(map_id, key):
    """Portalın hedef haritadaki varış yeri: (x, y), 'rastgele' ya da None (geri dönüş portalının yanı)."""
    v = of(map_id).get('varis', {}).get(str(key))
    return tuple(v) if isinstance(v, list) else v


def one_way_gates(map_id):
    """Haritanın tek yönlü varış portalları [(x, y, firma)] (5-X: tasarım 52; harita.map_world)."""
    return [tuple(v) for v in of(map_id).get('arrival_portals', [])]


def design_pos(map_id, design):
    """Kapı ya da mod portalının bu haritadaki yeri (tasarıma göre; resmî sunucu kaydı: 2-1, 2-8) ya da None (dunya.fit_gate)."""
    p = of(map_id).get('design_spot', {}).get(str(design))
    return tuple(p) if p else None


def structure_pos(map_id):
    p = of(map_id).get('yapi')
    return tuple(p) if p else None


def structure_asset(map_id):
    """Yapının varlığının (5-2'nin ticaret noktası) yeri ve yaklaşma bölgesinin yarıçapı -> ((x, y) ya da None, yarıçap ya da None)."""
    d = of(map_id)
    return (tuple(d['structure_asset']) if 'structure_asset' in d else None), d.get('structure_radius')


def lairs(map_id):
    """Türün sabit doğma noktaları (inler): {tür: [[x, y], …]}."""
    return of(map_id).get('lairs', {})


def safe_zones(map_id):
    return of(map_id).get('guvenli', [])


def gate_peace_radius(map_id, default):
    return of(map_id).get('portal_safe', default)


def in_safe(map_id, x, y, margin=0):
    """Düzenin güvenli bölgesinde (5-2 korsan üssü) mi."""
    return any(math.hypot(x - cx, y - cy) <= r + margin for cx, cy, r in safe_zones(map_id))


def blocked(map_id, x, y, pad=0):
    return any(x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad for x0, y0, x1, y1 in walls(map_id))


def _seg_hits(ax, ay, bx, by, r):
    """Doğru parçası dikdörtgeni kesiyor mu (Liang-Barsky)."""
    x0, y0, x1, y1 = r
    dx, dy = bx - ax, by - ay
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def clear(map_id, ax, ay, bx, by, pad=SHIP_PAD):
    return not any(_seg_hits(ax, ay, bx, by, (x0 - pad, y0 - pad, x1 + pad, y1 + pad)) for x0, y0, x1, y1 in walls(map_id))


def free_spot(map_id, rect, pad=SHIP_PAD, tries=40):
    """Dikdörtgende engel dışında rastgele nokta ya da None."""
    x0, y0, x1, y1 = rect
    for _ in range(tries):
        x, y = int(random.uniform(x0, x1)), int(random.uniform(y0, y1))     # denetlenen nokta verilen nokta (yuvarlama payı aşmasın)
        if not blocked(map_id, x, y, pad):
            return x, y
    return None


def navigates(map_id):
    return bool(of(map_id).get('roaming'))


_GRIDS = {}


def _grid(map_id, w, h):
    key = (int(map_id), w, h)
    if key not in _GRIDS:
        nx, ny = int(math.ceil(w / CELL)), int(math.ceil(h / CELL))
        g = [[False] * nx for _ in range(ny)]
        for x0, y0, x1, y1 in walls(map_id):
            for cy in range(max(0, int((y0 - NAV_PAD) // CELL)), min(ny, int((y1 + NAV_PAD) // CELL) + 1)):
                for cx in range(max(0, int((x0 - NAV_PAD) // CELL)), min(nx, int((x1 + NAV_PAD) // CELL) + 1)):
                    g[cy][cx] = True
        _GRIDS[key] = (g, nx, ny)
    return _GRIDS[key]


def _nearest_free(g, nx, ny, c):
    cx, cy = c
    for r in range(1, max(nx, ny)):
        for dy in range(-r, r + 1):
            for dx in (-r, r) if abs(dy) != r else range(-r, r + 1):
                x, y = cx + dx, cy + dy
                if 0 <= x < nx and 0 <= y < ny and not g[y][x]:
                    return x, y
    return c


def waypoint(map_id, w, h, ax, ay, bx, by):
    """Dolaşma: hedefe giden yolun ilk ara noktası (engel yoksa hedefin kendisi). Izgarada 8 yönlü A*, yol ilk görünmeyen
    noktaya kadar kısaltılır; hedef engelin içindeyse en yakın boş hücreye, yol yoksa hedefe en yakın varılabilen hücreye (duvarın
    içinden geçmez)."""
    if clear(map_id, ax, ay, bx, by, NAV_PAD):
        return bx, by
    g, nx, ny = _grid(map_id, w, h)
    cell = lambda x, y: (min(nx - 1, max(0, int(x // CELL))), min(ny - 1, max(0, int(y // CELL))))
    center = lambda c: (c[0] * CELL + CELL / 2, c[1] * CELL + CELL / 2)
    s, t = cell(ax, ay), cell(bx, by)
    if g[s[1]][s[0]]:
        return center(_nearest_free(g, nx, ny, s))       # engelin içinde (doğduğu yer, itilme): en yakın boşluğa çık
    if g[t[1]][t[0]]:
        t = _nearest_free(g, nx, ny, t)
        bx, by = center(t)
    came, cost = {s: None}, {s: 0.0}
    todo = [(0.0, s)]
    near = s                                              # hedefe en yakın varılan hücre
    while todo:
        _, c = heapq.heappop(todo)
        if c == t:
            break
        if math.hypot(t[0] - c[0], t[1] - c[1]) < math.hypot(t[0] - near[0], t[1] - near[1]):
            near = c
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            n = (c[0] + dx, c[1] + dy)
            if not (0 <= n[0] < nx and 0 <= n[1] < ny) or g[n[1]][n[0]]:
                continue
            if dx and dy and (g[c[1]][n[0]] or g[n[1]][c[0]]):
                continue                                  # köşeden geçmez
            k = cost[c] + (1.4142 if dx and dy else 1.0)
            if k < cost.get(n, 1e18):
                cost[n], came[n] = k, c
                heapq.heappush(todo, (k + math.hypot(t[0] - n[0], t[1] - n[1]), n))
    if t not in came:
        t = near                                          # yol yok: duvarın bu yüzünde hedefe en yakın yere
        bx, by = center(t)
    path = [t]
    while came[path[-1]] is not None:
        path.append(came[path[-1]])
    path.reverse()                                        # s ... t
    best = center(path[1]) if len(path) > 1 else (bx, by)
    for c in path[1:]:
        p = center(c)
        if not clear(map_id, ax, ay, *p, pad=NAV_PAD):
            break
        best = p
    if best == center(t) and clear(map_id, ax, ay, bx, by, NAV_PAD):
        return bx, by
    return best


def mine_spots(map_id, gates, n=None):
    """Mayın alanlarına dağılan mayınların yerleri: engellerin ve portalların dışında (alan başına mayin.adet)."""
    out = []
    for rect in of(map_id).get('mine_fields', []):
        for _ in range(MINE['adet'] if n is None else n):
            p = free_spot(map_id, _in_map(map_id, rect), pad=100)
            if p and all(math.hypot(p[0] - g['x'], p[1] - g['y']) > MINE['portal_far'] for g in gates):
                out.append(p)
    return out


def _in_map(map_id, r):
    """Mayın alanının harita içindeki kısmı (kayıttaki alanlar harita dışına taşıyor: 5-1'de y -1.000..28.000)."""
    import map_links as H
    w, h = H.map_size(map_id)
    return max(r[0], 0), max(r[1], 0), min(r[2], w), min(r[3], h)


def mine_field_of(map_id, x, y):
    """(x, y)'yi içeren mayın alanının harita içindeki kısmı ya da None (patlayan mayının yenisi aynı alanda)."""
    r = next((r for r in of(map_id).get('mine_fields', []) if r[0] <= x <= r[2] and r[1] <= y <= r[3]), None)
    return r and _in_map(map_id, r)
