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

import settings as SET
import shop as SHP
import auction as MZ
import pet as PETM
import combat_items as CIT
import skylab as SKY

PORT = 8098
KEY_NAMES = {v: k for k, v in SHP.BASEKEY.items()}      # BaseKey numarası -> adı (mesaj_anahtarlari.json)


class Error(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def session(game):
    s = game.CURRENT
    if s is None or s.profile is None or getattr(s, 'shop', None) is None:
        raise Error(409, 'oyun bağlı değil')
    return s


def wallet(s):
    pl = s.profile.d['pilot']
    return {'kredi': pl.get('credits', 0), 'uridyum': pl.get('uridium', 0), 'istasyonda': in_station(s),
            'firma': {1: 'mmo', 2: 'eic', 3: 'vru'}.get(pl.get('factionId'), 'eic')}     # gemi simgeleri şirkete göre


def shop(game):
    s = session(game)
    with s.packet_lock:
        by_category = {}
        for c in s.shop.lists:
            m = s.shop.shop_list(c)            # ('ShopItemListCommand', alanlar)
            if m and m[1]['itemList']:
                by_category[c] = m[1]['itemList']
        order = [p['category'] for p in next(iter(s.shop.lists.values()), {}).get('promptList', []) if p['category'] in by_category]
        return dict(wallet(s), kategoriler=order + [c for c in by_category if c not in order], esyalar=by_category)


def bot_name_log(game, b):
    """Panel bir botun adını değiştirdi (name_log.py): oyun açıkken hemen uygulanır (botlar, klanlar, bağlı oyuncuların rehberi)."""
    from bot import manager as MGR
    y = MGR.ACTIVE
    return {'tamam': True, 'degisen': y.apply_name_log() if y is not None else 0}


def _bot(b):
    from bot import manager as MGR
    y = MGR.ACTIVE
    if y is None:
        raise Error(409, 'botlar açık değil')
    bot = next((x for x in y.bots if x.k['no'] == int(b.get('no') or 0)), None)
    roster_row = next((x for x in y.package.get('kadro', []) if x['no'] == int(b.get('no') or 0)), None)
    if bot is None or roster_row is None:
        raise Error(404, 'bot yok')
    return y, bot, roster_row


def bot_detail(game, b):
    """Panelin bot penceresi, oyun açıkken: canlı botun durumu (bot/duzenle.gorunum)."""
    from bot import edit as ED
    y, bot, roster_row = _bot(b)
    with y.lock:
        bot.save()                                    # ruh hâli nesneden sözlüğe
        return ED.appearance(bot.k, roster_row, online=bot.online)


def edit_bot(game, b):
    """Panel bir botu düzenledi, oyun açıkken: canlı bota hemen uygulanır (ruh hâli nesnesi, ekipman önbelleği, profil eşitlenir).
    Hata kodu yanıtta (panel kendi dilinde iletir)."""
    from bot import edit as ED, society
    y, bot, roster_row = _bot(b)
    value = b.get('degisiklik') or {}
    with y.lock:
        bot.save()
        try:
            ED.apply(bot.k, roster_row, value, online=bot.online)
        except ED.EditError as e:
            return {'hata': e.code, 'alan': e.area}
        if 'ruh' in value:
            bot.mood.d.update(bot.k['ruh'])
        if any(a in value for a in ('gemi', 'ekip', 'cephane')):
            bot.loadout_changed()
        society.update(bot)
        return ED.appearance(bot.k, roster_row, online=bot.online)


def handle(s, name, f):
    """İstemci göndermiş gibi (game.Session.inject gibi) -> o sırada istemciye gönderilen mesajlar."""
    outgoing = []
    with s.packet_lock:
        original = s.send

        def capture(msgs, *a, **k):
            outgoing.extend(msgs)
            return original(msgs, *a, **k)
        s.send = capture              # alt sistemler self.send'i çağrı anında arar (lambda m: self.send(...)): hepsi yakalanır
        try:
            s.on_packet(name, -1, f, None)
        finally:
            del s.send
    return outgoing


def buy(game, b):
    s = session(game)
    lid = str(b.get('lootId') or '')
    if not lid:
        raise Error(400, 'lootId')
    f = {'lootId': lid, 'category': str(b.get('category') or ''), 'amount': max(1, int(b.get('amount') or 1)),
         'level': max(1, int(b.get('level') or 1)), 'buyCategory': '', 'petName': ''}
    cmd = response(handle(s, 'ShopItemBuyRequest', f), 'ShopItemBuyCommand')
    if cmd is None:
        return dict(wallet(s), tamam=False, hata='shop_item_not_found')
    return dict(wallet(s), tamam=cmd.get('resultId') == 1, hata=error_name(cmd.get('errorMessage')))


def response(outgoing, name):
    return next((m[1] for m in outgoing if isinstance(m, tuple) and m[0] == name), None)


def error_name(e):
    """Yanıt komutunun BaseStackCommand'i -> BaseKey adı (type 0) ya da ham metin (type 1)."""
    if not e:
        return None
    return e.get('stringBasekey') if e.get('type') == 1 else KEY_NAMES.get(e.get('enumBaseKey'))


def in_station(s):
    """Oyunda donanımın değişebildiği yer (dunya.in_station: istasyon, ayara göre portalın güvenli bölgesi; savaştan sonra bekleme).
    Harita yüklenmemişse (giriş ekranı, hangar) istemci de izin veriyor."""
    w = getattr(s, 'world', None)
    return w is None or w.in_station()


def cpus(s):
    """Etkin geminin etkin config'indeki (dronlar dahil) aç/kapa CPU'ları ve otomatik alım CPU'ları (seçilebilecek cephaneyle)."""
    p, shop = s.profile, s.shop
    equipped = SHP.EX.equipped(p)
    ids = {l: int(i) for i, l in p.d['esyalar'].items() if l in equipped}
    out = []
    for l in dict.fromkeys(equipped):
        if l in CIT.TOGGLES:
            out.append({'lootId': l, 'tur': 'ackapa', 'acik': CIT.toggled(p, l)})
        cfg = SHP.EX.X.get(l, {}).get('oto_alim')
        if cfg and cfg['tur'] in ('lazer', 'roket') and l in ids:
            pre = ('ammunition_laser_',) if cfg['tur'] == 'lazer' else ('ammunition_rocket_', 'ammunition_rocketlauncher_')
            out.append({'lootId': l, 'id': ids[l], 'tur': 'cephane', 'esik': cfg['esik'], 'adet': cfg['adet'],
                        'secili': p.d.get('oto_alim_cephane', {}).get(l),
                        'secenekler': sorted(c for c in shop.catalog if c.startswith(pre) and shop.price(c))})
    return out


def hangar(game, q):
    s = session(game)
    p, shop = s.profile, s.shop
    with s.packet_lock:
        sid = str(q.get('gemi') or '') if str(q.get('gemi') or '') in p.d['gemiler'] else p.d['aktif_gemi']
        ship = p.ship(sid)
        slots = [y for _p, y in SHP.SLOTS if shop.capacity(y, sid) > 0]
        places = p.item_places()
        configs = {}
        for cid in sorted(ship['konfigler']):
            cfg = p.config(cid, sid)
            configs[cid] = {y: {'kapasite': shop.capacity(y, sid, cid),
                                  'esyalar': [{'id': i, 'lootId': p.d['esyalar'][str(i)]} for i in cfg.get(y, []) if str(i) in p.d['esyalar']]}
                              for y in slots}
        item = lambda i: {'id': i, 'lootId': p.d['esyalar'][str(i)]} if i and str(i) in p.d['esyalar'] else None
        drones, pet = {}, {}
        for cid in sorted(ship['konfigler']):
            dcfg = p.drone_config(cid, sid)
            drones[cid] = [{'id': x['kimlik'], 'lootId': x['lootId'], 'kapasite': SHP.DRONES.get(x['lootId'], {}).get('yuva', 1),
                             'esyalar': [item(i) for i in dcfg.get(str(x['kimlik']), []) if item(i)],
                             'tasarim': item(p.drone_design_id(x, 'design', cid, sid)), 'gorunum': item(p.drone_design_id(x, 'visual', cid, sid))}
                            for x in p.d['dronlar']]
            if shop.pet.owned:
                pc = shop.pet.config(cid, sid)
                pet[cid] = {y: {'kapasite': shop.pet.open_slots(y), 'esyalar': [item(i) for i in pc.get(y, []) if item(i)],
                                'fiyat': shop.pet.slot_price(y) if y in PETM.PET['yuva_fiyatlari'] else 0} for y in PETM.ALL_SLOTS}

        def targets(l):
            h = (['ship'] if SHP.slot_of(l) in slots else []) + (['drone'] if SHP.drone_ok(l) or l in SHP.DESIGNS else [])
            return h + (['pet'] if shop.pet.owned and PETM.slot_for(l) else [])
        inventory = []
        for i, l in p.d['esyalar'].items():
            place = places.get(int(i))
            # items on another ship are hidden; items in a config of this ship stay listed for the other config (as in game)
            if (place and place[0] != sid) or l.startswith(('drone_', 'ship_')):          # dronlar ve gemiler eşya kaydında da durur
                continue
            sale = shop.sale_value(l) if not l.startswith(SHP.QF.PREFIX) else None
            if targets(l) or (sale and not place):
                inventory.append({'id': int(i), 'lootId': l, 'hedefler': targets(l), 'seviye': SHP.UPG.item_level(p, int(i)),
                                 'yuva': SHP.slot_of(l) or PETM.slot_for(l) or ('tasarim' if l in SHP.DESIGNS else 'diger'),
                                 'satis': list(sale) if sale and not place else None, 'konfigler': sorted(place[1]) if place else []})
        ships = [{'id': k, 'lootId': g['lootId'], 'tasarim': g.get('tasarim'), 'aktif': k == p.d['aktif_gemi'],
                    'favori': bool(g.get('favori')), 'kayitli': bool(g.get('kayitli_konfig'))} for k, g in p.d['gemiler'].items()]
        petd = shop.pet.d if shop.pet.owned else None
        return dict(wallet(s), gemi=sid, aktif_konfig=str(ship['aktif_konfig']), gemiler=ships, yuvalar=slots,
                    konfigler=configs, dronlar=drones, pet=pet or None, pet_yuvalari=list(PETM.ALL_SLOTS),
                    pet_bilgi={'ad': petd.get('ad'), 'seviye': petd.get('seviye'), 'ad_fiyati': shop.pet.rename_price(),
                               'heat_acik': shop.pet.heat_lv() >= PETM.HEAT['yuva_seviyesi']} if petd else None,
                    tasarimlar=shop.designs(sid), gorunum=p.ship_look(sid), envanter=inventory, cpular=cpus(s),
                    istasyonda=in_station(s), portal_hangar=bool(SET.get('portal_hangar')))


def carry(game, b):
    s = session(game)
    sid = str(b.get('gemi') or '')
    if sid not in s.profile.d['gemiler']:
        raise Error(400, 'gemi')
    if not in_station(s):
        return {'tamam': False, 'hata': 'istasyon'}
    equip, target = b.get('yon') == 'tak', b.get('hedef') if b.get('hedef') in ('ship', 'drone', 'pet') else 'ship'
    f = {'items': [int(b.get('esya') or 0)], 'source': 'inventory' if equip else target, 'destination': target if equip else 'inventory',
         'configId': int(b.get('konfig') or 1), 'hangarId': s.profile.ship(sid)['hangarId'], 'droneId': int(b.get('dron') or 0),
         'slotSet': 'default' if target == 'drone' else 'heat' if b.get('kume') == 'heat' else ''}
    cmd = response(handle(s, 'HangarShipMoveItemsRequest', f), 'HangarShipMoveItemsCommand') or {}
    return {'tamam': cmd.get('result') == 1, 'hata': error_name(cmd.get('errorMessage'))}


def active(game, b):
    s = session(game)
    cmd = response(handle(s, 'HangarShipActivateShipRequest', {'shipId': str(b.get('gemi') or '')}), 'HangarShipActivateShipCommand') or {}
    return {'tamam': cmd.get('result') == 1, 'hata': None if cmd.get('result') == 1 else error_name(cmd.get('errorMessage'))}


def design(game, b):
    s = session(game)
    if not in_station(s):
        return {'tamam': False, 'hata': 'istasyon'}
    f = {'shipId': str(b.get('gemi') or ''), 'lootId': str(b.get('lootId') or '')}
    cmd = response(handle(s, 'HangarShipChangeShipModelRequest', f), 'HangarShipChangeShipModelCommand') or {}
    return {'tamam': cmd.get('resultId') == 1, 'hata': error_name(cmd.get('errorMessage'))}


def result(outgoing, name):
    """Yanıt komutu -> {tamam, hata}: resultId ya da result 1 başarı; hata errorMessage ya da (yükleme penceresi) description."""
    cmd = response(outgoing, name) or {}
    ok = (cmd.get('resultId') if 'resultId' in cmd else cmd.get('result')) == 1
    return {'tamam': ok, 'hata': None if ok else error_name(cmd.get('errorMessage') or cmd.get('description')) or 'eqt_error_generic'}


# işlem -> (istek, alanlar(b, profil), yanıt komutu); ISTASYON'dakiler oyunda yalnız istasyonda (donanım değişir)
OPS = {
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
STATION = ('temizle', 'yukle', 'aktar', 'dron_sat')


def hangar_action(game, b):
    s = session(game)
    operation = b.get('islem')
    if operation == 'konfig':                   # kısayol çubuğunun config düğmesi gibi (eski metin isteği S|CFG; oyunda her yerde, beklemeli)
        n = str(int(b.get('konfig') or 1))
        once = s.profile.ship()['aktif_konfig']
        handle(s, 'LegacyModule', {'message': 'S|CFG|%s|%d' % (n, s.profile.user_id)})
        ok = str(s.profile.ship()['aktif_konfig']) == n
        return {'tamam': ok, 'hata': None if ok else 'config_change_failed_time' if str(once) != n else None}
    if operation == 'cpu':                      # aç/kapa CPU'su: kısayol çubuğundaki öğesine tıklamak gibi
        l = str(b.get('lootId') or '')
        if l not in CIT.TOGGLES or getattr(s, 'world', None) is None:
            raise Error(400, 'cpu')
        once = CIT.toggled(s.profile, l)
        handle(s, 'MenuActionRequest', {'menuItemId': l, 'actionType': 0})
        return {'tamam': CIT.toggled(s.profile, l) != once, 'hata': None}
    if operation not in OPS:
        raise Error(400, 'islem')
    if operation in STATION and not in_station(s):
        return {'tamam': False, 'hata': 'istasyon'}
    request, fields, reply_name = OPS[operation]
    return result(handle(s, request, fields(b, s.profile)), reply_name)


def subscriber(game, b):
    s = session(game)
    f = {'lootId': str(b.get('lootId') or ''), 'category': str(b.get('category') or ''), 'amount': 1, 'action': 'toggleSubscription',
         'buyCategory': '', 'level': 1, 'petName': ''}
    cmd = response(handle(s, 'ShopItemBuyRequest', f), 'ShopItemBuyCommand') or {}
    return dict(wallet(s), tamam=cmd.get('resultId') == 1, hata=error_name(cmd.get('errorMessage')))


def skylab(game):
    s = session(game)
    skylab = s.skylab
    handle(s, 'SkylabActionRequest', {'construction': '', 'subaction': ''})       # biriken üretim, biten yükseltme ve taşıma
    with s.packet_lock:
        now, st = time.time(), skylab.st
        modules = []
        for k in SKY.ORDER:
            m, c = skylab.module(k), skylab.upgrade_cost(k)
            modules.append({'id': k, 'seviye': m['seviye'], 'azami': SKY.MODULES[k]['azami'], 'durum': skylab.state(k),
                             'enerji': skylab.energy(k), 'uretim': skylab.production(k),
                             'maliyet': dict(c, sure_sn=SET.duration(c['sure_sn'], 'skylab')) if c else None,     # panelin bekleme çarpanıyla
                             'kalan': max(0, int(m['yukseltme'] - now)) if m.get('yukseltme') else None, 'bitirme': skylab.finish_price(k, now),
                             'acilir': k not in SKY.ALWAYS_ON, 'verim': skylab.efficiency(k) if k in SKY.COLLECTORS else None,
                             'robot': {'etkin': len(st['robotlar'].get(k, [])), 'depoda': len(st['yedek'].get(k, [])),
                                       'azami': SKY.ROBOTS['azami'], 'fiyat': {t: skylab.robot_price(t) for t in ('1', '2')}}
                             if k in SKY.COLLECTORS else None})
        t = st.get('tasima')
        return dict(wallet(s), moduller=modules, enerji={'kullanilan': skylab.consumption(), 'gunes': skylab.solar()},
                    depo=[{'id': o, 'ad': SKY.ORES[o][0], 'miktar': skylab.amount(o), 'kapasite': skylab.capacity(o)} for o in SKY.ORE_ORDER],
                    tasima={'kalan': max(0, int(t['bitis'] - now)), 'yuk': t['yuk']} if t else None,
                    hizli_fiyat=SET.price('hizmet_fiyat', SKY.TRANSPORT['hizli_uridyum'], 'skylab'))


SKYLAB_ACTIONS = ('upgrade', 'instantUpgrade', 'instantFinishUpgrade', 'abortUpgrade', 'setActive', 'setInactive', 'startTransport')


def skylab_action(game, b):
    s = session(game)
    if b.get('islem') not in SKYLAB_ACTIONS:
        raise Error(400, 'islem')
    f = {'construction': str(b.get('modul') or ''), 'subaction': b['islem'], 'transportMode': str(b.get('mod') or '')}
    for o, n in (b.get('miktarlar') or {}).items():
        if o in SKY.ORES:
            f['count' + SKY.ORES[o][0]] = max(0, int(n or 0))
    s.skylab.last_operation = ([], [])
    handle(s, 'SkylabActionRequest', f)
    name = lambda c: error_name(c) if isinstance(c, dict) else KEY_NAMES.get(c, str(c))
    err, ok = s.skylab.last_operation
    return {'tamam': not err, 'hatalar': [name(c) for c in err], 'basarilar': [name(c) for c in ok]}


def robot(game, b):
    s = session(game)
    if b.get('modul') not in SKY.COLLECTORS or str(b.get('tip')) not in ('1', '2'):
        raise Error(400, 'robot')
    s.skylab.last_operation = ([], [])
    handle(s, 'SkylabPurchaseRobotRequest', {'construction': b['modul'], 'robotType': int(b['tip'])})
    err = s.skylab.last_operation[0]
    return {'tamam': not err, 'hatalar': [KEY_NAMES.get(c, str(c)) for c in err]}


def auction(game):
    s = session(game)
    auc = s.social.auction
    handle(s, 'AuctionListRequest', {})                 # dönem sonu ve geçilen teklifler işlenir; istemcinin listesi de yenilenir
    with s.packet_lock:
        now = time.time()
        lots = []
        for lot in MZ.LOTS.values():
            if auc.owned(lot) and not auc.bid_rec(lot, now):
                continue
            d, key = auc.data(lot, now), '%s|%s' % (lot['tur'], lot['loot'])
            lots.append({'tur': lot['tur'], 'loot': lot['loot'], 'grup': lot['grup'], 'adet': lot['adet'], 'anlik': bool(lot['anlik'] and lot['fiyat']),
                           'fiyat': auc.unit_price(lot), 'en_yuksek': d['highestBid'], 'en_yuksek_ad': d['highestBidderName'], 'benim': d['myBid'],
                           'onde': auc.top(lot, now)[1], 'sonraki': auc.next_bid(lot, now), 'oto': auc.d['otomatik'].get(key),
                           'alarm': auc.d['alarmlar'].get(key)})
        return dict(wallet(s), lotlar=lots, kalan={k: MZ.period_end(k, now) - int(now) for k in MZ.SPAN}, artis=MZ.D['artis'],
                    en_az=MZ.D['en_az_teklif'], gecmis=auc.history(now)[:30], olaylar=auc.d['olaylar'][:30], rakip=MZ.rival_level(),
                    kimlik=s.profile.user_id)


def auction_bid(s, kind, loot, price):
    cmd = response(handle(s, 'AuctionBidRequest', {'type': kind, 'lootId': loot, 'price': int(price)}), 'AuctionBidCommand') or {}
    return {'tamam': bool(cmd.get('success')), 'hata': None if cmd.get('success') else error_name(cmd.get('stack'))}


def bid(game, b):
    return dict(auction_bid(session(game), str(b.get('tur')), str(b.get('loot')), int(b.get('fiyat') or 0)))


def all_(game, b):
    """Hepsine katıl: önde olunmayan her lota en düşük geçerli teklif (kredi yetene dek)."""
    s = session(game)
    auc, given, amount, errors = s.social.auction, 0, 0, {}
    for kind, loot in b.get('lotlar') or []:
        lot = MZ.LOTS.get((str(kind), str(loot)))
        now = time.time()
        if not lot or auc.top(lot, now)[1]:
            continue
        price = auc.next_bid(lot, now)
        r = auction_bid(s, lot['tur'], lot['loot'], price)
        if r['tamam']:
            given, amount = given + 1, amount + price
        else:
            errors[r['hata']] = errors.get(r['hata'], 0) + 1
    return dict(wallet(s), verilen=given, tutar=amount, hatalar=errors)


def instant(game, b):
    s = session(game)
    cmd = response(handle(s, 'AuctionQuickBuyRequest', {'type': str(b.get('tur')), 'lootId': str(b.get('loot'))}), 'AuctionQuickBuyCommand') or {}
    return {'tamam': bool(cmd.get('success')), 'hata': None if cmd.get('success') else error_name(cmd.get('stack'))}


def rule(game, b, area):
    """Otomatik teklif ya da alarm kuralı (profilde; muzayede.oto tick'te uygular)."""
    s = session(game)
    lot = MZ.LOTS.get((str(b.get('tur')), str(b.get('loot'))))
    if not lot:
        raise Error(400, 'lot')
    key, auc = '%s|%s' % (lot['tur'], lot['loot']), s.social.auction
    if area == 'otomatik':
        maximum = max(0, int(b.get('azami') or 0))
        new_ = {'azami': maximum} if maximum >= MZ.D['en_az_teklif'] else None
    else:
        new_ = {'gecilince': bool(b.get('gecilince')), 'dk': max(0, min(10080, int(b.get('dk') or 0)))}
        new_ = new_ if new_['gecilince'] or new_['dk'] else None
    with s.profile.lock:
        if new_:
            auc.d[area][key] = new_
        else:
            auc.d[area].pop(key, None)
        s.profile.dirty = True
    return {'tamam': True}


def events(game, q):
    s = session(game)
    last = int(q.get('son') or 0)
    return {'olaylar': [o for o in s.social.auction.d['olaylar'] if o['no'] > last]}


def start(game, folder, log=print):
    key = secrets.token_hex(16)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _reply(self, code, d):
            data = json.dumps(d, ensure_ascii=False).encode('utf8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, fn):
            if not secrets.compare_digest(self.headers.get('X-Anahtar') or '', key):
                return self._reply(403, {'hata': 'anahtar'})
            try:
                return self._reply(200, fn())
            except Error as e:
                return self._reply(e.code, {'hata': str(e)})
            except Exception as e:
                log('panel kanalı: %s hatası: %r' % (self.path, e))
                return self._reply(500, {'hata': repr(e)})

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == '/magaza':
                return self._handle(lambda: shop(game))
            if u.path == '/hangar':
                return self._handle(lambda: hangar(game, q))
            if u.path == '/skylab':
                return self._handle(lambda: skylab(game))
            if u.path == '/muzayede':
                return self._handle(lambda: auction(game))
            if u.path == '/muzayede/olaylar':
                return self._handle(lambda: events(game, q))
            self._reply(404, {'hata': 'yok'})

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            try:
                b = json.loads(self.rfile.read(n).decode('utf8') or '{}') if n else {}
            except ValueError:
                return self._reply(400, {'hata': 'json'})
            paths = {'/magaza/al': buy, '/magaza/abone': subscriber, '/hangar/tasi': carry, '/hangar/etkin': active, '/hangar/tasarim': design,
                      '/hangar/islem': hangar_action,
                      '/skylab/islem': skylab_action, '/skylab/robot': robot, '/muzayede/teklif': bid, '/muzayede/hepsi': all_,
                      '/muzayede/anlik': instant, '/muzayede/oto': lambda g, b: rule(g, b, 'otomatik'),
                      '/muzayede/alarm': lambda g, b: rule(g, b, 'alarmlar'), '/bot/ad_kaydi': bot_name_log,
                      '/bot/detay': bot_detail, '/bot/duzenle': edit_bot}
            if self.path in paths and isinstance(b, dict):
                return self._handle(lambda: paths[self.path](game, b))
            self._reply(404, {'hata': 'yok'})

    try:
        srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError as e:
        log('panel kanalı açılamadı (%d): %r' % (PORT, e))
        return None
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    path = os.path.join(folder, 'panel_kanali.json')
    with open(path + '.tmp', 'w', encoding='utf8') as fh:
        json.dump({'port': srv.server_address[1], 'anahtar': key, 'pid': os.getpid()}, fh)
    os.replace(path + '.tmp', path)
    return srv
