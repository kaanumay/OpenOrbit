"""Local chat server (roadmap stage 10): the client's "AChat" chat, TCP 7771.

The client takes the chat address from ChatParamCommand (chat_ip) at login. The template in the save pointed at the official chat server
and the client connected there in the local game (client log: "achat:connected"); it is now redirected to this server via login_replace.

At the start of a connection the client sends a 2-byte introduction: 0x2A ('*') + 0x01 (TcpEndpoint2ServerNetLayer.Open); the server also
sends a 0x10 introduction frame (the address the client sees, UTF-8). The client sends InitConnector only once this frame arrives
(TcpEndpoint2ServerNetLayer.Write: LowLevelIntroductionMessage -> connection handler). Live trial 2026-10-17: both were
missing, so chat was never established in the real client (the tests' fake client sent InitConnector directly).
Frame (the client's APServiceStorm.Net.Codec.APlay encoder): 1 byte type + int32 BE length + payload
  0x50 'P'  UTF-8 JSON (server -> client uses this)
  0x53 'S'  binary JSON (client -> server; JSONWriter: object = int32 count + [int32 length + UTF-8 name, value]...)
  0x61 'a'  gzip JSON (the client does not send it)
  0x10 introduction (UTF-8), 0x11 ping (server -> client: int64 time + int32 delay), 0x12 pong (int64)
Binary JSON value types (type byte + value): 0 null, 1 bool (1/2), 2 array (int32 count), 3 int32, 4 object, 5 text (int32 + UTF-8),
6 byte, 7 int64, 8 float32. Numbers are big-endian.

Infinicast messages are a JSON object with a 't' type (Connector2Eps/Eps2Connector converters): 1 Request, 2 RequestResponse,
3 InitConnector, 8 Message, 14 RemoveHandlers, 15 RegisterHandler; the others (30 GetListeningList ...) are answered with the request id.
Flow (the client's AChatGameClientConnection):
  1. InitConnector {space: achat, role: chatter} -> InitConnector {endpointObject {path: /endpoint/<endpoint>/, endpoint: <endpoint>}}
  2. the client registers a Message handler on its endpoint's serverStatus/ and changePredefinedRoom/ paths (each registration is
     acknowledged with RequestResponse {requestId}); once acknowledged it reports the endpoint id to the game server with ChatAuthenticateUserRequest
  3. the game server (game.py) calls authenticate(): serverStatus gets {type: loggedIn}, changePredefinedRoom gets, for each room,
     {roomType, roomClass, newRoomName}; the client registers a handler on the /room/<roomClass>/<newRoomName>/ path and opens the room
     (here roomClass = roomType)
  4. the player's message: Message {path: room, data: {msg}} -> Message {path, data {msg, sentAt},
     endpointObject {path, endpoint, data: sender info}} to those listening to the room
Sender info (ChatUserVo.FromJson): userId = display name, id = numeric id, globalId, role (chatter/system/mod),
clanTag, factionId, instanceId. Room types (ChatRoomVo): global, faction, clan, group (tab names are translated in the client).

Private rooms (official forum 127334: /create, /close, /invite, /join, /leave; the client's AChatGameClientConnection, il2cpp 1.1.115):
  /create <name> [user] -> Request /roomSvc/usr/createRoom/ {roomName: 'private_<name>'}; when the response arrives the client looks the room up
  in its model (GetRoomByName), so the server first hands out the room with changePredefinedRoom (roomType = roomName: one room is kept per
  type, roomClass 'usr'; ChatRoomVo drops the 'private_' prefix and shows the name). /invite -> inviteUser {roomName, whisperId}; to the invitee's
  /userRoomInvite/<whisperId>/ path Message {roomName, invitingUserData: sender info}. Accept -> acceptInvite {roomName};
  /close -> close {roomName} (creator only); /leave -> removeUser {roomName, whisperId}. Error response with errorMsg (the client's
  ChatIcErrorTranslator: 'Not creator of this channel' -> inviteErrorNotYourRoom, 'user no longer logged in' ->
  inviteErrorUserNotFound); success response data {success: true}. /report -> Request <room path>/reportUser {targetUserId, targetGlobalId, reason, reasonKey, message}:
  written to the file server/logs/chat_reports.jsonl (forum 132515).
Announcements (announcement()): a message from the system user (role system). The client treats a system message as a localization key
("key|old|new|...": it translates the key's text and substitutes the pairs; an unknown key comes out empty). That is why the text is put in place of
the translation of the 'dochat.chat.system' key ("System"/"Sistem").
"""
import json, os, socket, struct, threading, time

