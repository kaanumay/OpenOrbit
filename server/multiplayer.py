"""Arkadaşlarla oyna: arkadaş sunucusu ve misafirlerin hesapları (panelin "Arkadaşlarınla Oyna" sayfası, panel/friends.py).

Sunucu: panel game.py'yi --multiplayer ile başlatır. Oyun (8081) ve sohbet (7771) portları bütün ağlardan dinlenir; web girişi
(80, 8090) yerel kalır: her oyuncu kendi bilgisayarındaki web.py'den girer (misafirinki --remote ile bu sunucuyu gösterir). Ayarlar
ortam değişkeninden (OO_MULTIPLAYER, JSON; komut satırında görünmesin): sifre (katılma şifresi; boş: yok), en_cok (misafir sayısı),
anahtar (panelin yönetim anahtarı), kod (panelin sürümü: misafirin paneli karşılaştırır), adres (dinlenen adres; öntanımlı 0.0.0.0,
tek bilgisayardaki canlı testte 127.0.0.1: güvenlik duvarı sorusu çıkmasın). Aynı normal haritadaki oyuncular
uzaylıları, kutuları ve cevherleri paylaşır, birbirini görür (shared_maps.py); sohbet ortak.

Hesap gönderimi: misafirin paneli oyuna girmeden kaydını oyun portundan HTTP ile gönderir (game.handle ilk baytlar "GET "/"POST"
ise buraya verir; oyun istemcisinin ilk paketi uzunlukla başlar).
  GET  /misafir/bilgi                     sunucunun adı, pilotu, oyuncular, şifre gerekli mi, yer var mı
  POST /misafir/giris {surum, sifre, anahtar, adres, profil}  -> {oturum, uid, surum, sohbet}
       Kayıt sunucunun belleğinde tutulur, diske yazılmaz: sunucunun Kayıtlar sayfasında görünmez. Oyuncu kimliği sunucuda benzersiz
       olsun diye geçici bir kimlikle değişir (kayıtların çoğu tohumun aynı kimliğiyle başlar), geri verilirken eskisine döner
       (kimlik alanlarında: kimlik_cevir). Aynı anahtarla yeniden giriş (bağlantı koptu, panel yeniden açıldı) oturumu ve
       sunucudaki son hâli sürdürür. adres: misafirin bu sunucuya bağlandığı adres (sohbetin adresi oradan).
  GET  /misafir/profil?oturum=&anahtar=&surum=N&bekle=25
       uzun yoklama: kayıt N'den yeni bir sürüme gelince (oyun değişince 10 sn'de bir kaydeder; MisafirProfil.save) ya da süre
       dolunca -> {surum, bagli, bitti, profil (yeniyse)}. Misafirin paneli her yeni sürümü kendi kayıt yuvasına yazar.
  POST /misafir/cikis {oturum, anahtar}   -> son hâl; oturum biter (oyun açıksa bağlantı kapanır), kayıt kısa süre sonra silinir
Gövdeler JSON; "Content-Encoding: gzip" ile sıkıştırılmış da olabilir, "Accept-Encoding: gzip" isteyene yanıt sıkıştırılır.
Yönetim (yalnız 127.0.0.1'den, panelin anahtarıyla): POST /yonetim/kick {anahtar, oturum}: misafiri çıkar.
İstemci girişte (LoginRequest) web girişinin verdiği sessionID'yi gönderir: misafirinki oturum anahtarı (bul), sunucunun kendi
oyuncusununki web.py'nin SESSION'ı (AYAR['yerel']: panelin bu açılışta ürettiği belirteç; yalnız bu bilgisayardan).
Yanlış katılma şifresi adres başına sınırlı (DENEME_SINIR denemeden sonra KILIT_SN kilit, 429).
Sunucu kapatılırken (panelin "Durdur"u) misafirlerin son hâli yayımlanır ve bekleyen yoklamalara verilir (kapanis).

Çoklu istemci (panelin OYNA'sından sonra bu bilgisayardaki öteki kayıtlarla açılan istemciler; panel/multi_client.py): sunucu aynı kipte
açılır, misafir kabul etmez (OO_MULTIPLAYER misafir: false, adres 127.0.0.1); Host'ta misafirlerle birlikte. Yalnız 127.0.0.1'den:
  POST /yerel/ekle {anahtar, kayit, yol}  -> {oturum, uid, devam}: yuvanın profil.json'u ek oyuncu olarak yüklenir (YerelProfil:
       dosyaya doğrudan yazılır; kimliği sunucudaki başka bir oyuncununkiyle aynıysa bellekte kayda göre sabit geçici kimlik).
       Aynı yuva yeniden eklenirse (istemci yeniden açıldı) oturum sürer. Ana kayıt, aynı pilot adı ve dolu sunucu reddedilir.
  POST /yerel/cikar {anahtar, oturum}     -> bağlıysa oyun bağlantısı kapanır, son hâl yazılır, yuva bırakılır
  GET  /yerel/oturum?oturum=              -> {uid, yol, kayit}: web.py ek istemcinin girişini bununla verir
"""
import collections, gzip, hmac, json, os, random, re, secrets, socket, threading, time, zlib
from urllib.parse import parse_qs, urlparse

