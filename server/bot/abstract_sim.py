"""Abstract simulation: the journey, grinding, death and bot-vs-bot encounters of bots that are not on the player's map (statistical).

The results are drawn with noise from catalog.evaluate_map's expected values: two bots of equal power make close
but not identical progress in the same time (luck, attention, "played well that day"). A bot's daily efficiency also varies with its personality: a patient bot
grinds steadily, an impatient one unevenly.
"""
import math, time

import map_links as H
from . import catalog as K
from . import personality as PS

BONUS_URIDIUM_PER_HOUR = 220          # uridium per hour from bonus boxes (grows per level; ~200 on 1-x, more boxes higher up)
BOX_URIDIUM = 170 / 19.0                 # average uridium of a bonus box (world.CFG['bonus_kutu']: 19 equally likely contents)
DEATH_WAIT = (25, 70)       # from death until respawn (death screen, repair choice, return to base)


def go(bot, target, y=None, now=None):
    """Builds the portal route -> is there a route. On the route one map is crossed per ATLAMA_SN (depending on speed)."""
    now = now or (y.now if y is not None else time.time())
    target = int(target)
    if target == bot.game_map:
        bot.en_route = None
        return True
    route = K.route(bot.game_map, target, bot.company, bot.level)
    if not route:
        bot.en_route = None
        return False
    if len(route) > 3 and bot.body is None:              # jump CPU: a long route to base in a single jump (in the concrete simulation ship.portala)
        from . import extras as EX
        cpu = EX.jump(bot, target)
        if cpu and EX.use(bot, cpu):
            jump_to(bot, target, y)
            bot.en_route = None
            bot.ist('jump_cpu')
            return True
    bot.en_route = route[1:]
    bot.en_route_time = now + jump_duration(bot)
    return True


def jump_duration(bot):
    return K.JUMP_SEC * bot.r.uniform(0.7, 1.3) * 320.0 / max(200, bot.value()['speed'])


def journey(bot, y, now=None):
    """If en route and it is time for the next jump, jumps -> is it still en route."""
    if not bot.en_route:
        return False
    now = now or (y.now if y is not None else time.time())
    if bot.body is not None:            # concrete: the ship flies to the portal, govde makes the jump
        return True
    if now >= bot.en_route_time:
        jump_to(bot, bot.en_route.pop(0), y)
        bot.en_route_time = now + jump_duration(bot)
    return bool(bot.en_route)


def jump_to(bot, target, y):
    old = bot.k['map']
    bot.k['map'] = int(target)
    bot.k['x'] = bot.k['y'] = 0
    seen = bot.k.setdefault('seen', [])
    if int(target) not in seen:
        seen.append(int(target))
    if y is not None:
        y.map_changed(bot, old)


def _collect_boxes(bot, dt, speed):
    """Has no ammo: cannot grind, collects bonus boxes like a player (ammo and credits come from the box; a bot that ran out of money recovers this way)."""
    from . import weapons as WP
    k = dt / 3600.0 * speed * 0.5 * (1 - 0.35 * bot.mood['fatigue'])
    box = BONUS_URIDIUM_PER_HOUR * (1 + bot.level / 6.0) * k * x1_cut(bot)
    bot.reward('box', uridium=box)
    WP.box_ammo(bot, box / BOX_URIDIUM)


