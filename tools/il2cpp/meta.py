"""IL2CPP global-metadata.dat (v31) parser: images, types, methods, fields, constant values, string literals.

Usage (module): from meta import Metadata; m = Metadata(path)
"""
import struct

HDR_FIELDS = ['stringLiteral', 'stringLiteralData', 'string', 'events', 'properties', 'methods', 'parameterDefaultValues',
              'fieldDefaultValues', 'fieldAndParameterDefaultValueData', 'fieldMarshaledSizes', 'parameters', 'fields',
              'genericParameters', 'genericParameterConstraints', 'genericContainers', 'nestedTypes', 'interfaces',
              'vtableMethods', 'interfaceOffsets', 'typeDefinitions', 'images', 'assemblies', 'fieldRefs',
              'referencedAssemblies', 'attributeData', 'attributeDataRange', 'unresolvedIndirectCallParameterTypes',
              'unresolvedIndirectCallParameterRanges', 'windowsRuntimeTypeNames', 'windowsRuntimeStrings',
              'exportedTypeDefinitions']


class Metadata:
    def __init__(self, path):
        b = self.b = open(path, 'rb').read()
        self.magic, self.version = struct.unpack_from('<Ii', b, 0)
        assert self.magic == 0xFAB11BAF, hex(self.magic)
        self.h = {}
        for i, n in enumerate(HDR_FIELDS):
            off, size = struct.unpack_from('<Ii', b, 8 + i * 8)
            self.h[n] = (off, size)
        self._parse()

    def s(self, idx):
        o = self.h['string'][0] + idx
        e = self.b.index(b'\0', o)
        return self.b[o:e].decode('utf8', 'replace')

    def table(self, name, fmt):
        off, size = self.h[name]
        n = struct.calcsize(fmt)
        return [struct.unpack_from(fmt, self.b, off + i * n) for i in range(size // n)]

    def _parse(self):
        # Il2CppImageDefinition: nameIndex, assemblyIndex, typeStart, typeCount, exportedTypeStart, exportedTypeCount, entryPointIndex, token, caStart, caCount
        self.images = [dict(name=self.s(r[0]), typeStart=r[2], typeCount=r[3], token=r[7]) for r in self.table('images', '<IiiIiIiIiI')]
        # Il2CppTypeDefinition v31 (88 bayt)
        tfmt = '<IIiiiiiIiiiiiiii8HII'
        self.types = []
        for r in self.table('typeDefinitions', tfmt):
            self.types.append(dict(name=self.s(r[0]), ns=self.s(r[1]), byval=r[2], declaring=r[3], parent=r[4], flags=r[7],
                                   fieldStart=r[8], methodStart=r[9], eventStart=r[10], propertyStart=r[11], nestedStart=r[12],
                                   method_count=r[16], property_count=r[17], field_count=r[18], nested_count=r[20], token=r[25]))
        # Il2CppMethodDefinition v31 (36 bayt): nameIndex, declaringType, returnType, returnParameterToken, parameterStart, genericContainerIndex, token, flags, iflags, slot, parameterCount
        self.methods = [dict(name=self.s(r[0]), type=r[1], ret=r[2], pstart=r[4], token=r[6], flags=r[7], slot=r[9], pcount=r[10])
                        for r in self.table('methods', '<IiiIiiIHHHH')]
        # Il2CppParameterDefinition: nameIndex, token, typeIndex
        self.params = [dict(name=self.s(r[0]), typeIndex=r[2]) for r in self.table('parameters', '<IIi')]
        # Il2CppFieldDefinition: nameIndex, typeIndex, token
        self.fields = [dict(name=self.s(r[0]), typeIndex=r[1], token=r[2]) for r in self.table('fields', '<IiI')]
        # Il2CppFieldDefaultValue: fieldIndex, typeIndex, dataIndex
        self.field_defaults = {r[0]: (r[1], r[2]) for r in self.table('fieldDefaultValues', '<iii')}
        self.nested = [r[0] for r in self.table('nestedTypes', '<i')]
        for ti, t in enumerate(self.types):
            t['index'] = ti
        for img in self.images:
            for ti in range(img['typeStart'], img['typeStart'] + img['typeCount']):
                self.types[ti]['image'] = img['name']

    def full_name(self, ti):
        t = self.types[ti]
        if t['declaring'] >= 0 and t['declaring'] < len(self.types) and False:
            pass
        return (t['ns'] + '.' if t['ns'] else '') + t['name']

    def type_methods(self, ti):
        t = self.types[ti]
        return range(t['methodStart'], t['methodStart'] + t['method_count']) if t['methodStart'] >= 0 else range(0)

    def type_fields(self, ti):
        t = self.types[ti]
        return range(t['fieldStart'], t['fieldStart'] + t['field_count']) if t['fieldStart'] >= 0 else range(0)

    def default_raw(self, fi, n=8):
        if fi not in self.field_defaults:
            return None
        _, di = self.field_defaults[fi]
        o = self.h['fieldAndParameterDefaultValueData'][0] + di
        return self.b[o:o + n]

    def string_literals(self):
        off, size = self.h['stringLiteral']
        doff = self.h['stringLiteralData'][0]
        out = []
        n = size // 8
        for i in range(n):
            length, di = struct.unpack_from('<Ii', self.b, off + i * 8)
            out.append(self.b[doff + di:doff + di + length].decode('utf8', 'replace'))
        return out


def read_compressed_uint(b, o):
    v = b[o]
    if v & 0x80 == 0:
        return v, 1
    if v & 0xC0 == 0x80:
        return ((v & 0x3F) << 8) | b[o + 1], 2
    if v & 0xE0 == 0xC0:
        return ((v & 0x1F) << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3], 4
    if v == 0xF0:
        return struct.unpack_from('<I', b, o + 1)[0], 5
    if v == 0xFE:
        return 0xFFFFFFFE, 1
    if v == 0xFF:
        return 0xFFFFFFFF, 1
    return None, 1


def read_compressed_int(b, o):
    u, n = read_compressed_uint(b, o)
    if u is None:
        return None, n
    if u == 0xFFFFFFFF:
        return -2147483648, n
    neg = u & 1
    u >>= 1
    return (-u - 1 if neg else u), n