import player_profile as PF
import paths as PTH

PROTOCOL = 1                    # hesap gönderiminin sürümü: misafirin paneliyle aynı olmalı
UID_LOWER, UID_UPPER = 2000000000, 2100000000     # misafirlerin sunucudaki geçici kimlikleri (int32; kayıt kimlikleriyle karışmaz)
BODY_LIMIT = 8 * 1024 * 1024   # hesap gönderimi (kayıtlar ~0,4 MB); şifreden önce okunur
ATTEMPT_LIMIT, LOCK_SEC = 5, 60  # adres başına yanlış şifre: bu kadar denemeden sonra bu kadar saniye kilit
HEADER_LIMIT = 64 * 1024
WAIT_MAX = 30
IDLE_SEC = 30 * 60              # bağlı değil ve yoklanmıyor: kayıt bu kadar sonra bırakılır (veri misafirin panelinde)
END_SEC = 120                  # biten oturumun son hâli bu kadar daha alınabilir (yoklama arasında biten oturum kaybolmasın)
CHAT_PORT = 7771

LOCAL_LOWER, LOCAL_UPPER = 2100000000, 2147000000     # ek oyuncuların geçici kimlikleri (misafirlerinkinden ayrı)
LOCAL_MAX = 16               # sunucunun sınırı (panelin kendi sınırı daha küçük: coklu_en_cok)

SETTINGS = {'acik': False, 'sifre': '', 'en_cok': 4, 'anahtar': None, 'kod': '', 'adres': '0.0.0.0', 'yerel': '', 'misafir': True}
COND = threading.Condition()
GUESTS = {}                 # oturum anahtarı -> Misafir
LOCAL_PLAYERS = {}                   # oturum anahtarı -> Yerel (çoklu istemcinin ek oyuncuları)
FAILED = {}                     # adres -> [yanlış şifre sayısı, kilidin bitişi]
log = print


def equal(a, b):
    """Gizli değerlerin karşılaştırması (sabit süreli; str'de ASCII dışı karakter TypeError veriyordu)."""
    return hmac.compare_digest(str(a or '').encode('utf8'), str(b or '').encode('utf8'))


def configure(raw, logger=print):
    """game.main: --multiplayer ile açıldıysa (raw: OO_MULTIPLAYER ortam değişkeni)."""
    global log
    log = logger
    try:
        d = json.loads(raw or '{}')
    except ValueError:
        d = {}
    # yerel: sunucunun kendi oyuncusunun oturumu (panel her açılışta üretir, kendi web.py'sine de verir). Sabit 'localtest'
    # tünelle açılan sunucuda (bağlantılar 127.0.0.1'den görünür) şifresiz girişti
    SETTINGS.update(acik=True, sifre=str(d.get('sifre') or ''), en_cok=max(1, min(16, int(d.get('en_cok') or 4))),
                anahtar=d.get('anahtar') or None, kod=str(d.get('kod') or ''), adres=str(d.get('adres') or '0.0.0.0'),
                yerel=str(d.get('yerel') or '') or secrets.token_urlsafe(24), misafir=bool(d.get('misafir', True)))


def is_local(sid):
    """LoginRequest'in sessionID'si sunucunun kendi oyuncusunun mu."""
    return bool(SETTINGS['yerel']) and equal(sid, SETTINGS['yerel'])


def is_open():
    return SETTINGS['acik']


