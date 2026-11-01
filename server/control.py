"""Canlı test kontrol kanalı: yalnız `game.py --kontrol` ile açılır (127.0.0.1:8099, satır başına bir JSON istek/yanıt).

Canlı denemede sunucuyu yönetmek ve istemcinin ne gönderdiğini görmek için (istemci tarafı araç: test/live.py):
- iz:     oturumun gelen istekleri (<-) ve giden komutları (->) sıra numarasıyla; enjekte edilen istekler '<='.
- bekle:  bir mesajın (ad düzenli ifadesi, yön) belli bir sıradan sonra gelmesini bekler.
- istek:  istemci göndermiş gibi bir isteği işletir; yanıtlar gerçek istemciye gider (pencere, HUD, harita değişimi ekranda
          görülür). Eksik alanlar protokolün varsayılanlarıyla doldurulur (kodla-çöz turu).
- gonder: istemciye doğrudan komut ([ad, alanlar]) ya da eski metin protokolü satırı ("0|A|STM|…").
- py:     sunucu sürecinde Python; ad alanı: S oturum, W dünya, P profil, G game modülü ve hazırlık yardımcıları (para, ver,
          isinla, uzayli, yakin, temizle, tamir). Son ifadenin değeri ya da `_` döner.
- durum:  bağlantı, harita, konum, gemi, para, dünyadaki uzaylı/kutu sayısı, son mesaj sırası.
- alanlar: bir mesajın alan düzeni (protokol tablosu).
Normal oyunda açılmaz (panelin Geliştirici ayarıyla açılır); yalnız yerel adrese bağlanır.
"""
import ast, collections, contextlib, io, json, re, socket, threading, time, traceback

PORT = 8099
NOISE = {'MoveRequest', 'KeepAlive', 'StayinAlive'}      # izde varsayılan olarak gösterilmeyenler (istenirse tam=1)


class Trace:
    """Mesaj izi: (sıra, zaman, yön, ad, alanlar) halka tamponu; bekleyenler koşul değişkeniyle uyanır."""

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
                continue                    # eski metin protokolü satırları ("0|A|STM|…") içerikleriyle de aranır
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
    """Sohbet sunucusunun çerçeveleri (chat.py): JSON olanlar 't' türüyle, ötekiler ham bayt."""
    if isinstance(body, dict):
        TRACE.add(direction, 'Sohbet:t%s' % body.get('t'), body)
    else:
        import json as _j
        try:
            d = _j.loads(bytes(body).decode('utf8'))
            TRACE.add(direction, 'Sohbet:t%s' % d.get('t'), d)
        except (ValueError, UnicodeDecodeError, AttributeError):
            TRACE.add(direction, 'Sohbet:0x%02x' % kind, {'bayt': bytes(body[:200]).hex(), 'uzunluk': len(body)})


def _json(v):
    return json.loads(json.dumps(v, default=lambda o: o.hex() if isinstance(o, (bytes, bytearray)) else repr(o)))


def _row(e, long):
    seq, t, direction, field_name, f = e
    s = json.dumps(_json(f), ensure_ascii=False)
    if long and len(s) > long:
        s = s[:long] + '…'
    return {'sira': seq, 'zaman': time.strftime('%H:%M:%S', time.localtime(t)) + ('%.3f' % (t % 1))[1:], 'yon': direction, 'ad': field_name,
            'alanlar': s}


