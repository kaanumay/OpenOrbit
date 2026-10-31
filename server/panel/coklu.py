"""Çoklu istemci (panel): OYNA'dan sonra bu bilgisayardaki öteki kayıtlarla ek oyun istemcileri.

Oyun sunucusu çok oturumlu kipte açılır (panel ayarı coklu_istemci açık ve en az iki kayıt varsa; arkadaş sunucusunda zaten öyle).
Ek istemcinin kaydı sunucuya POST /yerel/ekle ile eklenir (server/cok_oyunculu.py: sunucu yuvanın profil.json'una doğrudan yazar;
kimliği başka bir oyuncununkiyle aynıysa bellekte geçici kimlik), istemci http://127.0.0.1:8090/?oturum=<anahtar>#darkorbit:// ile
açılır (web.py anahtarı sunucuya sorar). İstemci kapanınca POST /yerel/cikar: son hâl yazılır, yuva serbest kalır. Ek istemciler
pencere kipinde açılır, pencere başlığı pilotun adı; günlükleri logs/client_<kayıt>.log. Ana kayıt, açık bir kayıt, aynı pilot adı
ve sınırın üstü reddedilir; ek istemci açıkken sunucuyu yeniden başlatan işler panelde engellenir (panel.py).
Plan ve önceden düşünülen sorunlar: belgeler/COKLU_ISTEMCI.md.
"""
import json, os, threading, time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from dil import t as _
import istemci as IST
import surecler as SR

OYUN = 'http://127.0.0.1:8081'
OPENER = build_opener(ProxyHandler({}))       # yerel sunucuya sistemin vekil sunucusu üzerinden gidilmesin
ERKEN_SN = 15                                  # bundan önce kapanan istemci: erken kapandı (kartta uyarı)


class CokluHatasi(Exception):
    """Kullanıcıya gösterilen hata."""


