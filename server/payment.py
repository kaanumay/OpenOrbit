"""Payment buttons -> the in-game shop (user 2026-10-18).

The client's "Buy now" / "Şimdi al" buttons (Battle Pass, Voyagers' Ascent and Trinity Trials VIP, Season Pass, Monthly Deluxe, Vortex
of Greed Vanguard, Stellar Pathfinder ...) go not to the game server but to the web payment API: JavascriptHelper.OpenWebUrl("PAY_TYPE",
<type>) -> PostUrl: Settings.PaymentUrl (the login data's host + /unityApi/payment.php) is changed to "https://" and POSTed. Which
button it is is in the encrypted request; the client is not patched (it would be needed again for every version, CANLI_TEST N23). But the request connects to 127.0.0.1:443:
the server listens there, closes the connection (the client writes "Cannot connect" and does nothing else) and answers the click in the game: the shop
opens on the Extras tab and the product's name and price are written on screen. The product is found from the last window the player opened (UIButtonTriggerRequest,
UIWindowUpdateRequest maximized); opening the shop is harmless, so even if the guess is wrong nothing is lost.
The command that opens the shop is ExpeditionBuyTicketCommand {result False}: the client's handler opens the shop on Extras ("extras,
resource_key_access-dse"; this also happens when there is not enough uridium for an Echoes ticket). In the shop's product list paid products are bought with uridium (shop.py).
Since the server does not send MileageMarketBuyCommand, VIPMerchantExchangeBuyCommand, ReturneeLoginBundleBuyCommand, UridiumBankClaimCommand
(the client opens a payment request with these too), every connection to 443 is the player pressing a payment button; the coupon code and image
upload also go to 443, and they are told apart by the last opened window (CEVRIMDISI).
With several clients (multiple clients, friend server) the client that clicked is found by the connecting process's id (connecting_pid).
"""
import os, socket, threading, time

import platform_compat as CP

PORT = 443
INTERVAL_SEC = 2.0              # retries of the same click (TLS) count as one
WINDOW_SEC = 600             # if the last opened window is older than this the product is not guessed

# window (menu item) -> (product name, lootIds in the shop: the price is that of the first one sold)
PRODUCTS = {
    'battle_pass': ('Battle Pass', ['resource_battle-pass']),
    'quests': ('Battle Pass', ['resource_battle-pass']),
    'voyagers': ("Voyagers' Ascent VIP Badge", ['package_event-deal-voyagers-vip-badge']),
    'trinityTrials': ('Trinity Trials VIP', ['package_event-deal-trinity-vip-discount']),
    'seasonPass': ('Gold Pass (Season Pass)', ['package_event-deal-goldpass-premium', 'resource_gold-pass']),
    'monthly_deluxe': ('Monthly Deluxe', ['package_event-deal-month-deluxe']),
    'strikeAndExit': ('Vanguard (Vortex of Greed)', ['package_event-deal-vog-vanguard']),
    'stellar_pathfinder': ('Stellar Pathfinder packages', ['package_event-deal-stellar2022-1']),
    'mileageMarket': ('Mileage Packs', []),
    'vipMerchantExchange': ('VIP Merchant Packs', []),
    'returnee_login': ('Returnee Bundles', []),
    'recallBattlePass': ('Return VIP Badge', ['package_event-deal-return-pass-vip-badge', 'package_event-deal-return-vip-special']),
}
GENERAL = 'Payment pages are offline: packages are sold in the Shop > Extras for uridium.'
# non-payment requests going to 443 (the path inside TLS is not visible): coupon code (UIVouchersSystem -> JavascriptHelper.PostVoucherUrl),
# avatar and clan logo upload (UploadHelper -> /unityApi/upload.php). If the last opened window is one of these the shop does not open, this text is written
OFFLINE = {
    'vouchers': 'Voucher codes cannot be redeemed offline.',
    'pilotSheet': 'Image upload is not available offline.',
    'clan': 'Image upload is not available offline.',
}


def open_shop():
    """The command that makes the shop open on the Extras tab (client: ExpeditionBuyTicketCommandHandler, result False)."""
    return ('ExpeditionBuyTicketCommand', dict(result=False, stack={'_': 'BaseStackCommand', 'type': 0, 'enumBaseKey': 0,
                                                                    'stringBasekey': '', 'argsList': []}))


def money(cur, n):
    return '{:,} {}'.format(int(round(n)), 'U' if cur == 'uridium' else 'C')


def product(item, shop):
    """The product the window sells now -> (lootId, (currency, price)) or None."""
    for loot in (PRODUCTS.get(item) or ('', []))[1]:
        pr = shop.buy_price(loot) if shop else None
        if pr and shop.contents(loot, 1) is not None and shop.gate_ok(loot):
            return loot, pr
    return None


