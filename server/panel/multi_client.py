"""Çoklu istemci (panel): OYNA'dan sonra bu bilgisayardaki öteki kayıtlarla ek oyun istemcileri.

Oyun sunucusu çok oturumlu kipte açılır (panel ayarı coklu_istemci açık ve en az iki kayıt varsa; arkadaş sunucusunda zaten öyle).
Ek istemcinin kaydı sunucuya POST /yerel/ekle ile eklenir (server/multiplayer.py: sunucu yuvanın profil.json'una doğrudan yazar;
kimliği başka bir oyuncununkiyle aynıysa bellekte geçici kimlik), istemci http://127.0.0.1:8090/?oturum=<anahtar>#darkorbit:// ile
açılır (web.py anahtarı sunucuya sorar). İstemci kapanınca POST /yerel/cikar: son hâl yazılır, yuva serbest kalır. Ek istemciler
pencere kipinde açılır, pencere başlığı pilotun adı; günlükleri logs/client_<kayıt>.log. Ana kayıt, açık bir kayıt, aynı pilot adı
ve sınırın üstü reddedilir; ek istemci açıkken sunucuyu yeniden başlatan işler panelde engellenir (panel.py).
Plan ve önceden düşünülen sorunlar: belgeler/COKLU_ISTEMCI.md.
"""
import json, os, threading, time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from lang import t as _
import client as IST
import processes as PR

GAME = 'http://127.0.0.1:8081'
OPENER = build_opener(ProxyHandler({}))       # yerel sunucuya sistemin vekil sunucusu üzerinden gidilmesin
EARLY_SEC = 15                                  # bundan önce kapanan istemci: erken kapandı (kartta uyarı)


class MultiClientError(Exception):
    """Kullanıcıya gösterilen hata."""