# ------------------------------------------------------------------ misafirler
def convert_ids(x, old, new_):
    """Kayıttaki oyuncu kimliklerini değiştirir (yerinde): pilot, klan haberi ve mesajı ('kim'), posta (sender_id, alici_idler),
    müzayede, klan hesabı (balanceUserId). Yalnız adı kimlik olan alanlarda: para ve sayaçlara dokunulmaz."""
    if isinstance(x, dict):
        for k, v in x.items():
            has_id = k == 'kim' or k.lower().endswith(('id', 'ids', 'idler'))
            if has_id and v == old and not isinstance(v, bool):
                x[k] = new_
            elif has_id and isinstance(v, list):
                x[k] = [new_ if (e == old and not isinstance(e, bool)) else e for e in v]
                for e in x[k]:
                    convert_ids(e, old, new_)
            else:
                convert_ids(v, old, new_)
    elif isinstance(x, list):
        for e in x:
            convert_ids(e, old, new_)


class GuestProfile(PF.Profile):
    """Misafirin kaydı: dosya yerine bellekte; her kayıt (oyunun 10 sn'lik kaydı) yeni bir sürüm yayımlar (uzun yoklamaya)."""

    def __init__(self, seed, d, guest):
        self.guest = guest
        super().__init__(seed, path=os.path.join(PTH.LOGS, 'misafir_yok.json'), d=d)   # yol hiç yazılmaz

    def save(self, force=False):
        with self.lock:
            if not (self.dirty or force):
                return
            for k in range(5):                    # oturum profile kilitsiz yazıyor (Profil.save gibi)
                try:
                    text = json.dumps(self.d, ensure_ascii=False)
                    break
                except RuntimeError:
                    if k == 4:
                        raise
                    time.sleep(0.01)
            self.dirty = False
        self.guest.publish(text)


class Guest:
    def __init__(self, token, key, uid, original_uid, address, ip):
        self.token, self.key, self.uid, self.original_uid = token, key, uid, original_uid
        self.address, self.ip = address, ip
        self.profile = None
        self.text = None             # son yayımlanan kaydın JSON'u (sunucudaki kimlikle)
        self.version = 0
        self.session = None           # bağlı oyun oturumu (game.Session)
        self.entry = time.time()
        self.last = time.time()        # son yoklama ya da bağlantı
        self.finished = False            # bitti: oyuna girilemez; son hâl BITIS_SN boyunca alınabilir
        self.end_time = 0.0

    def publish(self, text):
        with COND:
            self.text, self.version = text, self.version + 1
            COND.notify_all()

    def export(self):
        """Misafirin kendi kimliğiyle kaydı (misafirin paneli yuvasına yazar)."""
        d = json.loads(self.text)
        convert_ids(d, self.uid, self.original_uid)
        return d

    def summary(self):
        p = self.profile.d if self.profile else {}
        pl = p.get('pilot') or {}
        return {'oturum': self.token[:8], 'ad': pl.get('userName', '?'), 'seviye': pl.get('level', 1), 'ip': self.ip,
                'bagli': self.session is not None, 'giris': int(self.entry)}


def _new_uid(full):
    while True:
        u = random.randrange(UID_LOWER, UID_UPPER)
        if u not in full:
            return u


def valid_profile(d):
    """Gönderilen kayıt oynanabilir mi -> hata metni ya da None."""
    if not isinstance(d, dict):
        return 'kayıt bir JSON nesnesi değil'
    pl, g, k = d.get('pilot'), d.get('gemi'), d.get('konum')
    if not (isinstance(pl, dict) and isinstance(g, dict) and isinstance(k, dict)):
        return 'kayıtta pilot, gemi ya da konum yok'
    if not isinstance(pl.get('userId'), int) or isinstance(pl.get('userId'), bool) or not str(pl.get('userName') or '').strip():
        return 'pilotun kimliği ya da adı yok'
    if not all(isinstance(k.get(a), (int, float)) for a in ('mapId', 'x', 'y')):
        return 'kayıttaki konum geçersiz'
    return None


