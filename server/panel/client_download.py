"""Downloading the game client (if no client is found on the computer; setup wizard and Client page): Bigpoint's archive (URL,
1.1.116 zip) is extracted into the project root, the client files are not modified.

The archive is not saved to disk: it is read with HTTP range requests (HttpFile), and zipfile extracts the files directly in order. So the
archive itself needs no extra space (just as much as its extracted form, about 4.4 GB). If the connection drops it reconnects from the same byte (RETRIES times);
if the job is stopped or the panel closes, the extracted files stay, and on restart only the missing ones are downloaded. Each file is written to .part first,
and gets its name once verified with the zip's CRC. Files are collected in a temporary folder (TEMP); when all are done and the client is verified, the folder
takes the name in the archive (DarkOrbit_Version1.1.116): a half download does not look like a valid client. Only one job at a time.

The server gives about 5 MB/s per connection: consecutive files in the archive are split into chunks of CHUNK_SIZE bytes, and CONNECTIONS connections each read and extract one chunk
with a single request. The number of requests is kept low: short, frequent range requests run into the CDN's protection (2026-10-28, with 8 MB
pieces the IP was blocked within a minute: HTTP 403 "denied by custom_acl"); when blocked it is not retried, the user is told.
"""
import http.client, json, os, shutil, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lang import t as _

URL = 'https://alicdn-oss-prod.darkorbit.com/release/archive/DarkOrbit_Version1.1.116.zip'
TEMP = 'client_downloading'       # in the project root; in .gitignore (old name istemci_indiriliyor: a half download starts from scratch)
CHUNK = 1 << 20
CHUNK_SIZE = 64 << 20                     # consecutive files a connection reads with a single request (a large file alone)
CONNECTIONS = 3                        # connections open at once (about 5 MB/s per connection); 6 connections ran into the CDN block
SKIP_AHEAD = 1 << 20                      # a forward skip of this size is read through without opening a new request
RETRIES = 8                          # successive reconnects on a dropped connection
TIMEOUT = 30
PAY = 200 << 20                     # extra space for the disk check
LT = float(1 << 30)


def cooldown(k):
    """Seconds to wait before the k-th reconnect (tests shorten it)."""
    return min(30, 2 ** k)


class DownloadError(Exception):
    """The error shown to the user."""


class Cancelled(Exception):
    pass


def block(e):
    """The CDN's access block (403/429): retrying prolongs the block."""
    if isinstance(e, HTTPError) and e.code in (403, 429):
        return DownloadError(_('The download server temporarily blocked access (HTTP %d). Resume in a few minutes: downloaded files '
                               'are kept.', e.code))
    return None


class HttpFile:
    """A seekable read-only file read with HTTP range requests (for zipfile). Sequential reads keep a single connection;
    if the connection drops it reopens at the same place. Stops if the archive changes on the server (ETag)."""

    def __init__(self, url, stop, on_bytes=None, opener=urlopen, size=None, etag=None):
        self.url, self.stop, self.on_bytes, self.opener = url, stop, on_bytes, opener
        self.pos, self.resp, self.rpos, self.etag = 0, None, None, etag
        if size is not None:                # the second connection of the same archive: size and ETag from the first
            self.size = size
            return
        try:
            r = self._request(0, 0)
        except (OSError, http.client.HTTPException) as e:
            raise block(e) or DownloadError(_('Could not connect to the download server (check your internet connection): %s', e))
        cr = r.headers.get('Content-Range') or ''
        r.close()
        try:
            self.size = int(cr.rsplit('/', 1)[1])
        except (IndexError, ValueError):
            raise DownloadError(_('The download server does not support resuming.'))

    def _request(self, start, end=None):
        h = {'Range': 'bytes=%d-%s' % (start, '' if end is None else end), 'User-Agent': 'OpenOrbit'}
        if self.etag:
            h['If-Range'] = self.etag
        r = self.opener(Request(self.url, headers=h), timeout=TIMEOUT)
        if r.status != 206:
            r.close()
            raise DownloadError(_('The download server does not support resuming, or the archive has changed; start again.'))
        self.etag = self.etag or r.headers.get('ETag')
        return r

    def _close(self):
        if self.resp is not None:
            try:
                self.resp.close()
            except Exception:
                pass
        self.resp = self.rpos = None

    def close(self):
        self._close()

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        n = self.size - self.pos if n is None or n < 0 else min(n, self.size - self.pos)
        out, tries = [], 0
        while n > 0:
            if self.stop.is_set():
                raise Cancelled()
            try:
                if self.resp is not None and self.rpos < self.pos <= self.rpos + SKIP_AHEAD:     # short forward skip: read through
                    while self.rpos < self.pos:
                        b = self.resp.read(self.pos - self.rpos)
                        if not b:
                            raise ConnectionError('bağlantı kapandı')
                        self.rpos += len(b)
                if self.resp is None or self.rpos != self.pos:
                    self._close()
                    self.resp, self.rpos = self._request(self.pos), self.pos
                data = self.resp.read(min(n, CHUNK))
                if not data:
                    raise ConnectionError('bağlantı kapandı')
            except (OSError, http.client.HTTPException) as e:          # URLError, timeout, dropped connection
                self._close()
                if block(e):
                    raise block(e)
                tries += 1
                if tries > RETRIES:
                    raise DownloadError(_('Connection lost: %s', e))
                if self.stop.wait(cooldown(tries)):
                    raise Cancelled()
                continue
            tries = 0
            self.pos += len(data)
            self.rpos = self.pos
            n -= len(data)
            out.append(data)
            if self.on_bytes:
                self.on_bytes(len(data))
        return b''.join(out)


