"""Save slots (admin panel): list and summary, new save, active slot, name and note, copy, delete (to the trash, recoverable),
export/import, editing and backups.

Layout (paths.py): save/slots/<id>/{profile.json, slot.json, web_settings.json, edit_base.json, backups/}. A deleted slot is moved to
save/trash/<id>_<time>/. Backups are backups/<type>_YYYYmmdd_HHMMSS.json:
  auto    taken by the panel on PLAY and while the game runs; the newest `backup_count` are kept
  manual  taken by the player; not deleted automatically
  before  the safety backup taken before restoring / editing; the newest BEFORE_COUNT are kept
Notes are in backups/notes.json. The profile must not change while the game server is open (the autosave overwrites it): the panel blocks
modifying operations while the slot is in use (in_use).
A new profile is built in a separate process (profile_tool.py: seed, pilot name, company, home station).
The character editor (save_editor.py, a separate process) works on the edit_base.json draft: the draft is opened at the first change, Save
takes a safety backup and writes to the profile, Cancel discards the draft. If the profile changed after the draft was opened (the game was
played, a backup was restored) the old draft is discarded.
"""
import json, os, re, shutil, subprocess, sys, threading, time, zipfile

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(PANEL_DIR)
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)
import paths as PTH  # noqa: E402
import save_migration as SM  # noqa: E402
from lang import t as _  # noqa: E402

COMPANIES = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
BEFORE_COUNT = 5
KINDS = ('auto', 'manual', 'before')
KIND_NAMES = {'auto': 'Automatic', 'manual': 'Manual', 'before': 'Before restore'}
TIE_ORDER = {'manual': 0, 'before': 1, 'auto': 2}
_TR = str.maketrans('çğıöşüÇĞİÖŞÜâîû', 'cgiosuCGIOSUaiu')


def default_key_bindings():
    """The game's default key bindings: the seed of the login template (player_profile.py uses it for a new profile too)."""
    p = PTH.template('login.json')                 # your own save, otherwise the shareable copy
    t = (_read_json(p).get('seed') if p else None) or {}
    return list((t.get('UserKeyBindingsUpdate') or {}).get('changedKeyBindings', []))


class SaveError(Exception):
    """Error shown to the user (message in the panel's language; lang.py)."""


def slugify(name):
    s = re.sub(r'[^a-z0-9]+', '_', name.translate(_TR).lower()).strip('_')
    return (s or 'record')[:32]


def ship_name(type_id):
    s = (type_id or '').replace('ship_', '', 1)
    return ' '.join('-'.join(p.capitalize() for p in w.split('-')) for w in s.split('_')) or '?'


def _read_json(path):
    with open(path, encoding='utf8') as fh:
        return json.load(fh)


def _write_json(path, d, indent=1):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def _copy_atomic(src, dst):
    tmp = dst + '.tmp'
    shutil.copy2(src, tmp)
    for k in range(6):                         # the game server's os.replace and virus scanners can lock it momentarily
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if k == 5:
                raise
            time.sleep(0.1 * (k + 1))


V1_SLOT_FILES = {'profil.json': 'profile.json', 'web_ayarlari.json': 'web_settings.json', 'kayit.json': 'slot.json',
                 'yedek/notlar.json': 'backups/notes.json'}
def _v2_slot_path(rel):
    """The path in a zip exported by an old version (profil.json, yedek/oto_...) -> the new path in the slot; new paths as they are."""
    rel = V1_SLOT_FILES.get(rel, rel)
    if rel.startswith('yedek/'):
        rel = 'backups/' + SM.backup_name(rel[len('yedek/'):])
    return rel


def validate_profile(d):
    """Is it a profile dictionary? (import, restore)"""
    if not (isinstance(d, dict) and isinstance(d.get('pilot'), dict) and isinstance(d.get('ship'), dict)
            and isinstance(d.get('position'), dict) and 'mapId' in d['position']):
        raise SaveError(_('This file is not a DarkOrbit profile (no pilot, ship and position sections).'))
    return d


_LEVELS = None


def level_for(ep):
    global _LEVELS
    if _LEVELS is None:
        try:
            _LEVELS = _read_json(os.path.join(SERVER, 'data', 'levels.json'))['levels']
        except (OSError, ValueError, KeyError):
            _LEVELS = [[1, 0]]
    lv = 1
    for level, need in _LEVELS:
        if ep >= need:
            lv = level
    return lv


