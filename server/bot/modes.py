"""Event-specific modes and PvE modes: bots enter every mode a player can, under the same rules (abstract run).

Each mode (a Mod subclass) from the game's data: is it open (calendar, time window), can it enter (level, ticket/key/CPU, daily /
yearly / cooldown limit, company), cost (a ticket is spent or bought with uridium), waves [(HP+shield, damage per second of those hitting
at the same time, the aliens' kill rewards)], lives, time limit and finishing reward (by the wave reached: stars, rifts,
steps, level). The run (kos) advances wave by wave: with the bot's best ammo and damage (the method of galaxy_gates.estimate), it stops when deaths
use up the lives; kill rewards are those of the waves reached, the finishing reward follows the mode's rule. During the run the bot is on
the mode's map (leaves your map; goals/mode_run.py).

Modes: event gates (Gauntlet of Plutus, Trial of Terrors, Birthday, Quarantine Zone, Compromising Invasion, Permafrost,
The Breach, Devolarium Attack), Voyagers' Ascent, Trinity Trials, Astral Ascension, Eternal Black Light, Deep Space Echoes,
Battle of LoW, Vortex of Greed, Mimesis Mutiny, World Boss, Kristallon Apotheosis, Frozen Labyrinth. Passes (Dispatch,
Galaxy Trek) via pasif() at decision time.
"""
import random, time

import game_data as DATA

from . import catalog as K

# read only: the one parse per process (event_gates.json is not event_gate's own copy, which fiesta/invasion extend)
D = DATA.shared
PVE = D('pve_modes.json')
EVG = D('event_gates.json')
BIG_CONTENT = D('major_content.json')
LOW = D('low.json')
EX = D('extra_events.json')
DISP = D('dispatch.json')


def _tech():
    import event_calendar as CAL
    return CAL


def kind_value(tip):
    """Alien type -> (hp, shield, damage, reward): PvE types, npc.json or the mode's own table."""
    t = PVE['kinds'].get(tip) or K.NPC['types'].get(str(tip))
    if not t:
        return None
    return t.get('hp', 0), t.get('shield', 0), t.get('damage', 0), t.get('reward') or {}


def wave(groups, health=1.0, damage=1.0, table=None):
    """[[[type, count], ...], ...] (groups) -> (HP+shield, damage taken per second, kill rewards)."""
    ehp = dps = 0.0
    reward = {}
    for group in groups:
        for x in group:
            tip, n = x[0], x[1]                          # [type, count] or [type, count, is it a boss]
            v = (table or {}).get(tip)
            v = (v.get('hp', 0), v.get('shield', 0), v.get('damage', 0), v.get('reward') or {}) if v else kind_value(tip)
            if not v:
                continue
            hp, kl, dmg, rew = v
            ehp += n * (hp + kl) * health
            dps += min(n, 2) * dmg * damage * K.COMBAT['npc_hit_chance'] * 0.6 / K.NPC_INTERVAL
            for k, x in rew.items():
                reward[k] = reward.get(k, 0) + x * n
    return ehp, dps, reward


def alien_wave(aliens):
    """Event gate format: [{hp, kalkan, damage, count, reward}] -> wave."""
    table = {str(i): u for i, u in enumerate(aliens)}
    return wave([[[str(i), u.get('count', 1)] for i, u in enumerate(aliens)]], table=table)


# ------------------------------------------------------------------------------------------------------------ reward
def grant_list(bot, rows, rng=random):
    """[[loot, count or [min, max]], ...] -> to the bot."""
    from . import loot as LT
    for r in rows or []:
        loot, n = r[0], r[1]
        n = rng.randint(*n) if isinstance(n, list) else n
        if n:
            LT.give(bot, loot, n)


def grant_reward(bot, o, rng=random, speed=1.0):
    """Event gate / general reward dictionary: ep, honor, credits, uridium, items, chance [[loot, n, probability]], one_of [[loot, n, weight]]."""
    if not o:
        return
    currency = {k: o[k] for k in ('ep', 'honor', 'credits', 'uridium') if o.get(k)}
    if currency:
        bot.reward('quest', speed, **currency)
    grant_list(bot, o.get('items'), rng)
    for loot, n, p in o.get('chance') or []:
        if rng.random() < p:
            grant_list(bot, [[loot, n]], rng)
    if o.get('one_of'):
        r = rng.choices(o['one_of'], weights=[x[2] if len(x) > 2 else 1 for x in o['one_of']])[0]
        grant_list(bot, [r[:2]], rng)


def state(bot, mod):
    return bot.k.setdefault('modes', {}).setdefault(mod, {})


def day():
    return time.strftime('%Y-%m-%d')


# ------------------------------------------------------------------------------------------------------------ modes
class Mod:
    name = ''
    uid = ''
    game_map = None              # the bot's map during the run (leaves your map)
    hp = 1
    level = 1
    time_limit = None          # the run's maximum duration (s; timed modes)
    tip = 'run'

    def is_open(self, now):
        return True

    def can_enter(self, bot, now):
        return bot.level >= self.level

    def cost(self, bot):
        return True

    def affordable(self, bot):
        """Can the entry cost be paid now (without spending): for candidate selection."""
        return True

    def waves(self, bot):
        return []

    def finish(self, bot, reached, total, duration, rng):
        pass

    def save(self, bot, reached, total):
        state(bot, self.uid).update(last=time.time(), day=day(), number=state(bot, self.uid).get('number', 0) + 1)


def _stock(bot):
    from . import weapons as WP
    return WP.stock(bot)


def _has_or_can_buy(bot, loot, uridium=None):
    if _stock(bot).get(loot, 0) > 0:
        return True
    f = K.price(loot)
    price = uridium if uridium else (f[1] if f and f[0] == 'U' else None)
    return bool(price) and bot.permission.get('shop', True) and \
        bot.k['uridium'] >= price * bot.game_settings.multiplier('shop_price') * (3 + 3 * bot.o('frugality'))


def _spend_or_take(bot, loot, uridium=None):
    """Spends the ticket/key/CPU if in stock; otherwise, if it can be bought with uridium (price or given) and the bot is rich, buys it."""
    s = _stock(bot)
    if s.get(loot, 0) > 0:
        s[loot] -= 1
        if not s[loot]:
            del s[loot]
        return True
    f = K.price(loot)
    price = uridium if uridium else (f[1] if f and f[0] == 'U' else None)
    if not price or not bot.permission.get('shop', True):
        return False
    price *= bot.game_settings.multiplier('shop_price')
    if bot.k['uridium'] < price * (3 + 3 * bot.o('frugality')):
        return False
    return bot.pay('U', price)


