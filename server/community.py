"""Sunucudaki oyuncular: grup (group.py), rehber (contacts.py), sohbetin fısıltısı, posta ve pilot kartı başka oyuncuyu buradan bulur.

Tek oyunculuda yalnız oyuncunun kendisi; arkadaş sunucusunda (multiplayer.py) sunucunun kendi oyuncusu ve misafirler, çoklu
istemcide ek oyuncular (bu bilgisayardaki öteki kayıtlar). Kaydı sunucuda
olan herkes bilinir (bağlı olmayan misafirin kaydı da bellekte durur: posta ve rehber isteği ona yazılır, son hâli paneline gider);
oyun bağlantısı olan çevrimiçidir. Misafirin sunucudaki kimliği her katılmada başka (cok_oyunculu._yeni_uid): kalıcı bağlar (rehber)
ada göre tutulur.
"""
import multiplayer as CO

GAME = None          # game modülü (game.py bağlar): PROFIL, CURRENT
BOTS = None        # () -> {kimlik: Kisi}: bot paketinin pilotları (bot/toplum.kaydol)


class Person:
    __slots__ = ('profile', 'session')

    def __init__(self, profile, session):
        self.profile, self.session = profile, session       # oturum: bağlı game.Session ya da None

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
        """Bağlıysa istemcisine (bağlantı kapanmışsa sessizce düşer) -> gitti mi."""
        s = self.session
        if s is None or not msgs:
            return False
        try:
            s.send(msgs, note)
            return True
        except (OSError, ConnectionError):
            return False


def all_():
    """kimlik -> Kisi: sunucunun oyuncusu, bitmemiş misafir oturumları ve çoklu istemcinin ek oyuncuları."""
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
    """Kimliğe ya da ada (büyük/küçük harf ayrımsız) göre oyuncu ya da None."""
    people = all_()
    if uid is not None:
        return people.get(uid)
    name = str(name or '').strip().lower()
    return next((k for k in people.values() if name and k.name.lower() == name), None) if name else None


def ranking(p, value, max_count=10):
    """Etkinlik sıralaması: sunucudaki oyuncular (değeri olanlar) değere göre -> ([(sıra, profil, değer)] ilk en_cok, oyuncunun
    (sıra, profil, değer) ya da değeri yoksa (0, p, 0)). Tek oyunculuda yalnız oyuncu."""
    lst = [k.profile for k in all_().values()]
    if all(x is not p for x in lst):                    # sunucuda olmayan profil tek başına
        lst = [p]
    vals = sorted(((x, value(x)) for x in lst), key=lambda xv: (-xv[1], str(xv[0].d['pilot'].get('userName', '')).lower()))
    rows = [(i + 1, x, v) for i, (x, v) in enumerate(xv for xv in vals if xv[1])]
    me = next((r for r in rows if r[1] is p), (0, p, 0))
    return rows[:max_count], me


def person(profile):
    """Profilin Kisi'si (oturumuyla) ya da yalnız profille (sunucudan düşmüş)."""
    return all_().get(profile.user_id) or Person(profile, None)