def _map_name(mid):
    try:
        import map_links as H
        return H.name(mid)
    except Exception:
        return str(mid)


def level_bounds(level):
    """The EP threshold of the level and the next one (progress bar; None for next at the last level)."""
    level_for(0)
    need = dict((lv, ep) for lv, ep in _LEVELS)
    return need.get(level, 0), need.get(level + 1)


def profile_summary(d):
    """The summary the panel shows from the profile."""
    pl, g, k = d.get('pilot') or {}, d.get('ship') or {}, d.get('position') or {}
    base, next_ = level_bounds(pl.get('level', 1))
    return {'ship_appearance': g.get('typeId'), 'level_base': base, 'next_level': next_, 'drone_count': len(d.get('drones') or []),
            'pet': (d.get('pet') or {}).get('name'), 'premium': bool(pl.get('premium')),'pilot': pl.get('userName') or '?', 'company': COMPANIES.get(pl.get('factionId'), '?'), 'firma_id': pl.get('factionId'),
            'level': pl.get('level', 1), 'ep': pl.get('ep', 0), 'honor': pl.get('honourPoints', 0), 'credits': pl.get('credits', 0),
            'uridium': pl.get('uridium', 0), 'ship': ship_name(g.get('typeId')), 'map': _map_name(k.get('mapId', 0)),
            'play_sec': int(d.get('play_sec') or 0), 'created': d.get('created'),
            'hp': g.get('hitPoints'), 'max_hp': g.get('hitMax'),
            'clan': pl.get('clanTag') or '', 'ship_count': len(d.get('ships') or {}) or 1}


