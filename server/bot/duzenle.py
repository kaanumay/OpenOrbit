"""Botun ayrıntısı ve düzenlenmesi (panelin Botlar > Kadro > bot penceresi): profil, hangar, kişilik, ruh hâli, hafıza, anılar.

Aynı kod iki yerde çalışır: oyun kapalıyken panel paketin durum dosyasındaki sözlük üzerinde (panel/botlar.bot_duzenle), oyun
açıkken oyun sunucusu canlı botun k sözlüğü üzerinde, y.lock altında (panel_kanali /bot/duzenle). Kişilik kadroda durur (yönetici
her açılışta kadrodan okur): kd paketin kadro satırı. Her değer doğrulanır; geçersizse DuzenlemeHatasi (kod: panel kendi dilinde
iletir).
"""
import time

import harita as H
import profil as PF
from . import katalog as K
from .kisilik import DUYGU_DENGE

OZELLIKLER = ('saldirganlik', 'rekabet', 'sosyallik', 'sabir', 'risk', 'sadakat', 'yardimseverlik', 'konuskanlik', 'tutumluluk', 'hirs')
KATEGORI = {'lazer': 'lazerler', 'kalkan': 'kalkan_jeneratorleri', 'hiz': 'hiz_jeneratorleri', 'dron': 'dronlar', 'ekstra': 'ekstralar'}
AZAMI = {'lazer': 100, 'kalkan': 100, 'hiz': 100, 'dron': 10, 'ekstra': 100000}


class DuzenlemeHatasi(ValueError):
    def __init__(self, kod, alan=''):
        self.kod, self.alan = kod, alan
        super().__init__('%s %s' % (kod, alan))


def _kisa(loot):
    return str(loot).rsplit('_', 1)[-1].upper()


def katalog():
    """Düzenleyicinin seçenekleri: gemiler (tasarımlar hariç), eşyalar, cephane, haritalar."""
    E = K.ESYA
    out = {'gemiler': [{'loot': l, 'ad': _kisa(l), 'lazer': v['laser'], 'jen': v['generators'], 'ekstra': v.get('extra', 1)}
                       for l, v in sorted(E['gemiler'].items(), key=lambda x: (x[1]['hp'], x[0])) if 'taban' not in v],
           'cephane': [{'loot': l, 'ad': _kisa(l)} for l in list(E['lazer_cephane']) + list(E['roketler'])],
           'haritalar': [{'id': m, 'ad': H.name(m)} for m in K.HARITALAR]}
    for kat, anahtar in KATEGORI.items():
        out[kat] = [{'loot': l, 'ad': _kisa(l)} for l in E[anahtar]]
    for x in out['ekstra']:                  # ekstranın sayısı adet değil kalan hak (bot/ekstra.py): eklenince tam hakla takılır
        x['hak'] = int((E['ekstralar'][x['loot']] or {}).get('hak', 1))
    return out


def _sayi(v, lo, hi, alan, tam=True):
    try:
        x = int(v) if tam else float(v)
    except (TypeError, ValueError):
        raise DuzenlemeHatasi('deger', alan) from None
    if not lo <= x <= hi:
        raise DuzenlemeHatasi('aralik', alan)
    return x


def _ani_kimligi(a):
    return '%.3f|%s' % (a['t'], a['kim'])


