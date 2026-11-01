"""Dünya Editörü'nün deposu ve bölümleri (panel.py'nin /api/dunya… uçları; kullanıcı isteği 2026-10-28, belgeler/DUNYA_EDITORU.md).

Dünya: standart oyun verisinin (server/data) üstüne konan değişiklik katmanı, save/dunyalar/<kimlik>.json:
  {surum, ad, aciklama, kapak, olusturma, guncelleme, yamalar: {dosya: {JSON Pointer: tam değer | {"$sil": true}}}}
Sunucu onu game_data.py ile uygular (OO_WORLD). Standart dünya ("standart") salt okunur: onda yapılan değişiklikler taslağa
(save/dunyalar/_taslak.json) yazılır, "Yeni dünya olarak kaydet" taslağı dünyaya çevirir.
Yalnız izin verilen yollar yazılır (YOLLAR); değerler türüne göre temizlenir (oyun sunucusu bozuk veriyle açılmasın).
Bölümler (editörün görünümleri): standart değer + dünyanınki + değişti işareti; harita, görev ve mağaza ayrıntıları ayrı.
"""
import base64, copy, datetime, hashlib, json, os, re, threading, zlib

import paths as PTH
import save_migration as SM
import game_data as DATA
from lang import t as _

STANDARD = 'standart'
COVERS = ('standart', 'nebula', 'crimson', 'ice', 'mining', 'crystal', 'toxic', 'void')
VERSION = 1
NAME_LENGTH, DESCRIPTION_LENGTH = 40, 240
NEW_QUEST = 900000              # yeni görevlerin kimliği buradan (oyunun görevleri < 900000; kök durumu ve koşul kimlikleri ayrı aralıkta)
NEW_ALIEN = 'ozel_'            # yeni uzaylı türlerinin anahtarı (ozel_1, ozel_2 …)
COUNT_MAX = 300                # bir haritada bir türün en çok adedi
# bölüm -> (dosya, yol öneki) listesi: değişiklik sayısı ve "bölümü standarda döndür"
SECTIONS = {
    'haritalar': [('npc.json', '/haritalar/'), ('map_layout.json', '/haritalar/'), ('items.json', '/cevherler/')],
    'uzaylilar': [('npc.json', '/tipler/')],
    'gorevler': [('quests.json', '/gorevler/'), ('quest_extras.json', '/gorevler/')],
    'magaza': [('magaza', '/urunler/')],
    'muzayede': [('social.json', '/muzayede/')],
    'kutular': [('npc.json', '/bonus_kutu'), ('boxes.json', '/kutular/')],
    'kapilar': [('gates.json', '/kapilar/')],
    'etkinlikler': [('events.json', '/etkinlikler/')],
    'ekonomi': [('levels.json', '/seviyeler'), ('ranks.json', '/')],
}
PATHS = [(d, re.compile(r)) for d, r in (
    ('npc.json', r'^/tipler/[^/]+$'), ('npc.json', r'^/haritalar/[^/]+/(npc|bonus_kutu)$'), ('map_layout.json', r'^/haritalar/[^/]+$'),
    ('quests.json', r'^/gorevler/\d+$'), ('quest_extras.json', r'^/gorevler/\d+$'), ('magaza', r'^/urunler/[^/]+$'),
    ('social.json', r'^/muzayede/lotlar$'), ('npc.json', r'^/bonus_kutu(_4x)?$'), ('boxes.json', r'^/kutular/[^/]+$'),
    ('gates.json', r'^/kapilar/[^/]+$'), ('events.json', r'^/etkinlikler/[^/]+$'),
    ('levels.json', r'^/seviyeler$'), ('ranks.json', r'^/(formul|esikler)$'), ('items.json', r'^/cevherler/haritalar/[^/]+$'), ('items.json', r'^/cevherler/yeniden_dogma_sn$'))]
GATE_REWARD = ('ep', 'onur', 'uridyum', 'xenomit', 'log_disk', 'kupon')           # kapı ödülünün düzenlenen sayıları
GATE_ALIEN = ('adet', 'hp', 'kalkan', 'hasar', 'hiz')                       # dalga uzaylısının düzenlenen değerleri
PACKAGE = 'paket'                                                             # ganimet.PAKET: kutu ödülünde birden çok eşyalı satır
NPC_NUMBERS = ('hp', 'kalkan', 'hasar', 'hiz')
REWARD = ('ep', 'onur', 'kredi', 'uridyum')
# görev koşul türleri (gorev.py, gorev_takip.py): editörün anladığı -> eşleşmenin anlamı
CONDITION = {6: 'npc', 27: 'npc', 34: 'harita', 67: 'esya', 51: 'yok', 55: 'yok', 52: 'cevher', 28: 'yok', 53: 'yok', 62: 'yok',
         35: 'yok', 42: 'yok', 2: 'sure', 3: 'sure', 63: 'sure', 13: 'yok', 12: 'yok', 7: 'yok', 9: 'yok', 80: 'kapi'}
SUB_MAP = 77
QUEST_TEMPLATES = {          # yeni görevin hedef türü -> (koşul türü, gösterim, eşleşme)
    'avla': (6, 6), 'topla': (67, 67), 'kesif': (34, 34), 'sat': (52, 52), 'kutu': (55, 55), 'kargo': (51, 51),
}
_LOCK = threading.Lock()


class WorldError(ValueError):
    """Kullanıcıya gösterilen hata (panel.py 400 döner)."""


def folder():
    return os.path.join(PTH.SAVE, 'worlds')


def _route(did):
    if did == STANDARD:
        return os.path.join(folder(), '_draft.json')
    if not isinstance(did, str) or not re.fullmatch(r'[a-z0-9_]{1,40}', did):
        raise WorldError(_('Dünya bulunamadı.'))
    return os.path.join(folder(), did + '.json')


