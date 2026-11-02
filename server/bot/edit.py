"""A bot's details and editing (the panel's Bots > Roster > bot window): profile, hangar, personality, mood, memory, recollections.

The same code runs in two places: when the game is closed, the panel on the dictionary in the package's state file (panel/bots.edit_bot), when the game is
open, the game server on the live bot's k dictionary, under y.lock (panel_channel /bot/edit). Personality lives in the roster (manager
reads it from the roster on every start): kd is the package's roster row. Every value is validated; if invalid, EditError (code: the panel
conveys it in its own language).
"""
import time

import map_links as H
import player_profile as PF
from . import catalog as K
from .personality import EMOTION_BASELINE

TRAITS = ('aggression', 'rivalry', 'sociability', 'patience', 'risk', 'loyalty', 'helpfulness', 'talkativeness', 'frugality', 'ambition')
CATEGORY = {'laser': 'lasers', 'shield': 'shield_generators', 'speed': 'speed_generators', 'drone': 'drones', 'extras': 'extras'}
MAX_COUNTS = {'laser': 100, 'shield': 100, 'speed': 100, 'drone': 10, 'extras': 100000}


class EditError(ValueError):
    def __init__(self, code, area=''):
        self.code, self.area = code, area
        super().__init__('%s %s' % (code, area))


def _short(loot):
    return str(loot).rsplit('_', 1)[-1].upper()


def catalog():
    """The editor's options: ships (excluding designs), items, ammo, maps."""
    E = K.ITEMS
    out = {'ships': [{'loot': l, 'name': _short(l), 'laser': v['laser'], 'gen': v['generators'], 'extras': v.get('extra', 1)}
                       for l, v in sorted(E['ships'].items(), key=lambda x: (x[1]['hp'], x[0])) if 'base' not in v],
           'ammunition': [{'loot': l, 'name': _short(l)} for l in list(E['laser_ammo']) + list(E['rockets'])],
           'maps': [{'id': m, 'name': H.name(m)} for m in K.MAPS]}
    for multiplier, key in CATEGORY.items():
        out[multiplier] = [{'loot': l, 'name': _short(l)} for l in E[key]]
    for x in out['extras']:                  # an extra's count is the remaining uses, not a quantity (bot/extras.py): when added it is fitted with full uses
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
    return '%.3f|%s' % (a['t'], a['who'])


ROSTER_FIELDS = ('traits', 'likes', 'talent', 'spend')      # edits that live in the roster (the pack file), not in the state


def _profile(roster_row):
    """The pack's play profile of the bot (stored in the roster, otherwise derived from the name without storing it)."""
    from . import playstyle as PL
    p = roster_row['personality']
    pl = p.get('play')
    if isinstance(pl, dict) and pl.get('v') == 1:
        return pl
    return PL.generate(dict(p, _name=roster_row['name']))


def _play(k, roster_row):
    """Play style for the bot window: talent, enjoyment, habits, spending (roster) and the current skill and motivation (state)."""
    from . import playstyle as PL
    pl = _profile(roster_row)
    st = (k or {}).get('play') if isinstance((k or {}).get('play'), dict) else {}
    skill = st.get('skill') or {d: round(pl['talent'][d] * pl['start'], 3) for d in PL.DOMAINS}
    return dict(talent={d: round(pl['talent'][d], 3) for d in PL.DOMAINS}, skill={d: round(skill.get(d, 0), 3) for d in PL.DOMAINS},
                likes={a: round(pl['likes'][a], 3) for a in PL.ACTIVITIES}, quirks=list(pl['quirks']), spend=pl['spend'],
                wallet=pl['wallet'], roam=pl['roam'], target=pl['target'], daily_h=pl.get('daily_h'),
                motivation=round(st.get('motivation', pl['motivation']), 3), theme=st.get('theme'), break_until=st.get('brk', 0) or 0,
                summary=pl.get('summary') or PL.summary(pl))


