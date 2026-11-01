"""Store of the Bots page (the /api/bot... endpoints of panel.py; belgeler/BOTLAR.md).

Bot package save/bots/<id>.json:
  {version, name, description, world, mode ('simple' | 'normal' | 'advanced'), progression ('progressive' | 'jumpstart'), seed, lang,
   company_distribution [MMO, EIC, VRU], settings {...}, roster [{no, name, company, personality}], created, update}
The package's progress is in save/bots/<id>/state.json (the game server writes it: bot/manager.py); when a package is deleted both
move to _trash. At most one package is assigned to a world (PLAY opens with that world's package: OO_BOT).
The roster is generated once when it is created (bot/personality.generate_roster, seeded): the same bots at every login.
"""
import copy, datetime, json, os, random, re, shutil, threading

import paths as PTH
import name_log as NL
from lang import t as _

VERSION = 1
MODES = ('simple', 'normal', 'advanced')
PROGRESSIONS = ('progressive', 'jumpstart')
from bot.language_data import CODES as _CODES
from bot import llm_provider as PRV
LANGUAGES = ('mixed',) + _CODES          # language of names and chat (bot/languages/<code>.json); mixed: each bot in the language of its name
NAME_LENGTH, DESCRIPTION_LENGTH = 40, 240
COUNT_MIN, COUNT_MAX = 1, 3000
_LOCK = threading.Lock()

# setting -> (type, min, max, default); the same keys as bot/manager.DEFAULTS
SETTINGS = {
    'speed': ('number', 0.1, 20.0, 1.0),
    'online_ratio': ('number', 0.05, 2.0, 0.6),
    'max_online': ('full', 0, 3000, 0),
    'catchup_hours': ('full', 0, 48, 4),
    'catch_up_rate': ('number', 0.0, 1.0, 0.35),
    'signup_sec': ('full', 0, 300, 15),
    'jumpstart_hours': ('full', 1, 2000, 60),
    'pvp_level': ('full', 1, 32, 6),
    'foreign_map': ('bool', None, None, True),
    'chat_min': ('full', 0, 60, 6),
    'help_max': ('full', 0, 20, 3),
    'max_concrete': ('full', 1, 150, 40),
    'bots_per_clan': ('full', 3, 100, 12),
    'rude_chat': ('full', 0, 3, 1),
    'moderator': ('bool', None, None, False),
    'mod_count': ('full', 1, 10, 2),
    'rule_caps': ('bool', None, None, True),
    'rule_flood': ('bool', None, None, True),
    'rule_insult': ('bool', None, None, True),
    'rule_ads': ('bool', None, None, True),
    'mute_min': ('full', 1, 1440, 10),
    'ban_threshold': ('full', 1, 10, 3),
    'ban_hours': ('full', 1, 720, 24),
    'prime_start': ('full', 0, 23, 19),
    'prime_end': ('full', 0, 23, 23),
    'prime_pvp': ('number', 1.0, 5.0, 2.0),
    'big_battle': ('bool', None, None, True),
    'simple_power': ('number', 0.3, 3.0, 1.0),
    'simple_friendly': ('number', 0.0, 1.0, 0.5),
    'llm_batch': ('full', 1, 16, 4),
    'llm_chat': ('bool', None, None, True),
    'llm_decision_min': ('full', 0, 120, 10),
    'llm_agent': ('bool', None, None, True),            # tool loop on a strong provider (bot/agent.py)
    'llm_agent_steps': ('full', 1, 10, 3),
    'llm_hourly': ('full', 0, 20000, 200),             # hourly limit for all language model requests (0: unlimited)
}
PERMISSIONS = ('shop', 'quest', 'pvp', 'attack_player', 'chat', 'clan', 'clan_found', 'friend', 'group', 'auction', 'assist', 'box_stealing', 'cargo', 'rocket', 'custom_ammunition', 'extras', 'mine', 'lab', 'skylab', 'technology', 'booty', 'assembly', 'gate', 'event', 'modes', 'clan_diplomacy', 'clan_order', 'gate_filler', 'clan_cbs')
SIMPLE_CLASSES = ('X-1', 'X-2', 'X-3', 'X-4', '4-X', 'X-5', 'X-6', 'X-7', 'X-8', '4-5')


