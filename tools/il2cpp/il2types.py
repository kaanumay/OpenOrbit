"""Il2CppMetadataRegistration -> Il2CppType table; turns field/parameter/return types into readable names (x86)."""
import struct, sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # also with python -I: the modules next to it
from symbols import Symbols

S = Symbols()
pe, m = S.pe, S.m
NT = len(m.types)

ELEM = {1: 'void', 2: 'bool', 3: 'char', 4: 'sbyte', 5: 'byte', 6: 'short', 7: 'ushort', 8: 'int', 9: 'uint', 10: 'long', 11: 'ulong',
        12: 'float', 13: 'double', 14: 'string', 0x18: 'IntPtr', 0x19: 'UIntPtr', 0x1c: 'object'}


def find_metadata_registration():
    for sec in pe.sections:
        if sec['name'] in ('.data', '.rdata'):
            r = _scan(sec)
            if r:
                return r
    return None


def _scan(data):
    b = pe.b
    o = data['roff']
    end = o + data['rsize'] - 64
    pat = struct.pack('<I', NT)
    while True:
        o = b.find(pat, o, end)
        if o < 0:
            return None
        if o % 4 == 0:
            # fieldOffsetsCount, fieldOffsets, typeDefinitionsSizesCount, typeDefinitionsSizes
            c1, p1, c2, p2 = struct.unpack_from('<IIII', b, o)
            if c1 == NT and c2 == NT and pe.va2off(p1) and pe.va2off(p2):
                base = o - 4 * 10   # first 5 pairs: genericClasses, genericInsts, genericMethodTable, types, methodSpecs
                vals = struct.unpack_from('<10I', b, base)
                return dict(genericClassesCount=vals[0], genericClasses=vals[1], genericInstsCount=vals[2], genericInsts=vals[3],
                            genericMethodTableCount=vals[4], genericMethodTable=vals[5], typesCount=vals[6], types=vals[7],
                            methodSpecsCount=vals[8], methodSpecs=vals[9], fieldOffsets=p1, typeDefinitionsSizes=p2)
        o += 1


MR = find_metadata_registration()
_types_ptrs = struct.unpack_from('<%dI' % MR['typesCount'], pe.b, pe.va2off(MR['types']))


def il2cpp_type(idx):
    p = _types_ptrs[idx]
    data, bits = struct.unpack_from('<II', pe.b, pe.va2off(p))
    return data, (bits >> 16) & 0xFF, bits & 0xFFFF


def type_name(idx, depth=0):
    data, t, attrs = il2cpp_type(idx)
    if t in ELEM:
        return ELEM[t]
    if t in (0x11, 0x12):  # VALUETYPE, CLASS -> typedef index
        return S.type_name(data) if 0 <= data < NT else 'class#%d' % data
    if t == 0x1d:  # SZARRAY -> data = Il2CppType*
        return _ptr_type_name(data, depth) + '[]'
    if t == 0x15 and depth < 4:  # GENERICINST -> Il2CppGenericClass*
        gc = pe.va2off(data)
        if gc is None:
            return 'generic?'
        type_ptr, inst_ptr = struct.unpack_from('<II', pe.b, gc)[:2]
        base = _ptr_type_name(type_ptr, depth + 1)
        argc, argv = struct.unpack_from('<II', pe.b, pe.va2off(inst_ptr))
        args = [_ptr_type_name(a, depth + 1) for a in struct.unpack_from('<%dI' % argc, pe.b, pe.va2off(argv))]
        return base.split('`')[0] + '<' + ','.join(args) + '>'
    if t in (0x13, 0x1e):
        return 'T%d' % data
    return 'type%#x' % t


_ptr_index = None


def _ptr_type_name(ptr, depth):
    global _ptr_index
    if _ptr_index is None:
        _ptr_index = {p: i for i, p in enumerate(_types_ptrs)}
    i = _ptr_index.get(ptr)
    if i is not None:
        return type_name(i, depth)
    off = pe.va2off(ptr)
    if off is None:
        return '?'
    data, bits = struct.unpack_from('<II', pe.b, off)
    t = (bits >> 16) & 0xFF
    if t in ELEM:
        return ELEM[t]
    if t in (0x11, 0x12):
        return S.type_name(data) if 0 <= data < NT else '?'
    return 'type%#x' % t


def field_offsets(ti):
    p = struct.unpack_from('<I', pe.b, pe.va2off(MR['fieldOffsets']) + 4 * ti)[0]
    if not p or pe.va2off(p) is None:
        return None
    n = m.types[ti]['field_count']
    return struct.unpack_from('<%di' % n, pe.b, pe.va2off(p))


def describe(ti):
    out = []
    offs = field_offsets(ti)
    for k, fi in enumerate(m.type_fields(ti)):
        f = m.fields[fi]
        out.append((f['name'], type_name(f['typeIndex']), offs[k] if offs else None))
    return out


def find_type(full):
    for ti in range(NT):
        if S.type_name(ti) == full:
            return ti
    return None


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print('MR', {k: (hex(v) if v > 100000 else v) for k, v in MR.items()})
    for q in sys.argv[1:]:
        ti = find_type(q)
        print('==', q, ti)
        if ti is not None:
            for name, tn, off in describe(ti):
                print('   %-45s %-40s %s' % (name, tn, hex(off) if off is not None else ''))
