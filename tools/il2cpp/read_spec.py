"""Extracts the wire layout from each protocol module's read() method -> server/data/protocol_read.json

The read() pattern (x86, IL2CPP, EndianBinaryReader virtual calls; reader = [ebp+0xc], this = [ebp+8]):
  reader slots: 0x108 bool, 0x110 byte, 0x128 short, 0x130 ushort, 0x138 int, 0x140 uint,
                0x148 long, 0x158 float, 0x160 double, 0x188 bytes(n)
  int field   : ReadInt32 -> (x >>> a) | (x << b) -> [this+ofs]
  long field  : ReadDouble -> double->long conversion -> [this+ofs], [this+ofs+4]
  string      : Encoding.UTF8 + ReadInt16 (length) + ReadBytes(n) + GetString -> [this+ofs]
  module      : ModuleFactory + ReadInt16 (id) + createInstance + sub.read(reader)
  list        : count (byte/short) + module or primitive reads in a loop + List.Add

Output (ordered steps for each module):
  {"f": field, "t": "int"|"short"|"bool"|"byte"|"float"|"double"|"long"|"string"|"module"|"list",
   "x": transform expression (for int/short, e.g. ["or", ["shr", "v", 14], ["shl", "v", 18]]),
   "n": list count type, "e": list element step}
Usage: python read_spec.py <protocol.json> <output.json> [Class ...]
"""
import sys, re, json, bisect
import capstone
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # also with python -I: the modules next to it
from il2types import describe, type_name, S as S2

S = S2
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
READ_SLOT = {0x108: 'bool', 0x110: 'byte', 0x118: 'sbyte', 0x120: 'char', 0x128: 'short', 0x130: 'ushort', 0x138: 'int',
             0x140: 'uint', 0x148: 'long64', 0x150: 'ulong64', 0x158: 'float', 0x160: 'double', 0x188: 'bytes'}
REGS = ('eax', 'ebx', 'ecx', 'edx', 'esi', 'edi')
SUB = {'ax': 'eax', 'bx': 'ebx', 'cx': 'ecx', 'dx': 'edx', 'si': 'esi', 'di': 'edi',
       'al': 'eax', 'bl': 'ebx', 'cl': 'ecx', 'dl': 'edx', 'ah': 'eax', 'dh': 'edx'}
NAME = {v: k for k, v in S.addr2name.items()}
_addrs = sorted(S.addr2name)
UTF8 = 'System.Text.Encoding$$get_UTF8'
FACTORY_GLOBAL_USAGE = 'net.bigpoint.darkorbit.com.module.ModuleFactory'


def full(r):
    return SUB.get(r, r)


def func_insns(addr):
    end = _addrs[bisect.bisect_right(_addrs, addr)]
    off = S.pe.va2off(addr)
    out = []
    for ins in md.disasm(S.pe.b[off:off + (end - addr)], addr):
        if ins.address >= end:
            break
        out.append(ins)
    return out


def _usage_type(op):
    m = re.search(r'\[(0x[0-9a-f]+)\]', op)
    if not m:
        return None
    u = S.usage(int(m.group(1), 16))
    return u


