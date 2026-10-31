"""Kayıt yuvaları (yönetim paneli): liste ve özet, yeni kayıt, etkin yuva, ad ve not, kopyalama, silme (çöp kutusuna, geri
alınabilir), dışa/içe aktarma, düzenleme ve yedekler.

Düzen (yollar.py): save/kayitlar/<kimlik>/{profil.json, kayit.json, web_ayarlari.json, duzenleme.json, yedek/}. Silinen yuva
save/silinenler/<kimlik>_<zaman>/'a taşınır. Yedekler yedek/<tür>_YYYYmmdd_HHMMSS.json:
  oto   panel Oyna'da ve oyun sürerken alır; en yeni `yedek_sayisi` kadarı kalır
  elle  oyuncunun aldığı; kendiliğinden silinmez
  once  geri yüklemeden / düzenlemeden önce alınan güvenlik yedeği; en yeni ONCE_SAYISI kalır
Notlar yedek/notlar.json'da. Profil oyun sunucusu açıkken değişmemeli (otomatik kayıt üstüne yazar): panel değiştiren işlemleri
yuva kullanımdayken engeller (in_use).
Yeni profil ayrı süreçte kurulur (profil_araci.py: tohum, pilot adı, firma, ana istasyon).
Karakter editörü (kayit_editoru.py, ayrı süreç) duzenleme.json taslağında çalışır: taslak ilk değişiklikte açılır, Kaydet güvenlik
yedeği alıp profile yazar, Vazgeç taslağı atar. Taslak açıldıktan sonra profil değiştiyse (oyun oynandı, yedek geri yüklendi) eski taslak
atılır.
"""
import json, os, re, shutil, subprocess, sys, threading, time, zipfile

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(PANEL_DIR)
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)
import yollar as YOL  # noqa: E402
from dil import t as _  # noqa: E402

FIRMALAR = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
ONCE_SAYISI = 5
TURLER = ('oto', 'elle', 'once')
TUR_ADLARI = {'oto': 'Otomatik', 'elle': 'Elle', 'once': 'Geri yükleme öncesi'}
_TR = str.maketrans('çğıöşüÇĞİÖŞÜâîû', 'cgiosuCGIOSUaiu')


def default_key_bindings():
    """Oyunun varsayılan tuş atamaları: giriş şablonunun tohumu (profil.py yeni profilde de bunu kullanır)."""
    p = YOL.sablon('giris.json')                 # kendi kaydın, yoksa paylaşılabilir kopya
    t = (_read_json(p).get('tohum') if p else None) or {}
    return list((t.get('UserKeyBindingsUpdate') or {}).get('changedKeyBindings', []))


class KayitHatasi(Exception):
    """Kullanıcıya gösterilecek hata (panelin dilinde ileti; dil.py)."""


def slugify(name):
    s = re.sub(r'[^a-z0-9]+', '_', name.translate(_TR).lower()).strip('_')
    return (s or 'kayit')[:32]


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
    for k in range(6):                         # oyun sunucusunun os.replace'i ve virüs tarayıcıları anlık kilitleyebilir
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if k == 5:
                raise
            time.sleep(0.1 * (k + 1))


def validate_profile(d):
    """Profil sözlüğü mü? (içe aktarma, geri yükleme)"""
    if not (isinstance(d, dict) and isinstance(d.get('pilot'), dict) and isinstance(d.get('gemi'), dict)
            and isinstance(d.get('konum'), dict) and 'mapId' in d['konum']):
        raise KayitHatasi(_('Bu dosya bir DarkOrbit profili değil (pilot, gemi ve konum bölümleri yok).'))
    return d


_LEVELS = None


def level_for(ep):
    global _LEVELS
    if _LEVELS is None:
        try:
            _LEVELS = _read_json(os.path.join(SERVER, 'data', 'seviyeler.json'))['seviyeler']
        except (OSError, ValueError, KeyError):
            _LEVELS = [[1, 0]]
    lv = 1
    for level, need in _LEVELS:
        if ep >= need:
            lv = level
    return lv


def _map_name(mid):
    try:
        import harita as H
        return H.name(mid)
    except Exception:
        return str(mid)


def level_bounds(level):
    """Seviyenin ve bir sonrakinin EP eşiği (ilerleme çubuğu; son seviyede sonraki None)."""
    level_for(0)
    need = dict((lv, ep) for lv, ep in _LEVELS)
    return need.get(level, 0), need.get(level + 1)