def _read_file(p):
    try:
        with open(p, encoding='utf8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write_file(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def var(did):
    return did == STANDARD or (isinstance(did, str) and re.fullmatch(r'[a-z0-9_]{1,40}', did) and os.path.isfile(_route(did)))


def read(did):
    """Dünya (standart: taslağın yamalarıyla). Yoksa DunyaHatasi."""
    if did == STANDARD:
        d = _read_file(_route(did)) or {}
        return {'id': STANDARD, 'ad': _('Standart dünya'), 'aciklama': _('Oyunun kendi içeriği. Düzenlenemez: değişikliklerini yeni bir dünya olarak kaydet.'),
                'cover': 'standart', 'standart': True, 'yamalar': d.get('yamalar') or {}}
    d = _read_file(_route(did))
    if d is None:
        raise WorldError(_('Dünya bulunamadı.'))
    d.setdefault('yamalar', {})
    d['id'] = did
    return d


def _save(did, d):
    d = {k: v for k, v in d.items() if k not in ('id', 'standart')}
    if did != STANDARD:
        d['guncelleme'] = _now()
    d['surum'] = VERSION
    _write_file(_route(did), d)


def file_path(did):
    """Sunucuya verilecek dünya dosyası (OO_WORLD); standart ya da olmayan dünya: None."""
    return _route(did) if did and did != STANDARD and var(did) else None


def counts(patches):
    """Bölüm başına değişiklik sayısı."""
    out = {b: 0 for b in SECTIONS}
    for file, patch_count in (patches or {}).items():
        for y in patch_count or {}:
            b = section_of(file, y)
            if b:
                out[b] += 1
    return out


def section_of(file, route):
    return next((b for b, ps in SECTIONS.items() for d, p in ps if d == file and route.startswith(p)), None)


def summary(did, users=None):
    d = read(did)
    n = counts(d['yamalar'])
    return {'id': did, 'ad': d.get('ad') or did, 'aciklama': d.get('aciklama', ''), 'cover': d.get('cover') if d.get('cover') in COVERS else 'nebula',
            'standart': did == STANDARD, 'created': d.get('created'), 'guncelleme': d.get('guncelleme'),
            'changes': sum(n.values()), 'sections': n, 'users': (users or {}).get(did, [])}


def entries(users=None):
    """Standart dünya önce, sonra özel dünyalar (son güncellenen önce)."""
    out = []
    if os.path.isdir(folder()):
        for f in os.listdir(folder()):
            did = f[:-5] if f.endswith('.json') else None
            if did and not did.startswith('_') and re.fullmatch(r'[a-z0-9_]{1,40}', did):
                try:
                    out.append(summary(did, users))
                except WorldError:
                    pass
    out.sort(key=lambda w: w['guncelleme'] or '', reverse=True)
    return [summary(STANDARD, users)] + out


def _clean_name(name):
    name = ' '.join(str(name or '').split())[:NAME_LENGTH]
    if not name:
        raise WorldError(_('Dünyaya bir ad ver.'))
    return name


def _new_id(name):
    tr = str.maketrans('çğıöşüâîûÇĞİÖŞÜ', 'cgiosuaiuCGIOSU')
    k = re.sub(r'[^a-z0-9]+', '_', name.translate(tr).lower()).strip('_')[:30] or 'dunya'
    if k == STANDARD:
        k = 'dunya'
    did, n = k, 2
    while os.path.exists(_route(did)):
        did, n = '%s_%d' % (k, n), n + 1
    return did


def create(name, description='', cover='nebula', source=None, from_draft=False):
    """Yeni dünya: boş (standart), kaynak dünyanın kopyası ya da standart dünyanın taslağından (taslak sonra silinir)."""
    with _LOCK:
        name = _clean_name(name)
        patches = {}
        if from_draft:
            patches = read(STANDARD)['yamalar']
        elif source and source != STANDARD:
            patches = copy.deepcopy(read(source)['yamalar'])
        did = _new_id(name)
        _save(did, {'ad': name, 'aciklama': str(description or '')[:DESCRIPTION_LENGTH], 'cover': cover if cover in COVERS[1:] else 'nebula',
                      'created': _now(), 'yamalar': patches})
        if from_draft:
            discard_draft()
        return did


def update(did, name=None, description=None, cover=None):
    if did == STANDARD:
        raise WorldError(_('Standart dünya değiştirilemez.'))
    with _LOCK:
        d = read(did)
        if name is not None:
            d['ad'] = _clean_name(name)
        if description is not None:
            d['aciklama'] = str(description)[:DESCRIPTION_LENGTH]
        if cover is not None and cover in COVERS[1:]:
            d['cover'] = cover
        _save(did, d)


def remove(did):
    if did == STANDARD:
        raise WorldError(_('Standart dünya silinemez.'))
    p = _route(did)
    if not os.path.isfile(p):
        raise WorldError(_('Dünya bulunamadı.'))
    os.makedirs(os.path.join(folder(), '_trash'), exist_ok=True)
    os.replace(p, os.path.join(folder(), '_trash', '%s_%s.json' % (did, datetime.datetime.now().strftime('%Y%m%d%H%M%S'))))


def duplicate(did, name=None):
    d = read(did)
    return create(name or _('{0} (kopya)').format(d.get('ad') or did)[:NAME_LENGTH], d.get('aciklama', ''), d.get('cover', 'nebula'),
                   source=did if did != STANDARD else None, from_draft=False) if did != STANDARD else \
        create(name or _('Yeni dünya'), '', 'nebula')


CODE_PREFIX = 'OODUNYA1:'


def data_signature(files):
    """Standart veri dosyalarının özeti (paylaşılan dünyanın hangi oyun verisiyle hazırlandığı): {dosya: sha1'in ilk 12'si}."""
    out = {}
    for f in files:
        p = os.path.join(DATA.DATA, f)
        if f not in DATA.VIRTUAL and os.path.isfile(p):
            with open(p, 'rb') as fh:
                out[f] = hashlib.sha1(fh.read()).hexdigest()[:12]
    return out


def export(did):
    """Paylaşılacak dünya: ad, açıklama, kapak, yamalar; hazırlandığı veri (veri_imzasi) ve bölüm sayıları (içe aktarırken uyarı)."""
    d = read(did)
    return {'openorbit_world': VERSION, 'ad': d.get('ad'), 'aciklama': d.get('aciklama', ''), 'cover': d.get('cover', 'nebula'),
            'tarih': _now(), 'veri': data_signature(d['yamalar']), 'sections': counts(d['yamalar']), 'yamalar': d['yamalar']}


def code(did):
    """Paylaşım kodu: OODUNYA1: + base64(zlib(dünya)); Discord'a ya da sohbete yapıştırılır."""
    raw_ = json.dumps(export(did), ensure_ascii=False, separators=(',', ':')).encode('utf8')
    return CODE_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw_, 9)).decode('ascii')


def from_code(text):
    text = ''.join(str(text or '').split())
    if not text.startswith(CODE_PREFIX):
        raise WorldError(_('Bu bir OpenOrbit dünya kodu değil.'))
    try:
        return json.loads(zlib.decompress(base64.urlsafe_b64decode(text[len(CODE_PREFIX):] + '=' * (-len(text) % 4))).decode('utf8'))
    except (ValueError, zlib.error):
        raise WorldError(_('Dünya kodu bozuk ya da eksik kopyalanmış.'))


def import_(data):
    """Paylaşılan dünyayı yeni dünya olarak ekler -> (kimlik, rapor). İzinsiz yollar atlanır, her değer düzenleyicinin süzgecinden
    geçer (bozuk olan atlanır); dünya başka bir oyun verisiyle hazırlandıysa rapor söyler."""
    if isinstance(data, dict):
        data = SM.migrate_world(data)                 # eski sürümde paylaşılan dünya: veri dosyası adları ve yollar yeni adlara
    if not isinstance(data, dict) or 'yamalar' not in data or not isinstance(data['yamalar'], dict):
        raise WorldError(_('Bu dosya bir OpenOrbit dünyası değil.'))
    if int(data.get('openorbit_world') or 1) > VERSION:
        raise WorldError(_('Bu dünya panelin daha yeni bir sürümüyle hazırlanmış: önce paneli güncelle.'))
    cleared, skipped = {}, 0
    for file, patch_count in data['yamalar'].items():
        for y, v in (patch_count or {}).items() if isinstance(patch_count, dict) else ():
            if allowed(file, y):
                cleared.setdefault(file, {})[y] = v
            else:
                skipped += 1
    did = create(data.get('ad') or _('İçe aktarılan dünya'), data.get('aciklama', ''), data.get('cover', 'nebula'))
    issues = []
    with _LOCK:
        d = read(did)
        d['yamalar'] = cleared
        _save(did, d)                          # süzgeç dünyanın kendi türlerini (ozel_*) görsün diye önce olduğu gibi
        order = sorted(((f, y) for f, patch_count in cleared.items() for y in patch_count), key=lambda x: (x[0] != 'npc.json' or not x[1].startswith('/tipler/'), x))
        for f, y in order:
            try:
                cleared[f][y] = clean_up(did, f, y, cleared[f][y])
            except (WorldError, KeyError, IndexError, TypeError, ValueError, AttributeError, ArithmeticError) as e:
                del cleared[f][y]
                issues.append('%s %s: %s' % (f, y, e))
        d['yamalar'] = {f: patch_count for f, patch_count in cleared.items() if patch_count}
        _save(did, d)
    now = data_signature(data.get('veri') or {})
    differs = sorted(f for f, h in (data.get('veri') or {}).items() if now.get(f) != h)
    return did, {'changes': sum(len(v) for v in d['yamalar'].values()), 'skipped': skipped + len(issues), 'issues': issues[:12],
                 'data_differs': differs, 'tarih': data.get('tarih')}


