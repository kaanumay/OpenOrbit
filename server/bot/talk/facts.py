"""Game knowledge for the chat: what players ask about items, gates, maps, ores and levels, read from this server's own data so every
answer is true for this server (shop prices from the catalog, drops from galaxy gates / boxes / the daily login / assembly / the season
pass / events, map levels from maps-config, refining from the lab recipes).

find(folded_text) -> entity keys named in a message ("lf4", "x4", "havok", "alfa kapısı", "promerium"); answer() turns a question about
one into a move (act, slots) for dialog.move. Source phrases ("epsilon kapısından çıkıyor") are acts of the language (src_*), rendered
into the {src} / {src2} fields of the answer act.
"""
import os, random, re

import map_links as H
from .. import catalog as K
from . import grammar as G
from . import knowledge as KN
from . import lexicon as LX
from . import persona as PE

KIND_TOPIC = {'laser': 'laser', 'ammo': 'ammo', 'rocket': 'ammo', 'drone': 'drone', 'design': 'drone', 'shield': 'shield', 'speed': 'shield',
              'pet': 'pet', 'gate': 'gate', 'ore': 'ore', 'ship': 'ship'}


def _ent(key, kind, loot, rx, nick):
    return dict(key=key, kind=kind, loot=loot, rx=rx, nick=nick)


