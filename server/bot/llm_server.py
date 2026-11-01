"""Yerel dil modeli: llama.cpp'nin llama-server'ı (OpenAI uyumlu /v1/chat/completions) ve Qwen3 4B Q4_K_M.

Kurulumu panel yapar (panel/llm_setup.py: save/llm/); burada süreç başlatma, sağlık denetimi ve çağrı var (oyun sunucusu da panelin
"Test et" düğmesi de bunu kullanır). Qwen3'ün düşünme kipi kapalı: istemde /no_think ve chat_template_kwargs.enable_thinking=false
(düşünürse yanıt saniyeler sürer); yanıtta yine de <think> kalırsa atılır. Paralel yuvalar (-np) sunucunun kendi toplu işlemesidir:
aynı anda gelen istekler tek geçişte hesaplanır.
"""
import json, os, re, socket, subprocess, sys, threading, time
from urllib.request import Request, urlopen

import paths as PTH

MODEL_FILE = 'Qwen3-4B-Q4_K_M.gguf'
CONTEXT_SIZE = 8192
DEFAULT_PORT = 8095
_THINK = re.compile(r'<think>.*?</think>\s*', re.S)


def folder():
    return os.path.join(PTH.SAVE, 'llm')


def setup():
    """Kurulumun kaydı {sunucu, model, test_ok, ...} ya da None."""
    try:
        with open(os.path.join(folder(), 'install.json'), encoding='utf8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if not (d.get('sunucu') and os.path.isfile(d['sunucu']) and os.path.isfile(os.path.join(folder(), MODEL_FILE))):
        return None
    return d


def free_port(preference=DEFAULT_PORT):
    for p in [preference] + list(range(preference + 1, preference + 20)):
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError('boş port yok')


class Server:
    """llama-server süreci. baslat() sağlık denetimi geçince döner (ya da RuntimeError)."""

    def __init__(self, slot=4, log=print):
        self.slot, self.log = max(1, int(slot)), log
        self.proc = None
        self.port = None
        self.ready = False
        self.name = 'Qwen3 4B'
        self.usage = {'request': 0, 'input': 0, 'cache': 0, 'output': 0}     # token sayımı (llm_saglayici.Uzak ile aynı)

    def launch(self, wait_sec=180):
        k = setup()
        if k is None:
            raise RuntimeError('dil modeli kurulu değil')
        self.port = free_port()
        cmd = [k['sunucu'], '-m', os.path.join(folder(), MODEL_FILE), '--host', '127.0.0.1', '--port', str(self.port),
               '-c', str(CONTEXT_SIZE * self.slot // 2), '-np', str(self.slot), '-ngl', '99', '--jinja', '--no-webui']
        kw = {}
        if sys.platform == 'win32':
            kw['creationflags'] = 0x08000000                 # CREATE_NO_WINDOW
        daily = open(os.path.join(PTH.LOGS, 'llm_sunucu.log'), 'ab')
        self.proc = subprocess.Popen(cmd, stdout=daily, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     cwd=os.path.dirname(k['sunucu']), **kw)
        last = time.time() + wait_sec
        while time.time() < last:
            if self.proc.poll() is not None:
                raise RuntimeError('llama-server kapandı (çıkış %s; günlük: logs/llm_sunucu.log)' % self.proc.returncode)
            try:
                with urlopen('http://127.0.0.1:%d/health' % self.port, timeout=2) as r:
                    if r.status == 200 and json.loads(r.read() or b'{}').get('status', 'ok') == 'ok':
                        self.ready = True
                        return self
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        self.stop()
        raise RuntimeError('llama-server %d sn içinde hazır olmadı' % wait_sec)

    def stop(self):
        self.ready = False
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def ask(self, system, user, schema=None, max_count=220, temperature=0.8, timestamp=60):
        """Tek çağrı -> (metin ya da JSON nesnesi, süre sn). sema verilirse yanıt o JSON şemasına uyar (llama-server dilbilgisi)."""
        body = {'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': '/no_think\n' + user}],
                 'max_tokens': max_count, 'temperature': temperature, 'top_p': 0.8, 'top_k': 20, 'min_p': 0.0,
                 'presence_penalty': 1.0, 'chat_template_kwargs': {'enable_thinking': False}}     # Qwen3 düşünmesiz kip önerisi
        if schema is not None:
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'response', 'schema': schema, 'strict': True}}
        t0 = time.time()
        req = Request('http://127.0.0.1:%d/v1/chat/completions' % self.port, data=json.dumps(body).encode('utf8'),
                      headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=timestamp) as r:
            d = json.loads(r.read())
        u, k = d.get('usage') or {}, self.usage
        k['request'] += 1
        k['input'] += int(u.get('prompt_tokens') or 0)
        k['cache'] += int((u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0)
        k['output'] += int(u.get('completion_tokens') or 0)
        text = _THINK.sub('', d['choices'][0]['message'].get('content') or '').strip()
        if schema is not None:                     # ilk geçerli JSON nesnesi (model bazen ardına ikincisini yazıyor)
            i = text.find('{')
            text = json.JSONDecoder().raw_decode(text[i if i >= 0 else 0:])[0]
        return text, time.time() - t0


def test(log=print):
    """Panelin "Test et" düğmesi: sunucuyu aç, kısa bir soru sor, kapat -> {ok, sure, yanit, hiz}."""
    s = Server(slot=1, log=log)
    t0 = time.time()
    try:
        s.launch()
        opening = time.time() - t0
        response, duration = s.ask('Sen bir uzay oyununda pilotsun. Kısa yanıt ver.',
                            'Bir arkadaşın "selam, nasılsın?" yazdı. JSON ver: cevap alanına kısa bir Türkçe yanıt, durum alanına "TAMAM".',
                            schema={'type': 'object', 'properties': {'cevap': {'type': 'string'}, 'durum': {'type': 'string'}},
                                  'required': ['cevap', 'durum']}, max_count=80)
        ok = isinstance(response, dict) and 'TAMAM' in str(response.get('durum', '')).upper()
        return {'ok': ok, 'startup_sec': round(opening, 1), 'sure_sn': round(duration, 2), 'response': response.get('cevap') if isinstance(response, dict) else str(response)}
    finally:
        s.stop()
