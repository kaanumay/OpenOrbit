"""Ödeme düğmeleri -> oyundaki mağaza (kullanıcı 2026-10-18).

İstemcinin "Buy now" / "Şimdi al" düğmeleri (Battle Pass, Voyagers' Ascent ve Trinity Trials VIP, Season Pass, Monthly Deluxe, Vortex
of Greed Vanguard, Stellar Pathfinder …) oyun sunucusuna değil web ödeme API'sine gidiyor: JavascriptHelper.OpenWebUrl("PAY_TYPE",
<tür>) -> PostUrl: Settings.PaymentUrl (giriş verisinin host'u + /unityApi/payment.php) "https://"ye çevrilip POST ediliyor. Hangi
düğme olduğu şifreli istekte; istemci yamalanmaz (her sürümde yeniden gerekirdi, CANLI_TEST N23). Ama istek 127.0.0.1:443'e bağlanıyor:
sunucu orayı dinler, bağlantıyı kapatır (istemci "Cannot connect" yazar, başka bir şey yapmaz) ve tıklamayı oyunda karşılar: mağaza
Extras sekmesinde açılır ve ürünün adı ile fiyatı ekranda yazılır. Ürün, oyuncunun son açtığı pencereden (UIButtonTriggerRequest,
UIWindowUpdateRequest maximized) bulunur; mağazayı açmak zararsız olduğu için tahmin yanlış olsa da bir şey kaybolmaz.
Mağazayı açan komut ExpeditionBuyTicketCommand {result False}: istemcinin işleyicisi mağazayı Extras'ta açıyor ("extras,
resource_key_access-dse"; Echoes biletine uridyum yetmeyince de bu). Mağazanın ürün listesinde ödemeli ürünler uridyumla (shop.py).
Sunucu MileageMarketBuyCommand, VIPMerchantExchangeBuyCommand, ReturneeLoginBundleBuyCommand, UridiumBankClaimCommand göndermediği için
(istemci bunlarla da ödeme isteği açıyor) 443'e gelen her bağlantı oyuncunun bir ödeme düğmesine basmasıdır; kupon kodu ve resim
yükleme de 443'e gidiyor, onlar son açılan pencereden ayrılır (CEVRIMDISI).
Birden çok istemcide (çoklu istemci, arkadaş sunucusu) tıklayan istemci, bağlanan sürecin kimliğiyle bulunur (baglanan_pid).
"""
import os, socket, threading, time

import platform_compat as CP

PORT = 443
INTERVAL_SEC = 2.0              # aynı tıklamanın yeniden denemeleri (TLS) bir sayılır
WINDOW_SEC = 600             # son açılan pencere bu kadar eskiyse ürün tahmin edilmez

# pencere (menü öğesi) -> (ürün adı, mağazadaki lootId'ler: fiyatı ilk satılanın)
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
# 443'e giden ödeme dışı istekler (TLS içindeki yol görünmez): kupon kodu (UIVouchersSystem -> JavascriptHelper.PostVoucherUrl),
# avatar ve klan logosu yükleme (UploadHelper -> /unityApi/upload.php). Son açılan pencere bunlardansa mağaza açılmaz, bu metin yazılır
OFFLINE = {
    'vouchers': 'Voucher codes cannot be redeemed offline.',
    'pilotSheet': 'Image upload is not available offline.',
    'clan': 'Image upload is not available offline.',
}


def open_shop():
    """Mağazayı Extras sekmesinde açtıran komut (istemci: ExpeditionBuyTicketCommandHandler, result False)."""
    return ('ExpeditionBuyTicketCommand', dict(result=False, stack={'_': 'BaseStackCommand', 'type': 0, 'enumBaseKey': 0,
                                                                    'stringBasekey': '', 'argsList': []}))


def money(cur, n):
    return '{:,} {}'.format(int(round(n)), 'U' if cur == 'uridium' else 'C')


def product(item, shop):
    """Pencerenin şimdi satılan ürünü -> (lootId, (para, fiyat)) ya da None."""
    for loot in (PRODUCTS.get(item) or ('', []))[1]:
        pr = shop.buy_price(loot) if shop else None
        if pr and shop.contents(loot, 1) is not None and shop.gate_ok(loot):
            return loot, pr
    return None


def text(item, shop):
    """Ekran metni: ürünün adı ve mağazadaki fiyatı; ürünü şimdi satılmıyorsa (etkinlik dışı) söyler; pencere bilinmiyorsa genel."""
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
    """Oyuncunun son açtığı pencereler (ürün tahmini için)."""

    def __init__(self):
        self.last = {}                # menü öğesi -> açılış zamanı

    def opened(self, item, now=None):
        if item:
            self.last[item] = time.time() if now is None else now

    def guess(self, now=None):
        """Son açılan, ürünü bilinen pencere (PENCERE_SN içinde) ya da None."""
        now = time.time() if now is None else now
        rows = [(t, i) for i, t in self.last.items() if i in PRODUCTS and now - t <= WINDOW_SEC]
        return max(rows)[1] if rows else None

    def offline(self, now=None):
        """Son açılan pencere ödeme dışı bir HTTPS isteğinin penceresiyse (CEVRIMDISI) onun metni, yoksa None."""
        now = time.time() if now is None else now
        rows = [(t, i) for i, t in self.last.items() if now - t <= WINDOW_SEC]
        return OFFLINE.get(max(rows)[1]) if rows else None


def redirect(shop, item):
    """Ödeme düğmesine basıldı -> mağazayı açan komut + ekran metni. Mağaza açılınca istemci Extras listesini istiyor: ürün listenin
    başına alınır, istemci onu seçili açar."""
    import galaxy_gates as KAPI
    got = product(item, shop)
    if shop and hasattr(shop, 'feature'):
        shop.feature('extras', got[0] if got else None)
    return [open_shop(), KAPI.screen(text(item, shop))]


def connecting_pid(addr, port):
    """Bu bilgisayardan gelen bağlantının (karşı ucu addr, bu uçtaki port) sürecinin kimliği: Windows TCP tablosundan
    (GetExtendedTcpTable, TCP_TABLE_OWNER_PID_CONNECTIONS); bulunamazsa None."""
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
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(wintypes.DWORD * 6))   # durum, yerel adres/port, uzak adres/port, pid
    for i in range(n):
        r = rows[i]
        if socket.ntohs(r[2] & 0xFFFF) == addr[1] and socket.ntohs(r[4] & 0xFFFF) == port:
            return r[5]
    return None


class Listener:
    """127.0.0.1:443: istemcinin ödeme isteği (TLS) bağlanınca on_click(adres) çağrılır, bağlantı kapatılır (aynı tıklamanın
    denemeleri bir). on_click bağlantı açıkken çağrılır: tıklayan istemcinin süreci TCP tablosunda görünür (baglanan_pid). macOS'ta
    0.0.0.0:443, yalnız bu bilgisayardan gelen bağlantılar (uyum.dinleme_adresi)."""

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
            self.log('   ödeme düğmeleri: %d dinlenemedi (%s); düğmeler mağazayı açmaz' % (self.port, e))
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
                except Exception as e:                  # noqa: BLE001 (dinleyici düşmesin)
                    self.log('   ödeme düğmesi hatası: %s' % e)
            try:
                c.close()
            except OSError:
                pass

    def stop(self):
        if self.sock:
            self.sock.close()