def discard_draft():
    p = _route(STANDARD)
    if os.path.isfile(p):
        os.remove(p)


# ------------------------------------------------------------------ yamalar
def allowed(file, route):
    return any(d == file and r.match(route) for d, r in PATHS)


def patch(did, file, route, value):
    """Dünyaya (standartta taslağa) bir değişiklik: tam değer. Standart değere eşitse yama kaldırılır."""
    if not allowed(file, route):
        raise WorldError(_('Bu içerik düzenlenemez.'))
    value = clean_up(did, file, route, value)
    with _LOCK:
        d = read(did)
        patch_count = d['yamalar'].setdefault(file, {})
        if value == default_value(file, route):
            patch_count.pop(route, None)
        else:
            patch_count[route] = value
        if not patch_count:
            d['yamalar'].pop(file, None)
        _save(did, d)


def revert(did, file=None, route=None, section=None):
    """Bir değişikliği (dosya + yol) ya da bölümün bütün değişikliklerini standarda döndürür."""
    with _LOCK:
        d = read(did)
        for f in list(d['yamalar']):
            for y in list(d['yamalar'][f] or {}):
                if (section and section_of(f, y) == section) or (f == file and y == route):
                    del d['yamalar'][f][y]
            if not d['yamalar'][f]:
                del d['yamalar'][f]
        _save(did, d)


_RAW = {}


def raw(file):
    """Standart veri (önbellekli)."""
    if file not in _RAW:
        _RAW[file] = DATA.raw(file)
    return _RAW[file]


def _get(data, route):
    for p in DATA.path_parts(route):
        if isinstance(data, list):
            data = data[int(p)]
        elif isinstance(data, dict) and p in data:
            data = data[p]
        else:
            return None
    return data


def default_value(file, route):
    return _get(raw(file), route)


def world_data(did, file):
    """Dosyanın dünyadaki hâli (standart + yamalar; kopya)."""
    v = copy.deepcopy(raw(file))
    DATA.apply(v, read(did)['yamalar'].get(file) or {}, file)
    return v


def _int(v, sub=0, parent=10 ** 9):
    try:
        return max(sub, min(parent, int(round(float(v)))))
    except (TypeError, ValueError, OverflowError):      # 1e999 / Infinity (içe aktarılan dünya kodu)
        raise WorldError(_('Sayı bekleniyordu.'))


def clean_up(did, file, route, v):
    """Değeri oyunun okuyacağı biçime getirir; uymayan değer DunyaHatasi."""
    part = DATA.path_parts(route)
    if isinstance(v, dict) and v.get(DATA.DELETE):
        if file == 'npc.json' and part[0] == 'tipler' and not part[1].startswith(NEW_ALIEN):
            raise WorldError(_('Oyunun uzaylıları silinemez; doğma listelerinden çıkarabilirsin.'))
        if file in ('quests.json', 'quest_extras.json') and int(part[1]) < NEW_QUEST:
            raise WorldError(_('Oyunun görevleri silinemez; kapatabilirsin.'))
        return {DATA.DELETE: True}
    if file == 'npc.json' and part[0] == 'tipler':
        if not isinstance(v, dict):
            raise WorldError(_('Uzaylı verisi bozuk.'))
        v = dict(v)
        v['ad'] = ' '.join(str(v.get('ad') or '').split())[:60] or '?'
        for k in NPC_NUMBERS:
            v[k] = _int(v.get(k, 0), 0, 50_000_000 if k in ('hp', 'kalkan') else 1_000_000 if k == 'hasar' else 2000)
        v['saldirgan'] = bool(v.get('saldirgan'))
        v['odul'] = {k: _int((v.get('odul') or {}).get(k, 0), 0, 10 ** 9) for k in REWARD}
        v['kargo'] = {str(_int(k, 0, 99)): _int(n, 0, 100_000) for k, n in (v.get('kargo') or {}).items() if _int(n, 0, 100_000) > 0}
        if part[1].startswith(NEW_ALIEN) and not v.get('model'):
            raise WorldError(_('Yeni uzaylının bir modeli olmalı.'))
        return v
    if file == 'npc.json' and part[0] == 'haritalar':
        types = world_data(did, 'npc.json')['tipler']
        if len(part) == 3 and part[2] == 'bonus_kutu':
            return _int(v, 0, 300)
        if len(part) == 3 and part[2] == 'npc':
            if not isinstance(v, list):
                raise WorldError(_('Doğma listesi bozuk.'))
            out = []
            for g in v:
                tip = str(g.get('tip'))
                if tip not in types:
                    continue
                e = {'tip': tip, 'adet': _int(g.get('adet', 1), 0, COUNT_MAX)}
                b = g.get('bolge')
                if isinstance(b, list) and len(b) == 3:
                    e['bolge'] = [_int(b[0], 0, 42000), _int(b[1], 0, 26200), _int(b[2], 200, 15000)]
                out.append(e)
            return out
        raise WorldError(_('Bu içerik düzenlenemez.'))
    if file == 'map_layout.json':
        if not isinstance(v, dict):
            raise WorldError(_('Harita düzeni bozuk.'))
        v = copy.deepcopy(v)
        if 'guvenli' in v:
            v['guvenli'] = [[_int(a, 0, 42000), _int(b, 0, 26200), _int(r, 100, 6000)] for a, b, r in v['guvenli']]
        if 'lairs' in v:
            v['lairs'] = {str(t): [[_int(a, 0, 42000), _int(b, 0, 26200)] for a, b in pts] for t, pts in v['lairs'].items() if pts}
        if 'portals' in v:
            v['portals'] = {str(k): [_int(p[0], 0, 42000), _int(p[1], 0, 26200)] for k, p in v['portals'].items()}
        return v
    if file in ('quests.json', 'quest_extras.json'):
        if not isinstance(v, dict) or 'kok' not in v:
            raise WorldError(_('Görev verisi bozuk.'))
        v = copy.deepcopy(v)
        v['seviye'] = _int(v.get('seviye', 1), 0, 40)
        v['oduller'] = [[str(l), _int(n, 1, 10 ** 9)] for l, n in v.get('oduller', []) if str(l)]
        v['onceki'] = [_int(x, 0) for x in v.get('onceki', [])]
        for k, n in (('baslik', 80), ('aciklama', 600)):          # oyunda görünen metin (eklentinin GorevMetinleri yaması)
            t = ' '.join(str(v.get(k) or '').split()) if k == 'baslik' else str(v.get(k) or '').strip()
            if t:
                v[k] = t[:n]
            else:
                v.pop(k, None)
        return v
    if file == 'magaza':
        if not isinstance(v, dict):
            raise WorldError(_('Ürün verisi bozuk.'))
        out = {}
        if v.get('fiyat') is not None:
            out['fiyat'] = _int(v['fiyat'], 0, 10 ** 10)
            out['currency'] = 'C' if v.get('currency') == 'C' else 'U'
        if v.get('on_sale') is False:
            out['on_sale'] = False
        return out
    if file == 'npc.json' and part[0] in ('bonus_kutu', 'bonus_kutu_4x'):
        out = [[str(l), _int(n, 1, 10 ** 7)] for l, n in (v if isinstance(v, list) else []) if str(l)]
        if not out:
            raise WorldError(_('Bonus kutusunda en az bir ödül olmalı.'))
        return out
    if file == 'boxes.json':
        return _clean_box(part[1], v)
    if file == 'gates.json':
        return _clean_gate(part[1], v, world_data(did, 'npc.json')['tipler'])
    if file == 'levels.json':
        base = raw('levels.json')['seviyeler']
        ep = [_int(x[1] if isinstance(x, list) else x, 0, 10 ** 20) for x in (v if isinstance(v, list) else [])]
        # tarayıcı 2^53'ten büyük sayıları yuvarlar (son seviyeler ~10^18): yuvarlama payındaki değer standarttır
        ep = [b[1] if abs(n - b[1]) <= b[1] * 1e-12 else n for n, b in zip(ep, base)]
        if len(ep) != len(base) or ep[0] != 0 or any(b <= a for a, b in zip(ep, ep[1:])):
            raise WorldError(_('Seviye eşikleri sıfırdan başlayıp artmalı.'))
        return [[lv, n] for (lv, _), n in zip(base, ep)]
    if file == 'ranks.json' and part[0] == 'esikler':
        base = raw('ranks.json')['esikler']
        n = [_int(x, 0, 10 ** 12) for x in (v if isinstance(v, list) else [])]
        if len(n) != len(base) or n[0] != 0 or any(b <= a for a, b in zip(n, n[1:])):
            raise WorldError(_('Rütbe eşikleri sıfırdan başlayıp artmalı.'))
        return n
    if file == 'ranks.json' and part[0] == 'formul':
        base = raw('ranks.json')['formul']
        try:
            return {k: max(-10 ** 6, min(10 ** 6, float(v.get(k, d)))) for k, d in base.items()}
        except (AttributeError, TypeError, ValueError):
            raise WorldError(_('Sayı bekleniyordu.'))
    if file == 'events.json':
        return _clean_event(part[1], v, world_data(did, 'npc.json')['tipler'])
    if file == 'items.json':
        if part[-1] == 'yeniden_dogma_sn':
            lo, hi = sorted(_int(x, 1, 86400) for x in (v if isinstance(v, list) and len(v) == 2 else [15, 30]))
            return [lo, hi]
        kinds = raw('items.json')['cevherler']['kinds']
        out = {str(t): _int(n, 0, 1000) for t, n in (v or {}).items() if str(t) in kinds}
        return out or {'0': 0}                   # hepsi 0: haritada cevher yok (boş sözlük sınıfın değerine düşerdi)
    if file == 'social.json':
        if not isinstance(v, list):
            raise WorldError(_('Lot listesi bozuk.'))
        out = []
        for l in v:
            loot, kind = str(l[0]), l[2] if l[2] in ('hour', 'day', 'week') else 'hour'
            out.append([loot, str(l[1] or 'other'), kind, _int(l[3], 1, 10 ** 7), bool(l[4]), _int(l[5], 0, 10 ** 9)])
        seen = set()
        return [l for l in out if (l[2], l[0]) not in seen and not seen.add((l[2], l[0]))]      # lot anahtarı (tür, eşya) tek
    return v


