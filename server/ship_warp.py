"""Gemi ışınlama penceresi (yol haritası Aşama 10; istemcinin ShipWarp* mesajları): başka bir gemiyi bulunduğun yere getirip
etkin gemi yapar (hangara gitmeden gemi değiştirme).

  UIButtonTriggerRequest 'ship_warp'  -> ShipWarpWindowCommand {jumpVoucherCount, uridium, isNearSpacestation, ships}; başka favori
                                         gemi yoksa kayıttaki gibi "msg_swnoactiveships" + ShipWarpNotAllowedCommand
  ShipWarpRequest {shipId}             -> geri sayım ("msg_swcountdown_p", %SECONDS%), sonra gemi değişir: ShipWarpCompletedCommand
                                         {currentShipLootId} ve istemci haritayı yeni gemiyle yeniden yükler (hangardaki değişim gibi)
Ücret (istemcinin metinleri): istasyonda ücretsiz ("desc_shipwarp_costs_spacestation"); dışarıda bir atlama kuponu
(resource_jumpvoucher, AJP-01'inkiyle aynı) ya da kupon yoksa uridyum. Savaşta ("msg_swnotallowed_fight"), Galaksi Kapısı ve etkinlik
haritalarında, Cubikon Mezarlığı ve LoW'da ("msg_swnotallowed_map") ışınlanılmaz; geri sayımda saldırıya uğrarsa ışınlama iptal
("msg_swblocked", ShipWarpCanceledCommand).
Uyarlamalar (kaynak vermediği için): uridyum fiyatı (AJP-01'in kuponsuz atlaması gibi 1.000 U), geri sayım 5 sn.
"""
import settings as SET
import map_links as H
from legacy_protocol import legacy, stm

