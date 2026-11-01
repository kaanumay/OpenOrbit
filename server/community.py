"""Players on the server: the group (group.py), contacts (contacts.py), chat whispers, mail and the pilot card find another player here.

In single player only the player themselves; on a friend server (multiplayer.py) the server's own player and the guests, with multiple
clients the extra players (the other saves on this computer). Everyone whose save is on the server is known (a disconnected guest's save
also stays in memory: mail and contact requests are written to it, its latest state goes to their panel); someone with a game connection
is online. A guest's id on the server differs at each join (cok_oyunculu._yeni_uid): persistent links (contacts) are kept by name.
"""
import multiplayer as CO

GAME = None          # the game module (game.py binds): PROFIL, CURRENT
BOTS = None        # () -> {id: Kisi}: the bot package's pilots (bot/toplum.kaydol)


class Person:
    __slots__ = ('profile', 'session')

    def __init__(self, profile, session):
        self.profile, self.session = profile, session       # session: the bound game.Session or None

    @property
    def uid(self):
        return self.profile.user_id

    @property
    def name(self):
        return str(self.profile.d['pilot'].get('userName', ''))

    @property
    def world(self):
        w = self.session.world if self.session is not None else None
        return w if w is not None and w.running else None

    def send(self, msgs, note=None):
        """To its client if connected (silently dropped if the connection is closed) -> whether it went."""
        s = self.session
        if s is None or not msgs:
            return False
        try:
            s.send(msgs, note)
            return True
        except (OSError, ConnectionError):
            return False


def all_():
    """id -> Kisi: the server's player, unfinished guest sessions and the extra players of multiple clients."""
    g = GAME
    if g is None:
        return {}
    host = g.PROFILE
    cur = g.CURRENT
    out = {host.user_id: Person(host, cur if cur is not None and cur.profile is host else None)}
    for m in CO.entries() + CO.local_players():
        if m.profile is not None:
            s = m.session
            out[m.profile.user_id] = Person(m.profile, s if s is not None and s.profile is m.profile else None)
    if BOTS is not None:
        for uid, k in BOTS().items():
            out.setdefault(uid, k)
    return out


def find(name=None, uid=None):
    """The player by id or by name (case-insensitive), or None."""
    people = all_()
    if uid is not None:
        return people.get(uid)
    name = str(name or '').strip().lower()
    return next((k for k in people.values() if name and k.name.lower() == name), None) if name else None


def ranking(p, value, max_count=10):
    """Event ranking: the players on the server (those with a value) by value -> ([(rank, profile, value)] first en_cok, the player's
    (rank, profile, value) or (0, p, 0) if they have no value). In single player only the player."""
    lst = [k.profile for k in all_().values()]
    if all(x is not p for x in lst):                    # a profile not on the server stands alone
        lst = [p]
    vals = sorted(((x, value(x)) for x in lst), key=lambda xv: (-xv[1], str(xv[0].d['pilot'].get('userName', '')).lower()))
    rows = [(i + 1, x, v) for i, (x, v) in enumerate(xv for xv in vals if xv[1])]
    me = next((r for r in rows if r[1] is p), (0, p, 0))
    return rows[:max_count], me


def person(profile):
    """The profile's Kisi (with its session) or only with the profile (dropped from the server)."""
    return all_().get(profile.user_id) or Person(profile, None)