class BotError(ValueError):
    """Error shown to the user (panel.py returns 400)."""


def folder():
    return os.path.join(PTH.SAVE, 'bots')


def _route(pid):
    if not isinstance(pid, str) or not re.fullmatch(r'[a-z0-9_]{1,40}', pid):
        raise BotError(_('Bot pack not found.'))
    return os.path.join(folder(), pid + '.json')


def state_path(pid):
    _route(pid)                                         # id check: an id like '..' cannot escape the package folder
    return os.path.join(folder(), pid, 'state.json')


def file_path(pid):
    """The server's package file (OO_BOT) or None."""
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
        raise BotError(_('Bot pack not found.'))
    return d


def _save(pid, d):
    os.makedirs(folder(), exist_ok=True)
    d['version'] = VERSION
    d['update'] = _now()
    p = _route(pid)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def var(pid):
    return file_path(pid) is not None


# ------------------------------------------------------------------ validation
def clean_settings(a, old=None):
    """Settings sent by the panel -> valid values (unknown keys are dropped, numbers are clamped to the limits)."""
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
            elif kind == 'full':
                v = max(lo, min(hi, int(v)))
            else:
                v = round(max(lo, min(hi, float(v))), 3)
        except (TypeError, ValueError):
            v = out.get(k, vars_)
        out[k] = v
    trace = dict(out.get('permissions') or {})
    for k in PERMISSIONS:
        if isinstance(a.get('permissions'), dict) and k in a['permissions']:
            trace[k] = bool(a['permissions'][k])
        trace.setdefault(k, True)
    out['permissions'] = trace
    fg = a.get('company_power', out.get('company_power', [1.0, 1.0, 1.0]))
    try:
        out['company_power'] = [round(max(0.2, min(5.0, float(x))), 2) for x in list(fg)[:3]] + [1.0] * (3 - len(list(fg)[:3]))
    except (TypeError, ValueError):
        out['company_power'] = [1.0, 1.0, 1.0]
    game_settings = a.get('game_settings', out.get('game_settings'))            # the bots' game settings profile (bot/game_settings.py)
    from bot import game_settings as GS
    import settings as SET
    if not isinstance(game_settings, dict) or game_settings.get('profile') not in GS.PROFILES:
        game_settings = {'profile': 'standard', 'values': {}}
    value = {}
    for k, v in (game_settings.get('values') or {}).items():
        s = SET.BY_KEY.get(k)
        if k in GS.FIELDS and s:
            try:
                value[k] = round(max(s.get('min', 0.0), min(s.get('max', 50.0), float(v))), 3)
            except (TypeError, ValueError):
                pass
    out['game_settings'] = {'profile': game_settings['profile'], 'values': value}
    bh = a.get('simple_maps', out.get('simple_maps'))
    if isinstance(bh, dict):
        out['simple_maps'] = {s: max(0, min(20, int(bh.get(s, 0) or 0))) for s in SIMPLE_CLASSES}
    else:
        from bot import simple
        out['simple_maps'] = dict(simple.DEFAULT_MAPS)
    return out


def _clean_name(name):
    name = ' '.join(str(name or '').split())[:NAME_LENGTH]
    if not name:
        raise BotError(_('Give the bot pack a name.'))
    return name


def _new_id(name):
    tr = str.maketrans('çğıöşüâîûÇĞİÖŞÜ', 'cgiosuaiuCGIOSU')
    k = re.sub(r'[^a-z0-9]+', '_', name.translate(tr).lower()).strip('_')[:30] or 'bots'
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
    """d: the package; if the name source is DOStats the names come from real players, the clan tags in the names d['clan_tags']."""
    from bot import personality as PS
    pool = None
    if d is not None and d.get('name_source') == 'dostats':
        from bot import dostats as DS
        try:
            pool = DS.names([name_lang] if name_lang in LANGUAGES[1:] else list(DS.SERVERS))
        except OSError:
            raise BotError(_("Could not reach DOStats. Set the name source to Generated or try again later."))
        d['clan_tags'] = DS.tags(pool)[:300]
    return PS.generate_roster(seed, count, company_distribution=distribution, lang=lang if lang in LANGUAGES else 'mixed', existing=existing,
                         name_lang=name_lang if name_lang in LANGUAGES else None, special=special, pool=pool)


