"""Panel owner channel for live, server-side actions.

This listener is intentionally separate from chat and the developer control
channel.  It binds only to loopback and accepts a fresh secret passed by the
Panel process when it starts the game server.

Endpoints (all need the X-OpenOrbit-Owner secret):
  GET  /oyuncular               connected pilots
  GET  /envanter?oyuncu=<id>    inventory of one connected pilot (read only)
  GET  /denetim                 latest audit log entries
  POST /ver                     give an item to one connected pilot (announced in chat)
  POST /herkese_ver             give an item to every connected pilot (announced in chat)
  POST /cikar                   remove an item from one connected pilot (audit log only, never broadcast)
"""
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8098
MAX_AMOUNT = 2_000_000_000
AUDIT_LIMIT = 200
HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT_PATH = None                    # tests point this at a temp file; None -> <logs>/yonetim_denetim.log
_KNOWN_LOOTS = None
_audit_lock = threading.Lock()


class Hata(ValueError):
    """User-facing error: a Turkish pattern plus values (like profil_araci). The panel translates the pattern, so the
    values are kept apart from the formatted text."""

    def __init__(self, kalip, *values):
        super().__init__(kalip % values if values else kalip)
        self.kalip, self.values = kalip, [str(v) for v in values]


def _error_body(exc):
    body = {'hata': str(exc)}
    if isinstance(exc, Hata):
        body.update(kalip=exc.kalip, arg=exc.values)
    return body


def known_loots():
    """Loot IDs accepted by the server, built from its bundled item tables."""
    global _KNOWN_LOOTS
    if _KNOWN_LOOTS is None:
        data = json.load(open(os.path.join(HERE, 'data', 'istemci_esyalari.json'), encoding='utf8'))
        _KNOWN_LOOTS = {key for key in (data.get('esyalar') or {})
                        if not key.startswith(('shipId_', 'paymentItem_'))}
        server_items = json.load(open(os.path.join(HERE, 'data', 'esyalar.json'), encoding='utf8'))
        for section in ('lazerler', 'lazer_cephane', 'roketler', 'onarim_robotlari', 'hiz_jeneratorleri',
                        'kalkan_jeneratorleri', 'gemiler', 'dronlar', 'formasyonlar', 'dron_tasarimlari',
                        'boosterlar', 'ekstralar', 'savas_esyalari', 'odeme_paketleri'):
            _KNOWN_LOOTS.update(key for key in (server_items.get(section) or {}) if isinstance(key, str) and not key.startswith('_'))
    return _KNOWN_LOOTS


# ---------------------------------------------------------------- audit log
def _audit_path():
    if AUDIT_PATH:
        return AUDIT_PATH
    import yollar as YOL
    return os.path.join(YOL.LOGS, 'yonetim_denetim.log')


