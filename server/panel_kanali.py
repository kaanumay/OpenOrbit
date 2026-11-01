"""Panelin oyun menüleri (kullanıcı isteği 2026-10-28: OYNA'dan sonra panelde Mağaza, Hangar, Skylab, Açık Artırma) için yerel kanal.

Oyun açıkken kayıt dosyası düzenlenemez (sunucu her 10 saniyede kaydeder; panel/kayitlar.guard): panel oyunu sunucunun içinden
değiştirir. İstekler istemci göndermiş gibi oturumun on_packet'inden geçer (fiyat, kural, görev ve başarım sayaçları oyundakiyle aynı);
sunucunun yanıtları gerçek istemciye de gider, oyundaki pencereler ve HUD anında güncellenir.

HTTP, yalnız 127.0.0.1:PORT. Anahtar her açılışta rastgele: <günlük klasörü>/panel_kanali.json {port, anahtar} (panel okur, istek
X-Anahtar başlığıyla). Sunucunun kendi oyuncusu (game.CURRENT) bağlı değilse 409.
  GET  /magaza   kredi, uridyum, kategoriler ve her kategorinin ürünleri (magaza.shop_list: istemcinin gördüğü liste)
  POST /magaza/al {lootId, category, amount, level}  ShopItemBuyRequest -> {tamam, hata (ShopItemBuyCommand.errorMessage'ın
                 BaseKey adı ya da ham metni; panel çevirir, istemci kendi ekranında da gösterir), kredi, uridyum}
  POST /magaza/abone {lootId, category}  booster aboneliği aç/kapa (ShopItemBuyRequest action toggleSubscription)
  GET  /hangar?gemi=<kimlik>  gemiler (favori, kayıtlı config), seçili geminin (yoksa etkin) iki config'i: gemi yuvaları, dronlar
                 (eşyaları, tasarım ve görünüm yuvası), P.E.T. (ad, seviye, yuvalar ve HEAT, yuva açma fiyatları); geminin tasarımları;
                 CPU'lar (aç/kapa, otomatik alımın cephanesi); envanterde hiçbir yere takılı olmayan eşyalar: takılabildiği yerler
                 (ship, drone, pet), yükseltme seviyesi, satış değeri; istasyonda mı
  POST /hangar/tasi {gemi, konfig, esya, yon: tak|cikar, hedef: ship|drone|pet, dron, kume: heat}  HangarShipMoveItemsRequest
  POST /hangar/etkin {gemi}  HangarShipActivateShipRequest (oyundaki gibi yalnız istasyonda) -> {tamam, hata}
  POST /hangar/tasarim {gemi, lootId}  HangarShipChangeShipModelRequest -> {tamam, hata}
  POST /hangar/islem {islem, …}  oyunun hangar menüsündeki öteki işlemler (ISLEMLER): config'i etkin yapma, temizleme, kaydetme,
                 yükleme, başka gemiye aktarma, favori, eşya ve dron satışı, P.E.T. adı ve yuvası, CPU aç/kapa ve otomatik alım cephanesi
Güvenli bölge: oyunda donanım yalnız istasyonda (panelin "Portallarda hangar" ayarıyla portalın güvenli bölgesinde de) ve savaştan
  bir süre sonra değişir; bunu istemci denetler (BeaconCommand inStation / inPeaceArea), sunucu takma isteğini konumdan bağımsız
  işler. Panel istemciyi atladığı için kanal aynı kuralı dünyanın in_station'ıyla uygular (ISTASYON işlemleri; hata 'istasyon').
  GET  /skylab   modüller (seviye, durum, enerji, üretim, yükseltme bedeli ve kalan süresi), depo, enerji, taşıma; önce biriken
                 üretim işlenir (istemcinin pencere yenilemesi: SkylabActionRequest, construction boş: istemcide pencere açılmaz)
  POST /skylab/islem {modul, islem, mod, miktarlar: {cevher kimliği: adet}}  SkylabActionRequest (upgrade, instantUpgrade,
                 instantFinishUpgrade, abortUpgrade, setActive, setInactive, startTransport) -> {tamam, hatalar, basarilar}
                 (BaseKey adları; skylab.son_islem)
  POST /skylab/robot {modul, tip: 1|2}  SkylabPurchaseRobotRequest -> {tamam, hatalar}
  GET  /muzayede  lotlar (en yüksek teklif ve sahibi, oyuncunun teklifi, önde mi, en düşük geçerli teklif, anında alım, otomatik teklif
                 ve alarm kuralı), dönemlerin kalan süreleri, geçmiş, olaylar; önce istemcinin listesi gibi (dönem sonu işlenir)
  POST /muzayede/teklif {tur, loot, fiyat}  AuctionBidRequest -> {tamam, hata}
  POST /muzayede/hepsi {lotlar: [[tur, loot]]}  her lota (önde olunmayanlara) en düşük geçerli teklif -> {verilen, tutar, hatalar}
  POST /muzayede/anlik {tur, loot}  AuctionQuickBuyRequest -> {tamam, hata}
  POST /muzayede/oto {tur, loot, azami}  otomatik teklif kuralı (azami 0: kapalı; muzayede.oto)
  POST /muzayede/alarm {tur, loot, gecilince, dk}  alarm kuralı (ikisi de boşsa kalkar)
  GET  /muzayede/olaylar?son=<no>  bu numaradan sonraki olaylar (panelin bildirimleri)
"""
import json, os, secrets, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ayar as AY
import magaza as MG
import muzayede as MZ
import pet as PETM
import savas_esya as SE
import skylab as SKY
import gm_center as GMC