def farm(bot, dt, y, target_kind=None):
    """Alien grinding for dt seconds: gain, quest progress, cargo, ammo consumption, death. hedef_tip: the alien the quest wants (chases only
    that: slower). Ammo and rockets from stock (weapons.py): x2/x3 against a tough alien, and the rocket's damage too if there is one; when the ammo runs out
    it grinds that much less."""
    from . import weapons as WP
    speed = y.speed(bot) if y is not None else 1.0
    d = bot.value()
    courage = max(0.0, min(1.0, 0.3 + 0.6 * bot.o('risk') + 0.2 * bot.mood['confidence'] - 0.3))
    r = K.evaluate_map(bot.game_map, d['dps'], d['ehp'], courage)
    if not r['targets']:
        if not WP.pick_laser(bot) and not WP.pick_rocket(bot):
            _collect_boxes(bot, dt, speed)        # also on a map with no alien suited to its power (otherwise an ammo-less bot never recovered there)
        return
    nv = K.npc_value(target_kind) if target_kind else None
    ehp_avg = nv['ehp'] if nv else sum(K.npc_value(t)['ehp'] * v for t, v in r['kills'].items()) / max(1e-9, sum(r['kills'].values()))
    lasers, rocket, dps, laser_dps = WP.grind_plan(bot, ehp_avg)
    if not lasers and not rocket:
        _collect_boxes(bot, dt, speed)
        return
    from . import lab as LB
    ehp = d['ehp'] * (1 + 0.5 * LB.bonus(bot, LB.SHIELD))      # shield charge (the shield's share ~half)
    if abs(dps - d['dps']) > 1e-6 or ehp != d['ehp']:
        r = K.evaluate_map(bot.game_map, dps, ehp, courage)
        if not r['targets']:
            return
    # efficiency: noisy (an impatient bot is uneven), low when tired
    efficiency = max(0.2, bot.r.gauss(PS.ACTIVITY[bot.archetype][1], 0.12 + 0.2 * (1 - bot.o('patience')))) * (1 - 0.35 * bot.mood['fatigue'])
    from . import extras as EX
    efficiency *= 1 + 0.04 * EX.repair_level(bot)          # repair robot: less time to recover
    from . import playstyle as PL
    efficiency *= PL.combat_efficiency(bot)                  # skill (combat, focus), the day's form, habits
    k = dt / 3600.0 * speed * efficiency
    kills = r['kills']
    if target_kind and target_kind in kills:
        kills = {target_kind: kills[target_kind] * 1.6}      # chases only what it wants: more of that type
        ratio = sum(kills.values()) / max(1e-9, sum(r['kills'].values()))
        k_reward = k * min(1.0, ratio)
    else:
        k_reward = k
    # ammo and rockets: as many as the HP to be killed (a player spends as much ammo as the laser count per shot)
    afforded = WP.consume(bot, sum(K.npc_value(t)['ehp'] * v * k for t, v in kills.items()), lasers, rocket, dps, laser_dps)
    from . import lab as LB
    LB.spend(bot, LB.SHIELD, dt)                         # shield charge per minute
    k, k_reward = k * afforded, k_reward * afforded
    lv = bot.level
    x1 = x1_cut(bot)
    bot.reward('npc', ep=r['ep_per_hour'] * k_reward * x1, credits=r['credits_per_hour'] * k_reward * x1, uridium=r['uridium_per_hour'] * k_reward * x1,
             honor=r['honor_per_hour'] * k_reward)
    box = BONUS_URIDIUM_PER_HOUR * (1 + lv / 6.0) * k * x1 * PL.box_factor(bot) / max(0.3, PL.combat_efficiency(bot))
    bot.reward('box', uridium=box)
    WP.box_ammo(bot, box / BOX_URIDIUM)                # the ammo and credits of the bonus boxes
    total = 0
    for tip, hour in kills.items():
        n = _poisson(bot.r, hour * k)
        if n:
            total += n
            from . import society as TB
            bot.ist('npc_points', TB.npc_rank_points(tip) * n)
            from . import loot as LT
            LT.extra_loot(bot, tip, n)                   # Scrapium, Mucosum, the daily file ...
            if bot.permission.get('cargo', True):             # cargo boxes: a patient player collects all, an impatient one leaves most
                take = (0.55 + 0.4 * bot.o('patience')) * bot.game_settings.multiplier('collecting', 'cargo') * (1 + LT.booster_share(bot, 'COLLECT_RESOURCES')) \
                    * PL.cargo_care(bot)                 # many pilots leave most ore boxes, an ore trader takes them all (playstyle.py)
                bot.add_cargo({t: int(v * n * take) for t, v in K.npc_cargo(tip, bot.level, bot.game_map).items()})
            if y is not None:
                y.npc_killed(bot, tip, n)
    if total:
        bot.ist('npc', total)
        bot.mood.it(morale=0.002 * total)
    from . import loot as LT, events as IX
    LT.abstract(bot, dt, y)                                 # the map's keyed boxes
    IX.abstract(bot, dt, y, dps)                            # event aliens, their drops and boxes
    if bot.r.random() < r['deaths_per_hour'] * dt / 3600.0 * (0.6 + 0.8 * (1 - bot.o('patience')) * 0.5) * PL.death_factor(bot):
        death(bot, y, reason='npc', now=y.now if y is not None else None)


