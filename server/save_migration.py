"""Save format migration: v1 (Turkish names) -> v2 (English names). Runs once, before anything reads the saves.

What changes (server/migration_map.json, built by the rename tools):
  - JSON keys of field dicts (a dict whose keys are mostly known field names; dicts keyed by player/slot names or item ids are
    left alone), in every JSON under the save dir, the personal login templates and the client folder's OpenOrbit files;
  - world patches: data file names (renamed in phase 1) and JSON Pointer segments;
  - file and directory names (layout: save/kayitlar -> save/slots, profil.json -> profile.json, ...).
Values (enum strings, ids) are not changed here.

Safety:
  - a ZIP backup of the save dir is written first (save/v1_backup_<time>.zip; language-model files and update backups excluded);
  - every rewritten file goes through <file>.tmp + os.replace; moves are os.replace per entry; the version stamp
    (save/format.json) is written last. Converting an already converted file changes nothing, so an interrupted migration
    simply runs again on the next start (the first backup is kept);
  - a lock file keeps two processes (panel, game server, web server) from migrating at the same time.
Old-format data that arrives later (profile import, a v1 backup restored, a world package imported, a guest's profile) goes
through migrate_obj / migrate_world.

Standard library only (imported by paths.py, so by every entry point).
"""
import fnmatch, json, os, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_FILE = os.path.join(HERE, 'migration_map.json')
VERSION = 2
STAMP = 'format.json'
LOCK = '.migration.lock'
STALE_LOCK = 60                                     # the holder touches the lock while it works (_Lock.beat)
SKIP_DIRS = ('wine', 'wine_motoru', 'wine_engine', 'proton', 'DarkOrbitPanel', 'browser', 'tarayici')   # prefixes, browser profile
SKIP_FILES = ('.gguf', '.part', '.tmp', '.zip')
FORCED = ('panel.json', 'ayarlar.json', 'settings.json', 'web_ayarlari.json', 'web_settings.json', 'kayit.json', 'slot.json',
          'guncelleme.json', 'update.json', 'kurulum.json', 'install.json', 'saglayici.json', 'provider.json')   # one config dict each
_MAP = None


def load_map():
    global _MAP
    if _MAP is None:
        with open(MAP_FILE, encoding='utf8') as fh:
            m = json.load(fh)
        m['fields'] = set(m['fields'])
        m['opaque'] = set(m.get('opaque', ()))
        _MAP = m
    return _MAP


# ------------------------------------------------------------------ content
def is_field_dict(d, fields):
    """Most keys are known field names (not player names, slot names or ids)."""
    if not d:
        return False
    known = sum(1 for k in d if k in fields)
    return known * 2 >= len(d)


def migrate_obj(o, m=None, opaque=False, force=False):
    """v1 or v2 JSON value -> v2 (new object; unchanged values are shared). Idempotent.
    opaque: o is the dict under an 'opaque' key (keyed by names or ids, e.g. a bot's memory of players): its own keys stay.
    force: o is a config dict (panel.json, settings ...): its keys are field names however few of them the map knows.
    A dict holding a v1 key and its v2 name (written by both versions, e.g. a friend session across versions) keeps the v2 one."""
    m = m or load_map()
    keys, fields, opq = m['keys'], m['fields'], m['opaque']
    if isinstance(o, dict):
        rename = force or (not opaque and is_field_dict(o, fields))
        if not rename:
            return {k: migrate_obj(v, m, k in opq) for k, v in o.items()}
        return {keys.get(k, k): migrate_obj(v, m, k in opq) for k, v in o.items() if not (k in keys and keys[k] in o)}
    if isinstance(o, list):
        return [migrate_obj(v, m) for v in o]
    return o


BACKUP_KINDS = {'oto_': 'auto_', 'elle_': 'manual_', 'once_': 'before_'}


def backup_name(name):
    """Backup file name of v1 (oto_/elle_/once_<time>.json) -> v2 (auto_/manual_/before_); v2 names unchanged."""
    for old, new in BACKUP_KINDS.items():
        if name.startswith(old):
            return new + name[len(old):]
    return name