class Coklu:
    def __init__(self, cfg, kay, yon, anahtar, logs, log=print):
        """anahtar: () -> oyun sunucusunun yönetim anahtarı (arkadas.Arkadas.anahtar; DO_COK_OYUNCULU)."""
        self.cfg, self.kay, self.yon, self.anahtar, self.logs, self.log = cfg, kay, yon, anahtar, logs, log
        self.lock = threading.RLock()
        self.acik = {}                 # kayıt -> {'proc', 'oturum', 'uid', 'basla', 'pilot', 'gunluk'} ('proc' None: açılıyor)
        self.son = {}                  # kayıt -> son kapanış {'sure_sn', 'erken', 'kod', 'zaman', 'bitis'}
        self.son_yedek = {}            # kayıt -> son aralıklı yedek
        self.on_exit = None            # panel bağlar: () -> None (bir ek istemci kapandı)

    # ------------------------------------------------------------ oyun sunucusu
    def istek(self, path, body):
        data = json.dumps(dict(body, anahtar=self.anahtar())).encode('utf8')
        req = Request(OYUN + path, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with OPENER.open(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode('utf8') or '{}')
        except HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode('utf8') or '{}')
            except ValueError:
                return e.code, {}
        except (URLError, OSError, ValueError) as e:
            raise CokluHatasi(_('Oyun sunucusuna ulaşılamadı (%s).', getattr(e, 'reason', e)))

    # ------------------------------------------------------------ durum
    def canli(self):
        """Açık, açılmakta ya da kapanmakta olan ek istemcilerin kayıtları (kapanan istemcinin yuvası sunucuda bırakılınca çıkar:
        hemen yeniden açılan istemci sunucudaki eski oturuma bağlanıp sonra onunla birlikte bırakılmasın)."""
        with self.lock:
            return list(self.acik)

    def kullanimda(self, slot):
        return slot in self.canli()

    def pids(self):
        with self.lock:
            return {e['proc'].pid for e in self.acik.values() if e['proc'] is not None}

    def durum(self, canli=None):
        """Panelin listesi: ek istemciler (sunucunun canli_durum.json'undaki 'yereller'le: bağlı mı, harita, seviye)."""
        sv = {y.get('kayit'): y for y in ((canli or {}).get('yereller') or [])}
        now = time.time()
        with self.lock:
            out = []
            for s, e in self.acik.items():
                y = sv.get(s) or {}
                out.append({'kayit': s, 'pilot': e['pilot'], 'pid': e['proc'].pid if e['proc'] else None,
                            'durum': 'aciliyor' if e['proc'] is None else 'acik' if e['proc'].poll() is None else 'kapaniyor',
                            'sure_sn': int(now - e['basla']),
                            'bagli': bool(y.get('bagli')), 'harita': y.get('harita'), 'seviye': y.get('seviye'), 'uid': e['uid']})
            return {'istemciler': out, 'son': dict(self.son)}

    # ------------------------------------------------------------ açma ve kapatma
    def ac(self, slot, folder, ana_slot):
        """Ek istemciyi aç (sunucu çok oturumlu açık olmalı: panel denetler). -> durum."""
        if slot == ana_slot:
            raise CokluHatasi(_('Bu kayıt ana istemcide açık: ek istemcide başka bir kayıt seç.'))
        if not self.kay.exists(slot):
            raise CokluHatasi(_('Kayıt bulunamadı.'))
        c = IST.check(folder)
        if not c['gecerli']:
            raise CokluHatasi(_('İstemci klasörü geçersiz: %s', ' '.join(c['sorunlar'])))
        with self.lock:
            if slot in self.canli():
                raise CokluHatasi(_('Bu kayıt zaten bir ek istemcide açık.'))
            n = self.cfg.get('coklu_en_cok')
            if len(self.canli()) >= n:
                raise CokluHatasi(_('En çok %d ek istemci açılabilir (İstemci > Çoklu istemci).', n))
            self.acik[slot] = {'proc': None, 'oturum': None, 'uid': None, 'basla': time.time(), 'pilot': '', 'gunluk': None}
        out = None
        try:
            summary = self.kay.summary(slot)
            if summary.get('bozuk'):
                raise CokluHatasi(_('Kayıt okunamıyor (bozuk): Kayıtlar > Yedekler\'den geri yükle.'))
            if self.cfg.get('yedek_acilista'):
                self.kay.backup(slot, 'oto', _('Ek istemci (açılış)'))
            self.son_yedek[slot] = time.time()
            code, out = self.istek('/yerel/ekle', {'kayit': slot, 'yol': self.kay.profile(slot)})
            if code != 200:
                raise CokluHatasi(out.get('mesaj') or _('Oyun sunucusu kaydı almadı (HTTP %s).', code))
            gunluk = os.path.join(self.logs, 'client_%s.log' % slot)
            import baslat
            baslat.rotate_logs(self.logs, names=(os.path.basename(gunluk),))
            cmd, env = IST.komut(self.cfg, folder, gunluk, oturum=out['oturum'], pencere=True)
            proc = SR.istemci_ac(folder, cmd, env, self.logs)
        except Exception:
            with self.lock:
                self.acik.pop(slot, None)
            if out and out.get('oturum'):            # sunucuya kaydolduysa bırakılsın (yoksa kayıt düzenlenebilir sanılıyordu)
                try:
                    self.istek('/yerel/cikar', {'oturum': out['oturum']})
                except Exception:
                    pass
            raise
        pilot = summary.get('pilot') or slot
        with self.lock:
            self.acik[slot].update(proc=proc, oturum=out['oturum'], uid=out['uid'], basla=time.time(), pilot=pilot, gunluk=gunluk)
        m = self.kay.meta(slot)
        self.kay.set_meta(slot, son_oynama=time.strftime('%Y-%m-%d %H:%M:%S'), oynama_sayisi=int(m.get('oynama_sayisi') or 0) + 1)
        SR.pencere_basligi(proc.pid, 'DarkOrbit — %s' % pilot)
        self.log('ek istemci açıldı: %s (%s), süreç %d, sunucudaki kimlik %s%s' % (slot, pilot, proc.pid, out['uid'],
                                                                               ' (sürüyor)' if out.get('devam') else ''))
        threading.Thread(target=self._izle, args=(slot, proc), daemon=True).start()
        return self.durum()

    def _izle(self, slot, proc):
        code = proc.wait()
        with self.lock:
            e = self.acik.get(slot)
        dur = time.time() - (e['basla'] if e else time.time())
        if e and e['oturum'] and self.yon.running():
            try:
                c, out = self.istek('/yerel/cikar', {'oturum': e['oturum']})
                if c not in (200, 404):
                    self.log('ek istemcinin kaydı bırakılamadı (%s): %s' % (c, out))
            except CokluHatasi as err:
                self.log('ek istemcinin kaydı bırakılamadı: %s' % err)
        with self.lock:
            if self.acik.get(slot, {}).get('proc') is proc:
                self.acik.pop(slot, None)
            self.son[slot] = {'sure_sn': int(dur), 'erken': dur < ERKEN_SN and not (e or {}).get('kapatildi'), 'kod': code,
                              'zaman': time.strftime('%H:%M:%S'), 'bitis': time.time()}      # panelden kapatılan erken sayılmaz
        self.log('ek istemci kapandı: %s (%d sn, kod %s)' % (slot, dur, code))
        if self.on_exit:
            try:
                self.on_exit()
            except Exception as err:                   # noqa: BLE001
                self.log('ek istemci kapanış işlemi hatası: %r' % err)

    def kapat(self, slot):
        with self.lock:
            e = self.acik.get(slot)
        if not e or e['proc'] is None:
            raise CokluHatasi(_('Bu kayıtla açık bir ek istemci yok.'))
        if e['proc'].poll() is None:
            e['kapatildi'] = True
            SR.istemci_kapat(e['proc'])

    def hepsini_kapat(self, bekle=0.0):
        """Bütün ek istemcileri kapat; bekle: kapanışları (sunucuya son kayıt) en çok bu kadar beklenir."""
        with self.lock:
            acik = [e for e in self.acik.values() if e['proc'] is not None and e['proc'].poll() is None]
        for e in acik:
            e['kapatildi'] = True
            SR.istemci_kapat(e['proc'])
        end = time.time() + bekle
        while self.canli() and time.time() < end:
            time.sleep(0.1)

    def yedekle(self, aralik_dk):
        """Oyun sürerken ek istemcilerin kayıtlarının aralıklı yedeği (panelin zamanlayıcısı)."""
        if not aralik_dk:
            return
        for s in self.canli():
            if time.time() - self.son_yedek.get(s, 0) >= aralik_dk * 60:
                self.kay.backup(s, 'oto', _('Oyun sırasında'))
                self.son_yedek[s] = time.time()
