"""Gelişmiş kipin dil modeli sağlayıcısı: dahili yerel model (llm_sunucu: llama-server + Qwen3 4B) ya da kullanıcının seçtiği bir
sağlayıcı (OpenAI, Anthropic, Gemini, DeepSeek ...; bilgisayardaki Ollama, LM Studio ya da başka bir OpenAI uyumlu sunucu).

Seçim tek ve genel: save/llm/saglayici.json {secili, saglayicilar: {kimlik: {anahtar, adres, model}}}. Anahtarlar bot paketlerine
girmez; panel onları yalnız maskeli gösterir. Uzak istemci Sunucu ile aynı arayüzü sunar (baslat, sor, durdur): Beyin ikisini ayırt
etmez. Dahili model yalnız İngilizce konuşur (Türkçede zayıf); öteki sağlayıcılarla botlar kendi dillerinde konuşur (cok_dilli).

JSON yanıt: OpenAI uyumlularda önce response_format json_schema, sağlayıcı reddederse json_object, o da olmazsa şema yalnız istemde;
inilen basamak istemcide kalır. Sağlayıcının tanımadığı parametre (temperature, max_tokens ...) 400 verirse o parametre bırakılıp
yeniden sorulur. Anthropic kendi Messages API'siyle (output_config.format) çağrılır.
"""
import json, os, re, threading, time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import paths as PTH

LOCAL = 'yerel'
# kimlik -> ad, tür ('openai' uyumlu ya da 'anthropic'), varsayılan adres ve model, anahtar gerekir mi, bilgisayarda mı çalışır
PROVIDERS = {
    LOCAL: dict(ad='Dahili yerel model (Qwen3 4B)', tur='dahili', adres='', model='', anahtar=False, yerel=True),
    'openai': dict(ad='OpenAI', tur='openai', adres='https://api.openai.com/v1', model='gpt-4.1-mini', anahtar=True, yerel=False),
    'anthropic': dict(ad='Anthropic Claude', tur='anthropic', adres='https://api.anthropic.com/v1', model='claude-haiku-5-5',
                      anahtar=True, yerel=False),
    'gemini': dict(ad='Google Gemini', tur='openai', adres='https://generativelanguage.googleapis.com/v1beta/openai',
                   model='gemini-2.5-flash', anahtar=True, yerel=False),
    'deepseek': dict(ad='DeepSeek', tur='openai', adres='https://api.deepseek.com/v1', model='deepseek-chat', anahtar=True, yerel=False),
    'openrouter': dict(ad='OpenRouter', tur='openai', adres='https://openrouter.ai/api/v1', model='openai/gpt-4.1-mini', anahtar=True,
                       yerel=False),
    'groq': dict(ad='Groq', tur='openai', adres='https://api.groq.com/openai/v1', model='llama-3.3-70b-versatile', anahtar=True,
                 yerel=False),
    'mistral': dict(ad='Mistral', tur='openai', adres='https://api.mistral.ai/v1', model='mistral-small-latest', anahtar=True,
                    yerel=False),
    'xai': dict(ad='xAI Grok', tur='openai', adres='https://api.x.ai/v1', model='grok-3-mini', anahtar=True, yerel=False),
    'ollama': dict(ad='Ollama', tur='openai', adres='http://127.0.0.1:11434/v1', model='qwen3:8b', anahtar=False, yerel=True),
    'lmstudio': dict(ad='LM Studio', tur='openai', adres='http://127.0.0.1:1234/v1', model='', anahtar=False, yerel=True),
    'ozel': dict(ad='Özel (OpenAI uyumlu)', tur='openai', adres='http://127.0.0.1:8080/v1', model='', anahtar=False, yerel=True),
}
_THINK = re.compile(r'<think>.*?</think>\s*', re.S)
_LOCK = threading.Lock()


class ProviderError(RuntimeError):
    """Kullanıcıya gösterilen hata (anahtar yanlış, model yok, sunucu kapalı ...)."""


def _route():
    return os.path.join(PTH.SAVE, 'llm', 'saglayici.json')