class Control:
    def __init__(self, game, port=PORT):
        self.G, self.port = game, port
        self.ns = {}

    # ------------------------------------------------------------------ yardımcılar
    def session(self):
        s = self.G.CURRENT
        if s is None:
            raise RuntimeError('bağlı istemci yok')
        return s

    def full_fields(self, field_name, fields):
        """Eksik alanları protokol varsayılanlarıyla doldurur (istemcinin göndereceği biçim)."""
        P = self.G.P
        mid, name, f, left, err = P.decode_message(P.encode_message(field_name, fields))
        if err:
            raise ValueError('alanlar çözülemedi: %s' % err)
        return f

    def state(self):
        G = self.G
        p = G.PROFILE.d
        s = G.CURRENT
        w = s.world if s else None
        out = {'bagli': s is not None, 'sira': TRACE.seq, 'harita': p['konum'].get('mapId'),
               'harita_adi': G.H.name(p['konum'].get('mapId')), 'konum': [p['konum'].get('x'), p['konum'].get('y')],
               'gemi': {k: p['gemi'].get(k) for k in ('typeId', 'hitPoints', 'hitMax', 'shield', 'shieldMax', 'cargoSpace')},
               'pilot': {k: p['pilot'].get(k) for k in ('userName', 'level', 'credits', 'uridium', 'ep', 'honourPoints',
                                                        'factionId', 'clanTag')}}
        if w:
            with w.lock:
                hx, hy = w.hero_pos()
                out['dunya'] = {'konum': [int(hx), int(hy)], 'uzayli': len(w.npcs), 'kutu': len(w.boxes),
                                'istasyonda': bool(w.in_station()), 'secili': getattr(w, 'target', None)}
        return out

    def helpers(self):
        """py ad alanındaki hazırlık yardımcıları (her biri istemciye gerekli güncellemeyi de gönderir)."""
        G, K = self.G, self

        def currency(credits=0, uridium=0, ep=0, honor=0):
            """Para/EP/onur ekler (eksi verilebilir), HUD'u günceller."""
            s = K.session()
            tot = G.PROFILE.gain(kredi=credits, uridyum=uridium, ep=ep, onur=honor)
            msgs = s.world.reward_msgs(tot, ep=ep, onur=honor) if s.world and (ep or honor) else []
            s.send(msgs + s.shop.money_msgs(), 'kontrol: para')
            return tot

        def give(loot, n=1):
            """Eşya/kaynak/cephane verir (mağaza ödül yolu) -> gönderilen mesaj sayısı."""
            s = K.session()
            msgs = s.shop.reward(loot, n) or []
            if msgs:
                s.send(msgs, 'kontrol: ver %s x%d' % (loot, n))
            return len(msgs)

        def phase_out(game_map=None, x=None, y=None):
            """Haritaya ya da aynı haritada bir noktaya (harita yeniden yüklenir)."""
            s = K.session()
            dest = int(game_map or G.PROFILE.d['konum']['mapId'])
            s.change_map(dest, None, pos=(int(x), int(y)) if x is not None else None)
            return {'harita': dest, 'konum': [x, y]}

        def alien(tip, count=1, far=400, angle=0.0, stop=True):
            """Geminin çevresinde NPC doğurur -> kimlikler. dur: saldırıya uğrayana dek yerinde durur (ekrandan tıklamak için)."""
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
            """En yakın uzaylılar: (uzaklık, kimlik, ad, konum, can, kalkan)."""
            import math
            w = K.session().world
            now = time.time()
            with w.lock:
                hx, hy = w.hero_pos()
                rows = []
                for n in w.npcs.values():
                    if n.alive:
                        x, y = n.mover.pos(now)
                        rows.append((int(math.hypot(x - hx, y - hy)), n.id, n.d.get('ad'), [int(x), int(y)], int(n.hp), int(n.shield)))
            return sorted(rows)[:count]

        def clean_up(radius=3000):
            """Geminin çevresindeki uzaylıları kaldırır (sakin test ortamı) -> kaldırılan sayısı."""
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
                        n.summoned = True                          # yeniden doğmasın
                        w.npcs.pop(n.id, None)
                        w.visible.discard(n.id)
                        w.send([('ShipRemoveCommand', {'userId': n.id})])
                        n_out += 1
            return n_out

        def repair():
            """Can ve kalkan dolu."""
            g = G.PROFILE.d['gemi']
            G.PROFILE.set_hull(hp=g.get('hitMax'), shield=g.get('shieldMax'))
            w = K.session().world
            if w:
                with w.lock:
                    w.send([w.hp_msg()])
            return [g.get('hitPoints'), g.get('shield')]

        return dict(para=currency, ver=give, isinla=phase_out, uzayli=alien, yakin=nearby, temizle=clean_up, tamir=repair)

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
        return {'cikti': buf.getvalue(), 'deger': _json(val)}

    # ------------------------------------------------------------------ komutlar
    def handle(self, r):
        k = r.get('komut')
        long = r.get('uzun', 600)
        if k == 'durum':
            return self.state()
        if k == 'son':
            return {'sira': TRACE.seq}
        if k == 'iz':
            rows = TRACE.since(r.get('sonra') or 0, r.get('ad'), r.get('yon'), r.get('tam', False), r.get('limit', 200))
            return {'sira': TRACE.seq, 'mesajlar': [_row(e, long) for e in rows]}
        if k == 'bekle':
            e = TRACE.wait(TRACE.seq if r.get('sonra') is None else r['sonra'], r['ad'], r.get('yon'), r.get('sure', 10))
            return {'bulundu': e is not None, 'mesaj': _row(e, long) if e else None, 'sira': TRACE.seq}
        if k == 'istek':
            s = self.session()
            f = self.full_fields(r['ad'], r.get('alanlar', {}))
            before = TRACE.seq
            s.inject(r['ad'], f)
            time.sleep(r.get('bekle', 0.4))
            return {'alanlar': _json(f), 'yanitlar': [_row(e, long) for e in TRACE.since(before, direction='->', limit=0)]}
        if k == 'gonder':
            s = self.session()
            msgs = []
            for m in r.get('mesajlar', []):
                if isinstance(m, str):
                    msgs.append(self.G.legacy(m))
                else:
                    self.G.P.encode_message(m[0], m[1])          # bilinmeyen alan/tür hatası burada çıksın
                    msgs.append((m[0], m[1]))
            s.send(msgs, 'kontrol: %d mesaj' % len(msgs))
            return {'gonderilen': len(msgs)}
        if k == 'py':
            return self.run_py(r['kod'])
        if k == 'alanlar':
            sp = self.G.P.spec().by_class.get(r['ad'])
            return {'ad': r['ad'], 'adimlar': sp['steps'] if sp else None}
        raise ValueError('bilinmeyen komut %r' % k)

    # ------------------------------------------------------------------ sunucu
    def serve(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', self.port))
        s.listen(4)
        self.G.log('kontrol kanalı: 127.0.0.1:%d' % self.port)
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
                    out = {'tamam': True, 'sonuc': self.handle(json.loads(line))}
                except Exception as e:
                    out = {'tamam': False, 'hata': '%s: %s' % (type(e).__name__, e), 'iz': traceback.format_exc()[-1500:]}
                f.write((json.dumps(out, ensure_ascii=False) + '\n').encode('utf8'))
                f.flush()
        except OSError:
            pass
        finally:
            c.close()

    def start(self):
        threading.Thread(target=self.serve, daemon=True).start()
        return self
