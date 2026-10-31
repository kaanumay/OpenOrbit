"""Dünya Editörü'nün deposu ve bölümleri (panel.py'nin /api/dunya… uçları; kullanıcı isteği 2026-10-28, belgeler/DUNYA_EDITORU.md).

Dünya: standart oyun verisinin (server/data) üstüne konan değişiklik katmanı, save/dunyalar/<kimlik>.json:
  {surum, ad, aciklama, kapak, olusturma, guncelleme, yamalar: {dosya: {JSON Pointer: tam değer | {"$sil": true}}}}
Sunucu onu veri.py ile uygular (DO_DUNYA). Standart dünya ("standart") salt okunur: onda yapılan değişiklikler taslağa
(save/dunyalar/_taslak.json) yazılır, "Yeni dünya olarak kaydet" taslağı dünyaya çevirir.
Yalnız izin verilen yollar yazılır (YOLLAR); değerler türüne göre temizlenir (oyun sunucusu bozuk veriyle açılmasın).
Bölümler (editörün görünümleri): standart değer + dünyanınki + değişti işareti; harita, görev ve mağaza ayrıntıları ayrı.
"""
import base64, copy, datetime, hashlib, json, os, re, threading, zlib

import yollar as YOL
import veri as VERI
from dil import t as _

STANDART = 'standart'
KAPAKLAR = ('standart', 'nebula', 'crimson', 'ice', 'mining', 'crystal', 'toxic', 'void')
SURUM = 1
AD_UZUNLUK, ACIKLAMA_UZUNLUK = 40, 240
YENI_GOREV = 900000              # yeni görevlerin kimliği buradan (oyunun görevleri < 900000; kök durumu ve koşul kimlikleri ayrı aralıkta)
YENI_UZAYLI = 'ozel_'            # yeni uzaylı türlerinin anahtarı (ozel_1, ozel_2 …)
ADET_EN_COK = 300                # bir haritada bir türün en çok adedi
# bölüm -> (dosya, yol öneki) listesi: değişiklik sayısı ve "bölümü standarda döndür"
BOLUMLER = {
    'haritalar': [('npc.json', '/haritalar/'), ('harita_duzeni.json', '/haritalar/'), ('esyalar.json', '/cevherler/')],
    'uzaylilar': [('npc.json', '/tipler/')],
    'gorevler': [('gorevler.json', '/gorevler/'), ('gorev_ekleri.json', '/gorevler/')],
    'magaza': [('magaza', '/urunler/')],
    'muzayede': [('sosyal.json', '/muzayede/')],
    'kutular': [('npc.json', '/bonus_kutu'), ('kutular.json', '/kutular/')],
    'kapilar': [('kapilar.json', '/kapilar/')],
    'etkinlikler': [('etkinlikler.json', '/etkinlikler/')],
    'ekonomi': [('seviyeler.json', '/seviyeler'), ('rutbe.json', '/')],
}
YOLLAR = [(d, re.compile(r)) for d, r in (
    ('npc.json', r'^/tipler/[^/]+$'), ('npc.json', r'^/haritalar/[^/]+/(npc|bonus_kutu)$'), ('harita_duzeni.json', r'^/haritalar/[^/]+$'),
    ('gorevler.json', r'^/gorevler/\d+$'), ('gorev_ekleri.json', r'^/gorevler/\d+$'), ('magaza', r'^/urunler/[^/]+$'),
    ('sosyal.json', r'^/muzayede/lotlar$'), ('npc.json', r'^/bonus_kutu(_4x)?$'), ('kutular.json', r'^/kutular/[^/]+$'),
    ('kapilar.json', r'^/kapilar/[^/]+$'), ('etkinlikler.json', r'^/etkinlikler/[^/]+$'),
    ('seviyeler.json', r'^/seviyeler$'), ('rutbe.json', r'^/(formul|esikler)$'), ('esyalar.json', r'^/cevherler/haritalar/[^/]+$'), ('esyalar.json', r'^/cevherler/yeniden_dogma_sn$'))]
KAPI_ODUL = ('ep', 'onur', 'uridyum', 'xenomit', 'log_disk', 'kupon')           # kapı ödülünün düzenlenen sayıları
KAPI_UZAYLI = ('adet', 'hp', 'kalkan', 'hasar', 'hiz')                       # dalga uzaylısının düzenlenen değerleri
PAKET = 'paket'                                                             # ganimet.PAKET: kutu ödülünde birden çok eşyalı satır
NPC_SAYI = ('hp', 'kalkan', 'hasar', 'hiz')
ODUL = ('ep', 'onur', 'kredi', 'uridyum')
# görev koşul türleri (gorev.py, gorev_takip.py): editörün anladığı -> eşleşmenin anlamı
KOSUL = {6: 'npc', 27: 'npc', 34: 'harita', 67: 'esya', 51: 'yok', 55: 'yok', 52: 'cevher', 28: 'yok', 53: 'yok', 62: 'yok',
         35: 'yok', 42: 'yok', 2: 'sure', 3: 'sure', 63: 'sure', 13: 'yok', 12: 'yok', 7: 'yok', 9: 'yok', 80: 'kapi'}
ALT_HARITA = 77
GOREV_SABLONLARI = {          # yeni görevin hedef türü -> (koşul türü, gösterim, eşleşme)
    'avla': (6, 6), 'topla': (67, 67), 'kesif': (34, 34), 'sat': (52, 52), 'kutu': (55, 55), 'kargo': (51, 51),
}
_KILIT = threading.Lock()


class DunyaHatasi(ValueError):
    """Kullanıcıya gösterilen hata (panel.py 400 döner)."""


def klasor():
    return os.path.join(YOL.SAVE, 'dunyalar')


def _yol(did):
    if did == STANDART:
        return os.path.join(klasor(), '_taslak.json')
    if not isinstance(did, str) or not re.fullmatch(r'[a-z0-9_]{1,40}', did):
        raise DunyaHatasi(_('Dünya bulunamadı.'))
    return os.path.join(klasor(), did + '.json')


