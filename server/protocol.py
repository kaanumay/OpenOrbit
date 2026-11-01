"""The game protocol of the DarkOrbit Unity client: framing, server compression and message decoding.

Source: the client's own code (tools/il2cpp/read_spec.py -> server/data/protocol_read.json).
No dependencies (only the Python standard library).

Framing:
  client -> server : the first packet has a 4-byte BE length, later ones a 3-byte BE length
  server -> client : 3-byte BE length
  payload          : u16 message id + fields
Server compression (DarkOrbit.DownstreamCompression, the client proposes "do-lz4-block-v3" in LoginRequest):
  payload = FF FF + magic (u32 BE) + raw length (u32 BE) + CRC32 (u32 BE) + LZ4 block
  "DOB3": the decompressed data consists of inner frames with a 3-byte length; "DOL4": the decompressed data is a single message.
"""
import json, os, struct, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, 'data', 'protocol_read.json')
CLIENT_HASH = '0b64b1b04d103c9ec4b4f121acb7de36'   # the client protocol_read.json was extracted from (1.1.115; the same in 1.1.116) VersionRequest value
SECRET_FIELDS = ('sessionid', 'password', 'token', 'secret')

# fields whose conversion read_spec.py could not find (by hand from the disassembly of the client's read(): the raw value is rotated right by a bits)
FIXES = {
    ('SkylabModuleProductivityCommand', 'bonus?'): ('bonus', ['or', ['shr', 'v', 8], ['shl', 'v', 24]]),
    ('SkylabModuleProductivityCommand', 'maxActive?'): ('maxActive', ['or', ['shr', 'v', 22], ['shl', 'v', 10]]),
    ('SkylabModuleProductivityCommand', 'inStorage?'): ('inStorage', ['or', ['shr', 'v', 17], ['shl', 'v', 15]]),
    # read(): CONCAT11((char)v, (char)((ushort)v >> 8)) - a rotation by 8 in 16 bits; read_spec.py does not follow this pattern
    ('PetActivationCommand', 'petLevel'): ('petLevel', ['or', ['and', ['shr', ['zx16', 'v'], 8], 255], ['shl', ['zx16', 'v'], 8]]),
    ('QualitySettingsRequest', 'qualityExplosion'): ('qualityExplosion', ['or', ['and', ['shr', ['zx16', 'v'], 8], 255], ['shl', ['zx16', 'v'], 8]]),
}

MAGIC_BLOCK = 0x444F4233   # "DOB3"
MAGIC_LEGACY = 0x444F4C34  # "DOL4"


class Spec:
    def __init__(self, path=SPEC_PATH):
        raw = json.load(open(path, encoding='utf8'))
        for v in raw.values():
            for st in v['steps']:
                fix = FIXES.get((v['name'].split('.')[-1], st.get('f')))
                if fix:
                    st['f'], st['x'] = fix
        self.by_id = {int(k): v for k, v in raw.items()}
        self.by_class = {v['name'].split('.')[-1]: v for v in raw.values()}

    def id_of(self, cls):
        if not hasattr(self, '_ids'):
            self._ids = {v['name'].split('.')[-1]: k for k, v in self.by_id.items()}
        return self._ids[cls]

    def name(self, mid):
        m = self.by_id.get(mid & 0xFFFF)
        return m['name'].split('.')[-1] if m else '?%d' % (mid & 0xFFFF)


_SPEC = None


def spec():
    global _SPEC
    if _SPEC is None:
        _SPEC = Spec()
    return _SPEC


# ------------------------------------------------------------------ field conversions
M32 = 0xFFFFFFFF