CUSTOM_MAX = 500
NAME_SOURCES = ('production', 'dostats')      # names: the generator (real server style) or the real players on dostats.info
_COMPANY_NAME = {'mmo': 1, 'eic': 2, 'vru': 3}
_ARCHETYPE_NAME = {'grinder': 'grinder', 'pve': 'grinder', 'hunter': 'hunter', 'pvp': 'hunter', 'social': 'social', 'trader': 'trader',
               'quester': 'quester', 'casual': 'casual', 'leader': 'leader', 'kasıcı': 'grinder', 'avcı': 'hunter', 'tüccar': 'trader',
               'görevci': 'quester',
               # Turkish names being typed (ASCII): the package list is text the user wrote by hand
               'kasici': 'grinder', 'avci': 'hunter', 'tuccar': 'trader', 'gorevci': 'quester', 'rahat': 'casual',
               'sosyal': 'social', 'lider': 'leader'}


def parse_custom(text, used=()):
    """The user's own bot list (one per line "name[, company][, behavior][, language]"; comma, semicolon or tab; # comment)
    -> [{name, company?, archetype?, lang?}] (player request 2026-10-30). A bad line raises BotError (with the line number); used names
    (players) and duplicates are rejected."""
    from bot import personality as PS
    out, seen = [], {str(a).lower() for a in used}
    for i, row in enumerate(str(text or '').splitlines(), 1):
        part = [x.strip() for x in re.split(r'[,;\t]', row) if x.strip()]
        if not part or part[0].startswith('#'):
            continue
        name = part[0]
        if not PS.NAME_PATTERN.match(name):
            raise BotError(_('Line {0}: "{1}" is not a valid name (3-20 letters, digits, _ . -).').format(i, name))
        if name.lower() in seen:
            raise BotError(_('Line {0}: the name "{1}" is already taken.').format(i, name))
        seen.add(name.lower())
        o = {'name': name}
        for x in part[1:]:
            k = x.lower()
            if k in _COMPANY_NAME and 'company' not in o:
                o['company'] = _COMPANY_NAME[k]
            elif (k in PS.ARCHETYPES or k in _ARCHETYPE_NAME) and 'archetype' not in o:
                o['archetype'] = _ARCHETYPE_NAME.get(k, k)
            elif k in LANGUAGES and k != 'mixed' and 'lang' not in o:
                o['lang'] = k
            else:
                raise BotError(_('Line {0}: "{1}" not understood (company: MMO, EIC, VRU; behaviour: {2}; language: {3}).').format(
                    i, x, ', '.join(PS.ARCHETYPES), ', '.join(d for d in LANGUAGES if d != 'mixed')))
        out.append(o)
        if len(out) > CUSTOM_MAX:
            raise BotError(_('At most {0} custom bots.').format(CUSTOM_MAX))
    return out


def _custom_lang(d, summary):
    """The built-in language model is English only: in Advanced mode the custom bot's language is English too (bot/llm.py)."""
    if d.get('mode') == 'advanced' and not PRV.multilingual():
        return [dict(o, lang='en') if o.get('lang') else o for o in summary]
    return summary


def name_lang(d):
    """The package's name language (in old packages name and chat were a single setting)."""
    return d.get('name_lang') or d.get('lang') or 'mixed'


def apply_chat_lang(d):
    """Chat language changed: existing bots also speak the new language (mixed: each bot in the language of its name). Names do not change."""
    for x in d['roster']:
        k = x['personality']
        k.setdefault('name_lang', k.get('lang'))
        k['lang'] = d['lang'] if d['lang'] in LANGUAGES[1:] else (k.get('name_lang') or k.get('lang') or 'en')


def _count(d):
    """In Simple mode the roster equals the number of map slots."""
    if d.get('mode') == 'simple':
        from bot import simple
        return max(1, simple.slot_count(d['settings'].get('simple_maps') or simple.DEFAULT_MAPS))
    return None


