"""Old text protocol (left over from the Flash era; LegacyModule {message}): helpers for building and parsing.

Dispatch in the client: belgeler/istemci/eski_protokol.md (tools/il2cpp/client_map.py). Server to client "0|<key>|...":
  0|LM|ST|<type>|...   gain/loot log: EP|<gain>|<total>|<level>, HON, CRE, URI (<gain>|<total>), BAT/ROK (ammo), LOT
                    (item, count) - BoxCollectResponseAssemblyHelper
  0|A|STM|<key>|...  localized on-screen message (loadfull, jumplevelfalse|%!|<level>, config_change_failed_time, ...);
                    the client only shows flashres keys. For the others (resource_system_inc ...) 0|A|CSTM|<key>|-1
                    (searches all resources): legacy() turns a parameterless STM that is not in flashres into this (live test H24)
  0|A|ACG|<achievement>_<level>|<count>  achievement earned effect and window
  0|A|SLA|0|<user>  collecting beam; 0|A|C|<credits>|<uridium>  money
  0|n|t|<user>|<title id>|<title>  title over the ship; 0|n|LSH|<target>|<attacker>  laser line;
  0|n|e|... / 0|n|INV|... / 0|n|d|...  ship appearance, invisibility, drone string; 0|S|CFG|<n>  config; 0|v|<attacker>|<target>|H|...  rocket;
  0|l  exit (the connection closes)
Client to server (save and logs): S|CFG|<n>|<user>|<key> (config switch), i|<id> (ask about an unknown entity),
LF|c and JCPU|GET (at every login; the real server does not reply).
"""

import json, os

MODULE = 'LegacyModule'
_FLASHRES = []                    # data/flashres_keys.json (tools/stm_keys.py); if the file is missing no translation is done


def flashres():
    if _FLASHRES == []:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'flashres_keys.json')
        _FLASHRES[:] = [set(json.load(open(p, encoding='utf8'))['keys']) if os.path.exists(p) else None]
    return _FLASHRES[0]


def legacy(text):
    """Command from ready text: legacy('0|A|STM|loadfull'). A parameterless STM that is not in flashres -> 0|A|CSTM|<key>|-1."""
    if text.startswith('0|A|STM|') and text.count('|') == 3:
        keys = flashres()
        if keys is not None and text[8:] not in keys:
            text = '0|A|CSTM|%s|-1' % text[8:]
    elif text.startswith(('0|LM|ST|CRE|', '0|LM|ST|URI|')):
        p = text.split('|')                # the client reads the gain as SafeInt (the total as SafeLong): a gain over 2^31-1 would show as negative
        if int(p[4]) > 2 ** 31 - 1:
            p[4] = str(2 ** 31 - 1)
            text = '|'.join(p)
    return (MODULE, {'message': text})


def msg(*parts):
    """A "0|..." command from parts: msg('A', 'STM', 'loadfull') -> 0|A|STM|loadfull."""
    return legacy('|'.join(['0'] + [str(p) for p in parts]))


def loot_kind(loot):
    """The item type of a 0|LM|ST line: BAT laser, RL rocket launcher (save: RL|ammunition_rocketlauncher_eco-10|7), ROK rocket ammo,
    the rest LOT; each has its own text in the client."""
    if loot.startswith('ammunition_laser_'):
        return 'BAT'
    if loot.startswith('ammunition_rocketlauncher_'):
        return 'RL'
    return 'ROK' if loot.startswith('ammunition_rocket_') else 'LOT'


# a LOT line takes its text from the item's client category (log_msg_gather_<category>_s/_p): the categories of these mines (acm, empm) have
# none and the log line was empty (user report 2026-11-07); the client's mine loot line is dead code (LM|ST|MIN is the mine explosion), so
# the mine text with its code (the client's items_<lootId>_code)
UNTEXTED_MINES = {'ammunition_mine_acm-01': 'ACM-1', 'ammunition_mine_empm-01': 'EMP-M01'}


def loot_line(loot, n):
    """The log line of n items received (LegacyModule)."""
    code = UNTEXTED_MINES.get(loot)
    if code:
        return msg('A', 'STM', 'log_msg_gather_mine_%s' % ('s' if n == 1 else 'p'), '%COUNT%', n, '%TYPE%', code)
    return legacy('0|LM|ST|%s|%s|%d' % (loot_kind(loot), loot, n))


def stm(key, *args):
    """Localized on-screen message: stm('jumplevelfalse', '%!', 2) -> 0|A|STM|jumplevelfalse|%!|2."""
    return msg('A', 'STM', key, *args)


def parse(fields):
    """From the client's LegacyModule fields -> (key, parts): 'S|CFG|2|...' -> ('S|CFG', [..]), 'i|533' -> ('i', ['i', '533'])."""
    parts = (fields or {}).get('message', '').split('|')
    key = '|'.join(parts[:2]) if parts and parts[0] == 'S' and len(parts) > 1 else parts[0] if parts else ''
    return key, parts


def text(m):
    """The text of a LegacyModule command (None if it is not one) - for tests and the log."""
    return m[1].get('message') if m and m[0] == MODULE else None
