"""Language model provider of Advanced mode: the built-in local model (llm_server: llama-server + Qwen3 4B) or a provider the user picks
(OpenAI, Anthropic, Gemini, DeepSeek ...; Ollama, LM Studio or another OpenAI-compatible server on the computer).

The choice is single and global: save/llm/provider.json {selected, providers: {uid: {anahtar, address, model}}}. Keys never go into the
bot packages; the panel shows them only masked. The remote client offers the same interface as Server (launch, ask, stop): Brain does
not tell them apart. The built-in model speaks only English (weak in Turkish); with the other providers the bots speak their own
languages (multilingual).

JSON reply: for OpenAI-compatibles first response_format json_schema, if the provider rejects it json_object, and if that fails too the
schema only in the prompt; the step reached stays on the client. If the provider returns 400 for a parameter it does not know
(temperature, max_tokens ...) that parameter is dropped and the question is asked again. Anthropic is called with its own Messages API
(output_config.format).
"""
import json, os, re, threading, time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import paths as PTH

LOCAL = 'local'
# id -> name, type ('openai' compatible or 'anthropic'), default address and model, whether a key is needed, whether it runs on the computer
PROVIDERS = {
    LOCAL: dict(name='Dahili yerel model (Qwen3 4B)', type='builtin', address='', model='', key=False, local=True),
    'openai': dict(name='OpenAI', type='openai', address='https://api.openai.com/v1', model='gpt-4.1-mini', key=True, local=False),
    'anthropic': dict(name='Anthropic Claude', type='anthropic', address='https://api.anthropic.com/v1', model='claude-haiku-5-5',
                      key=True, local=False),
    'gemini': dict(name='Google Gemini', type='openai', address='https://generativelanguage.googleapis.com/v1beta/openai',
                   model='gemini-2.5-flash', key=True, local=False),
    'deepseek': dict(name='DeepSeek', type='openai', address='https://api.deepseek.com/v1', model='deepseek-chat', key=True, local=False),
    'openrouter': dict(name='OpenRouter', type='openai', address='https://openrouter.ai/api/v1', model='openai/gpt-4.1-mini', key=True,
                       local=False),
    'groq': dict(name='Groq', type='openai', address='https://api.groq.com/openai/v1', model='llama-3.3-70b-versatile', key=True,
                 local=False),
    'mistral': dict(name='Mistral', type='openai', address='https://api.mistral.ai/v1', model='mistral-small-latest', key=True,
                    local=False),
    'xai': dict(name='xAI Grok', type='openai', address='https://api.x.ai/v1', model='grok-3-mini', key=True, local=False),
    'ollama': dict(name='Ollama', type='openai', address='http://127.0.0.1:11434/v1', model='qwen3:8b', key=False, local=True),
    'lmstudio': dict(name='LM Studio', type='openai', address='http://127.0.0.1:1234/v1', model='', key=False, local=True),
    'special': dict(name='Custom (OpenAI-compatible)', type='openai', address='http://127.0.0.1:8080/v1', model='', key=False, local=True),
}
_THINK = re.compile(r'<think>.*?</think>\s*', re.S)
_LOCK = threading.Lock()


class ProviderError(RuntimeError):
    """Error shown to the user (wrong key, no model, server down ...)."""


def _route():
    return os.path.join(PTH.SAVE, 'llm', 'provider.json')