# ------------------------------------------------------------------ storage
def create(name, description='', world=None, mode='normal', progression='progressive', count=60, lang='mixed', company_distribution=(1, 1, 1),
            settings=None, players=(), name_lang_=None, special='', name_source=None):
    """New package: the roster is generated from the seed (players' names are not used)."""
    if mode not in MODES:
        raise BotError(_('Unknown bot mode.'))
    with _LOCK:
        name = _clean_name(name)
        pid = _new_id(name)
        if mode == 'advanced' and not PRV.multilingual():
            lang = 'en'                         # the built-in language model is English only (bot/llm.py; free on another provider)
        d = {'name': name, 'description': str(description or '')[:DESCRIPTION_LENGTH], 'world': None, 'mode': mode,
             'progression': progression if progression in PROGRESSIONS else 'progressive', 'seed': random.randrange(1, 2 ** 31),
             'lang': lang if lang in LANGUAGES else 'mixed', 'name_lang': name_lang_ if name_lang_ in LANGUAGES else 'mixed',
             'company_distribution': _distribution(company_distribution), 'name_source': name_source if name_source in NAME_SOURCES else 'production',
             'settings': clean_settings(settings or {}), 'created': _now()}
        summary = _custom_lang(d, parse_custom(special, players))
        n = max(len(summary), _count(d) or max(COUNT_MIN, min(COUNT_MAX, int(count or 60))))
        d['roster'] = generate_roster(d['seed'], n, d['company_distribution'], d['lang'], players, d['name_lang'], summary, d)
        _save(pid, d)
    if world:
        assign(pid, world)
    return pid


def update(pid, name=None, description=None, mode=None, progression=None, settings=None):
    with _LOCK:
        d = read(pid)
        if name is not None:
            d['name'] = _clean_name(name)
        if description is not None:
            d['description'] = str(description)[:DESCRIPTION_LENGTH]
        old_mode = d['mode']
        if mode is not None:
            if mode not in MODES:
                raise BotError(_('Unknown bot mode.'))
            d['mode'] = mode
        if progression is not None and progression in PROGRESSIONS:
            d['progression'] = progression
        if settings is not None:
            d['settings'] = clean_settings(settings, d.get('settings'))
        n = _count(d)
        if n is not None and (n != len(d['roster']) or old_mode != d['mode']):
            d['roster'] = _resize(d, n)
        _save(pid, d)


def _resize(d, n, players=()):
    """Roster to n bots: any excess is removed from the end, any shortfall is filled with new bots (continuing from the same seed; existing ones keep their name and personality)."""
    k = d['roster'][:n]
    if len(k) < n:
        extra = generate_roster(d['seed'] + len(k) * 7919, n - len(k), d['company_distribution'], d.get('lang', 'mixed'),
                        [x['name'] for x in k] + list(players), name_lang(d), d=d)
        last = max([x['no'] for x in k], default=0)
        for i, x in enumerate(extra, 1):
            x['no'] = last + i
        k += extra
    return k


def roster(pid, count=None, lang=None, company_distribution=None, regenerate=False, players=(), name_lang_=None, special='', name_source=None):
    """Resize the roster (count) or regenerate it from scratch (regenerate: new seed, progress is reset). The chat language is applied to existing bots
    immediately; the name language to newly added bots and to regeneration (existing names do not change). ozel: the user's own bots
    (ozel_cozumle): on regeneration at the head of the roster; otherwise those in the roster without a name are appended at the end."""
    with _LOCK:
        d = read(pid)
        if name_lang_ in LANGUAGES:
            d['name_lang'] = name_lang_
        elif not d.get('name_lang'):
            d['name_lang'] = d.get('lang') or 'mixed'
        if name_source in NAME_SOURCES:
            d['name_source'] = name_source           # to newly added bots and to regeneration (existing names do not change)
        if d.get('mode') == 'advanced' and not PRV.multilingual():
            lang = 'en'                         # the built-in language model is English only (bot/llm.py; free on another provider)
        if lang in LANGUAGES and lang != d.get('lang'):
            d['lang'] = lang
            apply_chat_lang(d)
        if company_distribution is not None:
            d['company_distribution'] = _distribution(company_distribution)
        n = _count(d) or max(COUNT_MIN, min(COUNT_MAX, int(count or len(d['roster']))))
        old_backups = [x['name'] for x in d['roster']]
        summary = _custom_lang(d, parse_custom(special, players))
        if regenerate:
            d['seed'] = random.randrange(1, 2 ** 31)
            d['roster'] = generate_roster(d['seed'], max(n, len(summary)), d['company_distribution'], d['lang'], players, d['name_lang'], summary, d)
            outgoing = old_backups                              # regeneration: all the old pilots go
        else:
            d['roster'] = _resize(d, n, players)
            outgoing = old_backups[n:]                          # reduction: the last ones go
            var = {x['name'].lower() for x in d['roster']}
            new_ = [o for o in summary if o['name'].lower() not in var]
            if new_:                                     # added custom bots go to the end (existing ones do not change)
                extra = generate_roster(d['seed'] + len(d['roster']) * 7919, len(new_), d['company_distribution'], d['lang'],
                                list(var) + list(players), name_lang(d), new_, d)
                last = max([x['no'] for x in d['roster']], default=0)
                for i, x in enumerate(extra, 1):
                    x['no'] = last + i
                d['roster'] += extra
        _save(pid, d)
    NL.add([{'type': 'delete', 'name': a} for a in outgoing])
    if regenerate:
        reset(pid, event=False)


