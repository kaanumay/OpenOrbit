"""Panelden yeni istemciye protokol uyarlaması (yol haritası "Sürekli işler" > İstemci güncellemesine hazırlık): araç
tools/il2cpp/protocol_update.py ayrı süreçte (python -I) çalışır; panel ilerleme satırlarını, fark özetini ve raporun yolunu
gösterir. "Uygula" sürüm klasöründeki protokolü etkin yapar (etkin dosyalar yedeklenir); oyun sunucusu yeniden başlatılınca
yeni protokolle çalışır. Aynı anda tek iş."""
import json, os, re, subprocess, threading, time

from lang import t as _


class Adapter:
    def __init__(self, root, python, log=print, no_window=0):
        self.root, self.python, self.log, self.no_window = root, python, log, no_window
        self.tool = os.path.join(root, 'tools', 'il2cpp', 'protocol_update.py')
        self.lock = threading.Lock()
        self.d = {'calisiyor': False, 'satirlar': [], 'ozet': None, 'hata': None, 'baslangic': None, 'bitis': None, 'is': None}

    def state(self):
        with self.lock:
            return json.loads(json.dumps(self.d))

    def _start(self, kind, args):
        with self.lock:
            if self.d['calisiyor']:
                raise RuntimeError(_('Protokol aracı zaten çalışıyor.'))
            self.d = {'calisiyor': True, 'satirlar': [], 'ozet': None, 'hata': None, 'baslangic': time.time(), 'bitis': None,
                      'is': kind}
        threading.Thread(target=self._run, args=(args,), daemon=True).start()
        return self.state()

    def generate(self, folder):
        if not folder or not os.path.isdir(folder):
            raise RuntimeError(_('İstemci klasörü yok.'))
        return self._start('uret', [folder])

    def activate(self, version):
        if not version or not re.match(r'^[0-9A-Za-z._-]+$', version):
            raise RuntimeError(_('Sürüm geçersiz.'))
        return self._start('uygula', ['--etkin=' + version])

    def _run(self, args):
        try:
            p = subprocess.Popen([self.python, '-I', '-X', 'utf8', self.tool] + args, cwd=self.root, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding='utf8', errors='replace',
                                 creationflags=self.no_window)
            for line in p.stdout:
                line = line.rstrip()
                with self.lock:
                    self.d['satirlar'] = (self.d['satirlar'] + [line])[-80:]
                m = re.search(r'fark: (\{.*\})', line)
                if m:
                    with self.lock:
                        self.d['ozet'] = dict(self.d['ozet'] or {}, **json.loads(m.group(1)))
                m = re.search(r'rapor: (.+)$', line)
                if m:
                    with self.lock:
                        self.d['ozet'] = dict(self.d['ozet'] or {}, rapor=m.group(1).strip())
                m = re.search(r'^istemci (\S+) ->', line)
                if m:
                    with self.lock:
                        self.d['ozet'] = dict(self.d['ozet'] or {}, surum=m.group(1))
            code = p.wait()
            if code:
                with self.lock:
                    self.d['hata'] = _('Araç hata verdi (çıkış %d); son satırlara bakın.', code)
        except Exception as e:
            with self.lock:
                self.d['hata'] = repr(e)
        finally:
            with self.lock:
                self.d['calisiyor'], self.d['bitis'] = False, time.time()
            self.log('protokol aracı bitti: %s' % (self.d['hata'] or 'tamam'))
