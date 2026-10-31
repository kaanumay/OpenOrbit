"""Yerel sohbet sunucusu (yol haritası Aşama 10): istemcinin "AChat" sohbeti, TCP 7771.

İstemci sohbet adresini girişteki ChatParamCommand'dan (chat_ip) alır. Kayıttaki şablon resmî sohbet sunucusunu gösteriyordu ve
istemci yerel oyunda oraya bağlanıyordu (istemci günlüğü: "achat:connected"); artık login_replace ile bu sunucuya yönlenir.

Bağlantı başında istemci 2 baytlık tanışma gönderir: 0x2A ('*') + 0x01 (TcpEndpoint2ServerNetLayer.Open); sunucu da bir
0x10 tanışma çerçevesi gönderir (istemcinin görünen adresi, UTF-8). İstemci InitConnector'ı ancak bu çerçeve gelince yollar
(TcpEndpoint2ServerNetLayer.Write: LowLevelIntroductionMessage -> bağlantı işleyicisi). Canlı deneme 2026-10-17: ikisi de
eksikti, gerçek istemcide sohbet hiç kurulmuyordu (testlerin sahte istemcisi doğrudan InitConnector gönderiyordu).
Çerçeve (istemcinin APServiceStorm.Net.Codec.APlay kodlayıcısı): 1 bayt tür + int32 BE uzunluk + yük
  0x50 'P'  UTF-8 JSON (sunucu -> istemci bunu kullanır)
  0x53 'S'  ikili JSON (istemci -> sunucu; JSONWriter: nesne = int32 sayı + [int32 uzunluk + UTF-8 ad, değer]…)
  0x61 'a'  gzip'li JSON (istemci göndermiyor)
  0x10 tanışma (UTF-8), 0x11 ping (sunucu -> istemci: int64 zaman + int32 gecikme), 0x12 pong (int64)
İkili JSON değer türleri (tür baytı + değer): 0 null, 1 bool (1/2), 2 dizi (int32 sayı), 3 int32, 4 nesne, 5 metin (int32 + UTF-8),
6 bayt, 7 int64, 8 float32. Sayılar big-endian.

Infinicast mesajları JSON nesnesi, 't' türü (Connector2Eps/Eps2Connector dönüştürücüleri): 1 Request, 2 RequestResponse,
3 InitConnector, 8 Message, 14 RemoveHandlers, 15 RegisterHandler; ötekiler (30 GetListeningList …) istek kimliğiyle yanıtlanır.
Akış (istemcinin AChatGameClientConnection'ı):
  1. InitConnector {space: achat, role: chatter} -> InitConnector {endpointObject {path: /endpoint/<uç>/, endpoint: <uç>}}
  2. istemci uç noktasının serverStatus/ ve changePredefinedRoom/ yollarına Message işleyicisi kaydeder (her kayıt
     RequestResponse {requestId} ile onaylanır); onaylanınca uç kimliğini oyun sunucusuna ChatAuthenticateUserRequest ile bildirir
  3. oyun sunucusu (game.py) authenticate() çağırır: serverStatus'a {type: loggedIn}, changePredefinedRoom'a her oda için
     {roomType, roomClass, newRoomName}; istemci /room/<roomClass>/<newRoomName>/ yoluna işleyici kaydeder ve odayı açar
     (burada roomClass = roomType)
  4. oyuncunun mesajı: Message {path: oda, data: {msg}} -> odayı dinleyenlere Message {path, data {msg, sentAt},
     endpointObject {path, endpoint, data: gönderenin bilgisi}}
Gönderenin bilgisi (ChatUserVo.FromJson): userId = görünen ad, id = sayısal kimlik, globalId, role (chatter/system/mod),
clanTag, factionId, instanceId. Oda türleri (ChatRoomVo): global, faction, clan, group (sekme adları istemcide çevrilir).

Özel odalar (resmî forum 127334: /create, /close, /invite, /join, /leave; istemcinin AChatGameClientConnection'ı, il2cpp 1.1.115):
  /create <ad> [kullanıcı] -> Request /roomSvc/usr/createRoom/ {roomName: 'private_<ad>'}; yanıt gelince istemci odayı modelinde
  arar (GetRoomByName), bu yüzden sunucu önce changePredefinedRoom ile odayı verir (roomType = roomName: tür başına tek oda tutulur,
  roomClass 'usr'; ChatRoomVo 'private_' önekini atıp adı gösterir). /invite -> inviteUser {roomName, whisperId}; davet edilenin
  /userRoomInvite/<whisperId>/ yoluna Message {roomName, invitingUserData: gönderenin bilgisi}. Kabul -> acceptInvite {roomName};
  /close -> close {roomName} (yalnız kurucu); /leave -> removeUser {roomName, whisperId}. Hata yanıtı errorMsg ile (istemcinin
  ChatIcErrorTranslator'ı: 'Not creator of this channel' -> inviteErrorNotYourRoom, 'user no longer logged in' ->
  inviteErrorUserNotFound); başarı yanıtı data {success: true}. /report -> Request <oda yolu>/reportUser {targetUserId, targetGlobalId, reason, reasonKey, message}:
  server/logs/sohbet_raporlari.jsonl dosyasına yazılır (forum 132515).
Duyurular (duyuru()): sistem kullanıcısının (role system) mesajı. İstemci sistem mesajını yerelleştirme anahtarı sayar
("anahtar|eski|yeni|…": anahtarın metnini çevirip çiftleri değiştirir; bilinmeyen anahtar boş çıkar). Bu yüzden metin
'dochat.chat.system' anahtarının çevirisinin ("System"/"Sistem") yerine konur.
"""
import json, os, socket, struct, threading, time

