"""Protocol adaptation to a new client version (roadmap "Ongoing work" > preparing for a client update).

Regenerates the protocol from the new version's GameAssembly.dll (protocol.py -> protocol.json, read_spec.py -> protocol_read.json;
client folder via OO_CLIENT), puts it in the version folder (server/data/protocols/<version>/), compares it with the active protocol, reports
the differences (belgeler/istemci/protokol_farki_<version>.md) and applies on request (the active files are backed up, the new ones go to server/data/;
the active version is in server/data/protocols/version.txt, which the panel compares the client version with).

Report: added / deleted messages, ones whose id changed, ones whose fields changed (added, deleted, order or type changed), ones whose
encoding (write) and read steps (read; bit rotations) changed. Messages named in the server's source are marked "sunucuda kullanılıyor"
(used on the server): look at those first. Fields whose name read_spec.py could not determine ('ad?') are fixed automatically if the
field list has the same name and no conversion is needed (text, bool) (the same as what was done by hand in 1.1.114); the rest are in the report.
Verification: run for 1.1.114 it is identical to the active protocol.json, and in protocol_read.json only the 3 fields fixed by hand differ.

Usage (from the project root):
  python -I tools/il2cpp/protocol_update.py <client folder>            generate and report (does not touch the active files)
  python -I tools/il2cpp/protocol_update.py <client folder> --apply   generate, report and apply
  python -I tools/il2cpp/protocol_update.py --activate=<version>              make the protocol in the version folder active (--rollback= also works)
"""
import glob, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SERVER = os.path.join(ROOT, 'server')
DATA = os.path.join(SERVER, 'data')
VDIR = os.path.join(DATA, 'protocols')
VERSION = os.path.join(VDIR, 'version.txt')
FILES = ('protocol.json', 'protocol_read.json')
DEFAULT_VERSION = '1.1.116'


def active_version():
    try:
        return open(VERSION, encoding='utf8').read().strip() or DEFAULT_VERSION
    except OSError:
        return DEFAULT_VERSION


def version_of(folder):
    sys.path.insert(0, os.path.join(SERVER, 'panel'))
    import client
    return client.version_of(folder)


def generate(folder, out, log=print):
    """Two files from the new client -> out/. Subprocess: the symbol cache is per client (symbols.py)."""
    os.makedirs(out, exist_ok=True)
    env = dict(os.environ, OO_CLIENT=os.path.abspath(folder), PYTHONIOENCODING='utf-8')
    py = [sys.executable, '-I', '-X', 'utf8']
    for args in ([os.path.join(HERE, 'protocol.py'), os.path.join(out, 'protocol.json')],
                 [os.path.join(HERE, 'read_spec.py'), os.path.join(out, 'protocol.json'), os.path.join(out, 'protocol_read.json')]):
        t = time.time()
        r = subprocess.run(py + args, env=env, capture_output=True, text=True, encoding='utf8', errors='replace')
        if r.returncode:
            raise RuntimeError('%s: %s' % (os.path.basename(args[0]), (r.stderr or r.stdout)[-1500:]))
        log('   %s: %s (%.0f s)' % (os.path.basename(args[0]), (r.stdout.strip().splitlines() or [''])[-1], time.time() - t))


def normalize(out):
    """Fixes the safe ones among the 'ad?' fields -> (fixed, remaining) lists."""
    proto = json.load(open(os.path.join(out, 'protocol.json'), encoding='utf8'))
    rp = os.path.join(out, 'protocol_read.json')
    read = json.load(open(rp, encoding='utf8'))
    fixed, left = [], []
    for v in read.values():
        names = {f[0] for f in proto.get(v['name'], {}).get('fields', [])}
        for st in v['steps']:
            f = st.get('f') or ''
            if not f.endswith('?'):
                continue
            if f[:-1] in names and st.get('t') in ('string', 'bool') and st.get('x', 'v') == 'v':
                st['f'] = f[:-1]
                fixed.append('%s.%s' % (v['name'].rsplit('.', 1)[-1], f[:-1]))
            else:
                left.append('%s.%s (%s)' % (v['name'].rsplit('.', 1)[-1], f, st.get('t')))
    json.dump(read, open(rp, 'w', encoding='utf8'), ensure_ascii=False, indent=0)
    return fixed, left


def server_names():
    src = ''
    for p in glob.glob(os.path.join(SERVER, '*.py')):
        src += open(p, encoding='utf8').read()
    return set(re.findall(r"['\"]([A-Za-z0-9_]+)['\"]", src))


