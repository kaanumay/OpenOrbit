"""What a bot knows: game facts from the data (aliens per map, bosses, ships, lasers; for the asker's company) and its own state
(ship, level, map, clan, what it is doing, recent events). Answers are true: a bot never names an alien on the wrong map or a ship it
does not fly."""
import random, re

import map_links as H
from .. import catalog as K
from .persona import seed_of

COMPANY = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
SHIP_LADDER = ((0, ('liberator', 'piranha')), (4, ('piranha', 'nostromo')), (7, ('bigboy', 'nostromo', 'piranha')),
               (10, ('vengeance', 'leonov', 'bigboy')), (12, ('goliath', 'vengeance')), (15, ('goliath', 'aegis', 'citadel', 'spearhead')))
LASER_LADDER = ((0, ('MP-1', 'LF-1')), (5, ('MP-1', 'LF-2')), (8, ('LF-2', 'LF-3')), (11, ('LF-3',)))
NICK = {'goliath': 'goli', 'vengeance': 'venge', 'leonov': 'leo', 'nostromo': 'nosto', 'piranha': 'pira', 'liberator': 'libe'}


def home_maps(company):
    f = company if company in COMPANY else 1
    return [(f - 1) * 4 + i for i in range(1, 5)] + [16 + (f - 1) * 4 + i for i in range(1, 5)]


def alien_name(v):
    return re.sub(r'[^A-Za-z ]', '', v['name']).strip()


_alien_maps = {}


def alien_maps(alien, company):
    """Home maps (of the company) where the alien lives, most of them first -> ['2-1', '2-2']."""
    key = (alien, company)
    if key not in _alien_maps:
        rows = []
        for m in home_maps(company):
            n = sum(c for v, c in K.map_npcs(m) if alien_name(v).lower() == alien or (alien == 'boss' and 'Boss' in v['name']))
            if n:
                rows.append((-n if alien != 'boss' else m, m))
        _alien_maps[key] = [H.name(m) for _, m in sorted(rows)]
    return _alien_maps[key]


def map_aliens(map_name):
    ids = {v: k for k, v in H.NAMES.items()}
    m = ids.get(map_name)
    if m is None:
        return []
    out = []
    for v, n in sorted(K.map_npcs(m), key=lambda x: -x[1]):
        a = alien_name(v).lower()
        if 'boss' not in a and a not in out:
            out.append(a)
    return out


def ladder(table, level, r):
    opts = table[0][1]
    for lv, o in table:
        if level >= lv:
            opts = o
    return r.choice(opts)


def ship_of(b):
    return str(b.k['gear'].get('ship', 'ship_phoenix')).replace('ship_', '')


def nick(ship, persona):
    """The ship as the bot writes it (some always say goli, others goliath)."""
    if ship in NICK and random.Random(seed_of('nick', persona.name.lower())).random() < 0.5:
        return NICK[ship]
    return ship


def level_of(y, name):
    """The level of a pilot by name (human or bot), None if unknown."""
    b = y.name_index.get(str(name).lower())
    if b is not None:
        return b.level
    try:
        import community as TP
        k = TP.find(name=name)
        return int(k.profile.d['pilot'].get('level', 1)) if k is not None else None
    except Exception:
        return None


def company_of(y, name):
    b = y.name_index.get(str(name).lower())
    if b is not None:
        return b.company
    try:
        import community as TP
        k = TP.find(name=name)
        return int(k.profile.d['pilot'].get('factionId', 0)) if k is not None else 0
    except Exception:
        return 0


def doing(b):
    """What the bot is doing now, as an act suffix of doing_<goal>."""
    t = b.target.name if b.target is not None else 'resting'
    return {'grinding': 'grinding', 'quest': 'quest', 'pvp': 'pvp', 'shopping': 'shopping', 'selling': 'selling', 'gate': 'gate',
            'group': 'grinding', 'assist': 'pvp', 'duel': 'pvp', 'exploring': 'exploring', 'resting': 'resting', 'mod': 'gate',
            'simple': 'grinding'}.get(t, 'grinding')


# Turkish case endings after a number, by its last digit (bir, iki, üç, dört, beş, altı, yedi, sekiz, dokuz) and the tens (on, yirmi ...)
_TR_HARD = {'3', '4', '5'}
_TR_BACK = {'6', '9'}
_TR_TENS_BACK = {'1', '3', '4', '5', '9'}              # on, otuz, kırk, elli, doksan


def tr_suffix(word, case, sep=''):
    """2-3 + locative -> 2-3'te, 2-6 + dative -> 2-6'ya, 2015 + ablative -> 2015'ten."""
    d = str(word)[-1:]
    if d == '0' and len(str(word)) >= 2:
        back, hard = str(word)[-2] in _TR_TENS_BACK, False
    else:
        back, hard = d in _TR_BACK, d in _TR_HARD
    v = 'a' if back else 'e'
    if case == 'loc':
        return '%s%s%s%s' % (word, sep, 't' if hard else 'd', v)
    if case == 'abl':
        return '%s%s%s%sn' % (word, sep, 't' if hard else 'd', v)
    if case == 'dat':
        y = 'y' if d in ('2', '6', '7') else ''
        return '%s%s%s%s' % (word, sep if sep != ' ' else "'", y, v)
    return str(word)


def add_suffixes(f, lang, persona):
    """Inflected copies of the map/year fields for languages that need them ({map_de}, {map_e}, {since_den} in Turkish)."""
    if lang != 'tr':
        return f
    sep = random.Random(seed_of('sep', persona.name.lower())).choice(("'", '', ' ', "'"))
    for k in ('map', 'map1'):
        if f.get(k):
            f[k + '_de'] = tr_suffix(f[k], 'loc', sep)
            f[k + '_e'] = tr_suffix(f[k], 'dat', sep)
            f[k + '_den'] = tr_suffix(f[k], 'abl', sep)
    if f.get('since'):
        f['since_den'] = tr_suffix(f['since'], 'abl', sep if sep != ' ' else "'")
        f['since_de'] = tr_suffix(f['since'], 'loc', sep if sep != ' ' else "'")
    return f


def fighting(b):
    body = getattr(b, 'body', None)
    try:
        return body is not None and bool(getattr(body, 'target', None)) and b.target is not None and b.target.name in ('grinding', 'pvp')
    except Exception:
        return False


def clan_tag(b):
    try:
        return b.profile.d['pilot'].get('clanTag', '') if b.profile is not None else ''
    except Exception:
        return ''


def helping(b, name):
    """The bot answered this player's call for help (on its way or there)."""
    plan = getattr(b, 'plan', None) or {}
    intent = (b.k.get('intent') or {}) if hasattr(b, 'k') else {}
    for p in (plan if b.target is not None and b.target.name == 'assist' else {}, intent.get('plan') or {} if intent.get('target') == 'assist' else {}):
        if str(p.get('name', '')).lower() == str(name).lower() and not p.get('finished'):
            return True
    return False
