"""Platform uyumu (yalnız standart kitaplık; web.py, game.py ve panel birlikte kullanır). Windows'ta ve Linux'ta hiçbir şeyi değiştirmez.

macOS:
  Düşük portlar  Mojave'den beri root olmayan süreç 1024'ten küçük bir portu yalnız joker adreste (0.0.0.0) açabiliyor, 127.0.0.1'de
                 PermissionError. Bu portlar (web API 80, sahte TCP 843, ödeme düğmeleri 443) orada 0.0.0.0'da açılır ve yalnız bu
                 bilgisayardan gelen bağlantılar kabul edilir (yerel_mi): dinleyiciler yine dışarıya kapalı.
  Sertifikalar   python.org'un macOS Python'u kendi OpenSSL'iyle gelir; "Install Certificates.command" çalıştırılmadıysa kök sertifikası
                 yok, HTTPS (istemci indirmesi, CDN görselleri, güncelleme) CERTIFICATE_VERIFY_FAILED verir. O zaman sistemin paketi
                 (/etc/ssl/cert.pem) SSL_CERT_FILE ile verilir; alt süreçler (web.py, game.py) devralır.
"""
import os, sys

MAC = sys.platform == 'darwin'
SYSTEM_CERTIFICATES = '/etc/ssl/cert.pem'


def listen_address(address, port):
    """Dinlenecek adres -> (adres, süzülsün mü). macOS'ta 127.0.0.1 ve 1024'ten küçük port: 0.0.0.0, yalnız yerel bağlantılar."""
    if MAC and port < 1024 and address in ('127.0.0.1', 'localhost'):
        return '0.0.0.0', True
    return address, False


def is_local(ip):
    """Bağlantı bu bilgisayardan mı (IPv4 ya da IPv6 geri döngü)?"""
    ip = str(ip or '')
    return ip.startswith(('127.', '::ffff:127.')) or ip == '::1'


def certificates():
    """macOS'ta Python'un OpenSSL'i kök sertifika bulamıyorsa sistemin paketini ver (SSL_CERT_FILE; ilk HTTPS isteğinden önce)."""
    if not MAC or os.environ.get('SSL_CERT_FILE'):
        return
    import ssl
    p = ssl.get_default_verify_paths()              # yollar yoksa None
    if p.cafile or p.capath:
        return
    if os.path.isfile(SYSTEM_CERTIFICATES):
        os.environ['SSL_CERT_FILE'] = SYSTEM_CERTIFICATES
        return
    try:
        import certifi
        os.environ['SSL_CERT_FILE'] = certifi.where()
    except ImportError:
        pass