def top_folder(names):
    """The name of the single top folder if all entries are in one, otherwise ''."""
    tops = {n.split('/', 1)[0] for n in names}
    return tops.pop() if len(tops) == 1 and all('/' in n or n.endswith('/') for n in names) else ''


def safe_path(base, rel):
    """Keep the path in the archive inside the folder (../ and absolute paths are invalid)."""
    parts = [p for p in rel.replace('\\', '/').split('/') if p not in ('', '.')]
    if not parts or any(p == '..' or ':' in p for p in parts):
        raise DownloadError(_('Invalid path in the archive: %s', rel))
    return os.path.join(base, *parts)


class Downloader:
    def __init__(self, root, check, log=print, on_done=None, url=URL, opener=urlopen):
        self.root, self.check, self.log, self.on_done, self.url, self.opener = root, check, log, on_done, url, opener
        self.stage = os.path.join(root, TEMP)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.d = self._blank('vacant')
        self.samples = []
        self.connection = CONNECTIONS

    @staticmethod
    def _blank(state):
        return {'state': state, 'running': False, 'claimed': 0, 'total': 0, 'unpacked_size': 0, 'file': '', 'done_files': 0,
                'file_count': 0, 'speed': 0, 'time_left_sec': None, 'error': None, 'target': None, 'start': None, 'end_time': None}

    def state(self):
        with self.lock:
            d = json.loads(json.dumps(self.d))
        if d['total']:
            d['claimed'] = min(d['claimed'], d['total'])
        d['url'] = self.url
        d['partial'] = not d['running'] and os.path.isdir(self.stage)       # files left from the previous download
        return d

    def running(self):
        with self.lock:
            return self.d['running']

    def start(self, fast=True):
        with self.lock:
            busy = self.d['running']
            if not busy:
                self.connection = CONNECTIONS if fast else 1
                self.stop.clear()
                self.d = dict(self._blank('preparing'), running=True, start=time.time())
                self.samples = []
        if not busy:
            threading.Thread(target=self._run, daemon=True).start()
        return self.state()

    def cancel(self):
        self.stop.set()
        return self.state()

    def discard(self):
        """Delete the temporary folder of a half-finished download (while the job is stopped; only TEMP)."""
        if self.running():
            raise DownloadError(_('The download is running: stop it first.'))
        if os.path.isdir(self.stage):
            shutil.rmtree(self.stage)
            self.log('half client download deleted: %s' % self.stage)
        with self.lock:
            self.d = self._blank('vacant')
        return self.state()

    def _count(self, n):
        now = time.monotonic()
        with self.lock:
            self.d['claimed'] += n
            self.samples.append((now, self.d['claimed']))
            while len(self.samples) > 2 and now - self.samples[0][0] > 8:
                self.samples.pop(0)
            t0, b0 = self.samples[0]
            if now - t0 >= 1:
                self.d['speed'] = int((self.d['claimed'] - b0) / (now - t0))
                left = max(0, self.d['total'] - self.d['claimed'])
                self.d['time_left_sec'] = int(left / self.d['speed']) if self.d['speed'] > 0 else None

    def _set(self, **kw):
        with self.lock:
            self.d.update(kw)

    def _target(self, name):
        """The final folder: the name in the archive in the project root; if that name is taken (another folder) "name (2)" ..."""
        p, k = os.path.join(self.root, name), 2
        while os.path.exists(p):
            p, k = os.path.join(self.root, '%s (%d)' % (name, k)), k + 1
        return p

    def _open(self, h, i, p):
        """Extract the file in the archive (from its local header) to .part; zipfile's reader extracts and checks the CRC."""
        h.seek(i.header_offset)
        fh = h.read(30)
        if fh[:4] != b'PK':
            raise zipfile.BadZipFile('yerel başlık yok: %s' % i.filename)
        h.read(int.from_bytes(fh[26:28], 'little') + int.from_bytes(fh[28:30], 'little'))   # name and extra field
        os.makedirs(os.path.dirname(p), exist_ok=True)
        part = p + '.part'
        with zipfile.ZipExtFile(h, 'rb', i) as src, open(part, 'wb') as out:     # checks the CRC at the end (BadZipFile)
            while True:
                b = src.read(CHUNK)
                if not b:
                    break
                out.write(b)
        os.replace(part, p)

    def _run(self):
        f = None
        try:
            f = HttpFile(self.url, self.stop, self._count, self.opener)
            z = zipfile.ZipFile(f)
            infos = sorted(z.infolist(), key=lambda i: i.header_offset)
            top = top_folder([i.filename for i in infos])
            files = []
            for i in infos:
                rel = i.filename[len(top) + 1:] if top else i.filename
                if rel.strip('/'):
                    files.append((i, safe_path(self.stage, rel)))
            items = [(i, p) for i, p in files if not i.is_dir()]
            done = {p for i, p in items if os.path.isfile(p) and os.path.getsize(p) == i.file_size}
            need = sum(i.file_size for i, p in items if p not in done)
            free = shutil.disk_usage(self.root).free
            if free < need + PAY:
                raise DownloadError(_('Not enough disk space: %.1f GB needed, %.1f GB free.', (need + PAY) / LT, free / LT))
            self._set(state='downloading', total=sum(i.compress_size for i, p in items), unpacked_size=sum(i.file_size for i, p in items),
                      claimed=sum(i.compress_size for i, p in items if p in done), file_count=len(items), done_files=len(done))
            self.log('downloading client: %s (%d files, %d already present, %d connections)' % (self.url, len(items), len(done), self.connection))
            for i, p in files:
                if i.is_dir():
                    os.makedirs(p, exist_ok=True)
            groups, g, size = [], [], 0
            for i, p in items:
                if p in done:
                    continue
                g.append((i, p))
                size += i.compress_size
                if size >= CHUNK_SIZE:
                    groups.append(g)
                    g, size = [], 0
            if g:
                groups.append(g)
            f.close()                               # the connection that reads the index; the groups extract the files
            errors = []

            def open_chunk(g):
                h = HttpFile(self.url, self.stop, self._count, self.opener, size=f.size, etag=f.etag)
                try:
                    for i, p in g:
                        if self.stop.is_set():
                            raise Cancelled()
                        self._set(file=os.path.relpath(p, self.stage))
                        self._open(h, i, p)
                        with self.lock:
                            self.d['done_files'] += 1
                except BaseException as e:
                    errors.append(e)
                    self.stop.set()                 # let the other connections stop too
                finally:
                    h.close()
            with ThreadPoolExecutor(self.connection) as pool:
                list(pool.map(open_chunk, groups))
            if errors:
                raise next((e for e in errors if not isinstance(e, Cancelled)), errors[0])
            self._set(state='verifying', file='')
            c = self.check(self.stage)
            if not c['valid']:
                raise DownloadError(_('The downloaded folder is not a DarkOrbit client: %s', ' '.join(c['issues'])))
            target = self._target(top or os.path.splitext(os.path.basename(self.url))[0])
            for k in range(10):                     # if an antivirus scanner is holding a file, wait a little
                try:
                    os.rename(self.stage, target)
                    break
                except OSError:
                    if k == 9:
                        raise
                    time.sleep(1)
            self._set(state='finished', target=target, claimed=self.d['total'], time_left_sec=0)
            self.log('client downloaded: %s' % target)
            if self.on_done:
                self.on_done(target)
        except Cancelled:
            self._set(state='stopped')
            self.log('client download stopped')
        except DownloadError as e:
            self._set(state='error', error=str(e))
            self.log('client download error: %s' % e)
        except zipfile.BadZipFile as e:
            self._set(state='error', error=_('The archive arrived damaged (%s). Start again: only the missing files are downloaded.', e))
            self.log('client download: corrupt archive: %s' % e)
        except OSError as e:
            self._set(state='error', error=_('Could not write a file: %s', e))
            self.log('client download: write error: %r' % e)
        except Exception as e:
            self._set(state='error', error=repr(e))
            self.log('client download: unexpected error: %r' % e)
        finally:
            if f is not None:
                f.close()
            with self.lock:
                self.d['running'], self.d['end_time'] = False, time.time()
                self.d['speed'] = 0