def _clean_box(kind, v):
    """Anahtarlı kutu: haritalardaki adet, yeniden doğma, harita sınıfları ve ödül tablosu (satır: [eşya, adet | [en az, en çok],
    ağırlık]; paket satırı olduğu gibi). Öteki alanlar (anahtar, takvim, mesajlar) standarttan."""
    base = raw('boxes.json')['kutular'].get(kind)
    if base is None or not isinstance(v, dict):
        raise WorldError(_('Kutu bulunamadı.'))
    out = copy.deepcopy(base)
    classes = raw('boxes.json')['haritalar']
    if 'adet' in v:
        out['adet'] = _int(v['adet'], 0, 100)
    if 'yeniden_sn' in v and isinstance(v['yeniden_sn'], list) and len(v['yeniden_sn']) == 2:
        out['yeniden_sn'] = sorted(_int(x, 10, 86400) for x in v['yeniden_sn'])
    if 'haritalar' in v:
        out['haritalar'] = [m for m in v['haritalar'] if m in classes]
    if 'odul' in v and base.get('odul'):
        rows = []
        for r in v['odul'] if isinstance(v['odul'], list) else []:
            if not isinstance(r, list) or len(r) != 3:
                continue
            w = max(0.0, min(1e6, float(r[2] or 0)))
            if w <= 0:
                continue
            if r[0] == PACKAGE:
                if any(b[0] == PACKAGE and b[1] == r[1] for b in base['odul']):
                    rows.append([PACKAGE, r[1], w])
                continue
            n = sorted(_int(x, 1, 10 ** 7) for x in r[1]) if isinstance(r[1], list) and len(r[1]) == 2 else _int(r[1], 1, 10 ** 7)
            rows.append([str(r[0]), n, w])
        if not rows:
            raise WorldError(_('Kutuda en az bir ödül olmalı.'))
        out['odul'] = rows
    return out


def _groups(groups, i, old, new_):
    """Dalganın alt gruplarında uzaylı i'nin adetlerini eskiden yeniye orantılı ölçekler (her satır en az 1; toplam yeni)."""
    place = [(g, k) for g, grp in enumerate(groups) for k, (j, n) in enumerate(grp) if j == i]
    if not place or old <= 0:
        return
    new_ = max(new_, len(place))
    pay = [max(1, round(groups[g][k][1] * new_ / old)) for g, k in place]
    diff = new_ - sum(pay)
    order = sorted(range(len(pay)), key=lambda x: -pay[x])
    while diff:
        for x in order:
            if diff > 0:
                pay[x] += 1
                diff -= 1
            elif diff < 0 and pay[x] > 1:
                pay[x] -= 1
                diff += 1
            if not diff:
                break
    for (g, k), n in zip(place, pay):
        groups[g][k] = [i, n]