def x1_cut(bot):
    """At high level in their own X-1 the reward shrinks (npc.json x1_odul; world.World.grant_loot)."""
    if H.map_class(bot.game_map) != 'X-1' or H.company(bot.game_map) != bot.company:
        return 1.0
    return next((k for l, k in reversed(K.COMBAT['x1_reward']) if bot.level >= l), 1.0)


def pick_repair(bot, y, killer=None):
    """As a player would choose on the death screen: 'station' (free, returns to base), 'portal' (500 U, at the nearest portal
    of the same map) or 'in_place' (1,000 U, 10% of HP and 10 s of protection). The expensive ones only if uridium is plentiful: in_place with impatience and
    vengefulness, portal with distance from home and generosity. The uridium paid is deducted."""
    m = bot.game_map
    if m not in K.MAPS or y is not None and y.mode == 'simple':
        return 'station'
    route = K.route(m, K.ev(bot.company), bot.company, bot.level)
    far = len(route) - 1 if route else 0
    if far < 1:
        return 'station'                           # already at home: a station repair is both free and close
    C, k, frugality = K.ITEMS['death_screen'], bot.game_settings.multiplier('repair_cost'), bot.o('frugality')
    for kind, price, urge in (('in_place', C['in_place_uridium'] * k,
                               0.12 * (1 - bot.o('patience')) + (0.3 * bot.mood['anger'] if killer else 0.0)),
                              ('portal', C['portal_uridium'] * k, 0.1 * far * (1.2 - frugality))):
        from . import playstyle as PL
        if bot.k['uridium'] >= price * (3 + 5 * frugality) and bot.r.random() < urge * PL.repair_urge(bot):     # pays if it is a small share of the savings
            bot.earn(uridium=-int(round(price)))
            return kind
    return 'station'


def death(bot, y, reason='npc', killer=None, now=None):
    """The bot died: mood, statistics, repair choice as on the player's death screen (tamir_sec). Repair at the station: after a while
    at the company's base (X-1 or X-8 depending on level) around the station; portal and in_place repair: on the same map, in a short
    time. Cargo stays (a player does not lose cargo on death either)."""
    now = now or (y.now if y is not None else time.time())
    bot.ist('death')
    bot.mood.it(anger=0.35 if killer else 0.15, morale=-0.15, confidence=-0.12)
    if killer:
        bot.memory.event(killer, 'killed_me', now)
    repair = pick_repair(bot, y, killer)
    bot.event('death', now, reason=reason, killer=killer, map=H.name(bot.game_map), repair=repair)
    bot.en_route = None
    bot.__dict__.pop('carry', None)                 # the next ship is repaired (ship.resume)
    bot.dead_until = now + bot.r.uniform(*DEATH_WAIT)
    if y is not None and y.mode == 'simple':
        y.bot_died(bot, killer)
        bot.next_decision = bot.dead_until
        return                                      # simple mode: respawns on the same map
    if repair != 'station':
        bot.dead_until = now + bot.r.uniform(5, 15)    # chose immediately on the death screen
        x, yy = bot.k.get('x') or 0, bot.k.get('y') or 0
        if repair == 'portal':
            g = min(H.gates(bot.game_map, bot.company) or [{'x': x, 'y': yy}], key=lambda g: math.hypot(g['x'] - x, g['y'] - yy))
            bot.k['x'], bot.k['y'] = int(g['x'] + bot.r.uniform(-150, 150)), int(g['y'] + bot.r.uniform(-150, 150))
        else:
            bot.in_place_repair = True                  # the body spawns with 10% HP and 10 s of protection (ship.tick)
        if y is not None:
            y.bot_died(bot, killer)
        bot.next_decision = bot.dead_until
        return
    bot.k['x'] = bot.k['y'] = None                    # to base: spawns around the station, not at the place of death
    ev = H.x8_home(bot.company, bot.level, bot.game_map) if bot.level >= 12 else None
    target = int(ev) if ev else K.ev(bot.company)
    if y is not None:
        y.bot_died(bot, killer)
    if target != bot.game_map:
        jump_to(bot, target, y)
    bot.next_decision = bot.dead_until


