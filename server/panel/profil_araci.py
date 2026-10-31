"""Profil aracı (panel ayrı süreçte çalıştırır; sunucu modüllerini panelin sürecine yüklememek için).

  python -I profil_araci.py yeni <profil.json> <pilot adı> <firma 1|2|3> [--kredi=N] [--uridyum=N] [--seviye=N] [--onur=N]
                                 [--lazer=N] [--roket=N]
      tohumdan (data/giris.json, yoksa varsayılan pilot) yeni profil: pilot adı, firma, firmanın ana haritasında (X-1) istasyon;
      isteğe bağlı başlangıç: kredi, uridyum, seviye (EP'si seviyenin eşiği, data/seviyeler.json), onur, LCB-10 ve R-310 adedi
  python -I profil_araci.py ana_us <profil.json>
      gemiyi firmasının ana istasyonuna taşı (bozuk ya da takılı kalınan haritadan kurtarma)
  python -I profil_araci.py ver <profil.json> <JSON [[lootId, adet], ...]>
      eşya, gemi, dron, cephane, kaynak, booster ver (oyunun ödül yolu: magaza.reward; Ö2)
  python -I profil_araci.py sifirla <profil.json> <bölüm,bölüm>
      durum sıfırlama: ipuclari, arayuz (pencere ve çubuk yerleri), oyun_ayarlari, aktif_gorevler, gecmis (seyir defteri ve hesap
      geçmişi)
  python -I profil_araci.py liste
      verilebilecek lootId'ler (istemcinin eşya verisi ve sunucunun eşya tabloları)
Çıktı: son satırda JSON {'ok': true, ...} ya da {'ok': false, 'hata': '...'}.
"""
import json, os, sys, time

SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER)
DATA = os.path.join(SERVER, 'data')
HOME_MAP = {1: 1, 2: 5, 3: 9}             # game.py HOME_MAP: firma -> X-1
START_AMMO = {'lazer': 'ammunition_laser_lcb-10', 'roket': 'ammunition_rocket_r-310'}     # yeni kaydın başlangıç cephanesi (tohumda da)


def _load(name):
    import yollar as YOL
    p = YOL.sablon(name) if name in YOL.SABLONLAR else os.path.join(DATA, name)     # şablon: kendi kaydın, yoksa paylaşılabilir kopya
    return json.load(open(p, encoding='utf8')) if p and os.path.exists(p) else {}


def station_pos(map_id):
    """Haritanın istasyonunun konumu (game.Sablonlar.station gibi) ya da None."""
    import harita as H
    hrt = _load('haritalar.json')
    rec = hrt.get(str(map_id))
    if rec is None:
        rec = H.map_world(map_id, hrt.get('5'))
    for m in rec.get('hazir', []):
        if m['_m'] == 'SpaceStationCommand' and m.get('type') not in H.DECOR_STATION_TYPES:
            return int(m['posX']), int(m['posY'])
    return None


def level_ep(level):
    """Seviyenin EP eşiği (data/seviyeler.json; en büyük seviyeye kırpılır) -> (seviye, EP)."""
    table = _load('seviyeler.json').get('seviyeler') or [[1, 0]]
    lv = max(table[0][0], min(int(level), table[-1][0]))
    return lv, next(need for l, need in table if l == lv)


