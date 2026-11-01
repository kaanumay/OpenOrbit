"""Panelin güncellemesi (GitHub): DEPO deposunun DAL dalındaki son commit kurulu sürümden farklıysa kurulur.

Kurulum biçimi kendiliğinden seçilir:
  git  proje bir git klonu ve git kurulu: `git fetch` + yalnız ileri sarma (`merge --ff-only`). İzlenen dosyalarda yerel değişiklik,
       başka dal ya da gönderilmemiş commit varsa (geliştirici kopyası) dokunulmaz, yalnız bildirilir.
  zip  elle indirilmiş (Code > Download ZIP) ya da git yok: kurulu sürüm SURUM_DOSYASI'ndan (GitHub'ın arşivi .gitattributes'taki
       export-subst ile commit'i yazar) ya da DURUM'dan (son güncellemenin kaydı). Yeni sürümün arşivi (≈2 MB) indirilir, değişen
       dosyalar yazılır, yeni sürümde olmayanlar kaldırılır (eski sürümün listesi: son güncellemenin listesi, yoksa GitHub'daki ağacı).
Kullanıcı verisine hiç dokunulmaz (korunan(): save/, logs/, kişisel giriş şablonları, istemci klasörü, protokol sürümleri, resmî
CDN'den inen oyun görselleri, .git).
Değişen ve kaldırılan dosyaların eski hâli save/guncelleme/yedek_<eski sürüm>/'e taşınır (son YEDEK_SAYISI yedek). Kurulumdan sonra
paneli yeniden başlatmak panelin işi (panel.py). Özel depo için (geliştirici) OO_GITHUB_TOKEN ortam değişkeni; belirteç yalnız
api.github.com'a gönderilir.
"""
import io, json, os, re, shutil, subprocess, threading, time, zipfile
import http.client
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lang import t as _

REPO = 'kaanumay/OpenOrbit'
BRANCH = 'main'
API = 'https://api.github.com'
VERSION_FILE = os.path.join('server', 'surum.txt')        # "$Format:%H %cI$" -> GitHub arşivinde "<commit> <tarih>"
BACKUP_COUNT = 2
TIMEOUT = 30
MAX_SIZE = 500 << 20                                        # arşiv sınırı (bayt)
REQUIRED = ('OpenOrbit Panel.pyw', 'server/panel/panel.py', 'server/game.py')   # arşiv bu projenin mi
# 2026-10-24'ten önceki sürümler 'DarkOrbit Panel.pyw' arıyordu (dosya kaldırıldı): o kurulumlar "Arşiv bu projenin değil"
# der, ZIP elle yeniden indirilir (README).
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


class UpdateError(Exception):
    """Kullanıcıya gösterilen hata."""


def protected(rel):
    """Güncellemenin hiç yazmadığı ve silmediği yollar (kullanıcı verisi, üretilen dosyalar)."""
    r = rel.replace('\\', '/').lstrip('/').lower()
    return (r.startswith(('server/save/', 'server/logs/', 'server/data/protocols/', 'server/data/protokol/', 'server/cdn/do_img/',
                          '.git/', 'client_downloading/', 'istemci_indiriliyor/'))      # eski adlar: göçten önceki kurulum
            or r in ('server/data/login.json', 'server/data/maps.json', 'server/data/responses.json',
                     'server/data/giris.json', 'server/data/haritalar.json', 'server/data/yanitlar.json',
                     'server/data/templates_format.json', '.git')
            or bool(re.match(r'server/data/v[12]_backup_[^/]*\.zip$', r))
            or bool(re.match(r'darkorbit_version[^/]*(/|$)', r)) or '/__pycache__/' in '/' + r)


def parse_version(text):
    """SURUM_DOSYASI'nın içeriği -> (commit, tarih) ya da (None, None) (arşivden gelmemiş: "$Format…$")."""
    m = re.match(r'\s*([0-9a-f]{40})\s+(\S+)', text or '')
    return (m.group(1), m.group(2)) if m else (None, None)


def safe_rel(name):
    parts = [p for p in name.replace('\\', '/').split('/') if p not in ('', '.')]
    if not parts or any(p == '..' or ':' in p for p in parts):
        raise UpdateError(_('Arşivde geçersiz yol: %s', name))
    return '/'.join(parts)