def login(body, ip, seed, server_uid, main=None):
    """POST /misafir/giris -> (durum kodu, yanıt). ana: sunucunun kendi profili (adı başka oyuncuyla aynı olamaz)."""
    if int(body.get('surum') or 0) != PROTOCOL:
        return 409, {'hata': 'surum', 'mesaj': 'Hesap gönderiminin sürümü farklı (sunucu %d): ikiniz de paneli güncelleyin.' % PROTOCOL}
    if SETTINGS['sifre']:
        now = time.time()
        with COND:
            h = FAILED.get(ip)
            if h and h[1] > now:
                return 429, {'hata': 'bekle', 'mesaj': 'Çok fazla yanlış şifre: %d saniye sonra yeniden dene.' % (h[1] - now + 1)}
        if not equal(body.get('sifre'), SETTINGS['sifre']):
            with COND:
                h = FAILED.setdefault(ip, [0, 0])
                h[0] += 1
                if h[0] >= ATTEMPT_LIMIT:
                    h[:] = [0, now + LOCK_SEC]
                    log('arkadaş: %s için yanlış şifre sınırı, %d sn kilit' % (ip, LOCK_SEC))
            return 403, {'hata': 'sifre', 'mesaj': 'Katılma şifresi yanlış.'}
        with COND:
            FAILED.pop(ip, None)
    key = str(body.get('anahtar') or '')
    if len(key) < 16:
        return 400, {'hata': 'anahtar', 'mesaj': 'Misafir anahtarı eksik.'}
    with COND:
        old = next((m for m in GUESTS.values() if equal(m.key, key) and not m.finished), None)
        if old:                                  # yeniden giriş: sunucudaki son hâl sürer
            old.last, old.ip = time.time(), ip
            old.address = str(body.get('adres') or old.address)
            log('misafir yeniden geldi: %s (%s)' % (old.summary()['ad'], ip))
            return 200, {'oturum': old.token, 'uid': old.uid, 'surum': old.version, 'devam': True}
        if sum(1 for m in GUESTS.values() if not m.finished) >= SETTINGS['en_cok']:
            return 503, {'hata': 'dolu', 'mesaj': 'Sunucu dolu (en çok %d misafir).' % SETTINGS['en_cok']}
    d = body.get('profil')
    err = valid_profile(d)
    if err:
        return 400, {'hata': 'profil', 'mesaj': 'Kayıt geçersiz: %s.' % err}
    name = str((d.get('pilot') or {}).get('userName') or '').strip().lower()
    with COND:
        names = {_name(m.profile) for m in GUESTS.values() if not m.finished and m.profile is not None} |             {_name(y.profile) for y in LOCAL_PLAYERS.values()} | ({_name(main)} if main is not None else set())
    if name in names:                               # sohbet, posta, grup, rehber ve klan oyuncuyu adıyla bulur (yerel_ekle gibi)
        return 409, {'hata': 'ad', 'mesaj': 'Sunucuda "%s" adlı bir pilot zaten var: aynı adla iki oyuncu sohbette, postada, grupta ve '
                                            'klanda karışır. Pilot adını değiştirip yeniden katıl.' % d['pilot']['userName']}
    with COND:
        uid = _new_uid({server_uid} | {m.uid for m in GUESTS.values()} | {y.uid for y in LOCAL_PLAYERS.values()})
        m = Guest(secrets.token_urlsafe(18), key, uid, d['pilot']['userId'], str(body.get('adres') or ''), ip)
        convert_ids(d, m.original_uid, uid)
        m.profile = GuestProfile(seed, d, m)
        m.publish(json.dumps(m.profile.d, ensure_ascii=False))
        GUESTS[m.token] = m
    log('misafir geldi: %s (%s), sunucudaki kimlik %d' % (d['pilot'].get('userName'), ip, uid))
    return 200, {'oturum': m.token, 'uid': uid, 'surum': m.version, 'devam': False}


def _guest(q):
    """Oturum ve anahtar tutan misafir ya da None."""
    with COND:
        m = GUESTS.get(str(q.get('oturum') or ''))
    if m and equal(m.key, q.get('anahtar')):
        return m
    return None


def poll_profile(q):
    """GET /misafir/profil: N'den yeni sürüm gelene ya da süre dolana dek bekler."""
    m = _guest(q)
    if not m:
        return 404, {'hata': 'oturum', 'mesaj': 'Bu sunucuda böyle bir misafir oturumu yok.'}
    try:
        have, wait = int(q.get('surum') or 0), min(WAIT_MAX, max(0.0, float(q.get('bekle') or 0)))
    except ValueError:
        return 400, {'hata': 'istek'}
    end = time.time() + wait
    with COND:
        while m.version <= have and not m.finished and time.time() < end:
            COND.wait(max(0.05, end - time.time()))
        m.last = time.time()
        out = {'surum': m.version, 'bagli': m.session is not None, 'bitti': m.finished}
        new_ = m.version > have
    if new_:
        out['profil'] = m.export()
    return 200, out


