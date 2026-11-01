"""Oyun istemcisini indirme (bilgisayarda istemci bulunamazsa; kurulum sihirbazı ve İstemci sayfası): Bigpoint'in arşivi (URL,
1.1.116 zip) proje köküne açılır, istemci dosyaları değiştirilmez.

Arşiv diske kaydedilmez: HTTP aralık istekleriyle okunur (HttpFile), zipfile dosyaları sırayla doğrudan açar. Böylece arşivin
kendisi için ayrıca yer gerekmez (açılmış hâli kadar, ≈4,4 GB). Bağlantı koparsa aynı bayttan yeniden bağlanır (DENEME kez);
iş durdurulur ya da panel kapanırsa açılmış dosyalar kalır, yeniden başlatınca yalnız eksikler iner. Her dosya önce .part'a yazılır,
zip'in CRC'siyle doğrulanınca adını alır. Dosyalar geçici klasörde (GECICI) toplanır; hepsi bitip istemci doğrulanınca klasör
arşivdeki adı (DarkOrbit_Version1.1.116) alır: yarım indirme geçerli istemci gibi görünmez. Aynı anda tek iş.

Sunucu bağlantı başına ≈5 MB/sn veriyor: arşivdeki ardışık dosyalar GRUP baytlık öbeklere bölünür, BAGLANTI bağlantı birer öbeği
tek istekle okuyup açar. İstek sayısı az tutulur: kısa ve sık aralık istekleri CDN'in korumasına takılıyor (2026-10-28, 8 MB'lık
parçalarla dakikada IP engellendi: HTTP 403 "denied by custom_acl"); engel gelince yeniden denenmez, kullanıcıya söylenir.
"""
import http.client, json, os, shutil, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lang import t as _

URL = 'https://alicdn-oss-prod.darkorbit.com/release/archive/DarkOrbit_Version1.1.116.zip'
TEMP = 'istemci_indiriliyor'      # proje kökünde; .gitignore'da
CHUNK = 1 << 20
CHUNK_SIZE = 64 << 20                     # bir bağlantının tek istekle okuduğu ardışık dosyalar (büyük dosya tek başına)
CONNECTIONS = 3                        # aynı anda açık bağlantı (tek bağlantıyla ≈5 MB/sn); 6 bağlantı CDN engeline takılıyordu
SKIP_AHEAD = 1 << 20                      # bu kadarlık ileri atlama yeni istek açmadan okunup geçilir
RETRIES = 8                          # kopan bağlantıda üst üste yeniden bağlanma
TIMEOUT = 30
PAY = 200 << 20                     # disk denetiminde fazladan yer
LT = float(1 << 30)


def cooldown(k):
    """k. yeniden bağlanmadan önce beklenen saniye (testler kısaltır)."""
    return min(30, 2 ** k)


class DownloadError(Exception):
    """Kullanıcıya gösterilen hata."""


class Cancelled(Exception):
    pass


def block(e):
    """CDN'in erişim engeli (403/429): yeniden denemek engeli uzatır."""
    if isinstance(e, HTTPError) and e.code in (403, 429):
        return DownloadError(_('İndirme sunucusu erişimi geçici olarak engelledi (HTTP %d). Birkaç dakika sonra sürdür: inen '
                               'dosyalar korunur.', e.code))
    return None


