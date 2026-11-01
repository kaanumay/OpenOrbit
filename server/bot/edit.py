"""Botun ayrıntısı ve düzenlenmesi (panelin Botlar > Kadro > bot penceresi): profil, hangar, kişilik, ruh hâli, hafıza, anılar.

Aynı kod iki yerde çalışır: oyun kapalıyken panel paketin durum dosyasındaki sözlük üzerinde (panel/botlar.bot_duzenle), oyun
açıkken oyun sunucusu canlı botun k sözlüğü üzerinde, y.lock altında (panel_kanali /bot/edit). Kişilik kadroda durur (yönetici
her açılışta kadrodan okur): kd paketin kadro satırı. Her değer doğrulanır; geçersizse DuzenlemeHatasi (kod: panel kendi dilinde
iletir).
"""
import time

import map_links as H
import player_profile as PF
from . import catalog as K
from .personality import EMOTION_BASELINE

TRAITS = ('aggression', 'rekabet', 'sociability', 'patience', 'risk', 'loyalty', 'helpfulness', 'talkativeness', 'frugality', 'ambition')
CATEGORY = {'lazer': 'lasers', 'kalkan': 'shield_generators', 'hiz': 'speed_generators', 'drone': 'drones', 'ekstra': 'extras'}
MAX_COUNTS = {'lazer': 100, 'kalkan': 100, 'hiz': 100, 'drone': 10, 'ekstra': 100000}


class EditError(ValueError):
    def __init__(self, code, area=''):
        self.code, self.area = code, area
        super().__init__('%s %s' % (code, area))


def _short(loot):
    return str(loot).rsplit('_', 1)[-1].upper()


def catalog():
    """Düzenleyicinin seçenekleri: gemiler (tasarımlar hariç), eşyalar, cephane, haritalar."""
    E = K.ITEMS
    out = {'ships': [{'loot': l, 'ad': _short(l), 'lazer': v['laser'], 'gen': v['generators'], 'ekstra': v.get('extra', 1)}
                       for l, v in sorted(E['ships'].items(), key=lambda x: (x[1]['hp'], x[0])) if 'base' not in v],
           'ammunition': [{'loot': l, 'ad': _short(l)} for l in list(E['laser_ammo']) + list(E['rockets'])],
           'haritalar': [{'id': m, 'ad': H.name(m)} for m in K.MAPS]}
    for multiplier, key in CATEGORY.items():
        out[multiplier] = [{'loot': l, 'ad': _short(l)} for l in E[key]]
    for x in out['ekstra']:                  # ekstranın sayısı adet değil kalan hak (bot/ekstra.py): eklenince tam hakla takılır
        x['right'] = int((E['extras'][x['loot']] or {}).get('right', 1))
    return out


def _number(v, lo, hi, area, full=True):
    try:
        x = int(v) if full else float(v)
    except (TypeError, ValueError):
        raise EditError('value', area) from None
    if not lo <= x <= hi:
        raise EditError('interval', area)
    return x


def _memory_id(a):
    return '%.3f|%s' % (a['t'], a['kim'])