class EventGate(Mod):
    """data/event_gates.json kapilar.<key>: event, rule (daily+group, yearly, period, cooldown_sec, level,
    max_level, company, once, cpu, quest), can, waves (aliens), reward."""

    def __init__(self, k, g):
        self.uid, self.g = 'egate_' + k, g
        self.name = g['name']
        self.game_map = (g.get('maps') or [None])[0]
        self.hp = min(int(g.get('hp', 1)), 50)
        self.rule = g.get('rule') or {}
        self.level = self.rule.get('level', 1)

    def is_open(self, now):
        e = self.g.get('event')
        if e and not _tech().is_active(e, now):
            return False
        period = self.rule.get('period')
        if period:
            md = time.strftime('%m-%d', time.localtime(now))
            return any((a <= md <= b) if a <= b else (md >= a or md <= b) for a, b in period)
        return True

    def can_enter(self, bot, now):
        k, st = self.rule, state(bot, self.uid)
        if bot.level < k.get('level', 1) or bot.level > k.get('max_level', 99):
            return False
        if k.get('company') and k['company'] != bot.company:
            return False
        if k.get('once') and st.get('number'):
            return False
        if k.get('daily'):
            group = k.get('group') or self.uid
            if state(bot, 'group_' + group).get('day') == day():
                return False
        if k.get('yearly') and st.get('year') == time.strftime('%Y'):
            return False
        if k.get('cooldown_sec') and now - st.get('last', 0) < k['cooldown_sec']:
            return False
        if k.get('quest'):
            g = bot.k.get('quest') or {}
            if str(g.get('id')) != str(k['quest']):
                return False
        if k.get('cpu') and _stock(bot).get(k['cpu'], 0) <= 0 and not K.price(k['cpu']):
            return False
        return True

    def cost(self, bot):
        cpu = self.rule.get('cpu')
        return _spend_or_take(bot, cpu) if cpu else True

    def affordable(self, bot):
        cpu = self.rule.get('cpu')
        return _has_or_can_buy(bot, cpu) if cpu else True

    def waves(self, bot):
        return [alien_wave(d.get('alien_spawns', [])) for d in self.g.get('waves', [])]

    def finish(self, bot, reached, total, duration, rng):
        if reached >= total:
            grant_reward(bot, self.g.get('reward'), rng)

    def save(self, bot, reached, total):
        super().save(bot, reached, total)
        k = self.rule
        if k.get('daily'):
            state(bot, 'group_' + (k.get('group') or self.uid))['day'] = day()
        if k.get('yearly'):
            state(bot, self.uid)['year'] = time.strftime('%Y')


class Voyagers(Mod):
    uid, name, tip = 'voyagers', "Voyagers' Ascent", 'arena'
    V = PVE['voyagers']
    game_map = V['map'] if isinstance(V['map'], int) else 0
    level = 8

    def difficulty(self, bot):
        st = state(bot, self.uid)
        d = 0
        while d + 1 < len(self.V['difficulties']) and st.get('star', {}).get(str(d), 0) >= 3:
            d += 1
        return d

    def can_enter(self, bot, now):
        return bot.level >= self.level

    def cost(self, bot):
        st = state(bot, self.uid)
        if st.get('free') != day():
            st['free'] = day()
            return True
        return _spend_or_take(bot, self.V['token'])

    def affordable(self, bot):
        return state(bot, self.uid).get('free') != day() or _has_or_can_buy(bot, self.V['token'])

    def waves(self, bot):
        z = self.V['difficulties'][self.difficulty(bot)]
        return [wave(d['groups']) for d in z['waves']]

    def finish(self, bot, reached, total, duration, rng):
        if reached < total:
            return
        sec = self.V['star_sec']
        star = 3 if duration <= sec[0] else 2 if duration <= sec[1] else 1
        d = self.difficulty(bot)
        st = state(bot, self.uid).setdefault('star', {})
        st[str(d)] = max(st.get(str(d), 0), star)
        grant_list(bot, self.V['difficulties'][d]['rewards'].get(str(star)), rng)


class Trinity(Mod):
    uid, name, tip = 'trinity', 'Trinity Trials', 'arena'
    T = PVE['trinity']
    game_map = next(iter(T['maps'].values()))[0] if isinstance(T['maps'], dict) else T['maps'][0]
    level = 8

    def arena(self):
        g = time.localtime().tm_wday
        return next((a for a, days in self.T['days'].items() if g in days), '1')

    def cost(self, bot):
        st = state(bot, self.uid)
        if st.get('free') != day():
            st['free'] = day()
            return True
        return _spend_or_take(bot, self.T['token'])

    def affordable(self, bot):
        return state(bot, self.uid).get('free') != day() or _has_or_can_buy(bot, self.T['token'])

    def difficulty(self, bot):
        return min(len(self.T['difficulties']) - 1, max(0, bot.level // 6 - 1))

    def waves(self, bot):
        z = self.T['difficulties'][self.difficulty(bot)]
        ar = z['arenas'].get(self.arena()) or next(iter(z['arenas'].values()))
        return [wave(d['groups']) for d in ar]

    def finish(self, bot, reached, total, duration, rng):
        milestone = reached // 5                                   # a milestone every 5 waves: Quantum Prism and Xyralith
        d = self.difficulty(bot) + 1
        if milestone:
            grant_list(bot, [[self.T['qp'], milestone], [self.T['xy'], milestone * 10 * d]], rng)


class Astral(Mod):
    uid, name = 'astral', 'Astral Ascension'
    A = PVE['astral']
    game_map = A['maps'][0]
    level = 12

    def can_enter(self, bot, now):
        return bot.level >= self.level and (_stock(bot).get(self.A['cpu'], 0) > 0 or bool(K.price(self.A['cpu'])))

    def cost(self, bot):
        return _spend_or_take(bot, self.A['cpu'])

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.A['cpu'])

    def waves(self, bot):
        o = self.A['scale']
        out = []
        for r, rift in enumerate(self.A['rifts'], 1):
            s = random.choice(rift['sets'])
            health = (1 + o['rift_hp'] * r) * o['boss_hp'].get(str(r), 1)
            dmg = (1 + o['rift_damage'] * r) * o['boss_damage'].get(str(r), 1)
            out.append(_combined([wave(d['groups'], health, dmg) for d in s]))
        return out

    def save(self, bot, reached, total):
        super().save(bot, reached, total)
        import monthly_rankings as MR
        MR.record_bot(bot, 'astral', reached)            # the month's Astral ranking (the player's competitors)

    def finish(self, bot, reached, total, duration, rng):
        row = next((r for r in self.A['reward'] if r['min_value'] <= reached <= r['max_count']), None)
        if row:
            grant_list(bot, [['resource_collectable_astralite', row.get('astralite', 0)],
                            ['resource_collectable_salvage-core', row.get('salvage', 0)],
                            ['resource_booty-key-astral', row.get('key', 0)]], rng)


class Ebl(Mod):
    uid, name = 'ebl', 'Eternal Black Light'
    E = PVE['ebl']
    game_map = E['maps'][0]
    level = E['level']

    def can_enter(self, bot, now):
        return bot.level >= self.level and (_stock(bot).get(self.E['cpu'], 0) > 0 or bool(K.price(self.E['cpu'])))

    def cost(self, bot):
        return _spend_or_take(bot, self.E['cpu'])

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.E['cpu'])

    def waves(self, bot):
        out = []
        for kind in range(3):                                 # at most 3 rounds (x1.8 each round): most pilots fall in the first
            k = self.E['kind_multiplier'] ** kind
            out += [wave(d['groups'], d.get('multiplier', 1) * k, d.get('multiplier', 1) * k) for d in self.E['waves']]
        return out

    def save(self, bot, reached, total):
        super().save(bot, reached, total)
        import monthly_rankings as MR
        MR.record_bot(bot, 'ebl', reached)               # the month's Eternal Black Light ranking

    def finish(self, bot, reached, total, duration, rng):
        row = next((r for r in self.E['death_reward'] if r['min_value'] <= reached <= r['max_count']), self.E['death_reward'][-1]
                   if reached > self.E['death_reward'][-1]['max_count'] else None)
        if row:
            grant_list(bot, [['resource_collectable_blacklight-shard', row.get('part', 0)]], rng)