def _oku_dosya(p):
    try:
        with open(p, encoding='utf8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _yaz_dosya(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _simdi():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def var(did):
    return did == STANDART or (isinstance(did, str) and re.fullmatch(r'[a-z0-9_]{1,40}', did) and os.path.isfile(_yol(did)))


def oku(did):
    """Dünya (standart: taslağın yamalarıyla). Yoksa DunyaHatasi."""
    if did == STANDART:
        d = _oku_dosya(_yol(did)) or {}
        return {'id': STANDART, 'ad': _('Standart dünya'), 'aciklama': _('Oyunun kendi içeriği. Düzenlenemez: değişikliklerini yeni bir dünya olarak kaydet.'),
                'kapak': 'standart', 'standart': True, 'yamalar': d.get('yamalar') or {}}
    d = _oku_dosya(_yol(did))
    if d is None:
        raise DunyaHatasi(_('Dünya bulunamadı.'))
    d.setdefault('yamalar', {})
    d['id'] = did
    return d


def _kaydet(did, d):
    d = {k: v for k, v in d.items() if k not in ('id', 'standart')}
    if did != STANDART:
        d['guncelleme'] = _simdi()
    d['surum'] = SURUM
    _yaz_dosya(_yol(did), d)


def dosya_yolu(did):
    """Sunucuya verilecek dünya dosyası (DO_DUNYA); standart ya da olmayan dünya: None."""
    return _yol(did) if did and did != STANDART and var(did) else None


def sayilar(yamalar):
    """Bölüm başına değişiklik sayısı."""
    out = {b: 0 for b in BOLUMLER}
    for dosya, ys in (yamalar or {}).items():
        for y in ys or {}:
            b = bolum_of(dosya, y)
            if b:
                out[b] += 1
    return out


def bolum_of(dosya, yol):
    return next((b for b, ps in BOLUMLER.items() for d, p in ps if d == dosya and yol.startswith(p)), None)


def ozet(did, kullananlar=None):
    d = oku(did)
    n = sayilar(d['yamalar'])
    return {'id': did, 'ad': d.get('ad') or did, 'aciklama': d.get('aciklama', ''), 'kapak': d.get('kapak') if d.get('kapak') in KAPAKLAR else 'nebula',
            'standart': did == STANDART, 'olusturma': d.get('olusturma'), 'guncelleme': d.get('guncelleme'),
            'degisiklik': sum(n.values()), 'bolumler': n, 'kullananlar': (kullananlar or {}).get(did, [])}


def liste(kullananlar=None):
    """Standart dünya önce, sonra özel dünyalar (son güncellenen önce)."""
    out = []
    if os.path.isdir(klasor()):
        for f in os.listdir(klasor()):
            did = f[:-5] if f.endswith('.json') else None
            if did and not did.startswith('_') and re.fullmatch(r'[a-z0-9_]{1,40}', did):
                try:
                    out.append(ozet(did, kullananlar))
                except DunyaHatasi:
                    pass
    out.sort(key=lambda w: w['guncelleme'] or '', reverse=True)
    return [ozet(STANDART, kullananlar)] + out


def _ad_temizle(ad):
    ad = ' '.join(str(ad or '').split())[:AD_UZUNLUK]
    if not ad:
        raise DunyaHatasi(_('Dünyaya bir ad ver.'))
    return ad


def _yeni_kimlik(ad):
    tr = str.maketrans('çğıöşüâîûÇĞİÖŞÜ', 'cgiosuaiuCGIOSU')
    k = re.sub(r'[^a-z0-9]+', '_', ad.translate(tr).lower()).strip('_')[:30] or 'dunya'
    if k == STANDART:
        k = 'dunya'
    did, n = k, 2
    while os.path.exists(_yol(did)):
        did, n = '%s_%d' % (k, n), n + 1
    return did


def olustur(ad, aciklama='', kapak='nebula', kaynak=None, taslaktan=False):
    """Yeni dünya: boş (standart), kaynak dünyanın kopyası ya da standart dünyanın taslağından (taslak sonra silinir)."""
    with _KILIT:
        ad = _ad_temizle(ad)
        yamalar = {}
        if taslaktan:
            yamalar = oku(STANDART)['yamalar']
        elif kaynak and kaynak != STANDART:
            yamalar = copy.deepcopy(oku(kaynak)['yamalar'])
        did = _yeni_kimlik(ad)
        _kaydet(did, {'ad': ad, 'aciklama': str(aciklama or '')[:ACIKLAMA_UZUNLUK], 'kapak': kapak if kapak in KAPAKLAR[1:] else 'nebula',
                      'olusturma': _simdi(), 'yamalar': yamalar})
        if taslaktan:
            taslak_at()
        return did


def guncelle(did, ad=None, aciklama=None, kapak=None):
    if did == STANDART:
        raise DunyaHatasi(_('Standart dünya değiştirilemez.'))
    with _KILIT:
        d = oku(did)
        if ad is not None:
            d['ad'] = _ad_temizle(ad)
        if aciklama is not None:
            d['aciklama'] = str(aciklama)[:ACIKLAMA_UZUNLUK]
        if kapak is not None and kapak in KAPAKLAR[1:]:
            d['kapak'] = kapak
        _kaydet(did, d)


def sil(did):
    if did == STANDART:
        raise DunyaHatasi(_('Standart dünya silinemez.'))
    p = _yol(did)
    if not os.path.isfile(p):
        raise DunyaHatasi(_('Dünya bulunamadı.'))
    os.makedirs(os.path.join(klasor(), '_silinenler'), exist_ok=True)
    os.replace(p, os.path.join(klasor(), '_silinenler', '%s_%s.json' % (did, datetime.datetime.now().strftime('%Y%m%d%H%M%S'))))


def kopyala(did, ad=None):
    d = oku(did)
    return olustur(ad or _('{0} (kopya)').format(d.get('ad') or did)[:AD_UZUNLUK], d.get('aciklama', ''), d.get('kapak', 'nebula'),
                   kaynak=did if did != STANDART else None, taslaktan=False) if did != STANDART else \
        olustur(ad or _('Yeni dünya'), '', 'nebula')


KOD_ONEKI = 'OODUNYA1:'


def veri_imzasi(dosyalar):
    """Standart veri dosyalarının özeti (paylaşılan dünyanın hangi oyun verisiyle hazırlandığı): {dosya: sha1'in ilk 12'si}."""
    out = {}
    for f in dosyalar:
        p = os.path.join(VERI.DATA, f)
        if f not in VERI.SANAL and os.path.isfile(p):
            with open(p, 'rb') as fh:
                out[f] = hashlib.sha1(fh.read()).hexdigest()[:12]
    return out


def disari(did):
    """Paylaşılacak dünya: ad, açıklama, kapak, yamalar; hazırlandığı veri (veri_imzasi) ve bölüm sayıları (içe aktarırken uyarı)."""
    d = oku(did)
    return {'openorbit_dunya': SURUM, 'ad': d.get('ad'), 'aciklama': d.get('aciklama', ''), 'kapak': d.get('kapak', 'nebula'),
            'tarih': _simdi(), 'veri': veri_imzasi(d['yamalar']), 'bolumler': sayilar(d['yamalar']), 'yamalar': d['yamalar']}


def kod(did):
    """Paylaşım kodu: OODUNYA1: + base64(zlib(dünya)); Discord'a ya da sohbete yapıştırılır."""
    ham_ = json.dumps(disari(did), ensure_ascii=False, separators=(',', ':')).encode('utf8')
    return KOD_ONEKI + base64.urlsafe_b64encode(zlib.compress(ham_, 9)).decode('ascii')


def koddan(metin):
    metin = ''.join(str(metin or '').split())
    if not metin.startswith(KOD_ONEKI):
        raise DunyaHatasi(_('Bu bir OpenOrbit dünya kodu değil.'))
    try:
        return json.loads(zlib.decompress(base64.urlsafe_b64decode(metin[len(KOD_ONEKI):] + '=' * (-len(metin) % 4))).decode('utf8'))
    except (ValueError, zlib.error):
        raise DunyaHatasi(_('Dünya kodu bozuk ya da eksik kopyalanmış.'))


def iceri(veri):
    """Paylaşılan dünyayı yeni dünya olarak ekler -> (kimlik, rapor). İzinsiz yollar atlanır, her değer düzenleyicinin süzgecinden
    geçer (bozuk olan atlanır); dünya başka bir oyun verisiyle hazırlandıysa rapor söyler."""
    if not isinstance(veri, dict) or 'yamalar' not in veri or not isinstance(veri['yamalar'], dict):
        raise DunyaHatasi(_('Bu dosya bir OpenOrbit dünyası değil.'))
    if int(veri.get('openorbit_dunya') or 1) > SURUM:
        raise DunyaHatasi(_('Bu dünya panelin daha yeni bir sürümüyle hazırlanmış: önce paneli güncelle.'))
    temiz, atlanan = {}, 0
    for dosya, ys in veri['yamalar'].items():
        for y, v in (ys or {}).items() if isinstance(ys, dict) else ():
            if izinli(dosya, y):
                temiz.setdefault(dosya, {})[y] = v
            else:
                atlanan += 1
    did = olustur(veri.get('ad') or _('İçe aktarılan dünya'), veri.get('aciklama', ''), veri.get('kapak', 'nebula'))
    sorunlar = []
    with _KILIT:
        d = oku(did)
        d['yamalar'] = temiz
        _kaydet(did, d)                          # süzgeç dünyanın kendi türlerini (ozel_*) görsün diye önce olduğu gibi
        sira = sorted(((f, y) for f, ys in temiz.items() for y in ys), key=lambda x: (x[0] != 'npc.json' or not x[1].startswith('/tipler/'), x))
        for f, y in sira:
            try:
                temiz[f][y] = temizle(did, f, y, temiz[f][y])
            except (DunyaHatasi, KeyError, IndexError, TypeError, ValueError, AttributeError, ArithmeticError) as e:
                del temiz[f][y]
                sorunlar.append('%s %s: %s' % (f, y, e))
        d['yamalar'] = {f: ys for f, ys in temiz.items() if ys}
        _kaydet(did, d)
    simdi = veri_imzasi(veri.get('veri') or {})
    farkli = sorted(f for f, h in (veri.get('veri') or {}).items() if simdi.get(f) != h)
    return did, {'degisiklik': sum(len(v) for v in d['yamalar'].values()), 'atlanan': atlanan + len(sorunlar), 'sorunlar': sorunlar[:12],
                 'veri_farkli': farkli, 'tarih': veri.get('tarih')}


def taslak_at():
    p = _yol(STANDART)
    if os.path.isfile(p):
        os.remove(p)


# ------------------------------------------------------------------ yamalar
def izinli(dosya, yol):
    return any(d == dosya and r.match(yol) for d, r in YOLLAR)


def yama(did, dosya, yol, deger):
    """Dünyaya (standartta taslağa) bir değişiklik: tam değer. Standart değere eşitse yama kaldırılır."""
    if not izinli(dosya, yol):
        raise DunyaHatasi(_('Bu içerik düzenlenemez.'))
    deger = temizle(did, dosya, yol, deger)
    with _KILIT:
        d = oku(did)
        ys = d['yamalar'].setdefault(dosya, {})
        if deger == standart_deger(dosya, yol):
            ys.pop(yol, None)
        else:
            ys[yol] = deger
        if not ys:
            d['yamalar'].pop(dosya, None)
        _kaydet(did, d)


def geri_al(did, dosya=None, yol=None, bolum=None):
    """Bir değişikliği (dosya + yol) ya da bölümün bütün değişikliklerini standarda döndürür."""
    with _KILIT:
        d = oku(did)
        for f in list(d['yamalar']):
            for y in list(d['yamalar'][f] or {}):
                if (bolum and bolum_of(f, y) == bolum) or (f == dosya and y == yol):
                    del d['yamalar'][f][y]
            if not d['yamalar'][f]:
                del d['yamalar'][f]
        _kaydet(did, d)


_HAM = {}


def ham(dosya):
    """Standart veri (önbellekli)."""
    if dosya not in _HAM:
        _HAM[dosya] = VERI.ham(dosya)
    return _HAM[dosya]


def _al(veri, yol):
    for p in VERI.yol_parcalari(yol):
        if isinstance(veri, list):
            veri = veri[int(p)]
        elif isinstance(veri, dict) and p in veri:
            veri = veri[p]
        else:
            return None
    return veri


def standart_deger(dosya, yol):
    return _al(ham(dosya), yol)


def dunya_verisi(did, dosya):
    """Dosyanın dünyadaki hâli (standart + yamalar; kopya)."""
    v = copy.deepcopy(ham(dosya))
    VERI.uygula(v, oku(did)['yamalar'].get(dosya) or {}, dosya)
    return v


def _int(v, alt=0, ust=10 ** 9):
    try:
        return max(alt, min(ust, int(round(float(v)))))
    except (TypeError, ValueError, OverflowError):      # 1e999 / Infinity (içe aktarılan dünya kodu)
        raise DunyaHatasi(_('Sayı bekleniyordu.'))


def temizle(did, dosya, yol, v):
    """Değeri oyunun okuyacağı biçime getirir; uymayan değer DunyaHatasi."""
    parca = VERI.yol_parcalari(yol)
    if isinstance(v, dict) and v.get(VERI.SIL):
        if dosya == 'npc.json' and parca[0] == 'tipler' and not parca[1].startswith(YENI_UZAYLI):
            raise DunyaHatasi(_('Oyunun uzaylıları silinemez; doğma listelerinden çıkarabilirsin.'))
        if dosya in ('gorevler.json', 'gorev_ekleri.json') and int(parca[1]) < YENI_GOREV:
            raise DunyaHatasi(_('Oyunun görevleri silinemez; kapatabilirsin.'))
        return {VERI.SIL: True}
    if dosya == 'npc.json' and parca[0] == 'tipler':
        if not isinstance(v, dict):
            raise DunyaHatasi(_('Uzaylı verisi bozuk.'))
        v = dict(v)
        v['ad'] = ' '.join(str(v.get('ad') or '').split())[:60] or '?'
        for k in NPC_SAYI:
            v[k] = _int(v.get(k, 0), 0, 50_000_000 if k in ('hp', 'kalkan') else 1_000_000 if k == 'hasar' else 2000)
        v['saldirgan'] = bool(v.get('saldirgan'))
        v['odul'] = {k: _int((v.get('odul') or {}).get(k, 0), 0, 10 ** 9) for k in ODUL}
        v['kargo'] = {str(_int(k, 0, 99)): _int(n, 0, 100_000) for k, n in (v.get('kargo') or {}).items() if _int(n, 0, 100_000) > 0}
        if parca[1].startswith(YENI_UZAYLI) and not v.get('model'):
            raise DunyaHatasi(_('Yeni uzaylının bir modeli olmalı.'))
        return v
    if dosya == 'npc.json' and parca[0] == 'haritalar':
        tipler = dunya_verisi(did, 'npc.json')['tipler']
        if len(parca) == 3 and parca[2] == 'bonus_kutu':
            return _int(v, 0, 300)
        if len(parca) == 3 and parca[2] == 'npc':
            if not isinstance(v, list):
                raise DunyaHatasi(_('Doğma listesi bozuk.'))
            out = []
            for g in v:
                tip = str(g.get('tip'))
                if tip not in tipler:
                    continue
                e = {'tip': tip, 'adet': _int(g.get('adet', 1), 0, ADET_EN_COK)}
                b = g.get('bolge')
                if isinstance(b, list) and len(b) == 3:
                    e['bolge'] = [_int(b[0], 0, 42000), _int(b[1], 0, 26200), _int(b[2], 200, 15000)]
                out.append(e)
            return out
        raise DunyaHatasi(_('Bu içerik düzenlenemez.'))
    if dosya == 'harita_duzeni.json':
        if not isinstance(v, dict):
            raise DunyaHatasi(_('Harita düzeni bozuk.'))
        v = copy.deepcopy(v)
        if 'guvenli' in v:
            v['guvenli'] = [[_int(a, 0, 42000), _int(b, 0, 26200), _int(r, 100, 6000)] for a, b, r in v['guvenli']]
        if 'inler' in v:
            v['inler'] = {str(t): [[_int(a, 0, 42000), _int(b, 0, 26200)] for a, b in pts] for t, pts in v['inler'].items() if pts}
        if 'portallar' in v:
            v['portallar'] = {str(k): [_int(p[0], 0, 42000), _int(p[1], 0, 26200)] for k, p in v['portallar'].items()}
        return v
    if dosya in ('gorevler.json', 'gorev_ekleri.json'):
        if not isinstance(v, dict) or 'kok' not in v:
            raise DunyaHatasi(_('Görev verisi bozuk.'))
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
    if dosya == 'magaza':
        if not isinstance(v, dict):
            raise DunyaHatasi(_('Ürün verisi bozuk.'))
        out = {}
        if v.get('fiyat') is not None:
            out['fiyat'] = _int(v['fiyat'], 0, 10 ** 10)
            out['para'] = 'C' if v.get('para') == 'C' else 'U'
        if v.get('satista') is False:
            out['satista'] = False
        return out
    if dosya == 'npc.json' and parca[0] in ('bonus_kutu', 'bonus_kutu_4x'):
        out = [[str(l), _int(n, 1, 10 ** 7)] for l, n in (v if isinstance(v, list) else []) if str(l)]
        if not out:
            raise DunyaHatasi(_('Bonus kutusunda en az bir ödül olmalı.'))
        return out
    if dosya == 'kutular.json':
        return _kutu_temizle(parca[1], v)
    if dosya == 'kapilar.json':
        return _kapi_temizle(parca[1], v, dunya_verisi(did, 'npc.json')['tipler'])
    if dosya == 'seviyeler.json':
        base = ham('seviyeler.json')['seviyeler']
        ep = [_int(x[1] if isinstance(x, list) else x, 0, 10 ** 20) for x in (v if isinstance(v, list) else [])]
        # tarayıcı 2^53'ten büyük sayıları yuvarlar (son seviyeler ~10^18): yuvarlama payındaki değer standarttır
        ep = [b[1] if abs(n - b[1]) <= b[1] * 1e-12 else n for n, b in zip(ep, base)]
        if len(ep) != len(base) or ep[0] != 0 or any(b <= a for a, b in zip(ep, ep[1:])):
            raise DunyaHatasi(_('Seviye eşikleri sıfırdan başlayıp artmalı.'))
        return [[lv, n] for (lv, _), n in zip(base, ep)]
    if dosya == 'rutbe.json' and parca[0] == 'esikler':
        base = ham('rutbe.json')['esikler']
        n = [_int(x, 0, 10 ** 12) for x in (v if isinstance(v, list) else [])]
        if len(n) != len(base) or n[0] != 0 or any(b <= a for a, b in zip(n, n[1:])):
            raise DunyaHatasi(_('Rütbe eşikleri sıfırdan başlayıp artmalı.'))
        return n
    if dosya == 'rutbe.json' and parca[0] == 'formul':
        base = ham('rutbe.json')['formul']
        try:
            return {k: max(-10 ** 6, min(10 ** 6, float(v.get(k, d)))) for k, d in base.items()}
        except (AttributeError, TypeError, ValueError):
            raise DunyaHatasi(_('Sayı bekleniyordu.'))
    if dosya == 'etkinlikler.json':
        return _etkinlik_temizle(parca[1], v, dunya_verisi(did, 'npc.json')['tipler'])
    if dosya == 'esyalar.json':
        if parca[-1] == 'yeniden_dogma_sn':
            lo, hi = sorted(_int(x, 1, 86400) for x in (v if isinstance(v, list) and len(v) == 2 else [15, 30]))
            return [lo, hi]
        turler = ham('esyalar.json')['cevherler']['turler']
        out = {str(t): _int(n, 0, 1000) for t, n in (v or {}).items() if str(t) in turler}
        return out or {'0': 0}                   # hepsi 0: haritada cevher yok (boş sözlük sınıfın değerine düşerdi)
    if dosya == 'sosyal.json':
        if not isinstance(v, list):
            raise DunyaHatasi(_('Lot listesi bozuk.'))
        out = []
        for l in v:
            loot, tur = str(l[0]), l[2] if l[2] in ('hour', 'day', 'week') else 'hour'
            out.append([loot, str(l[1] or 'other'), tur, _int(l[3], 1, 10 ** 7), bool(l[4]), _int(l[5], 0, 10 ** 9)])
        seen = set()
        return [l for l in out if (l[2], l[0]) not in seen and not seen.add((l[2], l[0]))]      # lot anahtarı (tür, eşya) tek
    return v


def _kutu_temizle(tur, v):
    """Anahtarlı kutu: haritalardaki adet, yeniden doğma, harita sınıfları ve ödül tablosu (satır: [eşya, adet | [en az, en çok],
    ağırlık]; paket satırı olduğu gibi). Öteki alanlar (anahtar, takvim, mesajlar) standarttan."""
    base = ham('kutular.json')['kutular'].get(tur)
    if base is None or not isinstance(v, dict):
        raise DunyaHatasi(_('Kutu bulunamadı.'))
    out = copy.deepcopy(base)
    siniflar = ham('kutular.json')['haritalar']
    if 'adet' in v:
        out['adet'] = _int(v['adet'], 0, 100)
    if 'yeniden_sn' in v and isinstance(v['yeniden_sn'], list) and len(v['yeniden_sn']) == 2:
        out['yeniden_sn'] = sorted(_int(x, 10, 86400) for x in v['yeniden_sn'])
    if 'haritalar' in v:
        out['haritalar'] = [m for m in v['haritalar'] if m in siniflar]
    if 'odul' in v and base.get('odul'):
        rows = []
        for r in v['odul'] if isinstance(v['odul'], list) else []:
            if not isinstance(r, list) or len(r) != 3:
                continue
            w = max(0.0, min(1e6, float(r[2] or 0)))
            if w <= 0:
                continue
            if r[0] == PAKET:
                if any(b[0] == PAKET and b[1] == r[1] for b in base['odul']):
                    rows.append([PAKET, r[1], w])
                continue
            n = sorted(_int(x, 1, 10 ** 7) for x in r[1]) if isinstance(r[1], list) and len(r[1]) == 2 else _int(r[1], 1, 10 ** 7)
            rows.append([str(r[0]), n, w])
        if not rows:
            raise DunyaHatasi(_('Kutuda en az bir ödül olmalı.'))
        out['odul'] = rows
    return out


def _gruplar(gruplar, i, eski, yeni):
    """Dalganın alt gruplarında uzaylı i'nin adetlerini eskiden yeniye orantılı ölçekler (her satır en az 1; toplam yeni)."""
    yer = [(g, k) for g, grp in enumerate(gruplar) for k, (j, n) in enumerate(grp) if j == i]
    if not yer or eski <= 0:
        return
    yeni = max(yeni, len(yer))
    pay = [max(1, round(gruplar[g][k][1] * yeni / eski)) for g, k in yer]
    fark = yeni - sum(pay)
    sira = sorted(range(len(pay)), key=lambda x: -pay[x])
    while fark:
        for x in sira:
            if fark > 0:
                pay[x] += 1
                fark -= 1
            elif fark < 0 and pay[x] > 1:
                pay[x] -= 1
                fark += 1
            if not fark:
                break
    for (g, k), n in zip(yer, pay):
        gruplar[g][k] = [i, n]


def _kapi_temizle(key, v, tipler=None):
    """Galaksi Kapısı: parça, can, ödül sayıları, cephane ödülü, şanslı ödüllerin olasılığı ve adedi, dalgaların uzaylı değerleri
    (adet değişince alt gruplar orantılı ölçeklenir). Dalga ve uzaylı listesinin yapısı standarttan (kapi.py'nin sayaçları ona bağlı)."""
    base = ham('kapilar.json')['kapilar'].get(key)
    if base is None or not isinstance(v, dict):
        raise DunyaHatasi(_('Kapı bulunamadı.'))
    out = copy.deepcopy(base)
    for k in ('parca', 'can'):
        if k in v:
            out[k] = _int(v[k], 1, 10000)
    o, vo = out['odul'], v.get('odul') or {}
    for k in KAPI_ODUL:
        if k in vo and k in o:
            o[k] = _int(vo[k], 0, 10 ** 10)
    if isinstance(vo.get('cephane'), dict):
        o['cephane'] = {str(l): _int(n, 1, 10 ** 8) for l, n in vo['cephane'].items() if str(l)}
    for i, x in enumerate(vo.get('sans') or []):
        if i < len(o.get('sans', [])) and isinstance(x, dict):
            if 'olasilik' in x:
                o['sans'][i]['olasilik'] = max(0.0, min(1.0, float(x['olasilik'])))
            if 'adet' in x and isinstance(o['sans'][i].get('adet'), int):
                o['sans'][i]['adet'] = _int(x['adet'], 1, 10 ** 7)
    for n, vw in enumerate(v.get('dalgalar') or []):
        if n >= len(out['dalgalar']) or not isinstance(vw, dict):
            continue
        w = out['dalgalar'][n]
        for i, va in enumerate(vw.get('uzaylilar') or []):
            if i >= len(w['uzaylilar']) or not isinstance(va, dict):
                continue
            a = w['uzaylilar'][i]
            tur = str(va.get('tur') or a['tur'])
            # yalnız istemcinin gemi türü olan anahtarlar (kapi.register_npcs türü model olarak gönderir: "ozel_1", "etk_…" olmaz)
            if tur != a['tur'] and not a.get('kalici') and a['tur'] != 'oyuncu' and tur.isdigit() and tur in (tipler or {}):
                t = tipler[tur]                          # uzaylıyı başka türle değiştir: türün değerleri, dalgadaki adet ve yer aynı
                a.update(tur=tur, ad=re.sub(r'^[-=\[\]:.{}\s]+|[-=\[\]:.{}\s]+$', '', t['ad']) or tur, gorunen_ad=t['ad'],
                         npc_kimlik=t.get('npc_kimlik', a.get('npc_kimlik')), hp=t['hp'], kalkan=t['kalkan'], hasar=t['hasar'], hiz=t['hiz'],
                         odul=dict(t.get('odul') or {}), kargo=dict(t.get('kargo') or {}))
                a.pop('davranis', None)
            for k in KAPI_UZAYLI:
                if k not in va:
                    continue
                yeni = _int(va[k], 1 if k == 'adet' else 0, 50_000_000)
                if k == 'adet':
                    eski = sum(c for grp in w['gruplar'] for j, c in grp if j == i)
                    _gruplar(w['gruplar'], i, eski, yeni)
                    yeni = sum(c for grp in w['gruplar'] for j, c in grp if j == i) or yeni
                a[k] = yeni
            if isinstance(va.get('odul'), dict):
                a['odul'] = {k: _int(va['odul'].get(k, a['odul'].get(k, 0)), 0, 10 ** 9) for k in ODUL}
    return out


SINIFLAR = tuple('X-%d' % n for n in range(1, 9))      # harita etkinliklerinin harita sınıfları


def _tarih(x):
    """Dönem ucu: 'YYYY-AA-GG' ya da her yıl 'AA-GG' (takvim._spans)."""
    x = str(x or '').strip()
    for bicim in ('%Y-%m-%d', '%m-%d'):
        try:
            datetime.datetime.strptime(x if bicim == '%Y-%m-%d' else '2024-' + x, '%Y-%m-%d')
            return x
        except ValueError:
            pass
    raise DunyaHatasi(_('Tarih geçersiz: %s', x))


def etkinlik_siniflari(h, tipler):
    """Harita etkinliğinin seçilebilen sınıfları: uzaylılarının ve patronunun o sınıfa özgü türü (etk_<ad>_x<n>) olanlar."""
    turler = [a['tur'] for a in h.get('uzaylilar', [])] + list((h.get('patron') or {}).get('turler', []))
    return [m for m in SINIFLAR if all(t.replace('{x}', 'x' + m[2:]) in tipler for t in turler)]


def _etkinlik_temizle(key, v, tipler):
    """Etkinlik: dünyadaki durum (dunya_durum: acik | kapali | takvim), dönemler ([başlangıç, bitiş] + standart satırın kuyruğu: saatler,
    'tek'), harita bölümü (haritalar, uzaylı adetleri, harita kotaları, patron adedi ve süresi). Öteki alanlar standarttan."""
    base = ham('etkinlikler.json')['etkinlikler'].get(key)
    if base is None or not isinstance(v, dict):
        raise DunyaHatasi(_('Etkinlik bulunamadı.'))
    out = copy.deepcopy(base)
    if v.get('dunya_durum') in ('acik', 'kapali'):
        out['dunya_durum'] = v['dunya_durum']
    if isinstance(v.get('donemler'), list) and 'donemler' in base:
        kuyruk = {(r[0], r[1]): r[2:] for r in base['donemler']}
        rows = []
        for r in v['donemler']:
            if isinstance(r, list) and len(r) >= 2:
                a, b = _tarih(r[0]), _tarih(r[1])
                if len(a) != len(b):
                    raise DunyaHatasi(_('Dönemin iki ucu da aynı biçimde olmalı (yıllı ya da her yıl).'))
                rows.append([a, b] + list(kuyruk.get((r[0], r[1]), [])))
        out['donemler'] = rows
    h, vh = out.get('harita'), v.get('harita')
    if h and isinstance(vh, dict):
        if isinstance(vh.get('haritalar'), list):
            izin = etkinlik_siniflari(h, tipler)          # X-n dışındakiler (Sunburst'ün 4-X'i) olduğu gibi
            h['haritalar'] = [m for m in SINIFLAR if m in vh['haritalar'] and m in izin] + [m for m in h['haritalar'] if m not in SINIFLAR]
        for i, a in enumerate(vh.get('uzaylilar') or []):
            if i < len(h.get('uzaylilar', [])) and isinstance(a, dict) and 'adet' in a:
                h['uzaylilar'][i]['adet'] = _int(a['adet'], 0, 200)
        if isinstance(vh.get('kota'), dict) and 'kota' in h:
            h['kota'] = dict({m: n for m, n in h['kota'].items() if m not in SINIFLAR},
                             **{m: _int(vh['kota'].get(m, h['kota'].get(m, max(h['kota'].values(), default=20))), 0, 10000)
                                for m in SINIFLAR if m in h['haritalar']})
        if isinstance(vh.get('patron'), dict) and h.get('patron'):
            for k, ust in (('adet', 50), ('sure_sn', 86400)):
                if k in vh['patron']:
                    h['patron'][k] = _int(vh['patron'][k], 0 if k == 'adet' else 60, ust)
    return out


# ------------------------------------------------------------------ bölümler
def _sunucu():
    """Sunucunun harita ve mağaza modülleri (panel ilk açılışta yüklemez: Dünya Editörü açılınca)."""
    import harita as H
    return H


def npc_ikon(tip, t):
    m = str(t.get('model') or tip)
    return 'npc_%s_icon' % m if m.isdigit() else None


def uzaylilar(did):
    w = oku(did)
    npc = dunya_verisi(did, 'npc.json')
    base = ham('npc.json')['tipler']
    nerede = {}
    for mid, m in npc['haritalar'].items():
        for g in m.get('npc', []):
            nerede.setdefault(g['tip'], []).append(harita_adi(mid))
    ys = w['yamalar'].get('npc.json') or {}
    out = []
    for tip, t in npc['tipler'].items():
        out.append({'tip': tip, 'ad': t['ad'], 'hp': t['hp'], 'kalkan': t['kalkan'], 'hasar': t['hasar'], 'hiz': t['hiz'],
                    'saldirgan': t['saldirgan'], 'odul': t.get('odul') or {}, 'kargo': t.get('kargo') or {}, 'ikon': npc_ikon(tip, t),
                    'model': t.get('model'), 'npc_kimlik': t.get('npc_kimlik'), 'etkinlik': bool(t.get('etkinlik')) or tip.startswith('etk_'), 'nerede': nerede.get(tip, []),
                    'degisti': VERI.yol_yap('tipler', tip) in ys, 'yeni': tip not in base,
                    'standart': {k: base[tip].get(k) for k in ('ad', 'hp', 'kalkan', 'hasar', 'hiz', 'saldirgan', 'odul', 'kargo')} if tip in base else None,
                    'tam': t})
    return out


def harita_adi(mid):
    H = _sunucu()
    return H.NAMES.get(int(mid)) or str(mid)


def _firma(ad):
    return {'1': 'mmo', '2': 'eic', '3': 'vru'}.get(ad[0]) if re.match(r'^\d-\d$', ad) and ad[0] in '123' else \
        'bl' if ad.startswith('BL') else 'korsan' if ad.startswith('5-') else 'savas' if ad.startswith('4-') else 'diger'


def haritalar(did):
    w = oku(did)
    npc = dunya_verisi(did, 'npc.json')
    ys = set((w['yamalar'].get('npc.json') or {})) | set('~' + y for y in (w['yamalar'].get('harita_duzeni.json') or {}))
    cev = set(w['yamalar'].get('esyalar.json') or {})
    out = []
    for mid, m in npc['haritalar'].items():
        ad = harita_adi(mid)
        degisti = any(y in ys for y in (VERI.yol_yap('haritalar', mid, 'npc'), VERI.yol_yap('haritalar', mid, 'bonus_kutu'),
                                       '~' + VERI.yol_yap('haritalar', mid))) or VERI.yol_yap('cevherler', 'haritalar', ad) in cev
        out.append({'id': mid, 'ad': ad, 'firma': _firma(ad), 'uzayli': sum(g['adet'] for g in m.get('npc', [])),
                    'tur': len(m.get('npc', [])), 'bonus_kutu': m.get('bonus_kutu', 0), 'degisti': degisti})
    sira = lambda x: ({'mmo': 0, 'eic': 1, 'vru': 2, 'savas': 3, 'korsan': 4, 'bl': 5}.get(x['firma'], 6), x['ad'])
    return sorted(out, key=sira)


def harita(did, mid):
    """Harita editörünün tuvali: boyut, doğma listesi, portallar, istasyon, düzen (güvenli bölgeler, inler, engeller)."""
    H = _sunucu()
    mid = str(mid)
    npc = dunya_verisi(did, 'npc.json')
    if mid not in npc['haritalar']:
        raise DunyaHatasi(_('Harita bulunamadı.'))
    m = npc['haritalar'][mid]
    duzen = dunya_verisi(did, 'harita_duzeni.json')['haritalar'].get(mid) or {}
    duzen0 = ham('harita_duzeni.json')['haritalar'].get(mid) or {}
    w, h = H.map_size(int(mid)) if hasattr(H, 'map_size') else (H.MAP_W, H.MAP_H)
    portallar = []
    for g in H.GATES.get(int(mid), []):
        p = (duzen.get('portallar') or {}).get(str(g['key']))
        portallar.append({'key': g['key'], 'x': p[0] if p else g['x'], 'y': p[1] if p else g['y'], 'hedef': harita_adi(g['hedef']),
                          'firma': g.get('yalniz_firma'), 'tasindi': bool(p) and p != (duzen0.get('portallar') or {}).get(str(g['key']))})
    ist = None
    if int(mid) in H.STATION_MAPS:
        gs = H.GATES.get(int(mid), [])
        ist = list(H.STATION_POS.get(int(mid)) or max(H.CORNERS, key=lambda c: min((((c[0] - g['x']) ** 2 + (c[1] - g['y']) ** 2) ** .5 for g in gs), default=0)))
    tipler = npc['tipler']
    base = ham('npc.json')['haritalar'].get(mid) or {}
    return {'id': mid, 'ad': harita_adi(mid), 'firma': _firma(harita_adi(mid)), 'boyut': [w, h],
            'npc': [dict(g, ad=tipler.get(g['tip'], {}).get('ad', g['tip']), ikon=npc_ikon(g['tip'], tipler.get(g['tip'], {})),
                         saldirgan=tipler.get(g['tip'], {}).get('saldirgan', False)) for g in m.get('npc', [])],
            'bonus_kutu': m.get('bonus_kutu', 0), 'portallar': portallar, 'istasyon': ist, 'yapi': duzen.get('yapi'),
            'guvenli': duzen.get('guvenli', []), 'inler': duzen.get('inler', {}), 'engeller': [e[1:5] for e in duzen.get('engeller', [])],
            'duzen': duzen, 'standart': {'npc': base.get('npc', []), 'bonus_kutu': base.get('bonus_kutu', 0), 'duzen': duzen0},
            'degisti': {'npc': m.get('npc', []) != base.get('npc', []), 'bonus_kutu': m.get('bonus_kutu', 0) != base.get('bonus_kutu', 0),
                        'duzen': duzen != duzen0},
            'cevher': cevherler(did, mid)}


# ---- görevler
def _gorev_dosyasi(qid):
    return 'gorevler.json' if str(qid) in ham('gorevler.json')['gorevler'] else 'gorev_ekleri.json'


def _tum_gorevler(did):
    a = dunya_verisi(did, 'gorevler.json')['gorevler']
    b = dunya_verisi(did, 'gorev_ekleri.json')['gorevler']
    return {**{k: ('gorevler.json', v) for k, v in a.items()}, **{k: ('gorev_ekleri.json', v) for k, v in b.items()}}


def kosullar(kok):
    """Görevin koşulları (ağacın yaprakları, sırayla): [{id, tur, gosterim, eslesme, hedef, alt: [{tur, eslesme}]}]."""
    out = []

    def gez(case):
        for el in case.get('modifier', []):
            c = el.get('condition') or {}
            if c.get('id'):
                out.append({'id': c['id'], 'tur': c['type'], 'gosterim': c.get('displayType', c['type']), 'eslesme': list(c.get('matches', [])),
                            'hedef': c.get('targetValue', 0), 'alt': [{'tur': s['type'], 'eslesme': list(s.get('matches', []))}
                                                                     for s in c.get('subConditions', [])]})
            q = el.get('questCase') or {}
            if q.get('id'):
                gez(q)
    gez(kok)
    return out


def _gorev_ozet(qid, q, dosya, ys, kok_sayisi=None):
    k = kosullar(q['kok'])
    return {'id': int(qid), 'ad': q.get('ad', str(qid)), 'seviye': q.get('seviye', 1), 'turler': q.get('turler', []),
            'kaynak': 'ana' if dosya == 'gorevler.json' else 'ek', 'kosullar': [{'tur': c['tur'], 'hedef': c['hedef'], 'eslesme': c['eslesme'][:3]} for c in k],
            'oduller': q.get('oduller', []), 'kapali': bool(q.get('kapali')), 'yeni': int(qid) >= YENI_GOREV,
            'degisti': VERI.yol_yap('gorevler', qid) in ys, 'etkinlik': bool(q.get('etkinlik')), 'havuz': bool(q.get('havuz'))}


def gorevler(did):
    w = oku(did)
    ys = set(w['yamalar'].get('gorevler.json') or {}) | set(w['yamalar'].get('gorev_ekleri.json') or {})
    return sorted((_gorev_ozet(qid, q, dosya, ys) for qid, (dosya, q) in _tum_gorevler(did).items()), key=lambda g: (g['seviye'], g['id']))


def gorev(did, qid):
    hepsi = _tum_gorevler(did)
    if str(qid) not in hepsi:
        raise DunyaHatasi(_('Görev bulunamadı.'))
    dosya, q = hepsi[str(qid)]
    base = ham(dosya)['gorevler'].get(str(qid))
    w = oku(did)
    ys = set(w['yamalar'].get(dosya) or {})
    o = _gorev_ozet(qid, q, dosya, ys)
    o.update(onceki=q.get('onceki', []), kosullar=kosullar(q['kok']), sure_sn=q.get('sure_sn'), baslik=q.get('baslik', ''), aciklama=q.get('aciklama', ''),
             standart={'seviye': base['seviye'], 'oduller': base.get('oduller', []), 'onceki': base.get('onceki', []),
                       'kosullar': kosullar(base['kok'])} if base else None,
             adlar={str(x): hepsi[str(x)][1].get('ad', str(x)) for x in q.get('onceki', []) if str(x) in hepsi})
    return o


def gorev_kaydet(did, qid, degisiklik):
    """Görevin düzenlenebilir alanları: seviye, önkoşullar, ödüller, koşulların hedefi ve eşleşmesi, kapalı, ad (yalnız yeni görev)."""
    hepsi = _tum_gorevler(did)
    if str(qid) not in hepsi:
        raise DunyaHatasi(_('Görev bulunamadı.'))
    dosya, q = hepsi[str(qid)]
    q = copy.deepcopy(q)
    d = degisiklik or {}
    if 'seviye' in d:
        q['seviye'] = d['seviye']
    if 'onceki' in d:
        q['onceki'] = [int(x) for x in d['onceki'] if str(x) in hepsi and int(x) != int(qid)]
    if 'oduller' in d:
        q['oduller'] = d['oduller']
    if 'kapali' in d:
        if d['kapali']:
            q['kapali'] = True
        else:
            q.pop('kapali', None)
    if 'ad' in d and int(qid) >= YENI_GOREV:
        q['ad'] = ' '.join(str(d['ad']).split())[:60] or q.get('ad')
    for k in ('baslik', 'aciklama'):
        if k in d:
            q[k] = d[k]
    if 'kosullar' in d:
        yeni = {int(c['id']): c for c in d['kosullar']}

        def gez(case):
            for el in case.get('modifier', []):
                c = el.get('condition') or {}
                if c.get('id') in yeni:
                    y = yeni[c['id']]
                    c['targetValue'] = _int(y.get('hedef', c.get('targetValue', 1)), 0, 10 ** 9)
                    if 'eslesme' in y and KOSUL.get(c['type']) in ('npc', 'harita', 'esya', 'cevher'):
                        es = [harita_es(x) if KOSUL[c['type']] == 'harita' else str(x) for x in y['eslesme'] if str(x)]
                        c['matches'] = es or c['matches']
                    if 'harita' in y:          # ON_MAP alt koşulu: boş liste -> her haritada
                        c['subConditions'] = [s for s in c.get('subConditions', []) if s['type'] != ALT_HARITA]
                        if y['harita']:
                            c['subConditions'].append(_alt_harita(c['id'], y['harita']))
                q2 = el.get('questCase') or {}
                if q2.get('id'):
                    gez(q2)
        gez(q['kok'])
    yama(did, dosya, VERI.yol_yap('gorevler', qid), q)


def harita_es(x):
    """Görev eşleşmesinde harita: ad "@1-1" (gorev.maps_for çözer; "@own X-3" gibi kalıplar olduğu gibi), kimlik olduğu gibi."""
    x = str(x)
    return x if x.startswith('@') or x.isdigit() else '@' + x


def _alt_harita(cid, haritalar_):
    return {'_': 'QuestConditionModule', 'id': cid * 10 + 7, 'matches': [harita_es(x) for x in haritalar_], 'type': ALT_HARITA,
            'displayType': ALT_HARITA, 'targetValue': 0, 'mandatory': True,
            'state': {'_': 'QuestConditionStateModule', 'currentValue': 0, 'active': True, 'completed': False}, 'subConditions': []}


def _kosul(cid, tur, eslesme, hedef, harita_listesi=None):
    return {'_': 'QuestElementModule', 'questCase': {'_': 'QuestCaseModule', 'id': 0, 'active': False, 'mandatory': False, 'ordered': False,
                                                     'mandatoryCount': 0, 'modifier': []},
            'condition': {'_': 'QuestConditionModule', 'id': cid, 'matches': [str(x) for x in eslesme], 'type': tur, 'displayType': tur,
                          'targetValue': hedef, 'mandatory': True,
                          'state': {'_': 'QuestConditionStateModule', 'currentValue': 0, 'active': True, 'completed': False},
                          'subConditions': [_alt_harita(cid, harita_listesi)] if harita_listesi else []}}


def gorev_yeni(did, ad, seviye, hedefler, oduller):
    """Yeni görev: hedefler [{tur: avla|topla|kesif|sat|kutu|kargo, eslesme: [...], hedef, harita: [...]}] sırasız, hepsi gerekli.
    Oyundaki başlığı adı (baslik; istemcide metni yok, eklentinin GorevMetinleri yaması gösterir)."""
    if not hedefler:
        raise DunyaHatasi(_('Göreve en az bir hedef ekle.'))
    hepsi = _tum_gorevler(did)
    qid = max([YENI_GOREV - 1] + [int(k) for k in hepsi if int(k) >= YENI_GOREV]) + 1
    kok_id = 1_900_000_000 + (qid - YENI_GOREV) * 100
    mods = []
    for i, x in enumerate(hedefler[:8]):
        if x.get('tur') not in GOREV_SABLONLARI:
            raise DunyaHatasi(_('Bilinmeyen görev hedefi.'))
        tur = GOREV_SABLONLARI[x['tur']][0]
        es = x.get('eslesme') or []
        if KOSUL[tur] in ('npc', 'esya', 'cevher', 'harita') and not es:
            raise DunyaHatasi(_('Her hedef için ne yapılacağını seç.'))
        if KOSUL[tur] == 'harita':
            es = [harita_es(m) for m in es]
        mods.append(_kosul(kok_id + 1 + i, tur, es, _int(x.get('hedef', 1), 1, 10 ** 7), x.get('harita') or None))
    q = {'ad': ' '.join(str(ad or '').split())[:60] or _('Yeni görev'), 'seviye': _int(seviye or 1, 1, 40), 'oncelik': 500, 'turler': [2],
         'simge': 0, 'onceki': [], 'kaynak': 'dunya', 'pvp': False,
         'kok': {'_': 'QuestCaseModule', 'id': kok_id, 'active': False, 'mandatory': True, 'ordered': False, 'mandatoryCount': len(mods),
                 'modifier': mods},
         'oduller': oduller or []}
    q['baslik'] = q['ad']
    yama(did, 'gorev_ekleri.json', VERI.yol_yap('gorevler', qid), q)
    return qid


# ---- mağaza ve açık artırma
_KATALOG = {}


def katalog():
    if 'k' not in _KATALOG:
        p = YOL.sablon('yanitlar.json')
        if not p:
            _KATALOG['k'] = {}
        else:
            import magaza as MG
            with open(p, encoding='utf8') as fh:
                _KATALOG['k'] = MG.katalog(json.load(fh))
    return _KATALOG['k']


def magaza(did):
    urun = dunya_verisi(did, 'magaza')['urunler']
    out = {}
    for cat, its in katalog().items():
        out[cat] = [dict(it, dunya=urun.get(it['lootId'])) for it in its]
    return out


def muzayede(did):
    lot = dunya_verisi(did, 'sosyal.json')['muzayede']['lotlar']
    base = ham('sosyal.json')['muzayede']['lotlar']
    return {'lotlar': [{'loot': l[0], 'grup': l[1], 'tur': l[2], 'adet': l[3], 'anlik': l[4], 'fiyat': l[5]} for l in lot],
            'degisti': lot != base, 'standart_sayisi': len(base)}


def esya_listesi():
    """Eşya seçicinin listesi: istemcinin eşyaları (istemci_esyalari.json) + para birimleri."""
    ist = ham('istemci_esyalari.json')['esyalar']
    return sorted(set(ist) | {'currency_credits', 'currency_uridium', 'currency_honour', 'currency_experience'})


# ---- kutular ve ganimet, galaksi kapıları, cevherler
def kutular(did):
    """Bonus kutularının içeriği (eşit olasılıklı satırlar) ve anahtarlı kutular (ağırlıklı ödül tablosu, haritalar, adet)."""
    npc = dunya_verisi(did, 'npc.json')
    base = ham('npc.json')
    k = dunya_verisi(did, 'kutular.json')
    kb = ham('kutular.json')['kutular']
    out = []
    for tur, b in k['kutular'].items():
        if not b.get('odul'):                    # Battle Pass Box (etkinliğe göre), içeriği başka yerde olanlar
            continue
        out.append({'tur': tur, 'ad': b['ad'], 'anahtar': b['anahtar'], 'haritalar': b['haritalar'], 'adet': b['adet'], 'yeniden_sn': b['yeniden_sn'],
                    'takvim': b.get('takvim'), 'odul': b['odul'], 'degisti': b != kb.get(tur), 'yerde': bool(b['haritalar'] and b['adet'])})
    return {'bonus': npc['bonus_kutu'], 'bonus_4x': npc['bonus_kutu_4x'], 'bonus_degisti': npc['bonus_kutu'] != base['bonus_kutu'],
            'bonus_4x_degisti': npc['bonus_kutu_4x'] != base['bonus_kutu_4x'], 'kutular': out, 'siniflar': list(ham('kutular.json')['haritalar'])}


def kapilar(did):
    k = dunya_verisi(did, 'kapilar.json')['kapilar']
    kb = ham('kapilar.json')['kapilar']
    out = []
    for key, g in k.items():
        o = g['odul']
        out.append({'key': key, 'ad': g['ad'], 'parca': g['parca'], 'can': g['can'], 'degisti': g != kb.get(key),
                    'odul': {x: o.get(x) for x in KAPI_ODUL if x in o}, 'cephane': o.get('cephane') or {},
                    'sans': [{'esya': x['esya'], 'adet': x.get('adet'), 'olasilik': x.get('olasilik', 0), 'paket': x['esya'] == 'cevher_paketi'}
                             for x in o.get('sans', [])],
                    'standart': {'parca': kb[key]['parca'], 'can': kb[key]['can'], 'odul': {x: kb[key]['odul'].get(x) for x in KAPI_ODUL}} if key in kb else None,
                    'dalgalar': [{'ad': w['ad'], 'uzaylilar': [{'tur': a['tur'], 'ad': a.get('gorunen_ad') or a.get('ad'), 'adet': a['adet'], 'hp': a['hp'],
                                                               'degisti_tur': key in kb and i < len(kb[key]['dalgalar'][n]['uzaylilar']) and a['tur'] != kb[key]['dalgalar'][n]['uzaylilar'][i]['tur'],
                                                               'sabit': bool(a.get('kalici')) or a['tur'] == 'oyuncu',
                                                               'kalkan': a['kalkan'], 'hasar': a['hasar'], 'hiz': a['hiz'], 'kalici': bool(a.get('kalici')),
                                                               'en_az': sum(1 for grp in w['gruplar'] for j, _ in grp if j == i),
                                                               'ikon': npc_ikon(a['tur'], {})}
                                                              for i, a in enumerate(w['uzaylilar'])]} for n, w in enumerate(g['dalgalar'])]})
    return out


def cevherler(did, mid):
    """Haritanın cevherleri: haritaya özel değer (dünya) yoksa harita sınıfınınki; türler ve yeniden doğma süresi."""
    H = _sunucu()
    c = dunya_verisi(did, 'esyalar.json')['cevherler']
    ad, sinif = harita_adi(mid), H.map_class(int(mid))
    ozel = c['haritalar'].get(ad) if ad != sinif else None
    return {'adet': ozel if ozel is not None else c['haritalar'].get(sinif, {}), 'ozel': ozel is not None, 'sinif': sinif, 'ad': ad,
            'turler': c['turler'], 'yeniden_sn': c['yeniden_dogma_sn'], 'yeniden_std': ham('esyalar.json')['cevherler']['yeniden_dogma_sn'],
            'yol': VERI.yol_yap('cevherler', 'haritalar', ad)}


# ---- oyundaki görev metinleri (eklenti: GorevMetinleri.cs)
METIN_DOSYASI = os.path.join('BepInEx', 'openorbit', 'gorev_metinleri.json')


def gorev_metinleri(did):
    """Dünyanın görevlerinin oyunda gösterilecek başlık ve açıklamaları: {"<görev>": {baslik, aciklama}}."""
    out = {}
    for qid, (_, q) in _tum_gorevler(did).items():
        m = {k: q[k] for k in ('baslik', 'aciklama') if q.get(k)}
        if m:
            out[qid] = m
    return out


def metinleri_yaz(istemci, did):
    """OYNA: dünyanın görev metinleri istemcinin BepInEx klasörüne (standart dünyada boş: önceki dünyanınkiler kalmasın)."""
    if not istemci or not os.path.isdir(os.path.join(istemci, 'BepInEx')):
        return 0
    m = gorev_metinleri(did) if did and did != STANDART and var(did) else {}
    _yaz_dosya(os.path.join(istemci, METIN_DOSYASI), m)
    return len(m)


# ---- etkinlikler
def etkinlikler(did):
    e = dunya_verisi(did, 'etkinlikler.json')['etkinlikler']
    eb = ham('etkinlikler.json')['etkinlikler']
    tipler = dunya_verisi(did, 'npc.json')['tipler']
    out = []
    for key, x in e.items():
        h = x.get('harita')
        harita = None
        if h:
            harita = {'haritalar': h.get('haritalar', []), 'kota': h.get('kota', {}),
                      'uzaylilar': [{'tur': a['tur'], 'adet': a['adet'], 'ad': (tipler.get(a['tur'].replace('{x}', 'x2')) or tipler.get(a['tur'].replace('{x}', 'x3')) or {}).get('ad', a['tur']),
                                     'ikon': npc_ikon(a['tur'], tipler.get(a['tur'].replace('{x}', 'x2')) or {})} for a in h.get('uzaylilar', [])],
                      'patron': {k: h['patron'][k] for k in ('adet', 'sure_sn') if k in h['patron']} if h.get('patron') else None,
                      'secilebilir': etkinlik_siniflari(h, tipler)}
        tur = 'harita' if h else 'yillik' if 'donemler' in x else 'haftalik'
        out.append({'key': key, 'ad': x.get('ad', key), 'tur': tur, 'donemler': [r[:2] for r in x.get('donemler', [])] if 'donemler' in x else None,
                    'gunler': x.get('gunler'), 'saatler': x.get('saatler'), 'dunya_durum': x.get('dunya_durum', 'takvim'), 'harita': harita,
                    'degisti': x != eb.get(key)})
    return sorted(out, key=lambda x: ({'harita': 0, 'yillik': 1, 'haftalik': 2}[x['tur']], x['ad'].lower()))


# ---- ödüller ve ekonomi
RUTBE_FORMUL = ('ep', 'onur', 'seviye', 'npc', 'gorev', 'oyuncu', 'gemi', 'gun', 'dost', 'olum_dusman', 'olum_radyasyon', 'phoenix')


def ekonomi(did):
    sv, svb = dunya_verisi(did, 'seviyeler.json')['seviyeler'], ham('seviyeler.json')['seviyeler']
    r, rb = dunya_verisi(did, 'rutbe.json'), ham('rutbe.json')
    return {'seviyeler': sv, 'seviyeler_std': svb, 'formul': r['formul'], 'formul_std': rb['formul'], 'esikler': r['esikler'],
            'esikler_std': rb['esikler'], 'rutbeler': [x['ad'] for x in r['rutbeler']]}