def text(item, shop):
    """On-screen text: the product's name and its price in the shop; says so if the product is not sold now (outside the event); generic if the window is unknown."""
    row = PRODUCTS.get(item)
    if not row:
        return GENERAL
    name, loots = row
    got = product(item, shop)
    if got:
        return '%s: Shop > Extras, %s.' % (name, money(*got[1]))
    if loots:
        return '%s: not on sale right now.' % name
    return '%s: Shop > Extras (uridium).' % name


class Windows:
    """The windows the player opened last (for guessing the product)."""

    def __init__(self):
        self.last = {}                # menu item -> opening time

    def opened(self, item, now=None):
        if item:
            self.last[item] = time.time() if now is None else now

    def guess(self, now=None):
        """The last opened window whose product is known (within WINDOW_SEC) or None."""
        now = time.time() if now is None else now
        rows = [(t, i) for i, t in self.last.items() if i in PRODUCTS and now - t <= WINDOW_SEC]
        return max(rows)[1] if rows else None

    def offline(self, now=None):
        """The text of the last opened window if it is the window of a non-payment HTTPS request (CEVRIMDISI), otherwise None."""
        now = time.time() if now is None else now
        rows = [(t, i) for i, t in self.last.items() if now - t <= WINDOW_SEC]
        return OFFLINE.get(max(rows)[1]) if rows else None


def redirect(shop, item):
    """A payment button was pressed -> the command that opens the shop + on-screen text. When the shop opens the client asks for the Extras list: the product is put
    at the head of the list, the client opens it selected."""
    import galaxy_gates as GALAXY
    got = product(item, shop)
    if shop and hasattr(shop, 'feature'):
        shop.feature('extras', got[0] if got else None)
    return [open_shop(), GALAXY.screen(text(item, shop))]


def connecting_pid(addr, port):
    """The id of the process of a connection coming from this computer (the far end addr, the port at this end): from the Windows TCP table
    (GetExtendedTcpTable, TCP_TABLE_OWNER_PID_CONNECTIONS); None if not found."""
    if os.name != 'nt' or not addr:
        return None
    import ctypes
    from ctypes import wintypes
    fn = ctypes.windll.iphlpapi.GetExtendedTcpTable
    size = wintypes.DWORD(0)
    fn(None, ctypes.byref(size), False, 2, 4, 0)                      # AF_INET, TCP_TABLE_OWNER_PID_CONNECTIONS
    for _ in range(3):
        buf = ctypes.create_string_buffer(size.value + 4096)
        size = wintypes.DWORD(len(buf))
        if fn(buf, ctypes.byref(size), False, 2, 4, 0) == 0:
            break
    else:
        return None
    n = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(wintypes.DWORD * 6))   # state, local address/port, remote address/port, pid
    for i in range(n):
        r = rows[i]
        if socket.ntohs(r[2] & 0xFFFF) == addr[1] and socket.ntohs(r[4] & 0xFFFF) == port:
            return r[5]
    return None


class Listener:
    """127.0.0.1:443: when the client's payment request (TLS) connects on_click(address) is called and the connection is closed (retries of the same
    click count as one). on_click is called while the connection is open: the clicking client's process is visible in the TCP table (connecting_pid). On macOS
    0.0.0.0:443, only connections coming from this computer (platform_compat.listen_address)."""

    def __init__(self, on_click, log=print, port=PORT):
        self.on_click, self.log, self.port = on_click, log, port
        self.last = 0.0
        self.sock = None
        self.filtered = False

    def start(self):
        address, self.filtered = CP.listen_address('127.0.0.1', self.port)
        try:
            s = socket.socket()
            s.bind((address, self.port))
            s.listen(5)
        except OSError as e:
            self.log('   payment buttons: could not listen on %d (%s); the buttons will not open the shop' % (self.port, e))
            return None
        self.sock = s
        threading.Thread(target=self.serve, daemon=True).start()
        return self

    def serve(self):
        while True:
            try:
                c, addr = self.sock.accept()
            except OSError:
                return
            if self.filtered and not CP.is_local(addr[0]):
                c.close()
                continue
            now = time.time()
            if now - self.last >= INTERVAL_SEC:
                self.last = now
                try:
                    self.on_click(addr)
                except Exception as e:                  # noqa: BLE001 (so the listener does not die)
                    self.log('   payment button error: %s' % e)
            try:
                c.close()
            except OSError:
                pass

    def stop(self):
        if self.sock:
            self.sock.close()