def migrate_backup_notes(d):
    """yedek/notlar.json {backup file: note} -> keys follow the renamed backup files."""
    return {backup_name(k): v for k, v in d.items()} if isinstance(d, dict) else d


def migrate_pointer(p, m=None):
    """JSON Pointer into a data file ('/cevherler/3/fiyat') -> v2 segments."""
    m = m or load_map()
    if not isinstance(p, str) or not p.startswith('/'):
        return p
    return '/'.join(m['keys'].get(s, s) for s in p.split('/'))


def migrate_world(d, m=None):
    """World or world package: keys, then patches {data file: {pointer: value | {"$sil": true}}}."""
    m = m or load_map()
    d = migrate_obj(d, m)
    for pk in ('yamalar', m['keys'].get('yamalar', 'yamalar')):
        patches = d.get(pk) if isinstance(d, dict) else None
        if isinstance(patches, dict):
            d[pk] = {m['data_files'].get(f, f): ({migrate_pointer(p, m): v for p, v in (fp or {}).items()} if isinstance(fp, dict) else fp)
                     for f, fp in patches.items()}
    return d


def _read(p):
    with open(p, encoding='utf8') as fh:
        return json.load(fh)


def _write(p, d):
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def migrate_file(p, world=False, m=None):
    """Rewrite one JSON file in place if anything changes -> changed. An unreadable file (locked by an antivirus ...) raises:
    the migration fails and runs again on the next start instead of stamping a half-migrated save."""
    try:
        d = _read(p)
    except FileNotFoundError:
        return False
    except ValueError:
        return False                                   # not JSON: left as it is
    name = os.path.basename(p)
    if world:
        new = migrate_world(d, m)
    elif name in ('ayar_sablonlari.json', 'settings_templates.json') and isinstance(d, dict):
        new = {k: migrate_obj(v, m, force=True) for k, v in d.items()}         # {template name: settings}
    else:
        new = migrate_obj(d, m, force=name in FORCED)
    if new == d and json.dumps(new) == json.dumps(d):
        return False
    _write(p, new)
    return True


# ------------------------------------------------------------------ layout
def _expand(root, pattern):
    """'kayitlar/*/yedek/oto_*' -> existing paths (one level per *)."""
    parts = pattern.split('/')
    cur = [root]
    for part in parts:
        nxt = []
        for c in cur:
            if any(ch in part for ch in '*?['):
                if os.path.isdir(c):
                    nxt += [os.path.join(c, n) for n in sorted(os.listdir(c)) if fnmatch.fnmatch(n, part)]
            elif os.path.exists(os.path.join(c, part)):
                nxt.append(os.path.join(c, part))
        cur = nxt
    return cur


def _target(src, root, old, new):
    """Path matched by the old pattern -> the same path under the new pattern (wildcards keep their matched text)."""
    rel = os.path.relpath(src, root).replace('\\', '/').split('/')
    op, np_ = old.split('/'), new.split('/')
    out = []
    for i, seg in enumerate(rel):
        if i < len(op) and any(ch in op[i] for ch in '*?['):
            pre_o, pre_n = op[i].split('*', 1)[0], np_[i].split('*', 1)[0]
            out.append(pre_n + seg[len(pre_o):] if seg.startswith(pre_o) else seg)
        elif i < len(np_):
            out.append(np_[i])
        else:
            out.append(seg)
    return os.path.join(root, *out)


def _move(src, dst, keep=True):
    """os.replace; if the destination directory exists already (an interrupted run, or v1 data copied in later), merge into it.
    A file whose new name exists already: the new one stays; the old one is kept next to it as <new>.v1 (keep) or dropped
    (the client folder's regenerated files)."""
    if not os.path.lexists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        return
    if os.path.isdir(src) and os.path.isdir(dst):
        for n in os.listdir(src):
            _move(os.path.join(src, n), os.path.join(dst, n), keep)
        os.rmdir(src)
    elif keep:
        side, i = dst + '.v1', 1
        while os.path.lexists(side):
            i += 1
            side = '%s.v1_%d' % (dst, i)
        os.replace(src, side)
    elif os.path.isfile(src):
        os.remove(src)