def exit(q, close_session):
    """POST /misafir/cikis: bağlıysa oyun bağlantısı kapanır, son hâl verilir, kayıt silinir."""
    m = _guest(q)
    if not m:
        return 404, {'hata': 'oturum', 'mesaj': 'Bu sunucuda böyle bir misafir oturumu yok.'}
    if not m.finished:
        finish(m, close_session, 'misafir ayrıldı')
    return 200, {'surum': m.version, 'profil': m.export(), 'bitti': True}


def finish(m, close_session, reason):
    s = m.session
    if s is not None:
        close_session(s)                           # oturum kapanırken son kaydı yayımlar (game.Session.run)
        end = time.time() + 5
        while m.session is not None and time.time() < end:
            time.sleep(0.05)
    if m.profile:
        m.profile.save(force=True)
    with COND:
        m.finished, m.end_time = True, time.time()
        COND.notify_all()
    log('misafir oturumu bitti (%s): %s' % (reason, m.summary()['ad']))


def find(sid):
    """LoginRequest'in sessionID'si -> misafir (yoksa None)."""
    with COND:
        m = GUESTS.get(str(sid or ''))
        return m if m and not m.finished else None


def entries():
    with COND:
        return [m for m in GUESTS.values() if not m.finished]


def tick(close_session):
    """Bağlı olmayan ve uzun süredir yoklanmayan misafir oturumları biter, bitenlerin kaydı bırakılır (game.autosave). Ek oyuncular
    da: panel istemcisi kapanınca bırakır (yerel_cikar); panel kapanmışsa bağlanmayan ek oyuncu BOSTA_SN sonra bırakılır."""
    now = time.time()
    for m in entries():
        if m.session is None and now - m.last > IDLE_SEC:
            finish(m, close_session, 'uzun süre bağlanmadı')
    with COND:
        for k in [k for k, m in GUESTS.items() if m.finished and now - m.end_time > END_SEC]:
            del GUESTS[k]
    for y in local_players():
        if y.session is None and now - y.last > IDLE_SEC:
            finish_local(y, close_session, 'uzun süre bağlanmadı')


def shutdown(wait=2.0):
    """Sunucu kapanıyor: misafirlerin son hâli yayımlanır, yoklamalar bitti diye yanıtlanır; panellerin almasına kısa süre."""
    ms = entries()
    for m in ms:
        if m.profile:
            m.profile.save(force=True)
    with COND:
        for m in ms:
            m.finished, m.end_time = True, time.time()
        COND.notify_all()
    if ms:
        time.sleep(wait)


# ------------------------------------------------------------------ çoklu istemci: bu bilgisayardaki öteki kayıtlar
class LocalProfile(PF.Profile):
    """Ek oyuncunun kaydı: kendi yuvasının dosyası (Profil gibi yazılır). Kimliği sunucudaki başka bir oyuncununkiyle aynıysa (kayıtlar
    tohumun kimliğiyle başlar) bellekte kayda göre sabit geçici kimlik alır; dosyaya asıl kimlikle yazılır (_metin)."""

    def __init__(self, seed, path, full, save):
        self.temporary = None
        super().__init__(seed, path=path)
        self.original_uid = self.user_id
        if self.original_uid in full:
            n = LOCAL_UPPER - LOCAL_LOWER
            u = LOCAL_LOWER + zlib.crc32(save.encode('utf8')) % n
            while u in full:
                u = LOCAL_LOWER + (u - LOCAL_LOWER + 1) % n
            self.temporary = u
            convert_ids(self.d, self.original_uid, u)

    def _text(self):
        if self.temporary is None:
            return super()._text()
        d = json.loads(json.dumps(self.d, ensure_ascii=False))
        convert_ids(d, self.temporary, self.original_uid)
        return json.dumps(d, ensure_ascii=False, indent=1)