class Extract:
    """Extracts the ordered events in read(): reads, field writes, module/list structures."""

    def __init__(self, cls):
        self.cls = cls
        ti = None
        for t in range(len(S.m.types)):
            if S.type_name(t) == cls:
                ti = t; break
        self.fields = describe(ti) if ti is not None else []
        # superclass chain: inherited fields sit in the same object, at low offsets
        self.all_fields = list(self.fields)
        self.parents = []      # superclasses (nearest to farthest)
        t = ti
        while t is not None:
            p = S.m.types[t]['parent']
            pn = type_name(p) if p is not None and p >= 0 else ''
            if not pn.startswith('net.bigpoint.'):
                break
            t = next((q for q in range(len(S.m.types)) if S.type_name(q) == pn), None)
            if t is None:
                break
            self.all_fields = describe(t) + self.all_fields
            self.parents.append(pn.split('.')[-1])
        self.by_off = {o: (n, t) for n, t, o in self.all_fields if o is not None}
        self.events = []

    def run(self):
        a = S.name2addr.get(self.cls + '$$read')
        if not a:
            return None
        ins = func_insns(a)
        this_regs, rdr_regs, klass_regs = set(), set(), set()
        this_slots = {'[ebp + 8]'}
        val = {}           # reg -> expression (tied to the read id)
        fp = None          # last floating-point read
        pending_slot = None
        reads = []         # (address, type)
        after_bytes = False
        factory_pending = False
        stores = []
        list_field = {}    # reg -> field offset (list object read from this)
        loop_back = []
        rdr_slots, this_stack = {'[ebp + 0xc]'}, {'[ebp + 8]'}
        klass_src, pending_src, pending_pushes = {}, None, []
        for i, x in enumerate(ins):
            mn, op = x.mnemonic, x.op_str
            # a written register loses its previous roles (the branches below reassign it if needed)
            dst = op.split(',')[0] if ',' in op else (op if mn == 'pop' else '')
            if mn in ('mov', 'movzx', 'movsx', 'lea', 'pop', 'xor', 'sub', 'imul', 'add', 'and', 'or', 'shl', 'shr',
                      'inc', 'dec', 'cwde', 'cdq') and (dst in REGS or full(dst) in REGS):
                list_field.pop(full(dst), None)
                klass_src.pop(full(dst), None)
            if mn == 'call':
                klass_src.pop('eax', None); klass_src.pop('ecx', None); klass_src.pop('edx', None)
            # reader / this saved on the stack (byte/word save: only for the list element conversion)
            m = re.match(r'(?:byte|word) ptr (\[ebp [+-] (?:0x[0-9a-f]+|\d+)\]), (\w+)$', op)
            if mn == 'mov' and m and full(m.group(2)) in val and val[full(m.group(2))][0] not in ('call',):
                self.events.append(('pushval', val[full(m.group(2))], x.address))
                continue
            m = re.match(r'dword ptr (\[ebp [+-] (?:0x[0-9a-f]+|\d+)\]), (\w+)$', op)
            if mn == 'mov' and m:
                if m.group(2) in rdr_regs: rdr_slots.add(m.group(1))
                else: rdr_slots.discard(m.group(1))
                if m.group(2) in this_regs: this_stack.add(m.group(1))
                else: this_stack.discard(m.group(1))
                if full(m.group(2)) in val and val[full(m.group(2))][0] not in ('call',):
                    # a converted list element is saved on the stack and added with an inline List.Add
                    self.events.append(('pushval', val[full(m.group(2))], x.address))
                continue
            # parameter registers
            m = re.match(r'(\w+), dword ptr (\[ebp [+-] (?:0x[0-9a-f]+|\d+)\])$', op)
            if mn == 'mov' and m and (m.group(2) in rdr_slots or m.group(2) in this_stack):
                d = m.group(1)
                this_regs.discard(d); rdr_regs.discard(d); klass_regs.discard(d); val.pop(d, None)
                (rdr_regs if m.group(2) in rdr_slots else this_regs).add(d)
                continue
            # the reader's klass pointer
            m = re.match(r'(\w+), dword ptr \[([a-z]{2,3})\]$', op)
            if mn == 'mov' and m:
                d, s = m.group(1), m.group(2)
                klass_src[d] = s          # d = the klass pointer of object s (virtual call table)
                if s in rdr_regs:
                    klass_regs.add(d)
                else:
                    klass_regs.discard(d)
                val.pop(full(d), None); this_regs.discard(d); rdr_regs.discard(d)
                continue
            # virtual call slot (even if the reader register is unknown: the klass source is remembered)
            m = re.match(r'(?:dword ptr )?\[(\w+) \+ (0x[0-9a-f]+)\]$', op)
            if mn == 'push' and m and m.group(1) in klass_src:
                pending_slot = int(m.group(2), 16) - 4
                pending_src, pending_pushes = klass_src[m.group(1)], []
                continue
            m = re.match(r'(\w+), dword ptr \[(\w+) \+ (0x[0-9a-f]+|\d+)\]$', op)
            if mn == 'mov' and m and m.group(2) in klass_src:
                pending_slot = int(m.group(3), 0)
                pending_src, pending_pushes = klass_src[m.group(2)], []
                val.pop(full(m.group(1)), None)
                continue
            if mn == 'push' and op in REGS and pending_slot is not None:
                pending_pushes.append(op)
            # reading a field from this (list object)
            if mn == 'mov' and m and m.group(2) in this_regs:
                d, o = m.group(1), int(m.group(3), 0)
                if o in self.by_off and 'List<' in self.by_off[o][1]:
                    list_field[d] = o
                else:
                    list_field.pop(d, None)
                val.pop(full(d), None)
                this_regs.discard(d); rdr_regs.discard(d); klass_regs.discard(d)
                continue
            if mn == 'call':
                tgt = S.addr2name.get(int(op, 16), '') if op.startswith('0x') else ''
                if tgt == UTF8:
                    self.events.append(('utf8', x.address)); pending_slot = None; continue
                if op.startswith('0x') and int(op, 16) == DTOL:
                    # double -> long conversion: eax:edx = long(fp)
                    if fp is not None:
                        val['eax'] = ['long', fp]; val['edx'] = ['long_hi', fp]
                    continue
                # reader read: a reader whose klass source is known, or the last pushed (this) argument is the same as the klass source
                # and there is no other reader argument (a sub-module read() call pushes the reader as an argument too)
                is_reader = pending_src in rdr_regs or (
                    pending_pushes and pending_pushes[-1] == pending_src and not any(p in rdr_regs for p in pending_pushes[:-1]))
                if pending_slot in READ_SLOT and is_reader and (op in REGS or op.startswith('dword ptr [ebp')):
                    rdr_regs.add(pending_src)
                    kind = READ_SLOT.get(pending_slot, 'slot%#x' % pending_slot)
                    rid = len(reads); reads.append((x.address, kind))
                    self.events.append(('read', rid, kind, x.address))
                    pending_slot = None
                    if kind in ('float', 'double'):
                        fp = rid; val.pop('eax', None)
                    else:
                        val['eax'] = ['v', rid]
                        val.pop('edx', None)
                    continue
                # a non-reader call (GetString, creating a sub-module with ModuleFactory …): the result is in eax
                val['eax'] = ['call', x.address]
                val.pop('edx', None)
                if tgt.endswith('$$read') and tgt.startswith('net.bigpoint.') and tgt != self.cls + '$$read':
                    # the superclass's read(): first the superclass id (short) is read and discarded, then the superclass fields
                    self.events.append(('super', tgt.split('$$')[0], x.address))
                elif tgt:
                    self.events.append(('callname', tgt, x.address))
                elif op.startswith('0x'):
                    self.events.append(('call', int(op, 16), x.address))
                pending_slot = None
                continue
            if mn == 'mov' and re.search(r'\[0x[0-9a-f]+\]$', op):
                u = _usage_type(op)
                if u and u.startswith('usage(1,'):
                    self.events.append(('klass', u, x.address))
                d = op.split(',')[0]
                val.pop(full(d), None)
                continue
            # value conversions
            if mn == 'mov' and re.match(r'^(\w+), (\w+)$', op):
                d, s = [full(r) for r in op.split(', ')]
                if s in val:
                    val[d] = val[s]
                else:
                    val.pop(d, None)
                was_this, was_rdr, was_klass = s in this_regs, s in rdr_regs, s in klass_regs
                this_regs.discard(d); rdr_regs.discard(d); klass_regs.discard(d)
                if was_this: this_regs.add(d)
                if was_rdr: rdr_regs.add(d)
                if was_klass: klass_regs.add(d)
                if s in list_field: list_field[d] = list_field[s]
                continue
            if mn in ('movzx', 'movsx') and re.match(r'^(\w+), (\w+)$', op):
                d, s = op.split(', ')
                fs = full(s)
                if fs in val:
                    w = 16 if s in ('ax', 'bx', 'cx', 'dx', 'si', 'di') else 8 if s in SUB else 32
                    val[full(d)] = [('sx' if mn == 'movsx' else 'zx') + str(w), val[fs]] if w < 32 else val[fs]
                else:
                    val.pop(full(d), None)
                continue
            if mn == 'cwde':
                if 'eax' in val:
                    val['eax'] = ['sx16', val['eax']]
                continue
            if mn in ('shl', 'shr', 'sar', 'rol', 'ror', 'and', 'or', 'xor', 'add', 'sub', 'not', 'neg') :
                parts = op.split(', ')
                d = full(parts[0])
                if d in val:
                    if len(parts) == 1:
                        val[d] = [mn, val[d]]
                    else:
                        s = parts[1]
                        if re.match(r'^-?(0x[0-9a-f]+|\d+)$', s):
                            val[d] = [mn, val[d], int(s, 0)]
                        elif full(s) in val:
                            if mn == 'add' and full(s) == d:
                                val[d] = ['shl', val[d], 1]
                            else:
                                val[d] = [mn, val[d], val[full(s)]]
                        else:
                            val.pop(d, None)
                continue
            # field writes
            m = re.match(r'(dword|word|byte) ptr \[(\w+) \+ (0x[0-9a-f]+|\d+)\], (\w+)$', op)
            if mn == 'mov' and m and m.group(2) in this_regs:
                o, s = int(m.group(3), 0), full(m.group(4))
                stores.append((x.address, o, val.get(s), m.group(1)))
                self.events.append(('store', o, val.get(s), m.group(1), x.address))
                continue
            m = re.match(r'(dword|qword) ptr \[(\w+) \+ (0x[0-9a-f]+|\d+)\]$', op)
            if mn == 'fstp' and m and m.group(2) in this_regs:
                o = int(m.group(3), 0)
                self.events.append(('store', o, ['fp', fp], m.group(1), x.address))
                continue
            if mn == 'push' and op in REGS and op in list_field:
                self.events.append(('listref', list_field[op], x.address))
                continue
            if mn == 'push' and full(op) in val and val[full(op)][0] not in ('call',):
                # a primitive list element is pushed together with its conversion to List.Add
                self.events.append(('pushval', val[full(op)], x.address))
            if mn.startswith('j') and op.startswith('0x') and int(op, 16) < x.address:
                self.events.append(('loop', int(op, 16), x.address))
                continue
            if mn in ('lea', 'pop', 'xor', 'inc', 'dec', 'imul') or mn == 'mov':
                d = op.split(',')[0]
                if full(d) in REGS:
                    val.pop(full(d), None)
                    this_regs.discard(d); rdr_regs.discard(d); klass_regs.discard(d)
        self.reads = reads
        return self.events


