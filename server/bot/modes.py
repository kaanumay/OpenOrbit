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
import json, os, random, time

from . import catalog as K

D = lambda f: json.load(open(os.path.join(K.HERE, 'data', f), encoding='utf8'))
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
    return t.get('hp', 0), t.get('kalkan', 0), t.get('damage', 0), t.get('reward') or {}


def wave(groups, health=1.0, damage=1.0, table=None):
    """[[[type, count], ...], ...] (groups) -> (HP+shield, damage taken per second, kill rewards)."""
    ehp = dps = 0.0
    reward = {}
    for group in groups:
        for x in group:
            tip, n = x[0], x[1]                          # [type, count] or [type, count, is it a boss]
            v = (table or {}).get(tip)
            v = (v.get('hp', 0), v.get('kalkan', 0), v.get('damage', 0), v.get('reward') or {}) if v else kind_value(tip)
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
        self.hp = min(int(g.get('can', 1)), 50)
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
        if k.get('company') and k['company'] != bot.firma:
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
            grant_list(bot, [[self.T['kp'], milestone], [self.T['xy'], milestone * 10 * d]], rng)


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

    def finish(self, bot, reached, total, duration, rng):
        row = next((r for r in self.A['reward'] if r['en_az'] <= reached <= r['max_count']), None)
        if row:
            grant_list(bot, [['resource_collectable_astralite', row.get('astralite', 0)],
                            ['resource_collectable_salvage-core', row.get('salvage', 0)],
                            ['resource_booty-key-astral', row.get('anahtar', 0)]], rng)


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

    def finish(self, bot, reached, total, duration, rng):
        row = next((r for r in self.E['death_reward'] if r['en_az'] <= reached <= r['max_count']), self.E['death_reward'][-1]
                   if reached > self.E['death_reward'][-1]['max_count'] else None)
        if row:
            grant_list(bot, [['resource_collectable_blacklight-shard', row.get('part', 0)]], rng)


class Echoes(Mod):
    uid, name = 'echoes', 'Deep Space Echoes'
    E = PVE['echoes']
    game_map = E['maps'][0]
    level = E['level_requirement']
    time_limit = E['sure_sn']

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
    time_limit = M['sure_sn']
    level = 10

    def is_open(self, now):
        return _tech().is_active(self.M['event'], now) and time.localtime(now).tm_hour in self.M['hours']

    def can_enter(self, bot, now):
        return bot.level >= self.level and state(bot, self.uid).get('hour') != time.strftime('%Y-%m-%d %H')

    def cost(self, bot):
        return _spend_or_take(bot, self.M['anahtar'], self.M.get('key_uridium'))

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.M['anahtar'], self.M.get('key_uridium'))

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
        return [(((f['hp'] + f['kalkan']) * pay), 0.0, {})]

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
        return [((p['hp'] + p['kalkan']) * 0.03, p['damage'] * 0.6 * K.COMBAT['npc_hit_chance'] / K.NPC_INTERVAL, {})]

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
        key = sum((u.get('anahtar') or 0) * u.get('count', 5) * 0.3 for u in aliens if isinstance(u.get('anahtar'), (int, float)))
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
    st.update(type=k, end_time=now + t['sure_sn'])


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