PORT = 8098
ANAHTARLAR = {v: k for k, v in MG.BASEKEY.items()}      # BaseKey numarası -> adı (mesaj_anahtarlari.json)


class Hata(Exception):
    def __init__(self, kod, mesaj):
        super().__init__(mesaj)
        self.kod = kod


def oturum(game):
    s = game.CURRENT
    if s is None or s.profil is None or getattr(s, 'magaza', None) is None:
        raise Hata(409, 'oyun bağlı değil')
    return s


def cuzdan(s):
    pl = s.profil.d['pilot']
    return {'kredi': pl.get('credits', 0), 'uridyum': pl.get('uridium', 0), 'istasyonda': istasyonda(s),
            'firma': {1: 'mmo', 2: 'eic', 3: 'vru'}.get(pl.get('factionId'), 'eic')}     # gemi simgeleri şirkete göre


def magaza(game):
    s = oturum(game)
    with s.packet_lock:
        kat = {}
        for c in s.magaza.lists:
            m = s.magaza.shop_list(c)            # ('ShopItemListCommand', alanlar)
            if m and m[1]['itemList']:
                kat[c] = m[1]['itemList']
        sira = [p['category'] for p in next(iter(s.magaza.lists.values()), {}).get('promptList', []) if p['category'] in kat]
        return dict(cuzdan(s), kategoriler=sira + [c for c in kat if c not in sira], esyalar=kat)


def bot_ad_kaydi(game, b):
    """Panel bir botun adını değiştirdi (ad_kaydi.py): oyun açıkken hemen uygulanır (botlar, klanlar, bağlı oyuncuların rehberi)."""
    from bot import yonetici as YN
    y = YN.AKTIF
    return {'tamam': True, 'degisen': y.ad_kaydi_uygula() if y is not None else 0}


def _bot(b):
    from bot import yonetici as YN
    y = YN.AKTIF
    if y is None:
        raise Hata(409, 'botlar açık değil')
    bot = next((x for x in y.botlar if x.k['no'] == int(b.get('no') or 0)), None)
    kd = next((x for x in y.paket.get('kadro', []) if x['no'] == int(b.get('no') or 0)), None)
    if bot is None or kd is None:
        raise Hata(404, 'bot yok')
    return y, bot, kd


def bot_detay(game, b):
    """Panelin bot penceresi, oyun açıkken: canlı botun durumu (bot/duzenle.gorunum)."""
    from bot import duzenle as DZ
    y, bot, kd = _bot(b)
    with y.lock:
        bot.kayit()                                    # ruh hâli nesneden sözlüğe
        return DZ.gorunum(bot.k, kd, cevrimici=bot.cevrimici)


def bot_duzenle(game, b):
    """Panel bir botu düzenledi, oyun açıkken: canlı bota hemen uygulanır (ruh hâli nesnesi, ekipman önbelleği, profil eşitlenir).
    Hata kodu yanıtta (panel kendi dilinde iletir)."""
    from bot import duzenle as DZ, toplum
    y, bot, kd = _bot(b)
    deg = b.get('degisiklik') or {}
    with y.lock:
        bot.kayit()
        try:
            DZ.uygula(bot.k, kd, deg, cevrimici=bot.cevrimici)
        except DZ.DuzenlemeHatasi as e:
            return {'hata': e.kod, 'alan': e.alan}
        if 'ruh' in deg:
            bot.ruh.d.update(bot.k['ruh'])
        if any(a in deg for a in ('gemi', 'ekip', 'cephane')):
            bot.ekip_degisti()
        toplum.guncelle(bot)
        return DZ.gorunum(bot.k, kd, cevrimici=bot.cevrimici)


def isle(s, name, f):
    """İstemci göndermiş gibi (game.Session.inject gibi) -> o sırada istemciye gönderilen mesajlar."""
    giden = []
    with s.packet_lock:
        asil = s.send

        def yakala(msgs, *a, **k):
            giden.extend(msgs)
            return asil(msgs, *a, **k)
        s.send = yakala              # alt sistemler self.send'i çağrı anında arar (lambda m: self.send(...)): hepsi yakalanır
        try:
            s.on_packet(name, -1, f, None)
        finally:
            del s.send
    return giden