# ------------------------------------------------------------------ bot detail and editing (bot/edit.py)
_CATALOG = None


def edit_catalog():
    global _CATALOG
    if _CATALOG is None:
        from bot import edit as ED
        _CATALOG = ED.catalog()
    return _CATALOG


def edit_error(e):
    """bot/edit.EditError -> message in the panel's language."""
    return {'value': _('Invalid value: %s', e.area), 'interval': _('Value out of range: %s', e.area),
            'item': _('Unknown item: %s', e.area), 'none': _('Not found: %s', e.area),
            'no_state': _('This bot has not appeared in the game yet: only its personality can be edited.'),
            'online': _("An online bot's map can't be changed: try once it is offline.")}.get(e.code, str(e))


def _roster_row(d, no):
    x = next((x for x in d['roster'] if x['no'] == int(no)), None)
    if x is None:
        raise BotError(_('Bot not found.'))
    return x


def bot_detail(pid, no):
    """While the game is closed: the bot's whole state in the last save (bot/edit.appearance)."""
    from bot import edit as ED
    d = read(pid)
    t, c = live(pid)
    return ED.appearance(c.get(int(no)), _roster_row(d, no))


def bot_personality(pid, no, traits):
    """The bot's personality (roster row): also written to the package file while the game is open (the manager reads it from the roster at the next start)."""
    from bot import edit as ED
    with _LOCK:
        d = read(pid)
        try:
            ED.apply(None, _roster_row(d, no), {'traits': traits})
        except ED.EditError as e:
            raise BotError(edit_error(e)) from None
        _save(pid, d)


def edit_bot(pid, no, value):
    """While the game is closed: edit the bot in the state file (and the package for its personality) -> new view."""
    from bot import edit as ED
    with _LOCK:
        d = read(pid)
        roster_row = _roster_row(d, no)
        route = state_path(pid)
        all_candidates = _read_file(route) or {}
        k = (all_candidates.get('bots') or {}).get(str(int(no)))
        try:
            ED.apply(k, roster_row, value)
        except ED.EditError as e:
            raise BotError(edit_error(e)) from None
        if k is not None and any(a != 'traits' for a in value):
            os.makedirs(os.path.dirname(route), exist_ok=True)
            with open(route + '.tmp', 'w', encoding='utf8') as fh:
                json.dump(all_candidates, fh, ensure_ascii=False, separators=(',', ':'))
            os.replace(route + '.tmp', route)
        if 'traits' in value:
            _save(pid, d)
    return bot_detail(pid, no)


def bot_name(pid, no, name, players=()):
    """Rename a bot (its progress stays)."""
    from bot import personality as PS
    name = str(name or '').strip()
    if not PS.NAME_PATTERN.match(name):
        raise BotError(_('The name must be 3-20 characters: letters, digits, _ . -'))
    with _LOCK:
        d = read(pid)
        if any(x['name'].lower() == name.lower() and x['no'] != no for x in d['roster']) or name.lower() in {str(o).lower() for o in players}:
            raise BotError(_('This name is in use.'))
        x = next((x for x in d['roster'] if x['no'] == int(no)), None)
        if x is None:
            raise BotError(_('Bot not found.'))
        old, x['name'] = x['name'], name
        _save(pid, d)
        if old != name:
            NL.add([{'type': 'name', 'old': old, 'new': name}])      # clans, guides, memories (the game applies them)


