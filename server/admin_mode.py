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
Per save (fork): the admin settings are read from each player's own save (save/slots/<id>/settings.json next to its profile.json), so in a
multi-client setup an extra client whose save is in admin mode is an admin too, and the server's player only when the active save is.
Friend-server guests are never admins.
"""
import os, time

import settings as SET

BADGE = 6000                    # the client's admin rank (same as gm_console.ADMIN_RANK)
SHIPS = (None, 'ship_admin', 'ship_police', 'ship_g-admincloak', 'ship_goliath_design_admincloak')
CHAT_ROLE = 'admin'
MOD_SHIPS = ('ship_admin', 'ship_police')     # the moderator ships that are real ships on the server (items.json)


def _host():
    import community as TP
    g = TP.GAME
    return g.PROFILE if g is not None else None


_OWN = {}                       # settings.json path -> (mtime, settings, checked): an extra client's own save
_RECHECK = 1.0                   # seconds between two looks at the file (an alien's every step asks: no stat each time)


def _local_players():
    try:
        import multiplayer as CO
        return CO.local_players()
    except Exception:                 # noqa: BLE001 (no server: a test)
        return []


def _setting(profile, key):
    """The admin setting of this player's own save: the active save's for the server's player (or with no server), the save next to the
    profile file for a multi-client extra player; None for a friend-server guest."""
    if getattr(profile, 'guest', None) is not None:
        return None
    host = _host()
    if profile is None or host is None or profile is host:
        return SET.get(key)
    path = os.path.join(os.path.dirname(os.path.abspath(getattr(profile, 'path', '') or '.')), 'settings.json')
    now = time.monotonic()
    c = _OWN.get(path)
    if not c or now - c[2] >= _RECHECK:
        try:
            mt = os.stat(path).st_mtime_ns
        except OSError:
            mt = None
        vals = (c[1] if c and c[0] == mt else SET.read(path) if mt is not None else {})
        _OWN[path] = c = (mt, vals, now)
    return c[1].get(key, SET.DEFAULTS.get(key))


def admins():
    """The profiles playing as admin right now: the server's player and the multi-client's extra players whose save is in admin mode."""
    host = _host()
    out = [host] if host is not None and SET.get('admin_mode') else []
    return out + [y.profile for y in _local_players() if y.profile is not None and _setting(y.profile, 'admin_mode')]


def is_open(profile=None):
    """Whether admin mode is on: for a profile, whether that player is an admin (its own save's setting; never a friend-server guest);
    without a profile, whether anyone plays as admin."""
    if profile is None:
        return bool(SET.get('admin_mode')) or bool(admins())
    return bool(_setting(profile, 'admin_mode'))


def ship(profile=None):
    """The admin ship's look (typeId) or None (own ship)."""
    if not is_open(profile):
        return None
    return SHIPS[min(len(SHIPS) - 1, max(0, int(_setting(profile, 'admin_ship') or 0)))]


def ship_allowed(profile, loot):
    """Whether this player may own and fly this ship: the moderator ships (MOD_SHIPS) only for an admin, or for every player
    with the server setting mod_ships_players. Bots (no profile) never."""
    if loot not in MOD_SHIPS:
        return True
    if profile is None:
        return False
    return is_open(profile) or bool(SET.get('mod_ships_players'))


def spectator(profile=None):
    """Untouchable spectator: aliens and bots do not attack, no damage taken."""
    return is_open(profile) and bool(_setting(profile, 'admin_spectator'))


def chat_role(profile=None, default='chatter'):
    return CHAT_ROLE if is_open(profile) and _setting(profile, 'admin_chat') else default


def name():
    """The admins' pilot names (comma-separated) or None."""
    names = [str(p.d['pilot'].get('userName', '')) for p in admins()]
    return ', '.join(n for n in names if n) or None


def mi(name_=None, profile=None, uid=None):
    """Whether this pilot is an admin (by name, profile or id)."""
    if profile is not None:
        return is_open(profile)
    for p in admins():
        if uid is not None and uid == p.user_id:
            return True
        if name_ is not None and str(name_).lower() == str(p.d['pilot'].get('userName', '')).lower():
            return True
    return False
