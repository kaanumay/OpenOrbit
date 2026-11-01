"""Botlar sayfasının deposu (panel.py'nin /api/bot… uçları; belgeler/BOTLAR.md).

Bot paketi save/botlar/<kimlik>.json:
  {surum, ad, aciklama, dunya, kip ('basit' | 'normal' | 'gelismis'), gelisim ('progressive' | 'jumpstart'), tohum, dil,
   firma_dagilimi [MMO, EIC, VRU], ayarlar {...}, kadro [{no, ad, firma, kisilik}], olusturma, guncelleme}
Paketin ilerlemesi save/botlar/<kimlik>/durum.json'da (oyun sunucusu yazar: bot/manager.py); paket silinince ikisi de
_silinenler'e taşınır. Bir dünyaya en çok bir paket atanır (OYNA o dünyanın paketiyle açar: DO_BOT).
Kadro oluşturulurken bir kez üretilir (bot/kisilik.kadro_uret, tohumlu): her girişte aynı botlar.
"""
import copy, datetime, json, os, random, re, shutil, threading

import paths as PTH
import name_log as NL
from lang import t as _

VERSION = 1
MODES = ('basit', 'normal', 'gelismis')
PROGRESSIONS = ('progressive', 'jumpstart')
from bot.language_data import CODES as _CODES
from bot import llm_provider as PRV
LANGUAGES = ('karisik',) + _CODES          # adların ve sohbetin dili (bot/languages/<kod>.json); karışık: her bot adının dilinde
NAME_LENGTH, DESCRIPTION_LENGTH = 40, 240
COUNT_MIN, COUNT_MAX = 1, 3000
_LOCK = threading.Lock()

# ayar -> (tür, en az, en çok, varsayılan); bot/yonetici.VARSAYILAN ile aynı anahtarlar
SETTINGS = {
    'hiz': ('sayi', 0.1, 20.0, 1.0),
    'cevrimici_oran': ('sayi', 0.05, 2.0, 0.6),
    'en_cok_cevrimici': ('tam', 0, 3000, 0),
    'telafi_saat': ('tam', 0, 48, 4),
    'telafi_oran': ('sayi', 0.0, 1.0, 0.35),
    'kayit_sn': ('tam', 0, 300, 15),
    'jumpstart_saat': ('tam', 1, 2000, 60),
    'pvp_seviye': ('tam', 1, 32, 6),
    'yabanci_harita': ('bool', None, None, True),
    'sohbet_dk': ('tam', 0, 60, 6),
    'yardim_en_cok': ('tam', 0, 20, 3),
    'somut_en_cok': ('tam', 1, 150, 40),
    'klan_basina': ('tam', 3, 100, 12),
    'kaba_sohbet': ('tam', 0, 3, 1),
    'moderator': ('bool', None, None, False),
    'mod_sayisi': ('tam', 1, 10, 2),
    'kural_buyuk': ('bool', None, None, True),
    'kural_sel': ('bool', None, None, True),
    'kural_hakaret': ('bool', None, None, True),
    'kural_reklam': ('bool', None, None, True),
    'sustur_dk': ('tam', 1, 1440, 10),
    'yasak_esik': ('tam', 1, 10, 3),
    'yasak_saat': ('tam', 1, 720, 24),
    'prime_baslangic': ('tam', 0, 23, 19),
    'prime_bitis': ('tam', 0, 23, 23),
    'prime_pvp': ('sayi', 1.0, 5.0, 2.0),
    'buyuk_savas': ('bool', None, None, True),
    'basit_guc': ('sayi', 0.3, 3.0, 1.0),
    'basit_dost': ('sayi', 0.0, 1.0, 0.5),
    'llm_toplu': ('tam', 1, 16, 4),
    'llm_sohbet': ('bool', None, None, True),
    'llm_karar_dk': ('tam', 0, 120, 10),
    'llm_ajan': ('bool', None, None, True),            # güçlü sağlayıcıda araç döngüsü (bot/ajan.py)
    'llm_ajan_adim': ('tam', 1, 10, 3),
    'llm_saatlik': ('tam', 0, 20000, 200),             # bütün dil modeli isteklerinin saatlik sınırı (0: sınırsız)
}
PERMISSIONS = ('magaza', 'gorev', 'pvp', 'oyuncuya_saldir', 'sohbet', 'klan', 'klan_kur', 'arkadas', 'grup', 'muzayede', 'yardim', 'kutu_calma', 'kargo', 'roket', 'ozel_cephane', 'ekstra', 'mayin', 'lab', 'skylab', 'teknoloji', 'ganimet', 'assembly', 'kapi', 'etkinlik', 'modlar', 'klan_diplomasi', 'klan_emir', 'kapi_dolgu', 'klan_ksi')
SIMPLE_CLASSES = ('X-1', 'X-2', 'X-3', 'X-4', '4-X', 'X-5', 'X-6', 'X-7', 'X-8', '4-5')