class Echoes(Mod):
    uid, name = 'echoes', 'Deep Space Echoes'
    E = PVE['echoes']
    game_map = E['maps'][0]
    level = E['level_requirement']
    time_limit = E['duration_sec']

    def level_no(self, bot):
        return min(len(self.E['levels']) - 1, state(bot, self.uid).get('cleared', 0))

    def cost(self, bot):
        return _spend_or_take(bot, self.E['ticket'], self.E['ticket_price'])

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.E['ticket'], self.E['ticket_price'])

    def waves(self, bot):
        s = self.E['levels'][self.level_no(bot)]
        k = 1 + self.E['scale_level'] * s['level']
        return [wave(d['groups'], k, k) for d in s['waves']]

    def finish(self, bot, reached, total, duration, rng):
        if reached < total:
            return
        st = state(bot, self.uid)
        s = self.E['levels'][self.level_no(bot)]
        t = self.E['repeat']
        if st.get('cleared', 0) <= self.level_no(bot):
            grant_list(bot, s.get('first'), rng)
            st['cleared'] = self.level_no(bot) + 1
        grant_list(bot, [['currency_uridium', t['uridium_base'] + t['uridium_level'] * s['level']],
                        ['ammunition_laser_ucb-100', t['ucb_base'] + t['ucb_level'] * s['level']]], rng)


class Low(Mod):
    uid, name = 'low', 'Battle of LoW'
    game_map = LOW['map']
    level = 10
    tip = 'full'                                          # about to finish the reward: does not enter a run it cannot get halfway through

    def can_enter(self, bot, now):
        return bot.level >= self.level and now - state(bot, self.uid).get('last', 0) > 6 * 3600     # now and then

    def waves(self, bot):
        return [wave([[[t, n]]]) for t, n in LOW['waves']] + [wave([[[LOW['boss'], 1]]])]


class VortexGreed(Mod):
    uid, name = 'vog', 'Vortex of Greed'
    V = BIG_CONTENT['vortex']
    game_map = V['map']
    level = V['level']
    time_limit = V['session_sec']

    def is_open(self, now):
        if not _tech().is_active(self.V['event'], now):
            return False
        t = time.localtime(now)
        minutes = t.tm_hour * 60 + t.tm_min
        return any(0 <= minutes - (int(s[:2]) * 60 + int(s[3:])) < self.V['session_sec'] // 60 for s in self.V['sessions'])

    def can_enter(self, bot, now):
        st = state(bot, self.uid)
        return bot.level >= self.level and st.get('session') != time.strftime('%Y-%m-%d %H')

    def waves(self, bot):
        aliens = self.V['alien_spawns']
        n = self.V['session_sec'] // self.V['wave_sec']
        return [wave([[[k, max(1, v.get('count', 3))] for k, v in aliens.items()]], table=aliens) for _ in range(n)]

    def finish(self, bot, reached, total, duration, rng):
        from . import loot as LT
        st = state(bot, self.uid)
        st['session'] = time.strftime('%Y-%m-%d %H')
        week = time.strftime('%Y-%W')
        if st.get('week') != week:
            st.update(week=week, coin=0)
        coin = int(reached * self.V['wave_box'] * self.V['box_sc'] * 0.4)       # collects a share of the boxes, evacuates
        coin = min(coin, self.V['weekly_limit'] - st['coin'])
        if coin > 0:
            st['coin'] += coin
            LT.give(bot, self.V['currency'], coin)


class Mimesis(Mod):
    uid, name = 'mimesis', 'Mimesis Mutiny'
    M = BIG_CONTENT['mimesis']
    game_map = M['maps'].get(str(1)) if isinstance(M['maps'], dict) else M['maps'][0]
    time_limit = M['duration_sec']
    level = 10

    def is_open(self, now):
        return _tech().is_active(self.M['event'], now) and time.localtime(now).tm_hour in self.M['hours']

    def can_enter(self, bot, now):
        return bot.level >= self.level and state(bot, self.uid).get('hour') != time.strftime('%Y-%m-%d %H')

    def cost(self, bot):
        return _spend_or_take(bot, self.M['key'], self.M.get('key_uridium'))

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.M['key'], self.M.get('key_uridium'))

    def waves(self, bot):
        table = self.M['kinds']
        d = self.M['waves']
        return [wave([d['start']], table=table)] + [wave([g], table=table) for g in d['waypoints']]

    def finish(self, bot, reached, total, duration, rng):
        state(bot, self.uid)['hour'] = time.strftime('%Y-%m-%d %H')
        points = reached * self.M['waypoint_points'] + (self.M['arrival_bonus'] if reached >= total else 0)
        row = next((r for r in reversed(self.M['trip_tiers']) if points >= r['from_']), None)
        if row:
            grant_list(bot, row['rewards'], rng)