def al(game, b):
    s = oturum(game)
    lid = str(b.get('lootId') or '')
    if not lid:
        raise Hata(400, 'lootId')
    f = {'lootId': lid, 'category': str(b.get('category') or ''), 'amount': max(1, int(b.get('amount') or 1)),
         'level': max(1, int(b.get('level') or 1)), 'buyCategory': '', 'petName': ''}
    cmd = yanit(isle(s, 'ShopItemBuyRequest', f), 'ShopItemBuyCommand')
    if cmd is None:
        return dict(cuzdan(s), tamam=False, hata='shop_item_not_found')
    return dict(cuzdan(s), tamam=cmd.get('resultId') == 1, hata=hata_adi(cmd.get('errorMessage')))


def yanit(giden, ad):
    return next((m[1] for m in giden if isinstance(m, tuple) and m[0] == ad), None)


def hata_adi(e):
    """Yanıt komutunun BaseStackCommand'i -> BaseKey adı (type 0) ya da ham metin (type 1)."""
    if not e:
        return None
    return e.get('stringBasekey') if e.get('type') == 1 else ANAHTARLAR.get(e.get('enumBaseKey'))


def istasyonda(s):
    """Oyunda donanımın değişebildiği yer (dunya.in_station: istasyon, ayara göre portalın güvenli bölgesi; savaştan sonra bekleme).
    Harita yüklenmemişse (giriş ekranı, hangar) istemci de izin veriyor."""
    w = getattr(s, 'world', None)
    return w is None or w.in_station()


def cpular(s):
    """Etkin geminin etkin config'indeki (dronlar dahil) aç/kapa CPU'ları ve otomatik alım CPU'ları (seçilebilecek cephaneyle)."""
    p, mg = s.profil, s.magaza
    takili = MG.EK.equipped(p)
    ids = {l: int(i) for i, l in p.d['esyalar'].items() if l in takili}
    out = []
    for l in dict.fromkeys(takili):
        if l in SE.TOGGLES:
            out.append({'lootId': l, 'tur': 'ackapa', 'acik': SE.toggled(p, l)})
        cfg = MG.EK.X.get(l, {}).get('oto_alim')
        if cfg and cfg['tur'] in ('lazer', 'roket') and l in ids:
            pre = ('ammunition_laser_',) if cfg['tur'] == 'lazer' else ('ammunition_rocket_', 'ammunition_rocketlauncher_')
            out.append({'lootId': l, 'id': ids[l], 'tur': 'cephane', 'esik': cfg['esik'], 'adet': cfg['adet'],
                        'secili': p.d.get('oto_alim_cephane', {}).get(l),
                        'secenekler': sorted(c for c in mg.catalog if c.startswith(pre) and mg.price(c))})
    return out