def appearance(k, roster_row, online=None):
    """All of the bot's state -> the panel's window (k: state dictionary, None if absent; kd: roster row)."""
    out = {'no': roster_row['no'], 'name': roster_row['name'], 'company': roster_row['company'], 'archetype': roster_row['personality'].get('archetype'),
           'habit': roster_row['personality'].get('habit'), 'lang': roster_row['personality'].get('lang'),
           'traits': {o: round(roster_row['personality']['traits'].get(o, 0.5), 3) for o in TRAITS}, 'exists': k is not None,
           'online': online, 'play': _play(k, roster_row)}
    if k is None:
        return out
    PF.level_for(0)
    lvl = int(k.get('level') or 1)
    e = k.get('gear') or K.new_gear()
    g = K.ITEMS['ships'].get(e.get('ship')) or K.ITEMS['ships']['ship_phoenix']
    gear = K.outfit(e)
    try:
        stats = K.values(e)
    except (KeyError, ValueError, TypeError):
        stats = {}
    quest = None
    if k.get('quest'):
        from .goals import quest as QU
        quest = {'id': k['quest'].get('id'), 'name': QU.quests().get(k['quest'].get('id'), {}).get('name', '?')}
    kinds = K.ITEMS['ores']['kinds']
    capacity = K.cargo_capacity(e)
    now = time.time()
    out.update(
        profile={'level': lvl, 'ep': int(k.get('ep') or 0), 'next_ep': next((n for lv, n in (PF._LEVELS or []) if lv == lvl + 1), None),
                'base_ep': next((n for lv, n in (PF._LEVELS or []) if lv == lvl), 0),
                'credits': int(k.get('credits') or 0), 'uridium': int(k.get('uridium') or 0), 'honor': int(k.get('honor') or 0),
                'map': k.get('map'), 'map_name': H.name(k['map']) if k.get('map') else '', 'target': k.get('target'),
                'intent': (k.get('intent') or {}).get('target'), 'clan': k.get('clan'), 'registered': k.get('registered', True),
                'friends': list(k.get('friends') or [])},
        mood={d: round(float((k.get('mood') or {}).get(d, EMOTION_BASELINE[d])), 3) for d in EMOTION_BASELINE},
        gear={'ship': e.get('ship'), 'ammunition': e.get('ammunition'), **{multiplier: dict(e.get(multiplier) or {}) for multiplier in CATEGORY}},
        slot={'laser': gear['laser_slots'], 'gen': gear['gen_slot'], 'extras': g.get('extra', 1), 'ship_laser': g['laser']},
        power={'power': round(stats.get('power', 0), 1), 'dps': round(stats.get('dps', 0)), 'ehp': round(stats.get('ehp', 0))},
        stock={l: int(n) for l, n in (k.get('stock') or {}).items()},
        cargo={_short(kinds.get(str(t), 'ore_%s' % t)): int(n) for t, n in (k.get('cargo') or {}).items() if n},
        cargo_capacity=capacity, quest=quest, done=len(k.get('done') or ()), stats=dict(k.get('stats') or {}),
        gate_times=dict(k.get('gate_times') or {}),
        warning={x: v for x, v in (k.get('warning') or {}).items() if x in ('chat', 'pvp', 'box') and v > time.time()},     # admin warning
        skylab=dict((k.get('skylab') or {}).get('mod') or {}), formation=k.get('formation'),
        relations=sorted(({'key': a, 'name': v.get('name', a), 'd': round(v.get('d', 0), 3), 'n': v.get('n', {})}
                          for a, v in (k.get('memory') or {}).items()), key=lambda x: -abs(x['d'])),
        memories=[{'id': _memory_id(a), 'who': a['who'], 'summary': a['summary'], 't': a['t'], 'n': a.get('n', 1), 'type': a.get('type'),
                 'importance': a.get('importance'), 'followup': a.get('followup')} for a in sorted(k.get('memories') or [], key=lambda a: -a['t'])],
        impression=[{'key': a, 'name': v.get('name', a), 'text': v.get('text', '')} for a, v in (k.get('impression') or {}).items()],
        ledger=[x['text'] for x in k.get('ledger') or [] if not x.get('finished')],
        reminder=[{'text': x.get('text'), 'time_left_sec': max(0, int(x.get('due', now) - now))} for x in k.get('reminder') or []],
        savings=k.get('savings'), agent=list(k.get('agent') or [])[-20:])
    return out