def _clean_gate(key, v, types=None):
    """Galaksi Kapısı: parça, can, ödül sayıları, cephane ödülü, şanslı ödüllerin olasılığı ve adedi, dalgaların uzaylı değerleri
    (adet değişince alt gruplar orantılı ölçeklenir). Dalga ve uzaylı listesinin yapısı standarttan (galaxy_gates.py'nin sayaçları ona bağlı)."""
    base = raw('gates.json')['kapilar'].get(key)
    if base is None or not isinstance(v, dict):
        raise WorldError(_('Kapı bulunamadı.'))
    out = copy.deepcopy(base)
    for k in ('parca', 'can'):
        if k in v:
            out[k] = _int(v[k], 1, 10000)
    o, value_reward = out['odul'], v.get('odul') or {}
    for k in GATE_REWARD:
        if k in value_reward and k in o:
            o[k] = _int(value_reward[k], 0, 10 ** 10)
    if isinstance(value_reward.get('cephane'), dict):
        o['cephane'] = {str(l): _int(n, 1, 10 ** 8) for l, n in value_reward['cephane'].items() if str(l)}
    for i, x in enumerate(value_reward.get('sans') or []):
        if i < len(o.get('sans', [])) and isinstance(x, dict):
            if 'probability' in x:
                o['sans'][i]['probability'] = max(0.0, min(1.0, float(x['probability'])))
            if 'adet' in x and isinstance(o['sans'][i].get('adet'), int):
                o['sans'][i]['adet'] = _int(x['adet'], 1, 10 ** 7)
    for n, value_wave in enumerate(v.get('waves') or []):
        if n >= len(out['waves']) or not isinstance(value_wave, dict):
            continue
        w = out['waves'][n]
        for i, va in enumerate(value_wave.get('uzaylilar') or []):
            if i >= len(w['uzaylilar']) or not isinstance(va, dict):
                continue
            a = w['uzaylilar'][i]
            kind = str(va.get('tur') or a['tur'])
            # yalnız istemcinin gemi türü olan anahtarlar (kapi.register_npcs türü model olarak gönderir: "ozel_1", "etk_…" olmaz)
            if kind != a['tur'] and not a.get('permanent') and a['tur'] != 'oyuncu' and kind.isdigit() and kind in (types or {}):
                t = types[kind]                          # uzaylıyı başka türle değiştir: türün değerleri, dalgadaki adet ve yer aynı
                a.update(tur=kind, ad=re.sub(r'^[-=\[\]:.{}\s]+|[-=\[\]:.{}\s]+$', '', t['ad']) or kind, gorunen_ad=t['ad'],
                         npc_kimlik=t.get('npc_kimlik', a.get('npc_kimlik')), hp=t['hp'], kalkan=t['kalkan'], hasar=t['hasar'], hiz=t['hiz'],
                         odul=dict(t.get('odul') or {}), kargo=dict(t.get('kargo') or {}))
                a.pop('davranis', None)
            for k in GATE_ALIEN:
                if k not in va:
                    continue
                new_ = _int(va[k], 1 if k == 'adet' else 0, 50_000_000)
                if k == 'adet':
                    old = sum(c for grp in w['gruplar'] for j, c in grp if j == i)
                    _groups(w['gruplar'], i, old, new_)
                    new_ = sum(c for grp in w['gruplar'] for j, c in grp if j == i) or new_
                a[k] = new_
            if isinstance(va.get('odul'), dict):
                a['odul'] = {k: _int(va['odul'].get(k, a['odul'].get(k, 0)), 0, 10 ** 9) for k in REWARD}
    return out


MAP_CLASSES = tuple('X-%d' % n for n in range(1, 9))      # harita etkinliklerinin harita sınıfları


def _date(x):
    """Dönem ucu: 'YYYY-AA-GG' ya da her yıl 'AA-GG' (takvim._spans)."""
    x = str(x or '').strip()
    for style in ('%Y-%m-%d', '%m-%d'):
        try:
            datetime.datetime.strptime(x if style == '%Y-%m-%d' else '2024-' + x, '%Y-%m-%d')
            return x
        except ValueError:
            pass
    raise WorldError(_('Tarih geçersiz: %s', x))


def event_classes(h, types):
    """Harita etkinliğinin seçilebilen sınıfları: uzaylılarının ve patronunun o sınıfa özgü türü (etk_<ad>_x<n>) olanlar."""
    kinds = [a['tur'] for a in h.get('uzaylilar', [])] + list((h.get('patron') or {}).get('kinds', []))
    return [m for m in MAP_CLASSES if all(t.replace('{x}', 'x' + m[2:]) in types for t in kinds)]


def _clean_event(key, v, types):
    """Etkinlik: dünyadaki durum (dunya_durum: acik | kapali | takvim), dönemler ([başlangıç, bitiş] + standart satırın kuyruğu: saatler,
    'tek'), harita bölümü (haritalar, uzaylı adetleri, harita kotaları, patron adedi ve süresi). Öteki alanlar standarttan."""
    base = raw('events.json')['etkinlikler'].get(key)
    if base is None or not isinstance(v, dict):
        raise WorldError(_('Etkinlik bulunamadı.'))
    out = copy.deepcopy(base)
    if v.get('world_status') in ('acik', 'kapali'):
        out['world_status'] = v['world_status']
    if isinstance(v.get('donemler'), list) and 'donemler' in base:
        queue = {(r[0], r[1]): r[2:] for r in base['donemler']}
        rows = []
        for r in v['donemler']:
            if isinstance(r, list) and len(r) >= 2:
                a, b = _date(r[0]), _date(r[1])
                if len(a) != len(b):
                    raise WorldError(_('Dönemin iki ucu da aynı biçimde olmalı (yıllı ya da her yıl).'))
                rows.append([a, b] + list(queue.get((r[0], r[1]), [])))
        out['donemler'] = rows
    h, value_map = out.get('harita'), v.get('harita')
    if h and isinstance(value_map, dict):
        if isinstance(value_map.get('haritalar'), list):
            permission = event_classes(h, types)          # X-n dışındakiler (Sunburst'ün 4-X'i) olduğu gibi
            h['haritalar'] = [m for m in MAP_CLASSES if m in value_map['haritalar'] and m in permission] + [m for m in h['haritalar'] if m not in MAP_CLASSES]
        for i, a in enumerate(value_map.get('uzaylilar') or []):
            if i < len(h.get('uzaylilar', [])) and isinstance(a, dict) and 'adet' in a:
                h['uzaylilar'][i]['adet'] = _int(a['adet'], 0, 200)
        if isinstance(value_map.get('quota'), dict) and 'quota' in h:
            h['quota'] = dict({m: n for m, n in h['quota'].items() if m not in MAP_CLASSES},
                             **{m: _int(value_map['quota'].get(m, h['quota'].get(m, max(h['quota'].values(), default=20))), 0, 10000)
                                for m in MAP_CLASSES if m in h['haritalar']})
        if isinstance(value_map.get('patron'), dict) and h.get('patron'):
            for k, parent in (('adet', 50), ('sure_sn', 86400)):
                if k in value_map['patron']:
                    h['patron'][k] = _int(value_map['patron'][k], 0 if k == 'adet' else 60, parent)
    return out


# ------------------------------------------------------------------ bölümler
def _server():
    """Sunucunun harita ve mağaza modülleri (panel ilk açılışta yüklemez: Dünya Editörü açılınca)."""
    import map_links as H
    return H


def npc_icon(tip, t):
    m = str(t.get('model') or tip)
    return 'npc_%s_icon' % m if m.isdigit() else None


def _kinds(x):
    """Davranıştaki uzaylı türleri (olunce_dogur, vurulunca_cagir … 'tur' alanları)."""
    if isinstance(x, dict):
        return ([x['tur']] if isinstance(x.get('tur'), str) else []) + [t for v in x.values() for t in _kinds(v)]
    return [t for v in x for t in _kinds(v)] if isinstance(x, list) else []


def aliens(did):
    w = read(did)
    npc = world_data(did, 'npc.json')
    base = raw('npc.json')['tipler']
    import alien as U
    used_in = {}
    for mid, m in npc['haritalar'].items():
        for g in m.get('npc', []) + m.get('zamanli', []):          # zamanli: saatli Black Light başıboşları
            if map_name(mid) not in used_in.get(g['tip'], []):
                used_in.setdefault(g['tip'], []).append(map_name(mid))
    order = list(used_in)                 # ölünce doğanlar ve çağrılanlar (Blighted Gygerthrall, Lordakium sporu) atasının haritalarında
    for tip in order:
        for sub in _kinds(U.of(npc['tipler'].get(tip, {}))):
            if sub in npc['tipler']:
                missing = [x for x in used_in[tip] if x not in used_in.get(sub, [])]
                if missing:
                    used_in.setdefault(sub, []).extend(missing)
                    order.append(sub)
    patch_count = w['yamalar'].get('npc.json') or {}
    out = []
    for tip, t in npc['tipler'].items():
        out.append({'tip': tip, 'ad': t['ad'], 'hp': t['hp'], 'kalkan': t['kalkan'], 'hasar': t['hasar'], 'hiz': t['hiz'],
                    'saldirgan': t['saldirgan'], 'odul': t.get('odul') or {}, 'kargo': t.get('kargo') or {}, 'ikon': npc_icon(tip, t),
                    'model': t.get('model'), 'npc_kimlik': t.get('npc_kimlik'), 'etkinlik': bool(t.get('etkinlik')) or tip.startswith('etk_'), 'nerede': used_in.get(tip, []),
                    'degisti': DATA.build_path('tipler', tip) in patch_count, 'yeni': tip not in base,
                    'standart': {k: base[tip].get(k) for k in ('ad', 'hp', 'kalkan', 'hasar', 'hiz', 'saldirgan', 'odul', 'kargo')} if tip in base else None,
                    'tam': t})
    return out