def hangar(game, q):
    s = oturum(game)
    p, mg = s.profil, s.magaza
    with s.packet_lock:
        sid = str(q.get('gemi') or '') if str(q.get('gemi') or '') in p.d['gemiler'] else p.d['aktif_gemi']
        gemi = p.ship(sid)
        yuvalar = [y for _p, y in MG.SLOTS if mg.capacity(y, sid) > 0]
        yerler = p.item_places()
        konfigler = {}
        for cid in sorted(gemi['konfigler']):
            cfg = p.config(cid, sid)
            konfigler[cid] = {y: {'kapasite': mg.capacity(y, sid, cid),
                                  'esyalar': [{'id': i, 'lootId': p.d['esyalar'][str(i)]} for i in cfg.get(y, []) if str(i) in p.d['esyalar']]}
                              for y in yuvalar}
        esya = lambda i: {'id': i, 'lootId': p.d['esyalar'][str(i)]} if i and str(i) in p.d['esyalar'] else None
        dronlar, pet = {}, {}
        for cid in sorted(gemi['konfigler']):
            dcfg = p.drone_config(cid, sid)
            dronlar[cid] = [{'id': x['kimlik'], 'lootId': x['lootId'], 'kapasite': MG.DRONES.get(x['lootId'], {}).get('yuva', 1),
                             'esyalar': [esya(i) for i in dcfg.get(str(x['kimlik']), []) if esya(i)],
                             'tasarim': esya(p.drone_design_id(x, 'design', cid, sid)), 'gorunum': esya(p.drone_design_id(x, 'visual', cid, sid))}
                            for x in p.d['dronlar']]
            if mg.pet.owned:
                pc = mg.pet.config(cid, sid)
                pet[cid] = {y: {'kapasite': mg.pet.open_slots(y), 'esyalar': [esya(i) for i in pc.get(y, []) if esya(i)],
                                'fiyat': mg.pet.slot_price(y) if y in PETM.PET['yuva_fiyatlari'] else 0} for y in PETM.ALL_SLOTS}

        def hedefler(l):
            h = (['ship'] if MG.slot_of(l) in yuvalar else []) + (['drone'] if MG.drone_ok(l) or l in MG.DESIGNS else [])
            return h + (['pet'] if mg.pet.owned and PETM.slot_for(l) else [])
        envanter = []
        for i, l in p.d['esyalar'].items():
            yer = yerler.get(int(i))
            # items on another ship are hidden; items in a config of this ship stay listed for the other config (as in game)
            if (yer and yer[0] != sid) or l.startswith(('drone_', 'ship_')):          # dronlar ve gemiler eşya kaydında da durur
                continue
            sat = mg.sale_value(l) if not l.startswith(MG.QF.PREFIX) else None
            if hedefler(l) or (sat and not yer):
                envanter.append({'id': int(i), 'lootId': l, 'hedefler': hedefler(l), 'seviye': MG.YK.item_level(p, int(i)),
                                 'yuva': MG.slot_of(l) or PETM.slot_for(l) or ('tasarim' if l in MG.DESIGNS else 'diger'),
                                 'satis': list(sat) if sat and not yer else None, 'konfigler': sorted(yer[1]) if yer else []})
        gemiler = [{'id': k, 'lootId': g['lootId'], 'tasarim': g.get('tasarim'), 'aktif': k == p.d['aktif_gemi'],
                    'favori': bool(g.get('favori')), 'kayitli': bool(g.get('kayitli_konfig'))} for k, g in p.d['gemiler'].items()]
        petd = mg.pet.d if mg.pet.owned else None
        return dict(cuzdan(s), gemi=sid, aktif_konfig=str(gemi['aktif_konfig']), gemiler=gemiler, yuvalar=yuvalar,
                    konfigler=konfigler, dronlar=dronlar, pet=pet or None, pet_yuvalari=list(PETM.ALL_SLOTS),
                    pet_bilgi={'ad': petd.get('ad'), 'seviye': petd.get('seviye'), 'ad_fiyati': mg.pet.rename_price(),
                               'heat_acik': mg.pet.heat_lv() >= PETM.HEAT['yuva_seviyesi']} if petd else None,
                    tasarimlar=mg.designs(sid), gorunum=p.ship_look(sid), envanter=envanter, cpular=cpular(s),
                    istasyonda=istasyonda(s), portal_hangar=bool(AY.get('portal_hangar')))


def tasi(game, b):
    s = oturum(game)
    sid = str(b.get('gemi') or '')
    if sid not in s.profil.d['gemiler']:
        raise Hata(400, 'gemi')
    if not istasyonda(s):
        return {'tamam': False, 'hata': 'istasyon'}
    tak, hedef = b.get('yon') == 'tak', b.get('hedef') if b.get('hedef') in ('ship', 'drone', 'pet') else 'ship'
    f = {'items': [int(b.get('esya') or 0)], 'source': 'inventory' if tak else hedef, 'destination': hedef if tak else 'inventory',
         'configId': int(b.get('konfig') or 1), 'hangarId': s.profil.ship(sid)['hangarId'], 'droneId': int(b.get('dron') or 0),
         'slotSet': 'default' if hedef == 'drone' else 'heat' if b.get('kume') == 'heat' else ''}
    cmd = yanit(isle(s, 'HangarShipMoveItemsRequest', f), 'HangarShipMoveItemsCommand') or {}
    return {'tamam': cmd.get('result') == 1, 'hata': hata_adi(cmd.get('errorMessage'))}


def etkin(game, b):
    s = oturum(game)
    cmd = yanit(isle(s, 'HangarShipActivateShipRequest', {'shipId': str(b.get('gemi') or '')}), 'HangarShipActivateShipCommand') or {}
    return {'tamam': cmd.get('result') == 1, 'hata': None if cmd.get('result') == 1 else hata_adi(cmd.get('errorMessage'))}


def tasarim(game, b):
    s = oturum(game)
    if not istasyonda(s):
        return {'tamam': False, 'hata': 'istasyon'}
    f = {'shipId': str(b.get('gemi') or ''), 'lootId': str(b.get('lootId') or '')}
    cmd = yanit(isle(s, 'HangarShipChangeShipModelRequest', f), 'HangarShipChangeShipModelCommand') or {}
    return {'tamam': cmd.get('resultId') == 1, 'hata': hata_adi(cmd.get('errorMessage'))}


def sonuc(giden, ad):
    """Yanıt komutu -> {tamam, hata}: resultId ya da result 1 başarı; hata errorMessage ya da (yükleme penceresi) description."""
    cmd = yanit(giden, ad) or {}
    ok = (cmd.get('resultId') if 'resultId' in cmd else cmd.get('result')) == 1
    return {'tamam': ok, 'hata': None if ok else hata_adi(cmd.get('errorMessage') or cmd.get('description')) or 'eqt_error_generic'}