PORT = 7771
P_JSON, P_BIN, P_GZIP, P_INTRO, P_PING, P_PONG = 0x50, 0x53, 0x61, 0x10, 0x11, 0x12
T_REQUEST, T_RESPONSE, T_INIT, T_MESSAGE, T_REMOVE, T_REGISTER = 1, 2, 3, 8, 14, 15
T_LISTENING_LIST = 30             # GetListeningList: sohbetin /users komutu (oda dinleyenleri; Infinicast ListenerQueryExecutor)
PING_SN = 15
SISTEM_ANAHTARI = 'dochat.chat.system'
SISTEM_METNI = {'en': 'System', 'tr': 'Sistem'}       # istemcinin çevirisi (resource_chat); başka dilde ikisi de denenir
ODA_SINIRI = 3                    # oyuncu başına özel oda (uyarlama: istemcinin noMorePrivateRoomsAllowed metni var, sayı yok)
SEL_SINIRI, SEL_SN = 8, 10        # sunucu tarafı sel denetimi: 10 sn'de 8'den çok mesaj atılır (uyarlama; istemci floodWarning kendi uyarır)
RAPOR_YOLU = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'sohbet_raporlari.jsonl')


# ------------------------------------------------------------ APlay çerçevesi ve ikili JSON
def frame(obj):
    """Sunucu -> istemci: düz JSON çerçevesi."""
    data = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf8')
    return bytes([P_JSON]) + struct.pack('>i', len(data)) + data


def ping_frame(ms):
    return bytes([P_PING]) + struct.pack('>iqi', 12, ms, 0)


def read_value(b, i):
    t = b[i]
    i += 1
    if t == 0:
        return None, i
    if t == 1:
        return b[i] == 2, i + 1
    if t == 2:
        n, = struct.unpack_from('>i', b, i)
        i += 4
        out = []
        for _ in range(n):
            v, i = read_value(b, i)
            out.append(v)
        return out, i
    if t == 3:
        return struct.unpack_from('>i', b, i)[0], i + 4
    if t == 4:
        return read_object(b, i)
    if t == 5:
        n, = struct.unpack_from('>i', b, i)
        return b[i + 4:i + 4 + n].decode('utf8'), i + 4 + n
    if t == 6:
        return b[i], i + 1
    if t == 7:
        return struct.unpack_from('>q', b, i)[0], i + 8
    if t == 8:
        return struct.unpack_from('>f', b, i)[0], i + 4
    raise ValueError('ikili JSON: bilinmeyen tür %d' % t)