# double -> long helper (MSVC _dtol3; fisttp if SSE3 is present): its address shifts with the version (1.1.114 0x1024e060, 1.1.115
# 0x1024ed50), found from the byte pattern. If not found, long fields come out as "double?".
_DTOL = re.search(rb'\x83\x3d....\x02\x7c\x15\x8b\xcc\x83\xc4\xf8\x83\xe4\xf8\xdd\x0c\x24\x8b\x04\x24\x8b\x54\x24\x04\x8b\xe1\xc3',
                  S.pe.b, re.S)
DTOL = S.pe.off2va(_DTOL.start()) if _DTOL else None


def expr_vars(e):
    if isinstance(e, list):
        if e and e[0] == 'v':
            return {e[1]}
        out = set()
        for z in e[1:]:
            out |= expr_vars(z)
        return out
    return set()


def subst(e, rid):
    if isinstance(e, list):
        if e and e[0] == 'v':
            return 'v'
        return [e[0]] + [subst(z, rid) for z in e[1:]]
    return e


def build_steps(ex):
    """Turns the events into ordered wire steps."""
    ev = ex.events
    steps = []
    used = set()
    i = 0
    reads_by_id = {e[1]: e for e in ev if e[0] == 'read'}
    # find the field each read was written to
    store_of = {}
    for e in ev:
        if e[0] == 'store':
            _, o, v, w, adr = e
            if v is None:
                continue
            if v[0] == 'fp':
                store_of.setdefault(v[1], (o, None, w))
            elif v[0] == 'long':
                store_of.setdefault(v[1], (o, 'long', w))
            elif v[0] == 'long_hi':
                continue
            else:
                vs = expr_vars(v)
                if len(vs) == 1:
                    store_of.setdefault(vs.pop(), (o, v, w))
    # conversion of reads that are not written to a field (added to a list)
    push_of = {}
    for e in ev:
        if e[0] == 'pushval':
            vs = expr_vars(e[1])
            if len(vs) == 1:
                push_of.setdefault(vs.pop(), e[1])
    # detect module and string patterns
    out = []
    k = 0
    n = len(ev)
    pend_utf8 = False
    fac = False
    loops = [e for e in ev if e[0] == 'loop']
    while k < n:
        e = ev[k]
        if e[0] == 'utf8':
            pend_utf8 = True; k += 1; continue
        if e[0] == 'klass' and e[1] == 'usage(1,%d)' % FACTORY_USAGE:
            fac = True; k += 1; continue
        if e[0] == 'read':
            rid, kind, adr = e[1], e[2], e[3]
            if pend_utf8 and kind in ('short', 'ushort'):
                # length + bytes + GetString -> field
                j = k + 1
                while j < n and not (ev[j][0] == 'read'):
                    j += 1
                if j < n and ev[j][2] == 'bytes':
                    # the field the GetString result is written to
                    o = None
                    for q in range(j + 1, n):
                        if ev[q][0] == 'store' and ev[q][2] is not None and ev[q][2][0] == 'call':
                            o = ev[q][1]; break
                        if ev[q][0] in ('read', 'utf8'):
                            break
                    out.append({'k': 'string', 'adr': adr, 'off': o})
                    pend_utf8 = False
                    k = j + 1
                    continue
            if fac and kind in ('short', 'ushort'):
                out.append({'k': 'module', 'adr': adr, 'off': None})
                fac = False
                k += 1
                continue
            st = store_of.get(rid)
            item = {'k': kind, 'adr': adr, 'off': st[0] if st else None}
            if st and st[1] not in (None, 'long'):
                item['x'] = subst(st[1], rid)
            if st and st[1] == 'long':
                item['k'] = 'long'
            if not st and rid in push_of and push_of[rid][0] not in ('v',):
                item['x'] = subst(push_of[rid], rid)
            out.append(item)
            k += 1
            continue
        if e[0] == 'store' and e[2] is not None and e[2][0] == 'call':
            # the sub-module object is written to the field
            for it in reversed(out):
                if it['k'] == 'module' and it['off'] is None:
                    it['off'] = e[1]; break
        if e[0] == 'super':
            # the short read discarded just before is the superclass id
            for it in reversed(out):
                if it['k'] in ('short', 'ushort') and it['off'] is None and 'x' not in it:
                    it['k'] = 'super'; it['cls'] = e[1]; break
            else:
                out.append({'k': 'super', 'cls': e[1], 'adr': e[2], 'off': None, 'noid': True})
        if e[0] == 'listref':
            # List.Add(list, element): the last module/primitive read is this list's element
            for it in reversed(out):
                if it.get('list') is None and it['k'] != 'count':
                    it['list'] = e[1]; break
        k += 1
    # list counters: the read just before the loop
    for lp in loops:
        start, end = lp[1], lp[2]
        inside = [it for it in out if start <= it['adr'] <= end]
        before = [it for it in out if it['adr'] < start]
        if inside and before:
            cnt = before[-1]
            if cnt['off'] is None and cnt['k'] in ('byte', 'short', 'ushort', 'int'):
                cnt['k_count'] = cnt['k']; cnt['k'] = 'count'
                lst = next((it.get('list') for it in inside if it.get('list') is not None), None)
                cnt['loop'] = (start, end)
                cnt['list'] = lst
                for it in inside:
                    it['in_loop'] = start
    return out