class LocalPlayer:
    def __init__(self, token, save, route, profile):
        self.token, self.save, self.route, self.profile = token, save, route, profile
        self.session = None           # bağlı oyun oturumu (game.Session)
        self.entry = self.last = time.time()
        self.finished = False            # bırakılıyor: girilemez; bağlantı kapanınca kayıttan çıkar (game.Session.run)

    @property
    def uid(self):
        return self.profile.user_id

    def summary(self):
        pl = self.profile.d.get('pilot') or {}
        return {'oturum': self.token[:8], 'kayit': self.save, 'ad': pl.get('userName', '?'), 'seviye': pl.get('level', 1),
                'uid': self.uid, 'bagli': self.session is not None, 'giris': int(self.entry)}


def _same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _name(profile):
    return str(((profile.d if profile else {}).get('pilot') or {}).get('userName') or '').strip().lower()


def add_local(body, seed, main):
    """POST /yerel/ekle -> (durum kodu, yanıt). ana: sunucunun kendi profili (game.PROFIL)."""
    save, route = str(body.get('kayit') or ''), str(body.get('yol') or '')
    if not re.fullmatch(r'[a-z0-9_]{1,40}', save) or os.path.basename(route) != 'profil.json' or not os.path.isfile(route):
        return 400, {'hata': 'kayit', 'mesaj': 'Kayıt bulunamadı.'}
    if not os.path.normcase(os.path.realpath(route)).startswith(os.path.normcase(os.path.realpath(PTH.SAVES)) + os.sep):
        return 400, {'hata': 'kayit', 'mesaj': 'Kayıt, kayıt klasöründe değil.'}
    if _same_path(route, main.path):
        return 409, {'hata': 'ana', 'mesaj': 'Bu kayıt ana istemcide açık.'}
    with COND:
        old = next((y for y in LOCAL_PLAYERS.values() if _same_path(y.route, route)), None)
        if old and old.finished:
            return 409, {'hata': 'kapaniyor', 'mesaj': 'Bu kaydın önceki istemcisi kapanıyor: birkaç saniye sonra yeniden dene.'}
        if old:                                  # istemci yeniden açıldı: sunucudaki oturum sürer
            old.last = time.time()
            return 200, {'oturum': old.token, 'uid': old.uid, 'devam': True}
        if sum(1 for y in LOCAL_PLAYERS.values() if not y.finished) >= LOCAL_MAX:
            return 503, {'hata': 'dolu', 'mesaj': 'Sunucuda en çok %d ek istemci açılabilir.' % LOCAL_MAX}
        full = {main.user_id} | {m.uid for m in GUESTS.values() if not m.finished} | {y.uid for y in LOCAL_PLAYERS.values()}
    try:
        p = LocalProfile(seed, route, full, save)
    except (OSError, ValueError, KeyError, TypeError) as e:
        return 400, {'hata': 'profil', 'mesaj': 'Kayıt okunamadı: %s' % e}
    err = valid_profile(p.d)
    if err:
        return 400, {'hata': 'profil', 'mesaj': 'Kayıt geçersiz: %s.' % err}
    with COND:
        names = {_name(main)} | {_name(m.profile) for m in GUESTS.values() if not m.finished} | {_name(y.profile) for y in LOCAL_PLAYERS.values()}
        if _name(p) in names:                       # sohbet, posta, grup ve rehber oyuncuyu adıyla bulur
            return 409, {'hata': 'ad', 'mesaj': 'Sunucuda "%s" adlı bir pilot zaten var: aynı adla iki oyuncu sohbette, postada ve '
                                                'grupta karışır. Bu kaydın pilot adını değiştir.' % p.d['pilot']['userName']}
        if any(_same_path(y.route, route) for y in LOCAL_PLAYERS.values()):
            return 409, {'hata': 'kapaniyor', 'mesaj': 'Bu kayıt az önce açıldı.'}
        y = LocalPlayer(secrets.token_urlsafe(18), save, route, p)
        LOCAL_PLAYERS[y.token] = y
    log('ek oyuncu: %s (kayıt %s), sunucudaki kimlik %d%s' % (p.d['pilot'].get('userName'), save, y.uid,
                                                             ' (geçici; asıl %d)' % p.original_uid if p.temporary else ''))
    return 200, {'oturum': y.token, 'uid': y.uid, 'devam': False}


