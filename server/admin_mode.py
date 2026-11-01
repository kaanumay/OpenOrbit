"""Yönetici modu (panelin Oyun ayarları > Yönetici; oyuncu isteği 2026-10-30): oyuncu oyunda yönetici olarak görünür.

İstemcide (canlı test 2026-10-30):
  - ShipInitializationCommand / ShipCreateCommand dailyRank 6000: adın önünde yönetici rozeti (sarı A; wiki "Administrator") ve
    istemci oyuncuyu Hero.Admin sayar (GM konsolu penceresi, gm_console.py). Rütbe 22 rozet çizmez.
  - Yönetici gemileri istemcinin gemi listesinde: ship_admin (ADMIN_SHIP; game.xml'de UFO uzaylısının modeli de bu), ship_police,
    ship_g-admincloak ve Goliath'ın tasarımı ship_goliath_design_admincloak. Görünüm typeId'den: değerler oyuncunun gemisinin.
  - Sohbet: gönderenin role alanı ChatUserVo türlerinden (Frida ile okunan statik alanlar): chatter, dev, customerServiceLead,
    customerService, admin, mod, system, cmd. Yönetici "admin" (istemcinin AdministratorMessageColor'u).
Kurallar: yönetici rütbe sistemine, Şeref Salonu listelerine ve şirketteki sıraya girmez (ranks.py); izleyici ayarı açıksa uzaylılar
ve botlar ona saldırmaz, hasar almaz (world.py, bot/ship.py). Botlar yöneticiyi tanır: saldırmaz, sohbetteki uyarısına uyar
(bot/admin_warnings.py), görünce tepki verir. Arkadaş sunucusunda yalnız sunucunun oyuncusu (misafir değil).
"""
import settings as SET

BADGE = 6000                    # istemcinin yönetici rütbesi (gm_konsol.ADMIN_RANK ile aynı)
SHIPS = (None, 'ship_admin', 'ship_police', 'ship_g-admincloak', 'ship_goliath_design_admincloak')
CHAT_ROLE = 'admin'


def _host():
    import community as TP
    g = TP.GAME
    return g.PROFILE if g is not None else None


def is_open(profile=None):
    """Yönetici modu açık mı (profil verilirse: o profil yönetici mi: yalnız sunucunun oyuncusu; misafir ve çoklu istemcinin ek
    oyuncuları değil; sunucu kurulmadan, ör. testte, profilin kendisi)."""
    if not SET.get('admin_mode'):
        return False
    if profile is None:
        return True
    host = _host()
    return getattr(profile, 'guest', None) is None and (host is None or profile is host)


def ship(profile=None):
    """Yönetici gemisinin görünümü (typeId) ya da None (kendi gemisi)."""
    if not is_open(profile):
        return None
    return SHIPS[min(len(SHIPS) - 1, max(0, int(SET.get('admin_ship') or 0)))]


def spectator(profile=None):
    """Dokunulmaz izleyici: uzaylılar ve botlar saldırmaz, hasar almaz."""
    return is_open(profile) and bool(SET.get('admin_spectator'))


def chat_role(profile=None, default='chatter'):
    return CHAT_ROLE if is_open(profile) and SET.get('admin_chat') else default


def name():
    """Yöneticinin pilot adı (sunucunun oyuncusu) ya da None."""
    host = _host()
    return str(host.d['pilot'].get('userName', '')) if is_open() and host is not None else None


def mi(name_=None, profile=None, uid=None):
    """Bu pilot yönetici mi (ad, profil ya da kimlik ile)."""
    host = _host()
    if not is_open() or host is None:
        return False
    if profile is not None:
        return profile is host
    if uid is not None:
        return uid == host.user_id
    return name_ is not None and str(name_).lower() == str(host.d['pilot'].get('userName', '')).lower()