class BotError(ValueError):
    """Kullanıcıya gösterilen hata (panel.py 400 döner)."""


def folder():
    return os.path.join(PTH.SAVE, 'botlar')


def _route(pid):
    if not isinstance(pid, str) or not re.fullmatch(r'[a-z0-9_]{1,40}', pid):
        raise BotError(_('Bot paketi bulunamadı.'))
    return os.path.join(folder(), pid + '.json')


def state_path(pid):
    _route(pid)                                         # kimlik denetimi: '..' gibi bir kimlik paket klasörünün dışına çıkamaz
    return os.path.join(folder(), pid, 'durum.json')


def file_path(pid):
    """Sunucunun paket dosyası (DO_BOT) ya da None."""
    if not pid:
        return None
    try:
        p = _route(pid)
    except BotError:
        return None
    return p if os.path.isfile(p) else None


def _read_file(p):
    try:
        with open(p, encoding='utf8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def read(pid):
    d = _read_file(_route(pid))
    if d is None:
        raise BotError(_('Bot paketi bulunamadı.'))
    return d


def _save(pid, d):
    os.makedirs(folder(), exist_ok=True)
    d['surum'] = VERSION
    d['guncelleme'] = _now()
    p = _route(pid)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def var(pid):
    return file_path(pid) is not None


# ------------------------------------------------------------------ doğrulama
def clean_settings(a, old=None):
    """Panelin gönderdiği ayarlar -> geçerli değerler (bilinmeyen anahtarlar atılır, sayılar sınırlara çekilir)."""
    out = copy.deepcopy(old) if old else {}
    a = a if isinstance(a, dict) else {}
    for k, (kind, lo, hi, vars_) in SETTINGS.items():
        if k not in a:
            out.setdefault(k, vars_)
            continue
        v = a[k]
        try:
            if kind == 'bool':
                v = bool(v)
            elif kind == 'tam':
                v = max(lo, min(hi, int(v)))
            else:
                v = round(max(lo, min(hi, float(v))), 3)
        except (TypeError, ValueError):
            v = out.get(k, vars_)
        out[k] = v
    trace = dict(out.get('izinler') or {})
    for k in PERMISSIONS:
        if isinstance(a.get('izinler'), dict) and k in a['izinler']:
            trace[k] = bool(a['izinler'][k])
        trace.setdefault(k, True)
    out['izinler'] = trace
    fg = a.get('firma_guc', out.get('firma_guc', [1.0, 1.0, 1.0]))
    try:
        out['firma_guc'] = [round(max(0.2, min(5.0, float(x))), 2) for x in list(fg)[:3]] + [1.0] * (3 - len(list(fg)[:3]))
    except (TypeError, ValueError):
        out['firma_guc'] = [1.0, 1.0, 1.0]
    game_settings = a.get('oyun_ayari', out.get('oyun_ayari'))            # botların oyun ayarı profili (bot/oyun_ayari.py)
    from bot import game_settings as GS
    import settings as SET
    if not isinstance(game_settings, dict) or game_settings.get('profil') not in GS.PROFILES:
        game_settings = {'profil': 'standart', 'degerler': {}}
    value = {}
    for k, v in (game_settings.get('degerler') or {}).items():
        s = SET.BY_KEY.get(k)
        if k in GS.FIELDS and s:
            try:
                value[k] = round(max(s.get('min', 0.0), min(s.get('max', 50.0), float(v))), 3)
            except (TypeError, ValueError):
                pass
    out['oyun_ayari'] = {'profil': game_settings['profil'], 'degerler': value}
    bh = a.get('basit_haritalar', out.get('basit_haritalar'))
    if isinstance(bh, dict):
        out['basit_haritalar'] = {s: max(0, min(20, int(bh.get(s, 0) or 0))) for s in SIMPLE_CLASSES}
    else:
        from bot import simple
        out['basit_haritalar'] = dict(simple.DEFAULT_MAPS)
    return out


def _clean_name(name):
    name = ' '.join(str(name or '').split())[:NAME_LENGTH]
    if not name:
        raise BotError(_('Bot paketine bir ad ver.'))
    return name


def _new_id(name):
    tr = str.maketrans('çğıöşüâîûÇĞİÖŞÜ', 'cgiosuaiuCGIOSU')
    k = re.sub(r'[^a-z0-9]+', '_', name.translate(tr).lower()).strip('_')[:30] or 'botlar'
    pid, n = k, 2
    while os.path.exists(_route(pid)):
        pid, n = '%s_%d' % (k, n), n + 1
    return pid


def _distribution(company_dist):
    try:
        company_dist = [max(0, int(x)) for x in list(company_dist)[:3]]
    except (TypeError, ValueError):
        company_dist = [1, 1, 1]
    return company_dist if len(company_dist) == 3 and sum(company_dist) > 0 else [1, 1, 1]


def generate_roster(seed, count, distribution, lang, existing=(), name_lang=None, special=(), d=None):
    """d: paket; ad kaynağı DOStats ise adlar gerçek oyunculardan, adlardaki klan etiketleri d['klan_etiketleri']."""
    from bot import personality as PS
    pool = None
    if d is not None and d.get('ad_kaynagi') == 'dostats':
        from bot import dostats as DS
        try:
            pool = DS.names([name_lang] if name_lang in LANGUAGES[1:] else list(DS.SERVERS))
        except OSError:
            raise BotError(_("DOStats'a ulaşılamadı. Ad kaynağını Üretilen yap ya da sonra yeniden dene."))
        d['klan_etiketleri'] = DS.tags(pool)[:300]
    return PS.generate_roster(seed, count, company_distribution=distribution, lang=lang if lang in LANGUAGES else 'karisik', existing=existing,
                         name_lang=name_lang if name_lang in LANGUAGES else None, special=special, pool=pool)


CUSTOM_MAX = 500
NAME_SOURCES = ('uretim', 'dostats')      # adlar: üretici (gerçek sunucu üslubu) ya da dostats.info'daki gerçek oyuncular
_COMPANY_NAME = {'mmo': 1, 'eic': 2, 'vru': 3}
_ARCHETYPE_NAME = {'grinder': 'kasici', 'pve': 'kasici', 'hunter': 'avci', 'pvp': 'avci', 'social': 'sosyal', 'trader': 'tuccar',
               'quester': 'gorevci', 'casual': 'rahat', 'leader': 'lider', 'kasıcı': 'kasici', 'avcı': 'avci', 'tüccar': 'tuccar',
               'görevci': 'gorevci'}


def parse_custom(text, used=()):
    """Kullanıcının kendi bot listesi (satır başına "ad[, firma][, davranış][, dil]"; virgül, noktalı virgül ya da sekme; # yorum)
    -> [{ad, firma?, arketip?, dil?}] (oyuncu isteği 2026-10-30). Hatalı satır BotHatasi (satır numarasıyla); kullanılan adlar
    (oyuncular) ve tekrar reddedilir."""
    from bot import personality as PS
    out, seen = [], {str(a).lower() for a in used}
    for i, row in enumerate(str(text or '').splitlines(), 1):
        part = [x.strip() for x in re.split(r'[,;\t]', row) if x.strip()]
        if not part or part[0].startswith('#'):
            continue
        name = part[0]
        if not PS.NAME_PATTERN.match(name):
            raise BotError(_('{0}. satır: "{1}" geçerli bir ad değil (3-20 harf, rakam, _ . -).').format(i, name))
        if name.lower() in seen:
            raise BotError(_('{0}. satır: "{1}" adı zaten kullanılıyor.').format(i, name))
        seen.add(name.lower())
        o = {'ad': name}
        for x in part[1:]:
            k = x.lower()
            if k in _COMPANY_NAME and 'firma' not in o:
                o['firma'] = _COMPANY_NAME[k]
            elif (k in PS.ARCHETYPES or k in _ARCHETYPE_NAME) and 'arketip' not in o:
                o['arketip'] = _ARCHETYPE_NAME.get(k, k)
            elif k in LANGUAGES and k != 'karisik' and 'dil' not in o:
                o['dil'] = k
            else:
                raise BotError(_('{0}. satır: "{1}" anlaşılamadı (firma: MMO, EIC, VRU; davranış: {2}; dil: {3}).').format(
                    i, x, ', '.join(PS.ARCHETYPES), ', '.join(d for d in LANGUAGES if d != 'karisik')))
        out.append(o)
        if len(out) > CUSTOM_MAX:
            raise BotError(_('En çok {0} özel bot.').format(CUSTOM_MAX))
    return out


def _custom_lang(d, summary):
    """Dahili dil modeli yalnız İngilizce: Gelişmiş kipte özel botun dili de İngilizce (bot/llm.py)."""
    if d.get('kip') == 'gelismis' and not PRV.multilingual():
        return [dict(o, dil='en') if o.get('dil') else o for o in summary]
    return summary


def name_lang(d):
    """Paketin ad dili (eski paketlerde ad ve sohbet tek ayardı)."""
    return d.get('ad_dili') or d.get('dil') or 'karisik'


def apply_chat_lang(d):
    """Sohbet dili değişti: var olan botlar da yeni dilde konuşur (karışık: her bot adının dilinde). Adlar değişmez."""
    for x in d['kadro']:
        k = x['kisilik']
        k.setdefault('ad_dili', k.get('dil'))
        k['dil'] = d['dil'] if d['dil'] in LANGUAGES[1:] else (k.get('ad_dili') or k.get('dil') or 'en')


def _count(d):
    """Basit kipte kadro harita yerlerinin sayısı kadar."""
    if d.get('kip') == 'basit':
        from bot import simple
        return max(1, simple.slot_count(d['ayarlar'].get('basit_haritalar') or simple.DEFAULT_MAPS))
    return None


# ------------------------------------------------------------------ depo
def create(name, description='', world=None, mode='normal', progression='progressive', count=60, lang='karisik', company_distribution=(1, 1, 1),
            settings=None, players=(), name_lang_=None, special='', name_source=None):
    """Yeni paket: kadro tohumla üretilir (oyuncuların adları kullanılmaz)."""
    if mode not in MODES:
        raise BotError(_('Bilinmeyen bot kipi.'))
    with _LOCK:
        name = _clean_name(name)
        pid = _new_id(name)
        if mode == 'gelismis' and not PRV.multilingual():
            lang = 'en'                         # dahili dil modeli yalnız İngilizce (bot/llm.py; başka sağlayıcıda serbest)
        d = {'ad': name, 'aciklama': str(description or '')[:DESCRIPTION_LENGTH], 'dunya': None, 'kip': mode,
             'gelisim': progression if progression in PROGRESSIONS else 'progressive', 'tohum': random.randrange(1, 2 ** 31),
             'dil': lang if lang in LANGUAGES else 'karisik', 'ad_dili': name_lang_ if name_lang_ in LANGUAGES else 'karisik',
             'firma_dagilimi': _distribution(company_distribution), 'ad_kaynagi': name_source if name_source in NAME_SOURCES else 'uretim',
             'ayarlar': clean_settings(settings or {}), 'olusturma': _now()}
        summary = _custom_lang(d, parse_custom(special, players))
        n = max(len(summary), _count(d) or max(COUNT_MIN, min(COUNT_MAX, int(count or 60))))
        d['kadro'] = generate_roster(d['tohum'], n, d['firma_dagilimi'], d['dil'], players, d['ad_dili'], summary, d)
        _save(pid, d)
    if world:
        assign(pid, world)
    return pid


def update(pid, name=None, description=None, mode=None, progression=None, settings=None):
    with _LOCK:
        d = read(pid)
        if name is not None:
            d['ad'] = _clean_name(name)
        if description is not None:
            d['aciklama'] = str(description)[:DESCRIPTION_LENGTH]
        old_mode = d['kip']
        if mode is not None:
            if mode not in MODES:
                raise BotError(_('Bilinmeyen bot kipi.'))
            d['kip'] = mode
        if progression is not None and progression in PROGRESSIONS:
            d['gelisim'] = progression
        if settings is not None:
            d['ayarlar'] = clean_settings(settings, d.get('ayarlar'))
        n = _count(d)
        if n is not None and (n != len(d['kadro']) or old_mode != d['kip']):
            d['kadro'] = _resize(d, n)
        _save(pid, d)


def _resize(d, n, players=()):
    """Kadro n bota: fazlası sondan çıkar, eksik yeni botlarla (aynı tohumdan devam; var olanların adı ve kişiliği değişmez)."""
    k = d['kadro'][:n]
    if len(k) < n:
        extra = generate_roster(d['tohum'] + len(k) * 7919, n - len(k), d['firma_dagilimi'], d.get('dil', 'karisik'),
                        [x['ad'] for x in k] + list(players), name_lang(d), d=d)
        last = max([x['no'] for x in k], default=0)
        for i, x in enumerate(extra, 1):
            x['no'] = last + i
        k += extra
    return k


def roster(pid, count=None, lang=None, company_distribution=None, regenerate=False, players=(), name_lang_=None, special='', name_source=None):
    """Kadroyu boyutla (adet) ya da baştan üret (yeniden: yeni tohum, ilerleme sıfırlanır). Sohbet dili var olan botlara hemen
    uygulanır; ad dili yeni eklenen botlara ve baştan üretime (var olanların adı değişmez). ozel: kullanıcının kendi botları
    (ozel_cozumle): baştan üretimde kadronun başında; değilse kadroda adı olmayanlar sona eklenir."""
    with _LOCK:
        d = read(pid)
        if name_lang_ in LANGUAGES:
            d['ad_dili'] = name_lang_
        elif not d.get('ad_dili'):
            d['ad_dili'] = d.get('dil') or 'karisik'
        if name_source in NAME_SOURCES:
            d['ad_kaynagi'] = name_source           # yeni eklenen botlara ve baştan üretime (var olanların adı değişmez)
        if d.get('kip') == 'gelismis' and not PRV.multilingual():
            lang = 'en'                         # dahili dil modeli yalnız İngilizce (bot/llm.py; başka sağlayıcıda serbest)
        if lang in LANGUAGES and lang != d.get('dil'):
            d['dil'] = lang
            apply_chat_lang(d)
        if company_distribution is not None:
            d['firma_dagilimi'] = _distribution(company_distribution)
        n = _count(d) or max(COUNT_MIN, min(COUNT_MAX, int(count or len(d['kadro']))))
        old_backups = [x['ad'] for x in d['kadro']]
        summary = _custom_lang(d, parse_custom(special, players))
        if regenerate:
            d['tohum'] = random.randrange(1, 2 ** 31)
            d['kadro'] = generate_roster(d['tohum'], max(n, len(summary)), d['firma_dagilimi'], d['dil'], players, d['ad_dili'], summary, d)
            outgoing = old_backups                              # baştan üretim: eski pilotların hepsi gider
        else:
            d['kadro'] = _resize(d, n, players)
            outgoing = old_backups[n:]                          # azaltma: sondakiler gider
            var = {x['ad'].lower() for x in d['kadro']}
            new_ = [o for o in summary if o['ad'].lower() not in var]
            if new_:                                     # eklenen özel botlar sona (var olanlar değişmez)
                extra = generate_roster(d['tohum'] + len(d['kadro']) * 7919, len(new_), d['firma_dagilimi'], d['dil'],
                                list(var) + list(players), name_lang(d), new_, d)
                last = max([x['no'] for x in d['kadro']], default=0)
                for i, x in enumerate(extra, 1):
                    x['no'] = last + i
                d['kadro'] += extra
        _save(pid, d)
    NL.add([{'tur': 'sil', 'ad': a} for a in outgoing])
    if regenerate:
        reset(pid, event=False)


# ------------------------------------------------------------------ botun ayrıntısı ve düzenlenmesi (bot/duzenle.py)
_CATALOG = None


def edit_catalog():
    global _CATALOG
    if _CATALOG is None:
        from bot import edit as ED
        _CATALOG = ED.catalog()
    return _CATALOG


def edit_error(e):
    """bot/duzenle.DuzenlemeHatasi -> panelin dilinde ileti."""
    return {'deger': _('Geçersiz değer: %s', e.area), 'aralik': _('Değer sınırların dışında: %s', e.area),
            'esya': _('Bilinmeyen eşya: %s', e.area), 'yok': _('Bulunamadı: %s', e.area),
            'durum_yok': _('Bu bot henüz oyunda görünmedi: yalnız kişiliği düzenlenebilir.'),
            'cevrimici': _('Çevrimiçi botun haritası değiştirilemez: çevrimdışı olunca dene.')}.get(e.code, str(e))


def _roster_row(d, no):
    x = next((x for x in d['kadro'] if x['no'] == int(no)), None)
    if x is None:
        raise BotError(_('Bot bulunamadı.'))
    return x


def bot_detail(pid, no):
    """Oyun kapalıyken: botun son kayıttaki bütün durumu (bot/duzenle.gorunum)."""
    from bot import edit as ED
    d = read(pid)
    t, c = live(pid)
    return ED.appearance(c.get(int(no)), _roster_row(d, no))


def bot_personality(pid, no, traits):
    """Botun kişiliği (kadro satırı): oyun açıkken de paket dosyasına yazılır (yönetici sonraki açılışta kadrodan okur)."""
    from bot import edit as ED
    with _LOCK:
        d = read(pid)
        try:
            ED.apply(None, _roster_row(d, no), {'ozellik': traits})
        except ED.EditError as e:
            raise BotError(edit_error(e)) from None
        _save(pid, d)


def edit_bot(pid, no, value):
    """Oyun kapalıyken: durum dosyasındaki botu (ve kişiliği için paketi) düzenle -> yeni görünüm."""
    from bot import edit as ED
    with _LOCK:
        d = read(pid)
        roster_row = _roster_row(d, no)
        route = state_path(pid)
        all_candidates = _read_file(route) or {}
        k = (all_candidates.get('botlar') or {}).get(str(int(no)))
        try:
            ED.apply(k, roster_row, value)
        except ED.EditError as e:
            raise BotError(edit_error(e)) from None
        if k is not None and any(a != 'ozellik' for a in value):
            os.makedirs(os.path.dirname(route), exist_ok=True)
            with open(route + '.tmp', 'w', encoding='utf8') as fh:
                json.dump(all_candidates, fh, ensure_ascii=False, separators=(',', ':'))
            os.replace(route + '.tmp', route)
        if 'ozellik' in value:
            _save(pid, d)
    return bot_detail(pid, no)


def bot_name(pid, no, name, players=()):
    """Bir botun adını değiştir (ilerlemesi kalır)."""
    from bot import personality as PS
    name = str(name or '').strip()
    if not PS.NAME_PATTERN.match(name):
        raise BotError(_('Ad 3-20 karakter olmalı: harf, rakam, _ . -'))
    with _LOCK:
        d = read(pid)
        if any(x['ad'].lower() == name.lower() and x['no'] != no for x in d['kadro']) or name.lower() in {str(o).lower() for o in players}:
            raise BotError(_('Bu ad kullanılıyor.'))
        x = next((x for x in d['kadro'] if x['no'] == int(no)), None)
        if x is None:
            raise BotError(_('Bot bulunamadı.'))
        old, x['ad'] = x['ad'], name
        _save(pid, d)
        if old != name:
            NL.add([{'tur': 'ad', 'eski': old, 'yeni': name}])      # klanlar, rehberler, hafızalar (oyun uygular)


def reset(pid, event=True):
    """Paketin ilerlemesini sil (botlar baştan başlar; jumpstart'ta yeniden dağıtılır). Botlar klanlardan çıkar (oyuncunun klanı
    dahil: ad_kaydi 'klan_cik'); adları ve tanışıklıkları kalır."""
    if event:
        NL.add([{'tur': 'klan_cik', 'ad': x['ad']} for x in read(pid)['kadro']])
    p = state_path(pid)
    for f in (p, os.path.join(os.path.dirname(p), 'klanlar.json')):
        if os.path.isfile(f):
            os.remove(f)


def remove(pid):
    """Paket _silinenler'e taşınır; botları her yerden çıkar (klanlar, rehberler: ad_kaydi, oyun sonraki açılışta uygular)."""
    p = _route(pid)
    if not os.path.isfile(p):
        raise BotError(_('Bot paketi bulunamadı.'))
    NL.add([{'tur': 'sil', 'ad': x['ad']} for x in read(pid)['kadro']])
    target = os.path.join(folder(), '_silinenler')
    os.makedirs(target, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    os.replace(p, os.path.join(target, '%s_%s.json' % (pid, timestamp)))
    dz = os.path.join(folder(), pid)
    if os.path.isdir(dz):
        shutil.move(dz, os.path.join(target, '%s_%s' % (pid, timestamp)))


def assign(pid, world):
    """Paketi bir dünyaya ata (o dünyanın önceki paketi boşa çıkar); dunya None: atamayı kaldır."""
    with _LOCK:
        d = read(pid)
        if world:
            for x in list_ids():
                if x != pid:
                    o = _read_file(_route(x))
                    if o and o.get('dunya') == world:
                        o['dunya'] = None
                        _save(x, o)
        d['dunya'] = world or None
        _save(pid, d)


def list_ids():
    if not os.path.isdir(folder()):
        return []
    return [f[:-5] for f in os.listdir(folder()) if f.endswith('.json') and not f.startswith('_')
            and re.fullmatch(r'[a-z0-9_]{1,40}', f[:-5])]


def world_pack(world):
    """Dünyanın paketi (kimlik) ya da None."""
    for pid in list_ids():
        d = _read_file(_route(pid))
        if d and d.get('dunya') == world:
            return pid
    return None


# ------------------------------------------------------------------ özetler
def live_llm(pid):
    """Sunucunun son kaydındaki dil modeli kullanımı (bot/llm.Beyin.ozet) ya da None."""
    return (_read_file(state_path(pid)) or {}).get('llm')


def live(pid):
    """Sunucunun son kaydı: no -> bot durumu (seviye, gemi, harita, klan, istatistik) ve kaydın anı."""
    d = _read_file(state_path(pid)) or {}
    return d.get('t'), {int(k): v for k, v in (d.get('botlar') or {}).items()}


def summary(pid):
    d = read(pid)
    t, c = live(pid)
    companies = [sum(1 for x in d['kadro'] if x['firma'] == f) for f in (1, 2, 3)]
    levels = [c[x['no']].get('seviye', 1) for x in d['kadro'] if x['no'] in c]
    return {'id': pid, 'ad': d['ad'], 'aciklama': d.get('aciklama', ''), 'dunya': d.get('dunya'), 'kip': d['kip'],
            'gelisim': d.get('gelisim'), 'adet': len(d['kadro']), 'firmalar': companies, 'guncelleme': d.get('guncelleme'),
            'son_oyun': t, 'seviye_ort': round(sum(levels) / len(levels), 1) if levels else None,
            'seviye_enb': max(levels) if levels else None}


def entries():
    out = []
    for pid in list_ids():
        try:
            out.append(summary(pid))
        except BotError:
            pass
    out.sort(key=lambda x: x['guncelleme'] or '', reverse=True)
    return out


def _memory(s):
    """Botun aklındakiler (bot/memories.py, bot/agent.py; güçlü sağlayıcı): açık hedefleri, bekleyen sözleri, izlenimleri, en yeni
    anıları -> yoksa None."""
    memories = s.get('anilar') or []
    out = {'defter': [x['metin'] for x in s.get('defter') or [] if not x.get('bitti')],
           'bekleyen': [{'kim': a['kim'], 'amac': a['takip']['amac'], 'ozet': a['ozet'], 'vade': a['takip'].get('vade')}
                        for a in memories if a.get('takip') and not a['takip'].get('bitti')],
           'izlenim': [{'kim': v.get('ad'), 'metin': v.get('metin')} for v in (s.get('izlenim') or {}).values()],
           'anilar': [{'kim': a['kim'], 'ozet': a['ozet'], 't': a['t'], 'n': a.get('n', 1)} for a in sorted(memories, key=lambda a: -a['t'])[:8]],
           'hatirlatici': [x.get('metin') for x in s.get('hatirlatici') or []], 'birikim': s.get('birikim')}
    return out if any(out.values()) else None


_STATION = {}


def _station_name(aid):
    if not _STATION:
        d = _read_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'cbs.json')) or {}
        _STATION.update({str(a['kimlik']): a['ad'] for a in d.get('asteroitler', [])})
    return _STATION.get(str(aid), str(aid))


