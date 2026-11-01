"""Ship warp window (roadmap stage 10; the client's ShipWarp* messages): brings another ship to where you are and makes it the
active ship (changing ships without going to the hangar).

  UIButtonTriggerRequest 'ship_warp'  -> ShipWarpWindowCommand {jumpVoucherCount, uridium, isNearSpacestation, ships}; if there is no other favorite
                                         ship, as in the save "msg_swnoactiveships" + ShipWarpNotAllowedCommand
  ShipWarpRequest {shipId}             -> countdown ("msg_swcountdown_p", %SECONDS%), then the ship changes: ShipWarpCompletedCommand
                                         {currentShipLootId} and the client reloads the map with the new ship (like a change in the hangar)
Cost (the client's texts): free at the station ("desc_shipwarp_costs_spacestation"); outside, one jump voucher
(resource_jumpvoucher, same as AJP-01's) or uridium if there is no voucher. No warping in combat ("msg_swnotallowed_fight"), on Galaxy Gate and event
maps, in the Cubikon Graveyard and LoW ("msg_swnotallowed_map"); if attacked during the countdown the warp is canceled
("msg_swblocked", ShipWarpCanceledCommand).
Adaptations (since no source gives them): the uridium price (1,000 U like AJP-01's jump without a voucher), countdown 5 s.
"""
import settings as SET
import map_links as H
from legacy_protocol import legacy, stm

VOUCHER = 'resource_jumpvoucher'
URIDIUM = 200            # official Turkish forum 127436 (Gemi Değiştirme): "1 atlama kuponu veya 200 Uridium" (1 jump voucher or 200 Uridium)
COUNTDOWN = 10          # the same FAQ: "10 saniye süren geri sayım" (a 10-second countdown)
REQUESTS = {'ShipWarpRequest'}


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Warp:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None
        self.busy = None                  # warp in progress: (shipId, payment)

    def allowed_map(self, map_id):
        return map_id in H.NAMES and map_id not in H.SPECIAL

    def ships(self):
        """Ships that can be warped to: inactive favorites (the client's window: "You can only Warp ships that are marked as your
        favorites!"; favorite is set in the hangar with HangarShipFavouriteRequest)."""
        act = str(self.p.d['active_ship'])
        return [sid for sid in sorted(self.p.d['ships'], key=int) if sid != act and self.p.d['ships'][sid].get('favorite')]

    def window(self, w):
        """Window opened (UIButtonTriggerRequest 'ship_warp')."""
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
                             mapId=(s.get('position') or {}).get('mapId', home)))      # the map where the ship was left (shop.activate)
        return [('ShipWarpWindowCommand', {'jumpVoucherCount': self.p.resource(VOUCHER), 'uridium': int(self.p.d['pilot'].get('uridium', 0)),
                                           'isNearSpacestation': near, 'ships': ships})]

    def price(self):
        """Uridium cost: the panel's service price, a discount for Premium (forum 127436: "VIP kullanıcılar için küçük bir indirim" - a small discount for VIP users)."""
        import shop as SHP
        k = 1 - SHP.ITEMS['shop_discount']['premium_rate'] if self.p.premium else 1
        return int(round(SET.price('service_price', URIDIUM, 'warp') * k))

    def refuse(self, key):
        self.log('   warp refused: %s' % key)
        return [stm(key), ('ShipWarpNotAllowedCommand', {})]

    def warp(self, f, w, now, done):
        """ShipWarpRequest. done(messages, ship_changed): the completion the session calls when the countdown ends (w.later)."""
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
        self.log('   warp started: shipId %s (%s)' % (sid, pay or 'free'))
        w.later(COUNTDOWN, lambda: done(*self.finish(w)))
        n = int(COUNTDOWN)
        for k in range(1, n):                        # the countdown ticks every second; the last second is "Warp finished in 1 second"
            w.later(k, lambda left=n - k: self.busy and self.busy[2] == now and w.send([self.countdown(left)]))
        return [('ShipWarpWindowCloseCommand', {}), stm('msg_swstarted'), self.countdown(COUNTDOWN)]

    def countdown(self, left):
        return stm('msg_swcountdown_s') if left == 1 else stm('msg_swcountdown_p', '%SECONDS%', left)

    def finish(self, w):
        """Countdown over -> (messages, did the ship change)."""
        sid, pay, t0, (x0, y0) = self.busy
        self.busy = None
        x, y = w.hero_pos()
        if w.last_combat > t0 or abs(x - x0) + abs(y - y0) > 5:     # forum 127436: also cancelled if the ship moves
            self.log('   warp canceled: %s' % ('attack' if w.last_combat > t0 else 'movement'))
            return [stm('msg_swblocked'), ('ShipWarpCanceledCommand', {})], False
        import inventory as INV
        if INV.spend(self.p, pay, 'balance_ship_warp_completed') is None:
            return [stm('ttip_currency_missing', '%CURRENCY%', 'Uridium'), ('ShipWarpCanceledCommand', {})], False
        _, changed = self.m.activate({'shipId': sid}, in_station=True)
        if not changed:
            return [('ShipWarpCanceledCommand', {})], False
        if getattr(w, 'items', None):                  # forum 127436: "değiştirme tamamlandığında kamuflaj devre dışı kalır" (camouflage is disabled when the change completes)
            w.items.reveal()
        import ranks as RT
        # logbook: the client (ReturnLogBookInfoText) splits infoText by "_" and recognizes "ship_warp_completed_<map>", the text is
        # history_ship_warp_completed; %SHIP_NAME% is the name of the ship in info (items_<lootId>_fullname), %MAP_NAME% the map's name. It does not
        # look at args: "history_ship_warp_completed" + the args row appeared with its placeholders (live round 2)
        RT.note(self.p, 'ship_warp_completed_%s' % w.map_id, self.p.ship()['lootId'])
        msgs = [('ShipWarpCompletedCommand', {'currentShipLootId': self.p.ship()['lootId']})]
        msgs += INV.update_msgs(self.m, self.p, list(pay)) if pay else []
        return msgs + [self.m.ships_cmd()], True
