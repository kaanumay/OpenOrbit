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
_USAGE_LOCK = threading.Lock()


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


_JOB = []


def _bind_to_parent(proc):
    """Windows: llama-server is put in a job object that kills its processes when its last handle closes; the handle lives as long as
    this process, so the child dies with the game server however it ends (forced stop, crash, os._exit, an exception in main: before,
    it stayed behind holding the model in memory and the port)."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        if not _JOB:
            class Basic(ctypes.Structure):
                _fields_ = [('a', ctypes.c_int64), ('b', ctypes.c_int64), ('LimitFlags', wintypes.DWORD), ('c', ctypes.c_size_t),
                            ('d', ctypes.c_size_t), ('e', wintypes.DWORD), ('f', ctypes.c_size_t), ('g', wintypes.DWORD),
                            ('h', wintypes.DWORD)]

            class Extended(ctypes.Structure):
                _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6), ('m', ctypes.c_size_t * 4)]
            job = k32.CreateJobObjectW(None, None)
            info = Extended()
            info.basic.LimitFlags = 0x2000                       # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not job or not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):   # JobObjectExtendedLimitInformation
                return
            _JOB.append(job)
        k32.AssignProcessToJobObject(_JOB[0], int(proc._handle))
    except (OSError, AttributeError, ValueError):
        pass                                                     # (the normal stop still terminates it)


# Linux and macOS: llama-server runs under this watcher, which ends it once the game server is gone however that happened (crash, kill -9,
# os._exit; the panel's forced stop signals the server's descendants itself). PR_SET_PDEATHSIG would need preexec_fn, unsafe in a
# threaded process, and it fires when the launching thread ends (Brain starts the model from a short-lived thread), not the process.
WATCHER = r'''
import os, signal, subprocess, sys, time
parent, child = int(sys.argv[1]), subprocess.Popen(sys.argv[2:])
def stop(*_):
    child.terminate()
    try:
        child.wait(4)
    except subprocess.TimeoutExpired:
        child.kill()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
while child.poll() is None:
    if os.getppid() != parent:
        stop()
    time.sleep(1)
sys.exit(child.returncode)
'''


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
        else:
            cmd = [sys.executable, '-I', '-c', WATCHER, str(os.getpid())] + cmd
        with open(os.path.join(PTH.LOGS, 'llm_server.log'), 'ab') as daily:     # the child has its own copy of the handle
            self.proc = subprocess.Popen(cmd, stdout=daily, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         cwd=os.path.dirname(k['server']), **kw)
        _bind_to_parent(self.proc)
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
        p, self.proc = self.proc, None                   # taken first: Brain._open and Brain.stop may both stop it (AttributeError on None)
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()

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
        with _USAGE_LOCK:                                  # several llm-N worker threads count at once (+= is not atomic)
            k['request'] += 1
            k['input'] += int(u.get('prompt_tokens') or 0)
            k['cache'] += int((u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0)
            k['output'] += int(u.get('completion_tokens') or 0)
        text = _THINK.sub('', d['choices'][0]['message'].get('content') or '').strip()
        if schema is not None:                     # the first valid JSON object (the model sometimes writes a second one after it)
            i = text.find('{')
            text = json.JSONDecoder().raw_decode(text[i if i >= 0 else 0:])[0]
            if not isinstance(text, dict):
                raise ValueError('the reply is not a JSON object')     # like llm_provider._json: Brain.ask asks once more
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
