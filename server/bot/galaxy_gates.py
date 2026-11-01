"""Galaxy Gates: the generator (energy, spin, part, multiplier) and the gate run (the player's rules and tables: galaxy_gates.py,
data/gates.json).

  energy    comes from bonus boxes and rewards (resource_extra-energy); otherwise 100 U per spin (quester and rich bots)
  spin      the probabilities are the game's: ammo 67, Xenomit 12, voucher 3, part 13, Nano Hull 4, daily disc 1; the part of Alpha/Beta/Gamma
            goes to one of the three; a duplicate part raises the multiplier (up to 5), with the game's "duplicate to the missing one" share
  run       when a gate is built the bot (if strong enough) moves to the gate map (leaves your map); time and success come from the
            waves' aliens: total HP / the bot's damage, damage taken / the bot's HP x number of lives. On success the gate's reward and its
            aliens' kill rewards; on failure the gate (with its parts) is lost. The Kronos part comes from the other gates.
State bot.k['kapi'] = {'parca': {gate: count}, 'kurulu': [gate ...], 'carpan': n, 'kronos': count}.
"""
import json, math, os, random

from . import catalog as K

D = json.load(open(os.path.join(K.HERE, 'data', 'gates.json'), encoding='utf8'))
KAPI = D['gates']
ABG = ('alpha', 'beta', 'gamma')
ORDER = ('alpha', 'beta', 'gamma', 'lambda', 'hades', 'delta', 'epsilon', 'kappa', 'zeta', 'streuner')
ENERGY = 'resource_extra-energy'
PROBABILITY = {c: w for c, w in D['probability']}            # 1 ammo, 2 resource, 3 voucher, 4 part, 5 special, 6 log
_difficulty = {}


def state(bot):
    return bot.k.setdefault('gate', {'part': {}, 'built': [], 'multiplier': 0, 'kronos': 0})


def stock(bot):
    from . import weapons as WP
    return WP.stock(bot)


def difficulty(gate):
    """The gate's waves -> ([(wave's total HP+shield, damage per second of those hitting at the same time)], kill rewards)."""
    if gate in _difficulty:
        return _difficulty[gate]
    import ast
    waves = KAPI[gate].get('waves') or []
    if isinstance(waves, str):
        waves = ast.literal_eval(waves)
    out, reward = [], {}
    for d in waves:
        ehp = dps = 0.0
        for u in d.get('alien_spawns', []):
            n = u.get('count', 1)
            ehp += n * (u.get('hp', 0) + u.get('shield', 0))
            dps += min(n, 2) * u.get('damage', 0) * K.COMBAT['npc_hit_chance'] * 0.6 / K.NPC_INTERVAL  # the player pulls them one by one, escapes out of range
            for k, v in (u.get('reward') or {}).items():
                reward[k] = reward.get(k, 0) + v * n
        out.append((ehp, dps))
    _difficulty[gate] = (out, reward)
    return _difficulty[gate]


def estimate(bot, gate):
    """Run estimate -> (time s, expected number of deaths). In a gate players use their best ammo (the strongest in stock x2-x4);
    between waves the shield refills and the ship is repaired."""
    from . import weapons as WP
    waves, _ = difficulty(gate)
    d = bot.value()
    s = WP.stock(bot)
    multiplier = max([WP.multiplier(c) for c in ('ammunition_laser_ucb-100', WP.MCB50, WP.MCB25, WP.LCB) if s.get(c, 0) > 1000] or [1])
    dps = max(1.0, d['dps'] * multiplier * 1.15)                 # rockets
    duration = death = 0.0
    for ehp, incoming_dps in waves:
        t = ehp / dps
        duration += t
        death += t * incoming_dps / max(1.0, d['ehp'] * 3)
    return duration, death


# ------------------------------------------------------------------------------------------------------------ generator
def draw(bot, gate, n):
    """n spins (energy first, then 100 U) -> the number done."""
    st = state(bot)
    s = stock(bot)
    crafted = 0
    for _ in range(n):
        if s.get(ENERGY, 0) > 0:
            s[ENERGY] -= 1
        elif not bot.pay('U', D['energy_price'] * bot.game_settings.multiplier('shop_price')):
            break
        crafted += 1
        _draw(bot, st, gate)
        if gate in st['built'] or (gate in ABG and all(k in st['built'] for k in ABG)):
            break
    if s.get(ENERGY) == 0:
        s.pop(ENERGY, None)
    if crafted:
        bot.ist('gate_draw', crafted)
    return crafted


