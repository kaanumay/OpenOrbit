"""Botların oyun ayarı profili: oyuncunun oyun ayarlarından (settings.py) ayrı. Oyuncu kendine kolay ayar seçse de botlar paketin
profiliyle ilerler (kullanıcı isteği 2026-10-29).

Profil (paketin 'oyun_ayari' ayarı): {'profil': 'standart' | 'oyuncu' | <ayar.HAZIR'daki hazır ayar> | 'ozel', 'degerler': {...}}
  standart  oyunun kendi değerleri (varsayılan)
  oyuncu    oyuncunun o anki oyun ayarları (eski davranış gibi değil: önceden botlar hiç çarpan kullanmıyordu)
  rahat, hizli, zorlu ...  ayar.HAZIR'ın değerleri
  ozel      paneldeki değerler (ALANLAR)
carpan(key, kaynak) ayar.carpan gibi: üst çarpan x kaynağın alt çarpanı (ep x ep_npc).
"""
import settings as SET

FIELDS = ('ep', 'kredi', 'uridyum', 'onur', 'npc_can', 'npc_damage', 'shop_price', 'repair_cost')   # Özel profilin düzenlenenleri
PROFILES = ('standard', 'player', 'casual', 'fast', 'hard', 'ozel')


class Profile:
    def __init__(self, setting=None):
        setting = setting if isinstance(setting, dict) else {}
        self.name = setting.get('profil') if setting.get('profil') in PROFILES else 'standard'
        if self.name == 'ozel':
            self.d = {k: float(v) for k, v in (setting.get('values') or {}).items() if k in SET.DEFAULTS}
        elif self.name in SET.PRESETS:
            self.d = dict(SET.PRESETS[self.name]['values'])
        else:
            self.d = {}

    def get(self, key):
        if self.name == 'player':
            return SET.get(key)
        return self.d.get(key, SET.DEFAULTS.get(key, 1.0))

    def multiplier(self, key, source=None):
        sub = SET.SUB.get((key, source))
        try:
            return float(self.get(key)) * (float(self.get(sub)) if sub else 1.0)
        except (TypeError, ValueError):
            return 1.0


STANDARD = Profile()