def finish_local(y, close_session, reason):
    """Ek oyuncuyu bırak: bağlantısı kapanır, son hâl yuvaya yazılır, kayıttan çıkar (bağlantı 5 sn'de kapanmazsa çıkışı oturum yapar)."""
    with COND:
        y.finished = True
    s = y.session
    if s is not None:
        close_session(s)                           # oturum kapanırken son hâli yazar (game.Session.run)
        end = time.time() + 5
        while y.session is not None and time.time() < end:
            time.sleep(0.05)
    try:
        y.profile.save(force=True)
    except Exception as e:                        # noqa: BLE001 (dosya kilitli: oturumun son kaydı yazmıştır)
        log('ek oyuncunun son kaydı yazılamadı: %r' % e)
    with COND:
        if y.session is None:
            LOCAL_PLAYERS.pop(y.token, None)
    log('ek oyuncu bırakıldı (%s): %s' % (reason, y.summary()['ad']))


def remove_local(b, close_session):
    """POST /yerel/cikar."""
    with COND:
        y = LOCAL_PLAYERS.get(str(b.get('oturum') or ''))
    if not y:
        return 404, {'hata': 'oturum', 'mesaj': 'Bu sunucuda böyle bir ek oyuncu yok.'}
    finish_local(y, close_session, 'istemci kapandı')
    return 200, {'tamam': True}


def find_local(sid):
    """LoginRequest'in sessionID'si -> ek oyuncu (yoksa ya da bırakılıyorsa None)."""
    with COND:
        y = LOCAL_PLAYERS.get(str(sid or ''))
        return y if y and not y.finished else None


def local_players():
    with COND:
        return [y for y in LOCAL_PLAYERS.values() if not y.finished]


# ------------------------------------------------------------------ gönderme kuyruğu
class SendQueue:
    """Arkadaş sunucusunda her bağlantının gönderme kuyruğu: dünya kilidi altındaki gönderim ağı beklemez (yavaş bir misafir öteki
    oyuncuların döngüsünü durdurmasın). Sıra korunur; birikim SINIR'ı aşarsa bağlantı kapanır."""
    LIMIT = 16 * 1024 * 1024

    def __init__(self, sock):
        self.sock = sock
        self.cond = threading.Condition()
        self.parts = collections.deque()
        self.size = 0
        self.closed = False
        self.finish = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def put(self, data):
        with self.cond:
            if self.closed or self.finish:
                raise ConnectionError('bağlantı kapandı')
            self.parts.append(data)
            self.size += len(data)
            if self.size > self.LIMIT:
                self._cut()
                raise ConnectionError('gönderme kuyruğu doldu (istemci okumuyor)')
            self.cond.notify()

    def run(self):
        while True:
            with self.cond:
                while not self.parts and not self.closed and not self.finish:
                    self.cond.wait()
                if self.closed:
                    return
                if not self.parts:             # bitir: kalanlar gitti, bağlantı kapanır
                    self._cut(shutdown=True)
                    return
                data = b''.join(self.parts)
                self.parts.clear()
                self.size = 0
            try:
                self.sock.sendall(data)
            except OSError:
                with self.cond:
                    self._cut()
                return

    def close(self):
        """Kuyruktakiler gidince bağlantıyı kapat (çıkış, misafiri çıkarma)."""
        with self.cond:
            self.finish = True
            self.cond.notify()

    def _cut(self, shutdown=False):
        self.closed = True
        self.cond.notify_all()                   # bekleyen calis uyansın (taşmada takılı kalıyordu)
        try:
            if shutdown:
                self.sock.shutdown(socket.SHUT_RDWR)
            else:
                self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------------------ HTTP (oyun portunda)
def is_http(first):
    return first[:4] in (b'GET ', b'POST', b'HEAD')