def gorunum(k, kd, cevrimici=None):
    """Botun bütün durumu -> panelin penceresi (k: durum sözlüğü, yoksa None; kd: kadro satırı)."""
    out = {'no': kd['no'], 'ad': kd['ad'], 'firma': kd['firma'], 'arketip': kd['kisilik'].get('arketip'),
           'aliskanlik': kd['kisilik'].get('aliskanlik'), 'dil': kd['kisilik'].get('dil'),
           'ozellik': {o: round(kd['kisilik']['ozellik'].get(o, 0.5), 3) for o in OZELLIKLER}, 'var': k is not None,
           'cevrimici': cevrimici}
    if k is None:
        return out
    PF.level_for(0)
    sv = int(k.get('seviye') or 1)
    e = k.get('ekip') or K.yeni_ekip()
    g = K.ESYA['gemiler'].get(e.get('gemi')) or K.ESYA['gemiler']['ship_phoenix']
    don = K.donat(e)
    try:
        dg = K.degerler(e)
    except (KeyError, ValueError, TypeError):
        dg = {}
    gorev = None
    if k.get('gorev'):
        from .hedefler import gorev as GV
        gorev = {'id': k['gorev'].get('id'), 'ad': GV.gorevler().get(k['gorev'].get('id'), {}).get('ad', '?')}
    turler = K.ESYA['cevherler']['turler']
    kap = K.kargo_kapasitesi(e)
    simdi = time.time()
    out.update(
        profil={'seviye': sv, 'ep': int(k.get('ep') or 0), 'sonraki_ep': next((n for lv, n in (PF._LEVELS or []) if lv == sv + 1), None),
                'taban_ep': next((n for lv, n in (PF._LEVELS or []) if lv == sv), 0),
                'kredi': int(k.get('kredi') or 0), 'uridyum': int(k.get('uridyum') or 0), 'onur': int(k.get('onur') or 0),
                'harita': k.get('harita'), 'harita_ad': H.name(k['harita']) if k.get('harita') else '', 'hedef': k.get('hedef'),
                'niyet': (k.get('niyet') or {}).get('hedef'), 'klan': k.get('klan'), 'kayitli': k.get('kayitli', True),
                'arkadaslar': list(k.get('arkadaslar') or [])},
        ruh={d: round(float((k.get('ruh') or {}).get(d, DUYGU_DENGE[d])), 3) for d in DUYGU_DENGE},
        ekip={'gemi': e.get('gemi'), 'cephane': e.get('cephane'), **{kat: dict(e.get(kat) or {}) for kat in KATEGORI}},
        yuva={'lazer': don['lazer_yuva'], 'jen': don['jen_yuva'], 'ekstra': g.get('extra', 1), 'gemi_lazer': g['laser']},
        guc={'guc': round(dg.get('guc', 0), 1), 'dps': round(dg.get('dps', 0)), 'ehp': round(dg.get('ehp', 0))},
        stok={l: int(n) for l, n in (k.get('stok') or {}).items()},
        kargo={_kisa(turler.get(str(t), 'ore_%s' % t)): int(n) for t, n in (k.get('kargo') or {}).items() if n},
        kargo_kapasite=kap, gorev=gorev, tamam=len(k.get('tamam') or ()), istat=dict(k.get('istat') or {}),
        kapi_sureleri=dict(k.get('kapi_sureleri') or {}),
        uyari={x: v for x, v in (k.get('uyari') or {}).items() if x in ('sohbet', 'pvp', 'kutu') and v > time.time()},     # yönetici uyarısı
        skylab=dict((k.get('skylab') or {}).get('mod') or {}), formasyon=k.get('formasyon'),
        iliskiler=sorted(({'anahtar': a, 'ad': v.get('ad', a), 'd': round(v.get('d', 0), 3), 'n': v.get('n', {})}
                          for a, v in (k.get('hafiza') or {}).items()), key=lambda x: -abs(x['d'])),
        anilar=[{'id': _ani_kimligi(a), 'kim': a['kim'], 'ozet': a['ozet'], 't': a['t'], 'n': a.get('n', 1), 'tur': a.get('tur'),
                 'onem': a.get('onem'), 'takip': a.get('takip')} for a in sorted(k.get('anilar') or [], key=lambda a: -a['t'])],
        izlenim=[{'anahtar': a, 'ad': v.get('ad', a), 'metin': v.get('metin', '')} for a, v in (k.get('izlenim') or {}).items()],
        defter=[x['metin'] for x in k.get('defter') or [] if not x.get('bitti')],
        hatirlatici=[{'metin': x.get('metin'), 'kalan_sn': max(0, int(x.get('vade', simdi) - simdi))} for x in k.get('hatirlatici') or []],
        birikim=k.get('birikim'), ajan=list(k.get('ajan') or [])[-20:])
    return out