def map_name(mid):
    H = _server()
    return H.NAMES.get(int(mid)) or str(mid)


def _firma(name):
    return {'1': 'mmo', '2': 'eic', '3': 'vru'}.get(name[0]) if re.match(r'^\d-\d$', name) and name[0] in '123' else \
        'bl' if name.startswith('BL') else 'korsan' if name.startswith('5-') else 'savas' if name.startswith('4-') else 'diger'


def maps(did):
    w = read(did)
    npc = world_data(did, 'npc.json')
    patch_count = set((w['yamalar'].get('npc.json') or {})) | set('~' + y for y in (w['yamalar'].get('map_layout.json') or {}))
    ores = set(w['yamalar'].get('items.json') or {})
    out = []
    for mid, m in npc['haritalar'].items():
        name = map_name(mid)
        changed = any(y in patch_count for y in (DATA.build_path('haritalar', mid, 'npc'), DATA.build_path('haritalar', mid, 'bonus_kutu'),
                                       '~' + DATA.build_path('haritalar', mid))) or DATA.build_path('cevherler', 'haritalar', name) in ores
        out.append({'id': mid, 'ad': name, 'firma': _firma(name), 'uzayli': sum(g['adet'] for g in m.get('npc', [])),
                    'tur': len(m.get('npc', [])), 'bonus_kutu': m.get('bonus_kutu', 0), 'degisti': changed})
    order = lambda x: ({'mmo': 0, 'eic': 1, 'vru': 2, 'savas': 3, 'korsan': 4, 'bl': 5}.get(x['firma'], 6), x['ad'])
    return sorted(out, key=order)


def game_map(did, mid):
    """Harita editörünün tuvali: boyut, doğma listesi, portallar, istasyon, düzen (güvenli bölgeler, inler, engeller)."""
    H = _server()
    mid = str(mid)
    npc = world_data(did, 'npc.json')
    if mid not in npc['haritalar']:
        raise WorldError(_('Harita bulunamadı.'))
    m = npc['haritalar'][mid]
    layout = world_data(did, 'map_layout.json')['haritalar'].get(mid) or {}
    layout0 = raw('map_layout.json')['haritalar'].get(mid) or {}
    w, h = H.map_size(int(mid)) if hasattr(H, 'map_size') else (H.MAP_W, H.MAP_H)
    portals = []
    for g in H.GATES.get(int(mid), []):
        p = (layout.get('portals') or {}).get(str(g['key']))
        portals.append({'key': g['key'], 'x': p[0] if p else g['x'], 'y': p[1] if p else g['y'], 'hedef': map_name(g['hedef']),
                          'firma': g.get('yalniz_firma'), 'moved': bool(p) and p != (layout0.get('portals') or {}).get(str(g['key']))})
    ist = None
    if int(mid) in H.STATION_MAPS:
        gs = H.GATES.get(int(mid), [])
        ist = list(H.STATION_POS.get(int(mid)) or max(H.CORNERS, key=lambda c: min((((c[0] - g['x']) ** 2 + (c[1] - g['y']) ** 2) ** .5 for g in gs), default=0)))
    types = npc['tipler']
    base = raw('npc.json')['haritalar'].get(mid) or {}
    return {'id': mid, 'ad': map_name(mid), 'firma': _firma(map_name(mid)), 'boyut': [w, h],
            'npc': [dict(g, ad=types.get(g['tip'], {}).get('ad', g['tip']), ikon=npc_icon(g['tip'], types.get(g['tip'], {})),
                         saldirgan=types.get(g['tip'], {}).get('saldirgan', False)) for g in m.get('npc', [])],
            'bonus_kutu': m.get('bonus_kutu', 0), 'portals': portals, 'istasyon': ist, 'yapi': layout.get('yapi'),
            'guvenli': layout.get('guvenli', []), 'lairs': layout.get('lairs', {}), 'obstacles': [e[1:5] for e in layout.get('obstacles', [])],
            'duzen': layout, 'standart': {'npc': base.get('npc', []), 'bonus_kutu': base.get('bonus_kutu', 0), 'duzen': layout0},
            'degisti': {'npc': m.get('npc', []) != base.get('npc', []), 'bonus_kutu': m.get('bonus_kutu', 0) != base.get('bonus_kutu', 0),
                        'duzen': layout != layout0},
            'cevher': ores(did, mid)}


# ---- görevler
def _quest_file(qid):
    return 'quests.json' if str(qid) in raw('quests.json')['gorevler'] else 'quest_extras.json'


def _all_quests(did):
    a = world_data(did, 'quests.json')['gorevler']
    b = world_data(did, 'quest_extras.json')['gorevler']
    return {**{k: ('quests.json', v) for k, v in a.items()}, **{k: ('quest_extras.json', v) for k, v in b.items()}}


def conditions(root):
    """Görevin koşulları (ağacın yaprakları, sırayla): [{id, tur, gosterim, eslesme, hedef, alt: [{tur, eslesme}]}]."""
    out = []

    def walk(case):
        for el in case.get('modifier', []):
            c = el.get('condition') or {}
            if c.get('id'):
                out.append({'id': c['id'], 'tur': c['type'], 'gosterim': c.get('displayType', c['type']), 'matches': list(c.get('matches', [])),
                            'hedef': c.get('targetValue', 0), 'sub': [{'tur': s['type'], 'matches': list(s.get('matches', []))}
                                                                     for s in c.get('subConditions', [])]})
            q = el.get('questCase') or {}
            if q.get('id'):
                walk(q)
    walk(root)
    return out


def _quest_summary(qid, q, file, patch_count, root_count=None):
    k = conditions(q['kok'])
    return {'id': int(qid), 'ad': q.get('ad', str(qid)), 'seviye': q.get('seviye', 1), 'kinds': q.get('kinds', []),
            'kaynak': 'ana' if file == 'quests.json' else 'ek', 'conditions': [{'tur': c['tur'], 'hedef': c['hedef'], 'matches': c['matches'][:3]} for c in k],
            'oduller': q.get('oduller', []), 'kapali': bool(q.get('kapali')), 'yeni': int(qid) >= NEW_QUEST,
            'degisti': DATA.build_path('gorevler', qid) in patch_count, 'etkinlik': bool(q.get('etkinlik')), 'havuz': bool(q.get('havuz'))}


def quests(did):
    w = read(did)
    patch_count = set(w['yamalar'].get('quests.json') or {}) | set(w['yamalar'].get('quest_extras.json') or {})
    return sorted((_quest_summary(qid, q, file, patch_count) for qid, (file, q) in _all_quests(did).items()), key=lambda g: (g['seviye'], g['id']))