def audit(action, **fields):
    """Append one JSON line to the admin audit log. Never raises: a full disk must not undo a finished action."""
    entry = dict(zaman=time.strftime('%Y-%m-%d %H:%M:%S'), islem=action, **fields)
    try:
        path = _audit_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _audit_lock, open(path, 'a', encoding='utf8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError:
        pass
    return entry


def audit_entries(limit=AUDIT_LIMIT):
    """Latest audit entries, newest first."""
    try:
        with open(_audit_path(), encoding='utf8') as fh:
            lines = fh.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- players
def players(game):
    """Return connected pilots only; offline profiles are never edited here."""
    out = []
    for session in list(getattr(game, 'OTURUMLAR', ())):
        profile = getattr(session, 'profil', None)
        if profile is None:
            continue
        pilot = profile.d.get('pilot', {})
        out.append({'id': str(getattr(profile, 'user_id', '')), 'ad': str(pilot.get('userName', ''))})
    return sorted(out, key=lambda row: row['ad'].casefold())


def _session(game, user_id):
    user_id = str(user_id)
    for session in list(getattr(game, 'OTURUMLAR', ())):
        profile = getattr(session, 'profil', None)
        if profile is not None and str(getattr(profile, 'user_id', '')) == user_id:
            return session
    return None


def _live_session(game, user_id):
    session = _session(game, user_id)
    if session is None:
        raise Hata('Oyuncu artık bağlı değil.')
    if not getattr(session, 'magaza', None):
        raise Hata('Oyuncu henüz hazır değil.')
    return session


def _name(session):
    return session.profil.d.get('pilot', {}).get('userName', 'oyuncu')


def _check_loot(loot_id):
    loot_id = str(loot_id or '').strip()
    if not loot_id or len(loot_id) > 120:
        raise Hata('Geçerli bir eşya seçin.')
    if loot_id not in known_loots():
        raise Hata('Bilinmeyen eşya: %s', loot_id)
    return loot_id


def _check_amount(amount, limit=MAX_AMOUNT):
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise Hata('Adet sayı olmalı.')
    if not 1 <= amount <= limit:
        raise Hata('Adet 1 ile %d arasında olmalı.', limit)
    return amount


# ---------------------------------------------------------------- inventory (read only)
def _ores():
    try:
        import magaza
        return dict(magaza.ORES)
    except Exception:
        return {}


def inventory(game, user_id):
    """What a connected pilot owns, grouped for the Player Management page.

    removable: how many units /cikar may take right now (equipped gear is never removable here)."""
    session = _live_session(game, user_id)
    p = session.profil
    d = p.d
    try:
        equipped = {int(i) for i in p.equipped_ids()}
    except Exception:
        equipped = set()
    rows = []
    gear = {}
    for iid, loot in (d.get('esyalar') or {}).items():
        g = gear.setdefault(loot, {'esya': loot, 'tur': 'ekipman', 'adet': 0, 'takili': 0})
        g['adet'] += 1
        if int(iid) in equipped:
            g['takili'] += 1
    for g in gear.values():
        g['silinebilir'] = g['adet'] - g['takili']
        rows.append(g)
    for loot, n in (d.get('cephane') or {}).items():
        if n > 0:
            rows.append({'esya': loot, 'tur': 'cephane', 'adet': n, 'takili': 0, 'silinebilir': n})
    ore_names = _ores()
    for m in d.get('madenler') or []:
        loot = ore_names.get(m['oreType']['typeValue'])
        if loot and m['count'] > 0:
            rows.append({'esya': loot, 'tur': 'cevher', 'adet': m['count'], 'takili': 0, 'silinebilir': m['count']})
    for loot, n in sorted((d.get('diger_esyalar') or {}).items()):
        if n > 0:
            rows.append({'esya': loot, 'tur': 'kaynak', 'adet': n, 'takili': 0, 'silinebilir': n})
    for sid, ship in sorted((d.get('gemiler') or {}).items(), key=lambda kv: int(kv[0])):
        rows.append({'esya': ship.get('lootId'), 'tur': 'gemi', 'adet': 1, 'takili': 1 if sid == str(d.get('aktif_gemi')) else 0,
                     'silinebilir': 0})
    for drone in d.get('dronlar') or []:
        rows.append({'esya': drone.get('lootId'), 'tur': 'dron', 'adet': 1, 'takili': 1, 'silinebilir': 0})
    pilot = d.get('pilot', {})
    return {'oyuncu': _name(session), 'id': str(p.user_id),
            'para': {'kredi': pilot.get('credits', 0), 'uridyum': pilot.get('uridium', 0), 'onur': pilot.get('honourPoints', 0),
                     'ep': pilot.get('ep', 0), 'seviye': pilot.get('level', 1)},
            'esyalar': rows}


# ---------------------------------------------------------------- grants
def _give(session, loot_id, amount):
    """The same server-side reward route that missions and loot use; tells the client and saves."""
    messages = list(session.magaza.reward(loot_id, amount) or [])
    session.send(messages + list(session.magaza.money_msgs() or []), quiet=True)
    session.profil.save()


def _announce(game, text):
    chat = getattr(game, 'SOHBET', None)
    if chat:
        chat.duyuru(text)


def grant(game, user_id, loot_id, amount):
    """Give a connected player one known loot entry and announce it globally."""
    loot_id = _check_loot(loot_id)
    amount = _check_amount(amount)
    session = _live_session(game, user_id)
    _give(session, loot_id, amount)
    name = _name(session)
    announcement = 'Sunucu sahibi %s oyuncusuna %s x%d verdi.' % (name, loot_id, amount)
    _announce(game, announcement)
    audit('ver', oyuncu=name, oyuncu_id=str(user_id), esya=loot_id, adet=amount)
    return {'oyuncu': name, 'esya': loot_id, 'adet': amount, 'duyuru': announcement}


def grant_all(game, loot_id, amount):
    """Give every connected, ready player the same item. One announcement for everyone."""
    loot_id = _check_loot(loot_id)
    amount = _check_amount(amount)
    given, skipped = [], 0
    for row in players(game):
        session = _session(game, row['id'])
        if session is None or not getattr(session, 'magaza', None):
            skipped += 1
            continue
        _give(session, loot_id, amount)
        given.append(_name(session))
    if not given:
        raise Hata('Eşya verilecek bağlı oyuncu yok.')
    announcement = 'Sunucu sahibi bağlı herkese %s x%d verdi (%d oyuncu).' % (loot_id, amount, len(given))
    _announce(game, announcement)
    audit('herkese_ver', oyuncular=given, esya=loot_id, adet=amount)
    return {'oyuncular': given, 'atlanan': skipped, 'esya': loot_id, 'adet': amount, 'duyuru': announcement}


# ---------------------------------------------------------------- removal
def remove(game, user_id, loot_id, amount):
    """Take an item away from a connected player. Mirrors the shop's sell path (same client messages), but pays nothing.

    Equipped gear is refused: the pilot must unequip it first. Never announced in chat; always written to the audit log."""
    loot_id = str(loot_id or '').strip()
    if not loot_id or len(loot_id) > 120:
        raise Hata('Geçerli bir eşya seçin.')
    amount = _check_amount(amount)
    session = _live_session(game, user_id)
    p, shop = session.profil, session.magaza
    d = p.d
    ore_types = {loot: t for t, loot in _ores().items()}
    msgs = []
    if loot_id.startswith('ammunition_') and d.get('cephane', {}).get(loot_id, 0) > 0:
        have = p.ammo(loot_id)
        if amount > have:
            raise Hata('Oyuncuda yalnız %d adet var.', have)
        total = p.add_ammo(loot_id, -amount)
        status = p.menu_status(loot_id)
        iid = shop.item_id(loot_id)
        msgs += ([('MenuItemStatusCommand', status)] if status else []) + [shop.inv_item(iid, loot_id, total),
                                                                         shop.pack([shop.hangar_item(iid, loot_id, total)])]
        before, after = have, total
    elif loot_id in (d.get('esyalar') or {}).values():
        equipped = {int(i) for i in p.equipped_ids()}
        owned = sorted((int(i) for i, loot in d['esyalar'].items() if loot == loot_id), reverse=True)
        free = [i for i in owned if i not in equipped]
        if not free:
            raise Hata('Bu eşya takılı: oyuncu önce hangardan çıkarmalı.')
        if amount > len(free):
            raise Hata('Takılı olmayan yalnız %d adet var.', len(free))
        with p.lock:
            for iid in free[:amount]:
                del d['esyalar'][str(iid)]
                d.get('esya_seviye', {}).pop(str(iid), None)
                msgs.append(('InventoryItemRemovedCommand', {'itemId': iid}))
            p.dirty = True
        before, after = len(owned), len(owned) - amount
    elif loot_id in ore_types:
        t = ore_types[loot_id]
        have = p.ore_count(t)
        if amount > have:
            raise Hata('Oyuncuda yalnız %d adet var.', have)
        p.remove_ores({t: amount})
        msgs += [('AttributeOreCountUpdateCommand', {'oreCountList': d['madenler']}), shop.ore_pack([t])]
        before, after = have, have - amount
    elif d.get('diger_esyalar', {}).get(loot_id, 0) > 0:
        have = p.resource(loot_id)
        if amount > have:
            raise Hata('Oyuncuda yalnız %d adet var.', have)
        total = p.add_resource(loot_id, -amount)
        msgs += shop.resource_msgs(loot_id, total, 0)
        before, after = have, total
    elif loot_id in known_loots():
        raise Hata('Oyuncuda bu eşya yok.')
    else:
        raise Hata('Bilinmeyen eşya: %s', loot_id)
    session.send(msgs, quiet=True)
    p.save()
    name = _name(session)
    audit('cikar', oyuncu=name, oyuncu_id=str(user_id), esya=loot_id, adet=amount, once=before, sonra=after)
    return {'oyuncu': name, 'esya': loot_id, 'adet': amount, 'once': before, 'sonra': after}


# ---------------------------------------------------------------- HTTP
class _Handler(BaseHTTPRequestHandler):
    server_version = 'OpenOrbitOwner/1'

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode('utf8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self):
        secret = self.headers.get('X-OpenOrbit-Owner', '')
        return hmac.compare_digest(secret, self.server.owner_secret)

    def do_GET(self):
        if not self._allowed():
            return self._send(403, {'hata': 'yetki'})
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == '/oyuncular':
                return self._send(200, {'oyuncular': players(self.server.game)})
            if url.path == '/envanter':
                return self._send(200, inventory(self.server.game, query.get('oyuncu')))
            if url.path == '/denetim':
                return self._send(200, {'kayitlar': audit_entries()})
            return self._send(404, {'hata': 'yok'})
        except (ValueError, RuntimeError) as exc:
            return self._send(400, _error_body(exc))
        except Exception:
            self.server.game.log('yönetim: okuma hatası')
            return self._send(500, {'hata': 'Okunamadı.'})

    def do_POST(self):
        if not self._allowed():
            return self._send(403, {'hata': 'yetki'})
        game = self.server.game
        try:
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n).decode('utf8') or '{}')
            if not isinstance(body, dict):
                raise Hata('JSON nesnesi gerekli.')
            if self.path == '/ver':
                return self._send(200, grant(game, body.get('oyuncu'), body.get('esya'), body.get('adet')))
            if self.path == '/herkese_ver':
                return self._send(200, grant_all(game, body.get('esya'), body.get('adet')))
            if self.path == '/cikar':
                return self._send(200, remove(game, body.get('oyuncu'), body.get('esya'), body.get('adet')))
            return self._send(404, {'hata': 'yok'})
        except (ValueError, RuntimeError) as exc:
            return self._send(400, _error_body(exc))
        except Exception:
            game.log('yönetim: işlem hatası (%s)' % self.path)
            return self._send(500, {'hata': 'İşlem yapılamadı.'})


def start(game, secret, port=PORT):
    """Start the Panel-only management listener if the Panel supplied a secret."""
    if not secret:
        return None
    try:
        server = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
    except OSError as exc:
        game.log('panel yönetim kanalı açılamadı (port %d): %s' % (port, exc))
        return None
    server.game, server.owner_secret = game, secret
    game.log('panel yönetim kanalı: 127.0.0.1:%d' % port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