def uygula(k, kd, deg, cevrimici=False):
    """Düzenlemeleri k (durum) ve kd (kadro satırı) üzerinde uygula -> değişen alanlar. Önce hepsi doğrulanır: biri geçersizse hiçbiri
    uygulanmaz."""
    deg = deg if isinstance(deg, dict) else {}
    isler = []
    ekip = k.setdefault('ekip', K.yeni_ekip()) if k is not None else None
    durum_gerek = [a for a in deg if a not in ('ozellik',)]
    if durum_gerek and k is None:
        raise DuzenlemeHatasi('durum_yok')
    E = K.ESYA
    if 'ep' in deg:
        ep = _sayi(deg['ep'], 0, 10 ** 12, 'ep')
        isler.append(lambda ep=ep: k.update(ep=ep, seviye=PF.level_for(ep)))
    for a, lo, hi in (('kredi', 0, 2 * 10 ** 12), ('uridyum', 0, 2 * 10 ** 12), ('onur', -2 * 10 ** 12, 2 * 10 ** 12)):
        if a in deg:
            v = _sayi(deg[a], lo, hi, a)
            isler.append(lambda a=a, v=v: k.__setitem__(a, v))
    if 'harita' in deg:
        m = _sayi(deg['harita'], 1, max(K.HARITALAR), 'harita')
        if m not in K.HARITALAR:
            raise DuzenlemeHatasi('aralik', 'harita')
        if cevrimici:
            raise DuzenlemeHatasi('cevrimici', 'harita')     # çevrimiçi botu ışınlamak soyut/somut konumunu bozar
        isler.append(lambda m=m: k.update(harita=m, niyet=None, hedef=None))
    if 'gemi' in deg:
        g = deg['gemi']
        if g not in E['gemiler'] or 'taban' in E['gemiler'][g]:
            raise DuzenlemeHatasi('esya', 'gemi')
        isler.append(lambda g=g: ekip.__setitem__('gemi', g))
    if 'cephane' in deg:
        c = deg['cephane']
        if c not in E['lazer_cephane']:
            raise DuzenlemeHatasi('esya', 'cephane')
        isler.append(lambda c=c: ekip.__setitem__('cephane', c))
    for kat, esyalar in (deg.get('ekip') or {}).items():
        if kat not in KATEGORI or not isinstance(esyalar, dict):
            raise DuzenlemeHatasi('esya', kat)
        yeni = {}
        for l, n in esyalar.items():
            if l not in E[KATEGORI[kat]]:
                raise DuzenlemeHatasi('esya', l)
            n = _sayi(n, 0, AZAMI[kat], l)
            if n:
                yeni[l] = n
        isler.append(lambda kat=kat, yeni=yeni: ekip.__setitem__(kat, yeni))
    if 'stok' in deg:
        gecerli = set(E['lazer_cephane']) | set(E['roketler']) | set((k.get('stok') or {}))
        yeni = {}
        for l, n in (deg['stok'] or {}).items():
            if l not in gecerli:
                raise DuzenlemeHatasi('esya', l)
            yeni[l] = _sayi(n, 0, 10 ** 9, l)
        isler.append(lambda yeni=yeni: k.setdefault('stok', {}).update(yeni))
    if deg.get('kargo_bosalt'):
        isler.append(lambda: k.__setitem__('kargo', {}))
    if deg.get('gorev_iptal'):
        isler.append(lambda: k.__setitem__('gorev', None))
    if 'ozellik' in deg:
        yeni = {}
        for o, v in (deg['ozellik'] or {}).items():
            if o not in OZELLIKLER:
                raise DuzenlemeHatasi('deger', o)
            yeni[o] = round(_sayi(v, 0.0, 1.0, o, tam=False), 3)

        def kisilik(yeni=yeni):
            kd['kisilik']['ozellik'].update(yeni)
            if k is not None and k.get('kisilik') is not kd['kisilik'] and isinstance(k.get('kisilik'), dict):
                k['kisilik'].setdefault('ozellik', {}).update(yeni)
        isler.append(kisilik)
    if 'ruh' in deg:
        yeni = {}
        for d, v in (deg['ruh'] or {}).items():
            if d not in DUYGU_DENGE:
                raise DuzenlemeHatasi('deger', d)
            yeni[d] = round(_sayi(v, 0.0, 1.0, d, tam=False), 3)
        isler.append(lambda yeni=yeni: k.setdefault('ruh', {}).update(yeni))
    hf = k.setdefault('hafiza', {}) if k is not None else {}
    for a, v in (deg.get('iliski') or {}).items():
        if a not in hf:
            raise DuzenlemeHatasi('yok', a)
        v = round(_sayi(v, -1.0, 1.0, a, tam=False), 3)
        isler.append(lambda a=a, v=v: hf[a].update(d=v, s=time.time()))
    for a in deg.get('iliski_sil') or ():
        isler.append(lambda a=a: hf.pop(a, None))
    if 'ani' in deg or 'ani_sil' in deg:
        la = k.setdefault('anilar', []) if k is not None else []
        ids = {_ani_kimligi(a): a for a in la}
        for i, metin in (deg.get('ani') or {}).items():
            if i not in ids or not str(metin).strip():
                raise DuzenlemeHatasi('yok' if i not in ids else 'deger', 'ani')
            isler.append(lambda a=ids[i], m=' '.join(str(metin).split())[:200]: a.__setitem__('ozet', m))
        sil = set(deg.get('ani_sil') or ())
        if sil:
            isler.append(lambda sil=sil: la.__setitem__(slice(None), [a for a in la if _ani_kimligi(a) not in sil]))
    iz = k.setdefault('izlenim', {}) if k is not None else {}
    for a, metin in (deg.get('izlenim') or {}).items():
        if a not in iz or not str(metin).strip():
            raise DuzenlemeHatasi('yok' if a not in iz else 'deger', 'izlenim')
        isler.append(lambda a=a, m=' '.join(str(metin).split())[:240]: iz[a].update(metin=m))
    for a in deg.get('izlenim_sil') or ():
        isler.append(lambda a=a: iz.pop(a, None))
    if 'defter' in deg:
        metinler = [' '.join(str(x).split())[:160] for x in deg['defter'] or [] if str(x).strip()][:8]
        isler.append(lambda metinler=metinler: k.__setitem__('defter', [x for x in k.get('defter') or [] if x.get('bitti')]
                                           + [{'metin': m, 't': time.time()} for m in metinler]))
    if deg.get('hatirlatici_sil'):
        isler.append(lambda: k.__setitem__('hatirlatici', []))
    if deg.get('birikim_sil'):
        isler.append(lambda: k.__setitem__('birikim', None))
    if deg.get('takip_iptal'):
        sil = set(deg['takip_iptal'])
        isler.append(lambda sil=sil: [a['takip'].__setitem__('bitti', True) for a in k.get('anilar') or ()
                              if a.get('takip') and _ani_kimligi(a) in sil])
    if deg.get('ajan_sil'):
        isler.append(lambda: k.__setitem__('ajan', []))
    for f in isler:
        f()
    return sorted(deg)
