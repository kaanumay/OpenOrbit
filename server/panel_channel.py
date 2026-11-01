"""Panelin oyun menüleri (kullanıcı isteği 2026-10-28: OYNA'dan sonra panelde Mağaza, Hangar, Skylab, Açık Artırma) için yerel kanal.

Oyun açıkken kayıt dosyası düzenlenemez (sunucu her 10 saniyede kaydeder; panel/kayitlar.guard): panel oyunu sunucunun içinden
değiştirir. İstekler istemci göndermiş gibi oturumun on_packet'inden geçer (fiyat, kural, görev ve başarım sayaçları oyundakiyle aynı);
sunucunun yanıtları gerçek istemciye de gider, oyundaki pencereler ve HUD anında güncellenir.

HTTP, yalnız 127.0.0.1:PORT. Anahtar her açılışta rastgele: <günlük klasörü>/panel_kanali.json {port, anahtar} (panel okur, istek
X-Anahtar başlığıyla). Sunucunun kendi oyuncusu (game.CURRENT) bağlı değilse 409.
  GET  /magaza   kredi, uridyum, kategoriler ve her kategorinin ürünleri (magaza.shop_list: istemcinin gördüğü liste)
  POST /magaza/al {lootId, category, amount, level}  ShopItemBuyRequest -> {tamam, hata (ShopItemBuyCommand.errorMessage'ın
                 BaseKey adı ya da ham metni; panel çevirir, istemci kendi ekranında da gösterir), kredi, uridyum}
  POST /magaza/subscribe {lootId, category}  booster aboneliği aç/kapa (ShopItemBuyRequest action toggleSubscription)
  GET  /hangar?ship=<kimlik>  gemiler (favori, kayıtlı config), seçili geminin (yoksa etkin) iki config'i: gemi yuvaları, dronlar
                 (eşyaları, tasarım ve görünüm yuvası), P.E.T. (ad, seviye, yuvalar ve HEAT, yuva açma fiyatları); geminin tasarımları;
                 CPU'lar (aç/kapa, otomatik alımın cephanesi); envanterde hiçbir yere takılı olmayan eşyalar: takılabildiği yerler
                 (ship, drone, pet), yükseltme seviyesi, satış değeri; istasyonda mı
  POST /hangar/tasi {gemi, konfig, esya, yon: tak|cikar, hedef: ship|drone|pet, dron, kume: heat}  HangarShipMoveItemsRequest
  POST /hangar/etkin {ship}  HangarShipActivateShipRequest (oyundaki gibi yalnız istasyonda) -> {tamam, hata}
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
  POST /muzayede/hepsi {lots: [[tur, loot]]}  her lota (önde olunmayanlara) en düşük geçerli teklif -> {verilen, tutar, hatalar}
  POST /muzayede/anlik {tur, loot}  AuctionQuickBuyRequest -> {tamam, hata}
  POST /muzayede/oto {tur, loot, azami}  otomatik teklif kuralı (azami 0: kapalı; muzayede.oto)
  POST /muzayede/alarm {tur, loot, gecilince, dk}  alarm kuralı (ikisi de boşsa kalkar)
  GET  /muzayede/olaylar?last=<no>  bu numaradan sonraki olaylar (panelin bildirimleri)
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
    return {'credits': pl.get('credits', 0), 'uridium': pl.get('uridium', 0), 'in_station': in_station(s),
            'company': {1: 'mmo', 2: 'eic', 3: 'vru'}.get(pl.get('factionId'), 'eic')}     # gemi simgeleri şirkete göre


def shop(game):
    s = session(game)
    with s.packet_lock:
        by_category = {}
        for c in s.shop.lists:
            m = s.shop.shop_list(c)            # ('ShopItemListCommand', alanlar)
            if m and m[1]['itemList']:
                by_category[c] = m[1]['itemList']
        order = [p['category'] for p in next(iter(s.shop.lists.values()), {}).get('promptList', []) if p['category'] in by_category]
        return dict(wallet(s), categories=order + [c for c in by_category if c not in order], items=by_category)


def bot_name_log(game, b):
    """Panel bir botun adını değiştirdi (name_log.py): oyun açıkken hemen uygulanır (botlar, klanlar, bağlı oyuncuların rehberi)."""
    from bot import manager as MGR
    y = MGR.ACTIVE
    return {'done': True, 'changed': y.apply_name_log() if y is not None else 0}


def _bot(b):
    from bot import manager as MGR
    y = MGR.ACTIVE
    if y is None:
        raise Error(409, 'botlar açık değil')
    bot = next((x for x in y.bots if x.k['no'] == int(b.get('no') or 0)), None)
    roster_row = next((x for x in y.package.get('roster', []) if x['no'] == int(b.get('no') or 0)), None)
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
    value = b.get('changes') or {}
    with y.lock:
        bot.save()
        try:
            ED.apply(bot.k, roster_row, value, online=bot.online)
        except ED.EditError as e:
            return {'error': e.code, 'area': e.area}
        if 'mood' in value:
            bot.mood.d.update(bot.k['mood'])
        if any(a in value for a in ('ship', 'gear', 'ammunition')):
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
        return dict(wallet(s), done=False, error='shop_item_not_found')
    return dict(wallet(s), done=cmd.get('resultId') == 1, error=error_name(cmd.get('errorMessage')))


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
    ids = {l: int(i) for i, l in p.d['items'].items() if l in equipped}
    out = []
    for l in dict.fromkeys(equipped):
        if l in CIT.TOGGLES:
            out.append({'lootId': l, 'type': 'ackapa', 'on': CIT.toggled(p, l)})
        cfg = SHP.EX.X.get(l, {}).get('auto_pickup')
        if cfg and cfg['type'] in ('laser', 'rocket') and l in ids:
            pre = ('ammunition_laser_',) if cfg['type'] == 'laser' else ('ammunition_rocket_', 'ammunition_rocketlauncher_')
            out.append({'lootId': l, 'id': ids[l], 'type': 'ammunition', 'threshold': cfg['threshold'], 'count': cfg['count'],
                        'selected': p.d.get('auto_buy_ammo', {}).get(l),
                        'options': sorted(c for c in shop.catalog if c.startswith(pre) and shop.price(c))})
    return out


def hangar(game, q):
    s = session(game)
    p, shop = s.profile, s.shop
    with s.packet_lock:
        sid = str(q.get('ship') or '') if str(q.get('ship') or '') in p.d['ships'] else p.d['active_ship']
        ship = p.ship(sid)
        slots = [y for _p, y in SHP.SLOTS if shop.capacity(y, sid) > 0]
        places = p.item_places()
        configs = {}
        for cid in sorted(ship['configs']):
            cfg = p.config(cid, sid)
            configs[cid] = {y: {'capacity': shop.capacity(y, sid, cid),
                                  'items': [{'id': i, 'lootId': p.d['items'][str(i)]} for i in cfg.get(y, []) if str(i) in p.d['items']]}
                              for y in slots}
        item = lambda i: {'id': i, 'lootId': p.d['items'][str(i)]} if i and str(i) in p.d['items'] else None
        drones, pet = {}, {}
        for cid in sorted(ship['configs']):
            dcfg = p.drone_config(cid, sid)
            drones[cid] = [{'id': x['uid'], 'lootId': x['lootId'], 'capacity': SHP.DRONES.get(x['lootId'], {}).get('slot', 1),
                             'items': [item(i) for i in dcfg.get(str(x['uid']), []) if item(i)],
                             'design': item(p.drone_design_id(x, 'design', cid, sid)), 'appearance': item(p.drone_design_id(x, 'visual', cid, sid))}
                            for x in p.d['drones']]
            if shop.pet.owned:
                pc = shop.pet.config(cid, sid)
                pet[cid] = {y: {'capacity': shop.pet.open_slots(y), 'items': [item(i) for i in pc.get(y, []) if item(i)],
                                'price': shop.pet.slot_price(y) if y in PETM.PET['slot_prices'] else 0} for y in PETM.ALL_SLOTS}

        def targets(l):
            h = (['ship'] if SHP.slot_of(l) in slots else []) + (['drone'] if SHP.drone_ok(l) or l in SHP.DESIGNS else [])
            return h + (['pet'] if shop.pet.owned and PETM.slot_for(l) else [])
        inventory = []
        for i, l in p.d['items'].items():
            place = places.get(int(i))
            # items on another ship are hidden; items in a config of this ship stay listed for the other config (as in game)
            if (place and place[0] != sid) or l.startswith(('drone_', 'ship_')):          # dronlar ve gemiler eşya kaydında da durur
                continue
            sale = shop.sale_value(l) if not l.startswith(SHP.QF.PREFIX) else None
            if targets(l) or (sale and not place):
                inventory.append({'id': int(i), 'lootId': l, 'targets': targets(l), 'level': SHP.UPG.item_level(p, int(i)),
                                 'slot': SHP.slot_of(l) or PETM.slot_for(l) or ('design' if l in SHP.DESIGNS else 'other'),
                                 'selling': list(sale) if sale and not place else None, 'configs': sorted(place[1]) if place else []})
        ships = [{'id': k, 'lootId': g['lootId'], 'design': g.get('design'), 'active': k == p.d['active_ship'],
                    'favorite': bool(g.get('favorite')), 'registered': bool(g.get('saved_config'))} for k, g in p.d['ships'].items()]
        petd = shop.pet.d if shop.pet.owned else None
        return dict(wallet(s), ship=sid, active_config=str(ship['active_config']), ships=ships, slots=slots,
                    configs=configs, drones=drones, pet=pet or None, pet_slots=list(PETM.ALL_SLOTS),
                    pet_info={'name': petd.get('name'), 'level': petd.get('level'), 'rename_price': shop.pet.rename_price(),
                               'heat_unlocked': shop.pet.heat_lv() >= PETM.HEAT['slot_level']} if petd else None,
                    designs=shop.designs(sid), appearance=p.ship_look(sid), inventory=inventory, cpus=cpus(s),
                    in_station=in_station(s), portal_hangar=bool(SET.get('portal_hangar')))


def carry(game, b):
    s = session(game)
    sid = str(b.get('ship') or '')
    if sid not in s.profile.d['ships']:
        raise Error(400, 'ship')
    if not in_station(s):
        return {'done': False, 'error': 'station'}
    equip, target = b.get('direction') == 'equip', b.get('target') if b.get('target') in ('ship', 'drone', 'pet') else 'ship'
    f = {'items': [int(b.get('item') or 0)], 'source': 'inventory' if equip else target, 'destination': target if equip else 'inventory',
         'configId': int(b.get('config') or 1), 'hangarId': s.profile.ship(sid)['hangarId'], 'droneId': int(b.get('drone') or 0),
         'slotSet': 'default' if target == 'drone' else 'heat' if b.get('set') == 'heat' else ''}
    cmd = response(handle(s, 'HangarShipMoveItemsRequest', f), 'HangarShipMoveItemsCommand') or {}
    return {'done': cmd.get('result') == 1, 'error': error_name(cmd.get('errorMessage'))}


def active(game, b):
    s = session(game)
    cmd = response(handle(s, 'HangarShipActivateShipRequest', {'shipId': str(b.get('ship') or '')}), 'HangarShipActivateShipCommand') or {}
    return {'done': cmd.get('result') == 1, 'error': None if cmd.get('result') == 1 else error_name(cmd.get('errorMessage'))}


def design(game, b):
    s = session(game)
    if not in_station(s):
        return {'done': False, 'error': 'station'}
    f = {'shipId': str(b.get('ship') or ''), 'lootId': str(b.get('lootId') or '')}
    cmd = response(handle(s, 'HangarShipChangeShipModelRequest', f), 'HangarShipChangeShipModelCommand') or {}
    return {'done': cmd.get('resultId') == 1, 'error': error_name(cmd.get('errorMessage'))}


def result(outgoing, name):
    """Yanıt komutu -> {tamam, hata}: resultId ya da result 1 başarı; hata errorMessage ya da (yükleme penceresi) description."""
    cmd = response(outgoing, name) or {}
    ok = (cmd.get('resultId') if 'resultId' in cmd else cmd.get('result')) == 1
    return {'done': ok, 'error': None if ok else error_name(cmd.get('errorMessage') or cmd.get('description')) or 'eqt_error_generic'}


# işlem -> (istek, alanlar(b, profil), yanıt komutu); ISTASYON'dakiler oyunda yalnız istasyonda (donanım değişir)
OPS = {
    'clean_up': ('HangarShipClearConfigRequest', lambda b, p: {'wipe': 0, 'configId': int(b.get('config') or 1), 'shipId': str(b.get('ship'))},
                'HangarShipClearConfigCommand'),
    'save': ('HangarShipSaveConfigRequest', lambda b, p: {'shipId': str(b.get('ship'))}, 'HangarShipSaveConfigCommand'),
    'load': ('HangarShipLoadConfigRequest', lambda b, p: {'shipId': str(b.get('ship'))}, 'HangarShipLoadConfigCommand'),
    'import_action': ('HangarShipImportConfigRequest', lambda b, p: {'originShipId': str(b.get('ship')), 'targetShipId': str(b.get('target_ship'))},
              'HangarShipImportConfigCommand'),
    'favorite': ('HangarShipFavouriteRequest', lambda b, p: {'shipId': str(b.get('ship')), 'favourite': bool(b.get('favorite'))},
               'HangarShipFavouriteCommand'),
    'sell': ('HangarShipSellItemRequest', lambda b, p: {'itemList': [{'itemId': int(i), 'quantity': 1} for i in b.get('items') or []]},
            'HangarShipSellItemCommand'),
    'drone_sell': ('HangarShipSellDroneRequest', lambda b, p: {'droneId': int(b.get('drone') or 0)}, 'HangarShipSellDroneCommand'),
    'pet_ad': ('HangarShipRenamePetRequest', lambda b, p: {'name': str(b.get('name') or '')}, 'HangarShipRenamePetCommand'),
    'pet_yuva': ('HangarShipUnlockSlotRequest', lambda b, p: {'slotset': str(b.get('slot') or '')}, 'HangarShipUnlockSlotCommand'),
    'cpu_ammo': ('HangarShipAutoBuyCpuAmmoRequest', lambda b, p: {'itemId': int(b.get('item') or 0), 'ammoLootId': str(b.get('ammunition') or '')},
                    'HangarShipAutoBuyCpuAmmoCommand'),
}
STATION = ('clean_up', 'load', 'import_action', 'drone_sell')


def hangar_action(game, b):
    s = session(game)
    operation = b.get('operation')
    if operation == 'config':                   # kısayol çubuğunun config düğmesi gibi (eski metin isteği S|CFG; oyunda her yerde, beklemeli)
        n = str(int(b.get('config') or 1))
        once = s.profile.ship()['active_config']
        handle(s, 'LegacyModule', {'message': 'S|CFG|%s|%d' % (n, s.profile.user_id)})
        ok = str(s.profile.ship()['active_config']) == n
        return {'done': ok, 'error': None if ok else 'config_change_failed_time' if str(once) != n else None}
    if operation == 'cpu':                      # aç/kapa CPU'su: kısayol çubuğundaki öğesine tıklamak gibi
        l = str(b.get('lootId') or '')
        if l not in CIT.TOGGLES or getattr(s, 'world', None) is None:
            raise Error(400, 'cpu')
        once = CIT.toggled(s.profile, l)
        handle(s, 'MenuActionRequest', {'menuItemId': l, 'actionType': 0})
        return {'done': CIT.toggled(s.profile, l) != once, 'error': None}
    if operation not in OPS:
        raise Error(400, 'operation')
    if operation in STATION and not in_station(s):
        return {'done': False, 'error': 'station'}
    request, fields, reply_name = OPS[operation]
    return result(handle(s, request, fields(b, s.profile)), reply_name)


def subscriber(game, b):
    s = session(game)
    f = {'lootId': str(b.get('lootId') or ''), 'category': str(b.get('category') or ''), 'amount': 1, 'action': 'toggleSubscription',
         'buyCategory': '', 'level': 1, 'petName': ''}
    cmd = response(handle(s, 'ShopItemBuyRequest', f), 'ShopItemBuyCommand') or {}
    return dict(wallet(s), done=cmd.get('resultId') == 1, error=error_name(cmd.get('errorMessage')))


def skylab(game):
    s = session(game)
    skylab = s.skylab
    handle(s, 'SkylabActionRequest', {'construction': '', 'subaction': ''})       # biriken üretim, biten yükseltme ve taşıma
    with s.packet_lock:
        now, st = time.time(), skylab.st
        modules = []
        for k in SKY.ORDER:
            m, c = skylab.module(k), skylab.upgrade_cost(k)
            modules.append({'id': k, 'level': m['level'], 'maximum': SKY.MODULES[k]['maximum'], 'state': skylab.state(k),
                             'energy': skylab.energy(k), 'uretim': skylab.production(k),
                             'cost': dict(c, sure_sn=SET.duration(c['sure_sn'], 'skylab')) if c else None,     # panelin bekleme çarpanıyla
                             'remaining': max(0, int(m['upgrade'] - now)) if m.get('upgrade') else None, 'finish': skylab.finish_price(k, now),
                             'toggleable': k not in SKY.ALWAYS_ON, 'efficiency': skylab.efficiency(k) if k in SKY.COLLECTORS else None,
                             'robot': {'etkin': len(st['robots'].get(k, [])), 'in_storage': len(st['backup'].get(k, [])),
                                       'maximum': SKY.ROBOTS['maximum'], 'price': {t: skylab.robot_price(t) for t in ('1', '2')}}
                             if k in SKY.COLLECTORS else None})
        t = st.get('transport')
        return dict(wallet(s), modules=modules, energy={'used': skylab.consumption(), 'solar': skylab.solar()},
                    storage=[{'id': o, 'name': SKY.ORES[o][0], 'amount': skylab.amount(o), 'capacity': skylab.capacity(o)} for o in SKY.ORE_ORDER],
                    transport={'remaining': max(0, int(t['end_time'] - now)), 'cargo': t['cargo']} if t else None,
                    instant_price=SET.price('service_price', SKY.TRANSPORT['fast_uridium'], 'skylab'))


SKYLAB_ACTIONS = ('upgrade', 'instantUpgrade', 'instantFinishUpgrade', 'abortUpgrade', 'setActive', 'setInactive', 'startTransport')


def skylab_action(game, b):
    s = session(game)
    if b.get('operation') not in SKYLAB_ACTIONS:
        raise Error(400, 'operation')
    f = {'construction': str(b.get('module') or ''), 'subaction': b['operation'], 'transportMode': str(b.get('mod') or '')}
    for o, n in (b.get('amounts') or {}).items():
        if o in SKY.ORES:
            f['count' + SKY.ORES[o][0]] = max(0, int(n or 0))
    s.skylab.last_operation = ([], [])
    handle(s, 'SkylabActionRequest', f)
    name = lambda c: error_name(c) if isinstance(c, dict) else KEY_NAMES.get(c, str(c))
    err, ok = s.skylab.last_operation
    return {'done': not err, 'errors': [name(c) for c in err], 'achievements': [name(c) for c in ok]}


def robot(game, b):
    s = session(game)
    if b.get('module') not in SKY.COLLECTORS or str(b.get('tip')) not in ('1', '2'):
        raise Error(400, 'robot')
    s.skylab.last_operation = ([], [])
    handle(s, 'SkylabPurchaseRobotRequest', {'construction': b['module'], 'robotType': int(b['tip'])})
    err = s.skylab.last_operation[0]
    return {'done': not err, 'errors': [KEY_NAMES.get(c, str(c)) for c in err]}


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
            d, key = auc.data(lot, now), '%s|%s' % (lot['type'], lot['loot'])
            lots.append({'type': lot['type'], 'loot': lot['loot'], 'group': lot['group'], 'count': lot['count'], 'instant': bool(lot['instant'] and lot['price']),
                           'price': auc.unit_price(lot), 'highest': d['highestBid'], 'highest_name': d['highestBidderName'], 'mine': d['myBid'],
                           'leading': auc.top(lot, now)[1], 'next': auc.next_bid(lot, now), 'auto': auc.d['auto'].get(key),
                           'alarm': auc.d['alarms'].get(key)})
        return dict(wallet(s), lots=lots, remaining={k: MZ.period_end(k, now) - int(now) for k in MZ.SPAN}, increase=MZ.D['increase'],
                    en_az=MZ.D['min_bid'], history=auc.history(now)[:30], events=auc.d['events'][:30], rival=MZ.rival_level(),
                    uid=s.profile.user_id)


def auction_bid(s, kind, loot, price):
    cmd = response(handle(s, 'AuctionBidRequest', {'type': kind, 'lootId': loot, 'price': int(price)}), 'AuctionBidCommand') or {}
    return {'done': bool(cmd.get('success')), 'error': None if cmd.get('success') else error_name(cmd.get('stack'))}


def bid(game, b):
    return dict(auction_bid(session(game), str(b.get('type')), str(b.get('loot')), int(b.get('price') or 0)))


def all_(game, b):
    """Hepsine katıl: önde olunmayan her lota en düşük geçerli teklif (kredi yetene dek)."""
    s = session(game)
    auc, given, amount, errors = s.social.auction, 0, 0, {}
    for kind, loot in b.get('lots') or []:
        lot = MZ.LOTS.get((str(kind), str(loot)))
        now = time.time()
        if not lot or auc.top(lot, now)[1]:
            continue
        price = auc.next_bid(lot, now)
        r = auction_bid(s, lot['type'], lot['loot'], price)
        if r['done']:
            given, amount = given + 1, amount + price
        else:
            errors[r['error']] = errors.get(r['error'], 0) + 1
    return dict(wallet(s), given=given, amount=amount, errors=errors)


def instant(game, b):
    s = session(game)
    cmd = response(handle(s, 'AuctionQuickBuyRequest', {'type': str(b.get('type')), 'lootId': str(b.get('loot'))}), 'AuctionQuickBuyCommand') or {}
    return {'done': bool(cmd.get('success')), 'error': None if cmd.get('success') else error_name(cmd.get('stack'))}


def rule(game, b, area):
    """Otomatik teklif ya da alarm kuralı (profilde; muzayede.oto tick'te uygular)."""
    s = session(game)
    lot = MZ.LOTS.get((str(b.get('type')), str(b.get('loot'))))
    if not lot:
        raise Error(400, 'lot')
    key, auc = '%s|%s' % (lot['type'], lot['loot']), s.social.auction
    if area == 'auto':
        maximum = max(0, int(b.get('maximum') or 0))
        new_ = {'maximum': maximum} if maximum >= MZ.D['min_bid'] else None
    else:
        new_ = {'when_outbid': bool(b.get('when_outbid')), 'min': max(0, min(10080, int(b.get('min') or 0)))}
        new_ = new_ if new_['when_outbid'] or new_['min'] else None
    with s.profile.lock:
        if new_:
            auc.d[area][key] = new_
        else:
            auc.d[area].pop(key, None)
        s.profile.dirty = True
    return {'done': True}


def events(game, q):
    s = session(game)
    last = int(q.get('last') or 0)
    return {'events': [o for o in s.social.auction.d['events'] if o['no'] > last]}


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
                return self._reply(403, {'error': 'anahtar'})
            try:
                return self._reply(200, fn())
            except Error as e:
                return self._reply(e.code, {'error': str(e)})
            except Exception as e:
                log('panel kanalı: %s hatası: %r' % (self.path, e))
                return self._reply(500, {'error': repr(e)})

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
            self._reply(404, {'error': 'none'})

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            try:
                b = json.loads(self.rfile.read(n).decode('utf8') or '{}') if n else {}
            except ValueError:
                return self._reply(400, {'error': 'json'})
            paths = {'/magaza/al': buy, '/magaza/subscribe': subscriber, '/hangar/tasi': carry, '/hangar/etkin': active, '/hangar/tasarim': design,
                      '/hangar/islem': hangar_action,
                      '/skylab/islem': skylab_action, '/skylab/robot': robot, '/muzayede/teklif': bid, '/muzayede/hepsi': all_,
                      '/muzayede/anlik': instant, '/muzayede/oto': lambda g, b: rule(g, b, 'auto'),
                      '/muzayede/alarm': lambda g, b: rule(g, b, 'alarms'), '/bot/ad_kaydi': bot_name_log,
                      '/bot/detay': bot_detail, '/bot/edit': edit_bot}
            if self.path in paths and isinstance(b, dict):
                return self._handle(lambda: paths[self.path](game, b))
            self._reply(404, {'error': 'none'})

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
