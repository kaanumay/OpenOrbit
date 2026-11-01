"""The panel's update (GitHub): if the last commit on branch BRANCH of repo REPO differs from the installed version, it is installed.

The install style is chosen automatically:
  git  the project is a git clone and git is installed: `git fetch` + fast-forward only (`merge --ff-only`). If there are local changes in tracked
       files, another branch or unpushed commits (a developer copy), nothing is touched, it is only reported.
  zip  downloaded by hand (Code > Download ZIP) or no git: the installed version comes from VERSION_FILE (GitHub's archive writes the commit via
       export-subst in .gitattributes) or from the state file (the record of the last update). The new version's archive (about 2 MB) is downloaded, changed
       files are written, those not in the new version are removed (the old version's list: the last update's list, otherwise the tree on GitHub).
User data is never touched (protected(): save/, logs/, personal login templates, the client folder, protocol versions, game images from the official
CDN, .git).
The old state of changed and removed files is moved to save/update/backup_<old version>/ (the last BACKUP_COUNT backups). Restarting the panel
after the install is the panel's job (panel.py). For a private repo (developer) the OO_GITHUB_TOKEN environment variable; the token is sent only to
api.github.com.
"""
import io, json, os, re, shutil, subprocess, threading, time, zipfile
import http.client
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lang import t as _

REPO = 'kaanumay/OpenOrbit'
BRANCH = 'main'
API = 'https://api.github.com'
VERSION_FILE = os.path.join('server', 'surum.txt')        # name kept (the old updater reads it); "$Format:%H %cI$" -> "<commit> <date>" in GitHub's archive
BACKUP_COUNT = 2
TIMEOUT = 30
MAX_SIZE = 500 << 20                                        # archive limit (bytes)
REQUIRED = ('OpenOrbit Panel.pyw', 'server/panel/panel.py', 'server/game.py')   # whether the archive is of this project
# versions before 2026-10-24 looked for 'DarkOrbit Panel.pyw' (the file was removed): those installs say "The archive is not of this project",
# the ZIP is downloaded again by hand (README).
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


class UpdateError(Exception):
    """Error shown to the user."""


def protected(rel):
    """Paths the update never writes or deletes (user data, generated files)."""
    r = rel.replace('\\', '/').lstrip('/').lower()
    return (r.startswith(('server/save/', 'server/logs/', 'server/data/protocols/', 'server/data/protokol/', 'server/cdn/do_img/',
                          '.git/', 'client_downloading/', 'istemci_indiriliyor/'))      # old names: install from before the migration
            or r in ('server/data/login.json', 'server/data/maps.json', 'server/data/responses.json',
                     'server/data/giris.json', 'server/data/haritalar.json', 'server/data/yanitlar.json',
                     'server/data/templates_format.json', '.git')
            or bool(re.match(r'server/data/v[12]_backup_[^/]*\.zip$', r))
            or bool(re.match(r'darkorbit_version[^/]*(/|$)', r)) or '/__pycache__/' in '/' + r)


def parse_version(text):
    """Contents of VERSION_FILE -> (commit, date) or (None, None) (not from an archive: "$Format...$")."""
    m = re.match(r'\s*([0-9a-f]{40})\s+(\S+)', text or '')
    return (m.group(1), m.group(2)) if m else (None, None)


def safe_rel(name):
    parts = [p for p in name.replace('\\', '/').split('/') if p not in ('', '.')]
    if not parts or any(p == '..' or ':' in p for p in parts):
        raise UpdateError(_('Invalid path in the archive: %s', name))
    return '/'.join(parts)