# (key, kind, lootId, regex on the folded text, how a player writes it). Specific forms first: "lf4 hp" before "lf4".
ENTITIES = [
    _ent('lf-4-hp', 'laser', 'equipment_weapon_laser_lf-4-hp', r'lf\s*-?\s*4\s*-?\s*hp|hiperplazmoi\w*|hyperplasmoi\w*', 'LF-4 HP'),
    _ent('lf-4-md', 'laser', 'equipment_weapon_laser_lf-4-md', r'lf\s*-?\s*4\s*-?\s*md|magmadrill\w*', 'LF-4 MD'),
    _ent('lf-4-pd', 'laser', 'equipment_weapon_laser_lf-4-pd', r'lf\s*-?\s*4\s*-?\s*pd|paritydrill\w*', 'LF-4 PD'),
    _ent('lf-4-unstable', 'laser', 'equipment_weapon_laser_lf-4-unstable', r'(unstable|kararsiz|instabil\w*|нестабильн\w*)\s+lf\s*-?\s*4',
         'unstable LF-4'),
] + [_ent('lf-%d' % n, 'laser', 'equipment_weapon_laser_lf-%d' % n, r'lf\s*-?\s*%d(?![\d])' % n, 'LF-%d' % n) for n in (1, 2, 3, 4, 5)] + [
    _ent('mp-1', 'laser', 'equipment_weapon_laser_mp-1', r'mp\s*-?\s*1(?!\d)', 'MP-1'),
    _ent('prometheus', 'laser', 'equipment_weapon_laser_pr-l', r'prometheus\s+(laser|lazer)\w*', 'Prometheus'),
    _ent('caucasus', 'laser', 'equipment_weapon_laser_caucasus', r'caucasus|kafkas\w*', 'Caucasus'),
    _ent('x1', 'ammo', 'ammunition_laser_lcb-10', r'(?<![\w-])x\s?1(?!\w)|lcb\s*-?\s*10', 'x1'),
    _ent('x2', 'ammo', 'ammunition_laser_mcb-25', r'(?<![\w-])x\s?2(?!\w)|mcb\s*-?\s*25', 'x2'),
    _ent('x3', 'ammo', 'ammunition_laser_mcb-50', r'(?<![\w-])x\s?3(?!\w)|mcb\s*-?\s*50', 'x3'),
    _ent('x4', 'ammo', 'ammunition_laser_ucb-100', r'(?<![\w-])x\s?4(?!\w)|ucb(\s*-?\s*100)?', 'x4'),
    _ent('rsb', 'ammo', 'ammunition_laser_rsb-75', r'(?<![\w-])x\s?6(?!\w)|rsb(\s*-?\s*75)?', 'rsb'),
    _ent('rcb', 'ammo', 'ammunition_laser_rcb-140', r'(?<![\w-])x\s?7(?!\w)|rcb(\s*-?\s*140)?', 'rcb'),
    _ent('sab', 'ammo', 'ammunition_laser_sab-50', r'sab(\s*-?\s*50)?(?!\w)', 'sab'),
    _ent('cbo', 'ammo', 'ammunition_laser_cbo-100', r'cbo(\s*-?\s*100)?(?!\w)', 'cbo'),
    _ent('r-310', 'rocket', 'ammunition_rocket_r-310', r'r\s*-?\s*310', 'r-310'),
    _ent('plt-2026', 'rocket', 'ammunition_rocket_plt-2026', r'plt\s*-?\s*2026', 'plt-2026'),
    _ent('plt-2021', 'rocket', 'ammunition_rocket_plt-2021', r'plt\s*-?\s*2021', 'plt-2021'),
    _ent('plt-3030', 'rocket', 'ammunition_rocket_plt-3030', r'plt\s*-?\s*3030', 'plt-3030'),
    _ent('flax', 'drone', 'drone_flax', r'flax', 'flax'),
    _ent('iris', 'drone', 'drone_iris', r'iris\w*', 'iris'),
    _ent('apis', 'drone', 'drone_apis', r'apis\w*', 'apis'),
    _ent('zeus', 'drone', 'drone_zeus', r'zeus\w*', 'zeus'),
    _ent('havoc', 'design', 'drone_designs_havoc', r'havo[ck]\w*|хавок\w*', 'havoc'),
    _ent('hercules', 'design', 'drone_designs_hercules', r'hercul\w*|herkul\w*|herk(?!\w)|геркулес\w*', 'hercules'),
    _ent('sg3n-b02', 'shield', 'equipment_generator_shield_sg3n-b02', r'(sg3n\s*-?\s*)?b\s*-?\s*0?2(?!\d)', 'B02'),
    _ent('sg3n-b01', 'shield', 'equipment_generator_shield_sg3n-b01', r'(sg3n\s*-?\s*)?b\s*-?\s*01(?!\d)', 'B01'),
    _ent('sg3n-a03', 'shield', 'equipment_generator_shield_sg3n-a03', r'(sg3n\s*-?\s*)?a\s*-?\s*03(?!\d)', 'A03'),
    _ent('g3n-7900', 'speed', 'equipment_generator_speed_g3n-7900', r'(g3n\s*-?\s*)?7900', 'G3N-7900'),
    _ent('pet', 'pet', 'pet_pet10', r'(?<!\w)p\.?e\.?t(?!\w)|(?<!\w)пет(?!\w)', 'pet'),
    _ent('alpha', 'gate', 'alpha', r'alfa|alpha|альф\w*', 'alfa'),
    _ent('beta', 'gate', 'beta', r'beta|бет[аы]\w*', 'beta'),
    _ent('gamma', 'gate', 'gamma', r'gam+a|гамм?\w*', 'gama'),
    _ent('delta', 'gate', 'delta', r'delta|дельт\w*', 'delta'),
    _ent('epsilon', 'gate', 'epsilon', r'epsilon\w*|эпсилон\w*', 'epsilon'),
    _ent('zeta', 'gate', 'zeta', r'zeta\w*|зет\w*', 'zeta'),
    _ent('kappa', 'gate', 'kappa', r'kap+a(?!\w)|kappa\w*|капп\w*', 'kappa'),
    _ent('lambda', 'gate', 'lambda', r'lambda\w*|лямбд\w*', 'lambda'),
    _ent('kronos', 'gate', 'kronos', r'kronos\w*|кронос\w*', 'kronos'),
    _ent('hades', 'gate', 'hades', r'hades\w*|аид\w*', 'hades'),
    _ent('kuiper', 'gate', 'streuner', r'kuiper\w*|койпер\w*', 'kuiper'),
    _ent('prometium', 'ore', 'resource_ore_prometium', r'prometium\w*|прометий\w*', 'prometium'),
    _ent('endurium', 'ore', 'resource_ore_endurium', r'end[ue]?rium\w*|эндуриум\w*', 'endurium'),
    _ent('terbium', 'ore', 'resource_ore_terbium', r'terbium\w*|тербий\w*', 'terbium'),
    _ent('prometid', 'ore', 'resource_ore_prometid', r'prometid\w*|прометид\w*', 'prometid'),
    _ent('duranium', 'ore', 'resource_ore_duranium', r'duranium\w*|дураниум\w*', 'duranium'),
    _ent('promerium', 'ore', 'resource_ore_promerium', r'promerium\w*|промериум\w*', 'promerium'),
    _ent('xenomit', 'ore', 'resource_ore_xenomit', r'xeno\w*|ксеномит\w*', 'xenomit'),
    _ent('seprom', 'ore', 'resource_ore_seprom', r'se[mp]+rom\w*|сепром\w*', 'seprom'),
    _ent('palladium', 'ore', 'resource_ore_palladium', r'pal+ad[iy]um\w*|паллади\w*', 'palladium'),
    _ent('osmium', 'ore', 'resource_ore_osmium', r'osmium\w*|осмий\w*', 'osmium'),
    _ent('ore', 'ore', None, r'maden\w*|hammadde\w*|ores?(?!\w)|erze?(?!\w)|rohstoff\w*|minerale?s?(?!\w)|minerai\w*|rud[ay](?!\w)|'
                             r'surowc\w*|minerio\w*|minerios|руд[аыу]?(?!\w)', 'ore'),
    _ent('season', 'season', 'resource_gold-pass', r'sezon\s*(bilet\w*|kart\w*|pass\w*)|season\s*pass\w*|saisonpass\w*|pases? de temporada|passe? de (temporada|saison)|karnet\w* sezon\w*|сезонн\w* пропуск\w*|gold\s*pass\w*', 'season pass'),
]
FORMATION_NAMES = {'tu': 'turtle', 'ar': 'arrow', 'la': 'lance', 'st': 'star', 'pi': 'pincer', 'da': 'double arrow', 'di': 'diamond',
                   'ch': 'chevron', 'mo': 'moth', 'cr': 'crab', 'he': 'heart', 'ba': 'barrier', 'bt': 'bat', 'rg': 'ring', 'dr': 'drill',
                   'vt': 'veteran', 'dm': 'dome', 'wl': 'wheel', 'x': 'x', 'wv': 'wave'}