def compare(old_dir, new_dir):
    """Two protocol folders -> difference dict."""
    po = json.load(open(os.path.join(old_dir, 'protocol.json'), encoding='utf8'))
    pn = json.load(open(os.path.join(new_dir, 'protocol.json'), encoding='utf8'))
    ro = {v['name']: v['steps'] for v in json.load(open(os.path.join(old_dir, 'protocol_read.json'), encoding='utf8')).values()}
    rn = {v['name']: v['steps'] for v in json.load(open(os.path.join(new_dir, 'protocol_read.json'), encoding='utf8')).values()}
    d = {'added': sorted(set(pn) - set(po)), 'deleted': sorted(set(po) - set(pn)), 'uid': [], 'fields': [], 'write': [], 'read': []}
    for k in sorted(set(po) & set(pn)):
        a, b = po[k], pn[k]
        if a.get('id') != b.get('id'):
            d['uid'].append((k, a.get('id'), b.get('id')))
        if a.get('fields') != b.get('fields'):
            fa, fb = [tuple(f[:2]) for f in a.get('fields', [])], [tuple(f[:2]) for f in b.get('fields', [])]
            d['fields'].append((k, [f for f in fb if f not in fa], [f for f in fa if f not in fb],
                                 [f[0] for f in fa] != [f[0] for f in fb if f in fa]))
        if a.get('write') != b.get('write'):
            d['write'].append(k)
        if ro.get(k) != rn.get(k):
            d['read'].append(k)
    return d


def write_report(give, d, fixed, left, used, path):
    short = lambda k: k.rsplit('.', 1)[-1]
    mark = lambda k: ' **(used by the server)**' if short(k) in used else ''
    L = ['# Protocol diff: %s -> %s' % (active_version(), give), '',
         'Generated by `tools/il2cpp/protocol_update.py` (%s). New files in `server/data/protocols/%s/`. Look at the ones marked '
         '"used by the server" first.' % (time.strftime('%Y-%m-%d %H:%M'), give), '',
         '| | Count |', '|---|---|']
    for key, name in (('added', 'Added messages'), ('deleted', 'Deleted messages'), ('uid', 'Changed id'),
                    ('fields', 'Changed fields'), ('write', 'Changed encoding (write)'), ('read', 'Changed read steps')):
        L.append('| %s | %d |' % (name, len(d[key])))
    L.append('| Fixed ambiguous fields | %d |' % len(fixed))
    L.append('| Remaining ambiguous fields | %d |' % len(left))
    L += ['', '## Deleted messages', ''] + ['- `%s`%s' % (short(k), mark(k)) for k in d['deleted']] or ['—']
    L += ['', '## Changed id', ''] + ['- `%s`: %s -> %s%s' % (short(k), a, b, mark(k)) for k, a, b in d['uid']]
    L += ['', '## Changed fields', '']
    for k, add, rem, order in d['fields']:
        L.append('- `%s`%s: added %s; deleted %s%s' % (short(k), mark(k), ', '.join('%s %s' % f for f in add) or '—',
                                                          ', '.join('%s %s' % f for f in rem) or '—', '; order changed' if order else ''))
    L += ['', '## Changed encoding or read steps', '']
    L += ['- `%s`%s%s%s' % (short(k), ' (write)' if k in d['write'] else '', ' (read)' if k in d['read'] else '', mark(k))
          for k in sorted(set(d['write']) | set(d['read']))]
    L += ['', '## Added messages', '', ', '.join('`%s`' % short(k) for k in d['added']) or '—']
    L += ['', '## Ambiguous fields', '', 'Fixed (text/bool, same name in the field list): ' + (', '.join(fixed) or '—'), '',
          'Remaining (by hand with server/protocol.py FIXES; the conversion from the client\'s read() disassembly): ' + (', '.join(left) or '—'), '']
    open(path, 'w', encoding='utf8', newline='\n').write('\n'.join(L))


def apply(give, log=print):
    """Makes the version folder active: the active files are backed up into their own version folder."""
    src = os.path.join(VDIR, give)
    if not all(os.path.exists(os.path.join(src, f)) for f in FILES):
        raise RuntimeError('no protocol files for %s' % give)
    cur = active_version()
    back = os.path.join(VDIR, cur)
    os.makedirs(back, exist_ok=True)
    for f in FILES:
        if not os.path.exists(os.path.join(back, f)):
            shutil.copy2(os.path.join(DATA, f), os.path.join(back, f))
    for f in FILES:
        shutil.copy2(os.path.join(src, f), os.path.join(DATA, f))
    os.makedirs(VDIR, exist_ok=True)
    open(VERSION, 'w', encoding='utf8').write(give + '\n')
    log('   active protocol: %s (previous %s backed up: %s)' % (give, cur, back))


def run(folder, do_apply=False, log=print):
    give = version_of(folder) or os.path.basename(os.path.normpath(folder))
    out = os.path.join(VDIR, give)
    log('client %s -> %s' % (give, out))
    generate(folder, out, log)
    fixed, left = normalize(out)
    d = compare(DATA, out)
    rep = os.path.join(ROOT, 'belgeler', 'istemci', 'protocol_diff_%s.md' % give)
    write_report(give, d, fixed, left, server_names(), rep)
    summary = {k: len(v) for k, v in d.items()}
    summary.update(duzeltilen=len(fixed), ambiguous=len(left), version=give, report=rep)
    log('   diff: %s' % json.dumps({k: v for k, v in summary.items() if k not in ('report', 'version')}, ensure_ascii=False))
    log('   report: %s' % rep)
    if do_apply:
        apply(give, log)
    return summary


def main():
    refund = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith(('--rollback=', '--activate='))), None)
    if refund:
        apply(refund)
        return
    folders = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not folders:
        print(__doc__)
        sys.exit(1)
    run(folders[0], '--apply' in sys.argv)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