# işlem -> (istek, alanlar(b, profil), yanıt komutu); ISTASYON'dakiler oyunda yalnız istasyonda (donanım değişir)
ISLEMLER = {
    'temizle': ('HangarShipClearConfigRequest', lambda b, p: {'wipe': 0, 'configId': int(b.get('konfig') or 1), 'shipId': str(b.get('gemi'))},
                'HangarShipClearConfigCommand'),
    'kaydet': ('HangarShipSaveConfigRequest', lambda b, p: {'shipId': str(b.get('gemi'))}, 'HangarShipSaveConfigCommand'),
    'yukle': ('HangarShipLoadConfigRequest', lambda b, p: {'shipId': str(b.get('gemi'))}, 'HangarShipLoadConfigCommand'),
    'aktar': ('HangarShipImportConfigRequest', lambda b, p: {'originShipId': str(b.get('gemi')), 'targetShipId': str(b.get('hedef_gemi'))},
              'HangarShipImportConfigCommand'),
    'favori': ('HangarShipFavouriteRequest', lambda b, p: {'shipId': str(b.get('gemi')), 'favourite': bool(b.get('favori'))},
               'HangarShipFavouriteCommand'),
    'sat': ('HangarShipSellItemRequest', lambda b, p: {'itemList': [{'itemId': int(i), 'quantity': 1} for i in b.get('esyalar') or []]},
            'HangarShipSellItemCommand'),
    'dron_sat': ('HangarShipSellDroneRequest', lambda b, p: {'droneId': int(b.get('dron') or 0)}, 'HangarShipSellDroneCommand'),
    'pet_ad': ('HangarShipRenamePetRequest', lambda b, p: {'name': str(b.get('ad') or '')}, 'HangarShipRenamePetCommand'),
    'pet_yuva': ('HangarShipUnlockSlotRequest', lambda b, p: {'slotset': str(b.get('yuva') or '')}, 'HangarShipUnlockSlotCommand'),
    'cpu_cephane': ('HangarShipAutoBuyCpuAmmoRequest', lambda b, p: {'itemId': int(b.get('esya') or 0), 'ammoLootId': str(b.get('cephane') or '')},
                    'HangarShipAutoBuyCpuAmmoCommand'),
}
ISTASYON = ('temizle', 'yukle', 'aktar', 'dron_sat')


def hangar_islem(game, b):
    s = oturum(game)
    islem = b.get('islem')
    if islem == 'konfig':                   # kısayol çubuğunun config düğmesi gibi (eski metin isteği S|CFG; oyunda her yerde, beklemeli)
        n = str(int(b.get('konfig') or 1))
        once = s.profil.ship()['aktif_konfig']
        isle(s, 'LegacyModule', {'message': 'S|CFG|%s|%d' % (n, s.profil.user_id)})
        ok = str(s.profil.ship()['aktif_konfig']) == n
        return {'tamam': ok, 'hata': None if ok else 'config_change_failed_time' if str(once) != n else None}
    if islem == 'cpu':                      # aç/kapa CPU'su: kısayol çubuğundaki öğesine tıklamak gibi
        l = str(b.get('lootId') or '')
        if l not in SE.TOGGLES or getattr(s, 'world', None) is None:
            raise Hata(400, 'cpu')
        once = SE.toggled(s.profil, l)
        isle(s, 'MenuActionRequest', {'menuItemId': l, 'actionType': 0})
        return {'tamam': SE.toggled(s.profil, l) != once, 'hata': None}
    if islem not in ISLEMLER:
        raise Hata(400, 'islem')
    if islem in ISTASYON and not istasyonda(s):
        return {'tamam': False, 'hata': 'istasyon'}
    istek, alanlar, yanit_ad = ISLEMLER[islem]
    return sonuc(isle(s, istek, alanlar(b, s.profil)), yanit_ad)


def abone(game, b):
    s = oturum(game)
    f = {'lootId': str(b.get('lootId') or ''), 'category': str(b.get('category') or ''), 'amount': 1, 'action': 'toggleSubscription',
         'buyCategory': '', 'level': 1, 'petName': ''}
    cmd = yanit(isle(s, 'ShopItemBuyRequest', f), 'ShopItemBuyCommand') or {}
    return dict(cuzdan(s), tamam=cmd.get('resultId') == 1, hata=hata_adi(cmd.get('errorMessage')))