def profile_summary(d):
    """Profilden panelin gösterdiği özet."""
    pl, g, k = d.get('pilot') or {}, d.get('gemi') or {}, d.get('konum') or {}
    taban, sonraki = level_bounds(pl.get('level', 1))
    return {'gemi_gorunum': g.get('typeId'), 'seviye_taban': taban, 'seviye_sonraki': sonraki, 'dron_sayisi': len(d.get('dronlar') or []),
            'pet': (d.get('pet') or {}).get('ad'), 'premium': bool(pl.get('premium')),'pilot': pl.get('userName') or '?', 'firma': FIRMALAR.get(pl.get('factionId'), '?'), 'firma_id': pl.get('factionId'),
            'seviye': pl.get('level', 1), 'ep': pl.get('ep', 0), 'onur': pl.get('honourPoints', 0), 'kredi': pl.get('credits', 0),
            'uridyum': pl.get('uridium', 0), 'gemi': ship_name(g.get('typeId')), 'harita': _map_name(k.get('mapId', 0)),
            'oynama_sn': int(d.get('oynama_sn') or 0), 'olusturma': d.get('olusturma'),
            'can': g.get('hitPoints'), 'can_azami': g.get('hitMax'),
            'klan': pl.get('clanTag') or '', 'gemi_sayisi': len(d.get('gemiler') or {}) or 1}