class WorldBoss(Mod):
    uid, name = 'world_boss', 'World Boss'
    W = BIG_CONTENT['world_boss']
    game_map = W['map']
    level = 12

    def is_open(self, now):
        if not _tech().is_active(self.W['event'], now):
            return False
        hm = time.strftime('%H:%M', time.localtime(now))
        return any(a <= hm < b for a, b in self.W['windows'])

    def can_enter(self, bot, now):
        return bot.level >= self.level and state(bot, self.uid).get('windowed') != time.strftime('%Y-%m-%d %H')

    def waves(self, bot):
        f = self.W['npcs'].get('dreadfyre_fortress') or next(iter(self.W['npcs'].values()))
        pay = 0.02                                           # the bot's damage share on a crowded server
        return [(((f['hp'] + f['shield']) * pay), 0.0, {})]

    def finish(self, bot, reached, total, duration, rng):
        state(bot, self.uid)['windowed'] = time.strftime('%Y-%m-%d %H')
        if reached:
            g = bot.value()['power']
            tier = self.W['tier'][min(len(self.W['tier']) - 1, int(g // 25))]
            grant_list(bot, tier['rewards'], rng)


class Apotheosis(Mod):
    uid, name = 'apotheosis', 'Kristallon Apotheosis'
    A = BIG_CONTENT['kristallon_apotheosis']
    game_map = A['map']
    level = 12

    def is_open(self, now):
        if not _tech().is_active(self.A['event'], now):
            return False
        hm = time.strftime('%H:%M', time.localtime(now))
        return any(a <= hm < b for a, b in self.A['windows'])

    def can_enter(self, bot, now):
        return bot.level >= self.level and state(bot, self.uid).get('windowed') != time.strftime('%Y-%m-%d %H')

    def waves(self, bot):
        p = self.A['boss']
        return [((p['hp'] + p['shield']) * 0.03, p['damage'] * 0.6 * K.COMBAT['npc_hit_chance'] / K.NPC_INTERVAL, {})]

    def finish(self, bot, reached, total, duration, rng):
        state(bot, self.uid)['windowed'] = time.strftime('%Y-%m-%d %H')
        k = self.A['participation']
        grant_list(bot, k[min(len(k) - 1, int(bot.value()['power'] // 30))], rng)


class Labyrinth(Mod):
    uid, name = 'labyrinth', 'Frozen Labyrinth'
    L = EVG['labyrinth']
    game_map = (L['start'] if isinstance(L.get('start'), int) else (list(L['maps'])[0] if L.get('maps') else 0))
    level = 12

    def is_open(self, now):
        if not _tech().is_active(self.L['event'], now):
            return False
        hours = self.L['hours_weekend'] if time.localtime(now).tm_wday >= 5 else self.L['hours']
        return time.localtime(now).tm_hour in (hours or range(24))

    def can_enter(self, bot, now):
        return bot.level >= self.level and now - state(bot, self.uid).get('last', 0) > 3600

    def waves(self, bot):
        aliens = self.L['alien_spawns']
        aliens = aliens if isinstance(aliens, list) else [dict(v, type=k) for k, v in aliens.items()]
        return [wave([[[str(u.get('type')), u.get('count', 5)] for u in aliens]]) for _ in range(4)]

    def finish(self, bot, reached, total, duration, rng):
        aliens = self.L['alien_spawns']
        aliens = aliens if isinstance(aliens, list) else list(aliens.values())
        key = sum((u.get('key') or 0) * u.get('count', 5) * 0.3 for u in aliens if isinstance(u.get('key'), (int, float)))
        if key:
            grant_list(bot, [['resource_key_labyrinth', int(key * reached)]], rng)


def _combined(waves):
    ehp = sum(d[0] for d in waves)
    dps = max([d[1] for d in waves] or [0])
    reward = {}
    for d in waves:
        for k, v in d[2].items():
            reward[k] = reward.get(k, 0) + v
    return ehp, dps, reward


def _gates():
    import event_gate as EKP
    return [EventGate(k, g) for k, g in EKP.GATES.items()]


MODES = []


def modes():
    if not MODES:
        MODES.extend(_gates() + [Voyagers(), Trinity(), Astral(), Ebl(), Echoes(), Low(), VortexGreed(), Mimesis(),
                                    WorldBoss(), Apotheosis(), Labyrinth()])
    return MODES


# ------------------------------------------------------------------------------------------------------------ run
def estimate(bot, mod, waves=None):
    """Run estimate -> (wave reached, total, time s, kill rewards). The gate's method: best ammo, simultaneous attackers,
    repair between waves; stops when deaths use up the lives; ends there if there is a time limit."""
    from . import weapons as WP
    waves = mod.waves(bot) if waves is None else waves
    d = bot.value()
    s = WP.stock(bot)
    multiplier = max([WP.multiplier(c) for c in ('ammunition_laser_ucb-100', WP.MCB50, WP.MCB25, WP.LCB) if s.get(c, 0) > 1000] or [1])
    dps = max(1.0, d['dps'] * multiplier * 1.15)
    duration = death = 0.0
    reward = {}
    reached = 0
    for ehp, incoming, rew in waves:
        t = ehp / dps
        if mod.time_limit and duration + t > mod.time_limit:
            break
        death += t * incoming / max(1.0, d['ehp'] * 3)
        if death >= mod.hp:
            break
        duration += t
        reached += 1
        for k, v in rew.items():
            reward[k] = reward.get(k, 0) + v
    return reached, len(waves), duration, reward


def value(bot, mod):
    """The mode's expected value to the bot (credits/hour, roughly): kill rewards and the finish, weighted by progress share; 0 for a mode it cannot pass."""
    ul, top, duration, reward = estimate(bot, mod)
    if top == 0 or ul == 0 or (mod.tip in ('full', 'run') and ul < top * 0.5):
        return 0.0                                       # does not enter if it cannot get halfway through a mode that gives no reward for progress
    v = reward.get('credits', 0) + reward.get('uridium', 0) * 100 + reward.get('ep', 0) * 0.3 + reward.get('honor', 0) * 3
    v += 200000 * ul / top                                    # finishing rewards (items, resources, keys), roughly
    return v / max(600.0, duration) * 3600


def candidates(bot, now):
    """Modes that can be entered now (open, conditions met, will pass at least the first wave)."""
    if not bot.permission.get('modes', True):
        return []
    out = []
    for m in modes():
        try:
            if m.is_open(now) and m.can_enter(bot, now) and m.affordable(bot) and value(bot, m) > 0:
                out.append(m)
        except (KeyError, TypeError, ValueError, IndexError):
            continue                                       # a mode whose data is in an unexpected form: skip
    return out


def run(bot, mod, rng=random):
    """Result of the run -> (reached, total, time, kill rewards); the time is extended by the real-run share."""
    waves = mod.waves(bot)
    ul, top, duration, reward = estimate(bot, mod, waves)
    if ul < top and rng.random() < 0.3:
        ul = min(top, ul + 1)                               # luck
    return ul, top, duration * rng.uniform(1.1, 1.5) + 90, reward


# ------------------------------------------------------------------------------------------------------------ pasif
def dispatch(bot, now):
    """Dispatch: a rich bot sends a gatherer (credit fee), when the time is up 4 rewards from its list (with the base counts)."""
    if not bot.permission.get('modes', True) or bot.level < 10:
        return
    st = state(bot, 'dispatch')
    if st.get('end_time') and now >= st['end_time']:
        t = DISP['collectors'][st['type']]
        entries = DISP['rewards'].get(t['code']) or []
        multiplier = 1 + (t.get('tier', 1) - 1) * DISP.get('tier_increase', 0.5)
        if _tech().is_active('dispatch_day', now):
            multiplier *= DISP.get('dispatch_day_multiplier', 2)
        for loot in random.sample(entries, min(DISP['reward_count'], len(entries))):
            n = DISP['base_count'].get(loot, 1)
            grant_list(bot, [[loot, n if loot in DISP['single'] else int(n * multiplier)]])
        st.pop('end_time')
        bot.ist('dispatch')
    if st.get('end_time'):
        return
    eligible = [(k, t) for k, t in DISP['collectors'].items()
             if all(bot.k[{'currency_credits': 'credits', 'currency_uridium': 'uridium'}.get(p, 'credits')] > n * (3 + 3 * bot.o('frugality'))
                    for p, n in t.get('fee', {}).items())]
    if not eligible:
        return
    k, t = max(eligible, key=lambda x: x[1].get('tier', 1))
    for p, n in t.get('fee', {}).items():
        bot.pay('C' if p == 'currency_credits' else 'U', n)
    st.update(type=k, end_time=now + t['duration_sec'])


def galaxy_trek(bot, now):
    """Galaxy Trek: while the event lasts, exploration with daily FTL keys (reward from the events table)."""
    g = EX['galaxy_trek']
    if not bot.permission.get('modes', True) or not _tech().is_active('galaxy_trek', now):
        return
    st = state(bot, 'galaxy_trek')
    if st.get('day') == day():
        return
    st['day'] = day()
    events = g.get('events')
    rows = events if isinstance(events, list) else list((events or {}).values())
    for _ in range(int(g.get('daily', 10)) // max(1, int(g.get('cost', 1)))):
        r = random.choice(rows) if rows else None
        if isinstance(r, dict):
            grant_list(bot, r.get('rewards') or r.get('items') or [])
        elif isinstance(r, list) and r and isinstance(r[0], str):
            grant_list(bot, [r[:2]])
    bot.ist('galaxy_trek')


def passive(bot, now):
    dispatch(bot, now)
    galaxy_trek(bot, now)


# ------------------------------------------------------------------------------------------------------------ PvP matches
# The team modes' matches the player is not in, played by the bot pilots under the player's rules (team_deathmatch.py,
# sector_control.py: the same bands, sides, team sizes, end rules and rewards). A pilot that chose goals/pvp_match.PvpEvent queues for a
# waiting match of its band and keeps grinding; once the sides are big enough the match is played out at once (the sides' PvP strength
# with luck) and its pilots stay on the mode map until its end (not on an open map meanwhile: pvp_match); then the result, the rewards
# and the history (after_match). pvp_rows / pvp_take: the same matches for the player's lobby (the modes' sim(); cross-domain).
TDM_PAIRS = {1: (1, 2), 2: (2, 3), 3: (1, 3)}                  # team_deathmatch.PAIRS
PVP = {'tdm': dict(event='team_deathmatch', done='tdm_done', d=EX.get('team_deathmatch') or {}),
       'sc': dict(event='sector_control', done='sc_done', d=EX.get('sector_control') or {})}
MATCH_DONE = {'tdm_done': 'tdm', 'sc_done': 'sc', 'ctb_done': 'ctb'}     # release events of a match (the modes' release_bots and pvp_settle)
QUEUE_SEC = (360, 900)       # how long a pilot waits in a queue that does not move before it gives up (behaviour: it grinds meanwhile)
QUEUE_GROW_SEC = 300         # a pilot whose queue grew waits at least this much longer from then
QUEUE_MAX_SEC = 2400         # nobody waits longer than this in one queue (40 minutes: a queue never holds pilots for hours)
QUEUE_PER_PILOT = 0.12       # appeal of a queue per pilot already waiting (up to 10): the lobby window shows them (behaviour weights)
QUEUE_NEAR = 1.5             # appeal of a queue close to starting with the pilot in it (readiness squared)
QUEUE_MATE = 0.5             # appeal per friend or clan mate waiting in it (up to 2)
QUEUE_TASTE = 0.4            # a pilot's own liking of each mode (when the queues are empty: who opens which)
RECRUIT_SEC = 60             # a forming queue calls its company mates at most this often
RECRUIT_P = 0.35             # the chance a free, sociable, aggressive company mate answers the call
RECRUIT_MATE = 0.35          # extra chance when a friend or clan mate is waiting in it
RECRUIT_PAY = 0.7            # the intent's weight in the called pilot's next decision (brain.force)
BUSY = ('gate', 'mod', 'duel', 'pvp_match', 'pvp_event')
TDM_RATE = (0.03, 0.10)      # points a second per side: the range of team_deathmatch.sim (the lobby's rows)
SC_POINTS = 4                # the most control points a company can be behind another (sector_control.bleed: all 4 held by one)
SC_KILL_SEC = 0.004          # kills a second per pilot in Sector Control (behaviour: about one every four minutes)
LOBBY = {}                   # (mode, band map, match id) -> {state wait|run, teams {company: [bot]}, ready, start, end, res}
_pvp_t = [0.0]


def pvp_open(mode, now):
    return bool(PVP[mode]['d'].get('brackets')) and _tech().is_active(PVP[mode]['event'], now)


def pvp_band(mode, level):
    return next((b for b in PVP[mode]['d'].get('brackets', ()) if b['min_level'] <= level <= b['max_level']), None)


def pvp_modes(bot, now):
    """The team modes open now with a band for the bot."""
    return [m for m in PVP if pvp_open(m, now) and pvp_band(m, bot.level) is not None]


def _sides(mode, mid):
    return TDM_PAIRS[mid] if mode == 'tdm' else (1, 2, 3)


def _mids(mode):
    return list(TDM_PAIRS) if mode == 'tdm' else list(range(1, int(PVP['sc']['d'].get('matches', 2)) + 1))


def _room(mode):
    d = PVP[mode]['d']
    return d['team_max'] if mode == 'tdm' else d.get('team_target', d['team_max'])     # the size the bots fill (sector_control.fill)


def recent_matches(bot, now, sec=3600):
    """Matches the bot played in the last hour (drafted or its own)."""
    return sum(1 for x in bot.k.get('matches') or () if now - x.get('t', 0) < sec)


def _readiness(mode, size):
    """How close a queue is to starting (0..1): the two biggest sides' pilots up to the mode's minimum."""
    need = PVP[mode]['d']['team_min']
    return sum(sorted((min(n, need) for n in size.values()), reverse=True)[:2]) / (2.0 * need)


def _mates(bot, others):
    """How many of the others are the bot's friends or clan mates."""
    friends = {str(x).lower() for x in bot.k.get('friends') or ()}
    clan = bot.k.get('clan')
    return sum(1 for o in others if o is not bot and (o.name.lower() in friends or (clan and o.k.get('clan') == clan)))


def _taste(bot, mode):
    """A pilot's own liking of a mode (stable: some prefer Sector Control's big fights, some Team Deathmatch)."""
    return random.Random('%s|%s' % (bot.name, mode)).uniform(0.0, QUEUE_TASTE)


def _appeal(bot, mode, L, size):
    """How much a queue draws the bot, as the lobby window shows it: pilots already waiting, how close it is to starting with the bot in
    it, friends and clan mates in it (0 for an empty queue)."""
    if L is None:
        return 0.0
    waiting = [b for v in L['teams'].values() for b in v]
    return (QUEUE_PER_PILOT * min(len(waiting), 10) + QUEUE_NEAR * _readiness(mode, size) ** 2
            + QUEUE_MATE * min(2, _mates(bot, waiting)))


def pvp_join(bot, modes, now, look=False, prefer=None):
    """Queues the bot for a waiting match of its band, of one of the modes, that has its company and room: the one that draws it most
    (_appeal: who waits, how close it is, its friends; its own taste of the mode when the queues are empty) -> lobby key or None.
    prefer: the queue a company mate called it to (if it still takes it). look: only -> the best queue's appeal."""
    best = None
    for mode in modes:
        band = pvp_band(mode, bot.level)
        if band is None:
            continue
        for mid in _mids(mode):
            if bot.company not in _sides(mode, mid):
                continue
            key = (mode, band['map'], mid)
            L = LOBBY.get(key)
            if L is not None and (L['state'] != 'wait' or len(L['teams'][bot.company]) >= _room(mode)):
                continue
            size = {c: len(L['teams'][c]) if L else 0 for c in _sides(mode, mid)}
            size[bot.company] += 1
            s = _appeal(bot, mode, L, size)
            if not look:
                s += _taste(bot, mode) + 0.1 * bot.r.random() + (10.0 if key == prefer else 0.0)
            if best is None or s > best[0]:
                best = (s, key)
    if look:
        return best[0] if best else 0.0
    if best is None:
        return None
    key = best[1]
    L = LOBBY.setdefault(key, dict(state='wait', teams={c: [] for c in _sides(key[0], key[2])}, ready=None, joins=0, called=0.0))
    L['teams'][bot.company].append(bot)
    L['joins'] = L.get('joins', 0) + 1
    return key


def _recruit(y, key, L, now):
    """A forming queue (2+ waiting) whose side is short: like 'sc need 2 more' in the company chat, a few online company mates of the band
    who are free hear it, friends and clan mates of those waiting first; one who wants to comes (an intent for the queue: brain.force)."""
    from . import brain as B
    d = PVP[key[0]]['d']
    band = next(b for b in d['brackets'] if b['map'] == key[1])
    waiting = [b for v in L['teams'].values() for b in v]
    if len(waiting) < 2:
        return
    for c, v in L['teams'].items():
        need = d['team_min'] - len(v)
        if need <= 0 or not v:
            continue                               # the call goes out in the company chat: only a company with pilots waiting makes it
        free = [b for b in y.bots if b.online and b.company == c and band['min_level'] <= b.level <= band['max_level'] and b.dead_until <= now
                and b.permission.get('pvp', True) and (b.target is None or b.target.name not in BUSY) and not b.k.get('intent')]
        free.sort(key=lambda b: -(b.o('sociability') + RECRUIT_MATE * _mates(b, waiting)) * b.r.random())
        for b in free[:need + 2]:
            if need <= 0:
                break
            p = RECRUIT_P * (0.3 + 0.7 * b.o('sociability')) * (0.5 + b.o('aggression')) + RECRUIT_MATE * min(1, _mates(b, waiting))
            if b.r.random() < p / (1 + recent_matches(b, now)):
                B.force(b, 'pvp_event', plan={'lobby': key}, pay=RECRUIT_PAY, duration=240, now=now)
                need -= 1


def pvp_leave(bot, key):
    L = LOBBY.get(key)
    if L is not None and L['state'] == 'wait':
        v = L['teams'].get(bot.company, [])
        if bot in v:
            v.remove(bot)


def pvp_tick(y, now):
    """Every few seconds: queues that are ready start (TDM: both sides at team_min; SC: two companies at team_min; full, or the
    mode's fill wait after that), played matches are dropped a while after their end."""
    if now - _pvp_t[0] < 5:
        return
    _pvp_t[0] = now
    for key, L in list(LOBBY.items()):
        d = PVP[key[0]]['d']
        if L['state'] == 'run':
            if now > L['end'] + 300:
                LOBBY.pop(key, None)
            continue
        for v in L['teams'].values():           # gone: offline, dead, chose something else, drafted into the player's match
            v[:] = [b for b in v if b.online and b.dead_until <= now and b.target is not None and b.target.name == 'pvp_event'
                    and b.plan.get('lobby') == key and not b.plan.get('finished')]
        size = {c: len(v) for c, v in L['teams'].items()}
        if not any(size.values()):
            LOBBY.pop(key, None)
            continue
        if sum(1 for n in size.values() if n >= d['team_min']) < 2:
            L['ready'] = None
            if y is not None and now - L.get('called', 0.0) >= RECRUIT_SEC:
                L['called'] = now
                _recruit(y, key, L, now)
            continue
        L['ready'] = L['ready'] or now
        if all(n >= _room(key[0]) for n in size.values()) or now - L['ready'] >= d['fill_wait_sec']:
            _start(y, key, L, now)


def _strength(b):
    """A pilot's PvP strength: gear, CPUs, technologies and skill (abstract_sim.encounter)."""
    from . import extras as EXT, technology as TECH, playstyle as PL
    return max(0.5, b.value()['power']) * EXT.pvp_factor(b) * TECH.pvp_factor(b) * PL.pvp_factor(b)


def _pick(weights, rng, items):
    x, i = rng.random() * sum(weights), 0
    while i < len(weights) - 1 and x >= weights[i]:
        x -= weights[i]
        i += 1
    return items[i]


def _share(weights, n, rng):
    """n events over the weights (a multinomial draw) -> counts."""
    out = [0] * len(weights)
    for _ in range(int(n)):
        out[_pick(weights, rng, range(len(weights)))] += 1
    return out


def _play(mode, teams, rng):
    """The match played out -> {sec, winner (company or None), score {company: points / tickets left}, kd {uid: [kills, deaths]},
    victims {uid: [bot]}}. TDM: 15 minutes or 100 points, 3 lives each (a side without lives loses); SC: the company bleeding slowest
    is left; a draw (TDM) loses for both (wiki)."""
    d = PVP[mode]['d']
    cs = list(teams)
    g = {c: sum(_strength(b) for b in teams[c]) for c in cs}
    share = {c: g[c] ** 1.5 / sum(g[x] ** 1.5 for x in cs) for c in cs}
    luck = {c: rng.uniform(0.75, 1.25) for c in cs}
    kd = {b.uid: [0, 0] for c in cs for b in teams[c]}
    victims = {b.uid: [] for c in cs for b in teams[c]}
    if mode == 'tdm':
        base = rng.uniform(*TDM_RATE)
        rate = {c: base * 2 * (0.15 + 0.7 * share[c]) * luck[c] for c in cs}
        sec = min(d['match_sec'], d['max_score'] / max(rate.values()))
        pts = {c: min(d['max_score'], int(rate[c] * sec)) for c in cs}
    else:
        # the mode's ticket rule (sector_control.step / bleed): every company bleeds bleed_base, plus bleed_point per control point another
        # company holds more than it (the weaker company holds fewer: up to SC_POINTS behind), late_factor times faster after late_sec, and
        # one ticket per death (the weaker company dies more); the last company with tickets wins
        k = len(cs)
        top = max(share.values())
        extra = {c: SC_POINTS * (top - share[c]) / top * luck[c] for c in cs}
        kr = SC_KILL_SEC * sum(len(v) for v in teams.values())
        lose = {c: (1 - share[c]) / (k - 1) for c in cs}
        left = {c: float(d['tickets']) for c in cs}
        out, sec = [], 0.0
        while len(out) < k - 1 and sec < 3 * 3600:
            f = d['late_factor'] if sec >= d['late_sec'] else 1
            sec += 10.0
            for c in cs:
                if c not in out:
                    left[c] -= ((d['bleed_base'] + d['bleed_point'] * extra[c]) * f + kr * lose[c]) * 10.0
                    if left[c] <= 0:
                        out.append(c)
        pts = dict(zip(cs, _share([share[c] * luck[c] for c in cs], int(kr * sec), rng)))
    lives = d.get('lives') if mode == 'tdm' else None
    st = {b.uid: _strength(b) for c in cs for b in teams[c]}
    kills = [c for c in cs for _ in range(pts[c])]
    rng.shuffle(kills)                             # in the order they happen: a side whose lives run out first loses (TDM)
    for i, c in enumerate(kills):                  # a kill goes to a pilot of the side by strength, the death to a pilot of the others
        alive = [b for x in cs if x != c for b in teams[x] if lives is None or kd[b.uid][1] < lives]
        if not alive or (lives is not None and any(all(kd[b.uid][1] >= lives for b in teams[x]) for x in cs)):
            sec *= max(0.2, i / float(len(kills)))     # a side is out of lives: the match ends there
            break
        v = _pick([1.0 / max(0.3, st[b.uid]) * rng.uniform(0.5, 1.5) for b in alive], rng, alive)
        k_ = _pick([st[b.uid] ** 1.2 * rng.uniform(0.5, 1.5) for b in teams[c]], rng, teams[c])
        kd[k_.uid][0] += 1
        kd[v.uid][1] += 1
        victims[k_.uid].append(v)
    if mode == 'tdm':
        score = {c: sum(kd[b.uid][0] for b in teams[c]) for c in cs}
        out = [c for c in cs if all(kd[b.uid][1] >= lives for b in teams[c])]
        top = max(score.values())
        winner = next((c for c in cs if c not in out), None) if out else (
            next(c for c in cs if score[c] == top) if list(score.values()).count(top) == 1 else None)
    else:
        score = {c: max(0, int(left[c])) for c in cs}
        winner = max(cs, key=lambda c: left[c])
    return dict(sec=sec, winner=winner, score=score, kd=kd, victims=victims)


def _start(y, key, L, now):
    """The queue becomes a match: played out now, its pilots move to the mode map (pvp_match) until its end."""
    from .brain import GOALS
    from . import abstract_sim as S
    mode, d = key[0], PVP[key[0]]['d']
    teams = {c: list(v) for c, v in L['teams'].items() if v}
    rng = teams[min(teams)][0].r
    res = _play(mode, teams, rng)
    start = now + (d.get('start_phase_sec') or d.get('start_sec') or 20) + rng.uniform(20, 60)     # confirmation, the jump, the countdown
    L.update(state='run', start=start, end=start + res['sec'], res=res, size={c: len(v) for c, v in teams.items()})
    for v in teams.values():
        for b in v:
            if b.body is not None:
                b.body.alive = False                    # its ship on the player's map goes (as team_deathmatch.draft_bots)
                b.body = None
            waited = int(now - b.plan.get('joined', now))
            b.target, b.goal_start = GOALS['pvp_match'], now
            b.plan = {'abstract': key, 'match': key[1], 'end': L['end'], 'min': L['end'] - now + 900}
            b.k['target'] = 'pvp_match'
            b.session_end = max(b.session_end, L['end'] + 120)
            b.en_route = None
            S.jump_to(b, key[1], y, now)
            b.event('match_start', now, mode=mode, band=key[1], match='%s_%d_%d_%d' % (mode, key[1], key[2], int(now)), waited=waited,
                    size=sum(len(x) for x in teams.values()))


def pvp_settle(bot, y, now):
    """The end of the bot's own match: the rewards by the player's rules (TDM: reward_for by kills and deaths; SC: each kill's EP and
    Honor by the PvP kill rule, the winners' bonus by kills), home to X-1, the result event (after_match)."""
    from . import abstract_sim as S
    key = bot.plan.get('abstract')
    bot.plan['finished'] = True
    L = LOBBY.get(key)
    res = (L or {}).get('res')
    if bot.game_map == key[1]:
        S.jump_to(bot, K.ev(bot.company), y, now)
    if res is None:
        return
    mode, d = key[0], PVP[key[0]]['d']
    kills, deaths = res['kd'].get(bot.uid, (0, 0))
    won = res['winner'] == bot.company
    if mode == 'tdm':
        import team_deathmatch as TDM
        grant_list(bot, [list(x) for x in TDM.reward_for(kills, deaths)], bot.r)
        bot.ist('tdm_kill', kills)
    else:
        from . import society as TB
        speed = y.speed(bot) if y is not None else 1.0
        ep = honor = 0
        for v in res['victims'].get(bot.uid, ()):
            ship = v.k['gear']['ship']
            e, h = S.kill_reward(bot, v.uid, ship, now)
            ep, honor = ep + e, honor + h
            bot.ist('player')
            bot.ist('player_points', TB.ship_rank_points(ship))
        pct = min(d['bonus_max_percent'], d['bonus_percent_per_kill'] * kills) if won else 0
        ep, honor = ep * (1 + pct / 100.0), honor * (1 + pct / 100.0)
        if ep or honor:
            bot.reward(None, speed, ep=ep, honor=honor)
    mates = [b.name for b in L['teams'].get(bot.company, ()) if b is not bot]
    bot.event(PVP[mode]['done'], now, kills=kills, deaths=deaths, won=won, mode=mode, mates=','.join(mates[:8]))


def strife_milestones(bot, now):
    """Galactic Strife: the reputation milestones the bot reached for the first time pay their items, as a player's do
    (galactic_strife.GalacticStrife.update_msgs: state 'paid', milestones()). -> milestones paid."""
    import galactic_strife as GS
    if not GS.active(now):
        return 0
    from . import society as TB
    p = TB.profile(bot)
    st = GS.state(p, now)
    n = 0
    for m, items in GS.milestones(int(st['rep'])):
        if st['paid'] < m <= st['rep']:
            st['paid'] = m
            p.dirty = True
            grant_list(bot, items, bot.r)
            n += 1
    return n


def pvp_rows(mode, band_map, now):
    """The bots' own matches of a band for the player's lobby: {match id: {state 0 waiting / 1 running, queue {company: n}, size {company: n},
    points {company: points so far} (TDM), tickets {company: left} (SC), start, end}}."""
    out = {}
    for mid in _mids(mode):
        L = LOBBY.get((mode, band_map, mid))
        if L is None:
            continue
        if L['state'] == 'wait':
            out[mid] = dict(state=0, queue={c: len(v) for c, v in L['teams'].items()})
            continue
        f = max(0.0, min(1.0, (now - L['start']) / max(1.0, L['end'] - L['start'])))
        r = L['res']
        row = dict(state=1, size=dict(L['size']), start=L['start'], end=L['end'])
        if mode == 'tdm':
            row['points'] = {c: int(r['score'][c] * f) for c in r['score']}
        else:
            row['tickets'] = {c: int(PVP['sc']['d']['tickets'] - (PVP['sc']['d']['tickets'] - r['score'][c]) * f) for c in r['score']}
        out[mid] = row
    return out


def pvp_take(mode, band_map, mid):
    """The player joins this match: the bots waiting in its queue go to the player's queue instead -> {company: [bot]} (they leave the
    bots' own queue; the mode drafts them)."""
    L = LOBBY.get((mode, band_map, mid))
    if L is None or L['state'] != 'wait':
        return {}
    LOBBY.pop((mode, band_map, mid), None)
    for v in L['teams'].values():
        for b in v:
            b.plan['finished'] = True
    return {c: list(v) for c, v in L['teams'].items()}


def _infer(ctx):
    """Who won a drafted match, from the last look at its state (pvp_match.concrete) when the release event does not say: TDM the higher
    score (a draw loses), SC still in with every other company out of tickets; None if unknown."""
    if not ctx:
        return None
    own = ctx['company']
    if ctx.get('score'):
        top = max(v for c, v in ctx['score'].items() if c != own) if len(ctx['score']) > 1 else 0
        return ctx['score'].get(own, 0) > top
    t = ctx.get('tickets')
    if t:
        out = {c for c, v in t.items() if v <= 0} | set(ctx.get('out') or ())
        if own in out:
            return False
        return all(c in out for c in t if c != own) or None
    return None


def after_match(bot, now):
    """The match results the bot has not taken in yet (a drafted match's release event, its own match's end): history (k['matches'], the
    last 20), statistics, mood (a win lifts, a loss and many deaths annoy), and the teammates (and the player, if on its side) a bit closer."""
    ctx = None
    for o in bot.events:
        mode = MATCH_DONE.get(o.get('type'))
        if mode is None or o.get('seen'):
            continue
        o['seen'] = True
        if ctx is None:
            ctx = bot.__dict__.pop('_match_ctx', None) or {}
        won = o.get('won')
        if won is None and mode != 'ctb':
            won = _infer(ctx)
            if won is not None:
                o['won'] = won
        kills, deaths = int(o.get('kills') or 0), int(o.get('deaths') or 0)
        hist = bot.k.setdefault('matches', [])
        hist.append(dict(t=round(o.get('t', now)), mode=mode, won=won, k=kills, d=deaths, drafted=bool(ctx.get('drafted'))))
        del hist[:-20]
        bot.ist('matches')
        if won:
            bot.ist('matches_won')
            bot.mood.it(morale=0.1, confidence=0.06, anger=-0.1)
        elif won is False:
            bot.mood.it(morale=-0.06, confidence=-0.04, anger=0.04 * min(3, deaths))
        if kills > deaths:
            bot.mood.it(confidence=0.03)
        mates = [x for x in str(o.get('mates') or '').split(',') if x] or ctx.get('mates') or []
        for name in mates[:8]:
            bot.memory.event(name, 'hunted_together', now)
        if ctx.get('player') and ctx.get('player_company') == bot.company:
            bot.memory.event(ctx['player'], 'hunted_together', now)