def yeni(path, pilot, firma, kredi=None, uridyum=None, seviye=None, onur=None, lazer=None, roket=None, ilerlemeli=False, kampanya=False):
    if os.path.exists(path):
        raise ValueError('Bu yolda zaten bir profil var.')
    from profil import Profil
    firma = int(firma)
    pr = Profil(_load('giris.json').get('tohum'), path)
    pl = pr.d['pilot']
    pl['userName'] = pilot
    pl['factionId'] = firma
    if kredi is not None:
        pl['credits'] = kredi
    if uridyum is not None:
        pl['uridium'] = uridyum
    if seviye is not None:                                  # seviye EP'den hesaplanır (oyun da öyle): EP seviyenin eşiği
        pl['level'], pl['ep'] = level_ep(seviye)
    if onur is not None:
        pl['honourPoints'] = onur
    for key, n in (('lazer', lazer), ('roket', roket)):
        if n is not None:
            pr.d['cephane'][START_AMMO[key]] = n
    mid = HOME_MAP[firma]
    pos = station_pos(mid)
    if pos:
        pr.d['konum'] = {'mapId': mid, 'x': pos[0], 'y': pos[1]}
    pr.d['olusturma'] = time.strftime('%Y-%m-%d %H:%M:%S')
    if ilerlemeli:                                          # Season Pass ilk sezondan sırayla (sezon.py)
        pr.d['ilerlemeli'] = True
    if kampanya:                                            # başlangıç kampanyası: "Level N" görevleri (gorev.KAMPANYA_SN boyunca)
        pr.d['kampanya'] = int(time.time())
    pr.save(force=True)
    return {'harita': mid, 'konum': pos, 'sablon': bool(_load('giris.json'))}


def ana_us(path):
    d = json.load(open(path, encoding='utf8'))
    mid = HOME_MAP.get(d['pilot'].get('factionId'), 5)
    pos = station_pos(mid)
    if not pos:
        raise ValueError('Ana istasyonun konumu bulunamadı.')
    d['konum'] = {'mapId': mid, 'x': pos[0], 'y': pos[1]}
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return {'harita': mid, 'konum': pos}


def known_loots():
    """Verilebilecek lootId -> tür (istemcinin eşya verisi; sunucunun eşya tabloları)."""
    out = {k: (v.get('tur') or '') for k, v in (_load('istemci_esyalari.json').get('esyalar') or {}).items()
           if not k.startswith(('shipId_', 'paymentItem_'))}
    es = _load('esyalar.json')
    prefixes = {k.split('_', 1)[0] for k in out}
    for sec in ('lazerler', 'lazer_cephane', 'roketler', 'onarim_robotlari', 'hiz_jeneratorleri', 'kalkan_jeneratorleri', 'gemiler',
                'dronlar', 'formasyonlar', 'dron_tasarimlari', 'boosterlar', 'ekstralar', 'savas_esyalari', 'odeme_paketleri'):
        for k in (es.get(sec) or {}):
            if isinstance(k, str) and not k.startswith('_') and k.split('_', 1)[0] in prefixes | {'package', 'deal'}:
                out.setdefault(k, sec)
    return out


def ver(path, items, pr=None):
    """Oyunun ödül yolu (görev ve kutu ödülleriyle aynı: magaza.reward) çevrimdışı profilde: gemi hangara, ekipman envantere
    (boş yuva varsa takılır), dron, cephane, kaynak, booster, tasarım. Bilinmeyen lootId reddedilir. pr: dosya yerine bu profil
    (kaydedilmez)."""
    import kapi as KAPI
    import yeni_sistemler as YS
    from profil import Profil
    from magaza import Magaza
    known = known_loots()
    items = [(str(l), max(1, min(10 ** 9, int(n)))) for l, n in items]
    bad = [l for l, n in items if l not in known and not l.startswith(('ammunition_', 'resource_', 'ship_', 'drone_', 'booster_'))]
    if bad:
        raise ValueError('Bilinmeyen eşya: %s', ', '.join(bad))
    notes = []
    kaydet = pr is None
    pr = pr or Profil(_load('giris.json').get('tohum'), path)
    m = Magaza(pr, _load('yanitlar.json'), notes.append)      # oyundaki şablonlar: takılan ekipmanın HangarShipEquipmentCommand'ı
    m.kapilar = KAPI.Kapilar(pr, notes.append)
    m.yeni = YS.YeniSistemler(pr, m, notes.append)
    before = (len(pr.d.get('esyalar', {})), len(pr.d.get('gemiler', {})), len(pr.d.get('dronlar', [])))
    for loot, n in items:
        m.reward(loot, n)
    if kaydet:
        pr.save(force=True)
    after = (len(pr.d.get('esyalar', {})), len(pr.d.get('gemiler', {})), len(pr.d.get('dronlar', [])))
    return {'verilen': [[l, n] for l, n in items], 'esya': after[0] - before[0], 'gemi': after[1] - before[1],
            'dron': after[2] - before[2], 'notlar': [x.strip() for x in notes if x.strip()][-20:]}