def read_object(b, i=0):
    n, = struct.unpack_from('>i', b, i)
    i += 4
    out = {}
    for _ in range(n):
        k, = struct.unpack_from('>i', b, i)
        key = b[i + 4:i + 4 + k].decode('utf8')
        i += 4 + k
        out[key], i = read_value(b, i)
    return out, i


def write_value(v):
    """İstemcinin JSONWriter'ı (testlerde istemciyi taklit etmek için)."""
    if v is None:
        return b'\x00'
    if isinstance(v, bool):
        return bytes([1, 2 if v else 1])
    if isinstance(v, int):
        return b'\x03' + struct.pack('>i', v)
    if isinstance(v, float):
        return b'\x08' + struct.pack('>f', v)
    if isinstance(v, str):
        d = v.encode('utf8')
        return b'\x05' + struct.pack('>i', len(d)) + d
    if isinstance(v, dict):
        return b'\x04' + write_object(v)
    if isinstance(v, (list, tuple)):
        return b'\x02' + struct.pack('>i', len(v)) + b''.join(write_value(x) for x in v)
    raise TypeError(type(v))


def write_object(o):
    out = [struct.pack('>i', len(o))]
    for k, v in o.items():
        d = k.encode('utf8')
        out += [struct.pack('>i', len(d)), d, write_value(v)]
    return b''.join(out)


def intro_frame(address):
    """Sunucunun tanışma çerçevesi (0x10 + uzunluk + UTF-8 adres)."""
    data = address.encode('utf8')
    return bytes([P_INTRO]) + struct.pack('>i', len(data)) + data


def client_frame(obj):
    """İstemci -> sunucu çerçevesi ('S' + ikili JSON)."""
    data = write_object(obj)
    return bytes([P_BIN]) + struct.pack('>i', len(data)) + data


TANISMA = b'*'                # istemcinin bağlantı başındaki baytları (protokol işareti + sürüm)


class Cozucu:
    """Akıştan çerçeveler: feed(bayt) -> [(tür, yük)]; JSON türlerinde yük sözlük. tanisma=True: akışın başındaki istemci
    tanışması (TANISMA) atlanır (sunucu tarafı); istemci tarafı (testler) False."""
    def __init__(self, tanisma=False):
        self.buf = b''
        self.bekle_tanisma = tanisma

    def feed(self, data):
        self.buf += data
        out = []
        if self.bekle_tanisma:
            if len(self.buf) < len(TANISMA):
                return out
            if self.buf.startswith(TANISMA):
                self.buf = self.buf[len(TANISMA):]
            self.bekle_tanisma = False
        while len(self.buf) >= 5:
            kind = self.buf[0]
            n, = struct.unpack_from('>i', self.buf, 1)
            if n < 0 or len(self.buf) < 5 + n:
                break
            body, self.buf = self.buf[5:5 + n], self.buf[5 + n:]
            if kind == P_BIN:
                out.append((kind, read_object(body)[0]))
            elif kind == P_JSON:
                out.append((kind, json.loads(body.decode('utf8'))))
            else:
                out.append((kind, body))
        return out