def apply_layout(root, rules, keep=True, beat=lambda: None):
    for old, new in rules:
        for src in _expand(root, old):
            dst = _target(src, root, old, new)
            if dst != src and os.path.lexists(src):
                _move(src, dst, keep)
                beat()


# ------------------------------------------------------------------ whole save dir
V1_MARKERS = ('kayitlar', 'profil.json', 'ayarlar.json', 'klanlar.json', 'botlar', 'dunyalar', 'silinenler', 'guncelleme.json',
              'guncelleme', 'ayar_sablonlari.json', 'yedek', 'wine_motoru', 'llm/kurulum.json', 'llm/saglayici.json')


def _has_v1(save_dir):
    """Old names in the save dir (also after the stamp: an old save copied into a migrated install)."""
    return any(os.path.lexists(os.path.join(save_dir, *n.split('/'))) for n in V1_MARKERS)


def stamp_version(save_dir):
    try:
        return int(_read(os.path.join(save_dir, STAMP)).get('version', 1))
    except (OSError, ValueError, AttributeError, TypeError):
        return 1


def needs_migration(save_dir):
    return stamp_version(save_dir) < VERSION or _has_v1(save_dir)


class _Lock:
    """Lock file; the holder touches it while working (beat), so a lock left by a crash is taken over after STALE_LOCK."""

    def __init__(self, root):
        self.p, self.t = os.path.join(root, LOCK), 0
        for _ in range(int((STALE_LOCK + 30) / 0.2)):      # another process migrates: wait for it (or for its lock to go stale)
            try:
                fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, ('%d %d' % (os.getpid(), time.time())).encode())
                os.close(fd)
                self.t = time.time()
                return
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.p) > STALE_LOCK:
                        os.remove(self.p)
                        continue
                except OSError:
                    pass
                time.sleep(0.2)
        raise RuntimeError('save migration: lock busy (%s)' % self.p)

    def beat(self):
        if time.time() - self.t > 5:
            self.t = time.time()
            try:
                os.utime(self.p)
            except OSError:
                pass

    def release(self):
        try:
            os.remove(self.p)
        except OSError:
            pass


def _walk(root):
    """os.walk without Wine prefixes, the browser profile, language-model servers and update backups."""
    for r, ds, fs in os.walk(root):
        rel = os.path.relpath(r, root).replace('\\', '/')
        ds[:] = [x for x in ds if not (rel == '.' and x in SKIP_DIRS) and not x.startswith('llama-')
                 and not (rel in ('guncelleme', 'update') and x.startswith(('yedek_', 'backup_')))]
        yield r, rel, fs