def quest(did, qid):
    all_ = _all_quests(did)
    if str(qid) not in all_:
        raise WorldError(_('Görev bulunamadı.'))
    file, q = all_[str(qid)]
    base = raw(file)['gorevler'].get(str(qid))
    w = read(did)
    patch_count = set(w['yamalar'].get(file) or {})
    o = _quest_summary(qid, q, file, patch_count)
    o.update(onceki=q.get('onceki', []), conditions=conditions(q['kok']), sure_sn=q.get('sure_sn'), baslik=q.get('baslik', ''), aciklama=q.get('aciklama', ''),
             standart={'seviye': base['seviye'], 'oduller': base.get('oduller', []), 'onceki': base.get('onceki', []),
                       'conditions': conditions(base['kok'])} if base else None,
             adlar={str(x): all_[str(x)][1].get('ad', str(x)) for x in q.get('onceki', []) if str(x) in all_})
    return o


def save_quest(did, qid, changes):
    """Görevin düzenlenebilir alanları: seviye, önkoşullar, ödüller, koşulların hedefi ve eşleşmesi, kapalı, ad (yalnız yeni görev)."""
    all_ = _all_quests(did)
    if str(qid) not in all_:
        raise WorldError(_('Görev bulunamadı.'))
    file, q = all_[str(qid)]
    q = copy.deepcopy(q)
    d = changes or {}
    if 'seviye' in d:
        q['seviye'] = d['seviye']
    if 'onceki' in d:
        q['onceki'] = [int(x) for x in d['onceki'] if str(x) in all_ and int(x) != int(qid)]
    if 'oduller' in d:
        q['oduller'] = d['oduller']
    if 'kapali' in d:
        if d['kapali']:
            q['kapali'] = True
        else:
            q.pop('kapali', None)
    if 'ad' in d and int(qid) >= NEW_QUEST:
        q['ad'] = ' '.join(str(d['ad']).split())[:60] or q.get('ad')
    for k in ('baslik', 'aciklama'):
        if k in d:
            q[k] = d[k]
    if 'conditions' in d:
        new_ = {int(c['id']): c for c in d['conditions']}

        def walk(case):
            for el in case.get('modifier', []):
                c = el.get('condition') or {}
                if c.get('id') in new_:
                    y = new_[c['id']]
                    c['targetValue'] = _int(y.get('hedef', c.get('targetValue', 1)), 0, 10 ** 9)
                    if 'matches' in y and CONDITION.get(c['type']) in ('npc', 'harita', 'esya', 'cevher'):
                        es = [map_match(x) if CONDITION[c['type']] == 'harita' else str(x) for x in y['matches'] if str(x)]
                        c['matches'] = es or c['matches']
                    if 'harita' in y:          # ON_MAP alt koşulu: boş liste -> her haritada
                        c['subConditions'] = [s for s in c.get('subConditions', []) if s['type'] != SUB_MAP]
                        if y['harita']:
                            c['subConditions'].append(_sub_map(c['id'], y['harita']))
                q2 = el.get('questCase') or {}
                if q2.get('id'):
                    walk(q2)
        walk(q['kok'])
    patch(did, file, DATA.build_path('gorevler', qid), q)


def map_match(x):
    """Görev eşleşmesinde harita: ad "@1-1" (gorev.maps_for çözer; "@own X-3" gibi kalıplar olduğu gibi), kimlik olduğu gibi."""
    x = str(x)
    return x if x.startswith('@') or x.isdigit() else '@' + x


def _sub_map(cid, maps_):
    return {'_': 'QuestConditionModule', 'id': cid * 10 + 7, 'matches': [map_match(x) for x in maps_], 'type': SUB_MAP,
            'displayType': SUB_MAP, 'targetValue': 0, 'mandatory': True,
            'state': {'_': 'QuestConditionStateModule', 'currentValue': 0, 'active': True, 'completed': False}, 'subConditions': []}


def _condition(cid, kind, matches, target, map_list=None):
    return {'_': 'QuestElementModule', 'questCase': {'_': 'QuestCaseModule', 'id': 0, 'active': False, 'mandatory': False, 'ordered': False,
                                                     'mandatoryCount': 0, 'modifier': []},
            'condition': {'_': 'QuestConditionModule', 'id': cid, 'matches': [str(x) for x in matches], 'type': kind, 'displayType': kind,
                          'targetValue': target, 'mandatory': True,
                          'state': {'_': 'QuestConditionStateModule', 'currentValue': 0, 'active': True, 'completed': False},
                          'subConditions': [_sub_map(cid, map_list)] if map_list else []}}


def new_quest(did, name, level, targets, rewards):
    """Yeni görev: hedefler [{tur: avla|topla|kesif|sat|kutu|kargo, eslesme: [...], hedef, harita: [...]}] sırasız, hepsi gerekli.
    Oyundaki başlığı adı (baslik; istemcide metni yok, eklentinin GorevMetinleri yaması gösterir)."""
    if not targets:
        raise WorldError(_('Göreve en az bir hedef ekle.'))
    all_ = _all_quests(did)
    qid = max([NEW_QUEST - 1] + [int(k) for k in all_ if int(k) >= NEW_QUEST]) + 1
    root_id = 1_900_000_000 + (qid - NEW_QUEST) * 100
    mods = []
    for i, x in enumerate(targets[:8]):
        if x.get('tur') not in QUEST_TEMPLATES:
            raise WorldError(_('Bilinmeyen görev hedefi.'))
        kind = QUEST_TEMPLATES[x['tur']][0]
        es = x.get('matches') or []
        if CONDITION[kind] in ('npc', 'esya', 'cevher', 'harita') and not es:
            raise WorldError(_('Her hedef için ne yapılacağını seç.'))
        if CONDITION[kind] == 'harita':
            es = [map_match(m) for m in es]
        mods.append(_condition(root_id + 1 + i, kind, es, _int(x.get('hedef', 1), 1, 10 ** 7), x.get('harita') or None))
    q = {'ad': ' '.join(str(name or '').split())[:60] or _('Yeni görev'), 'seviye': _int(level or 1, 1, 40), 'priority': 500, 'kinds': [2],
         'simge': 0, 'onceki': [], 'kaynak': 'dunya', 'pvp': False,
         'kok': {'_': 'QuestCaseModule', 'id': root_id, 'active': False, 'mandatory': True, 'ordered': False, 'mandatoryCount': len(mods),
                 'modifier': mods},
         'oduller': rewards or []}
    q['baslik'] = q['ad']
    patch(did, 'quest_extras.json', DATA.build_path('gorevler', qid), q)
    return qid


# ---- mağaza ve açık artırma
_CATALOG = {}


def catalog():
    if 'k' not in _CATALOG:
        p = PTH.template('responses.json')
        if not p:
            _CATALOG['k'] = {}
        else:
            import shop as SHP
            with open(p, encoding='utf8') as fh:
                _CATALOG['k'] = SHP.catalog(json.load(fh))
    return _CATALOG['k']


def shop(did):
    product = world_data(did, 'magaza')['urunler']
    out = {}
    for cat, its in catalog().items():
        out[cat] = [dict(it, dunya=product.get(it['lootId'])) for it in its]
    return out


def auction(did):
    lot = world_data(did, 'social.json')['muzayede']['lotlar']
    base = raw('social.json')['muzayede']['lotlar']
    return {'lotlar': [{'loot': l[0], 'grup': l[1], 'tur': l[2], 'adet': l[3], 'anlik': l[4], 'fiyat': l[5]} for l in lot],
            'degisti': lot != base, 'default_count': len(base)}


