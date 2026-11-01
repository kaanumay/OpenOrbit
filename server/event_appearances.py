"""Event appearances (data data/event_appearances.json <- tools/event_appearances.py): the designs without a source in the shop that
are won through an event in the real game, and the ways of winning them in single player.

The panel's 'event_looks_in_shop' setting (default on): when on they are sold in the shop (as in E11); when off they do not
appear in the shop and are not sold (shop.gate_ok). The ways are always open regardless of the setting:
  exchange battle_pass: in the key exchange while the event's Battle Pass lasts (exchange_rows)
  box      loot: into the box's local design rows with their weight (box_rows; those in the wiki table are 'table', no extra row)
  gate     calendar: an optional row in the gate rewards of GG Special Rewards Weekends (apply)
  map      calendar: into the contents of the event's map box (apply)
  season   season: the season designs in the reward tracks, in the season's order (season_track)
"""
import json, os, re

import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'event_appearances.json'), encoding='utf8'))
ITEMS = D['looks']
SEASONS = D['seasons']
RECORDED = SEASONS[-1]                   # the season in the save (its designs in the reward tracks)
FIRST = tuple(int(x) for x in SEASONS[0]['season'].split('-'))


def in_shop(loot):
    """Is it sold in the shop: if it is not an event appearance or the panel's setting is on."""
    return loot not in ITEMS or bool(SET.get(D['setting']))


def paths(kind):
    return [(loot, y) for loot, x in ITEMS.items() for y in x['paths'] if y['route'] == kind]


def exchange_id(loot):
    """Name of the key exchange row, in the client's format (<theme>-<ship>-ship-design, nobilis-a-elite-pet-design): the row's title is the
    client's items_bpk_<name>_fullname text (it has texts for the ones in the real game's exchanges, the title is empty for the others, the
    reward row is still "Obtain 1 ... Design")."""
    if loot.startswith('ship_'):
        base, d = re.match(r'ship_(.+?)_design_(.+)$', loot).groups()
        return '%s-%s-ship-design' % (re.sub(r'^(ship-)?%s-' % re.escape(base), '', d), base)
    kind = 'drone' if loot.startswith('drone_') else 'pet'
    name = re.sub(r'^%s-' % kind, '', loot.split('_designs_', 1)[1]).rsplit('-', 1)
    return '%s-%s-%s-design' % (name[1], name[0], kind) if len(name) == 2 else '%s-%s-design' % (name[0], kind)


def exchange_rows(event):
    """Design rows added to an event's key exchange (BattlePassKeyExchangeRewardModule; special like the designs in the save)."""
    return [dict(_='BattlePassKeyExchangeRewardModule', cost=y['charge'], limit=y['cap'], exchangeReward=exchange_id(loot),
                 listOfloot=[dict(_='BattlePassKeyExchangeLootModule', lootId=loot, amount=1)], priority=2, isSpecial=True, claimCount=0)
            for loot, y in paths('exchange') if y['event'] == event]


def box_rows(box):
    """The box's local design rows [lootId, 1, weight] (they take part in the design draw in loot.pick): appearances not in the wiki table
    and the box's old Red / Blue P.E.T. pool ('box_extra'); a design already in its table does not become an extra row ('table')."""
    return [[loot, 1, y['weight']] for loot, y in paths('box') if y['box'] == box and not y.get('table')] + \
           [list(r) for r in D.get('box_extra', {}).get(box, [])]


def apply(events):
    """Into the calendar's events (in place): the gates' optional reward and the contents of the map boxes."""
    gates = {}
    for loot, y in paths('gate'):
        gates.setdefault((y['event'], tuple(y['kapilar']), y['probability']), []).append([loot, 1])
    for (ev, keys, chance), rows in gates.items():
        for k, e in events.items():
            if k.startswith(ev):                               # gg_weekend_1, _3, _4
                e.setdefault('gate_reward', []).append(dict(kapilar=list(keys), probability=chance, choice=rows, non_repeating=True))
    for loot, y in paths('map'):
        e = events[y['event']]
        for s in ([e['map']] if 'map' in e else []) + e.get('map_extra', []):
            for b in s.get('boxes', []):
                if b['type'] == y['box']:
                    b['contents'].append([loot, 1, y['weight']])


def season(sid):
    """The season's designs (like '2026-11'): a 14-season order counted from the first season (2023-05), then from the start again."""
    y, m = (int(x) for x in sid.split('-'))
    n = ((y - FIRST[0]) * 12 + m - FIRST[1]) // 3
    return SEASONS[n % len(SEASONS)]


def season_track(key, rows, sid):
    """Reward track ('ucretsiz' | 'gold' | 'ext': [[level, lootId, count]]) -> with the season's designs: the season's drone and P.E.T.
    designs instead of those of the season in the save; if the season has a ship design, instead of the Gold track's last reward (the big Gold reserve)."""
    s = season(sid)
    swap = {RECORDED['drone']: s['drone'], RECORDED['pet']: s['pet']}
    out = [[lv, swap.get(l, l), n] for lv, l, n in rows]
    if key == 'gold' and s['ship']:
        out[-1] = [out[-1][0], s['ship'], 1]
    return out