FACTORY_USAGE = None
PRIM_OF = {'int': ('int', 'uint'), 'short': ('short', 'ushort'), 'ushort': ('short', 'ushort'), 'bool': ('bool',),
           'byte': ('byte', 'sbyte'), 'sbyte': ('sbyte', 'byte'), 'float': ('float',), 'double': ('double', 'long'),
           'long': ('long', 'ulong', 'double'), 'string': ('string',)}


def type_ok(step_t, field_t):
    """Is the wire step type compatible with the C# field type? (enums are read as short or int)"""
    if not field_t:
        return True
    if step_t == 'list':
        return 'List<' in field_t or field_t.endswith('[]')
    if step_t == 'module':
        return '.' in field_t and 'List<' not in field_t and field_t not in ('string',)
    if field_t in ('int', 'uint', 'short', 'ushort', 'bool', 'byte', 'sbyte', 'float', 'double', 'long', 'ulong', 'string'):
        return field_t in PRIM_OF.get(step_t, ())
    # an unknown simple name = enum (read as int/short)
    return step_t in ('int', 'short', 'ushort', 'byte', 'sbyte')


# (class, field) -> (right, left) shift; from the client's read() code (live test H50)
MANUAL_X = {('SkylabModuleProductivityCommand', 'bonus'): (8, 24), ('SkylabModuleProductivityCommand', 'maxActive'): (22, 10),
            ('SkylabModuleProductivityCommand', 'inStorage'): (17, 15), ('SkylabModuleProductivityCommand', 'active'): (3, 29),
            ('ExchangesShopItem', 'maxLimit'): (12, 20),
            ('ExchangesShopItem', 'limit'): (26, 6), ('ExchangesShopItem', 'eid'): (9, 23),
            ('ExpeditionInfoCommand', 'timeLimit'): (20, 12), ('ExpeditionInfoCommand', 'myRank'): (20, 12),
            ('DisplayOfferCommand', 'percentage'): (23, 9)}


