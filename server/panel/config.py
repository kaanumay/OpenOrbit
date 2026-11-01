"""Panel ayarları (save/panel.json): dil ve kurulum, etkin kayıt yuvası, istemci klasörü ve görüntü, yedekleme, sunucu davranışı,
Linux ve macOS'ta istemciyi açan Wine ya da Proton.

Bilinmeyen anahtarlar korunur (eski/yeni sürümler aynı dosyayı paylaşabilir); türü yanlış değer varsayılana döner.
"""
import json, os, threading

import lang as D

DEFAULTS = {
    'dil': None,                    # dil.DILLER'den bir kod; None: henüz seçilmedi (kurulum sihirbazı dil seçimiyle açılır)
    'setup_done': False,         # ilk açılış sihirbazı bitti (ya da atlandı)
    'aktif_kayit': None,            # save/kayitlar/<kimlik>
    'istemci_klasoru': None,        # None: kendiliğinden (proje kökündeki en yeni DarkOrbit_Version* klasörü)
    'window_mode': 'pencere',      # pencere | tam_ekran | kenarliksiz
    'width': 1440,
    'height': 900,
    'monitor': 0,                   # 0: Unity'nin seçtiği; 1..: -monitor N
    'extra_args': '',            # istemciye eklenecek başka Unity argümanları
    'backup_on_launch': True,         # Oyna'da etkin yuvanın otomatik yedeği
    'backup_count': 10,             # saklanan otomatik yedek (elle alınanlar silinmez)
    'backup_interval_min': 30,          # oyun açıkken otomatik yedek aralığı (0: kapalı)
    'istemci_kapaninca': 'kapat',   # kapat: panelin açtığı sunucular kapanır | acik: açık kalır
    'rotate_logs': True,          # büyük günlükler başlatmada .1, .2 … olarak kayar
    'pencere_kapaninca': 'bekle',   # panel penceresi kapanınca: bekle (oyun sürüyorsa bitince kapanır) | kapat (her şeyi kapatır)
    'guncelleme': 'otomatik',       # GitHub'daki yeni sürüm (guncelleme.py): otomatik kur | bildir (yalnız haber ver) | kapali
    'fast_download': True,          # istemci indirmesi BAGLANTI bağlantıyla (indirme.py); kapalıyken tek bağlantı
    'friend_password': '',            # Arkadaşlarınla Oyna > Host: katılma şifresi (boş: şifresiz)
    'friend_max': 4,            # Host: en çok misafir
    'friend_world': '',            # Host: sunucunun dünyası (Dünya Editörü; boş: etkin kaydın varsayılan dünyası)
    'friend_last_address': '',        # Join: son katılınan adres
    'multi_client': True,          # çoklu istemci: en az iki kayıt varsa OYNA sunucuyu çok oturumlu açar (coklu.py)
    'multi_client_max': 3,              # en çok ek istemci (her istemci ~600 MB bellek)
    'runner': 'otomatik',      # Linux ve macOS: istemciyi açan otomatik | motor | wine | proton | ozel (calistirici.py)
    'runner_path': '',         # wine programı, Proton klasörü ya da özel komut (boş: kendiliğinden)
    'wine_prefix': '',                # Wine öneki / Proton veri klasörü (boş: save/wine ya da save/proton)
    'discord_rp': True,             # Discord Rich Presence (discord_rp.py); rp_*: profilde görünenler
    'rp_pilot': False,              # pilot adı (gizlilik: varsayılan kapalı)
    'rp_klan': True,
    'rp_gemi': True,
    'rp_seviye': True,
    'rp_harita': True,              # harita adı ve bölgenin görseli
    'rp_durum': True,               # savaşta (hedef), kapı dalgası, güvenli bölge, gemi parçalandı
    'rp_firma': True,               # firmanın amblemi
    'rp_sure': True,                # oturumun geçen süresi
    'rp_grup': True,                # Arkadaşlarınla Oyna: grup büyüklüğü
    'rp_butonlar': True,            # Discord sunucusu ve GitHub düğmeleri
    'rp_panelde': True,             # oyun kapalıyken de (panelde)
}
CHOICES = {'window_mode': ('pencere', 'tam_ekran', 'kenarliksiz'), 'istemci_kapaninca': ('kapat', 'acik'),
           'pencere_kapaninca': ('bekle', 'kapat'), 'guncelleme': ('otomatik', 'bildir', 'kapali'),
           'runner': ('otomatik', 'motor', 'wine', 'proton', 'ozel')}
LIMITS = {'width': (640, 7680), 'height': (480, 4320), 'monitor': (0, 8), 'backup_count': (1, 200), 'backup_interval_min': (0, 600),
          'friend_max': (1, 16), 'multi_client_max': (1, 8)}


def clean(key, v):
    """Değeri doğrula -> geçerli değer ya da ValueError."""
    if key not in DEFAULTS:
        raise ValueError('bilinmeyen ayar: %s' % key)
    d = DEFAULTS[key]
    if key == 'dil':
        return v if v in D.LANGUAGES else None
    if key in CHOICES:
        if v not in CHOICES[key]:
            raise ValueError('%s: geçersiz seçim' % key)
        return v
    if isinstance(d, bool):
        return bool(v)
    if isinstance(d, int):
        v = int(v)
        lo, hi = LIMITS.get(key, (v, v))
        return min(hi, max(lo, v))
    if key in ('aktif_kayit', 'istemci_klasoru'):
        return str(v) if v else None
    return str(v if v is not None else '')


class PanelConfig:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.d = {}
        self.load()

    def load(self):
        try:
            with open(self.path, encoding='utf8') as fh:
                d = json.load(fh)
            self.d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            self.d = {}

    def get(self, key):
        v = self.d.get(key, DEFAULTS.get(key))
        try:
            return clean(key, v) if key in DEFAULTS else v
        except (TypeError, ValueError):
            return DEFAULTS[key]

    def all(self):
        return {k: self.get(k) for k in DEFAULTS}

    def update(self, values):
        """Değerleri doğrulayıp yaz -> güncel ayarlar. Geçersiz değer ValueError (hiçbiri yazılmaz)."""
        new = {k: clean(k, v) for k, v in values.items()}
        with self.lock:
            self.d.update(new)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
                json.dump(self.d, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        return self.all()