PORT = 7771
P_JSON, P_BIN, P_GZIP, P_INTRO, P_PING, P_PONG = 0x50, 0x53, 0x61, 0x10, 0x11, 0x12
T_REQUEST, T_RESPONSE, T_INIT, T_MESSAGE, T_REMOVE, T_REGISTER = 1, 2, 3, 8, 14, 15
T_LISTENING_LIST = 30             # GetListeningList: the chat's /users command (room listeners; Infinicast ListenerQueryExecutor)
PING_SEC = 15
SYSTEM_KEY = 'dochat.chat.system'
SYSTEM_TEXT = {'en': 'System', 'tr': 'Sistem'}       # the client's translation (resource_chat); in another language both are tried
ROOM_LIMIT = 3                    # one private room per player (adaptation: the client has the noMorePrivateRoomsAllowed text, but no number)
FLOOD_LIMIT, FLOOD_SEC = 8, 10        # server-side flood control: more than 8 messages in 10 s are dropped (adaptation; the client's floodWarning warns on its own)
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'chat_reports.jsonl')


# ------------------------------------------------------------ APlay frame and binary JSON
def frame(obj):
    """Server -> client: plain JSON frame."""
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
    raise ValueError('binary JSON: unknown type %d' % t)


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
    """The client's JSONWriter (for imitating the client in tests)."""
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
    """The server's introduction frame (0x10 + length + UTF-8 address)."""
    data = address.encode('utf8')
    return bytes([P_INTRO]) + struct.pack('>i', len(data)) + data


def client_frame(obj):
    """Client -> server frame ('S' + binary JSON)."""
    data = write_object(obj)
    return bytes([P_BIN]) + struct.pack('>i', len(data)) + data


HANDSHAKE = b'*'                # the client's bytes at the start of a connection (protocol marker + version)


class FrameDecoder:
    """Frames from the stream: feed(bytes) -> [(type, payload)]; for JSON types the payload is a dict. handshake=True: the client
    introduction (handshake) at the start of the stream is skipped (server side); False on the client side (tests)."""
    def __init__(self, handshake=False):
        self.buf = b''
        self.wait_handshake = handshake

    def feed(self, data):
        self.buf += data
        out = []
        if self.wait_handshake:
            if len(self.buf) < len(HANDSHAKE):
                return out
            if self.buf.startswith(HANDSHAKE):
                self.buf = self.buf[len(HANDSHAKE):]
            self.wait_handshake = False
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


# ------------------------------------------------------------ server
class Connection:
    def __init__(self, srv, sock, ep):
        self.srv, self.sock, self.ep = srv, sock, ep
        self.send_lock = threading.Lock()
        self.handlers = set()             # paths with a registered Message handler
        self.joined = set()               # '/room/<class>/<name>/' rooms the server put the player in (join): only these can be registered
        self.user = None                  # sender info after authenticate()
        self.lang = None
        self.pending = []                 # announcements whose room is not registered yet (room type, text)
        self.pending_lock = threading.Lock()
        self.history = []                  # recent message times (flood control)
        self.alive = True

    @property
    def path(self):
        return '/endpoint/%s/' % self.ep

    def send(self, obj):
        self.send_raw(frame(obj))

    def send_raw(self, data):
        if self.srv.trace:                   # live test trace (game.py --control): outgoing frame
            self.srv.trace('->', data[0], data[5:])
        try:
            with self.send_lock:
                self.sock.sendall(data)
        except OSError:
            self.alive = False
            try:                             # the reader blocked in recv returns -> drop runs
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def run(self):
        dec = FrameDecoder(handshake=True)
        try:
            while self.alive:
                data = self.sock.recv(65536)
                if not data:
                    break
                for kind, body in dec.feed(data):
                    if self.srv.trace:
                        self.srv.trace('<-', kind, body)
                    if kind in (P_BIN, P_JSON):
                        self.srv.on_message(self, body)
                    elif kind != P_PONG:
                        self.srv.log('chat: unknown frame 0x%02x (%d bytes) %r' % (kind, len(body), bytes(body[:60])))
        except Exception as e:                  # a broken frame (struct.error, IndexError...) too: otherwise the connection stayed in conns
            self.srv.log('chat: connection error %r' % e)
        self.alive = False
        self.srv.drop(self)