# ------------------------------------------------------------ sunucu
class Baglanti:
    def __init__(self, srv, sock, ep):
        self.srv, self.sock, self.ep = srv, sock, ep
        self.send_lock = threading.Lock()
        self.handlers = set()             # Message işleyicisi kayıtlı yollar
        self.user = None                  # authenticate() sonrası gönderen bilgisi
        self.dil = None
        self.pending = []                 # odası henüz kaydedilmemiş duyurular (oda türü, metin)
        self.gecmis = []                  # son mesaj zamanları (sel denetimi)
        self.alive = True

    @property
    def path(self):
        return '/endpoint/%s/' % self.ep

    def send(self, obj):
        self.send_raw(frame(obj))

    def send_raw(self, data):
        if self.srv.iz:                   # canlı test izi (game.py --kontrol): giden çerçeve
            self.srv.iz('->', data[0], data[5:])
        try:
            with self.send_lock:
                self.sock.sendall(data)
        except OSError:
            self.alive = False

    def run(self):
        dec = Cozucu(tanisma=True)
        try:
            while self.alive:
                data = self.sock.recv(65536)
                if not data:
                    break
                for kind, body in dec.feed(data):
                    if self.srv.iz:
                        self.srv.iz('<-', kind, body)
                    if kind in (P_BIN, P_JSON):
                        self.srv.on_message(self, body)
                    elif kind != P_PONG:
                        self.srv.log('sohbet: bilinmeyen çerçeve 0x%02x (%d bayt) %r' % (kind, len(body), bytes(body[:60])))
        except Exception as e:                  # bozuk çerçeve (struct.error, IndexError…) de: yoksa bağlantı conns'ta kalıyordu
            self.srv.log('sohbet: bağlantı hatası %r' % e)
        self.alive = False
        self.srv.drop(self)