RESETS = ('ipuclari', 'arayuz', 'oyun_ayarlari', 'aktif_gorevler', 'gecmis')


def sifirla(path, parts):
    d = json.load(open(path, encoding='utf8'))
    done = sifirla_d(d, parts)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return {'sifirlanan': done}


def sifirla_d(d, parts):
    """Profil sözlüğünde durum sıfırlama (kayit_editoru.py taslakta da kullanır) -> sıfırlanan bölümler."""
    seed = _load('giris.json').get('tohum') or {}
    done = []
    for part in parts:
        if part == 'ipuclari':                     # ipucu pencereleri ve etkinlik bildirimleri yeniden (ipucu.py)
            for k in ('ipuclari_gosterilen', 'ipuclari_kapali', 'etkinlik_bildirimi'):
                d.pop(k, None)
        elif part == 'arayuz':                     # menü çubukları ve pencere yerleri tohumdaki (UILayoutCommand)
            d['arayuz'] = seed.get('UILayoutCommand') or {'featureBars': []}
        elif part == 'oyun_ayarlari':              # oyunun Ayarlar penceresi (grafik, ses, oynanış) tohumdaki
            d['ayarlar'] = seed.get('UserSettingsCommand') or {}
        elif part == 'aktif_gorevler':             # alınmış görevler bırakılır (bitenler kalır)
            d.setdefault('gorevler', {})['aktif'] = {}
        elif part == 'gecmis':                     # seyir defteri ve hesap geçmişi boşalır
            d['seyir_defteri'], d['hesap_gecmisi'] = [], []
        else:
            raise ValueError('Bilinmeyen bölüm: %s', part)
        done.append(part)
    return done


def main(argv):
    opts = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in argv if a.startswith('--') and '=' in a}
    args = [a for a in argv if not a.startswith('--')]
    if args[:1] == ['yeni'] and len(args) == 4:
        num = {k: int(opts[k]) for k in ('kredi', 'uridyum', 'seviye', 'onur', 'lazer', 'roket') if k in opts}
        return yeni(args[1], args[2], args[3], ilerlemeli=opts.get('ilerlemeli') == '1', kampanya=opts.get('kampanya') == '1', **num)
    if args[:1] == ['ana_us'] and len(args) == 2:
        return ana_us(args[1])
    if args[:1] == ['ver'] and len(args) == 3:
        return ver(args[1], json.loads(args[2]))
    if args[:1] == ['sifirla'] and len(args) == 3:
        return sifirla(args[1], [x for x in args[2].split(',') if x])
    if args[:1] == ['liste'] and len(args) == 1:
        return {'esyalar': sorted(known_loots().items())}
    raise ValueError('kullanım: profil_araci.py yeni <yol> <pilot> <firma> | ana_us <yol> | ver <yol> <json> | sifirla <yol> <bölümler> | liste')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    try:
        out = main(sys.argv[1:])
        print(json.dumps(dict(out, ok=True), ensure_ascii=False))
    except Exception as e:
        # ValueError(kalıp, *değerler): panel iletiyi kendi dilinde kurar (kayitlar.run_tool, dil.py)
        kalip = e.args[0] if isinstance(e, ValueError) and e.args and isinstance(e.args[0], str) else None
        msg = (kalip % e.args[1:] if len(e.args) > 1 else kalip) if kalip else str(e)
        print(json.dumps({'ok': False, 'hata': '%s: %s' % (type(e).__name__, msg), 'kalip': kalip, 'arg': [str(a) for a in e.args[1:]]},
                         ensure_ascii=False))