def _poisson(r, lam):
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(r.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= r.random()
        if p <= L:
            return k
        k += 1


# ------------------------------------------------------------------------------------------------------------ bot-bot PvP
def encounter(a, b, y, now=None):
    """Two enemy bots met on the same map (manager.pvp_tick chooses): the attacker attacks, the other fights or flees; the result depends
    on the power ratio, luck and personality. -> ('kazandi', winner, loser) | ('kacti', fleeing, chasing) | None"""
    now = now or time.time()
    from . import extras as EX
    from . import technology as TECH
    from . import playstyle as PL
    ga = max(0.5, a.value()['power']) * EX.pvp_factor(a) * TECH.pvp_factor(a) * PL.pvp_factor(a)      # + PvP skill (aim, movement)
    gb = max(0.5, b.value()['power']) * EX.pvp_factor(b) * TECH.pvp_factor(b) * PL.pvp_factor(b)
    ratio = gb / ga                                 # >1: b is stronger
    if ratio < 0.6 and b.r.random() < 1 - b.o('risk') and EX.cloak(b):          # stealth CPU: slips away unseen
        b.ist('hidden')
        return ('fled', b, a)
    from . import weapons as WP
    mine_choice = WP.pick_mine(b)                      # the fleeing one drops a mine behind: the chaser slows down
    # does b flee: if cautious and weak
    flee = ratio < 0.8 and b.r.random() < (1 - b.o('risk')) * (1 - ratio) + 0.2 * (1 - b.o('aggression'))
    if flee and b.r.random() < 0.4 + 0.3 * PL.skill(b, 'survival') + 0.25 * (b.value()['speed'] > a.value()['speed']) + 0.15 * bool(mine_choice and WP.spend(b, mine_choice, 1)):
        b.memory.event(a.name, 'insult', now, multiplier=0.5)
        b.mood.it(anger=0.1, confidence=-0.05)
        return ('fled', b, a)
    pa = ga ** 1.5 / (ga ** 1.5 + gb ** 1.5)       # the stronger one's advantage is not linear
    pa = 0.08 + 0.84 * pa                          # a surprise is always possible
    winner, loser = (a, b) if a.r.random() < pa else (b, a)
    pvp_reward(winner, loser, y, now)
    death(loser, y, reason='player', killer=winner.name, now=now)
    return ('won', winner, loser)


def pvp_reward(winner, loser, y, now):
    """Honor and EP of a kill (items.json player_kill: honor 100 x, EP 1,000 x the victim's ship score; roughly with level)."""
    kill_rewards = K.ITEMS['player_kill']
    multiplier = max(1, loser.level // 2)
    speed = y.speed(winner) if y is not None else 1.0
    winner.reward(None, speed, ep=kill_rewards['ep_points'] * multiplier, honor=kill_rewards['honor_points'] * multiplier)
    winner.ist('player')
    from . import society as TB
    winner.ist('player_points', TB.ship_rank_points(loser.k['gear']['ship']))
    winner.mood.it(morale=0.1, confidence=0.08, anger=-0.2)
    winner.memory.event(loser.name, 'i_killed', now)
    winner.event('i_killed', now, victim=loser.name)
