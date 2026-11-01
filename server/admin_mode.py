"""Admin mode (panel Game settings > Admin; player request 2026-10-30): the player appears in game as an administrator.

On the client (live test 2026-10-30):
  - ShipInitializationCommand / ShipCreateCommand dailyRank 6000: an admin badge in front of the name (yellow A; wiki "Administrator") and
    the client treats the player as Hero.Admin (GM console window, gm_console.py). Rank 22 draws no badge.
  - Admin ships in the client's ship list: ship_admin (ADMIN_SHIP; in game.xml the UFO alien's model is this too), ship_police,
    ship_g-admincloak and Goliath's design ship_goliath_design_admincloak. The look comes from typeId: the values are the player's ship.
  - Chat: the sender's role field is one of the ChatUserVo types (static fields read with Frida): chatter, dev, customerServiceLead,
    customerService, admin, mod, system, cmd. Admin uses "admin" (the client's AdministratorMessageColor).
Rules: the admin does not enter the rank system, the Hall of Fame lists or the standings in the company (ranks.py); with the spectator
setting on, aliens and bots do not attack the admin and the admin takes no damage (world.py, bot/ship.py). Bots recognize the admin: they
do not attack, they obey the admin's warning in chat (bot/admin_warnings.py) and react on sight. On a friend server, only the server's
player (not guests).
"""
import settings as SET

BADGE = 6000                    # the client's admin rank (same as gm_console.ADMIN_RANK)
SHIPS = (None, 'ship_admin', 'ship_police', 'ship_g-admincloak', 'ship_goliath_design_admincloak')
CHAT_ROLE = 'admin'


def _host():
    import community as TP
    g = TP.GAME
    return g.PROFILE if g is not None else None


def is_open(profile=None):
    """Whether admin mode is on (if a profile is given: whether that profile is an admin: only the server's player; not guests or the
    extra players of a multi-client setup; without a server, e.g. in a test, the profile itself)."""
    if not SET.get('admin_mode'):
        return False
    if profile is None:
        return True
    host = _host()
    return getattr(profile, 'guest', None) is None and (host is None or profile is host)


def ship(profile=None):
    """The admin ship's look (typeId) or None (own ship)."""
    if not is_open(profile):
        return None
    return SHIPS[min(len(SHIPS) - 1, max(0, int(SET.get('admin_ship') or 0)))]


def spectator(profile=None):
    """Untouchable spectator: aliens and bots do not attack, no damage taken."""
    return is_open(profile) and bool(SET.get('admin_spectator'))


def chat_role(profile=None, default='chatter'):
    return CHAT_ROLE if is_open(profile) and SET.get('admin_chat') else default


def name():
    """The admin's pilot name (the server's player) or None."""
    host = _host()
    return str(host.d['pilot'].get('userName', '')) if is_open() and host is not None else None


def mi(name_=None, profile=None, uid=None):
    """Whether this pilot is the admin (by name, profile or id)."""
    host = _host()
    if not is_open() or host is None:
        return False
    if profile is not None:
        return profile is host
    if uid is not None:
        return uid == host.user_id
    return name_ is not None and str(name_).lower() == str(host.d['pilot'].get('userName', '')).lower()