def clans(pid):
    """Paketin botlarının klanları (sunucunun son kaydı: durum.json'un yanındaki klanlar.json): logo (OP-017), lider, üyeler, kasa,
    vergi, bütçe, istasyonlar ve yarış (bot/clan_stations.py), son haberler. Kalabalık önce."""
    d = _read_file(os.path.join(os.path.dirname(state_path(pid)), 'klanlar.json')) or {}
    names = {x['ad'].lower() for x in read(pid)['kadro']}
    out = []
    for k in (d.get('klanlar') or {}).values():
        members = k.get('uyeler') or {}
        bot = sum(1 for a in members if a in names)
        if not bot:
            continue
        s = k.get('ksi') or {}
        out.append({'ad': k.get('ad', ''), 'etiket': k.get('etiket', ''), 'logo': k.get('logo'), 'firma': k.get('firma', 0),
                    'lider': (members.get(k.get('lider')) or {}).get('ad', k.get('lider')), 'bot_lider': k.get('lider') in names,
                    'uye': len(members), 'bot': bot, 'kasa': k.get('kasa', 0), 'vergi': k.get('vergi', 0), 'butce': k.get('butce'),
                    'kurulus': k.get('kurulus'), 'aciklama': k.get('aciklama', ''),
                    'rutbeler': [r.get('ad') for r in k.get('rutbeler') or []],
                    'istasyonlar': [_station_name(a) for a, x in (s.get('gordu') or {}).items() if x == 'kurulu'],
                    'yaris': _station_name(s['hedef']) if s.get('hedef') else None,
                    'diplomasi': [{'tur': x.get('tur'), 'ad': x.get('ad') or ((d.get('klanlar') or {}).get(str(x.get('klan'))) or {}).get('ad', '')}
                                  for x in k.get('diplomasi') or []],
                    'haberler': [x.get('metin') for x in k.get('haberler') or [] if x.get('metin')][:3]})
    out.sort(key=lambda x: (-x['uye'], x['ad']))
    return out