class Sohbet:
    def __init__(self, log=print, port=PORT, adres='127.0.0.1'):
        self.log, self.port = log, port
        self.adres = adres                # arkadaş sunucusunda 0.0.0.0 (misafirler başka bilgisayarlardan bağlanır)
        self.lock = threading.RLock()
        self.conns = {}                   # uç kimliği -> Baglanti
        self.seq = 0
        self.sock = None
        self.running = False
        self.iz = None                    # canlı test izi: iz(yön, tür, yük) (game.py --kontrol bağlar)
        self.bot_kanca = None             # (yol, mesaj, gönderen) -> None: botlar oda mesajlarını okur (bot/toplum.kaydol)
        self.bot_fisilti = None           # (alıcının adı, mesaj, gönderen) -> alıcı bot muydu
        self.engel_kanca = None           # (gönderen, oda yolu, dil) -> bildirim ya da None: susturulan oyuncu (bot/moderasyon.py)
        self.odalar = {}                  # özel oda adı ('private_<ad>') -> {'kurucu': kimlik, 'uyeler': set, 'davetli': set}
        self.rapor_yolu = RAPOR_YOLU

    # -------------------------------------------------------- dinleme
    def start(self):
        """Dinlemeye başlar -> gerçek port (port 0 verilirse işletim sisteminin seçtiği); port doluysa None."""
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((self.adres, self.port))
        except OSError as e:
            self.log('sohbet: %d dinlenemedi (%r)' % (self.port, e))
            s.close()
            return None
        s.listen(5)
        self.sock, self.running = s, True
        self.port = s.getsockname()[1]
        threading.Thread(target=self.accept_loop, daemon=True).start()
        threading.Thread(target=self.ping_loop, daemon=True).start()
        self.log('sohbet listening %d' % self.port)
        return self.port

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except (OSError, AttributeError):
            pass
        with self.lock:
            conns = list(self.conns.values())
        for c in conns:
            c.alive = False
            try:
                c.sock.close()
            except OSError:
                pass

    def accept_loop(self):
        while self.running:
            try:
                sock, addr = self.sock.accept()
            except OSError:
                break
            with self.lock:
                self.seq += 1
                ep = 'yerel_sohbet_%d_%d' % (int(time.time()) % 100000, self.seq)
                c = Baglanti(self, sock, ep)
                self.conns[ep] = c
            self.log('sohbet: bağlantı %s' % ep)
            c.send_raw(intro_frame('%s:%d' % addr[:2]))       # istemci bunu görmeden InitConnector göndermez
            threading.Thread(target=c.run, daemon=True).start()

    def ping_loop(self):
        while self.running:
            time.sleep(PING_SN)
            with self.lock:
                conns = list(self.conns.values())
            for c in conns:
                c.send_raw(ping_frame(int(time.time() * 1000)))

    def drop(self, c):
        with self.lock:
            if self.conns.get(c.ep) is c:
                del self.conns[c.ep]
        try:
            c.sock.close()
        except OSError:
            pass
        self.log('sohbet: bağlantı kapandı %s' % c.ep)

    # -------------------------------------------------------- Infinicast
    def on_message(self, c, m):
        t, rid = m.get('t'), m.get('requestId')
        if t == T_INIT:
            c.send({'t': T_INIT, 'endpointObject': {'path': c.path, 'endpoint': c.ep}, 'requestId': rid or 0})
            return
        if t == T_REGISTER:
            if m.get('handlerType', 'Message') == 'Message' and m.get('path'):
                c.handlers.add(m['path'])
                if m['path'].startswith('/room/') and rid is not None:
                    c.send({'t': T_RESPONSE, 'requestId': rid})
                    rid = None
                    self.flush(c)
        elif t == T_REMOVE:
            c.handlers.discard(m.get('path'))
        elif t == T_MESSAGE:
            if (m.get('path') or '').startswith('/whisper/'):
                self.whisper(c, m['path'], m.get('data') or {}, rid)
                return
            self.relay(c, m.get('path') or '', m.get('data') or {})
        elif t == T_REQUEST:
            self.request(c, m)
            return
        elif t == T_LISTENING_LIST and rid is not None:
            c.send({'t': T_RESPONSE, 'requestId': rid, 'data': {'list': self.listeners(m.get('path') or '')}})
            return
        if rid is not None:
            c.send({'t': T_RESPONSE, 'requestId': rid})

    def listeners(self, path):
        """Odayı dinleyenler (istemci yanıtın data.list'inden okur: path, endpoint, data = kullanıcı bilgisi)."""
        with self.lock:
            conns = list(self.conns.values())
        return [{'path': x.path, 'endpoint': x.ep, 'data': x.user} for x in conns if x.user and path in x.handlers]

    def request(self, c, m):
        """Oda servisi (/roomSvc/usr/…) ve rapor (<oda>/reportUser) istekleri; hata errorMsg ile, başarı data.success (istemcinin
        yanıt geri çağrısı json['success']'i okur: yoksa NullReferenceException, canlı 2026-10-26)."""
        path, d, rid = m.get('path') or '', m.get('data') or {}, m.get('requestId', 0)
        self.log('sohbet: istek %s %s' % (path, json.dumps(d, ensure_ascii=False)[:200]))
        if not c.user:
            err = 'user no longer logged in'
        elif path.rstrip('/').endswith('/reportUser'):
            err = self.report(c, path, d)
        else:
            fn = {'/roomSvc/usr/createRoom/': self.oda_kur, '/roomSvc/usr/inviteUser/': self.oda_davet,
                  '/roomSvc/usr/acceptInvite/': self.oda_katil, '/roomSvc/usr/close/': self.oda_kapat,
                  '/roomSvc/usr/removeUser/': self.oda_ayril}.get(path)
            err = fn(c, str(d.get('roomName') or ''), d) if fn else 'unknown request'
        if err:
            c.send({'t': T_RESPONSE, 'requestId': rid, 'errorReason': 'invalid', 'errorMsg': err, 'errorPath': path})
        else:
            c.send({'t': T_RESPONSE, 'requestId': rid, 'data': {'success': True}})

    def report(self, c, path, d):
        """Sohbet raporu (/report): sunucu günlüğüne bir satır (forum 132515; tek oyunculuda moderatör yok)."""
        row = {'zaman': time.strftime('%Y-%m-%d %H:%M:%S'), 'raporlayan': c.user.get('userId'), 'oda': path.rsplit('/reportUser', 1)[0],
               **{k: d.get(k) for k in ('targetUserId', 'targetGlobalId', 'reason', 'reasonKey', 'message')}}
        os.makedirs(os.path.dirname(self.rapor_yolu), exist_ok=True)
        with self.lock, open(self.rapor_yolu, 'a', encoding='utf8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.log('sohbet: rapor %s -> %s (%s)' % (row['raporlayan'], row['targetUserId'], row['reasonKey'] or row['reason']))
        return None

    def oda_yolu(self, name):
        return '/room/usr/%s/' % name

    def oda_kur(self, c, name, d):
        me = c.user.get('id')
        if not name.startswith('private_') or len(name) <= len('private_') or '/' in name:
            return 'invalid room name'
        with self.lock:
            if name in self.odalar:
                return 'room already exists'
            if sum(o['kurucu'] == me for o in self.odalar.values()) >= ODA_SINIRI:
                return 'no more private rooms allowed'
            self.odalar[name] = {'kurucu': me, 'uyeler': {me}, 'davetli': set()}
        self.join(c, name, 'usr', name)
        return None

    def oda_davet(self, c, name, d):
        o = self.odalar.get(name)
        if not o or o['kurucu'] != c.user.get('id'):
            return 'Not creator of this channel'
        want = '/userroominvite/%s/' % str(d.get('whisperId') or '').lower()
        with self.lock:
            conns = [x for x in self.conns.values() if x.user and x is not c]
        hits = [(x, p) for x in conns for p in x.handlers if p.lower() == want]
        if not hits:                       # başka örnek kimliği ile dinleyen: adın kendisi (fısıltıdaki gibi)
            ad = '_' + want[len('/userroominvite/'):].split('_', 1)[-1]
            hits = [(x, p) for x in conns for p in x.handlers if p.lower().startswith('/userroominvite/') and p.lower().endswith(ad)]
        if not hits:
            return 'user no longer logged in'
        for x, p in hits:
            o['davetli'].add(x.user.get('id'))
            x.send({'t': T_MESSAGE, 'path': p, 'data': {'roomName': name, 'invitingUserData': c.user},
                    'endpointObject': {'path': c.path, 'endpoint': c.ep, 'data': c.user}})
        return None

    def oda_katil(self, c, name, d):
        me = c.user.get('id')
        o = self.odalar.get(name)
        if not o or me not in o['davetli'] | o['uyeler']:
            return 'no playerId found'
        o['uyeler'].add(me)
        self.join(c, name, 'usr', name)
        return None

    def oda_kapat(self, c, name, d):
        o = self.odalar.get(name)
        if not o or o['kurucu'] != c.user.get('id'):
            return 'Not creator of this channel'
        with self.lock:
            del self.odalar[name]
            for x in self.conns.values():
                x.handlers.discard(self.oda_yolu(name))
        return None

    def oda_ayril(self, c, name, d):
        o = self.odalar.get(name)
        if o:
            o['uyeler'].discard(c.user.get('id'))
        c.handlers.discard(self.oda_yolu(name))
        return None

    def relay(self, c, path, data):
        """Oyuncunun oda mesajı: odayı dinleyenlere (kendisi dahil) gönderenin bilgisiyle."""
        if not c.user or not path.startswith('/room/'):
            return
        msg = str(data.get('msg', ''))[:500]
        if not msg:
            return
        now = time.time()
        c.gecmis = [t for t in c.gecmis if now - t < SEL_SN] + [now]
        if len(c.gecmis) > SEL_SINIRI:
            self.log('sohbet: sel, atıldı %s: %s' % (c.user.get('userId'), msg[:60]))
            return
        if self.engel_kanca is not None:
            bildirim = self.engel_kanca(dict(c.user), path, c.dil)
            if bildirim:
                self.log('sohbet: susturulu, atıldı %s: %s' % (c.user.get('userId'), msg[:60]))
                self.duyuru(bildirim, path.split('/')[2], kim=c.user.get('id'))
                return
        self.log('sohbet: %s: %s' % (path, msg))
        self.broadcast(path, msg, c.ep, c.user)
        if self.bot_kanca is not None:
            self.bot_kanca(path, msg, dict(c.user))      # botlar okur (bot/yonetici.sohbet_gelen)

    def whisper(self, c, path, data, rid):
        """Fısıltı: istemci /whisper/<InstanceID>_<alıcının adı>/ yoluna yazar, alıcının istemcisi kendi adıyla bu yolu dinler
        (AChat, giriş sonrası). Ad büyük/küçük harf ayırmaz. Alıcı yoksa hata yanıtı: istemci "kullanıcı yok ya da çevrimdışı" yazar."""
        msg = str(data.get('msg', ''))[:500]
        want = path.lower()
        with self.lock:
            conns = [x for x in self.conns.values() if x.user and x is not c]
        hits = [(x, p) for x in conns for p in x.handlers if p.lower() == want]
        if not hits:                       # başka örnek kimliği (InstanceID) ile dinleyen: adın kendisi
            ad = '_' + want[len('/whisper/'):].split('_', 1)[-1]
            hits = [(x, p) for x in conns for p in x.handlers if p.startswith('/whisper/') and p.lower().endswith(ad)]
        if not hits and c.user and msg and self.bot_fisilti is not None and                 self.bot_fisilti(want[len('/whisper/'):].split('_', 1)[-1].rstrip('/'), msg, dict(c.user)):
            self.log('sohbet: fısıltı -> bot %s: %s' % (path, msg))       # alıcı bot (bot/yonetici.fisilti_gelen)
            if rid is not None:
                c.send({'t': T_RESPONSE, 'requestId': rid})
            return
        if not c.user or not msg or not hits:
            self.log('sohbet: fısıltı yerine ulaşmadı %s' % path)
            if rid is not None:
                c.send({'t': T_RESPONSE, 'requestId': rid, 'errorReason': 'notFound', 'errorMsg': 'no listener',
                        'errorPath': path})
            return
        self.log('sohbet: fısıltı %s -> %s: %s' % (c.user.get('userId'), path, msg))
        for x, p in hits:
            x.send({'t': T_MESSAGE, 'path': p, 'data': {'msg': msg, 'sentAt': str(int(time.time() * 1000))},
                    'endpointObject': {'path': c.path, 'endpoint': c.ep, 'data': c.user}})
        if rid is not None:
            c.send({'t': T_RESPONSE, 'requestId': rid})

    def bot_fisildar(self, alici, msg, ep, user):
        """Bot oyuncuya fısıldar: alıcının kendi fısıltı yolunu dinleyen bağlantılarına (whisper'ın teslimi gibi) -> ulaştı mı."""
        ad = '_' + str(alici).lower() + '/'
        with self.lock:
            hits = [(x, p) for x in self.conns.values() if x.user for p in x.handlers
                    if p.startswith('/whisper/') and p.lower().endswith(ad)]
        for x, p in hits:
            x.send({'t': T_MESSAGE, 'path': p, 'data': {'msg': str(msg)[:500], 'sentAt': str(int(time.time() * 1000))},
                    'endpointObject': {'path': '/endpoint/%s/' % ep, 'endpoint': ep, 'data': user}})
        return bool(hits)

    def broadcast(self, path, msg, ep, user):
        out = {'t': T_MESSAGE, 'path': path, 'data': {'msg': msg, 'sentAt': str(int(time.time() * 1000))},
               'endpointObject': {'path': '/endpoint/%s/' % ep, 'endpoint': ep, 'data': user}}
        with self.lock:      # yalnız giriş yapmış bağlantılar: arkadaş sunucusunda 7771 ağa açık, kaydolan herkes dinliyordu
            conns = [x for x in self.conns.values() if x.user and path in x.handlers]
        for x in conns:
            x.send(out)
        return len(conns)

    # -------------------------------------------------------- oyun sunucusundan
    def authenticate(self, ep, user, rooms, dil=None):
        """ChatAuthenticateUserRequest: uç noktası bu oyuncu -> loggedIn ve odalar. rooms: [(roomType, roomClass, ad)]."""
        with self.lock:
            c = self.conns.get(ep)
        if not c:
            self.log('sohbet: bilinmeyen uç %s' % ep)
            return False
        c.user, c.dil = dict(user), dil
        c.send({'t': T_MESSAGE, 'path': c.path + 'serverStatus/', 'data': {'type': 'loggedIn', 'wordFilter': []},
                'endpointObject': {'path': c.path, 'endpoint': c.ep, 'data': {}}})
        for room in rooms:
            self.join(c, *room)
        self.log('sohbet: giriş %s (%s), odalar %s' % (user.get('userId'), ep, [r[0] for r in rooms]))
        return True

    def join(self, c, room_type, room_class, name):
        c.send({'t': T_MESSAGE, 'path': c.path + 'changePredefinedRoom/',
                'data': {'roomType': room_type, 'roomClass': room_class, 'newRoomName': name},
                'endpointObject': {'path': c.path, 'endpoint': c.ep, 'data': {}}})

    def update_rooms(self, rooms, kim=None):
        """Oda değişimi (klan kuruldu/dağıldı): oyuncunun (kim: kimliği; verilmezse giriş yapmış herkesin) bağlantılarına yeni oda
        listesi."""
        with self.lock:
            conns = [x for x in self.conns.values() if x.user and kim in (None, x.user.get('id'))]
        for c in conns:
            for room in rooms:
                self.join(c, *room)

    def oda_birak(self, kim, room_class, name):
        """Oyuncu odadan çıktı (gruptan ayrıldı): bağlantıları o odanın mesajlarını artık almaz."""
        prefix = '/room/%s/%s/' % (room_class, name)
        with self.lock:
            for c in self.conns.values():
                if c.user and c.user.get('id') == kim:
                    c.handlers = {p for p in c.handlers if not p.startswith(prefix)}

    def update_user(self, kim=None, **kw):
        with self.lock:
            for c in self.conns.values():
                if c.user and kim in (None, c.user.get('id')):
                    c.user.update(kw)

    def duyuru(self, text, room_type='global', kim=None):
        """Sistem duyurusu: oyuncunun (kim: kimliği; verilmezse giriş yapmış herkesin) o türdeki odalarına -> gönderilen mesaj
        sayısı. Oda henüz kaydedilmemişse (girişin hemen ardı) duyuru bekler, oda kaydı gelince gider."""
        text = str(text).replace('|', '/')
        n = 0
        with self.lock:
            conns = [x for x in self.conns.values() if x.user and kim in (None, x.user.get('id'))]
        for c in conns:
            c.pending.append((room_type, text))
            n += self.flush(c)
        return n

    def flush(self, c):
        sent, keep = 0, []
        for room_type, text in c.pending:
            paths = [p for p in c.handlers if p.startswith('/room/%s/' % room_type)]
            if not paths:
                keep.append((room_type, text))
                continue
            msg = '|'.join([SISTEM_ANAHTARI] + ([SISTEM_METNI[c.dil], text] if c.dil in SISTEM_METNI else
                                               [v for k in ('en', 'tr') for v in (SISTEM_METNI[k], text)]))
            data = {'msg': msg, 'sentAt': str(int(time.time() * 1000))}
            for p in paths:
                c.send({'t': T_MESSAGE, 'path': p, 'data': data,
                        'endpointObject': {'path': '/endpoint/sistem/', 'endpoint': 'sistem',
                                           'data': {'userId': 'System', 'id': '0', 'globalId': '0', 'role': 'system'}}})
                sent += 1
        c.pending = keep[-20:]
        return sent

    def online(self):
        with self.lock:
            return any(c.user for c in self.conns.values())