_FWORD = r'(\s+(formation\w*|formasyon\w*|duzen\w*|formacion\w*|formacao|formacja\w*|формаци\w*))'
_AMBIGUOUS = ('star', 'arrow', 'heart', 'ring', 'wave', 'x', 'bat', 'wheel', 'dome', 'lance', 'crab', 'moth', 'turtle', 'diamond', 'barrier',
              'double arrow')                                   # common words: a formation only next to "formation" / "formasyon"
ENTITIES += [_ent('f_' + k.split('-')[-1], 'formation', k, (r'%s%s' % (n, _FWORD)) if n in _AMBIGUOUS else r'%s(?!\w)' % n, n)
             for k in K.ITEMS.get('formations', {}) for n in [FORMATION_NAMES.get(k.split('-')[-1])] if n]
ENTITIES += [
    _ent('formation', 'formation', None, r'formasyon\w*|formation\w*|ucus duzen\w*|formacion\w*|formacao|formacja\w*|формаци\w*', 'formation'),
    _ent('clan', 'clan', None, r'klan\w*|clan\w*|guild\w*|cla(?!\w)|клан\w*', 'clan'),
    _ent('rank', 'rank', None, r'rutbe\w*|rank\w*|rang(?!\w)|rango\w*|grade\w*|ранг\w*|звани\w*', 'rank'),
    _ent('honor', 'honor', None, r'seref\w*|honou?r\w*|ehre(?!\w)|honneur\w*|honra\w*|чест[ьи]|хонор\w*', 'honor'),
    _ent('skylab', 'skylab', None, r'skylab\w*|скайлаб\w*', 'skylab'),
]
BY_KEY = {e['key']: e for e in ENTITIES}
_RX = [(e['key'], re.compile(r'(?<![\w])(%s)' % e['rx'])) for e in ENTITIES]


def find(f):
    """Entity keys named in a folded message, in order of appearance (a more specific name hides the shorter one inside it)."""
    hits, taken = [], []
    for key, rx in _RX:
        for mt in rx.finditer(f):
            a, b = mt.span()
            if any(a < y and x < b for x, y in taken):
                continue
            taken.append((a, b))
            hits.append((a, key))
    return list(dict.fromkeys(k for _, k in sorted(hits)))


def topics_of(keys):
    return {KIND_TOPIC[BY_KEY[k]['kind']] for k in keys if BY_KEY[k]['kind'] in KIND_TOPIC}


# ------------------------------------------------------------------------------------------------- data
_cache = {}


