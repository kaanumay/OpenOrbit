"""Local language model: llama.cpp's llama-server (OpenAI-compatible /v1/chat/completions) and Qwen3 4B Q4_K_M.

The panel does the setup (panel/llm_setup.py: save/llm/); here are process launch, the health check and the call (the game server and the panel's
"Test" button both use it). Qwen3's thinking mode is off: /no_think in the prompt and chat_template_kwargs.enable_thinking=false
(if it thinks, the reply takes seconds); if <think> still remains in the reply it is dropped. Parallel slots (-np) are the server's own batching:
requests that arrive at the same time are computed in one pass.
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
    """The setup's record {server, model, test_ok, ...} or None."""
    try:
        with open(os.path.join(folder(), 'install.json'), encoding='utf8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if not (d.get('server') and os.path.isfile(d['server']) and os.path.isfile(os.path.join(folder(), MODEL_FILE))):
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
    raise RuntimeError('No free port.')


class Server:
    """The llama-server process. launch() returns once the health check passes (or raises RuntimeError)."""

    def __init__(self, slot=4, log=print):
        self.slot, self.log = max(1, int(slot)), log
        self.proc = None
        self.port = None
        self.ready = False
        self.name = 'Qwen3 4B'
        self.usage = {'request': 0, 'input': 0, 'cache': 0, 'output': 0}     # token counting (same as llm_provider.Remote)

    def launch(self, wait_sec=180):
        k = setup()
        if k is None:
            raise RuntimeError('The language model is not installed.')
        self.port = free_port()
        cmd = [k['server'], '-m', os.path.join(folder(), MODEL_FILE), '--host', '127.0.0.1', '--port', str(self.port),
               '-c', str(CONTEXT_SIZE * self.slot // 2), '-np', str(self.slot), '-ngl', '99', '--jinja', '--no-webui']
        kw = {}
        if sys.platform == 'win32':
            kw['creationflags'] = 0x08000000                 # CREATE_NO_WINDOW
        daily = open(os.path.join(PTH.LOGS, 'llm_server.log'), 'ab')
        self.proc = subprocess.Popen(cmd, stdout=daily, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     cwd=os.path.dirname(k['server']), **kw)
        last = time.time() + wait_sec
        while time.time() < last:
            if self.proc.poll() is not None:
                self.log('llama-server exited: %s' % self.proc.returncode)
                raise RuntimeError('llama-server closed (log: logs/llm_server.log).')
            try:
                with urlopen('http://127.0.0.1:%d/health' % self.port, timeout=2) as r:
                    if r.status == 200 and json.loads(r.read() or b'{}').get('status', 'ok') == 'ok':
                        self.ready = True
                        return self
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        self.stop()
        self.log('llama-server was not ready in %d s' % wait_sec)
        raise RuntimeError('llama-server did not become ready in time.')

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
        """One call -> (text or JSON object, duration in s). If schema is given the reply conforms to that JSON schema (llama-server grammar)."""
        body = {'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': '/no_think\n' + user}],
                 'max_tokens': max_count, 'temperature': temperature, 'top_p': 0.8, 'top_k': 20, 'min_p': 0.0,
                 'presence_penalty': 1.0, 'chat_template_kwargs': {'enable_thinking': False}}     # Qwen3 non-thinking mode recommendation
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
        if schema is not None:                     # the first valid JSON object (the model sometimes writes a second one after it)
            i = text.find('{')
            text = json.JSONDecoder().raw_decode(text[i if i >= 0 else 0:])[0]
        return text, time.time() - t0


def test(log=print):
    """The panel's "Test" button: start the server, ask a short question, stop it -> {ok, startup_sec, duration_sec, response}."""
    s = Server(slot=1, log=log)
    t0 = time.time()
    try:
        s.launch()
        opening = time.time() - t0
        response, duration = s.ask('You are a pilot in a space game. Answer briefly.',
                            'A friend wrote "selam, nasılsın?". Give JSON: in answer a short reply in Turkish, in state the word "OK".',
                            schema={'type': 'object', 'properties': {'answer': {'type': 'string'}, 'state': {'type': 'string'}},
                                  'required': ['answer', 'state']}, max_count=80)
        ok = isinstance(response, dict) and 'OK' in str(response.get('state', '')).upper()
        return {'ok': ok, 'startup_sec': round(opening, 1), 'duration_sec': round(duration, 2), 'response': response.get('answer') if isinstance(response, dict) else str(response)}
    finally:
        s.stop()