def to_steps(cls):
    ex = Extract(cls)
    if ex.run() is None:
        return None, ex
    items = build_steps(ex)
    fields = {o: (nm, t) for nm, t, o in ex.all_fields if o is not None}
    # if the first read is a short that is written nowhere, it is the superclass id (the superclass's read() is inlined)
    for n_pid, it in enumerate(items):
        if it['k'] in ('short', 'ushort') and it['off'] is None and 'x' not in it and not it.get('in_loop'):
            it['k'] = 'pid'
            it['cls'] = ex.parents[n_pid] if n_pid < len(ex.parents) else None
        else:
            break
    steps = []
    k = 0
    while k < len(items):
        it = items[k]
        if it['k'] == 'count':
            el = [z for z in items if z.get('in_loop') == it['loop'][0]]
            o = it.get('list')
            if o is None:
                o = next((z.get('list') for z in el if z.get('list') is not None), None)
            e = None
            if el:
                z = el[0]
                e = {'t': z['k']}
                if 'x' in z:
                    e['x'] = z['x']
            steps.append({'f': fields.get(o, ('?', ''))[0] if o is not None else None, 't': 'list', 'n': it['k_count'], 'e': e})
            k += 1 + len(el)
            continue
        if it.get('in_loop') is not None:
            k += 1
            continue
        if it['k'] == 'super':
            steps.append({'f': None, 't': 'super', 'c': it['cls'].split('.')[-1], 'id': not it.get('noid')})
            k += 1
            continue
        nm = fields.get(it['off'], (None, ''))[0] if it['off'] is not None else None
        s = {'f': nm, 't': it['k']}
        if 'x' in it:
            s['x'] = it['x']
        if it['k'] == 'pid':
            s['c'] = it.get('cls')   # inlined superclass (its id is written)
        steps.append(s)
        k += 1
    return steps, ex


