"""IL2CPP address <-> method name map and named disassembly (GameAssembly.dll, x86)."""
import sys, os, struct, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meta import Metadata
from pe import PE

# Client folder: the OO_CLIENT environment variable (protocol_update.py supplies it for a new version), else 1.1.116. The cache is per client
# (1.1.114's is symbols.pkl as before).
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('OO_CLIENT') or os.path.join(os.path.dirname(os.path.dirname(_HERE)), 'DarkOrbit_Version1.1.116')
_tag = os.path.basename(os.path.normpath(ROOT))
CACHE = os.path.join(_HERE, 'symbols.pkl' if _tag == 'DarkOrbit_Version1.1.114' else 'symbols_%s.pkl' % _tag)


class Symbols:
    def __init__(self):
        self.m = Metadata(os.path.join(ROOT, 'DarkOrbit_Data', 'il2cpp_data', 'Metadata', 'global-metadata.dat'))
        self.pe = PE(os.path.join(ROOT, 'GameAssembly.dll'))
        if os.path.exists(CACHE):
            self.addr2name, self.name2addr, self.method_addr = pickle.load(open(CACHE, 'rb'))
            return
        self.addr2name, self.name2addr, self.method_addr = {}, {}, {}
        for img in self.m.images:
            types = range(img['typeStart'], img['typeStart'] + img['typeCount'])
            nmeth = sum(self.m.types[t]['method_count'] for t in types)
            cands = self.pe.find_codegen_module(img['name'], nmeth) if nmeth else []
            cands = [c for c in cands if self.pe.va2off(c['methodPointers']) is not None]
            if not cands:
                continue
            mp = cands[0]['methodPointers']
            ptrs = struct.unpack_from('<%dI' % nmeth, self.pe.b, self.pe.va2off(mp))
            for t in types:
                tn = self.type_name(t)
                for mi in self.m.type_methods(t):
                    M = self.m.methods[mi]
                    rid = M['token'] & 0xFFFFFF
                    a = ptrs[rid - 1] if 0 < rid <= len(ptrs) else 0
                    name = tn + '$$' + M['name']
                    self.method_addr[mi] = a
                    if a:
                        self.addr2name.setdefault(a, name)
                        self.name2addr.setdefault(name, a)
        pickle.dump((self.addr2name, self.name2addr, self.method_addr), open(CACHE, 'wb'))

    def type_name(self, ti):
        t = self.m.types[ti]
        n = t['name']
        d = t['declaring']
        seen = 0
        while 0 <= d < len(self.m.types) and seen < 8:
            n = self.m.types[d]['name'] + '.' + n
            if self.m.types[d]['ns']:
                return self.m.types[d]['ns'] + '.' + n
            d = self.m.types[d]['declaring']
            seen += 1
        return (t['ns'] + '.' if t['ns'] else '') + n

    # IL2CPP v27+: the initial value of a metadata usage global is an encoded token
    # (type << 29) | (index << 1) | 1 ; type 5 = string literal, 3 = method definition, 6 = method reference
    def usage(self, p):
        v = self.pe.u32(p)
        if v in self.addr2name:
            return 'ptr->' + self.addr2name[v]
        if v & 1:
            kind, idx = v >> 29, (v & 0x1FFFFFFE) >> 1
            if kind == 5:
                if not hasattr(self, '_lits'):
                    self._lits = self.m.string_literals()
                if idx < len(self._lits):
                    return 'STR %r' % self._lits[idx][:120]
            if kind == 3 and idx < len(self.m.methods):
                M = self.m.methods[idx]
                return 'METHOD ' + self.type_name(M['type']) + '$$' + M['name']
            return 'usage(%d,%d)' % (kind, idx)
        return ''

    def find(self, substr):
        return sorted((n, a) for n, a in self.name2addr.items() if substr in n)

    def disasm(self, addr, max_insn=400, stop_at_ret=True):
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = False
        off = self.pe.va2off(addr)
        code = self.pe.b[off:off + max_insn * 8]
        out = []
        for ins in md.disasm(code, addr):
            note = ''
            if ins.mnemonic in ('call', 'jmp') and ins.op_str.startswith('0x'):
                tgt = int(ins.op_str, 16)
                note = self.addr2name.get(tgt, '')
            elif 'dword ptr [0x' in ins.op_str:
                try:
                    p = int(ins.op_str.split('[0x')[1].split(']')[0], 16)
                    note = self.usage(p) if self.pe.va2off(p) else ''
                except Exception:
                    pass
            out.append('%08x  %-6s %-40s %s' % (ins.address, ins.mnemonic, ins.op_str, note))
            if stop_at_ret and ins.mnemonic == 'ret':
                break
            if len(out) >= max_insn:
                break
        return '\n'.join(out)


if __name__ == '__main__':
    S = Symbols()
    print('mapped methods', len(S.addr2name))
    for q in sys.argv[1:]:
        for n, a in S.find(q)[:50]:
            print(hex(a), n)
