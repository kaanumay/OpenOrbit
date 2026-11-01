"""Live test control channel: opened only with `game.py --control` (127.0.0.1:8099, one JSON request/response per line).

For driving the server and seeing what the client sends in a live trial (client-side tool: test/live.py):
- iz:     the session's incoming requests (<-) and outgoing commands (->) with sequence numbers; injected requests are '<='.
- wait:   waits for a message (name regex, direction) to arrive after a given sequence number.
- request: runs a request as if the client had sent it; the replies go to the real client (window, HUD, map change are visible on
          screen). Missing fields are filled with the protocol's defaults (encode-decode round trip).
- send:   sends the client a command directly ([name, fields]) or an old text protocol line ("0|A|STM|…").
- py:     Python in the server process; namespace: S session, W world, P profile, G game module and setup helpers (currency, give,
          phase_out, alien, nearby, clean_up, repair). The value of the last expression or `_` is returned.
- state:  connection, map, position, ship, money, number of aliens/boxes in the world, last message sequence.
- fields: a message's field layout (protocol table).
It is not opened in normal play (it is opened with the panel's Developer setting); it binds only to the local address.
"""
import ast, collections, contextlib, io, json, re, socket, threading, time, traceback

PORT = 8099
NOISE = {'MoveRequest', 'KeepAlive', 'StayinAlive'}      # not shown in the trace by default (full=1 if wanted)


class Trace:
    """Message trace: (sequence, time, direction, name, fields) ring buffer; waiters are woken by a condition variable."""

    def __init__(self, n=30000):
        self.q = collections.deque(maxlen=n)
        self.seq = 0
        self.cond = threading.Condition()

    def add(self, direction, field_name, fields):
        with self.cond:
            self.seq += 1
            self.q.append((self.seq, time.time(), direction, field_name, fields))
            self.cond.notify_all()
            return self.seq

    def since(self, seq=0, field_name=None, direction=None, noise=False, limit=400):
        rx = re.compile(field_name) if field_name else None
        with self.cond:
            rows = [e for e in self.q if e[0] > seq]
        out = []
        for e in rows:
            if direction and not e[2].startswith(direction):
                continue
            if rx and not (rx.search(e[3]) or (isinstance(e[4], dict) and rx.search(str(e[4].get('message', ''))))):
                continue                    # old text protocol lines ("0|A|STM|…") are also searched by their content
            if not noise and not rx and e[3] in NOISE:
                continue
            out.append(e)
        return out[-limit:] if limit else out

    def wait(self, seq, field_name, direction=None, timeout=10.0):
        end = time.time() + timeout
        while True:
            hit = self.since(seq, field_name, direction, noise=True, limit=0)
            if hit:
                return hit[0]
            left = end - time.time()
            if left <= 0:
                return None
            with self.cond:
                self.cond.wait(min(left, 0.5))


TRACE = Trace()


def chat_trace(direction, kind, body):
    """The chat server's frames (chat.py): the JSON ones with type 't', the others raw bytes."""
    if isinstance(body, dict):
        TRACE.add(direction, 'Sohbet:t%s' % body.get('t'), body)
    else:
        import json as _j
        try:
            d = _j.loads(bytes(body).decode('utf8'))
            TRACE.add(direction, 'Sohbet:t%s' % d.get('t'), d)
        except (ValueError, UnicodeDecodeError, AttributeError):
            TRACE.add(direction, 'Sohbet:0x%02x' % kind, {'byte': bytes(body[:200]).hex(), 'length': len(body)})


def _json(v):
    return json.loads(json.dumps(v, default=lambda o: o.hex() if isinstance(o, (bytes, bytearray)) else repr(o)))


def _row(e, long):
    seq, t, direction, field_name, f = e
    s = json.dumps(_json(f), ensure_ascii=False)
    if long and len(s) > long:
        s = s[:long] + '…'
    return {'order': seq, 'time': time.strftime('%H:%M:%S', time.localtime(t)) + ('%.3f' % (t % 1))[1:], 'direction': direction, 'name': field_name,
            'fields': s}