def setting():
    """{secili, saglayicilar: {kimlik: {anahtar, adres, model}}} (dosya yoksa dahili model)."""
    try:
        with open(_route(), encoding='utf8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    if d.get('secili') not in PROVIDERS:
        d['secili'] = LOCAL
    d['saglayicilar'] = {k: v for k, v in (d.get('saglayicilar') or {}).items() if k in PROVIDERS and isinstance(v, dict)}
    return d


def selected():
    """Seçili sağlayıcının tam ayarı {kimlik, tur, adres, model, anahtar}."""
    d = setting()
    return full(d['secili'], d['saglayicilar'].get(d['secili']) or {})


def full(uid, a):
    s = PROVIDERS[uid]
    return {'kimlik': uid, 'tur': s['tur'], 'adres': (a.get('adres') or s['adres']).rstrip('/'),
            'model': a.get('model') or s['model'], 'anahtar': a.get('anahtar') or ''}


def multilingual(uid=None):
    """Botlar kendi dillerinde konuşabilir mi (dahili Qwen3 4B yalnız İngilizce)."""
    return (uid or setting()['secili']) != LOCAL


def mask(key):
    return ('…' + key[-4:]) if len(key or '') > 8 else ('•••' if key else '')


def status():
    """Panelin görünümü: seçili sağlayıcı, her sağlayıcının adresi, modeli ve maskeli anahtarı."""
    d = setting()
    out = []
    for k, s in PROVIDERS.items():
        a = d['saglayicilar'].get(k) or {}
        out.append({'kimlik': k, 'ad': s['ad'], 'tur': s['tur'], 'anahtar_gerekir': s['anahtar'], 'yerel': s['yerel'],
                    'adres': a.get('adres') or s['adres'], 'model': a.get('model') or s['model'],
                    'varsayilan_adres': s['adres'], 'anahtar': mask(a.get('anahtar') or ''), 'anahtar_var': bool(a.get('anahtar'))})
    return {'secili': d['secili'], 'cok_dilli': multilingual(d['secili']), 'liste': out}


def save(uid, address=None, model=None, key=None, sec=True):
    """Sağlayıcının ayarını yaz; anahtar None ya da boşsa eskisi kalır ('-' siler)."""
    if uid not in PROVIDERS:
        raise ProviderError('Bilinmeyen sağlayıcı.')
    if address is not None:
        address = str(address).strip()
    if address and not re.fullmatch(r'https?://[^\s]+', address):
        raise ProviderError('Adres http:// ya da https:// ile başlamalı.')
    with _LOCK:
        d = setting()
        a = dict(d['saglayicilar'].get(uid) or {})
        if address is not None:
            a['adres'] = address
        if model is not None:
            a['model'] = str(model).strip()[:200]
        if key == '-':
            a.pop('anahtar', None)
        elif key:
            a['anahtar'] = str(key).strip()
        d['saglayicilar'][uid] = a
        if sec:
            d['secili'] = uid
        os.makedirs(os.path.dirname(_route()), exist_ok=True)
        temporary = _route() + '.tmp'
        with open(temporary, 'w', encoding='utf8') as fh:
            json.dump(d, fh, indent=1, ensure_ascii=False)
        os.replace(temporary, _route())
    return status()


# ------------------------------------------------------------------------------------------------------------ HTTP
def _headers(c):
    h = {'Content-Type': 'application/json', 'User-Agent': 'OpenOrbit'}
    if c['tur'] == 'anthropic':
        h.update({'x-api-key': c['anahtar'], 'anthropic-version': '2023-06-01'})
    elif c['anahtar']:
        h['Authorization'] = 'Bearer ' + c['anahtar']
    if c['kimlik'] == 'openrouter':
        h.update({'HTTP-Referer': 'https://github.com/OpenOrbit', 'X-Title': 'OpenOrbit'})
    return h


def _request(c, route, body=None, timestamp=60):
    req = Request(c['adres'] + route, data=None if body is None else json.dumps(body).encode('utf8'), headers=_headers(c),
                  method='GET' if body is None else 'POST')
    with urlopen(req, timeout=timestamp) as r:
        return json.loads(r.read() or b'{}')


class HttpError(ProviderError):
    def __init__(self, code, text):
        self.code, self.text = code, text
        super().__init__(_human_error(code, text))


def _human_error(code, text):
    """Sağlayıcının hata iletisi (dilden bağımsız: panel her dilde gösterir; iletiler çoğunlukla İngilizce)."""
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
        raise ProviderError('%s: %s' % (c['adres'], getattr(e, 'reason', e))) from None


def models(uid, address=None, key=None):
    """Sağlayıcının modelleri (/models). Anahtar verilmezse kayıtlıdır."""
    if uid not in PROVIDERS or uid == LOCAL:
        raise ProviderError('Bilinmeyen sağlayıcı.')
    a = dict(setting()['saglayicilar'].get(uid) or {})
    if address:
        a['adres'] = address
    if key:
        a['anahtar'] = key
    c = full(uid, a)
    d = _call(c, '/models' + ('?limit=100' if c['tur'] == 'anthropic' else ''), timestamp=20)
    entries = d.get('data') if isinstance(d, dict) else d
    names = [str(m.get('id') or m.get('name') or '') for m in entries or [] if isinstance(m, dict)]
    return sorted({re.sub(r'^models/', '', x) for x in names if x})


# ------------------------------------------------------------------------------------------------------------ istemci
def _anthropic_schema(s):
    """Anthropic yapılandırılmış çıktısının kabul ettiği şema: nesnelerde additionalProperties false; uzunluk ve adet sınırları atılır
    (istemdeki "kısa" yönergesi ve llm.py'nin süzgeci sınırlar)."""
    if isinstance(s, dict):
        out = {k: _anthropic_schema(v) for k, v in s.items() if k not in ('maxLength', 'minLength', 'maxItems', 'minItems')}
        if out.get('type') == 'object':
            out['additionalProperties'] = False
        return out
    if isinstance(s, list):
        return [_anthropic_schema(x) for x in s]
    return s


def _json(text):
    """Yanıttaki ilk JSON nesnesi (``` çiti, önündeki laf ya da ardındaki ikinci nesne atılır)."""
    text = _THINK.sub('', text or '')
    i = text.find('{')
    if i < 0:
        raise ValueError('yanıtta JSON yok')
    d = json.JSONDecoder(strict=False).raw_decode(text[i:])[0]       # strict=False: metin içinde ham satır sonu
    if not isinstance(d, dict):
        raise ValueError('yanıt JSON nesnesi değil')
    return d


class Remote:
    """Seçili uzak ya da bilgisayardaki sağlayıcı (Sunucu'nun arayüzü)."""

    def __init__(self, c, log=print):
        self.c, self.log = c, log
        self.name = '%s · %s' % (PROVIDERS[c['kimlik']]['ad'], c['model'] or '?')
        self.port = None
        self.ready = False
        self.json_mode = 'sema'              # sema -> nesne -> istem (sağlayıcı reddettikçe)
        self.jump_to = set()                   # sağlayıcının tanımadığı parametreler
        self.wait = 0.0                    # 429'dan sonra bu ana dek istek yok (işler kalıplara düşer)
        self.usage = {'istek': 0, 'girdi': 0, 'onbellek': 0, 'cikti': 0}     # token sayımı (önbellekten gelen girdi ayrı)

    def launch(self, wait_sec=None):
        if PROVIDERS[self.c['kimlik']]['anahtar'] and not self.c['anahtar']:
            raise ProviderError('API anahtarı girilmemiş.')
        if not self.c['model']:
            raise ProviderError('Model seçilmemiş.')
        try:                                # bağlantı ve anahtar denetimi: HTTP hatası durdurur, modelin tek bozuk yanıtı durdurmaz
            self.ask('Reply with JSON.', 'Say hi.', schema={'type': 'object', 'properties': {'cevap': {'type': 'string'}},
                                                          'required': ['cevap']}, max_count=40, timestamp=60)
        except ValueError as e:
            self.log('   botlar: sağlayıcının deneme yanıtı bozuk (%s), yine de açılıyor' % e)
        self.ready = True
        return self

    def stop(self):
        self.ready = False

    def ask(self, system, user, schema=None, max_count=220, temperature=0.8, timestamp=60):
        """Tek çağrı -> (metin ya da JSON nesnesi, süre sn)."""
        if time.time() < self.wait:
            raise ProviderError('istek sınırı: bekleniyor')
        t0 = time.time()
        for _ in range(4):                  # her 400'de bir parametre ya da JSON basamağı düşer
            try:
                text = (self._anthropic if self.c['tur'] == 'anthropic' else self._openai)(system, user, schema, max_count, temperature,
                                                                                            timestamp)
                break
            except HttpError as e:
                if e.code == 429:
                    self.wait = time.time() + 20
                    raise
                if e.code != 400 or not self._adapt(e.text, schema):
                    raise
        else:
            raise ProviderError('sağlayıcı isteği kabul etmedi')
        return (_json(text) if schema is not None else _THINK.sub('', text).strip()), time.time() - t0

    def _adapt(self, text, schema):
        """400 yanıtına göre isteği değiştir -> yeniden denenebilir mi."""
        m = text.lower()
        if self.c['tur'] == 'anthropic' and 'effort' in m and 'output_config' not in self.jump_to:
            self.jump_to.add('output_config')          # eski model: effort yok (şema da istemde)
            self.json_mode = 'istem'
            return True
        for p in ('temperature', 'top_p', 'max_tokens', 'max_completion_tokens'):
            if p in m and p not in self.jump_to:
                self.jump_to.add(p)
                self.log('   botlar: sağlayıcı %s kabul etmiyor, onsuz soruluyor' % p)
                return True
        if schema is not None and self.json_mode != 'istem' and re.search(r'response_format|json_schema|json_object|output_config|'
                                                                       r'schema|format', m):
            self.json_mode = 'nesne' if self.json_mode == 'sema' and self.c['tur'] == 'openai' else 'istem'
            self.log('   botlar: sağlayıcı JSON şemasını kabul etmiyor, JSON kipi: %s' % self.json_mode)
            return True
        return False

    def _count(self, input_, cache, output):
        k = self.usage
        k['istek'] += 1
        k['girdi'] += int(input_ or 0)
        k['onbellek'] += int(cache or 0)
        k['cikti'] += int(output or 0)

    @staticmethod
    def _prompt_schema(system, schema):
        # şema sistem isteminde (değişken kullanıcı metninin önünde): sağlayıcının önek önbelleğine girer
        return '%s\n\nReply with only one JSON object (no other text) that follows this JSON schema:\n%s' % (
            system, json.dumps(schema, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _messages(user):
        """Kullanıcı metni ya da çok turlu konuşma [{role, content}] (ajanın adımları: önek her adımda aynı kalır, önbelleğe girer)."""
        return list(user) if isinstance(user, list) else [{'role': 'user', 'content': user}]

    def _openai(self, system, user, schema, max_count, temperature, timestamp):
        if schema is not None and self.json_mode != 'sema':
            system = self._prompt_schema(system, schema)
        # sınır geniş: düşünen modeller düşünceyi de bu sınırdan harcar (yalnız üretilen kadar ödenir; Qwen3 1024'te kesiliyordu)
        body = {'model': self.c['model'], 'messages': [{'role': 'system', 'content': system}] + self._messages(user),
                 'temperature': temperature, 'max_tokens': max(max_count * 8, 4096)}
        if self.c['kimlik'] == 'openai' or 'max_tokens' in self.jump_to:
            body['max_completion_tokens'] = body.pop('max_tokens')
        for p in self.jump_to:
            body.pop(p, None)
        if schema is not None and self.json_mode == 'sema':
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'yanit', 'schema': schema, 'strict': False}}
        elif schema is not None and self.json_mode == 'nesne':
            body['response_format'] = {'type': 'json_object'}
        d = _call(self.c, '/chat/completions', body, timestamp)
        u = d.get('usage') or {}
        self._count(u.get('prompt_tokens', 0), u.get('prompt_cache_hit_tokens')              # DeepSeek
                  or (u.get('prompt_tokens_details') or {}).get('cached_tokens', 0), u.get('completion_tokens', 0))   # OpenAI uyumlu
        ch = (d.get('choices') or [{}])[0]
        text = (ch.get('message') or {}).get('content') or ''
        if not text.strip():
            raise ValueError('boş yanıt (%s)' % ch.get('finish_reason'))
        return text

    def _anthropic(self, system, user, schema, max_count, temperature, timestamp):
        if schema is not None and self.json_mode != 'sema':
            system = self._prompt_schema(system, schema)
        body = {'model': self.c['model'], 'max_tokens': max(max_count * 8, 2048), 'system': system,
                 'messages': self._messages(user), 'cache_control': {'type': 'ephemeral'}}   # önek önbelleği (sistem + adımlar)
        oc = {'effort': 'low'}              # sohbet satırı: derin düşünme gerekmez (gecikme ve maliyet)
        if schema is not None and self.json_mode == 'sema':
            oc['format'] = {'type': 'json_schema', 'schema': _anthropic_schema(schema)}
        body['output_config'] = oc
        if 'output_config' in self.jump_to:
            body.pop('output_config')
        d = _call(self.c, '/messages', body, timestamp)
        u = d.get('usage') or {}
        self._count(u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0),
                  u.get('cache_read_input_tokens', 0), u.get('output_tokens', 0))
        if d.get('stop_reason') == 'refusal':
            raise ValueError('model yanıtlamayı reddetti')
        text = ''.join(b.get('text', '') for b in d.get('content') or [] if b.get('type') == 'text')
        if not text.strip():
            raise ValueError('boş yanıt (%s)' % d.get('stop_reason'))
        return text