VOUCHER = 'resource_jumpvoucher'
URIDIUM = 200            # resmî Türk forumu 127436 (Gemi Değiştirme): "1 atlama kuponu veya 200 Uridium"
COUNTDOWN = 10          # aynı SSS: "10 saniye süren geri sayım"
REQUESTS = {'ShipWarpRequest'}


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Warp:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None
        self.busy = None                  # süren ışınlama: (shipId, ödeme)

    def allowed_map(self, map_id):
        return map_id in H.NAMES and map_id not in H.SPECIAL

    def ships(self):
        """Işınlanabilecek gemiler: etkin olmayan favoriler (istemcinin penceresi: "You can only Warp ships that are marked as your
        favorites!"; favori hangarda HangarShipFavouriteRequest)."""
        act = str(self.p.d['active_ship'])
        return [sid for sid in sorted(self.p.d['ships'], key=int) if sid != act and self.p.d['ships'][sid].get('favorite')]

    def window(self, w):
        """Pencere açıldı (UIButtonTriggerRequest 'ship_warp')."""
        sids = self.ships()
        if not sids:
            return [legacy('0|A|STM|msg_swnoactiveships'), ('ShipWarpNotAllowedCommand', {})]
        home = self.p.d['position'].get('mapId', 1)
        near = bool(w and w.in_station())
        pay = 0 if near else self.price()
        ships = []
        for sid in sids:
            s = self.p.ship(sid)
            ships.append(mod('ShipWarpModule', shipId=int(sid), typeId=s['lootId'], shipDesignName=s.get('design') or '',
                             uridiumPrice=pay, voucherPrice=0 if near else 1, hangarId=int(sid), hangarName='',
                             mapId=(s.get('position') or {}).get('mapId', home)))      # geminin bırakıldığı harita (magaza.activate)
        return [('ShipWarpWindowCommand', {'jumpVoucherCount': self.p.resource(VOUCHER), 'uridium': int(self.p.d['pilot'].get('uridium', 0)),
                                           'isNearSpacestation': near, 'ships': ships})]

    def price(self):
        """Uridyum bedeli: panelin hizmet fiyatı, Premium'a indirim (forum 127436: "VIP kullanıcılar için küçük bir indirim")."""
        import shop as SHP
        k = 1 - SHP.ITEMS['shop_discount']['premium_rate'] if self.p.premium else 1
        return int(round(SET.price('service_price', URIDIUM, 'warp') * k))

    def refuse(self, key):
        self.log('   ışınlama yok: %s' % key)
        return [stm(key), ('ShipWarpNotAllowedCommand', {})]

    def warp(self, f, w, now, done):
        """ShipWarpRequest. done(mesajlar, gemi_değişti): geri sayım bitince oturumun çağırdığı tamamlama (w.later)."""
        sid = str(f.get('shipId'))
        if sid not in self.ships():
            return self.refuse('msg_swnoactiveships')
        if self.busy:
            return []
        if not w or not self.allowed_map(self.p.d['position'].get('mapId', 0)):
            return self.refuse('msg_swnotallowed_map')
        import shop as SHP
        if now - w.last_combat < SHP.ITEMS['out_of_combat_sec']:
            return self.refuse('msg_swnotallowed_fight')
        if w.in_station():
            pay = {}
        elif self.p.resource(VOUCHER):
            pay = {VOUCHER: 1}
        else:
            pay = {'currency_uridium': self.price()}
        import inventory as INV
        if INV.missing(self.p, pay):
            return [stm('ttip_currency_missing', '%CURRENCY%', 'Uridium'), ('ShipWarpNotAllowedCommand', {})]
        self.busy = (sid, pay, now, w.hero_pos(now))
        self.log('   ışınlama başladı: shipId %s (%s)' % (sid, pay or 'ücretsiz'))
        w.later(COUNTDOWN, lambda: done(*self.finish(w)))
        n = int(COUNTDOWN)
        for k in range(1, n):                        # geri sayım saniyede bir; son saniye "Warp finished in 1 second"
            w.later(k, lambda left=n - k: self.busy and self.busy[2] == now and w.send([self.countdown(left)]))
        return [('ShipWarpWindowCloseCommand', {}), stm('msg_swstarted'), self.countdown(COUNTDOWN)]

    def countdown(self, left):
        return stm('msg_swcountdown_s') if left == 1 else stm('msg_swcountdown_p', '%SECONDS%', left)

    def finish(self, w):
        """Geri sayım bitti -> (mesajlar, gemi değişti mi)."""
        sid, pay, t0, (x0, y0) = self.busy
        self.busy = None
        x, y = w.hero_pos()
        if w.last_combat > t0 or abs(x - x0) + abs(y - y0) > 5:     # forum 127436: hareket edilirse de iptal
            self.log('   ışınlama iptal: %s' % ('saldırı' if w.last_combat > t0 else 'movement'))
            return [stm('msg_swblocked'), ('ShipWarpCanceledCommand', {})], False
        import inventory as INV
        if INV.spend(self.p, pay, 'balance_ship_warp_completed') is None:
            return [stm('ttip_currency_missing', '%CURRENCY%', 'Uridium'), ('ShipWarpCanceledCommand', {})], False
        _, changed = self.m.activate({'shipId': sid}, in_station=True)
        if not changed:
            return [('ShipWarpCanceledCommand', {})], False
        if getattr(w, 'items', None):                  # forum 127436: "değiştirme tamamlandığında kamuflaj devre dışı kalır"
            w.items.reveal()
        import ranks as RT
        # seyir defteri: istemci (ReturnLogBookInfoText) infoText'i "_" ile bölüp "ship_warp_completed_<harita>"yı tanıyor, metni
        # history_ship_warp_completed; %SHIP_NAME% info'daki geminin adı (items_<lootId>_fullname), %MAP_NAME% haritanın adı. args'a
        # bakmıyor: "history_ship_warp_completed" + args satırı yer tutucularıyla görünüyordu (canlı tur 2)
        RT.note(self.p, 'ship_warp_completed_%s' % w.map_id, self.p.ship()['lootId'])
        msgs = [('ShipWarpCompletedCommand', {'currentShipLootId': self.p.ship()['lootId']})]
        msgs += INV.update_msgs(self.m, self.p, list(pay)) if pay else []
        return msgs + [self.m.ships_cmd()], True