class HttpFile:
    """HTTP aralık istekleriyle okunan, konumlanabilir salt-okunur dosya (zipfile için). Sıralı okumada tek bağlantı sürer;
    bağlantı koparsa aynı yerden yeniden açılır. Arşiv sunucuda değişirse (ETag) durur."""

    def __init__(self, url, stop, on_bytes=None, opener=urlopen, size=None, etag=None):
        self.url, self.stop, self.on_bytes, self.opener = url, stop, on_bytes, opener
        self.pos, self.resp, self.rpos, self.etag = 0, None, None, etag
        if size is not None:                # aynı arşivin ikinci bağlantısı: boyut ve ETag ilkinden
            self.size = size
            return
        try:
            r = self._request(0, 0)
        except (OSError, http.client.HTTPException) as e:
            raise block(e) or DownloadError(_('İndirme sunucusuna bağlanılamadı (internet bağlantını denetle): %s', e))
        cr = r.headers.get('Content-Range') or ''
        r.close()
        try:
            self.size = int(cr.rsplit('/', 1)[1])
        except (IndexError, ValueError):
            raise DownloadError(_('İndirme sunucusu kaldığı yerden sürdürmeyi desteklemiyor.'))

    def _request(self, start, end=None):
        h = {'Range': 'bytes=%d-%s' % (start, '' if end is None else end), 'User-Agent': 'OpenOrbit'}
        if self.etag:
            h['If-Range'] = self.etag
        r = self.opener(Request(self.url, headers=h), timeout=TIMEOUT)
        if r.status != 206:
            r.close()
            raise DownloadError(_('İndirme sunucusu kaldığı yerden sürdürmeyi desteklemiyor ya da arşiv değişti; yeniden başlatın.'))
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
                if self.resp is not None and self.rpos < self.pos <= self.rpos + SKIP_AHEAD:     # kısa ileri atlama: okuyup geç
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
            except (OSError, http.client.HTTPException) as e:          # URLError, zaman aşımı, kopan bağlantı
                self._close()
                if block(e):
                    raise block(e)
                tries += 1
                if tries > RETRIES:
                    raise DownloadError(_('Bağlantı koptu: %s', e))
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
    """Bütün girdiler tek bir üst klasördeyse onun adı, değilse ''."""
    tops = {n.split('/', 1)[0] for n in names}
    return tops.pop() if len(tops) == 1 and all('/' in n or n.endswith('/') for n in names) else ''


def safe_path(base, rel):
    """Arşivdeki yolu klasörün içinde tut (../ ve mutlak yollar geçersiz)."""
    parts = [p for p in rel.replace('\\', '/').split('/') if p not in ('', '.')]
    if not parts or any(p == '..' or ':' in p for p in parts):
        raise DownloadError(_('Arşivde geçersiz yol: %s', rel))
    return os.path.join(base, *parts)