def item_list():
    """Eşya seçicinin listesi: istemcinin eşyaları (client_items.json) + para birimleri."""
    ist = raw('client_items.json')['esyalar']
    return sorted(set(ist) | {'currency_credits', 'currency_uridium', 'currency_honour', 'currency_experience'})


# ---- kutular ve ganimet, galaksi kapıları, cevherler
def boxes(did):
    """Bonus kutularının içeriği (eşit olasılıklı satırlar) ve anahtarlı kutular (ağırlıklı ödül tablosu, haritalar, adet)."""
    npc = world_data(did, 'npc.json')
    base = raw('npc.json')
    k = world_data(did, 'boxes.json')
    kb = raw('boxes.json')['kutular']
    out = []
    for kind, b in k['kutular'].items():
        if not b.get('odul'):                    # Battle Pass Box (etkinliğe göre), içeriği başka yerde olanlar
            continue
        out.append({'tur': kind, 'ad': b['ad'], 'anahtar': b['anahtar'], 'haritalar': b['haritalar'], 'adet': b['adet'], 'yeniden_sn': b['yeniden_sn'],
                    'takvim': b.get('takvim'), 'odul': b['odul'], 'degisti': b != kb.get(kind), 'spawns': bool(b['haritalar'] and b['adet'])})
    return {'bonus': npc['bonus_kutu'], 'bonus_4x': npc['bonus_kutu_4x'], 'bonus_changed': npc['bonus_kutu'] != base['bonus_kutu'],
            'bonus_4x_changed': npc['bonus_kutu_4x'] != base['bonus_kutu_4x'], 'kutular': out, 'classes': list(raw('boxes.json')['haritalar'])}


def gates(did):
    k = world_data(did, 'gates.json')['kapilar']
    kb = raw('gates.json')['kapilar']
    out = []
    for key, g in k.items():
        o = g['odul']
        out.append({'key': key, 'ad': g['ad'], 'parca': g['parca'], 'can': g['can'], 'degisti': g != kb.get(key),
                    'odul': {x: o.get(x) for x in GATE_REWARD if x in o}, 'cephane': o.get('cephane') or {},
                    'sans': [{'esya': x['esya'], 'adet': x.get('adet'), 'probability': x.get('probability', 0), 'paket': x['esya'] == 'cevher_paketi'}
                             for x in o.get('sans', [])],
                    'standart': {'parca': kb[key]['parca'], 'can': kb[key]['can'], 'odul': {x: kb[key]['odul'].get(x) for x in GATE_REWARD}} if key in kb else None,
                    'waves': [{'ad': w['ad'], 'uzaylilar': [{'tur': a['tur'], 'ad': a.get('gorunen_ad') or a.get('ad'), 'adet': a['adet'], 'hp': a['hp'],
                                                               'changed_kind': key in kb and i < len(kb[key]['waves'][n]['uzaylilar']) and a['tur'] != kb[key]['waves'][n]['uzaylilar'][i]['tur'],
                                                               'sabit': bool(a.get('permanent')) or a['tur'] == 'oyuncu',
                                                               'kalkan': a['kalkan'], 'hasar': a['hasar'], 'hiz': a['hiz'], 'permanent': bool(a.get('permanent')),
                                                               'en_az': sum(1 for grp in w['gruplar'] for j, _ in grp if j == i),
                                                               'ikon': npc_icon(a['tur'], {})}
                                                              for i, a in enumerate(w['uzaylilar'])]} for n, w in enumerate(g['waves'])]})
    return out


def ores(did, mid):
    """Haritanın cevherleri: haritaya özel değer (dünya) yoksa harita sınıfınınki; türler ve yeniden doğma süresi."""
    H = _server()
    c = world_data(did, 'items.json')['cevherler']
    name, klass = map_name(mid), H.map_class(int(mid))
    special = c['haritalar'].get(name) if name != klass else None
    return {'adet': special if special is not None else c['haritalar'].get(klass, {}), 'ozel': special is not None, 'sinif': klass, 'ad': name,
            'kinds': c['kinds'], 'yeniden_sn': c['yeniden_dogma_sn'], 'respawn_default': raw('items.json')['cevherler']['yeniden_dogma_sn'],
            'yol': DATA.build_path('cevherler', 'haritalar', name)}


# ---- oyundaki görev metinleri (eklenti: GorevMetinleri.cs)
TEXT_FILE = os.path.join('BepInEx', 'openorbit', 'quest_texts.json')


def quest_texts(did):
    """Dünyanın görevlerinin oyunda gösterilecek başlık ve açıklamaları: {"<görev>": {baslik, aciklama}}."""
    out = {}
    for qid, (_, q) in _all_quests(did).items():
        m = {k: q[k] for k in ('baslik', 'aciklama') if q.get(k)}
        if m:
            out[qid] = m
    return out


def write_texts(client, did):
    """OYNA: dünyanın görev metinleri istemcinin BepInEx klasörüne (standart dünyada boş: önceki dünyanınkiler kalmasın)."""
    if not client or not os.path.isdir(os.path.join(client, 'BepInEx')):
        return 0
    m = quest_texts(did) if did and did != STANDARD and var(did) else {}
    _write_file(os.path.join(client, TEXT_FILE), m)
    return len(m)


# ---- etkinlikler
def events(did):
    e = world_data(did, 'events.json')['etkinlikler']
    events_raw = raw('events.json')['etkinlikler']
    types = world_data(did, 'npc.json')['tipler']
    out = []
    for key, x in e.items():
        h = x.get('harita')
        game_map = None
        if h:
            game_map = {'haritalar': h.get('haritalar', []), 'quota': h.get('quota', {}),
                      'uzaylilar': [{'tur': a['tur'], 'adet': a['adet'], 'ad': (types.get(a['tur'].replace('{x}', 'x2')) or types.get(a['tur'].replace('{x}', 'x3')) or {}).get('ad', a['tur']),
                                     'ikon': npc_icon(a['tur'], types.get(a['tur'].replace('{x}', 'x2')) or {})} for a in h.get('uzaylilar', [])],
                      'patron': {k: h['patron'][k] for k in ('adet', 'sure_sn') if k in h['patron']} if h.get('patron') else None,
                      'selectable': event_classes(h, types)}
        kind = 'harita' if h else 'yillik' if 'donemler' in x else 'haftalik'
        out.append({'key': key, 'ad': x.get('ad', key), 'tur': kind, 'donemler': [r[:2] for r in x.get('donemler', [])] if 'donemler' in x else None,
                    'days': x.get('days'), 'saatler': x.get('saatler'), 'world_status': x.get('world_status', 'takvim'), 'harita': game_map,
                    'degisti': x != events_raw.get(key)})
    return sorted(out, key=lambda x: ({'harita': 0, 'yillik': 1, 'haftalik': 2}[x['tur']], x['ad'].lower()))


# ---- ödüller ve ekonomi
RANK_FORMULA = ('ep', 'onur', 'seviye', 'npc', 'gorev', 'oyuncu', 'gemi', 'gun', 'dost', 'olum_dusman', 'olum_radyasyon', 'phoenix')


def economy(did):
    lv, raw_levels = world_data(did, 'levels.json')['seviyeler'], raw('levels.json')['seviyeler']
    r, rb = world_data(did, 'ranks.json'), raw('ranks.json')
    return {'seviyeler': lv, 'levels_default': raw_levels, 'formul': r['formul'], 'formula_default': rb['formul'], 'esikler': r['esikler'],
            'thresholds_default': rb['esikler'], 'rutbeler': [x['ad'] for x in r['rutbeler']]}