def setting():
    """{selected, providers: {uid: {anahtar, address, model}}} (the built-in model if the file does not exist)."""
    try:
        with open(_route(), encoding='utf8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    if d.get('selected') not in PROVIDERS:
        d['selected'] = LOCAL
    d['providers'] = {k: v for k, v in (d.get('providers') or {}).items() if k in PROVIDERS and isinstance(v, dict)}
    return d


def selected():
    """The selected provider's full setting {uid, type, address, model, anahtar}."""
    d = setting()
    return full(d['selected'], d['providers'].get(d['selected']) or {})


def full(uid, a):
    s = PROVIDERS[uid]
    return {'uid': uid, 'type': s['type'], 'address': (a.get('address') or s['address']).rstrip('/'),
            'model': a.get('model') or s['model'], 'key': a.get('key') or ''}


def multilingual(uid=None):
    """Whether the bots can speak their own languages (the built-in Qwen3 4B is English only)."""
    return (uid or setting()['selected']) != LOCAL


def mask(key):
    return ('…' + key[-4:]) if len(key or '') > 8 else ('•••' if key else '')


def status():
    """The panel's view: the selected provider, each provider's address, model and masked key."""
    d = setting()
    out = []
    for k, s in PROVIDERS.items():
        a = d['providers'].get(k) or {}
        out.append({'uid': k, 'name': s['name'], 'type': s['type'], 'key_required': s['key'], 'local': s['local'],
                    'address': a.get('address') or s['address'], 'model': a.get('model') or s['model'],
                    'default_url': s['address'], 'key': mask(a.get('key') or ''), 'has_key': bool(a.get('key'))})
    return {'selected': d['selected'], 'multilingual': multilingual(d['selected']), 'entries': out}


def save(uid, address=None, model=None, key=None, sec=True):
    """Write the provider's setting; if the key is None or empty the old one stays ('-' deletes)."""
    if uid not in PROVIDERS:
        raise ProviderError('Unknown provider.')
    if address is not None:
        address = str(address).strip()
    if address and not re.fullmatch(r'https?://[^\s]+', address):
        raise ProviderError('The address must start with http:// or https://.')
    with _LOCK:
        d = setting()
        a = dict(d['providers'].get(uid) or {})
        if address is not None:
            a['address'] = address
        if model is not None:
            a['model'] = str(model).strip()[:200]
        if key == '-':
            a.pop('key', None)
        elif key:
            a['key'] = str(key).strip()
        d['providers'][uid] = a
        if sec:
            d['selected'] = uid
        os.makedirs(os.path.dirname(_route()), exist_ok=True)
        temporary = _route() + '.tmp'
        with open(temporary, 'w', encoding='utf8') as fh:
            json.dump(d, fh, indent=1, ensure_ascii=False)
        os.replace(temporary, _route())
    return status()


# ------------------------------------------------------------------------------------------------------------ HTTP
def _headers(c):
    h = {'Content-Type': 'application/json', 'User-Agent': 'OpenOrbit'}
    if c['type'] == 'anthropic':
        h.update({'x-api-key': c['key'], 'anthropic-version': '2023-06-01'})
    elif c['key']:
        h['Authorization'] = 'Bearer ' + c['key']
    if c['uid'] == 'openrouter':
        h.update({'HTTP-Referer': 'https://github.com/OpenOrbit', 'X-Title': 'OpenOrbit'})
    return h


def _request(c, route, body=None, timestamp=60):
    req = Request(c['address'] + route, data=None if body is None else json.dumps(body).encode('utf8'), headers=_headers(c),
                  method='GET' if body is None else 'POST')
    with urlopen(req, timeout=timestamp) as r:
        return json.loads(r.read() or b'{}')


class HttpError(ProviderError):
    def __init__(self, code, text):
        self.code, self.text = code, text
        super().__init__(_human_error(code, text))


def _human_error(code, text):
    """The provider's error message (language independent: the panel shows it in every language; messages are mostly English)."""
    try:
        e = json.loads(text)
        e = e[0] if isinstance(e, list) and e else e
        m = (e.get('error') or {}) if isinstance(e, dict) else {}
        m = m.get('message') if isinstance(m, dict) else (m or e.get('message'))
    except (ValueError, AttributeError):
        m = None
    m = ' '.join(str(m or text or '').split())[:240]
    return 'HTTP %d: %s' % (code, m) if m else 'HTTP %d' % code


def _call(c, route, body=None, timestamp=60):
    try:
        return _request(c, route, body, timestamp)
    except HTTPError as e:
        try:
            text = e.read().decode('utf8', 'replace')
        except OSError:
            text = ''
        raise HttpError(e.code, text) from None
    except (URLError, OSError) as e:
        raise ProviderError('%s: %s' % (c['address'], getattr(e, 'reason', e))) from None


def models(uid, address=None, key=None):
    """The provider's models (/models). If no key is given the saved one is used."""
    if uid not in PROVIDERS or uid == LOCAL:
        raise ProviderError('Unknown provider.')
    a = dict(setting()['providers'].get(uid) or {})
    if address:
        a['address'] = address
    if key:
        a['key'] = key
    c = full(uid, a)
    d = _call(c, '/models' + ('?limit=100' if c['type'] == 'anthropic' else ''), timestamp=20)
    entries = d.get('data') if isinstance(d, dict) else d
    names = [str(m.get('id') or m.get('name') or '') for m in entries or [] if isinstance(m, dict)]
    return sorted({re.sub(r'^models/', '', x) for x in names if x})


# ------------------------------------------------------------------------------------------------------------ client
def _anthropic_schema(s):
    """The schema Anthropic structured output accepts: additionalProperties false on objects; length and count limits are dropped
    (the "short" directive in the prompt and llm.py's filter bound them)."""
    if isinstance(s, dict):
        out = {k: _anthropic_schema(v) for k, v in s.items() if k not in ('maxLength', 'minLength', 'maxItems', 'minItems')}
        if out.get('type') == 'object':
            out['additionalProperties'] = False
        return out
    if isinstance(s, list):
        return [_anthropic_schema(x) for x in s]
    return s


def _json(text):
    """The first JSON object in the reply (a ``` fence, chatter before it, or a second object after it is dropped)."""
    text = _THINK.sub('', text or '')
    i = text.find('{')
    if i < 0:
        raise ValueError('no JSON in the reply')
    d = json.JSONDecoder(strict=False).raw_decode(text[i:])[0]       # strict=False: raw line break inside the text
    if not isinstance(d, dict):
        raise ValueError('the reply is not a JSON object')
    return d


class Remote:
    """The selected remote or on-computer provider (Server's interface)."""

    def __init__(self, c, log=print):
        self.c, self.log = c, log
        self.name = '%s · %s' % (PROVIDERS[c['uid']]['name'], c['model'] or '?')
        self.port = None
        self.ready = False
        self.json_mode = 'schema'              # schema -> object -> prompt (as the provider rejects)
        self.jump_to = set()                   # parameters the provider does not know
        self.wait = 0.0                    # no requests until this moment after a 429 (jobs fall back to templates)
        self.usage = {'request': 0, 'input': 0, 'cache': 0, 'output': 0}     # token count (cached input counted separately)

    def launch(self, wait_sec=None):
        if PROVIDERS[self.c['uid']]['key'] and not self.c['key']:
            raise ProviderError('Enter the API key first.')
        if not self.c['model']:
            raise ProviderError('Choose a model first.')
        try:                                # connection and key check: an HTTP error stops, a single bad reply from the model does not
            self.ask('Reply with JSON.', 'Say hi.', schema={'type': 'object', 'properties': {'answer': {'type': 'string'}},
                                                          'required': ['answer']}, max_count=40, timestamp=60)
        except ValueError as e:
            self.log('   bots: the provider trial reply is malformed (%s), opening anyway' % e)
        self.ready = True
        return self

    def stop(self):
        self.ready = False

    def ask(self, system, user, schema=None, max_count=220, temperature=0.8, timestamp=60):
        """A single call -> (text or JSON object, duration in s)."""
        if time.time() < self.wait:
            raise ProviderError('Request limit: waiting.')
        t0 = time.time()
        for _ in range(4):                  # on each 400 one parameter or JSON step is dropped
            try:
                text = (self._anthropic if self.c['type'] == 'anthropic' else self._openai)(system, user, schema, max_count, temperature,
                                                                                            timestamp)
                break
            except HttpError as e:
                if e.code == 429:
                    self.wait = time.time() + 20
                    raise
                if e.code != 400 or not self._adapt(e.text, schema):
                    raise
        else:
            raise ProviderError('The provider refused the request.')
        return (_json(text) if schema is not None else _THINK.sub('', text).strip()), time.time() - t0

    def _adapt(self, text, schema):
        """Change the request according to the 400 reply -> whether it can be retried."""
        m = text.lower()
        if self.c['type'] == 'anthropic' and 'effort' in m and 'output_config' not in self.jump_to:
            self.jump_to.add('output_config')          # old model: no effort (schema in the prompt too)
            self.json_mode = 'prompt'
            return True
        for p in ('temperature', 'top_p', 'max_tokens', 'max_completion_tokens'):
            if p in m and p not in self.jump_to:
                self.jump_to.add(p)
                self.log('   bots: provider does not accept %s, asking without it' % p)
                return True
        if schema is not None and self.json_mode != 'prompt' and re.search(r'response_format|json_schema|json_object|output_config|'
                                                                       r'schema|format', m):
            self.json_mode = 'object' if self.json_mode == 'schema' and self.c['type'] == 'openai' else 'prompt'
            self.log('   bots: provider does not accept the JSON schema, JSON mode: %s' % self.json_mode)
            return True
        return False

    def _count(self, input_, cache, output):
        k = self.usage
        k['request'] += 1
        k['input'] += int(input_ or 0)
        k['cache'] += int(cache or 0)
        k['output'] += int(output or 0)

    @staticmethod
    def _prompt_schema(system, schema):
        # schema in the system prompt (before the variable user text): goes into the provider's prefix cache
        return '%s\n\nReply with only one JSON object (no other text) that follows this JSON schema:\n%s' % (
            system, json.dumps(schema, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _messages(user):
        """User text or multi-turn conversation [{role, content}] (the agent's steps: the prefix stays the same at each step, goes into the cache)."""
        return list(user) if isinstance(user, list) else [{'role': 'user', 'content': user}]

    def _openai(self, system, user, schema, max_count, temperature, timestamp):
        if schema is not None and self.json_mode != 'schema':
            system = self._prompt_schema(system, schema)
        # wide limit: thinking models spend their thoughts from this limit too (only what is generated is paid for; Qwen3 was cut off at 1024)
        body = {'model': self.c['model'], 'messages': [{'role': 'system', 'content': system}] + self._messages(user),
                 'temperature': temperature, 'max_tokens': max(max_count * 8, 4096)}
        if self.c['uid'] == 'openai' or 'max_tokens' in self.jump_to:
            body['max_completion_tokens'] = body.pop('max_tokens')
        for p in self.jump_to:
            body.pop(p, None)
        if schema is not None and self.json_mode == 'schema':
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'response', 'schema': schema, 'strict': False}}
        elif schema is not None and self.json_mode == 'object':
            body['response_format'] = {'type': 'json_object'}
        d = _call(self.c, '/chat/completions', body, timestamp)
        u = d.get('usage') or {}
        self._count(u.get('prompt_tokens', 0), u.get('prompt_cache_hit_tokens')              # DeepSeek
                  or (u.get('prompt_tokens_details') or {}).get('cached_tokens', 0), u.get('completion_tokens', 0))   # OpenAI-compatible
        ch = (d.get('choices') or [{}])[0]
        text = (ch.get('message') or {}).get('content') or ''
        if not text.strip():
            raise ValueError('empty reply (%s)' % ch.get('finish_reason'))
        return text

    def _anthropic(self, system, user, schema, max_count, temperature, timestamp):
        if schema is not None and self.json_mode != 'schema':
            system = self._prompt_schema(system, schema)
        body = {'model': self.c['model'], 'max_tokens': max(max_count * 8, 2048), 'system': system,
                 'messages': self._messages(user), 'cache_control': {'type': 'ephemeral'}}   # prefix cache (system + steps)
        oc = {'effort': 'low'}              # chat line: deep thinking not needed (latency and cost)
        if schema is not None and self.json_mode == 'schema':
            oc['format'] = {'type': 'json_schema', 'schema': _anthropic_schema(schema)}
        body['output_config'] = oc
        if 'output_config' in self.jump_to:
            body.pop('output_config')
        d = _call(self.c, '/messages', body, timestamp)
        u = d.get('usage') or {}
        self._count(u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0),
                  u.get('cache_read_input_tokens', 0), u.get('output_tokens', 0))
        if d.get('stop_reason') == 'refusal':
            raise ValueError('the model refused to answer')
        text = ''.join(b.get('text', '') for b in d.get('content') or [] if b.get('type') == 'text')
        if not text.strip():
            raise ValueError('empty reply (%s)' % d.get('stop_reason'))
        return text


def client(slot=4, log=print):
    """The selected provider's client: llm_server.Server for the built-in model, Remote for every other provider."""
    c = selected()
    if c['uid'] == LOCAL:
        from . import llm_server as LS
        return LS.Server(slot, log)
    return Remote(c, log)


def test(log=print):
    """The panel's "Test" button (remote provider): a short question, so it also shows whether the bots can speak in the selected language -> {ok, startup_sec, duration_sec, response, provider}."""
    c = selected()
    s = Remote(c, log)
    t0 = time.time()
    s.launch()
    opening = time.time() - t0
    response, duration = s.ask('You are a pilot in a space game. Answer briefly.',
                        'A friend wrote "selam, nasılsın?". Give JSON: in answer a short reply in Turkish, in state the word "OK".',
                        schema={'type': 'object', 'properties': {'answer': {'type': 'string'}, 'state': {'type': 'string'}},
                              'required': ['answer', 'state']}, max_count=80)
    ok = 'OK' in str(response.get('state', '')).upper()
    return {'ok': ok, 'startup_sec': round(opening, 1), 'duration_sec': round(duration, 2), 'response': response.get('answer'), 'provider': s.name}