def skylab(game):
    s = oturum(game)
    sk = s.skylab
    isle(s, 'SkylabActionRequest', {'construction': '', 'subaction': ''})       # biriken üretim, biten yükseltme ve taşıma
    with s.packet_lock:
        now, st = time.time(), sk.st
        moduller = []
        for k in SKY.ORDER:
            m, c = sk.module(k), sk.upgrade_cost(k)
            moduller.append({'id': k, 'seviye': m['seviye'], 'azami': SKY.MODULES[k]['azami'], 'durum': sk.state(k),
                             'enerji': sk.energy(k), 'uretim': sk.production(k),
                             'maliyet': dict(c, sure_sn=AY.sure(c['sure_sn'], 'skylab')) if c else None,     # panelin bekleme çarpanıyla
                             'kalan': max(0, int(m['yukseltme'] - now)) if m.get('yukseltme') else None, 'bitirme': sk.finish_price(k, now),
                             'acilir': k not in SKY.ALWAYS_ON, 'verim': sk.efficiency(k) if k in SKY.COLLECTORS else None,
                             'robot': {'etkin': len(st['robotlar'].get(k, [])), 'depoda': len(st['yedek'].get(k, [])),
                                       'azami': SKY.ROBOTS['azami'], 'fiyat': {t: sk.robot_price(t) for t in ('1', '2')}}
                             if k in SKY.COLLECTORS else None})
        t = st.get('tasima')
        return dict(cuzdan(s), moduller=moduller, enerji={'kullanilan': sk.consumption(), 'gunes': sk.solar()},
                    depo=[{'id': o, 'ad': SKY.ORES[o][0], 'miktar': sk.amount(o), 'kapasite': sk.capacity(o)} for o in SKY.ORE_ORDER],
                    tasima={'kalan': max(0, int(t['bitis'] - now)), 'yuk': t['yuk']} if t else None,
                    hizli_fiyat=AY.fiyat('hizmet_fiyat', SKY.TRANSPORT['hizli_uridyum'], 'skylab'))


SKYLAB_ISLEM = ('upgrade', 'instantUpgrade', 'instantFinishUpgrade', 'abortUpgrade', 'setActive', 'setInactive', 'startTransport')


def skylab_islem(game, b):
    s = oturum(game)
    if b.get('islem') not in SKYLAB_ISLEM:
        raise Hata(400, 'islem')
    f = {'construction': str(b.get('modul') or ''), 'subaction': b['islem'], 'transportMode': str(b.get('mod') or '')}
    for o, n in (b.get('miktarlar') or {}).items():
        if o in SKY.ORES:
            f['count' + SKY.ORES[o][0]] = max(0, int(n or 0))
    s.skylab.son_islem = ([], [])
    isle(s, 'SkylabActionRequest', f)
    ad = lambda c: hata_adi(c) if isinstance(c, dict) else ANAHTARLAR.get(c, str(c))
    err, ok = s.skylab.son_islem
    return {'tamam': not err, 'hatalar': [ad(c) for c in err], 'basarilar': [ad(c) for c in ok]}


def robot(game, b):
    s = oturum(game)
    if b.get('modul') not in SKY.COLLECTORS or str(b.get('tip')) not in ('1', '2'):
        raise Hata(400, 'robot')
    s.skylab.son_islem = ([], [])
    isle(s, 'SkylabPurchaseRobotRequest', {'construction': b['modul'], 'robotType': int(b['tip'])})
    err = s.skylab.son_islem[0]
    return {'tamam': not err, 'hatalar': [ANAHTARLAR.get(c, str(c)) for c in err]}


def muzayede(game):
    s = oturum(game)
    mz = s.sosyal.muzayede
    isle(s, 'AuctionListRequest', {})                 # dönem sonu ve geçilen teklifler işlenir; istemcinin listesi de yenilenir
    with s.packet_lock:
        now = time.time()
        lotlar = []
        for lot in MZ.LOTS.values():
            if mz.owned(lot) and not mz.bid_rec(lot, now):
                continue
            d, key = mz.data(lot, now), '%s|%s' % (lot['tur'], lot['loot'])
            lotlar.append({'tur': lot['tur'], 'loot': lot['loot'], 'grup': lot['grup'], 'adet': lot['adet'], 'anlik': bool(lot['anlik'] and lot['fiyat']),
                           'fiyat': mz.unit_price(lot), 'en_yuksek': d['highestBid'], 'en_yuksek_ad': d['highestBidderName'], 'benim': d['myBid'],
                           'onde': mz.top(lot, now)[1], 'sonraki': mz.next_bid(lot, now), 'oto': mz.d['otomatik'].get(key),
                           'alarm': mz.d['alarmlar'].get(key)})
        return dict(cuzdan(s), lotlar=lotlar, kalan={k: MZ.period_end(k, now) - int(now) for k in MZ.SPAN}, artis=MZ.D['artis'],
                    en_az=MZ.D['en_az_teklif'], gecmis=mz.history(now)[:30], olaylar=mz.d['olaylar'][:30], rakip=MZ.rival_level(),
                    kimlik=s.profil.user_id)


