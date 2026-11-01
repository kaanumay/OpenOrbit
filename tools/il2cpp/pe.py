"""Minimal PE32 reader + IL2CPP CodeGenModule finder (GameAssembly.dll)."""
import struct


class PE:
    def __init__(self, path):
        b = self.b = open(path, 'rb').read()
        e = struct.unpack_from('<I', b, 0x3C)[0]
        assert b[e:e + 4] == b'PE\0\0'
        machine, nsec = struct.unpack_from('<HH', b, e + 4)
        opt_size = struct.unpack_from('<H', b, e + 20)[0]
        opt = e + 24
        magic = struct.unpack_from('<H', b, opt)[0]
        self.is64 = magic == 0x20B
        self.base = struct.unpack_from('<Q' if self.is64 else '<I', b, opt + (24 if self.is64 else 28))[0]
        self.sections = []
        so = opt + opt_size
        for i in range(nsec):
            name, vsize, va, rsize, roff = struct.unpack_from('<8sIIII', b, so + i * 40)
            self.sections.append(dict(name=name.rstrip(b'\0').decode(), vsize=vsize, va=va, rsize=rsize, roff=roff))

    def off2va(self, off):
        for s in self.sections:
            if s['roff'] <= off < s['roff'] + s['rsize']:
                return self.base + s['va'] + off - s['roff']
        return None

    def va2off(self, va):
        rva = va - self.base
        for s in self.sections:
            if s['va'] <= rva < s['va'] + max(s['vsize'], s['rsize']):
                o = rva - s['va']
                return s['roff'] + o if o < s['rsize'] else None
        return None

    def u32(self, va):
        return struct.unpack_from('<I', self.b, self.va2off(va))[0]

    def cstr(self, va):
        o = self.va2off(va)
        return self.b[o:self.b.index(b'\0', o)].decode('latin1')

    def find_codegen_module(self, module_name, expected_count=None):
        """Finds the Il2CppCodeGenModule { moduleName*, methodPointerCount, methodPointers*, ... } structure."""
        needle = module_name.encode() + b'\0'
        res = []
        start = 0
        while True:
            o = self.b.find(needle, start)
            if o < 0:
                break
            start = o + 1
            if o > 0 and self.b[o - 1] != 0:
                continue
            va = self.off2va(o)
            ptr = struct.pack('<I', va)
            p = 0
            while True:
                q = self.b.find(ptr, p)
                if q < 0:
                    break
                p = q + 1
                if q % 4:
                    continue
                cnt, mptrs = struct.unpack_from('<II', self.b, q + 4)
                if expected_count is None or cnt == expected_count:
                    res.append(dict(struct_va=self.off2va(q), count=cnt, methodPointers=mptrs))
        return res
