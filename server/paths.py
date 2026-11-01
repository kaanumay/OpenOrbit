"""Kayıt ve panel yolları (yönetim paneli, panel/): profil, web ayarları, oyun ayarları.

  save/kayitlar/<kimlik>/profil.json     kayıt yuvasının profili (oyun sunucusu yazar)
  save/kayitlar/<kimlik>/web_ayarlari.json  giriş ekranının dili (web.py, profilin yanında)
  save/kayitlar/<kimlik>/kayit.json      yuvanın adı, notu, tarihleri (panel)
  save/kayitlar/<kimlik>/yedek/          yedekler (panel)
  save/panel.json                        panel ayarları: etkin yuva, istemci klasörü, görüntü, yedekleme …
  save/ayarlar.json                      oyun ayarları (settings.py)
Giriş şablonları (giris.json, haritalar.json, yanitlar.json): kendi kaydından çıkarılanlar data/'da (git'e girmez), yoksa depodaki
paylaşılabilir kopya data/defaults/'da (tools/template_sharing.py; hesap ve oyuncu kimlikleri takma): sablon().
Etkin yuva panel.json'un 'aktif_kayit'ı. Eski düzen (save/profil.json) panel ilk açılınca 'ana' yuvasına taşınır; taşınmadıysa ya da
etkin yuva yoksa profil yolu eski dosyadır (game.py / web.py --profile olmadan çalışınca).
Yalnız standart kitaplık: web.py, game.py ve panel birlikte kullanır.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SAVE = os.environ.get('OO_SAVE_DIR') or os.path.join(HERE, 'save')      # testler geçici klasör verir
SAVES = os.path.join(SAVE, 'kayitlar')
TRASH = os.path.join(SAVE, 'silinenler')
PANEL = os.path.join(SAVE, 'panel.json')
SETTINGS = os.path.join(SAVE, 'ayarlar.json')
LEGACY_PROFILE = os.path.join(SAVE, 'profil.json')
LOGS = os.environ.get('OO_LOG_DIR') or os.path.join(HERE, 'logs')
DATA = os.path.join(HERE, 'data')
TEMPLATES = ('giris.json', 'haritalar.json', 'yanitlar.json')
DEFAULT_TEMPLATE = os.path.join(DATA, 'defaults')


def template(name):
    """Giriş şablonunun yolu: kendi kaydından çıkarılan (data/<ad>) varsa o, yoksa paylaşılabilir kopya (data/defaults/<ad>);
    ikisi de yoksa None."""
    for p in (os.path.join(DATA, name), os.path.join(DEFAULT_TEMPLATE, name)):
        if os.path.isfile(p):
            return p
    return None


def panel_config(path=PANEL):
    try:
        with open(path, encoding='utf8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def slot_dir(slot, root=SAVES):
    return os.path.join(root, slot)


def active_slot(path=PANEL):
    s = panel_config(path).get('aktif_kayit')
    return s if isinstance(s, str) and s and os.path.isdir(slot_dir(s)) else None


def profile_path(slot=None):
    """Yuvanın (verilmezse etkin yuvanın) profil dosyası; yuva yoksa eski save/profil.json."""
    slot = slot or active_slot()
    return os.path.join(slot_dir(slot), 'profil.json') if slot else LEGACY_PROFILE


def settings_path(slot=None):
    """Yuvanın (verilmezse etkin yuvanın) oyun ayarları (kayda özgü; panel ilk açılışta oluşturur); yoksa eski save/ayarlar.json."""
    slot = slot or active_slot()
    p = os.path.join(slot_dir(slot), 'ayarlar.json') if slot else None
    return p if p and os.path.isfile(p) else SETTINGS