class MultiClient:
    def __init__(self, cfg, saves, direction, key, logs, log=print):
        """anahtar: () -> oyun sunucusunun yönetim anahtarı (arkadas.Arkadas.anahtar; OO_MULTIPLAYER)."""
        self.cfg, self.saves, self.direction, self.key, self.logs, self.log = cfg, saves, direction, key, logs, log
        self.lock = threading.RLock()
        self.is_open = {}                 # kayıt -> {'proc', 'oturum', 'uid', 'basla', 'pilot', 'gunluk'} ('proc' None: açılıyor)
        self.last = {}                  # kayıt -> son kapanış {'sure_sn', 'erken', 'kod', 'zaman', 'bitis'}
        self.last_backup = {}            # kayıt -> son aralıklı yedek
        self.on_exit = None            # panel bağlar: () -> None (bir ek istemci kapandı)

    # ------------------------------------------------------------ oyun sunucusu
    def request(self, path, body):
        data = json.dumps(dict(body, anahtar=self.key())).encode('utf8')
        req = Request(GAME + path, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with OPENER.open(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode('utf8') or '{}')
        except HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode('utf8') or '{}')
            except ValueError:
                return e.code, {}
        except (URLError, OSError, ValueError) as e:
            raise MultiClientError(_('Oyun sunucusuna ulaşılamadı (%s).', getattr(e, 'reason', e)))

    # ------------------------------------------------------------ durum
    def live(self):
        """Açık, açılmakta ya da kapanmakta olan ek istemcilerin kayıtları (kapanan istemcinin yuvası sunucuda bırakılınca çıkar:
        hemen yeniden açılan istemci sunucudaki eski oturuma bağlanıp sonra onunla birlikte bırakılmasın)."""
        with self.lock:
            return list(self.is_open)

    def in_use(self, slot):
        return slot in self.live()

    def pids(self):
        with self.lock:
            return {e['proc'].pid for e in self.is_open.values() if e['proc'] is not None}

    def state(self, live=None):
        """Panelin listesi: ek istemciler (sunucunun canli_durum.json'undaki 'yereller'le: bağlı mı, harita, seviye)."""
        lv = {y.get('kayit'): y for y in ((live or {}).get('local_players') or [])}
        now = time.time()
        with self.lock:
            out = []
            for s, e in self.is_open.items():
                y = lv.get(s) or {}
                out.append({'kayit': s, 'pilot': e['pilot'], 'pid': e['proc'].pid if e['proc'] else None,
                            'durum': 'aciliyor' if e['proc'] is None else 'acik' if e['proc'].poll() is None else 'kapaniyor',
                            'sure_sn': int(now - e['basla']),
                            'bagli': bool(y.get('bagli')), 'harita': y.get('harita'), 'seviye': y.get('seviye'), 'uid': e['uid']})
            return {'clients': out, 'son': dict(self.last)}

    # ------------------------------------------------------------ açma ve kapatma
    def open_(self, slot, folder, main_slot):
        """Ek istemciyi aç (sunucu çok oturumlu açık olmalı: panel denetler). -> durum."""
        if slot == main_slot:
            raise MultiClientError(_('Bu kayıt ana istemcide açık: ek istemcide başka bir kayıt seç.'))
        if not self.saves.exists(slot):
            raise MultiClientError(_('Kayıt bulunamadı.'))
        c = IST.check(folder)
        if not c['valid']:
            raise MultiClientError(_('İstemci klasörü geçersiz: %s', ' '.join(c['issues'])))
        with self.lock:
            if slot in self.live():
                raise MultiClientError(_('Bu kayıt zaten bir ek istemcide açık.'))
            n = self.cfg.get('coklu_en_cok')
            if len(self.live()) >= n:
                raise MultiClientError(_('En çok %d ek istemci açılabilir (İstemci > Çoklu istemci).', n))
            self.is_open[slot] = {'proc': None, 'oturum': None, 'uid': None, 'basla': time.time(), 'pilot': '', 'gunluk': None}
        out = None
        try:
            summary = self.saves.summary(slot)
            if summary.get('bozuk'):
                raise MultiClientError(_('Kayıt okunamıyor (bozuk): Kayıtlar > Yedekler\'den geri yükle.'))
            if self.cfg.get('yedek_acilista'):
                self.saves.backup(slot, 'oto', _('Ek istemci (açılış)'))
            self.last_backup[slot] = time.time()
            code, out = self.request('/yerel/ekle', {'kayit': slot, 'yol': self.saves.profile(slot)})
            if code != 200:
                raise MultiClientError(out.get('mesaj') or _('Oyun sunucusu kaydı almadı (HTTP %s).', code))
            daily = os.path.join(self.logs, 'client_%s.log' % slot)
            import launcher
            launcher.rotate_logs(self.logs, names=(os.path.basename(daily),))
            cmd, env = IST.command(self.cfg, folder, daily, session=out['oturum'], window=True)
            proc = PR.open_client(folder, cmd, env, self.logs)
        except Exception:
            with self.lock:
                self.is_open.pop(slot, None)
            if out and out.get('oturum'):            # sunucuya kaydolduysa bırakılsın (yoksa kayıt düzenlenebilir sanılıyordu)
                try:
                    self.request('/yerel/cikar', {'oturum': out['oturum']})
                except Exception:
                    pass
            raise
        pilot = summary.get('pilot') or slot
        with self.lock:
            self.is_open[slot].update(proc=proc, oturum=out['oturum'], uid=out['uid'], basla=time.time(), pilot=pilot, gunluk=daily)
        m = self.saves.meta(slot)
        self.saves.set_meta(slot, son_oynama=time.strftime('%Y-%m-%d %H:%M:%S'), oynama_sayisi=int(m.get('oynama_sayisi') or 0) + 1)
        PR.window_title(proc.pid, 'DarkOrbit — %s' % pilot)
        self.log('ek istemci açıldı: %s (%s), süreç %d, sunucudaki kimlik %s%s' % (slot, pilot, proc.pid, out['uid'],
                                                                               ' (sürüyor)' if out.get('devam') else ''))
        threading.Thread(target=self._watch, args=(slot, proc), daemon=True).start()
        return self.state()

    def _watch(self, slot, proc):
        code = proc.wait()
        with self.lock:
            e = self.is_open.get(slot)
        stop = time.time() - (e['basla'] if e else time.time())
        if e and e['oturum'] and self.direction.running():
            try:
                c, out = self.request('/yerel/cikar', {'oturum': e['oturum']})
                if c not in (200, 404):
                    self.log('ek istemcinin kaydı bırakılamadı (%s): %s' % (c, out))
            except MultiClientError as err:
                self.log('ek istemcinin kaydı bırakılamadı: %s' % err)
        with self.lock:
            if self.is_open.get(slot, {}).get('proc') is proc:
                self.is_open.pop(slot, None)
            self.last[slot] = {'sure_sn': int(stop), 'early': stop < EARLY_SEC and not (e or {}).get('kapatildi'), 'kod': code,
                              'zaman': time.strftime('%H:%M:%S'), 'bitis': time.time()}      # panelden kapatılan erken sayılmaz
        self.log('ek istemci kapandı: %s (%d sn, kod %s)' % (slot, stop, code))
        if self.on_exit:
            try:
                self.on_exit()
            except Exception as err:                   # noqa: BLE001
                self.log('ek istemci kapanış işlemi hatası: %r' % err)

    def close(self, slot):
        with self.lock:
            e = self.is_open.get(slot)
        if not e or e['proc'] is None:
            raise MultiClientError(_('Bu kayıtla açık bir ek istemci yok.'))
        if e['proc'].poll() is None:
            e['kapatildi'] = True
            PR.close_client(e['proc'])

    def close_all(self, wait=0.0):
        """Bütün ek istemcileri kapat; bekle: kapanışları (sunucuya son kayıt) en çok bu kadar beklenir."""
        with self.lock:
            is_open = [e for e in self.is_open.values() if e['proc'] is not None and e['proc'].poll() is None]
        for e in is_open:
            e['kapatildi'] = True
            PR.close_client(e['proc'])
        end = time.time() + wait
        while self.live() and time.time() < end:
            time.sleep(0.1)

    def backup(self, interval_min):
        """Oyun sürerken ek istemcilerin kayıtlarının aralıklı yedeği (panelin zamanlayıcısı)."""
        if not interval_min:
            return
        for s in self.live():
            if time.time() - self.last_backup.get(s, 0) >= interval_min * 60:
                self.saves.backup(s, 'oto', _('Oyun sırasında'))
                self.last_backup[s] = time.time()