class Downloader:
    def __init__(self, root, check, log=print, on_done=None, url=URL, opener=urlopen):
        self.root, self.check, self.log, self.on_done, self.url, self.opener = root, check, log, on_done, url, opener
        self.stage = os.path.join(root, TEMP)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.d = self._blank('bos')
        self.samples = []
        self.connection = CONNECTIONS

    @staticmethod
    def _blank(state):
        return {'durum': state, 'calisiyor': False, 'alinan': 0, 'toplam': 0, 'unpacked_size': 0, 'dosya': '', 'done_files': 0,
                'file_count': 0, 'hiz': 0, 'time_left_sec': None, 'hata': None, 'hedef': None, 'baslangic': None, 'bitis': None}

    def state(self):
        with self.lock:
            d = json.loads(json.dumps(self.d))
        if d['toplam']:
            d['alinan'] = min(d['alinan'], d['toplam'])
        d['url'] = self.url
        d['partial'] = not d['calisiyor'] and os.path.isdir(self.stage)       # önceki indirmeden kalan dosyalar
        return d

    def running(self):
        with self.lock:
            return self.d['calisiyor']

    def start(self, fast=True):
        with self.lock:
            busy = self.d['calisiyor']
            if not busy:
                self.connection = CONNECTIONS if fast else 1
                self.stop.clear()
                self.d = dict(self._blank('hazirlaniyor'), calisiyor=True, baslangic=time.time())
                self.samples = []
        if not busy:
            threading.Thread(target=self._run, daemon=True).start()
        return self.state()

    def cancel(self):
        self.stop.set()
        return self.state()

    def discard(self):
        """Yarım kalan indirmenin geçici klasörünü sil (iş durmuşken; yalnız GECICI)."""
        if self.running():
            raise DownloadError(_('İndirme sürüyor: önce durdurun.'))
        if os.path.isdir(self.stage):
            shutil.rmtree(self.stage)
            self.log('yarım istemci indirmesi silindi: %s' % self.stage)
        with self.lock:
            self.d = self._blank('bos')
        return self.state()

    def _count(self, n):
        now = time.monotonic()
        with self.lock:
            self.d['alinan'] += n
            self.samples.append((now, self.d['alinan']))
            while len(self.samples) > 2 and now - self.samples[0][0] > 8:
                self.samples.pop(0)
            t0, b0 = self.samples[0]
            if now - t0 >= 1:
                self.d['hiz'] = int((self.d['alinan'] - b0) / (now - t0))
                left = max(0, self.d['toplam'] - self.d['alinan'])
                self.d['time_left_sec'] = int(left / self.d['hiz']) if self.d['hiz'] > 0 else None

    def _set(self, **kw):
        with self.lock:
            self.d.update(kw)

    def _target(self, name):
        """Son klasör: proje kökünde arşivdeki ad; o ad doluysa (başka bir klasör) "ad (2)" …"""
        p, k = os.path.join(self.root, name), 2
        while os.path.exists(p):
            p, k = os.path.join(self.root, '%s (%d)' % (name, k)), k + 1
        return p

    def _open(self, h, i, p):
        """Arşivdeki dosyayı (yerel başlığından) .part'a aç; zipfile'ın okuyucusu açar ve CRC'yi denetler."""
        h.seek(i.header_offset)
        fh = h.read(30)
        if fh[:4] != b'PK':
            raise zipfile.BadZipFile('yerel başlık yok: %s' % i.filename)
        h.read(int.from_bytes(fh[26:28], 'little') + int.from_bytes(fh[28:30], 'little'))   # ad ve ek alan
        os.makedirs(os.path.dirname(p), exist_ok=True)
        part = p + '.part'
        with zipfile.ZipExtFile(h, 'rb', i) as src, open(part, 'wb') as out:     # sonda CRC'yi denetler (BadZipFile)
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
                raise DownloadError(_('Diskte yer yetmiyor: %.1f GB gerekli, %.1f GB boş.', (need + PAY) / LT, free / LT))
            self._set(durum='indiriliyor', toplam=sum(i.compress_size for i, p in items), unpacked_size=sum(i.file_size for i, p in items),
                      alinan=sum(i.compress_size for i, p in items if p in done), file_count=len(items), done_files=len(done))
            self.log('istemci indiriliyor: %s (%d dosya, %d zaten var, %d bağlantı)' % (self.url, len(items), len(done), self.connection))
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
            f.close()                               # dizini okuyan bağlantı; dosyaları gruplar açar
            errors = []

            def open_chunk(g):
                h = HttpFile(self.url, self.stop, self._count, self.opener, size=f.size, etag=f.etag)
                try:
                    for i, p in g:
                        if self.stop.is_set():
                            raise Cancelled()
                        self._set(dosya=os.path.relpath(p, self.stage))
                        self._open(h, i, p)
                        with self.lock:
                            self.d['done_files'] += 1
                except BaseException as e:
                    errors.append(e)
                    self.stop.set()                 # öteki bağlantılar da dursun
                finally:
                    h.close()
            with ThreadPoolExecutor(self.connection) as pool:
                list(pool.map(open_chunk, groups))
            if errors:
                raise next((e for e in errors if not isinstance(e, Cancelled)), errors[0])
            self._set(durum='dogrulaniyor', dosya='')
            c = self.check(self.stage)
            if not c['valid']:
                raise DownloadError(_('İndirilen klasör bir DarkOrbit istemcisi değil: %s', ' '.join(c['issues'])))
            target = self._target(top or os.path.splitext(os.path.basename(self.url))[0])
            for k in range(10):                     # virüs tarayıcısı bir dosyayı tutuyorsa biraz bekle
                try:
                    os.rename(self.stage, target)
                    break
                except OSError:
                    if k == 9:
                        raise
                    time.sleep(1)
            self._set(durum='bitti', hedef=target, alinan=self.d['toplam'], time_left_sec=0)
            self.log('istemci indirildi: %s' % target)
            if self.on_done:
                self.on_done(target)
        except Cancelled:
            self._set(durum='durdu')
            self.log('istemci indirme durduruldu')
        except DownloadError as e:
            self._set(durum='hata', hata=str(e))
            self.log('istemci indirme hatası: %s' % e)
        except zipfile.BadZipFile as e:
            self._set(durum='hata', hata=_('Arşiv bozuk geldi (%s). Yeniden başlatın: yalnız eksik dosyalar iner.', e))
            self.log('istemci indirme: bozuk arşiv: %s' % e)
        except OSError as e:
            self._set(durum='hata', hata=_('Dosya yazılamadı: %s', e))
            self.log('istemci indirme: yazma hatası: %r' % e)
        except Exception as e:
            self._set(durum='hata', hata=repr(e))
            self.log('istemci indirme: beklenmeyen hata: %r' % e)
        finally:
            if f is not None:
                f.close()
            with self.lock:
                self.d['calisiyor'], self.d['bitis'] = False, time.time()
                self.d['hiz'] = 0