class Kayitlar:
    def __init__(self, cfg, root=YOL.KAYITLAR, trash=YOL.SILINENLER, legacy=YOL.ESKI_PROFIL, python=None):
        self.cfg, self.root, self.trash, self.legacy = cfg, root, trash, legacy
        self.python = python or sys.executable
        self.lock = threading.RLock()
        self.in_use = lambda slot: False           # panel bağlar: yuvayı açık bir oyun sunucusu kullanıyor mu
        self._cache = {}                           # yol -> (mtime, boyut, özet)

    # ------------------------------------------------------------ yollar
    def dir(self, slot):
        if not slot or not re.fullmatch(r'[a-z0-9_]{1,40}', slot):
            raise KayitHatasi(_('Geçersiz kayıt kimliği.'))
        return os.path.join(self.root, slot)

    def profile(self, slot):
        return os.path.join(self.dir(slot), 'profil.json')

    def settings(self, slot):
        """Kaydın oyun ayarları (ayar.py; kayda özgü: etkin kayıt değişince ayarlar da). Yoksa eski ortak dosyadan
        (save/ayarlar.json) kopyalanır, o da yoksa boş (varsayılanlar)."""
        p = os.path.join(self.dir(slot), 'ayarlar.json')
        if not os.path.isfile(p) and os.path.isdir(self.dir(slot)):
            with self.lock:
                if not os.path.isfile(p):
                    shutil.copyfile(YOL.AYARLAR, p) if os.path.isfile(YOL.AYARLAR) else _write_json(p, {})
        return p

    def copy_settings(self, src, dst):
        """src kaydının oyun ayarları (etkinlik seçimleri dahil) dst kaydına."""
        if not self.exists(src) or not self.exists(dst):
            raise KayitHatasi(_('Kayıt bulunamadı.'))
        if src != dst:
            shutil.copyfile(self.settings(src), os.path.join(self.dir(dst), 'ayarlar.json'))

    def backup_dir(self, slot):
        return os.path.join(self.dir(slot), 'yedek')

    def exists(self, slot):
        try:
            return os.path.isfile(self.profile(slot))
        except KayitHatasi:
            return False

    def slots(self):
        if not os.path.isdir(self.root):
            return []
        return sorted(s for s in os.listdir(self.root) if re.fullmatch(r'[a-z0-9_]{1,40}', s) and self.exists(s))

    def meta(self, slot):
        try:
            d = _read_json(os.path.join(self.dir(slot), 'kayit.json'))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_meta(self, slot, **kw):
        with self.lock:
            m = self.meta(slot)
            m.update(kw)
            _write_json(os.path.join(self.dir(slot), 'kayit.json'), m)
            return m

    def new_id(self, name):
        base = slugify(name)
        sid, k = base, 2
        while os.path.exists(os.path.join(self.root, sid)):
            sid = '%s_%d' % (base[:28], k)
            k += 1
        return sid

    def guard(self, slot, what='Bu işlem'):
        if self.in_use(slot):
            raise KayitHatasi(_('%s için önce oyunu ve sunucuyu kapatın: kayıt şu an kullanımda (sunucu her 10 saniyede kaydediyor).',
                                _(what)))

    # ------------------------------------------------------------ etkin yuva
    def active(self):
        s = self.cfg.get('aktif_kayit')
        if s and self.exists(s):
            return s
        slots = self.slots()
        return slots[0] if slots else None

    def set_active(self, slot):
        if not self.exists(slot):
            raise KayitHatasi(_('Kayıt bulunamadı.'))
        self.cfg.update({'aktif_kayit': slot})
        return slot

    # ------------------------------------------------------------ eski düzenden taşıma
    def migrate(self):
        """save/profil.json (eski tek kayıt) -> 'ana' yuvası; web ayarları ve eski yedekler (profil_*.json -> oto_*.json) birlikte.
        -> taşınan yuvanın kimliği ya da None."""
        with self.lock:
            if not os.path.isfile(self.legacy):
                return None
            save = os.path.dirname(self.legacy)
            sid = self.new_id('ana')
            d = os.path.join(self.root, sid)
            os.makedirs(os.path.join(d, 'yedek'), exist_ok=True)
            pr = profile_summary(_read_json(self.legacy))
            shutil.copy2(self.legacy, os.path.join(d, 'yedek', 'once_%s.json' % time.strftime('%Y%m%d_%H%M%S')))    # güvenlik kopyası
            web = os.path.join(save, 'web_ayarlari.json')
            if os.path.isfile(web):
                shutil.move(web, os.path.join(d, 'web_ayarlari.json'))
            old_bk = os.path.join(save, 'yedek')
            if os.path.isdir(old_bk):
                for f in sorted(os.listdir(old_bk)):
                    m = re.fullmatch(r'profil_(\d{8}_\d{6})\.json', f)
                    if m:
                        shutil.move(os.path.join(old_bk, f), os.path.join(d, 'yedek', 'oto_%s.json' % m.group(1)))
                try:
                    os.rmdir(old_bk)
                except OSError:
                    pass
            _write_json(os.path.join(d, 'kayit.json'), {'ad': _('Ana kayıt (%s)', pr['pilot']), 'olusturma': pr['olusturma'] or
                                                        time.strftime('%Y-%m-%d %H:%M:%S'), 'not': 'Eski save/profil.json'})
            shutil.move(self.legacy, os.path.join(d, 'profil.json'))
            if not self.cfg.get('aktif_kayit') or not self.exists(self.cfg.get('aktif_kayit')):
                self.cfg.update({'aktif_kayit': sid})
            return sid

    # ------------------------------------------------------------ özetler
    def summary(self, slot):
        p = self.profile(slot)
        st = os.stat(p)
        c = self._cache.get(p)
        if not c or c[0] != st.st_mtime_ns:
            try:
                s = profile_summary(_read_json(p))
                s['bozuk'] = False
            except (OSError, ValueError):
                s = {'pilot': '?', 'bozuk': True}
            self._cache[p] = c = (st.st_mtime_ns, s)
        m = self.meta(slot)
        out = dict(c[1])
        out.update(id=slot, ad=m.get('ad') or slot, not_=m.get('not', ''), kayit_olusturma=m.get('olusturma'),
                   son_oynama=m.get('son_oynama'), son_kayit=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime)),
                   boyut=st.st_size, yedek_sayisi=len(self.backup_files(slot)), aktif=(slot == self.active()),
                   kullanimda=self.in_use(slot), dunya=m.get('dunya') or 'standart', taslak=self._draft_valid(slot))
        return out

    def list(self):
        out = []
        for s in self.slots():
            try:
                out.append(self.summary(s))
            except OSError:
                continue
        out.sort(key=lambda x: (not x['aktif'], -(time.mktime(time.strptime(x['son_oynama'], '%Y-%m-%d %H:%M:%S'))
                                                    if x.get('son_oynama') else 0), x['ad'].lower()))
        return out

    # ------------------------------------------------------------ yeni, ad, kopya, silme
    def run_tool(self, *args, tool='profil_araci.py'):
        """profil_araci.py'yi (ya da kayit_editoru.py'yi) ayrı süreçte çalıştır -> çıktının JSON'u."""
        kw = {'creationflags': 0x08000000} if os.name == 'nt' else {}         # CREATE_NO_WINDOW
        r = subprocess.run([self.python, '-I', os.path.join(PANEL_DIR, tool)] + list(args), capture_output=True,
                           text=True, encoding='utf8', timeout=120, **kw)
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise KayitHatasi(_('Profil aracı çalışmadı: %s', (r.stderr or r.stdout).strip()[-400:] or _('çıktı yok')))
        if not out.get('ok'):
            if out.get('kalip'):
                raise KayitHatasi(_(out['kalip'], *out.get('arg') or ()))
            raise KayitHatasi(out.get('hata') or _('Profil aracı başarısız.'))
        return out

    def create(self, ad, pilot, firma, kredi=None, uridyum=None, seviye=None, onur=None, lazer=None, roket=None, ilerlemeli=False,
               ayar_kaynagi=None, kampanya=False):
        """Yeni kayıt (profil_araci.py yeni). Başlangıç değerleri isteğe bağlı (boş: tohumdaki): kredi, uridyum, seviye (1-50),
        onur, LCB-10 lazer cephanesi ve R-310 roketi adedi; sınırlara kırpılır. ilerlemeli: Season Pass ilk sezondan sırayla. kampanya: başlangıç
        kampanyası ("Level N" görevleri, gorev.KAMPANYA_SN boyunca)."""
        ad, pilot = (ad or '').strip(), (pilot or '').strip()
        if not re.fullmatch(r'[\w\-\.\[\]\(\) ]{3,20}', pilot, re.UNICODE):
            raise KayitHatasi(_('Pilot adı 3-20 karakter olmalı (harf, rakam, boşluk, - _ . [ ] ( ) ).'))
        if not ad:
            raise KayitHatasi(_('Kayda bir ad verin.'))
        firma = int(firma)
        if firma not in FIRMALAR:
            raise KayitHatasi(_('Firma seçin (MMO, EIC ya da VRU).'))
        try:
            kredi, uridyum, seviye, onur, lazer, roket = [None if v in (None, '') else int(float(v))
                                                          for v in (kredi, uridyum, seviye, onur, lazer, roket)]
        except (TypeError, ValueError, OverflowError):
            raise KayitHatasi(_('Başlangıç değerleri sayı olmalı.'))
        with self.lock:
            sid = self.new_id(ad)
            d = os.path.join(self.root, sid)
            os.makedirs(os.path.join(d, 'yedek'), exist_ok=True)
            args = ['yeni', os.path.join(d, 'profil.json'), pilot, str(firma)]
            for key, v, lo, hi in (('kredi', kredi, 0, 10 ** 12), ('uridyum', uridyum, 0, 10 ** 12), ('seviye', seviye, 1, 50),
                                   ('onur', onur, 0, 10 ** 12), ('lazer', lazer, 0, 10 ** 9), ('roket', roket, 0, 10 ** 9)):
                if v not in (None, ''):
                    args += ['--%s=%d' % (key, min(hi, max(lo, v)))]
            if ilerlemeli:
                args += ['--ilerlemeli=1']
            if kampanya:
                args += ['--kampanya=1']
            try:
                self.run_tool(*args)
            except Exception:
                shutil.rmtree(d, ignore_errors=True)
                raise
            _write_json(os.path.join(d, 'kayit.json'), {'ad': ad, 'olusturma': time.strftime('%Y-%m-%d %H:%M:%S'), 'not': ''})
            if ayar_kaynagi and self.exists(ayar_kaynagi):        # ayarlar başka bir kayıttan (yoksa eski ortak dosyadan)
                self.copy_settings(ayar_kaynagi, sid)
            return sid

    def rename(self, slot, ad):
        ad = (ad or '').strip()
        if not ad:
            raise KayitHatasi(_('Ad boş olamaz.'))
        self.dir(slot)
        return self.set_meta(slot, ad=ad[:60])

    def set_note(self, slot, text):
        return self.set_meta(slot, **{'not': (text or '')[:500]})

    def duplicate(self, slot, ad=None):
        src = self.dir(slot)
        with self.lock:
            ad = (ad or '').strip() or _('%s (kopya)', self.meta(slot).get('ad') or slot)
            sid = self.new_id(ad)
            dst = os.path.join(self.root, sid)
            os.makedirs(os.path.join(dst, 'yedek'), exist_ok=True)
            _copy_atomic(os.path.join(src, 'profil.json'), os.path.join(dst, 'profil.json'))
            if os.path.isfile(os.path.join(src, 'web_ayarlari.json')):
                shutil.copy2(os.path.join(src, 'web_ayarlari.json'), os.path.join(dst, 'web_ayarlari.json'))
            meta = {'ad': ad, 'olusturma': time.strftime('%Y-%m-%d %H:%M:%S'), 'not': _('Kopyalandı: %s', self.meta(slot).get('ad') or slot)}
            if self.meta(slot).get('dunya'):              # varsayılan dünya (Dünya Editörü) kopyaya geçer
                meta['dunya'] = self.meta(slot)['dunya']
            _write_json(os.path.join(dst, 'kayit.json'), meta)
            return sid

    def delete(self, slot):
        """Çöp kutusuna taşı (geri alınabilir)."""
        self.guard(slot, 'Silmek')
        with self.lock:
            src = self.dir(slot)
            os.makedirs(self.trash, exist_ok=True)
            dst = os.path.join(self.trash, '%s_%s' % (slot, time.strftime('%Y%m%d_%H%M%S')))
            shutil.move(src, dst)
            if self.cfg.get('aktif_kayit') == slot:
                rest = self.slots()
                self.cfg.update({'aktif_kayit': rest[0] if rest else None})
            return os.path.basename(dst)

    def deleted(self):
        if not os.path.isdir(self.trash):
            return []
        out = []
        for name in sorted(os.listdir(self.trash), reverse=True):
            d = os.path.join(self.trash, name)
            m = re.fullmatch(r'([a-z0-9_]+)_(\d{8})_(\d{6})', name)
            if not (m and os.path.isfile(os.path.join(d, 'profil.json'))):
                continue
            try:
                meta = _read_json(os.path.join(d, 'kayit.json'))
            except (OSError, ValueError):
                meta = {}
            try:
                pr = profile_summary(_read_json(os.path.join(d, 'profil.json')))
            except (OSError, ValueError):
                pr = {'pilot': '?'}
            t = time.strptime(m.group(2) + m.group(3), '%Y%m%d%H%M%S')
            out.append({'dosya': name, 'ad': meta.get('ad') or m.group(1), 'pilot': pr.get('pilot'), 'seviye': pr.get('seviye'),
                        'silinme': time.strftime('%Y-%m-%d %H:%M:%S', t)})
        return out

    def _trash_dir(self, name):
        if not re.fullmatch(r'[a-z0-9_]+_\d{8}_\d{6}', name or ''):
            raise KayitHatasi(_('Geçersiz çöp kutusu kaydı.'))
        d = os.path.join(self.trash, name)
        if not os.path.isdir(d):
            raise KayitHatasi(_('Silinen kayıt bulunamadı.'))
        return d

    def undelete(self, name):
        with self.lock:
            src = self._trash_dir(name)
            sid = self.new_id(re.sub(r'_\d{8}_\d{6}$', '', name))
            shutil.move(src, os.path.join(self.root, sid))
            return sid

    def purge(self, name=None):
        """Çöp kutusundan kalıcı sil (name verilmezse hepsi) -> silinen sayısı."""
        with self.lock:
            names = [name] if name else [x['dosya'] for x in self.deleted()]
            for n in names:
                shutil.rmtree(self._trash_dir(n))
            return len(names)

    # ------------------------------------------------------------ dışa / içe aktarma
    def export(self, slot, dest, with_backups=True):
        """Yuvayı zip olarak dışa aktar (profil, kayıt bilgisi, web ayarları, isteğe bağlı yedekler)."""
        src = self.dir(slot)
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                if rel.split(os.sep)[0] == 'yedek' and not with_backups:
                    continue
                for f in files:
                    if f.endswith('.tmp') or (rel == '.' and f == 'duzenleme.json'):     # editörün kaydedilmemiş taslağı
                        continue
                    z.write(os.path.join(root, f), os.path.join(slot, rel, f) if rel != '.' else os.path.join(slot, f))
        return dest

    def import_file(self, path, ad=None):
        """.zip (panelin dışa aktardığı) ya da .json (profil) -> yeni yuvanın kimliği."""
        if not os.path.isfile(path):
            raise KayitHatasi(_('Dosya bulunamadı.'))
        with self.lock:
            if path.lower().endswith('.zip'):
                with zipfile.ZipFile(path) as z:
                    names = [n for n in z.namelist() if not n.endswith('/')]
                    prof = [n for n in names if n.replace('\\', '/').split('/')[-1] == 'profil.json'
                            and n.replace('\\', '/').count('/') <= 1]
                    if not prof:
                        raise KayitHatasi(_('Zip içinde profil.json yok.'))
                    base = prof[0].replace('\\', '/').rsplit('/', 1)[0] + '/' if '/' in prof[0].replace('\\', '/') else ''
                    d = validate_profile(json.loads(z.read(prof[0]).decode('utf8')))
                    meta = {}
                    if base + 'kayit.json' in names:
                        try:
                            meta = json.loads(z.read(base + 'kayit.json').decode('utf8'))
                        except ValueError:
                            meta = {}
                    ad = (ad or meta.get('ad') or profile_summary(d)['pilot']).strip()
                    sid = self.new_id(ad)
                    dst = os.path.join(self.root, sid)
                    os.makedirs(os.path.join(dst, 'yedek'), exist_ok=True)
                    for n in names:
                        nn = n.replace('\\', '/')
                        if not nn.startswith(base):
                            continue
                        rel = nn[len(base):]
                        ok = rel in ('profil.json', 'web_ayarlari.json') or re.fullmatch(r'yedek/(oto|elle|once)_\d{8}_\d{6}(_\d+)?\.json',
                                                                                        rel) or rel == 'yedek/notlar.json'
                        if ok:
                            out = os.path.join(dst, *rel.split('/'))
                            with open(out, 'wb') as fh:
                                fh.write(z.read(n))
            else:
                try:
                    d = validate_profile(_read_json(path))
                except ValueError:
                    raise KayitHatasi(_('Dosya okunamadı (geçerli JSON değil).'))
                ad = (ad or _('%s (içe aktarıldı)', profile_summary(d)['pilot'])).strip()
                sid = self.new_id(ad)
                dst = os.path.join(self.root, sid)
                os.makedirs(os.path.join(dst, 'yedek'), exist_ok=True)
                shutil.copy2(path, os.path.join(dst, 'profil.json'))
            _write_json(os.path.join(dst, 'kayit.json'), {'ad': ad[:60], 'olusturma': time.strftime('%Y-%m-%d %H:%M:%S'),
                                                          'not': _('İçe aktarıldı: %s', os.path.basename(path))})
            return sid

    # ------------------------------------------------------------ düzenleme
    def edit(self, slot, values):
        """Pilot adı, kredi, uridyum, onur, EP (seviye EP'den), gemiyi onar, ana üsse taşı, tuş atamalarını varsayılana döndür;
        eşya/gemi ver (ver: [[lootId, adet]]), durum sıfırla (sifirla: bölümler; profil_araci.py). Önce 'once' yedeği alınır."""
        self.guard(slot, 'Düzenlemek')
        with self.lock:
            p = self.profile(slot)
            d = validate_profile(_read_json(p))
            pl, g = d['pilot'], d['gemi']
            changed = []
            if 'pilot' in values:
                name = str(values['pilot']).strip()
                if not re.fullmatch(r'[\w\-\.\[\]\(\) ]{3,20}', name, re.UNICODE):
                    raise KayitHatasi(_('Pilot adı 3-20 karakter olmalı.'))
                if name != pl.get('userName'):
                    pl['userName'] = name
                    changed.append(_('pilot adı'))
            for key, field, lo, hi in (('kredi', 'credits', 0, 10 ** 12), ('uridyum', 'uridium', 0, 10 ** 12),
                                       ('onur', 'honourPoints', -10 ** 12, 10 ** 12), ('ep', 'ep', 0, 2 ** 62)):
                if key in values and values[key] not in (None, ''):
                    v = min(hi, max(lo, int(values[key])))
                    if v != pl.get(field):
                        pl[field] = v
                        changed.append(_(key))
                        if key == 'ep':
                            pl['level'] = level_for(v)
            if values.get('tuslar'):
                # oyunun Ayarlar > Reset'i sunucuya ulaşmıyor (istemci bağlantıyı kapatmadan ResetSettingsRequest gönderemiyor;
                # CANLI_TEST N12): tuşlar tohumdakine (kayıttaki varsayılan dizilim) döner, sonraki girişte istemciye gider
                d['tus_atamalari'] = default_key_bindings()
                changed.append(_('tuş atamaları varsayılana döndü'))
            if values.get('onar'):
                g['hitPoints'], g['shield'] = g.get('hitMax', g.get('hitPoints', 1)), g.get('shieldMax', g.get('shield', 0))
                changed.append(_('gemi onarıldı'))
            give = [[str(l), int(n or 1)] for l, n in (values.get('ver') or []) if str(l).strip()]
            resets = [r for r in (values.get('sifirla') or []) if r]
            if not changed and not values.get('ana_us') and not give and not resets:
                return []
            safety = self.backup(slot, 'once', _('Düzenlemeden önce'))
            try:
                if changed:
                    _write_json(p, d)
                if values.get('ana_us'):
                    self.run_tool('ana_us', p)
                    changed.append(_('ana üsse taşındı'))
                if give:
                    r = self.run_tool('ver', p, json.dumps(give))
                    changed.append(_('verildi: %s', ', '.join('%s x%d' % (l, n) for l, n in r['verilen'])))
                if resets:
                    r = self.run_tool('sifirla', p, ','.join(resets))
                    changed.append(_('sıfırlandı: %s', ', '.join(r['sifirlanan'])))
            except Exception as e:                        # yarım düzenleme kalmasın: kayıt düzenlemeden önceki hâline döner
                _copy_atomic(os.path.join(self.backup_dir(slot), safety), p)
                raise KayitHatasi(_('Düzenleme uygulanamadı, kayıt değişmedi: %s', e))
            return changed

    def loot_list(self):
        """Kayıt düzenleyicinin eşya listesi (profil_araci.py liste; ilk istekten sonra bellekte)."""
        if getattr(self, '_loots', None) is None:
            self._loots = self.run_tool('liste')['esyalar']
        return self._loots

    # ------------------------------------------------------------ karakter editörü (taslak)
    def draft(self, slot):
        return os.path.join(self.dir(slot), 'duzenleme.json')

    def _draft_valid(self, slot):
        """Taslak var ve profil o açıldığından beri değişmedi mi."""
        try:
            return os.path.isfile(self.draft(slot)) and self.meta(slot).get('duzenleme_taban') == os.stat(self.profile(slot)).st_mtime_ns
        except OSError:
            return False

    def _ensure_draft(self, slot):
        """Geçerli taslak yoksa profilin kopyası."""
        with self.lock:
            if self._draft_valid(slot):
                return
            validate_profile(_read_json(self.profile(slot)))
            _copy_atomic(self.profile(slot), self.draft(slot))
            self.set_meta(slot, duzenleme_taban=os.stat(self.profile(slot)).st_mtime_ns)

    def editor_open(self, slot):
        """Editörün görünümü: taslak varsa taslak (asıl kayda göre farkıyla), yoksa profil. Kayıt oyundaysa profil salt okunur
        gösterilir (sunucu her 10 saniyede üstüne yazar)."""
        if not self.exists(slot):
            raise KayitHatasi(_('Kayıt bulunamadı.'))
        if self.in_use(slot):
            return dict(self.run_tool('oku', self.profile(slot), tool='kayit_editoru.py'), salt_okunur=True, atildi=False)
        with self.lock:
            stale = os.path.isfile(self.draft(slot)) and not self._draft_valid(slot)
            if stale:
                self.editor_discard(slot)
            if self._draft_valid(slot):
                v = self.run_tool('oku', self.draft(slot), self.profile(slot), tool='kayit_editoru.py')
            else:
                v = self.run_tool('oku', self.profile(slot), tool='kayit_editoru.py')
        return dict(v, salt_okunur=False, atildi=stale)

    def editor_apply(self, slot, ops):
        """İşlemleri taslağa uygula (kayit_editoru.ISLEMLER) -> yeni görünüm."""
        self.guard(slot, 'Düzenlemek')
        if not isinstance(ops, list) or not ops:
            raise KayitHatasi(_('Değişiklik yok.'))
        with self.lock:
            self._ensure_draft(slot)
            v = self.run_tool('uygula', self.draft(slot), json.dumps(ops), self.profile(slot), tool='kayit_editoru.py')
            return dict(v, salt_okunur=False, atildi=False)

    def editor_commit(self, slot):
        """Taslağı kayda yaz: önce 'once' yedeği -> yedeğin adı."""
        self.guard(slot, 'Düzenlemek')
        with self.lock:
            if not self._draft_valid(slot):
                raise KayitHatasi(_('Kaydedilecek değişiklik yok.'))
            validate_profile(_read_json(self.draft(slot)))
            safety = self.backup(slot, 'once', _('Karakter editöründen önce'))
            _copy_atomic(self.draft(slot), self.profile(slot))
            self.editor_discard(slot)
            return safety

    def editor_discard(self, slot):
        with self.lock:
            if os.path.isfile(self.draft(slot)):
                os.remove(self.draft(slot))
            m = self.meta(slot)
            if 'duzenleme_taban' in m:
                del m['duzenleme_taban']
                _write_json(os.path.join(self.dir(slot), 'kayit.json'), m)

    def editor_catalog(self):
        """Editörün eşya kataloğu (kayit_editoru.py katalog; ilk istekten sonra bellekte)."""
        if getattr(self, '_katalog', None) is None:
            self._katalog = self.run_tool('katalog', tool='kayit_editoru.py')
        return {'esyalar': self._katalog['esyalar'], 'kategoriler': self._katalog['kategoriler']}

    def item_info(self):
        """Eşya ipucunun değerleri (kayit_editoru.py bilgi; ilk istekten sonra bellekte): panelin Hangar, Mağaza ve editör sayfaları."""
        if getattr(self, '_bilgi', None) is None:
            self._bilgi = self.run_tool('bilgi', tool='kayit_editoru.py')['esyalar']
        return self._bilgi

    # ------------------------------------------------------------ yedekler
    def backup_files(self, slot):
        bd = self.backup_dir(slot)
        if not os.path.isdir(bd):
            return []
        return sorted((f for f in os.listdir(bd) if re.fullmatch(r'(oto|elle|once)_\d{8}_\d{6}(_\d+)?\.json', f)),
                      key=lambda f: f.split('_', 1)[1], reverse=True)

    def notes(self, slot):
        try:
            d = _read_json(os.path.join(self.backup_dir(slot), 'notlar.json'))
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
                    s = {'pilot': '?', 'bozuk': True}
                self._cache[p] = c = (st.st_mtime_ns, s)
            tur, stamp = f.split('_', 1)
            t = time.strptime(stamp[:15], '%Y%m%d_%H%M%S')
            out.append(dict(c[1], dosya=f, tur=tur, tur_ad=_(TUR_ADLARI[tur]), zaman=time.strftime('%Y-%m-%d %H:%M:%S', t),
                            boyut=st.st_size, not_=notes.get(f, '')))
        return out

    def backup(self, slot, tur='elle', note='', keep=None):
        """Profilin yedeği -> dosya adı. oto/once türleri döndürülür (eskiler silinir)."""
        if tur not in TURLER:
            raise KayitHatasi(_('Geçersiz yedek türü.'))
        with self.lock:
            src = self.profile(slot)
            if not os.path.isfile(src):
                raise KayitHatasi(_('Kayıt bulunamadı.'))
            bd = self.backup_dir(slot)
            os.makedirs(bd, exist_ok=True)
            base = '%s_%s' % (tur, time.strftime('%Y%m%d_%H%M%S'))
            name, k = base + '.json', 2
            while os.path.exists(os.path.join(bd, name)):
                name = '%s_%d.json' % (base, k)
                k += 1
            for attempt in range(5):                      # sunucu o an yazıyorsa (os.replace) bir sonraki denemede
                try:
                    validate_profile(_read_json(src))
                    shutil.copy2(src, os.path.join(bd, name))
                    break
                except (OSError, ValueError):
                    if attempt == 4:
                        raise KayitHatasi(_('Profil okunamadı, yedek alınamadı.'))
                    time.sleep(0.2)
            if note:
                n = self.notes(slot)
                n[name] = note[:200]
                _write_json(os.path.join(bd, 'notlar.json'), n)
            if tur == 'oto':
                self.rotate(slot, 'oto', keep or self.cfg.get('yedek_sayisi'))
            elif tur == 'once':
                self.rotate(slot, 'once', ONCE_SAYISI)
            return name

    def rotate(self, slot, tur, keep):
        files = [f for f in self.backup_files(slot) if f.startswith(tur + '_')]
        for f in files[keep:]:
            self._remove_backup(slot, f)
        return files[keep:]

    def _backup_path(self, slot, name):
        if not re.fullmatch(r'(oto|elle|once)_\d{8}_\d{6}(_\d+)?\.json', name or ''):
            raise KayitHatasi(_('Geçersiz yedek adı.'))
        p = os.path.join(self.backup_dir(slot), name)
        if not os.path.isfile(p):
            raise KayitHatasi(_('Yedek bulunamadı.'))
        return p

    def _remove_backup(self, slot, name):
        os.remove(self._backup_path(slot, name))
        n = self.notes(slot)
        if name in n:
            del n[name]
            _write_json(os.path.join(self.backup_dir(slot), 'notlar.json'), n)

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
            _write_json(os.path.join(self.backup_dir(slot), 'notlar.json'), n)

    def restore(self, slot, name):
        """Yedeği geri yükle: önce şimdiki profilin 'once' yedeği -> o yedeğin adı."""
        self.guard(slot, 'Geri yüklemek')
        with self.lock:
            p = self._backup_path(slot, name)
            validate_profile(_read_json(p))
            kopya = p + '.geri'                       # en eski 'once' yedeği geri yüklenirken güvenlik yedeğinin döndürmesi onu siliyordu
            shutil.copy2(p, kopya)
            try:
                safety = self.backup(slot, 'once', _('Geri yükleme öncesi (%s)', name))
                _copy_atomic(kopya, self.profile(slot))
            finally:
                os.remove(kopya)
            return safety

    def backup_as_new(self, slot, name, ad=None):
        with self.lock:
            p = self._backup_path(slot, name)
            d = validate_profile(_read_json(p))
            ad = (ad or '').strip() or _('%s (%s yedeği)', self.meta(slot).get('ad') or slot, name.split('_', 1)[1][:8])
            sid = self.new_id(ad)
            dst = os.path.join(self.root, sid)
            os.makedirs(os.path.join(dst, 'yedek'), exist_ok=True)
            shutil.copy2(p, os.path.join(dst, 'profil.json'))
            web = os.path.join(self.dir(slot), 'web_ayarlari.json')
            if os.path.isfile(web):
                shutil.copy2(web, os.path.join(dst, 'web_ayarlari.json'))
            _write_json(os.path.join(dst, 'kayit.json'), {'ad': ad[:60], 'olusturma': time.strftime('%Y-%m-%d %H:%M:%S'),
                                                          'not': _('Yedekten: %s / %s (%s)', self.meta(slot).get('ad') or slot, name,
                                                                                               profile_summary(d)['pilot'])})
            return sid