def apply(k, roster_row, value, online=False):
    """Apply the edits to k (state) and kd (roster row) -> the changed fields. All are validated first: if one is invalid none
    is applied."""
    value = value if isinstance(value, dict) else {}
    jobs = []
    gear = k.setdefault('gear', K.new_gear()) if k is not None else None
    needs_state = [a for a in value if a not in ROSTER_FIELDS]
    if needs_state and k is None:
        raise EditError('no_state')
    E = K.ITEMS
    if 'ep' in value:
        ep = _number(value['ep'], 0, 10 ** 12, 'ep')
        jobs.append(lambda ep=ep: k.update(ep=ep, level=PF.level_for(ep)))
    for a, lo, hi in (('credits', 0, 2 * 10 ** 12), ('uridium', 0, 2 * 10 ** 12), ('honor', -2 * 10 ** 12, 2 * 10 ** 12)):
        if a in value:
            v = _number(value[a], lo, hi, a)
            jobs.append(lambda a=a, v=v: k.__setitem__(a, v))
    if 'map' in value:
        m = _number(value['map'], 1, max(K.MAPS), 'map')
        if m not in K.MAPS:
            raise EditError('interval', 'map')
        if online:
            raise EditError('online', 'map')     # teleporting an online bot breaks its abstract/concrete position
        jobs.append(lambda m=m: k.update(map=m, intent=None, target=None))
    if 'ship' in value:
        g = value['ship']
        if g not in E['ships'] or 'base' in E['ships'][g]:
            raise EditError('item', 'ship')
        jobs.append(lambda g=g: gear.__setitem__('ship', g))
    if 'ammunition' in value:
        c = value['ammunition']
        if c not in E['laser_ammo']:
            raise EditError('item', 'ammunition')
        jobs.append(lambda c=c: gear.__setitem__('ammunition', c))
    for multiplier, items in (value.get('gear') or {}).items():
        if multiplier not in CATEGORY or not isinstance(items, dict):
            raise EditError('item', multiplier)
        new_ = {}
        for l, n in items.items():
            if l not in E[CATEGORY[multiplier]]:
                raise EditError('item', l)
            n = _number(n, 0, MAX_COUNTS[multiplier], l)
            if n and multiplier == 'drone' and not K.drone_room(new_, l, n):
                raise EditError('interval', l)           # Flax/Iris 8 in all, Apis and Zeus one each (catalog.drone_room)
            if n:
                new_[l] = n
        jobs.append(lambda multiplier=multiplier, new_=new_: gear.__setitem__(multiplier, new_))
    if 'stock' in value:
        valid = set(E['laser_ammo']) | set(E['rockets']) | set((k.get('stock') or {}))
        new_ = {}
        for l, n in (value['stock'] or {}).items():
            if l not in valid:
                raise EditError('item', l)
            new_[l] = _number(n, 0, 10 ** 9, l)
        jobs.append(lambda new_=new_: k.setdefault('stock', {}).update(new_))
    if value.get('empty_cargo'):
        jobs.append(lambda: k.__setitem__('cargo', {}))
    if value.get('cancel_quest'):
        jobs.append(lambda: k.__setitem__('quest', None))
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
    from . import playstyle as PL
    play_edit = {}
    for field, keys, lo, hi in (('likes', PL.ACTIVITIES, 0.15, 3.0), ('talent', PL.DOMAINS, 0.05, 1.0)):
        if field in value:
            new_ = {}
            for o, v in (value[field] or {}).items():
                if o not in keys:
                    raise EditError('value', o)
                new_[o] = round(_number(v, lo, hi, o, full=False), 3)
            play_edit[field] = new_
    if 'spend' in value:
        if value['spend'] not in ('saver', 'balanced', 'spender', 'impulsive'):
            raise EditError('value', 'spend')
        play_edit['spend'] = value['spend']
    if play_edit:
        def play(play_edit=play_edit):
            p = roster_row['personality']
            pl = p['play'] = dict(_profile(roster_row))           # stored in the roster from now on (the edited profile)
            for a, v in play_edit.items():
                if isinstance(v, dict):
                    pl[a] = dict(pl[a], **v)
                else:
                    pl[a] = v
            pl['summary'] = PL.summary(pl)
            if k is not None and isinstance(k.get('personality'), dict) and k['personality'] is not p:
                k['personality']['play'] = pl
        jobs.append(play)
    if 'skill' in value or 'motivation' in value:
        new_ = {}
        for o, v in (value.get('skill') or {}).items():
            if o not in PL.DOMAINS:
                raise EditError('value', o)
            new_[o] = round(_number(v, 0.0, 1.0, o, full=False), 4)
        mot = round(_number(value['motivation'], 0.02, 1.0, 'motivation', full=False), 3) if 'motivation' in value else None

        def state(new_=new_, mot=mot):
            st = k.get('play')
            if not isinstance(st, dict) or 'skill' not in st:
                pl = _profile(roster_row)
                st = k['play'] = dict(v=PL.STATE_VERSION, skill={d: round(pl['talent'][d] * pl['start'], 4) for d in PL.DOMAINS},
                                      xp={d: 0.0 for d in PL.DOMAINS}, motivation=pl['motivation'], maps={}, brk=0.0, paid=time.time(),
                                      theme=None, form=1.0)
            st['skill'].update(new_)
            if mot is not None:
                st['motivation'] = mot
        jobs.append(state)
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
        jobs.append(lambda a=a, m=' '.join(str(text).split())[:240]: trace[a].update(text=m))
    for a in value.get('delete_impression') or ():
        jobs.append(lambda a=a: trace.pop(a, None))
    if 'ledger' in value:
        texts = [' '.join(str(x).split())[:160] for x in value['ledger'] or [] if str(x).strip()][:8]
        jobs.append(lambda texts=texts: k.__setitem__('ledger', [x for x in k.get('ledger') or [] if x.get('finished')]
                                           + [{'text': m, 't': time.time()} for m in texts]))
    if value.get('clear_reminder'):
        jobs.append(lambda: k.__setitem__('reminder', []))
    if value.get('clear_savings'):
        jobs.append(lambda: k.__setitem__('savings', None))
    if value.get('cancel_followup'):
        remove = set(value['cancel_followup'])
        jobs.append(lambda remove=remove: [a['followup'].__setitem__('finished', True) for a in k.get('memories') or ()
                              if a.get('followup') and _memory_id(a) in remove])
    if value.get('clear_agent'):
        jobs.append(lambda: k.__setitem__('agent', []))
    for f in jobs:
        f()
    return sorted(value)