def _backup(root, log, files=None, beat=lambda: None, again=False):
    """ZIP of the v1 files (the whole save dir, or the given files of the data dir) -> its name; None if one exists already
    (an interrupted run made it before anything changed: that one is kept) unless again (v1 data that arrived after the stamp).
    Regular files only (a dangling symlink, e.g. a browser lock, would stop zipfile); a file that cannot be read is logged."""
    for n in os.listdir(root):
        if n.startswith('v1_backup_') and n.endswith('.zip.tmp'):
            try:
                os.remove(os.path.join(root, n))           # left by a crash
            except OSError:
                pass
    if not again and any(n.startswith('v1_backup_') and n.endswith('.zip') for n in os.listdir(root)):
        return None
    name = 'v1_backup_%s.zip' % time.strftime('%Y%m%d-%H%M%S')
    tmp = os.path.join(root, name + '.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        if files is not None:
            for f in files:
                z.write(os.path.join(root, f), f)
        else:
            for r, rel, fs in _walk(root):
                for f in fs:
                    p = os.path.join(r, f)
                    if f.endswith(SKIP_FILES) or f in (LOCK, STAMP) or os.path.islink(p) or not os.path.isfile(p):
                        continue
                    try:
                        z.write(p, os.path.relpath(p, root))
                    except OSError as e:
                        log('yedeğe alınamadı: %s (%s)' % (p, e))
                    beat()
    os.replace(tmp, os.path.join(root, name))
    log('kayıtların yedeği: %s' % os.path.join(root, name))
    return name


V1_TEMPLATES = ('giris.json', 'haritalar.json', 'yanitlar.json')


def _data_pending(data_dir):
    return any(os.path.exists(os.path.join(data_dir, f)) for f in V1_TEMPLATES + ('protokol',))


def migrate_data(data_dir, log=lambda *a: None):
    """Personal login templates (data/giris.json ... -> login.json ...) and the protocol folder. No stamp: the old names are
    the sign. Its own lock and backup (every process of every save dir shares the data dir)."""
    if not os.path.isdir(data_dir) or not _data_pending(data_dir):
        return False
    lock = _Lock(data_dir)
    try:
        if not _data_pending(data_dir):
            return False
        m = load_map()
        present = [f for f in V1_TEMPLATES if os.path.isfile(os.path.join(data_dir, f))]
        if present:
            _backup(data_dir, log, present)
        for f in present:
            migrate_file(os.path.join(data_dir, f), m=m)
        apply_layout(data_dir, m['layout']['data'], beat=lock.beat)
        log('giriş şablonları yeni biçime taşındı')
        return True
    finally:
        lock.release()


def ensure(save_dir, data_dir, log=lambda *a: None):
    """Migrate the save dir (and the personal templates in data_dir) to v2 if needed. Safe to call from every process."""
    migrate_data(data_dir, log)
    if not needs_migration(save_dir) or not os.path.isdir(save_dir):
        return False                                   # done, or nothing saved yet (the first write creates the v2 layout)
    lock = _Lock(save_dir)
    try:
        if not needs_migration(save_dir):              # another process finished while we waited
            return False
        m = load_map()
        late = stamp_version(save_dir) >= VERSION      # v1 data copied in after the migration
        backup = None
        if any(n not in (STAMP, LOCK) and not n.startswith('v1_backup_') for n in os.listdir(save_dir)):
            backup = _backup(save_dir, log, beat=lock.beat, again=late)
        n = 0
        for r, rel, fs in _walk(save_dir):             # every run converts everything: an interrupted one finishes
            for f in fs:
                p = os.path.join(r, f)
                if f in ('notlar.json', 'notes.json') and rel.split('/')[-1] in ('yedek', 'backups'):
                    try:
                        d = _read(p)
                    except (FileNotFoundError, ValueError):
                        continue
                    if migrate_backup_notes(d) != d:
                        _write(p, migrate_backup_notes(d))
                        n += 1
                elif f.endswith('.json') and f != STAMP:
                    n += migrate_file(p, world=rel.split('/')[0] in ('dunyalar', 'worlds'), m=m)
                lock.beat()
        for p in _expand(save_dir, 'wine_motoru/*/kurulum.json') + _expand(save_dir, 'wine_engine/*/install.json'):
            n += migrate_file(p, m=m)                  # the engine's install record (the rest of the folder is skipped)
        apply_layout(save_dir, m['layout']['save'], beat=lock.beat)
        log('kayıtlar yeni biçime taşındı (%d dosya)' % n)
        if not late:
            _write(os.path.join(save_dir, STAMP), {'version': VERSION, 'migrated': time.strftime('%Y-%m-%d %H:%M:%S'), 'backup': backup})
        return True
    finally:
        lock.release()


def migrate_client(client_dir, log=lambda *a: None):
    """Game client folder: OpenOrbit's own files (BepInEx/openorbit.json, BepInEx/openorbit/*). Idempotent."""
    if not client_dir or not os.path.isdir(os.path.join(client_dir, 'BepInEx')):
        return False
    m = load_map()
    changed = migrate_file(os.path.join(client_dir, 'BepInEx', 'openorbit.json'), m=m)
    old_index = os.path.join(client_dir, 'BepInEx', 'openorbit', 'gorsel', 'dizin.json')     # the image dump's index (other dump files: names)
    if os.path.isfile(old_index):
        changed |= migrate_file(old_index, m=m)
    apply_layout(client_dir, m['layout']['client'], keep=False)
    if changed:
        log('istemci klasöründeki OpenOrbit dosyaları yeni biçime taşındı')
    return changed