class Chat:
    def __init__(self, log=print, port=PORT, address='127.0.0.1'):
        self.log, self.port = log, port
        self.address = address                # 0.0.0.0 on the friend server (guests connect from other computers)
        self.lock = threading.RLock()
        self.conns = {}                   # endpoint id -> Connection
        self.seq = 0
        self.sock = None
        self.running = False
        self.trace = None                    # live test trace: iz(direction, type, payload) (game.py --control hooks it up)
        self.bot_hook = None             # (path, message, sender) -> None: bots read room messages (bot/society.register)
        self.bot_whisper_hook = None           # (recipient's name, message, sender) -> was the recipient a bot
        self.block_hook = None           # (sender, room path, language) -> notice or None: a muted player (bot/moderation.py)
        self.rooms = {}                  # private room name ('private_<name>') -> {'creator': id, 'members': set, 'invited': set}
        self.report_path = REPORT_PATH

    # -------------------------------------------------------- dinleme
    def start(self):
        """Starts listening -> the real port (the one the operating system picks if port 0 is given); None if the port is taken."""
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((self.address, self.port))
        except OSError as e:
            self.log('chat: %d could not listen (%r)' % (self.port, e))
            s.close()
            return None
        s.listen(5)
        self.sock, self.running = s, True
        self.port = s.getsockname()[1]
        threading.Thread(target=self.accept_loop, daemon=True).start()
        threading.Thread(target=self.ping_loop, daemon=True).start()
        self.log('chat listening %d' % self.port)
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
                c = Connection(self, sock, ep)
                self.conns[ep] = c
            self.log('chat: connection %s' % ep)
            c.send_raw(intro_frame('%s:%d' % addr[:2]))       # the client does not send InitConnector until it sees this
            threading.Thread(target=c.run, daemon=True).start()

    def ping_loop(self):
        while self.running:
            time.sleep(PING_SEC)
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
        self.log('chat: connection closed %s' % c.ep)

    # -------------------------------------------------------- Infinicast
    def on_message(self, c, m):
        t, rid = m.get('t'), m.get('requestId')
        if t == T_INIT:
            c.send({'t': T_INIT, 'endpointObject': {'path': c.path, 'endpoint': c.ep}, 'requestId': rid or 0})
            return
        if t == T_REGISTER:
            if m.get('handlerType', 'Message') == 'Message' and m.get('path'):
                if m['path'].startswith('/room/') and not self.member(c, m['path']):
                    self.log('chat: room not joined, registration ignored %s' % m['path'])
                else:
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
        """Those listening to the room (the client reads them from the response's data.list: path, endpoint, data = user info)."""
        with self.lock:
            conns = list(self.conns.values())
        return [{'path': x.path, 'endpoint': x.ep, 'data': x.user} for x in conns if x.user and path in x.handlers]

    def request(self, c, m):
        """Room service (/roomSvc/usr/...) and report (<room>/reportUser) requests; errors with errorMsg, success with data.success (the client's
        response callback reads json['success']: if it is missing, NullReferenceException, live 2026-10-26)."""
        path, d, rid = m.get('path') or '', m.get('data') or {}, m.get('requestId', 0)
        self.log('chat: request %s %s' % (path, json.dumps(d, ensure_ascii=False)[:200]))
        if not c.user:
            err = 'user no longer logged in'
        elif path.rstrip('/').endswith('/reportUser'):
            err = self.report(c, path, d)
        else:
            fn = {'/roomSvc/usr/createRoom/': self.room_create, '/roomSvc/usr/inviteUser/': self.room_invite,
                  '/roomSvc/usr/acceptInvite/': self.room_join, '/roomSvc/usr/close/': self.room_close,
                  '/roomSvc/usr/removeUser/': self.room_leave}.get(path)
            err = fn(c, str(d.get('roomName') or ''), d) if fn else 'unknown request'
        if err:
            c.send({'t': T_RESPONSE, 'requestId': rid, 'errorReason': 'invalid', 'errorMsg': err, 'errorPath': path})
        else:
            c.send({'t': T_RESPONSE, 'requestId': rid, 'data': {'success': True}})

    def report(self, c, path, d):
        """Chat report (/report): one line in the server log (forum 132515; there is no moderator in single player)."""
        row = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'reporter': c.user.get('userId'), 'room': path.rsplit('/reportUser', 1)[0],
               **{k: d.get(k) for k in ('targetUserId', 'targetGlobalId', 'reason', 'reasonKey', 'message')}}
        os.makedirs(os.path.dirname(self.report_path), exist_ok=True)
        with self.lock, open(self.report_path, 'a', encoding='utf8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.log('chat: report %s -> %s (%s)' % (row['reporter'], row['targetUserId'], row['reasonKey'] or row['reason']))
        return None

    def room_path(self, name):
        return '/room/usr/%s/' % name

    def room_create(self, c, name, d):
        me = c.user.get('id')
        if not name.startswith('private_') or len(name) <= len('private_') or '/' in name:
            return 'invalid room name'
        with self.lock:
            if name in self.rooms:
                return 'room already exists'
            if sum(o['creator'] == me for o in self.rooms.values()) >= ROOM_LIMIT:
                return 'no more private rooms allowed'
            self.rooms[name] = {'creator': me, 'members': {me}, 'invited': set()}
        self.join(c, name, 'usr', name)
        return None

    def room_invite(self, c, name, d):
        o = self.rooms.get(name)
        if not o or o['creator'] != c.user.get('id'):
            return 'Not creator of this channel'
        want = '/userroominvite/%s/' % str(d.get('whisperId') or '').lower()
        with self.lock:
            conns = [x for x in self.conns.values() if x.user and x is not c]
        hits = [(x, p) for x in conns for p in x.handlers if p.lower() == want]
        if not hits:                       # listening under another instance id: the name itself (as with whispers)
            room_name = want[len('/userroominvite/'):].split('_', 1)[-1]
            hits = [(x, p) for x in conns for p in x.handlers if p.lower().startswith('/userroominvite/')
                    and p.lower()[len('/userroominvite/'):].split('_', 1)[-1] == room_name]
        if not hits:
            return 'user no longer logged in'
        for x, p in hits:
            o['invited'].add(x.user.get('id'))
            x.send({'t': T_MESSAGE, 'path': p, 'data': {'roomName': name, 'invitingUserData': c.user},
                    'endpointObject': {'path': c.path, 'endpoint': c.ep, 'data': c.user}})
        return None

    def room_join(self, c, name, d):
        me = c.user.get('id')
        o = self.rooms.get(name)
        if not o or me not in o['invited'] | o['members']:
            return 'no playerId found'
        o['members'].add(me)
        self.join(c, name, 'usr', name)
        return None

    def room_close(self, c, name, d):
        o = self.rooms.get(name)
        if not o or o['creator'] != c.user.get('id'):
            return 'Not creator of this channel'
        with self.lock:
            del self.rooms[name]
            for x in self.conns.values():
                x.handlers.discard(self.room_path(name))
                x.joined.discard(self.room_path(name))
        return None

    def room_leave(self, c, name, d):
        o = self.rooms.get(name)
        if o:
            o['members'].discard(c.user.get('id'))
        c.handlers.discard(self.room_path(name))
        c.joined.discard(self.room_path(name))
        return None

    def member(self, c, path):
        return any(path.startswith(p) for p in c.joined)

    def relay(self, c, path, data):
        """The player's room message: to those listening to the room (including themselves) with the sender's info."""
        if not c.user or not path.startswith('/room/') or not self.member(c, path):
            return
        msg = str(data.get('msg', ''))[:500]
        if not msg:
            return
        now = time.time()
        c.history = [t for t in c.history if now - t < FLOOD_SEC] + [now]
        if len(c.history) > FLOOD_LIMIT:
            self.log('chat: flood, dropped %s: %s' % (c.user.get('userId'), msg[:60]))
            return
        if self.block_hook is not None:
            notification = self.block_hook(dict(c.user), path, c.lang)
            if notification:
                self.log('chat: muted, dropped %s: %s' % (c.user.get('userId'), msg[:60]))
                self.announcement(notification, path.split('/')[2], who=c.user.get('id'))
                return
        self.log('chat: %s: %s' % (path, msg))
        self.broadcast(path, msg, c.ep, c.user)
        if self.bot_hook is not None:
            self.bot_hook(path, msg, dict(c.user))      # the bots read it (bot/chat_engine.incoming_chat)

    def whisper(self, c, path, data, rid):
        """Whisper: the client writes to the /whisper/<InstanceID>_<recipient's name>/ path, the recipient's client listens to this path under its own name
        (AChat, after login). The name is case-insensitive. If there is no recipient, an error response: the client writes "user does not exist or is offline"."""
        msg = str(data.get('msg', ''))[:500]
        want = path.lower()
        with self.lock:
            conns = [x for x in self.conns.values() if x.user and x is not c]
        hits = [(x, p) for x in conns for p in x.handlers if p.lower() == want]
        if not hits:                       # listening under another instance id (InstanceID): the name itself
            room_name = want[len('/whisper/'):].split('_', 1)[-1]
            hits = [(x, p) for x in conns for p in x.handlers if p.startswith('/whisper/') and p.lower()[len('/whisper/'):].split('_', 1)[-1] == room_name]
        if not hits and c.user and msg and self.bot_whisper_hook is not None and                 self.bot_whisper_hook(want[len('/whisper/'):].split('_', 1)[-1].rstrip('/'), msg, dict(c.user)):
            self.log('chat: whisper -> bot %s: %s' % (path, msg))       # recipient is a bot (bot/chat_engine.incoming_whisper)
            if rid is not None:
                c.send({'t': T_RESPONSE, 'requestId': rid})
            return
        if not c.user or not msg or not hits:
            self.log('chat: whisper did not reach its destination %s' % path)
            if rid is not None:
                c.send({'t': T_RESPONSE, 'requestId': rid, 'errorReason': 'notFound', 'errorMsg': 'no listener',
                        'errorPath': path})
            return
        self.log('chat: whisper %s -> %s: %s' % (c.user.get('userId'), path, msg))
        for x, p in hits:
            x.send({'t': T_MESSAGE, 'path': p, 'data': {'msg': msg, 'sentAt': str(int(time.time() * 1000))},
                    'endpointObject': {'path': c.path, 'endpoint': c.ep, 'data': c.user}})
        if rid is not None:
            c.send({'t': T_RESPONSE, 'requestId': rid})

    def bot_whisper(self, recipient, msg, ep, user):
        """A bot whispers to a player: to the connections listening to the recipient's own whisper path (like whisper delivery) -> did it arrive."""
        room_name = str(recipient).lower() + '/'
        with self.lock:
            hits = [(x, p) for x in self.conns.values() if x.user for p in x.handlers
                    if p.startswith('/whisper/') and p.lower()[len('/whisper/'):].split('_', 1)[-1] == room_name]
        for x, p in hits:
            x.send({'t': T_MESSAGE, 'path': p, 'data': {'msg': str(msg)[:500], 'sentAt': str(int(time.time() * 1000))},
                    'endpointObject': {'path': '/endpoint/%s/' % ep, 'endpoint': ep, 'data': user}})
        return bool(hits)

    def broadcast(self, path, msg, ep, user):
        out = {'t': T_MESSAGE, 'path': path, 'data': {'msg': msg, 'sentAt': str(int(time.time() * 1000))},
               'endpointObject': {'path': '/endpoint/%s/' % ep, 'endpoint': ep, 'data': user}}
        with self.lock:      # only connections that have logged in: on the friend server 7771 is open to the network, and everyone who registered was listening
            conns = [x for x in self.conns.values() if x.user and path in x.handlers]
        for x in conns:
            x.send(out)
        return len(conns)

    # -------------------------------------------------------- from the game server
    def authenticate(self, ep, user, rooms, lang=None):
        """ChatAuthenticateUserRequest: this player owns the endpoint -> loggedIn and rooms. rooms: [(roomType, roomClass, name)]."""
        with self.lock:
            c = self.conns.get(ep)
        if not c:
            self.log('chat: unknown endpoint %s' % ep)
            return False
        c.user, c.lang = dict(user), lang
        c.send({'t': T_MESSAGE, 'path': c.path + 'serverStatus/', 'data': {'type': 'loggedIn', 'wordFilter': []},
                'endpointObject': {'path': c.path, 'endpoint': c.ep, 'data': {}}})
        for room in rooms:
            self.join(c, *room)
        self.log('chat: login %s (%s), rooms %s' % (user.get('userId'), ep, [r[0] for r in rooms]))
        return True

    def join(self, c, room_type, room_class, name):
        c.joined.add('/room/%s/%s/' % (room_class, name))
        c.send({'t': T_MESSAGE, 'path': c.path + 'changePredefinedRoom/',
                'data': {'roomType': room_type, 'roomClass': room_class, 'newRoomName': name},
                'endpointObject': {'path': c.path, 'endpoint': c.ep, 'data': {}}})

    def update_rooms(self, rooms, who=None):
        """Room change (clan founded/dissolved): the new room list to the player's connections (who: their id; if not given, to everyone who has
        logged in)."""
        with self.lock:
            conns = [x for x in self.conns.values() if x.user and who in (None, x.user.get('id'))]
        for c in conns:
            for room in rooms:
                self.join(c, *room)

    def room_drop(self, who, room_class, name):
        """The player left a room (left the group): their connections no longer receive that room's messages."""
        prefix = '/room/%s/%s/' % (room_class, name)
        with self.lock:
            for c in self.conns.values():
                if c.user and c.user.get('id') == who:
                    c.handlers = {p for p in c.handlers if not p.startswith(prefix)}
                    c.joined.discard(prefix)

    def update_user(self, who=None, **kw):
        with self.lock:
            for c in self.conns.values():
                if c.user and who in (None, c.user.get('id')):
                    c.user.update(kw)

    def announcement(self, text, room_type='global', who=None):
        """System announcement: to the player's rooms of that type (who: their id; if not given, everyone who has logged in) -> number of messages
        sent. If the room is not registered yet (right after login) the announcement waits and goes out when the room is registered."""
        text = str(text).replace('|', '/')
        n = 0
        with self.lock:
            conns = [x for x in self.conns.values() if x.user and who in (None, x.user.get('id'))]
        for c in conns:
            with c.pending_lock:
                c.pending.append((room_type, text))
            n += self.flush(c)
        return n

    def flush(self, c):
        with c.pending_lock:
            return self._flush(c)

    def _flush(self, c):
        sent, keep = 0, []
        for room_type, text in c.pending:
            paths = [p for p in c.handlers if p.startswith('/room/%s/' % room_type)]
            if not paths:
                keep.append((room_type, text))
                continue
            msg = '|'.join([SYSTEM_KEY] + ([SYSTEM_TEXT[c.lang], text] if c.lang in SYSTEM_TEXT else
                                               [v for k in ('en', 'tr') for v in (SYSTEM_TEXT[k], text)]))
            data = {'msg': msg, 'sentAt': str(int(time.time() * 1000))}
            for p in paths:
                c.send({'t': T_MESSAGE, 'path': p, 'data': data,
                        'endpointObject': {'path': '/endpoint/sistem/', 'endpoint': 'system',
                                           'data': {'userId': 'System', 'id': '0', 'globalId': '0', 'role': 'system'}}})
                sent += 1
        c.pending = keep[-20:]
        return sent

    def online(self):
        with self.lock:
            return any(c.user for c in self.conns.values())