def appearance(k, roster_row, online=None):
    """Botun bütün durumu -> panelin penceresi (k: durum sözlüğü, yoksa None; kd: kadro satırı)."""
    out = {'no': roster_row['no'], 'ad': roster_row['ad'], 'firma': roster_row['firma'], 'archetype': roster_row['personality'].get('archetype'),
           'habit': roster_row['personality'].get('habit'), 'dil': roster_row['personality'].get('dil'),
           'traits': {o: round(roster_row['personality']['traits'].get(o, 0.5), 3) for o in TRAITS}, 'exists': k is not None,
           'online': online}
    if k is None:
        return out
    PF.level_for(0)
    lvl = int(k.get('seviye') or 1)
    e = k.get('gear') or K.new_gear()
    g = K.ITEMS['ships'].get(e.get('gemi')) or K.ITEMS['ships']['ship_phoenix']
    gear = K.outfit(e)
    try:
        stats = K.values(e)
    except (KeyError, ValueError, TypeError):
        stats = {}
    quest = None
    if k.get('gorev'):
        from .goals import quest as QU
        quest = {'id': k['gorev'].get('id'), 'ad': QU.quests().get(k['gorev'].get('id'), {}).get('ad', '?')}
    kinds = K.ITEMS['ores']['kinds']
    capacity = K.cargo_capacity(e)
    now = time.time()
    out.update(
        profil={'seviye': lvl, 'ep': int(k.get('ep') or 0), 'next_ep': next((n for lv, n in (PF._LEVELS or []) if lv == lvl + 1), None),
                'base_ep': next((n for lv, n in (PF._LEVELS or []) if lv == lvl), 0),
                'kredi': int(k.get('kredi') or 0), 'uridyum': int(k.get('uridyum') or 0), 'onur': int(k.get('onur') or 0),
                'harita': k.get('harita'), 'map_name': H.name(k['harita']) if k.get('harita') else '', 'hedef': k.get('hedef'),
                'intent': (k.get('intent') or {}).get('hedef'), 'klan': k.get('klan'), 'registered': k.get('registered', True),
                'friends': list(k.get('friends') or [])},
        mood={d: round(float((k.get('mood') or {}).get(d, EMOTION_BASELINE[d])), 3) for d in EMOTION_BASELINE},
        gear={'gemi': e.get('gemi'), 'ammunition': e.get('ammunition'), **{multiplier: dict(e.get(multiplier) or {}) for multiplier in CATEGORY}},
        yuva={'lazer': gear['laser_slots'], 'gen': gear['gen_slot'], 'ekstra': g.get('extra', 1), 'ship_laser': g['laser']},
        power={'power': round(stats.get('power', 0), 1), 'dps': round(stats.get('dps', 0)), 'ehp': round(stats.get('ehp', 0))},
        stock={l: int(n) for l, n in (k.get('stock') or {}).items()},
        kargo={_short(kinds.get(str(t), 'ore_%s' % t)): int(n) for t, n in (k.get('kargo') or {}).items() if n},
        cargo_capacity=capacity, gorev=quest, tamam=len(k.get('tamam') or ()), stats=dict(k.get('stats') or {}),
        gate_times=dict(k.get('gate_times') or {}),
        warning={x: v for x, v in (k.get('warning') or {}).items() if x in ('sohbet', 'pvp', 'kutu') and v > time.time()},     # yönetici uyarısı
        skylab=dict((k.get('skylab') or {}).get('mod') or {}), formation=k.get('formation'),
        relations=sorted(({'anahtar': a, 'ad': v.get('ad', a), 'd': round(v.get('d', 0), 3), 'n': v.get('n', {})}
                          for a, v in (k.get('memory') or {}).items()), key=lambda x: -abs(x['d'])),
        memories=[{'id': _memory_id(a), 'kim': a['kim'], 'summary': a['summary'], 't': a['t'], 'n': a.get('n', 1), 'tur': a.get('tur'),
                 'importance': a.get('importance'), 'takip': a.get('takip')} for a in sorted(k.get('memories') or [], key=lambda a: -a['t'])],
        impression=[{'anahtar': a, 'ad': v.get('ad', a), 'metin': v.get('metin', '')} for a, v in (k.get('impression') or {}).items()],
        ledger=[x['metin'] for x in k.get('ledger') or [] if not x.get('finished')],
        reminder=[{'metin': x.get('metin'), 'time_left_sec': max(0, int(x.get('due', now) - now))} for x in k.get('reminder') or []],
        savings=k.get('savings'), agent=list(k.get('agent') or [])[-20:])
    return out