class Updater:
    def __init__(self, root, save_dir, log=print, opener=urlopen, go='git'):
        self.root, self.log, self.opener = root, log, opener
        self.git_exe = shutil.which(go) if go else None
        self.dir = os.path.join(save_dir, 'update')
        self.state_path = os.path.join(save_dir, 'update.json')
        self.lock = threading.Lock()
        self.d = {'state': 'unknown', 'running': False, 'last': None, 'last_check': None, 'error': None, 'claimed': 0, 'total': 0,
                  'changed': 0, 'removed': 0, 'backup': None, 'installed': None}
        self._inst = (0.0, None)                                 # cache of the installed version (so git does not run on every poll)

    # ------------------------------------------------------------ state
    def mode(self):
        return 'git' if self.git_exe and os.path.isdir(os.path.join(self.root, '.git')) else 'zip'

    def _saved(self):
        try:
            with open(self.state_path, encoding='utf8') as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp = self.state_path + '.tmp'
        with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    def _version_text(self):
        try:
            return open(os.path.join(self.root, VERSION_FILE), encoding='utf8').read().strip()
        except OSError:
            return ''

    def installed(self, fresh=False):
        """Installed version -> {'version', 'date', 'style'} (None if the version is unknown); cached for 10 s."""
        t, v = self._inst
        if not fresh and v and time.time() - t < 10:
            return dict(v)
        v = self._installed()
        self._inst = (time.time(), v)
        return dict(v)

    def _installed(self):
        if self.mode() == 'git':
            out = self._go_to('log', '-1', '--format=%H %cI', check=False)
            sha, date = parse_version(out)
            return {'version': sha, 'date': date, 'style': 'git'}
        txt, st = self._version_text(), self._saved()
        if st.get('version') and st.get('version_txt') == txt:          # this module installed the last update
            return {'version': st['version'], 'date': st.get('date'), 'style': 'zip'}
        sha, date = parse_version(txt)                             # archive downloaded by hand
        if sha:
            return {'version': sha, 'date': date, 'style': 'zip'}
        return {'version': st.get('version'), 'date': st.get('date'), 'style': 'zip'}

    def state(self):
        with self.lock:
            d = json.loads(json.dumps(self.d))
        d['built'] = self.installed()
        d['storage'] = 'https://github.com/%s' % REPO
        return d

    def running(self):
        with self.lock:
            return self.d['running']

    def _set(self, **kw):
        with self.lock:
            self.d.update(kw)

    # ------------------------------------------------------------ GitHub
    def _request(self, url, accept='application/vnd.github+json'):
        req = Request(url, headers={'Accept': accept, 'User-Agent': 'OpenOrbit', 'X-GitHub-Api-Version': '2022-11-28'})
        tok = os.environ.get('OO_GITHUB_TOKEN')
        if tok and url.startswith(API + '/'):
            req.add_unredirected_header('Authorization', 'Bearer ' + tok)    # not sent on a redirect (codeload)
        try:
            return self.opener(req, timeout=TIMEOUT)
        except HTTPError as e:
            if e.code == 404:
                raise UpdateError(_('GitHub repository not found (%s): it may be private or renamed.', REPO))
            if e.code in (403, 429) and (e.headers or {}).get('X-RateLimit-Remaining') == '0':
                raise UpdateError(_('GitHub request limit reached; it will try again within an hour.'))
            raise UpdateError(_('GitHub did not answer (HTTP %s).', e.code))
        except (OSError, http.client.HTTPException) as e:
            raise UpdateError(_("Could not reach GitHub (check your internet connection): %s", getattr(e, 'reason', e)))

    def _json(self, url):
        r = self._request(url)
        try:
            return json.loads(r.read().decode('utf8'))
        except ValueError:
            raise UpdateError(_('GitHub gave an unexpected answer.'))
        finally:
            r.close()

    def latest(self):
        """The latest version on GitHub -> {'version', 'date', 'message'}."""
        d = self._json('%s/repos/%s/commits/%s' % (API, REPO, BRANCH))
        c = d.get('commit') or {}
        if not re.match(r'^[0-9a-f]{40}$', d.get('sha') or ''):
            raise UpdateError(_('GitHub gave an unexpected answer.'))
        return {'version': d['sha'], 'date': (c.get('committer') or {}).get('date'), 'message': (c.get('message') or '').split('\n')[0][:200]}

    def tree(self, sha):
        """A version's files (GitHub's tree) -> set or None (could not be fetched/incomplete)."""
        try:
            d = self._json('%s/repos/%s/git/trees/%s?recursive=1' % (API, REPO, sha))
        except UpdateError:
            return None
        if d.get('truncated'):
            return None
        return {e['path'] for e in d.get('tree', []) if e.get('type') == 'blob'}

    # ------------------------------------------------------------ git
    def _go_to(self, *args, check=True, timeout=120):
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never', LC_ALL='C')
        try:
            r = subprocess.run([self.git_exe, '-C', self.root] + list(args), capture_output=True, text=True, encoding='utf8',
                               errors='replace', timeout=timeout, env=env, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as e:
            if check:
                raise UpdateError(_('Could not run git: %s', e))
            return ''
        if check and r.returncode:
            raise UpdateError(_('git %s failed: %s', args[0], (r.stderr or r.stdout).strip()[-300:]))
        return r.stdout.strip()

    def _git_ok(self, *args):
        """Did the git command succeed (exit code 0)."""
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
        try:
            return subprocess.run([self.git_exe, '-C', self.root] + list(args), capture_output=True, timeout=60, env=env,
                                  creationflags=NO_WINDOW).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _git_remote(self):
        """Fetch the latest version from origin -> (local, remote commit). An error if the fetch fails."""
        self._go_to('fetch', '--quiet', 'origin', BRANCH)
        return self._go_to('rev-parse', 'HEAD'), self._go_to('rev-parse', 'FETCH_HEAD')

    # ------------------------------------------------------------ check
    def check(self):
        """Check the latest version -> state: up_to_date | exists | local_changes | local_ahead | error."""
        with self.lock:
            if self.d['running'] or self.d.get('state') == 'installed':     # installed: waiting for a restart, 'up_to_date' would cancel it
                return json.loads(json.dumps(self.d))
            self.d.update(running=True, error=None)
        try:
            if self.mode() == 'git':
                head, remote = self._git_remote()
                out = self._go_to('log', '-1', '--format=%cI%n%s', remote)
                date, msg = (out.split('\n', 1) + [''])[:2]
                last = {'version': remote, 'date': date, 'message': msg[:200]}
                if head == remote:
                    state = 'up_to_date'
                elif self._git_ok('merge-base', '--is-ancestor', head, remote):
                    dirty = self._go_to('status', '--porcelain', '--untracked-files=no')
                    branch = self._go_to('rev-parse', '--abbrev-ref', 'HEAD')
                    state = 'local_changes' if dirty or branch != BRANCH else 'exists'
                else:
                    state = 'local_ahead'
            else:
                last = self.latest()
                state = 'up_to_date' if last['version'] == self.installed(fresh=True)['version'] else 'exists'
            self._set(last=last, state=state)
            self.log('update check (%s): %s, GitHub %s' % (self.mode(), state, last['version'][:7]))
        except UpdateError as e:
            self._set(state='error', error=str(e))
            self.log('update check: %s' % e)
        finally:
            self._set(running=False, last_check=time.time())
        return self.state()

    # ------------------------------------------------------------ installation
    def install_async(self):
        with self.lock:
            if self.d['running']:
                raise UpdateError(_('An update is already running.'))
            if self.d['state'] != 'exists' or not self.d['last']:
                raise UpdateError(_('There is no new version to install.'))
            self.d.update(running=True, state='downloading', error=None, claimed=0, total=0, changed=0, removed=0)
            target = dict(self.d['last'])
        threading.Thread(target=self._install, args=(target,), daemon=True).start()
        return self.state()

    def _install(self, last):
        try:
            if self.mode() == 'git':
                self._install_git(last)
            else:
                self._install_zip(last)
            self._inst = (0.0, None)
            self._set(state='installed', installed=time.time())
            self.log('update installed: %s (%s)' % (last['version'][:7], last.get('message', '')))
        except UpdateError as e:
            self._set(state='error', error=str(e))
            self.log('update could not be installed: %s' % e)
        except Exception as e:
            self._set(state='error', error=_('Unexpected error: %r', e))
            self.log('update could not be installed: %r' % e)
        finally:
            self._set(running=False)

    def _install_git(self, last):
        self._set(state='installing')
        head, remote = self._git_remote()
        if self._go_to('status', '--porcelain', '--untracked-files=no') or self._go_to('rev-parse', '--abbrev-ref', 'HEAD') != BRANCH:
            raise UpdateError(_('There are local changes: get the update with git.'))
        self._go_to('merge', '--ff-only', '--quiet', remote)
        if self._go_to('rev-parse', 'HEAD') != remote:
            raise UpdateError(_('git could not fast-forward.'))
        last.update(version=remote)

    def _download(self, sha):
        """Download the version's archive -> bytes (opened in memory; about 2 MB)."""
        r = self._request('%s/repos/%s/zipball/%s' % (API, REPO, sha), accept='application/vnd.github+json')
        try:
            self._set(total=int(r.headers.get('Content-Length') or 0))
            buf = io.BytesIO()
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                buf.write(b)
                with self.lock:
                    self.d['claimed'] += len(b)
                if buf.tell() > MAX_SIZE:
                    raise UpdateError(_('The archive is larger than expected.'))
        except (OSError, http.client.HTTPException) as e:
            raise UpdateError(_('The download was interrupted: %s', e))
        finally:
            r.close()
        return buf.getvalue()

    def _install_zip(self, last):
        before = self.installed(fresh=True)
        data = self._download(last['version'])
        self._set(state='installing')
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise UpdateError(_('The downloaded archive is damaged.'))
        infos = [i for i in z.infolist() if not i.is_dir()]
        tops = {i.filename.split('/', 1)[0] for i in infos}
        if len(tops) != 1 or not all('/' in i.filename for i in infos):
            raise UpdateError(_('The archive has an unexpected layout.'))
        top = tops.pop() + '/'
        files = {}
        for i in infos:
            rel = safe_rel(i.filename[len(top):])
            if not protected(rel):
                files[rel] = i
        if not all(g in files for g in REQUIRED):
            raise UpdateError(_('The archive is not this project.'))
        old = None
        st = self._saved()
        if before['version'] and st.get('version') == before['version'] and isinstance(st.get('files'), list):
            old = set(st['files'])
        elif before['version']:
            old = self.tree(before['version'])
        backup = os.path.join(self.dir, 'backup_%s_%s' % ((before['version'] or 'unknown')[:7], time.strftime('%Y%m%d_%H%M%S')))

        def keep(rel):                                    # the old state to the backup
            src = os.path.join(self.root, *rel.split('/'))
            dst = os.path.join(backup, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        changed = removed = 0
        # version stamp last: so an install cut short does not think it is "up to date" (so it is retried)
        for rel, info in sorted(files.items(), key=lambda x: (x[0] == VERSION_FILE.replace(os.sep, '/'), x[0])):
            new = z.read(info)                            # CRC zipfile'da denetlenir
            dest = os.path.join(self.root, *rel.split('/'))
            if os.path.isfile(dest):
                with open(dest, 'rb') as fh:
                    if fh.read() == new:
                        continue
                keep(rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + '.guncelleme'
            with open(tmp, 'wb') as fh:
                fh.write(new)
            os.replace(tmp, dest)
            changed += 1
        for rel in sorted((old or set()) - set(files)):
            p = os.path.join(self.root, *rel.split('/'))
            if protected(rel) or not os.path.isfile(p):
                continue
            keep(rel)
            os.remove(p)                                  # the old state in the backup
            removed += 1
            d = os.path.dirname(p)
            while d != self.root and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                d = os.path.dirname(d)
        self._set(changed=changed, removed=removed, backup=backup if os.path.isdir(backup) else None)
        self._save({'version': last['version'], 'date': last.get('date'), 'message': last.get('message'), 'version_txt': self._version_text(),
                    'files': sorted(files), 'previous': before['version'], 'setup': time.strftime('%Y-%m-%d %H:%M:%S')})
        self._prune()

    def _prune(self):
        try:
            old_backups = sorted((os.path.join(self.dir, n) for n in os.listdir(self.dir) if n.startswith('backup_')), key=os.path.getmtime)
        except OSError:
            return
        for d in old_backups[:-BACKUP_COUNT]:
            shutil.rmtree(d, ignore_errors=True)