class Updater:
    def __init__(self, root, save_dir, log=print, opener=urlopen, go='git'):
        self.root, self.log, self.opener = root, log, opener
        self.git_exe = shutil.which(go) if go else None
        self.dir = os.path.join(save_dir, 'update')
        self.state_path = os.path.join(save_dir, 'update.json')
        self.lock = threading.Lock()
        self.d = {'durum': 'bilinmiyor', 'running': False, 'last': None, 'last_check': None, 'hata': None, 'claimed': 0, 'toplam': 0,
                  'changed': 0, 'removed': 0, 'backup': None, 'installed': None}
        self._inst = (0.0, None)                                 # kurulu sürümün önbelleği (git her yoklamada çalışmasın)

    # ------------------------------------------------------------ durum
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
        """Kurulu sürüm -> {'surum', 'tarih', 'bicim'} (sürüm bilinmiyorsa None); 10 sn önbellekli."""
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
            return {'surum': sha, 'tarih': date, 'style': 'git'}
        txt, st = self._version_text(), self._saved()
        if st.get('surum') and st.get('version_txt') == txt:          # son güncellemeyi bu modül kurdu
            return {'surum': st['surum'], 'tarih': st.get('tarih'), 'style': 'zip'}
        sha, date = parse_version(txt)                             # elle indirilen arşiv
        if sha:
            return {'surum': sha, 'tarih': date, 'style': 'zip'}
        return {'surum': st.get('surum'), 'tarih': st.get('tarih'), 'style': 'zip'}

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
            req.add_unredirected_header('Authorization', 'Bearer ' + tok)    # yönlendirmede (codeload) gönderilmez
        try:
            return self.opener(req, timeout=TIMEOUT)
        except HTTPError as e:
            if e.code == 404:
                raise UpdateError(_('GitHub deposu bulunamadı (%s): depo özel ya da adı değişmiş olabilir.', REPO))
            if e.code in (403, 429) and (e.headers or {}).get('X-RateLimit-Remaining') == '0':
                raise UpdateError(_('GitHub istek sınırı doldu; bir saat içinde yeniden denenir.'))
            raise UpdateError(_('GitHub yanıt vermedi (HTTP %s).', e.code))
        except (OSError, http.client.HTTPException) as e:
            raise UpdateError(_("GitHub'a ulaşılamadı (internet bağlantını denetle): %s", getattr(e, 'reason', e)))

    def _json(self, url):
        r = self._request(url)
        try:
            return json.loads(r.read().decode('utf8'))
        except ValueError:
            raise UpdateError(_('GitHub beklenmeyen bir yanıt verdi.'))
        finally:
            r.close()

    def latest(self):
        """GitHub'daki son sürüm -> {'surum', 'tarih', 'mesaj'}."""
        d = self._json('%s/repos/%s/commits/%s' % (API, REPO, BRANCH))
        c = d.get('commit') or {}
        if not re.match(r'^[0-9a-f]{40}$', d.get('sha') or ''):
            raise UpdateError(_('GitHub beklenmeyen bir yanıt verdi.'))
        return {'surum': d['sha'], 'tarih': (c.get('committer') or {}).get('date'), 'message': (c.get('message') or '').split('\n')[0][:200]}

    def tree(self, sha):
        """Bir sürümün dosyaları (GitHub'ın ağacı) -> küme ya da None (alınamadı/eksik)."""
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
                raise UpdateError(_('git çalıştırılamadı: %s', e))
            return ''
        if check and r.returncode:
            raise UpdateError(_('git %s başarısız: %s', args[0], (r.stderr or r.stdout).strip()[-300:]))
        return r.stdout.strip()

    def _git_ok(self, *args):
        """git komutu başarılı mı (çıkış kodu 0)."""
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
        try:
            return subprocess.run([self.git_exe, '-C', self.root] + list(args), capture_output=True, timeout=60, env=env,
                                  creationflags=NO_WINDOW).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _git_remote(self):
        """origin'den son sürümü al -> (yerel, uzak commit). Fetch başarısızsa hata."""
        self._go_to('fetch', '--quiet', 'origin', BRANCH)
        return self._go_to('rev-parse', 'HEAD'), self._go_to('rev-parse', 'FETCH_HEAD')

    # ------------------------------------------------------------ denetim
    def check(self):
        """Son sürümü denetle -> durum: guncel | var | yerel_degisiklik | yerelde_ileri | hata."""
        with self.lock:
            if self.d['running'] or self.d.get('durum') == 'installed':     # kuruldu: yeniden başlatma bekliyor, 'guncel' onu iptal ederdi
                return json.loads(json.dumps(self.d))
            self.d.update(running=True, hata=None)
        try:
            if self.mode() == 'git':
                head, remote = self._git_remote()
                out = self._go_to('log', '-1', '--format=%cI%n%s', remote)
                date, msg = (out.split('\n', 1) + [''])[:2]
                last = {'surum': remote, 'tarih': date, 'message': msg[:200]}
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
                state = 'up_to_date' if last['surum'] == self.installed(fresh=True)['surum'] else 'exists'
            self._set(last=last, durum=state)
            self.log('güncelleme denetimi (%s): %s, GitHub %s' % (self.mode(), state, last['surum'][:7]))
        except UpdateError as e:
            self._set(durum='hata', hata=str(e))
            self.log('güncelleme denetimi: %s' % e)
        finally:
            self._set(running=False, last_check=time.time())
        return self.state()

    # ------------------------------------------------------------ kurulum
    def install_async(self):
        with self.lock:
            if self.d['running']:
                raise UpdateError(_('Güncelleme zaten sürüyor.'))
            if self.d['durum'] != 'exists' or not self.d['last']:
                raise UpdateError(_('Kurulacak yeni sürüm yok.'))
            self.d.update(running=True, durum='downloading', hata=None, claimed=0, toplam=0, changed=0, removed=0)
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
            self._set(durum='installed', installed=time.time())
            self.log('güncelleme kuruldu: %s (%s)' % (last['surum'][:7], last.get('message', '')))
        except UpdateError as e:
            self._set(durum='hata', hata=str(e))
            self.log('güncelleme kurulamadı: %s' % e)
        except Exception as e:
            self._set(durum='hata', hata=_('Beklenmeyen hata: %r', e))
            self.log('güncelleme kurulamadı: %r' % e)
        finally:
            self._set(running=False)

    def _install_git(self, last):
        self._set(durum='installing')
        head, remote = self._git_remote()
        if self._go_to('status', '--porcelain', '--untracked-files=no') or self._go_to('rev-parse', '--abbrev-ref', 'HEAD') != BRANCH:
            raise UpdateError(_('Yerel değişiklikler var: güncellemeyi git ile al.'))
        self._go_to('merge', '--ff-only', '--quiet', remote)
        if self._go_to('rev-parse', 'HEAD') != remote:
            raise UpdateError(_('git ileri saramadı.'))
        last.update(surum=remote)

    def _download(self, sha):
        """Sürümün arşivini indir -> bayt (bellekte açılır; ≈2 MB)."""
        r = self._request('%s/repos/%s/zipball/%s' % (API, REPO, sha), accept='application/vnd.github+json')
        try:
            self._set(toplam=int(r.headers.get('Content-Length') or 0))
            buf = io.BytesIO()
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                buf.write(b)
                with self.lock:
                    self.d['claimed'] += len(b)
                if buf.tell() > MAX_SIZE:
                    raise UpdateError(_('Arşiv beklenenden büyük.'))
        except (OSError, http.client.HTTPException) as e:
            raise UpdateError(_('İndirme yarıda kaldı: %s', e))
        finally:
            r.close()
        return buf.getvalue()

    def _install_zip(self, last):
        before = self.installed(fresh=True)
        data = self._download(last['surum'])
        self._set(durum='installing')
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise UpdateError(_('İndirilen arşiv bozuk.'))
        infos = [i for i in z.infolist() if not i.is_dir()]
        tops = {i.filename.split('/', 1)[0] for i in infos}
        if len(tops) != 1 or not all('/' in i.filename for i in infos):
            raise UpdateError(_('Arşivin düzeni beklenmiyor.'))
        top = tops.pop() + '/'
        files = {}
        for i in infos:
            rel = safe_rel(i.filename[len(top):])
            if not protected(rel):
                files[rel] = i
        if not all(g in files for g in REQUIRED):
            raise UpdateError(_('Arşiv bu projenin değil.'))
        old = None
        st = self._saved()
        if before['surum'] and st.get('surum') == before['surum'] and isinstance(st.get('files'), list):
            old = set(st['files'])
        elif before['surum']:
            old = self.tree(before['surum'])
        backup = os.path.join(self.dir, 'backup_%s_%s' % ((before['surum'] or 'bilinmiyor')[:7], time.strftime('%Y%m%d_%H%M%S')))

        def keep(rel):                                    # eski hâli yedeğe
            src = os.path.join(self.root, *rel.split('/'))
            dst = os.path.join(backup, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        changed = removed = 0
        # sürüm damgası en son: yarıda kalan kurulum kendini "güncel" sanmasın (yeniden denensin)
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
            os.remove(p)                                  # eski hâli yedekte
            removed += 1
            d = os.path.dirname(p)
            while d != self.root and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                d = os.path.dirname(d)
        self._set(changed=changed, removed=removed, backup=backup if os.path.isdir(backup) else None)
        self._save({'surum': last['surum'], 'tarih': last.get('tarih'), 'message': last.get('message'), 'version_txt': self._version_text(),
                    'files': sorted(files), 'previous': before['surum'], 'setup': time.strftime('%Y-%m-%d %H:%M:%S')})
        self._prune()

    def _prune(self):
        try:
            old_backups = sorted((os.path.join(self.dir, n) for n in os.listdir(self.dir) if n.startswith('backup_')), key=os.path.getmtime)
        except OSError:
            return
        for d in old_backups[:-BACKUP_COUNT]:
            shutil.rmtree(d, ignore_errors=True)