def mz_teklif(s, tur, loot, fiyat):
    cmd = yanit(isle(s, 'AuctionBidRequest', {'type': tur, 'lootId': loot, 'price': int(fiyat)}), 'AuctionBidCommand') or {}
    return {'tamam': bool(cmd.get('success')), 'hata': None if cmd.get('success') else hata_adi(cmd.get('stack'))}


def teklif(game, b):
    return dict(mz_teklif(oturum(game), str(b.get('tur')), str(b.get('loot')), int(b.get('fiyat') or 0)))


def hepsi(game, b):
    """Hepsine katıl: önde olunmayan her lota en düşük geçerli teklif (kredi yetene dek)."""
    s = oturum(game)
    mz, verilen, tutar, hatalar = s.sosyal.muzayede, 0, 0, {}
    for tur, loot in b.get('lotlar') or []:
        lot = MZ.LOTS.get((str(tur), str(loot)))
        now = time.time()
        if not lot or mz.top(lot, now)[1]:
            continue
        fiyat = mz.next_bid(lot, now)
        r = mz_teklif(s, lot['tur'], lot['loot'], fiyat)
        if r['tamam']:
            verilen, tutar = verilen + 1, tutar + fiyat
        else:
            hatalar[r['hata']] = hatalar.get(r['hata'], 0) + 1
    return dict(cuzdan(s), verilen=verilen, tutar=tutar, hatalar=hatalar)


def anlik(game, b):
    s = oturum(game)
    cmd = yanit(isle(s, 'AuctionQuickBuyRequest', {'type': str(b.get('tur')), 'lootId': str(b.get('loot'))}), 'AuctionQuickBuyCommand') or {}
    return {'tamam': bool(cmd.get('success')), 'hata': None if cmd.get('success') else hata_adi(cmd.get('stack'))}


def kural(game, b, alan):
    """Otomatik teklif ya da alarm kuralı (profilde; muzayede.oto tick'te uygular)."""
    s = oturum(game)
    lot = MZ.LOTS.get((str(b.get('tur')), str(b.get('loot'))))
    if not lot:
        raise Hata(400, 'lot')
    key, mz = '%s|%s' % (lot['tur'], lot['loot']), s.sosyal.muzayede
    if alan == 'otomatik':
        azami = max(0, int(b.get('azami') or 0))
        yeni = {'azami': azami} if azami >= MZ.D['en_az_teklif'] else None
    else:
        yeni = {'gecilince': bool(b.get('gecilince')), 'dk': max(0, min(10080, int(b.get('dk') or 0)))}
        yeni = yeni if yeni['gecilince'] or yeni['dk'] else None
    with s.profil.lock:
        if yeni:
            mz.d[alan][key] = yeni
        else:
            mz.d[alan].pop(key, None)
        s.profil.dirty = True
    return {'tamam': True}


def olaylar(game, q):
    s = oturum(game)
    son = int(q.get('son') or 0)
    return {'olaylar': [o for o in s.sosyal.muzayede.d['olaylar'] if o['no'] > son]}



# ---------------------------------------------------------------- GM Center (yalnız host; okuma / Dispatch yönetimi oyun açıkken)
def gm_admin(game):
    s = oturum(game)
    import gm_konsol as GMK
    if not GMK.enabled(s.profil):
        raise Hata(403, 'GM Center kapalı: Geliştirici > GM konsolu ayarını açın.')
    return s


def gm_bootstrap(game, anahtar):
    # Kanal yalnız 127.0.0.1 üzerinde dinliyor. Bu ilk el sıkışma yalnız arayüzün
    # oturum anahtarını almasını sağlar; tüm veri/işlem uçları anahtarla korunur.
    gm_admin(game)
    return {'enabled': True, 'port': PORT, 'token': anahtar}


def gm_players(game):
    gm_admin(game)
    import topluluk as TP
    import harita as H
    out = []
    for person in TP.hepsi().values():
        try:
            row = GMC.player_snapshot(person)
            try:
                row['map_name'] = H.name(row.get('map_id')) if row.get('map_id') is not None else ''
            except Exception:
                row['map_name'] = str(row.get('map_id') or '')
            row['session_ready'] = person.oturum is not None
            out.append(row)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda x: (not x['online'], x['name'].casefold(), x['uid']))
    return {'players': out, 'count': len(out)}


def gm_dispatch_gates(game, q):
    gm_admin(game)
    import topluluk as TP
    raw_uid = str(q.get('uid') or '').strip()
    if not raw_uid:
        raise Hata(400, 'uid')
    uid = int(raw_uid) if raw_uid.isdigit() else raw_uid
    person = TP.bul(uid=uid)
    if person is None:
        raise Hata(404, 'gracz')
    return {'target': GMC.player_snapshot(person), 'gates': GMC.dispatch_snapshot(person)}