def client(slot=4, log=print):
    """Seçili sağlayıcının istemcisi: dahili model için llm_sunucu.Sunucu, öteki her sağlayıcı için Uzak."""
    c = selected()
    if c['kimlik'] == LOCAL:
        from . import llm_server as LS
        return LS.Server(slot, log)
    return Remote(c, log)


def test(log=print):
    """Panelin "Test et" düğmesi (uzak sağlayıcı): kısa bir soru, botların seçilen dilde konuşabildiği de görülsün -> {ok, sure, yanit}."""
    c = selected()
    s = Remote(c, log)
    t0 = time.time()
    s.launch()
    opening = time.time() - t0
    response, duration = s.ask('You are a pilot in a space game. Answer briefly.',
                        'A friend wrote "selam, nasılsın?". Give JSON: in cevap a short reply in Turkish, in durum the word "TAMAM".',
                        schema={'type': 'object', 'properties': {'cevap': {'type': 'string'}, 'durum': {'type': 'string'}},
                              'required': ['cevap', 'durum']}, max_count=80)
    ok = 'TAMAM' in str(response.get('durum', '')).upper()
    return {'ok': ok, 'acilis_sn': round(opening, 1), 'sure_sn': round(duration, 2), 'yanit': response.get('cevap'), 'saglayici': s.name}
