"""Yeni istemci sürümüne protokol uyarlaması (yol haritası "Sürekli işler" > İstemci güncellemesine hazırlık).

Yeni sürümün GameAssembly.dll'inden protokolü yeniden üretir (protocol.py -> protocol.json, read_spec.py -> protocol_read.json;
istemci klasörü OO_CLIENT ile), sürüm klasörüne koyar (server/data/protokol/<sürüm>/), etkin protokolle karşılaştırıp farkları
raporlar (belgeler/istemci/protokol_farki_<sürüm>.md) ve istenirse uygular (etkin dosyalar yedeklenir, yenisi server/data/'ya;
etkin sürüm server/data/protokol/surum.txt'de, panel istemci sürümünü bununla karşılaştırır).

Rapor: eklenen / silinen mesajlar, kimliği değişenler, alanları değişenler (eklenen, silinen, sırası ya da türü değişen), kodlaması
(write) ve okuma adımları (read; bit döndürmeleri) değişenler. Sunucunun kaynağında adı geçen mesajlar "sunucuda kullanılıyor" diye
işaretlenir: önce onlara bakılmalı. read_spec.py'nin adını kesinleştiremediği alanlar ('ad?') alan listesinde aynı ad varsa ve
dönüşüm gerektirmiyorsa (metin, bool) kendiliğinden düzeltilir (1.1.114'te elle yapılanın aynısı); kalanlar raporda.
Doğrulama: 1.1.114 için çalıştırınca etkin protocol.json'la birebir aynı, protocol_read.json'da yalnız elle düzeltilen 3 alan.

Kullanım (proje kökünden):
  python -I tools/il2cpp/protocol_update.py <istemci klasörü>            üret ve raporla (etkin dosyalara dokunmaz)
  python -I tools/il2cpp/protocol_update.py <istemci klasörü> --apply   üret, raporla ve uygula
  python -I tools/il2cpp/protocol_update.py --activate=<sürüm>              sürüm klasöründeki protokolü etkin yap (--rollback= de olur)
"""
import glob, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SERVER = os.path.join(ROOT, 'server')
DATA = os.path.join(SERVER, 'data')
VDIR = os.path.join(DATA, 'protokol')
VERSION = os.path.join(VDIR, 'surum.txt')
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
    """Yeni istemciden iki dosya -> out/. Alt süreç: sembol önbelleği istemci başına (symbols.py)."""
    os.makedirs(out, exist_ok=True)
    env = dict(os.environ, OO_CLIENT=os.path.abspath(folder), PYTHONIOENCODING='utf-8')
    py = [sys.executable, '-I', '-X', 'utf8']
    for args in ([os.path.join(HERE, 'protocol.py'), os.path.join(out, 'protocol.json')],
                 [os.path.join(HERE, 'read_spec.py'), os.path.join(out, 'protocol.json'), os.path.join(out, 'protocol_read.json')]):
        t = time.time()
        r = subprocess.run(py + args, env=env, capture_output=True, text=True, encoding='utf8', errors='replace')
        if r.returncode:
            raise RuntimeError('%s: %s' % (os.path.basename(args[0]), (r.stderr or r.stdout)[-1500:]))
        log('   %s: %s (%.0f sn)' % (os.path.basename(args[0]), (r.stdout.strip().splitlines() or [''])[-1], time.time() - t))


def normalize(out):
    """'ad?' alanlarından güvenli olanları düzeltir -> (düzeltilen, kalan) listeleri."""
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
    """İki protokol klasörü -> fark sözlüğü."""
    po = json.load(open(os.path.join(old_dir, 'protocol.json'), encoding='utf8'))
    pn = json.load(open(os.path.join(new_dir, 'protocol.json'), encoding='utf8'))
    ro = {v['name']: v['steps'] for v in json.load(open(os.path.join(old_dir, 'protocol_read.json'), encoding='utf8')).values()}
    rn = {v['name']: v['steps'] for v in json.load(open(os.path.join(new_dir, 'protocol_read.json'), encoding='utf8')).values()}
    d = {'eklenen': sorted(set(pn) - set(po)), 'silinen': sorted(set(po) - set(pn)), 'kimlik': [], 'alanlar': [], 'yazma': [], 'okuma': []}
    for k in sorted(set(po) & set(pn)):
        a, b = po[k], pn[k]
        if a.get('id') != b.get('id'):
            d['kimlik'].append((k, a.get('id'), b.get('id')))
        if a.get('fields') != b.get('fields'):
            fa, fb = [tuple(f[:2]) for f in a.get('fields', [])], [tuple(f[:2]) for f in b.get('fields', [])]
            d['alanlar'].append((k, [f for f in fb if f not in fa], [f for f in fa if f not in fb],
                                 [f[0] for f in fa] != [f[0] for f in fb if f in fa]))
        if a.get('write') != b.get('write'):
            d['yazma'].append(k)
        if ro.get(k) != rn.get(k):
            d['okuma'].append(k)
    return d