def reset(pid, event=True):
    """Delete the package's progress (bots start from scratch; redistributed in jumpstart). Bots leave the clans (including the player's
    clan: name_log 'clan_leave'); their names and acquaintances remain."""
    if event:
        NL.add([{'type': 'clan_leave', 'name': x['name']} for x in read(pid)['roster']])
    p = state_path(pid)
    for f in (p, os.path.join(os.path.dirname(p), 'clans.json')):
        if os.path.isfile(f):
            os.remove(f)


def remove(pid):
    """The package moves to _silinenler; its bots are removed from everywhere (clans, guides: ad_kaydi, the game applies it at the next start)."""
    p = _route(pid)
    if not os.path.isfile(p):
        raise BotError(_('Bot pack not found.'))
    NL.add([{'type': 'delete', 'name': x['name']} for x in read(pid)['roster']])
    target = os.path.join(folder(), '_trash')
    os.makedirs(target, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    os.replace(p, os.path.join(target, '%s_%s.json' % (pid, timestamp)))
    dz = os.path.join(folder(), pid)
    if os.path.isdir(dz):
        shutil.move(dz, os.path.join(target, '%s_%s' % (pid, timestamp)))


def assign(pid, world):
    """Assign the package to a world (that world's previous package becomes unassigned); world None: remove the assignment."""
    with _LOCK:
        d = read(pid)
        if world:
            for x in list_ids():
                if x != pid:
                    o = _read_file(_route(x))
                    if o and o.get('world') == world:
                        o['world'] = None
                        _save(x, o)
        d['world'] = world or None
        _save(pid, d)


def list_ids():
    if not os.path.isdir(folder()):
        return []
    return [f[:-5] for f in os.listdir(folder()) if f.endswith('.json') and not f.startswith('_')
            and re.fullmatch(r'[a-z0-9_]{1,40}', f[:-5])]


def world_pack(world):
    """The world's package (id) or None."""
    for pid in list_ids():
        d = _read_file(_route(pid))
        if d and d.get('world') == world:
            return pid
    return None


# ------------------------------------------------------------------ summaries
def live_llm(pid):
    """The language model usage in the server's last record (bot/llm.Beyin.ozet) or None."""
    return (_read_file(state_path(pid)) or {}).get('llm')


def live(pid):
    """The server's last record: no -> bot state (level, ship, map, clan, statistics) and the time of the record."""
    d = _read_file(state_path(pid)) or {}
    return d.get('t'), {int(k): v for k, v in (d.get('bots') or {}).items()}


def summary(pid):
    d = read(pid)
    t, c = live(pid)
    companies = [sum(1 for x in d['roster'] if x['company'] == f) for f in (1, 2, 3)]
    levels = [c[x['no']].get('level', 1) for x in d['roster'] if x['no'] in c]
    return {'id': pid, 'name': d['name'], 'description': d.get('description', ''), 'world': d.get('world'), 'mode': d['mode'],
            'progression': d.get('progression'), 'count': len(d['roster']), 'companies': companies, 'update': d.get('update'),
            'last_played': t, 'level_avg': round(sum(levels) / len(levels), 1) if levels else None,
            'level_max': max(levels) if levels else None}


def entries():
    out = []
    for pid in list_ids():
        try:
            out.append(summary(pid))
        except BotError:
            pass
    out.sort(key=lambda x: x['update'] or '', reverse=True)
    return out


def _memory(s):
    """What is on the bot's mind (bot/memories.py, bot/agent.py; strong provider): its open goals, pending promises, impressions, newest
    memories -> None if there are none."""
    memories = s.get('memories') or []
    out = {'ledger': [x['text'] for x in s.get('ledger') or [] if not x.get('finished')],
           'pending': [{'who': a['who'], 'purpose': a['followup']['purpose'], 'summary': a['summary'], 'due': a['followup'].get('due')}
                        for a in memories if a.get('followup') and not a['followup'].get('finished')],
           'impression': [{'who': v.get('name'), 'text': v.get('text')} for v in (s.get('impression') or {}).values()],
           'memories': [{'who': a['who'], 'summary': a['summary'], 't': a['t'], 'n': a.get('n', 1)} for a in sorted(memories, key=lambda a: -a['t'])[:8]],
           'reminder': [x.get('text') for x in s.get('reminder') or []], 'savings': s.get('savings')}
    return out if any(out.values()) else None


_STATION = {}


def _station_name(aid):
    if not _STATION:
        d = _read_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'cbs.json')) or {}
        _STATION.update({str(a['uid']): a['name'] for a in d.get('asteroids', [])})
    return _STATION.get(str(aid), str(aid))