def gm_dispatch_gate(game, b):
    gm_admin(game)
    import topluluk as TP
    import dispatch as DSP
    raw_uid = str(b.get('uid') or '').strip()
    if not raw_uid:
        raise Hata(400, 'uid')
    uid = int(raw_uid) if raw_uid.isdigit() else raw_uid
    person = TP.bul(uid=uid)
    if person is None:
        raise Hata(404, 'gracz')
    if person.oturum is None or person.oturum.profil is not person.profil:
        raise Hata(409, 'gracz jest offline; w tej wersji operacje Dispatch wymagają aktywnej sesji')
    action = str(b.get('action') or '')
    try:
        gate_id = int(b.get('gateId') or 0)
    except (TypeError, ValueError):
        raise Hata(400, 'gateId')
    if action == 'send':
        request, fields = 'DispatchSendGateRequest', {'gateId': gate_id}
    elif action == 'collect':
        request, fields = 'DispatchCollectGateRewardRequest', {'gateId': gate_id}
    else:
        raise Hata(400, 'action')
    s = person.oturum
    giden = isle(s, request, fields)
    if action == 'send':
        cmd = yanit(giden, 'DispatchMessageCommand') or {}
        message_type = cmd.get('messageType')
        tamam = message_type == DSP.SUCCESS_SEND_GATE
    else:
        cmd = yanit(giden, 'DispatchLootMessageCommand') or {}
        message_type = cmd.get('messageType')
        tamam = message_type == DSP.COLLECTED
    return {'tamam': bool(tamam), 'message_type': message_type, 'gates': GMC.dispatch_snapshot(person)}



def start(game, folder, log=print):
    anahtar = secrets.token_hex(16)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _yanit(self, kod, d):
            data = json.dumps(d, ensure_ascii=False).encode('utf8')
            self.send_response(kod)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _isle(self, fn):
            if not secrets.compare_digest(self.headers.get('X-Anahtar') or '', anahtar):
                return self._yanit(403, {'hata': 'anahtar'})
            try:
                return self._yanit(200, fn())
            except Hata as e:
                return self._yanit(e.kod, {'hata': str(e)})
            except Exception as e:
                log('panel kanalı: %s hatası: %r' % (self.path, e))
                return self._yanit(500, {'hata': repr(e)})

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == '/gm/bootstrap':
                try:
                    return self._yanit(200, gm_bootstrap(game, anahtar))
                except Hata as e:
                    return self._yanit(e.kod, {'hata': str(e)})
            if u.path == '/gm/players':
                return self._isle(lambda: gm_players(game))
            if u.path == '/gm/dispatch/gates':
                return self._isle(lambda: gm_dispatch_gates(game, q))
            if u.path == '/magaza':
                return self._isle(lambda: magaza(game))
            if u.path == '/hangar':
                return self._isle(lambda: hangar(game, q))
            if u.path == '/skylab':
                return self._isle(lambda: skylab(game))
            if u.path == '/muzayede':
                return self._isle(lambda: muzayede(game))
            if u.path == '/muzayede/olaylar':
                return self._isle(lambda: olaylar(game, q))
            self._yanit(404, {'hata': 'yok'})

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            try:
                b = json.loads(self.rfile.read(n).decode('utf8') or '{}') if n else {}
            except ValueError:
                return self._yanit(400, {'hata': 'json'})
            yollar = {'/gm/dispatch/gate': gm_dispatch_gate, '/magaza/al': al, '/magaza/abone': abone,
                      '/hangar/tasi': tasi, '/hangar/etkin': etkin, '/hangar/tasarim': tasarim,
                      '/hangar/islem': hangar_islem,
                      '/skylab/islem': skylab_islem, '/skylab/robot': robot, '/muzayede/teklif': teklif, '/muzayede/hepsi': hepsi,
                      '/muzayede/anlik': anlik, '/muzayede/oto': lambda g, b: kural(g, b, 'otomatik'),
                      '/muzayede/alarm': lambda g, b: kural(g, b, 'alarmlar'), '/bot/ad_kaydi': bot_ad_kaydi,
                      '/bot/detay': bot_detay, '/bot/duzenle': bot_duzenle}
            if self.path in yollar and isinstance(b, dict):
                return self._isle(lambda: yollar[self.path](game, b))
            self._yanit(404, {'hata': 'yok'})

    try:
        srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError as e:
        log('panel kanalı açılamadı (%d): %r' % (PORT, e))
        return None
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    path = os.path.join(folder, 'panel_kanali.json')
    with open(path + '.tmp', 'w', encoding='utf8') as fh:
        json.dump({'port': srv.server_address[1], 'anahtar': anahtar, 'pid': os.getpid()}, fh)
    os.replace(path + '.tmp', path)
    return srv