def write_report(give, d, fixed, left, used, path):
    short = lambda k: k.rsplit('.', 1)[-1]
    mark = lambda k: ' **(sunucuda kullanılıyor)**' if short(k) in used else ''
    L = ['# Protokol farkı: %s -> %s' % (active_version(), give), '',
         '`tools/il2cpp/protocol_update.py` ile üretildi (%s). Yeni dosyalar `server/data/protokol/%s/`. Önce "sunucuda '
         'kullanılıyor" işaretlilere bakılmalı.' % (time.strftime('%Y-%m-%d %H:%M'), give), '',
         '| | Sayı |', '|---|---|']
    for key, name in (('eklenen', 'Eklenen mesaj'), ('silinen', 'Silinen mesaj'), ('kimlik', 'Kimliği değişen'),
                    ('alanlar', 'Alanları değişen'), ('yazma', 'Kodlaması (write) değişen'), ('okuma', 'Okuma adımları değişen')):
        L.append('| %s | %d |' % (name, len(d[key])))
    L.append('| Düzeltilen belirsiz alan | %d |' % len(fixed))
    L.append('| Kalan belirsiz alan | %d |' % len(left))
    L += ['', '## Silinen mesajlar', ''] + ['- `%s`%s' % (short(k), mark(k)) for k in d['silinen']] or ['—']
    L += ['', '## Kimliği değişen', ''] + ['- `%s`: %s -> %s%s' % (short(k), a, b, mark(k)) for k, a, b in d['kimlik']]
    L += ['', '## Alanları değişen', '']
    for k, add, rem, order in d['alanlar']:
        L.append('- `%s`%s: eklenen %s; silinen %s%s' % (short(k), mark(k), ', '.join('%s %s' % f for f in add) or '—',
                                                          ', '.join('%s %s' % f for f in rem) or '—', '; sıra değişti' if order else ''))
    L += ['', '## Kodlaması ya da okuma adımları değişen', '']
    L += ['- `%s`%s%s%s' % (short(k), ' (write)' if k in d['yazma'] else '', ' (read)' if k in d['okuma'] else '', mark(k))
          for k in sorted(set(d['yazma']) | set(d['okuma']))]
    L += ['', '## Eklenen mesajlar', '', ', '.join('`%s`' % short(k) for k in d['eklenen']) or '—']
    L += ['', '## Belirsiz alanlar', '', 'Düzeltilen (metin/bool, alan listesinde aynı ad): ' + (', '.join(fixed) or '—'), '',
          'Kalan (server/protocol.py FIXES ile elle; dönüşümü istemcinin read() sökümünden): ' + (', '.join(left) or '—'), '']
    open(path, 'w', encoding='utf8', newline='\n').write('\n'.join(L))


def apply(give, log=print):
    """Sürüm klasörünü etkin yap: etkin dosyalar kendi sürüm klasörüne yedeklenir."""
    src = os.path.join(VDIR, give)
    if not all(os.path.exists(os.path.join(src, f)) for f in FILES):
        raise RuntimeError('%s için protokol dosyaları yok' % give)
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
    log('   etkin protokol: %s (önceki %s yedekte: %s)' % (give, cur, back))


def run(folder, do_apply=False, log=print):
    give = version_of(folder) or os.path.basename(os.path.normpath(folder))
    out = os.path.join(VDIR, give)
    log('istemci %s -> %s' % (give, out))
    generate(folder, out, log)
    fixed, left = normalize(out)
    d = compare(DATA, out)
    rep = os.path.join(ROOT, 'belgeler', 'istemci', 'protokol_farki_%s.md' % give)
    write_report(give, d, fixed, left, server_names(), rep)
    summary = {k: len(v) for k, v in d.items()}
    summary.update(duzeltilen=len(fixed), belirsiz=len(left), surum=give, rapor=rep)
    log('   fark: %s' % json.dumps({k: v for k, v in summary.items() if k not in ('rapor', 'surum')}, ensure_ascii=False))
    log('   rapor: %s' % rep)
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