def detail(pid):
    """Paket + kadronun canlı durumu (son kayıttan)."""
    import map_links as H
    d = read(pid)
    t, c = live(pid)
    rows = []
    for x in d['kadro']:
        s = c.get(x['no'], {})
        e = s.get('ekip') or {}
        rows.append({'no': x['no'], 'ad': x['ad'], 'firma': x['firma'], 'arketip': x['kisilik']['arketip'],
                     'aliskanlik': x['kisilik'].get('aliskanlik'), 'dil': x['kisilik'].get('dil'),
                     'ad_dili': x['kisilik'].get('ad_dili') or x['kisilik'].get('dil'),
                     'ozellik': x['kisilik']['ozellik'], 'seviye': s.get('seviye', 1), 'gemi': e.get('gemi', 'ship_phoenix'),
                     'harita': s.get('harita'), 'harita_ad': H.name(s['harita']) if s.get('harita') else '', 'klan': s.get('klan'), 'hedef': s.get('hedef'), 'istat': s.get('istat') or {},
                     'kredi': s.get('kredi', 0), 'uridyum': s.get('uridyum', 0), 'onur': s.get('onur', 0),
                     'ep': s.get('ep', 0), 'rutbe': s.get('rutbe') or 1, 'ozel': bool(x.get('ozel')),
                     'kapi': {g: v.get('en_iyi') for g, v in (s.get('kapi_sureleri') or {}).items()},
                     'ajan': (s.get('ajan') or [])[-6:],                    # ajanın son adımları (bot/ajan.py; güçlü sağlayıcı)
                     'hafiza': _memory(s)})
    out = dict(summary(pid), ayarlar=clean_settings({}, d['ayarlar']),          # eski paketlerde yeni ayarlar varsayılanla
               llm_kullanim=live_llm(pid), dil=d.get('dil'), ad_dili=name_lang(d), ad_kaynagi=d.get('ad_kaynagi', 'uretim'), diller=list(LANGUAGES),
               firma_dagilimi=d.get('firma_dagilimi'), kadro=rows, klanlar=clans(pid),
               durum_var=bool(c))
    return out


def signature(pid):
    """Sunucunun yeniden başlaması gereken değişiklik: paket dosyasının içeriği (durum.json değil)."""
    p = file_path(pid)
    if not p:
        return None
    import hashlib
    with open(p, 'rb') as fh:
        return os.path.normcase(p), hashlib.sha1(fh.read()).hexdigest()
