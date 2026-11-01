"""Events, Battle Pass and Season Pass: bots join the events on the calendar like players (the rules of the game's event_maps.py,
battle_pass.py, season.py and data/tickets.json).

  event       if the map section of an active event covers the bot's map: it hunts the event aliens it is strong enough for (in the concrete
              case those actually spawned on the map, in the abstract case from the section's list), takes their drops ('drop': event
              currency), collects the keyless event boxes on the map (contents from the game's event_maps.roll); the currency goes to Assembly's
              event recipes (loot.assembly)
  Battle Pass while an event with a pass lasts, pass quests are completed as the bot plays (by its share of time played and kills), the
              reward of each quest is collected; a bot that bought the pass (200,000 U, rich and ambitious bot) also gets a key per quest;
              keys are spent in the exchange table on the reward with the best value / key ratio (within its limit)
  Season Pass points from daily and weekly quests (with hours played); when the level's point cost is filled, the free track's reward
State: bot.k['pass'] = {'period', 'done', 'purchased', 'sure', 'exchange': {reward: count}}, bot.k['season'] = {'period', 'points', 'level'}.
"""
import json, os, random, time

from . import catalog as K

B = json.load(open(os.path.join(K.HERE, 'data', 'tickets.json'), encoding='utf8'))
SEASON = B['season']
BT = B['battle_pass']
PASS_PRICE = 200000
PASS_QUEST_SEC = 2700            # one pass quest per ~45 minutes played
SEASON_POINTS_PER_HOUR = 30            # Season Pass points per hour played (daily + weekly quests)
_on = {'t': 0, 'section': [], 'active': set()}


def _refresh():
    import event_maps as EM, event_calendar as CAL
    t = time.time()
    if t - _on['t'] > 60:
        _on.update(t=t, section=EM.specs(), active=set(CAL.active()))
    return _on


def sections(game_map):
    """Active event map sections covering this map [(event, section)]."""
    import map_links as H
    klass, name = H.map_class(game_map), H.name(game_map)
    return [(k, s) for k, s in _refresh()['section'] if klass in s.get('maps', ()) or name in s.get('maps', ())]


def event_types(bot, game_map):
    """Event alien types it is strong enough for."""
    d = bot.value()
    out = set()
    for _, s in sections(game_map):
        for u in s.get('alien_spawns', []):
            tip = str(u['type']).replace('{x}', 'x%s' % map_number(game_map)) if '{x}' in str(u['type']) else str(u['type'])
            v = K.npc_value(tip) or K.npc_value(str(u['type']))
            if v and d['dps'] > 0 and v['ehp'] / d['dps'] < 120 and v['dps'] * v['ehp'] / d['dps'] < d['ehp'] * 0.6:
                out.add(tip if K.npc_value(tip) else str(u['type']))
    return out


def map_number(game_map):
    import map_links as H
    return H.name(game_map).split('-')[-1]


def drop(bot, game_map, tip):
    """The event drops of an event alien (or of the map's alien) to the bot (the game's event_maps.roll)."""
    import world as WD
    import event_maps as EM
    from . import loot as LT
    if not bot.permission.get('event', True):
        return
    b = EM.base(tip)
    for _, s in sections(game_map):
        tab = s.get('drop', {})
        for loot, a in (tab.get(tip) or tab.get(b) or {}).items():
            n = WD.extra_count(a, 1.0)                    # the game's reading: a number, [min, max] or {count, probability} (Agatus)
            if n > 0:
                LT.give(bot, loot, n)
                bot.ist('event_drop', n)
        box_drop = (s.get('box_drop', {}).get(tip) or s.get('box_drop', {}).get(b))
        if box_drop and random.random() < box_drop.get('probability', 1.0) * 0.8:            # mostly picks up the chest that dropped
            for loot, n in EM.roll(box_drop):
                LT.give(bot, loot, n)


def open_box(bot, spec):
    import event_maps as EM
    from . import loot as LT
    got = EM.roll(spec)
    for loot, n in got:
        LT.give(bot, loot, n)
    bot.ist('event_box')
    return got