def _sx(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def eval_x(e, v):
    """Applies the bit operations in read() with 32-bit unsigned arithmetic."""
    if e == 'v':
        return v & M32
    if isinstance(e, int):
        return e & M32
    op = e[0]
    a = eval_x(e[1], v)
    if op in ('sx16', 'zx16', 'sx8', 'zx8'):
        bits = 16 if op.endswith('16') else 8
        return (_sx(a, bits) & M32) if op[0] == 's' else a & ((1 << bits) - 1)
    if op == 'not':
        return ~a & M32
    if op == 'neg':
        return -a & M32
    b = eval_x(e[2], v)
    if op == 'or': return a | b
    if op == 'and': return a & b
    if op == 'xor': return a ^ b
    if op == 'add': return (a + b) & M32
    if op == 'sub': return (a - b) & M32
    if op == 'shl': return (a << (b & 31)) & M32
    if op == 'shr': return a >> (b & 31)
    if op == 'sar': return (_sx(a, 32) >> (b & 31)) & M32
    if op == 'rol': return ((a << (b & 31)) | (a >> (32 - (b & 31)))) & M32 if b & 31 else a
    if op == 'ror': return ((a >> (b & 31)) | (a << (32 - (b & 31)))) & M32 if b & 31 else a
    raise ValueError('unknown operation %r' % (op,))


class DecodeError(Exception):
    pass


class Buf:
    def __init__(self, b):
        self.b, self.o = b, 0

    def take(self, n):
        if self.o + n > len(self.b):
            raise DecodeError('data ended (%d bytes requested, %d left)' % (n, len(self.b) - self.o))
        r = self.b[self.o:self.o + n]; self.o += n
        return r

    def u8(self): return self.take(1)[0]
    def i16(self): return struct.unpack('>h', self.take(2))[0]
    def u16(self): return struct.unpack('>H', self.take(2))[0]
    def u32(self): return struct.unpack('>I', self.take(4))[0]
    def f32(self): return struct.unpack('>f', self.take(4))[0]
    def f64(self): return struct.unpack('>d', self.take(8))[0]

    @property
    def left(self):
        return len(self.b) - self.o


def _prim(buf, t, x):
    if t == 'int' or t == 'uint':
        v = eval_x(x, buf.u32()) if x else buf.u32()
        return _sx(v, 32) if t == 'int' else v
    if t in ('short', 'ushort'):
        raw = buf.i16() & M32
        v = eval_x(x, raw) if x else raw
        return _sx(v, 16) if t == 'short' else v & 0xFFFF
    if t in ('byte', 'sbyte'):
        raw = buf.u8()
        raw = (raw - 256 if raw > 127 else raw) & M32 if t == 'sbyte' else raw
        v = eval_x(x, raw) if (x and x != 'v') else raw
        return _sx(v, 8) if t == 'sbyte' else v & 0xFF
    if t == 'bool':
        return buf.u8() != 0
    if t == 'float':
        return buf.f32()
    if t == 'double':
        d = buf.f64()
        return int(d) if d == int(d) else d
    if t == 'long':
        return int(buf.f64())
    if t == 'string':
        n = buf.u16()
        return buf.take(n).decode('utf8', 'replace')
    if t == 'module':
        return decode_module(buf)
    raise DecodeError('unknown type %s' % t)


def _steps(buf, steps, out, depth, ctx=None):
    ctx = {'n': 0} if ctx is None else ctx
    for s in steps:
        t = s['t']
        if t in ('pid', 'super') and (t == 'pid' or s.get('id', True)):
            # superclass id: if it differs from the expected value it is kept under "_super" (for re-encoding)
            v = buf.u16()
            if v != _parent_id(s.get('c')):
                out.setdefault('_super', {})[str(ctx['n'])] = v
            ctx['n'] += 1
        if t == 'pid':
            continue
        if t == 'super':
            parent = spec().by_class.get(s['c'])
            if parent is None:
                raise DecodeError('superclass unknown: %s' % s['c'])
            _steps(buf, parent['steps'], out, depth, ctx)
            continue
        name = s['f'] or '_%s%d' % (t, len(out))
        if t == 'list':
            n = {'byte': buf.u8, 'short': buf.i16, 'ushort': buf.u16, 'int': buf.u32}[s['n']]()
            if n < 0 or n > 100000:
                raise DecodeError('impossible list length: %d (%s)' % (n, name))
            e = s.get('e') or {'t': 'module'}
            out[name] = [_prim(buf, e['t'], e.get('x')) for _ in range(n)]
        else:
            out[name] = _prim(buf, t, s.get('x'))


def _parent_id(cls):
    try:
        return spec().id_of(cls) if cls else None
    except KeyError:
        return None


def decode_module(buf, depth=0):
    mid = buf.u16()
    if mid == 0:
        return None
    m = spec().by_id.get(mid)
    if m is None:
        raise DecodeError('unknown submodule id %d' % mid)
    out = {'_': m['name'].split('.')[-1]}
    if depth > 30:
        raise DecodeError('nested module depth too large')
    _steps(buf, m['steps'], out, depth + 1)
    return out


def decode_message(payload):
    """Decodes a message payload -> (id, name, fields, remaining_bytes, error)."""
    if len(payload) < 2:
        return None, '?', {}, len(payload), 'short payload'
    mid = struct.unpack('>H', payload[:2])[0]
    m = spec().by_id.get(mid)
    if m is None:
        return mid, '?%d' % mid, {}, len(payload) - 2, 'unknown message id'
    buf = Buf(payload)
    buf.o = 2
    out = {}
    try:
        _steps(buf, m['steps'], out, 0)
        err = None
    except DecodeError as e:
        err = str(e)
    return mid, m['name'].split('.')[-1], out, buf.left, err


# ------------------------------------------------------------------ encoding (the reverse of decoding)
class EncodeError(Exception):
    pass


_INV = {}
warning = None        # encoding warning (an int field clamped to the limit): the game server hooks up the log function
LIST_MAX = {'byte': 255, 'short': 32767, 'ushort': 65535, 'int': M32}


def _inverse_table(t, x):
    """For 16/8-bit fields builds the inverse table by decoding all raw values (exactly consistent with the decoder)."""
    key = (t, json.dumps(x))
    tab = _INV.get(key)
    if tab is None:
        tab = {}
        size = 2 if t in ('short', 'ushort') else 1
        for raw in range(1 << (8 * size)):
            b = raw.to_bytes(size, 'big')
            tab.setdefault(_prim(Buf(b), t, x), b)
        _INV[key] = tab
    return tab


def _enc_prim(out, t, x, v, name=None):
    if t in ('int', 'uint'):
        v = int(v)
        hi = (1 << 31) - 1 if t == 'int' else M32
        if not -(1 << 31) <= v <= hi:      # it would silently wrap to negative (earnings, points): clamped to the limit
            c = min(max(v, -(1 << 31)), hi)
            if warning:
                warning('   field %s did not fit in 32 bits: %d -> %d' % (name or t, v, c))
            v = c
        v &= M32
        if x and x != 'v':
            # read(): value = (raw >>> a) | (raw << b)  ->  raw = the value rotated left by a bits
            if not (x[0] == 'or' and x[1][0] == 'shr' and x[2][0] == 'shl'):
                raise EncodeError('int conversion cannot be inverted %r' % (x,))
            a = x[1][2] & 31
            v = ((v << a) | (v >> (32 - a))) & M32 if a else v
        out += struct.pack('>I', v)
    elif t in ('short', 'ushort', 'byte', 'sbyte'):
        tab = _inverse_table(t, x)
        b = tab.get(int(v))
        if b is None:
            raise EncodeError('field %s cannot hold value %r' % (t, v))
        out += b
    elif t == 'bool':
        out.append(1 if v else 0)
    elif t == 'float':
        out += struct.pack('>f', float(v))
    elif t in ('double', 'long'):
        out += struct.pack('>d', float(v))
    elif t == 'string':
        d = (v or '').encode('utf8')
        out += struct.pack('>H', len(d)) + d
    elif t == 'module':
        if v is None:
            out += b'\x00\x00'
        else:
            _enc_module(out, v)
    else:
        raise EncodeError('unknown type %s' % t)


def _enc_steps(out, steps, f, ctx):
    for s in steps:
        t = s['t']
        if t in ('pid', 'super') and (t == 'pid' or s.get('id', True)):
            parent = f.get('_super') or {}
            v = parent.get(str(ctx['n']), _parent_id(s.get('c')))
            if v is None:
                raise EncodeError('superclass id unknown (%s)' % s.get('c'))
            out += struct.pack('>H', v)
            ctx['n'] += 1
        if t == 'pid':
            continue
        if t == 'super':
            _enc_steps(out, spec().by_class[s['c']]['steps'], f, ctx)
            continue
        name = s['f'] or '_%s%d' % (t, len(f))
        if name not in f and name.endswith('?') and name[:-1] in f:
            name = name[:-1]
        v = f.get(name, _default(s))
        if t == 'list':
            v = v or []
            n = len(v)
            if n > LIST_MAX[s['n']]:
                raise EncodeError('list %s has %d items; its counter (%s) allows at most %d' % (name, n, s['n'], LIST_MAX[s['n']]))
            out += {'byte': lambda: struct.pack('>B', n), 'short': lambda: struct.pack('>h', n),
                    'ushort': lambda: struct.pack('>H', n), 'int': lambda: struct.pack('>I', n)}[s['n']]()
            e = s.get('e') or {'t': 'module'}
            for item in v:
                _enc_prim(out, e['t'], e.get('x'), item, name)
        else:
            _enc_prim(out, t, s.get('x'), v, name)


def _default(s):
    return {'list': [], 'string': '', 'module': None, 'bool': False, 'float': 0.0, 'double': 0.0}.get(s['t'], 0)


def _enc_module(out, f):
    cls = f.get('_')
    m = spec().by_class.get(cls)
    if m is None:
        raise EncodeError('unknown module %r' % cls)
    out += struct.pack('>H', spec().id_of(cls))
    _enc_steps(out, m['steps'], f, {'n': 0})


def encode_message(name, fields=None):
    """Produces a message payload (id + fields); missing fields take the type's default."""
    m = spec().by_class.get(name)
    if m is None:
        raise EncodeError('unknown message %r' % name)
    out = bytearray(struct.pack('>H', spec().id_of(name)))
    _enc_steps(out, m['steps'], fields or {}, {'n': 0})
    return bytes(out)


def frame(payload):
    """Server -> client frame: 3-byte BE length + payload."""
    return len(payload).to_bytes(3, 'big') + payload


def secrets_of(fields, out=None):
    """Collects the values of fields with secret names (e.g. LoginRequest.sessionID)."""
    out = set() if out is None else out
    if isinstance(fields, dict):
        for k, v in fields.items():
            if isinstance(v, str) and len(v) >= 8 and any(s in k.lower() for s in SECRET_FIELDS):
                out.add(v)
            else:
                secrets_of(v, out)
    elif isinstance(fields, list):
        for v in fields:
            secrets_of(v, out)
    return out


def redact(fields, values=()):
    """Hides the secret fields and every text where these values appear (nested structures included).
    Note: the old text protocol also carries the session key (e.g. the client's "S|CFG|2|<user>|<sessionID>")."""
    if isinstance(fields, dict):
        return {k: ('<gizlendi>' if any(s in k.lower() for s in SECRET_FIELDS) and isinstance(v, str) and v else redact(v, values))
                for k, v in fields.items()}
    if isinstance(fields, list):
        return [redact(v, values) for v in fields]
    if isinstance(fields, str):
        for s in values:
            if s in fields:
                fields = fields.replace(s, '<gizlendi>')
    return fields


# ------------------------------------------------------------------ server compression (LZ4 block)
def lz4_block(src, raw_len):
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        if off == 0 or off > len(out):
            raise DecodeError('LZ4: invalid offset')
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        for k in range(ml):
            out.append(out[start + k])
    if len(out) != raw_len:
        raise DecodeError('LZ4: uzunluk tutmuyor (%d != %d)' % (len(out), raw_len))
    return bytes(out)


def downstream(payload):
    """Decompresses the server payload if it is compressed -> [(payload, compression_type)]; otherwise [(payload, None)]."""
    if len(payload) >= 14 and payload[0] == 0xFF and payload[1] == 0xFF:
        magic, raw_len, crc = struct.unpack('>III', payload[2:14])
        if magic in (MAGIC_BLOCK, MAGIC_LEGACY):
            data = lz4_block(payload[14:], raw_len)
            if zlib.crc32(data) & M32 != crc:
                raise DecodeError('compressed block CRC error')
            if magic == MAGIC_LEGACY:
                return [(data, 'DOL4')]
            out, i = [], 0
            while i + 3 <= len(data):
                ln = int.from_bytes(data[i:i + 3], 'big'); i += 3
                out.append((data[i:i + ln], 'DOB3')); i += ln
            return out
    return [(payload, None)]


# ------------------------------------------------------------------ stream framing
class Framer:
    """Splits the byte stream of one TCP direction into message payloads."""

    def __init__(self, client_side):
        self.client_side = client_side
        self.buf = bytearray()
        self.first = True

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            hdr = 3
            if self.client_side and self.first and len(self.buf) >= 6 and self.buf[0] == 0 and self.buf[4:6] == b'\x02\x9a':
                hdr = 4   # VersionRequest (666) comes with a 4-byte length
            if len(self.buf) < hdr:
                break
            n = int.from_bytes(self.buf[:hdr], 'big')
            if len(self.buf) < hdr + n:
                break
            out.append(bytes(self.buf[hdr:hdr + n]))
            del self.buf[:hdr + n]
            self.first = False
        return out


def messages(payload, server_side):
    """Extracts the messages from a frame payload (decompressing if needed) -> [(id, name, fields, remaining, error, compression)]."""
    parts = downstream(payload) if server_side else [(payload, None)]
    res = []
    for p, comp in parts:
        mid, name, fields, left, err = decode_message(p)
        res.append((mid, name, fields, left, err, comp, p))
    return res


def fmt(v, limit=600):
    """Turns the fields into a short, readable single line."""
    def f(x):
        if isinstance(x, dict):
            name = x.get('_', '')
            inner = ', '.join('%s=%s' % (k, f(w)) for k, w in x.items() if not k.startswith('_'))
            return '%s{%s}' % (name, inner)
        if isinstance(x, list):
            return '[' + ', '.join(f(w) for w in x) + ']'
        if isinstance(x, str):
            return json.dumps(x, ensure_ascii=False)
        if isinstance(x, float):
            return '%.6g' % x
        return str(x)
    s = f(v)
    return s if len(s) <= limit else s[:limit] + '…'