def _load(name):
    if name not in _cache:
        import game_data as GD
        try:
            _cache[name] = GD.load(name)
        except Exception:
            _cache[name] = {}
    return _cache[name]


def _items():
    return K.ITEMS


SKIP = {'parts', 'cost', 'key', 'fee', 'input', 'token', 'ticket', 'price', 'needs', 'entry', 'point_cost', 'uridium_cost'}


def _has(obj, loot):
    """Is the lootId somewhere in a reward structure (cost keys skipped)."""
    if isinstance(obj, str):
        return obj == loot
    if isinstance(obj, dict):
        return any((k == loot) or (k not in SKIP and _has(v, loot)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return any(_has(v, loot) for v in obj)
    return False


def sources(loot):
    """Ways to get an item -> [(kind, info)] in the order a player would name them. kind: shop, gate, event, box, assembly, login,
    season, battlepass, alien, eventgate, quest."""
    k = ('src', loot)
    if k in _cache:
        return _cache[k]
    out = []
    p = K.price(loot)
    if p:
        out.append(('shop', p))
    gates = []
    for g, v in (_load('gates.json').get('gates') or {}).items():
        r = v.get('reward') or {}
        for c in r.get('chance') or ():
            if c.get('item') == loot or _has(c.get('package'), loot) or _has(c.get('together'), loot):
                gates.append((-(1.0 if c.get('first_guaranteed') else 0) - c.get('probability', 0), g))
        if loot in (r.get('ammunition') or {}):
            gates.append((-0.5, g))
    if gates:
        out.append(('gate', [g for _, g in sorted(gates)]))
    ev = [e for e in (_load('events.json').get('events') or {}).values() if _has(e.get('gate_reward'), loot)]
    if ev:
        out.append(('event', sorted({g for e in ev for r in e.get('gate_reward') or () for g in r.get('gates', ())})))
    bx = [k2 for k2, v in (_load('boxes.json').get('boxes') or {}).items() if _has(v.get('reward'), loot)]
    if bx:
        out.append(('box', bx))
    rec = [v for v in (_load('recipes.json').get('recipes') or {}).values() if _has(v.get('result'), loot)]
    if rec:
        out.append(('assembly', rec))
    if any(_has(m, loot) for m in (_load('daily_login.json').get('months') or {}).values()):
        out.append(('login', None))
    t = _load('tickets.json')
    if _has((t.get('season') or {}).get('reward'), loot):
        out.append(('season', None))
    if _has((t.get('battle_pass') or {}).get('passes'), loot):
        out.append(('battlepass', None))
    al = [KN.alien_name(v) for v in (_load('npc.json').get('types') or {}).values() if _has(v.get('extra_reward'), loot)]
    if al:
        out.append(('alien', al))
    eg = [v.get('name') for v in (_load('event_gates.json').get('gates') or {}).values() if _has(v.get('reward'), loot)]
    if eg:
        out.append(('eventgate', eg))
    _cache[k] = out
    return out


def fmt(n):
    """10000 -> 10k, 1080000 -> 1.08m (how players write amounts)."""
    n = float(n)
    if n >= 1e6:
        return ('%.2f' % (n / 1e6)).rstrip('0').rstrip('.') + 'm'
    if n >= 1e4 or (n >= 1e3 and n % 1000 == 0):
        return ('%.1f' % (n / 1e3)).rstrip('0').rstrip('.') + 'k'
    return str(int(n)) if n == int(n) else str(n)


def _mult(key):
    try:
        import settings as SET
        return SET.multiplier(key)
    except Exception:
        return 1.0


def price_text(p, pe, lang, r):
    cur, n = p
    return '%s %s' % (fmt(n * _mult('shop_price')), pe.pick('cur_u' if cur == 'U' else 'cur_c', lang, r) or ('uri' if cur == 'U' else 'cr'))


def grind_maps(company, level):
    """The company's home maps a pilot of this level should grind on (the highest ones he can enter, 4-X left out) -> ['2-3', '2-4']."""
    ids = {v: k for k, v in H.NAMES.items()}
    rows = []
    for i in range(1, 9):
        name = '%d-%d' % (company, i)
        m = ids.get(name)
        if m is None:
            continue
        need = H.level_required(m, company)
        if need <= level:
            rows.append((need, i, name))
    if not rows:
        return ['%d-1' % company]
    top = max(x[0] for x in rows)
    return [x[2] for x in sorted(rows) if x[0] == top][:2]


def map_level(map_name, company):
    ids = {v: k for k, v in H.NAMES.items()}
    m = ids.get(map_name)
    return None if m is None else H.level_required(m, company)


# ------------------------------------------------------------------------------------------------- rendering
def _render(act, lang, slots, pe, r):
    pats = LX.act(lang, act)
    if not pats:
        return None
    ex = G.Expander(slots, lambda c: pe.pick(c, lang, r), lambda n: r.choice(LX.act(lang, n)) if LX.act(lang, n) else None, r, opt=0.4)
    for _ in range(4):
        t = ex.run(r.choice(pats))
        if t:
            return G.tidy(t).replace(' // ', ' ')
    return None


def _box_name(key, lang):
    names = (LX.DATA.get(lang) or {}).get('names') or {}
    return names.get(key) or ((_load('boxes.json').get('boxes') or {}).get(key) or {}).get('name', key)


def _gate_name(key, lang=None):
    names = (LX.DATA.get(lang) or {}).get('names') or {}
    key = 'kuiper' if key == 'streuner' else key
    return names.get(key, key)


def source_text(src, lang, pe, r):
    kind, info = src
    s = {}
    if kind == 'shop':
        s['price'] = price_text(info, pe, lang, r)
    elif kind in ('gate', 'event'):
        g = [_gate_name(x, lang) for x in info[:3]]
        s['gates'] = ', '.join(g)
    elif kind == 'box':
        s['box'] = _box_name(info[0], lang)
    elif kind == 'alien':
        s['alien'] = info[0]
    elif kind == 'eventgate':
        s['event'] = info[0]
    return _render('src_' + kind, lang, s, pe, r)


# ------------------------------------------------------------------------------------------------- answering
def question_kind(m):
    """What the player wants to know: get, price, what, sell, make, reward, xp, level -> str or None."""
    fl = m.fq
    for k in ('xp', 'sell', 'price', 'reward', 'make', 'get', 'what'):
        if k in fl:
            return k
    if m.qtype == 'q_howmuch':
        return 'price'
    if m.qtype in ('q_how', 'q_where'):
        return 'get'
    if m.qtype in ('q_what', 'q_which') and m.entities:
        return 'what'
    if m.want:
        return 'get'
    return None


def answer(y, b, m, asker, lang):
    """A fact answer -> (act, slots) or None (not a question about a known thing: the normal moves answer)."""
    pe = PE.of(b)
    r = b.r
    q = question_kind(m)
    fac = KN.company_of(y, asker) or b.company
    if q == 'xp' and m.numbers:
        n = m.numbers[0]
        table = dict((int(a), int(x)) for a, x in (_load('levels.json').get('levels') or ()))
        if n in table:
            return ('fact_xp', dict(n=n, xp=fmt(table[n])))
    if m.maps and not m.entities and (q in ('price', 'level') or 'level' in m.topics) and not m.aliens:
        need = map_level(m.maps[0], fac)
        if need is not None:
            return ('fact_map_level', dict(map1=m.maps[0], n=need))
    if m.aliens and q in ('price', 'reward') and m.aliens[0] != 'boss':
        v = _alien_type(m.aliens[0])
        if v:
            rw = v.get('reward') or {}
            return ('fact_alien_reward', dict(alien=KN.alien_name(v).lower(), uri=fmt(rw.get('uridium', 0)), cr=fmt(rw.get('credits', 0)),
                                              xp=fmt(rw.get('ep', 0))))
    if not m.entities or q is None:
        return None
    e = BY_KEY[m.entities[0]]
    if r.random() < (0.2 if b.level < 5 else 0.04):             # a fresh pilot (and now and then anyone) does not know
        return ('dunno_game', {})
    item = e['nick']
    if e['kind'] == 'ship':
        return None
    if e['kind'] == 'gate':
        return _gate(e, q, pe, lang, r)
    if e['kind'] in ('formation', 'clan', 'rank', 'honor', 'skylab'):
        return _other(e, q, pe, lang, r)
    if e['kind'] == 'season':                                   # points only from the season missions; levels for uridium; Gold Pass
        t = _load('tickets.json').get('season') or {}
        gold = K.price('resource_gold-pass')
        if q == 'price' and gold:
            return ('fact_season_gold', dict(price=price_text(gold, pe, lang, r)))
        cost = [c for c in t.get('uridium_cost') or () if c]
        return ('fact_season', dict(n=len(t.get('quests') or {}), price=price_text(('U', cost[0]), pe, lang, r) if cost else None))
    if e['kind'] == 'ore':
        return _ore(e, q, fac, pe, lang, r)
    if q in ('what', 'reward'):                                  # "hercules ne veriyor": what it gives you
        return _what(e) or _get(e, item, pe, lang, r)
    if q == 'price':
        p = K.price(e['loot'])
        if p:
            return ('fact_price', dict(item=item, price=price_text(p, pe, lang, r)))
        alt = [s for s in sources(e['loot']) if s[0] != 'shop']
        return ('fact_not_sold', dict(item=item, src=source_text(alt[0], lang, pe, r) if alt else None))
    return _get(e, item, pe, lang, r)


def _get(e, item, pe, lang, r):
    srcs = sources(e['loot'])
    if not srcs:
        return ('dunno_game', {})
    a = source_text(srcs[0], lang, pe, r)
    b2 = source_text(srcs[1], lang, pe, r) if len(srcs) > 1 and r.random() < 0.6 else None
    if not a:
        return ('dunno_game', {})
    if srcs[0][0] != 'shop' and K.price(e['loot']) is None and r.random() < 0.4:
        return ('fact_not_sold', dict(item=item, src=a))
    return ('fact_get', dict(item=item, src=a, src2=b2))


def _what(e):
    I = _items()
    loot, item = e['loot'], e['nick']
    if e['kind'] == 'laser':
        v = (I.get('lasers') or {}).get(loot)
        return ('fact_laser', dict(item=item, n=v['damage'])) if v and v.get('damage') else None
    if e['kind'] == 'ammo':
        if e['key'] == 'sab':
            return ('fact_sab', dict(item=item))
        v = (I.get('laser_ammo') or {}).get(loot)
        return ('fact_ammo', dict(item=item, n=v['multiplier'])) if v and v.get('multiplier') else None
    if e['kind'] == 'rocket':
        v = (I.get('rockets') or {}).get(loot)
        return ('fact_rocket', dict(item=item, n=fmt(v['damage']))) if v and v.get('damage') else None
    if e['kind'] == 'design':
        v = (I.get('drone_designs') or {}).get(loot) or {}
        sb = v.get('set_bonus') or {}
        if 'drone_laser' in sb:
            return ('fact_design_dmg', dict(item=item, n=int(round(sb['drone_laser'] * 100))))
        if 'hp' in sb:
            return ('fact_design_hp', dict(item=item, n=int(round(sb['hp'] * 100)), pct=int(round(v.get('drone_shield', 0) * 100))))
        return None
    if e['kind'] == 'drone':
        return ('fact_drone', dict(item=item))
    if e['kind'] == 'shield':
        v = (I.get('shield_generators') or {}).get(loot)
        return ('fact_shield', dict(item=item, n=fmt(v['shield']), pct=int(round(v.get('absorb', 0) * 100)))) if v else None
    if e['kind'] == 'speed':
        v = (I.get('speed_generators') or {}).get(loot)
        return ('fact_speed', dict(item=item, n=v['speed'])) if v else None
    if e['kind'] == 'pet':
        return ('fact_pet', dict(item=item))
    return None


def _gate(e, q, pe, lang, r):
    g = (_load('gates.json').get('gates') or {}).get(e['loot']) or {}
    name = _gate_name(e['loot'], lang)
    if not g:
        return None
    if q in ('reward', 'what'):
        rw = g.get('reward') or {}
        ucb = (rw.get('ammunition') or {}).get('ammunition_laser_ucb-100', 0)
        best = [c['item'] for c in rw.get('chance') or () if c.get('item') and c['item'] in {x['loot'] for x in ENTITIES}]
        extra = next((x['nick'] for x in ENTITIES if best and x['loot'] == best[0]), None)
        return ('fact_gate_reward', dict(gate=name, uri=fmt(rw.get('uridium', 0)), n=fmt(ucb), item=extra))
    if e['loot'] == 'kronos':
        return ('fact_gate_kronos', dict(gate=name, n=g.get('part', 21)))
    energy = _load('gates.json').get('energy_price') or 100
    return ('fact_gate_parts', dict(gate=name, n=g.get('part'), price='%s %s' % (fmt(energy * _mult('gate_price')), pe.pick('cur_u', lang, r) or 'uri')))


def _ore(e, q, fac, pe, lang, r):
    I = _items()
    kinds = {v: k for k, v in ((I.get('ores') or {}).get('kinds') or {}).items()}
    kid = kinds.get(e['loot'])
    item = e['nick']
    if q == 'sell' or (q == 'price' and kid in ('0', '1', '2', '4', '5', '6')):
        if q == 'price':
            p = K.ore_prices(0)
            v = p.get(int(kid)) if isinstance(p, dict) else None
            if v:
                return ('fact_ore_price', dict(item=item, n=fmt(v), maps=_sell_maps(fac)))
        return ('fact_ore_sell', dict(item=item, maps=_sell_maps(fac)))
    rec = ((I.get('lab') or {}).get('recipes') or {}).get(kid)
    if rec:
        names = {k: v.replace('resource_ore_', '') for k, v in ((I.get('ores') or {}).get('kinds') or {}).items()}
        parts = ' + '.join('%d %s' % (n, names.get(k, k)) for k, n in rec.items())
        return ('fact_ore_recipe', dict(item=item, recipe=parts))
    if e['key'] == 'seprom':
        return ('fact_ore_recipe', dict(item=item, recipe='10 promerium (skylab)'))
    maps = [m.replace('X', str(fac)) for m, v in ((I.get('ores') or {}).get('maps') or {}).items() if kid in v]
    if maps:
        return ('fact_ore_where', dict(item=item, maps=', '.join(maps[:3])))
    if e['key'] == 'xenomit':                                   # npc.json cargo '3': boss / uber aliens and Cubikon; Skylab's xeno module
        return ('fact_xenomit', dict(item=item))
    return None


STAT_KEYS = ('laser', 'shield', 'hp', 'rocket', 'speed', 'ep', 'honor', 'absorb', 'npc')


def _bonus_text(v, lang):
    names = (LX.DATA.get(lang) or {}).get('names') or {}
    parts = ['%+d%% %s' % (round(v[k] * 100), names.get('stat_' + k, k)) for k in STAT_KEYS if v.get(k)]
    return ', '.join(parts[:3])


def _other(e, q, pe, lang, r):
    """Formations (from items.json), clan founding (clan.FOUNDING_COST), rank (ranks.json formula), honor, skylab."""
    if e['kind'] == 'formation':
        forms = {k: v for k, v in ((_items().get('formations') or {}).items()) if k != 'drone_formation_default'}
        nick = lambda k: FORMATION_NAMES.get(k.split('-')[-1], k)
        if e['loot'] and e['loot'] in forms:
            v = forms[e['loot']]
            p = K.price(e['loot'])
            if q == 'price' and p:
                return ('fact_price', dict(item=e['nick'], price=price_text(p, pe, lang, r)))
            return ('fact_formation_one', dict(item=e['nick'], bonus=_bonus_text(v, lang), price=price_text(p, pe, lang, r) if p else None))
        dmg = max(forms, key=lambda k: forms[k].get('laser', 0))
        sh = max(forms, key=lambda k: forms[k].get('shield', 0))
        pve = max(forms, key=lambda k: forms[k].get('npc', 0) + forms[k].get('ep', 0))
        alt = r.choice((('pve', pve), ('shield', sh)))
        return ('fact_formation', dict(item=nick(dmg), n=round(forms[dmg]['laser'] * 100), item2=nick(alt[1]),
                                       pct=round(max(forms[alt[1]].get('shield', 0), forms[alt[1]].get('ep', 0)) * 100)))
    if e['kind'] == 'clan':
        if q not in ('make', 'price', 'get'):
            return None
        import clan as KL
        return ('fact_clan_found', dict(price=price_text(('C', KL.FOUNDING_COST), pe, lang, r)))
    if e['kind'] == 'rank':
        return ('fact_rank', {})
    if e['kind'] == 'honor':
        return ('fact_honor', {})
    if e['kind'] == 'skylab':
        return ('fact_skylab', {})
    return None


def _sell_maps(fac):
    return ', '.join(H.name(m) for m in K.sell_maps(fac))


def _alien_type(alien):
    for v in (_load('npc.json').get('types') or {}).values():
        if KN.alien_name(v).lower() == alien.lower():
            return v
    return None