def _read(c):
    """-> (yöntem, yol, başlıklar, gövde) ya da None."""
    buf = b''
    while b'\r\n\r\n' not in buf:
        d = c.recv(65536)
        if not d:
            return None
        buf += d
        if len(buf) > HEADER_LIMIT and b'\r\n\r\n' not in buf[:HEADER_LIMIT]:
            return None
    head, body = buf.split(b'\r\n\r\n', 1)
    lines = head.decode('latin-1').split('\r\n')
    try:
        method, path, _ = lines[0].split(' ', 2)
    except ValueError:
        return None
    hdr = {}
    for ln in lines[1:]:
        if ':' in ln:
            k, v = ln.split(':', 1)
            hdr[k.strip().lower()] = v.strip()
    n = int(hdr.get('content-length') or 0)
    if n < 0 or n > BODY_LIMIT:
        return None
    while len(body) < n:
        d = c.recv(min(1 << 20, n - len(body)))
        if not d:
            return None
        body += d
    if hdr.get('content-encoding') == 'gzip' and body:
        z = zlib.decompressobj(16 + zlib.MAX_WBITS)
        body = z.decompress(body, BODY_LIMIT)            # sınırlı açılır (sıkıştırma bombası)
        if z.unconsumed_tail:
            return None
    return method, path, hdr, body


def _reply(c, code, obj, gz=False):
    data = json.dumps(obj, ensure_ascii=False).encode('utf8')
    extra = ''
    if gz and len(data) > 2048:
        data = gzip.compress(data, 6)
        extra = 'Content-Encoding: gzip\r\n'
    status = {200: 'OK', 400: 'Bad Request', 403: 'Forbidden', 404: 'Not Found', 409: 'Conflict', 429: 'Too Many Requests',
              503: 'Service Unavailable'}.get(code, 'OK')
    c.sendall(('HTTP/1.1 %d %s\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: %d\r\n%sConnection: close\r\n'
               'X-DarkOrbit: arkadas\r\n\r\n' % (code, status, len(data), extra)).encode('latin-1') + data)


def http(c, addr, game):
    """Oyun portuna gelen HTTP isteği (hesap gönderimi ve yönetim). game: game.py modülü."""
    try:
        c.settimeout(WAIT_MAX + 15)
        req = _read(c)
        if not req:
            return
        method, path, hdr, body = req
        u = urlparse(path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        gz = 'gzip' in hdr.get('accept-encoding', '')
        try:
            b = json.loads(body.decode('utf8') or '{}') if method == 'POST' else {}
        except ValueError:
            return _reply(c, 400, {'hata': 'json'})
        if not isinstance(b, dict):
            return _reply(c, 400, {'hata': 'json'})
        ip = addr[0]
        local = ip in ('127.0.0.1', '::1')
        management = local and SETTINGS['anahtar'] and equal(b.get('anahtar'), SETTINGS['anahtar'])
        if u.path.startswith('/misafir/') and not SETTINGS['misafir']:
            code, out = 403, {'hata': 'kapali', 'mesaj': 'Bu sunucu misafir kabul etmiyor.'}
        elif u.path == '/yerel/ekle' and method == 'POST' and management:
            code, out = add_local(b, game.TEMPLATE.entry.get('tohum'), game.PROFILE)
        elif u.path == '/yerel/cikar' and method == 'POST' and management:
            code, out = remove_local(b, game.close_session)
        elif u.path == '/yerel/oturum' and local:
            y = find_local(q.get('oturum'))
            code, out = (200, {'uid': y.uid, 'yol': y.route, 'kayit': y.save}) if y else (404, {'hata': 'oturum'})
        elif u.path == '/misafir/bilgi':
            code, out = 200, game.server_info()
        elif u.path == '/misafir/giris' and method == 'POST':
            code, out = login(b, ip, game.TEMPLATE.entry.get('tohum'), game.PROFILE.user_id, game.PROFILE)
        elif u.path == '/misafir/profil':
            code, out = poll_profile(q)
        elif u.path == '/misafir/cikis' and method == 'POST':
            code, out = exit(b, game.close_session)
        elif u.path == '/yonetim/kick' and method == 'POST' and management:
            m = next((x for x in entries() if x.token.startswith(str(b.get('oturum') or '-'))), None)
            if m:
                finish(m, game.close_session, 'sunucu çıkardı')
            code, out = (200, {'tamam': True}) if m else (404, {'hata': 'oturum'})
        else:
            code, out = 404, {'hata': 'yok'}
        if u.path not in ('/misafir/profil', '/yerel/oturum'):
            log('arkadaş: %s %s <- %s -> %d' % (method, u.path, ip, code))
        _reply(c, code, out, gz)
    except (OSError, ValueError, zlib.error) as e:      # bozuk gzip gövdesi de (yanıtsız kopuyordu)
        log('arkadaş: istek hatası %s: %r' % (addr[0], e))
    finally:
        try:
            c.close()
        except OSError:
            pass