def main():
    global FACTORY_USAGE
    from il2types import type_name
    # ModuleFactory usage id
    for idx in range(60232):
        try:
            if type_name(idx) == FACTORY_GLOBAL_USAGE:
                FACTORY_USAGE = idx; break
        except Exception:
            continue
    proto = json.load(open(sys.argv[1], encoding='utf8'))
    only = set(sys.argv[3:])
    out = {}
    problems = 0
    for cls, info in proto.items():
        short = cls.split('.')[-1]
        if only and short not in only:
            continue
        steps, ex = to_steps(cls)
        if steps is None:
            continue
        declared = [n for n, t, o in ex.fields if o is not None]
        dtype = {n: t for n, t, o in ex.all_fields}
        # type check: if the step type does not match the declared field type or the name was used twice, remove the name
        seen = set()
        for s in steps:
            if s['f'] is None or s['t'] in ('pid', 'super'):
                continue
            if s['f'] in seen or not type_ok(s['t'], dtype.get(s['f'], '')):
                s['f'] = None
            else:
                seen.add(s['f'])
        got = [s['f'] for s in steps]
        missing = [d for d in declared if d not in got]
        # steps whose name was not found: if there is a single type-compatible candidate, to it; otherwise if the counts are equal, by
        # declaration order ("?" = guess)
        unnamed = [s for s in steps if s['f'] is None and s['t'] not in ('pid', 'super')]
        for s in unnamed:
            cand = [d for d in missing if type_ok(s['t'], dtype.get(d, ''))]
            if len(cand) == 1:
                s['f'] = cand[0] + '?'
                missing.remove(cand[0])
        unnamed = [s for s in steps if s['f'] is None and s['t'] not in ('pid', 'super')]
        if unnamed and len(unnamed) == len(missing):
            for s, nm in zip(unnamed, missing):
                s['f'] = nm + '?'
            missing = []
        unknown = sum(1 for s in steps if s['f'] is None and s['t'] not in ('pid', 'super'))
        if missing or unknown:
            problems += 1
        out[str(info['id'] & 0xFFFF)] = {'name': cls, 'steps': steps, 'missing': missing}   # the id is 16 bit as on the wire
        if only:
            print(cls, info['id'])
            for s in steps:
                print('   ', s)
            if missing:
                print('   MISSING:', missing)
    # the conversion of integers that come after a module read cannot be extracted (the shift information is lost): the ones read by hand
    # from the client's read code (live test H50: Echoes' time limit was read as 2,457,600 s instead of 600, "10:40:00")
    for m in out.values():
        for s in m['steps']:
            k = (m['name'].split('.')[-1], (s['f'] or '').rstrip('?'))
            if k in MANUAL_X and 'x' not in s:
                a, b = MANUAL_X[k]
                s['x'], s['f'] = ['or', ['shr', 'v', a], ['shl', 'v', b]], k[1]
    if not only:
        json.dump(out, open(sys.argv[2], 'w', encoding='utf8'), ensure_ascii=False, indent=0)
        print('modules', len(out), 'problems', problems)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