def apply(k, roster_row, value, online=False):
    """Düzenlemeleri k (durum) ve kd (kadro satırı) üzerinde uygula -> değişen alanlar. Önce hepsi doğrulanır: biri geçersizse hiçbiri
    uygulanmaz."""
    value = value if isinstance(value, dict) else {}
    jobs = []
    gear = k.setdefault('gear', K.new_gear()) if k is not None else None
    needs_state = [a for a in value if a not in ('traits',)]
    if needs_state and k is None:
        raise EditError('no_state')
    E = K.ITEMS
    if 'ep' in value:
        ep = _number(value['ep'], 0, 10 ** 12, 'ep')
        jobs.append(lambda ep=ep: k.update(ep=ep, seviye=PF.level_for(ep)))
    for a, lo, hi in (('kredi', 0, 2 * 10 ** 12), ('uridyum', 0, 2 * 10 ** 12), ('onur', -2 * 10 ** 12, 2 * 10 ** 12)):
        if a in value:
            v = _number(value[a], lo, hi, a)
            jobs.append(lambda a=a, v=v: k.__setitem__(a, v))
    if 'harita' in value:
        m = _number(value['harita'], 1, max(K.MAPS), 'harita')
        if m not in K.MAPS:
            raise EditError('interval', 'harita')
        if online:
            raise EditError('online', 'harita')     # çevrimiçi botu ışınlamak soyut/somut konumunu bozar
        jobs.append(lambda m=m: k.update(harita=m, intent=None, hedef=None))
    if 'gemi' in value:
        g = value['gemi']
        if g not in E['ships'] or 'base' in E['ships'][g]:
            raise EditError('esya', 'gemi')
        jobs.append(lambda g=g: gear.__setitem__('gemi', g))
    if 'ammunition' in value:
        c = value['ammunition']
        if c not in E['laser_ammo']:
            raise EditError('esya', 'ammunition')
        jobs.append(lambda c=c: gear.__setitem__('ammunition', c))
    for multiplier, items in (value.get('gear') or {}).items():
        if multiplier not in CATEGORY or not isinstance(items, dict):
            raise EditError('esya', multiplier)
        new_ = {}
        for l, n in items.items():
            if l not in E[CATEGORY[multiplier]]:
                raise EditError('esya', l)
            n = _number(n, 0, MAX_COUNTS[multiplier], l)
            if n:
                new_[l] = n
        jobs.append(lambda multiplier=multiplier, new_=new_: gear.__setitem__(multiplier, new_))
    if 'stock' in value:
        valid = set(E['laser_ammo']) | set(E['rockets']) | set((k.get('stock') or {}))
        new_ = {}
        for l, n in (value['stock'] or {}).items():
            if l not in valid:
                raise EditError('esya', l)
            new_[l] = _number(n, 0, 10 ** 9, l)
        jobs.append(lambda new_=new_: k.setdefault('stock', {}).update(new_))
    if value.get('empty_cargo'):
        jobs.append(lambda: k.__setitem__('kargo', {}))
    if value.get('cancel_quest'):
        jobs.append(lambda: k.__setitem__('gorev', None))
    if 'traits' in value:
        new_ = {}
        for o, v in (value['traits'] or {}).items():
            if o not in TRAITS:
                raise EditError('value', o)
            new_[o] = round(_number(v, 0.0, 1.0, o, full=False), 3)

        def personality(new_=new_):
            roster_row['personality']['traits'].update(new_)
            if k is not None and k.get('personality') is not roster_row['personality'] and isinstance(k.get('personality'), dict):
                k['personality'].setdefault('traits', {}).update(new_)
        jobs.append(personality)
    if 'mood' in value:
        new_ = {}
        for d, v in (value['mood'] or {}).items():
            if d not in EMOTION_BASELINE:
                raise EditError('value', d)
            new_[d] = round(_number(v, 0.0, 1.0, d, full=False), 3)
        jobs.append(lambda new_=new_: k.setdefault('mood', {}).update(new_))
    mem = k.setdefault('memory', {}) if k is not None else {}
    for a, v in (value.get('relation') or {}).items():
        if a not in mem:
            raise EditError('none', a)
        v = round(_number(v, -1.0, 1.0, a, full=False), 3)
        jobs.append(lambda a=a, v=v: mem[a].update(d=v, s=time.time()))
    for a in value.get('delete_relation') or ():
        jobs.append(lambda a=a: mem.pop(a, None))
    if 'memory_log' in value or 'delete_memory' in value:
        mems = k.setdefault('memories', []) if k is not None else []
        ids = {_memory_id(a): a for a in mems}
        for i, text in (value.get('memory_log') or {}).items():
            if i not in ids or not str(text).strip():
                raise EditError('none' if i not in ids else 'value', 'memory_log')
            jobs.append(lambda a=ids[i], m=' '.join(str(text).split())[:200]: a.__setitem__('summary', m))
        remove = set(value.get('delete_memory') or ())
        if remove:
            jobs.append(lambda remove=remove: mems.__setitem__(slice(None), [a for a in mems if _memory_id(a) not in remove]))
    trace = k.setdefault('impression', {}) if k is not None else {}
    for a, text in (value.get('impression') or {}).items():
        if a not in trace or not str(text).strip():
            raise EditError('none' if a not in trace else 'value', 'impression')
        jobs.append(lambda a=a, m=' '.join(str(text).split())[:240]: trace[a].update(metin=m))
    for a in value.get('delete_impression') or ():
        jobs.append(lambda a=a: trace.pop(a, None))
    if 'ledger' in value:
        texts = [' '.join(str(x).split())[:160] for x in value['ledger'] or [] if str(x).strip()][:8]
        jobs.append(lambda texts=texts: k.__setitem__('ledger', [x for x in k.get('ledger') or [] if x.get('finished')]
                                           + [{'metin': m, 't': time.time()} for m in texts]))
    if value.get('clear_reminder'):
        jobs.append(lambda: k.__setitem__('reminder', []))
    if value.get('clear_savings'):
        jobs.append(lambda: k.__setitem__('savings', None))
    if value.get('cancel_followup'):
        remove = set(value['cancel_followup'])
        jobs.append(lambda remove=remove: [a['takip'].__setitem__('finished', True) for a in k.get('memories') or ()
                              if a.get('takip') and _memory_id(a) in remove])
    if value.get('clear_agent'):
        jobs.append(lambda: k.__setitem__('agent', []))
    for f in jobs:
        f()
    return sorted(value)