def _draw(bot, st, gate):
    from . import weapons as WP
    r = bot.r
    cat = r.choices(list(PROBABILITY), weights=list(PROBABILITY.values()))[0]
    if cat == 4:
        k = r.choice([x for x in ABG if x not in st['built']] or [gate]) if gate in ABG else gate
        total = KAPI[k]['part']
        var = st['part'].get(k, 0)
        missing = (total - var) / total
        new_ = r.random() < missing + (1 - missing) * 0.5 or st['multiplier'] >= D['max_multiplier']
        if new_:
            earn = 1 + (st['multiplier'] if st['multiplier'] >= D['max_multiplier'] else 0)
            st['multiplier'] = 0 if earn > 1 else st['multiplier']
            st['part'][k] = min(total, var + earn)
            if st['part'][k] >= total and k not in st['built']:
                st['built'].append(k)
                bot.event('gate_set_up', gate=KAPI[k]['name'])
        else:
            st['multiplier'] = min(D['max_multiplier'], st['multiplier'] + 1)
        return
    if cat == 1:
        loot, _, count = r.choice(D['ammunition'])
        WP.add(bot, loot, count)
    elif cat == 2:
        bot.k.setdefault('cargo', {})
        bot.k['cargo']['3'] = bot.k['cargo'].get('3', 0) + r.randint(*D['xenomit'])
    elif cat == 3:
        stock(bot)['resource_jumpvoucher'] = stock(bot).get('resource_jumpvoucher', 0) + 1
    elif cat == 6:
        stock(bot)['resource_logfile'] = stock(bot).get('resource_logfile', 0) + 1


def target_gate(bot):
    """The gate to collect parts for: not built and the first gate the bot can probably pass (players' order: ABG, then the others)."""
    st = state(bot)
    for k in ORDER:
        if k in st['built'] or KAPI[k].get('not_producible'):
            continue
        duration, death = estimate(bot, k)
        if death < KAPI[k]['hp'] * 1.5:
            return k
    return None


def generator(bot):
    """At decision time: spins if it has energy; a quester and a rich bot also with uridium (permission 'kapi', from level 10)."""
    if not bot.permission.get('gate', True) or bot.level < 10:
        return 0
    k = target_gate(bot)
    if not k:
        return 0
    n = stock(bot).get(ENERGY, 0)
    t = bot.o('frugality')
    if bot.o('ambition') + bot.o('rivalry') > 1.1 and bot.k['uridium'] > D['energy_price'] * 300 * (1 + 2 * t):
        n += int(bot.k['uridium'] * 0.15 // D['energy_price'])
    return draw(bot, k, min(n, 200)) if n else 0


# ------------------------------------------------------------------------------------------------------------ run
def run_result(bot, gate, rng=random):
    """Result of the run -> (did it succeed, time s)."""
    duration, death = estimate(bot, gate)
    death = rng.gauss(death, 0.3 * death + 0.2)
    return death < KAPI[gate]['hp'], duration * rng.uniform(1.1, 1.6) + 120


def grant_reward(bot, gate, speed=1.0):
    """The gate's completion reward and its aliens' kill rewards; the Kronos part."""
    from . import weapons as WP
    o = KAPI[gate].get('reward') or {}
    if isinstance(o, str):
        import ast
        o = ast.literal_eval(o)
    _, aliens = difficulty(gate)
    bot.reward('quest', speed, ep=o.get('ep', 0) + aliens.get('ep', 0), honor=o.get('honor', 0) + aliens.get('honor', 0),
             uridium=o.get('uridium', 0) + aliens.get('uridium', 0), credits=aliens.get('credits', 0))
    for loot, n in (o.get('ammunition') or {}).items():
        WP.add(bot, loot, n)
    if o.get('xenomit'):
        bot.k.setdefault('cargo', {})
        bot.k['cargo']['3'] = bot.k['cargo'].get('3', 0) + o['xenomit']
    s = stock(bot)
    for loot, n in (('resource_logfile', o.get('log_disk', 0)), ('resource_jumpvoucher', o.get('voucher', 0)),
                    ('resource_booty-key', (o.get('booty') or {}).get('green_key', 0))):
        if n:
            s[loot] = s.get(loot, 0) + n
    st = state(bot)
    if gate != 'kronos':
        st['kronos'] = min(KAPI['kronos']['part'], st['kronos'] + 1)
        if st['kronos'] >= KAPI['kronos']['part'] and 'kronos' not in st['built']:
            st['built'].append('kronos')
    if gate not in st.setdefault('done', []):
        st['done'].append(gate)                      # gate ring (appearance.rings)
    bot.ist('gate_done')
    bot.event('gate_done', gate=KAPI[gate]['name'])


def record_duration(save, key, sec):
    """The gate's completion time (statistics; player request 2026-10-30) -> save['gate_times'][key] {best, last, number} (s)."""
    d = save.setdefault('gate_times', {}).setdefault(key, {'best': 0, 'last': 0, 'number': 0})
    sec = int(max(1, sec))
    d.update(last=sec, number=d['number'] + 1, best=min(d['best'], sec) if d['best'] else sec)
    return d


def can_run(bot):
    """A built and passable gate or None."""
    st = state(bot)
    for k in st['built']:
        if estimate(bot, k)[1] < KAPI[k]['hp']:
            return k
    return None
