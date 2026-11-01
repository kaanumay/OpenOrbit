"""Log of bot name changes and deletions: the panel's Bots page writes it, the game applies it everywhere.

A bot's name is held by name in many places in the game: the clan's members, leader, applications (clan.py), the player's clan copy (profile
'clan'), contact lists (profile 'contacts': friend, request, blocked), the memory and contacts of the other bots. When the panel renames a bot,
regenerates the roster, reduces the bot count or deletes the package, it appends ordered events here:
  {'n': seq, 't': time, 'type': 'name', 'eski': name, 'new': name}   name changed
  {'n', 't', 'type': 'delete', 'name': name}                        the bot no longer exists (removed from everywhere)
  {'n', 't', 'type': 'clan_leave', 'name': name}                    its progress was reset: leaves the clans, its acquaintances remain
Every consumer stores the last sequence it applied (profile 'bot_name_log', clan file 'bot_name_log', package state.json) and applies only the
new ones once: a change made while the game is closed at the next login, while it is open at once through the panel channel (panel_channel
/bot/ad_kaydi). Even if someone else later takes a deleted name, the old event does not touch them.
It works by name: when the roster is regenerated the new bots take the old ones' ids (1800000000 + sequence).
Mail already sent and received is history and stays as it is.
"""
import json, os, threading, time

import paths as PTH

LOCK = threading.RLock()
_cache = {'mtime': None, 'events': []}
BOT_UID = (1800000000, 1900000000)        # bot ids (bot/state.BOT_UID_BASE ...): when clan leadership passes to a human


def file():
    return os.path.join(PTH.SAVE, 'bots', '_name_log.json')


def read():
    """All events (from the cache unless the file changes)."""
    p = file()
    try:
        m = os.path.getmtime(p)
    except OSError:
        return []
    with LOCK:
        if _cache['mtime'] != m:
            try:
                with open(p, encoding='utf8') as f:
                    _cache['events'] = json.load(f).get('events') or []
            except (OSError, ValueError):
                _cache['events'] = []
            _cache['mtime'] = m
        return _cache['events']


def last():
    o = read()
    return o[-1]['n'] if o else 0


def add(events):
    """Panel: append events (rename, deletion). -> last sequence."""
    events = [x for x in events if x]
    if not events:
        return last()
    with LOCK:
        all_ = list(read())
        n = all_[-1]['n'] if all_ else 0
        t = time.time()
        for x in events:
            n += 1
            all_.append(dict(x, n=n, t=t))
        p = file()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + '.tmp', 'w', encoding='utf8') as f:
            json.dump({'events': all_}, f, ensure_ascii=False)
        os.replace(p + '.tmp', p)
        _cache['mtime'] = None
        return n


def events_since(n):
    return [x for x in read() if x['n'] > int(n or 0)]


# ------------------------------------------------------------------------------------------------------------ apply
def _k(name):
    return str(name or '').strip().lower()


def apply_list(lst, events):
    """Name list (contacts): rename and deletion -> new list or None (unchanged)."""
    out, changed = list(lst), False
    for e in events:
        if e['type'] == 'name':
            new_ = []
            for x in out:
                if _k(x) == _k(e['eski']):
                    x, changed = e['new'], True
                if not any(_k(y) == _k(x) for y in new_):
                    new_.append(x)
            out = new_
        elif e['type'] == 'delete':
            remaining = [x for x in out if _k(x) != _k(e['name'])]
            changed = changed or len(remaining) != len(out)
            out = remaining
    return out if changed else None


def apply_clan(k, events):
    """Clan record (the main record or the copy in the profile) -> 'vacant' (nobody left), True (changed) or False. If the leader goes, leadership
    passes to a human member (or the next one if none)."""
    changed = False
    for e in events:
        if e['type'] == 'name':
            old, new_ = _k(e['eski']), _k(e['new'])
            if old in k['members'] and old != new_:
                k['members'][new_] = dict(k['members'].pop(old), name=e['new'])
                if k['leader'] == old:
                    k['leader'] = new_
                changed = True
            for b in k.get('applications', []):
                if _k(b.get('name')) == old:
                    b.update(name=new_, first_name=e['new'])
                    changed = True
            k['rejected'] = [new_ if _k(r) == old else r for r in k.get('rejected', [])]
        else:                                            # delete, clan_leave
            a = _k(e['name'])
            if a in k['members']:
                del k['members'][a]
                changed = True
                if k['leader'] == a:
                    if not k['members']:
                        return 'vacant'
                    human = [x for x, u in k['members'].items() if not BOT_UID[0] <= int(u.get('uid') or 0) < BOT_UID[1]]
                    k['leader'] = (human or list(k['members']))[0]
            n = len(k.get('applications', []))
            k['applications'] = [b for b in k.get('applications', []) if _k(b.get('name')) != a]
            changed = changed or n != len(k['applications'])
            if e['type'] == 'delete':
                k['rejected'] = [r for r in k.get('rejected', []) if _k(r) != a]
    return changed


def apply_profile(p):
    """Pending events to the profile's contacts and clan copy (while a session opens, while contacts are read) -> whether changed."""
    new_ = events_since(p.d.get('bot_name_log', 0))
    if not new_:
        return False
    changed = False
    with p.lock:
        r = p.d.get('contacts') or {}
        for name in ('friend', 'incoming', 'outgoing', 'declined', 'blocked'):
            if isinstance(r.get(name), list):
                x = apply_list(r[name], new_)
                if x is not None:
                    r[name], changed = x, True
        k = p.d.get('clan')
        if k and 'members' in k:
            s = apply_clan(k, new_)
            if s == 'vacant':
                p.d['clan'] = None
                p.d['pilot'].update(clanId=0, clanTag='')
            changed = changed or bool(s)
        p.d['bot_name_log'] = new_[-1]['n']
        p.dirty = True
    return changed


def apply_clans(KL):
    """Pending events to the main clan records (clan.CLANS); a clan that empties is deleted (its diplomacy too) -> changed clans."""
    new_ = events_since(KL.BOT_NAME_N)
    if not new_:
        return []
    out = []
    with KL.LOCK:
        for cid, k in list(KL.CLANS.items()):
            s = apply_clan(k, new_)
            if s == 'vacant':
                KL.CLANS.pop(cid, None)
                KL.DELETED[cid] = k.get('anahtar')
                for c in KL.CLANS.values():
                    c['diplomacy'] = [d for d in c.get('diplomacy', []) if d['clan'] != cid]
                    c['diplomacy_requests'] = [r for r in c.get('diplomacy_requests', []) if cid not in (r['from_clan'], r['to'])]
            elif s:
                out.append(k)
        KL.BOT_NAME_N = new_[-1]['n']
    for k in out:
        KL.changed(k)                                    # the version increases, the connected members' copies are refreshed
    KL.save()
    return out