class Saves:
    def __init__(self, cfg, root=PTH.SAVES, trash=PTH.TRASH, legacy=PTH.LEGACY_PROFILE, python=None):
        self.cfg, self.root, self.trash, self.legacy = cfg, root, trash, legacy
        self.python = python or sys.executable
        self.lock = threading.RLock()
        self.in_use = lambda slot: False           # the panel binds: is an open game server using the slot
        self._cache = {}                           # path -> (mtime, size, summary)

    # ------------------------------------------------------------ paths
    def dir(self, slot):
        if not slot or not re.fullmatch(r'[a-z0-9_]{1,40}', slot):
            raise SaveError(_('Invalid save id.'))
        return os.path.join(self.root, slot)

    def profile(self, slot):
        return os.path.join(self.dir(slot), 'profile.json')

    def settings(self, slot):
        """The save's game settings (settings.py; per-save: the settings change when the active save changes). If missing, copied from the old shared
        file (save/settings.json), and if that is missing too, empty (defaults)."""
        p = os.path.join(self.dir(slot), 'settings.json')
        if not os.path.isfile(p) and os.path.isdir(self.dir(slot)):
            with self.lock:
                if not os.path.isfile(p):
                    shutil.copyfile(PTH.SETTINGS, p) if os.path.isfile(PTH.SETTINGS) else _write_json(p, {})
        return p

    def copy_settings(self, src, dst):
        """The game settings of save src (including event selections) to save dst."""
        if not self.exists(src) or not self.exists(dst):
            raise SaveError(_('Save not found.'))
        if src != dst:
            shutil.copyfile(self.settings(src), os.path.join(self.dir(dst), 'settings.json'))

    def backup_dir(self, slot):
        return os.path.join(self.dir(slot), 'backups')

    def exists(self, slot):
        try:
            return os.path.isfile(self.profile(slot))
        except SaveError:
            return False

    def slots(self):
        if not os.path.isdir(self.root):
            return []
        return sorted(s for s in os.listdir(self.root) if re.fullmatch(r'[a-z0-9_]{1,40}', s) and self.exists(s))

    def meta(self, slot):
        try:
            d = _read_json(os.path.join(self.dir(slot), 'slot.json'))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_meta(self, slot, **kw):
        with self.lock:
            m = self.meta(slot)
            m.update(kw)
            _write_json(os.path.join(self.dir(slot), 'slot.json'), m)
            return m

    def new_id(self, name):
        base = slugify(name)
        sid, k = base, 2
        while os.path.exists(os.path.join(self.root, sid)):
            sid = '%s_%d' % (base[:28], k)
            k += 1
        return sid

    def guard(self, slot, what='do this'):
        if self.in_use(slot):
            raise SaveError(_('To %s, close the game and the server first: the save is in use (the server saves it every 10 seconds).',
                                _(what)))

    # ------------------------------------------------------------ active slot
    def active(self):
        s = self.cfg.get('active_save')
        if s and self.exists(s):
            return s
        slots = self.slots()
        return slots[0] if slots else None

    def set_active(self, slot):
        if not self.exists(slot):
            raise SaveError(_('Save not found.'))
        self.cfg.update({'active_save': slot})
        return slot

    # ------------------------------------------------------------ moving from the old layout
    def migrate(self):
        """save/profil.json (the old single save) -> the 'ana' slot; web settings and old backups (profil_*.json -> oto_*.json) together.
        -> the id of the moved slot or None."""
        with self.lock:
            if not os.path.isfile(self.legacy):
                return None
            save = os.path.dirname(self.legacy)
            sid = self.new_id('main')
            d = os.path.join(self.root, sid)
            os.makedirs(os.path.join(d, 'backups'), exist_ok=True)
            pr = profile_summary(_read_json(self.legacy))
            shutil.copy2(self.legacy, os.path.join(d, 'backups', 'before_%s.json' % time.strftime('%Y%m%d_%H%M%S')))    # safety copy
            web = os.path.join(save, 'web_settings.json')
            if os.path.isfile(web):
                shutil.move(web, os.path.join(d, 'web_settings.json'))
            old_bk = os.path.join(save, 'backups')
            if os.path.isdir(old_bk):
                for f in sorted(os.listdir(old_bk)):
                    m = re.fullmatch(r'profile_(\d{8}_\d{6})\.json', f)
                    if m:
                        shutil.move(os.path.join(old_bk, f), os.path.join(d, 'backups', 'auto_%s.json' % m.group(1)))
                try:
                    os.rmdir(old_bk)
                except OSError:
                    pass
            _write_json(os.path.join(d, 'slot.json'), {'name': _('Main save (%s)', pr['pilot']), 'created': pr['created'] or
                                                        time.strftime('%Y-%m-%d %H:%M:%S'), 'not': 'Eski save/profil.json'})
            shutil.move(self.legacy, os.path.join(d, 'profile.json'))
            if not self.cfg.get('active_save') or not self.exists(self.cfg.get('active_save')):
                self.cfg.update({'active_save': sid})
            return sid

    # ------------------------------------------------------------ summaries
    def summary(self, slot):
        p = self.profile(slot)
        st = os.stat(p)
        c = self._cache.get(p)
        if not c or c[0] != st.st_mtime_ns:
            try:
                s = profile_summary(_read_json(p))
                s['corrupt'] = False
            except (OSError, ValueError):
                s = {'pilot': '?', 'corrupt': True}
            self._cache[p] = c = (st.st_mtime_ns, s)
        m = self.meta(slot)
        out = dict(c[1])
        out.update(id=slot, name=m.get('name') or slot, not_=m.get('not', ''), save_created=m.get('created'),
                   last_played=m.get('last_played'), last_save=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime)),
                   size=st.st_size, backup_count=len(self.backup_files(slot)), active=(slot == self.active()),
                   in_use=self.in_use(slot), world=m.get('world') or 'standard', draft=self._draft_valid(slot))
        return out

    def list(self):
        out = []
        for s in self.slots():
            try:
                out.append(self.summary(s))
            except OSError:
                continue
        out.sort(key=lambda x: (not x['active'], -(time.mktime(time.strptime(x['last_played'], '%Y-%m-%d %H:%M:%S'))
                                                    if x.get('last_played') else 0), x['name'].lower()))
        return out

    # ------------------------------------------------------------ new, name, copy, delete
    def run_tool(self, *args, tool='profile_tool.py'):
        """Run profile_tool.py (or save_editor.py) in a separate process -> the output's JSON."""
        kw = {'creationflags': 0x08000000} if os.name == 'nt' else {}         # CREATE_NO_WINDOW
        r = subprocess.run([self.python, '-I', os.path.join(PANEL_DIR, tool)] + list(args), capture_output=True,
                           text=True, encoding='utf8', timeout=120, **kw)
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise SaveError(_("The profile tool didn't run: %s", (r.stderr or r.stdout).strip()[-400:] or _('no output')))
        if not out.get('ok'):
            if out.get('template'):
                raise SaveError(_(out['template'], *out.get('arg') or ()))
            raise SaveError(out.get('error') or _('The profile tool failed.'))
        return out

    def create(self, label, pilot, company, credits=None, uridium=None, level=None, honor=None, laser=None, rocket=None, progressive=False,
               settings_source=None, campaign=False):
        """New save (profile_tool.py new). Starting values are optional (empty: the seed's): credits, uridium, level (1-50), honor, LCB-10 laser ammo
        and R-310 rocket counts; clamped to the limits. progressive: Season Pass in order from the first season. campaign: starting
        campaign ("Level N" quests, for quest.CAMPAIGN_SEC)."""
        label, pilot = (label or '').strip(), (pilot or '').strip()
        if not re.fullmatch(r'[\w\-\.\[\]\(\) ]{3,20}', pilot, re.UNICODE):
            raise SaveError(_('The pilot name must be 3-20 characters (letters, digits, spaces, - _ . [ ] ( ) ).'))
        if not label:
            raise SaveError(_('Give the save a name.'))
        company = int(company)
        if company not in COMPANIES:
            raise SaveError(_('Choose a company (MMO, EIC or VRU).'))
        try:
            credits, uridium, level, honor, laser, rocket = [None if v in (None, '') else int(float(v))
                                                          for v in (credits, uridium, level, honor, laser, rocket)]
        except (TypeError, ValueError, OverflowError):
            raise SaveError(_('Starting values must be numbers.'))
        with self.lock:
            sid = self.new_id(label)
            d = os.path.join(self.root, sid)
            os.makedirs(os.path.join(d, 'backups'), exist_ok=True)
            args = ['new', os.path.join(d, 'profile.json'), pilot, str(company)]
            for key, v, lo, hi in (('credits', credits, 0, 10 ** 12), ('uridium', uridium, 0, 10 ** 12), ('level', level, 1, 50),
                                   ('honor', honor, 0, 10 ** 12), ('laser', laser, 0, 10 ** 9), ('rocket', rocket, 0, 10 ** 9)):
                if v not in (None, ''):
                    args += ['--%s=%d' % (key, min(hi, max(lo, v)))]
            if progressive:
                args += ['--progressive=1']
            if campaign:
                args += ['--campaign=1']
            try:
                self.run_tool(*args)
            except Exception:
                shutil.rmtree(d, ignore_errors=True)
                raise
            _write_json(os.path.join(d, 'slot.json'), {'name': label, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'not': ''})
            if settings_source and self.exists(settings_source):        # settings from another save (otherwise from the old shared file)
                self.copy_settings(settings_source, sid)
            return sid

    def rename(self, slot, label):
        label = (label or '').strip()
        if not label:
            raise SaveError(_('The name cannot be empty.'))
        self.dir(slot)
        return self.set_meta(slot, name=label[:60])

    def set_note(self, slot, text):
        return self.set_meta(slot, **{'not': (text or '')[:500]})

    def duplicate(self, slot, label=None):
        src = self.dir(slot)
        with self.lock:
            label = (label or '').strip() or _('%s (copy)', self.meta(slot).get('name') or slot)
            sid = self.new_id(label)
            dst = os.path.join(self.root, sid)
            os.makedirs(os.path.join(dst, 'backups'), exist_ok=True)
            _copy_atomic(os.path.join(src, 'profile.json'), os.path.join(dst, 'profile.json'))
            if os.path.isfile(os.path.join(src, 'web_settings.json')):
                shutil.copy2(os.path.join(src, 'web_settings.json'), os.path.join(dst, 'web_settings.json'))
            meta = {'name': label, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'not': _('Copied from: %s', self.meta(slot).get('name') or slot)}
            if self.meta(slot).get('world'):              # the default world (World Editor) passes to the copy
                meta['world'] = self.meta(slot)['world']
            _write_json(os.path.join(dst, 'slot.json'), meta)
            return sid

    def delete(self, slot):
        """Move to the trash (recoverable)."""
        self.guard(slot, 'delete it')
        with self.lock:
            src = self.dir(slot)
            os.makedirs(self.trash, exist_ok=True)
            dst = os.path.join(self.trash, '%s_%s' % (slot, time.strftime('%Y%m%d_%H%M%S')))
            shutil.move(src, dst)
            if self.cfg.get('active_save') == slot:
                rest = self.slots()
                self.cfg.update({'active_save': rest[0] if rest else None})
            return os.path.basename(dst)

    def deleted(self):
        if not os.path.isdir(self.trash):
            return []
        out = []
        for name in sorted(os.listdir(self.trash), reverse=True):
            d = os.path.join(self.trash, name)
            m = re.fullmatch(r'([a-z0-9_]+)_(\d{8})_(\d{6})', name)
            if not (m and os.path.isfile(os.path.join(d, 'profile.json'))):
                continue
            try:
                meta = _read_json(os.path.join(d, 'slot.json'))
            except (OSError, ValueError):
                meta = {}
            try:
                pr = profile_summary(_read_json(os.path.join(d, 'profile.json')))
            except (OSError, ValueError):
                pr = {'pilot': '?'}
            t = time.strptime(m.group(2) + m.group(3), '%Y%m%d%H%M%S')
            out.append({'file': name, 'name': meta.get('name') or m.group(1), 'pilot': pr.get('pilot'), 'level': pr.get('level'),
                        'deletion': time.strftime('%Y-%m-%d %H:%M:%S', t)})
        return out

    def _trash_dir(self, name):
        if not re.fullmatch(r'[a-z0-9_]+_\d{8}_\d{6}', name or ''):
            raise SaveError(_('Invalid trash entry.'))
        d = os.path.join(self.trash, name)
        if not os.path.isdir(d):
            raise SaveError(_('Deleted save not found.'))
        return d

    def undelete(self, name):
        with self.lock:
            src = self._trash_dir(name)
            sid = self.new_id(re.sub(r'_\d{8}_\d{6}$', '', name))
            shutil.move(src, os.path.join(self.root, sid))
            return sid

    def purge(self, name=None):
        """Permanently delete from the trash (all if name is not given) -> number deleted."""
        with self.lock:
            names = [name] if name else [x['file'] for x in self.deleted()]
            for n in names:
                shutil.rmtree(self._trash_dir(n))
            return len(names)

    # ------------------------------------------------------------ export / import
    def export(self, slot, dest, with_backups=True):
        """Export the slot as a zip (profile, save info, web settings, optionally backups)."""
        src = self.dir(slot)
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                if rel.split(os.sep)[0] == 'backups' and not with_backups:
                    continue
                for f in files:
                    if f.endswith('.tmp') or (rel == '.' and f == 'edit_base.json'):     # the editor's unsaved draft
                        continue
                    z.write(os.path.join(root, f), os.path.join(slot, rel, f) if rel != '.' else os.path.join(slot, f))
        return dest

    def import_file(self, path, label=None):
        """.zip (exported by the panel) or .json (profile) -> the id of the new slot."""
        if not os.path.isfile(path):
            raise SaveError(_('File not found.'))
        with self.lock:
            if path.lower().endswith('.zip'):
                with zipfile.ZipFile(path) as z:
                    names = [n for n in z.namelist() if not n.endswith('/')]
                    prof = [n for n in names if n.replace('\\', '/').split('/')[-1] in ('profile.json', 'profil.json')   # v1 zip: profil.json
                            and n.replace('\\', '/').count('/') <= 1]
                    if not prof:
                        raise SaveError(_('The zip has no profil.json.'))
                    base = prof[0].replace('\\', '/').rsplit('/', 1)[0] + '/' if '/' in prof[0].replace('\\', '/') else ''
                    d = validate_profile(SM.migrate_obj(json.loads(z.read(prof[0]).decode('utf8'))))
                    meta = {}
                    for mn in ('slot.json', 'kayit.json'):
                        if base + mn in names:
                            try:
                                meta = SM.migrate_obj(json.loads(z.read(base + mn).decode('utf8')))
                            except ValueError:
                                meta = {}
                            break
                    label = (label or meta.get('name') or profile_summary(d)['pilot']).strip()
                    sid = self.new_id(label)
                    dst = os.path.join(self.root, sid)
                    os.makedirs(os.path.join(dst, 'backups'), exist_ok=True)
                    for n in names:
                        nn = n.replace('\\', '/')
                        if not nn.startswith(base):
                            continue
                        rel = _v2_slot_path(nn[len(base):])
                        ok = rel in ('profile.json', 'web_settings.json') or re.fullmatch(r'backups/(auto|manual|before)_\d{8}_\d{6}(_\d+)?\.json',
                                                                                        rel) or rel == 'backups/notes.json'
                        if ok:
                            try:
                                d_ = json.loads(z.read(n).decode('utf8'))
                                _write_json(os.path.join(dst, *rel.split('/')), SM.migrate_backup_notes(d_) if rel == 'backups/notes.json'
                                            else SM.migrate_obj(d_))
                            except ValueError:
                                pass                         # corrupt backup: skipped
            else:
                try:
                    d = validate_profile(SM.migrate_obj(_read_json(path)))
                except ValueError:
                    raise SaveError(_('The file could not be read (not valid JSON).'))
                label = (label or _('%s (imported)', profile_summary(d)['pilot'])).strip()
                sid = self.new_id(label)
                dst = os.path.join(self.root, sid)
                os.makedirs(os.path.join(dst, 'backups'), exist_ok=True)
                _write_json(os.path.join(dst, 'profile.json'), SM.migrate_obj(d))
            _write_json(os.path.join(dst, 'slot.json'), {'name': label[:60], 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                                                          'not': _('Imported: %s', os.path.basename(path))})
            return sid

    # ------------------------------------------------------------ editing
    def edit(self, slot, values):
        """Pilot name, credits, uridium, honor, EP (level from EP), repair the ship, move to the home base, reset key bindings to default;
        give items/ships (give: [[lootId, amount]]), reset state (reset: sections; profile_tool.py). A 'before' backup is taken first."""
        self.guard(slot, 'edit it')
        with self.lock:
            p = self.profile(slot)
            d = validate_profile(_read_json(p))
            pl, g = d['pilot'], d['ship']
            changed = []
            if 'pilot' in values:
                name = str(values['pilot']).strip()
                if not re.fullmatch(r'[\w\-\.\[\]\(\) ]{3,20}', name, re.UNICODE):
                    raise SaveError(_('The pilot name must be 3-20 characters.'))
                if name != pl.get('userName'):
                    pl['userName'] = name
                    changed.append(_('pilot name'))
            for key, field, lo, hi, label in (('credits', 'credits', 0, 10 ** 12, 'credits'), ('uridium', 'uridium', 0, 10 ** 12, 'uridium'),
                                              ('honor', 'honourPoints', -10 ** 12, 10 ** 12, 'honor'), ('ep', 'ep', 0, 2 ** 62, 'EP')):
                if key in values and values[key] not in (None, ''):
                    v = min(hi, max(lo, int(values[key])))
                    if v != pl.get(field):
                        pl[field] = v
                        changed.append(_(label))
                        if key == 'ep':
                            pl['level'] = level_for(v)
            if values.get('keybinds'):
                # the game's Settings > Reset does not reach the server (the client cannot send ResetSettingsRequest without closing the connection;
                # CANLI_TEST N12): the keys return to the seed's (the default layout in the save), and go to the client at the next login
                d['key_bindings'] = default_key_bindings()
                changed.append(_('key bindings reset'))
            if values.get('repair'):
                g['hitPoints'], g['shield'] = g.get('hitMax', g.get('hitPoints', 1)), g.get('shieldMax', g.get('shield', 0))
                changed.append(_('ship repaired'))
            give = [[str(l), int(n or 1)] for l, n in (values.get('give') or []) if str(l).strip()]
            resets = [r for r in (values.get('reset') or []) if r]
            if not changed and not values.get('home_base') and not give and not resets:
                return []
            safety = self.backup(slot, 'before', _('Before editing'))
            try:
                if changed:
                    _write_json(p, d)
                if values.get('home_base'):
                    self.run_tool('home_base', p)
                    changed.append(_('moved to the home base'))
                if give:
                    r = self.run_tool('give', p, json.dumps(give))
                    changed.append(_('given: %s', ', '.join('%s x%d' % (l, n) for l, n in r['given'])))
                if resets:
                    r = self.run_tool('reset', p, ','.join(resets))
                    changed.append(_('reset: %s', ', '.join(r['reset_items'])))
            except Exception as e:                        # no half-finished edit remains: the save returns to its state before the edit
                _copy_atomic(os.path.join(self.backup_dir(slot), safety), p)
                raise SaveError(_('The edit could not be applied; the save is unchanged: %s', e))
            return changed

    def loot_list(self):
        """The save editor's item list (profile_tool.py entries; in memory after the first request)."""
        if getattr(self, '_loots', None) is None:
            self._loots = self.run_tool('entries')['items']
        return self._loots

    # ------------------------------------------------------------ character editor (draft)
    def draft(self, slot):
        return os.path.join(self.dir(slot), 'edit_base.json')

    def _draft_valid(self, slot):
        """Whether a draft exists and the profile has not changed since it was opened."""
        try:
            return os.path.isfile(self.draft(slot)) and self.meta(slot).get('edit_base') == os.stat(self.profile(slot)).st_mtime_ns
        except OSError:
            return False

    def _ensure_draft(self, slot):
        """A copy of the profile if there is no valid draft."""
        with self.lock:
            if self._draft_valid(slot):
                return
            validate_profile(_read_json(self.profile(slot)))
            _copy_atomic(self.profile(slot), self.draft(slot))
            self.set_meta(slot, edit_base=os.stat(self.profile(slot)).st_mtime_ns)

    def editor_open(self, slot):
        """The editor's view: the draft if there is one (with its difference from the main save), otherwise the profile. If the save is in the game the
        profile is shown read-only (the server overwrites it every 10 seconds)."""
        if not self.exists(slot):
            raise SaveError(_('Save not found.'))
        if self.in_use(slot):
            return dict(self.run_tool('read', self.profile(slot), tool='save_editor.py'), read_only=True, discarded=False)
        with self.lock:
            stale = os.path.isfile(self.draft(slot)) and not self._draft_valid(slot)
            if stale:
                self.editor_discard(slot)
            if self._draft_valid(slot):
                v = self.run_tool('read', self.draft(slot), self.profile(slot), tool='save_editor.py')
            else:
                v = self.run_tool('read', self.profile(slot), tool='save_editor.py')
        return dict(v, read_only=False, discarded=stale)

    def editor_apply(self, slot, ops):
        """Apply the operations to the draft (save_editor.OPS) -> the new view."""
        self.guard(slot, 'edit it')
        if not isinstance(ops, list) or not ops:
            raise SaveError(_('No changes.'))
        with self.lock:
            self._ensure_draft(slot)
            v = self.run_tool('apply', self.draft(slot), json.dumps(ops), self.profile(slot), tool='save_editor.py')
            return dict(v, read_only=False, discarded=False)

    def editor_commit(self, slot):
        """Write the draft to the save: first an 'once' backup -> the backup's name."""
        self.guard(slot, 'edit it')
        with self.lock:
            if not self._draft_valid(slot):
                raise SaveError(_('There are no changes to save.'))
            validate_profile(_read_json(self.draft(slot)))
            safety = self.backup(slot, 'before', _('Before character editor'))
            _copy_atomic(self.draft(slot), self.profile(slot))
            self.editor_discard(slot)
            return safety

    def editor_discard(self, slot):
        with self.lock:
            if os.path.isfile(self.draft(slot)):
                os.remove(self.draft(slot))
            m = self.meta(slot)
            if 'edit_base' in m:
                del m['edit_base']
                _write_json(os.path.join(self.dir(slot), 'slot.json'), m)

    def editor_catalog(self):
        """The editor's item catalog (save_editor.py catalog; in memory after the first request)."""
        if getattr(self, '_catalog', None) is None:
            self._catalog = self.run_tool('catalog', tool='save_editor.py')
        return {'items': self._catalog['items'], 'categories': self._catalog['categories']}

    def item_info(self):
        """Values for the item tooltip (save_editor.py info; in memory after the first request): the panel's Hangar, Shop and editor pages."""
        if getattr(self, '_info', None) is None:
            self._info = self.run_tool('info', tool='save_editor.py')['items']
        return self._info

    # ------------------------------------------------------------ backups
    def backup_files(self, slot):
        bid = self.backup_dir(slot)
        if not os.path.isdir(bid):
            return []
        return sorted((f for f in os.listdir(bid) if re.fullmatch(r'(auto|manual|before)_\d{8}_\d{6}(_\d+)?\.json', f)),
                      key=lambda f: (f.split('_', 1)[1], -TIE_ORDER[f.split('_', 1)[0]]), reverse=True)   # in the same second: manual, before, auto

    def notes(self, slot):
        try:
            d = _read_json(os.path.join(self.backup_dir(slot), 'notes.json'))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def backups(self, slot):
        notes, out = self.notes(slot), []
        for f in self.backup_files(slot):
            p = os.path.join(self.backup_dir(slot), f)
            st = os.stat(p)
            c = self._cache.get(p)
            if not c or c[0] != st.st_mtime_ns:
                try:
                    s = profile_summary(_read_json(p))
                except (OSError, ValueError):
                    s = {'pilot': '?', 'corrupt': True}
                self._cache[p] = c = (st.st_mtime_ns, s)
            kind, stamp = f.split('_', 1)
            t = time.strptime(stamp[:15], '%Y%m%d_%H%M%S')
            out.append(dict(c[1], file=f, type=kind, kind_name=_(KIND_NAMES[kind]), time=time.strftime('%Y-%m-%d %H:%M:%S', t),
                            size=st.st_size, not_=notes.get(f, '')))
        return out

    def backup(self, slot, kind='manual', note='', keep=None):
        """The profile's backup -> file name. The oto/once types are rotated (old ones deleted)."""
        if kind not in KINDS:
            raise SaveError(_('Invalid backup type.'))
        with self.lock:
            src = self.profile(slot)
            if not os.path.isfile(src):
                raise SaveError(_('Save not found.'))
            bid = self.backup_dir(slot)
            os.makedirs(bid, exist_ok=True)
            base = '%s_%s' % (kind, time.strftime('%Y%m%d_%H%M%S'))
            name, k = base + '.json', 2
            while os.path.exists(os.path.join(bid, name)):
                name = '%s_%d.json' % (base, k)
                k += 1
            for attempt in range(5):                      # if the server is writing at that moment (os.replace), at the next attempt
                try:
                    validate_profile(_read_json(src))
                    shutil.copy2(src, os.path.join(bid, name))
                    break
                except (OSError, ValueError):
                    if attempt == 4:
                        raise SaveError(_('The profile could not be read; no backup was taken.'))
                    time.sleep(0.2)
            if note:
                n = self.notes(slot)
                n[name] = note[:200]
                _write_json(os.path.join(bid, 'notes.json'), n)
            if kind == 'auto':
                self.rotate(slot, 'auto', keep or self.cfg.get('backup_count'))
            elif kind == 'before':
                self.rotate(slot, 'before', BEFORE_COUNT)
            return name

    def rotate(self, slot, kind, keep):
        files = [f for f in self.backup_files(slot) if f.startswith(kind + '_')]
        for f in files[keep:]:
            self._remove_backup(slot, f)
        return files[keep:]

    def _backup_path(self, slot, name):
        if not re.fullmatch(r'(auto|manual|before)_\d{8}_\d{6}(_\d+)?\.json', name or ''):
            raise SaveError(_('Invalid backup name.'))
        p = os.path.join(self.backup_dir(slot), name)
        if not os.path.isfile(p):
            raise SaveError(_('Backup not found.'))
        return p

    def _remove_backup(self, slot, name):
        os.remove(self._backup_path(slot, name))
        n = self.notes(slot)
        if name in n:
            del n[name]
            _write_json(os.path.join(self.backup_dir(slot), 'notes.json'), n)

    def delete_backup(self, slot, name):
        with self.lock:
            self._remove_backup(slot, name)

    def set_backup_note(self, slot, name, note):
        with self.lock:
            self._backup_path(slot, name)
            n = self.notes(slot)
            if note:
                n[name] = note[:200]
            else:
                n.pop(name, None)
            _write_json(os.path.join(self.backup_dir(slot), 'notes.json'), n)

    def restore(self, slot, name):
        """Restore the backup: first an 'once' backup of the current profile -> that backup's name."""
        self.guard(slot, 'restore it')
        with self.lock:
            p = self._backup_path(slot, name)
            validate_profile(_read_json(p))
            copy = p + '.geri'                       # when the oldest 'before' backup was restored, the safety backup's rotation deleted it
            shutil.copy2(p, copy)
            try:
                safety = self.backup(slot, 'before', _('Before restore (%s)', name))
                _copy_atomic(copy, self.profile(slot))
            finally:
                os.remove(copy)
            return safety

    def backup_as_new(self, slot, name, label=None):
        with self.lock:
            p = self._backup_path(slot, name)
            d = validate_profile(_read_json(p))
            label = (label or '').strip() or _('%s (backup %s)', self.meta(slot).get('name') or slot, name.split('_', 1)[1][:8])
            sid = self.new_id(label)
            dst = os.path.join(self.root, sid)
            os.makedirs(os.path.join(dst, 'backups'), exist_ok=True)
            shutil.copy2(p, os.path.join(dst, 'profile.json'))
            web = os.path.join(self.dir(slot), 'web_settings.json')
            if os.path.isfile(web):
                shutil.copy2(web, os.path.join(dst, 'web_settings.json'))
            _write_json(os.path.join(dst, 'slot.json'), {'name': label[:60], 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                                                          'not': _('From backup: %s / %s (%s)', self.meta(slot).get('name') or slot, name,
                                                                                               profile_summary(d)['pilot'])})
            return sid