def clans(pid):
    """The clans of the package's bots (the server's last record: clans.json next to state.json): logo (OP-017), leader, members, treasury,
    tax, budget, stations and race (bot/clan_stations.py), latest news. Crowded first."""
    d = _read_file(os.path.join(os.path.dirname(state_path(pid)), 'clans.json')) or {}
    names = {x['name'].lower() for x in read(pid)['roster']}
    out = []
    for k in (d.get('clans') or {}).values():
        members = k.get('members') or {}
        bot = sum(1 for a in members if a in names)
        if not bot:
            continue
        s = k.get('cbs') or {}
        out.append({'name': k.get('name', ''), 'tag': k.get('tag', ''), 'logo': k.get('logo'), 'company': k.get('company', 0),
                    'leader': (members.get(k.get('leader')) or {}).get('name', k.get('leader')), 'bot_leader': k.get('leader') in names,
                    'member': len(members), 'bot': bot, 'treasury': k.get('treasury', 0), 'tax': k.get('tax', 0), 'budget': k.get('budget'),
                    'founded': k.get('founded'), 'description': k.get('description', ''),
                    'ranks': [r.get('name') for r in k.get('ranks') or []],
                    'stations': [_station_name(a) for a, x in (s.get('seen') or {}).items() if x == 'built'],
                    'race': _station_name(s['target']) if s.get('target') else None,
                    'diplomacy': [{'type': x.get('type'), 'name': x.get('name') or ((d.get('clans') or {}).get(str(x.get('clan'))) or {}).get('name', '')}
                                  for x in k.get('diplomacy') or []],
                    'clan_news': [x.get('text') for x in k.get('clan_news') or [] if x.get('text')][:3]})
    out.sort(key=lambda x: (-x['member'], x['name']))
    return out


def detail(pid):
    """Live state of the package + roster (from the last record)."""
    import map_links as H
    d = read(pid)
    t, c = live(pid)
    rows = []
    for x in d['roster']:
        s = c.get(x['no'], {})
        e = s.get('gear') or {}
        rows.append({'no': x['no'], 'name': x['name'], 'company': x['company'], 'archetype': x['personality']['archetype'],
                     'habit': x['personality'].get('habit'), 'lang': x['personality'].get('lang'),
                     'name_lang': x['personality'].get('name_lang') or x['personality'].get('lang'),
                     'traits': x['personality']['traits'], 'level': s.get('level', 1), 'ship': e.get('ship', 'ship_phoenix'),
                     'map': s.get('map'), 'map_name': H.name(s['map']) if s.get('map') else '', 'clan': s.get('clan'), 'target': s.get('target'), 'stats': s.get('stats') or {},
                     'credits': s.get('credits', 0), 'uridium': s.get('uridium', 0), 'honor': s.get('honor', 0),
                     'ep': s.get('ep', 0), 'rank': s.get('rank') or 1, 'special': bool(x.get('special')),
                     'gate': {g: v.get('best') for g, v in (s.get('gate_times') or {}).items()},
                     'agent': (s.get('agent') or [])[-6:],                    # the agent's latest steps (bot/agent.py; strong provider)
                     'memory': _memory(s)})
    out = dict(summary(pid), settings=clean_settings({}, d['settings']),          # new settings in old packages default
               llm_usage=live_llm(pid), lang=d.get('lang'), name_lang=name_lang(d), name_source=d.get('name_source', 'production'), languages=list(LANGUAGES),
               company_distribution=d.get('company_distribution'), roster=rows, clans=clans(pid),
               has_state=bool(c))
    return out


def signature(pid):
    """A change that needs the server to restart: the package file's contents (not state.json)."""
    p = file_path(pid)
    if not p:
        return None
    import hashlib
    with open(p, 'rb') as fh:
        return os.path.normcase(p), hashlib.sha1(fh.read()).hexdigest()
