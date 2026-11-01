"""Platform compatibility (standard library only; web.py, game.py and the panel use it together). It changes nothing on Windows and Linux.

macOS:
  Low ports      Since Mojave a non-root process can open a port below 1024 only on the wildcard address (0.0.0.0), on 127.0.0.1
                 PermissionError. These ports (web API 80, fake TCP 843, payment buttons 443) are opened there on 0.0.0.0 and only connections coming from this
                 computer are accepted (is_local): the listeners are still closed to the outside.
  Certificates   python.org's macOS Python comes with its own OpenSSL; if "Install Certificates.command" was not run it has no root certificate,
                 and HTTPS (client download, CDN images, update) gives CERTIFICATE_VERIFY_FAILED. In that case the system's bundle
                 (/etc/ssl/cert.pem) is given through SSL_CERT_FILE; child processes (web.py, game.py) inherit it.
"""
import os, sys

MAC = sys.platform == 'darwin'
SYSTEM_CERTIFICATES = '/etc/ssl/cert.pem'


def listen_address(address, port):
    """Address to listen on -> (address, filter or not). On macOS 127.0.0.1 and a port below 1024: 0.0.0.0, only local connections."""
    if MAC and port < 1024 and address in ('127.0.0.1', 'localhost'):
        return '0.0.0.0', True
    return address, False


def is_local(ip):
    """Is the connection from this computer (IPv4 or IPv6 loopback)?"""
    ip = str(ip or '')
    return ip.startswith(('127.', '::ffff:127.')) or ip == '::1'


def certificates():
    """If Python's OpenSSL on macOS cannot find a root certificate, give it the system's bundle (SSL_CERT_FILE; before the first HTTPS request)."""
    if not MAC or os.environ.get('SSL_CERT_FILE'):
        return
    import ssl
    p = ssl.get_default_verify_paths()              # None if the paths do not exist
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