def abstract(bot, dt, y, dps):
    """Abstract: hunts the event aliens (their drops and kill reward) and comes across the map's event boxes."""
    if not bot.permission.get('event', True):
        return
    bl = sections(bot.game_map)
    if not bl:
        return
    speed = y.speed(bot) if y is not None else 1.0
    crowd = max(1.0, 0.3 * len(y.on_map.get(bot.game_map, ()))) if y is not None else 1.0
    kinds = event_types(bot, bot.game_map)
    for k, s in bl:
        for u in s.get('alien_spawns', []):
            tip = next((t for t in kinds if t == str(u['type']) or t.startswith(str(u['type']).split('{')[0])), None)
            v = K.npc_value(tip) if tip else None
            if not v:
                continue
            ratio = min(u.get('count', 1) * dt / 60.0 / crowd, dt * 0.25 * dps / max(1.0, v['ehp']))    # event alien share
            n = int(ratio) + (bot.r.random() < ratio - int(ratio))
            for _ in range(n):
                o = v['reward']
                bot.reward('npc', speed, ep=o.get('ep', 0), credits=o.get('credits', 0), uridium=o.get('uridium', 0), honor=o.get('honor', 0))
                drop(bot, bot.game_map, tip)
            if n:
                bot.ist('event_npc', n)
                if y is not None:
                    y.npc_killed(bot, tip, n)
        for box in s.get('boxes', []):
            respawn = box.get('renew_sec') or [300, 600]
            if bot.r.random() < box.get('count', 1) * dt / (sum(respawn) / 2.0) / crowd:
                open_box(bot, box)


# ------------------------------------------------------------------------------------------------------------ Battle Pass
def active_pass():
    """The event of the pass currently running (the active event that has a pass) or None."""
    active = _refresh()['active']
    return next((k for k in BT['passes'] if k in active), None)


def battle_pass(bot, dt):
    """Pass quests are completed as the bot plays; reward and (if the pass was bought) keys; keys go to the exchange."""
    from . import loot as LT
    if not bot.permission.get('event', True):
        return
    k = active_pass()
    if not k:
        return
    st = bot.k.setdefault('pass', {})
    if st.get('period') != k:
        st.clear()
        st.update(period=k, done=0, purchased=False, sure=0.0, exchange={})
    p = BT['passes'][k]
    rewards = list((p.get('rewards') or {}).values())
    if not st['purchased'] and not p.get('keyless') and bot.level >= 12 and bot.o('ambition') > 0.6 \
            and bot.k['uridium'] > PASS_PRICE * (2 + bot.o('frugality')) and bot.pay('U', PASS_PRICE * bot.game_settings.multiplier('shop_price')):
        st['purchased'] = True
        bot.ist('battle_pass')
        stock = LT.stock(bot)
        stock['resource_battle-pass-key'] = stock.get('resource_battle-pass-key', 0) + st['done']     # collected up to that moment
    st['sure'] += dt
    while st['sure'] >= PASS_QUEST_SEC and st['done'] < len(rewards):
        st['sure'] -= PASS_QUEST_SEC
        o = rewards[st['done']]
        st['done'] += 1
        for loot, n in o.get('reward', []):
            LT.give(bot, loot, n)
        if st['purchased']:
            stock = LT.stock(bot)
            stock['resource_battle-pass-key'] = stock.get('resource_battle-pass-key', 0) + o.get('anahtar', 0)
        bot.ist('pass_quest')
    exchange(bot, st)


def exchange(bot, st):
    """Spends Battle Pass keys in the exchange table on the reward with the best value / key ratio (within its limit)."""
    from . import loot as LT
    stock = LT.stock(bot)
    table = (BT['passes'].get(st['period']) or {}).get('key_exchange') or BT['key_exchange']
    while stock.get('resource_battle-pass-key', 0) > 0:
        eligible = [r for r in table if r['cost'] <= stock['resource_battle-pass-key']
                 and st['exchange'].get(r['exchangeReward'], 0) < r.get('limit', 99)]
        if not eligible:
            return
        r = max(eligible, key=lambda r: sum(LT.value(l['lootId'], l['amount']) for l in r['listOfloot']) / max(1, r['cost']))
        stock['resource_battle-pass-key'] -= r['cost']
        st['exchange'][r['exchangeReward']] = st['exchange'].get(r['exchangeReward'], 0) + 1
        for l in r['listOfloot']:
            LT.give(bot, l['lootId'], l['amount'])
        bot.ist('pass_exchange')


# ------------------------------------------------------------------------------------------------------------ Season Pass
def season_period():
    t = time.localtime()
    month = ((t.tm_mon - 2) // 3) * 3 + 2 if t.tm_mon >= 2 else 11
    return '%d-%02d' % (t.tm_year if t.tm_mon >= 2 else t.tm_year - 1, month)


def season_pass(bot, dt):
    from . import loot as LT
    if not bot.permission.get('event', True):
        return
    st = bot.k.setdefault('season', {})
    d = season_period()
    if st.get('period') != d:
        st.clear()
        st.update(period=d, points=0.0, level=0)
    st['points'] += SEASON_POINTS_PER_HOUR * dt / 3600.0 * (0.7 + 0.6 * bot.o('ambition'))
    cost = SEASON['point_cost']
    order = {lv: (loot, n) for lv, loot, n in SEASON['reward'].get('free', [])}
    while st['level'] + 1 < len(cost) and st['points'] >= cost[st['level'] + 1]:
        st['points'] -= cost[st['level'] + 1]
        st['level'] += 1
        if st['level'] in order:
            LT.give(bot, *order[st['level']])
        bot.ist('season_level')