class Control:
    def __init__(self, game, port=PORT):
        self.G, self.port = game, port
        self.ns = {}

    # ------------------------------------------------------------------ helpers
    def session(self):
        s = self.G.CURRENT
        if s is None:
            raise RuntimeError('no connected client')
        return s

    def full_fields(self, field_name, fields):
        """Fills in missing fields with the protocol defaults (the form the client would send)."""
        P = self.G.P
        mid, name, f, left, err = P.decode_message(P.encode_message(field_name, fields))
        if err:
            raise ValueError('could not decode fields: %s' % err)
        return f

    def state(self):
        G = self.G
        p = G.PROFILE.d
        s = G.CURRENT
        w = s.world if s else None
        out = {'connected': s is not None, 'order': TRACE.seq, 'map': p['position'].get('mapId'),
               'map_name': G.H.name(p['position'].get('mapId')), 'position': [p['position'].get('x'), p['position'].get('y')],
               'ship': {k: p['ship'].get(k) for k in ('typeId', 'hitPoints', 'hitMax', 'shield', 'shieldMax', 'cargoSpace')},
               'pilot': {k: p['pilot'].get(k) for k in ('userName', 'level', 'credits', 'uridium', 'ep', 'honourPoints',
                                                        'factionId', 'clanTag')}}
        if w:
            with w.lock:
                hx, hy = w.hero_pos()
                out['world'] = {'position': [int(hx), int(hy)], 'alien': len(w.npcs), 'box': len(w.boxes),
                                'in_station': bool(w.in_station()), 'selected': getattr(w, 'target', None)}
        return out

    def helpers(self):
        """Setup helpers in the py namespace (each also sends the client the update it needs)."""
        G, K = self.G, self

        def currency(credits=0, uridium=0, ep=0, honor=0):
            """Adds money/EP/honor (can be negative), updates the HUD."""
            s = K.session()
            tot = G.PROFILE.gain(credits=credits, uridium=uridium, ep=ep, honor=honor)
            msgs = s.world.reward_msgs(tot, ep=ep, honor=honor) if s.world and (ep or honor) else []
            s.send(msgs + s.shop.money_msgs(), 'kontrol: para')
            return tot

        def give(loot, n=1):
            """Gives items/resources/ammo (the shop reward path) -> number of messages sent."""
            s = K.session()
            msgs = s.shop.reward(loot, n) or []
            if msgs:
                s.send(msgs, 'kontrol: ver %s x%d' % (loot, n))
            return len(msgs)

        def phase_out(game_map=None, x=None, y=None):
            """To a map or to a point on the same map (the map is reloaded)."""
            s = K.session()
            dest = int(game_map or G.PROFILE.d['position']['mapId'])
            s.change_map(dest, None, pos=(int(x), int(y)) if x is not None else None)
            return {'map': dest, 'position': [x, y]}

        def alien(tip, count=1, far=400, angle=0.0, stop=True):
            """Spawns NPCs around the ship -> ids. dur: stands still until attacked (for clicking from the screen)."""
            import math
            w = K.session().world
            out = []
            with w.lock:
                hx, hy = w.hero_pos()
                for i in range(count):
                    a = math.radians(angle) + 2 * math.pi * i / max(1, count)
                    n = w.spawn_npc_at(str(tip), hx + far * math.cos(a), hy + far * math.sin(a))
                    if stop:
                        n.next_think = time.time() + 600
                    out.append(n.id)
            return out

        def nearby(count=5):
            """Nearest aliens: (distance, id, name, position, HP, shield)."""
            import math
            w = K.session().world
            now = time.time()
            with w.lock:
                hx, hy = w.hero_pos()
                rows = []
                for n in w.npcs.values():
                    if n.alive:
                        x, y = n.mover.pos(now)
                        rows.append((int(math.hypot(x - hx, y - hy)), n.id, n.d.get('name'), [int(x), int(y)], int(n.hp), int(n.shield)))
            return sorted(rows)[:count]

        def clean_up(radius=3000):
            """Removes the aliens around the ship (a calm test environment) -> number removed."""
            import math
            w = K.session().world
            now = time.time()
            n_out = 0
            with w.lock:
                hx, hy = w.hero_pos()
                for n in list(w.npcs.values()):
                    x, y = n.mover.pos(now)
                    if math.hypot(x - hx, y - hy) <= radius:
                        n.alive = False
                        n.summoned = True                          # so it does not respawn
                        w.npcs.pop(n.id, None)
                        w.visible.discard(n.id)
                        w.send([('ShipRemoveCommand', {'userId': n.id})])
                        n_out += 1
            return n_out

        def repair():
            """HP and shield full."""
            g = G.PROFILE.d['ship']
            G.PROFILE.set_hull(hp=g.get('hitMax'), shield=g.get('shieldMax'))
            w = K.session().world
            if w:
                with w.lock:
                    w.send([w.hp_msg()])
            return [g.get('hitPoints'), g.get('shield')]

        return dict(currency=currency, give=give, phase_out=phase_out, alien=alien, nearby=nearby, clean_up=clean_up, repair=repair)

    def run_py(self, code):
        s = self.G.CURRENT
        ns = self.ns
        if not ns:
            ns.update(self.helpers())
        ns.update(G=self.G, S=s, W=s.world if s else None, P=self.G.PROFILE, json=json, time=time)
        buf = io.StringIO()
        tree = ast.parse(code, mode='exec')
        last = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last = ast.Expression(tree.body.pop().value)
        with contextlib.redirect_stdout(buf):
            exec(compile(tree, '<kontrol>', 'exec'), ns)
            val = eval(compile(last, '<kontrol>', 'eval'), ns) if last else ns.get('_')
        return {'output': buf.getvalue(), 'value': _json(val)}

    # ------------------------------------------------------------------ commands
    def handle(self, r):
        k = r.get('command')
        long = r.get('long', 600)
        if k == 'state':
            return self.state()
        if k == 'last':
            return {'order': TRACE.seq}
        if k == 'iz':
            rows = TRACE.since(r.get('after') or 0, r.get('name'), r.get('direction'), r.get('full', False), r.get('limit', 200))
            return {'order': TRACE.seq, 'messages': [_row(e, long) for e in rows]}
        if k == 'wait':
            e = TRACE.wait(TRACE.seq if r.get('after') is None else r['after'], r['name'], r.get('direction'), r.get('sure', 10))
            return {'found': e is not None, 'message': _row(e, long) if e else None, 'order': TRACE.seq}
        if k == 'request':
            s = self.session()
            f = self.full_fields(r['name'], r.get('fields', {}))
            before = TRACE.seq
            s.inject(r['name'], f)
            time.sleep(r.get('wait', 0.4))
            return {'fields': _json(f), 'replies': [_row(e, long) for e in TRACE.since(before, direction='->', limit=0)]}
        if k == 'send':
            s = self.session()
            msgs = []
            for m in r.get('messages', []):
                if isinstance(m, str):
                    msgs.append(self.G.legacy(m))
                else:
                    self.G.P.encode_message(m[0], m[1])          # an unknown field/type error should surface here
                    msgs.append((m[0], m[1]))
            s.send(msgs, 'kontrol: %d mesaj' % len(msgs))
            return {'sent': len(msgs)}
        if k == 'py':
            return self.run_py(r['code'])
        if k == 'fields':
            sp = self.G.P.spec().by_class.get(r['name'])
            return {'name': r['name'], 'steps': sp['steps'] if sp else None}
        raise ValueError('unknown command %r' % k)

    # ------------------------------------------------------------------ server
    def serve(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', self.port))
        s.listen(4)
        self.G.log('control channel: 127.0.0.1:%d' % self.port)
        while True:
            c, _ = s.accept()
            threading.Thread(target=self.client, args=(c,), daemon=True).start()

    def client(self, c):
        f = c.makefile('rwb')
        try:
            for line in f:
                if not line.strip():
                    continue
                try:
                    out = {'done': True, 'result': self.handle(json.loads(line))}
                except Exception as e:
                    out = {'done': False, 'error': '%s: %s' % (type(e).__name__, e), 'iz': traceback.format_exc()[-1500:]}
                f.write((json.dumps(out, ensure_ascii=False) + '\n').encode('utf8'))
                f.flush()
        except OSError:
            pass
        finally:
            c.close()

    def start(self):
        threading.Thread(target=self.serve, daemon=True).start()
        return self
